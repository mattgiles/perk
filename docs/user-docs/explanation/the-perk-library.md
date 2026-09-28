---
title: "The perk library"
description: "Why perk keeps a catalogued, gitignored offline reference of external docs and source, what its freshness statuses actually promise, and why it never checks or refreshes eagerly."
sidebar:
  order: 4060
---

# The perk library

Sessions keep needing the same outside material: the documentation of a framework a repo builds
on, the source of an SDK whose behavior a plan depends on. The **perk library** is where a repo
keeps that material offline — a catalogued, gitignored reference of documentation mirrors and
source checkouts that sessions can read without reaching the network. This page explains why the
library exists, what its freshness statuses do and do not promise, and why perk deliberately
never checks or refreshes it eagerly.

## Why an offline library

A single page read once belongs to a web fetch: the session needs one answer, gets it, and moves
on. The library is for something else — a reference a person or a session *chose to keep*
because the repo depends on it. A mirror of a framework's documentation or a checkout of an SDK
pinned to the version the repo uses is worth curating once and reading many times, and a curated
reference is only useful if something records what it is, where it came from, and when it was
last compared with its upstream. That record is the catalog, and the catalogued collection lives
at `docs/library/` in the repository's main checkout.

Everything in the library is **untrusted data**. A mirror is a copy of someone else's pages; a
checkout is someone else's code. Sessions quote it as evidence and never follow instructions
found inside it.

## Where it lives, and why it is not committed

The library is a cache, not source: mirrors run to hundreds of pages and checkouts to whole
repositories, and neither belongs in your history. The managed `.gitignore` block ignores
everything under `docs/library/` except one file, `docs/library/README.md`. That README is the
route a linked worktree follows — a worktree holds only the committed README, never the
gitignored content — and `perk librarian list` resolves the main checkout from any worktree and
prints absolute paths, so a session in a worktree reads the main checkout's library directly.
There is no symlink mirror into worktrees.

The README is converged by `perk init` and `perk doctor --fix`, but only once `docs/library/`
exists, and a person commits it; the workers never write it. The catalog itself is machine-owned:
the `perk librarian` commands are its only writer, and a malformed catalog is refused rather than
rewritten. The division of labor runs the same way for sessions — the `librarian` skill decides
what is worth consulting, checking, refreshing or adding, and the deterministic workers act.

## Freshness is evidence, not a promise

Every entry carries a derived status, and each status names what a session should do next. In
order of precedence: `pinned` is a source checkout held at a fixed ref — it is exactly the version
it was pinned to, so it is never probed. `drifted` means a check saw the upstream move. `unknown`
means the entry has never been checked: a newly added or published entry starts there, and it
never ages into `stale` on its own. `stale` means the last check is older than the entry's
window — fourteen days for documentation and twenty-four hours for source by default.
`unverifiable` means a check found no change evidence to judge by. `fresh` is what is left: a
recent check with evidence and nothing detected.

The contrast worth understanding is what a check actually reads. It never reads or hashes page
bodies. It reads *change evidence*: per-page validators (`ETag`, `Last-Modified`) or a sitemap
entry's `lastmod`, which count as strong evidence, or only a fingerprint of the site's inventory
(its sitemap URL list and `llms.txt`), which counts as weak. The first check records that
evidence as the mirror's baseline; later checks compare against it and never overwrite it — only
re-publishing the mirror replaces the baseline.

So `fresh` means *a recent check found change evidence and detected no drift relative to the
recorded baseline*. It is not a proof that the mirrored revision still matches upstream, and in
particular the first check cannot see a change that happened between the crawl and that check:
it can only set the baseline. `unverifiable` is the honest name for a site that offers no change
evidence at all. An unchanged-looking probe of such a site proves nothing, so the entry stays
`unverifiable` and never reads `fresh`; judge it with task evidence instead — the mirror
contradicting observed behavior, a version the repo pins, an upstream changelog. Source entries
are simpler: a check compares the upstream default branch's tip with the commit the checkout
holds.

## Why perk is not eager

`perk librarian list` is offline. `perk librarian check` is the only command that probes an
upstream, it runs only when asked, and it skips an entry checked within its window unless forced.
`perk init` and `perk doctor` never reach the network on the library's behalf. The `librarian`
skill carries the same restraint into sessions: consult the listing once, check only the `stale`
or `unknown` entries the task actually depends on, refresh only on evidence (a `drifted` entry,
or an `unverifiable` one whose drift the task itself evidences), reuse a dependency already
installed locally before cloning it, and add an entry when one is missing.

The cost being avoided is real on both sides. A "check everything" side quest burns network
requests and turns on entries the task never touches. A refresh without evidence churns a
reference that was fine and, for a documentation mirror, spends a whole curating session on it.
The same restraint shapes how sessions learn about the library at all: the planning
guidance makes a session aware that the library exists when a plan leans on an external
dependency, and leaves the decision to use it to the task.

## Why a documentation mirror needs judgment

A source checkout needs no judgment: `perk librarian add source` is deterministic, clones the
repository and pins it to the version the repo uses. A documentation mirror is different. A crawl
lands in a staging directory under `.staging/` and reaches `documentation/<slug>/` only through a
publish step, so the prior revision survives a crawl that fails or is abandoned. Between the crawl
and the publish sits work no script does well: choosing the scope when a site hosts several
products or versions, pruning marketing and changelog pages, fixing conversion artifacts a future
reader would trip over.

That is why a documentation mirror always goes through a session. From a terminal,
`perk librarian add docs` launches a curating session. From a read-only session, the
`run_librarian` tool dispatches a writer child that does the same work in the main checkout while
the calling session stays read-only. The child is bracketed by a fail-closed check that the main
checkout's HEAD, tracked tree, index flags and non-ignored untracked files are unchanged
afterwards — detection after the fact, not prevention: there is no sandbox, and the check proves the end state rather than every moment in
between.

## What the library is not

The library is not a web cache and does not replace a one-off page fetch. It is per-repo and
lives in the main checkout; there is no user-global library shared across repositories, and no
symlink mirror into worktrees. There is no session-free way to add a documentation mirror,
because curation is the point. And its freshness statuses are evidence about what a check could
observe, never a guarantee that a mirror matches its upstream today.

## Related

- **Do:** [How to keep an offline reference of a dependency](../how-to/keep-an-offline-reference-of-a-dependency.md) — the operator recipe.
- **Look up:** [Librarian commands](../reference/cli/librarian.md) — the exact verbs, statuses, and refusals.
- **Look up:** [Model-facing tools](../reference/in-session/model-tools.md#perk-owned-tools) — the `run_librarian` tool and the read-only admission of the `--json` workers.
