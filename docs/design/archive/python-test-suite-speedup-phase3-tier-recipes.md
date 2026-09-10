# Python test-suite speedup, phase 3 — tier recipes, selection accounting and independent tier benchmarks (Objective #2306, node 3.2)

A **developer-ergonomics / selection** record for the plan branch `plan-2375`: the `test-py-fast`
(`-m "not slow"`) and `test-py-slow` (`-m slow`) recipes added beside the unchanged full `test-py`,
one permanent command-wiring guard, the canonical developer testing guide, and the acceptance
experiments run at the implementation commit. The recipes change nothing the full suite runs, so
there is **no baseline/candidate comparison and no speed claim**; each tier is characterised
independently. The fast-vs-full framing and the verdict rule below were pre-registered in the plan
before any measurement. Compact tables and verbatim lines only; the raw logs, JUnit files, node-id
lists and the throwaway reduction script stayed under `/tmp/perk-phase3b-b06bb524*/` and are not
committed.

## 1. Scope and revisions

| Item | Value |
|---|---|
| Base revision of the plan branch | `f8d6cb38` (main; `git merge-base origin/main HEAD`) |
| Measured candidate | `b06bb524` — the implementation commit (§2); `git status --porcelain` empty before the first command and after the last of every experiment |
| Final HEAD | one docs-only commit on the candidate: this record. `git diff --stat b06bb524..HEAD` names only `docs/design/archive/python-test-suite-speedup-phase3-tier-recipes.md` (verified before submission; any later post-review change is appended to this row with what was re-run) |
| Host | macOS (Darwin 25.5.0, arm64, Apple M3 Pro, 11 cores), an uncontrolled laptop |
| Tools | Python 3.13.9 · pytest 9.0.3 · pytest-xdist 3.8.0 · pluggy 1.6.0 · uv 0.12.3 · node v26.3.0 · npm 11.16.0 · just 1.58.0 · `uv`, `npm`, `node`, `just`, `git` all on PATH |
| User | `id -u` = 502 (not root) |
| Environment | `PERK_PROSE_REVIEW_TESTS` and `PYTEST_ADDOPTS` unset; workers = 6 (the `tests/conftest.py` auto cap on an 11-core host) |
| Experiment roots | `/tmp/perk-phase3b-b06bb524` (series 1, aborted — §4) and `/tmp/perk-phase3b-b06bb524-s2` (series 2, valid); each created with `mkdir` without `-p`, each holding its own `revision`, `porcelain`, `.ids`, `.log`, `.wall`, `.xml`, `.builds`, `exits.txt` and per-sample basetemps; nothing written under the checkout |

No earlier revision was timed: the node changes no test, marker, fixture or pytest configuration,
so a base-revision run would measure the same suite under the same options — there is nothing to
compare against, and the objective's classification for this node forbids a speed claim anyway.

## 2. What changed and how it is classified

**`justfile`.** Two recipes inserted directly after `test-py`:

```
test-py-fast *args:
    uv run pytest -m "not slow" {{args}}

test-py-slow *args:
    uv run pytest -m slow {{args}}
```

`test-py` and `test` are byte-identical to the base; `test`'s pytest line is identical to
`test-py`'s (`uv run pytest {{args}}`). `.github/workflows/ci.yml` still runs `run: just test`;
`.perk/config.toml`'s `[[ci.checks]]` `test-py` row still runs `just test-py` with `glob = "*.py"`.
Neither tier recipe is wired into `[[ci.checks]]`, `ci.yml`, `test` or `ci`. `just --dry-run`
confirmed the interpolation: `just test-py-fast -n0 --collect-only -q` →
`uv run pytest -m "not slow" -n0 --collect-only -q`.

**Guard.** `tests/test_pytest_tiers.py` (new, self-contained: own recipe parser, no import from
another test module, not on the `docs-check` pytest line) collects exactly 4 items, all unmarked:
`test_full_gate_recipes_run_the_whole_python_suite` (no `-m`/`--markexpr` token on the `test-py`
or `test` pytest line, and the two lines identical), `test_tier_recipes_select_complementary_markers`
(the `shlex`-modelled argv is exactly `["uv", "run", "pytest", "-m", "not slow"]` /
`["uv", "run", "pytest", "-m", "slow"]`, each line ending in `{{args}}`),
`test_perk_python_gate_runs_the_full_recipe` (the config row), and
`test_testing_guide_names_every_tier_recipe` (the guide exists, names every recipe, is indexed and
linked from the README). `git diff --stat f8d6cb38..b06bb524 -- tests/` names only
`tests/test_pytest_tiers.py` (120 insertions). Marker *validity* is not mirrored — strict
collection owns it (node 3.1).

Fault check on the clean candidate tree (each edit restored with `git restore justfile`;
porcelain empty before and after):

- `test-py`'s line changed to `uv run pytest -m "not slow" {{args}}` → `1 failed, 3 passed`,
  exactly `test_full_gate_recipes_run_the_whole_python_suite`, message ``just test-py` carries the
  marker filter ['-m'] — that silently narrows every gate built on it (`just test`, GitHub CI,
  run_ci's test-py row)`.
