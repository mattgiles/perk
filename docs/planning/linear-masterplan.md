# Linear as a perk Issue Backend: Operating Principles and Masterplan

> **Historical — largely realized (Objective #548, 2026-06).** This memo's core recommendations
> shipped: Linear is the canonical **issue backend** for plan / learn / objective issues; PRs, CI,
> and merge stay **GitHub-universal**; workflow status is a **fail-open visibility mirror**. One
> honest **divergence**: the memo recommended that a perk objective *initially remain* a Linear
> issue (not a Project or Initiative). Reality went further — perk introduced an explicit
> `ObjectiveStore` split and made **Linear Projects canonical objectives** (overview = `objective-header`
> + Reconcilable prose; one node-issue per node; phases = milestones; explicit `depends_on` =
> blocking relations). See the current operator docs
> [`../user-docs/reference/providers-and-backends.md`](../user-docs/reference/providers-and-backends.md)
> and [`../user-docs/reference/objectives.md`](../user-docs/reference/objectives.md), the cross-plane
> contract `shared/contracts.md` §8.21 / §8.24, and the live-validation runbook
> [`./linear-smoke-gate.md`](./linear-smoke-gate.md).

This memo lays out an opinionated model for using Linear as a canonical issue
backend for perk while preserving the spirit of developing-with-erk: plan first,
separate thinking from doing, keep durable state outside a chat session, and make
agent work resumable, reviewable, and human-supervised.

It is intentionally more normative than the current user docs. Some items
describe current implementation. Some describe recommended Linear workspace
configuration. Some describe future product direction. The text calls out those
boundaries explicitly.

## Executive Summary

Linear should not be treated as "GitHub Issues, but with a different API."
Linear has a richer operating model: teams, workflow statuses, labels, projects,
initiatives, views, updates, documents, and agent-native activity streams. perk
should use that richness carefully.

The core recommendation:

- A **perk plan** corresponds to a **Linear issue** with `perk:plan`.
- A **perk learn issue** corresponds to a **Linear issue** with `perk:learn`.
- A **consolidated learning** remains the same issue, closed/done and labeled
  `perk:consolidated`.
- A **perk objective** should initially remain a **Linear issue** with
  `perk:objective`, not a Linear Project or Initiative.
- A **Linear Project** should represent a human-facing deliverable or body of
  work that may contain many perk plans and possibly one or more perk objectives.
- A **Linear Initiative** should represent a higher-level company or product
  goal. It should group projects, not replace perk's objective roadmap model.
- Linear workflow status should be a **visibility mirror**, not the source of
  truth for perk's stage machine.
- Linear AgentSession should become perk's **native operator visibility layer**
  for agent runs, but it must remain additive and fail-open.
- GitHub remains first-class. PRs, CI, review threads, and merge mechanics stay
  GitHub-universal even when canonical plan/learn/objective issues live in
  Linear.

The deepest principle: perk owns the workflow contract; Linear presents and
coordinates it. Linear should make the work more legible to humans without
creating a second canonical workflow.

## Current State

perk already has a backend-neutral issue tier:

- `perk/backends/issue_backend.py` defines the `IssueBackend` protocol.
- `perk/backends/issues.py` resolves the selected backend.
- `perk/backends/linear.py` and `perk/backends/linear_backend.py` implement
  Linear over GraphQL.
- `shared/contracts.md` section 8.21 defines the committed `[issues]` selection.
- `shared/contracts.md` section 8.22 defines opt-in Linear AgentSession
  emission.
- `docs/user-docs/how-to/switch-to-linear.md` documents the current switch path.
- `docs/user-docs/reference/providers-and-backends.md` documents the current
  Linear backend maturity.

The current supported config shape is:

```toml
[issues]
backend = "linear"
team = "SAV"
```

`SAV` is the observed Savantbio team key in Linear project data. Before relying
on it, verify through `perk init --verify` or `perk doctor`.

The current Linear backend is offline-validated against fakes but not yet proven
against a live workspace. The live validation runbook is
`docs/planning/linear-smoke-gate.md`. This is not a minor caveat. The following are still
live-unproven:

- ProseMirror round-trip fidelity for perk's metadata blocks.
- Exact GraphQL not-found error shapes.
- Rate-limit behavior under real API responses.
- Whether all mutation signatures accept the id forms perk currently supplies.
- AgentSession mutation signatures and behavior.
- Interaction with Linear's GitHub Issues Sync if it is enabled.

Any live rollout should start with a throwaway or low-risk repo and explicitly
record observations in `docs/planning/linear-smoke-gate.md`.

## The Spirit to Preserve

Linear adoption should preserve these perk principles:

1. **Plans are gates, not notes.** A plan is written and reviewed before code is
   changed. It is durable, externally visible, and resumable.

2. **Thinking and doing are separate.** Read-only planning remains structurally
   distinct from implementation on a branch.

3. **Canonical state is external.** The durable source of truth lives in the
   selected issue backend. Local `.pi/workflow/` state is cache. Session state is
   transient.

4. **Stages are explicit.** The spine remains plan -> save -> implement ->
   submit -> address -> land -> learn. Linear must not blur those into an
   ambient ticket workflow.

5. **Humans supervise the irreversible gates.** Review, merge, and objective
   reconciliation remain legible and auditable.

6. **Backends are swappable at the issue tier.** GitHub and Linear differ in
   affordances, but perk's common issue contract must remain clear enough that
   GitHub stays first-class.

7. **Visibility is valuable, but not authority.** Linear can display progress,
   group work, and notify teams. It should not silently decide that a perk plan
   or objective is complete.

## Recommended Linear Workspace Model

### Workspace

Use the existing Savantbio workspace. Do not create a dedicated "perk" workspace.
perk-authored issues should live beside human-authored issues because the work is
real product and engineering work, not an internal implementation detail.

The workspace is the company-level collaboration surface. perk should avoid
workspace-global clutter except for namespaced labels and optional views.

### Team

Use one configured Linear team per repo at first.

For Savantbio, the observed team is:

- Team name: `Savantbio`
- Team key: `SAV`
- Observed statuses: `Triage`, `Backlog`, `Planned`, `In Progress`,
  `In Review`, `Done`, `Canceled`, `Duplicate`

This status set is a good fit. It is simple enough for automation and human
interpretation.

Recommended status interpretation:

| Linear status | perk interpretation |
| --- | --- |
| `Triage` | Human intake. perk should not create canonical plan issues here by default. |
| `Backlog` | Accepted but not currently planned. Good for human-authored work. |
| `Planned` | A useful initial state for saved perk plans. |
| `In Progress` | Optional mirror when `perk implement` starts. |
| `In Review` | Optional mirror after `/submit` or `/ready`. |
| `Done` | Terminal mirror after `/land` explicitly closes the plan issue. |
| `Canceled` | Human/operator cancellation, not a normal perk terminal state. |
| `Duplicate` | Linear-native duplicate state; perk should not use it for workflow. |

The important word is "mirror." perk should not infer its stage from these
statuses. perk's durable metadata and plan-ref remain the workflow source of
truth.

### Labels

Labels are the cleanest way to let perk-authored issues coexist with ordinary
Linear issues.

perk should own a small namespaced label vocabulary:

| Label | Owner | Meaning |
| --- | --- | --- |
| `perk:plan` | perk | Canonical implementation plan issue. |
| `perk:learn` | perk | Learning captured after a landed plan. |
| `perk:consolidated` | perk | Learning consumed into docs. |
| `perk:objective` | perk | Canonical multi-plan objective issue. |

These labels should be workspace-level or team-visible labels. Namespacing with
`perk:` is non-negotiable. It makes machine-authored issues easy to filter while
avoiding collisions with human labels such as `Feature`, `Bug`, `Improvement`,
and `area/data`.

Avoid using non-namespaced labels for perk behavior. Human labels may be added
to perk issues, but perk should not depend on them.

Avoid a large status-like label vocabulary such as `perk:in-progress`,
`perk:review`, `perk:blocked`, and so on. Linear already has workflow statuses,
and perk already has canonical metadata. Duplicating state in labels creates
drift.

### Human Labels Beside perk Labels

Human-authored labels are useful context. For example:

- A plan can also be labeled `Bug`.
- A plan can also be labeled `Feature`.
- A plan can also be labeled `area/data`.

These labels should be treated as descriptive, not structural. They help humans
filter and plan work; they do not change perk behavior.

The long-term rule should be:

> `perk:*` labels classify perk artifacts. Human labels classify domain work.

### Issues

A perk-authored Linear issue should look like a normal issue at a glance, but
carry enough structure for perk to resume and mutate it safely.

Recommended conventions:

- The title should be human-readable and not overencoded.
- The label should identify the artifact type.
- The description should carry compact metadata in Linear-safe encoding.
- The plan body should remain recoverable by perk through the backend contract.
- Comments should be used for durable reports, marked comments, and lifecycle
  notes when the common backend contract requires them.
- Manual human comments are allowed.
- Manual edits inside perk metadata regions are unsupported unless done through
  perk.

perk should assume humans can comment, subscribe, assign, add labels, add a
project, and change priority. perk should be robust to those edits.

perk should not assume humans will preserve marker syntax if they edit the
description directly. That is a corruption mode; tooling should diagnose it, not
silently reinterpret it.

### Projects

Linear Projects should represent human-facing deliverables or bounded bodies of
work. They are not the same thing as perk plans.

Good Linear Projects:

- "Pipeline Evaluation Infrastructure"
- "First class support in repo for coding agents"
- "Evaluate Judge-Model Performance"
- "SOC2 Audit - Type 2"

A Linear Project can contain:

- Human-authored issues.
- perk plan issues.
- perk objective issues.
- Learn/consolidation issues if useful, though that is probably less common.

Use Projects as the operator cockpit for a body of work. Do not use Projects as
the canonical representation of a perk objective until perk deliberately owns
that mapping.

Why not map perk objectives directly to Projects now?

- perk objectives have a specific roadmap node schema.
- Nodes have perk-specific statuses: `pending`, `planning`, `in_progress`,
  `done`, `blocked`, `skipped`.
- `planning` is a resumable lease, not a Linear project status.
- Objective reconciliation rewrites bounded prose after landed diffs.
- Linear project status is manual and intentionally not auto-derived from all
  issues.
- Project milestones are useful, but they are not the same as objective nodes.

The likely future direction is "objective issue linked to a Linear Project," not
"objective replaced by a Linear Project."

### Initiatives

Linear Initiatives should remain company/product goal groupings.

Savantbio already uses Initiatives this way:

- Better Evals
- Better Extraction Pipelines
- Better Resolution Pipelines
- Dev Productivity
- Scale
- Quality
- Cost
- Move to GCP

This is a good use of Linear's model. Initiatives are manually curated lists of
projects with high-level health and progress. That is different from a perk
objective, which is an executable roadmap that emits bounded plans.

Recommended rule:

> Linear Initiatives organize projects. perk objectives organize plans.

An Initiative may contain a Project that contains perk objective and plan issues.
That gives leadership visibility without forcing Linear's initiative model to
become perk's execution model.

### Milestones

Linear Project Milestones may be useful for human planning, but they should not
be required for perk initially.

Possible future mapping:

- A project milestone can correspond to a phase of a perk objective.
- A milestone can group the plan issues emitted by objective nodes in that
  phase.

Caveat: milestone progress is based on Linear issue completion status, while
perk objective progress is based on explicit node terminality and land-time
reconciliation. Those are related but not identical.

Do not make milestone completion drive objective node completion.

### Views

Views are one of Linear's strongest advantages over GitHub Issues. They can give
humans a clean operations cockpit without adding new backend contract surface.

Recommended shared views:

- **perk Plans**: `label includes perk:plan`, not completed/canceled.
- **perk Objectives**: `label includes perk:objective`, not completed/canceled.
- **perk Learn Inbox**: `label includes perk:learn`, not `perk:consolidated`,
  not completed/canceled.
- **Active Agent Work**: `label includes perk:plan`, status is `In Progress` or
  `In Review`.
- **Needs Human Attention**: later, if AgentSession or status mirroring exposes
  awaiting input/error states, filter for those.

Views should be treated as presentation. They should not become hidden workflow
dependencies. perk should still work if a view is deleted.

### Assignment and Delegation

Linear has a useful distinction between human assignment and agent delegation.
perk should eventually lean into it.

Recommended model:

- The **assignee** remains the human accountable for the work.
- The **delegate** may be a Linear agent/app user representing perk or a specific
  coding agent.
- A perk implementation run may set or mirror the agent delegate when the
  AgentSession path is enabled.

This preserves human accountability while making agent work visible.

Do not assign all perk-created issues to an agent by default. That makes Linear's
"My Issues" and accountability model worse.

### Triage

Triage should be for human intake and external requests.

perk-authored canonical issues should generally skip Triage and land in a
deliberate accepted status, probably `Planned`. A perk plan has already passed a
planning/review gate; it is not an untriaged request.

Human-authored issues can begin in Triage and later become inputs to perk. For
example, a human issue in Triage can be refined into a perk objective or a perk
plan. The original human issue should remain separate unless we explicitly
support conversion.

## What Corresponds to What

| perk concept | Recommended Linear primitive | Current or future |
| --- | --- | --- |
| Plan | Issue with `perk:plan` | Current/current-compatible |
| Learn issue | Issue with `perk:learn` | Current/current-compatible |
| Consolidated learning | Same issue, plus `perk:consolidated`, terminal status | Current/current-compatible |
| Objective | Issue with `perk:objective` | Current/current-compatible |
| Objective node | Metadata row inside objective issue | Current |
| Objective phase | Metadata convention; optionally future Project Milestone | Future optional |
| Implementation run | perk run/session plus optional Linear AgentSession | Partly current, live-unproven |
| PR | GitHub pull request | Current, always GitHub |
| Review feedback | GitHub PR review threads | Current, always GitHub |
| Project/body of work | Linear Project | Human operating model |
| Company/product goal | Linear Initiative | Human operating model |
| Agent progress | Linear AgentActivity | Future/additive |
| Operator dashboards | Linear Views | Human operating model |

The controversial row is objective. The conservative recommendation is to keep
objectives as special issues until perk has a deliberate Project integration.
Linear Projects are attractive, but they are not a drop-in replacement for the
objective roadmap state machine.

## perk's Strict Point of View

perk should impose a stricter point of view on Linear than a normal team would.
That is the price of making agent-driven work deterministic and resumable.

### 1. Only perk writes perk metadata

Humans may edit surrounding issue prose and comments, but the marker-bounded
metadata belongs to perk.

If metadata is missing or malformed, perk should report a repairable corruption
condition. It should not guess.

### 2. Status is never the only source of truth

Linear status can mirror a stage:

- saved plan -> `Planned`
- implement started -> `In Progress`
- PR opened/ready -> `In Review`
- landed -> `Done`

But perk must not derive the stage solely from Linear status. The existing
contract already normalizes backend state only to `OPEN` or `CLOSED`. That is
the right common abstraction.

### 3. Closing is explicit

GitHub can use `Closes #N` in a squash body. Linear cannot rely on the same magic
words as a backend-neutral guarantee. The current contract is right:

- GitHub backend keeps autoclose semantics.
- Non-GitHub backends use a plain `Plan: <id> - <url>` footer.
- perk explicitly closes the plan issue after land.
- That close is fail-open because merge already succeeded.

This preserves the land gate while avoiding backend-specific commit magic.

### 4. IDs are opaque strings

The common issue tier must treat issue ids as opaque strings:

- GitHub: `"42"`
- Linear: `"SAV-123"`

No shared code should infer backend from id shape. Branch on `backend_id` or
stamped `cache.plan-ref.provider`.

PR numbers remain integers because PRs are still GitHub-universal.

### 5. GitHub remains the PR tier

Even under Linear issue backend:

- PR creation uses GitHub.
- CI/checks use GitHub.
- Review thread resolution uses GitHub.
- Address/review workflows use GitHub.
- Learn derives merged PR context from GitHub.

Linear is the canonical issue tier, not the code-hosting tier.

### 6. Linear Projects and Initiatives are not required for correctness

perk should work if no Project is assigned.

Project/Initiative integration should be additive:

- Good for dashboards.
- Good for human planning.
- Good for leadership visibility.
- Not required to resume a plan.
- Not required to land a PR.
- Not required to reconcile an objective.

### 7. AgentSession is an observability channel, not the run ledger

AgentSession is valuable because humans can see agent work natively in Linear.
But perk's own run id, handoff, cache, plan-ref, and GitHub PR state remain the
operational ledger.

AgentSession emission must stay:

- opt-in;
- environment-token gated;
- fail-soft;
- one-way until a webhook receiver is deliberately designed;
- never allowed to change command exit codes or JSON payloads.

### 8. No hidden dependency on Linear automations

Linear has useful automations: status changes, parent/sub-issue behavior,
GitHub integration behavior, auto-archive, cycle rollover. perk must not require
them for correctness.

Specifically:

- Parent auto-close must not be relied on for objectives.
- Sub-issue auto-close must not mark emitted plans complete.
- GitHub Issues Sync should not be enabled for the initial smoke unless
  deliberately testing sync behavior.
- Auto-archive should not hide active canonical issues unexpectedly.

### 9. Machine-authored and human-authored issues coexist

perk-authored issues should be normal enough that humans can read and discuss
them. Human-authored issues should be normal enough that perk ignores them
unless they are explicitly converted or linked.

The boundary is the `perk:*` label plus metadata. If an issue has no perk label
and no valid perk metadata, it is not a perk artifact.

## Recommended Lifecycle in Linear

### Plan Save

When a plan is approved and saved:

1. perk creates a Linear issue in the configured team.
2. The issue receives `perk:plan`.
3. The issue starts in the team's default state or, preferably, `Planned` if the
   backend grows status-selection support.
4. The body/description contains Linear-safe metadata.
5. The plan body is stored in the canonical location used by the backend
   contract.
6. `cache.plan-ref.provider` is stamped as `"linear"`.
7. `cache.plan-ref.id` is the Linear identifier, e.g. `SAV-123`.

The plan is now canonical. It can be resumed from another session or machine.

### Implement Start

When implementation starts:

1. perk creates or enters a `plan-SAV-123` worktree.
2. The implementation session reads the plan through backend-aware prompt
   instructions.
3. Optionally, perk moves the issue to `In Progress`.
4. If AgentSession emission is enabled, perk creates an AgentSession on the
   issue and emits an initial activity.

The Linear issue is now a human-visible window into active work.

### Submit and Ready

When `/submit` opens a PR:

1. GitHub remains the PR system.
2. perk can add the PR URL to the AgentSession `externalUrls`.
3. perk can emit an AgentActivity describing the opened PR.
4. Optionally, perk can move the Linear issue to `In Review`.

When `/ready` runs checks and marks the PR ready:

1. GitHub check status remains authoritative.
2. Linear status remains a mirror.

### Address

Address remains driven by GitHub PR review state.

Future Linear enhancement: emit AgentActivities during address runs so humans
watch feedback resolution in Linear, but do not move review-thread authority out
of GitHub.

### Land

When `/land` merges the PR:

1. GitHub merge succeeds or fails independently of Linear.
2. After merge, perk explicitly closes/moves the Linear plan issue to terminal
   Done.
3. If objective linkage exists, perk performs objective reconciliation through
   the objective issue.
4. AgentSession emission, if enabled, emits a final response and PR/summary
   context.

Failures in Linear bookkeeping after a successful merge are loud but non-fatal.
The merge already happened.

### Learn

When `/learn` captures a learning:

1. perk creates a Linear issue with `perk:learn`.
2. It links back to the plan id in metadata.
3. The issue remains open until consumed by learn-docs.

When learn-docs consumes it:

1. perk adds `perk:consolidated`.
2. perk moves/closes it to terminal Done.
3. The operation is fail-open on land, following existing secondary bookkeeping
   discipline.

## Advantages Linear Offers Over GitHub Issues

### Native Operator Cockpit

GitHub Issues can store durable text. Linear can present work as an operating
system:

- fast filtered views;
- project dashboards;
- initiative rollups;
- team workflows;
- issue subscriptions;
- status visibility;
- project updates;
- Slack notifications;
- richer search and filters.

This is valuable because perk creates durable work artifacts. Those artifacts
should not be buried in a repository issue list if the team operates in Linear.

### First-Class Agent Identity

Linear distinguishes humans and agents better than GitHub Issues:

- Humans remain assignees.
- Agents can be delegates.
- Agents can be mentionable.
- Agents can have sessions.
- Agent work can be visible without pretending the agent is a human owner.

This maps well to perk's philosophy: humans supervise, agents execute bounded
work.

### AgentSession and AgentActivity

AgentSession is the biggest product advantage.

GitHub issue metadata blocks are durable but visually poor. AgentSession can show
humans:

- the agent has started;
- what it is doing;
- tool/action progress;
- whether it is blocked;
- whether it needs input;
- final result;
- PR link;
- external run link;
- possible future checklist.

This should become the Linear backend's signature feature, but it should not
pollute the shared `IssueBackend` protocol.

### Views and Subscriptions

Linear views can create shared team surfaces such as:

- all active perk plans;
- plans in review;
- objectives in progress;
- stale learn issues;
- agent runs needing input;
- project-specific perk work.

These are much better than asking operators to remember `gh issue list` labels.

### Projects and Initiatives

Linear gives perk-created work a natural place in the company's planning
hierarchy. A plan can belong to a project. A project can belong to an
initiative. That makes agent-authored work visible in the same planning system
as human-authored work.

GitHub Issues has labels and milestones, but Linear's model is more aligned with
how product/engineering teams track bodies of work.

### Webhooks

Linear webhooks could eventually support:

- responding to agent delegation;
- reacting to stop signals;
- detecting human comments on AgentSessions;
- syncing statuses;
- triggering remote perk runs;
- surfacing permission changes.

This should be future work. The first Linear backend phase should remain
explicit-command driven.

## Abstraction Layer Strategy

The right abstraction is not "every Linear feature must map to GitHub." The
right abstraction is two-tiered.

### Tier 1: Backend-Neutral Issue Contract

The common `IssueBackend` stays narrow and canonical:

- ensure labels;
- create/find/update plan issues;
- read plan state/body;
- create/list/close learn issues;
- add/upsert comments;
- create/read/update objectives;
- close issues;
- normalize open/closed state;
- surface opaque string ids.

Both GitHub and Linear must fully support this tier.

This tier is what makes GitHub first-class forever.

### Tier 2: Backend-Specific Enhancements

Linear-only enhancements should sit beside the issue backend, not inside the
core protocol unless GitHub can support the same semantic operation.

Examples:

- AgentSession emission.
- Linear status mirroring.
- Project assignment.
- Initiative/project links.
- View setup guidance.
- Agent delegate handling.
- AgentActivity progress.
- Webhook receiver.

These should be optional and fail-open unless/until promoted into a deliberate
cross-backend contract.

### Promotion Rule

A Linear-only feature can move toward the shared abstraction only if one of these
is true:

1. GitHub can implement a real equivalent, not a fake one.
2. The shared abstraction is phrased at the semantic level, and each backend has
   an honest implementation.
3. The feature is necessary for correctness, not just nicer visibility.

Otherwise, keep it as a Linear side channel.

## Caveats and Failure Modes

### Live Validation Is Still Required

The current Linear backend should be treated as unproven until the live smoke
gate is run. Offline fakes are valuable but cannot prove Linear's editor,
ProseMirror round trip, exact API error shapes, or rate-limit behavior.

### ProseMirror Can Damage Hidden Structure

Linear stores rich text through ProseMirror. HTML comments and details blocks
are not safe assumptions. perk mitigates this through inline-code sentinels, but
the live round trip must be proven.

If metadata fidelity fails, do not paper over it with looser parsing until the
corruption mode is understood. The metadata is the canonical machine contract.

### GitHub Issues Sync Can Create Confusing Mirrors

Linear has GitHub integration and GitHub Issues Sync. For the first live tests,
use a team or repo setup where GitHub Issues Sync is disabled. Otherwise a
perk-created Linear issue may mirror into GitHub, which blurs which issue store
is canonical.

GitHub PR linking is useful. GitHub Issues two-way sync is a separate feature and
should not be part of the initial backend proof.

### Linear Status Automation Can Drift

Linear may move issues based on integrations or workflow automation. That is
fine for human visibility, but perk must not infer correctness from status.

If a user manually moves `SAV-123` to `Done` before `/land`, perk should still
treat the plan according to its own metadata and PR state.

### Parent/Sub-Issue Automation Is Risky

Linear parent/sub-issue auto-close is convenient for ordinary project
management. It is risky for perk objectives because objectives already have a
node state machine.

Avoid representing objective nodes as Linear sub-issues until the mapping is
designed in detail.

### Agent APIs Are Developer Preview

Linear's Agent APIs are powerful but still preview. perk should keep the
AgentSession path behind an environment-token gate and avoid making it required
for normal operation.

### Rate Limits Should Fail Loud

The current Linear client intentionally does not retry/back off on rate limits.
That is acceptable at CLI scale while live usage is unknown. If remote/headless
or webhook-driven use increases call volume, revisit retry/backoff with real
observations.

### Remote Runs Need Secrets

If a remote GitHub Actions runner uses Linear as issue backend, it needs
`LINEAR_API_KEY` available in that environment. If AgentSession emission is
enabled remotely, it also needs `LINEAR_AGENT_TOKEN`.

Those secrets must remain environment/secret-store values, never committed
config.

## Recommended Rollout Plan

### Phase 0: Confirm Workspace Conventions

Before switching a real repo:

1. Confirm the team key is `SAV`.
2. Confirm the team has the expected statuses.
3. Confirm no GitHub Issues Sync interaction will confuse the smoke.
4. Decide whether perk-created issues should initially land in default state or
   whether a later backend enhancement should set `Planned`.
5. Decide whether to create shared views manually for the smoke.

No code change is required for this phase.

### Phase 1: Live Smoke the Existing Backend

Use `docs/planning/linear-smoke-gate.md`.

Exercise:

- `perk init --verify`
- label creation/idempotency
- plan save
- plan re-save
- implement prompt read path
- submit/land closure
- learn capture
- objective create/show/plan/reconcile if in scope

Record every live observation, especially any mismatch with offline fake
assumptions.

Do not enable AgentSession for the first smoke unless the plain backend path is
already proven.

### Phase 2: Human Operating Model

Once the backend works:

1. Create shared Linear views for perk plans/objectives/learn issues.
2. Decide whether to manually add active perk plans to relevant Linear Projects.
3. Establish team guidance: humans may comment and label; do not edit
   perk metadata blocks.
4. Document the status mirror expectations.

This phase can be mostly process/docs.

### Phase 3: Status Mirroring

Add optional backend behavior to set Linear statuses at key moments:

- plan saved -> `Planned`
- implement started -> `In Progress`
- submit/ready -> `In Review`
- land -> `Done`

This should be best-effort and Linear-specific. It should not change the shared
`PlanState` beyond normalized `OPEN`/`CLOSED`.

If status ids are configurable, store only stable user-owned config in
`.pi/perk.toml`. If using status names, doctor should verify them. Do not hide a
status-name mismatch.

### Phase 4: AgentSession Visibility

Validate and then expand the existing `shared/contracts.md` section 8.22 path:

- create AgentSession on implement start;
- emit thought/action activities;
- add PR external URL on submit;
- emit final response on land;
- emit error on failed remote run;
- later add address-run activity;
- later experiment with AgentSession plan/checklist.

Keep `LINEAR_AGENT_TOKEN` as the gate. No token means no behavior change.

### Phase 5: Project/Objective Integration

Only after the issue backend and AgentSession path are stable, design Project
integration.

Possible direction:

- A perk objective issue can optionally link to a Linear Project.
- Plans emitted by the objective can inherit that Project.
- Objective phases may optionally map to Project Milestones.
- Initiative membership remains a Project-level human planning decision.

Do not replace objective issues with Projects until the objective lifecycle is
redesigned around Linear semantics. That is a major product decision, not a
backend implementation detail.

### Phase 6: Webhook-Driven Linear Agent Mode

This is a separate product surface:

- A human delegates a Linear issue to a perk agent.
- Linear creates an AgentSession.
- A webhook receiver starts an appropriate perk workflow.
- The agent emits activities back to Linear.
- Stop/elicitation signals are honored.

This is not required for "Linear as issue backend." It should not be mixed into
the initial backend switch.

## Open Decisions

1. **Should perk set Linear status on create, or leave the team default?**
   Default is simpler. Setting `Planned` is more legible.

2. **Should `[issues]` grow optional status-name config?**
   Example: `planned_status = "Planned"`, `implement_status = "In Progress"`.
   This is useful but adds config surface.

3. **Should perk automatically assign a Linear Project?**
   Probably no at first. Project membership is human planning context unless an
   objective/project mapping is designed.

4. **Should objectives remain issues forever?**
   Conservative answer: yes for now. Future answer may be objective issue plus
   optional project link, not project-only.

5. **Should human-authored Linear issues be convertible into perk plans?**
   This could be valuable, but it needs an explicit command and provenance
   model. Do not infer conversion from labels alone.

6. **Should AgentSession become required for Linear backend?**
   No. It should remain optional until the API is stable and the failure modes
   are well understood.

7. **Should Linear documents hold long-form objective/plan prose?**
   Not initially. Documents are excellent for specs and collaborative editing,
   but introducing them into the canonical issue contract would widen the
   backend substantially.

## The Opinionated Bottom Line

Use Linear as the canonical issue store only at the issue tier. Let perk remain
strict about plans, objectives, ids, metadata, run state, and land semantics.

Then use Linear's strengths where they are strongest: making the work visible,
filterable, discussable, grouped into projects, rolled up into initiatives, and
observable through native agent sessions.

That gives perk the best of both systems:

- GitHub remains the first-class PR and CI backend.
- GitHub Issues remains a first-class canonical issue backend.
- Linear becomes a richer canonical issue backend for teams that live in Linear.
- Linear-only affordances make the experience better without weakening the
  backend abstraction.

The design principle to keep repeating is:

> Canonical workflow belongs to perk. Operational visibility belongs to Linear.
