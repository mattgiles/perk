# The Road to Using Linear Projects as perk Objectives

This memo thinks through what it would mean for perk to use Linear Projects as
the representation of objectives. It is deliberately narrower than
`docs/planning/linear-masterplan.md`: that memo covers Linear as an issue backend in
general; this one focuses on the specific question of whether a perk objective
should eventually become a Linear Project.

The short answer: Linear Projects are a strong conceptual fit for the human
side of objectives, but they are not a drop-in replacement for perk's current
objective storage model. The gap is not a fundamental mismatch between perk and
Linear. The gap is between a Linear Project as a collaboration container and a
perk objective as a machine-readable state document with strict mutation rules.

The right path is probably staged:

1. Keep objective issues canonical while adding optional Linear Project mirrors.
2. Attach perk plan issues to the mirrored Project.
3. Use Linear Project affordances for visibility, grouping, updates, and human
   navigation.
4. Learn from live usage before deciding whether Linear Projects should become
   canonical objective storage.
5. If they should, introduce an explicit objective storage abstraction instead
   of stretching the issue backend abstraction past its natural limits.

## Current Objective Shape

perk's current objective model is issue-shaped.

At the storage contract level, objectives are methods on the issue backend:

- `find_objective_issue`
- `create_objective_issue`
- `get_objective`
- `update_objective_header`
- `update_objective_node`
- `update_objective_body`

That matters. The current abstraction does not say "create a strategic work
container." It says "create and mutate an issue that stores objective state."

The objective state itself is more than prose. An objective contains a roadmap
made of explicit nodes. Each node has stable structured fields:

- `id`
- `description`
- `status`
- `depends_on`
- `pr`
- `slug`
- `comment`

The status vocabulary is also perk-specific:

- `pending`
- `planning`
- `in_progress`
- `done`
- `blocked`
- `skipped`

This is not simply a display model. perk uses those fields to decide what can
happen next. The dependency graph chooses plannable nodes. Objective planning
marks a node as `planning` before launching a read-only planning session. Land
reconciliation finds the node linked to the landed plan or PR and marks it
`done`. When the objective's terminal conditions are met, perk closes the
objective.

The current Linear backend preserves this shape by treating a Linear issue like
a GitHub issue. It stores objective metadata in the Linear issue description and
stores the rendered objective body in a comment. That is intentionally
conservative: Linear becomes another implementation of the issue-shaped
contract.

## What Linear Projects Naturally Provide

Linear Projects are attractive because they represent a real body of work
better than a single issue does.

A Linear Project naturally provides:

- A first-class named work container.
- Project status and health.
- A lead and team associations.
- Target dates and timeframes.
- A place to attach many issues.
- Initiative linkage for larger company goals.
- Project documents for specs, notes, and working context.
- Project updates for periodic human-readable status reports.
- Milestones for phases of work.
- Timeline and progress views.
- Native Linear navigation, filtering, and reporting.

Those are valuable for perk objectives. A perk objective is usually not just one
task. It is a bounded campaign of planning, implementation, review,
reconciliation, and learning. Humans should be able to see it as a coherent
thing.

GitHub Issues can hold structured text, but they do not naturally provide that
operating surface. Linear Projects do.

## The Key Distinction

The central distinction is:

- A Linear Project is a collaboration and planning container.
- A perk objective is currently a canonical state machine artifact.

Those are compatible roles, but they are not the same role.

Linear Projects are excellent at answering human questions:

- What is this body of work?
- Who owns it?
- What team is it for?
- What issues belong to it?
- What is its health?
- What has changed recently?
- How does it fit into a larger initiative?
- What phase is it in?

perk objectives must also answer machine questions:

- What roadmap nodes exist?
- Which node is the next plannable node?
- Which nodes are blocked by dependencies?
- Has a node already been claimed for planning?
- Which plan issue belongs to which node?
- Which landed PR completed which node?
- Which objective prose region is safe to reconcile?
- Can a failed or interrupted session resume deterministically?
- What exact state transition should happen after land?

Linear can support many of those machine questions, but not through Projects
alone without additional conventions.

## Why Full "Project Is the Objective" Is a Wider Redesign

"Project is the objective" can mean several different things. The design cost
depends on which meaning we choose.

### 1. Project as a Mirror

The objective remains an issue. A Linear Project is created alongside it. Plan
issues are attached to the Project. The Project links back to the objective
issue, and the objective issue links to the Project.

This is the smallest change.

Benefits:

- Humans get a better Linear surface.
- Plans can be grouped under the Project.
- Project updates can summarize progress.
- Initiatives can group objective Projects.
- GitHub support remains unchanged.
- perk's strict objective state remains where it already lives.

