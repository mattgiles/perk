---
title: The git substrate safety contract (src/perk/substrate/git.py)
read_when: You are adding or changing a git primitive — diffs or blob reads of committed bytes, fetch/clone/merge/status of untrusted checkouts, cleanliness proofs, lock-free network phases, ignore probes.
cluster: plan-lifecycle
---

# The git substrate safety contract

`src/perk/substrate/git.py` is the one place perk shells out to `git`. Two of its primitives run
against inputs perk does not control — **untrusted PR content** (a reviewer reads a diff of
whatever an author pushed) and **a shared ref store** (linked worktrees under one `$GIT_COMMON_DIR`,
with parallel reviewer lanes fetching at once). The contract also covers the **library**
primitives that clone, fetch, merge and `status` untrusted checkouts (`src/perk/library/`) and the
change-stats blob reads of committed bytes. The contract below is what keeps those reads safe;
every rule was established by a live failure or a live control, not by reading the git manual.

## Distillation

- Review-read diffs pin every rendering knob to git's default and never run an external diff or
  textconv helper — "A review-read diff is config-pinned, not bare".
- A both-configured control proves only the external diff; prove textconv alone first — "Git
  precedence gotcha".
- `status` can execute fsmonitor hooks and clean filters: pin every call against untrusted
  content, and give never-execute canaries a positive control — "`git status` is not a passive read".
- The pin nulls only global/system config; env and repo-local config still apply, so scope every
  "nothing can execute" claim — "Config-pinned is not a sandbox".
- Compare stored config, classify by ancestry, merge the resolved SHA, fetch with prune — "Never
  infer identity or movement from convenient names or exit codes".
- Private temp-ref namespaces still share `FETCH_HEAD`; fetch with `--no-write-fetch-head` — "A
  private temp-ref namespace does not make concurrent fetches private".
- Network work outside the lock commits under it only while the catalog owner is unchanged — "A
  lock-free network phase needs a fence at the locked commit".
- Mechanics in the substrate, forge policy in `perk.github.reviews` — "Layering".
- Exact committed bytes come from `diff --raw -z` + one `cat-file --batch`, never archive or
  checkout — "`git archive` and checkout are not raw committed-blob reads".
- Cleanliness proofs pass `--ignore-submodules=none`; `worktreeDirty` does not yet — "Cleanliness
  proofs must override submodule ignore settings".
- Walk symlinks before an ignore probe, or probe a known-free path — "Ignore probes are name-only".
- Invocation root vs main root decide config reads and selector writes — "Two roots".

No section below is historical; every rule is current.

## A review-read diff is config-pinned, not bare

`diff_range(repo, base, head)` never runs a bare `git diff`. It pins every rendering knob to git's
**default**, so a default-configured repo renders byte-identically and a customised one cannot leak
its config into a review artifact:

| Pin | What it defends against |
| --- | --- |
| `--no-ext-diff` / `--no-textconv` | **Never-execute.** A `diff.external` or `diff.<driver>.textconv` helper is a *command from user config*, while the `diff=<driver>` attribute comes from the *tree being diffed*. PR content can therefore select a driver, and the user's config supplies the executable — pin both off regardless of what the tree says. |
| `--no-color` | `color.ui=always` corrupts the unified diff with escape sequences. |
| `--unified=3` / `--diff-algorithm=myers` | `diff.context` / `diff.algorithm` move hunk boundaries, which changes which lines `parse_diff_anchors` (`src/perk/github/diff_anchors.py`) accepts as anchors. |
| `--find-renames` | Explicit rename detection regardless of `diff.renames`. |
| `--src-prefix=a/` / `--dst-prefix=b/` | The anchor parser keys files on the `a/`/`b/` header prefixes; `diff.noprefix` / `diff.mnemonicPrefix` break them. |

