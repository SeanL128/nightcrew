# Nightcrew — Architecture Decision Records

Decisions made during the design grilling (2026-07-09, ADR-1…13, as "EVE") and
the public-release reshape (2026-07-16, ADR-14…19). Each is a settled contract
the BACKLOG and its blueprints must honor. Format: Context · Decision ·
Consequences. Supersedes the interim `DECISIONS.md`. Where an early ADR says
"EVE" or `eve`, read "Nightcrew" / `nightcrew` (ADR-14).

---

## ADR-1 — EVE is a from-scratch successor to autodev
**Context.** Autodev already runs a spec→plan→review→TDD→PR pipeline and lists
"verification gate" and "value-learning" as its own unbuilt backlog items —
so "just extend autodev" was on the table. **Decision.** Build EVE clean; retire
autodev once EVE reaches parity. The load-bearing justification is the
**substrate**: autodev orchestrates a headless Claude Code black box it cannot
inspect mid-run, whereas EVE is SDK-native with explicit, inspectable stages
(picker / planner / builder / gate / learning as real code, not prompt handoffs).
**Consequences.** No autodev code is reused. "Inspectable stages" is the acceptance
test for every architectural choice — if a design reintroduces an opaque
prompted pipeline, it violates this ADR.

## ADR-2 — Models via OpenRouter, not the Anthropic SDK
**Context.** Sean prefers OpenRouter. **Decision.** EVE calls OpenRouter
(OpenAI-compatible), model-agnostic, any model per stage swappable by config.
**Consequences.** (a) Enables ADR-7 and the value-learning layer to eventually
learn *which model* is worth its cost per task-type. (b) Real per-request USD
cost comes back in the response — no autodev-style cost-guessing. (c) No
5-hour/weekly meter exists, so the budget guardrail is a hard dollar cap EVE
enforces itself (ADR-9). (d) The Anthropic-SDK skill is not the reference.

## ADR-3 — Builder delegated to aider; EVE owns the rest
**Context.** The builder is a full coding agent; rolling one from scratch is a
mountain. **Decision.** Delegate keystroke-level code editing to **aider**
(headless, via OpenRouter). Picker, planner, verification gate, and learning are
EVE's own inspectable code. **Consequences.** Differs from autodev, which
delegated the *entire* plan+build to one black box — here only editing is rented;
every decision around it is EVE's. Satisfies ADR-1 because the novel parts stay
inspectable. aider chosen over opencode for its proven headless mode and built-in
test loop (ADR-6).

## ADR-4 — Standalone now, agentic-os-contract-compatible
*(Generalized by ADR-17 — the proposal record becomes a generic review-record
contract; agentic-os is one consumer, documented privately.)*
**Context.** The agentic-os was explicitly designed to host an autonomous builder
(built `v3-project-tracker`; unbuilt `v3-proposals-review` + autodev wiring
blueprints 8/10). **Decision.** Ship EVE standalone now — spec items in a
**per-repo spec file**, PR review via GitHub — but (a) emit PR-approval records in
the existing `/proposals` record shape and (b) shape `fleet.json` to align with
the Tracker registry, so integration later is a config flip, not a rebuild. No
day-one dependency on the unbuilt proposals sidecar. **Consequences.** The spec
file is the single source of truth and the decision surface (ADR-8). Integration
is Phase 3 (BP15/BP16), not a rewrite.

## ADR-5 — Verification gate is hybrid: deterministic + evidence-citing judge
**Context.** The gate is EVE's reason to exist; "spec-alignment" must be concrete
enough to block on. Precedent: Descry's Overseer (deterministic + LLM judge).
**Decision.** Hard block in two layers: (1) tests pass + cheap structural checks;
(2) an LLM judge that maps **each** `acceptance_criterion` to concrete evidence in
the diff/tests and blocks on any unaddressed one. **Consequences.** Objective
floor + forced-evidence judgment (not vibe-approval), without demanding every
criterion be pre-written as a test. No PR ships unverified. Rejected: pure
LLM-judge (too soft), pure criteria-as-tests (too heavy for day one).

