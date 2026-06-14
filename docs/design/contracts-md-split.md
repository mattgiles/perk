# Design (deferred follow-up): split `shared/contracts.md` into current-spec vs history

> **Status:** execution **IN PROGRESS** — see Objective #539. `shared/contracts-history.md` now exists
> and the relocation is landing across the objective's nodes (the document-opening statuses have
> already moved, and §8.4 has now relocated too; the §8.9/§8.10 clusters follow). This doc was originally written as a proposal
> (proposed, not executed) so an objective-plan node could author the split **without
> re-investigation**; the forward note near the top of `shared/contracts.md` points here.

## Problem statement

`shared/contracts.md` is currently **both spec and changelog**. Each section interleaves the durable
current contract (the `## §N.M` spec bodies) with chronological `Status (…)` blockquotes that record
*when* each slice landed (`Status (T2)`, `Status (P1.T2a)`, `Status (Node 2.3)`, …). A caller who
just wants to know the current truth must read past historical aspiration/landing notes to find it —
the interface is **shallow**: the signal (current spec) is diluted by the changelog.

This drift is the same class the refresh plan (#537) fixed at the prose level (the
`provider id == cache.plan-ref.provider` contradiction, the stale counts): the `Status (…)` blocks
are where stale claims accumulate, because they are written in the present tense of a past node and
never revisited. Relocating them out of the live spec removes the place drift hides.

## Inventory (verified; durably anchored — no line numbers)

- **`## §` spec sections:** ~22 top-level sections, numbered `§8.1` … `§8.23` (with `§8.8` absent and
  a couple of inline `§3.2` cross-refs that are not their own top-level section). Coverage: the
  `.pi/workflow/` layout (§8.1), run-id (§8.2), workflow-state (§8.3), the GitHub gateway (§8.4),
  the init/doctor machine surfaces (§8.5/§8.6), bindings (§8.9), providers (§8.10), the
  headless-worker / remote-runner family (§8.11–§8.20), the issue-backend seam (§8.21), Linear
  emission (§8.22), and the file-first plan contract (§8.23). These spec bodies are the **current
  contract to keep inline**.
- **Inline `Status (…)` blocks:** ~28 blockquotes. The heaviest concentrations:
  - the **document-opening** statuses (`Status (T2)`, `Status (T5)`, `Status (P1.T2a)`);
  - the **§8.4 gateway** run (a dozen blocks: `P1.T2b`, `P1.T3`, `P1.T4a`, origin-aware-create-base,
    `P1.T4c`, `P1.T5a`, `P1.T5b`, `P1.T5c`, `P1.T6`, `P2.T8a`, `P2.T8b`, `P2.T8c`);
  - the **§8.9 bindings** statuses (`Node 3.1` / `2.3` / `3.2`);
  - the **§8.10 providers** statuses (`Node 2.1` / `2.2` / `3.1` / `2.3` / `2.6` / `3.2` /
    plannotator-plan / askuser / footer / web).
  - These `Status (…)` blocks are the **history material to relocate**; the surrounding `## §` spec
    bodies are the **current contract to keep**.

(Counts are approximate-by-design — they will drift as sections land; the durable anchors are the
`§N.M` section numbers and the `Status (…)` label text, not any count or line number.)

## Proposed convention

Keep `contracts.md` a **compact current-spec index/spec**: each `## §N.M` section keeps its spec
body and loses its inline `Status (…)` blocks. Move the chronological `Status (…)` material into a
sibling **history** doc, in chronological/section order, each entry tagged with the `§N.M` anchor it
came from so the cross-reference survives.

**Open choice the future plan must settle (with a recommendation):** where the history lives —

1. a single sibling `shared/contracts-history.md` *(recommended — lowest-friction first cut: the
   `§N.M` cross-refs already in the prose become the anchors, and there is exactly one new file to
   add to the bundle)*; vs.
2. per-section history files (`shared/contracts-history/§8.4.md`, …) — finer-grained but many files
   and a bundling change; vs.
3. folding the landed-node narrative into `docs/learned/` — but `docs/learned/` is cross-cutting
   *reasoning*, not a contract changelog, so this blurs two distinct surfaces.

Recommendation: option 1.

## Cross-reference migration concern (primary risk)

The prose is **densely self-referential** (`§8.10`, `§8.21`, `§8.4`, … appear throughout) and other
files cite it by section: `shared/README.md`, the four substrate readers
(`extension/substrate/{bindings,providers}.ts`, `perk/substrate/{bindings,providers}.py`), and the
design docs (`docs/design/provider-contract.md`, `docs/design/adapter-architecture.md`). The split
**must preserve every `§N.M` anchor** in `contracts.md` and **update any reference that points
specifically at a relocated `Status (…)` block** (most references point at spec sections, which stay
— but the few that cite a status note must be repointed to the history doc). This is the primary
risk and the bulk of the mechanical work.

## Out of scope / non-goals

- **No schema/behavior/validator/test-logic change** — this is a documentation relocation only.
- **The spec bodies' *wording* is not rewritten** — only the `Status (…)` blocks move.
- **Keep-and-annotate, not delete** — per the doc-reconciliation discipline in `docs/learned/`, the
  status history is preserved (relocated), never dropped.

## Acceptance criteria

- `contracts.md` retains all `## §` spec sections and **every** `§N.M` anchor.
- **No `Status (…)` block remains inline** in `contracts.md`.
- The history doc carries every relocated `Status (…)` block in chronological/section order, each
  tagged with its originating `§N.M` anchor.
- Every cross-reference that pointed at a relocated status block is repointed at the history doc; all
  spec-section cross-refs still resolve.
- `just ci` green (the YAML loaders/validators and `node:test`/`pytest` suites unaffected).
