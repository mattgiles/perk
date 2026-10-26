# How to re-verify the Pi pair (Pi + pi-subagents) after an upstream bump

This page is a **how-to guide** — the one procedure for the next Pi or pi-subagents bump, both
halves of the pair. perk consumes Pi through the SDK boundary and the PATH `pi` CLI, and the
borrowed `pi-subagents` engine only through public surfaces (the v1 RPC envelope, the delegation
events, agent-def frontmatter). Compatibility therefore rests on *recorded baselines*, exact pins
(see "The five version facts") and this ritual — never on reading the installed source from tests
or doctor. Two carve-outs. The host-SDK bridge's **census drift guard**
(`extension/substrate/nativeSdkBridge.test.ts`) lexes the installed consumers' *import specifiers*
— a structural fact of the shipped artifact (which SDK modules it imports), not engine mechanics —
so a new release that imports an SDK subpath perk does not bridge fails loudly instead of silently
loading a second SDK copy. The **Pi config-schema producer check** reads the
`schemas/settings.schema.json` / `schemas/models.schema.json` data files the exact-pinned dev
`@earendil-works/pi-coding-agent` publishes (listed in its `package.json` `files`) — Pi's published
configuration contract, not engine mechanics — so a perk-written value outside the adopted Pi's
declared contract fails CI.

**Vocabulary.** An **exact pin** is what gets installed; a **floor** is the admitted minimum
(**Host floor** in `CONTEXT.md` § Host admission); the **guidance stamp** is the last supplier
version whose guidance was fully re-verified. A release is **adopted** when its pins move (on
characterization + offline evidence) and **certified** only when a live certification record says
so — the two are separate claims. **Characterization** measures a published release in a
throwaway install before any pin moves; **certification** runs the live matrix on the landed
tree; **re-verification** is this whole ritual. The **Adopted Pi pin**, **Pinned install set**,
**Remote install pin** and **Dev pins** are defined in `CONTEXT.md` § Host admission.

**When to re-verify:**

- a new Pi or pi-subagents release you intend to adopt;
- `perk doctor`'s `subagent-compat` check **warns** (installed version ≠
  `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`);
- the `pi` row's advisory — an admitted PATH `pi` that is not the adopted pin;
- you are about to build on new engine or SDK mechanics.

## The five version facts

| Fact | Home | Guard | How it moves |
|---|---|---|---|
| Dev pins | the four `@earendil-works/*` `devDependencies` in `package.json` + `package-lock.json` | `tests/test_packaging.py::test_pi_toolchain_pin_lockstep` | `just bump-pi <v>` (`justfile::bump-pi` moves only these four) |
| Host floor | `shared/host-floor.yaml` (`pi.min_version`; `node.min_version` + `node.line_floors`) | `tests/test_host_floor.py::test_real_host_floor_loads_validates_and_pins_the_floors`; `extension/substrate/hostFloor.test.ts` | by hand, with the adopted pin, never above it |
| Adopted Pi pin + pinned install set (= the remote install pin) | `src/perk/substrate/pi_host.py` (`PI_ADOPTED_VERSION`; `PI_COMPANION_PACKAGES`, the six-name coherence family; `PI_INSTALL_SPECS`, the one exact spec; `PI_INSTALL_COMMAND`); `src/perk/run/workflow_artifacts.py` (`REMOTE_PI_VERSION`, `_PI_GLOBAL_INSTALL`, the consumer worker install with `--save-exact`) | `tests/test_pi_host.py::test_install_command_is_the_pinned_set`, `::test_pinned_install_family_is_closed_against_the_characterized_lockfile`, `::test_the_family_declares_itself_exactly_in_the_characterized_lockfile`, `::test_remote_install_pin_is_the_adopted_pin`; `tests/test_workflow_artifacts.py::test_committed_self_repo_remote_artifacts_are_the_owners_render` | by hand; `uv run perk init --no-interactive` regenerates `.github/actions/perk-remote-setup/action.yml` and its `.perk/managed-state.toml` digest (`perk doctor --fix` converges them too, but also installs the pinned set into the global prefix whenever the PATH `pi` is not the adopted pin) |
| Supplier pin | `src/perk/convergence/init/settings.py::SUBAGENTS_PACKAGE`; `.pi/settings.json`; the `settings-wiring` digest in `.perk/managed-state.toml` | `tests/test_init_idempotent.py::test_subagents_borrow_is_version_pinned`; the two pin-bound assertions `tests/test_native_sdk_bridge_live.py::test_the_installed_pi_subagents_is_the_managed_pin` and `::test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded` | by hand; `uv run perk init --no-interactive` converges `.pi/settings.json` and the digest (same `doctor --fix` caveat as above) |
| Guidance stamp | `src/perk/convergence/doctor/checks.py::_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` | `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` | last, only on a certification whose every required supplier row passes |

One lockstep surface rides beside them: the extension refusal's public URL,
`extension/substrate/hostAdmission.ts::REQUIREMENTS_DOC_URL`, points at
`docs/user-docs/reference/requirements-and-compatibility.md#version-compatibility`;
`extension/substrate/hostAdmission.test.ts` ("the refusal's public URL points at a file and
heading that exist in this checkout") pins the page and the `## Version compatibility` heading.
Node's supported lines live in the floor file; TypeBox is a dev pin of its own (`typebox` in
`package.json` `devDependencies`) that `just bump-pi` only lists.

The rule: the adopted pin and the pinned install set move on characterization + offline evidence,
never below the floor, and the certification follows (contracts §8.76(b)); the supplier pin may lead
the stamp the same way; the stamp moves only on certification evidence.

## Steps

1. **Record the current and target version facts.** From the checkout: every row of the table
   above, the Node floor lines and TypeBox. From the host: `pi --version` and the `pi` row of
   `perk doctor --json` (the companion-family read), and the installed supplier,
   `node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"`. The targets
   come from the registry: `npm view @earendil-works/pi-coding-agent dist-tags --json`;
   `npm view @earendil-works/<pkg>@<target> name version dependencies peerDependencies
   _hasShrinkwrap --json` for every family member; `npm view pi-subagents@<target> name version
   dependencies peerDependencies --json`. **If a later release appears mid-bump, re-audit it as a
   dated deviation — never substitute it silently, and never install a floating `latest` as
   evidence.**
