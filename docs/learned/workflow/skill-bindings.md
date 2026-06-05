---
title: Skill bindings — the two-plane trigger→skill delivery subsystem
read_when: You are working on skill-binding config (.pi/perk.toml [[bindings]]), the cold/warm delivery doors, the resolver, or debugging double-delivered / missing binding context.
---

# Skill bindings

Skill bindings let a user attach a skill to a trigger (`stage:<id>` or `command:<id>`) in
`.pi/perk.toml`, so that launching that stage/command delivers the skill's `SKILL.md` content into
the session. The subsystem is **two-plane** (Python cold door + TS warm door) over a **shared data
contract** (`shared/bindings.yaml`), built across Objective #63 nodes 1.1–2.2. The cross-cutting
knowledge below is what an agent can't derive from reading any single file.

## The data contract and the resolver (Nodes 1.1, 1.2)

The vocabulary, model, and shipped-default set live in `shared/bindings.yaml` — the **second**
parsed `shared/` contract after `registry.yaml` (see `shared-contracts.md` for the repeatable recipe
for adding such a contract). A trigger is a single `"<kind>:<id>"` string (`kind ∈ {stage, command}`)
stored **literally**, not split into fields, because that's exactly what a user types in
`.pi/perk.toml`; readers split on the **first** `:`. Kind-selection rule: bind to `stage:<id>` when a
command maps 1:1 to a registry stage of the same name (the canonical trigger fires across BOTH cold
launch and warm slash-command); reserve `command:<id>` for commands with no registry stage. Loaders
stay **registry-free** — target-existence cross-validation is deferred to `doctor`.

Resolution overlays user bindings onto shipped defaults. Two subtle semantics:

- **Whole-array replace, local wins.** A user `[[bindings]]` array replaces the array wholesale
  (mirroring Python `_overlay`'s list-replaces-list), never element-merge. The TS `parseTomlSubset`
  return type had to grow from a flat `StringTable` to `{ tables, arrays }` to carry array-of-tables
  — see `toolchain/biome.md` for the parser-rewrite gotchas.
- **"Earlier-*applied* duplicate", not raw validate-duplicate.** A user binding applies iff
  shape-valid AND its trigger wasn't *already applied*. This differs from naive `validate()` on the
  edge case `[invalid-shape@T, valid@T]`: validate flags the second as a duplicate, but the locked
  decision wants it *applied* (the first was dropped, never applied). Both planes share a per-binding
  issues primitive plus an `applied` set in the resolver — **the resolver does not call validate**.
  Downstream delivery nodes get unique-triggers-by-construction for free.

## "User-originated" is the delivery filter — and the frozen-dataclass test is exact

perk still hardcodes its own "Follow the … skill" nudges (until a later node deletes them), so the
delivery layer must deliver **only** user-originated bindings to avoid double-pointing. The exact
test: a resolved binding **value-equal to a shipped default is dropped**; a *new* trigger or an
*override* of a perk-owned trigger is delivered. Python expresses this as frozen-dataclass set
membership (`Binding` is `@dataclass(frozen=True)` → hashable; `b not in set(defaults)`). The TS twin
has no value identity (plain object), so it serializes a tuple key
(`JSON.stringify([trigger,kind,targetId,skill,mode])`) into a `Set` — the same pattern applies any
time a TS plane mirrors a Python set/`in` over structural objects.

## The two doors and the cold↔warm dedup marker (Nodes 2.1, 2.2)

Cold and warm renderers are **independent code paths** that must not double-deliver when both fire
for one session (a cold launch *and* `before_agent_start`). They dedup through one **byte-identical
header literal**: `BINDING_HEADER` (TS, `extension/bindingDelivery.ts`) ≡ `_HEADER` (Python,
`perk/binding_delivery.py`). The warm injector skips when **any entry on `ctx.sessionManager.getBranch()`
already contains the header** — a shape-agnostic scan (`branch.some(e => JSON.stringify(e).includes(HEADER))`)
robust because the header is a distinctive literal. The equality is pinned by a literal test in BOTH
planes; changing the literal in one plane must update the other in the same turn. It is idempotent
across turns/reloads, and re-delivers after compaction drops the original entry (the ongoing value).

The cold/warm injection+strip mechanics (why the strip must be conditional, why it must be narrower
than planMode's) are pi-lifecycle facts captured in `pi/context-injection.md`.

### The `binding_trigger` "borrows-a-stage" hazard

`launch_stage` (`perk/launch.py`) is the single cold-launch chokepoint every stage launcher routes
through, so binding delivery wired there covers all launches uniformly. But the trigger defaults to
`f"stage:{stage.id}"`, and **`learn-docs` borrows the `plan` stage descriptor** — keying delivery off
`stage.id` alone would fire `plan`'s bindings for it. The fix is an explicit
`binding_trigger: str | None = None` param; only `learn-docs` overrides it (to `command:learn-docs`).
**Any future "borrows-a-stage" command must set `binding_trigger` or it silently fires the borrowed
stage's bindings.**

Two delivery-surface boundaries that held:

- **Worker commands have no cold-door delivery surface.** `objective-reconcile` rewrites the
  objective body with no `pi` session / initial prompt, so `command:objective-reconcile` can only
  fire at the warm door. Don't wire cold delivery for non-launching workers.
- **Delivery I/O lives apart from the model.** Disk reads (`SKILL.md` transclusion) live in
  `perk/binding_delivery.py`, keeping `perk/bindings.py` a pure model/resolver. Resolver `issues` +
  delivery `warnings` are **returned, never raised**, and surfaced loud-but-non-fatal: a missing
  transclude target degrades to the nudge pointer with a warning, never blocking a launch.

## Cross-references

- `shared/bindings.yaml`, `shared/contracts.md` §8.9 — the data contract and trigger vocabulary
- `perk/bindings.py` — pure model + resolver; `perk/binding_delivery.py` — `_HEADER`, cold render
- `extension/bindingDelivery.ts` — `BINDING_HEADER`, `BINDING_CONTEXT_TYPE`, warm injector + dedup scan
- `perk/launch.py` — `launch_stage`, the `binding_trigger` param (the borrows-a-stage seam)
- `docs/learned/workflow/shared-contracts.md` — adding a new parsed `shared/` contract
- `docs/learned/pi/context-injection.md` — the conditional inject-and-strip lifecycle
- `docs/learned/toolchain/biome.md` — the `parseTomlSubset` rewrite gotchas
