# Python test performance: hermetic launch tests and shared source scans

Measured on macOS with Python 3.13.9, pytest 9.0.3, and 11 xdist workers. These numbers are
diagnostic, not CI thresholds: subprocess and filesystem timings vary with host load.

## Measurement discipline

The per-test datasets come from JUnit XML generated with
`-o junit_duration_report=call`. Therefore a test's CSV duration is its call phase only; pytest
fixture setup and teardown are not attributed to every consumer. Full-suite wall time remains the
aggregate check that shared fixture work did not merely disappear from the per-test numbers.

The repository text corpus is a session fixture. All consumers share the `source_scan` xdist group,
so its setup runs once on one worker. A controlled serial run measured that setup at 0.55 seconds;
the source-guard calls themselves were at most 0.30 seconds.

## Results

| Measurement | Before | After |
|---|---:|---:|
| Full `just test-py` wall time | 116.66 s | 88.93 s |
| Collected tests | 4,060 | 4,224 |
| Call phases over 2 seconds under xdist | 46 | 22 |
| Original audited node IDs over 2 seconds in the after-only controlled serial rerun | — | 1 of 45 retained |

The final full-suite run passed all 4,224 tests. The wall-clock reduction is 27.73 seconds (23.8%)
despite the larger collected suite. A second post-change run completed in 87.33 seconds, showing the
expected host-load variation without changing the conclusion.

The original cohort's serial rerun completed in 24.54 seconds. Its only remaining call over two
seconds was the real delivery-sync transplantation integration at 3.249 seconds. The accidental
outliers moved much further: the GitHub-error init test fell from 112.70 seconds to 0.22 seconds,
and every audited launch call measured below one second.

## What changed

- Ordinary launch tests explicitly stub extension warming; dedicated warming tests override that
  stub and retain the call-site coverage.
- Environment precedence is tested through a private pure builder. Worktree, setup, materializing,
  Linear, and exec behavior use their narrow phase seams, with real Git retained where Git is the
  assertion.
- Contract, output, and path guards share one tracked-plus-untracked repository corpus. The
  `log_step` guard uses Python AST calls rather than textual matches.
- Init, upgrade-notice, doctor, and dot-directory tests no longer pay unrelated environment,
  registry, or duplicate full-engine work.

The remaining xdist outliers are dominated by intentionally real Git, npm-pack, delivery-sync,
doctor/dogfood, worker-positioning, and CLI integration behavior. Their raw machine-specific data
stays in the local before/after CSVs rather than being committed as a performance contract.
