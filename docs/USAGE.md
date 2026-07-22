# Nightcrew usage

The full command and configuration reference. The [README](../README.md) covers the quick start; this file covers everything else.

## Commands

All commands accept `--fleet` (path to the fleet file, default `fleet.json`) and, where noted, `--log` (path to the SQLite build log, default `nightcrew.db`).

### `nightcrew run`

Runs one full pass over the fleet: backfill the outcomes of previously opened PRs via `gh pr view`, then for each enabled repo in priority order, pick the first ready spec item, plan a brief, dispatch the builder into an isolated git worktree, gate the result, attempt at most one fix dispatch on a gate block, and open a PR only if the gate passes.

```sh
uv run nightcrew run --fleet fleet.json --log nightcrew.db
```

Flags: `--fleet`, `--log`. Exit code is 0 only when every outcome is `pr-opened` or `skipped`.

### `nightcrew enroll <repo_path>`

Validates the repo's `nightcrew.yaml`, then runs its `test_cmd` live and refuses enrollment (exit 2, with the output tail) if it exits nonzero — a repo with no working tests cannot be gated, so it cannot be enrolled. On success the repo is added to (or updated in) the fleet file without clobbering existing `trust`, `priority`, or unknown keys.

```sh
uv run nightcrew enroll ~/code/my-repo --priority 1
```

Flags: `--fleet`, `--github owner/repo` (inferred from the origin remote when omitted), `--name` (defaults to the directory name), `--priority` (default 100). New entries default to `trust: propose_only` and `max_items_per_run: 1`.

### `nightcrew status`

Prints per-repo outcome tallies, total recorded cost, and a summary of the last run, read from the build log.

```sh
uv run nightcrew status
```

Flags: `--fleet`, `--log`.

### `nightcrew digest`

Prints the item records of the last N runs (gate criteria met/total, cost, PR URLs) plus a list of PRs still awaiting review.

```sh
uv run nightcrew digest --runs 3
```

Flags: `--fleet`, `--log`, `--runs` (default 1).

## Per-repo spec: `nightcrew.yaml`

```yaml
config:
  test_cmd: "python -m pytest -q"   # required; run by enroll and re-run by the gate
  off_limits: ["docs/**"]           # optional; paths the builder may not touch
  conventions: "Plain Python."      # optional; prose passed into the build brief

items:
  - id: my-feature                  # required, unique
    description: >                  # what to build
      ...
    acceptance_criteria:            # the gate judges each one against the diff
      - "..."
    deps: []                        # item ids that must be done first
```

Items need at least 2 acceptance criteria of at least 15 characters each, or they are marked underspecified and skipped with a logged reason. An item with an open or merged PR on its branch (`nightcrew/<id>`) is not re-picked.

## Fleet file: `fleet.json`

See `examples/fleet.portable.json` for a complete portable example.

- `repos[]` — `name`, `github` (`owner/repo`), `path` (local checkout, required at run time), `enabled` (default true), `priority` (lower runs first, default 100), `trust` (only `propose_only` today), `max_items_per_run` (default 1).
- `dispatch.roles.<role>` — either `{"backend": "command", "argv": [...]}` with `{brief_text}` or `{brief_path}` placeholders, or `{"backend": "openrouter", "model": "..."}` (needs `OPENROUTER_API_KEY`). An explicit `"family"` key overrides model-family inference; the gate refuses to run when the judge and builder families are equal or unknown.
- `caps` — `daily_usd` (UTC-day sum), `per_run_usd`, `max_items` (attempted items per run), and an optional `usage` check (`{"argv": [...], "max_used_percent": N}`) for subscription backends. A tripped cap logs `outcome=capped` and stops the run at the item boundary.

The roles Nightcrew dispatches are `foreman-build` (build and fix) and `nightcrew-judge` (the gate's evidence judge).

## What a run touches on disk

- **The build log** — a SQLite file at `--log` (default `./nightcrew.db`), tables `runs`, `item_records`, `review_records`. No other state is kept.
- **Temporary worktrees** — each build runs in a `git worktree` under a `nightcrew-wt-*` temp directory on branch `nightcrew/<item-id>`, removed after the item completes. A crash during dispatch can leave a worktree behind; `git worktree prune` plus deleting the temp directory cleans it up.
- **The fleet file** — rewritten in place by `enroll`.
- **Your repo's remote** — a passing gate pushes branch `nightcrew/<item-id>` and opens a PR with `gh pr create`. Nightcrew never merges.
- **Brief temp files** — `nightcrew-brief-*.json` files, deleted after each dispatch.

There is no installer: no shell-rc edits, no PATH changes, no files outside the paths above. To uninstall, delete the clone, the build log, and any leftover worktree temp directories.

## Scheduling

`nightcrew run` is one-shot by design; scheduling belongs to the host. `examples/scheduling.md` walks through the three reference setups (GitHub Actions via `examples/nightly.yml`, a cron line, and a systemd user timer).
