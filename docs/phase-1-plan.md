# Phase 1 — Close the thin loop (own the spine)

> Phase-decomposition plan for **Phase 1**, decomposed into landable turns. Authored on the
> perk-scaffolded substrate as the Phase-0 dogfood gate (see [phase-0-gate.md](./planning/phase-0-gate.md)).
> Granularity matches [phase-0-plan.md](./planning/phase-0-plan.md): objective, acceptance gate, a turn
> breakdown, dependencies, deferrals — **not** full per-turn docs (each turn gets its own
> `phase-1-turn-N.md` when it is picked up). Per-stage state-I/O (`requires`/`reads`/`writes`) stays
> deferred to each handler's turn, mirroring the registry's empty fields.

---

## Objective

A *minimal* end-to-end **plan → save → implement → submit → land → learn** that lets **perk ship
perk**. Build only the spine; defer every deepening (objectives, CI iteration, review
classification, the `address` loop, PR-body craft) to Phase 2. The point is to close the loop fast
so all later depth is built **through** it (ROADMAP §"Phase 1").

Keep **borrowed plan mode** (`@tombell/pi-plan`) for read-only exploration — internalizing it needs
the Phase-2 gating primitive. Build perk-owned, **GitHub-backed plan storage** and the spine
commands on top of it. This is where the **TS interior grows real handlers** and where **GitHub
mutation** (verification-only until now) first happens — lazily, per stage.

## Acceptance gate (the Phase-1 dogfood gate)

**perk ships perk.** A real change to perk is **authored and saved as a perk plan, then implemented,
submitted, landed, and learned-from through perk's own thin loop** — end to end, on perk's own repo.
From that point, every Phase-2/3 change rides the validated spine, not planning alone.

## Turn decomposition

### P1.T1 — Plan storage core + the SDK test harness
The deterministic, testable foundation everything downstream needs.
- **GitHub plan write ops** (the first mutation; extends `perk/github.py` + the gateway): create the
  plan issue with the **header/body split** (foundational #2 / PRIOR_ART §2), idempotent.
- **Provider-agnostic plan ref** materialized in `.pi/workflow/` (contracts §8.4): canonical copy in
  GitHub, transient linkage in the session `appendEntry`, idempotent on the **Pi session id**.
- **Stand up the command/extension test harness** (`SessionManager.inMemory()`, pi best-practices
  §2) here and use it to test the storage core. "Testing starts here, not Phase 3."
- *Fills the registry `save` stage's `writes` (`github.plan`, `cache.plan-ref`).*

### P1.T2 — `/plan-save` (the terminating tool) + the planning skill
The in-session command wrapping T1's storage — the read-only → read-write boundary.
- **Terminating tool** (`terminate: true`) so the turn ends on save without an extra LLM round-trip;
  cache-mutating tools marked `executionMode: "sequential"` to avoid `.pi/workflow/` races
  (pi best-practices §6).
- **Planning skill** encoding the plan-authoring rules — most importantly erk's hard rule that
  **line-number references are disallowed** (they drift); require durable anchors (function names,
  behavioral descriptions, structural locations).
- Closes `plan → save`. *Depends on T1.*

### P1.T3 — `/implement` (cold door) + session-lifecycle gates
A *thin* execution path.
- Primary transition is the **CLI cold door** (`perk implement <plan>`: materialize the worktree
  from the plan ref + launch a fresh `pi`) — a clean implement context for free, no perk-owned
  gating yet. The warm in-session command just continues in the current worktree.
- **Stage-transition hygiene:** guard transitions with Pi's session-lifecycle gates
  (`session_before_switch` / `session_before_fork` → `{ cancel }`) — port erk's dirty-repo /
  commit-before-leaving checks, **failing safe (block) when headless** (pi best-practices §7).
- Closes `save → implement`. *Depends on T1 (plan ref), T2.*

### P1.T4 — `/submit` (thin PR)
- Commit and open a (draft) PR whose body carries the plan (GitHub PR mutation). Defer the
  two-target body craft, `pr check`, and the draft→ready nuance to Phase 2.
- Closes `implement → submit`. *Depends on T3.*

### P1.T5 — `/land` + `/learn` + `perk resume`
- **`/land`** — merge the approved PR and set the `pending-learn` marker (Q2's `cache.markers`
  semaphore). Defer reconciliation typing to Phase 2.
- **`/learn`** — a thin knowledge-capture pass that **clears** `pending-learn`, so the land→learn
  cycle closes and the worktree is releasable. Defer deep learn tooling to Phase 2+.
- **`perk resume <plan>`** — the resume verb, registry-generated alongside the spine launchers.
- Closes `submit → land → learn`. *Depends on T4.*

### P1.T6 — Phase-1 dogfood gate *(checkpoint)*
- Drive a real perk change through the whole loop on perk's own repo; record the run as the gate.
- Reconcile `AGENTS.md`/README/contracts against what got built; confirm the registry's per-stage
  state-I/O is now filled for the spine. *Depends on T1–T5.*

## Dependencies

- **On Phase 0 (all green):** `perk init`/`doctor` (scaffold + health), the stage registry + the
  `perk <stage>` launchers (T4), the `.pi/workflow/` cache + `run_id` + `perk:workflow-state` state
  tiers (T3), the GitHub gateway + `require_github` (T5), `PerkContext`/`require_*` DI.
- **Internal:** T1 is foundational (storage + harness); T2–T5 are a linear spine on top; T6 is the
  gate.

## Explicitly deferred (Phase 2+)

- **Perk-owned plan mode + the tool-gating primitive** — Phase 2 (keep borrowing `pi-plan` through
  the thin loop; decide keep-wrap vs own from real usage).
- **Objectives, the CI executor, the review/`address` loop, feedback classification** — Phase 2.
- **PR-body two-target craft, `pr check`, draft→ready nuance, reconciliation typing, deep learn
  tooling** — Phase 2.
- **The end-to-end *worker* tests** — Phase 3 (Phase 1 ships the command/extension test layer only).
- **Untrusted-input hygiene & agent scoping** — lands with the first comment ingestion / agent spawn
  (Phase 2).
- **Per-stage state-I/O values** for stages whose handler hasn't landed — filled turn-by-turn, never
  authored ahead (mirrors the registry).
