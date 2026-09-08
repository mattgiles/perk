---
title: Pi context injection — Pi-projection live-evidence dedup, selection-driven retention, stage-field disambiguation
read_when: You are injecting or stripping session context, deduplicating delivery across compaction via Pi's projection, handling compaction callbacks or a token-cap failure, or validating branch-entry data.
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
- ONE decision drives both hooks. Each injected context declares a `select(ctx, branch)` policy
  over the FULL rebuilt branch; the same selection result drives injection at `before_agent_start`
  AND retention on `context` (`extension/pi/v1/contextInjection.ts::installInjectedContext`). The
  `context` filter touches only the owned `customType`: a null selection (ineligible) removes every
  owned copy; a selected flavor retains only owned copies carrying that flavor's marker and drops
  obsolete sibling flavors (plannotator's plan→objective transition). A failed branch read or a
  throwing selector fails CLOSED to "nothing selected" — stale owned guidance never survives an
  unreadable branch.

The pattern: **keep while relevant, strip only when stale.** Injected custom messages persist to the
branch (`pi/extension-api.md`). Compaction keeps the historical entries on the branch — it appends a
compaction entry and rebuilds the model context from the summary plus a kept tail. Liveness is
therefore Pi's *projection* of the branch into model context, not the append-only branch history.

## Dedup against Pi's own live projection (delegate, don't re-derive)

Injected custom messages persist to the branch as *message* entries whose exact shape (where
`customType` sits) varies. The shared `branchCarries(branch, needle)` helper in
`extension/substrate/workflowState.ts` therefore serializes entries and scans for a distinctive
marker rather than assuming one custom-entry shape. A full-branch scan is suitable only for a
strict once-per-session fact: Pi's branch is append-only through compaction, so it sees every
historical marker forever. Used for model-context delivery, it silently suppresses the very
post-compaction re-delivery the model now needs.

perk's first answer was a manual window reconstruction — find the latest compaction, validate its
kept-entry cutoff, scan serialized entries from there. That machinery was **deleted**. Live-delivery
dedup now flattens `sessionManager.buildContextEntries()` (the current leaf's compaction-aware
`SessionEntry[]`) through Pi's package-root `sessionEntryToContextMessages` converter, and perk keeps
only typed predicates in the no-state leaf `extension/pi/v1/contextEvidence.ts`
(`activeContextMessages`, `contextCarriesMarker`). The durable insight: **prefer the platform's
projection over re-deriving it** — the whole window machinery existed only because perk rebuilt what
Pi already computes for every provider call.

Evidence is **typed, not serialized**: a marker counts only on `user` content (a cold launch prompt)
or on `custom` content whose `customType` is exactly the owner's. A compaction/branch summary
quoting the marker, assistant/tool/bash output, an unrelated custom, or plain custom `data` state is
never a live delivery — Pi's converter keeps the roles distinguishable, so the predicate never
guesses from bytes. This retires the old fragility where a live tool result quoting a marker could
false-positive the dedup.

Two authorities stay distinct. Full-branch history (`branchOf` + `branchCarries` in
`extension/substrate/workflowState.ts`) serves eligibility and state rebuild, and the strict
once-per-selected-branch read-only marker — `toolGating` deliberately keeps the full-branch scan,
a historical latch rather than a model-context-bound delivery. The new leaf answers only "is the
delivery live in model context *now*". Projection failures propagate to the consumer (a read
failure is never manufactured into a falsely clean empty projection).

Two invariants carried over unchanged: the dedup key is each block's **marker literal**, not the
customType (plannotator's flavors-share-one-customType case needs per-flavor markers so a stage
transition can deliver the missing flavor), and the submitting `event.prompt` is checked BEFORE
the projection read at `before_agent_start` — a cold launch's prompt is not yet persisted on the
launch turn, so only that check sees a cold seed. All five flow injections — gist, plan,
objective-authoring, plannotator's three flavors, the tombell bridge — consume the leaf through
`installInjectedContext`; `extension/substrate/bindingDelivery.ts` and
`extension/substrate/agentScratch.ts` consume it directly with their own strip semantics.

