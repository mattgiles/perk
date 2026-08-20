---
title: "Issue backends"
description: "GitHub and Linear auth, storage, identifiers, labels, doctor checks, objective representation, and native metadata."
sidebar:
  order: 3052
---

# Issue backends

The committed `[issues]` selection chooses GitHub or Linear for canonical issue and objective
state. One selection controls two distinct protocols — the issue backend and the objective store —
so plans, learnings, gists, and objectives stay in the same tracker family. It does not move pull
requests, review, CI, or merge away from GitHub.

## Comparison

| Concern | GitHub | Linear |
| --- | --- | --- |
| Selection / default | Default when `[issues] backend` is absent or `"github"`; no team key | `[issues] backend = "linear"` plus a committed Linear team key |
| Auth | Authenticated `gh` CLI with repository access | Personal `LINEAR_API_KEY`, sent as a plain `Authorization` value |
| Plan / learn / gist storage | GitHub Issues | Linear issues; an objective-scoped gist is a light Linear Project |
| Objective storage | One GitHub Issue plus its first body comment | One Linear Project, node-issues, milestones, relations, and a metadata sentinel issue |
| Pull request / review / CI / merge | GitHub | Still GitHub; Linear only receives links and bookkeeping |
| Identifiers | Numeric issue ids, commonly written `#42`, and GitHub issue URLs | Human issue identifiers such as `ENG-123`; objective refs are Linear Project ids/URLs |
| Labels | Relevant `perk:*` repository labels are ensured lazily as writes need them | Six `perk:*` workspace labels are checked or ensured by readiness |
| Metadata | Readable HTML-comment metadata blocks in issue bodies and comments | Machine metadata in native issue attachments; selected prose markers remain inline-code sentinels |
| Readiness checks | `issues-backend`, `github-auth`, `github-repo` | `issues-backend`, `linear-auth`, `linear-team`, `linear-labels`, `linear-project-scopes`, `linear-workflow-states` |

The `[issues]` table is read only from the main checkout's committed `.perk/config.toml`. A linked
worktree cannot change the canonical store with a branch-local edit, and `.perk/local.toml` cannot
override the backend or team. A backend edit takes effect after it reaches the main checkout. This
committed-only rule is separate from Linear's local secret storage described below.

## GitHub

### Selection and authentication

GitHub is the zero-config backend. An absent `[issues]` table and an explicit
`backend = "github"` resolve to `GitHubIssueBackend` for issue operations and
`GitHubObjectiveStore` for objective operations.

Authentication uses the `gh` CLI and the current repository remote. The non-mutating,
verify-gated doctor group reports:

- **`github-auth`** — whether `gh` is authenticated and which account it uses;
- **`github-repo`** — whether the checkout resolves to a repository and whether the account has
  push access.

The shared offline **`issues-backend`** check validates the committed backend selection before
network readiness runs.

### Storage, labels, and identifiers

Plans, learnings, and plan-scoped gists are GitHub Issues. Objective-scoped gists also fall back to
GitHub Issues because GitHub has no separate project-tier gist surface. A GitHub objective is one
GitHub Issue: its body owns the objective header and canonical roadmap, while its first comment owns
the rendered roadmap table and Reconcilable prose.

Each write lazily ensures the relevant repository label, including the `perk:plan`, `perk:learn`,
`perk:gist`, `perk:consolidated`, and objective labels. Issue identifiers are numeric and are often
shown as `#42`. Commands that accept an issue or objective id also accept a GitHub
`.../issues/42` URL; a `.../pull/42` URL is rejected because a pull request is a different object.

### Metadata and lifecycle

GitHub keeps perk metadata as readable, marker-bounded blocks in issue bodies or comments. Plan,
learning, gist, and objective headers remain inspectable with `gh issue view`; the objective's
roadmap block is the authoritative manifest for that issue-backed model.

Plan selection is **positively identified** by the backend's own plan-header carrier: the
explicit-id plan doors (`implement`, `address`, `ready`, `plan resume`) refuse an existing issue
with no plan-header block (`issue_kind_mismatch`); a GitHub objective issue's refusal names
`perk objective plan <N>`. Plan-header writes are **merge-only**: `update_plan_header` refuses a
body with no plan-header block (creation is confined to plan-issue creation and in-place
adoption). A malformed-but-present body block degrades to an empty header on read (`{}`) while
still identifying the issue as a plan — the GitHub read posture is tolerant.