2. **Audit the published delta, packaging shape included**, in a THROWAWAY install (the
   characterization-record shape: `docs/design/archive/pi-1.1.0-characterization.md`). Read the
   release notes either way.

   **The Pi half.** The packaging facts: since Pi 1.3.0 the package declares its
   `@earendil-works/*` companions at exact versions (no `npm-shrinkwrap.json` — none needed), so
   the one exact spec places the whole family. Is the family still closed at the seven names, and
   is every declaration still exact? A new `@earendil-works/*` dependency is a new
   `PI_COMPANION_PACKAGES` member; a dropped one (as `chord` was in 1.2.0) leaves the tuple and is
   checked against the supplier's host aliases (`src/runs/background/runner-aliases.js` — 0.76.1
   required Chord on every 1.x host; 0.78.0 made it conditional); a return to ranged declarations
   fails `test_the_family_declares_itself_exactly_in_the_characterized_lockfile` and means the
   install must name the family again. Then the SDK surfaces perk binds: the census drift guard
   (`extension/substrate/nativeSdkBridge.test.ts`), the `before_agent_start` event shape (since Pi
   1.2.0 a discriminated union: a user start, `messageType: "user"`, carries `prompt`; a custom
   start, `messageType: "custom"` — pi-subagents' completion wake, any idle
   `sendMessage(…, { triggerTurn: true })` — carries `message` and no prompt; perk's two hooks scan
   the prompt only on a user start, contracts §8.9 and §8.31),
   `extension/piAiCompatGuard.test.ts`, `McpExtensionOptions` (the worker's factory-scoped
   isolation, contracts §8.11), `agent_settled.aborted` (the driven-compaction seam,
   `extension/pi/v1/drivenCompaction.ts`), codemode exposure (`model-only` for the bounded
   writers, contracts §8.40), `parentToolCallId` on `tool_call` events and `tool_search`'s
   `exposure: "model-only"` (the nested policy, contracts §8.40), and tool selectors preserving
   MCP tools (the MCP read-only floor).

   **The supplier half.** The installed package under `.pi/npm/node_modules/pi-subagents/` ships
   compiled JavaScript since 0.70.0 (`pi.extensions: ["./index.js"]`, `src/**/*.js` with `.d.ts`
   files and source maps; ≤ 0.68.x shipped `src/**/*.ts`) — re-read it in place: the module and
   function anchors below survive compilation, so `grep -n` over `src/**/*.js` finds them. Fall
   back to the matching tag of `nicobailon/pi-subagents` (`gh api` / `gh browse`, or a local clone
   at the tag) only for a fact the compiled output obscures. Install a new supplier with Pi
   stopped and start a fresh process — 0.76.1 refuses an in-process version change. Walk each
   engine mechanic `docs/learned/pi/subagents.md` states (its `## Sources` names the baseline):
   - the supervisor channel's `expectsReply` handling in
     `src/intercom/native-supervisor-channel.ts::poll` — progress updates are **discarded** on
     the parent side since 0.68.0, which is why every perk wave spawns with
     `intercomBridge: {mode: "off"}` (`WAVE_INTERCOM_BRIDGE`); confirm the per-launch
     `SubagentParams.intercomBridge` override still spreads onto workflow children
     (`src/runs/foreground/subagent-executor.ts` `workflowDefaults`) and still yields
     `active: false` under `resolveIntercomBridge`;
   - the wake rules in `src/runs/background/notify.ts` (`incrementalChildCompletionTriggersTurn`
     — a routine successful child completion does not wake the parent; failed/paused/stopped
     children and the workflow completion do);
   - the typed child runtime config, the omitted-async semantics, the in-process async workflow
     host, structured output (`outputSchema` → the injected `structured_output` call), the v1 RPC
     envelope, the partial-settlement projection;
   - the agent-definition parser (`src/agents/agents.ts`, `src/agents/frontmatter.ts`): its
     **removed-field throws** (`uses removed frontmatter field '<name>'` — 0.68.0 rejects
     `fallbackModels`; a new removal fails every shipped def at load and shows up as 0/N
     waves, so grep `agents/*.md` for the named field); a report-only lane must complete on a
     valid `structured_output` report and still fail a missing/invalid one (`run_ci` cannot catch
     this);
   - **package agent discovery** — perk's `perk.*` defs reach sessions ONLY this way:
     `collectPackageSubagentPaths` (`src/agents/agents.ts`) must still gather the project root
     and every `.pi/npm/node_modules/*` package root, `extractSubagentPathsFromPackageRoot` must
     still honor the top-level `package.json` `"pi-subagents": {"agents": [...]}` form,
     `mergeAgentsForScope` (`src/agents/agent-selection.ts`) must keep the
     `builtin < package < user < project` rank (a same-named project def SHADOWS a package def —
     the doctor `subagent-engine` leftover arm rests on this), and `resolveSkills`
     (`src/agents/skills.ts`) must keep resolving `skillPath` against `dirname(agent.filePath)`
     and skipping a missing entry (`collectFilesystemSkills`: `if (!fs.existsSync(...)) continue`)
     — the reviewer defs' two-candidate Ponytail `skillPath` depends on both;
   - the **child tool plan** (`src/runs/shared/child-tool-plan.ts`): since 0.70.0 the engine no
     longer intersects a child's declared tools with the host session's builtins (the 0.67.x
     `getHostBuiltinToolNames` census that failed review/scout-named agents closed under a
     pi-fff `override` is gone), so perk injects no `PI_FFF_MODE` and runs no host-tool doctor
     check; if a later release reintroduces a host-side intersection, that is a new hazard to
     name, not a reopened one;
   - the **completion contract**: 0.70.1 removed the completion mutation guard (a def's
     `completionGuard` is ignored) and tightened acceptance inference — a report lane must still
     complete on its validated `structured_output` report under `WAVE_ACCEPTANCE`;
   - **fork context**: the Pi 0.87 fork/pruned-fork repair shipped in 0.71.0
     (`src/shared/fork-context.js`, `src/shared/pruned-fork.js`); perk's waves and writers still
     spawn `context: "fresh"` by choice (`extension/waves/transport.ts`,
     `extension/pi/v1/foregroundDelegation.ts`), and fork context stays uncertified for perk
     children — re-read it only if a perk child is ever to fork;
   - the **RPC spawn key** (`src/extension/rpc.ts::spawnParams`): perk sends the inline script
     text as `script`, which the engine copies onto its internal `workflowScript` carrier; since
     0.74.0 a request carrying `workflowScript`/`workflowScriptPath` (an `Object.hasOwn` check, so
     an `undefined` value counts) is rejected `invalid_params`. A rename here is a wire break the
     fake responder (`extension/testing/fakeSubagents.ts`) must mirror;
   - the **RPC `stop` and `status` shapes** perk reads after its own timeout/cancel
     (`src/extension/rpc.ts::stopAsyncRun` — its own implementation, not the model-facing
     `async-stop-action` — and `src/runs/background/run-status.ts` +
     `workflow-terminal-proof.ts::readWorkflowTerminalProof`): a `stop` success is a `state:
     "stopping"` request and a refusal a typed `not_found`/`invalid_state`/`execution_failed`;
     `status {id}` carries the proof at `details.workflowTerminalProof` with states
     `observed`/`pending`/`unknown`. `rpcAdapter.ts::narrowTerminalProof` and the fake's
     `stopReply`/`terminalProof`/`statusReply` knobs mirror them;
   - the **lifecycle cells 0.76.1's certification measured as FAILs** (W4, W6, W7a in
     `docs/design/archive/pi-1.1.0-certification.md` § W): W6 is repaired in perk (the
     roster-correlated unfinished-lane diagnosis, contracts §8.35) and W4/W7a are re-specified
     with fixed dispositions — the rows live in step 5's lifecycle-cell table and are measured by
     a certification (first by objective #2767's node 3.1,
     `docs/design/archive/pi-1.4.0-certification.md`), not by this audit step; re-read the partial
     `results` projection, the `/reload` stop and the terminal-proof reasons — including the
     never-started-writer `writer-close-unverified` arm behind W7a(i)'s amended staging (step 5) —
     at the next release;
   - the **awaited-child event** (`subagent-executor.ts::emitWorkflowAwaitedChildComplete`): a
     per-child `subagent:async-complete` payload carrying the CHILD's `id`/`asyncDir` on the
     wave's channel. perk correlates by identity only and must never match it to the workflow
     handle (`reportWaveRpc.test.ts`'s `awaitedChildEvent` builder pins the exact shape);
   - **project-trust forwarding** (`src/runs/foreground/subagent-executor.ts::sessionProjectTrust`
     → `src/runs/shared/child-session.ts` `SettingsManager.create(cwd, agentDir, {projectTrusted})`):
     perk's extension — the restriction packet's consumer — loads in a child only where the
     project tier loads, so the parent's trust must still be forwarded unchanged (contracts §8.3);
   - the **child prompt-runtime inline path**: `child-session.ts`
     `CHILD_PROMPT_RUNTIME_EXTENSION_PATH` must still equal the
     `<inline:pi-subagents:prompt-runtime>` key of `toolPolicy.ts::SYNTHETIC_PATH_TOOL_POLICY` —
     perk's gate classifies `structured_output`/`contact_supervisor` by that provenance. A new
     `<inline:pi-subagents:…>` extension that a perk agent's `tools:` can reach needs its own row;
   - **`toolActivation`** (`src/extension/tool-activation.ts`, modes `auto`/`dynamic`/`eager`)
     against perk's own-names-only reconciliation (`toolPolicy.ts::reconcileTarget` +
     `hiddenDeclarationsFor`): `extension/substrate/ownNamesActivation.test.ts` models the
     loader-present (`dynamic`) shape; `eager` registers no loader at all;
   - the **`./node` host alias** (`src/runs/background/runner-aliases.ts`): optional since 0.75.0,
     so background children start on a Pi host whose `pi-agent-core` no longer exports it;
   - **workflow reuse** (`src/workflows/workflow-reuse.ts::findWorkflowReuseSource`): a relaunch
     re-attaches only to the same session's newest terminal workflow with the same
     `scriptDigest`/`argsDigest` whose `stopCause` is `runtime-replaced` (after `/reload` or a
     resume), then returns its settled `ok` children (`reused: true`) and re-attaches the running
     ones. perk's `ReportWave` pending map is per-activation, so a wave launched before
     `/reload` stays uncollectable afterwards, and every wave spawn carries a per-launch token
     (`transport.ts`: `args: { launch: randomUUID() }`) so the reuse key never matches a perk
     wave — a relaunch is fresh. Re-read: the key is still session + script digest + args
     digest, and RPC `spawn` still accepts a plain-JSON `args` with an inline `script`
     (`src/extension/public-execution.ts` refuses `args` only without a workflow input);
   - **`outputPartial` reach** (`src/runs/background/run-child-session.ts`,
     `src/runs/foreground/subagent-executor.ts::workflowResultChildren`): the single-run partial
     marker rides beside `exitCode: 1` (so `success: false`) and the workflow projection drops
     it. perk reads `ok` alone (`reportWaveRpc.test.ts`'s source pin forbids the marker names in
     the wave modules); a new projection that carried a report-bearing `success: true` partial
     would need a decision, not a silent read;
   - **MCP attachment** (`src/runs/shared/child-session.ts::createDefaultChildSessionFactory`):
     a child gets `builtin:mcp` only when its launch names `mcp:` selectors (a nonempty
     `builtinMcpTools`), and a definition's `excludeTools` reaches the SDK only without an
     explicit `tools:` allowlist (`src/runs/shared/child-launch.ts`). perk's report children name
     no `mcp:` selector, so they register no MCP tool; the read-only floor against a registered
     one is `extension/substrate/mcpReadOnlyFloor.test.ts`;
   - the **`disabledFeatures` surfaces** (`src/shared/disabled-features.ts`): the features whose
     parameters perk sends (`workflow-scripts`, `missions`, `extension-bindings`) refuse every
     wave with the engine's own setting-naming message — surfaced verbatim, never mapped;
   - the **structured-delegation `providerDiagnostics` snapshot**
     (`src/api/delegation.d.ts::SubagentDelegationProviderDiagnostics`, produced by
     `src/shared/provider-diagnostics.js` and projected onto updates by
     `src/slash/delegation-adapters.js`): perk's `extension/substrate/providerDiagnostics.ts`
     mirrors the closed `lastError.kind`/`retry.phase` vocabularies and the numeric bounds and
     treats any other shape as unavailable (display-only — the foreground writers' `perk` status
     activity; never termination, lock or spend evidence). Re-read the unions and the `message`
     policy at the next bump; a vocabulary change is a decoder update + test pin
     (`providerDiagnostics.test.ts`), never a wire break.
   - the **runner launcher** (`src/runs/shared/runner-launcher.js`, with the supplier's
     `docs/agents.md` § "Sandboxing background children with a launcher" and
     `docs/configuration.md` § `runnerLaunchers`): characterized NO-GO at 0.81.0
     (`docs/design/archive/pi-subagents-0.81.0-launcher.md`); re-read where a launcher may live,
     the refusal shape and the status files it writes (`docs/learned/pi/subagents.md` § Runner
     launchers);
   - the **delegation-request census and bridge rules** mirrored in
     `extension/testing/fakeConflictResolver.ts` (the request field census and the
     `intercomBridge` validator) and the foreground transport's bridge override
     (`foregroundDelegation.ts::FOREGROUND_INTERCOM_BRIDGE`, byte-equal to the wave constant) —
     a census change is a fake update with its vacuity controls, re-read at every bump;
   - the **frontmatter parser's `allowedAgents` handling** (`src/agents/frontmatter.js` /
     `agents.js`): a blank `allowedAgents:` line must still mean "deny all descendants" while a
     literal `[]` parses to `["[]"]` and drops the def (`tests/_agent_defs.py::assert_descendant_ceiling`);
   - the **`autoResume` default**: 0.82.0 defaults it `true`, resuming reload/exit-interrupted
     workflows on reopen — a bump to ≥ 0.82.0 must pin it `false` in the managed settings or
     per-activation wave collection breaks (beside the `argsDigest` reuse key above).

   Keep MEASURED observations and SOURCE-DERIVED design apart in the record, and hand a gap the
   source establishes to a repair design — never record it as a measured result.
