# Authoring the operator docs

This file is **maintainer-facing**: it is never routed on the docs site and never
search-indexed. The `_` basename prefix keeps it out of the site collection (the
`docs/site/src/content.config.ts` glob pattern `**/[^_]*.{md,mdx}`) **and** out of the
learn-evidence docs inventory (`src/perk/learn/docs_scan.py` applies the same admission rule).
It deliberately carries no frontmatter. The binding source for everything below is
[`docs/design/docs-site-blueprint.md`](../design/docs-site-blueprint.md) §6 — this file is the
working reference that later authoring passes extend; the blueprint stays the record of what is
bound.

## Scope: the operator, never contributors

This tree is the documentation for the **operator** — someone using perk on their own
repository. It is never for perk contributors: perk's internal research and planning record
lives in [`docs/guiding-principles/`](../guiding-principles/), [`docs/design/`](../design/),
and [`shared/contracts.md`](../../shared/contracts.md), and is never duplicated here. (Links
from this file are unswept — it sits outside the routed corpus.)

The tree follows the [Divio documentation system](https://docs.divio.com/documentation-system/):
documentation is not one thing but **four distinct kinds**, each answering a different reader
need — learning (tutorials), achieving a goal (how-to), looking something up (reference), and
understanding (explanation). Mixing them is the system's named failure mode ("the tendency to
collapse"): a tutorial that digresses into rationale stops being learnable; a reference that
instructs stops being trustworthy. Each kind gets its own directory, and every page belongs to
exactly one.

## Divio editorial contracts

- **Tutorial** — one live-run path with observable results at each stage and a recap of what
  the reader accomplished. The reader follows; the tutorial guarantees the outcome. Accuracy
  is gated by a live run-through on a scratch repo before a tutorial lands, and the quadrant
  stays deliberately small — anything beyond the basics belongs in how-to.
- **How-to** — one bounded goal per guide, titled "How to …"; imperative, ordered steps;
  refusal states documented at the step where they occur, with the recovery move. Guides
  assume the basics and never re-teach them — tutorials own the teaching.
- **Reference** — exact names, defaults, precedence, and failure modes, verified against
  code / `--help` / schemas; parallel structure across entries of the same kind. The CLI
  reference is written against real `--help` output and guarded by a pytest existence check,
  so a documented-but-missing command fails CI.
- **Explanation** — relationships and trade-offs; no ordered steps, no reference tables that
  belong in the reference quadrant. Opinions and trade-offs are welcome here — admit what was
  considered and why it was declined. This boundary is machine-enforced over the live corpus
  by `tests/test_explanation_boundary.py` (runs in `just test` and `just docs-check`), with
  these exact rules: outside fenced code blocks, no `explanation/` source (`.md` or `.mdx`)
  may contain an ordered-list marker (`1. …` / `1) …`, at any indentation) or a
  Markdown/HTML table; and every article except the landing (`explanation/index.*`) must end
  in a final `## Related` section of 1–3 one-item links in the standard shape below, labeled
  only **Understand**, **Do**, or **Look up**, with at least one **Do** or **Look up** route
  out to task/reference material. The landing is exempt only from the `Related` requirement,
  not from the no-ordered-list/no-table rule.

Cross-cutting: **one primary intent per page** (a page serves exactly one quadrant), and
**routed-or-excluded accounting** (every canonical source file is routed exactly once or
explicitly excluded — no orphans).

## Related links

The bounded onward-pointer convention for article pages (applied by the batch migration
passes, never ad hoc): a page that carries onward pointers ends with a final `## Related`
section of **at most 3 items**, each shaped

```markdown
- **<Label>:** [Page title](relative-path.md) — why.
```

with the label drawn only from the closed set **Learn** (tutorials), **Do** (how-to),
**Look up** (reference), **Understand** (explanation). In the Explanation quadrant this
convention is mandatory and machine-enforced with the narrower label subset (no **Learn**) —
see the Explanation contract above; the other quadrants keep this general vocabulary.

Corpus-wide, the trailer is now the rule, not the exception: every routed article page ends
with a `## Related` section, guarded by `tests/test_user_docs_findability.py` (shape, the
1–3 bound, the closed label set). The only pages without one are the **deliberate
omissions** — the pure routers and the lookup index: the home page, the four quadrant
landings, and the glossary carry no Related trailer, and the guard's frozen allowlist pins
exactly that set (an allowlisted page that gains a trailer fails as a stale entry).

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
  explanation `4000`); each section's index page (`index.*` — the section index by stem)
  carries the block base; children normally ascend in steps of 10. Insert a new top-level page
  at the midpoint between its neighbors (for example, `2105` between `2100` and `2110`). When a
  hub splits into nested children and the flattened sidebar has no 10-step slots before the next
  page, the children may use consecutive integers after the hub (for example, `3021`–`3024` after
  `3020`). Orders remain unique within each directory and never leave their section's block.
- **`sidebarGroup` (conditionally required)** — the navigation-**ownership** record where
  ownership is not structural: the flat `how-to/` tree renders as the five §3 operator groups,
  so every routed `how-to/` page except the section index carries exactly one of **Core workflow**,
  **Objectives & learnings**, **Headless & remote**, **Customization**, **Providers &
  backends** — and the field is absent everywhere else (elsewhere, ownership is the
  directory/section). Pages sharing a group occupy a contiguous `sidebar.order` range, and the
  five ranges appear in §3 group order.
- **`sidebar.label` (optional)** — a sidebar display-label override, used when the full title
  is too long for the sidebar; recorded at migration time.
- **`prev` / `next` (optional)** — per-page pagination opt-in (`true` renders the
  flattened-sidebar neighbor in that direction). Global pagination stays off; these keys are
  allowed **only for a deliberately linear reading sequence** — currently exactly the
  tutorials chain (`get-started → drive-an-objective → drive-a-stacked-objective`, four
  edges: no prev into the tutorials landing, no next out of the last tutorial). The exact
  key placement is guarded by `tests/test_user_docs_findability.py`, the rendered edges by
  `docs/site/checks/built-site.test.mjs`.

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
