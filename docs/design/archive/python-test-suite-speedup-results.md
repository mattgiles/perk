# Python test-suite speedup — consolidated closeout (Objective #2306, node 4.1)

## 0. Status and binding

Evidence record for the plan branch `plan-2382`, authored 2026-09-10. A thin, pointer-based
synthesis over the four committed phase records — not a second copy of them. Short names: **P1** =
`docs/design/archive/python-test-suite-speedup-phase1-doctor.md`, **P2** =
`docs/design/archive/python-test-suite-speedup-phase2-resolve-guard.md`, **P3a** =
`docs/design/archive/python-test-suite-speedup-phase3-slow-classification.md`, **P3b** =
`docs/design/archive/python-test-suite-speedup-phase3-tier-recipes.md`.

| Item | Value |
|---|---|
| Closeout revision | `995dd772` — the plan branch's base (`git merge-base origin/main HEAD`); `git status --porcelain` empty before the §5 census and after its last command; every edit on this branch came after the census |
| Scope of this branch | this record, plus one closeout-time wiring change decided by the user during node 4.1 (§8): perk's in-session Python gate in `.perk/config.toml` re-wired from one `test-py` `[[ci.checks]]` row to the two complementary tier rows `test-py-fast` + `test-py-slow` on the suite's one `*.py` glob, its guard `tests/test_pytest_tiers.py::test_perk_python_gate_runs_the_complementary_tiers` re-aimed, and `docs/developers/testing.md` updated. No change under `src/`, `pyproject.toml`, `justfile`, `uv.lock`, `.github/` or `tests/conftest.py`; no recipe, marker or fixture change |
| Standing verification | `git diff 995dd772..HEAD --stat` must name exactly `.perk/config.toml`, `docs/design/archive/python-test-suite-speedup-results.md`, `docs/developers/testing.md` and `tests/test_pytest_tiers.py` |

**Consolidation rule.** Every measured figure below is a pointer into a committed phase record at
that record's own revision, re-run by nothing here; the one measurement this record adds is the §5
collection census (deterministic, not a timing). The gate re-wiring changes no recipe and nothing
pytest reads, so the census and every pointer stand unchanged; it carries **no speed claim** (§6).

## 1. Verdict and benefit classification

