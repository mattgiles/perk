# How to re-verify pi-subagents after an upstream bump

This page is a **how-to guide**. perk consumes the borrowed `pi-subagents` engine only through
public surfaces (the v1 RPC envelope, the delegation events, agent-def frontmatter), so
compatibility rests on a *recorded baseline*, a consumer pin (see "The standing pin decision"),
and this re-verify ritual — never on reading the installed source from tests or doctor. One carve-out: the host-SDK bridge's **census drift guard**
(`extension/substrate/nativeSdkBridge.test.ts`) lexes the installed consumers' *import specifiers*
— a structural fact of the shipped artifact (which SDK modules it imports), not engine mechanics —
so a new release that imports an SDK subpath perk does not bridge fails loudly instead of silently
loading a second SDK copy.

**When to re-verify:** `perk doctor`'s `subagent-compat` check **warns** (installed version ≠
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`), or you are about to build on new engine mechanics.

## Steps

1. **Read the installed version** and compare it with `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` in
   `src/perk/convergence/doctor/checks.py`:
   `node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"`.
2. **Re-read the source.** The installed package under `.pi/npm/node_modules/pi-subagents/`
   ships compiled JavaScript since 0.70.0 (`pi.extensions: ["./index.js"]`, `src/**/*.js` with
   `.d.ts` files and source maps; ≤ 0.68.x shipped `src/**/*.ts`) — re-read it in place: the
   module and function anchors below survive compilation, so `grep -n` over `src/**/*.js` finds
   them. Fall back to the matching tag of `nicobailon/pi-subagents` (`gh api` / `gh browse`, or a
   local clone at the tag) only for a fact the compiled output obscures. Read the release notes
   (the package's `CHANGELOG.md`) for the version either way. Walk each engine mechanic
   `docs/learned/pi/subagents.md` states (its `## Sources` names the baseline):
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
   - the **fork-context repair** for Pi 0.87 (the checkout-only fix): confirm whether the
     installed artifact carries it; until it does, perk children stay on `context: "fresh"`
     (the support boundary recorded in `docs/design/pi-subagents-child-execution-policy.md`);
   - the **RPC spawn key** (`src/extension/rpc.ts::spawnParams`): perk sends the inline script
     text as `script`, which the engine copies onto its internal `workflowScript` carrier; since
     0.74.0 a request carrying `workflowScript`/`workflowScriptPath` (an `Object.hasOwn` check, so
     an `undefined` value counts) is rejected `invalid_params`. A rename here is a wire break the
     fake responder (`extension/testing/fakeSubagents.ts`) must mirror;
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
     resume). perk's `ReportWave` pending map is per-activation, so a wave launched before
     `/reload` stays uncollectable afterwards; an identical relaunch after `/reload` reuses the
     replaced run's finished lanes;
   - the **`disabledFeatures` surfaces** (`src/shared/disabled-features.ts`): the features whose
     parameters perk sends (`workflow-scripts`, `missions`, `extension-bindings`) refuse every
     wave with the engine's own setting-naming message — surfaced verbatim, never mapped.
3. **Run `just ci`.** Then run the host-SDK bridge's census drift guard against the live install
   — `node --test extension/substrate/nativeSdkBridge.test.ts` (it scans the consumers under this
   checkout's `.pi/npm/node_modules/` and skips where none are installed, so this checkout is where
   it runs for real). A census mismatch is a real finding: a new SDK specifier means a second SDK
   copy would load unbridged — extend `NATIVE_SDK_CENSUS` and bump `BRIDGE_SCHEMA` in
   `extension/substrate/nativeSdkBridge.ts` (contracts §8.73); a vanished one is a stale entry.
