# Testing perk

This page is a **how-to guide**: how to run perk's Python test suite whole or by tier, how to
pass pytest arguments through `just`, what the full gates actually run, and how to time a tier
honestly.

## The suites and the gates

Regression coverage lives in two framework suites — **pytest** (`tests/`) and **node:test**
(`extension/**/*.test.ts`, `docs/site/src/**/*.test.mjs`). Four entrypoints run the Python suite,
and all four run the **full default Python suite** — every case ordinarily collected from
`tests/`, slow cases included:

- `just test-py` — pytest alone.
- `just test` — pytest, then node:test, then the docs-site check.
- GitHub CI (`.github/workflows/ci.yml`) — `just lint`, `just typecheck`, `just test`.
- perk's in-session `run_ci` — the `[[ci.checks]]` `test-py` row in `.perk/config.toml` runs
  `just test-py` (skipped on the run-all path only when no changed `*.py` file matches its glob).

The perk-dev prose suites (`tests/test_prose_review_*.py`, `tests/test_prose_map*.py`) are a
deliberate opt-in carve-out: `tests/conftest.py` ignores them unless `PERK_PROSE_REVIEW_TESTS=1`,
and `just prose-review-test` sets that variable. They are never part of the default suite or any
gate.

The only submission gate in a perk session is one green **run-all** `run_ci` report (AGENTS.md's
rule). A tier is a focused local selection while iterating — never a substitute for the run-all.

## Recipes

| Command | Selection |
| --- | --- |
| `just test-py` | Full default Python suite, including slow cases |
| `just test-py-fast` | Default cases selected by `-m "not slow"` |
| `just test-py-slow` | Default cases selected by `-m slow` |
| `just test`, GitHub CI, perk's Python gate | Full default Python suite under existing gate scope rules |
| `just prose-review-test` | Existing separately opt-in prose suite |

`test-py-fast` and `test-py-slow` are complementary selections of the same suite: together they
collect exactly what `test-py` collects, and neither is a different regression standard.
`tests/test_pytest_tiers.py` regression-tests this wiring (no marker filter on the full
entrypoints, the complementary quoted expressions on the tier recipes, the config row, and this
guide naming every recipe).

## What `slow` means

`slow` is the one project marker, registered in `pyproject.toml`. It is a **selection** marker —
never a skip, xfail or quarantine. A `slow` case runs in every full gate; the marker only lets
`-m slow` / `-m "not slow"` split the suite into tiers.

A case is marked `slow` when either rule holds:

- **Build cohort** — its fixture closure reaches `built_distributions` (the shared `uv build` of
  the wheel and sdist in `tests/test_packaging.py`).
- **Threshold** — its serially measured own-cost median is ≥ 1.0 s.

The measurement and the marked cohort are recorded in
`docs/design/archive/python-test-suite-speedup-phase3-slow-classification.md`. Marks go on tests
or parameter cases, never on fixtures (pytest rejects marks on fixtures, and a fixture mark would
protect nothing).

Collection is **strict**: `strict_markers = true` plus `--strict-markers` in `addopts` turn a
misspelt mark into a collection error, so a typo can never silently move a case into the fast
tier. (The ini key is what bites on the pinned pytest 9.0.x, where the `addopts` flag alone is
silently ignored — pytest-dev/pytest#14442; the flag keeps the declared `pytest>=8` floor strict.)

`tests/test_packaging.py::test_every_build_consumer_is_slow` proves no fast-selected test reaches
the shared build: it walks the post-deselection session items and fails on any unmarked consumer
of `built_distributions`. It is itself unmarked, so it runs in the full gates and in the fast tier;
the slow tier neither needs nor runs it.

## Passing arguments

Every recipe above ends in `{{args}}`, so extra pytest arguments ride on the end of the pytest
command line after the recipe's own options:

```bash
just test-py-fast -n0                       # serial (no xdist workers) — for debugging
just test-py-fast -n 4                      # an explicit worker count
just test-py-fast -k doctor                 # a simple keyword filter
just test-py-slow --collect-only -q         # see what the slow tier selects
just test-py tests/test_doctor.py           # a file, or a node id
```

One caveat, stated plainly: the justfile does not set `positional-arguments`, so `{{args}}` is
interpolated as one space-joined string and re-split by bash — caller **quoting is not preserved**
through any recipe. For a compound `-k` or `-m` expression, call pytest directly:

```bash
uv run pytest -m 'not slow' -k 'doctor and not story'
```

Never pass `-m` to a tier recipe: pytest keeps the last `-m` it sees, which silently replaces the
tier's own selection.

## Parallelism

`addopts` sets `-n auto --dist loadgroup`, so every recipe runs under pytest-xdist by default.
`tests/conftest.py::pytest_xdist_auto_num_workers` caps `-n auto` at six workers; an explicit
`-n0` / `-n N` on the command line overrides it. `loadgroup` distributes by load except for tests
sharing an `xdist_group` — the build consumers share `xdist_group("wheel_build")`, so they land on
one worker and `uv build` runs once per selecting run.

Running `just test-py-fast` and `just test-py-slow` concurrently in two shells creates two
independent xdist pools (up to twelve workers, two collections, two basetemps). It is **not** an
optimised combined runner and no combined-time benefit is claimed; `just test-py` is the combined
run.

## Timing a tier

The protocol, in brief — it is what the archive records apply, and a measurement that skips a step
is not comparable to them:

1. Start from a clean tree and record `git rev-parse HEAD` and `git status --porcelain` before the
   first sample and after the last.
2. Use a fresh experiment root under `/tmp` that must not already exist (`mkdir` without `-p`);
   never the checkout or a general-purpose directory. Give every sample its own `--basetemp`
   under the root and write `--junitxml` beside it; pass nothing else that alters selection,
   workers or output.
3. Record **both** durations for every sample: the external wall clock around the whole `just …`
   invocation (uv startup, collection, worker spawn and shutdown, basetemp handling) and pytest's
   own reported duration (the `N passed in X.XXs` summary — when the developer has the verdict).
4. Take at least three samples per tier, rotating the tier order across rounds so every tier
   occupies every position once; run nothing else heavy alongside.
5. Report the median and min–max of both durations per tier, and record the revision, dirty
   status, host, tool versions, worker count and any environment overrides
   (`PYTEST_ADDOPTS`, `PERK_PROSE_REVIEW_TESTS`).
6. An invalid series (a non-zero exit, a failing test, a tool-availability skip, an interruption,
   a source edit or an unrelated heavy workload mid-series) is re-run whole in a new root and
   reported as aborted — never patched sample by sample.

Measured results live in the archive records
(`docs/design/archive/python-test-suite-speedup-*.md`), not on this page, so the guide cannot
carry stale numbers. No numerical target ever becomes a CI requirement.
