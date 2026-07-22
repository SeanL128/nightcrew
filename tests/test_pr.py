import json
import subprocess

import pytest

from nightcrew.config import Item
from nightcrew.gate import CriterionVerdict, GateResult
from nightcrew.log import BuildLog
from nightcrew.pr import PRError, open_pr, pr_body, review_record

ITEM = Item(id="alpha", description="Add greet", acceptance_criteria=["a", "b"])

PASSED = GateResult(True, [], [
    CriterionVerdict("greet() returns hello", True, "greet.py hunk +2"),
    CriterionVerdict("a test | asserts it", True, "test_x.py::test_a\npasses"),
])


def test_pr_body_table_cost_and_escaping():
    body = pr_body(ITEM, PASSED, 0.42)
    assert "gate: PASS" in body
    assert "| greet() returns hello | ✅ | greet.py hunk +2 |" in body
    assert "a test \\| asserts it" in body  # pipes escaped
    assert "test_x.py::test_a passes" in body  # newlines flattened
    assert "**Total run cost:** $0.42" in body
    assert "Never auto-merged" in body


def test_pr_body_unmetered_cost():
    assert "n/a (unmetered)" in pr_body(ITEM, PASSED, None)


def test_open_pr_refuses_unverified():
    blocked = GateResult(False, ["criterion 1 not met"], [])
    with pytest.raises(PRError, match="unverified"):
        open_pr("/nowhere", "nightcrew/alpha", ITEM, blocked, None)


@pytest.fixture
def worktree_with_origin(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(wt), "remote", "add", "origin", str(origin)], check=True)
    (wt / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(wt), "checkout", "-qb", "nightcrew/alpha"], check=True)
    (wt / "greet.py").write_text("def greet():\n    return 'hello'\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
    return wt, origin


def test_open_pr_commits_pushes_and_returns_url(tmp_path, worktree_with_origin):
    wt, origin = worktree_with_origin
    gh_stub = tmp_path / "gh"
    gh_stub.write_text("#!/bin/sh\necho https://github.com/x/y/pull/7\n")
    gh_stub.chmod(0o755)

    url = open_pr(str(wt), "nightcrew/alpha", ITEM, PASSED, 0.1,
                  gh_argv=[str(gh_stub)])

    assert url == "https://github.com/x/y/pull/7"
    pushed = subprocess.run(
        ["git", "-C", str(origin), "log", "--oneline", "nightcrew/alpha"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "nightcrew: alpha" in pushed


def test_open_pr_overwrites_stale_remote_branch(tmp_path, worktree_with_origin):
    """A leftover nightcrew/<item> branch from a closed PR must not block the push."""
    wt, origin = worktree_with_origin
    stale = tmp_path / "stale"
    subprocess.run(["git", "clone", "-q", str(origin), str(stale)], check=True)
    subprocess.run(["git", "-C", str(stale), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(stale), "config", "user.name", "T"], check=True)
    (stale / "old.txt").write_text("stale attempt\n")
    subprocess.run(["git", "-C", str(stale), "checkout", "-qb", "nightcrew/alpha"], check=True)
    subprocess.run(["git", "-C", str(stale), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(stale), "commit", "-qm", "stale"], check=True)
    subprocess.run(["git", "-C", str(stale), "push", "-q", "origin", "nightcrew/alpha"], check=True)

    gh_stub = tmp_path / "gh"
    gh_stub.write_text("#!/bin/sh\necho https://github.com/x/y/pull/8\n")
    gh_stub.chmod(0o755)

    url = open_pr(str(wt), "nightcrew/alpha", ITEM, PASSED, 0.1,
                  gh_argv=[str(gh_stub)])

    assert url == "https://github.com/x/y/pull/8"
    pushed = subprocess.run(
        ["git", "-C", str(origin), "log", "--oneline", "nightcrew/alpha"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "nightcrew: alpha" in pushed
    assert "stale" not in pushed


def test_open_pr_surfaces_gh_failure(tmp_path, worktree_with_origin):
    wt, _ = worktree_with_origin
    gh_stub = tmp_path / "gh"
    gh_stub.write_text("#!/bin/sh\necho no auth >&2\nexit 1\n")
    gh_stub.chmod(0o755)
    with pytest.raises(PRError, match="no auth"):
        open_pr(str(wt), "nightcrew/alpha", ITEM, PASSED, None,
                gh_argv=[str(gh_stub)])


def test_review_record_contract():
    record = review_record(ITEM, "nightcrew", "https://github.com/x/y/pull/7",
                           "body md")
    assert record["source"] == "nightcrew"
    assert record["kind"] == "pr"
    assert record["title"] == "[nightcrew] alpha: Add greet"
    assert record["body_md"] == "body md"
    assert record["options"] == ["approve", "decline"]
    assert record["meta"] == {"pr_number": 7, "repo": "nightcrew"}
    assert record["id"].startswith("nightcrew-")


def test_review_record_sink_in_build_log(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    record = review_record(ITEM, "r", "https://github.com/x/y/pull/9", "b")
    log.record_review(record)
    row = log.db.execute("SELECT record FROM review_records WHERE id = ?",
                         (record["id"],)).fetchone()
    assert json.loads(row["record"]) == record
