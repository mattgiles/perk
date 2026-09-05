---
title: The ObjectiveStore seam — splitting an objective tier off IssueBackend
read_when: You are touching `src/perk/backends/objective_store.py`, its GitHub/Linear stores, an objective-storage consumer, the node↔plan unification protocol, objective replan/supersede, or Protocol growth.
cluster: objective-system
---

# The ObjectiveStore seam

Objective #548 carved the **objective-storage tier** out of `IssueBackend` into its own
backend-neutral Protocol — the parallel split to the issue tier (`issue-backend.md`). The contract
lives in `src/perk/backends/objective_store.py` (the `Protocol`, frozen result dataclasses, the
`ObjectiveStoreError` type); the concrete stores live in the backend packages —
`src/perk/backends/github/objective_store.py`, and on Linear the **live project-backed
`LinearProjectObjectiveStore`** in `src/perk/backends/linear/project_store.py` (what
`resolve_objective_store` constructs on the Linear arm) alongside the **dormant issue-backed
`LinearObjectiveStore`** in `src/perk/backends/linear/objectives.py` (self-labeled dormant, not
resolver-wired); the resolver is `src/perk/backends/resolve.py` (all originally one
*perk/backends/objective_stores.py*, since carved apart). This doc preserves the patterns that
generalize the issue-backend extraction to a second tier off the same monolith, plus the Phase-3
node↔plan unification protocol. The backend-neutral contract + consumer rules live here; the Linear
project materialization and manifest-drift *mechanics* live in `linear-backend.md` (the
Projects-substrate, `add_objective_node` project-store flow, and manifest-drift #609/#626
sections) — this doc points there and never restates them.

## Distillation

- Splitting a tier off `IssueBackend` lands in two nodes: Node A = the dormant contract only
  (Protocol + frozen results + fresh error type, implementation-free imports), Node B = atomic
  removal + extraction + resolver + rewire — "The dormant-contract recipe (Node A / Node B
  split)".
- Carving a store off a substrate-heavy backend rides the facade-refactor pattern — "The
  facade-refactor pattern for splitting a tier off a substrate-heavy backend".
- "Behaviorally equivalent, not byte-identical": the store delegates LATE-BOUND to the same
  module functions the CLI tests monkeypatch, keeping them green unchanged — "The equivalence
  lock = late-bound delegation".
- Nodes and plans unify through the node↔plan protocol (`pr`-field linkage, claim semantics) —
  "The node↔plan unification protocol".
- Objective replan is supersede (close-old/create-new, fresh `run_id`, bidirectional lineage) —
  NOT an in-place upsert; `create_objective` is find-then-return idempotent — "Objective
  replan: supersede ≠ upsert".
- Scripted node-linked plan saves must mint a fresh run id per node — the ambient run id
  triggers the same-run-id upsert that rewrites the previous plan in place — "The same-run-id
  upsert trap".
- `find_open_objective_by_origin` is exhaustive-or-raise (§8.24): never silently under-scan; the
  dormant store raises rather than returning a falsely-authoritative `None`; create-only header
  fields are allowlist-omission-enforced and auto-carried across replan — "The origin
  lookup — exhaustive-or-raise".
- The reviewed dream report persists as marker-keyed companion comments on the objective's
  `journal_carrier_id`, with the `dream_report` header reference recorded LAST as the completion
  marker — "The dream-companion flow".
- Historical: the node-numbered growth narratives (Phase-4 protocol growth, the manifest/doctor
  design arcs, adoption growth) chronicle landed work.

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

**Every** concrete store's `backend_id` is a class-level literal — `"linear"` on both Linear
stores; `"github"` on `GitHubObjectiveStore`, exactly as `GitHubIssueBackend.backend_id` —
**never** imported from the resolver: `src/perk/backends/resolve.py` (which owns
`GITHUB_BACKEND_ID` / `LINEAR_BACKEND_ID`) imports the store modules to construct them, so
importing the constant back would cycle. An earlier version of this doc said the GitHub store *can*
reuse the shared `GITHUB_BACKEND_ID` — superseded history: that held only while the resolver and
the GitHub store shared the single retired module the intro names. The working import shape,
cycle-free:

