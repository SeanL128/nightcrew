import json

import pytest

from nightcrew.config import ConfigError, load_fleet, load_repo_spec
from nightcrew.dispatch import DispatchError, dispatch
from nightcrew.log import BuildLog
from nightcrew.spec import statuses

SPEC = """\
config:
  test_cmd: "pytest -q"
  off_limits: ["deploy/"]
items:
  - id: alpha
    description: first
    acceptance_criteria: ["fn('x') returns 'y' verified", "full suite passes cleanly"]
  - id: beta
    description: depends on alpha
    acceptance_criteria: ["fn('a') returns 'b' verified", "full suite passes cleanly"]
    deps: [alpha]
  - id: thin
    description: too thin
    acceptance_criteria: ["works"]
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "nightcrew.yaml").write_text(SPEC)
    return tmp_path


def test_repo_spec_loads(repo):
    spec = load_repo_spec(repo)
    assert spec.test_cmd == "pytest -q"
    assert [i.id for i in spec.items] == ["alpha", "beta", "thin"]


def test_repo_spec_requires_test_cmd(tmp_path):
    (tmp_path / "nightcrew.yaml").write_text("config: {}\nitems: []\n")
    with pytest.raises(ConfigError, match="test_cmd"):
        load_repo_spec(tmp_path)


def test_statuses(repo):
    spec = load_repo_spec(repo)
    assert statuses(spec.items, done=set(), open_prs=set()) == {
        "alpha": "ready", "beta": "blocked-by-deps", "thin": "underspecified",
    }
    assert statuses(spec.items, done={"alpha"}, open_prs={"beta"}) == {
        "alpha": "done", "beta": "has-open-pr", "thin": "underspecified",
    }


def test_fleet_loads(tmp_path):
    f = tmp_path / "fleet.json"
    f.write_text(json.dumps({
        "repos": [{"name": "r", "github": "u/r"}],
        "dispatch": {"roles": {"build": {"backend": "command", "argv": ["true"]}}},
    }))
    fleet = load_fleet(f)
    assert fleet.repos[0].trust == "propose_only"
    assert "build" in fleet.dispatch["roles"]


def test_dispatch_command_roundtrip():
    # smoke brief through a command-template backend (cat echoes the brief file)
    cfg = {"roles": {"build": {"backend": "command", "argv": ["cat", "{brief_path}"]}}}
    r = dispatch("build", {"goal": "smoke"}, cfg)
    assert json.loads(r.text) if r.text.startswith("{") else r.text
    assert "smoke" in r.text


def test_dispatch_parses_claude_json():
    payload = json.dumps({"result": "done", "total_cost_usd": 0.12, "usage": {"output_tokens": 5}})
    cfg = {"roles": {"j": {"backend": "command", "argv": ["echo", payload]}}}
    r = dispatch("j", {}, cfg)
    assert (r.text, r.cost_usd, r.usage["output_tokens"]) == ("done", 0.12, 5)


def test_dispatch_parses_alloyd_jsonl():
    # shape captured from the real alloyd/codex smoke, 2026-07-21
    from nightcrew.dispatch import _parse_output
    stream = "\n".join([
        "→ foreman-build: codex/gpt-5.6 (medium)",
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "item.completed",
                    "item": {"id": "i1", "type": "agent_message", "text": "SMOKE-OK"}}),
        json.dumps({"type": "turn.completed",
                    "usage": {"input_tokens": 21091, "output_tokens": 8}}),
    ])
    r = _parse_output(stream)
    assert (r.text, r.cost_usd, r.usage["output_tokens"]) == ("SMOKE-OK", None, 8)


def test_dispatch_unknown_role():
    with pytest.raises(DispatchError):
        dispatch("nope", {}, {"roles": {}})


def test_build_log(tmp_path):
    log = BuildLog(tmp_path / "log.db")
    run = log.start_run()
    rec = log.record_item(run, "sandbox", "alpha", plan="do it",
                          gate=[{"criterion": "c", "verdict": "pass"}],
                          pr_url="http://pr/1")
    log.finish_run(run, cost_usd=0.5)
    log.set_outcome(rec, "merged")
    assert log.item_ids_with("sandbox", ("merged",)) == {"alpha"}
    assert log.item_ids_with("sandbox", ("pending",)) == set()
