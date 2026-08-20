---
title: The §8.25 human-engagement read contract
read_when: You are working on the §8.25 human-engagement read contract — a read seam (issue-keyed vs node-keyed), a flow consumer, the `src/perk/backends/engagement.py` renderers, or the delivery asymmetry.
cluster: backends-and-integrations
---

# The §8.25 human-engagement read contract

perk plans and objectives accrue **human engagement** — comments, description edits, and prior
agent-session transcripts on the backing issue/node. The engagement subsystem reads that signal
honestly (real authorship, real timestamps) and surfaces it into a plan/author/replan session as
bounded **untrusted DATA**, so the model can take human steering into account without trusting
arbitrary body content as instructions. This is the durable reasoning behind that subsystem,
end to end.

## The decoupled-vocabulary leaf

`src/perk/backends/issue_backend.py` (issue-keyed) and `src/perk/backends/objective_store.py`
(objective-keyed) are **intentionally decoupled** — neither imports the other. But the engagement
reads need a shared vocabulary: the result dataclasses, `AgentSessionRead`, and the author model.
That vocabulary lives in a **third pure leaf**, `src/perk/backends/engagement.py`, which imports
*neither* tier.

**The rule:** when two intentionally-decoupled modules need a shared vocabulary type, add a pure
leaf and have both depend on it — never reach across with a cross-tier import to borrow the type.

## Two keyings, two seams — never reuse across keying

There are two distinct read keyings, and they are not interchangeable:

- **Issue/objective-keyed** — `read_comments` / `read_description_edits` / `read_agent_session`,
  keyed by the issue (or the objective-as-issue).
- **Node-keyed** — `read_node_engagement(*, objective_id, node_id)`, keyed by a roadmap node, which
  is a *different subject* than the objective issue.

The decision rule for a **new** consumer:

- **If the subject IS itself an issue, reuse the issue-keyed reads directly** — no new Protocol
  method, bundle, or conformer. (Replan got the engagement feature *for free* this way, #702: its
  subject is the plan issue.)
