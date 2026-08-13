---
title: "How perk thinks"
description: "The mental model behind perk — the four ideas that make the commands stop feeling arbitrary."
sidebar:
  order: 4010
---

# How perk thinks

This page is the mental model behind perk. Read it once and the commands stop feeling
arbitrary — you stop memorizing gestures and start recognizing the shape they belong to. It
assumes you have done (or at least skimmed) the getting-started tutorial; where that lesson
showed you *what* to type, this page explains the *why* underneath it. There are no steps here
and nothing to run — just the four ideas that make perk make sense: that work is organized
around a plan, that the system is split into two planes, that state lives in tiers with one
authority, and that every unit of work has two doors you can walk through.

## perk is plan-oriented

perk's unit of work is a **plan**: a written, reviewed, durable description of a change,
authored *before* any code is written. A plan is not a scratch note you jot and discard — it is
a first-class artifact that outlives the session that wrote it. It lives in GitHub, where it can
be read, linked, and resumed long after the conversation that produced it has ended.

Why front-load a plan at all? Because it separates **thinking** from **doing**. Exploration and
design happen in a deliberately constrained, read-only mode where the agent literally cannot
edit files — it can read, search, and reason, but not change anything. Only once a human has
reviewed the plan and it has been saved does editing become possible. This is the antidote to
the failure mode every coding agent is prone to: starting to edit before it understands the
problem, then spending the rest of the session defending its first guess. By making the plan a
gate rather than a suggestion, perk forces understanding to come first.

The plan is also what makes the whole workflow **resumable and hand-off-able**. Because the plan
and its progress are durable and external — not trapped in one chat history on one laptop — a
different session can pick the work up where it was left. So can a different machine, or a
teammate. The mechanisms that make this work (where state lives, and how you re-enter a piece of
work) are the subjects of the later sections; for now the point is simply that durability is not
an accident, it is the design.

It helps to name the **spine** a plan travels: *explore → plan → save → implement → submit →
(address) → land → learn*. That is the lifecycle, start to finish — explore the problem, write
the plan, save it as the canonical record, implement it on a branch, submit the result for
review, *address* any feedback, land it, and capture what was learned. `address` is in
parentheses because it is conditional: you only enter it when a reviewer leaves feedback to
respond to. Section 4 explains how you actually move along this spine. Work can also be
*generated* rather than hand-authored: a longer-running **objective** — a roadmap that emits
bounded plans as it advances — can feed plans into this same spine, but that is its own topic
and the objectives material is where its depth lives.

## Two planes: the exterior and the interior

perk is split across **two planes**, and the split is worth understanding because it explains
why some things happen at your shell and others happen inside the agent.

The first plane is a Python **`perk` CLI** — the session *exterior*. It is everything that
happens *outside* a session: it scaffolds a repository, manages the git worktrees each plan
lives on, mints the identifiers that tie a run to its plan, and **launches** a primed `pi`
session ready to do a piece of work. The second plane is a TypeScript **Pi extension** — the
session *interior*. It is everything that happens *inside* a running session: it drives the
stage transitions, gates which tools the agent may use, injects the right context at the right
moment, and performs the workflow's GitHub mutations as the work proceeds.

The rule that decides what goes where is simple to state: **the boundary is the session, and
authority follows the actor.** If something happens *while the agent is reasoning or acting* — or
in reaction to it within a turn — that is the extension's job. If something *sets up, launches,
or coordinates* sessions from the outside, the kind of work a human at a shell or a supervising
process does, that is the CLI's job.

There is a corrective half to the rule that matters just as much: **the CLI may *start* a stage
but never *steers* a live turn.** The exterior positions the environment, launches `pi`, and
hands off — and from that moment, only the interior governs behavior. This is why you do not
babysit the agent from the shell mid-run, and why in-session behavior — plan mode, the read-only
gate, formatting on save — is enforced *structurally* by the extension rather than nagged at
through reminders injected from outside. The constraints are part of the machine, not
suggestions shouted at it.

