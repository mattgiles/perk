---
title: "How to dispatch a stage to a remote runner"
description: "Hand an unattended stage off to a CI runner instead of running it locally, with the --remote cold door."
sidebar:
  order: 2230
sidebarGroup: "Headless & remote"
---

# How to dispatch a stage to a remote runner

Hand an unattended `implement` or `address` stage to the configured CI runner instead of opening a
local Pi session.

## Steps

1. **Verify the runner first.** Complete [the remote-runner setup](./set-up-the-remote-runner.md),
   including its waited smoke test.
2. **Select the saved plan and dispatch.** Use the direct command for the work you need:

   ```bash
   perk implement 42 --remote
   perk pr address 42 --remote
   ```

   To continue an approved saved plan without choosing the stage yourself, let the shared resume
   classifier select it:

   ```bash
   perk plan resume 42 --remote
   ```

   Resume dispatches only when the selected next stage is remotely eligible. A remote dispatch
   records the perk run-to-plan linkage, triggers GitHub Actions, and lets the runner create or
   restore the plan branch in CI.
3. **Leave local positioning options behind.** Only unattended `implement` and `address` stages are
   remote-drivable. Interactive or deterministic stages remain local, and `--worktree` is a local
   checkout-positioning option that cannot be combined with `--remote`.
4. **Continue from durable state.** The command returns after dispatch. Use GitHub Actions and
   `perk workflow run list` to follow the run; coordination does not depend on keeping the launching
   terminal open.

## Expected result

GitHub Actions contains a run whose name identifies the stage, plan, and full perk run id. The local
dispatch record preserves the same run-to-plan linkage for later supervision.

## Related

- **Do:** [Set up the remote runner](./set-up-the-remote-runner.md) — provision and verify the
  prerequisite runner.
- **Do:** [Supervise dispatched runs](./supervise-dispatched-runs.md) — observe or control the run.
- **Understand:** [Headless and remote](../explanation/headless-and-remote.md) — why coordination uses
  durable state rather than a watched terminal.