- Only a genuinely **node-level** subject needs the node-keyed plumbing (#696) — a roadmap node is
  not the objective issue, so it cannot borrow the issue-keyed reads.

## Growing the contract is a ty-static conformance ripple across all sites

Adding the three engagement reads to *both* `IssueBackend` and `ObjectiveStore` at once (#687)
forced conformance across **7 sites**: 5 production implementers (including the dormant
`LinearObjectiveStore`) + 2 test fakes. `read_node_engagement` (#696) was a smaller 3-implementer
+ `_FakeObjectiveStore` ripple.

**Census every site up front** — the dormant store and the test fakes are the easy misses. The
whole-repo `ty check` is the oracle that catches an unconformed site.

## The empty/no-op conformer family + shared frozen constants

**Honesty is per-method, per-backend**: a backend implements a read honestly wherever its platform
exposes the primitive, and ships a clean **empty/no-op** return where it doesn't — `()` for
comments/edits, and the **shared frozen constants** `EMPTY_AGENT_SESSION` / `EMPTY_NODE_ENGAGEMENT`
for the bundle reads. The current matrix:

| read | GitHub issue backend | Linear issue backend | GitHub objective store | Linear project store | dormant Linear store |
|---|---|---|---|---|---|
| `read_comments` | honest (gh GraphQL) | honest | honest (the objective IS an issue) | honest (project threads) | empty |
| `read_description_edits` | honest (`userContentEdits`) | honest | honest | honest-empty (no project-level edit-history primitive — a flagged deferral) | empty |
| `read_agent_session` | empty (no GitHub surface) | honest | empty | empty | empty |
| `read_node_engagement` | — (issue tier) | — (issue tier) | empty (no per-node issues) | honest (node-issue comments+edits) | empty |

Test fakes stay all-empty. Each no-op docstring flags where the honest read actually lands (or why
none exists).

A single shared **immutable** constant is safe to reuse across all no-op sites (the constants are
frozen). This mirrors the established `save_node_plan → None` / `post_status_update → False` no-op
family on the objective store.

## The author classifier (a heuristic over perk's OWN grammar)

`classify_author` orders perk → other_agent → human → unknown. Durable points:

- **perk has no committed app-actor id.** perk detection therefore rests on the **body-sentinel
  regex** (perk's own marker grammar), not an actor id; `perk_bot_ids` is an **empty forward seam**
  kept for the day a committed actor id exists.
- **The sentinel check is an identity heuristic over perk's own marker grammar** — sentinel-wins
  even when a human `user` is also present — never trust of arbitrary untrusted body content. The
  regex uses per-block-bounded negated character classes, so it is **ReDoS-safe**.
- **Gotcha (#690): an always-constructed `Actor` defeats the `unknown` tier.** If the backend
  always hands `classify_author` a constructed actor, nothing ever resolves to `unknown`. The
  neutral actor mapper must return `None` when the backend resolved no fields, so the absent actor
  flows through as `classify_author(user=None, bot_actor=None) → unknown`. (Mirror Linear's
  `_actor_or_none`.)

## Honest read mechanics, per backend

- **Linear (#687).** The marker-matching comment selection is load-bearing and byte-pinned. Add a
  **sibling** `_comments_with_authors` (which also selects `editedAt`/`user`/`botActor`) rather
  than mutating the byte-stable `_comments` — the established "leave the byte-stable selection
  untouched, add a sibling query" rule (cf. `project_issues` vs `project_issues_with_milestones`).
  `read_agent_session` is a two-step resolve: a **missing** issue/session reuses the
  `_is_entity_not_found` (INPUT_ERROR + "entity not found") → empty pattern; an **auth** failure
  **raises** (fail-loud accommodates the still-unproven personal-key-vs-agent-token question).
- **GitHub (#690).** *Both* comments and description edits go through `gh api graphql` — porcelain
  `gh issue view --json comments` lacks the edited-at timestamp and the bot/human discriminator,
  and `Issue.userContentEdits` is the only honest edit-history source. (The transport-level
  gh-GraphQL facts live in `github-gateway.md`; the contract-level "why GraphQL, not porcelain"
  lives here.)

## The renderer family (untrusted-DATA bounded blocks)

The renderer family is pure and dependency-free (so unit-testable): `render_node_engagement` /
`render_plan_engagement` / `render_adopted_engagement` / `render_objective_engagement` →
`_render_engagement` → `_engagement_item_lines`.

- **Filtering policy.** Skip only the unambiguous perk-sentinel **comments**. Render description
  **edits labeled-by-kind, never filtered** — classification is preview-grade, and silently
  dropping an edit loses real human signal.
- **Bounded.** Most-recent ≤30 items per surface, each body ~1500-char truncated; wrapped in
  `<untrusted_*_engagement>` blocks with a treat-as-DATA preamble.
- **The byte-stable extraction discipline.** Each deeper extraction (now three-deep:
  `render_node_engagement` → `_render_engagement` → `_engagement_item_lines`) MUST keep the prior
  renderers byte-identical — pin every pre-existing surface with explicit byte-equality asserts.

## Cold-injects / warm-instructs asymmetry

- **The cold door knows its subject** (the node/issue is fixed at launch) → it reads engagement
  **directly** and **injects** the rendered block into the seed. Fail-soft (`try/except → EMPTY`)
  and gated (`if not dry_run`).
- **The warm door cannot pre-fetch** (the model selects the subject in-session) → it **instructs
  the model to run** the read worker once it knows the subject.
- **Seed byte-unchanged on the empty path** is the discipline: the injection rides an optional
  `node_engagement: str = ""` param, proven by a seed byte-equality assertion.
- **Per-consumer injection placement (#702):** match the injection to where the consumer already
  keeps its untrusted DATA — inline seed vs scratch-file append after `</untrusted_plan>`. Note
  that replan `--dry-run` is **not** offline (it materializes the real artifact, so it reads
  engagement, with fail-soft yielding determinism).

## Worker-side composition over Protocol growth (3rd application, #705)

The aggregate `perk objective engagement <N>` **composes existing reads** (project-level +
`read_node_engagement` looped over every node) rather than growing the Protocol. The accepted cost
is N re-scans on Linear (a batched single-fetch is a flagged follow-up). Registering a read worker
is two edits: `objective/__init__.py` `mark_kind(…, "worker")` + an alphabetical `EXPECTED_SURFACE`
parity-smoke entry.

## Cross-references

- `issue-backend.md` — the issue-keyed reads + the github-native-rows→adapter mapping
- `objective-store.md` — the objective-keyed reads + the node-keyed sibling
- `linear-backend.md` — Linear's honest-read mechanics (sibling selection, `_is_entity_not_found`)
- `github-gateway.md` — the gh-GraphQL transport facts behind the GitHub honest reads
- `plan-factories.md` — the cold-injects/warm-instructs asymmetry as a reusable factory pattern
- `doc-reconciliation.md` — reconciling objectives whose nodes deliver engagement reads