```
objective_store (contract; imports no concrete backend)
  ← github/objective_store + linear/project_store + linear/objectives (each imports the contract)
  ← resolve (imports the concrete stores + the contract; owns the backend-id constants)
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
- **Guard asymmetry (know which guard owns which set).** Today the direct delegation to the
  issue-close primitive stays inside `src/perk/backends/github/` (the store delegates to the
  `plans` substrate), which the consumer-boundary scan in `tests/test_resolve.py` allows
  wholesale — no allowed-set edit is needed. Dated history: when the guards were per-tier
  function-set scans, this delegation had to be added to the issue-tier guard's allowed-set —
  know which guard owns which set. Cross-ref `source-scan-guards.md`.

## The consumer-boundary source scan — the resolver is the only door

The scan lives in `tests/test_resolve.py::TestConsumerBoundary` — folded in from the retired
`test_objective_stores.py` (per that test module's own docstring) — asserting no production module
outside `src/perk/backends/github/` imports the substrate modules
`perk.backends.github.{plans,objectives}` directly; both tiers now express one rule, **"the
resolver is the only door"**. Dated history: adding the objective-tier guard (then a separate
function-set scan) required moving the objective gateway functions OUT of the issue-tier guard's
function set, else the old scan flagged the new module. Static conformance is one ty-checked
annotated binding per store (a protocol-annotated local bound to the concrete instance).

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
- **The project store has no stored roadmap block, so an added node IS a new Linear issue.**
  `comment_updated` is therefore **always `False`** (no body-comment table to patch). The
  Linear-side pipeline lives in `linear-backend.md`
  (`### add_objective_node project-store flow (#614)`).

### The "no-surface, no-op" return-value pattern is a family

`save_node_plan → None`, `post_status_update → False`, and the design-doc'd
`detect/repair_objective_drift` no-ops on GitHub + issue-backed Linear all share one shape: **a no-op
return lets every call site invoke the method UNCONDITIONALLY — no `if backend_id == "linear"`
branch** (mirrors `None`-means-doesn't-unify on the unify path). The fail-open isolation matters: a
`post_status_update` failure lives in its own helper (`_post_landed_update`) so it can't discard an
already-marked node set — the same posture as the existing close fail-open.

### An id-normalization fix at an adapter boundary must cover every entry point

Normalizing canonical `#<n>` ids in one method of
`src/perk/backends/github/objective_store.py` (`_number`) while a sibling method on the same
adapter (`journal_carrier_id`) accepted and re-emitted the same id vocabulary still broke the
production succession fold end to end — the fix initially missed the very path the work existed
to repair. When normalizing an id at a boundary, enumerate **every** method on that boundary
that accepts or emits the vocabulary, and add an end-to-end regression over the **production
adapters**, not just the fixed method's unit test.

### Protocol widening with defaulted-`None` keyword params across N stores

Fakes at the CLI seam plus `None`-only delegation tests leave a real adapter free to hard-code
or drop the new value without failing the suite. When widening the Protocol with a
defaulted-`None` keyword param, add a **non-default forwarding case per concrete adapter per
arm** — including **supersede**, which composes the successor header on a separate path from
create (the delivery/lineage pair, `DeliveryPolicy.STACKED`, is the shipped instance).

### The manifest unifies both backends (the #609 design decision)

GitHub's `objective-roadmap` YAML block **already IS its manifest** (atomically edited → trivially-empty
drift report), so the `detect/repair_objective_drift` methods carry real behavior **only**
on the project store (which derives its roadmap live from node-issues — no baseline to diff) and no-op
everywhere else — the same precedent as the no-op family above. Cross-ref `linear-backend.md` for the
manifest's storage shape.

## The manifest + drift-detection/repair design (#626)