3. **Update every pin surface, in this order.**
   1. **Dev pins** — `just bump-pi <v>`; commit the lockfile as npm produces it (trimmed per
      `docs/learned/toolchain/worktree-node-modules.md` § "Pi pin-bump mechanics"). It IS the
      characterized single-spec graph: the family's exact declarations leave nothing to float, so
      no registry caret preflight is needed; `npm install --package-lock-only` byte-identical;
      `npm ci` green; `npm prune` drops an orphan a departed member leaves.
   2. **The adopted pin and the family tuple** in `src/perk/substrate/pi_host.py`
      (`PI_ADOPTED_VERSION`, `PI_COMPANION_PACKAGES`).
      `tests/test_pi_host.py::test_pinned_install_family_is_closed_against_the_characterized_lockfile`
      pins the family closed against the lockfile, so a new member fails it first;
      `::test_the_family_declares_itself_exactly_in_the_characterized_lockfile` pins the
      single-spec premise (every declaration exact).
   3. **The floor** in `shared/host-floor.yaml` — the floor guards in the table, plus the
      hard-coded refusal strings in `tests/test_launch.py`, `tests/test_plain_session.py`,
      `tests/test_resume_session_cmd.py`, `tests/test_session_resume.py`,
      `tests/test_launch_materialize.py`, `tests/test_env.py`, `tests/test_doctor.py`,
      `extension/entryAdmission.test.ts`, `extension/index.test.ts`,
      `extension/pi/v1/selfcheck.test.ts` and `extension/substrate/hostAdmission.test.ts`.
      Historical fixtures and CHANGELOG fixtures stay as written.
   4. **The managed remote artifacts**, regenerated through their owner
      (`uv run perk init --no-interactive`, run with the target `pi` first on PATH — init's
      preflight probes PATH `pi` against the new floor; never `perk doctor --fix` before landing,
      see "Pre-land gating" below): one `action.yml` line and the `.perk/managed-state.toml`
      digest move, while `perk-run.yml` stays byte-identical; revert any other hunk init leaves;
      `tests/test_workflow_artifacts.py::test_committed_self_repo_remote_artifacts_are_the_owners_render`
      is the lockstep pin. Never revert an owner's output by hand.
   5. **Measure placement** in throwaway prefixes, on the host toolchain AND under the composite's
      Node line (`mise exec node@<node.min_version> --` prefixing every npm/node call): the
      treatment (`PI_INSTALL_COMMAND`: seven packages from one spec, every one at `<v>` — nested
      inside the global package under `-g`, hoisted under `--prefix` — `pi --version` answers, the
      module link succeeds, and `probe_pi_host` admits the result), the consumer shape
      (`--save-exact`), and pi-subagents' alias resolver answering `missing: []` /
      `outside: []`. The matrix shape is `docs/design/archive/pi-1.1.0-install-pins.md` § The
      preflight matrix (its caret-float control is 1.1.0-era).
   6. **The refusal URL's page and heading** — move the heading and `hostAdmission.test.ts`
      together.
   7. **The supplier pin** (`SUBAGENTS_PACKAGE`). `uv run perk init --no-interactive` converges
      `.pi/settings.json` and the `settings-wiring` digest. Install the exact version the way Pi
      does — remove the stale `.pi/npm/node_modules/pi-subagents` first, then
      `npm install pi-subagents@<v> --prefix <checkout>/.pi/npm --legacy-peer-deps`, with no
      `/reload` afterwards in the running session — and in a worktree only on an independent
      `.pi/npm` (a clonefile stage is independent; otherwise copy the tree first, as
      `pi-subagents-0.76.1-pin.md` did).
   8. **The stamp, LAST**, and only on step 5's evidence.

   None of the pins upgrades the PATH `pi`. `perk doctor --fix` installs the pinned set when the
   `pi` row fails or is not the adopted pin — which is why it is forbidden before landing — and
   doctor's companion check covers only the adopted version's family, so run every live leg in a
   fresh host process whose PATH `pi` is the target.
