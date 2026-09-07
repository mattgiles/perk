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
stamp, Pi dev pins, unpinned engine policy and stale-error fingerprints stay unchanged. The warm
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
waivers and stale-error exception remain separately scoped; no case is retroactively passed.

## Submit foreground delegation (bounded offline compatibility)

Submit/address uses the public structured foreground delegation interface, not the async RPC or
ReportWave. Its sole transport/public-loader carrier is
`extension/pi/v1/delivery/conflictResolverEngine.ts`. The loader starts from the registered
`subagent` tool's `sourceInfo.path`, walks real package ancestry, requires manifest-declared
`./preflight` and `./delegation`, and loads only the realpath-contained public preflight using the
engine's own jiti. Missing/malformed/escaping exports fail unavailable; no installation or global
fallback is authorized.

Run these **offline**, with no model/rebase/push experiment:

```bash
node --test extension/pi/v1/delivery/conflictResolverEngineCompat.test.ts
node --test extension/pi/v1/delivery/conflictResolverEngine.test.ts extension/pi/v1/delivery/submitConflict.test.ts
node --test extension/substrate/worktreeResolverLock.test.ts extension/substrate/resolverLease.test.ts
```

The installed suite must actually execute in an implementing checkout; only an absent optional
installation on clean CI is a skip. A present incompatible installation fails. Check the public
export event literals/full correlation tuple, actual-cwd canonical profile discovery, native model
selection/fallbacks, foreground-only behavior against background defaults, acceptance-disable and
plain-JSON schema forwarding, config-path parity with native `getConfigPath`, result projection and
exact-tuple cancellation. The cancellation leg must reach real `runSync` with a fake
ChildSessionFactory, not only a simulated bridge. Private installed imports remain test-only.
TypeBox's non-enumerable metadata must not enter the native plain-JSON request.

The narrow `worktree` setting comes from `join(getAgentDir(), "extensions/subagent/config.json")`.
Missing/absent/false are compatible; true, nonboolean, malformed/unreadable or activation-changed
settings refuse. Inspect/correct and reload, never rewrite settings or allocate a second worktree
inside the adapter. Preflight/config observations are not atomic against concurrent source edits.
The persistent canonical Git-directory execution lock survives reload and process death; do not
use compatibility testing as an unlock gesture. See the
[human-only recovery procedure](../user-docs/how-to/recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock).

These checks corroborate launch/result plumbing and conservative ownership, not a live resolver,
independent verification, or remote mergeability certificate. They do **not** advance the full
compatibility baseline/doctor stamp, change Pi pins or stale-error fingerprints, or alter the
retained-continuation script/session claim.

## Temporary stale-error guard

`extension/waves/staleErrorCompat.ts` is a temporary, fail-closed exception for the two
human-review report families, not a general failed-lane recovery facility. It attests the
registered subagent tool's source path, version **0.65.1**, and exact hashes of
`run-child-session.ts`, `subagent-runner.ts` and `structured-output.ts` at launch and collection.
Source drift disables it; do not update the hashes merely to make a newer engine pass.

The guard requires correlated completed workflow/child artifacts, a confirmed successful native
retry, a matching successful capture followed by settlement, and no later/hard failure. It
validates against Perk's snapshotted requested schema with the host-provided `typebox/compile`,
not an artifact's substituted schema. Reads are confined and bounded; incomplete evidence leaves
the original failure. Only the in-memory aggregate changes. Receipt details retain the original
error plus evidence hashes, and both collect tools disclose recovery. See contracts §8.35 for
exact proof limits. Non-streaming waves never enable this exception.

For changes here, run the `staleErrorCompat` and `rpcAdapter` node:test suites and both collect-tool
suites. Their fixtures are offline and do not install/patch the engine; a source-digest injection
exists only at the interior test seam. The archived D2 replay exercises the real fingerprint and
captured artifacts, but does **not** retroactively pass that failed live leg. Fresh human-operated
validation still requires the recorded owner authorization and committed code.

Remove the guard after a source-reviewed upstream fix and the same error→retry→structured-capture
replay establish correct native settlement. Remove its plumbing, tests and disclosure docs together;
keep the original failure evidence. Doctor remains report-only and pi-subagents stays unpinned.

## Steps

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
