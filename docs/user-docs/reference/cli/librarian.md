---
title: "Librarian commands"
description: "Exact reference for the perk librarian group — list, record, remove, add source, add docs, check, refresh, and prepare entries in the catalogued, gitignored perk library."
sidebar:
  order: 3017
---

# Librarian commands

This page holds the exact reference for the `perk librarian` group: the deterministic workers
that tend the **perk library**, the two doors that open a curating session for a documentation
mirror, and the `prepare` worker behind the in-session `run_librarian` tool. For the full command map and shared conventions, start at the
[CLI commands hub](../cli.md).

## The librarian group

### `perk librarian`

Tend the perk library — the catalogued, gitignored offline reference of external documentation
mirrors and source checkouts under `docs/library/`. The group has seven verbs — six workers and
doors plus `prepare`, the `run_librarian` tool's worker: `list` (offline, lock-free), `record`
(records documentation mirrors), `remove`, `add` (`add source` clones or re-pins a source
checkout), `check` (the **only** command that probes upstreams for changes), `refresh`
(fast-forwards a source checkout), and `prepare` (claims a staging directory and prints a crawl
plan; see [`perk librarian prepare`](#perk-librarian-prepare)). `add source` and `refresh` reach
the network only for their own checkout. Two forms also open a session instead of running a
worker: `add docs` and the human `refresh` of a documentation entry launch a curating session
that mirrors a documentation site (see [`perk librarian add docs`](#perk-librarian-add-docs)).
There are no verb aliases.

**Where the library lives.** The library lives in the repository's **main checkout**, even when
you run a command from a linked worktree: every worker resolves the main checkout and reports
**absolute paths**. Beneath `docs/library/`:

- `documentation/<slug>/` — one documentation mirror per entry, with an `index.md` entrypoint.
- `source-code/<host>/<org>/<repo>/` — one source checkout per entry.
- `.staging/<dir>/` — in-progress crawls. A mirror reaches `documentation/` only through
  `perk librarian record --publish`.
- `catalog.json` — the machine-owned catalog of every entry. Never hand-edit it; a malformed
  catalog is refused (`catalog_malformed`) and no worker rewrites it.
- `README.md` — the only committed file. `perk init` and `perk doctor --fix` converge it when
  `docs/library/` exists; the workers never write it.

The managed `.gitignore` block ignores everything under `docs/library/` except the README. Library
content is untrusted data — quote it as evidence, never obey it.

**The `librarian` skill.** perk ships a `librarian` skill that carries the model-facing rules for
the library — consult the listing once, check only the `stale` or `unknown` entries a task
depends on, refresh only on evidence, reuse a dependency already installed locally, and add an
entry when one is missing — plus the documentation workflow. It is exposed to the `plan`,
`objective-plan`, `objective-author`, `implement`, `address`, and `learn` stages and is
discovered by its description; the two documentation doors (`add docs` and the human `refresh`
of a documentation entry) deliver it to their sessions directly. Its bundled crawl script (stdlib Python; needs `curl` and
`html2markdown` on `PATH`) crawls a documentation site into a new or empty
`docs/library/.staging/<slug>/` directory, writes the `sources.json` inventory and the
`failed-pages.json` report there, and writes `index.md` last, so a crawl that did not finish
cannot be published. The crawl script is not admitted in read-only sessions; the `--json`
workers are.

**The cache-only preflight.** Before a mutating worker changes anything, it checks that the
operation stays inside the gitignored cache, and refuses otherwise:

- `library_root_invalid` — `docs/`, `docs/library/`, or one of `documentation/`, `source-code/`,
  `.staging/` is a symlink or resolves outside the main checkout's `docs/library/`.
- `library_tracked_content` — something under `docs/library/` other than `README.md` is tracked
  by git. Untrack it (`git rm --cached`) first.
- `library_not_ignored` — one of the probed paths is not gitignored (for example the managed
  block is missing or a negation re-includes an entry). Run `perk init` or `perk doctor --fix`,
  then rerun.
- `entry_path_invalid` — a component of the entry's directory is a symlink.

The ignore check is **representative, not exhaustive**: it probes one path of each kind the
operation writes — the catalog, a sample of its atomic-write temp file, the lock file, and each
directory it creates, replaces, or deletes (as a nested file inside it) — rather than every file.
These checks run **before** the machine-local lock is taken, so a `publish` or `adopt` refusal
writes nothing at all. The one exception is `remove`: it learns the entry's directory from the
catalog, so it probes that directory after taking the lock, and a `library_not_ignored` refusal
there can leave the lock file behind (in the gitignored `.perk/workflow/`, whose ignore status is
checked before the lock). `refresh` likewise probes its checkout after taking the lock. A
`.gitignore` edited while a worker runs is outside what these checks cover.

Because of that preflight, the `--json` forms of `list`, `record`, `remove`, `add source`,
`check`, and `refresh` are admitted in read-only perk sessions (with `--json` as the last
argument); `add docs` is not. `prepare` is not admitted either — it is the extension's own
worker; in a read-only session the `run_librarian` tool is the route to a documentation mirror.
The network verbs run the same preflight and write only the gitignored cache.

**Concurrency.** Every catalog write and entry-directory change holds an exclusive, non-blocking,
machine-local lock (`.perk/workflow/library.lock` in the main checkout). A second writer is
refused immediately with `library_busy` — wait for the other operation and rerun. `list` never
takes the lock; `add source` clones and `check` probes without holding it, taking it only to
record the result. The lock file is never opened through a symlink: a symlinked or non-regular lock
path is `library_lock_invalid` — remove it and rerun.

**Output and exits.** `--json` writes the envelope to stdout; human text goes to stderr. A failure
under `--json` is `{success: false, error_type, message}`. An unexpected filesystem or git failure
is the typed `io_error`, never a traceback. Exit `0` ok · `1` typed refusal or operation failure ·
`2` not a git repository (`not_a_repo`).

### `perk librarian list`

List the library: every catalogued entry with its derived status, every uncatalogued directory,
and every leftover staging directory. Offline and lock-free; an absent or empty library is not an
error.

| Status | Meaning — and the next action |
| --- | --- |
| `pinned` | A source entry held at a fixed `ref`. Trust it as pinned. |
| `drifted` | A check found the upstream changed. Refresh it. |
| `unknown` | Never checked. Check it before relying on it. |
| `stale` | The last check is older than the entry's `stale_after` window. Check it. |
| `unverifiable` | Checked, but the upstream offered no change evidence. Judge it with task evidence. |
| `fresh` | Checked within its window with change evidence. Trust it. |

The precedence is the table's order: `pinned` wins over `drifted`, `drifted` over `unknown`, and
so on.

**Uncatalogued directories** are the top-level directories other than `documentation`,
`source-code`, and `.staging`, plus any directory under `documentation/` that no entry owns — for
example a prior revision a publish could not delete, or residue from an interrupted publish. Each
is printed with a copyable hint:

```sh
perk librarian record --adopt <absolute-dir> --kind docs --source <url>
```

The human render prints `library: <root>` (or `(absent)`), one line per entry — status, kind,
slug, absolute path, `checked <age> ago` or `never checked`, and `[missing]` when the entry's
directory is gone — then the `uncatalogued:` and `staging:` lists. `--json` emits the
`LibrarianListOut` envelope: `library_root`, `catalog_present`, `entries[]` (`kind`, `slug`,
`source`, `path`, `present`, `ref`, `added_at`, `checked_at`, `checked_age_seconds`,
`stale_after`, `evidence`, `drifted`, `status`), `uncatalogued[]` (`name`, `path`, `hint`), and
`staging[]` (`name`, `path`).

### `perk librarian record`

Record a documentation entry in `catalog.json`. Pass exactly one of
`--publish` or `--adopt`; `--source <url>` (an absolute `http` or `https` URL) is always required.
Every option is parsed inside the command, so a bad value is a typed refusal (`invalid_input`,
`invalid_source`, `invalid_slug`, `invalid_stale_after`, `invalid_kind`), never a usage error.

- **`--publish <staging-dir> --slug <slug>`** moves a staged mirror from `.staging/` to
  `documentation/<slug>/` and records it, atomically. The staging directory must be a direct child
  of `.staging/`, a real directory with no symlinks inside, and carry an `index.md`
  (`staging_not_found`, `staging_outside_library`, `staging_invalid`). A slug is lowercase letters,
  digits, `.`, `_`, or `-`, at most 64 characters.
  - Create-only by default: an existing entry of either kind, or an existing uncatalogued
    `documentation/<slug>/`, is `slug_exists`.
  - **`--replace`** refreshes an existing docs entry, keeping its `added_at` (and its
    `stale_after` unless you pass a new one). It refuses `entry_removed_meanwhile` when no such
    entry exists, and `kind_mismatch` when the slug belongs to a source entry — remove it first.
  - **`--accept-failures`** publishes despite a non-empty `failed-pages.json` crawl report
    (otherwise `staging_failed_pages`). The `librarian` skill's crawl script always writes the
    report: `[]` on a clean crawl, otherwise one record per failed page with its `url`, the
    `stage` that failed (`fetch`, `convert`, or `write`), and a one-line `reason`. The report is
    deleted from the published mirror.
  - A `sources.json` per-page inventory in the mirror — the crawl script writes one — seeds the
    entry's per-page change markers; a malformed one is skipped with a warning.
- **`--adopt <dir>`** catalogs a pre-existing uncatalogued directory — one directly under
  `docs/library/` or under `documentation/` — as a docs entry, moving it to
  `documentation/<slug>/` when needed. The slug defaults to the directory name; pass `--slug` when
  the name is not a valid slug. Adoption is orphan-only and never renames an entry: a directory
  an entry already owns is `directory_catalogued` (keep using that entry, or refresh its content
  with `--publish … --replace`; `remove` would delete the directory), and a taken slug is
  `slug_exists` (`adopt_not_found`, `adopt_invalid`
  cover a missing, symlinked, nested, or reserved directory).
- **`--kind`** accepts only `docs` (the default). Source checkouts are recorded by
  [`perk librarian add source`](#perk-librarian-add-source).
- **`--stale-after <window>`** sets the freshness window as a whole number of seconds, minutes,
  hours, or days (`45s`, `90m`, `24h`, `7d`); the defaults are 14 days for docs and 24 hours for
  source entries.

Every refusal leaves the staging directory intact. If a publish fails partway, the command rolls
back — the prior revision returns to `documentation/<slug>/`, the staged mirror returns to
`.staging/`, and the catalog is unchanged — and reports `io_error` saying the library was
restored, so you can rerun the same command. In the rare case a rollback step itself fails, the
`io_error` names every leftover path to inspect; `perk librarian list` reports any displaced
directory as uncatalogued. Deleting the replaced prior revision is best-effort: if it fails the
publish still succeeds with a warning, and `list` shows the leftover.

A publish that is **killed** partway (no rollback runs) is not repaired automatically; `list`
shows where it stopped. If it stopped after moving the old revision aside but before moving the
new mirror in, the entry is still catalogued but its directory is `[missing]`, the moved-aside
`documentation/.<slug>.previous-*` directory is the only copy of the old revision, and the staged
mirror is still in `.staging/`. Rerun the same `perk librarian record --publish … --replace` from
the staged mirror (or rename the moved-aside directory back to `documentation/<slug>/`), and only
then delete the leftover `.previous-*` directory — adopting it is refused while the slug is
catalogued. If it stopped after moving the new mirror in but before writing the catalog, a fresh
publish's `documentation/<slug>/` shows up as uncatalogued (adopt it under its slug), and a
replace keeps the old catalog record over the new content; any `.previous-*` leftover is then
safe to delete.

The human render prints `published <slug> → <path>` (or `adopted …`) plus one `warning:` line per
warning. `--json` emits the `LibrarianRecordOut` envelope: `action`, `entry` (the `list` entry
shape), `replaced_previous`, and `warnings[]`.

### `perk librarian remove`

`perk librarian remove <slug>` removes an entry: its catalog record first, then exactly its entry
directory. A missing entry is `entry_not_found`; a symlink anywhere on the entry's path is
`entry_path_invalid` and nothing is touched. If deleting the directory fails after the catalog
write, the command reports `io_error` — the entry is already gone from the catalog and the
leftover directory shows up in `list` as uncatalogued, ready to adopt again or delete.

The human render prints `removed <slug> (<kind>) — <path>`. `--json` emits the
`LibrarianRemoveOut` envelope: `slug`, `kind`, `path`, and `content_removed`.

### `perk librarian add`

`perk librarian add <kind>` adds a library entry by kind: `source` clones a source checkout, and
`docs` launches the session that mirrors a documentation site.

### `perk librarian add docs`

`perk librarian add docs <url> [--slug <slug>] [--scope-prefix <prefix>] [--dry-run] [pi-args…]`
launches a perk session in the repository's main checkout that mirrors a documentation site into
the library as a new documentation entry. Mirroring is judgment work — choosing the scope,
pruning off-topic pages, fixing conversion artifacts — so there is no session-free add: the door
checks everything it can first, then hands the session a seeded flow that the `librarian` skill
details.

- **`<url>`** — the seed page, an absolute `http` or `https` URL (`invalid_source` otherwise).
- **`--slug <slug>`** — the entry slug. It defaults to the URL's first host label after dropping
  a leading `www.` and then a leading `docs.`: `https://pi.dev/docs` → `pi`,
  `https://docs.astro.build/en/` → `astro`. When that label is not a valid slug, the command
  refuses with `invalid_slug` and asks for `--slug`. The door always prints the slug it chose.
- **`--scope-prefix <prefix>`** — the URL path prefix to keep in scope, such as `/docs/`; `/`
  keeps the whole site. Without it, the crawl keeps the seed URL's parent path. A prefix with a
  `.` or `..` segment, whitespace, or a blank value is `invalid_input`.
- **`--dry-run`** — runs the crawl script's own dry-run and prints the URL → file map, the scope
  prefix, and the counts. No session starts and nothing is written. Exit `0` means every
  discovered page was reachable; exit `1` means a discovery fetch failed (the `WARNING:` lines
  say which); a script refusal is `crawl_refused`, and any other script exit is `io_error`.
- **Trailing arguments** pass through to `pi`.

**Before the session.** The command refuses, and starts nothing, when:

- `slug_exists` — the slug is already catalogued (refresh that entry with
  `perk librarian refresh <slug>`, or pick another `--slug`), or `documentation/<slug>/` already
  exists uncatalogued (adopt it with `record --adopt`, delete it, or pick another `--slug`).
- `skill_missing` — the `librarian` skill's crawl script is not installed at
  `.agents/skills/librarian/scripts/copy_docs_to_markdown.py` in the main checkout. Run
  `perk init` (it syncs perk's skills), then rerun.
- `missing_converter` — `curl` or `html2markdown` is not on `PATH` (install `html2markdown` with
  `brew install html2markdown`). This is checked on `--dry-run` too.
- a cache-only preflight refusal (`library_root_invalid`, `library_tracked_content`,
  `library_not_ignored`), or `catalog_malformed`.

**The staging directory.** On a real launch, the command creates an empty
`docs/library/.staging/<slug>/` directory for the session — or `<slug>-2/`, `<slug>-3/`, … when
that name is already taken — and never deletes a staging directory. If you abandon the session,
the empty directory stays behind; `perk librarian list` reports it under `staging:`, and you can
delete it.

**What the session does.** The seed names the URL, the slug, the scope, the staging directory, and
two exact, shell-quoted commands: the crawl (the `librarian` skill's script run through perk's own
Python interpreter) into the staging directory, and the publish
(`perk librarian record --publish <staging> --slug <slug> --source <url> --json`). The session
crawls, prunes and fixes the staged mirror, publishes it (adding `--accept-failures` only after
judging a partial crawl's report), and reports what it published. Its scope is soft: it is told
to write only under the gitignored library — never a commit, never `docs/library/README.md`,
never `catalog.json` by hand — but no sandbox enforces that.

`add docs` has no `--json` form and is not admitted in read-only perk sessions; run it from a
terminal, or let a session call `run_librarian`.

### `perk librarian add source`

`perk librarian add source <repo-ref> [--ref <pin>] [--slug <slug>] [--stale-after <window>]`
clones a source repository into `source-code/<host>/<org>/<repo>/` and records it. The clone is
a blobless partial clone (history and trees up front, file contents on demand). The entry's
`source` is the normalised clone URL, and its slug defaults to the lowercased repository name —
pass `--slug` when that name is not a valid slug (`invalid_slug`).

**Repository references.** Any of these forms (anything else is `invalid_repo_ref`):

| Form | Clones |
| --- | --- |
| `pallets/click` | `https://github.com/pallets/click.git` |
| `gitea.example.com/org/repo` | `https://gitea.example.com/org/repo.git` |
| `https://<host>/<org>/<repo>[.git]` (also `http://`) | the same URL with `.git` |
| `ssh://[user@]<host>/<org>/<repo>[.git]` | the same URL with `.git` |
| `git@<host>:<org>/<repo>[.git]` | `git@<host>:<org>/<repo>.git` |

The host is lowercased; deeper paths (`/tree/main`), GitLab subgroups, ports, credentials in the
URL, and query strings are refused.

**The git policy.** Every git operation that runs over a library checkout — the clone, fetches,
checkouts, fast-forwards, the uncommitted-changes check, and `check`'s probe — ignores your
global and system git config and runs with hooks disabled, so nothing a cloned repository's
content, or your global or system config (hooks, filters, an fsmonitor), selects can execute.
Two things stay trusted and are not audited: git configuration set through environment
variables (`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`, `GIT_CONFIG_PARAMETERS`),
and a checkout's own repository-local `.git/config`. For a checkout `add source` cloned, that
file is what git wrote at clone time; for an existing checkout it adopts (see below), it is
whatever its creator configured — adopt only checkouts you trust. The costs: no credential helper, no `insteadOf` rewrite, and no config-file proxy (proxy
environment variables still apply). **Private repositories** therefore need the `git@…` or
`ssh://…` form (ssh-agent authentication does not depend on git config). Repositories that use
Git LFS clone with LFS pointer files instead of the large files.

**Reruns and existing checkouts.** The command is idempotent: rerunning it over a valid checkout
reports `reused` and changes nothing (a new `--stale-after` is the only thing it updates). A
valid checkout of the same URL that is not yet catalogued — for example one an interrupted run
left behind — is catalogued as it stands, including its repository-local git config, which later
`refresh` and re-pin runs honour. A directory at the target that is not a checkout of
that URL (a plain directory, another remote, a linked worktree) is `checkout_invalid` — rerun
later if another `add source` may still be running, otherwise delete it and rerun. If the target
appears while the command is cloning — or another `add source` catalogs or re-pins the checkout
before this one records it — it is `checkout_invalid` and the directory is left alone.
A failed clone is `clone_failed`; a clone that cannot be recorded is removed again, so nothing is
left behind. An entry already catalogued at the path must be re-added with the same URL and slug
(`invalid_input` — `remove` it first to switch URLs); a slug another entry uses is `slug_exists`.

**Pinning.** `--ref <pin>` detaches the checkout at a tag, a branch, or a commit (tried in that
order; a pin that does not resolve is `ref_not_found`) and records it as the entry's `ref`, which
makes its status `pinned`. A pin has no whitespace and does not start with `-` (`invalid_input`).

- **Re-pin:** rerun with a different `--ref`. The checkout is fetched and moved (`repinned`); a
  checkout with uncommitted changes is refused (`checkout_dirty`), and a failed fetch is
  `fetch_failed`.
- **Unpin:** there is no unpin option — `perk librarian remove <slug>`, then
  `perk librarian add source <repo-ref>` without `--ref` to track the default branch.
- **A missing pinned checkout** is not re-cloned silently: without `--ref` the command refuses
  with `entry_pinned`. Rerun with `--ref <recorded pin>` to restore it, another `--ref` to
  re-pin, or remove and re-add it to track the default branch.

If the catalog cannot be written after a re-pin, the command reports `io_error`: the checkout is
already at the new pin, and rerunning the same command completes the re-pin.

The human render prints `cloned <slug> → <path>` (with `at <pin>` when pinned), `reused …`, or
`repinned <slug> at <pin> → <path>`. `--json` emits the `LibrarianAddSourceOut` envelope:
`action` (`cloned`, `reused`, or `repinned`) and `entry` (the `list` entry shape).

### `perk librarian check`

`perk librarian check [<slug>…] [--force]` probes library entries for upstream changes — every
entry, or the named slugs in the order given. It is the only command that probes an upstream,
and it records each entry's `checked_at`, `evidence`, and `drifted` flag. An unknown slug is
refused (`entry_not_found`) before anything is probed. Each entry gets one result:

| Result | Meaning |
| --- | --- |
| `probed` | The upstream was probed and the observation recorded. |
| `pinned` | A pinned source entry — never probed. |
| `recent` | Checked within its `stale_after` window — skipped. Pass `--force` to probe anyway. An entry never checked is always probed. |
| `missing` | The entry's directory is gone — re-clone it with `add source` or re-publish the mirror. |
| `failed` | The probe could not reach the upstream (or the entry changed while it ran — rerun); the entry is unchanged. |

**Source entries** compare the upstream default branch's tip (`git ls-remote`) with the commit
the checkout holds; a different tip marks the entry `drifted` until `refresh` fast-forwards it.

**Documentation entries** send conditional requests for the recorded pages (the source URL
first) and read the site's inventory: `sitemap.xml` (or `sitemap-index.xml`, following up to five
child sitemaps) and `llms.txt`. A page's own body is never read or hashed (when a page
redirects, the HTTP client does read each intermediate redirect response's body — small in
practice). The **evidence** tiers:

- `strong` — a page answered with a validator (`ETag`, `Last-Modified`) or its sitemap entry
  carries a `lastmod`, or a page is gone (`404`/`410`).
- `weak` — only the inventory fingerprint (a hash of the sitemap's URL list and of `llms.txt`)
  was available. An unchanged `weak` entry reads `fresh`.
- `none` — the site offers no change evidence. The entry reads `unverifiable`, never `fresh` —
  judge it with task evidence.

The first check records each marker as the mirror's baseline; later checks compare against that
baseline and never overwrite it (only re-publishing with `record --publish … --replace` does). A
changed validator, lastmod, or fingerprint, or a vanished page, marks the entry `drifted`. A
check that cannot re-observe a comparison (a server error, a timeout, a page that stops
returning a recorded validator, an unparseable sitemap) keeps an existing drift rather than
clearing it, and notes why.

**Request bounds.** Per documentation entry: at most 20 page requests, up to 8 inventory
requests, and 5 redirects per request; three page errors in a row stop the page requests.
Inventory bodies are read up to 2 MiB. Skipped requests are listed as notes. The time limits are
**soft**: the 10-second timeout applies to each network operation (connecting, each read), not to
a whole request, and the 60-second per-entry budget is checked only between requests — so a
server that keeps trickling a response can hold one request, and the check, past those
figures.

A completed check exits `0` even when some results are `failed`; exit `1` means the whole command
was refused (an unknown slug, a malformed catalog, a preflight refusal, `library_busy`).

The human render prints one line per result — result, status, kind, slug, detail — with indented
`note:` lines and a final `warning:` line per warning. `--json` emits the `LibrarianCheckOut`
envelope: `results[]` (`action`, `detail`, `notes[]`, `entry`) and `warnings[]`.

### `perk librarian refresh`

`perk librarian refresh <slug>` fetches a source entry's checkout and fast-forwards it to the
upstream default branch. The checkout must be clean and on that branch; otherwise nothing is
fetched or recorded. Outcomes:

| Outcome | Meaning |
| --- | --- |
| `fast_forwarded` | The checkout moved to the upstream tip; `previous_head` is where it was. |
| `up_to_date` | The checkout already matches the upstream tip. |
| `skipped_dirty` | The checkout has uncommitted changes — commit, stash, or discard them. |
| `skipped_non_ff` | The checkout is detached or on another branch, has local commits ahead, or has diverged — or the default branch no longer exists upstream; the detail says which. Local commits or divergence mark the entry `drifted`; a vanished branch leaves it `unverifiable`. |

**Documentation entries.** Refreshing a mirror is judgment work, so `perk librarian refresh
<slug>` on a documentation entry (without `--json`) launches the refresh session — the same door
as [`add docs`](#perk-librarian-add-docs), with the same `skill_missing` and `missing_converter`
refusals and the same staging directory rules. The session re-crawls the entry's source URL into
the new staging directory with the prior crawl's scope (read from the published mirror's
`sources.json`; when the recorded scope is unusable, the command prints a `warning:` and the crawl
uses the default scope), curates, and publishes with `record --publish … --replace`. The prior
revision stays published until that publish succeeds. `refresh --json` on a documentation entry
refuses with `needs_session` and names the door. `refresh` of a documentation entry takes no
`--dry-run` and no `pi` arguments.

Refusals: a pinned entry is `entry_pinned` — re-pin with `add source … --ref <new>`, or remove and
re-add it to track the default branch. A missing checkout is `entry_missing` — `add source`
re-clones it. A failed fetch is `fetch_failed`. If the catalog cannot be written after a
fast-forward, the command reports `io_error`: the checkout is already fast-forwarded, and
rerunning `refresh` records it.

The human render prints `fast-forwarded <slug> <old>..<new>`, `up to date <slug> (<sha>)`, or
`skipped (dirty|non-ff) <slug>: <detail>`. `--json` emits the `LibrarianRefreshOut` envelope:
`action`, `detail`, `previous_head`, and `entry`.

### `perk librarian prepare`

`perk librarian prepare <docs|refresh>` is the worker behind the in-session `run_librarian` tool
(see [Model tools](../in-session/model-tools.md)). It runs the documentation doors' checks, claims
an empty staging directory, and prints the crawl plan — the exact crawl and publish commands the
tool's `perk.librarian` writer child runs. It launches nothing: no session, no crawl. It is not
admitted in read-only perk sessions; the tool runs it through the extension itself. You rarely
run it by hand — a claimed staging directory you do not use stays behind until you delete it
(`perk librarian list` reports it under `staging:`).

Both forms print the same plan. `--json` emits the `LibrarianPrepareOut` envelope: `action`
(`add-docs` or `refresh-docs`), `url`, `slug`, `scope_prefix` (`""` when defaulted), `staging_dir`
(the claimed directory, absolute), `main_root` (the main checkout), `current_dir` (the published
revision a refresh replaces, else `null`), `replace`, `crawl_command`, `publish_command`, and
`warnings[]`. The human render prints one `key=value` line per field, then one `warning:` line per
warning. Refusals use the doors' error types and exit codes: `1` for a typed refusal, `2` outside
a git repository.

### `perk librarian prepare docs`

`perk librarian prepare docs <url> [--slug <slug>] [--scope-prefix <prefix>] [--json]` runs the
same checks as [`add docs`](#perk-librarian-add-docs), in the same order — the URL
(`invalid_source`), the slug (`invalid_slug`) and scope prefix (`invalid_input`), `slug_exists`,
`skill_missing`, `missing_converter`, and the cache-only preflight — and then creates the empty
`docs/library/.staging/<slug>/` directory (or `<slug>-2/`, … when taken). A refusal claims
nothing. The plan's `publish_command` is
`perk librarian record --publish <staging> --slug <slug> --source <url> --json`.

### `perk librarian prepare refresh`

`perk librarian prepare refresh <slug> [--json]` prepares a re-crawl of an existing documentation
entry, with the same checks as the human [`refresh`](#perk-librarian-refresh) of a documentation
entry: the entry's source URL, the prior crawl's scope (a `warnings[]` entry when the recorded
scope is unusable and the default scope is used), `current_dir` set to the published mirror, and
a `publish_command` carrying `--replace`. An unknown slug or a source entry is `entry_not_found`.

## Related

- **Look up:** [CLI commands](../cli.md) — the hub and shared conventions.
- **Look up:** [Repository layout](../configuration/repository-layout.md) — where the library lives and what is committed.
- **Understand:** [The perk library](../../explanation/the-perk-library.md) — the freshness-evidence model and the not-over-eager policy.