## ADR-6 — Builder self-heals; gate re-runs tests and guards tampering
**Context.** aider's `--auto-test` overlaps the gate's test-running.
**Decision.** aider runs `--auto-test` against the repo's `test_cmd` and fixes
its own failures before returning; the gate **independently re-runs** tests (never
trusts the builder) and **blocks any diff that removes or weakens tests** without
justification. **Consequences.** Fewer gate bounces and lower cost on the
objective half, with the "gate runs tests, blocks on failure" invariant preserved.
Test-tampering is an explicit gate check, not an afterthought.

## ADR-7 — Per-stage model config; judge ≠ builder family
**Context.** Self-referential verification is the failure mode the gate exists to
prevent. **Decision.** Each stage (picker/planner/builder/judge) has a
configurable OpenRouter model with sensible defaults; the **judge defaults to a
different vendor/family than the builder**. **Consequences.** The builder and
judge don't share blind spots, so the gate's independence is a property you can
point at, not just assert. Learnable later (Phase 2) which model per stage is
worth its cost.

## ADR-8 — Skip ambiguous items; no decision queue
**Context.** Autodev's two-stream model (park ambiguous specs as GitHub
decision-issues, ingest via a watcher) is a whole subsystem.
**Decision.** The picker **skips** items too underspecified for the gate to ever
pass, logging `skipped: underspecified, <reason>`; Sean sharpens the item in the
spec file; next run it's buildable. No decision queue, no watcher — the spec file
is the decision surface. **Consequences.** An entire subsystem removed; matches
ADR-4. The "surface a question and get an answer" capability arrives naturally
with the proposals inbox (Phase 3), not as throwaway GitHub-issue machinery now.

## ADR-9 — Nightly VPS systemd user timer; hard dollar caps
*(Runtime half superseded by ADR-16 — scheduling is host-provided; the hard
dollar caps and item-boundary checks stand unchanged.)*
**Context.** Substrate for an always-on autonomous agent; OpenRouter has no meter.
**Decision.** Runs on the shared VPS as a systemd **user** timer, **nightly**
(e.g. 02:00 box-local): pick→plan→build→gate→PR for up to N items until a **hard
daily $ cap / per-run $ cap / item cap** is hit, checked at item boundaries.
**Consequences.** Laptop-independent; same box as the agentic-os; compatible with
the Project Tracker Builds band (which uses `systemd-run` on the VPS). Predictable
spend; "review the PR in the morning" rhythm. Rejected: continuous loop
(unpredictable spend), on-demand-only (not autonomous).

## ADR-10 — Instrument now, learn later; propose_only only; outcome backfill
**Context.** A learner needs accumulated outcomes; there are none at launch.
**Decision.** v1 records the full trace to a SQLite build log and **backfills each
PR's outcome** (`merged_clean` / `merged_revised` / `rejected`) via `gh pr view`
at the start of each nightly run. Everything ships `propose_only`. The
value-learning feedback loop and `auto_merge_small` are **separate later backlog
items** (BP12/BP13), gated on weeks of real outcomes. **Consequences.** v1 is
honest — it can't learn from data it doesn't have; it builds the recorder now, the
learner once the log has weight. No watcher needed (backfill rides the nightly run).

## ADR-11 — v1 picker = first ready item (deps + status aware)
**Context.** Ranking intelligence can't be tuned without outcome data.
**Decision.** v1 picks the first spec-file item whose deps are satisfied, that's
well-specified, and has no open/merged PR. Risk/staleness/priority ranking is a
self-contained later item (BP14). **Consequences.** Correct and near-impossible to
get wrong; proves the pipeline before optimizing item selection.

## ADR-12 — Defer digest & audit modules; digest as a v1 CLI command
**Context.** Autodev shipped scheduled digest + audit modules. **Decision.** v1 =
core pipeline + build log only. The morning readout is a v1 `eve digest` / `eve
status` CLI query over the log (no scheduling). The scheduled digest module lands
with proposals-inbox wiring (BP17); audit is its own later feature (BP18).
**Consequences.** v1 stays focused on proving the thesis; the modules land where
they naturally belong (inbox for digest; a separate "finding work" job for audit).

