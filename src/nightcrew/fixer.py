"""Fix loop (foreman max-2 rule): one fix dispatch after a gate block.

The caller drives attempt 1 (build → gate); on a block it calls
``fix_and_regate`` exactly once, then stops and logs whatever came back.
No retries beyond that — foreman's initial-plus-one-fix rule.
"""

from dataclasses import dataclass, field

from .builder import dispatch_and_stage
from .config import Item, RepoSpec
from .gate import GateResult, gate


@dataclass
class FixResult:
    gate: GateResult
    diff: str
    cost_usd: float | None = None
    usage: dict = field(default_factory=dict)


def fix_brief(brief: dict, reasons: list[str]) -> dict:
    goal = (
        brief["goal"]
        + "\n\nA previous attempt at this item was BLOCKED by the verification "
        "gate for the reasons below. Fix these and only these, keeping the "
        "existing changes in the working tree:\n"
        + "\n".join(f"- {r}" for r in reasons)
    )
    return {**brief, "goal": goal}


def fix_and_regate(worktree: str, item: Item, spec: RepoSpec, brief: dict,
                   blocked: GateResult, builder_role: str, judge_role: str,
                   dispatch_config: dict) -> FixResult:
    diff, result = dispatch_and_stage(
        worktree, fix_brief(brief, blocked.reasons), builder_role,
        dispatch_config, spec.off_limits,
    )
    regated = gate(worktree, item, spec, judge_role, builder_role, dispatch_config)
    return FixResult(regated, diff, result.cost_usd, result.usage)
