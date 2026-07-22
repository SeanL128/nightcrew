"""PR + review record (BP8, ADR-17/18).

The PR body is the gate's verdict: per-criterion criterion → evidence table
plus total run cost. PRs are opened, NEVER merged (trust ratchet is Phase 2).
The review record is the generic ADR-17 contract; the default sink is the
build log (``BuildLog.record_review``), anything else is caller wiring.
"""

import subprocess
import tempfile
import uuid
from pathlib import Path

from .config import Item
from .gate import GateResult


class PRError(Exception):
    pass


def pr_body(item: Item, gate: GateResult, total_cost_usd: float | None) -> str:
    rows = "\n".join(
        f"| {_cell(v.criterion)} | {'✅' if v.met else '❌'} | {_cell(v.evidence)} |"
        for v in gate.verdicts
    )
    cost = f"${total_cost_usd:.2f}" if total_cost_usd is not None else "n/a (unmetered)"
    return (
        f"## Nightcrew verification gate: {'PASS' if gate.passed else 'BLOCKED'}\n\n"
        f"**[{item.id}]** {item.description}\n\n"
        "| Criterion | Verdict | Evidence |\n|---|---|---|\n"
        f"{rows}\n\n"
        f"**Total run cost:** {cost}\n\n"
        "_Opened by Nightcrew. Verified by the gate. Never auto-merged._"
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def open_pr(worktree: str, branch: str, item: Item, gate: GateResult,
            total_cost_usd: float | None, gh_argv: list[str] = ("gh",)) -> str:
    """Commit staged changes, push the branch, open the PR. Returns the URL."""
    if not gate.passed:
        raise PRError(f"gate did not pass for {item.id}; no PR ships unverified")
    _git(worktree, "commit", "-m", f"nightcrew: {item.id} — {item.description}")
    # Force: picker guarantees no OPEN PR on this branch, so any remote
    # nightcrew/<item> ref is a stale leftover from a closed PR — ours to overwrite.
    _git(worktree, "push", "-u", "--force", "origin", branch)
    body = pr_body(item, gate, total_cost_usd)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     prefix="nightcrew-pr-") as f:
        f.write(body)
        body_path = f.name
    try:
        r = subprocess.run(
            [*gh_argv, "pr", "create", "--head", branch,
             "--title", f"[nightcrew] {item.id}: {item.description}",
             "--body-file", body_path],
            capture_output=True, text=True, cwd=worktree,
        )
    finally:
        Path(body_path).unlink()
    if r.returncode:
        raise PRError(f"gh pr create failed: {r.stderr.strip()[:500]}")
    return r.stdout.strip().splitlines()[-1]


def review_record(item: Item, repo: str, url: str, body_md: str) -> dict:
    """The generic ADR-17 review-record contract."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "id": f"nightcrew-{uuid.uuid4().hex[:12]}",
        "source": "nightcrew",
        "kind": "pr",
        "title": f"[nightcrew] {item.id}: {item.description}",
        "body_md": body_md,
        "url": url,
        "options": ["approve", "decline"],
        "meta": {"pr_number": int(tail) if tail.isdigit() else None, "repo": repo},
    }


def _git(worktree: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", worktree, *args],
                       capture_output=True, text=True)
    if r.returncode:
        raise PRError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout
