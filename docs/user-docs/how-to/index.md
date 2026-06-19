# How-to guides

**Purpose:** goal-oriented recipes. A how-to guide serves a competent user who already knows
what they want to do and needs the reliable sequence of steps that does it.

## Authoring rules

- Every guide is titled "How to …" and scoped to exactly one goal.
- Assume basic familiarity with perk — [tutorials/](../tutorials/index.md) teach the basics;
  guides never re-teach them.
- A sequence of steps toward the goal: no teaching, no conceptual discussion — link to
  [explanation/](../explanation/index.md) or [reference/](../reference/index.md) instead.

See the [user-docs router](../index.md) for how this quadrant fits the overall system.

## Guides

### Core workflow

- [How to drive a change through the full spine](./drive-the-full-spine.md) — walk one change
  plan → learn, staying in-session where possible (the connective map to the recipes below).
- [How to resume a plan at its current stage](./resume-a-plan.md) — re-enter an in-flight plan
  from a cold shell with fresh context.
- [How to address review feedback on a PR](./address-review-feedback.md) — classify reviewer
  feedback, fix actionable items, resolve threads.
- [How to replan an open plan](./replan-an-open-plan.md) — re-author a saved-but-not-landed plan
  against the current codebase.
- [How to adopt an existing issue as a plan](./adopt-an-existing-issue.md) — turn a pre-existing
  human-authored issue into a perk plan in place, without minting a second object.
- [How to adopt an existing project as an objective](./adopt-an-existing-project.md) — turn a
  pre-existing Linear project (or GitHub issue) into a perk objective in place, mapping existing
  issues to roadmap nodes, without minting a second object.
- [How to target a non-default base branch](./target-a-non-default-base-branch.md) — point plans
  and objectives at a target branch other than the GitHub default.
- [How to run CI checks in a session](./run-ci-in-session.md) — run the project's configured
  `[[ci]]` checks and read results in-session.
- [How to recover a dirty worktree](./recover-a-dirty-worktree.md) — get unblocked when
  uncommitted changes are in the way.
- [How to run a worktree setup hook](./run-a-worktree-setup-hook.md) — declare `[worktree] setup`
  commands that prepare every fresh worktree before `pi` starts.
- [How to work with implementation checkpoints](./work-with-checkpoints.md) — track step-by-step
  implement progress with `## Steps` + `[WIP:n]`/`[DONE:n]`.

### Objectives & learnings

- [How to author an objective roadmap](./author-a-roadmap.md) — stand up a new objective + roadmap
  in a read-only authoring session.
- [How to advance or skip roadmap nodes manually](./advance-or-skip-nodes.md) — change a node's
  status by hand outside the auto-on-land path.
- [How to reconcile an objective manually](./reconcile-an-objective.md) — re-sync an objective's
  roadmap prose to what landed when the automatic reconcile didn't.
- [How to check an objective for drift](./check-an-objective-for-drift.md) — detect and repair
  divergence between a Linear objective's manifest and its live state with `perk objective doctor`.
- [How to run the learn-docs factory](./run-the-learn-docs-factory.md) — consolidate accumulated
  `perk:learn` issues into committed `docs/learned/` knowledge.

### Headless & remote

- [How to set up and verify the remote runner](./set-up-the-remote-runner.md) — converge the
  managed runner and prove the wiring with `doctor workflow smoke-test`.
- [How to dispatch a stage to a remote runner](./dispatch-a-stage-to-ci.md) — hand an unattended
  stage off to CI with `--remote`.
- [How to observe and control dispatched runs](./supervise-dispatched-runs.md) — list, cancel,
  and retry remote runs from a cold shell.
- [How to advance an objective with the run supervisor](./advance-an-objective-headlessly.md) —
  push an objective forward one safe step with `perk objective run`.

### Customization

- [How to attach your own skill to a stage or command](./attach-a-skill-to-a-stage.md) — bind an
  installed skill to a stage or command via `[[bindings]]`, as a new trigger or an override (also
  notes the auto-discovered `perk-expert` skill perk delivers for configuration/customization help).
- [How to write a custom subagent](./write-a-custom-subagent.md) — author your own
  `.pi/agents/<name>.md` agent def and invoke it via pi's native `subagent` tool.

### Providers & backends

- [How to select a plan or todo provider](./select-a-provider.md) — point the `[providers]` table
  at a supported plan-authoring or todo provider, then converge and validate.
- [How to switch the issue backend to Linear](./switch-to-linear.md) — move the canonical issue
  store from GitHub to Linear (auth, labels, what changes).