The #609 design landed: persist an authoritative manifest,
detect drift = `diff(manifest, observed)`, repair only the safe/unambiguous cases.

### The manifest pattern (structural identity, not live state)

The `objective-manifest` block (primitives in the `src/perk/objective/` package, `manifest.py`)
pins each node's
**id/slug/description + explicit `depends_on` (always a list)** plus a `phases` map of pinned
milestone names. `status`/`pr` are **deliberately excluded** — they are live/observed, not identity.
Parsing is **three-state**: absent / malformed / valid. Where the manifest physically lives per
backend is `linear-backend.md`'s territory (the manifest-drift #609/#626 + attachment-native #1355
sections) — point, don't restate. It is a **no-op
on GitHub + issue-backed stores** (their roadmap edits are atomic with the body → no divergence
surface), extending the `save_node_plan→None` / `post_status_update→False` no-op family above.

### Pure engine split

`src/perk/objective/drift.py` is fully **offline** (no network/clock/Click): the **store** builds an
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

## The objective doctor is an explicit state machine, not a flat report

The doctor flow resolves a superseded requested id to the **one active objective** up front and
targets *that* for both manifest AND train diagnosis/repair (`redirected_from` preserves the
requested id; the predecessor is never mutated). It then sequences **manifest repair before train
repair**, and **re-diagnoses after writes** — a repair invalidates the diagnosis it acted on, so
the report the human sees is always derived from post-write state, never a stale pre-repair
snapshot patched by hand.

## Objective-keyed engagement reads + the node-keyed sibling (#687/#696/#705)

The objective-keyed engagement reads (`read_comments` / `read_description_edits` /
`read_agent_session`) on GitHub **reuse the issue-tier honest reads** — a GitHub objective IS a
single issue, so the GitHub objective store (`src/perk/backends/github/objective_store.py`) reuses
the sibling engagement substrate (`src/perk/backends/github/engagement.py`) plus the shared private
mappers from `src/perk/backends/github/backend.py` — same backend package/tier, no import-guard
violation.

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

## The same-run-id upsert trap (scripted node-linked saves)

The flip side of `plan_save` being a `run_id`-keyed upsert:

- **Scripted node-linked plan saves must mint a fresh run ID per node.** Reusing the ambient
  workflow run ID invokes the documented same-run idempotent upsert: the stacked-publication
  gate's second save rewrote the previous node's plan **in place** (self-predecessor header, two
  roadmap nodes pointing at one plan) while the command *succeeded* — `issue.existed: true` in
  the payload is the tell.
- `plan save` now refuses a node-linked same-run-id upsert whose stored header names a
  *different* node (`error_type: node_conflict`, fail closed before any mutation; a null stored
  node still links). The fresh-run-id rule remains the correct scripting posture — the guard is
  a backstop, not the workflow.

## Adoption Protocol growth + the no-op family (#708/#711)

`read_objective_source` / `adopt_source_as_objective` extend the `→None` no-op family
(`None` = "no project surface" / "doesn't adopt"); `dry_run → None` falls through to the offline
compose-preview. (See `in-place-adoption.md` for the full adoption story.)

## The origin lookup — exhaustive-or-raise

`ObjectiveStore.find_open_objective_by_origin(origin, exclude_run_id=None)` answers "is an open
objective with this origin already live?" under the **exhaustive-or-raise** posture (§8.24): a
store never silently under-scans. Infra failure raises; a present-but-malformed header raises; an
off-vocabulary origin raises via the closed `ObjectiveOrigin` vocabulary
(`src/perk/objective/_models.py`) and the fail-closed `origin_value` classifier
(`src/perk/objective/parse.py`); only an absent or *different* origin is a skip. Each store
enumerates its full open population: GitHub is an all-pages label scan; the Linear project store
is a team-scoped sentinel sweep; and the **dormant issue-backed store RAISES** — a deliberate
break from the `→None` no-op family, because `None` here would falsely assert
authoritatively-none and silently open a fail-closed guard.

