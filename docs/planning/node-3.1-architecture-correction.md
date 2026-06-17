# Node 3.1 architecture correction — re-home the Linear Projects substrate onto the client

**Status:** landed-but-defective. PR #578 (merged as #579) shipped the Node 3.1 Linear Projects
GraphQL substrate, but with an **architecture defect** in *where the API-client logic lives*. This
note records exactly what landed, why it is wrong, and the precise end-state the **Node 3.2**
implementer must converge to **before** building `create_objective`. Read this in full first.

This is a context-handoff document, not a plan. It does not change the objective's goals — every
Phase-3 design decision in objective #548 stands. It corrects only the *substrate's internal
shape*.

---

## 1. The principle that was violated

**The only thing that should encapsulate Linear GraphQL API-client logic is the `LinearClient`.**

A "Linear op" class (`_LinearIssueOps`, `_LinearProjectOps`) is an orchestration layer. It composes
higher-level behaviors (find-by-run-id, create-objective, attach-issue-to-project) out of primitive
client operations. It must **register only the client** and reach all GraphQL machinery through it.
It must **never** reach into a *sibling* op class's private internals, and one op class must
**never compose another** just to borrow the client and the shared helpers.

Concretely, the intended constructor shape is symmetric and client-only:

```python
class _LinearIssueOps:
    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        ...

class _LinearProjectOps:
    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        ...
```

Both **simply register the client and that's it.** Neither holds the other.

---

## 2. What actually landed in PR #578 (the defect)

The substrate shipped in `perk/backends/linear_backend.py` as:

```python
class _LinearProjectOps:
    def __init__(self, issue_ops: _LinearIssueOps) -> None:
        self.issue_ops = issue_ops   # <-- WRONG: composes the issue ops, not the client
```

and every method reaches **through** the sibling op class's private internals:

- `self.issue_ops._client.request(...)`
- `self.issue_ops._team_id()`
- `self.issue_ops._uuid_for(...)` (via `_update_issue`)
- `self.issue_ops._paginate(...)`
- `self.issue_ops._update_issue(...)` / `self.issue_ops._create_issue(...)`
- the module-level `_require_*` validators and `_is_entity_not_found` (those are at least
  module-level, not reached through the sibling — but the team-id / uuid / paginate / create /
  update machinery is all borrowed from `_LinearIssueOps`).

**Why this is wrong (not a style nit):**

