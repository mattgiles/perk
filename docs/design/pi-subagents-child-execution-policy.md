# Native child execution policy and scratch identity

**Accepted policy; profiles, restriction producer and consumer implemented.** Approval status is
recorded only in the pointer below. The consumer adds bounded advisory scratch identity and an
independent runner-only read-only floor, including a full-allowlist tool-call backstop. Source and
ordinary offline regressions corroborate this bounded implementation; they do not extend the
historical native measurements or certify a universal foreground/background sandbox.
The [characterization archive](archive/pi-subagents-child-capability-characterization.md)
contains the protocol, native outcomes, historical failures, exact disposable sources and
independent teardown. Experiment approval is not approval of these selections.

## Approval pointer

**Accepted by owner merge.** Owner `mattgiles` accepted PR #2231's unchanged published head
`a45e437c3be3da9f0e57e9caaa2808978bfc4516` by merging it at `2026-09-06T15:03:37Z`,
merge commit `de133aeb26d74b95f16a699b3a88cd757344251b`, and confirmed acceptance during
implementation planning. There were no formal PR reviews or discussion comments and no separate
local commit/blob attestation. Historically the owner authorized draft publication for review,
not the originally planned pre-submit local approval; publication itself was not approval.
Neither checkpoint `bfb6a09c` nor `b5dd31ef` is approval.

## Consumer source/offline reconciliation

