"""Orchestrator (BP9): backfill PR outcomes, then pick→plan→build→gate→PR.

One-shot (ADR-16). Per enabled repo (priority order) it loops until
``max_items_per_run`` or no ready item remains; caps beyond the item count
are Phase D's next item and slot in at the same boundary. The orchestrator
owns worktree cleanup — the builder deliberately leaves it to us.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import builder, fixer, gate as gate_mod, planner, pr as pr_mod
from .caps import check as check_caps
from .config import Fleet, Repo, load_repo_spec
from .log import BuildLog
from .picker import pick

BUILDER_ROLE = "foreman-build"
JUDGE_ROLE = "nightcrew-judge"


@dataclass
class ItemOutcome:
    repo: str
    item_id: str
    status: str  # pr-opened | blocked | build-error | skipped
    pr_url: str | None = None
    reasons: list[str] = field(default_factory=list)


def backfill_outcomes(log: BuildLog, gh_argv=("gh",)) -> None:
    """Resolve pending PR outcomes via ``gh pr view`` before picking."""
    rows = log.db.execute(
        "SELECT id, pr_url FROM item_records"
        " WHERE outcome = 'pending' AND pr_url IS NOT NULL"
    ).fetchall()
    for row in rows:
        r = subprocess.run(
            [*gh_argv, "pr", "view", row["pr_url"], "--json", "state"],
            capture_output=True, text=True,
        )
        if r.returncode:
            continue  # transient gh failure — stays pending
        state = (json.loads(r.stdout).get("state") or "").upper()
        if state == "MERGED":
            log.set_outcome(row["id"], "merged")
        elif state == "CLOSED":
            log.set_outcome(row["id"], "closed")


def run(fleet: Fleet, log: BuildLog, gh_argv=("gh",), usage_argv=None) -> list[ItemOutcome]:
    backfill_outcomes(log, gh_argv)
    run_id = log.start_run()
    outcomes = []
    try:
        for repo in sorted(fleet.repos, key=lambda r: r.priority):
            if not repo.enabled:
                continue
            repo_outcomes = run_repo(repo, fleet.dispatch, log, run_id, gh_argv,
                                     fleet.caps, usage_argv)
            outcomes += repo_outcomes
            if repo_outcomes and repo_outcomes[-1].status == "capped":
                break
    finally:
        log.finish_run(run_id, _total_cost(log, run_id))
    return outcomes


def run_repo(repo: Repo, dispatch_config: dict, log: BuildLog, run_id: int,
             gh_argv=("gh",), caps=None, usage_argv=None) -> list[ItemOutcome]:
    if not repo.path or not Path(repo.path).is_dir():
        log.record_item(run_id, repo.name, "-", skip_reason="no local checkout path",
                        outcome="skipped")
        return [ItemOutcome(repo.name, "-", "skipped", reasons=["no local checkout path"])]
    outcomes = []
    open_prs = {
        r["item_id"] for r in log.db.execute(
            "SELECT item_id FROM item_records WHERE repo = ?"
            " AND outcome = 'pending' AND pr_url IS NOT NULL", (repo.name,))
    }
    try:
        result = subprocess.run(
            [*gh_argv, "pr", "list", "--repo", repo.github, "--state", "open",
             "--json", "headRefName"], capture_output=True, text=True,
        )
        if not result.returncode:
            for pr in json.loads(result.stdout):
                branch = pr.get("headRefName", "")
                if branch.startswith("nightcrew/"):
                    open_prs.add(branch.removeprefix("nightcrew/"))
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    for _ in range(repo.max_items_per_run):
        reason = check_caps(caps, log, run_id, usage_argv) if caps else None
        if reason:
            log.record_item(run_id, repo.name, "-", skip_reason=reason, outcome="capped")
            outcomes.append(ItemOutcome(repo.name, "-", "capped", reasons=[reason]))
            break
        spec = load_repo_spec(Path(repo.path))
        done = log.item_ids_with(repo.name, ("merged", "done"))
        item, skips = pick(spec.items, done, open_prs)
        for skipped, reason in skips:
            log.record_item(run_id, repo.name, skipped.id,
                            skip_reason=reason, outcome="skipped")
        if item is None:
            break
        outcome = _run_item(repo, item, spec, dispatch_config, log, run_id, gh_argv)
        outcomes.append(outcome)
        if outcome.status == "pr-opened":
            open_prs.add(item.id)  # open_prs is prefetched; keep the new PR out of re-picks
    return outcomes


def _run_item(repo: Repo, item, spec, dispatch_config: dict, log: BuildLog,
              run_id: int, gh_argv) -> ItemOutcome:
    brief = planner.plan(item, spec)
    models = {"builder": BUILDER_ROLE, "judge": JUDGE_ROLE}
    try:
        built = builder.build(repo.path, item.id, brief, BUILDER_ROLE,
                              dispatch_config, spec.off_limits)
    except builder.BuildError as e:
        log.record_item(run_id, repo.name, item.id, plan=json.dumps(brief),
                        models=models, skip_reason=str(e), outcome="build-error")
        return ItemOutcome(repo.name, item.id, "build-error", reasons=[str(e)])

    cost = built.cost_usd
    gate_json = None
    try:
        result = gate_mod.gate(built.worktree, item, spec, JUDGE_ROLE,
                               BUILDER_ROLE, dispatch_config)
        cost = _add(cost, result.judge_cost_usd)
        if not result.passed:
            fixed = fixer.fix_and_regate(built.worktree, item, spec, brief,
                                         result, BUILDER_ROLE, JUDGE_ROLE,
                                         dispatch_config)
            cost = _add(_add(cost, fixed.cost_usd), fixed.gate.judge_cost_usd)
            result = fixed.gate

        gate_json = [{"criterion": v.criterion, "met": v.met, "evidence": v.evidence}
                     for v in result.verdicts]
        if not result.passed:
            log.record_item(run_id, repo.name, item.id, plan=json.dumps(brief),
                            models=models, gate=gate_json, cost_usd=cost,
                            skip_reason="; ".join(result.reasons), outcome="blocked")
            return ItemOutcome(repo.name, item.id, "blocked", reasons=result.reasons)

        url = pr_mod.open_pr(built.worktree, built.branch, item, result, cost,
                             gh_argv=gh_argv)
        record = pr_mod.review_record(item, repo.github, url,
                                      pr_mod.pr_body(item, result, cost))
        log.record_review(record)
        log.record_item(run_id, repo.name, item.id, plan=json.dumps(brief),
                        models=models, gate=gate_json, cost_usd=cost,
                        pr_url=url, outcome="pending")
        return ItemOutcome(repo.name, item.id, "pr-opened", pr_url=url)
    except (gate_mod.GateError, builder.BuildError, pr_mod.PRError) as e:
        log.record_item(run_id, repo.name, item.id, plan=json.dumps(brief),
                        models=models, gate=gate_json, cost_usd=cost, skip_reason=str(e),
                        outcome="build-error")
        return ItemOutcome(repo.name, item.id, "build-error", reasons=[str(e)])
    finally:
        _cleanup_worktree(repo.path, built.worktree, built.branch)


def _cleanup_worktree(repo_path: str, worktree: str, branch: str) -> None:
    subprocess.run(["git", "-C", repo_path, "worktree", "remove", "--force", worktree],
                   capture_output=True)
    shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(["git", "-C", repo_path, "branch", "-D", branch],
                   capture_output=True)  # pushed branches live on the remote


def _total_cost(log: BuildLog, run_id: int) -> float | None:
    row = log.db.execute(
        "SELECT SUM(cost_usd) AS total FROM item_records WHERE run_id = ?",
        (run_id,)).fetchone()
    return row["total"]


def _add(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)
