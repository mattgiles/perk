# Human-interaction API inventory — SDK decision + operation/field shapes

*Objective #682, Node 1.1 — a **design-only** node. Deliverable = this `docs/planning/` doc. No
code, no `shared/contracts.md` amendment, no `docs/user-docs/` change ships here; the doc is
forward-guidance the implementing nodes (1.2–4.3) consume. This repo has **no markdown linter** in
`just ci` (`ci: setup lint typecheck test` → ruff/biome/ty/tsc/pytest/node:test only), so this
docs-only change skips all hooks.*

This follows the **design-only node pattern** documented in
`docs/learned/workflow/objective-lifecycle.md` (genus of `node-3.1-architecture-correction.md`,
`node-4.3-outcomes.md`): the node is reframed from *build-X* to *author-a-design-doc*; the node
status stays `done` once this lands; a post-merge `/objective-reconcile` updates the roadmap prose +
node 1.1 description (a "delivered the design doc" landed note).

> **Every operation entry below is reference-grade.** It records the operation name, the field
> selection perk needs, the GitHub equivalent (or clean no-op), and which node consumes it. It is
> **not** copy-paste-ready query strings — those are finalized against the live SDL / smoke in node
> 1.2+. Every Linear-touching *read* surface here is **preview-grade / live-unproven** unless an
> entry explicitly cites a `docs/planning/linear-smoke-gate.md` row.

---

## 1. Decision: keep the Python GraphQL backend (SDK + published SDL as reference only)

