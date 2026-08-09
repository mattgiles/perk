---
title: Worktree filesystem lifecycle — batch ops over plan-<N> checkouts
read_when: You are writing a worktree-batch command, extending `perk worktree wipe`'s residue sweep, the `[worktree] setup` hook, locating the main checkout via `main_worktree_root`, or a dirty worktree test.
---

# Worktree filesystem lifecycle

perk worktrees are filesystem checkouts (`plan-<N>/`) created per worktree stage. Batch operations over
them — like `perk worktree wipe` (`perk/cli/commands/worktree/wipe_cmd.py`) — are a distinct concern from a
worktree's plan-ref *binding* role (see `plan-ref-lifecycle.md`). The mechanics below generalize to any
worktree-batch command.

## Worktree-candidate identification

Filter `git.worktree_list()` by **both**:

- `wt.path.parent.resolve() == worktree_root.resolve()`, **and**
- name matching `^plan-(\d+)$`.

**`.resolve()` on BOTH sides is mandatory** — git porcelain returns absolute paths and macOS
`/var`→`/private/var` symlinks otherwise mismatch. This filter naturally excludes the main repo
worktree (not under `worktree_root`) and any hand-created / non-numeric worktrees. The rule is
**not** scoped to batch candidate identification — it holds for **all `git worktree list` path
comparisons** (another site: `perk worktree checkout`'s best-effort branch-label lookup,
`src/perk/cli/commands/worktree/checkout_cmd.py`).

The same rule has a new site beyond worktree matching: **CliRunner JSON-payload assertions on
macOS** — `git rev-parse --show-toplevel` resolves `runner.isolated_filesystem()`'s `/var/folders`
dir to `/private/var/folders`, so `.resolve()` the tmp dir before building expected repo-rooted
paths (see `session-data.md`).

## Uncertainty ⇒ skip, never delete

Per-worktree PR-state lookup goes through `github.get_plan(number=...)`. Any `GitHubError`,
`state is None`, or `pr is None` **skips** that worktree. Consequence: the command does **not** call
`require_github`, so a fully-offline run is a safe no-op that skips everything — no hard auth gate.

## `--force` semantics are split

`--force` bypasses only the *local* safety guards (dirty tree / pending-learn not cleared); it
**never** relaxes the MERGED requirement. When forcing, `git.worktree_remove(..., force=True)` is
required so git itself doesn't refuse a dirty tree.

The pure `_classify_worktree(...) -> WipeDecision` helper encodes all of this and is unit-testable with
no I/O. **Push the decision into a pure classifier, keep I/O in the loop.**

## Gather (parallel) → act (parallel removal + batched deletes) split

`_wipe_impl` runs in phases. **Gather**: per-worktree facts (`backend.get_plan`, `git.is_dirty`,
`cache.has_marker`) are network/subprocess-bound, read-only, and thread-safe, so they run
concurrently on a `ThreadPoolExecutor` (capped by `_MAX_GATHER_WORKERS`), each producing a frozen
`_GatheredFacts`. The issue backend is resolved **once** before the pool; an `IssueBackendError`
there marks every target skipped with `could not determine PR state (...)` — the offline no-op
posture is preserved.

**Act** is no longer fully sequential. It runs:

1. **Classify** on the main thread, in candidate order — record each skip reason / removable
   `Worktree` (no output yet).
2. **Parallel worktree removal** — one `git.worktree_remove` per removable worktree on a
   `ThreadPoolExecutor` (capped by `_MAX_REMOVE_WORKERS`). This is safe to parallelize because the
   dominant cost is the **filesystem `rm -rf`** of the checkout (perk worktrees carry large
   gitignored trees, e.g. `.pi/npm/node_modules`), which is lock-free; git's per-worktree *admin*
   teardown is independent. This is distinct from the ref/index/commit churn git actually
   serializes (concurrent `commit`/`add`). **No output from worker threads** — results are keyed by
   path; a `GitError` is captured, a non-`GitError` propagates (crash, as before).
3. **Report** in one candidate-order pass — interleave skip lines and `✓ removed <name>` /
   `git worktree remove failed` lines so the global ordering still holds (asserted by
   `test_wipe_output_in_candidate_order`). Branch outcomes are *not* attached per-worktree anymore
   (the deletes happen afterward in one call each).
4. **Batched local branch delete** — one `git.delete_branches(repo, names, force=True)` call for
   all removed worktrees' branches.
