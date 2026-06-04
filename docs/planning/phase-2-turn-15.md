# Phase 2 · Turn 15 — Close the checkpoint loop: teach the marker protocol, add an in-progress state, and a coarse fallback

> The decision-complete plan lives on GitHub plan **#32** (`plan-body` block). This doc records the
> prior-art pass, the turn's decisions, and — written **after** the work lands — the as-built
> **outcomes**. (Planned/saved as "P2.T13", but turns 13 and 14 landed first on `main`, so this
> turn took the next free number, **T15**.)

## 1. Objective

perk-owned checkpoints (`extension/checkpoints.ts`, P2.T2c) were effectively dead in practice: they
only render when a plan carries a `## Steps` list (prose plans showed **nothing**), nothing told the
implement session to emit the `[DONE:n]` markers that advance them, and the model was binary
(done/not-done) with no "currently working on" signal. This turn closes the loop end-to-end:

1. **Teach the implementer the marker protocol** via both `_implement_prompt` (`perk/launch.py`) and
   a new `perk-implement` skill.
2. **Add an explicit in-progress state** via a `[WIP:n]` marker plus a derived `current` step,
   rendered with a ▶ glyph.
3. **Add a coarse fallback** so an active prose plan always surfaces *something* (`📋 <stage>`) in
   the status bar instead of going dark.

## 2. Decisions

- **(1) Teach in both places.** The launch prompt is the only guaranteed load; the skill carries the
  detail. `_implement_prompt` gains a concise progress-marker paragraph + a `perk-implement` skill
  pointer (mirrors `_address_prompt`).
- **(2c) Coarse status, not auto-derivation.** When no `## Steps` exists but a plan is active, show a
  coarse stage label from the handoff (`readHandoff(cwd, run_id).stage`, falling back to `"active"`)
  rather than inventing steps from `## Key changes`.
- **(3) Explicit `[WIP:n]` + derived fallback.** `current` is the latest live `[WIP:n]` after the
  marker (existing + incomplete), else the lowest incomplete step, else `null`. Completion always
  wins — ▶ never renders on a completed step.
- **`current` is derived, not persisted.** It is recomputed deterministically on every rebuild from
  the after-marker text + completion, so only `steps` continues to live in the `perk:checkpoint`
  entry (no entry-shape change, no migration).
- **A new skill needs no `perk/init.py` change** — `package.json` `pi.skills` already globs
  `./skills`.

## 3. Key changes

- `extension/checkpoints.ts`: `CheckpointState` gains `current: number | null`; new pure helpers
  `extractWipSteps` / `latestWipStep` / `computeCurrent`; `rebuildCheckpoint` derives `current`;
  `progressLine` / `renderStatus` / `/checkpoints` render `☑/▶/☐` + the `done/total · ▶n` summary;
  a coarse-fallback path (workflow-state + handoff stage) wired into `session_start`, `session_tree`,
  and the inert `turn_end` branch.
- `perk/launch.py`: `_implement_prompt` teaches the `[WIP:n]`/`[DONE:n]` protocol + points at the
  `perk-implement` skill.
- `skills/perk-implement/SKILL.md`: new skill documenting the implement flow + marker protocol.
- `skills/perk-plan/SKILL.md`: mentions `[WIP:n]` and nudges `## Steps` for multi-step work.
- `shared/contracts.md`: the "Checkpoints" section amended for the `[WIP:n]`/`current`/▶ model, the
  coarse fallback, and that the protocol is taught to the implement session.
- `extension/testing/harness.ts`: `scaffoldRepo` accepts an optional `stage`; the headful UI context
  records `setStatus`/`setWidget` calls (`statuses` / `widgets` on `PerkSession`).
- Tests: `extension/checkpoints.test.ts` (WIP/current derivation + coarse fallback);
  `tests/test_launch.py` (implement prompt teaches the protocol) — these framework suites **are**
  the regression coverage (no `scripts/verify-*.sh`; see the outcomes note below).

## 4. Outcomes (as-built)

Implemented as planned. Notes / minor deviations:

- The `turn_end` handler now **always re-renders** (not only on completion advance), so a `[WIP:n]`
  declared mid-turn updates the ▶ marker without a step completing; it still only **appends** a new
  `perk:checkpoint` entry when a step actually advances (avoids high-churn appends).
- `renderStatus` gained a `branch` parameter (it needs the branch to compute the coarse descriptor
  via `rebuildWorkflowState` + `readHandoff`); all three handlers pass the branch they already hold.
- The coarse-fallback test asserts against newly-recorded `statuses`/`widgets` on the harness rather
  than `notify` (status-bar rendering, not a notification).
- **Verify-script step dropped on rebase.** The plan's step 7 added a `scripts/verify-p2-t13.sh`
  hard gate + `justfile` wiring, but PR #33 ("Retire `scripts/verify-*.sh`") landed on `main` first
  and removed the entire `scripts/` verify tree + the `just verify` recipe. Per the new
  regression-testing convention (coverage lives in `pytest` + `node:test`, gated by `just ci`), the
  verify script was **not** carried forward; the `checkpoints.test.ts` + `test_launch.py` cases are
  the gate.
- **Renumbered T13 → T15.** The plan was saved as "P2.T13", but turns 13 (`/plan-save` re-save fix)
  and 14 (CLI aliases) landed on `main` first; this turn took the next free number.
- All offline gates green: `checkpoints.test.ts` (14 tests), `tests/test_launch.py` (22),
  `just ci` (lint + typecheck + test) green.
