# Phase 3 · Turn 12 — Headless-safe `report()` seam (Objective #224, Node 1.2)

Plan: GitHub #231.

## Decisions

- **One report seam, repo-wide.** Added `report(target, scope, severity, message, opts?)` to
  `extension/report.ts`. It builds the `perk: <scope> — <message>` prefix, routes
  `hasUI ? ui.notify : console.error` (the headless-fail-safe invariant), and returns the prefixed
  string. `opts.alsoLog` additionally writes stderr when headful (so cold-door failures still land
  in run logs in a TUI). Minimal structural `ReportTarget` interface (`hasUI` + `ui.notify`) so
  `ExtensionContext` satisfies it and tests fake it — mirrors Node 1.1's `BranchSource`/`branchOf`.
- **Routing rule = pure either/or for all severities, plus opt-in `alsoLog`.** This reproduces the
  cold-door reporters' notify-if-UI-AND-always-stderr behavior byte-for-byte via `{ alsoLog: true }`.
- **Migrate the P1 shape only.** Same-message, severity-driven reports/announces/errors. P2
  command-echoes (different text per branch + `pi.sendUserMessage`) and P3 self-prefixed
  renders/background catch-logs are deliberately out of scope.

## What got built

- `extension/report.ts`: `Severity` type, `ReportTarget` interface, `report()` function.
- `extension/report.test.ts`: 8 cases — headful/headless × alsoLog, return value, severity
  pass-through (info/warning/error). Stubs `console.error`, fakes `ReportTarget`.
- **Cold-door reporters** (`{ alsoLog: true }`, output unchanged): `submit.ts`, `ready.ts`,
  `land.ts`, `address.ts`, `learn.ts`, `objectiveSave.ts`, `planSave.ts` (no-plan guard),
  `index.ts` (`workflow-state linkage error` scope), `objectivePlan.ts` ×2 (`objective-plan`,
  `objective-reconcile`). Each local `reportError` closure body now delegates to `report(...)`;
  the `full`/`if (ctx.hasUI)…console.error` duplication is gone.
- **Either/or + notify-only P1 sites** (de-prefixed embedded `"perk: "`): `objective.ts`
  (`reportError` helper + the three status/clear/activate announces), `lifecycleGates.ts`
  (`DIRTY_MESSAGE`/`HANDOFF_DIRTY_MESSAGE` constants de-prefixed; `lifecycle`/`implement` scopes),
  `planMode.ts` announce, `checkpoints.ts` deferral announce (list render left — P3),
  `learnDocs.ts` four parsed-failure guards (echo left — P2), `objectivePlan.ts` two "no objective"
  guards (echoes left — P2), `planSave.ts` final command-result echo.

## Behavior notes / deviations

- `planSave.ts` final echo now routes through `report()`: the headful notify gains the
  `perk: plan-save — ` prefix (previously bare) and the headless path now logs `info` too
  (previously `severity !== "info"`-gated). Both are the intended "inherit fail-safe for free"
  change per the plan; tests substring-match the preserved tokens and stay green.
- No separate in-`savePlan` failed-advance notify existed beyond `reportError` (already migrated),
  so the plan's conditional "any" warning had nothing to migrate.

## Cross-plane

- Interior-only (TypeScript extension plane). No `shared/contracts.md` change. `docs/learned/`
  handled by the post-merge `/learn` factory.

## Verification

- `just ci` green: ty + tsc clean, Biome clean, pytest 720 passed, `node:test` 362 passed
  (8 new `report.test.ts` cases).
