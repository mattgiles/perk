# Python test-suite speedup, phase 1 — the Doctor bridge matrix (Objective #2306, node 1.1)

Evidence record for the plan branch `plan-2352`: a fresh, correctly attributed full-suite baseline,
the narrowing of the surviving `test_subagent_bridge_config_*` engine matrix onto the check it owns,
the assertion-ownership ledger, the fault-injection evidence, before/after measurements, and a
reprofile of the remaining hotspots. Summarized tables only — raw logs, JUnit XML and pstats stayed
under `/tmp` and are not committed. Diagnostic profiles (cProfile, audit hook, `--durations`) are
never compared with the uninstrumented timing samples.

## 1. Scope and revisions

| Item | Value |
|---|---|
| Seed revision (historical, the memo's numbers) | `9186a1d6` — its Doctor attribution (272 cases, 19–20% of summed worker time) predates two deletions and is **not** the "before" of this node |
| Plan branch base revision (baseline, as measured) | `758a59d0` — clean (`git status --porcelain` empty before and after every baseline sample) |
| Candidate revision | `532f0dd0` — the single test-only commit on top of the base; clean before and after every candidate sample |
| Host | macOS 26.5 (build 25F71); `os.process_cpu_count()` = 11 |
| Tools | Python 3.13.9 · pytest 9.0.3 · pytest-xdist 3.8.0 · uv 0.12.3 · just 1.58.0 · node v26.3.0 |
| Workers | 6 — `-n auto --dist loadgroup` bounded by `tests/conftest.py`'s auto-worker cap of 6 (`min(11, 6)`) |
| Environment overrides | `PERK_PROSE_REVIEW_TESTS` unset (`env | grep -c` → 0), so the opt-in prose suites were never collected |
| Retained-temp count before each sample | 4 (`pytest-of-$USER/pytest-*` under the Python `tempfile` dir) — identical before and after all six samples |
| Sampling order | sequential in the plan worktree: environment capture → three baseline samples → cohort runs → commit → fault injection → three candidate samples → cohort runs → collection timing |

## 2. What changed and how it is classified

**Deleted-matrix discovery.** The objective's second target — the `test_subagent_worktree_default_*`
matrix and its converger `src/perk/convergence/init/subagent_config.py` — no longer exists. Commit
`eb4bd441` removed the `subagent-worktree-default` managed convergence, its doctor check and that
10-test matrix; commit `0fcbcbe0` removed ~20 `test_subagent_compat_*` tests. `tests/test_doctor.py`
is ~575 lines shorter than at the seed revision, which is why the seed's Doctor attribution is
stale.

**Bridge narrowing.** At the base revision the `-k subagent_bridge_config` cohort collected 10 cases
of which six ran the whole doctor engine (`run_doctor`) to inspect one finding. They are replaced by
one two-step real-engine story (`test_subagent_bridge_config_engine_story`, two `run_doctor` calls),
a four-row direct-seam matrix over the project scope
(`test_subagent_bridge_config_project_scope_matrix[off|fork-only|always|invalid-json]`) and one
direct user-scope case (`test_subagent_bridge_config_user_scope_off_is_warn`), all calling
`_subagent_bridge_config_check` directly on a bare `tmp_path` root (the autouse
`isolated_pi_agent_dir` sets `PI_CODING_AGENT_DIR`, so the env arm resolves without any git
subprocess). Net: **10 → 10 collected cases, 6 → 2 engine runs**; `run_doctor(` call sites in the
file 129 → 125; test functions 196 → 193; the module still collects 225 cases. The three
config-arm direct tests and every other test in the file are untouched. A pure helper
`_bridge_settings_text(mode)` now produces the settings body both `_plant_user_bridge_mode` and the
matrix rows write (same bytes as before).

**Classification: maintenance/ownership.** Each observation now lives on the seam that owns it
(registration, composition and exit mapping on the engine story; the value/scope matrix on the
check builder). No speed claim is made or implied by this change; the timing outcome appears only
in section 6 under the Verdict vocabulary.

## 3. Assertion-ownership ledger

| Pre-change node id | Observation(s) | Post-change owner |
|---|---|---|
| `test_subagent_bridge_config_default_is_ok` | check present in the engine report; `ok`; group `package`; `"bridge active"` in message | `test_subagent_bridge_config_engine_story` step 1 (adds an explicit `bridge is not None` registration assertion + `report.healthy and report.exit_code == 0`) |
| `test_subagent_bridge_config_project_off_is_warn` | `warn`; `.pi/settings.json` and `"off"` in detail; remediation set; `report.healthy` | `test_subagent_bridge_config_engine_story` step 2 (adds `exit_code == 0`) |
| `test_subagent_bridge_config_project_fork_only_is_warn` | `warn`; `"fork-only"` in detail; `report.healthy` | `test_subagent_bridge_config_project_scope_matrix[fork-only]` (status + the exact offender line); healthy-under-warn is owned by engine-story step 2 plus the pure `test_exit_code_healthy_allows_warnings` |
| `test_subagent_bridge_config_explicit_always_is_ok` | `ok` | `test_subagent_bridge_config_project_scope_matrix[always]` (adds `detail == ""`) |
| `test_subagent_bridge_config_user_scope_off_is_warn` | `warn`; absolute planted path in detail; `report.healthy` | `test_subagent_bridge_config_user_scope_off_is_warn` (direct seam; adds "clean project scope is not named"); healthy-under-warn as above |
| `test_subagent_bridge_config_invalid_settings_stays_quiet` | `ok` on `not json{` | `test_subagent_bridge_config_project_scope_matrix[invalid-json]` (adds `detail == ""`) |
| `test_subagent_bridge_config_user_scope_follows_configured_agent_dir` | unchanged | unchanged |
| `test_subagent_bridge_config_unresolvable_agent_dir_skips_user_scope` | unchanged | unchanged |
| `test_subagent_bridge_config_bad_config_skips_user_scope[...]` ×2 | unchanged | unchanged |
| `test_subagent_worktree_default_*` (10 tests) | deleted upstream at `eb4bd441` with the convergence they tested | N/A — recorded, not migrated |

Absent-file / key-absent defaults stay covered by the engine story's scaffolded-default step; the
matrix carries exactly the four migrated engine cases and adds no equivalence class.

## 4. Fault-injection evidence (F1 — omitted registration)

Precondition met: the test change was committed (`532f0dd0`) and `git status --porcelain` was
empty, so the restore touched nothing else.

- **Mutation:** in `_build_checks` (`src/perk/convergence/doctor/__init__.py`) the single statement
  that appends `_subagent_bridge_config_check(root)` to the check list was deleted — the check
  builder still exists and still behaves; only its registration in the engine's report is gone
  (`git diff --stat`: 1 file, 1 deletion).
- **Command:** `uv run pytest -n0 -q tests/test_doctor.py tests/test_dot_directory_dogfood.py`
- **Result:** `1 failed, 225 passed` (exit 1). Failing node id, verbatim from pytest's summary:
  `FAILED tests/test_doctor.py::test_subagent_bridge_config_engine_story` — at the registration
  assertion (`assert bridge is not None` → `E assert None is not None`,
  `tests/test_doctor.py:1177`), not a `StopIteration`.
- **Direct-seam tests under the fault:** all green — the four matrix rows, the direct user-scope
  case and the three config-arm tests do not own registration, exactly as the ledger says.
- **Restoration:** `git restore src/perk/convergence/doctor/__init__.py`; `git status --porcelain`
  afterwards printed nothing.

F1 discriminates the retained engine story from the direct seam — the one guarantee the refactor
could have lost. The post-fix recheck is untouched by this change and stays guarded by the
unchanged drift/fix stories; no mutation of it was performed.

## 5. Serial cohort before/after

`uv run pytest -n0 -q tests/test_doctor.py -k subagent_bridge_config --durations=0 --durations-min=0`,
three uninstrumented runs per side.

| Side | Collected | Engine runs (`run_doctor` census) | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|---|---|
| baseline `758a59d0` | 10 (215 deselected) | 6 | 2.56 s | 2.51 s | 2.28 s | 2.51 s |
| candidate `532f0dd0` | 10 (215 deselected) | 2 | 1.91 s | 2.72 s | 1.37 s | 1.91 s |

Instrumented cohort census (one in-process run per side under cProfile with a
`subprocess.Popen` audit hook; **counts only**, never compared as time):

| Count | baseline | candidate |
|---|---|---|
| `run_doctor` | 6 | 2 |
| `_build_checks` | 6 | 2 |
| `load_registry` | 18 | 6 |
| `load_providers` | 24 | 10 |
| `safe_load` | 48 | 18 |
| `subprocess.Popen` — `git rev-parse` | 35 | 16 |
| `subprocess.Popen` — `git ls-files` | 6 | 2 |
| `subprocess.Popen` — `git init` / `git add` / `git commit` | 1 / 1 / 1 | 1 / 1 / 1 |
| `subprocess.Popen` — `git config` | 4 | 4 |

The `git init`/`add`/`commit`/`config` processes are the session-scoped scaffolded-repo template
build and are paid once per session regardless of the matrix; the per-check `rev-parse` and
`ls-files` counts fall with the engine-run count.

## 6. Full-suite samples

`/usr/bin/time -p just test-py -q --durations=0 --durations-min=0 -o junit_duration_report=total --junitxml=…`
(the unthresholded durations block is printed on both sides, so its cost is paid equally).

| Sample | HEAD | Exit | Console duration | External `real` | Summed total-phase worker time | Collected | passed / skipped / failed / errors | Shutdown tail | Retained temp (before → after) | Interference notes |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline-1 | `758a59d0` | 0 | 113.35 s | 116.62 s | 604.675 s | 6961 | 6961 / 0 / 0 / 0 | 3.27 s | 4 → 4 | none observed |
| baseline-2 | `758a59d0` | 0 | 103.04 s | 104.78 s | 584.722 s | 6961 | 6961 / 0 / 0 / 0 | 1.74 s | 4 → 4 | none observed |
| baseline-3 | `758a59d0` | 0 | 116.74 s | 137.20 s | 667.418 s | 6961 | 6961 / 0 / 0 / 0 | 20.46 s | 4 → 4 | shutdown tail ~6× the other baselines; cause not attributed (no per-phase instrumentation of shutdown) |
| candidate-1 | `532f0dd0` | 0 | 101.38 s | 103.81 s | 570.458 s | 6961 | 6961 / 0 / 0 / 0 | 2.43 s | 4 → 4 | none observed |
| candidate-2 | `532f0dd0` | 0 | 114.56 s | 122.07 s | 651.205 s | 6961 | 6961 / 0 / 0 / 0 | 7.51 s | 4 → 4 | none observed |
| candidate-3 | `532f0dd0` | 0 | 129.34 s | 136.25 s | 734.174 s | 6961 | 6961 / 0 / 0 / 0 | 6.91 s | 4 → 4 | slowest console duration and largest summed worker time of all six; no operator workload was running — background host activity was not controlled |

Per configuration (median · range):

| Configuration | Console duration | External `real` | Summed worker time | Shutdown tail |
|---|---|---|---|---|
| baseline (n=3) | 113.35 s · 103.04–116.74 s | 116.62 s · 104.78–137.20 s | 604.675 s · 584.722–667.418 s | 3.27 s · 1.74–20.46 s |
| candidate (n=3) | 114.56 s · 101.38–129.34 s | 122.07 s · 103.81–136.25 s | 651.205 s · 570.458–734.174 s | 6.91 s · 2.43–7.51 s |

**Validity gate: passed.** All six samples exited 0 with zero failures and zero errors; the
collected count is 6961 in every sample (identical within and across configurations — the change
keeps the cohort at 10 cases); the skipped count is 0 in all six.

**Verdict: within observed noise.** The rule requires every candidate `real` to fall below every
baseline `real` and the same for console durations; candidate-3 (`real` 136.25 s, console 129.34 s)
exceeds baseline-2 (`real` 104.78 s, console 103.04 s), so neither condition holds. No sample was
discarded. This is consistent with the classification in section 2: the narrowing removed four
engine runs from a cohort whose entire serial run takes ~2 s.

## 7. Reprofile (candidate revision)

Source: the three candidate JUnit XMLs (`junit_duration_report=total`) and the three candidate logs'
unthresholded `--durations` blocks. Parallel samples only — **no per-worker split** (unavailable
from JUnit XML) and **no suite-wide subprocess census** (the section-5 cohort census is the only
process count) were captured; this is a chosen limitation.

### 7a. Per-module ranking — median across the three candidate XMLs of summed total-phase time

Per-sample grand totals: 570.458 s / 651.205 s / 734.174 s; median 651.205 s (the share
denominator). The top 15 modules account for 50.0% of the median summed worker time. All six seed
leads rank inside the top 15.

| Rank | Module | Median summed time | Share | Cases | Per-sample totals (c1 / c2 / c3) | Seed lead? |
|---|---|---|---|---|---|---|
| 1 | `tests/test_doctor.py` | 93.407 s | 14.34% | 225 | 89.718 / 96.686 / 93.407 | — |
| 2 | `tests/test_objective_refine_cmd.py` | 34.587 s | 5.31% | 18 | 18.252 / 34.587 / 39.109 | yes |
| 3 | `tests/test_git.py` | 33.110 s | 5.08% | 93 | 30.536 / 33.110 / 38.493 | yes |
| 4 | `tests/test_launch_restore.py` | 18.707 s | 2.87% | 22 | 16.155 / 18.707 / 21.346 | yes |
| 5 | `tests/test_packaging.py` | 17.347 s | 2.66% | 19 | 13.725 / 17.347 / 26.103 | yes |
| 6 | `tests/test_launch.py` | 14.493 s | 2.23% | 116 | 14.493 / 13.791 / 16.371 | — |
| 7 | `tests/test_delivery_cross_machine.py` | 14.029 s | 2.15% | 7 | 12.059 / 15.468 / 14.029 | — |
| 8 | `tests/test_pr_review_stack_checkout.py` | 14.005 s | 2.15% | 9 | 14.005 / 13.537 / 15.694 | yes |
| 9 | `tests/test_objective_cmd.py` | 13.467 s | 2.07% | 90 | 13.467 / 15.984 / 13.385 | — |
| 10 | `tests/test_plan_watch.py` | 13.121 s | 2.01% | 44 | 10.432 / 13.121 / 14.311 | — |
| 11 | `tests/test_plan_save.py` | 12.907 s | 1.98% | 61 | 12.907 / 13.220 / 12.557 | yes |
| 12 | `tests/test_binding_render_parity.py` | 12.009 s | 1.84% | 1 | 10.873 / 12.009 / 13.895 | — |
| 13 | `tests/test_learn_dream_cmd.py` | 11.893 s | 1.83% | 27 | 11.501 / 11.893 / 14.954 | — |
| 14 | `tests/test_linear_lifecycle.py` | 11.307 s | 1.74% | 28 | 11.047 / 12.055 / 11.307 | — |
| 15 | `tests/test_init_idempotent.py` | 11.225 s | 1.72% | 59 | 10.040 / 11.225 / 12.539 | — |

### 7b. Phase attribution — complete, unthresholded

Every candidate log lists all three phases for all 6961 cases (6961 `setup`, 6961 `call`, 6961
`teardown` lines per log), so a module/phase pair absent from a block would mean "no report", not
censoring — none was absent. Values are per-pair medians across the three logs; **residual** =
XML median total − (setup + call + teardown medians). Teardown rounds to 0.00 s for all but 4–6
lines per log (maximum single teardown 0.06 s), so every module's teardown median is 0.000 s.

| Rank | Module | setup | call | teardown | Sum of phase medians | XML median | Residual | Dominant phase |
|---|---|---|---|---|---|---|---|---|
| 1 | `tests/test_doctor.py` | 21.880 | 71.390 | 0.000 | 93.270 | 93.407 | +0.137 | call |
| 2 | `tests/test_objective_refine_cmd.py` | 0.010 | 34.520 | 0.000 | 34.530 | 34.587 | +0.057 | call |
| 3 | `tests/test_git.py` | 7.320 | 25.680 | 0.000 | 33.000 | 33.110 | +0.110 | call |
| 4 | `tests/test_launch_restore.py` | 4.900 | 13.840 | 0.000 | 18.740 | 18.707 | −0.033 | call |
| 5 | `tests/test_packaging.py` | 6.040 | 13.550 | 0.000 | 19.590 | 17.347 | −2.243 | call |
| 6 | `tests/test_launch.py` | 3.580 | 10.130 | 0.000 | 13.710 | 14.493 | +0.783 | call |
| 7 | `tests/test_delivery_cross_machine.py` | 0.000 | 14.010 | 0.000 | 14.010 | 14.029 | +0.019 | call |
| 8 | `tests/test_pr_review_stack_checkout.py` | 1.830 | 12.620 | 0.000 | 14.450 | 14.005 | −0.445 | call |
| 9 | `tests/test_objective_cmd.py` | 0.050 | 13.180 | 0.000 | 13.230 | 13.467 | +0.237 | call |
| 10 | `tests/test_plan_watch.py` | 8.170 | 4.940 | 0.000 | 13.110 | 13.121 | +0.011 | setup |
| 11 | `tests/test_plan_save.py` | 0.140 | 12.660 | 0.000 | 12.800 | 12.907 | +0.107 | call |
| 12 | `tests/test_binding_render_parity.py` | 0.000 | 12.010 | 0.000 | 12.010 | 12.009 | −0.001 | call |
| 13 | `tests/test_learn_dream_cmd.py` | 0.020 | 11.790 | 0.000 | 11.810 | 11.893 | +0.083 | call |
| 14 | `tests/test_linear_lifecycle.py` | 0.020 | 11.220 | 0.000 | 11.240 | 11.307 | +0.067 | call |
| 15 | `tests/test_init_idempotent.py` | 0.990 | 10.120 | 0.000 | 11.110 | 11.225 | +0.115 | call |

Residuals are near zero except `tests/test_packaging.py` (−2.243 s): its per-sample phase sums do
match its per-sample XML totals (13.670 vs 13.725; 17.310 vs 17.347; 26.060 vs 26.103), but the
setup median comes from candidate-1 (6.040 s) while the call median comes from candidate-2
(13.550 s), so the cross-sample medians do not sum to the median total. The remaining residuals
are the durations block's 0.01 s-per-line rounding (up to 675 lines for `test_doctor.py`).

### 7c. Serial collection time (candidate, once)

`/usr/bin/time -p uv run pytest -n0 --collect-only -q`: `6961 tests collected in 4.21s`; external
`real` 5.18 s (exit 0).

### 7d. Shutdown tails

`real` − console duration, from section 6: baseline 3.27 / 1.74 / 20.46 s; candidate 2.43 / 7.51 /
6.91 s. The tail is the time between pytest's summary line and process exit; what runs there
(xdist worker shutdown, session finalizers, basetemp housekeeping) was not instrumented, so it is
reported but not attributed. The retained-temp count never changed across a sample (4 → 4 in all six), so
basetemp deletion volume did not differ between samples in a way this count can see.

## 8. Ranked follow-up proposals (not authorized by this record)

Rows = the union of the top-15 modules and the six seed leads (all six are inside the top 15, so
15 rows) in ranking order. The candidate intervention is fixed by the dominant phase — `setup` →
"fixture/world reuse (immutable template + per-test copy)"; `call` → "narrow to the owning seam /
remove repeated engine, subprocess or build work"; `teardown` → "temp-dir and cleanup lifecycle" —
and becomes "none proposed" when the share is below 2% of summed worker time. The must-measure
column is fixed by the intervention class. Nothing outside these rules is written here.

| Module | Median summed time · share | Cases | Dominant phase | Candidate intervention | What must be measured before promotion |
|---|---|---|---|---|---|
| `tests/test_doctor.py` | 93.407 s · 14.34% | 225 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_objective_refine_cmd.py` | 34.587 s · 5.31% | 18 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_git.py` | 33.110 s · 5.08% | 93 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_launch_restore.py` | 18.707 s · 2.87% | 22 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_packaging.py` | 17.347 s · 2.66% | 19 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_launch.py` | 14.493 s · 2.23% | 116 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_delivery_cross_machine.py` | 14.029 s · 2.15% | 7 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_pr_review_stack_checkout.py` | 14.005 s · 2.15% | 9 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_objective_cmd.py` | 13.467 s · 2.07% | 90 | call | narrow to the owning seam / remove repeated engine, subprocess or build work | assertion-ownership ledger; engine-story retention; serial cohort before/after |
| `tests/test_plan_watch.py` | 13.121 s · 2.01% | 44 | setup | fixture/world reuse (immutable template + per-test copy) | construction counts per worker; replicated vs grouped setup; copy-isolation proof |
| `tests/test_plan_save.py` | 12.907 s · 1.98% | 61 | call | none proposed | — |
| `tests/test_binding_render_parity.py` | 12.009 s · 1.84% | 1 | call | none proposed | — |
| `tests/test_learn_dream_cmd.py` | 11.893 s · 1.83% | 27 | call | none proposed | — |
| `tests/test_linear_lifecycle.py` | 11.307 s · 1.74% | 28 | call | none proposed | — |
| `tests/test_init_idempotent.py` | 11.225 s · 1.72% | 59 | call | none proposed | — |

## 9. Limitations

- n=3 per configuration; sequential (non-interleaved) sampling — baseline before the first commit,
  candidate after — so the change is confounded with host drift over the ~17-minute window.
- No serial full-suite profile; the reprofile is derived from parallel-run XML and durations
  blocks, which attribute wall time under contention and cannot split cost per worker.
- No suite-wide subprocess census; the only process count is the section-5 cohort census.
- Host noise as observed: one baseline sample carried a 20 s shutdown tail and one candidate
  sample's console duration was 13–28% above the other two candidates; neither was attributed. The host was a developer laptop with
  uncontrolled background activity and no operator-started workload during any sample.
- Per-module shares near the 2% follow-up threshold (`test_plan_watch.py` 2.01%, `test_plan_save.py`
  1.98%) are within sample-to-sample variance; the rule was applied to the medians as recorded.
