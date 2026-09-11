---
title: The `/learn` docs scanner and the generated routing tier — deterministic facts, untrusted-text hardening, cue hazards, docs-sync/docs-check
read_when: You are touching `perk/learn/docs_scan.py` or `docs_sync.py`, the learned-doc frontmatter/cue contract, the generated routing block or catalog, or a `perk learn docs-check` finding.
cluster: knowledge-stewardship
---

# The `/learn` docs scanner and the generated routing tier

`scan_docs_richly` (`perk/learn/docs_scan.py`) is the deterministic advisory scan behind the
evidence bundle's `docs_findings` and the docs-factory inbox's `_scan_section`
(`factory_common.py`); `perk/learn/docs_sync.py` derives the routing tier from the same frontmatter
reads and gates it in `docs-check`. §8.35 names ownership; this doc carries the why + the traps.

## Deterministic facts vs analyst judgment

The scan emits only verifiable FACTS: stale `path::symbol` spans; broken doc→doc references
(Markdown links + backtick `.md`/`.mdx` tokens resolved against repo root, doc parent and scan root,
slashless tokens skipped); exact normalized title/`read_when` collisions. The de-dup DECISION is the
analyst's, candidate-vs-corpus; `_duplicate_groups` fires zero times on a curated corpus — a guard,
never the dedup mechanism. Rule: a deterministic detector emits facts + guards; the LLM decides.
Source pointers stay import-path-shaped (`perk/...`), probed literal → src-layout → package form
(`_resolve_source_pointer`) under `_SOURCE_ROOTS` only.

## Validate heuristics against the live corpus

Learned docs cite files as-they-were, so a large share of `missing-file` pointers is intentional
history, not drift; broken links to *renamed* files are the signal. A hygiene scanner is high-recall
by design: tune precision on the real corpus before committing a rule; when cleaning a doc, fix
present-tense mechanics pointers and leave narrative history. The backtick-token widening
(`docs/design/archive/learn-dream-dogfood.md`) repeated the method: a live-corpus survey yielded the
two suppressions above.

## "Never raises" must catch `UnicodeDecodeError` and guard text-derived paths

`except OSError` alone is incomplete: `read_text(encoding="utf-8")` on binary raises
`UnicodeDecodeError` (a `ValueError`), and `.is_file()`/`.resolve()` on a path derived from
untrusted document text can raise `ValueError` (embedded NUL) or `OSError`. Catch
`(OSError, UnicodeDecodeError)` on every read, route text-derived existence checks through
`_is_existing_file` (catching `(OSError, ValueError)`), guard each per-link `resolve()`; degrade to
skip, never crash.

## Frontmatter cue hazards — the plain-scalar family

`title`/`read_when` are parsed by never-raise `yaml.safe_load` (`_frontmatter_dict`); an unquoted
plain scalar fails two ways: an inline `: ` is a YAML error, so the whole parse fails (empty catalog
row + empty ambient cue); an inline ` #` starts a comment, so the parse succeeds and the cue is
silently truncated. Neither shows in parsed values; quoting escapes both. `docs-check` flags the
closed set (`space-hash`, `colon-space`, the parsed-side `multiline`) via `scan_cues` and gates its
exit on them alongside `READ_WHEN_MAX_CHARS`.

## How docs-sync and docs-check derive the routing tier

`read_learned_docs` reads each doc's `title`/`read_when`/`cluster` (never raises; `index.md`
excluded; `(category, slug)` order). `generate_routing_block` renders one line per registry cluster
in registry order, members sorted, unassigned docs falling to per-doc lines; `generate_catalog` one
row per doc; `render_with_markers` splices the marked region. Blast radius: `read_when` → one
catalog row; `title`/H1 → no generated surface; cluster, slug or a new doc → the ambient block.
`check_docs` gates freshness, cue budget/hazards, the cluster gates (`CLUSTER_ROLLUP_MAX_CHARS`),
distillation (`DISTILLATION_THRESHOLD_BYTES`, `DISTILLATION_MAX_LINES`, `DISTILLATION_WINDOW_LINES`)
and the ambient-block budget (`AMBIENT_ROUTING_BLOCK_MAX_BYTES`); advisory hygiene never gates and
`docs-sync` stays permissive. A skipped comparison renders UNCHECKED, never green
(`DocsCheckReport`'s non-compared defaults); preambles vary with the generating mode.

## Cross-references

- `perk/learn/docs_scan.py`, `perk/learn/docs_sync.py`, `tests/test_learned_docs_cues.py`.
- `docs/user-docs/reference/cli/learn-and-gist.md` — `docs-check` exit codes.
- `cold-door-launch.md` — the stale-pointer cleanup judgment.
- `doc-reconciliation.md` § "Deliberate nonzero stale-pointer advisories (`perk learn docs-check`)".
- `learn-evidence-pipeline.md`, `learn-harvest-dream-core.md` — the siblings.
