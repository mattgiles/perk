# How to re-verify pi-subagents after an upstream bump

This page is a **how-to guide**. perk consumes the borrowed `pi-subagents` engine only through
public surfaces (the v1 RPC envelope, the delegation events, agent-def frontmatter) and the
package is deliberately **unpinned**, so compatibility rests on a *recorded baseline* plus this
re-verify ritual — never on a version constraint and never on reading the installed source from
tests or doctor.

**When to re-verify:** `perk doctor`'s `subagent-compat` check **warns** (installed version ≠
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`), its `subagent-host-tools` check **warns** (the installed
version is in the host-tool-intersection affected range and pi-fff resolves to `override`), or
you are about to build on new engine mechanics.

## Steps

1. **Read the installed version** and compare it with `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` in
   `src/perk/convergence/doctor/checks.py`:
   `node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"`.
2. **Re-read the source at the upstream tag.** The installed package ships compiled JS + `.d.ts`
   only (`scripts/build-package.mjs` publishes `src/**/*.js`, no `.ts`), so the source re-read
   happens against the matching tag of `nicobailon/pi-subagents` — `gh api` / `gh browse` on
   the tag, or a local clone checked out at it — and the release notes for that version. Walk
   each engine mechanic `docs/learned/pi/subagents.md` states (its `## Sources` names the
   baseline):
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
     `fallbackModels`; a new removal fails every delivered def at load and shows up as 0/N
     waves, so grep `agents/*.md` for the named field) and its `completionGuard: false`
     handling: a report-only lane must complete on a valid `structured_output` report and still
     fail a missing/invalid one (`run_ci` cannot catch this);
   - the **host-tool intersection**: `getHostBuiltinToolNames` / `resolvePiLaunchToolPlan` /
     `isReviewOrScoutLaneAgent` in `src/runs/shared/child-tool-plan.ts` and the
     `hostAvailableBuiltins` call sites in `src/runs/background/async-execution.ts`. The 0.67.x
     engine counted only builtin-*sourced* host tools, so pi-fff `override` (re-registering
     `grep`/`find`) failed review/scout-named agents closed at launch; 0.68.0's
     `getHostBuiltinToolNames` counts wrapped core slots regardless of source. The affected
     range is closed: `_SUBAGENTS_HOST_INTERSECTION_AFFECTED = ("0.67.0", "0.68.0")` (exact pin
     `tests/test_doctor.py::test_subagent_host_tools_affected_range_is_pinned`). perk keeps
     injecting `PI_FFF_MODE=tools-and-ui` (`FFF_MODE_ENV`) as a harmless additive default; if a
     later release reintroduces a source-classified census, open a NEW range rather than
     reopening this one.
3. **Run `just ci`.**
4. **Run the live leg** from a read-write session whose installed pi-subagents is the new
   version: `perk doctor` (`subagent-compat` warns until the stamp moves; `subagent-host-tools`
   `ok`), then one `/plan-review-browser` wave and one `/pr-review-browser` wave to N/N coverage
   — the `perk:wave` marker appears at launch and clears at collection, and the final
   annotations land after `collect_*`. **The stamp moves only on a passing leg**: bump
   `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and
   `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` together. A
   failed leg is diagnosed, fixed, and re-run once; if it still fails, record the FAIL verdict
   (step 6), leave the stamp where it was (an honest `warn`), and stop for owner diagnosis.
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
   `pi-subagents-native-baseline-dogfood.md` (0.65.1) and `pi-subagents-0.68.0-reverify.md`
   (0.68.0) are the templates.

## The standing pin decision

pi-subagents stays **unpinned** (owner-affirmed): perk tracks the engine's latest and pays for
it with this early-warning + re-verify discipline instead of a pin/upgrade lifecycle. If drift
ever becomes too expensive, pinning is a one-line `.pi/settings.json` change — and the recorded
baseline names exactly which version to pin.
