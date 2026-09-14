---
title: The ObjectiveStore tier — backend-neutral objective storage, its three stores, and the Protocol-growth rules
read_when: You are touching `perk/backends/objective_store.py`, its GitHub/Linear stores or the resolver, an objective-storage consumer, node↔plan unification, objective replan/supersede, or Protocol growth.
cluster: objective-system
---

# The ObjectiveStore tier

perk's durable state has two populations: the **issue tier** (plan/learn issues — `IssueBackend`,
`issue-backend.md`) and the **objective tier** — the `ObjectiveStore` `Protocol` in
`perk/backends/objective_store.py` with its frozen results and `ObjectiveStoreError`. An objective
is a GitHub issue **or** a Linear **Project**. `shared/contracts.md` §8.24 is the normative
statement (the method census, the state disciplines, stores, resolver, unification storage,
close/reopen, manifest + drift, origin); `linear-backend.md` owns the Linear materialization,
attachment and manifest-drift *mechanics*. This doc keeps only the rules and traps neither states
as such — point, never restate.

## Distillation

- One tier, three stores, one door: `GitHubObjectiveStore`, the **live** project-backed
  `LinearProjectObjectiveStore`, the **dormant** issue-backed `LinearObjectiveStore`, resolved
  off the committed `[issues]` selection — "The tier's shape".
- Growing the Protocol touches every store **plus the structural conformance fake** in one
  change, caught only by whole-repo `ty check` — "Growing the Protocol".
- The GitHub store delegates **late-bound** to the substrate functions the CLI tests monkeypatch:
  behaviorally equivalent, not byte-identical — "The equivalence lock".
- `save_node_plan → ObjectiveRef | None` is the whole unification capability; `None` is
  unambiguous because a unifying store **raises** on a missing node — "Node↔plan unification".
- Replan is supersede (close-old/create-new, fresh `run_id`, bidirectional lineage), never an
  upsert; its fail-open close composes from primitives, not public store methods — "Objective
  replan is supersede".
- Scripted node-linked saves mint a fresh run id per node — "The same-run-id upsert trap".
- `find_open_objective_by_origin` never silently under-scans; the dormant store **raises** instead
  of joining the `→ None` family — "The origin lookup".
- Manifest authority depends on the operation; split node-creation from edge-creation; re-diagnose
  after every repair write — "The manifest + drift engine".

## The tier's shape

- **Contract:** `perk/backends/objective_store.py` — the `Protocol` (its class body is the method
  census; this doc restates no count), the frozen results, `ObjectiveStoreError` with its typed
  subclasses, and `ensure_stacked_tail_append`, the one guard every store's `add_objective_node`
  runs against its OWN fresh read (§8.66). Imports stay implementation-free: no concrete backend.
- **Three stores.** `perk/backends/github/objective_store.py::GitHubObjectiveStore`;
  `perk/backends/linear/project_store.py::LinearProjectObjectiveStore` (the resolver's Linear
  arm); and `perk/backends/linear/objectives.py::LinearObjectiveStore` — **dormant**: never
  resolver-wired, directly constructable, unit-tested, still on inline header blocks. The naming
  hazard is live: issue-backed `LinearObjectiveStore` ≠ project-backed
  `LinearProjectObjectiveStore`.
- **One selection.** `perk/backends/resolve.py::resolve_objective_store_id` re-exports
  `resolve_issue_backend_id` — an objective and its plan/learn issues share ONE tracker; there is
  **no `[objectives]` table**, and project-vs-issue is not selectable (it is what `linear` means
  for objectives).
- **`backend_id` is a class-level literal on every store**, never imported from the resolver:
  the resolver owns `GITHUB_BACKEND_ID`/`LINEAR_BACKEND_ID` and imports the store modules, so a
  back-import cycles. Shape: contract ← stores (each imports the contract) ← resolver.
- **Error translation is a context manager, not a rewrite of every raise** —
  `github/objective_store.py::_translate` (`GitHubError`) and
  `linear/_helpers.py::_translate_objective` (`IssueBackendError`, which `LinearGraphQLError`
  subclasses). **`ObjectiveStoreError` is NOT a subclass of `IssueBackendError`** (both derive
  from `Exception`): a nested self-call's converted error passes an outer CM untouched (no
  double-wrap), and `except IssueBackendError` never catches a public store method's raise — the
  replan trap below.

