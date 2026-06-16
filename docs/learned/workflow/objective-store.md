---
title: The ObjectiveStore seam — splitting an objective tier off IssueBackend
read_when: You are touching `perk/backends/objective_store.py` / `perk/backends/objective_stores.py`, an objective-storage consumer, the dormant-contract → atomic-removal recipe, the Linear facade-refactor pattern, the resolver single-sourced off `[issues]`, the `backend_id` import-cycle literal, the `close_issue`-vs-`close_objective` tier split, or the node↔plan unification protocol on the objective-linked `plan-save` path.
---

# The ObjectiveStore seam

Objective #548 carved the **objective-storage tier** out of `IssueBackend` into its own
backend-neutral Protocol — the parallel split to the issue tier (`issue-backend.md`). The contract
lives in `perk/backends/objective_store.py` (the `Protocol`, frozen result dataclasses, the
`ObjectiveStoreError` type); the concrete stores + resolver live in
`perk/backends/objective_stores.py`. This doc preserves the patterns that generalize the
issue-backend extraction to a second tier off the same monolith, plus the Phase-3 node↔plan
unification protocol.

## The dormant-contract recipe (Node A / Node B split)

The split lands in two roadmap nodes, directly reusing the proven `issue_backend.py` Node-1.1
pattern (cross-ref `issue-backend.md`):

- **Node A = dormant contract only.** A new module carrying the `Protocol`, its frozen result
  dataclasses, and a fresh backend-neutral error type — and *nothing else*. No concrete impl, no
  resolver, no consumer rewire, **no removal from the old protocol**. Imports stay
  implementation-free: here only `dataclass`/`Protocol`/`perk.objective` — deliberately **no
  `perk.github`**, because (unlike `IssueBackend.PlanState`) no objective value type carries a PR
  field. The import-direction guards (read the module text, assert `perk.github` /
  `perk.backends.issues` substrings are absent) prove the decision.
- **Node B = atomic removal + extraction + resolver + rewire** in one PR.

Shape decisions worth reusing: `ObjectiveState` was **already** backend-neutral (opaque `id`,
opaque `header` dict), so a Linear Project id/metadata fits with no shape change — the only
genuinely new value type was `ObjectiveRef` (the old find/create returned the issue-named
`IssueRef`). The contracts carry a field rename across the twin tiers: `issue_id → objective_id` on
the node/body update dataclasses. Brief intentional duplication of the objective dataclasses across
the two contract modules during the dormant phase is accepted.

## The atomic-removal CI-green rule (Node B)

Removing a `Protocol` surface + its dataclasses from a contract that has **≥2 concrete impls and
many consumers MUST land in ONE PR.** It is CI-green only when the new store surface, the resolver,
ALL consumer rewires, AND the removal from BOTH concrete backends land **together**.

*Why the removal cannot be its own standalone green PR* — two compounding reasons ty enforces:

1. **Consumers are typed against the protocol.** Every consumer resolves a backend annotated
   `-> IssueBackend` then calls the objective method; drop the methods and ty reports
   unresolved-attribute at every call site.
2. **The new surface returns a NEW type.** The new contract's find/create return `ObjectiveRef`
   (not the old `IssueRef`), so the concrete backends do **not** already satisfy the new protocol —
   they must be adapted (the Node B extraction).

So the removal and the rewire are **inseparable**. Consequence: a roadmap node whose prompt says
"remove the methods" often must have that removal **reassigned to the next node** — pre-declare it
in the plan body and let `/objective-reconcile` fix the node descriptions post-merge (done here:
2.1 → dormant-only, 2.2 → gains the removal).

## The facade-refactor pattern for splitting a tier off a substrate-heavy backend

GitHub was the easy case: a thin late-bound delegation adapter — its objective methods moved
verbatim. **Linear was the hard part:** its objective methods sat on the issue backend atop ~68
internal `self._…` call sites across shared caches (`_uuid_cache`/`_team_id_cache`/`_label_ids`)
and ~18 private helpers. The resolution is a **registered collaborator, not inheritance**:

