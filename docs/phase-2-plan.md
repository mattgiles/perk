# Phase 2 — Deepen the loop (objectives, CI, review)

> Phase-decomposition plan for **Phase 2**, decomposed into landable turns. Authored on the
> validated Phase-1 spine (see [phase-1-gate.md](./planning/phase-1-gate.md)) as the true dogfood
> the close-then-deepen ordering buys: **every Phase-2 turn is itself planned, saved, implemented,
> submitted, landed, and learned-from through perk's own thin loop**. Granularity matches
> [phase-1-plan.md](./planning/docs/phase-1-plan.md) and [phase-0-plan.md](./planning/phase-0-plan.md): objective,
> acceptance gate, a turn breakdown, dependencies, deferrals — **not** full per-turn docs (each turn
> gets its own `phase-2-turn-N.md` when it is picked up). Implementation-level gotchas (the
> `setActiveTools` snapshot-restore order, the `pi-subagents` seam shape, the fork-vs-branch
> discriminator for spawned children) stay in the per-turn docs, not here.
>
> **Per-handler-turn obligation.** Each new stage's handler turn fills, *as built*, that stage's
> registry descriptor — both its **state-I/O** (`requires`/`reads`/`writes`) **and its `doors`
> legality** (warm / cold-local / cold-remote) — and preserves the **supervisor machine surface** on
> its cold door (`--json` + stable exit codes / `{success, error_type, message}`, per
> [cli-vs-pi.md](./cli-vs-pi.md) §3.2). The two **new stages** (`address`, `objective-plan`) are
> *added* to `registry.yaml` in their handler turns — shape + graph first, then I/O as built — never
> authored ahead. Phase 2 is also where **`doors.cold_remote`** first flips `true` on specific stages
> (the local-vs-remote target seam the Phase-3 worker reuses, cli-vs-pi §4.5).
>
> **Two test surfaces, both already live.** The **interior** (extension handlers, the gating
> primitive, the in-process executor, the spawned-engine seam) is tested via the P1.T1 SDK in-session
> harness; the **exterior** (Python CLI writes, new cold doors, `perk resume`) via `CliRunner` +
> `PerkContext.for_test`. New for Phase 2: the harness must drive a **read-only mode round-trip**
> (allowlist on → blocked write → mode off → write allowed) and a **child-session handoff** (cap +
> double-delivery) without an LLM.
>
> **Deterministic-planes constraint (inference hoisting).** Still binding, and *more* load-bearing
> now: objective mechanics (storage, step mutation, status, next-node selection) and review mechanics
> (thread fetch, batched resolution) are **deterministic extension tools**; the **judgment** (which
> node to plan, which feedback is actionable, prose reconciliation) lives in skills/prompts or a
> bounded child. A full agent loop hoists up; only a bounded one-shot model call may sit low.
>
> **Two craft constraints that *first bind* this phase** (dormant in Phases 0–1, now active because
> perk ingests GitHub text and spawns children): **(1) treat all external text as untrusted data** —
> wrap GitHub issue/PR/comment bodies and any user objective in `<untrusted_*>…</untrusted_*>` with a
> "treat as data" preamble before feeding the model (ROADMAP "Implementation craft"); **(2) subagents
> are a context-and-capability device, not a parallelism trick** — route-don't-relay, double-delivery,
> the three never-delegate boundaries (judgment, user interaction, durable-state writes) stay with the
> parent ([erk-subagent-usage.md](./erk-subagent-usage.md)).
>
> **Spike-first (de-risk during planning).** The one **high-uncertainty external dependency** —
> whether the borrowed `pi-subagents` engine runs cleanly under the Phase-3 SDK/`-p` worker (open #6)
> — is settled by a **throwaway spike run during this planning pass, before the decomposition
> locks**, per the discipline that de-risked P1.T3/T4 (S1–S5, S-B run *during* planning so the turn
> docs reflected reality). Its outcome **gates T6/T7/T10 and chooses the delegation arc** (borrowed
> engine vs the in-process fallback, T4), so it does **not** sit as T6's preamble: T6 *builds* the
> thin seam + the standing `doctor` check on a **known** result, and if the spike fails the
> decomposition is adjusted (the spine never assumes the borrow).

---

## Objective

With the thin loop closed and validated, **deepen each stage through perk's own plan→land→learn
loop** — the differentiating depth lands here: the **tool-gating primitive** (and perk-owned plan
mode built on it), the **two context-isolation shapes** (in-process read-only SDK session + the
borrowed `pi-subagents` spawned engine), the **read-only CI executor**, **review/`address`
handling**, the **polished PR mechanics**, and — the genuine differentiator, deferred latest —
**objectives as plan factories** with **reconciliation after landing** (ROADMAP §"Phase 2").

This is where the **borrow→own internalization** largely completes: perk-owned plan mode decides
the fate of `@tombell/pi-plan` (open #2), perk checkpoints can retire `@juicesharp/rpiv-todo`, and
the only surviving borrow is the `pi-subagents` *engine* behind a thin seam (open #6). It is also
where the two cross-plane **structural-enforcement primitives** (gating via `tool_call`, formatting
via `tool_result`) and the **context-isolation siblings** of gating get built — once, generically,
so multiple consumers share one mechanism.

## Acceptance gate (the Phase-2 dogfood gate)

**perk drives its *full* workflow on itself.** On a real perk change: an **objective selects the
next plan** (the plan factory), the **read-only CI executor iterates** (Run→Report→Fix→Verify), a
**review is classified and resolved** (`/address` in an isolated child), and **objective prose
reconciles after landing** — end to end, on perk's own repo, with each stage's transitions gated
structurally (read-only modes enforced by tool gating, not prompting). `rpiv-todo` checklists are
retired in favor of perk-owned checkpoints; the borrow→own internalization is largely complete.

**Incremental dogfood, not just the end gate.** Each turn rides the loop the previous turns
deepened: the post-edit formatter (T3) improves every later implement; the CI executor (T5) iterates
on every later turn's tests; `/address` (T7) classifies the review of every later PR. By the
objective turns (T9–T11) perk is authoring its own remaining work *as objective nodes*.

## Turn decomposition

The dependency spine has a keystone and two roots. **T1 (gating primitive)** is the keystone —
plan mode (T2) and the CI executor (T5) both consume it. The two **context-isolation shapes** are
roots: the in-process session (T4) feeds the CI executor (T5); the spawned engine (T6) feeds
`/address` (T7). **T3** (formatting), **T8a/b** (PR depth), and the **T8c** CLI/config slice are
independent of the gating arc. **Objectives (T9–T11)** come last by design — they need a real
plan→land pipeline to prove the plans they emit are useful (ROADMAP open #4). **T12** is the gate.
The borrowed-engine arc (T6/T7/T10) rests on the **planning-pass spike** above, not a mid-phase turn.

### P2.T1 — Tool-gating primitive (the keystone)
The reusable read-only-mode primitive, designed **once and generically** so the same machinery
powers perk-owned plan mode *and* the read-only CI executor (PRIOR_ART §5). Built first because its
two consumers (T2, T5) now exist.
- **Structural enforcement, not prompting** (ROADMAP "Implementation craft"): a `setActiveTools`
  allowlist + a `tool_call` bash **sub-allowlist** + `{ block, reason }` on unsafe calls (the
  `go-to-bed.ts` half) — the model **cannot** proceed by being persuaded. Pi's `examples/plan-mode/`
  is the **complete authoritative recipe** and `examples/preset.ts` generalizes it (model + thinking
  + tools + instructions, with **snapshot-then-restore** and project-overrides-global config) — pi
  best-practices §5.
- **Persist/restore + context hygiene:** persist the active mode in `perk:workflow-state` (§8.3) and
  restore on `session_start`/`session_tree`; a hidden `before_agent_start` mode-context; a `context`
  **strip-when-off** so mode bookkeeping never pollutes the window (per `goal.ts`).
- **Headless-fail-safe** (`ctx.hasUI`): gating is the *more* dangerous direction to get wrong — a
  failure must fail **closed** (stay read-only), never silently open.
- **Scope:** the generic primitive only; its two consumers land in T2 and T5. Tested via the P1.T1
  harness (read-only round-trip: allowlist on → blocked write → mode off → write allowed). No new
  registry stage — modes attach to existing stages' `mode` field.
- *Depends on Phase 1.*

### P2.T2 — Perk-owned plan mode + deepen `/implement` warm path *(internal seam available)*
The first consumer of T1's primitive, and the **borrow→own decision point** for `@tombell/pi-plan`.
- **T2a — Perk-owned plan mode** (open #2): build plan mode on T1's primitive and **decide
  internalize vs keep-wrapping `pi-plan`** — an evidence-based call after a full loop of use, made
  **in this turn's doc** (decide-then-build). Tie perk-owned plan mode to `/plan-save` + GitHub
  state; if internalized, **retire P1.T3b's `isPlanModeActive` soft coupling** (the detection of
  pi-plan's persisted `plan-mode-state` entry) and own the `enabled` flag directly. Fills the `plan`
  stage's deferred state-I/O. Also **port project-local workflow config** here — the old
  `.erk/prompt-hooks/*` markdown becomes **extension-injected config at the right workflow point**
  via `before_agent_start` / `resources_discover` (pi §12), generalizing the same mode-context
  injection machinery this turn already owns (ROADMAP §"Phase 2").
- **T2b — Deepen `/implement`'s warm path** with the `ctx.newSession` / handoff pattern for a fresh
  context (pi best-practices §8) — the **in-process twin of the Phase-1 CLI cold door**. The warm
  `/implement` graduates from P1.T4b's guard-only refusal to an actual in-session fresh-context
  handoff (honoring the same handoff contract: cap visible output, full state in the worktree, verify
  the handoff). This is a **non-trivial door-legality shift, not bookkeeping**: P1.T4b made warm
  `/implement` *guard-only* (it refuses the plan→implement jump), but an in-session `ctx.newSession`
  handoff *is* a legal fresh-context path — so the turn doc must **resolve whether/how**
  `implement.doors.warm` flips, not assume it.
- **T2c — Perk-owned checkpoints** (the `rpiv-todo` replacement; ROADMAP internalization schedule):
  once perk owns the implement phase, **implement-progress tracking belongs to perk** — a perk
  checkpoint/overlay seeded from plan-mode §5's `turn_end`-scans-`[DONE:n]` progress pattern,
  persisted in `perk:workflow-state` and restored on both entry points. **This is what T12 retires
  `rpiv-todo` in favor of** — the retirement is conditional on this landing.
- *Depends on T1.*

### P2.T3 — Deterministic post-edit formatting (the `tool_result` middleware)
The Pi analogue of erk's PostToolUse Ruff-on-edit (PRIOR_ART §7): run the project formatter
automatically after `edit`/`write`, so **formatting never becomes a CI iteration**.
- The **middleware-style use of `tool_result`** — distinct from T1's `tool_call` gating primitive
  (the two structural-enforcement primitives are siblings, built apart on purpose).
- Reads the project formatter from config (the existing ruff/prek wiring); headless-safe; never
  blocks the edit, only formats after it. Small, independent, high-value early — every later turn's
  implement benefits. Tested via the P1.T1 harness (edit → formatter ran).
- *Depends on Phase 1. Independent of the gating arc — though numbered T3, it should land **as early
  as T1 allows** (right after the primitive), since its benefit compounds over every later implement;
  the number reflects grouping, not a dependency.*

### P2.T4 — In-process read-only SDK session (context-isolation primitive #1)
The **perk-owned** context-isolation shape — deterministic, in-process, no extra process boundary
([erk-subagent-usage.md](./erk-subagent-usage.md)). The right shape for the most test- and
determinism-sensitive consumer (the CI executor, T5).
- `createAgentSession` with `tools: ["read", "grep", "find", "ls"]` (pi best-practices §2) — a
  read-only session spun purely at the SDK level, the alternative to in-session gating where
  determinism matters most.
- **The handoff contract** (shared with the spawned shape, T6): **cap model-visible output, keep the
  full result in `details`/a scratch file, verify the handoff, return double-delivery** (compact
  prose for the human + a structured block for the orchestrator). **Route, don't relay** — the
  child's raw data never enters the parent.
- Tested via the P1.T1 harness (child handoff: cap + double-delivery, no LLM). Substrate only — its
  consumer is T5.
- *Depends on T1 (shares the read-only enforcement discipline).*

### P2.T5 — Read-only CI executor
The Run→Report→Fix→Verify cycle in a tool-gated, in-process read-only context — structurally
preventing the "auto-fix trap" (blind `--fix`, broad excepts, suppressed warnings) and keeping noisy
test output out of the main context (PRIOR_ART §5).
- **Composition:** T1's gating primitive + T4's in-process read-only SDK session (perk-owned,
  deterministic — **not** the spawned engine). The **executor reports** failures; the **parent agent
  analyzes and fixes**; the executor **re-verifies**.
- **Two working controllers for the cycle** (agent-stuff §9, §11): `loop.ts`'s
  iterate-until-`signal_success` loop, and `review.ts`'s `navigateTree` branch-and-return sub-session
  (run the read-only pass in a child branch against a rubric, inject only the summary).
- **Untrusted/scoped agents:** project-supplied agents/prompts are untrusted — gate them behind a
  scope flag + confirm (the first consumer of the untrusted-input discipline).
- *Depends on T1, T4.*

### P2.T6 — Spawned delegation engine (context-isolation primitive #2; borrow `pi-subagents`)
**Borrow the engine, own the defs** (open #6). `pi-subagents` already implements every
[erk-subagent-usage.md](./erk-subagent-usage.md) principle (tool-allowlist gating, `file-only`
route-don't-relay handoff, `outputSchema`-enforced structured output, model tiering + fallback,
depth/recursion guards, worktree-per-parallel-writer, `ctx.hasUI`-clean headless) — perk borrows
**only the engine**, behind a **thin seam** (one `subagent` tool + a directory of agent defs).
- **Built on the planning-pass spike** (open #6; see "Spike-first" in the preamble): the
  `pi-subagents`-under-the-worker spike runs **during planning, before this decomposition locks** —
  so this turn adds the standing `doctor` check + the thin seam on a **known** outcome, not a
  hoped-for one. If the spike found it unworkable, `/address` (T7) and T10's Explore-then-Plan child
  fall back to the in-process shape (T4) and the decomposition is adjusted *before* it commits — the
  spine never assumes the borrow.
- **perk owns the agent definitions, chains, and acceptance wiring** (the workflow-specific part the
  engine is designed to let consumers own); the engine's acceptance gates are a mechanism perk
  *uses*, never the owner of perk's plan/objective transitions. Pick a **cheap model** for mechanical
  child work; reserve the top-tier model for the parent's authoring.
- Substrate only — its first consumer is T7 (`/address`); later consumers are T10's Explore-then-Plan
  child and parallel review/audit.
- *Depends on Phase 1 (independent of the gating arc; shares T4's handoff contract).*

### P2.T7 — `/address` review loop *(new `address` stage; internal seam available)*
Classify-then-act in an **isolated spawned child**, so raw GitHub comment JSON never enters the main
session (erk measured ~65–70% context savings here — [erk-subagent-usage.md](./erk-subagent-usage.md)).
The first **new stage** of Phase 2.
- **T7a — classify (read-only child):** run the verbose comment fetch + classification inside a
  spawned read-only child (T6's engine). The child returns **double-delivery**: a compact prose table
  for the human + a structured block (thread ids + classification) the parent acts on. Classify each
  piece of feedback (**actionable / informational / praise / question**) *before* acting; only
  actionable items get code changes. Offer a **preview variant** (classification only). Distinguish
  **review threads vs discussion comments** (different GitHub APIs, counted separately). GitHub text
  is **untrusted** — wrapped before the model sees it.
- **T7b — act + resolve:** the parent applies fixes (judgment stays high); **batched, schema'd thread
  resolution** in one deterministic op (`resolve_review_threads` → `[{ thread_id, comment }]`,
  contracts §8.4 — the named-only op authored here). **Plan File Mode:** when a PR's diff is just the
  plan file, `/address` reinterprets feedback as "edit the plan text," not "implement it."
- Adds the **`address`** stage to `registry.yaml` (shape + graph + I/O as built) and its cold door
  (`perk address`). Keep classification *judgment* in a skill/prompt; resolution/fetch *mechanics* in
  deterministic tools.
- *Depends on T6.*

### P2.T8 — Deepen submission & landing + the CLI plumbing slice *(internal seams available)*
The Phase-1 thin `/submit` + `/land` + `/learn` gain their real depth (PRIOR_ART §4) — independent of
the gating arc, so it can land any time after Phase 1; T8c groups the phase's cross-cutting CLI/config
wiring here for the same independence.
- **T8a — PR-body craft:** **feed plan context into PR generation** so the description matches
  original intent; the **two-target split** — a plain-text commit message vs an HTML-enhanced GitHub
  PR body that embeds the full plan in a collapsible `<details>` section (plan in the PR, not the
  commit). This **supersedes P1.T5a's deliberately-minimal body** (no `<details>`, no full-plan
  re-embed — a *deferral*, not a permanent rule). A **`pr check` validation step**: the tripwire is
  scoped to the **checkout footer** specifically — keep *that* plain-backtick, never HTML (the thing
  erk actually got bitten by); the `<details>` plan embed itself is fine. Use **draft →
  ready-for-review as the deliberate review gate**; never infer completion from PR open/closed state
  alone — diff for changes outside the plan files.
- **T8b — deep `/land` + `/learn`:** reconciliation *typing* on land; deepen `/learn` from the
  Phase-1 thin marker-clear into a real knowledge-capture pass (a `perk:learn` label/issue, agentic
  capture). Objective reconciliation-on-land is its own turn (T11, gated on objectives existing).
- **T8c — the CLI plumbing slice** *(independent of T8a/b; grouped here as the phase's CLI/config
  wiring)*: add the **local-vs-remote target option to *every* stage launcher** (cli-vs-pi §4.5) and
  flip **`doors.cold_remote` `true`** on the stages that can run remote — the **seam the Phase-3
  worker reuses** (Phase 2 *builds* the seam + resolves a target; the process that *drives* the
  remote target is Phase 3). The Phase-1-blocked `--remote` stub graduates to a real target resolver.
  Pairs with the new cold doors `perk address` (T7) / `perk objective-plan` (T10) that the ROADMAP
  bundles into this same "CLI slice."
- *Depends on Phase 1.*

### P2.T9 — Objective storage + mechanics *(new — the plan factory's foundation)*
Now that the loop is closed and validated, add the **objective layer** — a long-running goal that
*generates bounded plans*, not something implemented directly (PRIOR_ART §3, the genuine
differentiator). This turn is the **deterministic mechanics** only.
- **Storage model** (carry over erk's): **frontmatter is canonical**, a rendered table is for humans,
  steps are a **flat list with phases derived from the ID prefix**. Stored as a GitHub objective
  issue (the `github.objective` state key already in the vocabulary). **Status model =
  explicit-status-only** (open #3 — simpler, trap-free; drop erk's two-tier infer-from-PR-column).
- **Mechanics (deterministic tools):** storage, step mutation, status, **dependency-graph next-node
  selection** (for `/objective-plan`, T10). **Budget accounting** (sum assistant token usage on
  `agent_end`, track elapsed wall-time, surface in a status line — agent-stuff `goal.ts`,
  best-practices §11). **Threshold-triggered compaction** for the long-running loop
  (`ctx.getContextUsage` + `ctx.compact`, or a `session_before_compact` summary on a cheaper model —
  pi best-practices §9).
- Adds the **`active_objective`** field to live use in `perk:workflow-state` (§8.3, reserved since
  Phase 0). No new stage yet — that is T10.
- *Depends on Phase 1.*

### P2.T10 — `/objective-plan` factory + completion-audit *(new `objective-plan` stage)*
The objective *transition* surface — select the next node and emit a bounded plan; the judgment layer
on T9's mechanics.
- **The plan factory:** `/objective-plan` selects the next actionable node (via T9's dependency-graph
  mechanics) and emits a **bounded plan** through the existing `plan → save` spine — so every plan it
  produces rides the validated loop. Optionally an **Explore-then-Plan child** (T6's spawned engine)
  for the read-only exploration half.
- **Completion-audit contract** (agent-stuff `goal.ts`, best-practices §11): before marking an
  objective node complete, the model must build a **prompt-to-artifact checklist** mapping every
  explicit requirement to real evidence, and **treat uncertainty as not-done**. Expose objective
  transitions as **model tools whose descriptions strictly bound when they may fire** ("only when
  explicitly requested," "only when actually achieved") — not free-form prose the model interprets.
- Adds the **`objective-plan`** stage to `registry.yaml` (shape + graph + I/O as built) and its cold
  door (`perk objective-plan`).
- *Depends on T9 (and T6 for the optional Explore-then-Plan child).*

### P2.T11 — Objective reconciliation after landing
Close the objective loop: when a PR linked to an objective node merges, the roadmap reconciles
against what was *actually* built — "the roadmap is a source of truth for what exists, not just what
was intended" (PRIOR_ART §3).
- **Mechanical:** mark the node done (deterministic, on merge — ties into T8's land path).
- **Reconcilable:** the model reconciles stale objective prose against the real diff. erk's
  **section boundary** — **Mechanical** (command-updated), **Reconcilable** (LLM-updated post-merge),
  **Immutable** (never touched, e.g. historical notes) — is mirrored so reconciliation **never
  clobbers** historical notes.
- *Depends on T8 (land depth), T9 (objective storage), T10 (the node↔plan link).*

### P2.T12 — Phase-2 dogfood gate *(checkpoint)*
- Drive perk's **full** workflow on perk's own repo: an objective selects the next plan, the CI
  executor iterates, a review is classified and resolved, and objective prose reconciles after
  landing. Record the run as the gate ([planning/phase-2-gate.md], mirroring phase-0/1).
- **Retire `@juicesharp/rpiv-todo`** in favor of the **perk-owned checkpoints built in T2c**; confirm
  the borrow→own internalization is complete except the `pi-subagents` engine (kept behind its seam).
  (Retirement is **conditional on T2c landing** — if it did not, keep `rpiv-todo`; don't fake todos.)
- Reconcile `AGENTS.md`/README/`contracts`/`index` against what got built; confirm both new stages'
  per-stage state-I/O + `doors` are filled and the registry self-check passes. *Depends on T1–T11.*

## Dependencies

- **On Phase 1 (all green):** the closed spine (`plan → save → implement → submit → land → learn`),
  GitHub-backed plan storage + the plan-ref, the P1.T1 SDK in-session harness, the session-lifecycle
  gates, `perk resume`, the canonical Python GitHub gateway + the warm-door delegation pattern
  (`pi.exec` → `perk <worker> --json`).
- **On Phase 0:** `perk init`/`doctor`, the stage registry + `perk <stage>` launchers, the
  `.pi/workflow/` cache + `run_id` + `perk:workflow-state` tiers, `PerkContext`/`require_*` DI.
- **Internal:** T1 (gating) is the keystone for T2 + T5; T4 (in-process session) feeds T5; T6
  (spawned engine, spike-gated) feeds T7 (and T10's optional child); T9 (objective mechanics) feeds
  T10, which with T8 feeds T11; T3, T8a/b, and the T8c CLI/config slice are independent of the gating
  arc; T12 is the gate.
- **External borrow:** `pi-subagents` (open #6) — gated on a **spike run during planning** (then a
  standing `doctor` check, T6) that it runs cleanly under the Phase-3 SDK/`-p` worker; if the spike
  fails, the delegation arc falls back to the in-process shape (T4) **before** the decomposition locks.

## Explicitly deferred (Phase 3+)

- **The headless worker + queue** — Phase 3. Phase 2's local-vs-remote target seam (`doors.cold_remote`
  flipping on specific stages, **built in T8c**) is in place; the process that *drives* the remote
  target is Phase 3.
- **End-to-end *worker* tests** (RPC/JSON mode) — Phase 3 (Phase 2 extends the command/extension test
  layer only).
- **Migration helpers** (import existing planned PRs, translate objective markers, map residual
  `.claude` references) — Phase 3.
- **`doctor workflow` GitHub-CI smoke test** — Phase 3 (needs the worker + queue).
- **Internalizing a minimal spawn primitive** to replace the `pi-subagents` engine — only if
  weight/determinism/headless costs prove out (internalization schedule); Phase 2 keeps the engine
  behind its thin seam.
- **Per-stage state-I/O values** for the two new stages until their handler lands — filled
  turn-by-turn (T7 for `address`, T10 for `objective-plan`), never authored ahead (mirrors the
  registry, as in Phases 0–1).
- **The `objective` two-tier status model** (explicit-status + infer-from-PR-column) — deliberately
  *not* built; Phase 2 ships **explicit-status-only** (open #3) unless human-editable raw tables
  become a hard requirement.