Two consumers, distinguished by `exclude_run_id`:

- **The pre-launch active-origin guard** (`src/perk/cli/commands/learn/dream_cmd.py`) enforces
  one open learn-dream objective per repo with `exclude_run_id=None`, failing closed on an
  unanswerable lookup (`origin_lookup_failed` / `origin_conflict`).
- **The save-time conflict re-check** (`src/perk/cli/commands/objective/create_cmd.py`) passes
  `exclude_run_id=resolved_run_id` — the caller-exclusion that makes a single-ref API sound for
  conflict checks: excluding its own run means any returned ref IS a conflict.

### Create-only header fields + replan closure (#2004)

- **Create-only header fields are enforced by allowlist OMISSION**: `OBJECTIVE_HEADER_FIELDS`
  LBYL-gates only incoming fields — the template for launch-owned provenance fields — and
  render-only-when-set keeps existing objectives byte-identical.
- **A guarded population must be closed under replan.** Supersede is close-old/create-new, so
  any header field feeding an open-population guard needs store-side auto-carry of the validated
  value into the successor — otherwise the guard's population silently loses members across
  replans.

## The dream-companion flow

The reviewed dream report persists as marker-keyed companion comments on the objective's report
carrier — `ObjectiveStore.journal_carrier_id` (GitHub = the objective issue itself; Linear = the
project metadata sentinel issue). The backend-neutral core is `src/perk/learn/dream_companion.py`
(contracts §8.64): the marker grammar, the part-invariance + size rule, the run-scoped
`DREAM_REPORT_TRANSFER_FILENAME` extension→door transfer, and the convergent `persist_parts`.

The save ordering in `src/perk/cli/commands/objective/create_cmd.py::_converge_dream_companion`
is: strict transfer validation (`_read_dream_transfer`: run-id match, requires the run-scoped
dream manifest, part-invariance violations refuse) → `persist_parts` →
`resolve.publish_dream_artifact` (a Linear-only artifact upload; GitHub no-ops — the no-op family
again) → record the `dream_report` header reference **last** (§8.64's convergent ordering — the
header ref is the completion marker, so an interrupted save converges on retry). The Linear
sentinel/attachment mechanics live in `linear-backend.md` — point, don't restate.

## Deferred-doc staleness is intentional, tracked

A code-only extraction node deliberately leaves the contract/module-docstring prose stale for the
dedicated amendment node — don't "fix" it in the extraction PR (perk's "plan bodies are historical;
reconcile via outcomes" discipline). The reconcile pass also disambiguated the live naming hazard:
2.2's **issue-backed** `LinearObjectiveStore` ≠ Phase-3's **project-backed**
`LinearProjectObjectiveStore`.

## Cross-references

- `src/perk/backends/objective_store.py` — the contract module
- `src/perk/backends/github/objective_store.py`, `src/perk/backends/linear/project_store.py` (the
  live project-backed store), `src/perk/backends/linear/objectives.py` (dormant) — the concrete
  stores; `src/perk/backends/resolve.py` — the resolver
- `docs/learned/workflow/issue-backend.md` — the parallel issue-tier split off the same monolith
- `docs/learned/workflow/linear-backend.md` — the Linear facade refactor + the project-backed
  store; owns all Linear project materialization + manifest-drift mechanics (the
  Projects-substrate, `add_objective_node` project-store flow, and #609/#626 manifest-drift
  sections)
- `docs/learned/workflow/objective-lifecycle.md` — objective node status + the supervisor loop
- `docs/learned/workflow/source-scan-guards.md` — the tier-guard asymmetry (which guard owns which set)
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table the resolver reads
- `docs/learned/workflow/doc-reconciliation.md` — the reassigned-removal / past-tense reconcile pattern
- `docs/learned/workflow/human-engagement-reads.md` — the engagement read contract across both tiers
- `docs/learned/workflow/in-place-adoption.md` — the adoption Protocol-growth + no-op family
