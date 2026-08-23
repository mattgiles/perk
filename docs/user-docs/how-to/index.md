---
title: "How-to guides"
description: "Goal-oriented recipes: the reliable step sequences for an operator who already knows what they want to do."
sidebar:
  order: 2000
---

# How-to guides

You know what you want to accomplish — each guide here is the reliable sequence of steps
for exactly one goal.

## Recommended starts

<div class="perk-recommended">

- **[How to drive a change through the full spine](./drive-the-full-spine.md)** — the
  connective map: walk one change plan → learn, staying in-session where possible.
- **[How to resume a plan at its current stage](./resume-a-plan.md)** — the recipe you will
  reach for most: re-enter an in-flight plan from a cold shell.
- **[How to recover a dirty worktree](./recover-a-dirty-worktree.md)** — the unblocker for
  the most common snag: uncommitted changes in the way.

</div>

## Core workflow

- [How to drive a change through the full spine](./drive-the-full-spine.md) — walk one change
  plan → learn, staying in-session where possible (the connective map to the recipes below).
- [How to resume a plan at its current stage](./resume-a-plan.md) — re-enter an in-flight plan
  from a cold shell with fresh context.
- [How to address review feedback on a PR](./address-review-feedback.md) — classify reviewer
  feedback, fix actionable items, resolve threads.
- [How to review a PR human-in-the-loop](./review-a-foreign-pr.md) — run an adversarial review
  of a PR (foreign or the active worktree's own) with `/pr-review-terminal` (hunk) or
  `/pr-review-browser` (plannotator), triage findings together, and post with your explicit
  approval.
- [How to review a stacked PR train](./review-a-stacked-train.md) — review each layer of a
  stacked pull-request train on its incremental diff, leave feedback on any layer safely, and
  never merge a layer individually.
- [How to review a PR stack in the browser](./review-a-stack-in-the-browser.md) — review a
  whole stack (a perk train or any base-ref chain) in one combined-diff plannotator session
  with `/stack-review-browser`, then post judgment-routed per-PR reviews.
- [How to replan an open plan](./replan-an-open-plan.md) — re-author a saved-but-not-landed plan
  against the current codebase.
- [How to adopt an existing issue as a plan](./adopt-an-existing-issue.md) — turn a pre-existing
  human-authored issue into a perk plan in place, without minting a second object.
- [How to capture a gist (a statement of intent)](./capture-a-gist.md) — record "something we
  would likely want to do" as a tracked, adoptable statement of intent, upstream of plans and
  objectives.
- [How to adopt an existing project as an objective](./adopt-an-existing-project.md) — turn a
  pre-existing Linear project (or GitHub issue) into a perk objective in place, mapping existing
  issues to roadmap nodes, without minting a second object.
- [How to target a non-default base branch](./target-a-non-default-base-branch.md) — point plans
  and objectives at a target branch other than the GitHub default.
- [How to run CI checks in a session](./run-ci-in-session.md) — run the project's configured
  `[[ci.checks]]` checks and read results in-session.
- [How to configure and verify CI checks](./configure-and-verify-ci-checks.md) — author the
  `[[ci.checks]]` rows, choose their trust posture, and prove pass, fail, and glob-skip states.
- [How to recover a dirty worktree](./recover-a-dirty-worktree.md) — get unblocked when
  uncommitted changes are in the way.
- [How to diagnose a perk repo](./diagnose-a-perk-repo.md) — read a failing `perk doctor` report,
  apply its bounded repair, and prove the repository healthy again.
- [How to run a worktree setup hook](./run-a-worktree-setup-hook.md) — declare `[worktree] setup`
  commands that prepare every fresh worktree before `pi` starts.
- [How to track implement progress](./track-implement-progress.md) — the plan's `## Steps` list
  seeds a live, model-owned todo checklist.
- [How to send feedback from a hunk watch](./send-feedback-from-hunk-watch.md) — save notes on
  the live `perk plan watch` diff and steer the implementing agent in place.

## Objectives & learnings

- [How to author an objective roadmap](./author-a-roadmap.md) — stand up a new objective + roadmap
  in a read-only authoring session.
- [How to replan an objective](./replan-an-objective.md) — re-author an objective as a superseding
  net-new objective that carries forward only the unfinished work and closes the old one.
- [How to advance or skip roadmap nodes manually](./advance-or-skip-nodes.md) — change a node's
  status by hand outside the auto-on-land path.
- [How to reconcile an objective manually](./reconcile-an-objective.md) — re-sync an objective's
  roadmap prose to what landed when the automatic reconcile didn't.
- [How to check an objective for drift](./check-an-objective-for-drift.md) — detect and repair
  divergence between a Linear objective's manifest and its live state — plus the delivery-train
  diagnosis on every backend — with `perk objective doctor`.
- [How to recover a stacked delivery train](./recover-a-stacked-train.md) — diagnose an
  interrupted or drifted stacked-train operation from its symptom and conclude it with the
  right sync or recover move.
- [How to run the learn-docs factory](./run-the-learn-docs-factory.md) — consolidate accumulated
  doc-destined `perk:learn` issues into committed `docs/learned/` knowledge.
- [How to run the learn-code factory](./run-the-learn-code-factory.md) — route pre-stamped
  `SHOULD_BE_CODE` `perk:learn` issues into their real code homes.
- [How to run the learn-harvest factory](./run-the-learn-harvest-factory.md) — mine `docs/learned/`
  as lenses into the code and curate ONE bounded improvement objective.
- [How to run the learn-dream factory](./run-the-learn-dream-factory.md) — audit the whole learned
  corpus at one stamped commit and curate ONE bounded curation objective plus the durable dream
  report.

## Headless & remote

- [How to set up and verify the remote runner](./set-up-the-remote-runner.md) — install the managed
  workflow and action, then prove them with a waited smoke.
- [How to dispatch a stage to a remote runner](./dispatch-a-stage-to-ci.md) — send a saved plan's
  unattended `implement` or `address` stage to CI.
- [How to observe and control dispatched runs](./supervise-dispatched-runs.md) — identify, cancel,
  or retry a remote Actions run from any clone.
- [How to advance an objective with the run supervisor](./advance-an-objective-headlessly.md) — let
  the deterministic supervisor make one safe objective decision.

## Customization

- [How to attach your own skill to a stage or command](./attach-a-skill-to-a-stage.md) — add one
  `[[bindings]]` row and verify that the skill reaches its trigger.
- [How to author a repo-specific skill](./author-a-repo-skill.md) — create, publish, synchronize,
  refine, or remove a skill under `.perk/skills/<name>/`.
- [How to write a custom subagent](./write-a-custom-subagent.md) — add a project agent under
  `.pi/agents/`, list it, and run it through `workflowScript`.
- [How to scope Pi resources per project](./scope-pi-resources-per-project.md) — filter one
  package's extensions, skills, prompts, or themes with `pi config -l`.
- [How to enable shell completion](./enable-shell-completion.md) — activate TAB completion so
  plan and objective ids complete from the live issue backend, with title previews.

## Providers & backends

- [How to select a provider](./select-a-provider.md) — switch `pi-status-footer` to `pi-default` and
  prove that only the selected package changes.
- [How to switch the issue backend to Linear](./switch-to-linear.md) — configure Linear, verify its
  readiness, and confirm one issue create/read round trip.