## ADR-13 — Walking skeleton targets a fresh eve-sandbox
**Context.** The gate needs tests, and the first run's correctness shouldn't ride
on a repo Sean cares about. **Decision.** Create `SeanL128/eve-sandbox` (Python +
pytest) with one trivially-verifiable first spec item; keep it separate from
`autodev-sandbox`. **Consequences.** Disposable, safe, fast to green, clean
provenance, no collision with autodev during EVE's shakedown.

## ADR-14 — Public project; renamed EVE → Nightcrew
**Context.** 2026-07-11 build-in-public decision: projects ship public, launched,
under Sean's name, in the agentic-AI niche. "EVE" collides badly (EVE Online;
`eve` on PyPI is a REST framework). **Decision.** The project is public from the
start, named **Nightcrew** (PyPI-free, low GitHub collision, carries the
overnight-worker story). Package/CLI `nightcrew`; per-repo file `nightcrew.yaml`;
sandbox `SeanL128/nightcrew-sandbox` (amends ADR-13's name). Sean-specific
infrastructure never appears in public docs. **Consequences.** Positioning lives
in `PITCH.md`; the README/launch pass is a backlog item, not an afterthought.
Earlier ADRs' "EVE"/`eve` read as Nightcrew.

## ADR-15 — Lite ships first; one brand, one contract; Lite freezes at launch
**Context.** The Engine is weeks of work; Claude Code cloud routines are new,
demonstrably underused, and reachable by anyone with a subscription — a launch
window measured in weeks. **Decision.** Ship **Nightcrew Lite** first: a Claude
Code plugin (run skill + enroll skill + `gate.py` + routine template) doing the
same pipeline routines-natively. Same repo, same brand, same `nightcrew.yaml`
contract and gate semantics as the Engine, so Lite → Engine is a drop-in
upgrade. After its launch pass, **Lite is frozen except bugfixes**; feature
requests become Engine backlog fuel. Gated on a 1-day capability spike (LT1):
a routine must clone/pull, run tests, push a branch, open a PR. **Consequences.**
Two launches (Lite, then Engine) instead of one distant one; the spike reshapes
Lite before polish is sunk; the known risk — launch feedback dragging work into
plugin feature-land — is refused by the freeze rule.

## ADR-16 — Engine is a one-shot CLI; scheduling is host-provided
**Context.** ADR-9's "VPS systemd timer" was Sean's deployment, not a product
property; requiring an always-on machine kills stranger adoption. **Decision.**
The Engine is a one-shot `nightcrew run`. Scheduling belongs to the host, with
three documented first-class recipes: **GitHub Actions nightly workflow** (the
zero-infra reference — every GitHub user already owns a cron-capable runner
with PR permissions), **cron** on an always-on machine, **systemd user timer**
on a VPS (better for heavy test suites, private runners, no Actions-minutes
limits). Dollar caps and item-boundary checks (ADR-9) unchanged. In Lite, the
same host-provided principle holds (cloud routine or local `claude -p` cron);
Lite's judge is same-vendor by default, honestly labeled, with an optional
BYO-second-vendor judge key preserving ADR-7's independence where users want
it. **Consequences.** No daemon, no server, nothing to keep alive; Sean's VPS
becomes just one recipe. Actions template must be part of Engine "done" (BP9).

## ADR-17 — Generic review-record contract; agentic-os is one consumer
**Context.** ADR-4 shaped PR-approval records to Sean's agentic-os `/proposals`
contract — meaningless to the public. **Decision.** BP8 emits a generic
**review-record JSON** (`{id, source, kind, title, body_md, url, options,
meta}`) to a configurable sink (default: the build log). The agentic-os wiring
becomes a private consumer of that contract, documented in
`docs/integrations-private.md` (kept out of the public repo/backlog).
**Consequences.** Anyone can wire an approval inbox (Slack bot, dashboard,
agentic-os) without Nightcrew knowing about it; Phase 3 of the old backlog
dissolves into a private doc.

## ADR-18 — The PR body is the gate's verdict
**Context.** The gate's evidence lived only in the build log; the PR — the one
artifact every user and launch-post reader sees — didn't show the thesis.
**Decision.** Every Nightcrew PR body carries the per-criterion
criterion → evidence verdict table plus total run cost. **Consequences.** The
PR is self-verifying and the screenshot is the launch asset; reviewers see
exactly what was proven without opening the log.

## ADR-19 — Single per-repo file `nightcrew.yaml`; JSONL log in Lite
**Context.** The old design split per-repo state across `.eve.json` (config)
and a separate spec file; Lite needs one-file simplicity, and both flavors must
share one contract. **Decision.** One per-repo, version-controlled
`nightcrew.yaml`: a `config` header (`test_cmd`, `off_limits`, `conventions`)
plus `items`. `fleet.json` remains for the Engine's multi-repo mode only.
Lite's build log is `.nightcrew/log.jsonl` in-repo; the Engine's SQLite log
(BP3) imports it so history survives the upgrade. **Consequences.** Enrollment
scaffolds one file; the spec file stays the single source of truth and decision
surface (ADR-8); no config/spec drift between flavors.

## ADR-20 — Lite scrapped before launch; cloud routines too buggy to build on
**Context.** Phase 0 (Lite) was complete through LT4 and packaged for launch
as a Claude Code plugin. My own research and testing (2026-07-16) found
scheduled cloud routines too buggy to be a foundation right now — consistent
with the LT1 gotchas (opaque init failures, `"role": "user"` landmine).
**Decision.** Scrap Nightcrew Lite entirely; do not launch it. The packaged
plugin is archived outside this repo in case routines mature. LT2's contract
+ `gate.py` remain live inputs to the Engine (BP2, BP7) — `lite/` stays the
working source. **Consequences.** ADR-15's Lite-first launch
plan and ADR-16's Lite note are superseded on the Lite side; the Engine is now
launch #1. LT5 and Lite-specific work are cancelled; BP3's Lite-log importer
becomes optional.

## ADR-21 — Public release, scoped as an opinionated personal tool
**Context.** Greenlight reframe (2026-07-19): not whether to build Nightcrew
(settled — Sean is building it regardless) but whether to frame it as a public
release or keep it private and tailored to Sean's workflow. The pull toward
private is real — "easy for anyone to adopt" (arbitrary repos/CI, config
abstraction, support) is a polish trap that risks the 70%-abandon. **Decision.**
Ship **public, but scoped as an opinionated personal tool** — not private, and
not a general product. Build for Sean's own workflow (OpenRouter, aider, GitHub
Actions — already the design) and release that as-is. The README leads with the
verification-gate **thesis** ("no PR ships unverified; the PR proves it"), not
"another autonomous coder," and honestly labels the tool as opinionated
("here's how I run it; fork it"). "Done = packaged" (README + demo GIF +
~3-command install + one launch pass) is the ceiling; generality for
hypothetical adopters is out of scope. **Consequences.** Keeps the North Star
(build-in-public, agent-orchestration anchor, seanlindsay.xyz card, top-lab
signal) while staying finishable. Does not chase adoption against OpenHands /
SWE-agent / Aider — competes on POV (gate-as-product), not reach.
`docs/integrations-private.md` stays out of the public repo (ADR-17). No change
to Engine scope or blueprints; this governs framing and README emphasis only.

