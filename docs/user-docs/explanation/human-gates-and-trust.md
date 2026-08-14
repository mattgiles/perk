---
title: "Human gates and trust"
description: "How perk keeps judgment with a person, and why workflow gates are a separate axis from execution trust and sandboxing."
sidebar:
  order: 4030
---

# Human gates and trust

Two different questions hide behind the word "trust," and perk answers them with two different
mechanisms. The first is a **workflow** question: where does human judgment enter, and what
stops an agent from steaming past it? The second is an **execution** question: what code and
commands is your machine actually willing to run, and with what permissions? This page explains
each axis, why perk keeps them separate, and — just as important — what neither axis gives you.

## Human gates preserve judgment

A **human gate** is a point in the workflow where a decision belongs to a person, and the
machine stops until that person makes it. perk has a small number of them, and each one guards
a genuinely irreversible or judgment-laden act:

- **Plan approval.** Exploration and plan authoring happen in a read-only mode; the plan is
  reviewed and saved by explicit human approval before any implementation session can edit
  files. The gate separates *thinking* from *doing* — an agent cannot promote its own draft
  into a commitment.
- **Review and landing.** A submitted pull request waits for a person: marking it ready,
  accepting the review, and merging are human acts. The agent can produce and revise the
  change, but acceptance judgment never moves to the machine.
- **Supervisor pauses.** The objective run supervisor is deterministic — it does no agentic
  reasoning. Each invocation advances the backlog by at most one autonomously safe step and
  then stops, and whenever the next step needs a person — a plan must be authored, a pull
  request is ready for review or waiting at review, a merge needs a decision — it reports that
  boundary instead of acting.

## Structural workflow gates are stronger than prompt reminders

What makes these gates trustworthy is that they are **structural**, not advisory. During plan
authoring, the session's tool surface is itself read-only: the tools that could mutate the
repository are withheld or intercepted, so read-only posture is a property of the machine
rather than a promise in a prompt. An instruction can be argued with or forgotten; a tool that
is not there cannot be misused. On the other side of each gate, the decision surfaces —
plan review and save, marking ready, landing — make the human act explicit and visible, so
approval is a recorded gesture rather than an inferred one. The exact tool inventory and its
per-stage availability is reference material, linked below; the guarantee to remember is that
the boundary is enforced by what the session *can do*, not by what it is told.

## Remote work stops at the same judgment boundary

Running a stage on a remote CI runner does not relax any of this. Only the bounded, agentic
stages — implement and address, where the goal is already pinned by a saved plan or by concrete
reviewer feedback — are ever dispatched remotely. A remote session may create or update its
pull request, because it drives the same shared submit implementation a local session uses; what
it never does is judge that work. No remote path marks a pull request ready, approves a review,
or lands a merge — those remain the human gates above, wherever the implementation happened to
run. There is no standalone remote door for the judgment stages; the remote surface exists
precisely so that the *bounded* work can run unattended while the decisions stay with you.

## Execution trust is a separate axis

Human gates govern *judgment*. A different set of switches governs *execution* — what project
code your tools will load and run:

- **Pi project trust** controls whether a repository's local packages, settings, and extensions
  load into a session at all. An untrusted repository's project resources are ignored; trusting
  it is an explicit, per-project act.
- **perk worktree setup hooks** execute repository-configured commands when a worktree is
  prepared — dependency installs, environment preparation — as your user, with your
  permissions.
- **The remote runner** executes checkout-controlled setup and stage work on CI infrastructure,
  with whatever credentials and permissions that environment grants it.

Approving any of these means *"load and run this project's resources."* It does not mean the
resources are inspected, constrained, or contained. Trust here is an on/off admission decision,
not a safety analysis — which is why it deserves its own axis, separate from the workflow
gates.

## Know the isolation boundary

Neither axis is a sandbox. perk's workflow gates bound *which stage acts when*; they do not
turn Pi, shell tools, setup hooks, or model-generated commands into an isolated environment.
Everything a session runs executes with the process's and user's real permissions, and a
repository you have trusted can run real code on your machine through the surfaces above. When
you need strong isolation — untrusted repositories, unmonitored autonomous work, code you would
not run by hand — that isolation belongs to the operating system: a container, a VM, or a
policy sandbox, provisioned with the minimum files and credentials the work needs.

The useful contrast inside perk itself is foreign-PR review: reviewing a pull request perk did
not author uses a detached, read-only checkout, and nothing from the foreign branch is ever
executed. That is the safe posture for untrusted code — reading without running — and it is the
exception that proves the rule: everywhere else, admitting a project's resources means running
them.

## Related

- **Do:** [Review a PR human-in-the-loop](../how-to/review-a-foreign-pr.md) — the adversarial
  review flow where nothing reaches GitHub without your approval.
- **Look up:** [Review and authoring](../reference/in-session/review-and-authoring.md) — the
  exact review, approval, and save surfaces.
- **Look up:** [Model-facing tools](../reference/in-session/model-tools.md) — the per-stage
  tool availability behind the read-only gate.
