# Phase 1 — Close the thin loop (own the spine)

> Phase-decomposition plan for **Phase 1**, decomposed into landable turns. Authored on the
> perk-scaffolded substrate as the Phase-0 dogfood gate (see [phase-0-gate.md](./planning/phase-0-gate.md)).
> Granularity matches [phase-0-plan.md](./planning/phase-0-plan.md): objective, acceptance gate, a turn
> breakdown, dependencies, deferrals — **not** full per-turn docs (each turn gets its own
> `phase-1-turn-N.md` when it is picked up). Implementation-level gotchas (e.g. `StringEnum` vs
> Google compatibility, the plan-mode "re-scan only after the current marker" subtlety) stay in the
> per-turn docs, not here.
>
> **Per-handler-turn obligation.** Each stage's handler turn fills, *as built*, that stage's registry
> descriptor — both its **state-I/O** (`requires`/`reads`/`writes`) **and its `doors` legality**
> (warm / cold-local / cold-remote) — and preserves the **supervisor machine surface** on its cold
> door (`--json` + stable exit codes / `{success, error_type, message}`, per
> [cli-vs-pi.md](./cli-vs-pi.md) §3.2). These values stay deferred to each handler's turn, mirroring
> the registry's empty fields — never authored ahead.
>
> **Two test surfaces, both live this phase.** The **interior** (extension handlers) is tested via
> the T1 SDK in-session harness; the **exterior** (Python CLI writes + `perk resume`) is tested via
> `CliRunner` + `PerkContext.for_test`, per [python-cli-guidelines.md](./python-cli-guidelines.md)
> §9. "Testing starts here" means *both* planes.
>
> **Deterministic-planes constraint (inference hoisting).** perk's storage tools and CLI carry **no
> agentic reasoning**: the agent authors the plan and computes values; the tool just stores them.
> This is what keeps the storage layer deterministically testable by the T1 harness.

---

## Objective

A *minimal* end-to-end **plan → save → implement → submit → land → learn** that lets **perk ship
perk**. Build only the spine; defer every deepening (objectives, CI iteration, review
classification, the `address` loop, PR-body craft) to Phase 2. The point is to close the loop fast
so all later depth is built **through** it (ROADMAP §"Phase 1").

Keep **borrowed plan mode** (`@tombell/pi-plan`) for read-only exploration — internalizing it needs
the Phase-2 gating primitive. Build perk-owned, **GitHub-backed plan storage** and the spine
commands on top of it. This is where the **TS interior grows real handlers** and where **GitHub
mutation** (verification-only until now) first happens — **lazily, with each write added beside its
consumer**, never ahead of one.

**What Phase 1 actually adds (a framing note).** The `perk plan/implement/submit/land/learn`
**launchers already exist** — Phase 0 (T4) registered them from the stage registry and they resolve
a launch today. Phase 1 does *not* rebuild the launchers; it fills in the **handler behavior**
behind them, the GitHub-backed plan storage they read/write, the in-session **warm doors** (slash
commands), the cross-stage **lifecycle gates**, and the one genuinely-new verb **`perk resume`**.
Each stage has two doors: a **cold door** (CLI → fresh `pi`, already wired) and a **warm door**
(in-session slash command, new this phase).

## Acceptance gate (the Phase-1 dogfood gate)

**perk ships perk.** A real change to perk is **authored and saved as a perk plan, then implemented,
submitted, landed, and learned-from through perk's own thin loop** — end to end, on perk's own repo.
From that point, every Phase-2/3 change rides the validated spine, not planning alone.

**Incremental dogfood, not just the end gate.** Once **plan → save closes (T3)**, perk can author and
save the *remaining* Phase-1 turn work as real perk plans — so perk starts building itself
mid-phase, and each later turn is the first consumer of the loop the previous turns closed.

## Turn decomposition

The spine is strictly linear after the foundation: **T1 (harness)** de-risks and unlocks
verification; **T2 (storage)** is the foundation the handlers read/write; **T3 → T5** close the loop
stage by stage; **T6** is the gate.