5. **Batched remote branch delete** — one `git.delete_remote_branches(repo, names)` call, guarded
   by `git.has_remote(repo)` so a remote-less repo emits nothing.

Branch deletes (local + remote) run **after** all removals — git refuses to delete a branch checked
out in a live worktree.

## Robust removal: self-heal slow + broken worktrees, then prune

`git.worktree_remove` shells `git worktree remove [--force] <path>` (the heavy `rm -rf` of the
gitignored `node_modules`/`.venv`/`.pi/npm/node_modules` trees) with a generous
`_WORKTREE_REMOVE_TIMEOUT = 300` (the default 30 s is far too short). On a **recoverable** `GitError`
it falls back to a Python `shutil.rmtree` (no subprocess timeout; copes with a partial tree):

- **`_is_recoverable_remove_failure(message)`** matches exactly two refusals: `timed out` (a slow
  `rm -rf` under disk contention) and `validation failed` (a broken worktree whose `.git` gitlink is
  gone — which `--force` does **not** bypass). These are causally linked: a timed-out removal leaves
  the residue that becomes the next run's validation failure, so the stale population only grows
  until self-heal breaks the loop.
- A **dirty refusal** (`contains modified or untracked files` / `use --force`) is deliberately NOT
  matched, so it re-raises unchanged — the `shutil.rmtree` fallback never fires on it, and
  `perk worktree remove` keeps protecting uncommitted work. (Safety test:
  `test_worktree_remove_dirty_refusal_not_recovered`.)
- **The fallback leaves a stale admin entry.** When `shutil.rmtree` removes the dir, the
  `.git/worktrees/<id>` admin record lingers (git didn't run its teardown). So the contract is:
  every caller MUST follow up with a **serialized** `git.worktree_prune(repo)`. The fallback does
  NOT prune itself — `git worktree prune` rewrites the whole worktree set and is unsafe under the
  concurrent removal pool.

**Prune ordering is load-bearing.** Wipe calls `worktree_prune` once on the main thread *after* the
removal pool and *before* the branch deletes: until the stale admin entry is pruned, git still
believes the (deleted) dir has the plan branch checked out and refuses `git branch -D <branch>` with
"checked out at …". This one serialized prune also sweeps the pre-existing orphan admin entries
already on disk. It runs in the **non-dry-run path only** (it sits after the dry-run early return).
`perk worktree remove` prunes after its single successful removal (a no-op when git's own removal
succeeded).

**Pool size.** `_MAX_REMOVE_WORKERS` is **8** (was 32): 32 concurrent `rm -rf`s of
`node_modules`/`.venv` trees thrash the disk badly enough that individual removals starve and time
out (producing the broken residue above); a smaller pool lets each finish on the primary git path so
the `shutil.rmtree` fallback stays the exception, not the norm.

**Gather guard for a fully-missing dir.** `_gather_facts` returns neutral facts
(`is_dirty=False, has_pending_learn=False`) when `not wt_path.exists()`, before running
`git.is_dirty` / `cache.has_marker` — a working dir that is entirely gone would otherwise let
`git status` run against an unexpected `.git`-walk ancestor (or crash on a nonexistent cwd). Such an
entry flows normally to classification; the end-of-pool prune clears its admin record.

## Branch deletion is best-effort, forced, and batched

- **Local** — `git.delete_branches(repo, names, *, force=False) -> list[str]` runs one
  `git branch -D|-d <names…>` via the lenient `_run_capture` (never raises per-branch), parsing the
  `Deleted branch <name>` stdout lines for what actually deleted; a refused/missing branch is just
  absent from the result. Wipe passes `force=True` (`-D`): wipe only ever touches worktrees whose PR
  is provably `MERGED`, so `-d`'s "refuses when local trunk lags the merge" check is wrong here (it
  was the old "branch survives wipe" bug). The single-branch `git.delete_branch(...)` (raises) stays
  for its existing test/caller.
- **Remote** — `git.delete_remote_branches(repo, names, *, remote="origin")` is default-on and
  best-effort (no opt-in flag, no `require_github` gate — offline stays a clean no-op). **Gotcha:**
  `git push --delete` aborts the **whole** batch client-side if *any* ref is missing
  (`remote ref does not exist`) — and an already-gone ref is the *common* case (GitHub's
  auto-delete-head-branch-on-merge). So the helper **probes `git ls-remote --heads` once** and
  deletes only the survivors (already-gone refs count as success). This is a deliberate deviation
  from the plan's "no pre-probe / blind batch" decision, which rested on a false premise about
  `git push --delete` being non-atomic for missing refs. `has_remote` / `delete_remote_branches`
  use `_run_capture` and never raise.