4. **Run the compatibility, identity and policy tests.** Use targeted checks while iterating; in a
   perk session the gate is ONE run-all `run_ci` immediately before submitting (never bare
   `just ci` in bash, `AGENTS.md` § Developing perk). The run-all gate carries only the fast JS
   tier, so a pin or runtime change also runs `just test-js-slow` explicitly. Then:
   - **the census drift guard** against the live install —
     `node --test extension/substrate/nativeSdkBridge.test.ts` from a checkout with the consumers
     installed (it scans `.pi/npm/node_modules/` and skips where none are installed). A mismatch
     is a real finding: a new SDK specifier means a second SDK copy would load unbridged — extend
     `NATIVE_SDK_CENSUS` and bump `BRIDGE_SCHEMA` in `extension/substrate/nativeSdkBridge.ts`
     (contracts §8.73); a vanished one is a stale entry;
   - **the Pi config-schema producer check** — `tests/test_pi_config_schemas.py` converges
     representative repos with `perk init` (consumer and self-repo wiring, the borrowed, provider
     and Linear entries, the filtered Ponytail object, `subagents.disableBuiltins` beside an
     operator's `agentOverrides`, `[compaction]`, `[models]` at every thinking level) plus the
     committed `.pi/settings.json`, validates each against the pinned dev package's
     `schemas/settings.schema.json` through `extension/testing/piConfigSchemasLive.ts`, and pins
     `PI_THINKING_LEVEL_ORDER` equal to the schema's `ModelThinkingLevel` enum;
     `extension/testing/piConfigSchemas.test.ts` proves the loader (the resolved manifest version
     equals the dev pin), the validators' controls and the harness's planted `models.json` against
     `schemas/models.schema.json`. Both run inside the run-all `run_ci`. The schemas are read from
     the resolved dev package — never vendored or fetched — so `just bump-pi` is the refresh. A
     failure is a finding: a perk-written value outside the new Pi's contract, a Pi thinking level
     added or removed (widen or narrow `PI_THINKING_LEVEL_ORDER` and its docs), or, when the
     loader names a version mismatch, a stale root `node_modules` (`npm install` in the
     checkout). If a release stops shipping `schemas/`, the loader fails naming it; vendoring is
     then a recorded fallback decision;
   - **the live bridge smoke**, `tests/test_native_sdk_bridge_live.py`, on both the PATH `pi` and
     the pinned CLI, each with a captured `/perk-selfcheck`: its two positive tests
     (`test_the_installed_pi_subagents_is_the_managed_pin`,
     `test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded`) must RUN and
     pass — a skip of either means the gate environment is wrong (PATH `pi` not admitted, or a
     consumer missing under `.pi/npm`); the negative control
     `test_a_below_floor_real_pi_refuses_to_load_perk` skips by design on an admitted host.
     Exactly its two `SUBAGENTS_PACKAGE`-bound assertions move with the supplier pin;
   - **the in-process child identity proof** — one blocking `perk.scout` through
     `dispatchForeground` under the module tracer, with the bridge-off control
     (`PERK_DISABLE_NATIVE_SDK_BRIDGE=1`), as `docs/design/archive/pi-subagents-0.76.1-pin.md`
     recorded it;
   - **the policy suites** — `tests/test_subagent_agents.py` and `tests/test_repo_local_agents.py`
     (the descendant ceiling; a removed-field throw fails every def at load),
     `extension/substrate/mcpReadOnlyFloor.test.ts`,
     `extension/substrate/restorationWindow.test.ts`,
     `extension/substrate/restoredDiscovery.test.ts`, `extension/substrate/codemodeLift.test.ts`,
     and the lifecycle matrix in `extension/waves/reportWaveRpc.test.ts`,
     `extension/waves/reportWave.test.ts` and `extension/pi/v1/waveIsolation.test.ts`. The fake
     `extension/testing/fakeSubagents.ts` mirrors the RPC where perk touches it — a wire change
     is mirrored there first.
5. **Elect live-leg owners.** The legs: `perk doctor` (the `pi` row and `subagent-compat`), both
   browser doors (`/plan-review-browser`, `/pr-review-browser`) to N/N coverage, repeated
   collection, PR-wave launch, codemode composition in a read-only stage, worker MCP, the
   subagent-under-worker cell, the remote drive, and the lifecycle cells (below). A browser leg
   passes on the five push-receipt criteria (launch, collect, delivery, decision order, owner
   observation) in `docs/learned/pi/subagents.md` § Sources — the push receipts, not the collect
   result, are the instrument. A failed leg is diagnosed, fixed and re-run once; if it still fails, record the
   FAIL (step 8), leave the stamp where it was (an honest `warn`), and stop for owner diagnosis.

   **The owner-election arm.** The browser doors are human-in-the-loop, so an implementing agent
   cannot drive them from its own session. The owner may elect to move the stamp on the source
   re-read + the doctor/scout/offline halves — an explicit, recorded decision (the plan's
   `## Assumptions` + the archive record's verdict line), never a default. That was done at
   0.68.0, 0.70.1 and 0.75.0; 0.73.1 waited for every half; 0.76.1 was adopted ahead of its
   certification and the certification HELD; 0.81.0 was adopted with Pi 1.4.0 ahead of its
   certification, whose record (`docs/design/archive/pi-1.4.0-certification.md`, 2026-10-25) then
   moved the stamp to 0.81.0 (its supplier rows passed) with 4 required cells NOT RUN (X1, X2, X3,
   C3-only). The record — and the `## Sources` provenance line of
   `docs/learned/pi/subagents.md` — then names the browser-door half as **owed**.

   **The self-referential gate.** A leg scheduled on the bump PR's own review door waits on the
   review of itself and never runs: elect it owed to the next node's sessions, or give the live
   legs their own node. **A held certification gets its own re-certification node** (the
   7.1 → 7.3 precedent of objective #2707), and the stamp moves only when every required supplier
   row passes.

   **Live legs — prerequisites and instrument notes:**
   - valid runner `PERK_GH_PAT`s in perk and in the consumer fixture (an expired token fails at
     `actions/checkout`, invisible to doctor's `runner-pat-secret`, which checks presence only) and
     `OPENAI_API_KEY` for the `review-classifier` binding — BEFORE the remote and U-bg legs;
   - every leg in a fresh host process whose PATH `pi` is the target;
   - ask for the `perk:wave` marker while the wave runs — it clears at collection;
   - keep the owner at the browser for a DENY leg: a `/plan-save` ends the read-only stage;
   - resume with the RUN_ID arm when a cell names it;
   - `run-worker` passes no `--model`, so a local worker runs the SDK default model;
   - a drive-scoped `TMPDIR` reaches worker children;
   - `perk plan save`, a `--remote` dispatch and `/plan-save` rewrite the main checkout's
     `plan-ref.json` cache — back it up first;
   - the cells, the probes (with their SHA-256s) and the sacrificial plan bodies are in
     `docs/design/archive/pi-1.1.0-certification.md` § Methodology appendix.

   **The lifecycle cells W4, W6, W7a (the live-matrix rows, re-specified 2026-10-25).** The 1.1.0
   certification (`docs/design/archive/pi-1.1.0-certification.md` § W) measured all three FAIL
   against their 0.76.1-era rows (`pi-subagents-0.76.1-lifecycle.md` § "Deferred live legs"). W6
   is repaired in perk (contracts §8.35); W4 keeps activation-local collection and is staged
   through the production draft-review tool pair; W7a scores proof and refusal classes, never
   engine reason text. Each cell has a fixed disposition: a leg that is not staged is re-run, never
   scored. That archive record closes with the table as re-specified on 2026-10-25
   (§ "Re-specified cells"); W7a(i)'s row here additionally carries the 1.4.0 certification's
   dated staging amendment, which neither dated archive restates.

   | Cell | Procedure (3.1 instantiates the 1.1.0 appendix's probe with the deltas below) | PASS iff | FAIL iff / not staged |
   |---|---|---|---|
   | **W6** live deadline partial | `PERK_WAVE_TIMEOUT_MS=20000`, `/probe-wave deadline <model>` (lanes `lane-quick` + `lane-long` "Read AGENTS.md and summarize it in 600 words."); record the RPC sends, the collected result, `<asyncDir>/status.json`. Staging: `status.json.workflowChildren` shows `lane-long` `state: "running"` at settlement; if `lane-long` finished before the deadline the leg is **not staged** — re-run with a longer task, never scored. | (1) the completion carried the explicit `terminalOutcome {partial, timeout}` and was consumed inside the grace (`failures[0]` = `{key: null, reason: "run-failed"}`, detail matching `native partial: timeout`); (2) `reports` = exactly `[lane-quick]`; (3) `failures[1]` = `{key: "lane-long", reason: "lane-failed", detail: "lane still running at native partial settlement"}`; (4) `complete: false`; (5) receipt `state: "failed"`, children = `lane-quick` only, no report bytes; (6) perk's RPC sends are exactly `ping`, `spawn`. | `lane-long` reported `missing-lane` or any other reason/detail; a report dropped or promoted; a `stop`/`status` sent. |
   | **W4** completion-while-busy → Escape → `/reload` → prompt (activation-local collection retained; the production draft-review tool pair owns the wave) | A `perk plan` read-only session in tmux on the appendix's sacrificial plan body (the X5a instrument). (1) prompt: write the sacrificial draft via `plan_draft`, then stop; (2) `/plan-review-browser`, accept the reviewer wave → the model calls `start_draft_review_wave` and yields — record the JSONL tool-result (`ok: true`, `asyncId`, `launch.runnable`); (3) immediately: `` Run exactly `sleep 170` with bash and then reply OK; nothing else. `` — record the JSONL timestamp of the `bash` tool call that starts the sleep; (4) record the completion timestamp (`<asyncDir>/status.json` `endedAt`); (5) Escape — record the timestamp and the JSONL entry that ends that `bash` call (an aborted result or turn, not a completed `sleep`); (6) 30 s idle; (7) `/reload`; (8) 60 s idle; (9) one prompt: `Call collect_draft_review_wave now and report its error_type verbatim; do nothing else.`; (10) re-read `status.json`; teardown: close the browser tab, never `/plan-save`. Staging: the (3) `bash` call started before (4) and was still running at (4) (no `bash` tool result before (5)); (4) precedes (5); (5) interrupts that call (its result or turn is aborted, never a completed `sleep`); AND the JSONL holds the (2) start result and NO `collect_draft_review_wave` result before (7) — else **not staged** (re-run — with a longer sleep when the wave outlasted it — never scored). | (a) no agent turn starts automatically between (5) and (9): the session JSONL holds no assistant message and no custom-message-started turn in that interval and the pane shows the idle editor through (6) and (8) — the presence/absence of a `subagent-notify` message is RECORDED, not scored; (b) `<asyncDir>/status.json` parses at (7)+ and at (10) with `state: "complete"` and an array `workflow.value` carrying every lane's `ok: true` entry (the result/index file's state is recorded, not scored); (c) the JSONL tool-result entry for `collect_draft_review_wave` at (9) carries `details.error_type: "no_wave"` and text containing `collection is per activation` — evidence of the collection boundary only because (2) proved the predecessor activation owned the uncollected wave. | an automatic wake/agent turn in (6) or (8); `status.json` missing or non-terminal; any collector answer but `no_wave`. The 1.1.0 auto-wake expectation is retired; a notice resend is neither required nor forbidden. |
   | **W7a(i)** cancel-while-running | `PROBE_CANCEL_DELAY_MS=10000 /probe-wave cancel <model>` (lane `lane-long`, the 600-word task): the probe waits for the runner pid, then for `subagent.run.started` in the child's `events.jsonl` (delta (4) below), waits 10 s, aborts; record the stop reply (with its timestamp), the immediate projected proof, the child's `subagent.run.started` timestamp, and ONE scored `status {id}` at **stop acknowledgement + 60 s**. Staging (amended 2026-10-25T02:54:34Z by the 1.4.0 certification's dated operator amendment): at abort time the child's `status.json` reads `state: "running"` with a numeric `pid` AND the child's `events.jsonl` (the child's run directory — a sibling of the workflow's `<asyncDir>` named by the child's run id) holds a `subagent.run.started` event timestamped before the abort, else **not staged** — re-run, never scored; an immediate proof of class `observed` means the child had already terminated at the read — **not staged**, re-run with a longer task (1500 words), never scored. | (1) `termination.stop.acknowledged === true` (detail contains `; stop requested;`); (2) the immediate projected proof is class `pending` — `Workflow dispatch is still open.` or the reason naming `lane-long`, whichever the instant of the read yields (text recorded, not asserted); (3) the 60 s re-query answers `details.workflowTerminalProof.state === "observed"`. | (1) fails; the immediate proof is `unknown`/`unavailable`; or the 60 s re-query answers `unknown` (record `reason` — e.g. `writer-close-unverified` — the runner close exit code and the child's `process-terminal.json` state/reason) or `pending` (record the reason) or no proof. Never inferred termination (a dead pid, `endedAt`, a freed slot); never an upstream waiver. A later re-query is a recorded diagnostic, never a score. A stop that landed before the child's `subagent.run.started` is **not staged** (the never-started-writer stop, below): record its stop reply, the event's later timestamp and the proof at + 60 s as an instance of the constrained capability — never a PASS, never a FAIL, never inferred termination. |
   | **W7a(ii)** reload-then-stop | `/probe-wave start-long <model>` (the 600-word task; the mode waits for the runner pid and logs it before returning, handle → `PROBE_HANDLE_FILE`) → within 5 s before the `/reload` keystroke record `<asyncDir>/status.json` `state: "running"` and the child's `status.json` `state: "running"` + pid (timestamped) → `/reload` → record the workflow's post-reload `status.json` state/`stopCause` → `/probe-stop` on the SAME handle (raw RPC `stop` + perk's adapter `stop`/`terminalProof`). Staging: the pre-reload reads show both running, else **not staged** (re-run with a longer task, never scored). | the raw reply is `success: false` with `error.code === "invalid_state"` (message recorded, not asserted); the adapter projects `acknowledged: false` with `reason` starting `invalid_state: `, the detail renders `stop refused (invalid_state: …)`, and `terminalProof` projects one of `observed` / `pending` / `unknown` / `unavailable` (recorded). | the stop is acknowledged; the refusal code is not `invalid_state`; the adapter throws or projects no proof. |

   **The never-started-writer stop (W7a(i)'s recorded constrained capability, 2026-10-25).** A
   stop that lands after the child's runner pid appears but before that runner starts its Pi
   child closes the runner with no writer ever started. pi-subagents 0.81.0's
   `src/runs/background/process-terminal.js` then writes a permanent `unknown` process-terminal
   proof with reason `writer-close-unverified` (its
   `allWriters.length === 0 && expectedEntries.length === 0` arm; the file is byte-identical in
   0.82.0), and perk renders `child termination unconfirmed (unknown: …)` — uncertainty perk
   never upgrades (contracts §8.35). The recorded instance is the 1.4.0 certification's W7a(i)
   run 1 (`docs/design/archive/pi-1.4.0-certification.md` § W: abort 02:23:33.914Z with the
   child `running`, `subagent.run.started` 02:23:35.904Z, proof `unknown` at + 60 s; FAIL under
   the original staging, which that record keeps). It is never a PASS, never inferred
   termination (a dead pid, `endedAt`, a freed slot) and never an upstream waiver; it is a
   constrained capability (`CONTEXT.md` § Constrained capability) whose retirement condition is
   a supplier release whose process-terminal proof resolves a runner that closed without ever
   starting a writer — re-read that arm at the next bump (step 2's terminal-proof bullet) and
   re-measure a deliberately early stop before dropping the staging requirement above. Until
   then the `subagent.run.started` staging keeps a timing artifact from scoring W7a(i).

   **Probe deltas applied when instantiating `probe-wave.ts` from the 1.1.0 appendix (3.1 applied (1)–(3) from the start and (4) under the dated amendment):** (1) `start-long` calls `waitRunnerPid` and logs the child before returning; (2) `cancel` logs the `stop` reply timestamp (the `rpc-send`/reply pair) and schedules its scored manual `status` at that timestamp + 60 s instead of sleeping 30 s after `drain()`; (3) W4 uses no probe wave — `/probe-wakes` is optional recording only; (4) `cancel`, after the runner pid, waits (up to 120 s) for a `subagent.run.started` event in the child's `events.jsonl`, starts the `PROBE_CANCEL_DELAY_MS` delay only then, and logs the event's timestamp beside the child's `status.json` state and pid at abort (`child-run-started`, then `abort` with `childRunStartedAtAbort` / `childStateAtAbort` / `childPidAtAbort`). The final probe with all four applied is the 1.4.0 certification's § "The probe deltas (verbatim)" (`probe-wave.ts` SHA-256 `dba8bc36…` in its Instruments table).

6. **Recheck the retained adaptations' retirement conditions** — the table in
   `docs/planning/pre-pi-durable-true-up.md` § Retained adaptations (its re-check column) and the
   certification's K rows. The host SDK bridge retires only on an in-process child + lazy-import
   identity proof whose bridge-off control observes zero escapes (it observed 33 at 0.76.1).
7. **Reconcile the evidence-contingent prose the same turn.** These carriers are written in their
   owed/held form and flipped together by the commit that appends the evidence: contracts
   §8.76(b); `docs/user-docs/reference/requirements-and-compatibility.md` and
   `docs/user-docs/reference/cli/setup-and-health.md` (its `subagent-compat` paragraph);
   `skills/perk-expert/references/configuration.md`; `CONTEXT.md` (**Adopted Pi pin**); this
   guide's standing-decision paragraph; and `docs/learned/pi/subagents.md` § Sources and
   `## History (dated)`, via `/learn`. Statements the new release *falsifies* are swept
   immediately — `shared/contracts.md`, the user docs and the learned docs alike, per
   `docs/learned/workflow/doc-reconciliation.md`'s same-turn rule; `uv run perk learn docs-check`
   confirms the navigation is still current. Only genuinely NEW learnings go through `/learn`.
8. **Record the evidence**: a dated record in `docs/design/archive/` with the exact versions, the
   file/function anchors, the decisions, and every leg's outcome in the vocabulary PASS / FAIL /
   DEFERRED (owed, with its owner) / NOT RUN (a missing prerequisite, or not attempted) / HELD —
   never omitted, never patched around. The templates: `pi-subagents-native-baseline-dogfood.md`
   (0.65.1), `pi-subagents-0.68.0-reverify.md`, `pi-subagents-0.70.1-reverify.md`,
   `pi-subagents-0.73.1-reverify.md`, `pi-subagents-0.75.0-reverify.md` (with the trust matrix
   and the headless-exit rows on a Pi 1.0.0 throwaway), `pi-subagents-0.76.1-pin.md` (adoption
   ahead of certification), `pi-subagents-0.76.1-lifecycle.md` (live legs deferred),
   `pi-1.1.0-characterization.md`, `pi-1.1.0-install-pins.md`, `pi-1.1.0-certification.md`
   (HELD) and `pi-1.4.0-adoption.md` (the pair adopted ahead of certification, single-spec
   install).

## Pre-land gating and the post-land cutover

The global `pi` is one shared host: every checkout, every worktree and every running session on
the machine uses it. A bump PR therefore gates against an **isolated** Pi and leaves the global
one alone until the change lands.

**Pre-land (the implement session).** Install the target into a throwaway prefix —
`npm install --prefix <tmp> @earendil-works/pi-coding-agent@<v>` — and put `<tmp>/node_modules/.bin`
first on PATH, with the host Node line selected, before launching the implement session; the
session, `run_ci` (each row runs through a login shell that keeps the PATH prefix), `perk init`
and the live PATH-`pi` tests then all see the target. Install the supplier into the worktree's own
`.pi/npm` (step 3.7). **Never `perk doctor --fix` before landing:** `env.repair_pi` would install
the pinned set into the global prefix while the main checkout and sibling worktrees still load the
previous supplier — a running previous-supplier session resolves the host package by path at its
next background-runner launch and breaks against the new host.

**Post-land (the operator, in a fresh process).** Prerequisite: finish or cancel every outstanding
wave or child and close every perk session on the machine. Then run `PI_INSTALL_COMMAND` (or
`perk doctor --fix` from the main checkout) and check that `perk doctor`'s `pi` row reads the
target; the earlier top-level companions may be removed with `npm uninstall -g` when convenient.
Run `npm ci` in the main checkout (its `node_modules` lags the manifest until then — never run the
suites from it before), and its supplier walks forward at the next Pi launch through the committed
`.pi/settings.json` pin. A sibling worktree still on a pre-bump branch (the old supplier pin and
hooks) is rebased onto main before waves run there, or closed — perk keeps no separate old-host
prefix, and the pre-land `<tmp>` prefix is a gate fixture, not a fallback host.

## The standing pin decision

pi-subagents is **pinned** to exact 0.81.0 (`SUBAGENTS_PACKAGE =
"npm:pi-subagents@0.81.0"` in `src/perk/convergence/init/settings.py`), adopted with Pi 1.4.0 on
characterization + offline evidence (`docs/planning/pi-and-subagents-assessment-2026-10-24.md`,
`docs/design/archive/pi-1.4.0-adoption.md`). perk's report waves send the inline script text under
the RPC spawn key `script`, which pi-subagents accepts since 0.74.0
(`docs/design/archive/pi-subagents-0.75.0-reverify.md`). The pin and the guidance stamp agree at
0.81.0: the pair's certification record (`docs/design/archive/pi-1.4.0-certification.md`,
2026-10-25) holds 4 required cells NOT RUN (X1, X2, X3, C3-only) and no required FAIL, so the pair
is adopted, not certified, and the guidance stamp is 0.81.0 (the certification's supplier rows
passed), so `subagent-compat` reads ok on a converged checkout. The previous pair's live
certification (`docs/design/archive/pi-1.1.0-certification.md`) HELD Pi 1.1.0 + 0.76.1 and kept
the stamp at 0.75.0, because W4, W6 and W7a failed and S3, S4a-live, U-bg, X5a and X5b were not
run; W6 was then repaired and W4/W7a re-specified (step 5's lifecycle-cell table, 2026-10-25), and
the 1.4.0 certification measured all three.
`perk init` writes the pinned spec and reconciles an existing unpinned or differently pinned
entry forward; `perk doctor --fix` repairs the same drift through `settings-wiring`. Pi installs
whatever the checkout's own committed `.pi/settings.json` names, so the pin reaches a branch only
with the change that moves it.

The re-verify ritual above decides **moving the pin**: the pin and the guidance stamp are two
distinct facts (what consumers install vs. what perk's guidance was verified against) that move
together only on evidence covering both — the source re-read, `run_ci` with the census drift
guard, and the live legs — or, when a release is adopted ahead of its live certification, the pin
moves first on characterization and offline evidence and the stamp follows the certification;
either way the record names which halves are owed. The browser-door halves cannot gate the stamp
PR's own merge — a leg scheduled on that PR's own review door waits on the review of itself and
does not run — so elect both halves up front as owed to the next node's sessions, or give the
live legs their own node (step 5); the evidence-contingent prose stays in its owed form until the
commit that appends the evidence flips every carrier. A release that breaks a surface perk sends
needs its migration first, in the same change as the pin.
