---
title: The `/learn` docs scanner and the generated routing tier — deterministic facts, untrusted-text hardening, cue hazards, docs-sync/docs-check
read_when: You are touching `perk/learn/docs_scan.py` or `docs_sync.py`, the learned-doc frontmatter/cue contract, the generated routing block or catalog, or a `perk learn docs-check` finding.
cluster: knowledge-stewardship
---

# The `/learn` docs scanner and the generated routing tier

## The rich existing-docs scan (`scan_docs_richly`) — facts feed judgment

`scan_docs_richly` (`perk/learn/docs_scan.py`) is the deterministic, advisory corpus scan consumed by
both `perk/learn/evidence.py` (the bundle manifest's `docs_findings`) and the docs-factory inbox
(`factory_common.py`'s `_scan_section`). It surfaces verifiable facts about the three docs roots so
the docs-plan analyst can do cleanup-first + UPDATE-vs-NEW placement. Three cross-cutting learnings:

- **Deterministic-FACTS vs LLM-JUDGMENT split.** The Python layer emits only **verifiable FACTS** —
  stale source pointers (phantom `path::symbol` spans), broken doc→doc references (Markdown links
  **plus** full-span backtick `.md`/`.mdx` path tokens, the latter tri-base-resolved — repo root /
  doc parent / the doc's scan root — with slashless name-mentions skipped), and exact normalized
  title/`read_when` collisions. The de-dup **DECISION** stays with the LLM analyst and is
  **candidate-vs-corpus** ("does THIS capture already live in an existing doc?"), powered by those
  facts plus the full docs inventory — the scan **never decides de-dup**. Within-corpus
  exact-collision detection (`_duplicate_groups`) fires **0× on a curated corpus** (every title is
  unique), so it is a cheap **GUARD, never the dedup mechanism**. Reusable rule: whenever you split
  a deterministic detector from an LLM decider, the detector emits facts + guards; the decision is
  the model's.

- **Validate detection heuristics against the LIVE corpus — learned docs intentionally carry
  historical pointers.** The rules were shaped by running them on `docs/learned` live: **~30% of
  code-pointers are `missing-file`** because learned docs cite filenames **as-they-were**
  (landing-log narrative surviving module→package splits) — **intentional history, NOT drift to
  fix**. Broken catalog links to *renamed* files are the high-value signal. A corpus-hygiene
  scanner is **high-recall by design** — weigh findings by relevance and tune precision against the
  real corpus before committing the rules. (This is the principle that governs a doc-cleanup
  judgment call: fix present-tense mechanics pointers, leave narrative history — see
  `cold-door-launch.md`'s stale-pointer cleanup.) The backtick doc-token widening repeated the
  method: at the dream-dogfood audit (`docs/design/archive/learn-dream-dogfood.md`, objective #1926, commit
  `5c3b5058`) the deterministic scan was blind to the analysts' verified stale `docs/planning/…`
  backtick refs, and a live-corpus acceptance survey of every backtick `.md`/`.mdx` token (326
  doc/token pairs) produced the two suppressions — skip slashless tokens, add the scan-root
  resolution base — that cut ~100+ structural false positives down to the genuine handful.

- **"Never raises" must catch `UnicodeDecodeError` and guard text-derived path ops.** A file scanner
  guarded only by `except OSError` is **incomplete**: `read_text(encoding="utf-8")` on a
  non-UTF-8/binary file raises `UnicodeDecodeError` (a `ValueError` subclass, **not** `OSError`),
  and `.is_file()`/`.resolve()` on a path **derived from untrusted document text** can raise
  `ValueError` (embedded NUL) or `OSError` (OS-illegal chars). The airtight pattern (as built):
  catch `(OSError, UnicodeDecodeError)` on **every** read, route text-derived existence checks
  through a guarded helper (`_is_existing_file` catching `(OSError, ValueError)`), and wrap the
  per-link `resolve()` in its own try/except → degrade to skip. Absence/badness always degrades to
  "skip this finding", never a crash out of the advisory scan.

- **The plain-scalar hazard family: two YAML traps in a learned doc's frontmatter, enforced by
  `docs-check`.** A learned doc's `title`/`read_when` are parsed by never-raise `yaml.safe_load`
  (`_frontmatter_dict` in `src/perk/learn/docs_scan.py`), and an unquoted plain scalar has two
  distinct failure members: an inline `: ` (colon-space) is a YAML error, so the **whole
  frontmatter parse fails** — `_frontmatter_dict` degrades to `{}` and the doc gets an empty
  index row + empty ambient routing cue; an inline ` #` (space-then-hash) starts a YAML comment,
  so the parse **succeeds** and the cue is **silently truncated** (looks valid, measures short).
  They manifest differently (parse failure vs truncation), neither is detectable from parsed
  values alone, and quoting the scalar escapes both. Enforcement: `perk learn docs-check` flags
  the closed hazard set (`space-hash`, `colon-space`, `multiline`) via `scan_cues` in
  `src/perk/learn/docs_sync.py` and **gates its exit** on them (exit 0 ok · 1 stale or cue
  violation · 2 not-a-repo), alongside the 200-char parsed-value ceiling (`READ_WHEN_MAX_CHARS`);
  the live-corpus pytest `tests/test_learned_docs_cues.py` enforces the same budget in CI.

- **A skipped gate must render UNCHECKED, never green.** When an invalid cluster registry makes
  the docs-check freshness comparison impossible, the report's defaults (`fresh=True`, an empty
  stale set) mean "not compared", not "fresh" — document the non-compared semantics on the report
  shape and render the gate as UNCHECKED, or a broken registry silently reads as a passing gate.
  Companion trap: **generated artifacts that embed their own explanation must vary with the
  generating mode** — a legacy-mode repo must not receive a bootstrap preamble describing a
  registry it doesn't have; when a generator grows modes, sweep its baked prose constants for
  mode-specific claims.

