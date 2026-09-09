# How to re-verify the pi-subagents compatibility baseline

This page is a **how-to guide**. Use it when perk's borrowed `pi-subagents` engine has moved
under the guidance — the package is deliberately **unpinned** (owner-affirmed; a future pin is a
separate one-line decision that this recorded-baseline procedure makes trivial), so compatibility
rests on a *tested baseline* plus this re-verify ritual, never on a version constraint.

**When to re-verify:**

- `perk doctor`'s `subagent-compat` check **warns** (a probe marker or file vanished, or the
  `validateWorkflowScript` behavior arm reported an invalid script);
- the check is `ok` but its detail carries the *installed ≠ guidance-verified* note (a version
  bump with a still-matching surface — mechanics beyond the markers are source-read-derived and
  unverified at the new version);
- you are about to **build on new engine mechanics** (anything the probes don't cover: wait/wake
  semantics, the supervisor channel, workflow child launch policy);
- relevant source bytes, provider/extension composition, or identity-carrier timing differ from
  the child-policy record below—even when the package still reports the same version.

**Prerequisites:** a checkout of the perk repository with both toolchains installed
(`just setup`). The live smoke additionally needs model credentials (the parent session's
default model and the `[models.subagents] objective-explorer` child model).

## Repo-local development host baseline

The development host pins **five** packages together at `0.85.1`: `@earendil-works/pi-coding-agent`,
`pi-ai`, `pi-tui`, `pi-server`, and `pi-client` (all with the same scope). Server/client are
explicit dev dependencies because Pi's published host does not supply the background runner's
full runtime peer graph. This is a **repo-local workaround**, not certification or automatic
repair of consumers' global Pi installs. Do not patch node_modules, reinstall globally, change
child mode, or pin pi-subagents to make a failing baseline pass. `just bump-pi VERSION` maintains
all five dev pins; published wildcard peers, zero runtime dependencies, and doctor report-only
behavior are unchanged.

Run normal setup **in the worktree under test** (`uv sync --all-packages && npm ci`), not just
its ancestor checkout. Stop if this does not establish the committed toolchain; do not change
manifests/lockfiles to repair the host. Check
`npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-server @earendil-works/pi-client --depth=0`,
then `npm run typecheck`, `node --test extension/piAiCompatGuard.test.ts`, and
`uv run pytest tests/test_packaging.py::test_pi_toolchain_pin_lockstep -q`. Commit before live probes.

Probe the installed engine using its own jiti and the absolute **repo-local** Pi package root:

```bash
node <<'JS'
const { createRequire } = require('node:module');
const path = require('node:path');
const engine = path.resolve('.pi/npm/node_modules/pi-subagents');
const engineRequire = createRequire(path.join(engine, 'package.json'));
const { createJiti } = engineRequire('jiti');
const jiti = createJiti(path.join(engine, 'package.json'));
const { resolveHostPeerAliases } = jiti(path.join(engine, 'src/runs/background/runner-aliases.ts'));
const host = path.resolve('node_modules/@earendil-works/pi-coding-agent');
const result = resolveHostPeerAliases(host);
console.log(JSON.stringify({ host, ...result }, null, 2));
if (result.missing.length) process.exitCode = 1;
JS
```

Require `missing: []`, record every resolved path and any supplemental aliases, then run the
existing `just subagents-smoke` from the clean commit. Inspect the child receipt/artifact metadata
for a real background runner process: a PASS under a foreground override is not this baseline.
Stop on install, resolution, or launch failure and retain run/status/cwd/ref and clean-state or
diff evidence; another version or execution protocol requires owner direction.

Use a **fresh process** for live review doors: put `$PWD/node_modules/.bin` first on PATH for
normal `uv run perk plan` draft handoffs, or launch `$PWD/node_modules/.bin/pi` directly for a
bare interactive probe after removing inherited `PERK_RUN_ID` and `PI_SESSION_FILE`. Keep Pi
open between model turns. The implementing session predates its dependencies/bindings and is
not a valid live host. See the scoped [native streaming record](../design/archive/pi-subagents-native-streaming-dogfood.md)
for the background baseline and the five human-operated streaming legs; unobserved legs are not passes.

## Child execution policy

The [child-policy record](../design/pi-subagents-child-execution-policy.md) is binding: two
booleans — the runner bit (`PI_SUBAGENT_CHILD=1`) and the constant report restriction packet
(`perk.parent-restrictions/1 = {readOnly: true}` + `worktree: false` on every report child) — give
a runner child a monotone read-only floor and no agent scratch; a malformed or unsupported-version
packet fails closed. Its regression table names the owning suites (`childRestrictions.test.ts`,
`sessionLifecycle.test.ts`, `agentScratch.test.ts`, `reportWave.test.ts`, `waveIsolation.test.ts`).

