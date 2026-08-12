---
title: Adding a parsed shared/ contract — the registry/bindings recipe (and dieting an overgrown contracts section)
read_when: You are adding a cross-plane data file under shared/, a registry stage (or its `writes`), dieting an overgrown contracts.md section, or making a prompt fragment agree byte-for-byte across planes.
cluster: cross-plane-contracts
---

# Parsed `shared/` contracts

Anything both planes must agree on lives in `shared/` and is read **directly by each plane — no
codegen**. There are two kinds of shared artifact: **parsed data files** (`registry.yaml`,
`bindings.yaml`) read by a Python reader + a TS reader, and **prose contracts** (`contracts.md`).
This doc captures the repeatable recipe for both, because the ripple is wide and easy to under-do.

## The six-seam recipe for a new parsed data file

`bindings.yaml` is the **second** instance of the pattern `registry.yaml` established. To add a
third, mirror exactly these six seams (no codegen, no manifest edits):

1. **Data file** `shared/<name>.yaml` with `schema_version: 1` + a documenting header comment.
2. **Python reader** `perk/<name>.py` — `load_*` raises a dedicated `*Error` **only for structural
   failures** (missing file / not a mapping / unsupported `schema_version`); `validate()` returns
   `list[Issue]` and **never raises for content**. Reuse `Issue`/`Severity` from `perk/substrate/registry.py`
   (one findings vocabulary — don't redefine). Parse leniently (coerce missing/ill-typed fields to
   `""`) so the *validator*, not the parser, reports every shape problem in one place.
3. **TS reader** `extension/<name>.ts` — a thin structural parse via the **vendored bounded reader**
   `extension/substrate/miniYaml.ts` (scoped to perk's own files; throws loudly on any unsupported
   construct); throws on missing-file/wrong-shape only. **The Python plane is the authoritative
   validator**; TS does not deep-validate. (The TS plane no longer depends on the `yaml` npm
   package — it was eliminated in #639/#641 to make the consumer extension-clone self-contained; see
   `docs/learned/workflow/distribution.md` for the npm delivery lifecycle the self-containment served.)
4. Both readers resolve the bundled dir via `shared_dir()` / `sharedDir()` (installed bundle →
   editable repo-sibling fallback).
5. **Bundling is automatic** — `pyproject.toml` force-includes the whole `shared/` dir (ships as
   `perk/_shared/<name>.yaml` in the wheel) and `package.json` `files` lists `shared/` (ships as
   `shared/<name>.yaml` in the npm tarball). **No manifest change needed** — but you MUST add the two
   bundle assertions to `tests/test_packaging.py` (`perk/_shared/<name>.yaml` in the wheel test;
   `shared/<name>.yaml` in the npm-pack test) or the publish surface goes unguarded.
6. **Tests in both planes** mirror `test_registry.py` / `registry.test.ts`: a `GOOD` constant + a
   per-test single-line `.replace()` mutation for each negative case; a "real bundled file
   validates" test; and a "matches shipped set" exact-tuple assertion.

### The "unconsumed seam" node convention

perk's standard way to split a feature is to **ship the readers first, imported by no production
module** — shape + defaults locked, zero runtime behavior, resolver/delivery deferred to a later
node. Verify the seam is unconsumed with a grep before submitting (it's part of the plan's
verification). Node 1.1 of the bindings work did exactly this.

## Prose-contract maintenance & objective hygiene — do it the same turn

A new parsed contract requires three doc edits **in the same turn**: a new `shared/contracts.md`
§8.x section (vocabulary + model + shipped-set table + a **Status (Node N)** deferral note), the
contracts intro line (e.g. "the one parsed contract" → "two parsed contracts"), and the
`shared/README.md` Contents list. Load-bearing prose like "the one parsed contract" had to be
corrected in two places — grep for such count-prose. More generally: **any implementation that
changes cross-plane behavior amends `shared/contracts.md` in the same turn.**

The same-turn rule has an observed failure mode: a runtime-tier prose change (injected guidance
constants) that skips contracts creates drift a *later node* must repair. When changing
factory/authoring guidance, check whether `shared/contracts.md` still records the behavior and
whether every other surface still respects its §8.57 carrier role (one canonical carrier per
statement; the skills are the detail tier — see `plan-review-flow.md`). Note also that §8.10's
"factory flows still instructing an autonomous `plan_save`" list has fully emptied — every
factory flow is review-first; §8.10 now records the terminal state.

**`shared/contracts.md` §-numbering is not contiguous.** §8.8 is skipped entirely and §8.10 was
already taken (provider selection), so the headless worker contract landed as **§8.11**. Always **grep the
existing `## §8.` headings in `shared/contracts.md` before assigning a section number** — do not trust
a plan's pre-assigned section id. **Pinned section numbers also race concurrent lands**: a plan
that pins "the next" number as fact should treat it as *"next free at land time"* — two
consecutive plans each lost their pinned number to a concurrently-landing plan (a §8.48 landed as
§8.49; a §8.49 landed as §8.50). A rebase must expect a renumber sweep, and the sweep greps the
pinned number across **code comments, tests, and prose**, not just `contracts.md`. (Related: `extension/*.ts` modules — minus `*.test.ts`/`testing/` —
ship in the npm tarball automatically via the `files` glob, and a flat `extension/` layout stays covered
by `node --test extension/*.test.ts` / `biome check extension` / `tsc` with **no justfile change** —
reinforcing the "bundling is automatic" theme above.)

### Post-merge objective roadmap reconciliation

When a PR lands, any objective roadmap prose or node descriptions can drift from what was actually built.
You must immediately reconcile the objective's Reconcilable prose region and node descriptions post-merge
(using `reconcile_objective` and `objective_node` tools) to ensure the active roadmap accurately reflects
the implemented reality.

## Dieting an overgrown contracts.md section

The recipe above is about *adding* contracts; the shared/ deep-clean established the inverse
pattern for prose sections that have grown past their cross-plane-binding job (§8.3/§8.4/§8.35 were
the proving ground). The diet's intent test: `contracts.md` keeps only **cross-plane-binding
facts**; single-plane narrative lives in the owning module's header docstring.

- **Verify-docstring-coverage-then-delete.** Before cutting a narrative block from
  `shared/contracts.md`, verify the named owner module's header docstring carries the essentials
  (add a sentence there if not), then **delete the block outright** — git history is the archive;
  there is no relocation into `contracts-history.md`. Headings/anchors are **never renamed or
  renumbered** (the diet deletes prose, never an anchor); a compact "owning modules" pointer list
  replaces the deleted narrative.
- **The anchor-liveness guard** (`tests/test_contracts_anchors.py`) converts the `§8.x` citation
  network from convention into CI, in three directions: heading **uniqueness**; wide-corpus
  **liveness** (every heading is cited somewhere outside contracts.md — self-reference confers no
  liveness); code-corpus **validity** (code may cite only live headings; docs may deliberately
  discuss absent numbers); plus contracts-history group integrity. **Gotcha:** the guard's own
  docstring can't spell a deliberately-absent `§8.x` token or it flags itself — write "the skipped
  8.8" without the `§`. Second gotcha: the guard also fires **mid-implementation** when code
  cites a `§` heading that doesn't exist yet — when a plan schedules "amend contracts in the
  same turn" as its *last* task, either add the `§` heading early or expect the guard to gate
  the intermediate commits.
- **Diet intent survives merges.** When a diet branch rebases over a main that added prose to the
  same section, "this content is accurate" ≠ "this content belongs": evaluate each conflict
  resolution against the **diet intent** (cross-plane-binding facts only), not mere accuracy. In
  the proving run a freshly-landed Python-only subsection was correctly *removed* during conflict
  resolution while main's legitimate cross-plane change was kept.
- **The concurrent-restructure rebase hazard.** A wholesale-section restructure whose branch
  predates a same-window, same-section addition can **silently delete just-landed content** during
  rebase — the §8.4 restructure erased the freshly-merged `perk pr review checkout`/`cleanup` ops
  block, and the tell was that §8.34 still listed the now-orphaned
  `pr-review-checkout`/`pr-review-cleanup` schemas. **Audit a restructure's deletions against
  content that merged after its branch point; orphaned cross-references are the detection signal.**
