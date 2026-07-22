"""Spec loader (BP2): derive per-item status from the spec + build-log state.

Statuses: ready | underspecified | blocked-by-deps | has-open-pr | done.
Underspecified = criteria too thin for the gate to cite evidence (ADR-5) —
thresholds shared with lite/gate.py.
"""

from .config import Item

MIN_CRITERIA = 2
MIN_CRITERION_LEN = 15


def item_status(item: Item, done: set[str], open_prs: set[str]) -> str:
    if item.id in done:
        return "done"
    if item.id in open_prs:
        return "has-open-pr"
    crits = item.acceptance_criteria
    if len(crits) < MIN_CRITERIA or any(len(c.strip()) < MIN_CRITERION_LEN for c in crits):
        return "underspecified"
    if not set(item.deps) <= done:
        return "blocked-by-deps"
    return "ready"


def statuses(items: list[Item], done: set[str], open_prs: set[str]) -> dict[str, str]:
    return {i.id: item_status(i, done, open_prs) for i in items}
