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
| Revision measured | `f23a542d54dea8fdeada9dcd114b192706ecad12` — `git status --porcelain` empty before the run and after it (`dirty: false` in the stamp) |
| Date | 2026-09-22T16:39:28+00:00 → 2026-09-22T16:40:15+00:00 (UTC) |
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
| Tool | perk-dev 3.6.0 @ `f23a542d54dea8fdeada9dcd114b192706ecad12` (the same checkout) |

The run was launched from inside a perk implement session with the session's own variables
cleared (`env -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u
PI_REASONING_LEVEL -u PI_CODING_AGENT -u PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u
PERK_RUN_ID`), i.e. the plain-shell environment the how-to asks for; with `PI_CODING_AGENT_DIR`
unset the subject resolved its agent dir through the `config` arm, the same store a plain shell
would reach.

## The measurement (verbatim `summary.md`)

````markdown
# perk startup profile

- started 2026-09-22T16:39:28+00:00 · finished 2026-09-22T16:40:15+00:00
- perk-dev 3.6.0 (perk-dev head f23a542d54dea8fdeada9dcd114b192706ecad12) · host macOS-26.5-arm64-arm-64bit-Mach-O arm64 · 11 CPUs
- runs 5 per subject (+1 discarded warm-up) · PTY 120x40 · timeout 180 s · exit grace 10 s · profiles on
- injected env: PI_STARTUP_BENCHMARK=1 PI_TIMING=1 PI_OFFLINE=1 · removed: PERK_RUN_ID, PERK_PROFILE_HANDOFF, PERK_MODULE_CENSUS_DIR, NODE_OPTIONS

## subjects

| subject | checkout | revision | dirty | perk | pi | node | agent dir | trust |
|---|---|---|---|---|---|---|---|---|
| baseline | /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488 | f23a542d54de | no | perk 3.6.0 | 0.87.0 | v26.3.0 | /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent (config) | trusted_by=/Users/mattgiles/dev/github/mattgiles/perk |

- baseline SDK copies installed: @earendil-works/pi-coding-agent 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent, @earendil-works/pi-tui 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-tui, @earendil-works/pi-ai 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-ai, @earendil-works/pi-agent-core 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-agent-core, typebox 1.1.38 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/typebox, typebox 1.3.27 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/typebox
- baseline consumer packages: @dietrichgebert/ponytail 4.10.0, @ff-labs/pi-fff 0.11.0, @juicesharp/rpiv-ask-user-question 2.11.0, @juicesharp/rpiv-todo 2.11.0, @plannotator/pi-extension 0.27.17, @tombell/pi-diff 0.0.4, @tombell/pi-plan 0.0.4, @tombell/pi-status 0.0.6, pi-subagents 0.70.1, pi-web-access 0.30.0

## elapsed_ms (spawn → Pi's `main` TOTAL line)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 6667.2 [4479.0-6820.4] (5 ok / 0 failed) |

## pi_main_total_ms (Pi's own `main` TOTAL)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 5366.0 [3244.0-5562.0] (5 ok / 0 failed) |

## pre_pi_remainder_ms

_derived estimate: elapsed_ms - Pi's `main` TOTAL = Python + Node boot up to Pi's `main()` entry plus Pi's fixed 150 ms benchmark settle_

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 1258.4 [1213.2-1323.1] (5 ok / 0 failed) |

## first run (the warm-up — reported apart, never in the statistics)

| subject | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | failed |
|---|---|---|---|---|
| baseline | 8098.6 | 6832 | 1266.6 | no |

## top 10 extension rows (median ms, successful samples only)

### baseline

