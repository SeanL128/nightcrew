# Scheduling recipes

Nightcrew is one-shot (`nightcrew run`); scheduling is host-provided (ADR-16).
Three recipes, pick one. All assume `examples/fleet.portable.json` copied to
`fleet.json` and edited: repo entries, and a judge model from a **different
model family** than the builder (the gate enforces judge ≠ builder, ADR-7 —
that's why the portable default pairs `claude -p` with an OpenRouter model).

## 1. GitHub Actions (zero-infra reference)

Copy `examples/nightly.yml` to `.github/workflows/`, set secrets
`CLAUDE_CODE_OAUTH_TOKEN`, `OPENROUTER_API_KEY`, `GH_PAT`. The workflow checks
out each enrolled repo at its fleet.json `path` and uploads `nightcrew.db` as
an artifact.

## 2. cron

```cron
0 2 * * * cd /path/to/nightcrew && uv run nightcrew run --fleet fleet.json --log nightcrew.db >> nightcrew-cron.log 2>&1
```

Put `CLAUDE_CODE_OAUTH_TOKEN` / `OPENROUTER_API_KEY` in the crontab
environment or a wrapper script — never in the repo.

## 3. systemd user timer

Use the units in `deploy/nightcrew.{service,timer}` (oneshot at 02:00,
`Persistent=true`, secrets via an `EnvironmentFile=.env`):

```sh
systemctl --user link $PWD/deploy/nightcrew.service $PWD/deploy/nightcrew.timer
systemctl --user enable --now nightcrew.timer
loginctl enable-linger $USER   # keeps the timer alive without a login session
```
