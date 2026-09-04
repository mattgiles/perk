---
title: Extension consolidation seams — minimal structural interfaces, the report()/EntrySink seams, the P1/P2/P3 triage
read_when: You are collapsing a repeated extension idiom into one tested seam (report()/branchOf/branchCarries), extracting a tool's execute core, or evacuating survivor code from a retiring module.
cluster: pi-extension
---

# Extension consolidation seams

When the same context-dependent idiom (notify-if-UI-else-log, branch lookup, strict workflow-state
append, …) is repeated across the extension, perk collapses it into one small tested seam. This
doc captures the *shape* of those seams — the recipe, the traps, and the triage for sites that
don't fit — distilled from the headless-safe `report()` seam (`extension/surfaces/report.ts`), its
predecessor `branchOf`/`BranchSource`, and the `appendWorkflowState`/`EntrySink` strict-append seam
(`extension/substrate/workflowState.ts`).

## The minimal-structural-interface recipe

Export a **tiny structural interface** that the real `ExtensionContext` satisfies *and* a test fake
implements trivially — `ReportTarget` (`hasUI` + `ui.notify`) in the report seam, mirroring
`BranchSource`/`branchOf`; `EntrySink` in the workflow-state seam is the third realized instance of
exactly this recipe. This keeps the seam unit-testable offline (headful/headless × options ×
severity) without importing the SDK context. Return the built string from the seam for reuse as
tool-result text.

Corollary for plan handoffs: **when a plan names SDK types for an exported core, narrow the landed
signature to the minimal structural slices the sibling seams already export** (`EntrySink`,
`BranchSource`, `ReportTarget`, `SessionDataCtx`). Callers pass `pi`/`ctx` unchanged — plan
fidelity is preserved — and the core's offline tests reuse the existing fakes with no harness
(the `writePlanDraft` precedent: spec'd against `ExtensionAPI`/`ExtensionContext`, landed against
the slices).

`branchCarries` is a further census entry: a repeated context-dependent idiom (2 hand-rolled
duplicates + 6 new call sites) collapsed into one tested pure function in
`extension/substrate/workflowState.ts` alongside `branchOf`/`appendWorkflowState`, per exactly
this recipe; the pattern's semantics (the once-only injection dedup) live in
`pi/context-injection.md` — cross-ref, don't duplicate.

The recipe extends to **extracting a tool's execute core for testability**: type the injected
dependency as the minimal structural slice (e.g. the one-method `{ review(plan, signal) }` in
`executePlanReview`), not the concrete collaborator — the fake then collapses an entire layer
(bus + envelope + timers) per test instead of re-implementing the collaborator. See
`workflow/plan-review-flow.md` for the realized testing recipe.

## Extract-to-survive-retirement

