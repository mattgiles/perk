# Phase 3 · Turn 10 — Typed `branchOf` seam (#226, Objective #224 Node 1.1)

## Decisions

- **One typed seam, repo-wide.** Added `branchOf(source: BranchSource): BranchEntry[]` to
  `extension/workflowState.ts` beside `BranchEntry`/`rebuildWorkflowState`. It performs the single
  unavoidable `as BranchEntry[]` assertion over `sessionManager.getBranch()`. After this turn it is
  the **sole** `BranchEntry` type assertion in the repo; the `getBranch() as unknown as
  BranchEntry[]` double-cast idiom is fully retired (`grep` returns zero matches).
- **Seam lives in `workflowState.ts`, stays SDK-import-free.** The param is a minimal structural
  `BranchSource = { sessionManager: { getBranch(): unknown[] } }`, not the SDK `ExtensionContext`,
  preserving the module's offline-testable, no-`@earendil-works/pi-coding-agent`-import discipline.
  Typing `getBranch` as `unknown[]` makes the body a single `as BranchEntry[]` (no `as unknown as`).
- **`ExtensionContext` and the harness `session` both satisfy `BranchSource`**, so production sites
  stay `branchOf(ctx)` and tests use `branchOf(session)` / `branchOf(h.session)`.

## What got built

- `workflowState.ts`: `BranchSource` interface + `branchOf` accessor with the explanatory comment
  about why the assertion is irreducible.
- `workflowState.test.ts`: new `branchOf` case (returns entries; composes with
  `rebuildWorkflowState`).
- Deleted the two duplicate local `branchOf` helpers (`checkpoints.ts`, `lifecycleGates.ts`).
- Migrated all production sites through the import: `address`, `learn`, `ciExecutor`, `planMode`,
  `objectivePlan`, `objectiveAuthor`, `bindingDelivery`, `todoAdapterJuicesharp`, `planSave`,
  `objectiveSave`, `index`. Dropped/kept the `BranchEntry` type-import per the plan's table.
- `objective.ts`: renamed local `branchOf(ctx): ScanEntry[]` → `scanBranchOf` (its two
  `rebuildBudget` callers updated); `activeObjective` now uses the shared `branchOf`; dropped its
  `BranchEntry` import.
- Test harness + `objective.test.ts` accessor casts swapped to `branchOf(...)`.

## Deferrals (flagged, not omitted)

- `worker.ts` `getBranch() as never` — worker has no `ExtensionContext`/`BranchEntry` coupling; left
  as-is.
- `objective.ts` `scanBranchOf` (`ScanEntry[]`) — a different, richer budget-scan type, not a
  `BranchEntry` seam; left as a separate concern.
- `BranchEntry` literal constructors in tests and `checkpoints.test.ts`'s `as never` casts — not the
  retired idiom; left as-is.

## Cross-plane

- None. Purely internal to the TypeScript extension plane; no `shared/contracts.md` amendment, no
  Python-plane change. Behavior unchanged.

## Verification

- `grep -rn "as unknown as BranchEntry\[\]" extension/` → zero matches; the only `as BranchEntry[]`
  is inside `branchOf`.
- `just ci` green: Biome + tsc clean, `node:test` + `pytest` pass.