Each pinned config was **empirically shown to change output** before its flag was added
(`tests/test_git.py::test_diff_range_pins_the_rendering_against_user_config`,
`::test_diff_range_pins_color_algorithm_and_rename_detection`), and the exact argv is pinned
separately (`::test_diff_range_and_fetch_refspecs_pin_their_argv`) so a dropped flag fails even where
the live control is insensitive. Callers pass an already-computed **merge-base SHA** as `base`, so the
two-dot form equals the three-dot merge-base diff the forge renders.

## Git precedence gotcha — external diff skips textconv

Once `diff.external` is configured, git hands the whole comparison to the external program and
**does not run textconv at all**. A single "both configured" control therefore proves the external
hook live and the textconv hook nothing. The never-execute test is two-stage: prove textconv fires
alone (canary 1), add the external diff and prove it fires (canary 2), delete both canaries, run
`diff_range`, and assert neither reappears
(`tests/test_git.py::test_diff_range_never_executes_configured_diff_helpers`). The general craft of
live controls for never-execute seams is in `workflow/vacuity-proof-tests.md`.

## `git status` is not a passive read

`status` can **execute** a configured fsmonitor hook (`core.fsmonitor`) or an attributes-selected
clean filter (run to decide whether a stat-dirty file really changed), and a relative global
`core.fsmonitor` can resolve to a script inside the cloned tree. Every invocation against untrusted
checkout content therefore takes the pin — `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`
and an empty `core.hooksPath` (`LIBRARY_GIT_ENV` plus the `pinned=` keyword in
`src/perk/substrate/git.py`) — including the "read-only" dirty checks (`git.is_dirty(pinned=)`).

Never-execute canaries here need a **positive control**: first prove the helpers fire under a
hostile global config with a bare `status`; bump the file's mtime so the clean filter actually
runs (an unchanged stat skips it); and have each helper log its `pwd`, so the consumer repo's own
git calls do not produce false positives
(`tests/test_library_source.py::test_refresh_and_repin_never_execute_status_helpers`).

## Config-pinned is not a sandbox

The pin nulls the user's global and system config files and nothing else. Env git config
(`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n`, `GIT_CONFIG_PARAMETERS`) and the
checkout's own `.git/config` still apply, and adopting a pre-existing checkout brings its creator's
repo-local config into the trust boundary. Scope every "nothing can execute" claim to **tree content
plus the user's global/system config** (the `LIBRARY_GIT_ENV` comment and contracts §8.75(i) state
the trusted, unaudited remainder).

A useful side effect: env config sits outside the nulled files, so `GIT_CONFIG_COUNT=1` plus
`GIT_CONFIG_KEY_0=url.<file-uri>.insteadOf` gives offline tests a local bare repo that production
code clones as `https://github.com/…` with no production seam (`tests/_library_upstream.py`).

## Never infer identity or movement from convenient names or exit codes

- **Identity:** `git remote get-url` expands `insteadOf` rewrites — compare the **stored**
  `remote.origin.url` read via `git config` (`src/perk/library/source.py`).
- **Movement:** `merge --ff-only` exits 0 on "Already up to date" — classify by ancestry
  (`merge-base --is-ancestor`, `git.is_ancestor`), never by the exit code.
- **Ref resolution:** an abbreviated `origin/<branch>` can resolve to a same-named tag
  (`refs/tags/origin/main` outranks `refs/remotes/origin/main`) — merge the fully resolved SHA that
  was classified, never the short name.
- **Stale tracking refs:** a plain `fetch` keeps the tracking refs of deleted upstream branches —
  `git.fetch(prune=True)` before trusting `refs/remotes/origin/<branch>`.

## A private temp-ref namespace does not make concurrent fetches private

