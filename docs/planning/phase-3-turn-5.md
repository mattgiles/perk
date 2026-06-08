# Phase 3 · Turn 5 — auto-drive `/objective-reconcile` after landing an objective-linked PR

GitHub plan **#154**. Today, when `/land` (or the `land` tool) merges a PR whose plan was linked to
an objective node, the warm door marks the node `done` and appends a **copy-pasteable**
`/objective-reconcile #<n>` nudge to its success text — the reconcile pass only fired if the user
manually ran that command. This turn makes the reconcile pass **fire automatically**, following
perk's established warm-door driving pattern (a command/tool sets up state and injects guidance via
`pi.sendUserMessage`; the model then performs the work via the canonical `reconcile_objective` tool).

## Decisions

- **Export `reconcileGuidance`** from `extension/objectivePlan.ts` (was module-private, used only by
  the `/objective-reconcile` command). No behavior change to the body — the land surface needs to
  inject the identical message. No circular-import risk (`objectivePlan.ts` does not import
  `land.ts`).
- **New exported helper `driveReconcileAfterLand(pi, ctx, details)`** in `extension/land.ts`:
  - Guard mirrors the *exact* old nudge condition: `details.ok === true`, objective present,
    `objective.number !== null`, `objective.nodes_marked.length > 0`.
  - Message is `reconcileGuidance(String(number)) + bindingSuffix(cwd, "command:objective-reconcile")`
    — byte-for-byte what `/objective-reconcile` injects, so the `perk-objective-reconcile` skill
    pointer rides the binding suffix (never hardcoded).
  - Delivery branches on `ctx.isIdle()`: idle (`/land` command) → immediate `sendUserMessage`;
    streaming (`land` tool) → `sendUserMessage(msg, { deliverAs: "followUp" })` (delivered after the
    terminating land batch).
- **`landPr` stays drive-free** — it merges, sets `pending-learn`, builds success text + `details`,
  and returns. The success-text objective line now reports auto-reconciliation
  (`… marked done — reconciling the roadmap against the merged diff.`) instead of the copy-pasteable
  `/objective-reconcile #<n>` nudge. Keeping `landPr` drive-free preserves it as directly
  unit-testable (merge/marker/learn-consume coverage).
- **Wire both surfaces:** the tool `execute` calls `landPr` then `driveReconcileAfterLand` then
  returns the result (still `{ terminate: true }` on success); the `/land` command handler calls the
  helper after notifying. `land` stays terminating — `terminate` only skips the *automatic*
  follow-up LLM call, while an injected `followUp` user message is a separate deliberate new turn, so
  the two compose cleanly.

## Tests (offline, `node:test`)

- **Reworked the objective land test** into a direct `landPr` unit test (a stub `pi.exec` resolving
  the objective fixture + a minimal `ctx`), asserting the auto-reconcile success text and *absence*
  of `/objective-reconcile #`. Routing it through `invokeTool` would now fire a real turn the keyless
  harness can't service.
- **New `driveReconcileAfterLand` unit tests** with a spy `pi`: no objective → not driven; failed
  land → not driven; idle → immediate (`options` undefined); streaming → `deliverAs: "followUp"`.
- **New `reconcileGuidance("5")` pure test** in `objectivePlan.test.ts`: names `#5`, carries the
  `gh pr diff` / `perk objective show 5` / `reconcile_objective` cues, contains no hardcoded skill
  pointer.
- Existing behavioral land tests unchanged (all use non-objective / empty-`nodes_marked` fixtures, so
  the helper short-circuits and no turn fires).

## Same-turn doc updates

- `shared/contracts.md` — the P2.T11 "Mechanical (on land)" bullet and the T11a Mechanical paragraph
  now describe the auto-drive (`driveReconcileAfterLand`, the `followUp`/immediate split, and that
  `land` stays terminating).
- `README.md` — objectives walkthrough now says reconciliation is automatically driven on land.

## Outcomes

Landed as planned, no deviations. `just ci` green.
