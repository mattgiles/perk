# Gate record: objective-node refinement — Linear persistence (offline)

**Status:** validation record (the archive's gate/evidence genre) for the objective
*Refine future objective nodes in advance* — its first roadmap slice, the Linear refinement
persistence layer (contracts.md §8.67): domain types + wire format, the one objective-store read
(`read_node_refinement_targets`), the guarded shared marked-comment upsert, the backend-neutral
service (`read` / `select` / `save`), plan/refinement coexistence, and the offline persistence
gate.

**What this record proves and what it does not.** Every observation below is **fake-proven**:
the real `LinearProjectObjectiveStore`, the real `LinearIssueBackend`, the real
`perk.objective.refinement.service`, and the real config/resolver path run over the in-memory
`FakeLinearWorkspace` (`tests/_linear_fakes.py`), which fakes the external GraphQL transport
only — it executes mutations against state, paginates with a two-item page so every cursor loop
runs on real data, and injects faults/races through deterministic `before_request` /
`after_request` hooks (never sleeps). **No authenticated Linear workspace was touched.** The
selection this slice adds (`_LinearProjectOps.project_issues_for_refinement`, requesting the
attachment connection's `pageInfo { hasNextPage }`) is flagged live-unproven in source like its
sibling queries. Authenticated refine-to-plan evidence — a real project, real node-issues, a
real refinement read back by a planning session — belongs to the later planning-consumption
slice's controlled Linear gate and is **not claimed here**.

## Executed (offline)

Executed in the implementation worktree against the branch under test:

- **Worktree:** `.worktrees/plan-2252`
- **Tested commit:** `120c38548627d2943609838f7a47caf19b3b5143` (the implementation +
  suites; this record's commit follows it)

The named gate (one ordinary pytest case, parameterized over the incremental and stacked
objective headers):

```
$ uv run pytest "tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence" -v -n0
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[incremental] PASSED
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[stacked] PASSED
============================== 2 passed in 0.64s ===============================
```

The two refinement suites together:

```
$ uv run pytest tests/test_linear_refinement.py tests/test_objective_refinement.py -q
120 passed in 1.20s
```

Whole-repo `uv run ty check` (the conformance oracle over every store/backend fake) and the
full `run_ci` gate were green at submission.

**Re-run after review** (commit `a78212ef1aee4519e558c18111e126505b1f067d` — the address pass
that unified family ownership between the plan-exclusion predicate and discovery, moved
attachment ownership ahead of any envelope decode, made the scalar checks whole-string, escaped
`<` in the wire header so quoted perk markers survive the transcoder, and made the duplicate
set independent of repeated-marker defects):

```
$ uv run pytest "tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence" -v -n0
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[incremental] PASSED
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[stacked] PASSED
============================== 2 passed in 0.61s ===============================
$ uv run pytest tests/test_linear_refinement.py tests/test_objective_refinement.py -q
141 passed in 1.22s
```

## What the gate case does (`test_phase1_gate_linear_refinement_persistence`)

1. **A real temp checkout** (`git init` + one commit + `.perk/config.toml` selecting
   `backend = "linear"`), and the **actual resolvers**: `resolve_objective_store(root)` →
   `LinearProjectObjectiveStore`, `resolve_issue_backend(root)` → `LinearIssueBackend`, with
   `client_from_env` late-bound to ONE `FakeLinearWorkspace`.
2. **An objective with an unfinished predecessor and a blocked future node**, created through
   the real store: node `1.1` claimed (`planning`) + a real plan saved into it + `in_progress`;
   `2.1` (explicit `depends_on: [1.10]`) set `blocked`; the concise roadmap
   (`get_objective`), the sentinel's `objective-manifest` attachment, and every non-comment
   surface (issues minus comments, attachments, relations, milestones, projects, labels) are
   snapshotted before any refinement work.
3. **The actual temp-checkout code basis**: `git.resolve_commit(root, "HEAD")` (full 40-hex),
   `git.is_dirty(root)` after dirtying the tree (recorded `dirty=True`, never refused),
   `plan.now_iso()` for both timestamps.
4. **Select → save → read → replace → retry**: default selection skips the ineligible
   predecessor and picks `1.2` (the first eligible absence; the blocked `2.1` is explicitly
   selectable — readiness is ignored); a long refinement (>1,500 chars — beyond the
   engagement-preview bound — with code fences, pipes, Unicode, trailing newlines, and a
   complete inline-code plan-body example) saves as one `commentCreate` on the node-issue and
   reads back with the full Markdown + provenance; the replacement (shorter Markdown, the
   read's expectation) is one `commentUpdate` on the **same comment id** with the old tail gone
   and provenance preserved verbatim; an explicit retry of the same request returns the same
   verified comment with **no mutation**.
5. **Zero non-comment effects**: the roadmap, manifest attachment, and the whole non-comment
   snapshot are byte-equal before/after; the sentinel (the journal carrier) gained no comment;
   refinement's mutation log is exactly `["commentCreate", "commentUpdate"]`.
6. **Then the real plan**: `1.2` is claimed and a real plan is saved into it (its own expected
   `attachmentCreate` metadata writes, separated from refinement's log); the historical
   refinement read still returns the identical record while the target now reads
   `has_plan_metadata=True` / ineligible; a new refinement save refuses `node_ineligible` with
   no mutation; `get_plan_body` returns the real plan, never the refinement. The stacked arm
   asserts the `delivery: stacked` header rode through and that no delivery operation ran.

## The surrounding matrix (same suites, same fake)

- **Codec goldens + refusals** (`tests/test_objective_refinement.py`): the exact envelope
  bytes, the pinned identity JSON / target key / source digest, canonical-timestamp and SHA
  refusals (fractional seconds, offsets, lenient widths, invalid calendar dates, uppercase,
  prefixes, wrong lengths), every missing/omitted header field, unknown schema, digest and
  key↔identity mismatches, repeated/misplaced markers, unknown-keys-ignored, dual encodings,
  neighboring node identities (`1.1`/`1.2`/`1.10`), foreign/historical records ignored,
  duplicate-target ambiguity deciding BEFORE payload parse, and every row of the service's
  error-mapping table with `comment_ids` / `write_attempted` pass-through.
- **The store read** (`tests/test_linear_refinement.py::TestSnapshotRead`): all statuses in
  natural order, identity/source/eligibility fields, observed vs effective dependencies,
  plan-header presence with a corrupt payload and with duplicates, native cancellation →
  `skipped`, missing / non-perk / empty objectives, every duplicate-identity `ambiguous_target`
  arm, every `malformed_target` arm (corrupt node payload, bad status, missing id, a perk-owned
  envelope whose `kind` is missing / blank / `null` / numeric / an object / a list, missing
  header run id, `hasNextPage: true`, a missing or non-boolean completeness field — with a
  focused structural check that the read requests the signal and the ordinary projection read
  does not), foreign cards with arbitrary `kind`/`source` types never breaking the read,
  transport failures staying plain `ObjectiveStoreError`, and the GitHub / dormant-Linear
  stores refusing `unsupported_backend` with zero requests.
- **The guarded upsert** (`TestGuardedUpsert`): first save / shorter replacement / no-write
  convergence, stale expectations (present-vs-absent, wrong digest, vanished comment),
  duplicates and misplaced/repeated markers across a later page, dry run and input validation
  with no network, the ordinary path unchanged (`verified_comment=None`), GitHub's guarded
  refusal before any operation, mutation-landed-then-raised → success, a native size error with
  proven absence → `backend_error` keeping the diagnostic and the FULL body in the single
  attempt, unreadable verification → `write_unverified`, server alteration → `stale_comment`,
  nominal success with an unchanged/absent baseline → `write_unverified`, concurrent first
  saves → `ambiguous_comment` (both records kept; retries keep refusing), and the documented
  writer-after-final-verification residual.
- **Coexistence** (`TestServiceOverLinear`): a refinement embedding a complete plan-body
  example (also with a damaged header) is never read or overwritten as the plan across
  `save_node_plan`, `get_plan_body`, `update_plan_issue`, and `adopt_issue_as_plan`; a real
  plan with later marker discussion stays the plan; reads survive `done`/`skipped`/native
  cancellation while authoring refuses; planning after the final eligibility check leaves an
  inert late refinement (no rollback, no plan update); fidelity equals the shared Linear
  rendering (perk HTML markers inside the Markdown transcode like every other comment).

## Deferred (explicitly, to later slices)

Public authoring/review doors (`perk objective refine`, `/objective-refine`), planning-seed
consumption of refinements, the authenticated Linear refine-to-plan gate, and the GitHub carrier
(`GitHubIssueBackend.upsert_marked_comment` with `expected` and
`GitHubObjectiveStore.read_node_refinement_targets` both raise `unsupported_backend` until
then).
