"""SQLite build log (BP3, ADR-19): run + per-item record, mutable outcome."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    cost_usd REAL
);
CREATE TABLE IF NOT EXISTS item_records (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    repo TEXT NOT NULL,
    item_id TEXT NOT NULL,
    plan TEXT,
    models TEXT,            -- json: {stage: model/role}
    gate TEXT,              -- json: [{criterion, evidence, verdict}]
    cost_usd REAL,
    pr_url TEXT,
    skip_reason TEXT,
    outcome TEXT            -- mutable: merged / closed / pending / …
);
CREATE TABLE IF NOT EXISTS review_records (
    id TEXT PRIMARY KEY,    -- record["id"]
    created TEXT NOT NULL,
    record TEXT NOT NULL    -- full ADR-17 json
);
"""


class BuildLog:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.row_factory = sqlite3.Row

    def start_run(self) -> int:
        cur = self.db.execute("INSERT INTO runs (started) VALUES (?)", (_now(),))
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, cost_usd: float | None = None) -> None:
        self.db.execute(
            "UPDATE runs SET finished = ?, cost_usd = ? WHERE id = ?",
            (_now(), cost_usd, run_id),
        )
        self.db.commit()

    def record_item(self, run_id: int, repo: str, item_id: str, *,
                    plan: str | None = None, models: dict | None = None,
                    gate: list | None = None, cost_usd: float | None = None,
                    pr_url: str | None = None, skip_reason: str | None = None,
                    outcome: str = "pending") -> int:
        cur = self.db.execute(
            "INSERT INTO item_records (run_id, repo, item_id, plan, models, gate,"
            " cost_usd, pr_url, skip_reason, outcome) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, repo, item_id, plan,
             json.dumps(models) if models else None,
             json.dumps(gate) if gate else None,
             cost_usd, pr_url, skip_reason, outcome),
        )
        self.db.commit()
        return cur.lastrowid

    def set_outcome(self, record_id: int, outcome: str) -> None:
        self.db.execute(
            "UPDATE item_records SET outcome = ? WHERE id = ?", (outcome, record_id)
        )
        self.db.commit()

    def record_review(self, record: dict) -> None:
        """Default review-record sink (ADR-17)."""
        self.db.execute(
            "INSERT INTO review_records (id, created, record) VALUES (?,?,?)",
            (record["id"], _now(), json.dumps(record)),
        )
        self.db.commit()

    def item_ids_with(self, repo: str, outcomes: tuple[str, ...]) -> set[str]:
        rows = self.db.execute(
            "SELECT DISTINCT item_id, outcome FROM item_records WHERE repo = ?",
            (repo,),
        )
        return {r["item_id"] for r in rows if r["outcome"] in outcomes}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