`_run_capture(args, *, cwd, timeout)` is the sanctioned best-effort primitive: `check=False`,
returns the `CompletedProcess` (callers parse stdout/stderr on partial failure), but still raises
`GitError` on `TimeoutExpired`. `_run` (raises on non-zero) remains the default for single ops.

## Wipe also sweeps unregistered residue dirs + stranded branches

Beyond git-registered `plan-<N>` worktrees, `perk worktree wipe` sweeps two further populations that
the registered-candidate filter can't see. Both are additive to the existing gather→act flow.

- **Unregistered `plan-*` residue dirs** under the worktree root are what a timed-out removal plus a
  later `git worktree prune` leaves behind: a partial checkout git no longer registers.
  `_enumerate_residue` classifies them **structurally and fully offline** — no `.git` entry ⇒
  provably not a checkout ⇒ `shutil.rmtree`; a `.git` entry / symlink / non-dir ⇒ skip with a
  reason. There is *no* backend resolution for a residue-only sweep (residue holds no checkout, so
  no PR state to protect), and the rmtrees ride the **same 8-worker removal pool** as the registered
  removals (they are the same heavy FS deletes).
- **Stranded local `plan-*` branches** checked out in no worktree (`_enumerate_stranded_branches`
  subtracts every checked-out branch from `git.local_branches("plan-*")`) are deleted **only when
  the PR is provably MERGED** — uncertainty ⇒ skip, offline ⇒ no-op — riding the existing batched
  local+remote delete. **Safety-by-posture, no name-shape guard needed:** a branch merely *matching*
  `plan-*` by coincidence (a human-created branch) is protected by the same uncertainty⇒skip gate —
  its plan lookup fails, so it's kept. The `--force` split does NOT relax this (a stranded branch has
  no working tree, so there's no local guard to bypass).

**Pre-prune snapshot enumeration ⇒ two-run convergence (deliberate).** Residue is enumerated against
the `git.worktree_list` snapshot taken at the *top* of `_wipe_impl`, *before* the end-of-run prune.
So an entry the prune orphans this run becomes the *next* wipe's residue — a run never deletes a dir
it just skipped, and the unconditional global prune's orphaning side effect becomes self-healing
over two runs rather than a same-run hazard.

**Output/return contracts stay byte-identical on a residue-free repo.** The early
`no plan worktrees to wipe` return fires only when the registered + residue + stranded candidate
sets are *all* empty; the residue/stranded output segments are conditional, so a repo with none of
them produces byte-identical output (and its existing test pins hold).

**Validation caution (the destructive sweep is under-proven).** All landed coverage is synthetic
pytest fixtures. The *actual* validation of a destructive sweep is the first real-repo run
(`--dry-run` → eyeball the candidate list → re-run with `--force`); parallel `rmtree` of large real
`node_modules` trees under disk contention is unproven at scale. Treat the first real run as the
validation, not the fixtures.

Source pointer: `perk/cli/commands/worktree/wipe_cmd.py` (`_enumerate_residue`,
`_enumerate_stranded_branches`, `_Residue`).

## The `main_worktree_root` primitive — the MAIN checkout from inside a linked worktree (#730)

`git.main_worktree_root(cwd) -> Path | None` locates the **main checkout's** root from anywhere
inside a *linked* worktree. It runs `git rev-parse --git-common-dir` (the shared `.git` of the main
checkout) and returns its `.parent`:

- **Both return forms are handled.** In the main checkout `--git-common-dir` returns a *relative*
  `.git` — resolve it against `cwd`, then take the parent. In a linked worktree it returns the
  *absolute* path to the main repo's `.git` — its parent is the main root directly. The
  implementation resolves the relative form (`(cwd / common).resolve()`) before taking `.parent`,
  so both collapse to the same answer.
- **Contrast `repo_root` / `--show-toplevel`,** which returns the *worktree's* own root — the whole
  reason a separate primitive exists. Use `main_worktree_root` for anything that lives canonically in
  the main checkout **only** (gitignored secrets/config that are never copied into a worktree, e.g.
  the `.pi/perk.local.toml` Linear key — see `config-tables.md` / `linear-backend.md`).
