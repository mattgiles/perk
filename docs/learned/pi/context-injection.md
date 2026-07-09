---
title: Pi context injection — the conditional inject-and-strip pattern, stage-field disambiguation
read_when: You are injecting context into a session (planMode/objectiveAuthor/bindings) and stripping it later, deduplicating a once-only injection, or serving two stages from one adapter.
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
`customType` sits) varies — so the proven once-only dedup guard is
`branch.some(e => JSON.stringify(e).includes(TYPE))` (the bindingDelivery `branchHasHeader` form),
**not** a typed customType scan. It is safe as long as the type string can't appear in other
entries' data — the known false-positive risk (e.g. a quoted doc embedding the type string in a
message payload); a typed scan over message-entry customType is the fix if that ever bites.

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
- `docs/learned/pi/extension-api.md` — the every-call `context` event + injected-message persistence
- `docs/learned/workflow/skill-bindings.md` — cold↔warm binding delivery this strip discipline serves
- `docs/learned/workflow/objective-lifecycle.md` — the authoring loop using the `stage` discriminator
