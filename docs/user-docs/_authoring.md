# Authoring the operator docs

This file is **maintainer-facing**: it is never routed on the docs site and never
search-indexed. The `_` basename prefix keeps it out of the site collection (the
`docs/site/src/content.config.ts` glob pattern `**/[^_]*.{md,mdx}`) **and** out of the
learn-evidence docs inventory (`src/perk/learn/docs_scan.py` applies the same admission rule).
It deliberately carries no frontmatter. The binding source for everything below is
[`docs/design/docs-site-blueprint.md`](../design/docs-site-blueprint.md) §6 — this file is the
working reference that later authoring passes extend; the blueprint stays the record of what is
bound.

## Divio editorial contracts

- **Tutorial** — one live-run path with observable results at each stage and a recap of what
  the reader accomplished. The reader follows; the tutorial guarantees the outcome.
- **How-to** — one bounded goal per guide; imperative, ordered steps; refusal states
  documented at the step where they occur, with the recovery move.
- **Reference** — exact names, defaults, precedence, and failure modes, verified against
  code / `--help` / schemas; parallel structure across entries of the same kind.
- **Explanation** — relationships and trade-offs; no ordered steps, no reference tables that
  belong in the reference quadrant.

Cross-cutting: **one primary intent per page** (a page serves exactly one quadrant), and
**routed-or-excluded accounting** (every canonical source file is routed exactly once or
explicitly excluded — no orphans).

## Voice rules

- Second person, present tense, result first.
- `perk` and `Pi` spelling; exact case and punctuation for commands, file paths, config
  tables, and warm doors (`/plan-save`, `[[ci.checks]]`, `perk objective plan`).
- Define a term once (the glossary is the durable home); after that, use it.
- **No contributor provenance or plan-history language in reader copy** — no node/phase/PR
  numbers, no maturity confessions in the reader's path (maturity caveats live in clearly
  scoped caveat sections, e.g. the providers hub).
- Sparing callouts — a callout must earn its interruption.
- Descriptive link text; never "here".

## Metadata contract

Every routed page (every non-`_`-prefixed `.md`/`.mdx` file in this tree) carries YAML
frontmatter in exactly this shape — `---` fences at byte 0, LF line endings:

```yaml
---
title: "How to resume a plan at its current stage"
description: "Re-enter an in-flight plan from a cold shell at whatever lifecycle stage it left off."
sidebar:
  order: 2020
sidebarGroup: "Core workflow"
---
```

- **`title` (required)** — **byte-equal to the page's standalone `#` H1 text**, which every
  source file keeps (the dual-presentation rule below). Change one, change both.
- **`description` (required)** — one sentence, unique corpus-wide, reader-centered, present
  tense, derived from the page's opening/lede.
- **Quoting** — `title` and `description` are always **double-quoted** (a wholesale escape
  from the YAML plain-scalar hazard family: an inline `: ` fails the whole parse, an inline
  ` #` silently truncates). Avoid embedded double quotes in titles and descriptions.
- **`sidebar.order` (required)** — the per-page record of the page's blueprint §3 sidebar
  position, numbered so it survives Starlight's min-order directory weighting: a **1000-block
  per section** (root home page `0`, tutorials `1000`, how-to `2000`, reference `3000`,
  explanation `4000`); each section's `index.md` carries the block base; children ascend in
  steps of 10. Insert a new page at the midpoint between its neighbors (e.g. `2105` between
  `2100` and `2110`). Orders are unique within a directory and never leave their section's
  block.
- **`sidebarGroup` (conditionally required)** — the navigation-**ownership** record where
  ownership is not structural: the flat `how-to/` tree renders as the five §3 operator groups,
  so every routed `how-to/` page except `index.md` carries exactly one of **Core workflow**,
  **Objectives & learnings**, **Headless & remote**, **Customization**, **Providers &
  backends** — and the field is absent everywhere else (elsewhere, ownership is the
  directory/section). Pages sharing a group occupy a contiguous `sidebar.order` range, and the
  five ranges appear in §3 group order.
- **`sidebar.label` (optional)** — the only optional field: a sidebar display-label override,
  used when the full title is too long for the sidebar; recorded at migration time.

Titles and routes are unique corpus-wide. **Plain Markdown is the default**; MDX is admitted
only where a content component materially improves comprehension, stays reviewable, and is
explicitly accounted for in source inventory and learn-evidence scans.

## Dual-presentation rule

Canonical Markdown stays pleasant and structurally correct on GitHub: one visible H1 and a
readable body. The site renders one semantic H1 from frontmatter `title`, with
first-source-H1 suppression in the rendered body only (`docs/site/src/remark-strip-first-h1.mjs`).
Acceptance covers both presentations.

## Enforcement pointers

Two surfaces enforce this contract; a violation fails one of them, naming the file:

- **`tests/test_user_docs_metadata.py`** (runs in `just test` and CI) — the routed-or-excluded
  accounting (this file is the only permitted exclusion; any other file must be routed, and
  only `.md`/`.mdx` files are admitted at all), frontmatter presence and shape, the byte-equal
  title↔H1 rule, corpus-wide title/description/route uniqueness, the `sidebar.order` block
  discipline, and the `sidebarGroup` requiredness/absence + contiguity discipline.
- **The site build** (`just docs-build`) — Starlight's `docsSchema()` requires `title`, and the
  schema extension in `docs/site/src/content.config.ts` requires a non-empty `description` and
  validates `sidebarGroup` against the closed five-group set, with file-precise errors.
