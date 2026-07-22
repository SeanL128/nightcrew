"""Pick the first buildable spec item (BP4)."""

from .config import Item
from .spec import item_status


def pick(items: list[Item], done: set[str], open_prs: set[str]) -> tuple[Item | None, list[tuple[Item, str]]]:
    skips = []
    for item in items:
        status = item_status(item, done, open_prs)
        if status == "ready":
            return item, skips
        if status == "underspecified":
            skips.append((item, status))
    return None, skips
