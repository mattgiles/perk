# run_ci gate restructure — per-check durations, a de-duplicated docs gate, split tsc rows

A **measurement/evidence** record for the plan branch `plan-2589`. The `run_ci` report gained a
per-check wall-clock duration (`durationMs` on every executed row, rendered `✓ name (12s)`); the
`docs-check` row shrank to its unique work and became the single row that invokes Astro; the
duplicated site coverage moved onto the code rows' globs; the non-Astro `tsc` work was split into
independently globbed rows; the Python `slow` tier was re-swept (its own record:
`python-test-suite-speedup-phase4-slow-reclassification.md`) and the `node:test` suite's per-file
durations were measured (no file was split — §4). The row restructure's correctness is proven by
the wiring tests (`tests/test_docs_gates.py`), not by speed; the before/after samples below are one
sample each and indicative only.

## 1. Method and scope

| Item | Value |
|---|---|
| Baseline revision | `50cedb2a` — the durations feature landed, rows unchanged; clean tree |
| After revision | `a6b73669` — the row restructure (`ba1b4ed5`) and the slow re-sweep landed; clean tree |
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
set and a no-op `runCheck` exercises the glob gate behaviourally (§3).

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

## 3. Coverage invariant (the docs-gate de-duplication)

Every gate surface still runs at least once for every changed-file class it guards — with one
named exception, the site typecheck's reach into `extension/` (§6):

| surface | before | after |
|---|---|---|
| `biome check docs/site` | lint-js + docs-check | lint-js (glob gains `docs/site/**`, `biome.json`) |
| `astro sync && tsc` (docs/site) | typecheck-js **and** docs-check, concurrently (a latent content-sync race) | docs-check only, serially before the build — no other row invokes Astro |
| `docs/site/src/**/*.test.mjs` | test-js + docs-check | test-js (glob gains `docs/site/**`); the two corpus-reading tests (`sidebar.test.mjs`, `in-session-reference.test.mjs`) also run inside the site `check` script, so a user-docs-only change reaches them via docs-check |
| docs-scoped pytest | test-py-fast + docs-check | unchanged (docs-check keeps it, now `-n0`; 77 cases) |
| `astro build` + post-build checks | docs-check | docs-check |
| root `tsc` (`extension` + `tools`) | typecheck-js (`just typecheck-js`, three serial `tsc`) | typecheck-js → `npm run typecheck` (glob `extension/**,tools/**,tsconfig.json,package*.json`) |
| prose-review `tsc` | typecheck-js | typecheck-prose-review → `npm run prose-review:typecheck` (glob `tools/prose-review/**,package*.json`) |

`tests/test_docs_gates.py` pins each row: the single-Astro-owner guard walks every row's command
(and, for `just` rows, the recipe body and its prerequisites) and requires exactly `docs-check` to
reach a docs-site script; the coverage-transfer and row→script assertions pin the globs and
commands above; the union assertion requires every `npm run` script the `typecheck-js` recipe
aggregates to be reached by a row (the site typecheck through `docs-check`). `just typecheck` and
`just test` — what GitHub CI runs — are unchanged, and `just --list` is byte-identical.

**Glob gating, behaviourally.** The §1 driver with a fixed changed set and a no-op `runCheck`
(rows executed for each single changed file, everything else skipped):

| changed file | executed rows |
|---|---|
| `docs/user-docs/how-to/run-ci-in-session.md` | docs-check |
| `extension/delivery/ci.ts` | lint-js, typecheck-js, test-js |
| `docs/site/src/sidebar.mjs` | lint-js, test-js, docs-check |
| `docs/site/tokens.css` | lint-js, test-js, docs-check |
| `tools/prose-review/src/main.tsx` | lint-js, typecheck-js, typecheck-prose-review, test-js |
| `biome.json` | lint-js |
| `package-lock.json` | typecheck-js, typecheck-prose-review, test-js, docs-check |

In every case Astro runs at most once (only `docs-check` reaches it). `just docs-check` standalone
at `ba1b4ed5`: exit 0 in 90 s — the pytest summary (`77 passed`), the `astro sync`/`tsc` output,
and the `docs:check` output (`tests 28`, `pass 28`); no biome or site unit-test lines.

## 4. node:test per-file durations

Node's reporters print no aggregate duration per successful test file, so a throwaway reporter
(an `.mjs` async generator under a `/tmp` root, never committed) emitted one `<file>\t<duration_ms>`
line per `test:summary` event carrying a `file` and ignored everything else. It was validated once
by running the `test-js` recipe's exact command with it in place of `dot`: 187 lines, exactly the
187 files the recipe's three globs match (compared against `fs.globSync` and `find`). Then three
detached runs at `a6b73669` (all exit 0; walls 178 / 174 / 177 s; host load 3.7–5.8; HEAD unchanged
and the tree clean throughout). Top 20 by median (seconds, min–max):

