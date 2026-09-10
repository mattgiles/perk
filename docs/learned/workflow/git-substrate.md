---
title: The git substrate safety contract (src/perk/substrate/git.py)
read_when: You are adding or changing a git.py primitive — a review-read diff, a fetch into temp refs, anything run against untrusted PR content or concurrently across linked worktrees.
cluster: plan-lifecycle
---

# The git substrate safety contract

`src/perk/substrate/git.py` is the one place perk shells out to `git`. Two of its primitives run
against inputs perk does not control — **untrusted PR content** (a reviewer reads a diff of
whatever an author pushed) and **a shared ref store** (linked worktrees under one `$GIT_COMMON_DIR`,
with parallel reviewer lanes fetching at once). The contract below is what keeps those reads safe;
every rule was established by a live failure or a live control, not by reading the git manual.

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

## A private temp-ref namespace does not make concurrent fetches private

Linked worktrees share ONE ref store. Fetching into a per-invocation namespace
(`refs/perk/review-ctx/<uuid>/…`) keeps *refs* from clobbering each other — but a plain `git fetch`
also locks and rewrites the **shared** `$GIT_COMMON_DIR/FETCH_HEAD`, so parallel reviewer lanes
fetching into otherwise-private namespaces failed nondeterministically on `FETCH_HEAD.lock`.
`fetch_refspecs` passes `--no-write-fetch-head`: every caller names its destination refs explicitly
and nobody reads `FETCH_HEAD` (perk treats it as clobber-racy by design). The flag needs git ≥ 2.29
— perk does not run a git version matrix, so that floor is asserted, not exercised. Other shared
state under the common dir (auto-gc, `packed-refs` rewrites) remains untested under concurrency.

## Layering — mechanics here, forge policy in `perk.github.reviews`

`pr_merge_base_diff(repo, pr_number=…, base_ref=…)` — fetch `refs/pull/N/head` and the base branch
into a private namespace → merge-base → `diff_range` → best-effort `finally` cleanup that never masks
the read's result — lives in the substrate, which already knows the `refs/pull/N/head` shape.
**When** a locally rendered diff replaces the forge's (GitHub's 406 `too_large`, a forced `--local`)
and **how** that is disclosed (`diff_source`, `LocalDiffReason`) stays in the gateway
(`src/perk/github/reviews.py`; see `workflow/github-gateway.md`). Objects are fetched into refs, never
checked out or executed. Residual: `review_context_cmd.py::_combined_diff` (the stack diff) still
carries its own temp-ref orchestration beside the substrate's — a fold into one primitive is an open
follow-up.

## Two roots

`main_worktree_root(cwd)` vs the invocation `repo_root`: from a linked worktree they differ, and the
choice decides where config is loaded from and which selector is written. The authoritative
statement is the "Two roots" docstring in `src/perk/cli/plan_selection.py` (invocation root for
worktree-local binding reads only; main root for config, canonical reads, and all selector writes);
the cold-door consequence — the launcher must compute both, not derive one from the other — is in
`workflow/cold-door-launch.md`.

## Cross-references

- `src/perk/substrate/git.py` — `diff_range`, `fetch_refspecs`, `pr_merge_base_diff`, `main_worktree_root`
- `tests/test_git.py` — the config-pin controls, the two-stage never-execute control, the argv pins
- `docs/learned/workflow/github-gateway.md` — the 406 `too_large` fallback and `diff_source` disclosure
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the conflict probe + rebase primitive
- `docs/learned/workflow/vacuity-proof-tests.md` — live controls for never-execute seams
- `docs/learned/workflow/cold-door-launch.md` — the two-roots consequence for launchers