The objective set out to speed up Python test feedback and **did not demonstrate a repeatable
external wall-time improvement of the full default suite at any node**. Both timed comparisons
returned the pre-registered verdict **"within observed noise"** (node 1.1's full-suite
baseline/candidate; node 3.2's fast-vs-full). No speed claim is made anywhere in this record. What
the objective delivered is **ownership** (1.1: the Doctor bridge matrix narrowed onto its owning
seam, 6 → 2 engine runs), **safety** (2.1: the resolve-boundary guard fails closed, its rule
widened, live anchors), **classification + protection** (3.1: the strict `slow` marker in
`pyproject.toml` over a measured 15-case cohort and the build-consumer reachability guard) and
**selection ergonomics** (3.2: `just test-py-fast` / `just test-py-slow`, the guard module, the
developer guide) — plus the one number that changes a developer's day: the slow tier's
**sub-ten-second focused verdict** on the whole build/integration cohort (a selection, not a
speedup).

| Node | Pre-registered classification | Speed verdict | Headline figure | Source |
|---|---|---|---|---|
| 1.1 | maintenance/ownership | full suite **within observed noise** (every-candidate-below-every-baseline rule failed; n = 3 + 3, sequential) | 6 → 2 engine runs on a 10-case cohort | P1 §2, §6 |
| 2.1 | safety | **none taken, by design** | `tests/test_resolve.py::TestConsumerBoundary` 1 → 4 collected cases; two faults discriminated | P2 §1–§3 |
| 3.1 | classification/safety | **none taken, by design** | 15 cases marked `slow` (10 cohort + 5 threshold) | P3a §2–§3 |
| 3.2 | developer-ergonomics/selection | fast-vs-full **within observed noise** (`fast_med ≥ full_min`, pre-registered) | slow tier median 8.59 s external wall (7.93 s pytest-reported) | P3b §4 |

Classifications were pre-registered in each plan before measurement; no sample in any record was
discarded. The seed's Doctor attribution (≈ 19–20% of summed worker time over 6,842 cases at
`9186a1d6`) is **historical** and was never used as a baseline (Objective #2306 "Why"; P1 §1); the
seed memo `docs/planning/plan-to-speed-up-python-test-suite.md` is its origin and is untouched.

## 2. Delivery ledger

Incremental delivery; the dependency chain 1.1 → 2.1 → 3.1 → 3.2 → 4.1 was honored. The roadmap's
`PR` column holds the *plan issue*; the merge PR is a different number.

| Node | Plan issue | Merge PR | Merge commit | Measured base → candidate | Files in the merge PR | Record |
|---|---|---|---|---|---|---|
| 1.1 | #2352 | #2356 | `1a986894` | `758a59d0` → `532f0dd0` | P1, `tests/test_doctor.py` | P1 |
| 2.1 | #2361 | #2362 | `6c421810` | `c81f4ac3` → `92538f06` | P2, `tests/test_resolve.py` | P2 |
| 3.1 | #2369 | #2370 | `3abc4efc` | `675173d8` → `ce2d2d87` | P3a, `pyproject.toml`, `tests/test_binding_render_parity.py`, `tests/test_delivery_sync_integration.py`, `tests/test_objective_refine_cmd.py`, `tests/test_packaging.py` | P3a |
| 3.2 | #2375 | #2380 | `0a024976` | `f8d6cb38` → `b06bb524` | P3b, `README.md`, `docs/developers/index.md`, `docs/developers/testing.md`, `justfile`, `tests/test_pytest_tiers.py` | P3b |

No merge PR touched `src/`, `uv.lock`, `tests/conftest.py`, `.perk/config.toml` or
`.github/workflows/ci.yml` (`gh pr view <n> --json files`, read at the closeout revision). Node 4.1
is this branch (plan issue #2382): the record plus the in-session gate re-wiring named in §0 — the
first and only change to `.perk/config.toml` in the objective.

## 3. Evidence map

One row per bullet of the objective's Phase 4 list; each row carries at most one headline figure or
verdict and the record § that holds the full table.

| Phase-4 evidence category | Where it lives | Headline |
|---|---|---|
| Before/after Doctor (serial cohort, engine-run census) | P1 §5 | serial cohort median 2.51 s → 1.91 s; `run_doctor` (`src/perk/convergence/doctor/__init__.py`) 6 → 2 (counts never compared as time) |
| Before/after full-suite samples and verdict | P1 §6 | 6961 collected in all six samples; verdict "within observed noise" |
| Final full/fast/slow timings | P3b §4 | medians (external wall) full 116.78 s · fast 114.16 s · slow 8.59 s; series attempted 2 (1 aborted, 1 valid) |
| Collection and outcome accounting | P3b §3; this record §5 | at `b06bb524`: 7013 = 6998 + 15, disjoint, union = full, 0 skipped in every tier |
| Assertion-ownership ledger | P1 §3 | six engine-running node ids → one engine story + a four-row seam matrix + one direct case; the matrix deleted upstream recorded, not migrated (P1 §2–§3) |
| Guard-safety evidence (Doctor) | P1 §4 | F1 fails exactly the retained engine story, `tests/test_doctor.py::test_subagent_bridge_config_engine_story` |
| Guard-safety evidence (resolve boundary) | P2 §2–§3 | fail-closed discovery + strict-superset rule; F-empty and F-import both escape the old guard and are caught by the new one |
| Marker rationale (cohort rule, threshold rule, own cost) | P3a §2–§3 | every threshold mark ≥ 1.0 s own-cost median; every fast-keep < 1.0 s |
| Strict markers and the pytest 9.0.x `addopts` trap | P3a §2, §5; `docs/developers/testing.md` | the `strict_markers` ini key in `pyproject.toml` is what bites on the pinned 9.0.3 (pytest-dev/pytest#14442); `uv.lock` still pins 9.0.3 at the closeout revision |
| Shared-build observations | P3a §4; P3b §3 | one `uv build` per full/slow run on the worker holding the `wheel_build` xdist group (`tests/test_packaging.py`); zero per fast run |
| Remaining hotspots (post-Doctor profile) | P1 §7–§8 | `tests/test_doctor.py` 14.34% of summed worker time; top 15 modules = 50.0%; the only setup-dominant hotspot is `tests/test_plan_watch.py` |
| Deviations recorded by the phases | P1 §2; P2 §2; P3a §2; P3b §2 | see §8 |

**Staleness of the hotspot row.** P1 §7–§8 at `532f0dd0` is the **latest available** full-suite
profile. Later nodes added executing cases (2.1: `tests/test_resolve.py::TestConsumerBoundary`
1 → 4; 3.1: the live-session reachability guard; 3.2: four wiring tests) and upstream test drift
continued (collected 6961 → 6966 → 7013 → the §5 count); none changed production behavior. The
profile was deliberately **not re-run** — the objective forbids a closeout optimization campaign —
so the hotspot rows in §7 are leads at that revision, not current measurements.

## 4. Success criteria → evidence

Verdict vocabulary (closed): **guard-enforced** — a named test green under the full gates;
**record-pinned** — a named phase record §; **derivation-verified** — a command inlined with its
result at the closeout revision; **not-claimed** — satisfied by making no claim.

| Criterion (objective's "Scope, delivery, and success criteria") | Verdict | Evidence |
|---|---|---|
| Full default suite = everything ordinarily collected from `tests/`, slow included; prose suites stay behind `PERK_PROSE_REVIEW_TESTS=1` | PASS | guard-enforced: `tests/test_pytest_tiers.py::test_full_gate_recipes_run_the_whole_python_suite`; the `tests/conftest.py` ignore arm keyed on `PERK_PROSE_REVIEW_TESTS`; record-pinned: P3b §3; derivation-verified: §5 |
| Fast and slow are complementary selections, never a different standard; `slow` never skipped/xfailed/nightly-only | PASS | guard-enforced: `tests/test_pytest_tiers.py::test_tier_recipes_select_complementary_markers`; record-pinned: P3b §3 (passed 7013 = 6998 + 15; skipped 0 = 0 + 0); derivation-verified: §5 set checks |
| `just test-py`, `just test`, GitHub CI and perk's Python gate run the full suite under existing scope rules | PASS (wiring changed, scope held — §8) | guard-enforced: the first row's guard (`just test-py` / `just test` carry no marker filter), `tests/test_docs_gates.py::test_github_ci_runs_the_gate_recipes` (GitHub CI runs `just test`), and `tests/test_pytest_tiers.py::test_perk_python_gate_runs_the_complementary_tiers` (the in-session gate is exactly the two tier rows on the suite's one `*.py` glob, so one change set selects both or neither and their union is the full suite — §5 set checks); record-pinned: P3b §2 (the recipes) |
| Real Doctor composition, Git behavior, packaging and independent integrations preserved | PASS | record-pinned: P1 §2/§4, P3a §2, P2 §2 |
| Speed improvement claimed only on repeatable external wall-time improvement beyond noise | PASS (not-claimed) | P1 §6 and P3b §4 both "within observed noise"; no record claims a speedup |
| Maintenance/safety benefits reported separately from speed | PASS | §1 of this record; each record's §2 classification line |
| No numerical speed target or machine-specific timing assertion becomes a CI requirement | PASS | derivation-verified: the guards this objective added (`tests/test_pytest_tiers.py`, `tests/test_packaging.py::test_every_build_consumer_is_slow`, `tests/test_resolve.py::TestConsumerBoundary`) read no clock (`rg -n 'import time|from time|perf_counter|monotonic|datetime|timeit' tests/test_pytest_tiers.py tests/test_packaging.py tests/test_resolve.py` → empty); `.perk/config.toml` and `.github/workflows/ci.yml` untouched by every merge PR (§2 file lists) |
| Deliverables: Doctor narrowing, resolve-guard repair, measured slow classification, focused commands, evidence closeout | PASS | §2 (four merged PRs) + this record |
| Non-goals held (no production Doctor/config/parser change; no unsafe loaders/global memoization; no shared mutable worlds; `isolated_pi_agent_dir` and prompt hermeticity retained; no new dependencies; no default skips; no CI tier split; no scheduler/worker-cap change) | PASS with one recorded deviation | derivation-verified: the four merge PRs' file lists (§2) contain no `src/`, `uv.lock`, `tests/conftest.py` (home of `isolated_pi_agent_dir`), `.perk/config.toml` or `.github/` path; `git show 3abc4efc -- pyproject.toml` is the pytest marker/strict-markers block only (15 insertions, 1 deletion; P3a §2). **Deviation:** the in-session `run_ci` gate was split into the two tier rows at closeout by user decision (§0, §8) — GitHub CI and `just test` stay one process (guard-enforced by `tests/test_docs_gates.py::test_github_ci_runs_the_gate_recipes` and the first row's guard); the split attaches no numerical target and skips no case |
| Evidence discipline (three+ comparable samples per side where speed could change; raw logs outside the checkout; revision/dirty/host/tool/selection recorded) | PASS with named limitations | record-pinned: P1 §1/§6/§9 (sequential, not interleaved); P3b §1/§4/§5 (order-rotated; series 1 aborted and reported) |

## 5. Closeout-revision collection census

The only measurement in this record: serial `--collect-only` **through the recipes**, mirroring P3b
§3's method (`just <recipe> -n0 --collect-only -q`, node-id lines sorted). Raw output stayed under
the root; nothing was written under the checkout.

| Item | Observed |
|---|---|
| Closeout revision (`$root/revision`) | `995dd772` |
| Census root | `/tmp/perk-phase4-995dd772-20260910T154045Z` |
| Exit status, all three recipes | 0 · 0 · 0 |
| `just test-py` | 7016 collected |
| `just test-py-fast` | 7001 collected (`7001/7016 tests collected (15 deselected)`) |
| `just test-py-slow` | 15 collected (`15/7016 tests collected (7001 deselected)`) |
| `comm -12 fast.ids slow.ids` | empty (`fast ∩ slow = ∅`) |
| `sort -u fast.ids slow.ids \| diff - full.ids` | empty (`fast ∪ slow = full`) |
| `tests/test_pytest_tiers.py` items in the fast set | 4 |
| `tests/test_packaging.py::test_every_build_consumer_is_slow` in the fast set | 1 |

The slow set, sorted, verbatim — the fifteen ids of P3a §2, unchanged:

```
tests/test_binding_render_parity.py::test_binding_render_cross_plane_byte_parity
tests/test_delivery_sync_integration.py::test_amended_bottom_layer_cascades_with_exact_transplants
tests/test_delivery_sync_integration.py::test_conflicted_cascade_resolves_through_the_real_continue_arc
tests/test_objective_refine_cmd.py::test_refinement_loop_end_to_end_over_a_fake_linear_objective
tests/test_packaging.py::test_npm_pack_lists_shipped_and_excludes_dev
tests/test_packaging.py::test_sdist_excludes_perk_dev
tests/test_packaging.py::test_sdist_includes_changelog
tests/test_packaging.py::test_sdist_includes_hunk_feedback_extension
tests/test_packaging.py::test_wheel_and_sdist_exclude_docs_site
tests/test_packaging.py::test_wheel_bundles_agents
tests/test_packaging.py::test_wheel_bundles_changelog
tests/test_packaging.py::test_wheel_bundles_hunk_feedback_extension
tests/test_packaging.py::test_wheel_bundles_prompts
tests/test_packaging.py::test_wheel_bundles_shared
tests/test_packaging.py::test_wheel_excludes_perk_dev
```

The full/fast counts differ from P3b's 7013/6998 by the upstream `tests/` drift between `b06bb524`
and the closeout base — `git diff --stat b06bb524..995dd772 -- tests/ pyproject.toml`:
`tests/test_refinement_cross_backend_gate.py` added (711 lines; 5 items in `full.ids`),
`tests/test_objective_refine_cmd.py` shortened (44 lines, two test functions removed; 16 items in
`full.ids`), `tests/_github_fakes.py` +11 lines (a helper module, collects nothing) — so
7013 + 5 − 2 = 7016 and 6998 + 5 − 2 = 7001, with the slow set at 15 as expected.

## 6. Limitations (consolidated)

- n = 3 everywhere, on an uncontrolled laptop (P1 §9; P3a §5; P3b §5).
- P1's sampling was sequential, so the change is confounded with host drift (P1 §9).
- No per-worker split, no suite-wide subprocess census; shutdown tails reported but unattributed
  (P1 §7, §9).
- The textual resolve rule is a backstop, not a completeness proof (P2 §4).
- Threshold marks are point-in-time — only the build-cohort rule is guard-enforced (P3a §5).
- The `strict_markers` ini key in `pyproject.toml` becomes redundant once `uv.lock` moves past the
  #14442 fix (P3a §5).
- The fast tier's wall range overlaps the full tier's; concurrent tiers were not measured (P3b §5).
- The in-session gate's two rows (§0) run as two independent xdist pools under `run_ci`'s
  concurrent scheduling, alongside the other checks; their combined time is unmeasured (P3b §5), so
  the split is a wiring choice with no speed claim attached.
- This record adds no measurement beyond §5, so no "current speed" statement is possible — none is
  made.

## 7. Ranked separate follow-ups — authorizes nothing

Ranked by the planner's judgment of expected regression-safe value per bounded plan, informed by —
not determined by — the P1 §7a median shares at `532f0dd0` (see §3's staleness statement); nothing
here is precommitted work; each row names the promotion criterion the objective set.

| Rank | Follow-up | Evidence pointer | Benefit class | Promotion criterion |
|---|---|---|---|---|
| 1 | `tests/test_doctor.py` — 14.34% of summed worker time (225 cases, call-dominant); the retained real-engine stories were deliberately not swept | P1 §7a/§8 | speed lead | the P1 recipe — assertion-ownership ledger, engine-story retention, serial cohort before/after, one discriminating fault; three + three full-suite samples before any claim |
| 2 | `tests/test_plan_watch.py` — 2.01%, the only setup-dominant hotspot | P1 §7b | speed lead (fixture) | measure construction counts **per worker** (a session fixture runs once per consuming worker); choose replicated vs grouped explicitly; reuse `tests/conftest.py::_copy_template` and the blueprint isolation contract; add only family-specific topology/containment proofs |
| 3 | The seed's three "specialized immutable world" candidates — `tests/test_objective_refine_cmd.py` (5.31%, high per-sample variance; one case already `slow`), `tests/test_launch_restore.py` (2.87%), `tests/test_pr_review_stack_checkout.py` (2.15%) | P1 §7a | speed leads, not measured savings | as row 2, plus fresh mutable copies, local-origin containment and real per-case Git operations preserved |
| 4 | `tests/test_git.py` — 5.08%, 93 cases, call-dominant | P1 §7a | speed lead | as row 1; real Git behavior stays per case |
| 5 | Near-threshold call-dominant modules grouped — `tests/test_launch.py`, `tests/test_delivery_cross_machine.py`, `tests/test_objective_cmd.py` (each ≈ 2.1–2.2%), and `tests/test_packaging.py` (2.66%; now the slow cohort, its cost the one-shot `uv build`) | P1 §7a | leads at the noise floor | none proposed — revisit only after a fresh profile |
| 6 | `/learn` reconciliation of `docs/learned/workflow/issue-backend.md` (under-describes the resolve guard) and `docs/learned/toolchain/test-parallelism.md` (omits strict markers, the `slow` marker and the tier recipes) | P2 §4; P3a §5; P3b §5 | docs-truth | the `/learn` pass — learned docs are never authored ad hoc |
| 7 | Measurement-method debt — per-worker split, suite-wide subprocess census, shutdown-tail attribution, interleaved sampling | P1 §7, §9 | measurement | a prerequisite for any future speed *claim* to be attributable; not itself an optimization |
| 8 | Concurrent fast/slow benchmarking — now the shape of the in-session gate (§0), still unmeasured | P3b §5; this record §6 | characterization | the first step if any combined-time claim for the split is ever wanted (three+ samples per configuration, run-all `run_ci` wall time, the single-row wiring as the control); the guide states none is claimed |
| 9 | Strict-markers redundancy — once `uv.lock` moves to a pytest carrying the #14442 fix, `pyproject.toml`'s `addopts` flag becomes effective and its `strict_markers` key redundant but harmless | P3a §5 | maintenance | touch when the pin moves; keep both until then |
| 10 | The seven duplicate deletions — measured combined cost 0.118 worker-seconds | Objective #2306 "Deferred work and promotion criteria" | maintenance | when those modules are touched for another reason; never as a speed plan |
| 11 | The remaining objective deferrals — broader production-source sharing and parsed-tree caching (must prove discovery/decoding/exclusion equivalence and preserve `LIVE_ANCHORS`, `EXCLUDED_ANCHOR` and the fail-closed `_production_files` in `tests/test_resolve.py`; never substitute `tests/conftest.py::source_corpus` for the package walker), retention/cleanup policy, YAML loaders, imports/plugins, worker calibration, scheduler changes | Objective #2306 "Deferred work" | unmeasured | no measured lead exists; a profile first |

## 8. Deviations and refinements recorded (noted, not re-decided)

- The objective's second Doctor target had already been deleted upstream before node 1.1 —
  recorded in the ledger, not migrated (P1 §2–§3).
- The resolve-rule hole found beyond node 2.1's authored scope, and the strict-superset widening
  (P2 §2).
- "Setup-inclusive" refined to own cost; ten live build consumers against the historical count of
  fifteen candidates (P3a §1–§2).
- The `strict_markers` ini key added beside the `addopts` flag in `pyproject.toml` (P3a §2).
- `docs/user-docs/how-to/run-ci-in-session.md` deliberately not edited in node 3.2 (P3b §2).
- Benchmark series 1 aborted and reported; series 2 valid (P3b §4).
- **Closeout-time deviation (this node, user decision):** perk's in-session Python gate re-wired in
  `.perk/config.toml` from one `test-py` `[[ci.checks]]` row to the complementary `test-py-fast` +
  `test-py-slow` rows on the same `*.py` glob, so `run_ci` overlaps the slow build/integration
  cohort with the rest — a deliberate departure from the objective's "CI tier splitting" non-goal
  for the in-session gate only. `just test-py`, `just test` and GitHub CI still run the suite in one
  process; the union of the two rows is the full suite (§5; guard-enforced by
  `tests/test_pytest_tiers.py::test_perk_python_gate_runs_the_complementary_tiers`); no case is
  skipped and no speed claim attaches (§6). The plan's "record only" file scope was superseded by
  this decision; the objective's non-goal prose is reconciled by the landing flow, not here.

## 9. What this record does not do

No re-measurement; no reproduction of the phase records' tables; no new learned-doc text (routed via
§7 row 6); no recipe, marker, fixture, `justfile` or GitHub CI change; the four phase records
untouched; the seed memo untouched; the objective body's Phase 4 prose and non-goals are reconciled
by the landing flow, not here; no `CHANGELOG.md` entry (`changelog-check` validates structure only
— the P2 precedent).