- **Fail-open to `None`** (not a git repo) preserves the caller's non-repo fallback (callers use
  `main_worktree_root(repo_root) or repo_root`, keeping `tmp_path`-rooted tests byte-identical).
- **Test gotcha (macOS):** `tmp_path` is a `/var → /private/var` symlink and `--git-common-dir`
  returns the realpath, so worktree-root assertions must `.resolve()` **both** sides (the same
  `.resolve()`-both-sides rule as worktree-path matching above).
- **Safe layering:** `config` importing `git` is fine — `git.py` imports only stdlib, so there is no
  cycle risk.

## The `[worktree] setup` hook and the `created`-flag dry-run asymmetry (#652)

`[worktree] setup` is an array of shell commands run inside a freshly created worktree before
`exec pi` (see `cold-door-launch.md` for `run_worktree_setup`, the single canonical
setup-execution path). The durable gotcha is in the dry-run preview:

- **`ResolvedWorktree.created` does NOT cover the dry-run "would create" case.** `created=True` is
  set only in the `elif materialize:` branch of `resolve_worktree`, so on a `--dry-run`
  (`materialize=False`) `created` is **always False**, even when the stage *would* freshly create
  the worktree. The real-run hook gate (`if resolved.created and config.worktree_setup`) therefore
  can't drive the dry-run preview. The fix: the `_emit_dry_run_preview` "would run setup" branch
  **re-derives the would-create signal independently** as
  `stage.worktree == "create" and not resolved.path.exists()` (the same condition that gates a real
  create), NOT `resolved.created` — the same two-signal split the existing dry-run base-resolution
  already uses. **Future "fires only on fresh create" features should expect this
  real-run-vs-preview asymmetry.**
- **`user_output` → stderr, `machine_output` → stdout.** A dry-run preview test asserting the human
  "would run setup: …" line reads `capsys.readouterr().err`; the JSON payload is on `.out`.
- **ty gotcha:** a `**kwargs` dict passed to a keyword-only `resolve_worktree` trips ty
  (`invalid-argument-type` — the dict's inferred union value type isn't assignable); use an inner
  helper closure calling the function with explicit keywords instead of unpacking an untyped dict.

This is exterior-only (no `shared/` change; the contract + a new Divio how-to landed in the same
turn per the amend-don't-drift rules). See `docs/learned/workflow/config-tables.md` for the
overlay-aware `[worktree] setup` parser.

## Exterior-only — no `shared/` change

Worktree lifecycle lives entirely in the Python plane. `wipe` is a plain CLI subcommand (not a stage),
emits plain text (no `--json`), and matches the rest of the `wt` family — so no
`contracts.md`/`registry.yaml` edit is needed (cli-vs-pi §2.2).

## Test-harness gotcha: `.pi/` makes a bare test repo dirty

`cache.set_marker(wt, cache.PENDING_LEARN)` writes into `.pi/workflow/markers/`, which makes the
worktree *dirty* in a bare test repo (where `.pi/` isn't gitignored). The dirty guard then fires
*before* the pending-learn guard and masks the intended assertion. **Fix in the test:** write `.pi/`
into the repo's `.git/info/exclude` to mirror what `perk init` gitignores in real repos, so the marker
is the sole signal under test.

## Cross-references

- `perk/cli/commands/worktree/wipe_cmd.py` — `wipe_worktrees`, `_classify_worktree`, `WipeDecision`, `_wipe_impl`, `_gather_facts`, `_enumerate_residue`, `_enumerate_stranded_branches`, `_Residue`, `_MAX_REMOVE_WORKERS`
- `perk/substrate/git.py` — `delete_branch`, `delete_branches`, `delete_remote_branches`, `has_remote`, `_run_capture`, `worktree_remove`, `worktree_prune`, `worktree_list`, `_is_recoverable_remove_failure`, `_WORKTREE_REMOVE_TIMEOUT`
- `docs/learned/workflow/plan-ref-lifecycle.md` — the plan-ref *binding* role of a worktree (distinct from filesystem batch ops)
- `docs/learned/workflow/session-data.md` — the CliRunner-payload instance of the `.resolve()` rule
- `docs/learned/workflow/cold-door-launch.md` — `run_worktree_setup`, the single canonical setup-execution path
- `docs/learned/workflow/config-tables.md` — the overlay-aware `[worktree] setup` config key + the local-only secret reader consuming `main_worktree_root`
- `docs/learned/workflow/linear-backend.md` — the corrected worktree Linear-key bridge (the other `main_worktree_root` consumer)
