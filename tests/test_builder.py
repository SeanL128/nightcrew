import subprocess
from pathlib import Path

import pytest

from nightcrew.builder import BuildError, build
from nightcrew.dispatch import dispatch


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    return tmp_path


def command_config(command):
    return {"roles": {"build": {"backend": "command", "argv": ["sh", "-c", command]}}}


def cleanup(repo, result):
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", result.worktree], check=True)


def cleanup_branch(repo, branch):
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    lines = listing.splitlines()
    for i, line in enumerate(lines):
        if line == f"branch refs/heads/{branch}":
            cleanup(repo, type("Result", (), {"worktree": lines[i - 2].removeprefix("worktree ")})())
            return


def test_build_returns_staged_diff_and_metadata(repo):
    result = build(repo, "alpha", {}, "build", command_config(
        "echo new > built.txt; echo '{\"result\":\"done\",\"total_cost_usd\":0.2,\"usage\":{\"output_tokens\":3}}'"
    ), [])

    assert "built.txt" in result.diff
    assert result.branch == "nightcrew/alpha"
    assert Path(result.worktree).exists()
    assert (Path(result.worktree) / "built.txt").read_text() == "new\n"
    assert result.cost_usd == 0.2
    assert result.usage == {"output_tokens": 3}
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout == ""
    cleanup(repo, result)


def test_build_rejects_off_limits_file_and_directory(repo):
    with pytest.raises(BuildError, match="built.txt"):
        build(repo, "blocked-file", {}, "build", command_config("echo new > built.txt"), ["built.txt"])
    cleanup_branch(repo, "nightcrew/blocked-file")
    with pytest.raises(BuildError, match="docs/x.txt"):
        build(repo, "blocked-dir", {}, "build", command_config("mkdir -p docs; echo new > docs/x.txt"), ["docs/"])
    cleanup_branch(repo, "nightcrew/blocked-dir")


def test_dispatch_command_runs_in_cwd(repo, tmp_path):
    worktree = tmp_path / "cwd"
    worktree.mkdir()
    result = dispatch("build", {}, command_config("pwd"), cwd=worktree)
    assert result.text == str(worktree)


def test_build_reuses_stale_branch_with_no_worktree(repo):
    subprocess.run(["git", "-C", str(repo), "branch", "nightcrew/stale"], check=True)
    result = build(repo, "stale", {}, "build", command_config("true"), [])
    assert result.branch == "nightcrew/stale"
    cleanup(repo, result)


def test_build_failed_worktree_add(repo):
    first = build(repo, "same", {}, "build", command_config("true"), [])
    with pytest.raises(BuildError, match="nightcrew/same"):
        build(repo, "same", {}, "build", command_config("true"), [])
    cleanup(repo, first)
