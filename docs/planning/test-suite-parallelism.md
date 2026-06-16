# Speed up the pytest and node:test suites with parallelism and file splitting

**Status:** landed (plan #590). Test-infrastructure only — no production code, no cross-plane
(`shared/contracts.md`) change, no user-facing command/tool/config/provider/backend change (so no
`docs/user-docs/` update).

This note records the decisions behind the suite-parallelism work and the measured before/after
wall-clock in its outcomes section.

---

## Decisions

1. **Python: xdist-by-default via `addopts`.** `pytest-xdist>=3.6` is now a dev dep and
   `[tool.pytest.ini_options]` carries `addopts = "-n auto --dist loadgroup"` plus
   `testpaths = ["tests"]`. Every `uv run pytest` (local, `just test`, CI) parallelizes across
   logical CPUs by default. A developer debugs serially by overriding on the CLI: `uv run pytest
   -n0 …` (`-n0` on the command line beats `addopts`). The suite was already xdist-safe — every env
   mutation goes through function-scoped `monkeypatch.setenv`, every `os.chdir` in
   `tests/test_launch.py` is a no-op `monkeypatch.setattr`, and fixtures use `tmp_path` /
   `tmp_path_factory` — so no test races another worker.

2. **`--dist loadgroup` + a shared `xdist_group` to build the wheel once.**
   `tests/test_packaging.py` previously ran a full `uv build --wheel` (180 s timeout) **twice** —
   once per wheel-bundle test. A session-scoped `built_wheel` fixture now builds it once;
   `test_wheel_bundles_shared` and `test_wheel_bundles_agents` both carry
   `@pytest.mark.xdist_group("wheel_build")`, so under `-n auto` they land on a single worker and
   reuse the one build (verified: both run on the same `gwN`). The fixture `pytest.skip`s cleanly
   when `uv` is absent, preserving the prior `skipif` behavior.

3. **JavaScript: file-splitting over intra-file concurrency.** Node's `--test` runner already runs
   each *file* in its own child process and parallelizes across files; tests **within** a file run
   sequentially, so the suite's wall-clock floor is the slowest single file. The two largest
   harness-heavy files built a real (offline) `pi` AgentSession per test and ran them serially.
   Splitting them at their existing `// --- … ---` section boundaries lets Node's cross-file
   parallelism absorb the load. Intra-file `describe({concurrency:true})` was **deliberately
   excluded**: `applyEnv` in `extension/testing/harness.ts` mutates `process.env` process-globally
   and restores on dispose, so concurrent `loadPerkSession` calls in one process would clobber each
   other. Because Node isolates env *per file (process)*, more files is safe; intra-file concurrency
   is not (without a deeper harness env-injection refactor, out of scope here).

   Files split (count-preserving — verified equal `test(` counts before/after):
   - `factories/planSave.test.ts` → `+ planSaveSource.test.ts` (the pure source-resolution / decode
     / `approvalSave` orchestration units).
   - `factories/planReview.test.ts` → `+ planReviewObjective.test.ts` (objective arm + mappers)
     `+ planReviewFirstParty.test.ts` (execute + `runFirstPartyReview` + mappers).
   - `factories/objectivePlan.test.ts` → `+ objectivePlanDecode.test.ts` (reconcile + decode + warm
     node-link + pure units).
   - `checkpoints/checkpoints.test.ts` → `+ checkpointsRoundTrip.test.ts` (live round-trip +
     generated-steps sections).

4. **JavaScript: 2× core oversubscription for `--test-concurrency`.** `test-js` and `test` pass
   `--test-concurrency=$(( $(getconf _NPROCESSORS_ONLN) * 2 ))` (portable on macOS dev + Linux CI).
   Session construction is I/O-bound, so more in-flight files overlap their I/O waits.

## Non-goals (unchanged from the plan)

- Refactoring `harness.ts` to inject env per-session (the prerequisite for intra-file JS
  concurrency).
- Reducing the number of real-session (`loadPerkSession`) tests.
- Splitting the CI workflow into parallel lint/typecheck/test jobs.
- Coverage instrumentation or reporter changes.

---

## Outcomes (measured)

Measured on the dev machine (`getconf _NPROCESSORS_ONLN` = 11 logical CPUs; JS
`--test-concurrency` = 22).

| Suite | Before | After |
| --- | --- | --- |
| `pytest` (Python) | ~70 s serial (`-n0`) | ~18 s (`-n auto --dist loadgroup`) |
| `node --test` (JS) | bounded by the slowest single file | ~35 s (split files + 2× concurrency) |

- **Python:** ~70 s serial → ~18 s under `-n auto` (≈4× on this multi-core box; CI's ~4-core
  `ubuntu-latest` sees a similar near-linear win). `tests/test_packaging.py` builds the wheel
  exactly once — both wheel tests share the `wheel_build` group and land on one worker.
- **JS:** total test count is unchanged (737 tests, all green) — the splits move tests between
  sibling files without dropping or duplicating any. The slowest-file floor drops because the two
  largest harness-heavy files (`planSave`, `planReview`) now run as several independent child
  processes that overlap with the rest of the suite.
- The `2×` oversubscription default held up against measured timings; no adjustment was needed.
- `just ci` is green end-to-end.
