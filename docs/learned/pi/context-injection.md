---
title: Pi context injection — the conditional inject-and-strip pattern, stage-field disambiguation
read_when: You are injecting context into a session (planMode/objectiveAuthor/bindings) and stripping it later, deduplicating an injection via branchCarries, or serving two stages from one adapter.
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
branch (`pi/extension-api.md`), so after compaction drops the original entry the context naturally
disappears and re-injects — the ongoing value of keying on live state rather than a one-shot flag.

## Once-only injection dedup: the stringify-includes branch scan

Injected custom messages persist to the branch as *message* entries whose exact shape (where
`customType` sits) varies — so the proven once-only dedup guard serializes each entry and scans
for a needle, **not** a typed customType scan. The pattern's home is the shared
`branchCarries(branch, needle)` helper in `extension/substrate/workflowState.ts` (beside
`branchOf`), adopted by every per-turn injector — toolGating's mode context, planMode's
plan-authoring context, objectiveAuthor's objective-authoring context, gistAuthor's context, the
two plan adapter bridges (plannotator/tombell), and bindingDelivery's header scan (migrated from
its hand-rolled `branchHasHeader`). Two original adopters are since removed with Objective #1416
— the juicesharp todo bridge and checkpoints' steps-context scan (itself one of the two migrated
hand-rolled sites). Prefer this enumeration over a hard count; counts are drift magnets.

The dedup key is each block's **marker literal** (a distinctive substring of the injected
content), not the customType. The notable refinement is **per-flavor dedup** for plannotator's
two-flavors-one-customType case: keying on the flavor's marker means a stage change still
delivers the missing flavor while a prior copy of the *other* flavor sits on the branch — a
customType key would wrongly suppress it. The scan is safe as long as the marker can't appear in
other entries' data — the known accepted false positive is a tool result quoting perk's own
source (which would suppress a post-compaction re-inject); a typed scan over message-entry
customType is the documented escalation if that ever bites.

An adjacent timing fact: slash commands do **not** fire `before_agent_start`, and a command
handler reads the branch **as-of the last completed turn** — so a fresh session shows 0–1 copies
of each injected context, and per-turn re-injection growth is only observable after completed
turns. The payload census confirmed the pre-dedup growth empirically (each perk context ×2 after
two turns; recorded in `docs/design/context-payload-baseline.md`) — the branch-scan dedup above
is what bounds it.

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

## Stage-field disambiguation when two stages share a `mode`

`planMode.ts` originally injected plan-authoring context off **any** read-only gate. Once two
read-only stages coexist (`plan` vs `objective-author`), the interior must know *which one* — the
gate alone is ambiguous. The fix: a `stage` field on `perk:workflow-state`, persisted at **cold
claim** from the handoff blob (the handoff already carried `stage` for plan-ref reconciliation, but
it was never written into workflow-state). Then context injection keys on `(gate AND stage)`:
`planMode` defers when `stage === "objective-author"` and `objectiveAuthor.ts` injects instead —
exactly one authoring context present.

**Pattern:** when stages share a `mode`, persist the stage id so context injection can be keyed on
`(gate AND stage)` rather than the mode alone.

## Cross-references

- `extension/factories/planMode.ts`, `extension/factories/objectiveAuthor.ts` — the two read-only authoring injectors
- `extension/substrate/bindingDelivery.ts` — the narrowest strip (own custom type only)
- `extension/substrate/workflowState.ts` — `branchCarries`, the shared once-only dedup guard
- `docs/learned/pi/extension-api.md` — the every-call `context` event + injected-message persistence
- `docs/learned/workflow/skill-bindings.md` — cold↔warm binding delivery this strip discipline serves
- `docs/learned/workflow/objective-lifecycle.md` — the authoring loop using the `stage` discriminator