Objective replan creates a new objective issue with a fresh identity, carries unfinished roadmap
rows into it, records the predecessor/successor lineage, and closes the old issue after the
successor is established. Unlike Linear, GitHub has no node-issue move or native node-cancellation
projection: the objective remains a single issue and node status is the stored roadmap value.

## Linear

### Selection, auth, and package

Select Linear in committed config and provide the team's **key**, not its display name:

```toml
[issues]
backend = "linear"
team = "ENG"
```

A personal `LINEAR_API_KEY` resolves in this order:

1. a non-blank environment variable;
2. `[linear] api_key` in the main checkout's gitignored `.perk/local.toml`.

The main-checkout lookup makes one local secret available to linked worktrees without copying the
file. The key is sent as a plain `Authorization: <key>` header; `Bearer` is reserved for the
separate OAuth agent token. Interactive `perk init` can prompt for a missing key, validate it, and
store it in `.perk/local.toml`; non-interactive and JSON modes do not prompt.

`perk init` adds `npm:pi-mono-linear` to `.pi/settings.json` when Linear is selected and removes it
when Linear is deselected. Hand-adding the package without selecting the backend is not a supported
configuration.

### Issue-tier storage and labels

Plan and learning records are Linear issues. A plan-scoped gist is also a Linear issue. For an
objective-scoped gist, the objective store first creates a deliberately light Linear Project: its
name and overview carry the gist, with no milestones, node-issues, or metadata sentinel. If that
project-tier path is unavailable, the command falls back to the issue tier.

The readiness path looks up or ensures six workspace-scoped labels:

- `perk:plan`
- `perk:learn`
- `perk:gist`
- `perk:consolidated`
- `perk:objective`
- `perk:objective-node`

Every perk-created Linear issue is assigned to the API-key user. Issue identifiers use the team
shape, such as `ENG-123`; plan worktrees therefore use names such as `plan-ENG-123`, and a Linear
land footer uses `Plan: ENG-123 — <url>` instead of GitHub's `Closes #N`. Id-taking commands accept
Linear issue URLs (`.../issue/ENG-123`) and Project URLs (`.../project/<slug>`); the parser leaves
the resulting id opaque and lets the configured backend resolve it.