- `test-py-fast`'s expression changed to `-m not slow` (unquoted) → `1 failed, 3 passed`, exactly
  `test_tier_recipes_select_complementary_markers` (argv `[…, '-m', 'not', 'slow']` ≠
  `[…, '-m', 'not slow']`).

**Docs.** `docs/developers/testing.md` (new; the one canonical how-to: suites and gates, the recipe
table, what `slow` means, argument passthrough and its quoting caveat, parallelism and the
separate-pools caveat, the timing protocol — no measurement numbers), one row in
`docs/developers/index.md`, one paragraph in the README's Develop section.

**Deviation from the objective's Phase 3 prose (review decision, recorded for Phase 4).**
`docs/user-docs/how-to/run-ci-in-session.md` is untouched: its step 4 already states that a green
run-all is the definitive full gate and a green subset run points at the run-all, which is the
clarification the objective asks for; a second paragraph would restate it and drift. No
`skills/perk-expert/references/`, `shared/contracts.md`, CHANGELOG, `pyproject.toml`,
`tests/conftest.py`, marker, fixture or `src/**` change.

**Classification: developer-ergonomics / selection.**

## 3. Selection and outcome accounting

Serial collection **through the recipes** (`just <recipe> -n0 --collect-only -q`, node-id lines
sorted), identical in both roots at `b06bb524`:

| Recipe | Collected | Check |
|---|---|---|
| `just test-py` | 7013 | — |
| `just test-py-fast` | 6998 | `tests/test_packaging.py::test_every_build_consumer_is_slow` present (1); `tests/test_pytest_tiers.py` items present (4) |
| `just test-py-slow` | 15 | the node-3.1 cohort exactly (ten `test_packaging.py` build consumers + the five threshold cases); no `test_pytest_tiers.py` item |

`comm -12 fast.ids slow.ids` → 0 lines (`fast ∩ slow = ∅`); `sort -u fast.ids slow.ids` equals
`full.ids` byte-for-byte (`fast ∪ slow = full`). The pre-change count was not measured at the base
revision: the diff-stat above proves the node adds exactly one collected module, whose own count is
4, so 7013 − 4 = 7009 is the base's collected count by construction.

Per-sample JUnit totals (xdist writes one file from the controller), valid series 2 — every sample
of every tier:

| Tier | tests | passed | skipped | failures | errors |
|---|---|---|---|---|---|
| full (×3) | 7013 | 7013 | 0 | 0 | 0 |
| fast (×3) | 6998 | 6998 | 0 | 0 | 0 |
| slow (×3) | 15 | 15 | 0 | 0 | 0 |

Reconciliation in every round: passed 7013 = 6998 + 15; skipped 0 = 0 + 0. Skip sets as
(node id, reason) pairs: `skipped_full = skipped_fast = skipped_slow = ∅`, so
`skipped_full = skipped_fast ∪ skipped_slow` and `skipped_fast ∩ skipped_slow = ∅` hold trivially —
the expected outcome on this host (non-root, POSIX, every gating tool present), reported as
observed. The eight completed samples of aborted series 1 showed the same totals.

Tool availability: `uv` ✓ · `npm` ✓ · `node` ✓ (so `built_distributions`, the `npm pack` test, the
three `node`-gated tests and `test_perk_dev_bump.py` all ran); `os.geteuid()` ≠ 0 and `fcntl`
present (so the root- and POSIX-gated tests ran). No skip reason of any family appeared.

Shared-build census per basetemp (`find "$bt" -maxdepth 2 -type d -name 'distribution_build*'`),
series 2:

| Tier | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| full | 1 (`popen-gw3`) | 1 (`popen-gw1`) | 1 (`popen-gw0`) |
| fast | 0 | 0 | 0 |
| slow | 1 (`popen-gw1`) | 1 (`popen-gw3`) | 1 (`popen-gw1`) |

Exactly one `uv build` per full and per slow run, hosted by whichever worker xdist's `loadgroup`
handed the `wheel_build` group; zero in every fast run (the guard in the fast set is green, so no
fast-selected case reached the fixture). Series 1's eight completed samples matched (full 1 / slow
1 / fast 0).

## 4. Independent tier benchmarks

**Protocol.** One series = three rounds with the tier order rotated so each tier occupies each
position exactly once (round 1: full, fast, slow; round 2: fast, slow, full; round 3: slow, full,
fast), all sequential, no warm-up, no other workload; every sample gets a fresh `--basetemp` and its
own `--junitxml` under the root and nothing else is passed; the external wall clock (`bash`'s
`time`, `TIMEFORMAT="wall %R"`) wraps the whole `just <recipe> …` invocation; pytest's reported
duration is the trailing `N passed in X.XXs` summary line. Validity (pre-registered): all nine
samples exit 0 with zero failures/errors and no tool-availability skip; anything else aborts the
whole series and a complete new series runs in a new root.

**Series attempted: 2 — 1 aborted, 1 valid.**