| # | file | median s (min–max) |
|---|---|---|
| 1 | `extension/pi/v1/delivery/commitCompact.test.ts` | 152.9 (152.3–154.8) |
| 2 | `extension/pi/v1/objectiveRefinement.test.ts` | 145.0 (142.0–145.6) |
| 3 | `extension/pi/v1/objectiveReviewBrowser.test.ts` | 126.1 (125.3–128.4) |
| 4 | `extension/pi/v1/codeReview/terminal.test.ts` | 122.9 (121.7–124.3) |
| 5 | `extension/pi/v1/planReviewBrowser.test.ts` | 114.8 (114.6–116.2) |
| 6 | `extension/pi/v1/delivery/submit.test.ts` | 111.4 (111.1–111.7) |
| 7 | `extension/substrate/git.test.ts` | 107.9 (105.5–108.7) |
| 8 | `extension/pi/v1/delivery/conflictResolverEngine.test.ts` | 102.4 (102.0–107.6) |
| 9 | `extension/session/saveDestination.test.ts` | 102.0 (102.0–102.9) |
| 10 | `extension/pi/v1/objectiveAuthoring.test.ts` | 95.2 (93.3–95.2) |
| 11 | `extension/pi/v1/objectiveDreamGate.test.ts` | 83.1 (82.2–84.5) |
| 12 | `extension/substrate/config.test.ts` | 70.1 (69.2–71.2) |
| 13 | `extension/pi/v1/plan.test.ts` | 63.5 (62.1–63.8) |
| 14 | `extension/substrate/worktreeResolverLock.test.ts` | 59.0 (58.2–59.5) |
| 15 | `extension/pi/v1/planReview.test.ts` | 56.5 (56.4–58.1) |
| 16 | `extension/pi/v1/objectivePlanning.test.ts` | 53.0 (51.9–55.8) |
| 17 | `extension/pi/v1/waveIsolation.test.ts` | 41.1 (40.6–41.6) |
| 18 | `extension/pi/v1/codeReview/automated.test.ts` | 37.9 (37.0–39.1) |
| 19 | `extension/pi/v1/delivery/address.test.ts` | 37.8 (36.4–38.0) |
| 20 | `extension/pi/v1/delivery/ready.test.ts` | 36.5 (36.2–36.7) |

Three more files exceed 30 s (`extension/worker/stageExecutionE2e.test.ts` 33.4,
`extension/pi/v1/learning/learn.test.ts` 32.9, `extension/pi/v1/lifecycleGates.test.ts` 30.6) —
23 of 187 in all. The sum of the 187 medians is 2,272 s.

**Split decision: none.** The plan's rule was to split every file over 30 s; with 23 files over
the line (10 over 90 s), the operator chose to record the table and defer the splits: splitting 23
hot `pi/v1` test files invites merge conflicts with in-flight plans, and the `test-js` row is not
the `run_ci` long pole (the Python fast tier is — §5), so the splits would not move the run-all wall
time. The table above is the input for that follow-up. Two observations for it: the per-file
durations are stable to within a few percent across runs, and `saveDestination.test.ts` run alone
(uncontended) takes 28.5 s of wall time on 3 s of user CPU — that file, at least, is dominated by
waiting on git subprocesses rather than JavaScript work (the other files were not profiled).

## 5. After (the restructured rows)

One sample at `a6b73669`, same driver, same host. Host load average 1.9 (1 min) at start, 23.5 at
the end — the host was again shared, so this is also a contended sample.

| row | exit | duration s |
|---|---|---|
| lint-py | 0 | 1.1 |
| lint-js | 0 | 8.6 |
| typecheck-py | 0 | 5.7 |
| typecheck-js | 0 | 53.1 |
| typecheck-prose-review | 0 | 21.2 |
| **test-py-fast** | 0 | **244.2** |
| test-py-slow | 0 | 149.1 |
| test-js | 0 | 156.6 |
| docs-check | 0 | 227.6 |
| changelog-check | 0 | 12.5 |
| **wall** | 0 | **244.2** |

`test-py-fast` reported `7553 passed in 236.21s`; `test-py-slow` reported `80 passed in 141.20s`;
the docs pytest line reported `77 passed in 7.89s`. One sample each, before and after, on a shared
host whose load differed between them — indicative only. What the pair does show structurally:
the long pole moved from `docs-check` (490 s, last to finish) to `test-py-fast`, and the typecheck
work that ran as one 214 s serial row now runs as a 53 s row and a 21 s row, with the site
typecheck inside `docs-check`.

## 6. Residuals

- **The live `(Ns)` rendering was not observed in-session.** This session's loaded extension
  predates the durations feature, so its own `run_ci` reports carry no suffix; the rendering is
  proven by unit tests (`extension/delivery/ci.test.ts`, `extension/pi/v1/delivery/ci.test.ts`)
  and by the driver above reading `durationMs` from the feature. The first fresh perk session after
  merge observes it.
- **The docs-site `tsc` program reaches into `extension/`.** Under Astro's `allowJs`, the site's
  `.mjs` tests import extension modules (`registry.ts`, `toolGating.ts`, the test harness), which
  pulls 168 `extension/` files into the site typecheck under Astro's strict config. An
  extension-only change no longer runs that program in-session (only `docs-check` does, on its
  docs-scoped glob); GitHub CI's `just typecheck` still does, and the root `tsc` — stricter on the
  shared files (`noUncheckedIndexedAccess`, `noUnused*`) — runs for every such change. What
  remains uncovered in-session is only a failure specific to Astro's differing compiler options.
- **node splits deferred** (§4), and the concurrency knobs (xdist caps, `--test-concurrency`,
  runner scheduling) were deliberately untouched.