Plan selection is positively identified by the plan-header **attachment**: the explicit-id plan
doors refuse a Linear issue with no plan-header attachment (`issue_kind_mismatch`, without
GitHub's right-door hint — a refused sentinel issue's id is not the objective's Project id), and
a Linear **Project** id resolves `plan_not_found` (the honest miss — a Project is not an issue).
Plan-header writes are merge-only here too: `update_plan_header` refuses an issue with no
plan-header attachment (creation is confined to plan-issue creation, adoption, and the node-plan
unification writer). Unlike GitHub's tolerant body-block read, Linear **fails loud** on a
perk-marked plan attachment with a corrupt payload at every plan read — fail-early at the door,
before any side effect (presence-only tolerance lives only in the adoption/doctor reads).

### Readiness checks

The offline **`issues-backend`** check rejects an unknown backend or a Linear selection without a
team. The verify-gated Linear group is non-fatal and ordered so an earlier failure explains why
later probes did not run:

- **`linear-auth`** — the personal key resolves a viewer;
- **`linear-team`** — the configured team key resolves;
- **`linear-labels`** — all six labels exist (`perk init` and `perk doctor --fix` can ensure them);
- **`linear-project-scopes`** — the token can read the team's Projects;
- **`linear-workflow-states`** — the team exposes the unstarted, started, completed, and canceled
  state types needed by the node-status mirror.

These probes report workspace readiness; they do not make pull requests or mutate Project scopes
or workflow states.

### Project-backed objectives

A Linear objective is a **Project**, not an issue. The Project overview contains the copyable
command callout and human Reconcilable prose. Each roadmap node is a Linear issue attached to the
Project, each phase is a Project Milestone, and explicit dependency edges are Linear blocking
relations. The Project's opaque id is the objective id used by perk.

The Project and its issues receive native Linear attributes:

- the API-key user is the Project lead and the assignee of perk-created issues;
- a new Project has a start date so it participates in Linear's project graph;
- entering a started-type node status moves the Project to Started best-effort, and objective
  closure moves it to Completed;
- fail-open Project Updates are posted for objective creation, a plan landing, and reconciliation;
- stamping a GitHub PR adds or updates a native Linear sidebar attachment linked to that PR.

The pull request itself, all review surfaces, CI checks, and merge remain GitHub operations. Linear
receives the PR link; it is not the merge authority.

### Native metadata footprint

Plan, learning, gist, objective-node, objective-header, and objective-manifest metadata use native
Linear issue attachments with machine-readable envelopes. A stable attachment URL is the upsert
identity, and each update replaces the whole envelope. Issue descriptions and Project overviews
therefore keep human prose rather than those machine blocks.

Linear exposes no project-level arbitrary metadata attachment, so every perk objective has a small
metadata sentinel issue named `Perk: objective metadata`, attached to the Project and normally born
in the canceled state. Its two attachments carry the objective header and structural manifest.
Each node-issue carries its node and, after planning, plan metadata in its own attachments. Plan
body comments, callouts, and Reconcilable markers still use Linear-safe inline-code sentinels where
they must live in prose.

This attachment model is a clean break from earlier inline metadata: older Linear artifacts must be
re-created or re-saved before current perk can manage them.

### The dream-report companion

An objective saved by a `perk learn dream` session durably persists the reviewed dream report as
immutable, marker-keyed comments
(`perk:learn-dream-report:<run_id>:<part>`) on the objective's report carrier — on GitHub the
objective issue itself (those comments are the human-visible report), on Linear the Project's
metadata sentinel issue. On Linear the rendered report is additionally uploaded as a workspace
file asset and linked in the Project's **Resources** as `Dream report (<run_id>)`, so humans never
have to read the sentinel. The `objective-header` records the carrier's id under `dream_report`.
The save is convergent: re-running it never duplicates or rewrites a part — a changed part fails
loudly instead.

One narrow Linear failure window is documented rather than closed: if the save crashes after the
Project is created but **before** its metadata sentinel exists, that Project is invisible to
perk's objective lookups (including the one-open-dream-objective guard), so a retried dream save
creates a **fresh** Project and the orphan lingers. An orphan is easy to identify — a Project
with no `Perk: objective metadata` issue and no perk header attachment — and safe to delete
manually: it carries no perk state and no report parts.

### Replan and cancellation behavior

Objective replan creates a net-new Project. Carried unfinished node-issues are **moved** to the
successor Project, preserving their identity, discussion, and open PRs; dropped open node-issues are
moved to Linear's canceled workflow state when available. The old Project receives the successor
link and is completed only after the new objective is established. GitHub replan instead creates
fresh rows in a new issue, as described above.

A human can also cancel a node-issue directly in Linear. perk reads that native state as an
effective `skipped` projection while retaining the attachment's persisted status for diagnosis.
`perk objective doctor --fix` persists the skip only when it can positively prove the node is
unpublished future work without conflicting identity, publication, branch, PR, or journal claims;
otherwise the canceled layer stays visible with blockers.

### Optional AgentSession emission

A separate `LINEAR_AGENT_TOKEN` can opt an implement run into a one-way, fail-soft mirror in
Linear's Agents UI. This token must be an OAuth `actor=app` token and is sent as
`Authorization: Bearer <token>`; a personal `LINEAR_API_KEY` does not work for this API. Without the
agent token, emission is dormant. The GraphQL operations are covered by offline fakes but remain
unverified against a live workspace, so this is not part of the ordinary Linear readiness path.

## Related

- **Look up:** [Providers & issue backends](../providers-and-backends.md) — the supported-set
  overview, comparison, and caveats.
- **Do:** [Switch the issue backend to Linear](../../how-to/switch-to-linear.md) — the
  migration recipe for this switch.
- **Look up:** [Objectives — the roadmap model](../objectives.md) — how objectives are stored
  and behave on each backend.