- **Series 1** (`/tmp/perk-phase3b-b06bb524`, started 14:30:19Z) — **aborted** during the ninth
  sample: the foreground session command hosting the series was interrupted (a user-side abort of
  the long-running tool call, not a test failure), which killed `fast` round 3 mid-run. Eight
  samples had completed, all exit 0 with zero failures/errors/skips and the §3 census intact:
  full 121.69 / 177.37 / 103.27 s wall (pytest 120.52 / 175.63 / 102.30 s), fast 101.94 / 99.21 s
  (98.85 / 98.25 s), slow 17.37 / 15.77 / 15.82 s (15.60 / 14.10 / 14.15 s). Recorded for
  transparency only; no medians were taken from it and no sample was carried over.
- **Series 2** (`/tmp/perk-phase3b-b06bb524-s2`, 14:43:21Z – 14:55:52Z) — **valid**; run detached
  from the session's foreground so an interruption could not recur. It started with the host's
  load average still elevated from series 1 (`uptime`: 12.20 / 18.48 / 14.57 at launch), which is
  visible in round 1.

Per-sample results, series 2 (`tail` = wall − pytest; every sample exit 0, 0 skipped, 0 failed,
0 errors):

| Tier | Round | Position | pytest s | wall s | tail s | collected = passed |
|---|---|---|---|---|---|---|
| full | 1 | 1 | 138.63 | 139.60 | 0.97 | 7013 |
| fast | 1 | 2 | 127.49 | 130.38 | 2.89 | 6998 |
| slow | 1 | 3 | 20.63 | 24.05 | 3.42 | 15 |
| fast | 2 | 1 | 102.76 | 103.65 | 0.89 | 6998 |
| slow | 2 | 2 | 7.93 | 8.59 | 0.66 | 15 |
| full | 2 | 3 | 104.23 | 105.10 | 0.87 | 7013 |
| slow | 3 | 1 | 7.47 | 8.20 | 0.73 | 15 |
| full | 3 | 2 | 115.78 | 116.78 | 1.00 | 7013 |
| fast | 3 | 3 | 113.11 | 114.16 | 1.05 | 6998 |

Per tier (median, min–max):

| Tier | Focused-feedback time (pytest-reported) s | Complete process-exit time (external wall) s | Tail median s |
|---|---|---|---|
| full | 115.78 (104.23–138.63) | 116.78 (105.10–139.60) | 0.97 |
| fast | 113.11 (102.76–127.49) | 114.16 (103.65–130.38) | 1.05 |
| slow | 7.93 (7.47–20.63) | 8.59 (8.20–24.05) | 0.73 |

**Verdict rule, applied verbatim to external wall time of the valid series.** `full_min` = 105.10,
`full_max` = 139.60, `fast_med` = 114.16, `fast_max` = 130.38. `fast_med ≥ full_min` (114.16 ≥
105.10) → **"within observed noise"**. This matches the pre-registered qualitative expectation
(overlapping fast and full ranges). No derived number was used as a yardstick; the plan's ≈ 30
worker-second estimate of the slow cohort's own cost is not a wall-time bound and was not consulted.

**The slow tier on its own.** Focused-feedback median 7.93 s (7.47–20.63) and process-exit median
8.59 s (8.20–24.05) for the fifteen-case cohort; round 1 (20.63 / 24.05 s) is the host-contention
outlier named above and stays in the table. For anyone iterating on the packaging or integration
cases this is the useful number: a complete verdict on the whole slow cohort in under ten seconds
on a quiet host.

## 5. Observations and limitations

- **Sampling.** n = 3 per tier from one valid order-rotated sequential series on an uncontrolled
  laptop. Round 1 of series 2 is the maximum in every tier (full 139.60, fast 130.38, slow 24.05 s
  wall) — the host was still shedding load from the aborted series; the medians come from rounds 2
  and 3 in every tier.
- **What the wall figure includes.** `just` + `uv run` startup, collection, xdist worker spawn and
  shutdown and basetemp handling; the tail column (median ≈ 1 s per tier, 2.9–3.4 s under the
  round-1 contention) separates it from pytest's own duration.
- **The fast tier is a selection, not a speedup.** Its wall range overlaps the full tier's — consistent
  with (not proven by) the fifteen slow cases riding along on one `wheel_build`-pinned worker while
  the other five drain the remaining 6998 cases. The recipe's value is the
  *complementary* slow tier — a sub-ten-second verdict on the build/integration cohort — and a
  cleanly named way to exclude it while iterating, never a shorter path to the gate.
- **Separate pools.** Running `test-py-fast` and `test-py-slow` concurrently creates two independent
  xdist pools, two collections and two basetemps; no combined-time benefit is claimed and none was
  measured. `just test-py` is the combined run.
- **`docs/learned/toolchain/test-parallelism.md`** still says xdist needed "no justfile change" and
  does not mention the tier recipes or strict markers — under-describes after this node; routed to
  the `/learn` pass (learned docs are never authored ad hoc).
- **For Phase 4.** The consolidated closeout consumes: collected 7013 = 6998 + 15 at `b06bb524`;
  the per-tier medians above; the run-ci how-to deviation in §2; the pre-registered verdict
  ("within observed noise", expectation met); and the reminder that no numerical target here ever
  becomes a CI requirement.
