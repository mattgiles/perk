---
title: "How to keep an offline reference of a dependency"
description: "Mirror a dependency's documentation or clone its source into the perk library, check its freshness only when a task depends on it, and refresh it on evidence."
sidebar:
  order: 2139
sidebarGroup: "Core workflow"
---

# How to keep an offline reference of a dependency

The perk library is a per-repo, catalogued offline reference of external documentation mirrors
and source checkouts. It lives in the repository's main checkout under `docs/library/`, and
everything in it except one README is gitignored. Planning sessions reach it through the shipped
`librarian` skill — there is nothing to configure. This guide keeps a dependency's docs or source
in the library, checks it only when a task depends on it, and refreshes it on evidence.

**Prerequisite:** `perk init` has synced perk's skills (the `librarian` skill is at
`.agents/skills/librarian/`); for documentation mirrors, `curl` and `html2markdown` are on `PATH`
(`brew install html2markdown`).

## Steps

1. **See what the repo already keeps.** Run `perk librarian list`. It is offline and lock-free,
   works from any worktree, and prints absolute paths under the main checkout, one line per entry
   with its status. It also lists `uncatalogued:` directories, each with a copyable
   `perk librarian record --adopt …` hint, and leftover `staging:` directories. An absent library
   is not an error — the list is simply empty.
2. **Reuse before acquiring.** The dependency is often already on disk: look under
   `node_modules/<pkg>/` or `.pi/npm/node_modules/<pkg>/` (its `src/` and `docs/`, and
   `package.json`'s `repository` and `version`), or at
   `.venv/lib/python*/site-packages/<dist>-<version>.dist-info/METADATA`. Clone or mirror only when
   that is insufficient or you want a retained, pinned reference.
3. **Keep source code.** Run `perk librarian add source <repo-ref> --ref <pin>`, where `<repo-ref>`
   is `owner/repo`, `host/org/repo`, `https://…`, `ssh://…`, or `git@host:org/repo`. Pin to the
   version the repo uses — read it from the lockfile, `package.json`, or `pyproject.toml`. Private
   repositories need the `git@…` or `ssh://…` form: the library's git runs config-pinned, with no
   credential helper. Rerunning the same command is idempotent (`reused`); a different `--ref`
   re-pins the checkout.
   - `invalid_repo_ref` — the reference is not one of the accepted forms; rewrite it.
   - `ref_not_found` — the pin resolves to no tag, branch, or commit; check the version.
   - `checkout_dirty` — a re-pin found uncommitted changes in the checkout; commit, stash, or
     discard them, then rerun.
   - `slug_exists` — another entry already uses the slug; rerun with `--slug <slug>`.
4. **Keep documentation.** Preview the crawl with `perk librarian add docs <url> --dry-run`, which
   prints the URL → file map and writes nothing. Add `--scope-prefix /docs/x/` when the site hosts
   several products or versions (`--scope-prefix /` keeps the whole site). Then run
   `perk librarian add docs <url> [--slug <slug>]`: it claims an empty `.staging/<slug>/`
   directory and launches a curating session that crawls, prunes, fixes conversion artifacts,
   publishes, and reports the slug, path, pages copied, and any failures it accepted. From inside a
   perk session — a read-only planning session included — ask the agent instead: it calls
   `run_librarian` with `{action: "add-docs", url, slug?, scope_prefix?}`, and the `perk.librarian`
   writer child does the same work in the main checkout.
   - `slug_exists` — the slug is catalogued; refresh that entry (step 7) or pick another `--slug`.
   - `skill_missing` — the crawl script is not installed; run `perk init`, then rerun.
   - `missing_converter` — `curl` or `html2markdown` is missing; install `html2markdown`
     (`brew install html2markdown`), then rerun.
   - `seed_redirect` — the URL is only a redirect page, such as a version alias like `/latest/`;
     the message names the real URL and scope prefix — rerun with those.
   - `unclean-start` (from `run_librarian`) — the main checkout has uncommitted tracked changes or
     index flags; commit or stash them, or run the `perk librarian add docs …` command the tool
     names from a terminal.
5. **Commit the README once (first use only).** Your first acquisition creates `docs/library/`,
   but the workers never write `docs/library/README.md`, and `perk init` / `perk doctor --fix`
   converge it only once the directory exists. So after your first `add source` or `add docs`, run
   `perk doctor --fix` (or `perk init`) in the main checkout to create the README, then commit it.
   It is the one committed file under `docs/library/`, and the route a linked worktree — where the
   gitignored content is absent — follows to the main checkout's library. Until it is committed,
   `perk doctor` flags it: the `library-readme` check fails while the README is missing or drifted,
   and a present but uncommitted README is a warning telling you to commit it.
6. **Check freshness only when a task depends on it.** Run `perk librarian check <slug>` for an
   entry the task relies on whose status is `stale` or `unknown`. It is the only command that
   probes an upstream; it skips an entry checked within its window (`recent` — `--force` overrides
   that), and never probes a `pinned` entry. Read the result by
   [status](../reference/cli/librarian.md#perk-librarian-list):
   - `fresh` — a recent check found change evidence and detected no drift against the recorded
     baseline (the first check only records that baseline); trust it for the task.
   - `unverifiable` — the site offers no change evidence; judge the mirror with task evidence.
   - `drifted` — the upstream moved; go to step 7.

   Never check the whole library as a side quest: every check reaches the network.
7. **Refresh on evidence.** For a source entry, `perk librarian refresh <slug>` fast-forwards a
   clean checkout to the upstream default branch. For a documentation entry, the same command
   launches a refresh session that re-crawls with the prior scope and publishes over the prior
   revision only on success; from a session, ask the agent to call `run_librarian` with
   `{action: "refresh-docs", slug}`.
   - `skipped_dirty` — the checkout has uncommitted changes; commit, stash, or discard them.
   - `skipped_non_ff` — the checkout is detached, on another branch, ahead, or diverged; the detail
     says which to fix.
   - `entry_pinned` — the entry is pinned; re-pin it with `perk librarian add source … --ref <new>`.
   - `library_busy` — another writer holds the library lock; wait for it and rerun.
8. **Let planning sessions use it.** There is nothing to configure. The shipped `librarian` skill
   is exposed to plan, objective-plan, objective-author, implement, address, and learn sessions and
   is discovered by its description, and a `perk plan` session's plan-authoring guidance points to
   it when a plan leans on an external dependency — the session decides whether the library is
   worth consulting for the task. `perk doctor` reports an unreadable catalog, an uncommitted
   README, tracked library content, and uncatalogued or leftover staging directories. Remove an
   entry you no longer need with `perk librarian remove <slug>`.

## Expected result

`perk librarian list` shows the entry — `pinned` for a pinned source checkout, `unknown` for a new
mirror until its first check — with an absolute path under the main checkout's `docs/library/`.
`git status` shows nothing under `docs/library/` except the `README.md` you committed in step 5;
everything else there is gitignored.

## Related

- **Understand:** [The perk library](../explanation/the-perk-library.md) — why freshness is evidence and why perk is not eager.
- **Look up:** [Librarian commands](../reference/cli/librarian.md) — every verb, status, and refusal.
- **Look up:** [Model-facing tools](../reference/in-session/model-tools.md#perk-owned-tools) — `run_librarian` from a session.