Costs:

- There are two visible objects.
- The Project is not the canonical state source.
- Some duplication is inevitable.

This is probably the best first step.

### 2. Project as the Primary Human Object

The Linear Project becomes the object users think of as the objective. The
objective issue still exists, but it is more internal: a canonical state record
that backs the Project.

This is a medium-sized change.

Benefits:

- The human model becomes cleaner: "open the objective Project."
- perk does not need to make Project storage carry every machine invariant.
- The Project can become the default URL shown in prompts and status output.
- The issue can remain a strict metadata anchor.

Costs:

- perk must maintain a bidirectional relationship between Project and objective
  issue.
- Commands need to accept or resolve both ids.
- The UI must avoid confusing users about which object is authoritative.
- Linear-only affordances start to appear in objective behavior.

This may be the best long-term product experience if we want Linear to feel
native without sacrificing the existing storage model.

### 3. Project as Canonical Storage

The Linear Project itself becomes the source of truth. There may be no objective
issue. Objective prose, roadmap nodes, node state, plan links, and reconciliation
state must all live somewhere under the Project.

This is the "wide storage redesign."

Benefits:

- The model is conceptually pure in Linear: objective equals Project.
- Humans see one first-class object.
- Project issues, milestones, docs, updates, and initiatives can all be used
  directly.
- Linear could become much more powerful than GitHub Issues for objectives.

Costs:

- The current `IssueBackend` abstraction is no longer the right abstraction for
  objectives.
- GitHub needs a different implementation path that still remains first-class.
- perk must define where every piece of objective state lives.
- Objective ids are no longer simply issue ids.
- Plan save, objective plan, reconcile, and land flows all need to route through
  a new objective store.
- Tests and contracts need to cover issue-backed and project-backed objectives.
- Migration and recovery behavior become more complex.

This is not impossible. It is just meaningfully larger than switching a storage
object from issue to project.

## The Hard Part: What Is a Roadmap Node?

The hardest design question is not "can Linear Projects represent objectives?"
They can.

The hardest question is: what is a perk roadmap node in Linear?

There are several plausible answers, and each one has tradeoffs.

### Node as Structured Metadata

The roadmap remains encoded as structured metadata in the Project description or
a Project document.

This is closest to the current implementation.

Benefits:

- Preserves perk's exact node state machine.
- Supports pending nodes that do not yet have plan issues.
- Keeps dependency graph behavior straightforward.
- Works similarly across GitHub and Linear.

Costs:

- It does not fully use Linear's native model.
- Humans may not see roadmap nodes as first-class Linear objects.
- Project docs/descriptions become machine-edited storage surfaces.

This is the least risky canonical Project implementation, but also the least
Linear-native.

### Node as Linear Issue

Each roadmap node becomes a Linear issue inside the Project.

Benefits:

- Nodes become visible and assignable.
- Linear progress becomes more meaningful.
- Dependencies and relations can potentially use Linear issue relations.
- Humans can discuss and track each node naturally.

Costs:

- Pending nodes become placeholder issues before perk has written a plan.
- Plan issues and node issues may duplicate each other unless they are merged
  into one concept.
- Node status and Linear workflow status must be reconciled.
- A node can only belong to one Project if represented as a Project issue.
- The objective roadmap may become noisy in the issue tracker.

This is attractive if we want Linear to own the visible execution graph, but it
changes what a perk plan issue is.

### Node as Project Milestone

Each roadmap node, or group of nodes, becomes a Project milestone.

Benefits:

- Milestones are native to Projects.
- They give good phase-level visualization.
- They appear in project planning views.

Costs:

- Milestones are too coarse for many roadmap nodes.
- They do not naturally represent a plan issue or PR backlink.
- They do not provide perk's `planning` lease semantics.
- They are better at grouping work than representing individual units of agent
  progress.

Milestones are probably useful for phases, not as the canonical node model.

### Node as Plan Issue

A roadmap node becomes real only when a plan issue is created.

Benefits:

- Simple after planning.
- Avoids placeholder issues.
- Keeps Linear issues focused on actionable work.

Costs:

- perk objectives need unplanned future nodes.
- Dependency planning needs to inspect nodes before plans exist.
- The objective roadmap loses its durable pre-plan structure.

This conflicts with the current objective model.

### Hybrid

Use structured metadata for pending nodes, Linear issues for planned/in-progress
nodes, and milestones for phase grouping.

Benefits:

- Captures the best parts of each Linear primitive.
- Avoids creating placeholder issues for every future node.
- Lets planned work become native Linear work.

