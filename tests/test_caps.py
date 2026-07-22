"""Fleet caps: parsing, accounting, usage headroom, and runner boundary."""

import json
from datetime import datetime, timedelta, timezone

from nightcrew.caps import Caps, check
from nightcrew.config import Fleet, Repo, load_fleet
from nightcrew.log import BuildLog
from nightcrew import runner


def test_load_fleet_caps_and_defaults(tmp_path):
    fleet_path = tmp_path / "fleet.json"
    fleet_path.write_text(json.dumps({"repos": [{"name": "r", "github": "x/r"}],
                                      "caps": {"daily_usd": 2.5, "max_items": 3}}))
    fleet = load_fleet(fleet_path)
    assert fleet.caps.daily_usd == 2.5
    assert fleet.caps.max_items == 3
    assert fleet.caps.per_run_usd is None

    fleet_path.write_text(json.dumps({"repos": [{"name": "r", "github": "x/r"}]}))
    assert load_fleet(fleet_path).caps == Caps()


def test_check_metered_caps(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    log.record_item(run_id, "r", "one", cost_usd=2.0)

    assert "daily" in check(Caps(daily_usd=2), log, run_id)
    assert "run" in check(Caps(per_run_usd=2), log, run_id)
    assert check(Caps(max_items=2), log, run_id) is None
    log.record_item(run_id, "r", "two", outcome="skipped")
    assert check(Caps(max_items=2), log, run_id) is None
    log.record_item(run_id, "r", "three")
    assert "item" in check(Caps(max_items=2), log, run_id)

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    log.db.execute("INSERT INTO runs (started) VALUES (?)", (yesterday,))
    old_run = log.db.execute("SELECT last_insert_rowid()").fetchone()[0]
    log.record_item(old_run, "r", "old", cost_usd=99)
    assert check(Caps(daily_usd=2.1), log, run_id) is None


def test_check_usage_requires_all_vendors_and_fails_open(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    run_id = log.start_run()
    caps = Caps(usage={"argv": ["unused"], "max_used_percent": 85})
    one_has_headroom = ["python3", "-c", "import json; print(json.dumps({'claude': {'windows': [{'usedPercent': 90}]}, 'codex': {'windows': [{'usedPercent': 60}]}, 'verdict': 'ok'}))"]
    saturated = ["python3", "-c", "import json; print(json.dumps({'claude': {'windows': [{'usedPercent': 90}]}, 'codex': {'windows': [{'usedPercent': 85}]}}))"]
    failed = ["python3", "-c", "raise SystemExit(1)"]
    assert check(caps, log, run_id, usage_argv=one_has_headroom) is None
    assert "usage" in check(caps, log, run_id, usage_argv=saturated)
    assert check(caps, log, run_id, usage_argv=failed) is None


def test_runner_stops_all_repos_at_cap_boundary(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    fleet = Fleet(repos=[Repo(name="first", github="x/first", path=str(tmp_path)),
                         Repo(name="second", github="x/second", path=str(tmp_path))],
                  dispatch={}, caps=Caps(max_items=0))
    outcomes = runner.run(fleet, log)
    assert [(o.repo, o.status) for o in outcomes] == [("first", "capped")]
    rows = log.db.execute("SELECT repo, item_id, outcome FROM item_records").fetchall()
    assert [tuple(row) for row in rows] == [("first", "-", "capped")]
