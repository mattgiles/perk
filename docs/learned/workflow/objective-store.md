---
title: The ObjectiveStore seam — splitting an objective tier off IssueBackend
read_when: You are touching `perk/backends/objective_store.py`, the concrete stores under `perk/backends/github/` / `perk/backends/linear/`, the resolver in `perk/backends/resolve.py`, an objective-storage consumer, the dormant-contract → atomic-removal recipe, the Linear facade-refactor pattern, the resolver single-sourced off `[issues]`, the `backend_id` import-cycle literal, the `close_issue`-vs-`close_objective` tier split, the node↔plan unification protocol on the objective-linked `plan-save` path, objective replan / `supersede_objective` (supersede ≠ upsert, the fail-open-close error boundary), the objective-keyed engagement reads + the node-keyed sibling, the adoption Protocol growth (`read_objective_source`/`adopt_source_as_objective`), the Protocol-method-count growth / three-implementers conformance rule, the `add_objective_node` re-render-vs-materialize split, or the no-op-return (`save_node_plan`/`post_status_update`/drift) family.
---

# The ObjectiveStore seam

Objective #548 carved the **objective-storage tier** out of `IssueBackend` into its own
backend-neutral Protocol — the parallel split to the issue tier (`issue-backend.md`). The contract
lives in `perk/backends/objective_store.py` (the `Protocol`, frozen result dataclasses, the
`ObjectiveStoreError` type); the concrete stores now live in the backend packages
(`perk/backends/github/objective_store.py`, `perk/backends/linear/objectives.py`) and the resolver
in `perk/backends/resolve.py` (all originally one *perk/backends/objective_stores.py*, since
carved apart). This doc preserves the patterns that generalize the
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

## Phase-4 protocol growth: three implementers, `add_objective_node`, the no-op-return family

### Adding a Protocol method now means THREE implementers