A seam-extraction variant whose forcing function is not a repeated idiom but **a consumer module
scheduled for wholesale deletion**. Instance: the `/review` door (the since-deleted
extension/doors/review.ts) was retired once the surface-named doors owned the flows.
Everything the surviving `/pr-review-terminal` door needed — the PR-token arg grammar
(`parseReviewArgs`), the strict checkout decode, the `hunk --version` probe, and the launch
handoff — had been extracted to `extension/doors/hunkHandoff.ts` (live today as
`extension/pi/v1/codeReview/checkout.ts`) **at the survivor's birth**,
with the retiring module importing it back (behaviorally byte-stable; the proof was that the
door's test file needed only import-path churn), so the retirement completed as a wholesale
`rm`. The hosting rule: **nothing a survivor needs may live in a module slated for deletion** —
extract when the survivor is born, parameterizing call-site differences (the launch handoff grew
a report-scope param) rather than duplicating, so the later retirement is a wholesale `rm`
instead of a second extraction under pressure.

## The type-only-import cycle break

When a vocabulary type moves to a new owning module that the old module still references, import
it back **type-only**: the new owner imports the old module's values normally; the old module's
`import type { … }` of the moved type is erased at runtime, so no cycle exists. Realized when
`plan_review` moved out of the plannotator adapter — `planReview.ts` imports the bridge (a value)
from `planAdapterPlannotator.ts`, and the adapter imports `ReviewOutcome` type-only back.

## The "pure module + effectful seam" reconciliation

A module headered "pure, fs-light, unit-testable" can absorb an effectful helper **without losing
the property** if effects enter only through structural slices (`EntrySink`, `BranchSource`,
`ReportTarget`) — **testability-with-fakes is the real invariant, not purity**. Amend the module
header to say so rather than splitting the module.

## The strict-append seam (`appendWorkflowState`)

The helper shape that worked for the verified workflow-state append:

- **Never throws:** the whole append + rebuild + compare runs in one try; the catch reports
  (`<field> append threw — …`) and returns false.
- **Boolean return** so the caller can gate establish-before-consume follow-ups (e.g. only mark a
  handoff consumed after the append verified).
- **Idempotence pre-checks stay caller-side** ("append iff rebuilt differs") — pushing
  skip-if-equal into the helper was considered and rejected to keep the seam single-purpose.

Two non-obvious facts around it:

- **Verified-linkage tiering:** strict read-back applies only to the four contracted linkage
  fields. Mode writes, activation appends, the fork append (LWW), and budget appends deliberately
  stay un-verified — do **not** "helpfully" migrate them onto the seam; the contract distinguishes
  the tiers.
- **Object-valued read-back is reference-identity:** `rebuildWorkflowState` copies `entry.data` by
  reference, so a default compare on an object field passes iff both sides share the same object
  reference — build the payload object once and pass it to both the append and the expectation. A
  deep compare is needed only when the expected value comes from a *different* source (e.g.
  decoded from the cold door, where `planRefsEqual` applies).
- **Object-valued fields need a custom `equals`** (second confirmed instance after
  `planRefsEqual`): the `session_artifacts` map append passes an identity-subset comparator —
  per-name `{run_id, digest}` plus key-count — not a deep-equal of the whole object (timestamps
  and informational fields may drift). Note the exact-key-count strictness: an interleaved append
  between rebuild and read-back spuriously fails the strict append — loud and fail-open, known
  and acceptable.

## Aspirational-comment fiction is a migration signal

When extracting an idiom, **grep for comments *claiming* the idiom** — they mark sites that
intended to adopt it but never did (a "strict read-back via rebuild" comment described nonexistent
behavior until the seam landed; the extraction was the right moment to make it true). Minor
corollary: when a plan prescribes a local variable name, check the target scope for collisions
first.

## "One idiom" is often 1 base + 1 superset — prefer an opt-in flag

The framing "the idiom is `ctx.hasUI ? ctx.ui.notify : console.error`" was demonstrably wrong: the
dominant error shape (the cold-door error closures) both notified-if-UI **and** always
console-logged, so failures land in run logs even in a TUI. The reconciliation was an opt-in
`alsoLog` boolean on one `report()` — preserving byte-for-byte existing behavior while keeping a
single seam, cleaner than forking the API or forcing every caller onto one shape. **Always grep the
actual call sites before trusting a one-line framing of "the idiom."**

The reconciled report-routing law, stated once and hasUI-first (#1761): sinkless lifecycle
contexts append no transcript-detail entry; tools retain complete Results; a headful RPC caller
may mirror a complete diagnostic to stderr with `alsoLog`. Repeated charter prose must be
reconciled against this canonical rule — docs checks cannot detect semantic contradictions
between paragraphs.

## The de-prefixing trap when a seam owns the prefix

`report()` owns the `perk: <scope> — ` prefix, so any migrated message that *embedded its own*
`"perk: "` double-prefixes — strip it at migration. Scope/message token overlap then yields cosmetic
doubling (scope `checkpoints` + a message starting `checkpoints deferred` — the checkpoints module
is since removed; the trap generalizes). That drift is acceptable
**only because** the suite substring-matches meaningful tokens, never full-string equality — verify
that assumption per-suite before accepting cosmetic drift.

## report()-rollout gotchas (from the full notify migration)

- **Local `report` bindings shadow the seam**: a handler that builds a local named `report` (e.g.
  a selfcheck report object) shadows the imported seam — import as `report as reportTo` in such
  modules. Expect recurrences as report() routing spreads to new handlers.
- **`failFor` is now the ONLY failure-surfacing path for door impls**: the handlers' duplicate raw
  toast is gone, so a door failure that bypasses `failFor` is *silent in the UI*. Keep failFor the
  single failure path in door implementations.
- **The startup banner makes count-based notify assertions fragile**: every headful harness
  session now receives the startup notify, so filter notify asserts by severity (e.g. "exactly one
  *error* notify"), never by count. See the harness recipes in `pi/tui-surfaces.md`.

## Not every site fits a single-message seam (the P1/P2/P3 triage)

- **P1 (migratable):** same message in both branches, severity-driven, no follow-up turn.
- **P2 (excluded):** command-echoes with *different* rich-headful vs terse headless text plus a
  `sendUserMessage` follow-up — a single-message seam loses information.
- **P3 (excluded):** self-prefixed status renders (already begin `perk N …`) and background
  catch-block diagnostics with no UI pairing — forcing them through the seam double-prefixes or
  invents a notify. A stderr-only `logError(scope, message)` sibling could absorb the P3
  catch-logs — deliberately deferred.

## Accepted-drift discipline

When a migration changes a message's prefix or severity-gating (e.g. planSave's final echo gained
the seam's prefix and the headless info-log), **flag it in the plan** and let tests adjudicate — the
planSave change deliberately inherited the seam's fail-safe.

## Cross-references

- `extension/surfaces/report.ts` — `report()`, `ReportTarget`
- `extension/substrate/workflowState.ts` — `appendWorkflowState`, `EntrySink`, `rebuildWorkflowState`
- `docs/learned/pi/extension-api.md` — the SDK context the structural interface slices
- `docs/learned/workflow/plan-review-flow.md` — the extracted-core + scripted-fake testing recipe
- `docs/learned/workflow/warm-door-commands.md` — the warm doors whose error paths these seams serve
- `docs/learned/pi/tui-surfaces.md` — the surfaces module that owns the rich-UI call sites, and
  the harness notify/status recipes
- `docs/learned/workflow/session-data.md` — the provenance map field behind the identity-subset
  comparator
