# Baseline: perk startup at the instrumented revision (`perk-dev profile-startup`, 2026-09)

**Status:** dated evidence record (2026-09) — the first repeatable measurement of perk's cold
startup, produced by the shipped `perk-dev profile-startup` at a clean SHA of the branch that
ships it. It is the reference later startup work compares against; the numbers below are
measured at commit time, never transcribed from the plan or the objective. The measured subject
is the **instrumented** revision: the maintainer-only stop-before-exec arm
(`PERK_PROFILE_HANDOFF`, contracts.md §8.72(i)) is present but inert during the timing samples
(its variable is unset), so the timed launch path is this branch's — no byte-identity claim
against pre-instrumentation `main` is made.

The method and every field's meaning are in [`docs/developers/profiling-startup.md`](../../developers/profiling-startup.md).
The origin of the work is the planning note `docs/planning/perk-slowness.md` (an untracked
maintainer memo behind the "Speed up plain perk startup" objective; untouched here).

## Context

| Field | Value |
|---|---|
| Revision measured | `0e9de38150b73ff2f7ceeb28f1339e64096dfd4a` — `git status --porcelain` empty before the run and after it (`dirty: false` in the stamp) |
| Date | 2026-09-22T18:18:39+00:00 → 2026-09-22T18:19:45+00:00 (UTC) |
| Host | macOS-26.5-arm64-arm-64bit-Mach-O · arm64 · 11 CPUs (Apple M3 Pro, 18 GiB) |
| perk | perk 3.6.0 (`<checkout>/.venv/bin/perk`, the console script) |
| Pi | 0.87.0 — `/Users/mattgiles/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` (the global mise Node install) |
| Node | v26.3.0 |
| Consumer packages (`.pi/npm`) | `@dietrichgebert/ponytail` 4.10.0, `@ff-labs/pi-fff` 0.11.0, `@juicesharp/rpiv-ask-user-question` 2.11.0, `@juicesharp/rpiv-todo` 2.11.0, `@plannotator/pi-extension` 0.27.17, `@tombell/pi-diff` 0.0.4, `@tombell/pi-plan` 0.0.4, `@tombell/pi-status` 0.0.6, `pi-subagents` 0.70.1, `pi-web-access` 0.30.0 |
| `sdk_copies` installed | `@earendil-works/pi-coding-agent` 0.87.0 — `<checkout>/node_modules/@earendil-works/pi-coding-agent`<br>`@earendil-works/pi-tui` 0.87.0 — `<checkout>/node_modules/@earendil-works/pi-tui`<br>`@earendil-works/pi-ai` 0.87.0 — `<checkout>/node_modules/@earendil-works/pi-ai`<br>`@earendil-works/pi-agent-core` 0.87.0 — `<checkout>/node_modules/@earendil-works/pi-agent-core`<br>`typebox` 1.1.38 — `<checkout>/.pi/npm/node_modules/typebox`<br>`typebox` 1.3.27 — `<checkout>/node_modules/typebox` |
| Agent dir | `/Users/mattgiles/dev/github/mattgiles/perk/.pi/agent` (source `config` — the main checkout's `[pi] agent_dir`) · `trusted_by=/Users/mattgiles/dev/github/mattgiles/perk` (Pi's nearest-ancestor trust entry covers the worktree) |
| PTY size | 120x40 |
| N | 5 timing samples after 1 discarded warm-up · timeout 180 s · exit grace 10 s · profiles on |
| Injected env | PI_STARTUP_BENCHMARK=1 PI_TIMING=1 PI_OFFLINE=1 |
| Removed env | PERK_RUN_ID, PERK_PROFILE_HANDOFF, PERK_MODULE_CENSUS_DIR, NODE_OPTIONS |
| `operator_node_options` | `null` (none was set) |
| Tool | perk-dev 3.6.0 @ `0e9de38150b73ff2f7ceeb28f1339e64096dfd4a` (the same checkout) |

The run was launched from inside a perk implement session with the session's own variables
cleared (`env -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u
PI_REASONING_LEVEL -u PI_CODING_AGENT -u PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u
PERK_RUN_ID`), i.e. the plain-shell environment the how-to asks for; with `PI_CODING_AGENT_DIR`
unset the subject resolved its agent dir through the `config` arm, the same store a plain shell
would reach.

## The measurement (verbatim `summary.md`)

````markdown
# perk startup profile

