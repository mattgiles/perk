---
title: Shell check fixture
description: Disposable fixture page exercising tables, code blocks, and fonts in the shell.
---

This page is a **disposable node-2.1 fixture** (removed by node 2.2). It exercises
the shell visually: the token palette in both themes, Inter Variable prose, IBM
Plex Mono code, GFM tables, and Expressive Code defaults — and gives Pagefind
indexable content to build a search index over.

## A GFM table

| Stage     | Owner    | Result                 |
| --------- | -------- | ---------------------- |
| plan      | operator | a reviewed plan issue  |
| implement | agent    | a bounded change       |
| submit    | agent    | a draft pull request   |

## A fenced code block

```sh
just docs-dev
just docs-build
just docs-preview
```

Inline code such as `docs/site/astro.config.mjs` renders in IBM Plex Mono, while
this prose paragraph renders in Inter Variable on the theme canvas.
