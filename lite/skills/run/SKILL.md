---
name: nightcrew-run
description: >
  Use to execute one Nightcrew build cycle in the current repo: pick the first
  ready item from nightcrew.yaml, implement it, verify it through the gate +
  judge, and open an evidence-cited PR. Triggers on "/nightcrew-run", "run
  nightcrew", or a scheduled Nightcrew routine prompt. One item per run.
---

# Nightcrew Run — one verified build cycle

You are the Nightcrew pipeline. Work in the current repo checkout. The
contract is `nightcrew.yaml` at the repo root (config header + spec items).
The gate script ships with this plugin at `<plugin root>/gate.py` (two
directories up from this file); call it as `python3 <plugin root>/gate.py`.

Hard rules — never break these:
- The gate and judge are HARD BLOCKS. No PR ships unverified.
- Never merge a PR. Never force-push. Never commit secrets.
- Never remove or weaken existing tests.
- Respect `config.off_limits` paths — do not modify them.
- One item per run. Stop after opening (or blocking) one PR.

## Pipeline

### 1. Backfill prior outcomes
Read `.nightcrew/log.jsonl` (create the dir/file if missing). For every past
`run` record whose `pr_url` has no later `outcome` record, check
`gh pr view <url> --json state,mergedAt,mergeCommit`:
merged → `merged_clean` (or `merged_revised` if commits were added after the
Nightcrew push), closed unmerged → `rejected`, open → leave pending. Append
one `{"type":"outcome","pr_url":...,"outcome":...,"ts":...}` line per
resolution.

### 2. Pick
Parse `nightcrew.yaml`. Walk `items` in file order; select the FIRST item
where all of:
- every id in `deps` has a merged PR (per the log/`gh pr list --state all`),
- no open or merged PR already exists for the item (branch `nightcrew/<id>`),
- it is well-specified: `python3 <plugin root>/gate.py spec` reports it `ok`.

Underspecified or dep-blocked items are skipped WITH a logged reason
(`{"type":"skip","item":id,"reason":...}`). If nothing is ready, log it,
report "no ready item", and stop.

### 3. Baseline
Run `config.test_cmd`. If the suite is red on the base branch, log
`{"type":"abort","reason":"red baseline"}` and stop — never build on red.

### 4. Plan + implement
Create branch `nightcrew/<id>` off the default branch. Write a short plan
mapping each acceptance criterion to the change that will satisfy it. Then
implement, including the tests the criteria demand. Follow
`config.conventions`. Re-run `test_cmd` until green.

### 5. Deterministic gate
Run `python3 <plugin root>/gate.py gate --base <default branch>` in the repo.
Nonzero exit ⇒ BLOCKED: log the reasons, do not push, stop. (Fix-and-retry is
allowed only if the fix doesn't weaken tests; at most 2 retries.)

### 6. Judge subagent (adversarial)
Dispatch a subagent (Agent tool, general-purpose) with ONLY this context: the
item's acceptance_criteria, the full `git diff <default>...HEAD`, and the
test-run output. Its prompt must instruct it to act as an adversarial
reviewer: for EACH criterion, either cite concrete evidence (file:line or
test name) that satisfies it, or declare it UNADDRESSED. It returns a JSON
verdict list `[{criterion, evidence, verdict: pass|fail}]`. ANY `fail` ⇒
BLOCKED: log the verdicts, do not push, stop (one fix-and-rejudge retry
allowed).

Optional second judge: if the user has configured a second-vendor API key
(e.g. `NIGHTCREW_JUDGE_CMD` env var), pipe the same context through it and
require both judges to pass.

### 7. Ship
Push the branch, then `gh pr create` against the default branch. PR body =
markdown table `| Acceptance criterion | Evidence |` from the judge's
verdicts, one row per criterion, plus a one-line summary. Never merge.

### 8. Log
Append the run record:
```json
{"type":"run","ts":"<iso8601>","item":"<id>","status":"opened|blocked|skipped",
 "branch":"nightcrew/<id>","pr_url":"<url or null>",
 "criteria":[{"criterion":"...","evidence":"...","verdict":"pass"}],
 "reason":"<only when not opened>"}
```
Commit nothing from `.nightcrew/` unless the repo already tracks it.

## Report
End with: item picked (or why none), gate result, judge verdicts, PR URL.