## Growing the Protocol: every store plus the fake, in one change

- **Static conformance is one protocol-annotated binding per implementer** (the issue tier's
  recipe, `issue-backend.md` § "Protocol-module shape"):
  `tests/test_github_objective_store.py::_make_store`,
  `tests/test_linear_project_store.py::_make_project_store`, `tests/_linear_fakes.py::_make_store`
  (dormant store), and `tests/test_objective_store.py::_make_store` binding `_FakeObjectiveStore`,
  the minimal in-memory **structural conformer**. A new member lands in all three stores AND the
  fake; the per-method delegation tests never catch a missing member — only **whole-repo**
  `uv run ty check` does (what `just ci` runs), because the fake lives under `tests/` and
  `ty check perk/` alone stays green on a stale fake.
- **The `→ None`/`→ False`/empty-result no-op family** (`save_node_plan`, `post_status_update`,
  the adopt/supersede/gist-source capabilities, the drift pair, `EMPTY_NODE_ENGAGEMENT`): a no-op
  return lets every call site invoke the method **unconditionally** — no
  `if backend_id == "linear"` branch. Isolate each fail-open call
  (`perk/delivery/finalize.py::_post_landed_update`) so a failure cannot discard an
  already-marked node set. The one deliberate exception is the origin lookup below.
- **A defaulted-`None` keyword param needs a non-default forwarding case per adapter per arm.**
  CLI-seam fakes plus `None`-only delegation tests leave a real adapter free to hard-code or drop
  the value; supersede composes the successor header on its own path, so it is its own arm (the
  `delivery`/`delivery_lineage` pair is the shipped instance).
- **An id-normalization fix at an adapter boundary covers every method on that boundary.**
  Normalizing canonical `#<n>` ids in the GitHub store's `_number` while `journal_carrier_id`
  re-emitted the caller's spelling broke the production succession fold end to end (today it
  returns the normalized id). Enumerate every method that accepts or emits the vocabulary, and
  regress end to end over the production adapters — a store must accept its own writer's form.
