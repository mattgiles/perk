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

## Distillation

- Export a tiny structural interface the real context satisfies and a fake implements trivially
  (`ReportTarget`, `EntrySink`, `BranchSource`) — "The minimal-structural-interface recipe".
- Nothing a survivor needs may live in a module slated for deletion — extract at the survivor's
  birth — "Extract-to-survive-retirement".
- Door→typed-op extractions preserve implicit failure ORDERING (lazy ports, pinned order), keep
  lazy reads lazy, and pair narrowing readers with refusing writers — "Door→typed-op extraction
  craft".
- Strict decode = tolerant decode + count check; identities the engine validates are port
  parameters, never re-derived in a backing; provider flag-bags become discriminated variants at
  the adapter — "Door→typed-op extraction craft".
- The strict-append seam never throws; the boolean entry is a thin wrapper over a classified
  sibling (`applied | rejected | unverified`) and is the common append path for durable
  workflow-state fields — each field's §8.3 contract row, not the mechanism, decides what a
  caller does on a non-applied result — "The strict-append seam".
- Grep call sites before trusting a one-line idiom framing ("1 base + 1 superset" — prefer an
  opt-in flag); comments claiming an unadopted idiom mark migration sites — "'One idiom' is often
  1 base + 1 superset" / "Aspirational-comment fiction".
- Seams that own a prefix de-prefix migrated messages; not every site fits a single-message seam
  (the P1/P2/P3 triage) — "The de-prefixing trap" / "Not every site fits".
