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
2. **Re-read the installed source** for each engine mechanic `docs/learned/pi/subagents.md` states
   (its `## Sources` names the baseline) — supervisor-channel delivery and wakes, the typed child
   runtime config, the omitted-async semantics, the in-process async workflow host, structured
   output, the v1 RPC envelope, the partial-settlement projection — and the agent-definition
   parser's `completionGuard: false` handling: a report-only lane must complete on a valid
   `structured_output` report and still fail a missing/invalid one (`run_ci` cannot catch this).
   Also re-read the **host-tool intersection**: `getHostBuiltinToolNames` /
   `resolvePiLaunchToolPlan` / `isReviewOrScoutLaneAgent` in
   `src/runs/shared/child-tool-plan.ts` and the `hostAvailableBuiltins` call sites in
   `src/runs/background/async-execution.ts`. Since 0.67.0 the engine intersects a child's declared
   tools with the tools the *host* session reports as builtin-sourced, so an extension that
   re-registers a builtin by name (pi-fff `override` mode shadows `grep`/`find`) fails
   review/scout-named agents closed at launch — which is why perk's launches inject
   `PI_FFF_MODE=tools-and-ui` (`FFF_MODE_ENV`). If the installed release counts a same-name
   replacement as providing the builtin (or no longer intersects background children), set the
   upper bound of `_SUBAGENTS_HOST_INTERSECTION_AFFECTED` in
   `src/perk/convergence/doctor/checks.py` (and its exact pin,
   `tests/test_doctor.py::test_subagent_host_tools_affected_range_is_pinned`) and decide whether
   to restore `FFF_MODE_ENV` to `override`.
3. **Run `just ci`.**
4. **Bump the stamp**: `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and
   `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned`.
5. **Reconcile the prose**: the `docs/learned/pi/subagents.md` `## Sources` re-read line via `/learn`, and the
   `subagent-compat` paragraph in `docs/user-docs/reference/cli/setup-and-health.md`.
6. **Record the evidence**: a dated note in `docs/design/archive/` (the 0.65.1 record,
   `pi-subagents-native-baseline-dogfood.md`, is the template).

## The standing pin decision

pi-subagents stays **unpinned** (owner-affirmed): perk tracks the engine's latest and pays for
it with this early-warning + re-verify discipline instead of a pin/upgrade lifecycle. If drift
ever becomes too expensive, pinning is a one-line `.pi/settings.json` change — and the recorded
baseline names exactly which version to pin.