Costs:

- More moving parts.
- More synchronization logic.
- Harder recovery after partial failures.
- More backend-specific behavior.

This may be the eventual destination, but it should not be the first step.

## Where Linear Projects Are Strictly Better

Even if Projects do not become canonical immediately, they offer meaningful free
benefits as an objective envelope.

### Better Human Navigation

A Linear Project can be the landing page for an objective. Humans can see all
related plans, status, docs, and updates in one place. This is stronger than a
single objective issue with a large body and comments.

### Better Grouping

Plans created under an objective can all be attached to the Project. That gives
perk an immediate grouping primitive without inventing new metadata views.

### Better Reporting

Linear already knows how to show project progress, issue lists, project health,
and timelines. perk can benefit from that instead of rebuilding it.

### Better Management Layer

Initiatives can group objective Projects. That gives organizations a natural
way to connect perk-driven technical objectives to company-level goals.

### Better Status Communication

Project updates can become the human-readable summary channel for objective
progress. perk can eventually post structured updates after major transitions:
plan saved, implementation submitted, PR landed, objective reconciled.

### Better Context Surfaces

Project documents can hold PRDs, design notes, decisions, investigation
summaries, and reconciliation context. This is more natural than stuffing every
long-lived piece of context into issue bodies.

### Better Agent Visibility

Linear's agent primitives, especially AgentSession, can make perk runs visible
as first-class activity. This should remain additive and fail-open, but it is a
major advantage over GitHub Issues as the only external surface.

## Where Projects Should Not Become Authority Too Quickly

Some Linear features are useful but should not become authoritative too early.

### Project Status

Project status should not initially decide whether a perk objective is complete.
perk completion should remain derived from explicit roadmap node state.

Linear project status is useful for human visibility. It is not the same thing
as perk's objective state machine.

### Issue Completion Progress

Linear can show progress based on completed issues, but perk should not assume
that issue completion equals objective completion unless the relationship is
carefully defined.

For example, if a human adds a non-perk issue to the Project, should that affect
objective progress? Probably yes for Linear's human progress bar, but no for
perk's machine completion check.

### Milestones

Milestones are valuable as planning affordances. They should not initially
replace roadmap node metadata.

### Project Documents

Project documents are attractive places for prose, but machine-editing
collaborative documents creates risks: formatting drift, user edits inside
machine blocks, permissions, and API representation complexity.

They may be excellent for objective body prose, but they should be introduced
carefully.

## Recommended Implementation Path

### Phase 1: Project Mirror

Add optional Linear Project creation for objectives while keeping objective
issues canonical.

The objective issue would gain metadata such as:

- `linear_project_id`
- `linear_project_url`
- maybe `linear_project_slug`

The Linear Project would link back to the objective issue.

When perk creates a plan from an objective node, the resulting Linear plan issue
would be attached to the Project. If the issue backend is GitHub, this feature
is unavailable unless there is an explicit Linear integration configured.

This phase should avoid changing objective correctness. If Project creation or
attachment fails, the objective should still work.

### Phase 2: Project-Aware Objective UX

Make the Project more visible in user-facing output.

Examples:

- `perk objective create` can print both the canonical objective issue and the
  Linear Project URL.
- Objective prompts can include the Project URL.
- Plan prompts can say which Project the plan belongs to.
- `perk doctor` can validate that the objective issue and Project still point
  to each other.
- `perk objective status` could eventually summarize the Project's attached
  plan issues.

At this stage, the Project is still not canonical, but it is becoming the main
human navigation surface.

### Phase 3: Project Updates and Documents

Use Project updates and documents for human-readable context.

Possible behavior:

- Post a Project update when an objective is created.
- Post a Project update when a plan is saved.
- Post a Project update when a PR lands.
- Post a Project update when objective reconciliation changes the roadmap.
- Create or update a Project document with the objective body.

This phase should keep strict machine state in the objective issue. Project
updates and docs are a visibility layer.

### Phase 4: ObjectiveStore Abstraction

If Project mirrors prove valuable enough, introduce a real objective storage
abstraction.

Today the issue backend owns both plan/learn issues and objectives. That is
fine while objectives are issue-shaped. It becomes awkward once Linear Projects
are allowed to be canonical objectives.

A future abstraction might look like:

```python
class ObjectiveStore(Protocol):
    def find_objective(self, run_id: str) -> ObjectiveRef | None: ...
    def create_objective(...) -> ObjectiveCreateResult: ...
    def get_objective(self, objective_id: str) -> ObjectiveRecord: ...
    def update_header(...) -> None: ...
    def update_node(...) -> ObjectiveNode: ...
    def update_body(...) -> None: ...
    def link_plan(...) -> None: ...
    def complete_objective(...) -> None: ...
```

