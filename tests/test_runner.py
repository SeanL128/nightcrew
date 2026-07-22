"""Orchestrator (BP9): backfill, per-repo loop, cleanup, exit paths."""

import json
import subprocess

import pytest

from nightcrew import runner
from nightcrew.pr import PRError
from nightcrew.config import Fleet, Repo
from nightcrew.gate import CriterionVerdict, GateResult
from nightcrew.log import BuildLog

FAKE_GH_MERGED = ["python3", "-c",
                  "import json,sys; a=sys.argv;"
                  "print(json.dumps({'state':'MERGED'}) if 'view' in a else 'https://github.com/x/y/pull/7')",
                  "gh"]

SPEC_YAML = """
config:
  test_cmd: "true"
items:
  - id: item-1
    description: first item
    acceptance_criteria:
      - "criterion one is satisfied fully"
      - "criterion two is satisfied fully"
"""


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(cmd, cwd=path, check=True, capture_output=True)
    (path / "nightcrew.yaml").write_text(SPEC_YAML)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "spec"], cwd=path, check=True, capture_output=True)
    return path


def fleet_for(path):
    return Fleet(
        repos=[Repo(name="r", github="x/r", path=str(path))],
        dispatch={"roles": {
            "foreman-build": {"backend": "command", "family": "openai", "argv": ["true"]},
            "nightcrew-judge": {"backend": "command", "family": "anthropic", "argv": ["true"]},
        }},
    )


def passing_gate(*a, **k):
    return GateResult(True, [], [CriterionVerdict("c1", True, "diff hunk"),
                                 CriterionVerdict("c2", True, "test output")])


def test_backfill_marks_merged(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    rec = log.record_item(run_id, "r", "item-0", pr_url="https://github.com/x/y/pull/1")
    runner.backfill_outcomes(log, gh_argv=FAKE_GH_MERGED)
    row = log.db.execute("SELECT outcome FROM item_records WHERE id=?", (rec,)).fetchone()
    assert row["outcome"] == "merged"


def test_run_opens_pr_and_cleans_worktree(tmp_path, repo, monkeypatch):
    monkeypatch.setattr(runner.gate_mod, "gate", passing_gate)
    monkeypatch.setattr(runner.pr_mod, "open_pr",
                        lambda *a, **k: "https://github.com/x/r/pull/7")
    log = BuildLog(tmp_path / "log.db")
    outcomes = runner.run(fleet_for(repo), log, gh_argv=FAKE_GH_MERGED)
    assert [o.status for o in outcomes] == ["pr-opened"]
    assert outcomes[0].pr_url.endswith("/7")
    row = log.db.execute("SELECT outcome, pr_url, gate FROM item_records").fetchone()
    assert row["outcome"] == "pending" and json.loads(row["gate"])[0]["met"]
    assert log.db.execute("SELECT COUNT(*) c FROM review_records").fetchone()["c"] == 1
    worktrees = subprocess.run(["git", "worktree", "list"], cwd=repo,
                               capture_output=True, text=True).stdout
    assert "nightcrew-wt" not in worktrees


def test_blocked_after_fix_logs_and_no_pr(tmp_path, repo, monkeypatch):
    blocked = GateResult(False, ["criterion 1 not met: c1"],
                         [CriterionVerdict("c1", False)])
    monkeypatch.setattr(runner.gate_mod, "gate", lambda *a, **k: blocked)
    monkeypatch.setattr(runner.fixer, "fix_and_regate",
                        lambda *a, **k: runner.fixer.FixResult(blocked, ""))
    log = BuildLog(tmp_path / "log.db")
    outcomes = runner.run(fleet_for(repo), log)
    assert [o.status for o in outcomes] == ["blocked"]
    row = log.db.execute("SELECT outcome, pr_url FROM item_records").fetchone()
    assert row["outcome"] == "blocked" and row["pr_url"] is None


def test_open_pr_item_not_repicked(tmp_path, repo, monkeypatch):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    log.record_item(run_id, "r", "item-1", pr_url="https://github.com/x/r/pull/1")
    fleet = fleet_for(repo)
    fleet.repos[0].max_items_per_run = 3
    outcomes = runner.run_repo(fleet.repos[0], fleet.dispatch, log, run_id)
    assert outcomes == []


def test_live_open_pr_item_not_repicked(tmp_path, repo):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    fleet = fleet_for(repo)
    live_prs = ["python3", "-c", "import json; print(json.dumps([{'headRefName': 'nightcrew/item-1'}]))"]
    assert runner.run_repo(fleet.repos[0], fleet.dispatch, log, run_id,
                           gh_argv=live_prs) == []


def test_live_open_pr_failure_falls_back_to_log(tmp_path, repo):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    log.record_item(run_id, "r", "item-1", pr_url="https://github.com/x/r/pull/1")
    fleet = fleet_for(repo)
    failed_gh = ["python3", "-c", "raise SystemExit(1)"]
    assert runner.run_repo(fleet.repos[0], fleet.dispatch, log, run_id,
                           gh_argv=failed_gh) == []


def test_mid_run_pr_not_repicked_same_run(tmp_path, repo, monkeypatch):
    monkeypatch.setattr(runner.gate_mod, "gate", passing_gate)
    monkeypatch.setattr(runner.pr_mod, "open_pr",
                        lambda *a, **k: "https://github.com/x/r/pull/7")
    log = BuildLog(tmp_path / "log.db")
    fleet = fleet_for(repo)
    fleet.repos[0].max_items_per_run = 3
    outcomes = runner.run(fleet, log, gh_argv=FAKE_GH_MERGED)
    assert [o.status for o in outcomes] == ["pr-opened"]  # item-1 not rebuilt


def test_pr_error_after_gate_records_gate_json(tmp_path, repo, monkeypatch):
    monkeypatch.setattr(runner.gate_mod, "gate", passing_gate)
    monkeypatch.setattr(runner.pr_mod, "open_pr", lambda *a, **k: (_ for _ in ()).throw(PRError("nope")))
    log = BuildLog(tmp_path / "log.db")
    outcomes = runner.run(fleet_for(repo), log)
    assert [o.status for o in outcomes] == ["build-error"]
    row = log.db.execute("SELECT gate FROM item_records").fetchone()
    assert json.loads(row["gate"])[0]["met"] is True


def test_missing_path_skips(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    outcomes = runner.run_repo(Repo(name="r", github="x/r", path=str(tmp_path / "nope")),
                               {}, log, run_id)
    assert [o.status for o in outcomes] == ["skipped"]
