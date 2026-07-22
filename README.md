<div align="center">

<img src="docs/banner.svg" alt="nightcrew" width="440" />

**A spec-to-PR build agent where no PR ships unverified.**

![version](https://img.shields.io/badge/version-0.1.0-blue?style=flat-square) ![license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

[Learn more →](https://seanlindsay.xyz/nightcrew) · [Install](#quick-start) · [Roadmap](#roadmap)

</div>

## Why

I built Nightcrew because I wanted an autonomous agent that could build from my backlogs overnight without me having to trust its word that the work is done. Coding agents are happy to open a pull request and declare success, and I found that checking those claims by hand costs almost as much as writing the code myself. Nightcrew hard-blocks every pull request behind a verification gate that re-runs the tests independently, checks that the builder didn't weaken them, and makes a judge from a different model family cite concrete evidence for every acceptance criterion, so the PR that lands in front of me carries its own proof.

## Features

- **Verification gate** — an independent test re-run, a tamper check that blocks removed or weakened tests, and an evidence judge that maps each acceptance criterion to concrete evidence in the diff before any PR can open.
- **Judge never shares a family with the builder** — the gate refuses to run if the judge and builder resolve to the same model family, so the builder can't grade its own homework.
- **Pluggable dispatch seam** — builder and judge are config-selected command templates (`claude -p`, `codex exec`, any CLI) or OpenRouter calls, with no vendored SDK.
- **Spec as the contract** — each repo carries a `nightcrew.yaml` of items with acceptance criteria; underspecified items are skipped and logged rather than guessed at.
- **Evidence-table PRs, never auto-merged** — the PR body is a criterion-by-criterion evidence table with the run cost, and merging is always left to a human.
- **Caps and a build log** — every run is recorded to SQLite, and daily or per-run dollar caps stop the run cleanly at the item boundary.

## Quick start

```sh
git clone https://github.com/SeanL128/nightcrew && cd nightcrew && uv sync
uv run nightcrew enroll /path/to/your/repo
uv run nightcrew run
```

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), git, an authenticated [gh](https://cli.github.com/) CLI, and at least one dispatch backend (the `claude` or `codex` CLI, or an `OPENROUTER_API_KEY`).

## Configuration

| Option | What it does | Default |
|--------|--------------|---------|
| `nightcrew.yaml` → `config.test_cmd` | The repo's test command; enrollment runs it live and refuses repos where it fails, and the gate re-runs it on every build | required |
| `nightcrew.yaml` → `items[]` | Spec items with `id`, `description`, `acceptance_criteria`, `deps` | required |
| `fleet.json` → `repos[]` | Enrolled repos with `path`, `priority`, `trust`, `max_items_per_run` | required |
| `fleet.json` → `dispatch.roles` | Per-role backend: a command template or an OpenRouter model, with an optional explicit `family` | `{}` |
| `fleet.json` → `caps` | `daily_usd`, `per_run_usd`, `max_items` run limits | none |

More in [docs/USAGE.md](docs/USAGE.md).

## Roadmap

- [x] Full pipeline: pick → plan → build → gate → fix → PR
- [x] Hybrid gate: independent test re-run, tamper check, cross-family evidence judge
- [x] Fleet CLI: `enroll` / `run` / `status` / `digest` with a SQLite build log and dollar caps
- [x] Portable scheduling recipes: GitHub Actions, cron, systemd (see `examples/`)
- [ ] First public release (v0.1.0)
- [ ] Value learning and a trust ratchet, gated on real outcome data; PRs stay propose-only until then

## License

[MIT](LICENSE)

---

<div align="center">

Built by Sean Lindsay · [seanlindsay.xyz](https://seanlindsay.xyz)

</div>