Then implementations can differ:

- GitHub: issue-backed objective store.
- Linear simple mode: issue-backed objective store.
- Linear project mode: project-backed objective store.

The important move is to stop pretending that all objectives are issues if we
decide they are not.

### Phase 5: Canonical Project-Backed Objectives

Only after the abstraction exists should perk consider a true Project-backed
objective mode.

That mode must decide:

- Where objective header metadata lives.
- Where roadmap node state lives.
- Where objective body prose lives.
- Whether pending nodes are Linear issues.
- Whether milestones represent phases or nodes.
- How plan issues attach to nodes.
- How objective completion is computed.
- How partial failures are recovered.
- How to migrate existing issue-backed objectives.

This should probably be an explicit config choice, not an automatic consequence
of selecting Linear as the issue backend.

For example:

```toml
[issues]
backend = "linear"
team = "SAV"

[objectives]
backend = "linear-project"
```

or:

```toml
[linear]
objective_mode = "project"
```

The exact config shape should come later. The principle is that issue backend
selection and objective storage strategy are related but not identical.

## Compatibility With GitHub

GitHub must remain first-class. That requirement argues strongly for a clean
abstraction.

If perk hard-codes Linear Project assumptions into objective logic, GitHub
becomes a compatibility burden. If perk introduces an `ObjectiveStore`, GitHub
can keep using issues without pretending to support Projects.

The shared conceptual model should be:

- perk objectives are backend-neutral records with roadmap state.
- GitHub stores them in issues.
- Linear may store them in issues or Projects.
- Backend-specific affordances can enrich the experience, but cannot redefine
  the core lifecycle without going through the objective contract.

This also protects Linear. It lets perk use Linear Projects seriously instead
of forcing them through an issue-shaped interface forever.

## Caveats

### Linear API Maturity Must Be Proven Live

The current Linear backend is still live-unproven in important ways. Before
building Project-backed objectives, perk should complete the Linear smoke gate
and record real API behavior.

Project APIs, project documents, milestones, updates, and issue attachment all
need live validation before they become part of a durable workflow contract.

### Human Edits Are A Feature And A Risk

Linear Projects invite human participation. That is good. It also means humans
may rename Projects, move issues, edit documents, change statuses, or add
non-perk work.

perk must decide which human edits are accepted, which are ignored, and which
are reported as drift.

### Project Membership Is Not Pure

A Linear Project may contain issues that are not perk plans. That is probably
desirable for real work, but it means perk cannot blindly treat all Project
issues as objective nodes.

### Project Completion Is Not Objective Completion

At least initially, Linear Project completion should not close a perk objective,
and perk objective completion should not necessarily complete the Linear Project
without a deliberate rule. These are related lifecycle events, not identical
ones.

### Backend-Neutral Prompts Need Care

Prompts should not teach agents that objectives are always Linear Projects. They
should describe the objective and include backend-specific links as context.

For GitHub, the link may be an issue. For Linear project mode, it may be a
Project. For hybrid mode, it may be both.

## Recommended Near-Term Position

The near-term position should be:

- Linear Projects are the preferred human envelope for Linear-backed
  objectives.
- The canonical objective state should remain issue-backed until the Project
  model is proven in live use.
- Plan issues should be attached to objective Projects as soon as practical.
- Milestones should be explored as phase/grouping affordances, not canonical
  node storage.
- Project updates should become a status communication layer.
- AgentSession should remain the run visibility layer.
- A true Project-backed objective mode should wait for an explicit
  `ObjectiveStore` abstraction.

This approach gets most of Linear's benefits early without weakening perk's
existing guarantees.

## Bottom Line

There is no fundamental impedance mismatch between perk and Linear.

There is, however, a real impedance mismatch between perk's current
issue-shaped objective storage contract and the idea that a Linear Project
should be the canonical objective object.

That mismatch is solvable. The solution is not to contort Projects into issues
or to make GitHub pretend it has Linear Projects. The solution is to introduce a
clear objective abstraction when the product need justifies it.

Until then, the strongest path is hybrid:

- issue as canonical objective state,
- Project as human-facing objective workspace,
- plan issues attached to the Project,
- Project updates/docs as visibility and context,
- GitHub preserved as a first-class issue-backed implementation.

That path lets perk learn from Linear's strengths without prematurely rewriting
the storage foundation that makes objectives reliable today.
