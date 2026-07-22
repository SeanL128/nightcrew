import pytest

from nightcrew.config import Item
from nightcrew.dispatch import DispatchError, dispatch
from nightcrew.picker import pick


def item(item_id, criteria=None, deps=None):
    return Item(item_id, item_id, criteria or ["criterion is sufficiently long", "another criterion passes"], deps or [])


def test_pick_returns_first_ready_item_in_order():
    items = [item("first"), item("second")]

    selected, skips = pick(items, done=set(), open_prs=set())

    assert selected is items[0]
    assert skips == []


def test_pick_reports_underspecified_items_before_selected_item():
    items = [item("thin", ["too short"]), item("done"), item("blocked", deps=["missing"]), item("ready")]

    selected, skips = pick(items, done={"done"}, open_prs=set())

    assert selected is items[3]
    assert skips == [(items[0], "underspecified")]


def test_pick_returns_all_underspecified_items_when_nothing_ready():
    items = [item("thin", ["too short"]), item("open"), item("also-thin", ["short"])]

    selected, skips = pick(items, done=set(), open_prs={"open"})

    assert selected is None
    assert skips == [(items[0], "underspecified"), (items[2], "underspecified")]


@pytest.mark.parametrize("value", ["--model claude-fable-5", "Mythos-Preview"])
def test_dispatch_rejects_banned_terms_in_nested_selected_role_config(value):
    config = {"roles": {"build": {"backend": "command", "argv": ["true"], "nested": {"value": value}}}}

    with pytest.raises(DispatchError, match="banned"):
        dispatch("build", {}, config)


def test_dispatch_accepts_clean_role_config():
    config = {"roles": {"build": {"backend": "command", "argv": ["true"]}}}

    assert dispatch("build", {}, config).text == ""
