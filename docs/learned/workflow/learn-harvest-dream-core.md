---
title: The harvest/dream gather-and-partition core — containment, lane routing, refuse vs filter, snapshot cleanliness, the two-level dream wave
read_when: You are touching `perk/learn/harvest.py` or `dream.py`, lane partitioning, the harvest/dream manifest, or the `perk learn harvest`/`dream` preflight and refusal arms.
cluster: knowledge-stewardship
---

# The harvest/dream gather-and-partition core

`perk/learn/harvest.py` is the pure core (`resolve_harvest_docs`, `partition_lanes`);
`perk/learn/dream.py` builds the complete-corpus dream gather on it. §8.48/§8.59/§8.61/§8.65 pin the
shapes; this doc carries the why + the traps.

## Containment before selection

Filter the enumerator's output once by resolved-path containment against the root, before any
selection arm: the default selection is then ≡ an explicit root target by construction and escaped
symlinks are excluded everywhere; targets get the mirrored posture (resolve, then check).
`is_relative_to` covers equality, so one predicate serves file, directory and root. A containment
check is only as trusted as its root: a symlinked `docs/learned` would launder outside-tree files
into the manifest, so validate the root first (`learned_root.is_relative_to(repo_root)` →
`invalid_input`).

## Lane routing and deterministic partition

Routing is decided by lane count, never total docs; the per-lane cap is `MAX_LANE_DOCS` (pinned by
`tests/test_learn_harvest.py::test_max_lane_docs_pinned`). `schema_version` is a **string** the TS
decoders pin byte-identical (`MANIFEST_SCHEMA_VERSION` / `DREAM_MANIFEST_SCHEMA_VERSION`,
independent lines). Pipeline-fed suites under-test downstream ordering (every case routing resolver
→ partition stays green if the partition stops sorting), so an ordering contract needs one
direct-input case where input order and sort key diverge
(`test_partition_sorts_shuffled_input_independently_of_resolver`). The per-lane report cap
(`HARVEST_MAX_OPPORTUNITIES`, `extension/learning/harvest.ts`) sits below the skill's global roadmap
cap, so a rich lane can starve cross-lane curation — kept deliberately: starvation is visible via
`omitted_count`, deepening is a bounded `--from` re-run of at most `MAX_LANE_DOCS` docs (one lane,
uncapped), widening a one-constant edit (§8.48).

## Refuse vs filter, and refusal ordering

`invalid_from` (per-target) and `no_harvest_docs` (empty union) stay orthogonal, so mixed inputs are
unambiguous. Refuse-vs-filter is a caller-side posture over the shared `eligible_learned_docs`:
harvest filters an escaping doc silently, dream refuses by diffing against the raw enumeration —
never a flag on the primitive. Readability precedes membership (§8.59): an unreadable doc is
reported before any derived classification. Test such failures on the richest mode path; the
registry-absent path once bypassed the buggy ordering (#2001).

## Snapshot cleanliness and the dream preflight

`git status --porcelain` has three blind spots (gitignored files, assume-unchanged/skip-worktree
index flags, sparse checkouts), so a snapshot proof is status-clean + no `ls-files -v` flags +
two-sided set equality between the filesystem enumeration and the tracked set (#1990). Fail-open
helpers must not serve fail-closed boundaries: `git.head_commit` is the strict twin of
`resolve_commit` (`GitError` instead of folding to `None`). An open same-origin curation objective
blocks `perk learn dream` with `origin_conflict` by design. Reducers run only after a complete
analyst wave (§8.61), over a bundle bounded by `DREAM_BUNDLE_BUDGET_BYTES`
(`extension/learning/dreamReducer.ts`). History: the first live dream (#2006) ran 14 analyst lanes +
3 reducers in ~15 min. Credential-smoke prompts must demand no punctuation: exact-match `READY`
fails on `READY.`.

## Cross-references

- `perk/learn/harvest.py`, `perk/learn/dream.py`.
- `perk/cli/commands/learn/dream_cmd.py` — the preflight census.
- `skills/perk-learn-harvest/SKILL.md` — the global roadmap cap.
- `docs/design/archive/learn-harvest-dogfood.md`, `docs/design/archive/learn-dream-dogfood.md`.
- `broad-catch-narrowing.md` — path-containment guards.
- `learn-docs-scan.md`, `learn-evidence-pipeline.md` — the siblings.
