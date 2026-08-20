---
title: "Operator glossary"
description: "The stable terms used across perk's operator workflow and reference pages."
sidebar:
  order: 3070
---

# Operator glossary

Use these terms when reading perk's messages, documentation, and configuration. Definitions stay
operator-facing; each entry links to the page that owns the detail.

- **Binding.** A configuration row that attaches one skill to a stage or command and delivers it
  by nudge or transclusion. See [Skills and bindings](./configuration/skills-and-bindings.md#bindings).
- **Canonical state.** The durable issue-tier record that wins when it disagrees with local cache
  or session state; pushed branches supply the corresponding durable code state. See
  [Where the truth lives](../explanation/how-perk-thinks.md#where-the-truth-lives-the-state-tiers).
- **Delivery train.** The ordered set of layers in one stacked-delivery lineage, including across
  a replan. See [Objectives — Delivery](./objectives.md#delivery).
- **Door.** A supported way to enter or drive a stage: a **warm door** stays in the current
  session, a **cold-local door** launches a fresh local session, and a **cold-remote door** runs an
  eligible bounded stage on the remote runner. See [Stages and doors](./in-session/stages-and-doors.mdx).
- **Dream.** The whole-corpus curation factory (`perk learn dream`): an inward audit of the
  learned corpus at one stamped commit that curates one bounded curation objective. Contrast a
  **harvest**, the bounded outward mine that reads docs as lenses into the code. See
  [Run the learn-dream factory](../how-to/run-the-learn-dream-factory.md).
- **Dream report.** The reviewed, durable companion record of a dream — one disposition row per
  doc, plus selections, overflow, and follow-ups — persisted as immutable comments on the
  objective's report carrier. See
  [The dream-report companion](./providers-and-backends/issue-backends.md#the-dream-report-companion).
- **Gist.** A rough, problem-space statement of intent upstream of both plans and objectives,
  without implementation detail. See
  [Gists, plans, and objectives](../explanation/gists-plans-and-objectives.md).
- **Human gate.** A workflow boundary that keeps judgment with a person rather than a machine:
  plan approval, marking a pull request ready, review, and landing. No standalone remote door
  exists for the judgment stages, though a remote `implement` run drives the same shared submit
  side effects. See [Human gates and trust](../explanation/human-gates-and-trust.md).
- **Incremental delivery.** The default objective policy in which each node plan integrates
  independently when it is ready. Contrast **stacked delivery**. See
  [Objectives — Delivery](./objectives.md#delivery).
- **Issue backend.** The selected tracker integration behind plan, learning, and objective storage;
  GitHub and Linear are the supported choices. See
  [Issue backends](./providers-and-backends/issue-backends.md).
- **JSON Schema snapshot.** A committed golden schema for a Pydantic machine boundary, used to
  make input, output, or shared-contract drift reviewable. See
  [JSON Schema snapshots](./json-schemas.md).
- **Layer.** One non-skipped roadmap node together with its plan, forming a delivery unit in a
  stacked train. See [Objectives — Delivery](./objectives.md#delivery).
- **Objective.** A multi-plan goal whose roadmap emits one bounded plan per node as it advances.
  See [Gists, plans, and objectives](../explanation/gists-plans-and-objectives.md).
- **Plan.** A written, reviewed, durable description of one bounded change, authored before code
  is edited. See [Gists, plans, and objectives](../explanation/gists-plans-and-objectives.md).
- **Provider.** A named selectable implementation from one seam's **supported set**;
  **selection** is a provider id in `[providers].<seam>`, and the catalog **default** is used when
  that key is omitted. See
  [Providers — Postures](./providers-and-backends/providers.md#postures).
- **Provider seam.** The shared catalog and resolution boundary that keeps the exterior and
  interior on the same provider name, package, tools, and fallback posture. It is the mechanism;
  a **provider** is one selectable catalog entry. See
  [Provider seam — the supported set](./providers-and-backends.md#provider-seam-the-supported-set).
- **Roadmap node.** One bounded unit of objective work, with status, dependencies, and an optional
  plan/PR backlink. See [The roadmap node schema](./objectives.md#the-roadmap-node-schema).
- **Run.** One identified workflow execution attempt, minted by a cold launch and used to correlate
  stage progress and remote reporting. A **session** is the live context that may carry the run.
  See [Stages and doors](./in-session/stages-and-doors.mdx).
- **Session.** One running Pi process and its conversational context. It is transient; durable
  plans and pushed work survive it. Contrast a **run**, the execution identity. See
  [Two planes](../explanation/how-perk-thinks.md#two-planes-the-exterior-and-the-interior).
- **Session exterior.** The Python `perk` CLI plane outside a session: it scaffolds, positions
  worktrees, mints run ids, and launches primed sessions. See
  [Two planes](../explanation/how-perk-thinks.md#two-planes-the-exterior-and-the-interior).
- **Session interior.** The TypeScript Pi-extension plane inside a session: it governs stage
  transitions, tools, context, and in-session workflow mutations. See
  [Two planes](../explanation/how-perk-thinks.md#two-planes-the-exterior-and-the-interior).
- **Skill.** Named guidance that Pi can expose or a binding can deliver. A **repo-authored skill**
  is committed under `.perk/skills/<name>/SKILL.md` and synchronized for discovery. See
  [Skills and bindings](./configuration/skills-and-bindings.md).
- **Spine.** The plan lifecycle `explore → plan → save → implement → submit → (address) → land →
  learn`. See [How perk thinks — plan-oriented](../explanation/how-perk-thinks.md#perk-is-plan-oriented).
- **Stacked delivery.** An objective policy in which plans remain separate review units but all
  non-skipped layers integrate together as one atomic delivery train. Contrast **incremental
  delivery**. See [Objectives — Delivery](./objectives.md#delivery).
- **Stage.** A named, resumable workflow unit with one posture, mode, input/output contract, and
  implementation. Doors are ways to enter it, not alternate implementations. See
  [Stages and doors](./in-session/stages-and-doors.mdx).
- **State tiers.** perk's authority ladder: the selected issue backend is **canonical**,
  `.perk/workflow/` is a reconstructable local **cache**, and in-session entries are
  **transient**. See
  [Where the truth lives](../explanation/how-perk-thinks.md#where-the-truth-lives-the-state-tiers).
- **Worktree.** An isolated Git checkout in which one plan's implementation and local edits live;
  uncommitted or unpushed work remains machine-local. See
  [Repository layout](./configuration/repository-layout.md).