**Recorded decision (the objective's non-goal made explicit): keep perk's hand-rolled Python GraphQL
Linear backend. Reject an `@linear/sdk` runtime dependency. Adopt the SDK + the published GraphQL SDL
as a *reference only*.**

### Rationale

- **`@linear/sdk` is TypeScript-only.** perk's Linear backend lives entirely in the **Python plane**
  (`perk/backends/linear.py` — the httpx GraphQL `LinearClient`; `perk/backends/linear_backend.py` —
  the `IssueBackend`/`ObjectiveStore` implementation; `perk/backends/linear_agent.py` — agent-session
  emission). The issue backend is the CLI **exterior**, which is single-plane Python. Adopting the SDK
  would require a **second TypeScript plane inside the Python CLI** — a cross-language boundary, a
  Node runtime dependency for a Python subcommand, and a serialization seam for every call. That is a
  large, permanent complexity cost for operations perk already issues directly.
- **The hand-rolled backend is live-proven.** `docs/planning/linear-smoke-gate.md` records live
  observations against a real workspace: ProseMirror round-trip fidelity (the headline check —
  `find_metadata_block` round-trips clean through Linear's re-encode), pagination via
  `LinearClient.paginate`, the rate-limit posture, bare-identifier mutation acceptance (#562), and the
  `_is_entity_not_found` discriminator (gate-8). The backend is not speculative — it ships.
- **The SDK gives nothing the raw GraphQL endpoint doesn't.** Linear's SDK is a thin generated client
  over the same `https://api.linear.app/graphql` endpoint perk already POSTs to. perk loses no
  capability by issuing the documents itself; it gains full control over field selection, error
  parsing (errors-array-first, `LinearGraphQLError.codes`), and ProseMirror handling.

### Adopted use of the SDK + SDL (reference only)

- The **published GraphQL SDL** (`linear/linear` → `packages/sdk/src/schema.graphql`, mirrored at
  Apollo Studio "Linear API@current") is the **authoritative reference** for operation names, input
  types, field availability, and union/enum shapes when authoring or auditing perk's hand-rolled
  GraphQL documents. The inventory in §3 is built against it.
- `@linear/sdk`'s generated `generated_documents.graphql` fragments (e.g. the `IssueHistory`
  fragment) are a useful **cross-check** for which fields are selectable — read, never imported.

### Revisit conditions

This decision is the **default**, not a closure of the question. Revisit if: (a) Linear ships a
read/interaction surface only exposed through the SDK (not the raw GraphQL endpoint) — unlikely given
the SDK is generated *from* the endpoint; (b) the OAuth/agent-token auth flow becomes materially
easier to drive through the SDK; or (c) perk grows a TS plane for unrelated reasons that already
carries the SDK. Absent one of these, keep the Python GraphQL backend.

---

## 2. Status quo — what the Python backend already does

Verified facts the inventory builds on (anchors, not aspirations):

### `perk/backends/linear.py` — the one request wrapper

- `LinearClient.request(query, variables)` — the single GraphQL POST. **Errors-array-first**: a
  GraphQL `errors` array raises `LinearGraphQLError` carrying `.codes` (the per-error `code` strings).
  Consumers branch on `.codes`, never on message substrings.
- `LinearClient.paginate(query, variables, *path)` — cursor pagination
  (`pageInfo { hasNextPage endCursor }`), used by `_comments`.
- `LinearClient.team_id(team_key)` (via `teams(filter:{key})`) and `LinearClient.viewer_id` —
  identity helpers.
- `_is_entity_not_found(exc)` — the missing-entity discriminator: `INPUT_ERROR` code **and**
  `"entity not found"` in the message (smoke-gate-8; `INPUT_ERROR` alone is too broad). Bare
  identifiers (`PER-<n>`) are accepted everywhere a UUID was once required (#562); only
  `issueRelationCreate` consumes a captured UUID.

### `perk/backends/linear_backend.py` — `_comments`, today

- `LinearIssueBackend._comments(issue_id)` selects **`comments { nodes { id body createdAt } }`**
  only, sorted ascending by `createdAt` (pins GitHub's oldest-first first-match semantics). Used today
  **only for marker matching** (find perk's metadata-block comment). It selects **no author identity**
  (`user`/`botActor`), **no `editedAt`**, **no reactions**. → Extending this selection is the heart of
  §3's comment-listing surface.

### `perk/backends/linear_agent.py` — one-way emission, today

- Emits only: `agentSessionCreateOnIssue`, `agentActivityCreate`, `agentSessionUpdate` (mutation
  documents substring-pinned offline; field signatures verified live at the smoke gate's "Agent
  session emission" section — Linear **accepts** these mutations live).
- **Reading** prompts/activities, the **stop signal**, and **elicitation replies** are explicitly
  **deferred** here today (the module's own deferral register). The agent token (`LINEAR_AGENT_TOKEN`,
  OAuth `actor=app`) gates emission; whether reads need it vs the personal API key is an **open
  question** (§6).

### `docs/planning/linear-smoke-gate.md` — proven documents to cite

- ProseMirror round-trip CLEAN (plan header, body comment, objective body, Reconcilable splice).
- `projectCreate` / `projectUpdate` content round-trip (content accepted at create).
- `projectUpdateCreate` — the Project Update status feed (Mode 4, live-proven).
- Issue/comment mutations by **bare identifier**; agent mutations accepted live.

---

## 3. Operation inventory (the core)

One entry per human-interaction surface named in the node. Each records the **Linear operation +
fields perk reads**, the **GitHub equivalent (`gh`) or clean no-op**, and the **consuming node(s)**.

### 3.1 Comment listing — human vs perk vs other-agent author

| | Detail |
| --- | --- |
| **Linear** | Extend `_comments`' selection: `comments { nodes { id body createdAt editedAt user { id name displayName } botActor { id name type } } }`. The **`user`** field is the human/account author; **`botActor`** is populated when the comment was posted by an integration/bot/agent (its presence + identity distinguishes "other agent / perk's own bot" from a human). `editedAt` (nullable) flags an edited comment. Optional: `reactions { emoji user { id } }`. Today's selection is `{ id body createdAt }` only. |
| **GitHub** | `gh issue view <n> --json comments` → `comments[]` with `author { login }`, `body`, `createdAt` (already used in `perk/github/prs.py` `_issue_body_and_comments`). Author identity = `author.login`; "perk vs human vs other agent" is decided by login + the perk-metadata grammar (a comment carrying a `perk:metadata-block:*` sentinel is perk's). GitHub exposes no `botActor` analogue beyond the login/`__typename: Bot`. |
| **Consumers** | 1.2 (read impl), 1.3 (GitHub impl), 2.1, 2.2, 2.3, 3.1 |
| **Grade** | Linear extension preview-grade (the `botActor`/`user`/`editedAt` selection is **live-unproven** — 1.2 records a smoke observation). |

### 3.2 Description / body edit history

| | Detail |
| --- | --- |
| **Linear** | Detect a **human** description edit via `issue(id){ history(first: N) { nodes { id createdAt actor { id name } descriptionUpdatedBy { id name } } } }`. The SDL's `IssueHistory.descriptionUpdatedBy` (added per `linear/linear` commit `f597059`, "the actors that edited the description of the issue, if any") is the precise field for "who edited the body." `actor` (nullable for integrations/automations) attributes the change. The ProseMirror `documentVersions` / userContent surface is an **alternative** for content-diffing — flag it preview-grade and unproven; the *history + `descriptionUpdatedBy`* path is the recommended default. **Caveat:** `issue.history()` has had SDK-side selection pitfalls (`relationChanges`), so select fields explicitly. |
| **GitHub** | The GraphQL `userContentEdits` connection on an `Issue` (and on each `IssueComment`) via `gh api graphql` — `issue(...) { userContentEdits(first: N) { nodes { editedAt editor { login } diff } } }`. Honest support with limits: `diff` is best-effort and may be null for old/migrated content; `userContentEdits` is GraphQL-only (not on `gh issue view --json`). Record the limit, don't overpromise. |
| **Consumers** | 1.2, 1.3, 2.2, 2.3 |
| **Grade** | Preview-grade / live-unproven on **both** backends (the exact field for a human description edit — history+`descriptionUpdatedBy` vs document versions — is an §6 open question to settle live in 1.2/4.3). |

### 3.3 Agent-session activities + prompts (read)

| | Detail |
| --- | --- |
| **Linear** | The **inbound counterpart** of `linear_agent.py`'s emission. Read via `agentSession(id){ activities(first: N) { nodes { id createdAt signal content { __typename ... on AgentActivityPromptContent { body } ... on AgentActivityElicitationContent { … } ... on AgentActivityResponseContent { … } ... on AgentActivityThoughtContent { body } ... on AgentActivityActionContent { … } ... on AgentActivityErrorContent { … } } } } }`. The `content` union (`AgentActivityContent!`) has the six variants **action / elicitation / error / prompt / response / thought** (SDL-confirmed). The `signal` enum (§3.4) is per-activity. A human prompt into an existing session lands as a `prompt` activity (the `prompted` webhook puts the text in `agentActivity.body`). `AgentSession.promptContext` is a formatted context string; `agentSession.issue` / `.comment` / `previousComments` give structured context. |
| **GitHub** | **No-op** — GitHub has no agent-session surface. The 1.3 GitHub impl returns empty/`None` cleanly. |
| **Consumers** | 1.2 (read contract), 4.1, 4.2 |
| **Grade** | Preview-grade / live-unproven (perk has only ever *emitted* these; reading them is new — 1.2/4.3 record observations). |

### 3.4 The `stop` signal

| | Detail |
| --- | --- |
| **Linear** | Per `linear.app/developers/agent-signals`, `signal` is an enum on an `AgentActivity` — values **`auth` / `continue` / `select` / `stop`** — set by a human on a `prompt`-type activity to guide the agent. The **`stop`** signal instructs the agent to halt immediately (no further actions/changes/API calls) and emit a final activity before disengaging. perk reads it via the §3.3 activities query (`activities { nodes { signal content { __typename } } }`) and surfaces a **stop-signal indicator** at session start/continuation; node 4.1 acts on it (disengage + final response). |
| **GitHub** | **No-op** — no signal surface. |
| **Consumers** | 1.2 (read contract), 4.1 (acts on it) |
| **Grade** | Preview-grade / live-unproven (the precise read path — which session, only the latest prompt, etc. — is an §6 open question). |

### 3.5 Project updates

| | Detail |
| --- | --- |
| **Linear** | Write path **already live-proven**: `projectUpdateCreate(input:{ projectId, body })` — the Project Update status feed (`LinearProjectObjectiveStore.post_status_update`; smoke-gate Mode 4, `health` omitted per D3). If a later node **reads** updates back: `project(id){ projectUpdates(first: N) { nodes { id body createdAt user { id name } } } }`. Record the read shape; perk does not read them today. |
| **GitHub** | **No-op** — GitHub has no Project-update surface in perk's model. |
| **Consumers** | 4.1 (status emit), 2.3 (reconcile context, if it reads updates back) |
| **Grade** | Write proven (Mode 4); read shape preview-grade / unproven. |

### 3.6 Elicitation activities

| | Detail |
| --- | --- |
| **Linear** | **Pull-based** (no live loop, no webhook receiver): perk emits an `elicitation` `AgentActivity` (`agentActivityCreate(input:{ agentSessionId, content:{ type: "elicitation", … }, signal: "select"? })`) and ends the session. The **next** perk session reads the human's reply via the §3.3 activities read path (a follow-up `prompt` activity) and/or the §3.1 comment read path, then resumes. The `select` signal optionally marks a choice-style elicitation. |
| **GitHub** | **No-op** — no elicitation surface. |
| **Consumers** | 4.2 |
| **Grade** | Preview-grade / live-unproven (emission of `elicitation` + reading the reply is new; `agentActivityCreate` is accepted live but the elicitation `content` shape + reply round-trip is unproven — 4.2/4.3 record it). |

---

## 4. Field-shape appendix — what the 1.2 read contract depends on

For each backend-neutral result the **1.2** node will define, the source fields that populate it on
each backend, and the author-identity rule. **Advisory only** — this does *not* pre-author 1.2's
dataclasses or Protocol methods (that is 1.2's deliverable).

### 4.1 A human comment

- **Linear source fields:** `comment.id`, `comment.body` (untrusted DATA), `comment.createdAt`,
  `comment.editedAt` (nullable → edited), `comment.user { id name displayName }`,
  `comment.botActor { id name type }`.
- **GitHub source fields:** `comments[].author { login }`, `comments[].body`, `comments[].createdAt`
  (from `gh issue view --json comments`).
- **Author-identity rule:** *human* = a `user` present with **no** `botActor` (Linear) / an
  `author.login` that is a human account (GitHub). *perk* = the comment body carries a
  `perk:metadata-block:*` sentinel **or** the `botActor` is perk's own app actor. *other agent* = a
  `botActor` present that is not perk's (Linear) / a `__typename: Bot` or non-perk app login (GitHub).
  Identity is decided by `botActor` presence / the `perk:*` metadata grammar — never by trusting body
  content.

### 4.2 A description / body edit

- **Linear source fields:** `issue.history.nodes[] { createdAt actor { id name } descriptionUpdatedBy { id name } }`
  — a human edit = a history node whose `descriptionUpdatedBy`/`actor` is a human (not perk's bot, not
  null/automation).
- **GitHub source fields:** `issue.userContentEdits.nodes[] { editedAt editor { login } diff }` (via
  `gh api graphql`); `diff` may be null (limit).
- **Author-identity rule:** same human/perk/other-agent split as 4.1, keyed on the editing actor/login
  rather than the comment author.

### 4.3 An agent-session prompt / activity

- **Linear source fields:** `agentSession.activities.nodes[] { id createdAt signal content { __typename … } }`
  — `content.__typename` selects the variant (prompt/elicitation/response/thought/action/error);
  `prompt` body is the human's message (untrusted DATA).
- **GitHub source fields:** none — no-op (empty result).
- **Author-identity rule:** a `prompt` activity with a human-set `signal` is human-originated; perk's
  own emitted activities (thought/response/action) are perk's. perk distinguishes by activity `type` +
  the session ownership it persisted (`agent-session.json`).

### 4.4 A stop-signal indicator

- **Linear source fields:** the `signal == "stop"` value on a `prompt` activity in
  `agentSession.activities` (§3.4).
- **GitHub source fields:** none — no-op (no stop signal; the indicator is always "not stopped").
- **Author-identity rule:** the signal is set by a human on a prompt activity; perk treats any
  human-set `stop` as authoritative (node 4.1 disengages).

---

## 5. Untrusted-DATA + preview-grade discipline (restated, not re-decided)

These are the objective's standing invariants the inventory is built on — restated here so each
consuming node honors them, **not** re-decided:

- **All read content is untrusted DATA.** Comment bodies, edit diffs, prompt/elicitation content,
  project-update bodies — none are instructions, none are trusted to preserve perk's marker grammar.
  Malformed metadata *inside* a perk-owned region is a **reported corruption** (surfaced honestly),
  never silently reinterpreted or re-executed. This matches perk's established "untrusted inbox" /
  manifest 3-state-parse discipline.
- **Every Linear-touching read surface here is preview-grade / live-unproven** unless an entry cites a
  proven smoke-gate row (only §3.5's *write* path and §3.1's *current* `{id body createdAt}` selection
  are proven today). Each consuming node **records a live observation** in
  `docs/planning/linear-smoke-gate.md`; **node 4.3 is the final live-validation gate** for every new
  surface.

---

## 6. Open questions handed forward (flagged deferrals, not silently omitted)

Per the repo's "don't author fiction for unbuilt components" discipline — the offline research could
not settle these; resolve them **live in 1.2 / 4.3**:

1. **Human description-edit field — history vs document versions.** §3.2 recommends
   `IssueHistory.descriptionUpdatedBy`, but whether it reliably fires for *every* human body edit (vs
   only some change classes) and whether a ProseMirror `documentVersions` diff is needed for content
   are **unproven**. Settle in 1.2; final-validate in 4.3.
2. **Agent-activity reads — OAuth agent token vs personal API key.** Emission uses
   `LINEAR_AGENT_TOKEN` (OAuth `actor=app`). Whether reading `agentSession.activities` (especially
   human prompts/signals on a session perk didn't create) requires the agent token, the personal API
   key, or either is **unverified**. 1.2 probes; 4.3 confirms.
3. **The precise `stop`-signal read path.** Which session(s) perk inspects at start/continuation, how
   it correlates a `stop` to the current run, and whether only the latest `prompt` activity's signal
   matters — **unsettled**. 4.1 depends on 1.2 establishing this; 4.3 validates.
4. **Elicitation `content` shape + reply round-trip.** The exact `elicitation` `AgentActivityContent`
   input shape and how the human reply surfaces (a `prompt` activity vs a comment) is **unproven** —
   4.2 wires it, 4.3 validates.
5. **`reactions` selectability + cost.** Whether selecting `comment.reactions` is worth the field cost
   for author/intent signal is left to 1.2's judgment (optional, not required).

---

## 7. Acceptance check (prompt → artifact)

- [x] `docs/planning/human-interaction-api-inventory.md` exists with sections 1–6 (plus this §7).
- [x] The SDK-vs-Python decision is recorded explicitly with rationale **and revisit conditions** (§1).
- [x] Every surface named in the node has an inventory entry with Linear op + GitHub equivalent/no-op
      + consuming node(s): comment listing (§3.1), description/body edit history (§3.2), agent-session
      activities + prompts (§3.3), the `stop` signal (§3.4), project updates (§3.5), elicitation
      activities (§3.6).
- [x] Each later node can point to the shapes it depends on: **1.2** (§3.1–3.6 + §4 contract bridge),
      **1.3** (§3.1–3.2 GitHub columns; §3.3–3.6 no-op), **2.1/2.2/2.3** (§3.1–3.2), **3.1/3.2**
      (§3.1 + §4 provenance read), **4.1** (§3.3–3.5), **4.2** (§3.3, §3.6), **4.3** (every
      preview-grade row + the §5/§6 validation list).
- [x] `just ci` green by construction — verified: `ci: setup lint typecheck test`, no markdown gate
      (ruff scoped to `perk tests`, biome/tsc on the TS plane, pytest/node:test); a docs-only change
      runs no hooks.
- [ ] Post-merge `/objective-reconcile` to update the roadmap prose + node 1.1 description (a
      "delivered the design doc" landed note) — flagged for the reconcile pass.
