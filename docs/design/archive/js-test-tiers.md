# node:test tiers — the slow list behind the in-session gate's fast JS row

A **measurement/evidence** record. A run-all `run_ci` on the objective-2656 worker-accounting
branch was stopped by the operator after **1,267 s** in the `test-js` row (2,191 of 3,707 cases
done; `docs-check` and `typecheck-js` ran beside it), against a five-minute budget for the whole
report. The fix this record backs: the in-session `test-js` row now runs only a **fast tier**
(`just test-js-fast`), and a measured **slow tier** (`just test-js-slow`) runs in `just test-js` /
`just test` / GitHub CI and ad hoc. The wiring is pinned by `extension/testing/jsTestTiers.test.ts`;
the how-to is `docs/developers/testing.md` § "The node:test tiers".

## Method

One full-suite run of the `test-js` recipe's exact command (`--test-concurrency` = 2 × 11 cores)
with a throwaway reporter yielding `<file>\t<duration_ms>` per `test:summary` event that carries a
`file` (the `run-ci-gate-restructure.md` §4 method), started at host load 1.9 and ending near 6.
Wall **266 s**, 205 files, sum of per-file walls **3,047 s**. One sample — the ranking matters, not
the seconds; the run-ci-gate record's three samples ranked the same files at the top.

## Selection

Threshold: a file's own wall ≥ **20 s**. 36 files qualify and carry **2,773 s** of the 3,047 s
(91 %); the 169 remaining files sum to 274 s, the slowest at 18.6 s. Thresholds considered:

| threshold | slow files (sum) | fast files (sum, slowest) |
|---|---|---|
| 15 s | 39 (2,827 s) | 166 (221 s, 13.3 s) |
| 20 s | 36 (2,773 s) | 169 (274 s, 18.6 s) |
| 25 s | 33 (2,708 s) | 172 (339 s, 23.6 s) |
| 30 s | 30 (2,627 s) | 175 (421 s, 28.0 s) |

The slow files are dominated by waiting, not JavaScript: `librarian.test.ts` alone, uncontended,
takes 53.6 s of wall on 13.5 s of user + system CPU (real Pi sessions over freshly initialized git
repositories per case).

Result: `just test-js-fast` (169 files + the new guard) ran in **53.6 s** wall at host load 2.6.

## The slow tier (seconds, full-suite run)

| file | s |
|---|---|
| `extension/pi/v1/librarian.test.ts` | 205.8 |
| `extension/pi/v1/delivery/commitCompact.test.ts` | 184.3 |
| `extension/pi/v1/objectiveRefinement.test.ts` | 177.0 |
| `extension/substrate/git.test.ts` | 163.5 |
| `extension/pi/v1/codeReview/terminal.test.ts` | 155.2 |
| `extension/pi/v1/objectiveReviewBrowser.test.ts` | 154.0 |
| `extension/pi/v1/planReviewBrowser.test.ts` | 144.9 |
| `extension/pi/v1/delivery/submit.test.ts` | 124.9 |
| `extension/session/saveDestination.test.ts` | 121.4 |
| `extension/pi/v1/delivery/conflictResolverEngine.test.ts` | 115.7 |
| `extension/pi/v1/objectiveAuthoring.test.ts` | 109.0 |
| `extension/pi/v1/objectiveDreamGate.test.ts` | 99.2 |
| `extension/pi/v1/plan.test.ts` | 83.9 |
| `extension/worker/stageExecutionE2e.test.ts` | 77.2 |
| `extension/substrate/config.test.ts` | 75.0 |
| `extension/pi/v1/planReview.test.ts` | 66.2 |
| `extension/pi/v1/objectivePlanning.test.ts` | 60.8 |
| `extension/substrate/worktreeResolverLock.test.ts` | 57.4 |
| `extension/pi/v1/waveIsolation.test.ts` | 47.1 |
| `extension/pi/v1/lifecycleGates.test.ts` | 45.9 |
| `extension/pi/v1/learning/learn.test.ts` | 45.6 |
| `extension/pi/v1/codeReview/automated.test.ts` | 39.7 |
| `extension/pi/v1/delivery/address.test.ts` | 39.3 |
| `extension/pi/v1/gist.test.ts` | 35.6 |
| `extension/pi/v1/delivery/submitConflict.test.ts` | 35.2 |
| `extension/pi/v1/draftReviewWaveTools.test.ts` | 33.9 |
| `extension/pi/v1/delivery/ready.test.ts` | 33.7 |
| `extension/pi/v1/delivery/stackSyncNative.test.ts` | 32.8 |
| `extension/pi/v1/codeReview/stack.test.ts` | 31.5 |
| `extension/pi/v1/codeReview/browser.test.ts` | 30.8 |
| `extension/substrate/sessionPointers.test.ts` | 28.0 |
| `extension/substrate/discoveryPilot.test.ts` | 27.8 |
| `extension/pi/v1/delivery/land.test.ts` | 26.1 |
| `extension/pi/v1/learning/dream.test.ts` | 23.6 |
| `extension/runSessionRecord.test.ts` | 21.1 |
| `extension/pi/v1/delivery/stackSync.test.ts` | 20.1 |
