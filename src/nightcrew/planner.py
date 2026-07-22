"""Compose a foreman dispatch brief from a spec item."""

from .config import Item, RepoSpec


def plan(item: Item, spec: RepoSpec) -> dict:
    goal = (
        f"[{item.id}] {item.description}\n\n"
        "Implement this in the repo at the current working directory. "
        "Write or extend tests proving each acceptance criterion, then run: "
        f"{spec.test_cmd}. Do NOT commit; leave changes in the working tree."
    )
    constraints = []
    if spec.conventions:
        constraints.append(spec.conventions)
    if spec.off_limits:
        constraints.append("Off limits (do not modify): " + ", ".join(spec.off_limits))
    constraints.extend([
        "Do NOT commit; leave changes in the working tree.",
        "Never weaken or remove existing tests.",
    ])
    acceptance = [
        *(f"{number}. {criterion}" for number, criterion in enumerate(item.acceptance_criteria, 1)),
        f"{len(item.acceptance_criteria) + 1}. Full test suite passes: {spec.test_cmd}",
    ]
    # ponytail: no file hints until the YAML contract grows them; add then.
    return {
        "goal": goal,
        "files": [],
        "constraints": "\n".join(constraints),
        "acceptance": "\n".join(acceptance),
    }