- started 2026-09-22T18:18:39+00:00 · finished 2026-09-22T18:19:45+00:00
- perk-dev 3.6.0 (perk-dev head 0e9de38150b73ff2f7ceeb28f1339e64096dfd4a) · host macOS-26.5-arm64-arm-64bit-Mach-O arm64 · 11 CPUs
- runs 5 per subject (+1 discarded warm-up) · PTY 120x40 · timeout 180 s · exit grace 10 s · profiles on
- injected env: PI_STARTUP_BENCHMARK=1 PI_TIMING=1 PI_OFFLINE=1 · removed: PERK_RUN_ID, PERK_PROFILE_HANDOFF, PERK_MODULE_CENSUS_DIR, NODE_OPTIONS

## subjects

| subject | checkout | revision | dirty | perk | pi | node | agent dir | trust |
|---|---|---|---|---|---|---|---|---|
| baseline | /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488 | 0e9de38150b7 | no | perk 3.6.0 | 0.87.0 | v26.3.0 | /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent (config) | trusted_by=/Users/mattgiles/dev/github/mattgiles/perk |

- baseline SDK copies installed: @earendil-works/pi-coding-agent 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent, @earendil-works/pi-tui 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-tui, @earendil-works/pi-ai 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-ai, @earendil-works/pi-agent-core 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-agent-core, typebox 1.1.38 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/typebox, typebox 1.3.27 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/typebox
- baseline consumer packages: @dietrichgebert/ponytail 4.10.0, @ff-labs/pi-fff 0.11.0, @juicesharp/rpiv-ask-user-question 2.11.0, @juicesharp/rpiv-todo 2.11.0, @plannotator/pi-extension 0.27.17, @tombell/pi-diff 0.0.4, @tombell/pi-plan 0.0.4, @tombell/pi-status 0.0.6, pi-subagents 0.70.1, pi-web-access 0.30.0

## elapsed_ms (the harness's spawn call → Pi's `main` TOTAL line observed on stderr)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 3977.7 [3665.4-4089.8] (5 ok / 0 failed) |

## pi_main_total_ms (Pi's own `main` TOTAL)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 2807.0 [2572.0-2928.0] (5 ok / 0 failed) |

## pre_pi_remainder_ms

_derived estimate: elapsed_ms - Pi's `main` TOTAL = everything outside Pi's own timing: process spawn/exec, Python (perk) up to the exec handoff, Node boot to Pi's `main()`, Pi's fixed 150 ms benchmark settle, and the harness's marker-observation latency_

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 1161.8 [1040.4-1235.8] (5 ok / 0 failed) |

## first run (the warm-up — reported apart, never in the statistics)

| subject | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | failed |
|---|---|---|---|---|
| baseline | 36045.0 | 34847 | 1198.0 | no |

## top 10 extension rows (median ms, successful samples only)

### baseline