On a pi-subagents bump, also confirm by reading the installed agent-definition parser that
`completionGuard: false` is still read from report definitions and that a report-only lane
completes on a valid `structured_output` report without edits (and still fails a missing or
invalid report). The automated engine-level proof (`reportOnlyCompletionCompat.test.ts`) was
retired because it imported pi-subagents' private source (the objective's rule 3: tests reach
pi-subagents only through its public exports, or not at all); the frontmatter stays pinned by the
pytest rows and `perk doctor`'s `subagent-compat` installed-vs-verified version warning signals
upstream drift — `run_ci` will not catch an upstream change to the guard semantics.

The linked [capability characterization](../design/archive/pi-subagents-child-capability-characterization.md)
records the pi-subagents 0.65.1 / five-package Pi 0.85.1 matrix, actual tool denials and writer
cancellation, preserved failed attempts, and independent teardown. Its finite launch budget
is exhausted. Source/prose inspection is not authorization to repeat those runs: another live
configuration or attempt needs a bounded owner-approved protocol first. A newer upstream HEAD
can still declare 0.65.1, so compare the actual relevant sources, not the version string alone.

This matrix does not certify every role/model, arbitrary cross-cwd handoff discovery, ambient
providers in foreground writers, or timely background supervisor delivery. E's explicit-loading
cases were read-only diagnostics, not admissible read-write profiles. The earlier streaming
waivers remain separately scoped; no case is retroactively passed.

## Foreground resolver delegation (bounded offline compatibility)

Both submit/address PR resolution and retained stack resolution emit directly on pi-subagents'
public delegation event family (the `./delegation` constants, carried as literals in
`extension/pi/v1/delivery/conflictResolverEngine.ts` and confined there by the import-direction
guard) — not async RPC, ReportWave or model-authored scripts. There is no loader, preflight or
profile evidence; the only presence check is Pi's tool census (a missing `subagent` tool refuses
`unavailable` before any lock). Run these **offline**, with no model/rebase/push experiment:

```bash
node --test extension/pi/v1/delivery/conflictResolverEngine.test.ts extension/pi/v1/delivery/submitConflict.test.ts extension/pi/v1/delivery/stackConflictResolver.test.ts extension/pi/v1/delivery/stackSyncNative.test.ts extension/substrate/worktreeResolverLock.test.ts extension/substrate/resolverLease.test.ts
```

pi-subagents' global `worktree` default (`join(getAgentDir(), "extensions/subagent/config.json")`)
is read once at engine activation; anything but a missing file, an absent key or `false` refuses
every dispatch naming the path, the observation and the fix — perk never rewrites it. An
event-protocol change in a newer pi-subagents surfaces as a no-ack cancellation with a retained
lock (the `doctor subagent-compat` version warning is the early signal). The execution lock
survives reload and process death; see the
[human-only recovery procedure](../user-docs/how-to/recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock).

These checks corroborate launch/result plumbing and conservative ownership, not a live resolver.
The retained-operation session claim stays held across child completion and cannot bypass the
execution lock; post-result render/send failures preserve the settled result and append one
delivery-unconfirmed diagnostic; consent tests are scripted actions, not autonomous model evidence.

## Native partial report settlement (additive offline compatibility)

Report waves retain independently successful reports after an explicitly marked native partial
settlement, without treating the workflow as complete. This is retention after settlement, not
status/resume recovery. The report-only doctor table has three additional **presence-only** probes:

| Surface | Installed source | Required markers |
| --- | --- | --- |
| Partial workflow terminal vocabulary | `src/shared/types.ts` | `WorkflowTerminalOutcome`, `state: "partial"`, `"budget_exhausted"`, `"timeout"` |
| Partial workflow result projection | `src/runs/foreground/subagent-executor.ts` | `workflowFailureTerminalOutcome`, `terminalOutcome`, `results: partial.children.map`, `workflowKey: child.key`, `structuredOutput: child.structuredOutput`, `success: child.ok` |
| Partial workflow completion forwarding | `src/runs/background/result-watcher.ts` | `SUBAGENT_ASYNC_COMPLETE_EVENT`, `...data`, `...data.results![index]` |

These file-scoped probes run whenever the engine is installed, even if the optional script-validation
behavior probe cannot run. Missing source/markers warn without a fix or execution gate. They were
source-verified on an installed package reporting 0.66.0; that is a source snapshot, not a pin or
full re-verification. A clean marker result is **not a live-retention certificate**.

Run the controlled acceptance and mandatory synthetic regressions offline:

```bash
node --test extension/waves/partialSettlementCompat.test.ts
node --test extension/waves/adapterContract.test.ts extension/waves/rpcAdapter.test.ts extension/waves/reportWave.test.ts extension/waves/reportWaveRpc.test.ts
uv run pytest tests/test_doctor.py -k subagent_compat -q
```