Why split across two languages and two planes at all? Honestly, it has a cost: two codebases,
two toolchains, two things to keep in step. The planes share **no in-process code** — they
coordinate only through durable artifacts, a process launch, and a shared static description of
the workflow that both read independently. The payoff is that each concern lives where it can
actually be enforced. The interior behaviors an agent runtime makes customizable — gating
tools, shaping context, reacting to turns — belong *inside* the session, because that is the
only place they can be made structural. The host concerns a session genuinely cannot do for
itself — a process cannot launch itself, cannot `cd` your shell, cannot create a worktree it is
not yet running in — stay outside. The boundary is not arbitrary; it traces the line between
what a session can enforce about itself and what it cannot.

## Where the truth lives: the state tiers

perk keeps workflow state in **three tiers**, and the single most useful thing to understand is
which one is authoritative when they disagree.

- **GitHub — canonical.** This is the source of truth (under the default backend). Plans are GitHub
  issues; pull requests, review threads, objectives, and the learnings captured at the end of a plan
  all live there. (On a Linear backend the canonical issue tier moves to Linear and objectives live
  as **Linear Projects**, while pull requests, review threads, CI, and merge stay GitHub-universal.)
  If two tiers ever disagree, the canonical issue tier wins, full stop. This is *why* the work is resumable from
  anywhere and shareable with a team: the truth is not sitting on one laptop waiting to be lost.

- **`.perk/workflow/` — cache.** A local, per-repo mirror that lets a session work quickly without
  round-tripping to GitHub for every read — things like the materialized plan body and the
  pointer from the active plan to its branch. The important word is *cache*: it is derivable from
  and reconcilable against GitHub, safe to lose, and — being machine-local — git-ignored rather
  than committed. It is a convenience, not a record.

- **Session entries — transient.** In-session working state that exists only for the duration of
  a turn or session: which stage you are in, whether you are in read-only or read-write mode.
  When the session ends, it evaporates. Anything that must survive is promoted up into one of the
  durable tiers before then.

The one load-bearing rule for an operator: **durable truth is in GitHub; the local cache is
convenience; session state is throwaway.** The consequence is liberating — you can delete a
worktree, switch machines, or hand a plan to a colleague, and nothing *canonical* is lost, because
the canonical record was never local to begin with. The one thing that is machine-local is
uncommitted worktree edits — the durability boundary defined in the doors section below.

One honest caveat: a stale or missing cache is a *repairable* condition, not a crisis. Because
the cache is derived from GitHub, perk can reconstruct it — that is what the repair tooling is
for. A cache that has drifted is an inconvenience to fix, never a loss of truth.

## Stages and doors: how you move through the workflow

This is where the pieces come together. The workflow is a small set of named, resumable
**stages** — the spine from the first section: *plan, save, implement, submit, address, land,
learn*, plus the objective-planning stage that feeds plans into it. A stage is the **unit** of
the workflow: it has one job, one well-defined input and output, and exactly one
implementation. There is no second copy of "implement" hiding somewhere; there is one, and both
planes agree on what it is.

Each stage has **two doors** — two ways to enter the *same* stage:

- **Warm (in-session):** you invoke the stage from inside a running `pi` session and **keep your
  current context**. This is best for tight, iterative flow, when you want continuity and do not
  want to lose the thread you are on.
- **Cold (from a shell):** you run a `perk` command that **positions the environment** —
  resolving or creating the right worktree and materializing the state the stage needs — and
  then **launches a fresh `pi` session primed to run that stage**. This is best for resuming
  after a break, or for starting a stage with deliberately clean context.

The doors are the **same stage logic with different *session semantics***, and that difference
is the entire point. Warm means *don't lose your seat*; cold means *a fresh, clean context*. Why
does that symmetry matter to you? Because every stage is re-enterable from a cold shell, you are
never stuck inside one long-lived session. You can stop, come back tomorrow, and re-enter the
*stage* you were in — not because the session was kept alive, but because the state is canonical
in GitHub (the previous section) and the cold door can rebuild everything else around it.

Be precise about what "re-enter where you were" durably means, though. What carries across
machines and sessions is **stage-boundary + pushed-branch durability**: the saved plan and its
recorded progress (the canonical tier) plus any branch pushed to `origin`. **Uncommitted local
edits — and unpushed commits — in a worktree are explicitly outside the cross-machine contract**:
they live only on the machine that made them. Resume re-enters the stage, not the keystrokes.
Committing (and pushing or submitting) is what promotes local work into the durable tier. When
leftover local WIP is in the way of a stage, the recipe is
[Recover a dirty worktree](../how-to/recover-a-dirty-worktree.md).

