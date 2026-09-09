# How to re-verify pi-subagents after an upstream bump

This page is a **how-to guide**. perk consumes the borrowed `pi-subagents` engine only through
public surfaces (the v1 RPC envelope, the delegation events, agent-def frontmatter) and the
package is deliberately **unpinned**, so compatibility rests on a *recorded baseline* plus this
re-verify ritual — never on a version constraint and never on reading the installed source from
tests or doctor.

**When to re-verify:** `perk doctor`'s `subagent-compat` check **warns** (installed version ≠
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`), or you are about to build on new engine mechanics.

## Steps

1. **Read the installed version** and compare it with `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` in
   `src/perk/convergence/doctor/checks.py`:
   `node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"`.
2. **Re-read the installed source** for each mechanic enumerated under the version anchor in
   `docs/learned/pi/subagents.md` — supervisor-channel delivery and wakes, the typed child
   runtime config, the omitted-async semantics, the in-process async workflow host, structured
   output, the v1 RPC envelope, the partial-settlement projection — and the agent-definition
   parser's `completionGuard: false` handling: a report-only lane must complete on a valid
   `structured_output` report and still fail a missing/invalid one (`run_ci` cannot catch this).
3. **Run `just ci`.**
4. **Bump the stamp**: `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and
   `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned`.
5. **Reconcile the prose**: the `docs/learned/pi/subagents.md` version anchor via `/learn`, and the
   `subagent-compat` paragraph in `docs/user-docs/reference/cli/setup-and-health.md`.
6. **Record the evidence**: a dated note in `docs/design/archive/` (the 0.65.1 record,
   `pi-subagents-native-baseline-dogfood.md`, is the template).

## The standing pin decision

pi-subagents stays **unpinned** (owner-affirmed): perk tracks the engine's latest and pays for
it with this early-warning + re-verify discipline instead of a pin/upgrade lifecycle. If drift
ever becomes too expensive, pinning is a one-line `.pi/settings.json` change — and the recorded
baseline names exactly which version to pin.