1. It makes `_LinearProjectOps` structurally depend on a *second op class* to function. The project
   substrate cannot exist without an `_LinearIssueOps` instance handed to it — a backwards coupling
   (projects depending on the issue tier's private surface).
2. It scatters API-client responsibilities. Team-UUID resolution, identifier→UUID resolution, the
   `nodes`+`pageInfo` cursor loop, and the missing-entity discriminator are **Linear GraphQL
   API-client concerns**. They were living as private methods on `_LinearIssueOps`; the project ops
   borrowing them cements the client logic in the wrong layer instead of on the client.
3. It violates the stated rule directly: `_LinearProjectOps` "registers" `_LinearIssueOps`. It must
   register only the client.

> The shared caches (`_team_id_cache`, `_uuid_cache`) were the original justification for composing
> — one shared cache. That is a **real** concern, but it is solved by putting the cache on the
> **client** (the natural owner of resolved-id memoization), **not** by composing op classes.

---

## 3. The required end-state (what Node 3.2 must converge to first)

Move the shared Linear GraphQL machinery **onto the `LinearClient`** (`perk/backends/linear.py`, the
class that today owns only `request()`), so it is the single home for API-client logic. Then both op
classes take the client and reach that machinery through `self._client`.

### 3a. Promote onto `LinearClient` (the "new LinearClient")

Move (or re-home) these from `_LinearIssueOps` onto `LinearClient`, with their caches:

- `_team_id()` resolution + `_team_id_cache` — **but note** team-key is constructor state on the op
  classes today; the client is currently team-agnostic. Decide the cleanest seam: either (a) the
  client gains a `team_id(team_key)` method with an internal `{team_key: uuid}` cache, or (b) a thin
  `LinearClient` is constructed per-team. **(a) is preferred** — keep the client team-agnostic at
  construction and pass `team_key` to the resolver, cached by key. Confirm against how the resolver
  (`resolve_objective_store` / `resolve_issue_backend`) constructs these today.
- `_uuid_for(identifier)` identifier→UUID resolution + `_uuid_cache` (read-seeded).
- `_paginate(query, variables, *path)` — the generic `nodes`+`pageInfo` cursor loop.
- `_is_entity_not_found(exc)` — already module-level; it can stay module-level **or** become a
  client method/staticmethod. Keep it reachable without composing a sibling.
- the `_require_dict/_require_list/_require_str` validators — already module-level; leave them
  module-level (pure functions, no client state) **or** fold onto the client. Either is fine; do not
  borrow them through a sibling op class.

### 3b. Symmetric, client-only op classes

- `_LinearIssueOps.__init__(self, client, *, team_key, repo_root)` — unchanged signature, but its
  body now calls `self._client.team_id(self._team_key)`, `self._client.uuid_for(...)`,
  `self._client.paginate(...)` instead of owning those methods.
- `_LinearProjectOps.__init__(self, client, *, team_key, repo_root)` — **takes the client**, holds
  `self._client = client` (+ `team_key`/`repo_root` as needed). It calls `self._client.<machinery>`
  for everything. **It does not accept or hold an `_LinearIssueOps`.**

### 3c. Preserve the landed Node 3.1 surface verbatim (behavior-equivalent move)

Every op that landed must survive the re-home, byte-faithful in its GraphQL document and its
parsed-return shape:

- `create_project(*, name, content) -> {id, url}`
- `update_project_content(project_id, content) -> None`
- `project_or_none(project_id, selection) -> dict | None`
- `project_milestones(project_id) -> list[{id, name}]`  (paginated; key phases by **name**)
- `project_issues(project_id) -> list[{id, identifier}]`  (paginated)
- `create_project_milestone(*, project_id, name) -> str`
- `attach_issue_to_project(*, issue_id, project_id) -> None`  (resolves issue id via uuid resolver)
- `create_document(*, project_id, title, content) -> str`  (reserved overview fallback)
- `document_content_or_none(document_id) -> str | None`
- `create_issue_relation(*, issue_id, related_issue_id) -> str`  (takes resolved UUIDs; does **not**
  route through `_is_entity_not_found` — its bad-id error is `INVALID_INPUT` / "Argument Validation
  Error", fail-loud)
- `issue_blocks(issue_id) -> list[str]` / `issue_blocked_by(issue_id) -> list[str]`  (filter
  `type == "blocks"`; `issue_blocked_by` reads `inverseRelations` — the `depends_on` sources)

And the `_LinearIssueOps._create_issue` extension stays: optional `project_id` / `milestone_id`,
added to the `input` only when non-`None` (omit, never explicit `null`).

### 3d. Single shared cache — on the client

The original "one `_team_id_cache`, one `_uuid_cache`" goal is **preserved**: the caches live on the
`LinearClient`, so a store that owns one client and constructs both op classes over it gets a single
shared cache automatically — *without* the op classes composing each other. This is strictly better
than the landed design (it also de-duplicates the cache when only one op class is in play).

---

## 4. Constraints / acceptance

- `just ci` (ruff + ty + pytest + node:test) stays green; `ruff`/`ty` clean on touched Python.
- All coverage stays **offline** through the `GraphQLClient` / `_FakeLinear` fake — no live Linear
  calls. Move the Node 3.1 tests (`TestLinearProjectOps`) to construct `_LinearProjectOps(client,
  team_key=..., repo_root=...)` — the client-only shape — and update any test that constructed it as
  `_LinearProjectOps(_LinearIssueOps(...))`.
- Behavior-equivalence is the bar: the GraphQL documents and parsed returns are unchanged; only the
  *ownership/wiring* of the client machinery moves. Re-assert the existing Node 3.1 test expectations
  (e.g. `create_project` still resolves the team UUID and sends `teamIds: [<uuid>]`; relation reads
  still filter to `type == "blocks"`).
- Keep `_is_entity_not_found`'s **pairing** semantics intact (`INPUT_ERROR` in `exc.codes` AND the
  `"Entity not found"` message prefix — Node 1.2 / docs/planning/linear-smoke-gate.md gate-8). Do not loosen
  it to a `.codes`-only check during the move.
- No cross-plane behavior change, no CLI/envelope/tool surface change — this stays dormant substrate
  (consumed by 3.2's `create_objective` and 3.3's reads). Contract/user-doc amendments remain
  deferred to the consuming nodes + Phase-5 reconciliation.

---

## 5. Why this preserves objective #548's goals (nothing is lost)

- **Projects == objectives, nodes == issues, explicit deps == blocking** — unchanged. The same ten
  ops back `create_objective`/`get_objective`; only their wiring moves.
- **Overview is canonical, document is the reserved fallback** — unchanged (`create_project` content,
  `documentCreate` reserved).
- **Deterministic node ordering, status-block authority, blocking-relation depends_on** — unchanged;
  the read/mutation ops (3.3) consume the same surface.
- **State-ownership invariants** (the table in the objective) — unchanged.
- The correction makes the substrate **more** faithful to the masterplan's "the client is the API
  seam" intent and removes a backwards coupling that would have made 3.3/3.4 harder. It is a net
  simplification, not a scope change.
