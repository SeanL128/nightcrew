"""CLI: ``nightcrew run`` (ADR-16 one-shot; enroll/status/digest are next)."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import ConfigError, load_fleet, load_repo_spec
from .log import BuildLog
from .runner import run


OUTCOMES = ("pending", "merged", "closed", "blocked", "build-error", "skipped", "capped")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nightcrew")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="one pass over the fleet: pick→plan→build→gate→PR")
    p_run.add_argument("--fleet", default="fleet.json", type=Path)
    p_run.add_argument("--log", default="nightcrew.db", type=Path,
                       help="SQLite build log path")
    p_enroll = sub.add_parser("enroll", help="validate and add a repository to the fleet")
    p_enroll.add_argument("repo_path", type=Path)
    p_enroll.add_argument("--fleet", default="fleet.json", type=Path)
    p_enroll.add_argument("--github")
    p_enroll.add_argument("--name")
    p_enroll.add_argument("--priority", type=int)
    for command in ("status", "digest"):
        report = sub.add_parser(command, help=f"show {command} report")
        report.add_argument("--fleet", default="fleet.json", type=Path)
        report.add_argument("--log", default="nightcrew.db", type=Path)
        if command == "digest":
            report.add_argument("--runs", type=int, default=1)
    args = parser.parse_args(argv)

    if args.command == "enroll":
        return enroll(args)
    try:
        fleet = load_fleet(args.fleet)
    except ConfigError as e:
        print(f"nightcrew: {e}", file=sys.stderr)
        return 2
    if args.command == "status":
        status(fleet, BuildLog(args.log))
        return 0
    if args.command == "digest":
        digest(BuildLog(args.log), args.runs)
        return 0
    outcomes = run(fleet, BuildLog(args.log))
    for o in outcomes:
        line = f"{o.repo}/{o.item_id}: {o.status}"
        if o.pr_url:
            line += f" {o.pr_url}"
        if o.reasons:
            line += " — " + "; ".join(o.reasons)
        print(line)
    return 0 if all(o.status in ("pr-opened", "skipped") for o in outcomes) else 1


def enroll(args) -> int:
    repo = args.repo_path.resolve()
    try:
        spec = load_repo_spec(repo)
    except ConfigError as e:
        print(f"nightcrew: enrollment refused: {e}", file=sys.stderr)
        return 2
    checked = subprocess.run(spec.test_cmd, cwd=repo, shell=True, capture_output=True, text=True)
    if checked.returncode:
        output = (checked.stdout or "") + (checked.stderr or "")
        print(f"nightcrew: enrollment refused: test_cmd failed ({checked.returncode})", file=sys.stderr)
        print("\n".join(output.rstrip().splitlines()[-20:]), file=sys.stderr)
        return 2
    github = args.github or github_origin(repo)
    if not github:
        print("nightcrew: enrollment refused: supply --github OWNER/REPO", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.fleet.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"nightcrew: enrollment refused: cannot read fleet: {e}", file=sys.stderr)
        return 2
    name = args.name or repo.name
    entry = next((item for item in data.get("repos", []) if item.get("name") == name), None)
    values = {"name": name, "github": github, "path": str(repo), "enabled": True}
    if entry is None:
        entry = {**values, "trust": "propose_only", "priority": args.priority if args.priority is not None else 100,
                 "max_items_per_run": 1}
        data.setdefault("repos", []).append(entry)
    else:
        entry.update(values)
        if args.priority is not None:
            entry["priority"] = args.priority
    args.fleet.write_text(json.dumps(data, indent=2) + "\n")
    print(f"enrolled {name}: {github}")
    return 0


def github_origin(repo: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                            capture_output=True, text=True)
    origin = result.stdout.strip()
    if result.returncode or "github.com" not in origin:
        return None
    path = origin.split("github.com", 1)[1].lstrip(":/").removesuffix(".git")
    return path if len(path.split("/")) == 2 else None


def status(fleet, log: BuildLog) -> None:
    for repo in fleet.repos:
        rows = log.db.execute("SELECT outcome, COUNT(*) count FROM item_records WHERE repo = ? GROUP BY outcome",
                              (repo.name,)).fetchall()
        counts = {row["outcome"]: row["count"] for row in rows}
        cost = log.db.execute("SELECT COALESCE(SUM(cost_usd), 0) cost FROM item_records WHERE repo = ?",
                              (repo.name,)).fetchone()["cost"]
        tallies = " ".join(f"{outcome}={counts.get(outcome, 0)}" for outcome in OUTCOMES)
        print(f"{repo.name}: enabled={repo.enabled} priority={repo.priority} {tallies} cost_usd={cost:.2f}")
    last = log.db.execute("SELECT started, finished, cost_usd FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    print("last run: none" if last is None else
          f"last run: started={last['started']} finished={last['finished']} cost_usd={last['cost_usd'] or 0:.2f}")


def digest(log: BuildLog, runs: int) -> None:
    run_rows = log.db.execute("SELECT id FROM runs ORDER BY id DESC LIMIT ?", (runs,)).fetchall()
    for run in reversed(run_rows):
        for item in log.db.execute("SELECT * FROM item_records WHERE run_id = ? ORDER BY id", (run["id"],)):
            line = f"{item['repo']}/{item['item_id']}: {item['outcome']} cost_usd={item['cost_usd'] or 0:.2f}"
            if item["pr_url"]:
                line += f" {item['pr_url']}"
            if item["skip_reason"]:
                line += f" — {item['skip_reason']}"
            if item["gate"]:
                gate = json.loads(item["gate"])
                line += f" gate={sum(bool(c.get('met')) for c in gate)}/{len(gate)}"
            print(line)
    print("PRs awaiting review:")
    for item in log.db.execute("SELECT repo, item_id, pr_url FROM item_records WHERE outcome = 'pending' AND pr_url IS NOT NULL"):
        print(f"{item['repo']}/{item['item_id']}: {item['pr_url']}")


if __name__ == "__main__":
    sys.exit(main())
