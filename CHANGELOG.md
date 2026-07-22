# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-22

### Added

- Full pipeline: picker → planner → builder → gate → fix loop → PR, run per enrolled repo by `nightcrew run`.
- Hybrid verification gate: independent `test_cmd` re-run, tamper check blocking removed or weakened tests, and a per-criterion evidence judge whose model family must differ from the builder's.
- Pluggable dispatch seam: command-template backends (`claude -p`, `codex exec`, `alloyd`, any CLI) and an OpenRouter backend, selected per role in `fleet.json`.
- Fleet CLI: `enroll` (runs the repo's tests live and refuses failures), `status`, and `digest` over a SQLite build log.
- Run caps: `daily_usd`, `per_run_usd`, `max_items`, and an optional subscription-usage check, enforced at the item boundary.
- Evidence-table PR bodies with run cost; PRs are opened, never auto-merged.
- Portable scheduling recipes under `examples/`: GitHub Actions nightly workflow, cron, and a systemd user timer.
