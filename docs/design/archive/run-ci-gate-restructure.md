# run_ci gate restructure — per-check durations, a de-duplicated docs gate, split tsc rows

A **measurement/evidence** record for the plan branch `plan-2589`. The `run_ci` report gained a
per-check wall-clock duration (`durationMs` on every executed row, rendered `✓ name (12s)`); the
`docs-check` row shrank to its unique work and became the single row that invokes Astro; the
duplicated site coverage moved onto the code rows' globs; the non-Astro `tsc` work was split into
independently globbed rows; the Python `slow` tier was re-swept (its own record:
`python-test-suite-speedup-phase4-slow-reclassification.md`) and the `node:test` suite's per-file
durations were measured. The row restructure's correctness is proven by the wiring tests
(`tests/test_docs_gates.py`), not by speed; the before/after samples below are one sample each and
indicative only.

## 1. Method and scope

| Item | Value |
|---|---|
| Baseline revision | `50cedb2a` — the durations feature landed, rows unchanged; clean tree |
| Host | macOS (Darwin 25.5.0, arm64, Apple M3 Pro, 11 cores), an uncontrolled shared workstation |
| Tools | Python 3.13.9 · pytest 9.0.3 · uv 0.12.3 · node v26.3.0 |

**Driver.** A throwaway Node module (gitignored run scratch, never committed) imports
`runCiChecks` from `extension/delivery/ci.ts` and `loadPerkConfig` from
`extension/substrate/config.ts`, loads the worktree's `[[ci.checks]]`, and runs them with
`only` = every configured row name joined by commas — explicit selection never glob-skips, so the
baseline and after samples run the full row set regardless of the diff. `runCheck` spawns
`bash -lc <command>` through `node:child_process` in the worktree; `persistOutput` writes each
row's full output beside the driver; `observeChangedFiles` is never consulted. It prints each
row's `durationMs` (the new field) and the wall total. The same driver with a fixed changed-file
set and a no-op `runCheck` exercises the glob gate behaviourally (§5).

## 2. Baseline (before the row restructure)

One sample at `50cedb2a`, host load average 17.2 (1 min) at start and 13.2 at the end — other
sessions were running on the host, so this is a contended sample.

| row | exit | duration s |
|---|---|---|
| lint-py | 0 | 6.6 |
| lint-js | 0 | 6.8 |
| typecheck-py | 0 | 7.8 |
| typecheck-js | 0 | 214.4 |
| test-py-fast | 0 | 392.0 |
| test-py-slow | 0 | 298.6 |
| test-js | 0 | 218.6 |
| **docs-check** | 0 | **490.0** |
| changelog-check | 0 | 20.2 |
| **wall** | 0 | **490.1** |

`test-py-fast` reported `7607 passed in 338.68s`; `test-py-slow` reported `23 passed in 119.65s`.
