---
title: Pi context injection — active compaction windows, conditional stripping, stage-field disambiguation
read_when: You are injecting or stripping session context, deduplicating delivery across compaction, handling Pi compaction callbacks, or validating branch-entry data.
cluster: pi-extension
---

# Context injection and stripping

perk injects context into sessions (plan-authoring guidance, objective-authoring guidance, skill
bindings) and later strips it from the model window when it goes stale. The lifecycle has sharp
edges because of how Pi's `context` event works (see `pi/extension-api.md`: it runs on **every**
provider call over the full message list).

## Inject-and-conditionally-strip

The injection happens at `before_agent_start` (and/or the cold launch's initial prompt); the strip
happens on the `context` event. Because `context` runs on every call, the strip **must be
conditional**, not unconditional:

- An unconditional strip of an injected custom type would remove it even on its **own injection
  turn**, defeating delivery.
- Key the strip off "is this injection still relevant?" perk keys it off the **current stage** —
  e.g. binding delivery strips its custom type only when the current stage no longer renders
  non-empty bindings, mirroring how `planMode`/`objectiveAuthor` strip their context once their gate
  is off.

The pattern: **keep while relevant, strip only when stale.** Injected custom messages persist to the
branch (`pi/extension-api.md`). Compaction does not drop those entries from the branch: Pi appends a
compaction entry and rebuilds only the model context from the summary plus the entries beginning at
`firstKeptEntryId`. Re-delivery decisions therefore need the active model-context window, not the
append-only branch history.

## Dedup against the active compaction window

Injected custom messages persist to the branch as *message* entries whose exact shape (where
`customType` sits) varies. The shared `branchCarries(branch, needle)` helper in
`extension/substrate/workflowState.ts` therefore serializes entries and scans for a distinctive
marker rather than assuming one custom-entry shape. A full-branch scan is suitable only for a
strict once-per-session fact: Pi's branch is append-only through compaction, so it sees every
historical marker forever. Used for model-context delivery, it silently suppresses the very
post-compaction re-delivery the model now needs.

The reusable delivery pattern is `activeContextWindow(...)`, beside `branchCarries` in
`extension/substrate/workflowState.ts` and consumed by
`extension/substrate/bindingDelivery.ts`. It finds the latest compaction, starts at that entry's
validated `firstKeptEntryId`, falls back to the first entry after the compaction when the id is
missing or unusable, and excludes compaction entries themselves. A summary that quotes a marker
is evidence of old delivery, not a live custom block. Run the shape-agnostic marker scan only over
this returned window. Contracts §8.38 records the cold/warm binding-delivery behavior that relies
on that distinction.

The dedup key remains each block's **marker literal**, not the custom type. In plannotator's
two-flavors-one-customType case, per-flavor markers let a stage transition deliver the missing
flavor even while the other flavor is active. Distinctive markers still matter: an unrelated
live tool result quoting one can false-positive, at which point a typed message-entry scan is the
escalation.

`bindingDelivery` is the first active-window adopter. The five flow injections — gist, plan,
objective-authoring, plannotator's three flavors, and the tombell bridge — all scan the active
window through the shared pi/v1 helper
(`extension/pi/v1/contextInjection.ts::installInjectedContext`, which composes `branchCarries` +
`activeContextWindow` behind each caller's policy closures). ToolGating's read-only mode context
deliberately remains the full-branch scan — the strict once-per-session marker, not a
model-context-bound delivery. Escalate to `activeContextWindow` when the feature's delivery
lifetime is model-context-bound.

An adjacent timing fact: slash commands do **not** fire `before_agent_start`, and a command
handler reads the branch **as of the last completed turn**. A fresh session therefore shows 0–1
copies of each injected context, and per-turn growth is observable only after completed turns.
The payload census in `docs/design/archive/context-payload-baseline.md` established the original growth;
the active-window scan bounds copies in the live context while still permitting delivery after
compaction.

## Compaction callback lifecycle and data-shape discipline

In Pi 0.84.1, manual compaction remains in the same `AgentSession` and extension runner; it does
not replace the session. `CompactOptions.onComplete` may use the captured extension API, but it
must not retain or read the event `ctx`, nor recompute session state from that stale callback
context. Pi's extension `sendUserMessage` wrapper is void/fire-and-forget: protect the synchronous
call boundary only rather than pretending an asynchronous result can be awaited.

Compaction metadata also illustrates a broader TypeScript boundary rule. After checking a few
fields on an `unknown` object, do not cast the original object to a richer declared structure.
Validate and reconstruct the fields one by one, or return a `Pick` containing only the fields the
check actually proved. `activeContextWindow` deliberately treats `firstKeptEntryId` as unknown
until its string check; the same discipline applies to every branch-entry decoder.

## Two content flavors, one customType

When one adapter serves two stages, don't mint a second customType: branch on `state.stage` inside
one `before_agent_start` handler to pick the injected content, and have the strip handler cover
**both** marker substrings — the customType filter already catches injected messages regardless of
content. Cheaper and safer than a second customType; deselect hygiene stays one filter.

## Strip-scope discipline: don't strip more than you own

A strip must be **narrower than it's tempting to make it.** `planMode` strips its marker from *user
messages* too (its marker only ever appears in perk-injected guidance). Binding delivery must NOT do
the same: **a cold launch's initial user prompt legitimately carries the binding header**, and
stripping user messages would erase the cold-delivered bindings. So binding delivery strips **only
its own `perk:binding-context` custom type**, never user turns.

**General rule:** scope a strip to exactly the custom type / marker the feature owns. If a marker can
legitimately appear in a user-authored message (because a cold door seeded the user prompt with it),
stripping user turns destroys real content.

## Stage-field disambiguation when stages share a `mode`

`planMode.ts` originally injected plan-authoring context off **any** read-only gate. Once a second
read-only stage coexisted (`plan` vs `objective-author`), the interior had to know *which one* —
the gate alone is ambiguous. The fix: a `stage` field on `perk:workflow-state`, persisted at
**cold claim** from the handoff blob (the handoff already carried `stage` for plan-ref
reconciliation, but it was never written into workflow-state). Context injection keys on
`(gate AND stage)`.

The current shape is **three** read-only authoring contexts sharing the gate: plan mode
(`extension/pi/v1/plan.ts::installPlanBindings`) defers to BOTH authoring stages — its select
callback returns no marker when the launched stage is `objective-author` OR `gist-author` — while
`extension/pi/v1/objectiveAuthoring.ts` and `extension/pi/v1/gist.ts` each gate their own injected
context on `(gate AND stage === <their own stage>)`. Exactly one authoring context present, however
many stages share the mode.

**Pattern:** when stages share a `mode`, persist the stage id so context injection can be keyed on
`(gate AND stage)` rather than the mode alone.

## Cross-references

- `extension/pi/v1/plan.ts` (plan mode), `extension/pi/v1/objectiveAuthoring.ts`, `extension/pi/v1/gist.ts` — the three read-only authoring injectors
- `extension/substrate/bindingDelivery.ts` — the narrowest strip (own custom type only)
- `extension/substrate/workflowState.ts` — `branchCarries` plus the compaction-aware `activeContextWindow`
- `docs/learned/pi/extension-api.md` — the every-call `context` event + injected-message persistence
- `docs/learned/workflow/skill-bindings.md` — cold↔warm binding delivery this strip discipline serves
- `docs/learned/workflow/objective-lifecycle.md` — the authoring loop using the `stage` discriminator
