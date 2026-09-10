# Python test-suite speedup, phase 3 — slow classification and the build-fixture guard (Objective #2306, node 3.1)

A **classification/safety** record for the plan branch `plan-2369`: the bounded slow-candidate
cohort remeasured serially with per-fixture attribution, a `slow` marker registered under strict
markers, the wheel/sdist build cohort and the threshold cases marked, and one live-session guard
proving no fast-selected test reaches the shared build. Marking changes nothing the full default
suite runs, so there is **no speed claim** and no full-suite timing section — node 3.2 benchmarks
the tiers under the recipes. Compact tables and verbatim lines only; the raw TSVs, logs and the
temporary timing plugin stayed under `/tmp/perk-phase3/` and are not committed.

## 1. Scope and revisions

| Item | Value |
|---|---|
| Base revision (as measured) | `675173d8` — clean (`git status --porcelain` empty) |
| Candidate revision | `ce2d2d87` — two commits on the base (marks + guard + `pyproject.toml`; then the `strict_markers` ini key, §2); clean before and after every fault |
| Host | macOS (Darwin 25.5.0, arm64, Apple M3 Pro), an uncontrolled laptop |
| Tools | Python 3.13.9 · pytest 9.0.3 · pytest-xdist 3.8.0 · pluggy 1.6.0 · uv 0.12.3 · node v26.3.0 · npm 11.16.0 |
| Environment | `PERK_PROSE_REVIEW_TESTS` unset — the opt-in prose suites were never collected |

Live build-cohort inventory at the base revision (grep for `xdist_group("wheel_build")` +
`built_wheel`/`built_sdist`/`built_distributions`, confirmed by the guard's own closure walk): ten
consumers, all in `tests/test_packaging.py` — `test_wheel_bundles_shared`,
`test_wheel_bundles_prompts`, `test_wheel_bundles_changelog`, `test_sdist_includes_changelog`,
`test_wheel_bundles_hunk_feedback_extension`, `test_sdist_includes_hunk_feedback_extension`,
`test_wheel_excludes_perk_dev`, `test_sdist_excludes_perk_dev`, `test_wheel_bundles_agents`,
`test_wheel_and_sdist_exclude_docs_site`. The objective's historical count of fifteen is not an
invariant; the guard, not a number, is what holds. No full-suite timing samples were taken.

## 2. What changed and how it is classified

**`pyproject.toml`.** `addopts` gained `--strict-markers`; a `markers` list registers the one
project marker, `slow` (a selection, never a skip — the full default suite still runs every slow
case). **Deviation from the plan:** on the pinned pytest 9.0.3 the flag is silently inert when it
arrives via `addopts` — pytest 9.0 turned `--strict-markers` into an ini override that is applied
during the first argument parse, before `addopts` is read (pytest-dev/pytest#14442, fixed in a later
9.0.x). Verified in isolation: the same `addopts = "--strict-markers"` errors at collection on
pytest 8.4.2 and only warns on 9.0.3. The `strict_markers = true` ini key was therefore added
beside the flag; it is what bites on 9.0.3, while the flag keeps the declared `pytest>=8` floor
strict (there the key is unknown — a config warning, never an error). The `pytest>=8` floor and
`uv.lock` are unchanged.

**Marks.** Fifteen cases: the ten build consumers (`slow / cohort`), and five threshold cases —
`test_npm_pack_lists_shipped_and_excludes_dev`, `test_binding_render_cross_plane_byte_parity`,
`test_refinement_loop_end_to_end_over_a_fake_linear_objective`,
`test_amended_bottom_layer_cascades_with_exact_transplants`,
`test_conflicted_cascade_resolves_through_the_real_continue_arc` (`slow / threshold`). Every
`xdist_group("wheel_build")` stays; no fixture carries a mark; no test body changed.

**Guard.** `tests/test_packaging.py::test_every_build_consumer_is_slow` walks
`request.session.items` (the post-deselection list, so under `-m 'not slow'` it IS the fast set)
and fails on any `pytest.Function` whose `fixturenames` closure contains `built_distributions`
without a `slow` marker; an anchor arm asserts the walk still sees `test_wheel_bundles_shared`.
Nothing is re-collected. `tests/test_packaging.py` collects 19 → 20 (`--collect-only -q`, observed).

**Method (measurement).** Three serial `-n0` runs of the 26-case cohort under a temporary `/tmp`
plugin wrapping `pytest_fixture_setup` — pytest resolves a fixture's dependencies before that hook
fires, so each wrapped duration is that fixture's own function (a session build or git template is
charged to itself, never to its first consumer) — plus `pytest_runtest_logreport` phase durations.
Own cost = `call` + Σ function-scoped fixture setup; broad-scoped setup is attributed to the
fixture and reported once as shared cost; `teardown` is excluded from own cost because it carries
scope-boundary finalization, and its raw median is recorded instead. All three runs: 26 collected,
26 passed, no skips (wall 34.64 s / 176.93 s / 26.00 s — run 2 is a host-contention outlier that is
the maximum in every row and flips no verdict).