An adjacent timing fact: slash commands do **not** fire `before_agent_start`, and a command
handler reads the branch **as of the last completed turn**. A fresh session therefore shows 0–1
copies of each injected context, and per-turn growth is observable only after completed turns.
The payload census in `docs/design/archive/context-payload-baseline.md` established the original
growth; the projection-based dedup bounds copies in the live context while still permitting
delivery after compaction.

## Compaction callback lifecycle and data-shape discipline

In Pi 0.84.1, manual compaction remains in the same `AgentSession` and extension runner; it does
not replace the session. `CompactOptions.onComplete` may use the captured extension API, but it
must not retain or read the event `ctx`, nor recompute session state from that stale callback
context. Pi's extension `sendUserMessage` wrapper is void/fire-and-forget: protect the synchronous
call boundary only rather than pretending an asynchronous result can be awaited.

Compaction metadata also illustrates a broader TypeScript boundary rule. After checking a few
fields on an `unknown` object, do not cast the original object to a richer declared structure.
Validate and reconstruct the fields one by one, or return a `Pick` containing only the fields the
check actually proved. A branch-entry decoder treats every field as unknown until its own type
check — `contextEvidence.ts`'s content check ignores non-text and malformed parts rather than
trusting the declared shape; the same discipline applies to every branch-entry decoder.

- The message `Compaction failed: … generation hit the token cap` is Pi's **summary output
  budget** (half of `reserveTokens` for a split turn's prefix, shared with adaptive-thinking
  reasoning; loud since Pi 0.84.3). It is fixed by `[compaction] reserve_tokens` in
  `.perk/config.toml` (`workflow/config-tables.md`), **not** by perk context code — the first
  planner to meet it misattributed it to the projection-dedup change.

## Two content flavors, one customType

When one adapter serves two stages, don't mint a second customType: branch on `state.stage` inside
one `before_agent_start` handler to pick the injected content, and have the strip handler cover
**both** marker substrings — the customType filter already catches injected messages regardless of
content. Cheaper and safer than a second customType; deselect hygiene stays one filter.

## Strip-scope discipline: don't strip more than you own

A strip must be **narrower than it's tempting to make it.** No authoring context strips user
messages any more: user/assistant/tool messages are **never** removed for carrying an owned marker
— a cold seed, an `<untrusted_draft>` body, a quotation stay byte-for-byte (the retention filter
edits only the outgoing model context; transcripts and compaction summaries are never rewritten).
Binding delivery's rule stands as the archetype: **a cold launch's initial user prompt legitimately
carries the binding header**, so it strips **only its own `perk:binding-context` custom type**,
never user turns.

**General rule:** scope a strip to exactly the custom type / marker the feature owns. If a marker can
legitimately appear in a user-authored message (because a cold door seeded the user prompt with it),
stripping user turns destroys real content.

The gate's `[READ-ONLY MODE]` retention (`perk:mode-context`, `extension/substrate/toolGating.ts`)
is independent of every authoring context and has a refinement flavor with its own distinct marker
that drops the generic copy in `objective-refine` sessions — tests model it separately from the
authoring injections.

## Warm stage transitions must strip the deselected flavor

Deferring the *injection* of a flavor does not remove an already-injected copy. A session that ran
a plan-mode turn and then entered `/objective-refine` kept live plan-authoring instructions in model
context until `installInjectedContext`'s retention was made to strip live owned copies of any
non-selected flavor (contracts §8.31). Any warm door that changes the selected stage must reason
about the copies the previous stage already delivered, not only about what it will inject.

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
- `extension/pi/v1/contextInjection.ts` — the one inject/retain hook pair behind the five flow injections
- `extension/pi/v1/contextEvidence.ts` — the typed live-projection predicates (`activeContextMessages`, `contextCarriesMarker`)
- `extension/substrate/bindingDelivery.ts` — the narrowest strip (own custom type only)
- `extension/substrate/workflowState.ts` — `branchCarries`, the full-branch history authority
- `docs/learned/pi/extension-api.md` — the every-call `context` event + injected-message persistence
- `docs/learned/workflow/skill-bindings.md` — cold↔warm binding delivery this strip discipline serves
- `docs/learned/workflow/objective-lifecycle.md` — the authoring loop using the `stage` discriminator
- `docs/learned/workflow/config-tables.md` — the `[compaction]` table (`reserve_tokens`)
