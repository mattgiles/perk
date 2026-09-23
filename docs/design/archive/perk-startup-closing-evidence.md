# Closing evidence: perk startup after the CLI diet and the host-SDK bridge (`perk-dev profile-startup`, 2026-09)

**Status:** dated evidence record (2026-09) — the closing measurement of the "Speed up plain perk
startup" objective. One `perk-dev profile-startup` run over two subjects, five alternating warm
samples each, first runs apart, profiles on: `baseline` is a detached worktree pinned at
`0e9de38150b73ff2f7ceeb28f1339e64096dfd4a` — the revision the committed baseline record
[`perk-startup-baseline.md`](./perk-startup-baseline.md) was measured at (instrumented: the
stop-before-exec seam present, so the handoff arms record; pre-diet, pre-bridge) — and `candidate`
is the landed tree, the plan worktree at its clean starting HEAD
`d3dcf5b5ac46ff3a94f91740a7077f1c104b1dad` (`main` after the CLI diet and the host-SDK bridge
merged; this record's own commit changes no source, so the candidate's source tree is the landed
tree by construction). The method and every field's meaning are in
[`docs/developers/profiling-startup.md`](../../developers/profiling-startup.md); the baseline record
is the compared-against artifact (its census is reproduced here exactly; its timings are cited
beside this run's baseline subject, not reconciled). The run was launched from inside a perk
implement session with the session's own variables cleared (`env -u PI_SESSION_FILE -u
PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT -u
PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u PERK_RUN_ID`), the plain-shell environment the how-to
asks for; both subjects resolved their agent dir through the `config` arm and their trust through
the main checkout's entry (nearest ancestor). Every number below is transcribed from the run
directory (`$OUT`, not committed) or from the live session; nothing is carried over from the plan
or the objective.

## Verdict

**PASS** — the acceptance predicate holds on both arms:

1. the candidate's Node module census is `status: ok` and reads (verbatim from `summary.md`):

   ```
   candidate: ok · 461 distinct modules · 37 builtin · 17 under the host root · SDK modules outside the host root: 0
   ```

   with `node-census-summary.json` → `sdk_outside_host`: `{}`, `sdk_outside_host_total`: `0`,
   `sdk_outside_host_roots`: `[]`;

2. the candidate session's **pre-reload** `/perk-selfcheck` (live leg A, operator-relayed, verbatim
   decisive lines):

   ```
   perk: selfcheck — 3.6.0: ok; shared=ok; ambient=reached (append=5239c); agents=reached (files=1); bridge=installed
     native sdk bridge: installed (roots=2, specifiers=7)
       host: /Users/mattgiles/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js
       roots: 2 — /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/pi-subagents, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/pi-web-access
   ```

Timing is reported, never gated: the harness's `pi_main_total_ms` delta (candidate − baseline,
over medians) is **−1110.0 ms, −50.4 %**; the prototype figure was **−45 %** (2.47 s →
1.33–1.38 s, Pi-only, ad-hoc pre-objective startup probes in the maintainer's untracked planning
memo, `perk-slowness.md`). Two numbers, two provenances.

## The measurement (verbatim `summary.md`)

````markdown
# perk startup profile

- started 2026-09-23T17:03:26+00:00 · finished 2026-09-23T17:04:47+00:00
- perk-dev 3.6.0 (perk-dev head d3dcf5b5ac46ff3a94f91740a7077f1c104b1dad) · host macOS-26.5-arm64-arm-64bit-Mach-O arm64 · 11 CPUs
- runs 5 per subject (+1 discarded warm-up) · PTY 120x40 · timeout 180 s · exit grace 10 s · profiles on
- injected env: PI_STARTUP_BENCHMARK=1 PI_TIMING=1 PI_OFFLINE=1 · removed: PERK_RUN_ID, PERK_PROFILE_HANDOFF, PERK_MODULE_CENSUS_DIR, NODE_OPTIONS

## subjects

| subject | checkout | revision | dirty | perk | pi | node | agent dir | trust |
|---|---|---|---|---|---|---|---|---|
| baseline | /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline | 0e9de38150b7 | no | perk 3.6.0 | 0.87.0 | v26.3.0 | /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent (config) | trusted_by=/Users/mattgiles/dev/github/mattgiles/perk |
| candidate | /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497 | d3dcf5b5ac46 | no | perk 3.6.0 | 0.87.0 | v26.3.0 | /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent (config) | trusted_by=/Users/mattgiles/dev/github/mattgiles/perk |

- baseline SDK copies installed: @earendil-works/pi-coding-agent 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent, @earendil-works/pi-tui 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-tui, @earendil-works/pi-ai 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-ai, @earendil-works/pi-agent-core 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-agent-core, typebox 1.1.38 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/typebox, typebox 1.3.27 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/typebox
- baseline consumer packages: @dietrichgebert/ponytail 4.10.0, @ff-labs/pi-fff 0.11.0, @juicesharp/rpiv-ask-user-question 2.11.0, @juicesharp/rpiv-todo 2.11.0, @plannotator/pi-extension 0.27.17, @tombell/pi-diff 0.0.4, @tombell/pi-plan 0.0.4, @tombell/pi-status 0.0.6, pi-subagents 0.70.1, pi-web-access 0.30.0
- candidate SDK copies installed: @earendil-works/pi-coding-agent 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/node_modules/@earendil-works/pi-coding-agent, @earendil-works/pi-tui 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/node_modules/@earendil-works/pi-tui, @earendil-works/pi-ai 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/node_modules/@earendil-works/pi-ai, @earendil-works/pi-agent-core 0.87.0 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/node_modules/@earendil-works/pi-agent-core, typebox 1.1.38 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/typebox, typebox 1.3.27 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/node_modules/typebox
- candidate consumer packages: @dietrichgebert/ponytail 4.10.0, @ff-labs/pi-fff 0.11.0, @juicesharp/rpiv-ask-user-question 2.11.0, @juicesharp/rpiv-todo 2.11.0, @plannotator/pi-extension 0.27.17, @tombell/pi-diff 0.0.4, @tombell/pi-plan 0.0.4, @tombell/pi-status 0.0.6, pi-subagents 0.70.1, pi-web-access 0.30.0

## elapsed_ms (the harness's spawn call → Pi's `main` TOTAL line observed on stderr)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 3000.4 [2759.4-22193.4] (5 ok / 0 failed) |
| candidate | 1599.3 [1504.9-2979.0] (5 ok / 0 failed) |

## pi_main_total_ms (Pi's own `main` TOTAL)

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 2203.0 [1907.0-21329.0] (5 ok / 0 failed) |
| candidate | 1093.0 [1010.0-2453.0] (5 ok / 0 failed) |

## pre_pi_remainder_ms

_derived estimate: elapsed_ms - Pi's `main` TOTAL = everything outside Pi's own timing: process spawn/exec, Python (perk) up to the exec handoff, Node boot to Pi's `main()`, Pi's fixed 150 ms benchmark settle, and the harness's marker-observation latency_

| subject | median [min-max] (n ok / n failed) |
|---|---|
| baseline | 852.4 [797.4-915.3] (5 ok / 0 failed) |
| candidate | 500.9 [483.7-526.0] (5 ok / 0 failed) |

## first run (the warm-up — reported apart, never in the statistics)

| subject | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | failed |
|---|---|---|---|---|
| baseline | 21680.6 | 20817 | 863.6 | no |
| candidate | 1892.0 | 1343 | 549.0 | no |

## top 10 extension rows (median ms, successful samples only)

### baseline

| row | median [min-max] (n) |
|---|---|
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/pi-subagents/index.js module import | 1370.0 [1086.0-20308.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/extension/index.ts module import | 140.0 [138.0-188.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/@juicesharp/rpiv-todo/index.ts module import | 92.0 [85.0-97.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts module import | 74.0 [68.0-76.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/@plannotator/pi-extension module import | 25.0 [20.0-102.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/pi-subagents/index.js factory | 12.0 [11.0-13.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/@ff-labs/pi-fff/src/index.ts module import | 6.0 [5.0-8.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/pi-web-access/dist/index.js module import | 6.0 [6.0-18.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/extension/index.ts factory | 6.0 [5.0-7.0] (5) |
| <inline:llama.cpp> factory | 2.0 [2.0-3.0] (5) |

### candidate

| row | median [min-max] (n) |
|---|---|
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/pi-subagents/index.js module import | 197.0 [172.0-1390.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/extension/index.ts module import | 157.0 [130.0-193.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/@juicesharp/rpiv-todo/index.ts module import | 95.0 [91.0-106.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts module import | 77.0 [75.0-79.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/@plannotator/pi-extension module import | 29.0 [26.0-99.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/pi-subagents/index.js factory | 11.0 [10.0-17.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/extension/index.ts factory | 8.0 [7.0-8.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/@ff-labs/pi-fff/src/index.ts module import | 6.0 [5.0-9.0] (5) |
| /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.pi/npm/node_modules/pi-web-access/dist/index.js module import | 6.0 [6.0-18.0] (5) |
| <inline:llama.cpp> factory | 3.0 [2.0-3.0] (5) |

## handoff (Python → Pi, the stop-before-exec seam)

- baseline: handoff_ms 597.6 · direct ok · cprofile ok · importtime ok
- candidate: handoff_ms 213.7 · direct ok · cprofile ok · importtime ok

## Node module census

- baseline: ok · 3671 distinct modules · 37 builtin · 17 under the host root · SDK modules outside the host root: 2799 · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-agent-core 78 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-ai 178 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai (0.87.0) · @earendil-works/pi-coding-agent 201 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui (0.87.0) · @earendil-works/pi-tui 41 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-tui (0.87.0) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/.pi/npm/node_modules/typebox (1.1.38) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox (1.3.27) · typebox 668 @ /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline/node_modules/typebox (1.3.27)
- candidate: ok · 461 distinct modules · 37 builtin · 17 under the host root · SDK modules outside the host root: 0

## delta (candidate - baseline, over medians; reported, not judged)

| metric | Δ ms | Δ % |
|---|---|---|
| elapsed_ms | -1401.1 | -46.7 |
| pi_main_total_ms | -1110.0 | -50.4 |
| pre_pi_remainder_ms | -351.6 | -41.2 |
| handoff_ms | -383.9 | -64.2 |
````

### Cross-check against the committed baseline (same revision, different day)

Both subjects called `baseline` are `0e9de381`; the committed record measured a plan worktree on
2026-09-22, this run a detached worktree on 2026-09-23. Reported, not reconciled:

| metric | committed record (2026-09-22) | this run's `baseline` subject |
|---|---|---|
| `elapsed_ms` median [min–max] | 3977.7 [3665.4–4089.8] | 3000.4 [2759.4–22193.4] |
| `pi_main_total_ms` | 2807.0 [2572.0–2928.0] | 2203.0 [1907.0–21329.0] |
| `pre_pi_remainder_ms` | 1161.8 | 852.4 |
| `handoff_ms` | 773.6 | 597.6 |
| `pi-subagents/index.js module import` | 1673.0 | 1370.0 |
| `extension/index.ts module import` | 219.0 | 140.0 |
| census: distinct / SDK outside the host root | 3671 / 2799 | 3671 / 2799 |

The census is identical down to the `by_package` top 15 (`typebox` 2004, `@earendil-works/pi-ai`
356, `pi-subagents` 258, `yaml` 216, `@earendil-works/pi-coding-agent` 201,
`@earendil-works/pi-agent-core` 156, `undici` 108, `@earendil-works/pi-tui` 82, `semver` 46,
`diff` 38, `highlight.js` 21, `@juicesharp/rpiv-todo` 14, `parse5` 14,
`@juicesharp/rpiv-ask-user-question` 12, `grok-mermaid` 11) and the same ten
`sdk_outside_host_roots` — the module graph is a property of the revision; the timings are a
property of the day (see Caveats). This run's baseline `001` sample (22193.4 ms, `pi-subagents`
module import 20308 ms) sits beside its 21680.6 ms warm-up — the compile-cache/filesystem-cache
pattern the baseline record's caveat describes; the median is unaffected.

## Candidate census detail

`profiles/candidate/node-census-summary.json`: `status: ok` · exit 0 · lingered false · marker seen
true · `registerHooks` supported true · main pid 83423 · 1 census file · CPU profile
`CPU.20260923.130443.83423.0.001.cpuprofile` · 461 distinct · 37 builtin · 17 under the host root ·
`sdk_outside_host_total` 0.

`by_package` (all 15 entries):

| package | modules |
|---|---|
| `pi-subagents` | 258 |
| `yaml` | 72 |
| `@juicesharp/rpiv-ask-user-question` | 34 |
| `@juicesharp/rpiv-todo` | 15 |
| `parse5` | 14 |
| `entities` | 5 |
| `@ff-labs/fff-bin-darwin-arm64` | 1 |
| `@ff-labs/fff-node` | 1 |
| `@juicesharp/rpiv-config` | 1 |
| `@yuuang/ffi-rs-darwin-arm64` | 1 |
| `ffi-rs` | 1 |
| `jiti` | 1 |
| `p-limit` | 1 |
| `pi-web-access` | 1 |
| `yocto-queue` | 1 |

The SDK-family grep over the raw census (the wider-bridge-scope lever's evidence), with the host
root `/Users/mattgiles/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent`:

```
$ rg "/(@earendil-works/|typebox/|@sinclair/typebox/|@mariozechner/)" $OUT/profiles/candidate/node-census/census-83423.jsonl | rg -v -F "$HOST" | wc -l
0
$ rg "/(@earendil-works/|typebox/|@sinclair/typebox/|@mariozechner/)" $OUT/profiles/candidate/node-census/census-83423.jsonl | rg -F "$HOST" | wc -l
390
```

Every SDK-family URL the main Pi process resolved (390 resolve records, 2034 in total) is under
the host root; none is under either checkout root. The raw JSONL's resolve records carry a
`parent` field (the importing module) that the summary's `by_package` does not: the 72 `yaml`
modules are loaded from `<candidate>/.pi/npm/node_modules/yaml/` with parents
`.pi/npm/node_modules/pi-subagents/src/agents/agents.js` and
`…/pi-subagents/src/agents/agent-serializer.js` (the rest are `yaml`-internal); no `diff` module
is loaded at all (0 URLs; the baseline loaded 38). perk's own extension files do not appear in the
census (jiti evaluates them — see Caveats), so the census records nothing about what
`extension/index.ts` imports.

## Candidate Python handoff detail

`handoff_ms` **213.7 ms** (the harness's spawn call → the `exec_pi` handoff instant, from the
direct arm; baseline 597.6 ms) · arms: direct `ok` (exit 0) · cprofile `ok` (exit 0) · importtime
`ok` (exit 0).

`-X importtime` top 15 by cumulative µs (`profiles/candidate/importtime-top.txt`):

```
cumulative_us    self_us  module
        45774        258  perk.cli.context
        44406       7009  perk.substrate.config
        21330        955  perk
        14713        465  importlib.metadata
        10206       1041  perk.substrate.bindings
         9427        146  pydantic
         8324        276  perk.cli.cli
         7037        246  pydantic._migration
         6791        159  pydantic.warnings
         6717        171  yaml
         6633         83  pydantic.version
         6551        253  pydantic_core
         5557       2324  pydantic.types
         4490       4027  pydantic_core.core_schema
         4375        141  perk.cli.version_check
```

The tree behind the top rows (reconstructed from `importtime.log`'s nesting): `perk.cli.context`
(45,774 µs cumulative, 258 µs self) has three direct children — `perk.substrate.config` 44,406 µs,
`tomllib` 984 µs, `perk.cli.ensure` 128 µs; under `perk.substrate.config` (7,009 µs self) sit
`perk.substrate.bindings` 10,206 µs (itself `yaml` 6,717 µs + `perk.substrate.registry` 2,371 µs +
`perk._resources` 78 µs), `pydantic` 9,427 µs, `pydantic.types` 5,557 µs, `perk.boundary` 3,594 µs,
`annotated_types` 2,559 µs, `pydantic._internal._validators` 2,365 µs,
`pydantic._internal._decorators` 2,212 µs, `perk.substrate.skill_exposure` 833 µs. The other
depth-0 `perk.*` rows are `perk` 21,330 µs (`importlib.metadata` 14,713 µs beneath it),
`perk.cli.cli` 8,324 µs, `perk.run.pi_exec` 579 µs, `perk.cli.plain_session` 343 µs, `perk.run`
172 µs.

cProfile top 15 by cumulative time (`profiles/candidate/cprofile-top.txt`, `python -m cProfile -o
… -m perk` up to the seam's `SystemExit(0)`):

```
Wed Sep 23 13:04:42 2026    /private/var/folders/90/b55dzd451137c93rcngpgdh00000gp/T/tmp.VzXNB4why1/closing/profiles/candidate/cprofile.prof

         218909 function calls (213619 primitive calls) in 0.168 seconds

   Ordered by: cumulative time
   List reduced from 2273 to 40 due to restriction <40>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
    280/1    0.010    0.000    0.168    0.168 {built-in method builtins.exec}
        1    0.000    0.000    0.168    0.168 <frozen runpy>:201(run_module)
        1    0.000    0.000    0.147    0.147 <frozen runpy>:65(_run_code)
        1    0.000    0.000    0.147    0.147 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/src/perk/__main__.py:1(<module>)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/src/perk/cli/cli.py:138(main)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/core.py:1522(__call__)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/core.py:1377(main)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/core.py:1878(invoke)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/core.py:1294(invoke)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/core.py:823(invoke)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/.venv/lib/python3.13/site-packages/click/decorators.py:33(new_func)
        1    0.000    0.000    0.137    0.137 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497/src/perk/cli/cli.py:103(cli)
    212/6    0.000    0.000    0.103    0.017 <frozen importlib._bootstrap>:1349(_find_and_load)
    209/6    0.000    0.000    0.103    0.017 <frozen importlib._bootstrap>:1304(_find_and_load_unlocked)
    200/7    0.000    0.000    0.102    0.015 <frozen importlib._bootstrap>:911(_load_unlocked)
```

Further down the same top-40: `perk/cli/context.py:1(<module>)` 0.072 s cumulative,
`perk/substrate/config.py:1(<module>)` 0.069 s, `perk/cli/plain_session.py:36(run_plain_session)`
0.064 s — of which `perk/substrate/git.py:128(_run)` × 4 = 0.060 s (subprocess `poll`, three of
them `main_worktree_root`), i.e. the bare path's remaining in-process time splits between the
config import and the git probes.

## The light-verb probe (candidate only)

The reprofile input the harness does not produce: the cost of the deferred one-unit command
registration, read as `perk release-notes --help` (a verb whose own module imports stdlib, `click`,
`perk.__version__`, `perk._resources`, `perk.cli.ensure`, `perk.release_notes` and
`perk.substrate.output`) minus `perk --version`. The script, verbatim (`$OUT/light_verb_probe.py`,
not committed):

```python
# light_verb_probe.py — run from the candidate checkout: .venv/bin/python light_verb_probe.py "$OUT"
# One discarded warm-up pair, then five alternating pairs in the fixed order --version → release-notes --help.
import json, statistics, subprocess, sys, time
from pathlib import Path

out = Path(sys.argv[1])
perk = Path(".venv/bin/perk").resolve()
VERBS = {"version": [str(perk), "--version"], "release_notes_help": [str(perk), "release-notes", "--help"]}

def run_ms(argv):
    t0 = time.perf_counter()
    subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
    return (time.perf_counter() - t0) * 1000.0

warmup = {k: run_ms(v) for k, v in VERBS.items()}
samples = {k: [] for k in VERBS}
for _ in range(5):
    for k, v in VERBS.items():
        samples[k].append(run_ms(v))
stats = {
    k: {"median_ms": statistics.median(s), "min_ms": min(s), "max_ms": max(s), "samples_ms": s}
    for k, s in samples.items()
}
stats["delta_median_ms"] = stats["release_notes_help"]["median_ms"] - stats["version"]["median_ms"]
stats["warmup_ms"] = warmup
(out / "light-verb-probe.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
print(json.dumps(stats, indent=2))
```

Run from the candidate checkout with the same `env -u …` prefix as the harness, then one import
trace and its top:

```bash
.venv/bin/python light_verb_probe.py "$OUT"
.venv/bin/python -X importtime -m perk release-notes --help 2> "$OUT/light-verb-importtime.log"
uv run python -c 'import sys; from pathlib import Path; from perk_dev.profile_startup.handoff import summarize_importtime, render_importtime_top; print(render_importtime_top(summarize_importtime(Path(sys.argv[1]).read_text(encoding="utf-8"))), end="")' "$OUT/light-verb-importtime.log" > "$OUT/light-verb-importtime-top.txt"
```

`light-verb-probe.json` (one discarded warm-up pair, then five alternating pairs):

| verb | median_ms | min_ms | max_ms | samples_ms |
|---|---|---|---|---|
| `perk --version` | 130.6 | 125.6 | 132.5 | 129.1, 131.0, 132.5, 130.6, 125.6 |
| `perk release-notes --help` | 619.9 | 563.4 | 1373.6 | 1373.6, 563.4, 620.2, 619.9, 615.2 |

`delta_median_ms` = **489.4 ms** · warm-up pair: 127.7 ms / 931.0 ms.

`light-verb-importtime-top.txt`, the decisive rows (cumulative µs · self µs · module):

```
       239570        765  perk.cli.commands.doctor
       233615        578  perk.cli.commands.doctor.render
       233037       1344  perk.convergence.doctor
       160852        509  perk.backends.linear
       153234       2671  perk.backends.linear._helpers
        83772        677  perk.cli.commands.objective
        57957        489  perk.cli.commands.objective.stack
        40619      10381  perk.cli.commands.learn
        31366        582  perk.cli.commands.objective.stack.review_cmd
        30784         10  perk.cli.commands.pr.review.checkout_cmd
        30775         18  perk.cli.commands.pr.review
        30757      10215  perk.cli.commands.pr
        27270      21091  perk.cli.commands.plan
        26184        346  perk.cli.commands.gist
        24593        636  perk.cli.commands.gist.author_cmd
        23958        740  perk.cli.commands.seeded_door
        22923       2685  perk.cli.commands.objective.stack.land_cmd
```

and, from the full `light-verb-importtime.log` (below the top-30 cut): `perk.substrate.registry`
2,535 µs (self-only), `perk.cli.commands.release_notes_cmd` 1,930 µs cumulative
(`perk.release_notes` 1,610 µs) — the verb's own module against the ~490 ms of siblings.

## The live pass

The implement session itself was the candidate session: a linked worktree with its own `.pi/npm`,
Pi loading `..` before the two consumers (`pi-subagents` 0.70.1, `pi-web-access` 0.30.0).
Classification vocabulary: `observed-live (operator-relayed)` · `observed-live (tool result)` ·
`unobserved — NOT PASSED (<reason>)`. Provenance is its own column. Session identities: **P** =
the objective-plan session (run `01M37AAX4V1MBHWG092TQBQWKN`, cwd
`/Users/mattgiles/dev/github/mattgiles/perk` — the main checkout at `d3dcf5b5`, tree clean apart
from the untracked planning memo, 2026-09-23 ≈15:20 UTC); **I** = the implement session (run
`01M37KA3R6032DBB0MXKVTH3PA`, cwd `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497`,
HEAD `d3dcf5b5`, 2026-09-23 17:08–17:16 UTC).

| leg | actor · session | what ran | evidence (verbatim, trimmed to the decisive lines) | classification | provenance |
|---|---|---|---|---|---|
| A `/reload` → `reused` | operator · I | `/perk-selfcheck` → `/reload` → `/perk-selfcheck`, both outputs pasted into the session | pre-reload: `bridge=installed` · `native sdk bridge: installed (roots=2, specifiers=7)` · `host: …/@earendil-works/pi-coding-agent/dist/index.js` · `roots: 2 — <candidate>/.pi/npm/node_modules/pi-subagents, <candidate>/.pi/npm/node_modules/pi-web-access` · `tools: 38 active / 60 registered … per source: ..=23 (22519c); … npm:pi-subagents=3 (22811c); npm:pi-web-access=4 (11096c)` · `branch: 92 entries`. post-reload: `bridge=installed` · `native sdk bridge: installed (roots=2, specifiers=7, reused)` · same `host:` · same `roots: 2 — …` · `branch: 96 entries`. No `perk: sdk bridge — …` warning in either. | `observed-live (operator-relayed)` | I · pre-reload feeds the Verdict; pasted 2026-09-23 ≈17:16 UTC |
| B foreground `run_scout_wave` | executor · P | one wave, three `perk.scout` briefs (`crosslinks`, `live-legs`, `stale-claims`) | workflow run `cd4ae3ef-92ee-4c35-a7df-9f00e2f2daa5`, child runs `056959f6…` / `93bc9b0a…` / `60e98b1e…`, all `completed`, `ok: true`, reports returned; configured model `[models.subagents] scout = openai/gpt-5.6-sol`. The operator's `/perk-selfcheck` in that session: `perk: selfcheck — 3.6.0: ok; shared=ok; ambient=reached (append=5239c); agents=reached (files=1); bridge=installed` · `native sdk bridge: installed (roots=2, specifiers=7)` · `host: /Users/mattgiles/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js` · `roots: 2 — /Users/mattgiles/dev/github/mattgiles/perk/.pi/npm/node_modules/pi-subagents, /Users/mattgiles/dev/github/mattgiles/perk/.pi/npm/node_modules/pi-web-access` · `per source: … npm:pi-subagents=2 (18414c); npm:pi-web-access=3 (8767c)`. What it proves: the parent-side wave launch (pi-subagents' async spawn RPC, `spawnRunner`) completes under an `installed` bridge; the lanes ran in the detached runner (pi-subagents' own peer preload), so this leg does not exercise the parent-process exact-entry import — leg C does. | `observed-live (tool result)` | P · planning time, recorded in the plan's Assumptions |
| C blocking `subagent` | executor · I | `subagent({ agent: "perk.scout", task: "List the file names under docs/developers/ and stop.", async: false })` | inline result, no `isError`: `Run fan-out: 1/64 used, 63 remaining` · the ten file names (`auditing-sessions.md` … `why-session-audit.md`) · `Mission: 61db0ea1-bccc-4b7d-a529-cc55f1454f7d (completed)`. The child session was created in the parent Pi process (`runSingleAttempt` → `childSessions.create` → `loadHostPiCodingAgent`'s exact-entry import of the host package), i.e. the facade mapping of contracts §8.73 resolved in-process. | `observed-live (tool result)` | I · 2026-09-23 ≈17:08 UTC |
| D detached `subagent` | executor · I | `subagent({ agent: "perk.scout", task: "List the file names under docs/developers/ and stop.", async: true })`; on the native completion notice, `subagent({ action: "status", id })` | immediate receipt `Async: perk.scout [36285d75-6961-4194-a399-d65df5a2a4cc]` · `Mission: 5cdf23ca-6fe6-42a4-8bc3-4129b1d90e5c (active)`; native notice `Background task completed: perk.scout` with the ten file names; status: `State: complete` · `Process terminal: observed` · `Mode: single` · `Started: 2026-09-23T17:16:16.865Z` · `Updated: 2026-09-23T17:16:24.586Z` · `Step 1: perk.scout: … complete (gpt-5.6-terra), acceptance: attested`. What it proves: the parent-side detached launch path under the bridge; the runner is its own `node` process (`subagent-runner.js` with pi-subagents' `runner-peer-preload.mjs`), where perk's bridge is `unsupported:embedded-host` by design (contracts §8.73, embedded SDK hosts). | `observed-live (tool result)` | I · launched 2026-09-23 17:16:16 UTC, after leg A so `/reload` never interleaved with a detached run |
| E `fetch_content` image | executor · I | `fetch_content({ url: "https://www.python.org/static/img/python-logo.png" })` | one image item (the logo rendered inline) + `Image fetched (580×164, image/png)`; no `error` — pi-web-access's lazy `await import("@earendil-works/pi-coding-agent")` for `resizeImage` resolved through the bridge. First attempt; the fallback URL was not needed. | `observed-live (tool result)` | I · 2026-09-23 ≈17:08 UTC |
| F `web_search` | executor · I | `web_search({ query: "node:module registerHooks resolve hook" })` | five source-linked results (`node:module` API — Node.js v26.9.0 documentation, https://nodejs.org/api/module.html; Customization Hooks — Node.js 26.8.2; `module.registerHooks`; the v26.1.0 and v26.4.0 `node:module` pages), stored as responseId `muecwlfwpxhd6q`; the tool executed and returned results, so the static `@earendil-works/pi-tui` / `typebox` facades loaded. | `observed-live (tool result)` | I · 2026-09-23 ≈17:08 UTC |

## Reprofile and deferrals

Disposition vocabulary (closed): `pursue → gist #N` · `defer — rule not met (measured: <number>)`
· `not measured — <failure named>`. The rules were fixed before the run; the executor read the
evidence and applied them. The Node-side registry read is `not isolated by this harness` (a
`.cpuprofile` walk would) — stated, never dispositioned.

| lever | evidence (paths under `$OUT`) | rule → `pursue` iff … | measured | disposition |
|---|---|---|---|---|
| Per-group lazy command loading | `light-verb-probe.json`: `delta_median_ms` 489.4 (`--version` 130.6 [125.6–132.5]; `release-notes --help` 619.9 [563.4–1373.6]); `light-verb-importtime-top.txt`: `perk.cli.commands.doctor` 239.6 ms, `perk.backends.linear` 160.9 ms, `perk.cli.commands.objective` 83.8 ms, `perk.cli.commands.learn` 40.6 ms, `perk.cli.commands.plan` 27.3 ms, `perk.cli.commands.gist` 26.2 ms; `perk.substrate.registry` 2.5 ms (log) | `delta_median_ms ≥ 100` | 489.4 ms | `pursue → gist #2498` ([Startup follow-up: per-group lazy command loading](https://github.com/mattgiles/perk/issues/2498)); the registry row rides it as a note |
| Broader TS import refactors inside perk's own extension | candidate top rows: `extension/index.ts module import` 157.0 ms + `factory` 8.0 ms = 165.0 ms summed; `pi-subagents/index.js module import` 197.0 ms (+ `factory` 11.0 ms = 208.0 ms); census: `yaml` 72 modules loaded from `<candidate>/.pi/npm/node_modules/yaml/` (raw-JSONL parents: `pi-subagents/src/agents/agents.js`, `agent-serializer.js`); `diff` not loaded (0 URLs) | perk's `extension/index.ts` (module import + factory medians summed) is the **largest** extension row of the candidate | 165.0 ms vs 197.0 ms (208.0 ms summed) for `pi-subagents` | `defer — rule not met (measured: 165.0 ms, second to pi-subagents' 197.0 ms)` |
| Configuration / registry caching | `profiles/candidate/importtime-top.txt`: `perk.substrate.config` 44,406 µs cumulative (7,009 self) with `perk.substrate.bindings` 10,206, `pydantic` 9,427, `pydantic.types` 5,557, `perk.boundary` 3,594 beneath it; its importer `perk.cli.context` 45,774 µs (258 self) = config + `tomllib` 984 + `perk.cli.ensure` 128; `cprofile-top.txt`: `config.py:1(<module>)` 0.069 s of 0.168 s; probe path: `perk.substrate.registry` 2,535 µs | `perk.substrate.config` is the **largest `perk.*` cumulative subtree** in the candidate's bare-`perk` importtime top | 44,406 µs — the largest `perk.*` subtree; the only `perk.*` row above it is its own importer frame (`perk.cli.context`, +1,368 µs of `tomllib`/`ensure`/self), which the reading here does not count as a distinct subtree; the next distinct `perk.*` subtree is `perk` at 21,330 µs | `pursue → gist #2499` ([Startup follow-up: configuration loading cost on the bare perk path](https://github.com/mattgiles/perk/issues/2499)) |
| Launcher preload (`--import` / `NODE_OPTIONS` at the exec seam) | census `sdk_outside_host_roots`: `[]`; raw JSONL: 0 SDK-family URLs outside the host root; `pre_pi_remainder_ms` 500.9 [483.7–526.0] (Node boot sits inside it; a preload cannot shrink it) | `sdk_outside_host_roots` non-empty AND the traced cause is a consumer Pi loaded before perk; an empty list ⇒ `defer` structurally | `[]` (0 roots) | `defer — rule not met (measured: 0 roots — structurally)` |
| Wider bridge scope | the SDK-family grep above: 0 non-host URLs; 390 SDK-family URLs, all under the host root | that grep returns at least one non-host URL | 0 | `defer — rule not met (measured: 0 non-host URLs)` |

Both gists are `plan`-scoped `perk:gist` issues, each created with its own minted run id
(`01M37MCDGDZCTRX0P7700T8Q4A` → #2498, `01M37MCMN1MKNDQQRZWZMZ6ZZG` → #2499); no objective node was
added.

## Reproduction

From the candidate checkout (a prepared perk worktree; `MAIN` = the main checkout):

```bash
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"

# 0e9de381 is reachable from refs/heads/plan-2488 / origin/plan-2488 / refs/pull/2489/head — not from main
git cat-file -t 0e9de38150b73ff2f7ceeb28f1339e64096dfd4a || git fetch origin plan-2488 \
  || git fetch origin refs/pull/2489/head

# pin + prepare the baseline (its own .venv and node_modules; trust inherited from MAIN)
git worktree add --detach "$MAIN/.worktrees/startup-baseline" 0e9de38150b73ff2f7ceeb28f1339e64096dfd4a
(cd "$MAIN/.worktrees/startup-baseline" && uv sync --all-packages && npm ci && uv run perk doctor --fix)
# At 0e9de381 (as on the landed tree) `perk doctor --fix` in perk's own repo does not populate
# .pi/npm — the self-repo posture leaves the consumer packages to Pi's lazy install at launch,
# and the harness refuses a subject without .pi/npm/node_modules (`subject_not_converged`).
# Stage it the way every plan worktree launch does (a hard-link clone of MAIN's converged tree):
uv run python -c "
from pathlib import Path
from perk.run.launch.materialize import materialize_extensions
materialize_extensions(Path('$MAIN'), Path('$MAIN/.worktrees/startup-baseline'))
"
ls "$MAIN/.worktrees/startup-baseline/.venv/bin/perk" \
   "$MAIN/.worktrees/startup-baseline/.pi/npm/node_modules/pi-subagents/package.json"

# the two-subject run, baseline first (the delta block then reads candidate − baseline)
OUT="$(mktemp -d)/closing"
env -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL \
    -u PI_CODING_AGENT -u PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u PERK_RUN_ID \
  uv run perk-dev profile-startup --runs 5 --output "$OUT" \
    --subject baseline="$MAIN/.worktrees/startup-baseline" --subject candidate="$(pwd)"

# the light-verb probe (candidate only; the script is quoted above, saved as $OUT/light_verb_probe.py)
env -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL \
    -u PI_CODING_AGENT -u PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u PERK_RUN_ID \
  .venv/bin/python "$OUT/light_verb_probe.py" "$OUT"
env -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL \
    -u PI_CODING_AGENT -u PI_CODING_AGENT_DIR -u PERK_CLI_VERSION -u PERK_RUN_ID \
  .venv/bin/python -X importtime -m perk release-notes --help 2> "$OUT/light-verb-importtime.log"
uv run python -c 'import sys; from pathlib import Path; from perk_dev.profile_startup.handoff import summarize_importtime, render_importtime_top; print(render_importtime_top(summarize_importtime(Path(sys.argv[1]).read_text(encoding="utf-8"))), end="")' "$OUT/light-verb-importtime.log" > "$OUT/light-verb-importtime-top.txt"
```

Validity gate (pre-committed, passed on the first run): each subject `5 ok / 0 failed`; both
censuses `status: ok`; all six handoff arms `ok`; both stamps `dirty: false`. A failed gate is
re-run whole into a fresh `--output` (runs are never merged); unavailable data would appear as the
literal `n/a — <failure named>` — none was needed.

## Teardown and caveats

Teardown — the pinned baseline worktree was removed before this record's single commit; the
proving output, verbatim (`MAIN` = the main checkout):

```
$ git worktree remove --force "$MAIN/.worktrees/startup-baseline"
exit=0
$ git worktree list | rg -n "startup-baseline"; echo "exit=$?"
exit=1
$ ls "$MAIN/.worktrees/startup-baseline"
ls: /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/startup-baseline: No such file or directory
$ git worktree list | rg "perk +[0-9a-f]+ \[main\]|plan-2497"
/Users/mattgiles/dev/github/mattgiles/perk                                                                                       d3dcf5b5 [main]
/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2497                                                                  d3dcf5b5 [plan-2497]
```

The SHAs in this record name the SUBJECTS (`0e9de381`, `d3dcf5b5`), not the commit that adds it.

The run directory (`meta.json`, `subjects/`, `samples/`, `profiles/` with the raw handoff records,
`cprofile.prof`, `importtime.log`, `node-census/census-<pid>.jsonl`, `cpu-prof/*.cpuprofile`,
`summary.json`, `summary.md`, plus the probe's `light_verb_probe.py`, `light-verb-probe.json`,
`light-verb-importtime.log`, `light-verb-importtime-top.txt`) is **not committed** — ~8.6 MB of
host-specific paths and binary profiles; this record carries the text evidence.

Caveats:

- Machine load and the filesystem/compile caches dominate the spread: this run's baseline warm-up
  (21680.6 ms) and its `001` sample (22193.4 ms) sit an order of magnitude above the other four
  samples, and the candidate's `001` (2979.0 ms) is twice its median; the light verb's first probe
  sample (1373.6 ms) shows the same pattern. Read medians with their ranges, and compare only runs
  taken under the same conditions — the alternating schedule spreads drift across both subjects,
  and the committed baseline's figures (a different day) are cited above, not merged.
- `pre_pi_remainder_ms` is a derived estimate (`elapsed_ms − pi_main_total_ms`): process
  spawn/exec, Python up to the exec handoff, Node boot to Pi's `main()`, Pi's fixed 150 ms
  benchmark settle and the harness's observation latency — never a measured phase.
- `PI_OFFLINE=1`: Pi's startup network operations are disabled; the numbers describe an offline
  start.
- The census records what Node's loader resolves; modules jiti evaluates itself (perk's own
  TypeScript extension files) do not appear — the candidate census lists no `extension/` file.
- The detached-runner boundary: legs B and D prove the parent-side launch paths under the bridge;
  the runner's own module graph (pi-subagents' peer preload; perk's bridge `unsupported:embedded-host`
  there by design) was not censused — a `NODE_OPTIONS` child census is possible and out of scope.
- The −45 % prototype figure is an ad-hoc, pre-objective, Pi-only probe from the maintainer's
  untracked memo; the harness's −50.4 % is `pi_main_total_ms` over five-sample medians under
  `PI_STARTUP_BENCHMARK=1`. They are set side by side as two numbers with two provenances.
- The baseline's `.pi/npm` was staged by hard-link clone from the main checkout (the same
  consumer versions the candidate has: `pi-subagents` 0.70.1, `pi-web-access` 0.30.0 — the
  `consumer packages` lines in `summary.md` agree), the state the committed baseline's plan-worktree
  subject also had; the physical files are shared inodes at distinct paths, and the census records
  paths.
- The live pass ran in a session whose other legs (C, E, F) had already exercised the bridge's
  lazy paths before the operator's pre-reload `/perk-selfcheck`; the selfcheck reports the install
  state the extension recorded at load, which those calls do not alter.
