import json
import subprocess

from nightcrew.__main__ import main
from nightcrew.log import BuildLog


def write_fleet(tmp_path, repos=None):
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps({
        "repos": repos or [],
        "dispatch": {"roles": {"builder": {"argv": ["true"]}}},
        "caps": {"per_run_usd": 3},
    }))
    return path


def write_spec(repo, test_cmd="pytest -q"):
    repo.mkdir()
    (repo / "nightcrew.yaml").write_text(f"config:\n  test_cmd: {test_cmd!r}\n")


def test_enroll_refuses_repo_without_spec(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["enroll", str(repo), "--fleet", str(write_fleet(tmp_path)),
                 "--github", "owner/repo"]) == 2
    assert "no nightcrew.yaml" in capsys.readouterr().err


def test_enroll_refuses_failing_test_command(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    write_spec(repo)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "one\ntwo\n", ""))
    assert main(["enroll", str(repo), "--fleet", str(write_fleet(tmp_path)),
                 "--github", "owner/repo"]) == 2
    assert "two" in capsys.readouterr().err


def test_enroll_adds_repo_and_preserves_fleet_settings(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    write_spec(repo)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    fleet = write_fleet(tmp_path)
    assert main(["enroll", str(repo), "--fleet", str(fleet), "--github", "owner/repo"]) == 0
    data = json.loads(fleet.read_text())
    assert data["dispatch"] == {"roles": {"builder": {"argv": ["true"]}}}
    assert data["caps"] == {"per_run_usd": 3}
    assert data["repos"] == [{"name": "repo", "github": "owner/repo", "path": str(repo.resolve()),
                               "enabled": True, "trust": "propose_only", "priority": 100,
                               "max_items_per_run": 1}]


def test_enroll_update_keeps_unowned_settings(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    write_spec(repo)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    fleet = write_fleet(tmp_path, [{"name": "repo", "github": "old/repo", "path": "/old",
                                    "enabled": False, "trust": "merge", "priority": 9,
                                    "max_items_per_run": 4, "unknown": True}])
    assert main(["enroll", str(repo), "--fleet", str(fleet), "--github", "owner/repo"]) == 0
    entry = json.loads(fleet.read_text())["repos"][0]
    assert entry == {"name": "repo", "github": "owner/repo", "path": str(repo.resolve()),
                     "enabled": True, "trust": "merge", "priority": 9,
                     "max_items_per_run": 4, "unknown": True}


def test_enroll_uses_explicit_priority(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    write_spec(repo)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    fleet = write_fleet(tmp_path)
    assert main(["enroll", str(repo), "--fleet", str(fleet), "--github", "owner/repo",
                 "--priority", "0"]) == 0
    assert json.loads(fleet.read_text())["repos"][0]["priority"] == 0


def test_status_prints_repo_tallies_and_empty_log(tmp_path, capsys):
    fleet = write_fleet(tmp_path, [{"name": "repo", "github": "owner/repo"}])
    log_path = tmp_path / "log.db"
    log = BuildLog(log_path)
    run = log.start_run()
    for outcome in ("pending", "merged", "closed", "blocked", "build-error", "skipped", "capped"):
        log.record_item(run, "repo", outcome, outcome=outcome, cost_usd=1)
    log.finish_run(run, 7)
    assert main(["status", "--fleet", str(fleet), "--log", str(log_path)]) == 0
    out = capsys.readouterr().out
    assert "repo: enabled=True priority=100" in out
    assert "pending=1 merged=1 closed=1 blocked=1 build-error=1 skipped=1 capped=1 cost_usd=7.00" in out
    assert "last run:" in out
    assert main(["status", "--fleet", str(fleet), "--log", str(tmp_path / "empty.db")]) == 0


def test_digest_prints_last_run_gate_and_pending_prs(tmp_path, capsys):
    fleet = write_fleet(tmp_path, [{"name": "repo", "github": "owner/repo"}])
    log_path = tmp_path / "log.db"
    log = BuildLog(log_path)
    old_run = log.start_run()
    log.record_item(old_run, "repo", "old", outcome="merged")
    log.finish_run(old_run)
    run = log.start_run()
    log.record_item(run, "repo", "new", outcome="pending", cost_usd=1.25,
                    pr_url="https://example/pr/1", skip_reason="note",
                    gate=[{"met": True}, {"met": False}])
    log.finish_run(run)
    assert main(["digest", "--fleet", str(fleet), "--log", str(log_path)]) == 0
    out = capsys.readouterr().out
    assert "repo/new: pending cost_usd=1.25 https://example/pr/1 — note gate=1/2" in out
    assert "PRs awaiting review:" in out
    assert "repo/new: https://example/pr/1" in out
    assert main(["digest", "--fleet", str(fleet), "--log", str(tmp_path / "empty.db")]) == 0