- `report()` contains a throwing detail sink with one stderr write (a charter exception); a notice
  from a caller holding a landed save uses the `reportGateTransition` pattern — "report()-rollout
  gotchas".

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
(the plan-draft-write precedent: spec'd against `ExtensionAPI`/`ExtensionContext`, landed against
the slices). The lesson stands; the instance is dated — `writePlanDraft` is gone: the core has
since been re-homed as `revisePlanDraft` over the `WorkflowSession` seam
(`extension/authoring/plan/draft.ts`), and the structural-slice discipline now lives one layer down
in `SessionStateStore` (`extension/session/lifecycle.ts`: `rebuild`/`append`/`appendVerified`).

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
handoff — had been extracted to a dedicated handoff module (the since-renamed hunkHandoff door
helper, live today as `extension/pi/v1/codeReview/checkout.ts`) **at the survivor's birth**,
with the retiring module importing it back (behaviorally byte-stable; the proof was that the
door's test file needed only import-path churn), so the retirement completed as a wholesale
`rm`. The hosting rule: **nothing a survivor needs may live in a module slated for deletion** —
extract when the survivor is born, parameterizing call-site differences (the launch handoff grew
a report-scope param) rather than duplicating, so the later retirement is a wholesale `rm`
instead of a second extraction under pressure.

## Door→typed-op extraction craft

Seam-design rules from the door→typed-op extraction train (one owner each, cross-referenced: the
move/sweep mechanics live in `toolchain/ts-module-moves.md`, the slice scope/review economics in
`workflow/objective-delivery.md`, the parity-pin shapes in `workflow/execution-path-parity.md`):

Ordering and laziness:

- **An inline door's control flow encodes an implicit failure *ordering*** — hoisting
  throwing/effectful reads into an eager deps factory moves them earlier in the run. Make them
  lazy ports and pin the ordering with a test (#2184).
- **Pure-function extraction of a resolution chain converts lazy reads eager** — keep laziness
  when tiers have side-effectful reads (#2171).

Read/write postures:

- **A reader that narrows demands a writer that refuses** — narrowing on read while the writer
  still accepts the wide shape only moves the failure later (#2184).
- **Fail-open is a read-path posture** — never feed a fail-open rebuild into an LWW write of an
  append-only ledger; the degraded read would overwrite good state (#2174).
- **Strict decode = tolerant decode + count check** — decode leniently, then require the decoded
  count to equal the input count so nothing is silently dropped (#2183).
- **Refusal-before-effect via read-back classification** when a write throws ambiguously: read
  the state back and classify, rather than guessing which side of the effect the throw landed on
  (#2170).
- **Cold-door decode honesty:** required fields at a process boundary return `null`/`bad_output`
  when absent — never a defaulted value (#2171).

Identity and typing:

- **Any identity the engine validates is a port *parameter***, never re-derived inside a backing
  (#2183).
- **Mint-only nominal evidence snapshots primitives** — never retain caller-reachable references
  (#2180).
- **When a spec repeats one identity across ≥2 fields, key a table by that identity** so drift
  fails at the literal-type level (#2191).
- **Provider flag-bags translate INTO discriminated variants at the adapter** (#2169);
  wire-faithful discriminated unions can internalize Result-skinned policy with zero wire delta
  (#2186).
- **Parallel discriminants are legitimate when the vocabularies have non-isomorphic domains** —
  name the one conversion point and record the declined unification (#2180).
- **A per-flow correlation wrapper compensating for a loosely-typed mechanism tier** is a signal
  the fix belongs at the seam, not in another wrapper (#2176).

Testability:

- **A declared behavior delta needs a positive test exercising its failure arm in the same
  commit** (#2171).
- **Execute-core extraction with a narrow injectable dependency** (the browser-open seam) makes
  failure arms testable — including pinning that a failed open never consumes a single-use latch
  (#2033).

## The type-only-import cycle break

When a vocabulary type moves to a new owning module that the old module still references, import
it back **type-only**: the new owner imports the old module's values normally; the old module's
`import type { … }` of the moved type is erased at runtime, so no cycle exists.

The realized instance is dated history: when `plan_review` moved out of the plannotator adapter,
`planReview.ts` imported the bridge (a value) from the adapter and the adapter imported
`ReviewOutcome` type-only back — the type-only import was the interim tool. The terminal shape
dissolves the cycle outright: `ReviewOutcome` now lives in a dedicated vocabulary module
(`extension/pi/v1/reviewOutcome.ts`, no imports of its own) that the adapter
(`extension/pi/v1/providers/plannotator.ts`) imports type-only, and the adapter imports nothing
back from `planReview.ts` (which still takes value helpers from the adapter, but no longer the
bridge).

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

Non-obvious facts around it:

- **Mechanism vs contract row.** The append → rebuild → compare mechanism is now the default path
  for durable workflow-state fields. `appendWorkflowStateClassified` classifies the outcome:
  `applied` (read-back equals expected, *including* when `appendEntry` threw — the read-back is
  the proof authority), `rejected` (the append threw AND the rebuilt field still differs — proven
  refusal-before-effect), `unverified` (the append returned but the read-back missed, or the
  post-throw rebuild itself failed — an effect may have landed unproven). `appendWorkflowState`
  is its boolean wrapper (`applied` → true), and `branchSessionStateStore`
  (`extension/session/lifecycle.ts`) exposes the classified form to the session seam as
  `SessionStateStore.appendVerified`. What differs per field is its **§8.3 contract row**, not the
  mechanism: the verified-linkage tier (`run_id ↔ pi_session_id`, `active_plan_ref`)
  withholds/propagates on a non-applied result; most best-effort fields continue past the loud
  report; and a best-effort field can still withhold — the conflict counter is best-effort tier,
  yet an unverified increment withholds the resolver dispatch. For the live census, grep
  `appendVerified(` / `appendWorkflowState(` rather than trusting a field list. The two
  boolean-wrapper riders: `setConflictAttempts` (refuses a non-integer/negative counter loudly
  *before* any append — the reader narrows such values to 0, so persisting one would silently
  reopen the budget; equal-value short-circuit) and the dream wave's `markBundleDigest` closure
  (`extension/pi/v1/learning/dream.ts`; fail-closed on an unverified CLEAR).
- **The plain-append remainder (deliberately unverified):** the fork/adopt identity append in
  `extension/session/lifecycle.ts` (LWW, inherits the parent's state); the gate's own `mode`
  enter/exit writes in `extension/substrate/toolGating.ts` (they return a typed `GateTransition`
  instead — `pi/context-system.md` § Gate engagement); `session_name`/`session_naming`
  (`extension/session/sessionName.ts`; the contract calls it a plain append); and the `/objective`
  command's `active_objective` write in `extension/pi/v1/objective.ts`. Don't migrate the fork
  append: a fail-open rebuild feeding an LWW write is the trap "Door→typed-op extraction craft"
  already names.
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
- **`report()` can recurse into the failing persistence path.** The warm-command detail sink
  appends through Pi's persistence, so a multi-line notice *about* a persistence failure could
  throw past a landed save. `report()` (`extension/surfaces/report.ts`) now wraps the sink in
  try/catch and falls back to one `console.error` of the full value — a bounded exception recorded
  in `docs/design/tui-charter.md` (describe it as "one write", not "one line"; any new
  `console.error` path in `report()` needs a charter amendment).
- **The `reportGateTransition` pattern** (`extension/pi/v1/gateTransitions.ts`: fold newline runs,
  wrap `report()`, fall back to stderr) is the shape for any notice sent by a caller holding a
  landed save or receipt — the notice must never undo what already landed.

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
- `extension/substrate/workflowState.ts` — `appendWorkflowState` / `appendWorkflowStateClassified`,
  `setConflictAttempts`, `EntrySink`, `rebuildWorkflowState`
- `extension/session/lifecycle.ts` — `SessionStateStore` (`rebuild`/`append`/`appendVerified`),
  `branchSessionStateStore`, the fork/adopt plain append
- `extension/pi/v1/reviewOutcome.ts` — the vocabulary module that dissolved the adapter cycle
- `docs/learned/pi/extension-api.md` — the SDK context the structural interface slices
- `docs/learned/workflow/plan-review-flow.md` — the extracted-core + scripted-fake testing recipe
- `docs/learned/workflow/warm-door-commands.md` — the warm doors whose error paths these seams serve
- `docs/learned/pi/tui-surfaces.md` — the surfaces module that owns the rich-UI call sites, and
  the harness notify/status recipes
- `docs/learned/workflow/session-data.md` — the provenance map field behind the identity-subset
  comparator
- `docs/learned/toolchain/ts-module-moves.md` — the move/sweep mechanics of the extraction train
- `docs/learned/workflow/objective-delivery.md` — the façade-slice migration pattern (slice
  scope/review economics)
- `docs/learned/workflow/execution-path-parity.md` — migration parity pins over registration
  objects
