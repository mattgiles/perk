# Phase 2 · Turn 2 — perk-owned plan mode, warm `/implement`, checkpoints

> Implementation-level plan for **P2.T2** — the first consumer of T1's tool-gating primitive and
> the borrow→own decision point for `@tombell/pi-plan`. Landed as **three independently-green seams**
> (T2a → T2b → T2c), each with its own `scripts/verify-p2-t2{a,b,c}.sh` wired cumulatively into
> `just verify` (mirroring the P1.T4a/T4b seam discipline). All work is the session **interior**
> (TS extension), grounded in pi's `examples/extensions/plan-mode/`, agent-stuff's
> structural-enforcement patterns, and erk's `context-preservation-prompting` /
> `tool-restriction-safety` learnings.

The canonical plan (decisions D1–D4, the full key-changes list, the test plan, and assumptions)
is GitHub plan issue **#5**. This doc records the prior-art pass and the **outcomes**.

---

## 1. Prior-art pass (what exists, what we copy)

- **`plan-mode/index.ts`** — the toggle shape: `registerFlag("plan")`, a `/plan` command, a
  `Ctrl+Alt+P` shortcut, `setActiveTools` on toggle, a `before_agent_start` hidden context, a
  `context` strip-when-off filter, and `session_start` flag/state restore. perk reuses the **toggle
  surface** but layers it over T1's gate (no parallel enforcement) and adopts only the **read-only
  authoring half** (no in-session "execution mode" flip).
- **`plan-mode/utils.ts`** — `extractTodoItems` / `extractDoneSteps` / `markCompletedSteps`. perk
  copies these perk-owned (as T1 copied the regex tables) and adapts the extractor to key off
  `## Steps` rather than plan-mode's `Plan:` header.
- **`examples/extensions/handoff.ts` + pi best-practices §8** — the lossless fresh-context handoff
  (`ctx.newSession` + a seeded prompt; full state in durable storage, capped model-visible output).
- **`perk/launch.py` `_initial_prompt`** — the cold door's implement priming; T2b's
  `implementHandoffPrompt` is its in-session twin (carry the plan forward, never summarize).
- **`perk/config.py`** — the `.pi/perk.toml` + `perk.local.toml` overlay; `extension/config.ts` is
  its minimal TS twin (dependency-free TOML-subset reader for the one optional addendum).

## 2. Files

- **`extension/planMode.ts` (new)** — `registerPlanMode(pi, gating)`: `/plan` + `Ctrl+Alt+P` +
  `--plan` toggle over T1's gate; `perk:plan-context` injection keyed off read-only, stripped when
  off; `planContextContent(cwd)` appends the config addendum.
- **`extension/config.ts` (new)** — `loadPerkConfig(cwd)` + `parseTomlSubset`: the minimal config
  port (D1b).
- **`extension/checkpoints.ts` (new)** — `registerCheckpoints(pi)` + the pure helpers
  (`extractSteps`/`extractDoneSteps`/`markCompletedSteps`/`rebuildCheckpoint`); the dedicated
  `perk:checkpoint` entry.
- **`extension/planSave.ts`** — `isPlanModeActive` reads perk's read-only `mode`; the `/plan-save`
  command auto-exits the gate on success (D1a).
- **`extension/lifecycleGates.ts`** — the deepened warm `/implement` (in-worktree `newSession`
  handoff) + `implementHandoffPrompt`.
- **`extension/cache.ts`** — `readPlanBody`/`planBodyPath` (the `cache.plan` body tier).
- **`extension/index.ts`** — wires `registerPlanMode` + `registerCheckpoints`; passes `gating` to
  `registerPlanSave`.
- **`perk/init.py` + `.pi/settings.json`** — drop `@tombell/pi-plan` from the borrowed set.
- **`shared/registry.yaml`** — `plan` stage `writes: [session.workflow-state]`.
- **`shared/contracts.md` §8.3** — the three amendments (perk-owned plan mode, warm `/implement`
  handoff, checkpoints).
- **`skills/perk-plan/SKILL.md`** — the optional `## Steps` list + the `/plan-save` auto-exit note.
- **`scripts/verify-p2-t2{a,b,c}.sh`** — the three offline hard gates.

## 3. Outcomes

Built as planned across the three seams. Notes / refinements:

- **T2a — config reader is dependency-free.** Rather than pull a runtime TOML dependency into the
  published extension for a single optional string (`yaml` is the only existing runtime dep),
  `config.ts` reads the **narrow TOML subset** perk actually uses (`[section]` headers, `key =
  "basic"` / `"""multiline"""` strings, `#` comments). This honors D1b's "config stays minimal"
  more faithfully than adding a dep, and `planContextContent` `trim()`s the addendum so trailing
  newlines never matter.
- **T2a — the read-only fail-fast in `savePlan` was removed, not just reworded.** D1a requires the
  `/plan-save` command to *save while read-only and then exit*; a refuse-while-read-only guard would
  make that impossible. The `plan_save` **tool** needs no guard either (T1's allowlist makes it
  structurally unreachable while read-only). `isPlanModeActive` is retained (now reading perk's
  `mode`) and is used by the command handler to decide whether to auto-exit. Two `planSave.test.ts`
  cases were rewritten from the retired-behavior assertions.
- **T2a — `--plan` flag testing surfaced a real env-leak.** `PERK_RUN_ID` is set in any shell
  launched by `perk implement` (including the test runner), forcing the `session_start` claim path.
  The `--plan` test unsets it so `decideClaim` takes the no-op `none` path; added a `setFlag`
  harness helper (`extensionRunner.setFlagValue`) + `emitBeforeAgentStart`/`emitContext` helpers to
  observe injection/stripping.
- **T2b — dirty-tree gate is manual (belt-and-suspenders).** `ctx.newSession` is a session-replace,
  not a fork/switch, so it may not trip the P1.T4b `session_before_*` gate; the `/implement` handler
  re-checks `git status --porcelain` and refuses on a dirty tree regardless. `doors.warm` stays
  `false` — the cross-worktree jump is structurally cold-only (D2: no extension session API changes
  cwd). Added a `runCommandHandler` harness helper that records `newSession` + seeded messages so
  the handoff is asserted offline without creating a real session.
- **T2c — checkpoints seed from `cache.plan`, inert until it's materialized.** No handler writes the
  `cache.plan` body yet, so in practice checkpoints are inert today (matching D4 for prose plans);
  `readPlanBody`/`planBodyPath` add the reader seam now. The rebuild uses the **scan-after-marker**
  discipline against the latest `perk:checkpoint` entry. `@juicesharp/rpiv-todo` is **not** retired
  here (P2.T12, conditional on this seam).
- **Follow-ups flagged (unchanged from the plan):** dynamic `resources_discover` skill/prompt
  contribution (config); a `cache.plan` body materializer for live checkpoints; a perk-owned
  "update an already-saved plan" door (`plan_save` is idempotent — revising a saved plan currently
  means editing the GitHub issue by hand; eventual owner is a `plan_save`-update path or P2.T7b's
  `/address` Plan File Mode).