- Extract a module-private ops class owning the whole substrate (client, team_key, caches, every
  helper). The backend becomes a thin facade that builds its own ops instance and delegates every
  public method to it.
- The new store builds its **own** ops instance and carries the objective methods.
- **The mechanical risk is the ~68 rewrites.** A scoped word-boundary `re.sub` over the
  public-method region is safe: `\b` does **not** match inside underscore-joined cache names
  (underscore is a word char), so cache-name prefixes don't get mangled. But keep the moved-helper
  name set **explicit** and **never blanket-replace `self._*`** — the PR-tier `_get_pr` and public
  self-calls (`find_comment_id_by_marker`) must NOT be rewritten. A renamed attribute
  (`self._repo_root` → the ops' public `repo_root`) is handled separately.
- **Re-expose what tests assert on the facade.** A `_team_key` attr and the readiness probe's
  private-helper calls were kept reachable via the facade so the existing backend tests stay green.

## The equivalence lock = late-bound delegation

The GitHub store keeps every CLI/integration objective test green **unchanged** because it delegates
late-bound to the same `perk.github` module functions those tests monkeypatch — only backend-level
*unit* tests move. This is the precise meaning of **"behaviorally equivalent, not byte-identical"**,
and the reason the move is low-risk. Mirror it in any future tier extraction over `perk.github`.

## Translate-CM beats rewriting every raise (Linear store)

Rather than rewrite every internal error raise, wrap each store-method body in a module-level
context manager mapping `IssueBackendError → ObjectiveStoreError` (message-verbatim via
`str(exc)`). Two facts make it clean:

- `LinearGraphQLError` **subclasses** `IssueBackendError`, so raw GraphQL errors are caught too.
- Nested self-calls already raise the *converted* `ObjectiveStoreError`, which the outer CM does
  **not** re-catch (it isn't an `IssueBackendError`) — it propagates with the right type, no
  double-wrap.

The GitHub store uses a local translate CM plus a `_number`-style raiser on the non-numeric-id edge
(the GitHub-numeric-id assumption), mirroring the issue gateway.

## Resolver single-sourced off `[issues]`

`resolve_objective_store_id` re-exports `resolve_issue_backend_id` — an objective and its plan/learn
issues share ONE `[issues] backend` selection (they live in the same tracker). **There is no
parallel `[objectives]` table.** The lazy/no-network resolver mirrors the issue resolver (the Linear
arm needs committed `[issues] team` + `LINEAR_API_KEY`, same hinted errors).

## `backend_id` literal discipline survives the split (import-cycle avoidance)

`LinearObjectiveStore.backend_id` is the module-level literal `"linear"` — **NOT** imported from the
resolver, because the resolver module imports the backend module, so importing back would cycle. The
GitHub store *can* reuse the shared `GITHUB_BACKEND_ID` because `objective_stores.py` imports the
issue gateway one-directionally. The working import shape, cycle-free:

```
objective_store (contract; imports only perk.objective)
  ← linear_backend (imports the contract)
  ← objective_stores (imports issues + linear_backend + the contract)
```

## `close_issue` is issue-tier; `close_objective` was added later onto the store

Node 2.1 defined **NO** close on the contract. Mixed consumers (`pr land` reconcile, `objective
run`) kept an `IssueBackend` for the close while also holding a store for the objective ops (under
both issue-backed stores objective id == issue id, so it was behaviorally identical). #595 (Node
3.4) added `ObjectiveStore.close_objective` to remove the issue-tier close leak: `pr land` and
`objective run` now close via `store.close_objective`.

- The GitHub store impl **deliberately delegates straight to the GitHub issue-close primitive** (a
  GitHub objective IS an issue), so existing GitHub-path tests that monkeypatch the issue close keep
  passing **transparently via delegation** — proving "via the store, not the issue backend" requires
  injecting a fake store.
- **Guard asymmetry (know which guard owns which set).** That direct call trips the **issue-tier**
  source-scan guard's allowed-set (so add `objective_stores.py` to it), NOT the objective-tier
  guard (whose function set does not include the issue-close primitive). Cross-ref
  `source-scan-guards.md`.

## The objective-tier source-scan guard mirrors the issue-tier one

The new objective-tier guard asserts no production module outside `objective_stores.py` /
`perk/github/` calls the objective gateway functions. When you add it you **MUST move those
functions OUT of the issue-tier guard's function set**, else the old scan flags the new module.
Static conformance is one ty-checked annotated binding per store (a protocol-annotated local bound
to the concrete instance).

## The node↔plan unification protocol (#595)

On the objective-linked `plan-save` path a *unifying* store (the project-backed Linear store) writes
the plan INTO the node-issue and returns its ref; a *non-unifying* store (GitHub, issue-backed
Linear) returns `None` unconditionally. The whole capability protocol is one method returning
`ObjectiveRef | None` — no separate capability flag — and it works because:

- **`None` is an unambiguous "doesn't unify" signal *because a unifying store RAISES on
  not-found*** (it never returns `None` for not-found).
- **`dry_run` also returns `None`** (resolving the node-issue needs a network read; `--dry-run` is
  offline) → the caller falls back to the offline compose-preview.
- The dispatch guard runs the unify path **only when `not dry_run and objective_id and node_id`**,
  leaving the standalone create branch (ensure_label + create) byte-unchanged in the `else`.
- The merge into the node-issue uses the **form-preserving inline-code replace** when a
  `plan-header` is present, else composes the inline-code render and appends — never the bare
  append path, which appends in lossy HTML form on Linear.

### Derive the land-time backlink self-referentially (the clobbered-field correction)

In the unified "the plan IS the node-issue" model, the node's land-time `pr` backlink is the
node-issue's **OWN identifier** — NOT the `plan-header`'s `pr` field, because `pr submit` overwrites
that field with the GitHub PR number; reading it would break the land-match after submit. This
supersedes the earlier "pr from the plan-header `pr` field" reading. Because the cached plan-ref's
id already *is* the node-issue identifier, `nodes_for_pr` / `pr submit` / `pr land` needed zero
changes. **Durable: in a unified model, derive the backlink self-referentially; never read a field a
later stage clobbers.**

### Unification has a visible side effect

The squash commit title is the **node-issue title** (its roadmap `"{id}: …"` identity), NOT the plan
H1 — so an objective-linked land's commit reads `"1.1: Node one\n\n…"`, not the plan title. Anyone
touching title rendering should know **node-issue title ≠ plan title**. (The TS plane needed no
change — `objective_id` was already an opaque string, and the resolver flip just makes it a Project
UUID.)

## Deferred-doc staleness is intentional, tracked

A code-only extraction node deliberately leaves the contract/module-docstring prose stale for the
dedicated amendment node — don't "fix" it in the extraction PR (perk's "plan bodies are historical;
reconcile via outcomes" discipline). The reconcile pass also disambiguated the live naming hazard:
2.2's **issue-backed** `LinearObjectiveStore` ≠ Phase-3's **project-backed**
`LinearProjectObjectiveStore`.

## Cross-references

- `perk/backends/objective_store.py` — the contract module
- `perk/backends/objective_stores.py` — the concrete stores + resolver
- `docs/learned/workflow/issue-backend.md` — the parallel issue-tier split off the same monolith
- `docs/learned/workflow/linear-backend.md` — the Linear facade refactor + the project-backed store
- `docs/learned/workflow/objective-lifecycle.md` — objective node status + the supervisor loop
- `docs/learned/workflow/source-scan-guards.md` — the tier-guard asymmetry (which guard owns which set)
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table the resolver reads
- `docs/learned/workflow/doc-reconciliation.md` — the reassigned-removal / past-tense reconcile pattern