Linked worktrees share ONE ref store. Fetching into a per-invocation namespace
(`refs/perk/review-ctx/<uuid>/…`) keeps *refs* from clobbering each other — but a plain `git fetch`
also locks and rewrites the **shared** `$GIT_COMMON_DIR/FETCH_HEAD`, so parallel reviewer lanes
fetching into otherwise-private namespaces failed nondeterministically on `FETCH_HEAD.lock`.
`fetch_refspecs` passes `--no-write-fetch-head`: every caller names its destination refs explicitly
and nobody reads `FETCH_HEAD` (perk treats it as clobber-racy by design). The flag needs git ≥ 2.29
— perk does not run a git version matrix, so that floor is asserted, not exercised. Other shared
state under the common dir (auto-gc, `packed-refs` rewrites) remains untested under concurrency.

## A lock-free network phase needs a fence at the locked commit

`perk librarian add source` claims its target atomically (`mkdir` without `exist_ok`), clones
**lock-free**, then records the entry under the library lock (`src/perk/library/source.py`). The
claim protects only directory creation. Two interleavings got through it: another run adopted the
finished clone and this run's failure cleanup removed the other run's catalogued checkout; another
run re-pinned and this run then recorded a stale `--ref` against the other's HEAD. The fix shape:
snapshot the catalog's owner of the path before the clone; under the lock, record only if the owner
still equals the snapshot (else refuse `checkout_invalid`); on failure clean up only while that
owner is unchanged, and keep the directory when unsure. This is the general shape for "network work
outside the lock, commit under it".

## Layering — mechanics here, forge policy in `perk.github.reviews`

`pr_merge_base_diff(repo, pr_number=…, base_ref=…)` — fetch `refs/pull/N/head` and the base branch
into a private namespace → merge-base → `diff_range` → best-effort `finally` cleanup that never masks
the read's result — lives in the substrate, which already knows the `refs/pull/N/head` shape.
**When** a locally rendered diff replaces the forge's (GitHub's 406 `too_large`, a forced `--local`)
and **how** that is disclosed (`diff_source`, `LocalDiffReason`) stays in the gateway
(`src/perk/github/reviews.py`; see `workflow/github-gateway.md`). Objects are fetched into refs, never
checked out or executed. The stack diff rides the same primitive:
`stack_merge_base_diff(repo, pr_numbers=…, base_ref=…)` fetches every member head + the base into one
private namespace, runs the ancestry gate (`check_stack_topology` → `StackTopologyError`, which also
folds a probe that fails to run into the typed refusal; shared with the checkout worker) and diffs
base→top; `pr_merge_base_diff` is its single-PR arity, and `review_context_cmd.py::_combined_diff`
is now only the `UserFacingCliError` translation boundary.

## `git archive` and checkout are not raw committed-blob reads

`git archive` honours `export-ignore` (silent drops, so change stats read all-zero),
`export-subst` (rewrites `$Format:…$`) and working-tree conversion (eol, ident, filter drivers
including an LFS smudge); `--attr-source=<empty tree>` does **not** neutralize archive attributes
(verified). `checkout-index` and worktrees convert the same way. For exactly what the commit
stores (`src/perk/substrate/git.py`, consumed by `src/perk/delivery/change_stats.py`):

- list the range with `git diff --raw -z --no-abbrev` — both sides' modes and blob ids, so a
  symlink (`120000`) or gitlink (`160000`) side is treated as absent;
- read the blobs with one `git cat-file --batch` in bytes mode (`git.read_blobs`, on the sanctioned
  `proc.run_captured_bytes`);
- decode `-z` pathnames with `os.fsdecode` (surrogateescape) — strict decoding raised
  `UnicodeDecodeError` past the fail-soft wrappers;
- materialize each side under a per-entry scratch directory named by base name, which avoids
  same-name and case-insensitive collisions and cloc's path-component exclusions while keeping
  filename-based language detection.

Fixtures that need a non-UTF-8 filename build it index-only (`git hash-object -w` +
`git update-index --cacheinfo`, `tests/test_change_stats.py`), because APFS refuses the name on
disk.

## Cleanliness proofs must override submodule ignore settings