- **Re-render vs materialize.** GitHub and the dormant store re-render the `objective-roadmap`
  block on `add_objective_node`; the project store materializes a node-issue instead, so its
  `comment_updated` is always `False` (`linear-backend.md` § "`add_objective_node` project-store
  flow").

## The equivalence lock = late-bound delegation

`GitHubObjectiveStore` resolves every delegate by attribute access on the substrate module object
(`perk.backends.github.objectives` / `.plans`) **at call time**, so CLI/integration tests that
`monkeypatch.setattr(<module>, ...)` keep intercepting unchanged, even a patch applied after
construction (`tests/test_github_objective_store.py::TestLateBinding`) — the precise meaning of
**behaviorally equivalent, not byte-identical**. `close_objective` delegates straight to
`plans.close_issue` (a GitHub objective IS an issue), so tests patching the issue close pass
**transparently via delegation**; proving "via the store" needs an injected fake store.

The resolver is the only door: `tests/test_resolve.py::TestConsumerBoundary` scans every
production module under `perk/` outside `perk/backends/github/` for the substrate imports
(`SUBSTRATE_MODULES` + `SUBSTRATE_FROM_IMPORT`); the whole GitHub backend package is the allowed
set, so that direct `close_issue` needs no allowlist entry. A textual backstop with live anchors,
not a completeness proof (`source-scan-guards.md`).

## Node↔plan unification is one `ObjectiveRef | None` capability

On the objective-linked `plan-save` path a **unifying** store (the project store) writes the plan
INTO the node-issue and returns its ref; a **non-unifying** store (GitHub, dormant Linear) returns
`None` unconditionally. No capability flag — the protocol is sound because:

- **`None` is unambiguous only because a unifying store RAISES on not-found**
  (`project_store.py::save_node_plan`: a `_find_node_issue` miss raises), never `None`.
- **`dry_run` also returns `None`** (resolving the node-issue is a network read; `--dry-run` is
  offline), so the caller falls back to the offline compose preview; the guard in
  `perk/cli/commands/plan/save_cmd.py` unifies only when `not dry_run and objective_id and
  node_id`, leaving the standalone create branch byte-unchanged.
- **Derive the land-time backlink self-referentially.** The node's `pr` is the node-issue's OWN
  identifier (`canonical_pr(identifier)` when a `plan-header` attachment is present), never the
  header's `pr` field — `pr submit` overwrites that with the PR number and would break the land
  match. In a unified model never read a field a later stage clobbers.
- **Visible side effect:** the squash title is the plan issue's title
  (`perk/delivery/landing.py::squash_commit_message`) — here the node-issue's `"1.1: …"` roadmap
  title, not the plan H1.

## Objective replan is supersede, not upsert

`perk objective replan` (§8.32) hinges on a store-shape fact: `create_objective` is
**find-then-return idempotent** on `run_id` (`existed=True`, no rewrite) — there is no in-place
objective-rewrite primitive, so objective-replan cannot mirror plan-replan's `run_id`-keyed upsert.
`supersede_objective` is close-old/create-new with a **fresh `run_id`**, **bidirectional lineage**
(`supersedes` on the new header, `superseded_by` on the old), **create-new-first, close-old-last,
fail-open on the close**; `finalize_supersession` is the extracted raising, idempotent close side
(§8.53's deferred-close arm). Carried nodes are MOVE where adopted nodes are STAMP — the same
`adopt_issue` field read per context (`in-place-adoption.md`). When a store op "isn't an upsert",
reach for close-old/create-new rather than inventing an in-place rewrite.

- **Fail-open close composes from `IssueBackendError`-raising primitives, never public store
  methods.** `project_store.py::_close_superseded_objective` wraps the shared private
  `_finalize_supersession` in `except IssueBackendError`; the public methods
  (`update_objective_header`/`close_objective`/`post_status_update`/`finalize_supersession`) each
  open their own `_translate_objective()` and raise `ObjectiveStoreError`, which that `except`
  would NOT catch — so the close-old work calls `_projects`/`_issue_ops` primitives directly. One
  implementation, two postures; watch the error-type boundary whenever fail-open bookkeeping is
  composed out of would-be-public methods.
- **Create-only header fields are enforced by allowlist omission, and a guarded population must
  be closed under replan.** `origin` is excluded from `objective.OBJECTIVE_HEADER_FIELDS`, so the
  header-update LBYL rejects any post-create merge; and because supersede is create-new both live
  stores auto-carry the validated predecessor `origin` — otherwise the guard's population silently
  loses members across replans.

## The same-run-id upsert trap (scripted node-linked saves)

The flip side of `plan_save` being a `run_id`-keyed upsert: saving several node-linked plans under
the ambient workflow run id invokes the same-run idempotent upsert — the second save rewrote the
previous node's plan **in place** (two roadmap nodes pointing at one plan) while the command
*succeeded*; `issue.existed: true` in the payload is the tell. `plan save` now refuses a
node-linked same-run-id upsert whose stored header names a *different* node (`error_type:
node_conflict`, fail-closed before any mutation), but the guard is a backstop — **mint a fresh run
id per node**.

## The origin lookup is exhaustive-or-raise

`find_open_objective_by_origin(origin, exclude_run_id=None)` never silently under-scans (§8.24):
infra failure raises; a present-but-malformed header raises; an off-vocabulary origin raises via
the closed `ObjectiveOrigin` `StrEnum` (`perk/objective/_models.py`) and the fail-closed
`origin_value` classifier (`perk/objective/parse.py`); only an absent/different origin is a skip.
The **dormant store RAISES** — a deliberate break from the `→ None` family, because `None` would
falsely assert authoritatively-none and open a fail-closed guard. `exclude_run_id` makes a
single-ref API sound for a save-time re-check: the pre-launch guard
(`perk/cli/commands/learn/dream_cmd.py`) passes `None`; the save-time re-check
(`perk/cli/commands/objective/create_cmd.py`) excludes its own run, so any returned ref IS a
conflict.

## The manifest + drift engine — durable traps

The project store persists an `objective-manifest` (structural identity, never `status`/`pr`)
and diffs it against observed Linear state in the pure offline engine
`perk/objective/drift.py::detect_drift`; GitHub and the dormant store have no divergence surface
(no-op family). §8.24 owns the code catalog, repair order and sync points; §8.54 the two-part
doctor. The traps:

- **Authority depends on the operation.** On add-node the **manifest** owns an existing phase's
  milestone name (overview prose only seeds a brand-new phase); on reconcile the **overview**
  owns the pins, *including* reverting to the `Phase N` default when a header is removed — a
  first attempt guarded that default-clobber, wrongly.
- **Split node-creation from edge-creation.** Detection only diffs an edge between two observed
  nodes, so the recreate path owns every edge touching a recreated node in BOTH directions:
  create all missing node-issues first, then one sweep driven off the full manifest (skipping
  observed↔observed edges the explicit dependency repair owns; loud on an unresolvable endpoint).
- **The doctor is a state machine, not a flat report.** It resolves a superseded id to the one
  active objective once (`redirected_from`; the predecessor is never mutated), repairs manifest
  before train, and **re-diagnoses after writes** — the report is post-write state, never a
  patched pre-repair snapshot.

## Reads with a stub: engagement, refinement, the dream companion

- **Engagement reads:** GitHub reuses the issue-tier honest reads + shared mappers from its own
  backend package; per-node engagement is honest only on the project store — GitHub and the
  dormant store return `EMPTY_NODE_ENGAGEMENT`. **A deferral comment names its consumer:** the
  named node's plan consumes the stub (flip it, update the comment), never adds a parallel
  surface. Subsystem: `human-engagement-reads.md`.
- **`read_node_refinement_targets` is the whole support+read surface** (§8.67): no capability
  flag, no dummy-node probe; `None` = missing/non-perk objective, **empty targets = a supported
  objective with no nodes**, no node-status eligibility on the read. Only the **dormant** store
  raises `RefinementTargetReadError("unsupported_backend")`, before any network call — GitHub
  reads every node off the objective issue's header + roadmap block. The service
  (`perk/objective/refinement/service.py`) maps typed store errors onto `RefinementError` codes
  through a fixed table, never by message-matching.
- **The dream companion** rides marker-keyed comments on `journal_carrier_id` (GitHub = the
  objective issue; Linear = the metadata sentinel's identifier); core `perk/learn/dream_companion.py`;
  convergent ordering (`dream_report` header ref recorded LAST) §8.64 +
  `perk/cli/commands/objective/create_cmd.py::_converge_dream_companion`.

## History (dated)

- Carved off `IssueBackend` in two nodes — a dormant contract module (Protocol + frozen results +
  fresh error type), then one atomic PR for removal + extraction + resolver + consumer rewire
  (removal and rewire are inseparable under ty), mirroring `issue-backend.md`.
- The Linear extraction rode the registered-collaborator refactor (`linear-backend.md` § "The
  substrate-home principle"); its ~68 facade rewrites used a word-boundary `re.sub` over an
  **explicit** helper name set — never a blanket `self._*` replace.
- `close_objective` (#595) removed the issue-tier close leak; `supersede_objective` (#855),
  `finalize_supersession` (§8.53), `read_node_refinement_targets` (§8.67) and the origin lookup
  (#2004) each grew the Protocol — CI's whole-repo `ty check` caught a stale `_FakeObjectiveStore`
  that `ty check perk/` missed (#626).
- Before attachment-native metadata (#1355) the unified plan-header was an inline-code block in
  the node-issue description; refinement reads once raised `unsupported_backend` on GitHub too.
- No repo record proves the Linear carried-node MOVE path (`supersede_objective` `carry_map`) live
  — offline `FakeLinearWorkspace` coverage only (#855; re-verified absent at this recast).

## Cross-references

- `shared/contracts.md` §8.24, §8.32/§8.53, §8.54, §8.64, §8.66, §8.67
- `docs/learned/workflow/issue-backend.md` — the parallel issue-tier split, the conformance recipe
- `docs/learned/workflow/linear-backend.md` — Linear materialization, attachments, manifest-drift
- `docs/learned/workflow/human-engagement-reads.md` — the engagement read contract
- `docs/learned/workflow/in-place-adoption.md` — adoption Protocol growth, STAMP vs MOVE
- `docs/learned/workflow/broad-catch-narrowing.md` — the typed-catch posture
