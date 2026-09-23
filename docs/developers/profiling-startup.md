# Profiling perk's startup

This page is a **how-to guide**: how to measure perk's cold startup repeatably with
`perk-dev profile-startup`, how to prepare the checkouts it measures, how to read the run
directory it writes, how the profiled arms work (the Python stop-before-exec seam, cProfile,
`-X importtime`, the Node module census), and how a committed baseline record is produced.

## What the command measures

`perk-dev profile-startup` drives each subject's real `perk` console script through a
pseudo-terminal under Pi's offline startup-benchmark mode (`PI_STARTUP_BENCHMARK=1 PI_TIMING=1
PI_OFFLINE=1`): Pi builds its interactive session, waits 150 ms, stops, prints its startup-timing
report to stderr, and exits — no prompt, no network, no model call. The command spawns one
discarded warm-up per subject, then `--runs` rounds in which every subject runs once (so machine
drift spreads across subjects instead of landing on one), records per-subject provenance, and
writes a run directory with raw samples plus a JSON + Markdown summary. Profiled runs (cProfile,
`-X importtime`, the Node module census) are separate spawns after all timing samples and never
enter the statistics.

## Prerequisites

- `pi` and `node` on `PATH` (`perk-dev profile-startup` refuses `tool_missing` otherwise).
- Each subject is a **prepared** perk checkout:
  - `uv sync --all-packages` inside it — the measured executable is `CHECKOUT/.venv/bin/perk`,
    the console script a user pays for (`uv run` adds resolver/sync overhead nobody pays, so it is
    the provisioning step, never the measured command);
  - `npm ci` inside it — its own `node_modules`, so Node never resolves a sibling checkout's tree by
    walking up;
  - `perk doctor --fix` inside it — converges `.pi/npm` (the consumer extension packages) and the
    skills mirror; a subject without `.pi/npm/node_modules` is refused `subject_not_converged`;
  - run `pi` there once from a terminal and choose **Trust** (then `/quit`). Pi keys its trust
    decision by canonical path in `<agent dir>/trust.json`, nearest ancestor wins; a benchmark
    session cannot answer the prompt, so an untrusted checkout is refused `subject_untrusted`.
    Perk's own worktree launches pass `--approve`, which writes no `trust.json` entry — hence this
    step. `"defaultProjectTrust": "always"` in the agent dir's `settings.json` also satisfies it.
- Run from a **plain shell**, not from inside a perk/Pi session: an operator `NODE_OPTIONS` would
  change both the timings and the module graph, so it is scrubbed from every spawned process and
  recorded as `operator_node_options`; `PERK_RUN_ID` and the two profiling variables are scrubbed
  too. `PI_CODING_AGENT_DIR` is **inherited untouched** (the same posture as perk's own launches)
  and the agent dir each subject resolves to is recorded in its stamp. A session's other `PI_*`
  variables (`PI_SESSION_FILE`, `PI_MODEL`, …) are not scrubbed — another reason to use a plain
  shell.

### Preparing a pinned baseline worktree

To compare a candidate against a fixed revision, materialize the revision as a detached worktree
and prepare it like any subject:

```bash
git worktree add --detach ../perk-baseline <sha>
cd ../perk-baseline
uv sync --all-packages && npm ci && perk doctor --fix
pi        # choose Trust, then /quit
```

## Running it

```bash
perk-dev profile-startup --runs 5 --output /tmp/perk-startup \
  --subject baseline=../perk-baseline --subject candidate=.
```

| Option | Domain | Default | Meaning |
|---|---|---|---|
| `--runs N` | integer ≥ 1 | `5` | timing samples per subject, after one discarded warm-up each |
| `--output DIR` | required; resolved absolute; no `"` character (it is embedded in `NODE_OPTIONS`); created (parents included); must be empty | — | the run directory (`output_not_empty` when it already holds files; a non-directory is `bad_arguments`) |
| `--subject LABEL=CHECKOUT` | repeatable, ≥ 1; label `^[A-Za-z0-9][A-Za-z0-9._-]*$`, unique | — | a prepared checkout |
| `--timeout S` | finite, > 0 | `180` | seconds from spawn to the startup marker before a sample is killed and marked `timed_out` |
| `--exit-grace S` | finite, ≥ 0 | `10` | seconds a process may outlive its startup marker before it is terminated (`SIGTERM`, 2 s, `SIGKILL`) and flagged `lingered` |
| `--pty-size COLSxROWS` | 40 ≤ COLS ≤ 400, 10 ≤ ROWS ≤ 200 | `120x40` | the pseudo-terminal geometry every spawn sees |
| `--no-profiles` | flag | off | skip the profiled arms |
| `--json` | flag | off | print `summary.json`'s exact bytes to stdout (human text stays on stderr) |

