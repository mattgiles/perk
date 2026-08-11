# Python test performance

Measured on macOS with Python 3.13.9 and pytest 9.0.3. These numbers are diagnostic, not CI
thresholds: subprocess and filesystem timings vary with host load.

## Measurement discipline

Two JUnit views answer different questions:

- `junit_duration_report=call` measures the test body. The tracked
  `test-durations-over-2s*.csv` files are the requested historical round-one call-phase artifacts.
- `junit_duration_report=total` includes setup, call, and teardown. A session fixture paid once for
  many tests is charged to its first consumer, so that consumer is not described as intrinsically
  slow. Total-phase reports are used for cohort and summed-worker-time comparisons; wall time is
  the end-to-end result.

Raw round-two XML and timing logs remain local rather than becoming a machine-specific performance
contract. Every before/after suite comparison used the same xdist distribution mode, and serial
cohort runs were used when process contention could masquerade as intrinsic test cost.

## Round two results

The fresh pre-change baseline was 80.52, 85.70, and 86.41 seconds: an 85.70-second median. Three
non-scanner-contended runs of the selected six-worker configuration were 65.68, 68.10, and 84.04
seconds: a 68.10-second median. That is 17.60 seconds (20.5%) below the fresh baseline while all
4,223 tests pass.

The setup-inclusive profile shows the cross-cutting gain more directly:

| Measurement | Before | After |
|---|---:|---:|
| Full-suite wall median | 85.70 s | 68.10 s |
| Summed total-phase worker time | 873.44 s median | 368.59 s |
| Tests over 2 seconds, total phase | 62 median | 6 |
| Tests over 1 second, total phase | 240 median | 50 |
| Tests over 2 seconds, call phase | — | 4 |

The before total-phase rows are medians of three reports. The after rows are from the final capped
total-phase report. An endpoint-security filesystem scan overlapped two additional samples
(183–193 seconds); they are recorded as invalid host-contention samples and excluded rather than
being attributed to the suite.

### Worker calibration

The host exposes 32 logical CPUs, but this suite is heavy on short Git subprocesses and filesystem
copies. More workers eventually increase contention and shutdown cost.

| Workers | Wall time |
|---|---:|
| 4 | 92.76 s |
| 6 | 68.10 s median |
| 8 | 73.54 s |
| auto (32) | 73.02 s median |

Six workers beat auto by 6.7%, clearing the preselected 5% threshold. The
`pytest_xdist_auto_num_workers` hook therefore caps only `-n auto` at six workers (or the available
CPU count when smaller). Explicit `-n0` and `-n N` invocations still override it.

### What changed

- Per-worker immutable blueprints cover unborn, committed, scaffolded perk, and local-remote Git
  topologies. Every test receives a full `copytree` copy; relative origin URLs keep copied remote
  worlds self-contained. Isolation tests prove refs and pushes do not leak between copies.
- The pre-created remote advance makes `advance_origin()` one push instead of five Git commands.
  Perk-dev changelog/release fixtures reuse specialized snapshots as well.
- Ordinary Doctor assertions use the specific check or migration seam they own. A compact set of
  full-engine, fix/idempotency, CLI, and dot-directory dogfood stories retains integration value.
- Packaging builds wheel and sdist in one `uv build`; PR checkout folds duplicate assertions into
  the real success path; worktree checkout and wipe use plain directories or a synthetic Git facade
  when registration/removal is not the behavior under test.
- Delivery ancestry uses one tri-state `git merge-base --is-ancestor` command. Sync and publish
  fail closed on unknown evidence, while observation preserves `None`. Already-resolved push URLs
  are reused during capability checks.
- Duplicate stacked-positioning and conflict-continuation stories were folded into canonical real
  integrations. Real fetch, merge-base, conflict/continue, atomic push, tag, bare-origin, cleanup,
  and packaging canaries remain.

Targeted serial evidence includes delivery-sync integrations falling from 24.54 to 8.03 seconds
and the combined release/wipe cohort falling from about 27.1 to 16.48 seconds.

## Round one historical result

The first round reduced full `just test-py` wall time from 116.66 to 88.93 seconds while collection
grew from 4,060 to 4,224 tests. It made launch tests hermetic, shared one repository source corpus,
and removed unrelated environment and registry work from init, upgrade-notice, Doctor, and
dot-directory tests. Its call-phase outlier count fell from 46 to 22.