The installed test executes the actual module-rendered script with native `runWorkflowScript`,
validates a controlled child report with native `validateStructuredOutputValue`, waits for trace
and sibling-start barriers, and fires the captured native workflow timer. Actual
`WorkflowScriptError.partial.children` feed `planWorkflowSettlement`; the explicit
`executeSettlement` fake writes failed status without `workflow.value` and delivers the public
projection to production `ReportWave.collect`. Network is blocked; timers/environment are restored
and the native runner terminates its worker. The test must run in an implementing checkout.
Only an absent optional installation may skip on clean CI; a present incompatible engine fails.
It does not run an autonomous model or the entire live executor/watcher chain, prove all profiles,
or recover Perk-local timeouts without completion, unreadable status or interrupted sessions.

**Additive probe maintenance is not a full baseline re-verify.** Reconcile new source rows,
literal row pins, synthetic marker/file-removal tests, and compatibility documentation together.
Do not bump `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, change historical evidence or update the
learned-doc version anchors for this bounded work. Only completion of the full baseline procedure
below advances that stamp; pi-subagents remains unpinned.

## Retired stale-error guard

The temporary 0.65.1 recovery layer was removed after a bounded offline native replay of the
upstream fix. The [retirement addendum](../design/archive/pi-subagents-native-streaming-dogfood.md#stale-error-guard-retirement--2026-09-07)
records the successful chain, failed probe preparations and unchanged historical live gaps.
Failed engine lanes now remain failed without special capture salvage, including on old affected
engines. This retirement does not advance the guidance-verified baseline: doctor remains
report-only and pi-subagents stays unpinned.

## Steps (full baseline re-verify)

These steps certify the full baseline, not an additive source-probe update. Only this full process
advances the guidance-verified stamp and baseline evidence.

1. **Read the installed version.**

   ```bash
   node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"
   ```

   Compare against `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` in
   `src/perk/convergence/doctor/checks.py`.

2. **Run the doctor probes.**

   ```bash
   just perk doctor
   ```

   The `subagent-compat` check runs the substring probes over the installed source AND the
   behavior arm: the installed engine's `validateWorkflowScript` over the shared representative
   wave script (`shared/subagents/representative-wave-script.js`). A skip note in the detail
   (`behavior probe skipped (…)`) means the behavior arm could not evaluate — investigate the
   named reason; it is never a divergence by itself.

3. **Run the live smoke from a clean committed tree.**

   ```bash
   just subagents-smoke
   ```

   Opt-in, dev-only, never part of `just ci` — it drives a real headless `pi --mode json -p`
   session through one `explore_objective_node` report-wave lifecycle on the installed engine.
   Run it from a **clean committed tree** so the recorded `perk @ <commit>` identifies the code
   actually exercised (the report flags a dirty tree).

4. **Source-re-verify the deeper mechanics.** The probes are surface tripwires; the mechanics
   perk's guidance actually leans on are enumerated in `docs/learned/pi/subagents.md` under its
   version anchor (supervisor-channel delivery and wakes, the typed child runtime config, the
   omitted-async semantics, the in-process async workflow host, structured output, the v1 RPC
   envelope). Read the installed source at
   `.pi/npm/node_modules/pi-subagents/src/` and confirm each claim still holds.

5. **Update the probe table.** Reconcile `_SUBAGENT_COMPAT_PROBES` per the tripwire-marker
   pattern (pin the positive literal whose *disappearance* signals the architectural change —
   the pattern is spelled out at the table's header comment and in
   `docs/learned/pi/subagents.md`), bump `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, and update the
   exact-pin test in `tests/test_doctor.py`
   (`test_subagent_compat_acceptance_probe_is_pinned_exactly`) plus the superset file-list and
   divergence-anchor tests as needed.

6. **Reconcile the learned docs' version anchors.** `docs/learned/pi/subagents.md` (the version
   anchor blockquote + any mechanics that moved) and `docs/learned/workflow/report-waves.md`
   (the doc-boundary name list and any currency notes).

7. **Update the user-docs probe listing.** The `subagent-compat` paragraph in
   `docs/user-docs/reference/cli/setup-and-health.md` enumerates the probed surfaces — keep it
   in lockstep with the table (and `shared/contracts.md`'s doctor-groups bullet if the check's
   shape changed).

8. **For a full baseline re-verify, record the evidence.** Author a dated evidence note in
   `docs/design/archive/` (the archive location is the status signal) naming the baseline
   matrix — perk @ the smoke-run commit, the pinned Pi version, the installed pi-subagents
   version — the smoke run's verbatim facts, and the re-verified mechanics. The 0.65.1
   baseline record (`docs/design/archive/pi-subagents-native-baseline-dogfood.md`) is the
   template.

## The standing pin decision

pi-subagents stays **unpinned** (owner-affirmed): perk tracks the engine's latest and pays for
it with this early-warning + re-verify discipline instead of a pin/upgrade lifecycle. If drift
ever becomes too expensive, pinning is a one-line `.pi/settings.json` change — and the recorded
baseline names exactly which version to pin.