**Classification: classification/safety.**

## 3. Measurement and verdict

Own cost is the median over the three runs with min–max; setup/teardown are raw phase medians;
external processes are read from the test source.

| Node id (`tests/…`) | Own cost s | Setup / teardown s | External processes | Role | Verdict |
|---|---|---|---|---|---|
| `test_packaging.py::test_wheel_bundles_shared` | 0.01 (0.01–0.02) | **5.42** / 0.00 | `uv build` via the shared fixture | wheel bundles `_shared` | slow / cohort |
| `test_packaging.py::test_wheel_bundles_prompts` | 0.00 (0.00–0.00) | 0.00 / 0.00 | shared build | wheel bundles `_prompts` | slow / cohort |
| `test_packaging.py::test_wheel_bundles_changelog` | 0.00 (0.00–0.00) | 0.00 / 0.00 | shared build | wheel bundles `_data/CHANGELOG.md` | slow / cohort |
| `test_packaging.py::test_sdist_includes_changelog` | 0.02 (0.02–0.03) | 0.00 / 0.00 | shared build | sdist carries the force-include source | slow / cohort |
| `test_packaging.py::test_wheel_bundles_hunk_feedback_extension` | 0.00 (0.00–0.00) | 0.00 / 0.00 | shared build | wheel bundles `_hunk` | slow / cohort |
| `test_packaging.py::test_sdist_includes_hunk_feedback_extension` | 0.02 (0.02–0.02) | 0.00 / 0.00 | shared build | sdist carries the force-include source | slow / cohort |
| `test_packaging.py::test_wheel_excludes_perk_dev` | 0.00 (0.00–0.00) | 0.00 / 0.00 | shared build | never-published member stays out | slow / cohort |
| `test_packaging.py::test_sdist_excludes_perk_dev` | 0.02 (0.02–0.02) | 0.00 / 0.00 | shared build | never-published member stays out | slow / cohort |
| `test_packaging.py::test_wheel_bundles_agents` | 0.00 (0.00–0.00) | 0.00 / 0.00 | shared build | agent-def census rides the wheel | slow / cohort |
| `test_packaging.py::test_wheel_and_sdist_exclude_docs_site` | 0.02 (0.02–0.02) | 0.00 / 0.00 | shared build | docs site never ships | slow / cohort |
| `test_packaging.py::test_npm_pack_lists_shipped_and_excludes_dev` | 1.67 (1.37–1.98) | 0.00 / 0.00 | `npm pack --dry-run --json` | npm tarball surface | slow / threshold |
| `test_binding_render_parity.py::test_binding_render_cross_plane_byte_parity` | 9.82 (7.48–19.24) | 0.00 / 0.00 | one `node renderBindingsLive.ts` | cross-plane binding render parity | slow / threshold |
| `test_objective_refine_cmd.py::test_refinement_loop_end_to_end_over_a_fake_linear_objective` | 3.40 (2.18–30.75) | 0.00 / 0.00 | ≈12 `git` (scaffold) + one `node refinementLoopLive.ts` | the Linear refinement loop across both planes | slow / threshold |
| `test_delivery_sync_integration.py::test_amended_bottom_layer_cascades_with_exact_transplants` | 4.34 (3.30–83.11) | 0.00 / 0.00 | ≈30 explicit `git` + the sync's `RepoDeliveryGit` | real three-layer cascade | slow / threshold |
| `test_delivery_sync_integration.py::test_conflicted_cascade_resolves_through_the_real_continue_arc` | 5.75 (4.09–29.34) | 0.00 / 0.00 | ≈30 explicit `git` + sync + the retained-worktree resolution | conflict → continue arc | slow / threshold |
| `test_delivery_sync_integration.py::test_orphan_sweep_removes_real_residue_and_prunes` | 0.75 (0.57–1.20) | 0.49 / 0.00 | `git_repo` copy + ≈6 `git` + the sweep's `git` | recover orphan sweep | fast / directive |
| `test_prompt_parity.py::test_live_cross_engine_parity` | 0.31 (0.26–0.36) | 0.00 / 0.00 | one `node` | Jinja ↔ mini-jinja parity | fast / directive |
| `test_prompt_parity.py::test_live_manifest_covers_every_real_template` | 0.03 (0.03–0.03) | 0.00 / 0.00 | none | manifest coverage | fast / directive |
| `test_packaging.py::test_skills_shipped` | 0.13 (0.04–0.18) | 0.00 / 0.00 | none | skill frontmatter + manifest | fast / directive |
| `test_packaging.py::test_build_pins_and_all_packages_flag_present` | 0.02 (0.00–0.04) | 0.00 / 0.00 | none | build-pin lockstep | fast / directive |
| `test_packaging.py::test_version_lockstep` | 0.01 (0.01–0.02) | 0.01 / 0.00 | none | version lockstep | fast / directive |
| `test_packaging.py::{test_no_runtime_dependencies, test_npm_pin_lockstep, test_pi_toolchain_pin_lockstep, test_docs_site_publish_isolation, test_perk_skills_matches_skills_dir}` | 0.00 (0.00–0.01) | 0.00 / 0.00 | none | manifest / lockstep checks | fast / directive |

