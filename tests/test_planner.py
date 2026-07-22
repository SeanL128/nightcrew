from nightcrew.config import Item, RepoSpec
from nightcrew.planner import plan


def test_plan_builds_alloyd_brief_with_conditional_constraints():
    item = Item("phase-c", "build the planner", ["returns the brief", "has no I/O"])
    spec = RepoSpec("uv run pytest", ["docs/", "deploy/"], "Use pure functions.", [item])

    brief = plan(item, spec)

    assert set(brief) == {"goal", "files", "constraints", "acceptance"}
    assert isinstance(brief["goal"], str)
    assert isinstance(brief["files"], list)
    assert isinstance(brief["constraints"], str)
    assert isinstance(brief["acceptance"], str)
    assert "[phase-c] build the planner" in brief["goal"]
    assert "uv run pytest" in brief["goal"]
    assert "Do NOT commit; leave changes in the working tree." in brief["goal"]
    assert brief["files"] == []
    assert brief["constraints"] == (
        "Use pure functions.\n"
        "Off limits (do not modify): docs/, deploy/\n"
        "Do NOT commit; leave changes in the working tree.\n"
        "Never weaken or remove existing tests."
    )
    assert brief["acceptance"] == (
        "1. returns the brief\n"
        "2. has no I/O\n"
        "3. Full test suite passes: uv run pytest"
    )


def test_plan_omits_empty_optional_constraints():
    item = Item("id", "description", [])
    spec = RepoSpec("pytest", [], "", [item])

    assert plan(item, spec)["constraints"] == (
        "Do NOT commit; leave changes in the working tree.\n"
        "Never weaken or remove existing tests."
    )