4. **Run the live leg** from a read-write session whose installed pi-subagents is the new
   version: `perk doctor` (`subagent-compat` warns until the stamp moves; no
   `subagent-host-tools` row), then one `/plan-review-browser` wave and one `/pr-review-browser`
   wave to N/N coverage
   — the `perk:wave` marker appears at launch and clears at collection, and the final
   annotations land after `collect_*`. A leg passes on the five push-receipt criteria (launch,
   collect, delivery, decision order, owner observation) in `docs/learned/pi/subagents.md`
   § Sources — the push receipts, not the collect result, are the instrument. **The stamp moves only on a passing leg**: bump
   `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and
   `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` together. A
   failed leg is diagnosed, fixed, and re-run once; if it still fails, record the FAIL verdict
   (step 6), leave the stamp where it was (an honest `warn`), and stop for owner diagnosis.
   **The owner-election arm:** the browser doors are human-in-the-loop, so an implementing agent
   cannot drive them from its own session. The owner may elect to move the stamp on the source
   re-read + the doctor/scout/offline halves (done for 0.68.0 and 0.70.1; 0.73.1 waited for every
   half) — an explicit, recorded decision (the plan's `## Assumptions` + the archive record's
   verdict line), never a default; otherwise the bump follows the letter of this step. The
   record — and the `## Sources` provenance line of `docs/learned/pi/subagents.md` — then names
   the browser-door half as **owed** and the requirements page describes the version as the
   source-verified guidance baseline, not a live-certified one; the owed half is appended to the
   record from the first live browser wave on that host.
5. **Reconcile the prose the same turn.** Statements the new release *falsifies* are swept
   immediately — `shared/contracts.md`, the user docs, and the learned docs alike
   (`docs/learned/pi/subagents.md` — its `## Sources` re-read line, `## History (dated)`, and any
   mechanic paragraph; `docs/learned/workflow/report-waves.md`), per
   `docs/learned/workflow/doc-reconciliation.md`'s same-turn rule; `uv run perk learn docs-check`
   confirms the navigation is still current. Only genuinely NEW learnings go through `/learn`.
   Also update the `subagent-compat` paragraph in
   `docs/user-docs/reference/cli/setup-and-health.md` if its wording moved.
6. **Record the evidence**: a dated note in `docs/design/archive/` — the source facts with
   file/function anchors, the decisions, and the live-leg outcome (PASS or FAIL, never omitted).
   `pi-subagents-native-baseline-dogfood.md` (0.65.1), `pi-subagents-0.68.0-reverify.md`
   (0.68.0), `pi-subagents-0.70.1-reverify.md` (0.70.1), `pi-subagents-0.73.1-reverify.md`
   (0.73.1) and `pi-subagents-0.75.0-reverify.md` (0.75.0, with the trust matrix and the
   headless-exit rows on a Pi 1.0.0 throwaway) are the templates.

## The standing pin decision

pi-subagents is **pinned** to the re-verified release (`SUBAGENTS_PACKAGE =
"npm:pi-subagents@0.75.0"` in `src/perk/convergence/init/settings.py`). perk's report waves send
the inline script text under the RPC spawn key `script`, which pi-subagents accepts since 0.74.0
(`docs/design/archive/pi-subagents-0.75.0-reverify.md`). `perk init` writes the pinned spec and
reconciles an existing unpinned or differently pinned entry forward; `perk doctor --fix` repairs
the same drift through `settings-wiring`. Pi installs whatever the checkout's own committed
`.pi/settings.json` names, so the pin reaches a branch only with the change that moves it.

The re-verify ritual above decides **moving the pin**: the pin and the guidance stamp are two
distinct facts (what consumers install vs. what perk's guidance was verified against) that move
together only on evidence covering both — the source re-read, `run_ci` with the census drift
guard, and the live leg. The browser-door halves cannot gate the stamp PR's own merge — a leg
scheduled on that PR's own review door waits on the review of itself and does not run — so elect
both halves up front as owed to the next node's sessions, or give the live leg its own node
(step 4's owner-election arm); the evidence-contingent prose stays in its owed form until the
commit that appends the evidence flips every carrier. A release that breaks a surface perk sends
needs its migration first, in the same change as the pin.