Plain `git status --porcelain` honours `submodule.<name>.ignore` (including one set in
`.gitmodules`) and `diff.ignoreSubmodules`; with `ignore=all` it hides dirty submodule content,
untracked files inside the submodule and a moved submodule HEAD. The `run_librarian` bracket passes
`--ignore-submodules=none` (`extension/substrate/git.ts::trackedChanges`, pinned by a submodule
test that fails without the flag). The superproject's untracked inventory cannot see inside a
submodule, so any content there fails closed as an unclean start.
`extension/substrate/git.ts::worktreeDirty` — used by the §8.65 `revalidationBracket` and
commit-compact — still runs plain status: a filed follow-up, named here so nobody treats it as
proven.

## Ignore probes are name-only, index-blind under --no-index, and order-sensitive

The `git check-ignore` mechanics live in `src/perk/substrate/git.py::ignored_subset`'s docstring —
`-z` needs `--stdin`; `--no-index` reports a tracked-but-covered file as ignored, so a "cache-only"
guard needs a separate `:(literal)` tracked sweep via `tracked_paths`; a path git still C-quotes
reads as unignored, so the probe fails closed. Read them there. Two cross-cutting rules the
docstring does not carry:

- **A probe beyond a symlink is fatal (exit 128, `pathspec … is beyond a symbolic link`), not
  "unignored".** Walk the path's components for symlinks *before* the ignore probe
  (`src/perk/library/guard.py::require_unlinked_components`); in the opposite order a typed refusal
  (`entry_path_invalid`) degrades into a `GitError` → `io_error`. Alternatively probe a
  **known-free** candidate path (the first free staging name), which by construction is neither
  present nor a symlink — the ignore probe is representative by path class.
- **Ignore probes never look where a link points** — a symlinked leaf passes the probe while the
  write lands outside the fenced directory. The write-site rule (refuse redirects without following
  links) is `workflow/init-doctor.md` § "Every write site behind an ignore-probe fence refuses
  redirects without following links".

## Two roots

`main_worktree_root(cwd)` vs the invocation `repo_root`: from a linked worktree they differ, and the
choice decides where config is loaded from and which selector is written. The authoritative
statement is the "Two roots" docstring in `src/perk/cli/plan_selection.py` (invocation root for
worktree-local binding reads only; main root for config, canonical reads, and all selector writes);
the function itself is `perk/cli/context.py::main_repo_root`, re-exported by `plan_selection.py`;
the cold-door consequence — the launcher must compute both, not derive one from the other — is in
`workflow/cold-door-launch.md`.

## Cross-references

- `src/perk/substrate/git.py` — `diff_range`, `fetch_refspecs`, `stack_merge_base_diff`,
  `pr_merge_base_diff`, `check_stack_topology`, `StackTopologyError`, `main_worktree_root`,
  `ignored_subset`, `tracked_paths`, `LIBRARY_GIT_ENV` + `pinned=`, `is_dirty`, `fetch`,
  `is_ancestor`, `read_blobs`
- `src/perk/substrate/proc.py::run_captured_bytes` — the sanctioned binary-output wrapper
- `extension/substrate/git.ts` — `trackedChanges` (the submodule-proof bracket probe),
  `worktreeDirty` (plain status, the open follow-up)
- `tests/test_git.py` — the config-pin controls, the two-stage never-execute control, the argv pins
- `tests/_library_upstream.py` — the env-config `insteadOf` offline upstream
- `docs/learned/workflow/github-gateway.md` — the 406 `too_large` fallback and `diff_source` disclosure
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the conflict probe + rebase primitive
- `docs/learned/workflow/vacuity-proof-tests.md` — live controls for never-execute seams
- `docs/learned/workflow/cold-door-launch.md` — the two-roots consequence for launchers
- `docs/learned/workflow/init-doctor.md` — the link-blind write-site rule behind an ignore-probe fence
- `src/perk/library/` — `source.py` (claim → lock-free clone → owner-fenced record), `check.py`,
  `probe.py`, `guard.py::require_unlinked_components` (walk before probe), `lock.py` (the no-follow
  open)