This also explains **why some stages are cold-only** — why a door is not always offered. The
clearest example is **implement**: it is cold-only because it *must not* inherit the planning
conversation. Carrying all the exploration and design back-and-forth into the doing phase
pollutes it — the agent starts implementing against the noise of how the plan was argued into
existence rather than against the clean plan itself. So perk deliberately forces a fresh session
there. That is a feature, not a limitation: it is context hygiene, enforced by withholding the
warm door.

### Running a stage somewhere else: the headless door

So far "cold" has meant *a fresh session on your machine*. But the cold door is really
**parameterized by *where* the process runs.** A cold launch can target your **local machine** —
a fresh `pi` session right here — or a **remote CI runner**, where the same stage runs on GitHub
Actions instead. Same stage logic, same canonical state in GitHub; only the *location* of the
process differs.

Stated precisely, this is the whole headless story: **there is no separate headless workflow.**
Headless is simply the cold door pointed at a remote target. Once you see it that way, there is
nothing extra to learn — it is the model you already have, aimed somewhere else.

**Not every stage gets a remote door.** Conceptually, only the stages that can run *unattended*
are remotely runnable: **doing the work** (`implement`) and **responding to review feedback**
(`address`). The interactive, exploratory stages — planning above all — and the quick
deterministic ones stay local. The rationale is plain: a CI runner has no human sitting beside
it to make a design call, so only the stages that are *agentic but bounded* — where the goal is
already pinned down by a plan or by reviewer feedback — are safe to hand off to a machine with
nobody watching.

How does a remote run coordinate, with no terminal to watch? Through the tiers from the previous
section. When you dispatch a stage remotely, perk records the run-to-plan linkage in durable
state and triggers the runner. The runner then reports its progress and outcome **back through
GitHub** — as PR comments and checks — so the run is observable without anyone staring at a
console. The canonical tier is what makes a headless run legible.

To name the concrete pieces (illustratively, not as a catalog): `perk init` installs a managed
GitHub Actions workflow, `perk-run.yml`, that on dispatch checks out the repository and runs
`perk run-worker` — the runner-side entrypoint that positions the plan branch and the worktree
and drives the stage exactly as a local cold launch would. A supervisor — you, or an automated queue — observes and
controls those runs with `perk workflow run list` (and its `cancel` and `retry` companions). The
exact flags and outputs for these belong to the command reference, not to this page.

A word on maturity: the live end-to-end chain — real `implement` and `address` runs, dispatch
through reporting — is proven on **both** perk's own repo (2026-07-04) and a consumer repo through
the published distributions (2026-07-06). For the operational depth and the current
maturity story, see [Headless and remote: how it works, and how proven it is](./headless-and-remote.md);
this page just places the surface in the mental model.

## Why this shape

Pull the four ideas together and the payoff is a single coherent property.

Because a plan is durable and canonical in GitHub, and because every stage has a cold local
door, **every stage is locally resumable** — from any machine, by anyone, with nothing more than
the repo and the plan id. The **bounded agentic stages** — `implement` and `address`, where the
goal is already pinned by a plan or by reviewer feedback — are additionally **remotely
headless-able**: the same cold door pointed at a CI runner. And the **human gates stay local**:
`submit`, `land`, and `learn` are local-only by design — review, merge, and judgment capture are
deliberately kept where a human is. Resumability and the remote door are not two features but
one property at two scopes.

Because there is exactly one implementation per stage in the interior, launched by a thin
exterior, the two planes **cannot drift into two behaviors.** There is no second "implement" to
fall out of sync; the split is along a clean line, not a duplicated one.

And because thinking — read-only planning — is structurally separated from doing —
implement-on-a-branch — the agent is *constrained* to understand before it edits. The discipline
that is hardest to enforce by good intentions is instead enforced by the shape of the machine.

If you want the exact commands and tools, that is the **[reference](../reference/index.md)**
quadrant. For task-focused recipes — the concrete steps to get a specific thing done — see the
**[how-to](../how-to/index.md)** quadrant. To learn the basics hands-on, start in the
**[tutorials](../tutorials/index.md)** quadrant. And the **[user-docs router](../index.mdx)** ties
all four quadrants together.
