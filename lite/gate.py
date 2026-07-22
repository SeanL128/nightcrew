#!/usr/bin/env python3
"""Nightcrew deterministic gate (ADR-5/6). Shared by Lite and Engine.

Usage:
    gate.py [--base main] [--repo DIR]   # run the gate: re-run tests + diff checks
    gate.py spec [--repo DIR]            # validate nightcrew.yaml, list item statuses

Exit 0 = pass, 1 = blocked (reasons on stdout), 2 = usage/config error.
Dependency-light: stdlib only, PyYAML used if available.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

TEST_FILE_RE = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.[^/.]*$)")
TEST_DEF_RE = re.compile(r"^\s*def (test_\w+)|^\s*(?:it|test|describe)\(")
ASSERT_RE = re.compile(r"^\s*(assert\b|self\.assert\w+|expect\()")

# criteria this thin can never anchor cited evidence (ADR-5)
MIN_CRITERIA = 2
MIN_CRITERION_LEN = 15


def load_spec(repo: Path):
    path = repo / "nightcrew.yaml"
    if not path.exists():
        sys.exit_code = 2
        print(f"BLOCKED: no nightcrew.yaml in {repo}")
        raise SystemExit(2)
    text = path.read_text()
    try:
        import yaml  # ponytail: PyYAML if present; regex fallback covers test_cmd-only use
        return yaml.safe_load(text)
    except ImportError:
        m = re.search(r"""^\s*test_cmd:\s*["']?(.+?)["']?\s*$""", text, re.M)
        return {"config": {"test_cmd": m.group(1) if m else None}, "items": None}


def run_tests(repo: Path, test_cmd: str) -> list:
    print(f"gate: re-running tests: {test_cmd}")
    r = subprocess.run(test_cmd, shell=True, cwd=repo)
    return [] if r.returncode == 0 else [f"test_cmd exited {r.returncode}"]


def check_test_tampering(repo: Path, base: str) -> list:
    """Block diffs that remove test functions or reduce assertions in test files."""
    r = subprocess.run(
        ["git", "diff", f"{base}...HEAD"], cwd=repo, capture_output=True, text=True
    )
    if r.returncode != 0:
        return [f"git diff failed: {r.stderr.strip()}"]
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

    for line in r.stdout.splitlines():
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


def item_status(item: dict) -> str:
    crits = item.get("acceptance_criteria") or []
    if len(crits) < MIN_CRITERIA or any(
        len(str(c).strip()) < MIN_CRITERION_LEN for c in crits
    ):
        return "underspecified"
    return "ok"


def cmd_spec(repo: Path) -> int:
    spec = load_spec(repo)
    if spec.get("items") is None:
        print("BLOCKED: could not parse items (is PyYAML installed?)")
        return 2
    cfg = spec.get("config") or {}
    if not cfg.get("test_cmd"):
        print("BLOCKED: config.test_cmd missing")
        return 1
    bad = 0
    for item in spec["items"]:
        status = item_status(item)
        print(f"{item.get('id', '<no id>')}: {status}")
        bad += status != "ok"
    return 1 if bad else 0


def cmd_gate(repo: Path, base: str) -> int:
    spec = load_spec(repo)
    test_cmd = (spec.get("config") or {}).get("test_cmd")
    if not test_cmd:
        print("BLOCKED: config.test_cmd missing from nightcrew.yaml")
        return 2
    reasons = check_test_tampering(repo, base) + run_tests(repo, test_cmd)
    if reasons:
        print("GATE: BLOCKED")
        for r in reasons:
            print(f"  - {r}")
        return 1
    print("GATE: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="gate", choices=["gate", "spec"])
    ap.add_argument("--base", default="main")
    ap.add_argument("--repo", default=".", type=Path)
    a = ap.parse_args()
    repo = a.repo.resolve()
    return cmd_spec(repo) if a.command == "spec" else cmd_gate(repo, a.base)


if __name__ == "__main__":
    raise SystemExit(main())