| row | median [min-max] (n) |
|---|---|
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-subagents/index.js module import | 3943.0 [1997.0-4137.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/extension/index.ts module import | 259.0 [253.0-270.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@juicesharp/rpiv-todo/index.ts module import | 144.0 [135.0-169.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts module import | 115.0 [111.0-138.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@plannotator/pi-extension module import | 63.0 [39.0-72.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-subagents/index.js factory | 24.0 [22.0-25.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/pi-web-access/dist/index.js module import | 14.0 [10.0-17.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/@ff-labs/pi-fff/src/index.ts module import | 12.0 [9.0-15.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/extension/index.ts factory | 8.0 [8.0-9.0] (5) |
| <inline:llama.cpp> factory | 4.0 [3.0-4.0] (5) |

## handoff (Python → Pi, the stop-before-exec seam)

- baseline: handoff_ms 881.4 · direct ok · cprofile ok · importtime ok

## Node module census

- baseline: ok · 3671 distinct modules · 37 builtin · 17 under the host root · SDK modules outside the host root: 2799 · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-coding-agent 201 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-tui (0.87.0) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/.pi/npm/node_modules/typebox (1.1.38) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox (1.3.27) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/node_modules/typebox (1.3.27)
````

### Per-sample detail

`createAgentSessionRuntime` (Pi's `main` row that contains extension loading) and the
`extensions` group total move together; `interactiveMode.init` and the pre-Pi remainder are
steady. Two of the five samples ran markedly faster than the other three — the range, not the
median alone, is the baseline.

| sample | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | exit_ms | createAgentSessionRuntime | interactiveMode.init | extensions TOTAL |
|---|---|---|---|---|---|---|---|
| warmup | 8098.6 | 6832 | 1266.6 | 8129.5 | 6020 | 790 | 5941 |
| 001 | 6667.2 | 5454 | 1213.2 | 6688.2 | 4808 | 629 | 4732 |
| 002 | 6820.4 | 5562 | 1258.4 | 6839.9 | 4921 | 623 | 4852 |
| 003 | 6689.1 | 5366 | 1323.1 | 6714.5 | 4675 | 670 | 4600 |
| 004 | 4823.9 | 3533 | 1290.9 | 4845.3 | 2916 | 599 | 2841 |
| 005 | 4479.0 | 3244 | 1235.0 | 4501.3 | 2665 | 560 | 2602 |

## The Node module census

Status `ok` · exit 0 · lingered false · marker seen
true · `registerHooks` supported true · main pid 10417 ·
1 census file(s) · CPU profile `CPU.20260922.124011.10417.0.001.cpuprofile`.

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

`handoff_ms` **881.4 ms** (spawn → the `exec_pi` handoff instant, from the direct arm) · arms: direct `ok` (exit 0) · cprofile `ok` (exit 0) · importtime `ok` (exit 0).

`-X importtime` top 15 by cumulative µs (`importtime-top.txt`):

```
cumulative_us    self_us  module
       698832      15465  perk.cli.cli
       363484        927  perk.cli.commands.doctor
       353185        849  perk.cli.commands.doctor.render
       352336       2243  perk.convergence.doctor
       247685        893  perk.backends.linear
       235402       3850  perk.backends.linear._helpers
       119385        823  perk.cli.commands.objective
        93411        909  perk.convergence.init
        84723       4931  perk.backends.issue_backend
        82087        541  perk.cli.commands.objective.stack
        68017       3400  perk.state.cache
        64078         11  perk.delivery.layer
        64067        536  perk.delivery
        61573        777  perk.backends.linear.client
        60752      18343  perk.delivery.facade
```

cProfile top 15 by cumulative time (`cprofile-top.txt`, `python -m cProfile -o … -m perk` up to
the seam's `SystemExit(0)`):

```

         1867228 function calls (1838598 primitive calls) in 1.243 seconds

   Ordered by: cumulative time
   List reduced from 4117 to 40 due to restriction <40>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1025/1    0.142    0.000    1.246    1.246 {built-in method builtins.exec}
        1    0.000    0.000    1.246    1.246 <frozen runpy>:201(run_module)
        1    0.000    0.000    1.201    1.201 <frozen runpy>:65(_run_code)
        1    0.000    0.000    1.201    1.201 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/__main__.py:1(<module>)
    571/2    0.002    0.000    1.148    0.574 <frozen importlib._bootstrap>:1349(_find_and_load)
    558/2    0.002    0.000    1.148    0.574 <frozen importlib._bootstrap>:1304(_find_and_load_unlocked)
    536/3    0.001    0.000    1.147    0.382 <frozen importlib._bootstrap>:911(_load_unlocked)
    501/3    0.001    0.000    1.147    0.382 <frozen importlib._bootstrap_external>:1021(exec_module)
   1186/7    0.000    0.000    1.147    0.164 <frozen importlib._bootstrap>:480(_call_with_frames_removed)
        1    0.000    0.000    1.104    1.104 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/cli.py:1(<module>)
    97/26    0.000    0.000    0.753    0.029 {built-in method builtins.__import__}
 1054/525    0.001    0.000    0.609    0.001 <frozen importlib._bootstrap>:1390(_handle_fromlist)
        1    0.000    0.000    0.500    0.500 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/commands/doctor/__init__.py:1(<module>)
        1    0.000    0.000    0.493    0.493 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/cli/commands/doctor/render.py:1(<module>)
        1    0.000    0.000    0.492    0.492 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2488/src/perk/convergence/doctor/__init__.py:1(<module>)
```

Reading: bare `perk` imports the whole command catalogue before it can open a plain session —
`perk.cli.cli` costs ~0.7 s of the ~0.88 s handoff, with `doctor` (its render + convergence
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
`cpu-prof/*.cpuprofile`, `summary.json`, `summary.md`) is **not committed** — it is ~6.5 MB of
host-specific paths and binary profiles; this record carries the text evidence.

## Caveats

- Machine load and filesystem cache dominate the spread: an earlier one-sample trial of the
  same tool on this branch two commits earlier (`2c85c392`, dirty tree), run concurrently with a
  test suite, measured 26.4 s elapsed (pi-subagents module import 23.5 s). The five-sample run
  above was taken with the host otherwise idle; its own range (4.5–6.8 s) is the honest picture.
- `pre_pi_remainder_ms` is a derived estimate (elapsed − Pi's `main` TOTAL): Python + Node boot
  up to Pi's `main()` plus Pi's fixed 150 ms benchmark settle.
- `PI_OFFLINE=1`: Pi's startup network operations are disabled; the numbers describe an offline
  start.
- The census records what Node's loader resolves; modules jiti evaluates itself (perk's own
  TypeScript extension files) may not appear.
- Pi persists no session file for a benchmark session (it persists only after an assistant
  message); perk's extension mints its in-memory warm run id as on any launch.
- One subject only — the delta block is absent by design; the closing evidence of the objective
  will run two subjects (a pinned baseline worktree at this revision vs the candidate).
