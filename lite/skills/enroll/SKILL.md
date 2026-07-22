---
name: nightcrew-enroll
description: >
  Use to enroll the current repo into Nightcrew: verify the repo has a real
  test suite (refuse if not), scaffold nightcrew.yaml, and offer a scheduling
  recipe. Triggers on "/nightcrew-enroll", "enroll this repo in nightcrew",
  or "set up nightcrew here".
---

# Nightcrew Enroll — put a repo on the night crew

You are enrolling the current repo checkout. The contract you scaffold is
`nightcrew.yaml` at the repo root (config header + spec items). The gate
script ships with this plugin at `<plugin root>/gate.py` (two directories up
from this file).

Hard rules:
- **No tests, no enrollment.** The gate re-runs the suite independently; a
  repo without one cannot be verified. Refuse — do not scaffold, do not
  invent a placeholder `test_cmd`.
- Never commit secrets. Never modify anything besides `nightcrew.yaml`.
- If `nightcrew.yaml` already exists, validate it instead of overwriting.

## Steps

### 1. Check for a test suite
Find how this repo runs its tests: look for test files (`tests/`, `test_*`,
`*_test.*`, `*.spec.*`) AND a runnable command (pytest/pyproject config,
`package.json` `scripts.test`, `cargo test`, `go test ./...`, Makefile
target, CI workflow). Run the candidate command; it must execute at least
one real test and exit 0.

- No test files, or the command runs zero tests ⇒ **REFUSE**: report
  "Nightcrew requires a test suite — the verification gate re-runs it on
  every build. Add tests, then re-enroll." Stop here.
- Suite exists but is red ⇒ refuse too, with the failure output: enrollment
  on a red baseline would block every future run.

### 2. Scaffold nightcrew.yaml
If `nightcrew.yaml` already exists: run `python3 <plugin root>/gate.py spec`,
report the result, and skip to step 4.

Otherwise write `nightcrew.yaml` at the repo root:

```yaml
config:
  test_cmd: "<the verified command from step 1>"
  off_limits: []          # paths the builder must not touch, e.g. [".github/workflows/"]
  conventions: "<one or two sentences from README/CONTRIBUTING, or ask the user>"

items:
  - id: <kebab-case-id>
    description: >
      <one buildable unit of work, described concretely>
    acceptance_criteria:
      - "<concrete, evidence-citable criterion>"
      - "<pytest/tests cover it and the full suite passes>"
    deps: []
```

Draft the first item WITH the user — ask what they want built first, then
write >=2 concrete criteria for it. If they have nothing yet, leave `items:
[]` and say runs will no-op until an item is added.

### 3. Validate
Run `python3 <plugin root>/gate.py spec`. Every item must report `ok`;
fix underspecified items (add/sharpen criteria) before finishing.

### 4. Offer scheduling
Ask which the user wants (or none — `/nightcrew-run` works manually):

- **Cloud routine (recommended):** use `/schedule` to create a nightly
  routine in this repo whose prompt is: "Run the nightcrew-run skill."
  Private repos need the Claude GitHub app installed.
- **Local cron:** offer this line (adjust path/schedule):
  `0 2 * * * cd <repo path> && claude -p "Run the nightcrew-run skill" --dangerously-skip-permissions`

## Report
End with: test command verified (or refusal reason), spec validation result,
and the chosen scheduling setup.
