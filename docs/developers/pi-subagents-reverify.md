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

## Child execution and scratch-identity decision

The [binding child-policy record](../design/pi-subagents-child-execution-policy.md) defines
owner-accepted behavior: its [approval pointer](../design/pi-subagents-child-execution-policy.md#approval-pointer)
records acceptance by the unchanged PR #2231 owner merge, not a separate formal review or local
attestation. Profiles, the restriction producer, bounded advisory identity, the independent floor
consumer and exact ten-report scratch suppression are implemented. Both producer and consumer
are required for the full selected report profile. The bounded
[consumer source/offline reconciliation](../design/pi-subagents-child-execution-policy.md#consumer-sourceoffline-reconciliation)
records resolved roots, actual package versions, implementation commit and concise command outcomes.
Its [owning regression suites](../design/pi-subagents-child-execution-policy.md#owning-consumer-regression-suites)
allocate input matrices, lifecycle/gate/scratch checks, SDK wiring, warm producer→consumer, side
session and optional installed interoperability checks without repeating every cross-product.
The earlier [0.66.0 producer record](../design/pi-subagents-child-execution-policy.md#0660-sourceoffline-reconciliation)
retains its C1–C6/hash ledger verbatim as history; that ledger and a trailing evidence-only commit
are not requirements for this consumer's bounded verification. Use the normal PR validation summary
for detailed execution. Neither record is a new full compatibility certification: the doctor
stamp, Pi dev pins and unpinned engine policy stay unchanged. The warm
path is source/offline corroborated, not a native-matrix PASS. Later changes must reconcile the
policy rather than choose a new profile implicitly.

For consumer changes, re-read the worktree-resolved Pi startup/rebuild/reload path and the installed
engine's prefix escaping, runner stamp, runner-only binding delivery and child loader. Relevant
source behavior, not version equality, is the compatibility bar. Stop on incompatibility for owner
disposition—no install, mode or composition fallback. Private imports remain test-only; the optional
installed test must execute in an implementing checkout, while clean CI may honestly skip a missing
engine. Mandatory offline SDK harness coverage remains independent of that installation.

The consumer deliberately hardens **every effective read-only session**, parents included, with a
full `READ_ONLY_TOOLS` tool-call check independent of toolset synchronization. The existing bash
argument policy and allowlisted carve-outs do not become an OS sandbox. Same-key startup ORs the
floor; unreadable keys retain the last known comparison key, carrying an anonymous floor into first
readable recovery. Only shutdown/new activation or positively different known-key capture resets
it. Known-key warning buckets survive retries; separate anonymous buckets survive recovery until
shutdown. Invalid runner packets warn with fixed messages; non-runner packets are ignored silently.
Mode reflection is verified and mode-only, never identity repair. Classified failures keep the
honest outcome; an escaping append exception reports the fixed persistence failure once and
continues startup with the in-memory floor. Normal reload uses the original packet plus branch
mode—loss of both is unsupported. Foreground/manual and arbitrary cross-cwd cases remain outside
this bounded profile.

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

Both submit/address PR resolution and retained stack resolution use public structured foreground
delegation, not async RPC, ReportWave or model-authored scripts. Retained invocations are awaited
inside `objective_stack_sync`, with their own activation-local authorization after canonical
preparation; they target the retained worktree, not the parent checkout. Its sole transport/public-loader carrier is
`extension/pi/v1/delivery/conflictResolverEngine.ts`. The loader starts from the registered
`subagent` tool's `sourceInfo.path`, walks real package ancestry, requires manifest-declared
`./preflight` and `./delegation`, and loads only the realpath-contained public preflight using the
engine's own jiti. These exports and the installed `docs/extension-api.md` are the public
integration contract. Private parser/bridge/result adapter sources are separately inspected and
loaded only by compatibility tests, never production. Missing/malformed/escaping exports fail
unavailable; no installation or global fallback is authorized.

Run these **offline**, with no model/rebase/push experiment:

```bash
node --test extension/pi/v1/delivery/conflictResolverEngineCompat.test.ts
node --test extension/pi/v1/delivery/conflictResolverEngine.test.ts extension/pi/v1/delivery/submitConflict.test.ts extension/pi/v1/delivery/stackConflictResolver.test.ts extension/pi/v1/delivery/stackSyncNative.test.ts
node --test extension/substrate/worktreeResolverLock.test.ts extension/substrate/resolverLease.test.ts
```

The installed suite must actually execute in an implementing checkout; only an absent optional
installation on clean CI is a skip. A present incompatible installation fails. Check the public
export event literals/full correlation tuple, actual-cwd canonical profile discovery, native model
selection/fallbacks, foreground-only behavior against background defaults, acceptance-disable and
mode-specific plain-JSON schema and submit-conflict/retained-conflict node-ID forwarding, config-path parity with native `getConfigPath`, result projection and
exact-tuple cancellation. The cancellation leg must reach real `runSync` with a fake
ChildSessionFactory for both modes, not only a simulated bridge. Exercise retained linked-worktree
cwd, exact sentinel task, no PR push field/aborted outcome, completed/passed offer-only classification,
shared target exclusion and parent-context invalidation. Private installed imports remain test-only.
TypeBox's non-enumerable metadata must not enter the native plain-JSON request.

The narrow `worktree` setting comes from `join(getAgentDir(), "extensions/subagent/config.json")`.
Missing/absent/false are compatible; true, nonboolean, malformed/unreadable or activation-changed
settings refuse, stamping `nativeWorktreeConfig {path, observed, atActivation}` on the receipt.
The adapter never rewrites settings or allocates a second worktree; the repair is the Python
plane's `subagent-worktree-default` managed convergence (`perk init` / `perk doctor --fix`),
which targets the launch-precedence agent dir (`PI_CODING_AGENT_DIR` → `[pi] agent_dir` →
`~/.pi/agent`, the `launch_pi_agent_dir` resolver shared with `launch_stage`) — then reload. Preflight/config observations are not atomic against concurrent source edits.
The persistent canonical Git-directory execution lock survives reload and process death; do not
use compatibility testing as an unlock gesture. See the
[human-only recovery procedure](../user-docs/how-to/recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock).

These checks corroborate launch/result plumbing and conservative ownership, not a live resolver,
independent verification, or remote mergeability certificate. They do **not** advance the full
compatibility baseline/doctor stamp, change Pi pins, or change the
retained-operation session-claim policy. That claim stays held across child completion and cannot
bypass the execution lock. Post-result render/send failures must preserve explicit resolution or
the original automatic cold refusal and append one delivery-unconfirmed tool diagnostic; a
secondary warning failure must not erase that result. Consent tests are scripted actions, not
autonomous model evidence. Canonical Python continuation is separately approved and revalidated.

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