Every threshold-rule mark is backed by a ≥ 1.0 s own-cost median; every fast-keep measured under
1.0 s, so no `fast / directive (measured N s)` exception arose; no case had a raw teardown median
≥ 0.1 s (all 0.00).

Shared cost (broad-scoped fixture setup, charged to the fixture once per run; median · min–max):
`built_distributions` [session] 5.41 (5.10–9.12) · `_unborn_git_template` [session] 0.26
(0.13–0.42) · `_committed_git_template` [session] 0.19 (0.14–0.32). The first-consumer effect in
one line: `test_wheel_bundles_shared`'s raw `setup` median is 5.42 s against an own cost of 0.01 s
— the whole `uv build`, which pytest's `--durations`/JUnit view would have blamed on it; likewise
`test_orphan_sweep…`'s raw setup 0.49 s is mostly the two git templates.

## 4. Guard and selection evidence

Fault injection on the clean candidate tree (each edit restored with `git restore`; porcelain
empty before and after):

- **F-unmarked** (the `@pytest.mark.slow` line above `test_wheel_bundles_changelog` deleted) —
  serial `uv run pytest -n0 -q tests/test_packaging.py` → `1 failed, 19 passed in 13.15s`, the
  one failure `test_every_build_consumer_is_slow` listing exactly
  `tests/test_packaging.py::test_wheel_bundles_changelog`; parallel fast tier
  `uv run pytest -q -m 'not slow' tests/test_packaging.py` → `1 failed, 9 passed in 4.40s`, the
  same guard listing exactly `tests/test_packaging.py::test_wheel_bundles_changelog@wheel_build`
  (xdist's loadgroup suffix) after paying for the build.
- **F-misspelt** (that line changed to `@pytest.mark.sloww`) — serial: `1 error in 0.19s`;
  parallel fast tier: `6 errors in 1.31s` (one per worker); both
  ``ERROR tests/test_packaging.py - Failed: 'sloww' not found in `markers` configuration option``,
  no tests run. Recorded for the deviation in §2: at the first candidate commit (`addopts` flag
  only), the same fault did **not** error — `1 failed, 19 passed, 1 warning in 3.90s` with
  `PytestUnknownMarkWarning: Unknown pytest.mark.sloww`, the leak caught by the guard alone.

Selection accounting (`uv run pytest -n0 --collect-only -q`, node-id lines sorted): full 6966 ·
slow 15 · fast 6951; `comm -12 slow fast` empty; `sort -u slow fast` equals full;
`tests/test_packaging.py::test_every_build_consumer_is_slow` is in the fast set.

Tier runs with fresh basetemps: `-v -m slow` → `15 passed in 8.62s`, exactly one
`popen-gw3/distribution_build0`, all ten `wheel_build` consumers on `[gw3]`; `-v -m 'not slow'` →
`6951 passed in 114.21s`, zero `distribution_build*` directories, the guard collected and
`PASSED` on `[gw4]`. Console durations are observations only.

## 5. Observations and limitations

- **Out of cohort (not marked, for Phase 4):** none surfaced by the cohort modules beyond the
  named candidates; `test_skills_shipped` (0.13 s) is the only manifest check above 0.1 s.
- **Teardown:** no case reached the 0.1 s raw-teardown callout.
- **Strict markers on pytest 9.0.0–9.0.3** are only effective through the `strict_markers` ini key
  (or `-o strict_markers=true` / the CLI flag outside `addopts`); the `addopts` flag alone is a
  silent no-op there. Once `uv.lock` moves to a pytest carrying the #14442 fix the flag becomes
  effective again and the key becomes redundant but harmless.
- **The guard is a live-session check:** it bites in every run that selects it — the full gates
  (`just test-py`, `just test`, CI, `run_ci`) and the fast tier; the slow tier neither needs nor
  runs it. A narrower `-k`/`-m` selection that drops the anchor makes the anchor arm vacuous by
  design.
- **Sampling:** n = 3 serial samples on an uncontrolled laptop; run 2 (176.93 s wall) is a
  host-contention outlier — the maximum in every row — and the medians come from runs 1 and 3.
- `docs/learned/toolchain/test-parallelism.md` now under-describes the pytest configuration
  (`--strict-markers`, `strict_markers`, the `slow` marker); left for the `/learn` pass. Node 3.2
  owns the tier recipes and developer docs.