Every option-domain violation is a `bad_arguments` refusal naming the option. Per subject, in
order and all before any sample is spawned: a missing checkout or console script is
`subject_missing`; a missing `.pi/npm` install is `subject_not_converged`; `pi`/`node` off `PATH`
is `tool_missing` (once); a checkout that is not a git repository or a failing `--version` probe
is `subject_probe_failed`; no trust is `subject_untrusted`. An `OSError` writing under `--output`
is `io_error` (exit 1; the partial run directory is left in place and named). A **completed** run
exits `0` even when samples failed — the summary reports them, and a `warning:` line names every
subject with zero successful samples.

What a run does, in order: stamp every subject → one warm-up per subject → `--runs` rounds, every
subject in order per round → (unless `--no-profiles`) the profiled arms per subject → write
`summary.json` and `summary.md` (also printed to stderr).

## Reading the run directory

```
meta.json                        schema, started_at, tool {perk_version, perk_dev_head}, host,
                                 options, env {injected, removed, operator_node_options},
                                 pty_size, subjects (in order), schedule
subjects/<label>/stamp.json      head, dirty, perk/pi/node versions, pi_path, packages
                                 (.pi/npm dependency → installed version), sdk_copies,
                                 agent_dir + agent_dir_source, trusted_by
samples/<label>/warmup.json      the discarded first run (+ warmup.stderr.txt)
samples/<label>/<NNN>.json       one timing sample (+ <NNN>.stderr.txt — Pi's raw report)
profiles/<label>/…               the profiled arms (below)
summary.json / summary.md        the machine snapshot / the human rendering
```

The metrics, and what each means:

- `elapsed_ms` — the harness's spawn call → the moment it observes the `TOTAL` line of Pi's
  `main` timing group on stderr. The startup number as a user experiences it: process
  creation/exec, the console script, Node boot, Pi's session being built — plus the harness's own
  read latency (a few ms; stamped in the parent, not inside the child).
- `exit_ms` — the same spawn stamp → the process's natural exit; `null` whenever the harness
  terminated it.
