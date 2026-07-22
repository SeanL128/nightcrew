"""Run a build dispatch in a dedicated git worktree."""

import fnmatch
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .dispatch import dispatch


class BuildError(Exception):
    pass


@dataclass
class BuildResult:
    diff: str
    worktree: str
    branch: str
    cost_usd: float | None
    usage: dict


def build(repo: str | Path, item_id: str, brief: dict, role: str,
          dispatch_config: dict, off_limits: list[str]) -> BuildResult:
    repo = str(repo)
    branch = f"nightcrew/{item_id}"
    worktree = tempfile.mkdtemp(prefix="nightcrew-wt-")
    os.rmdir(worktree)
    added = subprocess.run(
        ["git", "-C", repo, "worktree", "add", "-B", branch, worktree],
        capture_output=True, text=True,
    )
    if added.returncode:
        raise BuildError(f"worktree add failed: {added.stderr.strip()}")

    diff, result = dispatch_and_stage(worktree, brief, role, dispatch_config, off_limits)
    # ponytail: caller-owned worktree; cleanup belongs to the PR stage.
    return BuildResult(diff, worktree, branch, result.cost_usd, result.usage)


def dispatch_and_stage(worktree: str, brief: dict, role: str,
                       dispatch_config: dict, off_limits: list[str]):
    """Dispatch into the worktree, stage everything, enforce off-limits.

    Returns (cumulative staged diff vs HEAD, DispatchResult). Shared by the
    initial build and the fix loop.
    """
    result = dispatch(role, brief, dispatch_config, cwd=worktree)
    _git(worktree, "add", "-A")
    diff = _git(worktree, "diff", "--cached")
    touched = _git(worktree, "diff", "--cached", "--name-only").splitlines()
    violations = [path for path in touched if any(
        fnmatch.fnmatch(path, pattern)
        or path == pattern
        or path.startswith(pattern.rstrip("/") + "/")
        for pattern in off_limits
    )]
    if violations:
        raise BuildError(f"off-limits paths touched: {', '.join(violations)}")
    return diff, result


def _git(worktree: str, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", worktree, *args], capture_output=True, text=True,
    )
    if completed.returncode:
        raise BuildError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout
