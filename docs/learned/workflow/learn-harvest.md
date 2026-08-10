---
title: The learn harvest gather/partition core
read_when: You are touching src/perk/learn/harvest.py, a docs-harvest consumer or lane ceiling, a path-selection containment API, or testing a pipeline-fed ordering contract.
---

# The learn harvest gather/partition core

`src/perk/learn/harvest.py` is the pure core the docs-harvest consumers build on:
`resolve_harvest_docs` (target resolution over `docs/learned/`) + `partition_lanes`
(deterministic per-group lane chunking). The downstream handoffs — the phase-1 ceiling must gate
on the **lane count**, never a total-doc count; the TS validator must pin `schema_version` as the
byte-identical string `"1"` — are encoded in `harvest.py`'s docstrings: point there, don't
duplicate.

## Pipeline-fed test suites silently under-test downstream ordering contracts

When every test case routes the composed pipeline (resolver output → partition), the suite stays
green even if the downstream function stops sorting — the upstream already emits sorted order.
For any pure function whose contract includes ordering/determinism, include at least one
**direct-input** case where input order and the competing sort key *diverge* (the shipped test
constructs shuffled nested-path docs pushing a doc across the chunk boundary). This generalizes
beyond harvest: a fully enumerated test matrix misses it whenever all cases compose the pipeline.

## The "eligible corpus" containment pattern for path-selection APIs

Filter the enumerator's output *once* by resolved-path containment against the root before any
selection arm — the default selection becomes ≡ an explicit root-directory target *by
construction* (no per-arm symlink policy to keep in sync), and escaped symlinks are excluded
everywhere. Targets get the mirrored posture (resolve before the containment check, so an
escaping symlink is invalid). Bonus idiom: `is_relative_to` covers equality, so one predicate
serves file-equality, directory-containment, and the root-passes-containment cases.

**A containment check is only as trusted as its root.** A `docs/learned` that is itself a symlink
out of the repository would make the outside target the trusted containment root and launder
outside-tree files into the manifest (which the launched session is then told to read). Validate
the root first — `learned_root.is_relative_to(repo_root)` → `invalid_input`, guarded in
`src/perk/learn/harvest.py` with a core test — before any per-doc containment runs.

## Watch item — the per-lane report cap vs the parent's global curation

The harvest-analyst lane caps its report at **≤5** ranked opportunities (+ `omitted_count`),
while the parent's curation policy (`skills/perk-learn-harvest/SKILL.md`) selects a global
top-≤8 — a lane with >5 high-rank candidates exposes only 5 + a count, which can starve
cross-lane curation. Deliberately kept (user-ratified; phase 1 is single-lane via the door
ceiling anyway), but the wave-schema owner must revisit the cap against the curation policy when
multi-lane harvests arrive.

## Orthogonal error-vocabulary composition

`invalid_from` is purely per-target (containment/existence); `no_harvest_docs` is purely "the
union selected zero docs" — keeping them orthogonal removes any ambiguity about which error wins
on mixed inputs.