| row | median [min-max] (n) |
|---|---|
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-subagents/index.js module import | 1673.0 [1540.0-1768.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/extension/index.ts module import | 219.0 [170.0-230.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@juicesharp/rpiv-todo/index.ts module import | 124.0 [122.0-131.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts module import | 102.0 [99.0-104.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@plannotator/pi-extension module import | 28.0 [28.0-35.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-subagents/index.js factory | 17.0 [15.0-20.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-web-access/dist/index.js module import | 8.0 [8.0-9.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/extension/index.ts factory | 8.0 [7.0-8.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@ff-labs/pi-fff/src/index.ts module import | 7.0 [6.0-8.0] (5) |
| <inline:llama.cpp> factory | 3.0 [3.0-4.0] (5) |

## handoff (Python → Pi, the stop-before-exec seam)

- baseline: handoff_ms 773.6 · direct ok · cprofile ok · importtime ok

## Node module census

- baseline: ok · 3671 distinct modules · 37 builtin · 17 under the host root · SDK modules outside the host root: 2799 · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-coding-agent 201 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-tui (0.87.0) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/typebox (1.1.38) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox (1.3.27) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/typebox (1.3.27)
````

### Per-sample detail

`createAgentSessionRuntime` (Pi's `main` row that contains extension loading) and the
`extensions` group total move together; `interactiveMode.init` and the pre-Pi remainder are
steady. The discarded warm-up paid a cold filesystem cache (the checkout's test suites had just
churned it) and is an order of magnitude slower than every warmed sample — exactly why the first
run is reported apart and never enters the statistics.

| sample | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | exit_ms | createAgentSessionRuntime | interactiveMode.init | extensions TOTAL |
|---|---|---|---|---|---|---|---|
| warmup | 36045.0 | 34847 | 1198.0 | 36058.3 | 32471 | 2348 | 32166 |
| 001 | 4046.8 | 2811 | 1235.8 | 4059.0 | 2307 | 486 | 2253 |
| 002 | 3671.9 | 2572 | 1099.9 | 3682.6 | 2078 | 482 | 2023 |
| 003 | 3665.4 | 2625 | 1040.4 | 3679.9 | 2077 | 534 | 2014 |
| 004 | 3977.7 | 2807 | 1170.7 | 3992.4 | 2260 | 528 | 2194 |
| 005 | 4089.8 | 2928 | 1161.8 | 4103.1 | 2378 | 530 | 2310 |

## The Node module census

Status `ok` · exit 0 · lingered false · marker seen
true · `registerHooks` supported true · main pid 4910 ·
1 census file(s) · CPU profile `CPU.20260922.141942.4910.0.001.cpuprofile`.

| Count | Value |
|---|---|
| distinct resolved modules (main Pi process) | 3671 |
| `node:` builtins | 37 |
| under the Pi host root (`…/@earendil-works/pi-coding-agent/`) | 17 |
| SDK modules loaded OUTSIDE the host root | 2799 |

Top packages by distinct modules (`by_package`):

| package | modules |
|---|---|
| `typebox` | 2004 |
| `@earendil-works/pi-ai` | 356 |
| `pi-subagents` | 258 |
| `yaml` | 216 |
| `@earendil-works/pi-coding-agent` | 201 |
| `@earendil-works/pi-agent-core` | 156 |
| `undici` | 108 |
| `@earendil-works/pi-tui` | 82 |
| `semver` | 46 |
| `diff` | 38 |
| `highlight.js` | 21 |
| `@juicesharp/rpiv-todo` | 14 |
| `parse5` | 14 |
| `@juicesharp/rpiv-ask-user-question` | 12 |
| `grok-mermaid` | 11 |

`sdk_outside_host_roots` — the duplicate-graph evidence. Every SDK package Pi's own bundle
already contains is loaded again from the checkout's `node_modules`, and several of them twice
(the top-level copy AND the copy nested under `node_modules/@earendil-works/pi-coding-agent/`);
TypeBox loads three times, one of them a different minor version (`1.1.38` under `.pi/npm`):

| package | modules | version | root |
|---|---|---|---|
| `@earendil-works/pi-agent-core` | 78 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-agent-core` |
| `@earendil-works/pi-agent-core` | 78 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core` |
| `@earendil-works/pi-ai` | 178 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-ai` |
| `@earendil-works/pi-ai` | 178 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai` |
| `@earendil-works/pi-coding-agent` | 201 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-coding-agent` |
| `@earendil-works/pi-tui` | 41 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui` |
| `@earendil-works/pi-tui` | 41 | 0.87.0 | `<checkout>/node_modules/@earendil-works/pi-tui` |
| `typebox` | 668 | 1.1.38 | `<checkout>/.pi/npm/node_modules/typebox` |
| `typebox` | 668 | 1.3.27 | `<checkout>/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox` |
| `typebox` | 668 | 1.3.27 | `<checkout>/node_modules/typebox` |

The host root contributes only 17 modules because Pi ships as one bundled
`dist/bundle/cli.js`; the 2799 SDK modules outside it are the second (and third) SDK graph
the objective targets.

## The Python handoff

`handoff_ms` **773.6 ms** (the harness's spawn call → the `exec_pi` handoff instant, from the direct arm) · arms: direct `ok` (exit 0) · cprofile `ok` (exit 0) · importtime `ok` (exit 0).

`-X importtime` top 15 by cumulative µs (`importtime-top.txt`):

```
cumulative_us    self_us  module
       640830      14865  perk.cli.cli
       333623        736  perk.cli.commands.doctor
       325297        722  perk.cli.commands.doctor.render
       324576       2027  perk.convergence.doctor
       227952        704  perk.backends.linear
       217925       3649  perk.backends.linear._helpers
       113172        409  perk.cli.commands.objective
        86129        753  perk.convergence.init
        79356        304  perk.cli.commands.objective.stack
        76008       4454  perk.backends.issue_backend
        64398       3132  perk.state.cache
        60717         10  perk.delivery.layer
        60708        332  perk.delivery
        60033        628  perk.backends.linear.client
        57647      17700  perk.delivery.facade
```

cProfile top 15 by cumulative time (`cprofile-top.txt`, `python -m cProfile -o … -m perk` up to
the seam's `SystemExit(0)`):

```

         1867228 function calls (1838598 primitive calls) in 1.242 seconds

   Ordered by: cumulative time
   List reduced from 4117 to 40 due to restriction <40>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1025/1    0.132    0.000    1.244    1.244 {built-in method builtins.exec}
        1    0.000    0.000    1.244    1.244 <frozen runpy>:201(run_module)
        1    0.000    0.000    1.186    1.186 <frozen runpy>:65(_run_code)
        1    0.000    0.000    1.186    1.186 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/__main__.py:1(<module>)
    571/2    0.002    0.000    1.129    0.564 <frozen importlib._bootstrap>:1349(_find_and_load)
    558/2    0.002    0.000    1.129    0.564 <frozen importlib._bootstrap>:1304(_find_and_load_unlocked)
    536/3    0.001    0.000    1.128    0.376 <frozen importlib._bootstrap>:911(_load_unlocked)
    501/3    0.001    0.000    1.128    0.376 <frozen importlib._bootstrap_external>:1021(exec_module)
   1186/7    0.000    0.000    1.127    0.161 <frozen importlib._bootstrap>:480(_call_with_frames_removed)
        1    0.000    0.000    1.082    1.082 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/cli.py:1(<module>)
    97/26    0.000    0.000    0.724    0.028 {built-in method builtins.__import__}
 1054/525    0.001    0.000    0.577    0.001 <frozen importlib._bootstrap>:1390(_handle_fromlist)
        1    0.000    0.000    0.464    0.464 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/commands/doctor/__init__.py:1(<module>)
        1    0.000    0.000    0.458    0.458 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/commands/doctor/render.py:1(<module>)
        1    0.000    0.000    0.456    0.456 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/convergence/doctor/__init__.py:1(<module>)
```

Reading: bare `perk` imports the whole command catalogue before it can open a plain session —
`perk.cli.cli` costs ~0.7 s of the ~0.8 s handoff, with `doctor` (its render + convergence
modules), the Linear backend and the objective/delivery packages the largest subtrees.

## Reproduction

At the revision above, with the checkout prepared as a subject (`uv sync --all-packages`,
`npm ci`, `perk doctor --fix`, trusted in Pi) and from a plain shell:

```bash
perk-dev profile-startup --runs 5 --output "$(mktemp -d)/baseline" \
  --subject baseline=/path/to/the/checkout
```

The run directory (`meta.json`, `subjects/`, `samples/`, `profiles/` with the raw handoff
records, `cprofile.prof`, `importtime.log`, `node-census/census-<pid>.jsonl`,
`cpu-prof/*.cpuprofile`, `summary.json`, `summary.md`) is **not committed** — it is ~7 MB of
host-specific paths and binary profiles; this record carries the text evidence.

## Caveats

- Machine load and filesystem cache dominate the spread. This run's own warm-up measured
  36.0 s against warmed samples of 3.7–4.1 s; an earlier five-sample run of the
  same tool on this branch (at `f23a542d`, the pre-review revision, host otherwise idle) measured
  a median of 6.7 s with a 4.5–6.8 s range, and a one-sample trial taken concurrently with a test
  suite measured 26.4 s (pi-subagents module import alone 23.5 s). Read medians with their ranges,
  and compare only runs taken under the same conditions.
- `elapsed_ms` is stamped by the harness (before `Popen`, until it reads the marker), so it
  includes process creation/exec and a few ms of observation latency; `pre_pi_remainder_ms` is a
  derived estimate of everything outside Pi's own `main` timing — process spawn/exec, Python
  (perk) up to the exec handoff, Node boot to Pi's `main()`, Pi's fixed 150 ms benchmark settle,
  and that observation latency — never a measured phase.
- `PI_OFFLINE=1`: Pi's startup network operations are disabled; the numbers describe an offline
  start.
- The census records what Node's loader resolves; modules jiti evaluates itself (perk's own
  TypeScript extension files) may not appear.
- Pi persists no session file for a benchmark session (it persists only after an assistant
  message); perk's extension mints its in-memory warm run id as on any launch.
- One subject only — the delta block is absent by design; the closing evidence of the objective
  will run two subjects (a pinned baseline worktree at this revision vs the candidate).
