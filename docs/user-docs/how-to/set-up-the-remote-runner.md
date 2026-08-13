---
title: "How to set up and verify the remote runner"
description: "Get a repo ready to dispatch perk stages to a remote CI runner, and prove the wiring is live before you depend on it."
sidebar:
  order: 2220
sidebarGroup: "Headless & remote"
---

# How to set up and verify the remote runner

Install the managed GitHub Actions runner and prove that it can start with the credentials a remote
perk stage needs.

## Steps

1. **Converge the runner files.** Run [`perk init`](../reference/cli.md#perk-init). Review both
   `.github/workflows/perk-run.yml` and `.github/actions/perk-remote-setup/action.yml`, then commit
   and push them to the repository's default branch. A workflow that exists only in a local branch
   cannot receive a dispatch.
2. **Set the required repository secrets.** Add `PERK_GH_PAT` and one model-provider secret:
   `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. The PAT is used for checkout, reporting, pushes, and
   any private skill-source clones. Do not set `PERK_ENABLED` just to turn the runner on: the gate
   is opt-out, so an absent value means enabled and `false` disables the runner.
3. **Run the static check.** Run
   [`perk doctor workflow check`](../reference/cli.md#perk-doctor-workflow-check). Fix every failure
   before dispatching. Add `--verbose` for all individual checks or `--json` for structured output.
4. **Run the waited smoke.** Run
   [`perk doctor workflow smoke-test --wait`](../reference/cli.md#perk-doctor-workflow-smoke-test).
   This directly dispatches the managed workflow's bounded smoke short-circuit: it validates the
   secrets, starts the Actions job, prints the smoke confirmation, and exits without checking out a
   plan or invoking a model. Waiting is capped at ten minutes; on timeout, perk reports the result as
   inconclusive and makes a best-effort cancellation.

## Expected result

The static report is healthy and the waited smoke concludes successfully. The smoke creates only its
GitHub Actions run: it writes no perk dispatch record or workflow artifact, and creates no branch,
pull request, or issue. It therefore does not appear in `perk workflow run list`. A successful smoke
proves the runner wiring and secret readability, not a full model-driven stage.

## Related

- **Do:** [Dispatch a stage to CI](./dispatch-a-stage-to-ci.md) — hand off an unattended stage after
  the smoke passes.
- **Look up:** [`perk doctor workflow check`](../reference/cli.md#perk-doctor-workflow-check) and
  [`perk doctor workflow smoke-test`](../reference/cli.md#perk-doctor-workflow-smoke-test) — exact
  check and smoke command surfaces.
- **Understand:** [Headless and remote](../explanation/headless-and-remote.md) — what smoke proves
  versus a full model-driven run.
