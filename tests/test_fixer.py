import json
import subprocess

import pytest

from nightcrew.builder import BuildError
from nightcrew.config import Item, RepoSpec
from nightcrew.fixer import FixResult, fix_and_regate, fix_brief
from nightcrew.gate import GateResult

ITEM = Item(
    id="alpha",
    description="Add a greet function",
    acceptance_criteria=[
        "greet() returns the string hello exactly",
        "a test exists that calls greet() and asserts its return value",
    ],
)

SPEC = RepoSpec(test_cmd="true", off_limits=["locked.txt"], conventions="", items=[ITEM])

BLOCKED = GateResult(False, ["criterion 1 not met: greet returns hi"], [])

ALL_MET = json.dumps({"verdicts": [
    {"criterion": 1, "met": True, "evidence": "greet.py"},
    {"criterion": 2, "met": True, "evidence": "test_x.py"},
]})


def config(build_command, judge_command=f"echo '{ALL_MET}'"):
    return {"roles": {
        "build": {"backend": "command", "argv": ["sh", "-c", build_command],
                  "family": "openai"},
        "judge": {"backend": "command", "argv": ["sh", "-c", judge_command],
                  "family": "anthropic"},
    }}


@pytest.fixture
def worktree(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    (tmp_path / "greet.py").write_text("def greet():\n    return 'hi'\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_fix_brief_appends_gate_reasons():
    brief = {"goal": "build it", "constraints": "c", "acceptance": "a"}
    fixed = fix_brief(brief, ["criterion 1 not met", "test_cmd exited 1"])
    assert fixed["goal"].startswith("build it")
    assert "BLOCKED" in fixed["goal"]
    assert "- criterion 1 not met" in fixed["goal"]
    assert "- test_cmd exited 1" in fixed["goal"]
    assert fixed["constraints"] == "c" and fixed["acceptance"] == "a"
    assert brief["goal"] == "build it"  # original untouched


def test_fix_passes_regate_and_keeps_cumulative_diff(worktree):
    result = fix_and_regate(
        str(worktree), ITEM, SPEC, {"goal": "build it"}, BLOCKED,
        "build", "judge",
        config("printf 'def greet():\\n    return \"hello\"\\n' > greet.py"),
    )
    assert isinstance(result, FixResult)
    assert result.gate.passed
    assert "greet.py" in result.diff  # cumulative staged diff vs HEAD
    assert [v.met for v in result.gate.verdicts] == [True, True]


def test_fix_dispatch_receives_gate_reasons(worktree):
    cfg = config("true")
    # builder exits nonzero (→ DispatchError) unless the gate reason is in the brief
    cfg["roles"]["build"]["argv"] = [
        "sh", "-c", "grep -q 'criterion 1 not met' \"$1\"", "sh", "{brief_path}",
    ]
    result = fix_and_regate(
        str(worktree), ITEM, SPEC, {"goal": "build it"}, BLOCKED,
        "build", "judge", cfg,
    )
    assert result.gate.passed


def test_fix_still_blocked_after_regate(worktree):
    unmet = json.dumps({"verdicts": [
        {"criterion": 1, "met": False, "evidence": "still hi"},
        {"criterion": 2, "met": True, "evidence": "test_x.py"},
    ]})
    result = fix_and_regate(
        str(worktree), ITEM, SPEC, {"goal": "build it"}, BLOCKED,
        "build", "judge", config("true", f"echo '{unmet}'"),
    )
    assert not result.gate.passed
    assert any("criterion 1 not met" in r for r in result.gate.reasons)


def test_fix_touching_off_limits_raises(worktree):
    with pytest.raises(BuildError, match="locked.txt"):
        fix_and_regate(
            str(worktree), ITEM, SPEC, {"goal": "build it"}, BLOCKED,
            "build", "judge", config("echo x > locked.txt"),
        )
