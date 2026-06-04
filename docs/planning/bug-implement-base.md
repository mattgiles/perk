# Bug — base the `implement` worktree branch on a freshly-fetched `origin/<trunk>`

Canonical plan: GitHub issue #34. This doc records only the **outcomes** (deviations,
refinements) per the per-turn doc discipline.

## Outcomes

- **`perk/git.py`** — added `fetch` (network op, `timeout=120` via a new `_run(timeout=...)`
  param), `detect_trunk_branch` (origin/HEAD symbolic-ref → main/master → `"main"`),
  `remote_ref_exists` (local-only `rev-parse --verify --quiet`); extended `worktree_add` with an
  optional `base` start-point.
- **`perk/launch.py`** — `ResolvedWorktree.base`; `resolve_base` (exported as a public helper so
  the plan-id dry-run reuses it — not a private `_resolve_base` per the plan's "thin wrapper"
  note); `_fetch_best_effort` (loud "STALE" warning, non-fatal). Create-only: reuse never fetches
  or re-bases (D4); dry-run resolves the base from local refs with no fetch; materialize fetches
  then resolves. `launch_stage` threads `base` and adds `"base"` to the dry-run payload.
- **`perk/cli/commands/implement_cmd.py`** — `--base` option threaded into both `launch_stage`
  calls; `_render_dry_run` resolves + surfaces `base` (consistent with the active-ref dry-run).
- **`shared/contracts.md`** — amended the implement/worktree Status with the origin-aware-base
  contract (same turn).
- **Tests** — `tests/conftest.py` grew a `git_repo_with_remote` fixture (local bare remote + an
  `advance_origin()` helper, fully offline). `tests/test_git.py` covers the four git functions;
  `tests/test_launch.py` covers origin-aware create, reuse-no-fetch, offline-warn, remote-branch
  tracking, `--base` verbatim, and dry-run-surfaces-base; `tests/test_implement_cmd.py` asserts the
  plan-id dry-run JSON carries `base`.

### Deviation from the plan

- **Step 6 (`scripts/verify-bug-implement-base.sh` + `just verify`) was dropped.** Plan #33 landed
  first and **retired all `scripts/verify-*.sh`**, moving regression coverage into the `pytest` +
  `node:test` suites gated by `just ci`. There is no `scripts/` dir or `just verify` recipe to wire
  into. Per the current convention the hard gate is the pytest coverage above (all of which is
  offline-runnable via the local bare remote), gated by `just ci` (green).