- `pi_main_total_ms` — Pi's own `main` `TOTAL`. Pi's `resetTimings()` runs at its `main()` entry,
  so this excludes everything before it (Python, Node boot, the bundle's evaluation).
- `pre_pi_remainder_ms` — `elapsed_ms − pi_main_total_ms`, a **derived estimate** of everything
  outside Pi's own timing: process spawn/exec, Python (perk) up to the exec handoff, Node boot to
  Pi's `main()`, Pi's fixed 150 ms benchmark settle, and the harness's marker-observation latency.
  Not a measured phase; every surface that prints it says so.
- `first_run` — the warm-up, reported apart and never in the statistics (it pays the filesystem
  cache and Node's compile cache).
- `failed` — the sample timed out, exited non-zero without a parsed `main` group, or never printed
  the `main` group (`failure` names which). Failed samples are excluded from the statistics and
  counted.
- `lingered` — the process outlived `--exit-grace` after its marker and was terminated. A flag,
  not a failure.
- `extension_rows` — the `extensions` timing group verbatim: `<path> module import` / `<path>
  factory` rows, each the delta since the previous row of that namespace (the first row is a real
  measurement from Pi's `resetTimings("extensions")`, never zero by construction).
- `deltas` — present for exactly two subjects: `second − first` over medians, with the percentage
  relative to the first. Reported, never judged: the tool has no verdict vocabulary.

Statistics are `median [min–max] (n ok / n failed)` over successful timing samples.

## The profiled arms

### The Python handoff (`PERK_PROFILE_HANDOFF`)

Perk's one Pi executor `exec_pi` (`perk.run.pi_exec`) ends in `os.execvpe`, so no in-process
profiler survives into Pi. The maintainer-only stop-before-exec seam ([contracts.md §8.72(i)](../../shared/contracts.md))
gives the exact handoff instant: when `PERK_PROFILE_HANDOFF=<file>` is set, `exec_pi` runs every
pre-exec phase, writes `<file>` (`schema`, `handoff_monotonic_ns`, `pid`, `pi_path`, `argv`, `cwd`,
`env_keys` — key names only, never values), prints one stderr line, and exits `0` without exec'ing
pi. **Never set it for a real session** — the session would end before Pi starts.

The harness runs three arms per subject, each with its own record file (unlinked before the
spawn, so a stale record can never stand in for an arm that failed before the seam):

| Arm | Command | Artifacts |
|---|---|---|
| direct | `perk` | `handoff-direct.json`; `handoff_ms` = the record's `handoff_monotonic_ns` minus the harness's spawn stamp (both `CLOCK_MONOTONIC`, system-wide) — the ONLY source of `handoff_ms` |
| cProfile | `python -m cProfile -o cprofile.prof -m perk` | `handoff-cprofile.json`, `cprofile.prof`, `cprofile-top.txt` (top 40 by cumulative) |
| importtime | `python -X importtime -m perk` | `handoff-importtime.json`, `importtime.log`, `importtime-top.txt` (top 30 by cumulative µs) |

`handoff-summary.json` records `handoff_ms` (`null` unless the direct arm is `ok`) and each arm's
`ArmStatus`: `record_present` (the seam's record was written and parses), `output_present` (the
arm's artifact exists **and is usable** — a `cprofile.prof` that pstats can load; an
`importtime.log` holding at least one `import time:` row, the raw stderr being saved as the log
either way; always true for the direct arm), and `status`: `ok` (exit 0, record present, output
present), `no_record` (exit 0 but the seam was never reached), `failed` (a non-zero exit, a
timeout, an unusable artifact, or a spawn that failed outright — `exit_code` is `null` when
nothing was spawned; the remaining arms still run). Explore the cProfile dump interactively:

```bash
python -m pstats /tmp/perk-startup/profiles/candidate/cprofile.prof
% sort cumulative
% stats 40
```

### The Node module census

The census arm spawns bare `perk` once more with `NODE_OPTIONS` composed from an **empty** base:
`--import=<module_tracer.mjs> --cpu-prof --cpu-prof-dir="<dir>"`. The perk-dev-owned tracer
(`packages/perk-dev/src/perk_dev/profile_startup/module_tracer.mjs`) registers a `node:module`
resolve hook (Node ≥ 22.15) and buffers every resolution in memory, flushing one
`node-census/census-<pid>.jsonl` per Node process on exit — children inherit `NODE_OPTIONS`, so
each writes its own file; the main Pi process is the one whose header `argv[1]` is the `pi` bin.
The tracer turns `SIGTERM` into an orderly `process.exit(0)` so a process the harness terminates
after its marker still flushes its census and lets Node write its `cpu-prof/*.cpuprofile`.

`node-census-summary.json` carries a `status` decided in this order: `host_root_unresolved` (no
`@earendil-works/pi-coding-agent` package root above the `pi` bin — the arm is not spawned),
`timed_out`, `failed_exit`, `no_marker`, `no_census_file`, `malformed_census`,
`hooks_unsupported`, else `ok`. For `ok`, `summary` groups the main process's distinct resolved
URLs: `builtin_modules` (`node:`), `host_modules` (under the Pi host root), `by_package` (the
package name after the last `node_modules/` segment; `<unpackaged>` otherwise), and
`sdk_outside_host` / `sdk_outside_host_roots` — the SDK packages that loaded from OUTSIDE the host
root, per package root with its version. That last list is the authoritative provenance of which
duplicate SDK copies a launch actually loaded (the subject stamp's `sdk_copies` only says which are
installed). Modules jiti evaluates itself (perk's own TypeScript extension files) may not appear in
the census — a property of the loader, not a defect.

Under perk's host-SDK bridge (contracts §8.73), `sdk_outside_host_roots` is expected to be
**empty** for a launch whose `/perk-selfcheck` reports `bridge=installed`: the two native consumers'
SDK imports resolve to facades addressed at the host entry, so no SDK module loads from outside the
host root. Those facade resolutions never reach the tracer — the bridge registers its hooks later
than the `--import` tracer, so it runs first and short-circuits them; the tracer sees only the
bridge's pass-throughs. A non-empty list under an installed bridge names an unbridged SDK path
(a `preloaded` consumer, a user-scope install, a specifier outside the census) and is the thing to
diagnose.

Open a `.cpuprofile` in Chrome DevTools (Performance → load profile) or any V8 profile viewer.

## Caveats

- Filesystem cache and machine load dominate run-to-run variance — quit heavy applications, keep
  `--runs` ≥ 5, and read medians with their ranges.
- Node's compile cache (Pi calls `enableCompileCache()`) makes the first run slower — hence the
  discarded warm-up.
- `PI_OFFLINE=1` disables Pi's startup network operations; the numbers describe an offline start.
- Pi's timings start at its `main()` entry, and the harness's stamps start before `Popen` and end
  when it reads the marker; `pre_pi_remainder_ms` is an estimate of the gap between the two, never
  a measured phase.
- Benchmark sessions leave no Pi session file behind (Pi persists a session only after an
  assistant message), though perk's extension mints an in-memory warm run id as on any launch.
- Under `--json`, the progress narration still streams on stderr; only `summary.json`'s bytes
  reach stdout.

## Producing a baseline record

A committed baseline lives in `docs/design/archive/` (the archive location is the status signal).
Numbers are measured at commit time — never transcribed from a plan or an objective:

1. Commit the implementation; confirm `git status --porcelain` is empty and note `git rev-parse
   HEAD`.
2. Prepare the checkout as a subject (above) and run from a plain shell:
   `perk-dev profile-startup --runs 5 --output <dir outside the repo> --subject baseline=<checkout>`.
3. Author the record from the verbatim outputs: a context table (revision, date, host, Pi / Node /
   perk / consumer-package versions, `sdk_copies`, agent dir source, PTY size, N, injected env,
   `operator_node_options`), the verbatim `summary.md`, the census (status, distinct modules, top
   packages, `sdk_outside_host_roots`), the Python handoff (`handoff_ms`, arm statuses, the
   importtime and cProfile tops), the exact reproduction command, a "not committed" note for the
   run directory, and the caveats. Text-only evidence.
4. Land the record as a trailing docs-only commit. Any later source edit → re-measure and
   re-author.
