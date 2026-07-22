# Nightcrew — Glossary

The ubiquitous language for Nightcrew. Docs and code should use these
terms exactly. (Project was named EVE until 2026-07-16; ADR-14.)

**Nightcrew** — an autonomous build agent that delivers verified, spec-aligned
PRs overnight and never merges them. Two flavors, one contract (ADR-15).
Successor to autodev (ADR-1).

**Nightcrew Lite (Lite)** — the ships-first flavor: a Claude Code plugin (run
skill + enroll skill + `gate.py` + scheduling templates) running the pipeline
via a scheduled cloud routine or local `claude -p` cron. Frozen after its
launch pass except bugfixes (ADR-15).

**Nightcrew Engine (Engine)** — the flagship flavor: the Python pipeline
(picker, planner, aider builder, hybrid gate, SQLite log, learning layer),
model-agnostic via OpenRouter, run as a one-shot CLI on a host-provided
schedule (ADR-16).

**Stage** — one inspectable step of the Engine pipeline owned as real code:
**picker**, **planner**, **gate**, **learning**. The **builder** stage is
delegated to aider (ADR-3). Each model-calling stage has its own configurable
OpenRouter model (ADR-7).

**Spec item** — a unit of work in a repo's `nightcrew.yaml`, shaped
`{id, description, acceptance_criteria: [...], deps: [ids]}`. The contract the
gate checks against.

**nightcrew.yaml** — the single per-repo, version-controlled file: a `config`
header (`test_cmd`, `off_limits`, `conventions`) plus `items` (ADR-19). The
single source of truth and the decision surface (ADR-4, ADR-8). Shared
verbatim by Lite and Engine.

**Acceptance criterion** — one checkable statement of "done" for a spec item.
The gate must cite concrete evidence for each one (ADR-5).

**Picker** — selects the next spec item: v1 = first ready item (deps
satisfied, well-specified, no open PR); skips + logs underspecified items
(ADR-8, ADR-11).

**Planner** — turns a spec item into an implementation plan.

**Builder** — in the Engine: aider, run headless via OpenRouter, self-healing
tests (`--auto-test`) before returning (ADR-3, ADR-6). In Lite: the Claude
Code session itself.

**Verification gate (the gate)** — the hard, non-negotiable block before any
PR: deterministic layer (`gate.py`: tests re-run + structural checks incl.
test-tampering block) plus an evidence-citing LLM judge (ADR-5, ADR-6).
"Spec-alignment" = every acceptance criterion has cited evidence.

**gate.py** — the dependency-light deterministic-gate script shipped with Lite
and reused by the Engine (LT2, BP7). Prompt-independent; its exit code blocks
the PR.

**Judge** — the model in the gate's second layer. Engine default: a different
vendor/family than the builder (ADR-7). Lite default: same-vendor, honestly
labeled, optional BYO second-vendor key (ADR-16).

**Underspecified** — a spec item whose acceptance criteria are too thin for
the gate to ever cite evidence against; skip-and-log, not built (ADR-8).

**Outcome** — the fate of a shipped PR, backfilled at the start of each run:
`merged_clean` (accepted as-is), `merged_revised` (merged with later commits —
the plan was off), `rejected` (closed) (ADR-10).

**Build log** — the durable record every run appends to: plans, models,
per-criterion gate evidence, cost, PR url, outcome. Lite: `.nightcrew/
log.jsonl` in-repo; Engine: SQLite, importing Lite's log (ADR-19, BP3).
Substrate for the learning layer (ADR-10).

**Evidence table** — the criterion → evidence verdict table (plus total cost)
that forms every Nightcrew PR body (ADR-18). The PR is the demo.

**Review record** — the generic JSON record (`{id, source, kind, title,
body_md, url, options, meta}`) BP8 emits to a configurable sink so external
approval inboxes can consume Nightcrew PRs (ADR-17).

**Value-learning layer** — the deferred subsystem (Phase 2) that mines the
build log for plan→outcome patterns and feeds them back into planner prompts
(ADR-10, BP13).

**Trust level** — a per-repo posture. `propose_only` (default, everywhere):
open PRs, never merge. `auto_merge_small` (Phase 2, BP14): auto-merge low-risk
verified PRs once a repo has demonstrated reliability. Ratcheting up is a
human config change gated on measured reliability, never automatic.

**fleet.json** — the Engine's optional multi-repo registry
(`{name, github, repo_path, enabled, trust, max_items_per_run}`). Single-repo
mode needs none (ADR-19).

**Enrollment** — `nightcrew enroll`, which refuses repos with no tests (the
gate needs them) and scaffolds `nightcrew.yaml` at `propose_only` (LT4, BP10).

**Budget cap** — the hard USD guardrail (daily + per-run) the Engine enforces
itself using real OpenRouter per-request costs, checked at item boundaries
(ADR-9).

**Scheduling recipe** — a documented way the host runs Nightcrew on a
schedule: GitHub Actions nightly workflow (zero-infra reference), cron,
systemd user timer; Lite adds the cloud routine (ADR-16).

**nightcrew-sandbox** — `SeanL128/nightcrew-sandbox`, the disposable
Python+pytest repo the walking skeleton targets and the public demo repo
(ADR-13/14, BP11).
