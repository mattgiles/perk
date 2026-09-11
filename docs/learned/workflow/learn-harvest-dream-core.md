---
title: The harvest/dream gather-and-partition core — containment, lane routing, refuse vs filter, snapshot cleanliness, the two-level dream wave
read_when: You are touching `perk/learn/harvest.py` or `dream.py`, lane partitioning, the harvest/dream manifest, or the `perk learn harvest`/`dream` preflight and refusal arms.
cluster: knowledge-stewardship
---

# The harvest/dream gather-and-partition core

## The harvest gather/partition core

`src/perk/learn/harvest.py` is the pure core the docs-harvest consumers build on —
`resolve_harvest_docs` (target resolution over `docs/learned/`) + `partition_lanes`
(deterministic per-group lane chunking); the downstream handoffs (single- vs multi-lane routing
is decided by the **lane count**, never a total-doc count; the TS validator pins
`schema_version` as the byte-identical string `"1"`) are encoded in `harvest.py`'s docstrings —
point there, don't duplicate.

### Pipeline-fed test suites silently under-test downstream ordering contracts

When every test case routes the composed pipeline (resolver output → partition), the suite stays
green even if the downstream function stops sorting — the upstream already emits sorted order.
For any pure function whose contract includes ordering/determinism, include at least one
**direct-input** case where input order and the competing sort key *diverge* (the shipped test
constructs shuffled nested-path docs pushing a doc across the chunk boundary). This generalizes
beyond harvest: a fully enumerated test matrix misses it whenever all cases compose the pipeline.

### The "eligible corpus" containment pattern for path-selection APIs

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

### The per-lane report cap vs the parent's global curation

The harvest-analyst lane caps its report at **≤5** ranked opportunities (+ `omitted_count`),
while the parent's curation policy (`skills/perk-learn-harvest/SKILL.md`) selects a global
top-≤8 — a lane with >5 high-rank candidates exposes only 5 + a count, which can starve
cross-lane curation. Deliberately kept (user-ratified), and re-affirmed now that multi-lane
harvests run live through `run_harvest_wave` (contracts §8.48): `HARVEST_MAX_OPPORTUNITIES`
stays 5 — starvation is made *visible* (a nonzero `omitted_count` is disclosed in coverage
reporting, with a bounded `--from` re-run scoped to that lane's exact doc paths as the deepening
move: ≤ 8 docs partitions to one lane and is analyzed directly, uncapped) rather than widened
away; widening stays a one-constant edit.

### Orthogonal error-vocabulary composition

`invalid_from` is purely per-target (containment/existence); `no_harvest_docs` is purely "the
union selected zero docs" — keeping them orthogonal removes any ambiguity about which error wins
on mixed inputs.

### Refusal ordering + refuse-vs-filter over the shared primitive

- **Refusal ordering over never-raising scanners:** the primitive failure (readability) precedes
  any derived classification (membership) — pinned as §8.59's "readability precedes
  membership". Test the failure on the richest mode path: the registry-absent path bypassed the
  buggy ordering entirely (#2001).
- **Refuse-vs-filter is a caller-side posture split over one shared primitive**
  (`eligible_learned_docs`): harvest keeps silent-filter semantics; dream derives its refusal by
  diffing against the raw enumeration — the posture lives in the caller, not as a flag on the
  primitive (#2001).

## The dream door's cleanliness census

- **`git status --porcelain` cleanliness proofs have three blind spots** — gitignored files,
  assume-unchanged/skip-worktree index flags (probe `git ls-files -v` for lowercase/`S` tags),
  and sparse checkouts (tracked files absent from disk). The census for any snapshot proof:
  status-clean + no index flags + TWO-SIDED set equality between the filesystem enumeration and
  the tracked set — each direction defends a different failure (#1990).
- **Fail-open helpers must not serve fail-closed boundaries.** When two `None` causes need
  different repair actions, grow a strict twin (`git.head_commit` raising `GitError` vs
  `resolve_commit`'s fold-to-`None`) and document the split on both (#1990).
- **Operational facts:** an open same-origin curation objective blocks `perk learn dream` with
  `origin_conflict` by design until it completes. Dated calibration point — 66 docs / 13
  clusters ⇒ 14 analyst lanes + 3 reducers, a ~15 min wave, and a 127 KB finalized bundle
  against the 384 KB budget (#2006).
- **Credential-smoke prompts must demand no punctuation** — an exact-match `READY` expectation
  fails on `READY.` (#2006).

