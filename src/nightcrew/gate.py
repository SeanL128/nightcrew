"""The gate (BP7 — the thesis, ADR-5/6/7).

Two halves, both hard blocks:

1. Deterministic — independently re-run ``test_cmd`` in the build worktree
   (never trust the builder) and block diffs that remove test functions or
   weaken assertions. Tamper parsing kept in lockstep with ``lite/gate.py``
   (same precedent as spec.py's shared thresholds).
2. Evidence judge — ``dispatch(judge_role, …)`` maps each acceptance
   criterion to concrete diff/test evidence. Judge model family must differ
   from the builder's (ADR-7): declared via a ``family`` key on the role's
   dispatch config, or inferred from model-name markers in it; unknown or
   equal families is a hard error.

Deterministic failures short-circuit the judge (no dispatch cost on an
already-blocked diff).
"""

import json
import re
import subprocess
from dataclasses import dataclass, field

from .config import Item, RepoSpec
from .dispatch import dispatch

# shared with lite/gate.py — keep in lockstep
TEST_FILE_RE = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.[^/.]*$)")
TEST_DEF_RE = re.compile(r"^\s*def (test_\w+)|^\s*(?:it|test|describe)\(")
ASSERT_RE = re.compile(r"^\s*(assert\b|self\.assert\w+|expect\()")

FAMILY_MARKERS = {
    "anthropic": ("claude", "anthropic"),
    "openai": ("codex", "gpt", "openai"),
    "google": ("gemini",),
}

DIFF_CAP = 200_000  # chars of diff sent to the judge
TEST_TAIL = 4_000  # chars of test output sent to the judge


class GateError(Exception):
    pass


@dataclass
class CriterionVerdict:
    criterion: str
    met: bool
    evidence: str = ""


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]
    verdicts: list[CriterionVerdict]
    judge_cost_usd: float | None = None
    judge_usage: dict = field(default_factory=dict)


def gate(worktree: str, item: Item, spec: RepoSpec, judge_role: str,
         builder_role: str, dispatch_config: dict) -> GateResult:
    _check_families(judge_role, builder_role, dispatch_config)
    diff = _git_diff(worktree)
    reasons = check_test_tampering(diff)
    test_output, test_reasons = run_tests(worktree, spec.test_cmd)
    reasons += test_reasons
    if reasons:
        return GateResult(False, reasons, [])
    return _judge(item, diff, test_output, judge_role, dispatch_config)


def _git_diff(worktree: str) -> str:
    r = subprocess.run(["git", "-C", worktree, "diff", "HEAD"],
                       capture_output=True, text=True)
    if r.returncode:
        raise GateError(f"git diff failed: {r.stderr.strip()}")
    return r.stdout


def run_tests(worktree: str, test_cmd: str) -> tuple[str, list[str]]:
    r = subprocess.run(test_cmd, shell=True, cwd=worktree,
                       capture_output=True, text=True)
    output = r.stdout + r.stderr
    return output, [] if r.returncode == 0 else [f"test_cmd exited {r.returncode}"]


def check_test_tampering(diff: str) -> list[str]:
    """Block diffs that remove test functions or reduce assertions in test files."""
    reasons = []
    current_file, in_test_file = None, False
    removed_defs, added_defs = set(), set()
    removed_asserts = added_asserts = 0

    def flush():
        nonlocal removed_asserts, added_asserts
        for name in removed_defs - added_defs:
            reasons.append(f"test function removed: {name} ({current_file})")
        if removed_asserts > added_asserts:
            reasons.append(
                f"assertions weakened in {current_file}: "
                f"-{removed_asserts}/+{added_asserts}"
            )
        removed_defs.clear(), added_defs.clear()
        removed_asserts = added_asserts = 0

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            if in_test_file:
                flush()
            current_file = line[6:]
            in_test_file = bool(TEST_FILE_RE.search(current_file))
        elif in_test_file and line.startswith("-") and not line.startswith("---"):
            body = line[1:]
            m = TEST_DEF_RE.match(body)
            if m and m.group(1):
                removed_defs.add(m.group(1))
            if ASSERT_RE.match(body):
                removed_asserts += 1
        elif in_test_file and line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            m = TEST_DEF_RE.match(body)
            if m and m.group(1):
                added_defs.add(m.group(1))
            if ASSERT_RE.match(body):
                added_asserts += 1
    if in_test_file:
        flush()
    return reasons


def _role_family(rc: dict) -> str | None:
    explicit = rc.get("family")
    if explicit:
        return str(explicit).lower()
    blob = json.dumps(rc).lower()
    for family, markers in FAMILY_MARKERS.items():
        if any(marker in blob for marker in markers):
            return family
    return None


def _check_families(judge_role: str, builder_role: str, dispatch_config: dict) -> None:
    roles = dispatch_config.get("roles") or {}
    families = {}
    for role in (judge_role, builder_role):
        if role not in roles:
            raise GateError(f"no dispatch config for role {role!r}")
        families[role] = _role_family(roles[role])
        if families[role] is None:
            raise GateError(
                f"cannot determine model family for role {role!r}; "
                "set an explicit 'family' key on its dispatch config (ADR-7)"
            )
    if families[judge_role] == families[builder_role]:
        raise GateError(
            f"judge family must differ from builder family (ADR-7): "
            f"both are {families[judge_role]!r}"
        )


def _judge(item: Item, diff: str, test_output: str, judge_role: str,
           dispatch_config: dict) -> GateResult:
    criteria = item.acceptance_criteria
    numbered = "\n".join(f"{n}. {c}" for n, c in enumerate(criteria, 1))
    goal = (
        "You are Nightcrew's verification judge. For EACH numbered acceptance "
        "criterion below, decide whether the diff satisfies it, citing concrete "
        "evidence (a file/hunk from the diff, or a line of test output). "
        "If evidence is missing or ambiguous, the criterion is NOT met.\n"
        'Respond with ONLY this JSON, no prose: {"verdicts": [{"criterion": 1, '
        '"met": true, "evidence": "..."}, ...]} — one entry per criterion.\n\n'
        f"Item [{item.id}]: {item.description}\n\n"
        f"Acceptance criteria:\n{numbered}\n\n"
        f"Diff:\n{diff[:DIFF_CAP]}\n\n"
        f"Test output (tail):\n{test_output[-TEST_TAIL:]}"
    )
    brief = {
        "goal": goal,
        "files": [],
        "constraints": "Respond with only the JSON object. Do not modify any files.",
        "acceptance": "Exactly one verdict per numbered criterion, each with evidence.",
    }
    result = dispatch(judge_role, brief, dispatch_config)
    raw = _extract_json(result.text)
    if raw is None:
        return GateResult(False, ["judge output unparseable"], [],
                          result.cost_usd, result.usage)
    by_index = {v.get("criterion"): v for v in raw.get("verdicts") or []
                if isinstance(v, dict)}
    reasons, verdicts = [], []
    for n, criterion in enumerate(criteria, 1):
        v = by_index.get(n)
        if v is None:
            verdicts.append(CriterionVerdict(criterion, False))
            reasons.append(f"criterion {n} unaddressed by judge: {criterion}")
            continue
        met = bool(v.get("met"))
        evidence = str(v.get("evidence") or "")
        verdicts.append(CriterionVerdict(criterion, met, evidence))
        if not met:
            reasons.append(f"criterion {n} not met: {criterion}"
                           + (f" — {evidence}" if evidence else ""))
    return GateResult(not reasons, reasons, verdicts, result.cost_usd, result.usage)


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