### P1.T1 — Test harness (de-risk first)
The highest-uncertainty mechanic in Phase 1, isolated up front so every later turn can verify
itself. We have never driven a real `pi` session through the SDK — Phase 0 tested the TS interior
only via isolated `node:test`.
- **Spike then build** the command/extension test substrate on the SDK + `SessionManager.inMemory()`
  (pi best-practices §2): drive a session programmatically, assert on tool calls + appended entries.
- **Determinism + isolation:** disable nondeterminism with `SettingsManager.inMemory({ compaction:
  { enabled: false } })` + retry-off settings overrides, and load **only the perk extension** via a
  `DefaultResourceLoader` override (never the user's config) so tests don't depend on the host
  environment (pi best-practices §2).
- **Prove it against a real first target** — re-test the Phase-0 T3 `run_id` **claim/fork** logic
  *through a live session* (not just the isolated unit). This means the harness must exercise the
  state-rebuild on **both** `session_start` **and** `session_tree` (branch navigation), not just a
  reload — the named antidote to erk's silent-stale-marker bug (agent-stuff §4 / pi §4).
- **Scope:** the command/extension layer **only** — end-to-end *worker* tests stay Phase 3.
- *Depends on Phase 0.*

### P1.T2 — Plan storage core *(held together; internal seam available)*
The deterministic, testable foundation everything downstream reads and writes. Held as one turn, but
carries a documented seam so it can land as incremental sub-turns if it bloats:
- **T2a — GitHub plan write** *(Python plane):* create the plan issue with the **header/body split**
  (foundational #2 / PRIOR_ART §2); establish the gateway's **write-safety conventions** —
  `--dry-run`, idempotency, error-translation — that submit/land reuse. The first GitHub *mutation*
  (Phase 0's gateway was read/verify only). **This is where the `PerkContext` + `require_github` DI
  seam first gets a real consumer** (Phase 0 built it; no command needed it yet), and write ops
  follow the established `isinstance(result, GitHubError) → raise UserFacingCliError` boundary
  (python-cli-guidelines §5).
- **T2b — Plan ref** *(cache / TS plane):* materialize the provider-agnostic **plan ref** in
  `.pi/workflow/` (contracts §8.4) — canonical copy in GitHub, transient linkage in the session
  `appendEntry`, **idempotent on the Pi session id**. The transient linkage is **rebuilt on both
  `session_start` and `session_tree`** with last-write-wins, so it survives reload, compaction, and
  branch navigation (agent-stuff §4 / pi §4).
- Tested via the T1 harness. Amends contracts §8.4; fills the registry `save` stage's `writes`
  (`github.plan`, `cache.plan-ref`).
- *Depends on T1 + the Phase-0 GitHub gateway.*

### P1.T3 — `/plan-save` (the terminating tool) + the planning skill
The in-session **warm door** wrapping T2's storage — the read-only → read-write boundary.
- **Terminating tool** (`terminate: true`) so the turn ends on save without an extra LLM round-trip;
  cache-mutating tools marked `executionMode: "sequential"` to avoid `.pi/workflow/` races
  (pi best-practices §6).
- **Dual-surface return:** the tool returns both `content` (for the model) and `details` (structured)
  — the in-session twin of the CLI's human/`--json` split — and `details` doubles as **forking-safe
  persisted state**. The tool's `description` + `promptGuidelines` carry the "when may you call this"
  safety contract structurally, not as system-prompt hope (agent-stuff §6 / pi §6).
- **Planning skill** encoding the plan-authoring *conventions* (judgment lives in the skill, save
  *mechanics* stay in the deterministic tool; the skill's `description` is its only trigger) — most
  importantly erk's hard rule that **line-number references are disallowed** (they drift); require
  durable anchors (function names, behavioral descriptions, structural locations).
- **Closes `plan → save`.** *Incremental dogfood starts here.* *Depends on T2.*

### P1.T4 — `/implement` (cold door) + session-lifecycle gates
A *thin* execution path, plus the cross-stage transition hygiene (built here because this is the
first transition that can **lose work**).
- Primary transition is the **CLI cold door** (`perk implement <plan>`: materialize the worktree
  from the plan ref + launch a fresh `pi`). The cold door **positions + launches + hands off, then
  done** — a launcher that delegates, never a reimplementation (cli-vs-pi §2.3).
- **Door legality — the warm door is not always safe** (cli-vs-pi §4.1). The **plan→implement**
  transition must *not* inherit the planning conversation, so a fresh context is required — that is
  the **cold door's** job. The warm `/implement` command is legal only as "continue an *already
  current* impl worktree" (you are already in the right context), never as the plan→implement jump.
  The registry records this per stage (`doors`).
- **Lifecycle gates** (one primitive, reused across all stages): guard transitions with Pi's
  `session_before_switch` / `session_before_fork` → `{ cancel: true }`. Port erk's dirty-repo /
  commit-before-leaving checks — detect via `pi.exec("git", ["status", "--porcelain"])`, and **fail
  safe (block) when headless** (`!ctx.hasUI ⇒ block`). Templates: `dirty-repo-guard.ts` /
  `confirm-destructive.ts` (pi best-practices §7). *The in-process `ctx.newSession` warm-path fresh
  context is **Phase 2** — Phase 1's only fresh-context move is the CLI cold door.*
- **Closes `save → implement`.** *Depends on T2 (plan ref) + T3.*

### P1.T5 — PR lifecycle *(one turn; internal seams available)*
The back half of the spine — three thin handlers + the resume verb. Cohesive at build time (all thin
GitHub ops + marker moves), separated only at *runtime* by review/CI. Held as one turn with
documented seams for incremental sub-turn landings:
- **T5a — `/submit`:** commit and open a (draft) PR whose body carries the plan (GitHub PR mutation,
  reusing T2a's write conventions). Defer the two-target body craft, `pr check`, and the
  draft→ready nuance to Phase 2.
- **T5b — `/land` + `/learn`:** `/land` merges the approved PR and sets the `pending-learn` marker
  (Q2's `cache.markers` semaphore); `/learn` is a thin knowledge-capture pass that **clears**
  `pending-learn`, so the land→learn cycle closes and the worktree is releasable. Defer
  reconciliation typing and deep learn tooling to Phase 2+.
- **T5c — `perk resume <plan>`:** the cross-stage resume verb (resume any plan at its current
  stage) — completable here because by T5 every stage exists. The one genuinely-new CLI command this
  phase: three-layer Click pattern + supervisor `--json` surface (python-cli-guidelines §8.2),
  tested via `CliRunner`.
- **Closes `implement → submit → land → learn`.** *Depends on T4.*

### P1.T6 — Phase-1 dogfood gate *(checkpoint)*
- Drive a real perk change through the whole loop on perk's own repo; record the run as the gate.
- Reconcile `AGENTS.md`/README/contracts against what got built; confirm the registry's per-stage
  state-I/O is now filled for the spine. *Depends on T1–T5.*

## Dependencies

- **On Phase 0 (all green):** `perk init`/`doctor` (scaffold + health), the stage registry + the
  `perk <stage>` launchers (T4), the `.pi/workflow/` cache + `run_id` + `perk:workflow-state` state
  tiers (T3), the GitHub gateway + `require_github` (T5), `PerkContext`/`require_*` DI.
- **Internal:** T1 (harness) is foundational and unlocks verification; T2 (storage) is the
  foundation the handlers read/write; T3 → T5 are a linear spine on top; T6 is the gate.

## Explicitly deferred (Phase 2+)

- **Perk-owned plan mode + the tool-gating primitive** — Phase 2 (keep borrowing `pi-plan` through
  the thin loop; decide keep-wrap vs own from real usage).
- **Objectives, the CI executor, the review/`address` loop, feedback classification** — Phase 2.
- **PR-body two-target craft, `pr check`, draft→ready nuance, reconciliation typing, deep learn
  tooling** — Phase 2.
- **The end-to-end *worker* tests** — Phase 3 (Phase 1 ships the command/extension test layer only).
- **Subagent delegation, untrusted-input hygiene & agent scoping** — land with the first comment
  ingestion / agent spawn (Phase 2). Phase 1 spawns no children, so the delegation/session-id
  constraints are dormant.
- **In-process `ctx.newSession` handoff** (the warm-path fresh context, the in-process twin of the
  cold door) — Phase 2; Phase 1's fresh-context move is the CLI cold door only.
- **Per-stage state-I/O values** for stages whose handler hasn't landed — filled turn-by-turn, never
  authored ahead (mirrors the registry).
