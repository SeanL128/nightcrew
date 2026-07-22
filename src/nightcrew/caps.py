"""Run-global spending and router-usage caps."""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Caps:
    daily_usd: float | None = None
    per_run_usd: float | None = None
    max_items: int | None = None
    usage: dict | None = None


def check(caps: Caps, log, run_id: int, usage_argv=None) -> str | None:
    today = datetime.now(timezone.utc).date().isoformat()
    daily = log.db.execute(
        "SELECT SUM(item_records.cost_usd) AS total FROM item_records"
        " JOIN runs ON runs.id = item_records.run_id WHERE date(runs.started) = ?",
        (today,),
    ).fetchone()["total"] or 0
    if caps.daily_usd is not None and daily >= caps.daily_usd:
        return f"daily cost cap reached (${daily:.2f} / ${caps.daily_usd:.2f})"

    run_cost = log.db.execute(
        "SELECT SUM(cost_usd) AS total FROM item_records WHERE run_id = ?", (run_id,)
    ).fetchone()["total"] or 0
    if caps.per_run_usd is not None and run_cost >= caps.per_run_usd:
        return f"per-run cost cap reached (${run_cost:.2f} / ${caps.per_run_usd:.2f})"

    attempted = log.db.execute(
        "SELECT COUNT(*) AS total FROM item_records"
        " WHERE run_id = ? AND outcome != 'skipped'", (run_id,)
    ).fetchone()["total"]
    if caps.max_items is not None and attempted >= caps.max_items:
        return f"item cap reached ({attempted} / {caps.max_items})"

    if not caps.usage:
        return None
    argv = usage_argv or caps.usage.get("argv")
    threshold = caps.usage.get("max_used_percent")
    if not argv or threshold is None:
        return None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout) if not result.returncode else None
        loads = [
            max(window["usedPercent"] for window in vendor.get("windows", [])
                if isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float)))
            for vendor in data.values()
            if isinstance(data, dict) and isinstance(vendor, dict)
            and any(isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float))
                    for window in vendor.get("windows", []))
        ] if isinstance(data, dict) else []
    except (OSError, TypeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
        # ponytail: fail open on status errors; dollar caps bound metered runs until status is reliable.
        return None
    if loads and all(load >= threshold for load in loads):
        return f"usage cap reached (all vendors >= {threshold}%)"
    return None
