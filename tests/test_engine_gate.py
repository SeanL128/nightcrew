import json
import subprocess

import pytest

from nightcrew.config import Item, RepoSpec
from nightcrew.gate import GateError, gate

ITEM = Item(
    id="alpha",
    description="Add a greet function",
    acceptance_criteria=[
        "greet() returns the string 'hello' exactly",
        "a test exists that calls greet() and asserts its return value",
    ],
)


def spec(test_cmd="true"):
    return RepoSpec(test_cmd=test_cmd, off_limits=[], conventions="", items=[ITEM])


def judge_json(verdicts):
    return json.dumps({"verdicts": verdicts})


def config(judge_command="true", judge_family="anthropic", builder_family="openai"):
    return {"roles": {
        "build": {"backend": "command", "argv": ["true"], "family": builder_family},
        "judge": {"backend": "command", "argv": ["sh", "-c", judge_command],
                  "family": judge_family},
    }}


@pytest.fixture
def worktree(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "test_x.py").write_text(
        "def test_a():\n    assert 1\n    assert 2\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    return tmp_path


def stage(worktree):
    subprocess.run(["git", "-C", str(worktree), "add", "-A"], check=True)


def test_satisfying_diff_passes(worktree):
    (worktree / "greet.py").write_text("def greet():\n    return 'hello'\n")
    stage(worktree)
    all_met = judge_json([
        {"criterion": 1, "met": True, "evidence": "greet.py returns hello"},
        {"criterion": 2, "met": True, "evidence": "test_x.py::test_a"},
    ])
    result = gate(str(worktree), ITEM, spec(), "judge", "build",
                  config(f"echo '{all_met}'"))
    assert result.passed
    assert [v.met for v in result.verdicts] == [True, True]
    assert result.verdicts[0].evidence == "greet.py returns hello"


def test_unmet_criterion_blocks_with_citing_reason(worktree):
    (worktree / "greet.py").write_text("def greet():\n    return 'hi'\n")
    stage(worktree)
    one_unmet = judge_json([
        {"criterion": 1, "met": False, "evidence": "greet returns hi not hello"},
        {"criterion": 2, "met": True, "evidence": "test_x.py::test_a"},
    ])
    result = gate(str(worktree), ITEM, spec(), "judge", "build",
                  config(f"echo '{one_unmet}'"))
    assert not result.passed
    assert any("criterion 1 not met" in r and "hi not hello" in r
               for r in result.reasons)


def test_missing_criterion_blocks(worktree):
    stage(worktree)
    partial = judge_json([{"criterion": 1, "met": True, "evidence": "x"}])
    result = gate(str(worktree), ITEM, spec(), "judge", "build",
                  config(f"echo '{partial}'"))
    assert not result.passed
    assert any("criterion 2 unaddressed" in r for r in result.reasons)


def test_failing_tests_block_without_calling_judge(worktree):
    stage(worktree)
    # judge argv exits 1: dispatch would raise if the judge were called
    result = gate(str(worktree), ITEM, spec(test_cmd="false"), "judge", "build",
                  config("exit 1"))
    assert not result.passed
    assert result.reasons == ["test_cmd exited 1"]
    assert result.verdicts == []


def test_test_weakening_diff_blocks_without_calling_judge(worktree):
    (worktree / "test_x.py").write_text("def test_a():\n    assert 1\n")
    stage(worktree)
    result = gate(str(worktree), ITEM, spec(), "judge", "build", config("exit 1"))
    assert not result.passed
    assert any("assertions weakened in test_x.py" in r for r in result.reasons)


def test_removed_test_function_blocks(worktree):
    (worktree / "test_x.py").write_text("def test_b():\n    assert 1\n    assert 2\n")
    stage(worktree)
    result = gate(str(worktree), ITEM, spec(), "judge", "build", config("exit 1"))
    assert not result.passed
    assert any("test function removed: test_a" in r for r in result.reasons)


def test_same_family_judge_and_builder_is_hard_error(worktree):
    with pytest.raises(GateError, match="differ"):
        gate(str(worktree), ITEM, spec(), "judge", "build",
             config(judge_family="openai", builder_family="openai"))


def test_unknown_family_is_hard_error(worktree):
    cfg = config()
    del cfg["roles"]["build"]["family"]
    with pytest.raises(GateError, match="family"):
        gate(str(worktree), ITEM, spec(), "judge", "build", cfg)


def test_family_inferred_from_model_markers(worktree):
    stage(worktree)
    cfg = {"roles": {
        "build": {"backend": "openrouter", "model": "openai/gpt-5"},
        "judge": {"backend": "command",
                  "argv": ["sh", "-c", f"echo '{judge_json([])}' # claude-opus-4-8"]},
    }}
    result = gate(str(worktree), ITEM, spec(), "judge", "build", cfg)
    assert not result.passed  # empty verdicts → both criteria unaddressed
    assert len(result.reasons) == 2


def test_unparseable_judge_output_blocks(worktree):
    stage(worktree)
    result = gate(str(worktree), ITEM, spec(), "judge", "build",
                  config("echo not-json"))
    assert not result.passed
    assert result.reasons == ["judge output unparseable"]


def test_judge_json_extracted_from_surrounding_prose(worktree):
    stage(worktree)
    wrapped = "Here is my verdict:\n" + judge_json([
        {"criterion": 1, "met": True, "evidence": "a"},
        {"criterion": 2, "met": True, "evidence": "b"},
    ]) + "\nDone."
    result = gate(str(worktree), ITEM, spec(), "judge", "build",
                  config(f"printf '%s' '{wrapped}'"))
    assert result.passed