## ADR-22 — Pluggable model + builder; portable default, Sean's infra configured-in
**Context.** ADR-21 reopened the stack: OpenRouter and aider were chosen to
maximize stranger adoption, but Sean runs alloyd (router), Claude Code headless,
and a VPS, and would prefer those. Constraint from ADR-21: the public repo must
stay clone-and-run so a stranger can watch the gate produce one self-verifying
PR (ADR-18) — that reproducible demo is the launch asset and the portfolio
payoff. **Decision.** Make the **model** and **builder** layers config-selected
adapters with a portable default; Sean's infra is the path he configures, never
a hard dependency. (1) **Model layer:** "any OpenAI-compatible endpoint +
per-stage model id" (generalizes ADR-3). Default ships portable (OpenRouter or a
direct Anthropic key); Sean's config points at his router. OpenRouter is *a*
default, not *the* dependency. (2) **Builder layer:** one adapter seam behind
picker/planner/gate/PR; ship `aider` (portable default) and Claude Code headless
(`claude` in print mode — Sean's path). (3) **Cost caps:** keep dollar caps on
the metered default (safety property + launch selling point); document that
subscription/router paths meter via usage windows instead — don't remove them.
Unchanged: host-provided scheduling (ADR-16), one-shot CLI + `nightcrew.yaml` +
SQLite log (ADR-19). **Consequences.** BP1's "OpenRouter client" becomes a
model-endpoint client (OpenRouter default); a builder-adapter blueprint is added
ahead of the aider builder. Two seams, each with ≥2 real implementations Sean
wants — config-selected adapters, not a plugin framework (no entry-points
registry). Supersedes ADR-3's OpenRouter-specific wording and ADR-21's implicit
aider/OpenRouter stack on the adapter question only.

## ADR-23 — The seam is a dispatch command; alloyd is Sean's backend, foreman loop is the orchestrator
**Context.** ADR-22 made the model and builder config-selected seams but left
their concrete shape open, and BP1 still specified a from-scratch OpenRouter
client + BP6 an aider integration. Re-brainstorm (2026-07-19): Sean already runs
**alloyd** (a dispatch router — per-role (band, effort) selection, live-usage-
aware, cross-vendor failover, headless CLI `alloyd dispatch <role> --brief
x.json`) and the **foreman** loop (interview → brief → dispatch bricklaying →
review/judge → one fix). BP1 duplicates a worse alloyd; BP5+BP6+BP9's build loop
duplicates foreman. **Decision.** (1) The ADR-22 seam is a single interface
`dispatch(role, brief) -> (text, cost_or_usage)` whose backend is a **command
template**, not a bespoke client. Sean's backend shells `alloyd dispatch …`
(reuses its routing + failover); the portable public default is one `claude -p
--output-format json` / OpenRouter call behind the same interface. Nightcrew
never imports alloyd. (2) Nightcrew is the **headless, autonomous form of the
foreman loop**: a thin Python orchestrator owns the inspectable stages (picker,
gate, log, PR, caps) as real code; planner + builder are dispatched through the
seam. This satisfies ADR-1 — the trustworthy/thesis stages stay inspectable;
only bricklaying is rented, exactly as foreman splits judgment from bricks.
(3) The gate's judge role stays a different vendor/family than the build role
(ADR-7 preserved via alloyd role choice). **Consequences.** BP1 (OpenRouter
client) and BP6 (aider) are decommissioned; BP5's planner becomes a foreman-
style brief. The blueprint / fable-blueprint workflow is retired and its forge
suite deleted (2026-07-19) — build directly from `TODO.md` via foreman/dispatch. Live-usage-aware failover is a Sean-path bonus, not
required of the portable default; the portable path keeps hard USD caps
(ADR-22). Supersedes ADR-3 (aider) and the client half of ADR-2 (the OpenRouter
SDK wrapper); the plan of record is `TODO.md`, and `BACKLOG.md` is superseded.

## ADR-24 — Nightcrew replaces autodev at parity (ADR-1 executed)
**Context.** ADR-1 built Nightcrew as a from-scratch successor to autodev, with
"retire autodev once EVE reaches parity" as the exit condition — but autodev is
deployed and working (VPS systemd user timers, `models.py` Fable-block,
`fleet.json`, propose_only). Now that the new stack (ADR-23) shares autodev's
substrate, the coexist-vs-replace question is live. **Decision.** Execute ADR-1
literally: **Nightcrew replaces autodev.** Nightcrew inherits autodev's VPS
substrate, the `models.py` Fable-hard-block (carried into the seam's role map —
Fable never gets a build role), and `fleet.json` (seed Nightcrew's from
autodev's). autodev's `autodev-build`/`autodev-audit` timers are disabled **only
after a parity soak**: N nights of Nightcrew runs on the sandbox + at least one
real repo producing PRs Sean would have wanted, gate blocking correctly, cost
within cap. autodev is kept dormant (not deleted) one cycle as rollback.
**Consequences.** One public pipeline, not two. Deliberate simplifications vs
autodev are accepted, not regressions: no decision-queue/watcher (the spec file
is the decision surface — ADR-8), digest is a CLI query not a scheduled module
(ADR-12). The retirement is `TODO.md` Phase E; the agentic-OS review-desk
(Phase F, `docs/integrations-private.md`) then consumes Nightcrew where it used
to consume autodev.