Implementation reference: `9b2613af3177606e9d7313a929e33ed50ca73ddc` (plan #2234).
This is bounded source/offline corroboration, not new native execution evidence. Normal worktree
setup (`uv sync --all-packages && npm ci`) succeeded without manifest/lockfile changes. The
worktree-resolved roots and actual installed versions were:

| Package | Resolved root | Version |
| --- | --- | --- |
| Pi coding agent | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/node_modules/@earendil-works/pi-coding-agent` | 0.85.1 |
| Pi AI | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/node_modules/@earendil-works/pi-ai` | 0.85.1 |
| Pi TUI | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/node_modules/@earendil-works/pi-tui` | 0.85.1 |
| Pi server | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/node_modules/@earendil-works/pi-server` | 0.85.1 |
| Pi client | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/node_modules/@earendil-works/pi-client` | 0.85.1 |
| pi-subagents | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2234/.pi/npm/node_modules/pi-subagents` | 0.66.0 |

`npm ls @earendil-works/pi-ai @earendil-works/pi-coding-agent @earendil-works/pi-tui @earendil-works/pi-server @earendil-works/pi-client`
passed with all five local 0.85.1 pins. Node was 26.3.0. Relevant source—not version equality—was
checked: Pi's `AgentSession._buildRuntime`/`_refreshToolRegistry`/`setActiveToolsByName` rebuild
from the loader before startup, `bindExtensions` emits startup, and `reload` tears down the old
activation and reconstructs the loader prompt before startup. `DefaultResourceLoader` retains
its replacement prompt source. In pi-subagents, `buildInProcessChildLaunch` retains its first-line
prefix and four XML escapes, `childProcessEnv` remains runner-only, the background runner stamps
`SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD"`, and `createDefaultChildSessionFactory` applies the
packet through loader/startup while retaining the replacement prompt. No private production
imports or installed-source changes were introduced.

Focused command outcomes (detailed execution belongs to the normal PR validation summary):

- `node --test extension/substrate/childIdentity.test.ts extension/substrate/childRestrictions.test.ts extension/substrate/toolGating.test.ts extension/substrate/agentScratch.test.ts extension/session/lifecycle.test.ts extension/importDirectionGuard.test.ts extension/surfacesGuard.test.ts extension/waves/reportWave.test.ts extension/waves/reportWaveRpc.test.ts`:
  **166 passed, 0 failed, 0 skipped**.
- `node --test extension/sessionLifecycle.test.ts extension/pi/v1/waveIsolation.test.ts extension/vendor/btw/btw.test.ts extension/waves/childExecutionCompat.test.ts`:
  **64 passed, 0 failed, 0 skipped**. The installed compatibility test actually executed, including
  real escaped-prefix→Perk-parser and true/false binding→Perk-decoder checks; clean CI still has
  its honest missing-install skip. Mandatory SDK wiring tests do not depend on that optional install.
- `uv run pytest tests/test_subagent_agents.py tests/test_repo_local_agents.py -q`:
  **24 passed**; definitions/tool inventories unchanged.
- Configured `run_ci` checks `lint-js,typecheck-js`: **passed**. Iteration corrected a partial
  TypeScript test-context assertion and a scratch fixture that navigated to its already-current
  leaf (which emits no tree event); neither was an installed-engine incompatibility.

The final run-all CI result is recorded in the PR validation summary. No model-backed/native
probe ran. No new raw-byte hash ledger or transcript archive was created. Full-baseline doctor
stamp, stale-error fingerprints, historical native failures and Phase-2 waivers remain unchanged.

## 0.66.0 source/offline reconciliation

**Historical producer record.** The following C1–C6 context, hashes, commands, outcomes and earlier
iteration diagnostics are retained verbatim. Its pending-consumer statements describe that
checkpoint, not today's implemented consumer; its trailing-evidence procedure is not a new
requirement for consumer changes.

This is bounded compatibility evidence for the implemented profiles/producer, not a second
approval attestation or full-baseline certification. No installed source or fingerprint was changed.

### Context

| Field | Value |
| --- | --- |
| UTC check time (before → after) | 2026-09-06T17:40:45.346Z → 2026-09-06T17:41:18.126Z |
| Full checked Perk commit (C1) | `3d1d9bda1fc7229484a7d843e97f6bb9bca3c852` |
| Real checkout cwd | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232` |
| Node version | `v26.3.0` |
| Real installed engine root (before = after) | `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232/.pi/npm/node_modules/pi-subagents` |
| Actual package name/version (before = after) | `pi-subagents` / `0.66.0` |
| git status --short before (C2-before) | clean (empty output) |
| git status --short after (C2-after) | clean (empty output) |
| Test reporter environment | `NODE_OPTIONS=--test-reporter=tap` exported for C4–C6 only |

The implementation/code/tests/definitions were committed before C1. This evidence is a trailing
documentation-only update. Further code/test/definition edits require repeating C1–C6 before final CI.

### Source census

SHA-256 is over raw file bytes, lowercase full hexadecimal (no newline normalization, Git blob
IDs or truncated digests). The package root was resolved with `realpathSync`. Root, version and
all nine digests agreed before/after. These are provenance facts, not production allowlist hashes.

| Engine-relative path | SHA-256 before | SHA-256 after |
| --- | --- | --- |
| `package.json` | `e9b166c2287a3938206fc1824226ca1cf137eb1b0a3da6f988a2bb9b74e28faf` | `e9b166c2287a3938206fc1824226ca1cf137eb1b0a3da6f988a2bb9b74e28faf` |
| `src/agents/agents.ts` | `f19b5b33dc24911d932a6ce3135b3d2f0e7733b28aecf4c568062f76b9f51bc5` | `f19b5b33dc24911d932a6ce3135b3d2f0e7733b28aecf4c568062f76b9f51bc5` |
| `src/runs/foreground/subagent-executor.ts` | `532eb27e4e0977776d7f93cd34c7b6a660ae0f1e0d1eb6452b96eebb89c3b8f4` | `532eb27e4e0977776d7f93cd34c7b6a660ae0f1e0d1eb6452b96eebb89c3b8f4` |
| `src/runs/foreground/execution.ts` | `5e0f5005cd1fb98d1c31ad8fef08e4e79806bba71c4248ae96d80b16e2428846` | `5e0f5005cd1fb98d1c31ad8fef08e4e79806bba71c4248ae96d80b16e2428846` |
| `src/runs/shared/child-launch.ts` | `32133511f0969ae279102c4aa20186d79f6466cbb2e0f6b80dec6042f6c0ddc8` | `32133511f0969ae279102c4aa20186d79f6466cbb2e0f6b80dec6042f6c0ddc8` |
| `src/runs/shared/child-tool-plan.ts` | `54f8dffbfb4c7a82fd89e0e51ff33098e57c58628bdffe4e18b8db00d0dc6415` | `54f8dffbfb4c7a82fd89e0e51ff33098e57c58628bdffe4e18b8db00d0dc6415` |
| `src/runs/shared/extension-bindings.ts` | `55bf824caa684eb49be04ba3760325b19ee5cee8f01a6082be4ba530fe26c8d2` | `55bf824caa684eb49be04ba3760325b19ee5cee8f01a6082be4ba530fe26c8d2` |
| `src/runs/shared/child-session.ts` | `5d97d6789395309b6470ecbaa58e4c3ce19c5b570ecbe2aa4dfcac9d77cdc1d7` | `5d97d6789395309b6470ecbaa58e4c3ce19c5b570ecbe2aa4dfcac9d77cdc1d7` |
| `src/workflows/scripted-workflow.ts` | `b9bd92cba0c71481aab5d611a36f91452b0a7944aeeb444b87a4896896a041c1` | `b9bd92cba0c71481aab5d611a36f91452b0a7944aeeb444b87a4896896a041c1` |

### Semantic checks

| Mechanism | Source symbol/structural anchor | Result | Evidence |
| --- | --- | --- | --- |
| Root scheduling / definition default / omitted-async awaiting | `subagent-executor.ts`: root `async: _workflowAsync` / `async: _async` extraction; `prepareWorkflowLaunchParams`, `applySingleAgentLaunchDefaults`, effective `requestedAsync` resolution, `waitForWorkflowAsyncSingleResult` | corroborated | C4: real preparation plus the installed private default function type-stripped/evaluated in memory proves opposing defaults. Source trace establishes awaited background routing; no live child-mode measurement. |
| Definition context / skill / extension parsing | `agents.ts::loadAgentsFromDefinitionFiles`: `defaultAsync`, `systemPromptMode`, `inheritGlobalContext`, project/skill fields, `skillPath`, `extensions`, `subagentOnlyExtensions` | corroborated | C4 real project discovery/parser on test-owned copies of canonical report/writer definitions; source inspection for explicit skillPath parsing. Closed ten-report/eleven-role census and model/skill exception pins are in ordinary Python tests. |
| Runner-only binding normalization / delivery | `extension-bindings.ts::normalizeExtensionBindings` / `encodeExtensionBindings`; `child-launch.ts::childProcessEnv` / `buildInProcessChildLaunch`; `child-tool-plan.ts::resolvePiLaunchToolPlan` | corroborated | C4 tests exact true/false normalization, runner processEnv, parent absence and runner-only ambient discovery. Source inspection confirms omitted versus empty/explicit extension selection. |
| Writer actual cwd / discovery | `subagent-executor.ts`: `discoverWorkflowAgents(childCwd, ...)` and child launch preparation; `execution.ts::runSyncCompletionInner` / `preflightLaunchCwd`; `child-launch.ts::buildInProcessChildLaunch` | corroborated | C4 real discovery/preparation, both actual scripts validated, fake child receives actual cwd; C6 each owning renderer evaluates its own script and callers retain thin trusted-input checks. Not autonomous prompt-following evidence. |
| Blocking-workflow cancellation | `scripted-workflow.ts::validateWorkflowScript` / `runWorkflowScript` childController and launch signal; blocking executor `workflowSignal` handoff; `execution.ts::runSync` origin forwarding, abortChild/finish; `child-session.ts::ChildSessionFactory` and abort/dispose contract | corroborated | C4 PR-rebase script only: pre-aborted starts no child; in-flight prompt is held until abort, settles non-completed, and disposes. Real workflow/runSync with injected launch adapter and per-call fake factory; native session abort/dispose implementation is source inspection only, not another live writer/root-scheduling PASS. |

### Commands and disposition

Executed from the checkout root in this order: C1, C2-before, C3-before, C4, C5, C6,
C3-after, C2-after. C3 is the identical read-only inline command shown below (not a checked-in
command surface). Shell stdout capture redirects used the run-scoped disposable directory
`.perk/workflow/scratch/runs/01M1VVK0HGGEJEKMZ8MP60054Q/agent/`: C1/C2 to their named `.txt` files, C3 to named `.json` files;
C4–C6 to named `.tap` files with `2>&1`, with each exit code captured immediately afterward.
The durable evidence is reproduced here, not delegated to those disposable files.

| ID | Exact command | Exit code | Pass/fail/skip totals | Evidence excerpt |
| --- | --- | --- | --- | --- |
| C1 | `git log -1 --format=%H` | 0 | n/a | `3d1d9bda1fc7229484a7d843e97f6bb9bca3c852` |
| C2-before | `git status --short` | 0 | n/a | empty: clean |
| C3-before | identical C3 Node snippet below | 0 | n/a | full JSON below |
| C4 | `node --test extension/waves/childExecutionCompat.test.ts` | 0 | 6 / 0 / 0 | actual installed engine executed; TAP totals below |
| C5 | `node --test extension/waves/reportWave.test.ts extension/waves/reportWaveRpc.test.ts` | 0 | 73 / 0 / 0 | TAP totals below |
| C6 | `node --test extension/pi/v1/delivery/submit.test.ts extension/pi/v1/delivery/stackSync.test.ts` | 0 | 77 / 0 / 0 | TAP totals below |
| C3-after | identical C3 Node snippet below | 0 | n/a | full JSON below; same root/version/digests |
| C2-after | `git status --short` | 0 | n/a | empty: clean |

**C3 command (both executions):**

```bash
node --input-type=module <<'JS'
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
const root = realpathSync('.pi/npm/node_modules/pi-subagents');
const files = [
  'package.json',
  'src/agents/agents.ts',
  'src/runs/foreground/subagent-executor.ts',
  'src/runs/foreground/execution.ts',
  'src/runs/shared/child-launch.ts',
  'src/runs/shared/child-tool-plan.ts',
  'src/runs/shared/extension-bindings.ts',
  'src/runs/shared/child-session.ts',
  'src/workflows/scripted-workflow.ts',
];
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
console.log(JSON.stringify({
  checkedAt: new Date().toISOString(), cwd: realpathSync('.'),
  node: process.version, root, name: manifest.name, version: manifest.version,
  sources: files.map(path => ({
    path,
    sha256: createHash('sha256').update(readFileSync(join(root, path))).digest('hex'),
  })),
}, null, 2));
JS
```

**C3-before JSON (verbatim):**

```json
{
  "checkedAt": "2026-09-06T17:40:45.346Z",
  "cwd": "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232",
  "node": "v26.3.0",
  "root": "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232/.pi/npm/node_modules/pi-subagents",
  "name": "pi-subagents",
  "version": "0.66.0",
  "sources": [
    {
      "path": "package.json",
      "sha256": "e9b166c2287a3938206fc1824226ca1cf137eb1b0a3da6f988a2bb9b74e28faf"
    },
    {
      "path": "src/agents/agents.ts",
      "sha256": "f19b5b33dc24911d932a6ce3135b3d2f0e7733b28aecf4c568062f76b9f51bc5"
    },
    {
      "path": "src/runs/foreground/subagent-executor.ts",
      "sha256": "532eb27e4e0977776d7f93cd34c7b6a660ae0f1e0d1eb6452b96eebb89c3b8f4"
    },
    {
      "path": "src/runs/foreground/execution.ts",
      "sha256": "5e0f5005cd1fb98d1c31ad8fef08e4e79806bba71c4248ae96d80b16e2428846"
    },
    {
      "path": "src/runs/shared/child-launch.ts",
      "sha256": "32133511f0969ae279102c4aa20186d79f6466cbb2e0f6b80dec6042f6c0ddc8"
    },
    {
      "path": "src/runs/shared/child-tool-plan.ts",
      "sha256": "54f8dffbfb4c7a82fd89e0e51ff33098e57c58628bdffe4e18b8db00d0dc6415"
    },
    {
      "path": "src/runs/shared/extension-bindings.ts",
      "sha256": "55bf824caa684eb49be04ba3760325b19ee5cee8f01a6082be4ba530fe26c8d2"
    },
    {
      "path": "src/runs/shared/child-session.ts",
      "sha256": "5d97d6789395309b6470ecbaa58e4c3ce19c5b570ecbe2aa4dfcac9d77cdc1d7"
    },
    {
      "path": "src/workflows/scripted-workflow.ts",
      "sha256": "b9bd92cba0c71481aab5d611a36f91452b0a7944aeeb444b87a4896896a041c1"
    }
  ]
}
```

**C3-after JSON (verbatim):**

```json
{
  "checkedAt": "2026-09-06T17:41:18.126Z",
  "cwd": "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232",
  "node": "v26.3.0",
  "root": "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2232/.pi/npm/node_modules/pi-subagents",
  "name": "pi-subagents",
  "version": "0.66.0",
  "sources": [
    {
      "path": "package.json",
      "sha256": "e9b166c2287a3938206fc1824226ca1cf137eb1b0a3da6f988a2bb9b74e28faf"
    },
    {
      "path": "src/agents/agents.ts",
      "sha256": "f19b5b33dc24911d932a6ce3135b3d2f0e7733b28aecf4c568062f76b9f51bc5"
    },
    {
      "path": "src/runs/foreground/subagent-executor.ts",
      "sha256": "532eb27e4e0977776d7f93cd34c7b6a660ae0f1e0d1eb6452b96eebb89c3b8f4"
    },
    {
      "path": "src/runs/foreground/execution.ts",
      "sha256": "5e0f5005cd1fb98d1c31ad8fef08e4e79806bba71c4248ae96d80b16e2428846"
    },
    {
      "path": "src/runs/shared/child-launch.ts",
      "sha256": "32133511f0969ae279102c4aa20186d79f6466cbb2e0f6b80dec6042f6c0ddc8"
    },
    {
      "path": "src/runs/shared/child-tool-plan.ts",
      "sha256": "54f8dffbfb4c7a82fd89e0e51ff33098e57c58628bdffe4e18b8db00d0dc6415"
    },
    {
      "path": "src/runs/shared/extension-bindings.ts",
      "sha256": "55bf824caa684eb49be04ba3760325b19ee5cee8f01a6082be4ba530fe26c8d2"
    },
    {
      "path": "src/runs/shared/child-session.ts",
      "sha256": "5d97d6789395309b6470ecbaa58e4c3ce19c5b570ecbe2aa4dfcac9d77cdc1d7"
    },
    {
      "path": "src/workflows/scripted-workflow.ts",
      "sha256": "b9bd92cba0c71481aab5d611a36f91452b0a7944aeeb444b87a4896896a041c1"
    }
  ]
}
```


**C4 TAP totals (verbatim):**

```text
# tests 6
# suites 0
# pass 6
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 3912.256875
```

**C5 TAP totals (verbatim):**

```text
# tests 73
# suites 0
# pass 73
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 636.481583
```

**C6 TAP totals (verbatim):**

```text
# tests 77
# suites 0
# pass 77
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 8716.6665
```

**Earlier iteration diagnostics (retained, not a failed recorded C1–C6 attempt):**

- The first ordinary C4-suite run used a test-authored interop view `valid` rather than the
  installed validator's real `ok` field. Exit 1; decisive diagnostic:
  `AssertionError [ERR_ASSERTION]: []`, `actual: undefined`, `expected: true`.
  Its verbatim totals were:

```text
ℹ tests 6
ℹ suites 0
ℹ pass 4
ℹ fail 2
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 4872.104708
```

  Corrected the test's field name after rereading the installed return interface. Imports,
  default preparation, binding construction and both cancellation cases had passed; no engine
  incompatibility, install, alias repair, execution-mode fallback or source patch was involved.
- Python live prompt parity initially rejected single-quoted YAML fixture values:
  `Error: perk miniYaml: single-quoted strings are not supported`; `1 failed, 58 passed`.
  The fixture was corrected to double-quoted strings with escaped JSON quotes, preserving the
  frozen grammar. Focused prompt grammar/render/live parity then passed (35 tests).
- Normal `uv run perk init` converged all ten managed agent mirrors, then exited 2 on
  `skills update --sync` conflicts in the existing materialized skills. No skills repair or
  unrelated convergence changes were included. The only managed-state delta is the intended
  agent-directory digest. Agent/mirror, repo-local, managed-state, init-idempotence and packaging
  suites passed: 155 tests. This is not a claim that the unrelated skills sync succeeded.

Additional focused validation: all configured JS tests and JS/Python lint passed; configured JS
typecheck passed. Consumer census suites passed (147 tests), and warm composition plus C4 passed
(13 tests). Both opt-in prose gates passed (553 Python tests, 364 Node tests and frontend build).
There are no matching conflict-template scenario variables in the prose-map registry; its generated
projection stayed current without hand-edited counts.

**Disposition: source/offline corroborated.** Mandatory checks executed and passed with unchanged
installed sources; C4 did not skip. No new live run; historical native evidence remains
pi-subagents 0.65.1; full-baseline doctor stamp unchanged; full restriction behavior also requires 3.3.

## Implemented repair: current-parent read-only restrictions

The cold claimed-parent R/E measurements remain valid, but do not establish warm inheritance.
The in-scope `/objective-plan` warm door calls `gating.enter(ctx)`, which appends parent branch
mode without updating a handoff. Fresh children instead take `handoff.mode` in `decideClaim`,
or mint without a mode when no inherited env identity exists. Thus a warmed read-only parent
can produce a child with stale read-write handoff mode or no mode. This is a source-established
gap, **not a newly executed case**.

The owner approved expanding the decision/consumer scope for this gap at
**2026-09-06T14:36:56.574Z**, session response `44ba3dfb`; canonical plan #2230 records the
clarification. No additional native probe or production prototype is authorized in this node.
The following is the **source-derived repair**, now implemented in both producer and consumer
and exercised by ordinary offline regressions—not a measured native warm-path PASS.

### Separate restriction channel

- **Producer:** the Perk-owned ReportWave renderer, for every child of every report attempt.
  `index.ts` supplies a live `() => gating.isActive()` callback to the wave composition.
  Sample it after asynchronous assignment preflight, immediately before rendering/spawning
  each attempt; never cache the value at extension startup or accept it from assignment/task
  data. A failed snapshot fails the wave without spawning. The public ReportWave caller
  interface stays unchanged.
- **Wire:** child `extensionBindings` has namespace **`perk.parent-restrictions/1`**, whose
  value is exactly **`{"readOnly": boolean}`**, with no additional fields. Always send the
  namespace, including false. No agent name, run id, stage or write grant belongs in it.
  The native runner exposes the canonical bounded JSON through
  `PI_SUBAGENT_EXTENSION_BINDINGS`; S-B proved this transport generically. This namespace's
  new gate effect was not exercised live.
- **Consumer:** a separate `extension/substrate/childRestrictions.ts` boundary, composed in
  `index.ts` before initial gate synchronization and any model turn. Only a runner-hosted
  child (`PI_SUBAGENT_CHILD === "1"`) consumes it; foreground/parent activations ignore this
  environment carrier. It is not a source of agent identity.
- **Decode:** bound the raw envelope to 16 KiB before JSON parsing. Require an object envelope;
  unrelated namespaces are ignored. Require the reserved value to have exactly one own
  boolean `readOnly` field. Invalid JSON/envelope, an invalid reserved value, or an unsupported
  version in the `perk.parent-restrictions/` family produces a read-only floor plus a bounded
  once-per-session warning, never a permissive default. An absent envelope/namespace is legacy
  input: no new floor and no claim of repaired warm inheritance. Both producer and consumer
  must be installed before this record's full report profile is realized.
- **Monotone effect:** true establishes a child-session read-only **floor**; false adds no
  restriction and is **not evidence of write authority**. Effective gating is the existing
  branch read-only mode **OR** this floor. Within the child activation, no later false/missing
  input, `exit()`, branch navigation or child mode append may clear a captured floor.
  Unknown/forged true can only restrict.
- **State/lifetime:** capture per extension activation and full SDK session identity, not in
  process-global mutable state. Preserve the existing claim/adopt/mint result and errors;
  apply the floor even when the handoff is absent or stale. Reflect a true restriction as
  read-only child branch mode where state establishment succeeds, but do not rely on that
  append for enforcement: a persistence failure remains loud and cannot open the gate or
  enable scratch. Never mint a replacement identity to hide a linkage failure, change stage,
  or rewrite/consume the parent's handoff. Normal reload recaptures the original native packet
  and preserves any existing branch read-only restriction. There is no invented durable copy
  of an unpersisted floor: loss/tampering of both packet and state is outside the repaired
  profile, not a claimed protected reload. A new physical session does not inherit an old
  activation's cached floor.
- **Scratch:** both scratch hooks consult effective read-only gating before advisory identity,
  including the floor even if a mode append failed. `/btw` retains its existing effective-gate
  check. The restriction reader and identity reader cannot grant authority to one another.

### Consumer failure and lifetime rules

The decoder checks at most 16384 UTF-8 bytes before standard `JSON.parse`. Undefined is legacy
absence; empty/whitespace, primitive/null/array envelopes, invalid v1 values and unsupported reserved
family versions are restrictive. Every own `perk.parent-restrictions/` key is inspected, so an
unsupported version cannot hide beside valid v1. Unrelated namespaces remain opaque. V1 has exactly
one own boolean `readOnly`, with no extra fields or coercion. Non-runner captures do not even read
the packet. An unreadable key or envelope in a runner capture also establishes a floor.

Both readers share only the neutral stateless `{sessionId, sessionFile}` key helper and startup's
runner boolean. Full SDK UUID/path (or null), not persisted basename or Perk run id, distinguishes
physical sessions. Advisory capture replaces its snapshot; lookup reads only the current key,
never prompt/env. Key mismatch gives stale advice with captured runner fallback. Restrictions OR
same-key captures, including changed runner/packet values. A positively different known key starts
a fresh floor; an unreadable key retains the last known comparison key. A never-keyed anonymous
floor carries to the first readable key because recovery is not proof of a different session.
There is no isolation claim while SDK key access is broken.

Known-key finite reason buckets survive same-key retries and reset on positively different-key
capture. Unreadable-key warnings use a separate anonymous activation-local reason set, retained
through readable recovery and cleared only on shutdown/discard. Stale advice warns in the captured
snapshot's scope. Warn only for unavailable runner identity or invalid runner restrictions, with
fixed `report(..., {alsoLog: true})` messages—never raw prompts/names/bindings or thrown payloads.
Shutdown clears both controllers. No process-global identity/floor, unbounded key map or durable
floor field is introduced.

`reflectSessionReadOnlyFloor` follows unchanged identity establishment. Unclaimed/already-read-only
outcomes append nothing; established non-read-only outcomes get one verified mode-only append
under `child restriction` scope. Applied changes only resolved mode; rejected/unverified returns
the honest original outcome and relies on the classified append's loud report. A throw escaping
`appendVerified` is caught only around that call and returned as `unexpectedFailure: true` with
the original outcome. The Pi edge reports the fixed error `could not persist child read-only
restriction; in-memory restriction remains active` once for that operation, with `alsoLog: true`,
and continues gate sync and remaining startup work. No retry, fabricated linkage problem or
replacement mint. Keep still does no version backfill; separate mode reflection is its documented
write-free-startup exception. Neither reader rewrites/consumes the parent handoff.

The deliberate gate hardening applies to **all effective read-only sessions**, including parents:
`tool_call` rejects every tool outside the existing `READ_ONLY_TOOLS` set even when snapshot or
toolset installation fails, including save/delivery and unknown/late foreign mutators. `edit` and
`write` retain their denial wording; listed bash retains its existing argument check; other listed
tools pass this gate but keep downstream checks. All gate observations OR in the floor; supplier
exceptions are restrictive. A floor-backed `exit()` skips the read-write append and reapplies the
gate even after reflection failure. Ordinary no-floor transitions, inventories and bash patterns
are unchanged. Allowlisted delegation, browser, web and artifact exceptions remain bounded posture
choices, not an OS sandbox. `/btw` and ReportWave use the same effective `gating.isActive()` supplier.

This is a spawn-time restriction snapshot, not continuous permission revocation. A later parent
mode change does not reopen a restricted child or retroactively restrict a child launched
without a floor; normal cancellation remains available. Public/manual subagent calls outside
Perk's code-owned ReportWave producer are not certified by this channel. It is not an operating-
system sandbox or authentication between malicious host extensions.

Producer wiring/serialization and strict consumer decoding, the monotone floor in `toolGating.ts`,
startup wiring and effective-gate scratch checks are implemented. Ordinary regressions cover:
warm parent without `PERK_RUN_ID`/handoff; warm read-only over a stale read-write handoff; each
retry sampling the current gate; false preserving an inherited read-only mode; true surviving
exit/tree changes and failed state persistence; malformed/version-skew packets; unchanged
parent/sibling gates; and all ten report assignments carrying the reserved namespace. No warm
native result is invented, and no new policy decision is deferred to those implementation nodes.

## 1. Evidence boundary and terms

The exercised Perk code is `5dd1cc2a26dbecdc715b72a4cf16f95b4705b62a`; the later commits
contain documentation only. The measured composition is Node 26.3.0, pi-subagents 0.65.1,
and the five repo-local Pi packages at 0.85.1. The engine remains unpinned; the five exact
dev pins remain unchanged. This is not certification of global/consumer installations.

- **Workflow scheduling** decides whether the parent waits for an enclosing workflow call.
  It does not determine its children's execution mode.
- **Child mode** is foreground (native session in the parent process) or background (native
  session in a detached runner).
- **Agent identity** names a resolved agent. **Perk run identity** identifies workflow data.
  Neither an agent name nor a Perk run id grants write authority or a launched stage.
- **Advisory identity** below is a source-bound prompt claim used only for scratch policy,
  not authenticated provenance or a security principal.

R/S/E measured the objective-explorer capability shape; W measured conflict-resolver's shape.
Other report roles are **representative-derived**, not individually run. Model defaults,
fallbacks, Ponytail variants, autonomous reviewer rubrics and real rebase/push procedures were
not all exercised. W was intentionally cancelled, not certified as a successful production
resolver task. The eight intended cases used eleven authorized launches including historical
failures, plus the single B0 smoke; that budget is exhausted.

The [closed matrix](archive/pi-subagents-child-capability-characterization.md#closed-matrix-classifications)
is the capability authority. R-F lacks inherited Perk enforcement; S-B reproduces missing
report-only scratch suppression; both W modes support the measured writer operations and
cancellation. E proves explicit loading only under read-only parents and **cannot authorize
any explicit-Perk-list production profile**. Phase-2 waived streaming legs remain waived.

## 2. Closed role and consumer census

`src/perk/convergence/init/agents.py::PERK_AGENTS` owns ten delivered definitions. Nine are
reports and one is the writer. The separately owned repo-local auditor adds one report:
**8 non-streaming reports + 2 streaming reports + 1 writer = 11 roles**. Every included role
appears exactly once below. `agents/<stem>.md` is canonical for delivered roles;
`.pi/agents/perk/<stem>.md` is its byte-identical managed copy.

| Role | Family / selected child mode | Owning launch source | Primary consumer regression suite |
| --- | --- | --- | --- |
| `perk.pr-reviewer` | Non-streaming / background | `extension/waves/prReviewWave.ts` | `extension/waves/prReviewWave.test.ts` |
| `perk.review-classifier` | Non-streaming / background | `extension/waves/reviewClassifierWave.ts` | `extension/waves/reviewClassifierWave.test.ts` |
| `perk.objective-explorer` | Non-streaming / background | `extension/waves/objectiveExplorerWave.ts` | `extension/waves/objectiveExplorerWave.test.ts` |
| `perk.learn-analyst` | Non-streaming / background | `extension/learning/analystWave.ts` | `extension/learning/analystWave.test.ts` |
| `perk.harvest-analyst` | Non-streaming / background | `extension/learning/harvest.ts` | `extension/learning/harvest.test.ts` |
| `perk.dream-analyst` | Non-streaming / background | `extension/learning/dream.ts`, orchestrated by `extension/learning/dreamAnalysis.ts` | `extension/learning/dream.test.ts`, `extension/learning/dreamAnalysis.test.ts` |
| `perk.dream-reducer` | Non-streaming / background | `extension/learning/dreamReducer.ts`, orchestrated by `extension/learning/dreamAnalysis.ts` | `extension/learning/dreamReducer.test.ts`, `extension/learning/dreamAnalysis.test.ts` |
| `perk-dev.session-auditor` | Non-streaming / background | `extension/learning/audit.ts`; definition `.pi/agents/perk-dev/session-auditor.md` | `extension/learning/audit.test.ts`, `extension/learning/auditorDef.test.ts`, `tests/test_repo_local_agents.py` |
| `perk.adversarial-reviewer` | Streaming / background | `extension/waves/adversarialReviewWave.ts` | `extension/waves/adversarialReviewWave.test.ts` |
| `perk.draft-reviewer` | Streaming / background | `extension/waves/draftReviewWave.ts` | `extension/waves/draftReviewWave.test.ts` |
| `perk.conflict-resolver` | Writer / foreground, both subprofiles | Submit/address: `extension/pi/v1/delivery/conflictResolverEngine.ts` through `resolve_submit_conflicts`; retained continuation: `stackSync.ts` + its continuation template | `conflictResolverEngine.test.ts`, `conflictResolverEngineCompat.test.ts`, `submitConflict.test.ts`, submit/address and stackSync suites; `extension/substrate/worktreeResolverLock.test.ts` |

Custom/Ponytail review lanes are invocation variants of the listed reviewers, not new agent
identities. Excluded: `perk-dev.analyst`, user/custom definitions, upstream builtins and external
CLI agents. The exclusion does not erase their explicit scratch fallback in §5. A new
code-owned role is scope drift: reconcile this record before encoding it, never classify it
by a name heuristic.

### Preserved model and skill exceptions

Keep `[models.subagents]` lookup and model selection unchanged (workflow-level for reports and
retained continuation; native request-level for submit/address), including the
`inherit` sentinel and thinking suffix. Keep every canonical default/fallback list; these are
source facts, not claims that each model was tested:

| Role stem | Default → ordered fallback |
| --- | --- |
| `pr-reviewer`, `learn-analyst`, `conflict-resolver` | `anthropic/claude-sonnet-4-5` → `anthropic/claude-haiku-4-5` |
| `review-classifier`, `objective-explorer` | `anthropic/claude-haiku-4-5` → `anthropic/claude-sonnet-4-5` |
| `harvest-analyst`, `dream-analyst` | `openai/gpt-5.6-terra` → `openai/gpt-5.6-luna` |
| `dream-reducer`, `adversarial-reviewer` | `anthropic/claude-fable-5` → `anthropic/claude-sonnet-4-5` |
| `draft-reviewer` | `openai/gpt-5.6-sol` → `openai/gpt-5.6-terra` |
| `session-auditor` | `openai/gpt-5.6-luna` → `openai/gpt-5.6-terra` |

Preserve source-bound Ponytail `skillPath` declarations: `ponytail-review` for pr-reviewer and
adversarial-reviewer, `ponytail` for draft-reviewer, under the project-installed
`@dietrichgebert/ponytail` package. `extension/waves/ponytail.ts` retains exact-source preflight,
lane-local failure and no same-named global/project fallback. An explicit assignment skill is
not discovered-skill inheritance. No other role gains an explicit skill or extension.

## 3. Selected execution profiles

| Dimension | All ten report roles | Conflict resolver, both subprofiles |
| --- | --- | --- |
| Child mode | Background | Foreground |
| Encoding | Canonical definition `async: true`; child-call `async` **absent** | Submit: native foreground-only structured delegation; retained: child-call `async: false`. Definition default remains omitted |
| Workflow scheduling | Existing `async: true` ReportWave transport | Submit: no workflow wrapper; retained: top-level `async: false` one-child workflow |
| Conversation | Existing fixed top-level `context: "fresh"` inherited by children | Submit: request `context: "fresh"`; retained: explicit top-level fresh context |
| Project context | `inheritProjectContext: false` | `inheritProjectContext: true` |
| Global context | `inheritGlobalContext: false` | `inheritGlobalContext: false` |
| Discovered skills | `inheritSkills: false` | `inheritSkills: true` |
| Base prompt | Preserve `systemPromptMode: replace` and role rubric | Preserve `systemPromptMode: replace` and both resolver rubrics |
| Extensions | Omit `extensions` and `subagentOnlyExtensions`; use ambient runner discovery | Omit both fields; foreground has no ambient discovery |
| Mission / acceptance | Fixed `mission: false` and existing `WAVE_ACCEPTANCE` (`level: none`) | Submit request omits both; native bridge disables acceptance. Retained keeps existing omissions/native defaults |
| Required tools | `read`, `grep`, `find`, `ls`, `bash`, engine `structured_output` | `read`, `grep`, `find`, `ls`, `bash`, `edit`, `write`; submit additionally uses engine-owned `structured_output` |
| Supervisor | Optional capability with the rules below | Optional; absence cannot change mode or authority |
| Actual cwd | Trusted calling session's cwd via the native RPC context | Explicit child `cwd` from the validated dispatch worktree |

**Why this split:** background reports preserve required ambient Perk/provider behavior and
inherited cold-parent enforcement that R-F loses. Warm-parent restriction and named scratch
suppression require **both implemented producer and consumer**, not the profile encoding alone.
The consumer's ordinary offline coverage is not a new native-mode PASS.
Foreground writers preserve the measured builtins, real cwd and project/skill inheritance while avoiding an unproven cross-cwd Perk handoff.
This is a fixed policy choice, never a failure-triggered mode fallback.

A1's encoding is mandatory. The installed `prepareWorkflowLaunchParams` sets
`workflowAwaitAsync: true` for an omitted child `async`, then the definition selects background.
Explicit child `async: true` instead returns detached-launch semantics and must not be substituted
for the omission. Do not expose that private await flag in Perk payloads or add a collector.
The release's `workflow-launch-params.test.ts` corroborates this distinction; R/S/E exercised it.

Node 3.2 implements `async: true` to the **nine delivered report definitions and the repo-local
auditor**, converges their managed copies, and tests the intentional renderer omission. It encodes
`async: false` and the actual `cwd` to the child item in **both** conflict templates. It makes
`inheritGlobalContext: false` explicit in the eleven definitions; that preserves the selected
resolved value rather than relying on a future engine default. Global context instructions
are distinct from skill discovery: writer skill inheritance includes the ordinary global/project
catalog, subject to the engine's mandatory removal of the orchestration skill. This never grants
nested-subagent tools. No `ReportAssignment`/`ReportWave` caller-interface expansion or generic
profile/agent registry is needed; the live restriction supplier is composition-internal.

### Submit foreground dispatch reconciliation

Submit/address now uses a code-owned domain interface and parameterless single-use authorization,
not the earlier model-authored workflow script. The loaded subagent tool's real package ancestry
anchors optional public preflight loading; no private execution import, global lookup, version pin
or fallback launcher exists. Public preflight checks the canonical unshadowed writer profile,
context/tool/extension policy and native model snapshot. Native foreground execution still owns
discovery; its `worktree` allocation default must be absent/false and unchanged since activation,
otherwise dispatch refuses for inspection/reload. No second worktree is allocated.

A canonical per-worktree Git-directory `perk-submit-conflict.lock` supplies cross-session/process
exclusion for participating submit/address resolvers. Exclusive creation, private token+inode
ownership, and conservative release/retention replace no other ownership protocol. Only a
correlated well-formed completed terminal (or a pre-launch refusal without start/update evidence)
proves release is safe after emission. Cancellation/no-ack/deadline has a bounded grace; uncertainty
retains the lock, including across exit/reload. Human recovery requires all writers and subprocesses
to be stopped, exact lock and rebase/index/HEAD inspection, then exact regular-file removal.
There is no automatic reclaim, model-callable unlock, retry, or late cleanup watcher.

The strict PR-mode terminal schema separates domain outcome, verification and push. Native
non-success never salvages a report. Only completed + passed + succeeded + successful lock release
returns resolved; the parent still calls canonical submit. Native bridge acceptance is disabled;
this record does not claim independent test or remote mergeability proof. Receipts expose only
whitelisted identity/status/preflight/lock evidence, never output, ownership secrets or invented
artifact paths. Summaries remain separately labeled untrusted DATA.

The retained-continuation path keeps its script, sentinel, consent, session claim, and no-push/no-
abort authority unchanged. The new execution lock neither retrofits that path nor fences arbitrary
manual Git. Offline characterization, real lock subprocess tests, and the installed bridge/runSync
fake-child compatibility suite are not live resolver certification. The historical native matrix,
full-baseline stamp and stale-error fingerprints below remain unchanged.

### Extension, provider and cwd boundaries

Reports run from the trusted parent project with normal Perk wiring. Cold handoff adoption
remains unchanged; warm parents use the additional restriction channel above rather than a
fictional handoff. The existing RPC context supplies the cwd deliberately; review-head worktree
paths remain **read-only task data**, not a runtime/agent/extension discovery root. No head-provided
agent definition, extension or setup command is loaded merely to review a PR. Preserve the
current explicit-source skill checks and native discovery; a missing/mismatched role or required
capability is a loud failure, never a switch to foreground.

Omitted, empty and explicit extension lists are not interchangeable. `extensions: []` disables
ambient loading; an explicit Perk list disables other ambient sources. Neither is selected.
The observer was diagnostic only and must not enter production definitions or payloads.

Foreground writers do **not** acquire Perk scratch, inherited Perk mode or ambient-extension-only
provider/MCP capabilities. Their native/global model configuration remains available, as W-F
proved for the configured `openai/gpt-5.6-luna`; this is not a provider-extension certificate.
A provider/extension composition requiring ambient child loading is outside this writer profile:
stop and re-verify/reconcile with the owner, not silently run background or drop the configured
model. Existing model configuration and declared model fallback lists are not rewritten by this
record; engine/provider errors remain loud.

### The two writer dispatch subprofiles

1. **PR rebase:** the source is `ctx.cwd` in the worktree-bound submit/address flow. Pass that
   absolute validated path as child `cwd`, not just `cd` prose. The existing resolver owns
   context fetch, rebase, verification and force-with-lease push; its PR-only abort behavior
   stays unchanged. `resolve_submit_conflicts` owns native foreground request/result handling and
   the worktree execution lock; parent re-submission still re-verifies mergeability.
2. **Retained continuation:** the source is the fresh, containment-validated
   `SyncConflictDispatch.worktree`, from the Python-owned continuation projection. Pass it as
   child `cwd`; preserve the retained-mode sentinel, explicit PR identity, in-progress-rebase
   checks, completed-only outcome gate, no push/no abort rule, claim lease and attempt cap.
   Publication remains the human's `objective_stack_sync {continue: true}` gesture.

Both require the existing authorized write-capable parent flow and exactly one writer per
worktree. Missing/ambiguous worktree or agent capability fails before mutation. Discovery occurs
at the actual target cwd; do not silently accept a conflicting/shadowed definition or install
new wiring inside an in-progress retained rebase to make discovery pass. Profile changes remain
in the prompt-authored dispatch; no code-owned dispatcher, rebase helper or authority migration.

The retained worktree does **not** automatically carry the caller's
`.perk/workflow/handoff/<PERK_RUN_ID>.json`. `cache.readHandoff` is cwd-local; `sync.py` creates
an isolated detached Git worktree, while the warm adapter only validates and injects guidance.
W-B explicitly linked the real consumed parent handoff into its separate fixtures. Selecting
background there as if that transport already existed would be fiction. **No cross-cwd handoff
copying, synthetic parent handoff or writer lifecycle transport is assigned to 3.2/3.3.**
Foreground is the measured writer profile that needs none of them. Its lack of Perk scratch
is part of the selected trade-off.

### Supervisor and cancellation limits

Non-streaming reports complete through their engine-validated structured report. Supervisor
absence, failed submission or no timely delivery is optional-capability degradation, not a
reason to retry/change mode or invalidate an otherwise valid report.

Streaming reviewers retain the Phase-2 contract: attempt nonempty finding batches when the
native tool is available; `streamed: true` means accepted/queued submission, not human-visible
delivery. No findings yields false without an empty batch; unavailable/partial streaming is
explained in `fyi`, and collection discloses completion-only findings. Preserve the existing
native-wake relay, schema/coverage rules, parent sink and final-authority behavior. The observed
background supervisor messages arrived after workflow settlement at the headless parent's
message-event surface. That is an allowed negative observation, **not** a timely-delivery
promise or a revalidation of the waived browser/draft/bridge-off legs.

Cancellation stays with existing owners: ReportWave transport owns its AbortSignal/deadline
and normal native stop request; the parent/native subagent tool owns the blocking resolver
workflow's cancellation. Stop acknowledgement, logical `stopped`, tool termination, observer
shutdown and detached-process proof are distinct. No automatic restart or `bg_wait` adoption.

W proved exact-child RPC stop inside an **async** enclosing workflow, including actual bash
abort, shutdown, a thirty-second no-trailing-write window and continued parent usability.
The selected blocking resolver workflow is retained from current behavior; propagation to the
same foreground child abort/dispose path is source-backed, **not a separately exercised root-
scheduling variant**. Direct top-level foreground targets are not RPC `stop` targets. Thirty
seconds is the experiment's observation bound, not a new universal production SLA. Node 3.2
pins cancellation propagation in ordinary framework tests without claiming a new live pass.

## 4. Identity carrier decision

**Use the engine-authored session system-prompt prefix as advisory agent identity.** Its exact
producer is pi-subagents 0.65.1 `buildInProcessChildLaunch` in
`src/runs/shared/child-launch.ts`; the namespace/field is `active_agent.name`:

```text
<active_agent name="perk.objective-explorer"/>
```

With a non-null role prompt and `systemPromptMode: replace`, the producer puts this line first,
followed by two newlines and the role prompt. It escapes `&`, `"`, `<`, `>` as the corresponding
named XML entities. The consumer reads **`ctx.getSystemPrompt()` at `session_start`**, before
scratch eligibility is evaluated by `before_agent_start` or `context`. R/S/W/E directly
observed that timing in the modes where the observer/Perk were active. At later provider time
the first line is the engine's child-boundary prose: do not re-scan the live prompt each turn.

Perk's new resolver belongs at `extension/substrate/childIdentity.ts`, composed by `index.ts`
and consumed by `agentScratch.ts`. Cache only within one extension activation, keyed to the
full SDK session UUID plus session-file path (or null). Never key it solely by Perk run id or
`pi_session_id` basename—multiple children use `session.jsonl`. No process-global name stamp,
new persisted identity entry, public model tool or engine-internal import.

The implemented shape is a typed advisory result: valid name versus unavailable (absent,
malformed, unreadable or stale), with provenance `native-system-prompt-prefix`. Availability
is not inferred from task text, session display name, a report's `case`, `PERK_RUN_ID`, stage,
parent-history content or arbitrary later prompt lines.

### Parsing, precedence and lifecycle

- Inspect only the exact first line; cap it at 4 KiB UTF-8. Require the entire line to match
  the one-tag/one-double-quoted-`name`-attribute shape, without leading/trailing whitespace,
  additional attributes, extra tags or literal unescaped XML-significant characters within
  the attribute value. Scan the prefix without whole-prompt splitting/copying; never trim,
  remove CR or normalize case. Over 4096 UTF-8 bytes is malformed regardless of content.
  For a bounded invalid line, malformed means the case-sensitive literal `<active_agent`
  appears anywhere (including partial/plural/prefixed/doubled tags); otherwise it is absent.
  A marker only on a later line is absent.
- Decode only the four producer entities, **once**, and require canonical re-encoding to
  reproduce the attribute bytes. No general XML parser or recursive entity expansion. Require
  a nonempty decoded name, at most 256 UTF-8 bytes and no Unicode General Category Cc
  control characters. Compare known
  names exactly and case-sensitively; valid names outside the census remain custom/unknown.
- The startup prefix is the only name carrier. Ignore `PI_SUBAGENT_CHILD_AGENT` entirely.
  Ignore every `extensionBindings` namespace for scratch identity, including conflicting
  claims. S proved that bindings are runner-only, so selecting them as a two-mode identity
  channel would add an unnecessary split. There is **no identity binding namespace**:
  `perk.parent-restrictions/1` is consumed only by the separate restriction boundary.
- `ChildRuntimeConfig.agent` is engine-internal hook data; no supported third-party getter was
  established. Do not import private engine modules, inspect closure state, or infer agent
  identity from runtime-acknowledgement IDs.
- Read `PI_SUBAGENT_CHILD === "1"` only as the documented **runner-hosted-child presence bit**
  for unavailable-identity fallback. It never supplies the name, mode, stage or write authority.
  Read it into the activation/session snapshot; never set it for a foreground child.
- Every `session_start` replaces the snapshot; `session_shutdown` clears it. Session-key
  mismatch makes the cached value unavailable, never an inherited name. `session_tree` and
  compaction do not reinterpret quoted markers or change the physical session's actor.
- Reload must discard and recapture, not carry a prior name. Source tracing in Pi 0.85.1 shows
  runtime/tool-registry reconstruction restores the loader's base system prompt before
  `session_start`; the child loader retains its tagged replacement prompt. This reload path
  is source-backed and pinned in `extension/sessionLifecycle.test.ts`, not labeled another
  native live case.

### Advisory—not authentication

Task/history/PR text containing a marker is ignored; it cannot precede the engine's prefix
through normal role construction. A privileged host/extension that forges the actual first
system-prompt line can forge this advisory claim. Perk does not pretend otherwise. A forged
known-report prefix may suppress scratch even in a parent; a forged writer/custom prefix may
change scratch eligibility, but **never** opens tools, changes workflow mode, grants mutation,
re-consumes a handoff or creates a launched stage. Such host tampering is outside the claim of
report-only enforcement. This trade-off is selected only for scratch guidance/provisioning,
not for an authorization principal. New uses require a separate decision.

## 5. Implemented exact scratch behavior

These rules apply only when Perk is active. Effective read-only gating—branch-LWW mode **or**
the separate parent-restriction floor—wins before identity and makes the turn ineligible.
Preserve the existing claim implementation; the identity resolver never changes authority.

| Identity after startup capture, with no effective read-only restriction | Agent scratch eligibility |
| --- | --- |
| Any of the ten report roles in §2 | **No** |
| `perk.conflict-resolver` | **Yes** |
| Valid custom/unknown name outside the closed census | **Yes**, retaining the named-custom fallback |
| Absent/malformed/unreadable/stale name in a runner-hosted child (`PI_SUBAGENT_CHILD === "1"`) | **No**, conservative unidentified-child fallback; warn once per session/reason |
| Unavailable name without the runner bit | **Yes**, parent/unidentified-foreground fallback; not proof of foreground report suppression |
| Legacy-only or bindings-only name claim | Ignore the claim; apply the applicable unavailable row |

The unidentified-background fallback is deliberately narrower than the former unconditional
unknown-name eligibility. It also covers custom append-mode prompts without an initial marker;
their definitions are not changed. A well-formed custom name remains eligible. A foreground
missing/malformed marker cannot reliably distinguish an uninstrumented child from a parent:
that is an **explicit unsupported negative case**, never a compatible report profile. All
selected report roles are background with tagged replacement prompts. Selected foreground
writers have no Perk activation, so their eligibility is not a promise of scratch provisioning.

`REPORT_ONLY_CHILD_AGENTS` contains the ten reports, including `perk-dev.session-auditor` and
excluding conflict-resolver. The auditor remains included even though init does not own its
definition. Parent and valid writer/custom eligibility remains subject to effective read-only mode.

For ineligible turns, `registerAgentScratch` must not call the agent-scratch provisioner in
**either** hook, and its context filter removes all direct `perk:agent-scratch` messages.
For eligible turns, preserve confined current-run provisioning before deduplication, one
current direct block, stale/duplicate direct-block removal, and visible provisioning failures.
Do not edit prose quoted inside ordinary messages/compaction summaries. The lifecycle may still
create a derived run root for workflow/session data: report suppression means no **`agent/`
directory or agent-scratch guidance**, not zero lifecycle filesystem activity.

## 6. Implementation-only responsibilities

### Node 3.2 — implemented profile/producer responsibilities

- Change the nine delivered report defaults and auditor default to `async: true`; converge
  byte-identical managed copies. Keep writer definition default unchanged and make both
  owned writer calls explicitly foreground with actual child cwd.
- Encode explicit global-context false while preserving project/skill fields, models,
  fallbacks, Ponytail exact-source exceptions, report mission/acceptance and writer defaults.
- Preserve `renderWaveScript`'s child-async omission and ReportWave's fixed async/fresh
  transport. Add the composition-internal live gate supplier and the exact per-child
  `perk.parent-restrictions/1` serialization specified above, sampled anew per attempt.
  Do not add a generic profile override, caller-controlled restriction/extension field or raw
  transport access outside the existing boundary.
- Update both conflict templates and their render/dispatch tests, including submit's address
  consumer and retained continuation's no-publish/completed-only gate. Keep model interpolation,
  attempt counters, leases and existing fail-closed path vocabulary.
- Tests: `tests/test_subagent_agents.py`, `tests/test_managed_state.py`,
  `tests/test_init_idempotent.py`, `tests/test_packaging.py`, `tests/test_repo_local_agents.py`;
  the per-consumer suites in §2; `extension/waves/reportWave.test.ts` (including transport
  timeout/cancellation tests), `extension/waves/reportWaveRpc.test.ts`,
  `extension/waves/rpcAdapter.test.ts`; and `extension/delivery/stackConflict.test.ts`.
  Pin all 11 memberships, background defaults despite a foreground engine default, writer
  explicit false despite a background default, writer definition default still omitted,
  no serialized child `async: true`, unchanged model/skill exceptions, actual cwd on both writer paths, and the fixed report context and
  acceptance contract. Regenerate `shared/subagents/representative-wave-script.js` for the
  new restriction field; never teach its golden the forbidden child `async: true` flag.
- Amend `shared/contracts.md` for the implemented behavior and matching user-facing docs.
  The implemented producer/profile behavior and the separate consumer are recorded there.

### Node 3.3 — implemented identity and independent restriction floor

The consumer is composed inside the extension factory and captured at the start of the main
startup handler before identity establishment/tool sync. Identity and restrictions classify
independently. Scratch uses the cached advisory lookup and effective gate, not env-name or
branch-mode fallbacks. The harness supports the real replacement loader prompt and clears inherited
run/runner/binding/legacy-name env by default; claim fixtures opt in. Same-process sessions start
sequentially and dispose in reverse order.

### Owning consumer regression suites

Each property has one primary suite rather than repeated cross-products:

| Boundary | Primary suite | Owned checks |
| --- | --- | --- |
| Advisory input | [`childIdentity.test.ts`](../../extension/substrate/childIdentity.test.ts) | Prefix matrix, byte/control/entity boundaries, full keys, stale/unreadable lookup, capture/clear/isolation and private known/anonymous warnings |
| Restriction input | [`childRestrictions.test.ts`](../../extension/substrate/childRestrictions.test.ts) | Decoder matrix, runner ignorance boundary, monotone same-key floor, unknown→known recovery, reset/isolation and warning buckets |
| Gate | [`toolGating.test.ts`](../../extension/substrate/toolGating.test.ts) | Floor across mode/snapshot/toolset/append failures, full allowlist denials, positive read/bash/engine tools, parent backstop and ordinary transitions |
| State reflection | [`session/lifecycle.test.ts`](../../extension/session/lifecycle.test.ts) | Outcome table, mode-only verification, classified/escaping failures and unchanged metadata |
| Scratch | [`agentScratch.test.ts`](../../extension/substrate/agentScratch.test.ts) | Ten reports × runner/non-runner, unavailable/custom fallback, both-hook provisioning counts, direct-only cleanup, repair/retry and separate auditor census |
| SDK composition | [`sessionLifecycle.test.ts`](../../extension/sessionLifecycle.test.ts) | Capture before rebuild, original-packet reload, branch-mode inheritance, tree/compaction, unclaimed and escaping-reflection continuation, paired-session authority isolation |
| Warm producer→consumer | [`waveIsolation.test.ts`](../../extension/pi/v1/waveIsolation.test.ts) | Actual rendered fake-RPC binding into runner-shaped mint/adopt children; unchanged parent handoff/sibling gates |
| Side session | [`btw.test.ts`](../../extension/vendor/btw/btw.test.ts) | Floor-backed read-only tools/cache and no scratch provisioner calls |
| Optional installed engine | [`childExecutionCompat.test.ts`](../../extension/waves/childExecutionCompat.test.ts) | Real escaped-prefix/parser and boolean-binding/decoder interop; existing foreground/ambient negatives retained |

The ordinary import-direction/surface guards, `reportWave`/`reportWaveRpc` suites and Python
agent-definition suites preserve the surrounding authority boundary. Harness instrumentation with
Perk is not authorization for an explicit-extension production profile; unavailable non-runner
scratch eligibility, ignored foreground packets and absent foreground ambient discovery remain
negative boundaries. No new live probe or prose-map/template work is implied.

## 7. Reconsideration and residuals

Re-verify and reconcile this record before either consumer departs from it when engine/Pi
version **or relevant bytes** change, extension/provider composition changes, native mode/default
resolution changes, the prefix producer/timing changes, or a contradictory live observation
appears. Upstream HEAD can differ while still declaring 0.65.1; version equality is insufficient.
Use [the re-verification guide](../developers/pi-subagents-reverify.md), preserve failures and
seek owner disposition. No automatic install, fallback mode, new live attempt or source-hash
refresh merely to get a pass.

Residuals presented for final review are: representative-derived sibling coverage; source-only
model/global-context/reload/root-scheduling claims; foreground writer's absent Perk scratch and
ambient-provider support; no arbitrary cross-cwd handoff inheritance; advisory spoofable identity
with the explicit fallback matrix; late background supervisor observation; and the untouched
Phase-2 streaming waivers. Report suppression and the strict warm-restriction consumer are
implemented alongside the profiles and per-attempt producer, with the exact lifetime/failure
limits above. No warm-path native PASS is claimed. No unresolved policy
choice is delegated to the implementation consumers.