- **Adapt a plan's dead contract anchors to intent.** A plan written against pre-diet sections
  (key lists, named paragraphs) whose anchors are gone at implement time should land its amendment
  per the restructured discipline — a compact cross-plane subsection where the flow's other ops
  live — honoring the plan's *intent*, not its literal instructions (the guest-reviewer — now
  `adversarial-reviewer` — amendment
  landed as a compact foreign-PR-review ops subsection in §8.4 after all three of its planned
  anchors had been dieted away).

## The cross-plane SSOT prompt-fragment pattern

When a prompt fragment must agree **byte-for-byte across planes**, give each plane one exported
helper (`perk/run/launch.py::_plan_read_instruction` ↔ `extension/doors/lifecycleGates.ts::planReadInstruction`)
plus a shared literal-fragment substring list (`LINEAR_READ_SUBSTRINGS`) asserted from BOTH suites
(`tests/test_worker_prompt_parity.py` ↔ `extension/worker/worker.test.ts`). Choose substrings as
fragments of the *instruction*, not the scaffold — scaffold fragments match every arm and pin
nothing.

## Registry vocabulary keys land with their first declaring stage

The §8.1 deferral discipline is proven: `cache.session-data` was deferred at one node and landed
the moment a stage declared it in `writes` — the Python self-check validates membership
automatically and the TS parser carries lists opaquely, so the whole change is YAML + one pytest
assertion. **Never add registry vocabulary speculatively.**

**Registry `writes` changes trip TWO pytest pins, not one.** Beyond the vocabulary-membership
assertion in `test_stage_io_contract`, stage-shape tests in `tests/test_registry.py` (e.g.
`test_objective_author_is_the_single_initial`) pin a stage's **exact `writes` list**. Grep
`tests/test_registry.py` for the stage id whenever changing any stage's I/O in
`shared/registry.yaml`.

## Wording-pinning tests on both planes are the anti-drift mechanism

For content-parallel prompts (the "mirror factory-threaded guidance on both planes" rule), pin the
same **property list** in both suites — draft tool present, review step present,
approval-carries-link present, old mandate absent — in `node:test` for the TS constant and
`pytest` for the Python seed prompt. Each suite guards its own plane; the shared property list is
the contract. The pinned regexes deliberately couple tests to prose phrasing — that's the drift
alarm, not a defect — so guidance polish must update the pins in **both** suites.

## Adding a registry stage ripples into both planes + hardcoded tests

A new stage in `shared/registry.yaml` ripples to:

1. The validator's **single-initial / symmetric-edge** invariants (`perk/substrate/registry.py`) — the new
   initial must be the *only* stage with no predecessors, and every edge must be listed on both ends.
2. `perk/cli/stages.py` `DEDICATED_STAGES` (if it needs a seeded/positional launcher rather than the
   generic one) + `perk/cli/cli.py` registration.
3. Tests that **hardcode the full stage-id list and the initial assertion**
   (`test_registry.py::test_real_registry_is_valid`,
   `test_cli_stages.py::test_all_stages_are_generated`).

**Grep the stage-id list before assuming a graph change is local.** A new skill also requires
updating BOTH `PERK_SKILLS` in `perk/convergence/init.py` AND the committed manifest fragment
`.agents/manifest.d/perk.yaml` (`perk doctor`'s `skills-manifest` check flags drift).

## Default at the new edge, don't loosen a shared validator

When a new caller wants laxer input than a shared validator enforces, **normalize at the new
boundary**, not by relaxing the shared validator. Example: `objective_save` treats per-node `status`
as optional (defaults `pending`), but shared `validate_roadmap` *requires* it (the YAML path relies
on that) — so the default was applied in the new `parse_structured_roadmap` edge, leaving the shared
validator strict.

## Cross-references

- `perk/substrate/registry.py` — `Issue`/`Severity`, the validator invariants (the canonical first contract)
- `shared/bindings.yaml` + `perk/substrate/bindings.py` + `extension/substrate/bindings.ts` — the second instance
- `tests/test_packaging.py` — the wheel + npm-pack bundle assertions (the publish-surface guard)
- `docs/learned/workflow/skill-bindings.md` — the bindings subsystem this contract underpins
- `docs/learned/workflow/init-doctor.md` — managed-convergence SSOT (the doctor-check side of drift)
- `docs/learned/workflow/linear-backend.md` — the backend-aware prompt arms the parity lists pin