The `ObjectiveStore` Protocol grew **6 → 9 → 10 → 12** methods across Phase 3/4: Phase 3 added
`save_node_plan` / `close_objective` / `post_status_update`; Phase 4 added
`add_objective_node` (#614) then `detect_objective_drift` / `repair_objective_drift` (#626). There
are now **three** concrete implementers — GitHub, the dormant
issue-backed `LinearObjectiveStore`, and the **live** project-backed `LinearProjectObjectiveStore`
(`linear-backend.md`). **Durable rule: adding any Protocol method now means writing THREE
implementers**, all enforced by ty static conformance — the `_make_store` / `_make_project_store`
typed-annotation bindings plus `_FakeObjectiveStore` in `tests/test_objective_store.py`. A
Phase-2-era plan authored against a 2-backend world **under-counts** this after a rebase pulls in the
third store (the #614 plan predated `LinearProjectObjectiveStore` and hit exactly this expansion); the
Protocol-append rebase conflict is purely additive (both parties append after `update_objective_body`
→ keep both). The #626 growth carries its own trap: CI's **whole-repo `uv run ty check` caught the
stale `_FakeObjectiveStore`** when `ty check perk/` alone did **not** — the conformance fake lives
under `tests/`, so scope the type check to the whole repo, never just `perk/`.

### `add_objective_node`: the re-render-vs-materialize split

`ObjectiveNodeAdd` is the **sixth** frozen result dataclass. The implementers split on *where a node
lives*:

- **GitHub + issue-backed Linear re-render the stored `objective-roadmap` block** — mirror
  `update_objective_node` verbatim, swapping the mutation to `objective.add_node`.
- **The project store has no stored roadmap block, so an added node IS a new Linear issue.** Its flow:
  compute the live roadmap → compute the `<phase>.<n>` id → enrich the phase name → ensure the phase
  milestone → create the node-issue → create one blocking relation per `depends_on`. `comment_updated`
  is therefore **always `False`** (no body-comment table to patch). The Linear-side mechanics live in
  `linear-backend.md`.

### The "no-surface, no-op" return-value pattern is a family

`save_node_plan → None`, `post_status_update → False`, and the design-doc'd
`detect/repair_objective_drift` no-ops on GitHub + issue-backed Linear all share one shape: **a no-op
return lets every call site invoke the method UNCONDITIONALLY — no `if backend_id == "linear"`
branch** (mirrors `None`-means-doesn't-unify on the unify path). The fail-open isolation matters: a
`post_status_update` failure lives in its own helper (`_post_landed_update`) so it can't discard an
already-marked node set — the same posture as the existing close fail-open.

### The manifest unifies both backends (the #609 design decision)

GitHub's `objective-roadmap` YAML block **already IS its manifest** (atomically edited → trivially-empty
drift report), so the `detect/repair_objective_drift` methods carry real behavior **only**
on the project store (which derives its roadmap live from node-issues — no baseline to diff) and no-op
everywhere else — the same precedent as the no-op family above. Cross-ref `linear-backend.md` for the
manifest's storage shape (a visible inline-code block in the project overview).

## The manifest + drift-detection/repair design (#626)

The #609 design landed: persist an authoritative manifest,
detect drift = `diff(manifest, observed)`, repair only the safe/unambiguous cases.

### The manifest pattern (structural identity, not live state)

The `objective-manifest` block (primitives in `perk/objective.py`) pins each node's
**id/slug/description + explicit `depends_on` (always a list)** plus a `phases` map of pinned
milestone names. `status`/`pr` are **deliberately excluded** — they are live/observed, not identity.
Parsing is **three-state**: absent / malformed / valid. The block lives in the overview **between**
the `objective-header` block and the Reconcilable region, inline-code (Linear-safe). It is a **no-op
on GitHub + issue-backed stores** (their roadmap edits are atomic with the body → no divergence
surface), extending the `save_node_plan→None` / `post_status_update→False` no-op family above.

### Pure engine split

`perk/objective/drift.py` is fully **offline** (no network/clock/Click): the **store** builds an
observed snapshot (the one network step), then the pure `detect_drift` returns a report of conditions
each carrying a stable **code / severity / target / `repairable` flag**. The test suite is one case
per code; a **malformed or absent manifest short-circuits** (no baseline to diff).

### Authority precedence — the subtle invariant

Who owns phase names **depends on the operation**:

- **add-node:** the **manifest** is authority for an **existing** phase — attach the node to the
  manifest-pinned milestone, **never re-derive** from externally-editable overview prose (the
  overview only *seeds* a brand-new phase).
- **reconcile:** the **overview** is authority — refresh the pins to match it exactly, **including
  reverting to the `Phase N` default** when a header is removed.

Consistent framing: manifest authoritative on add-node *reads*, overview authoritative on reconcile
*writes*. (A first attempt guarded against the default-clobber on reconcile — **wrong**; reconcile
tracks the overview.)

### Graph reconstruction with intra-batch deps (the deferred-edge sweep)

Detection can only diff a dependency **between two observed nodes** — it can't diff an edge while an
endpoint is absent. So the recreate path **owns every edge touching a recreated node in BOTH
directions** (the node's own `depends_on` AND an already-existing dependent's edge to it). The robust
shape: **create all missing node-issues first**, then **one comprehensive post-loop sweep** restores
every manifest edge Linear lacks — skipping edges already present and observed↔observed (owned by the
explicit dependency repair, so no double-create), failing loud on a genuinely unresolvable endpoint.
**General lesson:** when repairs create nodes other repairs depend on, **split node-creation from
edge-creation** and drive edges off the **full manifest**, not per-node.

## Objective-keyed engagement reads + the node-keyed sibling (#687/#696/#705)

The objective-keyed engagement reads (`read_comments` / `read_description_edits` /
`read_agent_session`) on GitHub **reuse the issue-tier honest reads** — a GitHub objective IS a
single issue, so cross-importing the private `issues.py` mappers into `objective_stores.py` is
allowed (same backend tier, no import-guard violation).

Linear specifics:

- Linear projects expose **no description-edit-history primitive** → `read_description_edits` stays an
  honest empty `()` (the edit signal lives on node-issues).
- `read_comments` is **honest over project comments** — Project Updates are deliberately NOT read
  (they are perk's own *outbound* feed).
- The node-keyed `read_node_engagement` is honest **only on the project-backed store** (a roadmap node
  IS a node-issue); GitHub + the dormant issue-backed store → `EMPTY_NODE_ENGAGEMENT`.

**The deferral-comment-names-its-consumer rule:** when a stub carries a comment naming a future node,
that node's plan should *consume* it (flip the stub + update the comment), not add a parallel surface.
(See `human-engagement-reads.md` for the full subsystem.)

## Objective replan: supersede ≠ upsert (#855)

`perk objective replan <N>` re-authors an objective as a **superseding net-new** objective (the
`supersede_objective` Protocol method), and the design hinges on a store-shape fact:

- **supersede (close-old/create-new) ≠ in-place upsert.** plan-`replan` rewrites in place because
  `plan_save` is a `run_id`-keyed **upsert**. objective-`replan` CANNOT mirror that:
  `create_objective` is **find-then-return idempotent** on `run_id` (returns `existed=True`
  *without* rewriting) — there is **no** in-place objective-rewrite primitive. The resolved shape is
  close-old/create-new with a **fresh `run_id`**, **bidirectional lineage** (`supersedes` on the new
  header / `superseded_by` on the old), and **create-new-first, close-old-last, fail-open on the
  close** (the §8.24 bookkeeping posture). Durable: when a store op "isn't an upsert," reach for
  close-old/create-new rather than inventing an in-place rewrite.
- **The no-op-family Protocol growth → census the conformance fakes.** `supersede_objective`
  (returns `ObjectiveRef | None`; `None` = "store doesn't support it") joins the no-op-family
  (`adopt_source_as_objective` / `save_node_plan` / `post_status_update`). The non-obvious ripple:
  `tests/test_objective_store.py::_FakeObjectiveStore` is a **structural conformer**, so whole-repo
  `ty check` fails (`protocol member … not defined`) until the fake gains the method — the
  per-method delegation tests do **not** catch a missing Protocol member. Always add a new method to
  the minimal conformance fake.
- **Fail-open close must use lower-level primitives, not the public store methods.** The
  superseded-close (`_close_superseded_objective`) runs **inside** the outer `_translate_objective()`
  CM and catches `IssueBackendError`. The public methods
  (`update_objective_header`/`close_objective`/`post_status_update`) each open their OWN
  `_translate_objective()` and raise `ObjectiveStoreError`, which an `except IssueBackendError`
  would **NOT** catch — so the close-old work calls the lower-level `_projects`/`_issue_ops`
  primitives directly (they raise `IssueBackendError`). Watch the error-type boundary when composing
  fail-open bookkeeping out of would-be-public methods.
- **Handoff-carrier symmetry.** The cold door stashes `supersedes=<OLD>` in the run handoff exactly
  as `objective author --from` stashes `adopt_from` (`_supersedes_from_handoff` is a verbatim
  structural copy of `_adopt_from_handoff`: explicit flag wins, malformed handoff never blocks a
  save). The carried-node mapping **reuses `objective.parse_adopt_mapping` + the per-node
  `adopt_issue` field** — interpreted as **MOVE** semantics in supersede context vs in-place **STAMP**
  in adoption context (no TS schema edit; `adopt_issue` already flows through `ROADMAP_PARAM_SCHEMA`).
  `create_cmd` dispatch went `if supersedes / elif adopt_from / else create`; `--supersedes` /
  `--adopt-from` are **mutually exclusive** (incompatible models).
- **Residual:** a Linear `pending` node-issue (no plan yet) reads back `pr=None`, so the cold-door
  scratch can cite a node-issue ref only for in-flight nodes; the Linear MOVE path itself is flagged
  **not-live-proven** (verify at the smoke gate). Cross-ref `in-place-adoption.md` (STAMP vs MOVE)
  and `linear-backend.md` (the `FakeLinearWorkspace` routing/state additions supersede surfaced).

## Adoption Protocol growth + the no-op family (#708/#711)

`read_objective_source` / `adopt_source_as_objective` extend the `→None` no-op family
(`None` = "no project surface" / "doesn't adopt"); `dry_run → None` falls through to the offline
compose-preview. (See `in-place-adoption.md` for the full adoption story.)

## Deferred-doc staleness is intentional, tracked

A code-only extraction node deliberately leaves the contract/module-docstring prose stale for the
dedicated amendment node — don't "fix" it in the extraction PR (perk's "plan bodies are historical;
reconcile via outcomes" discipline). The reconcile pass also disambiguated the live naming hazard:
2.2's **issue-backed** `LinearObjectiveStore` ≠ Phase-3's **project-backed**
`LinearProjectObjectiveStore`.

## Cross-references

- `perk/backends/objective_store.py` — the contract module
- `perk/backends/github/objective_store.py`, `perk/backends/linear/objectives.py` — the concrete
  stores; `perk/backends/resolve.py` — the resolver
- `docs/learned/workflow/issue-backend.md` — the parallel issue-tier split off the same monolith
- `docs/learned/workflow/linear-backend.md` — the Linear facade refactor + the project-backed store
- `docs/learned/workflow/objective-lifecycle.md` — objective node status + the supervisor loop
- `docs/learned/workflow/source-scan-guards.md` — the tier-guard asymmetry (which guard owns which set)
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table the resolver reads
- `docs/learned/workflow/doc-reconciliation.md` — the reassigned-removal / past-tense reconcile pattern
- `docs/learned/workflow/human-engagement-reads.md` — the engagement read contract across both tiers
- `docs/learned/workflow/in-place-adoption.md` — the adoption Protocol-growth + no-op family
