---
title: Objective delivery — the Delivery façade, migration slices, journals, trains, sync, recovery, and landing
read_when: You are changing the Delivery façade or adapters/fakes, migrating a delivery operation, reading trains, syncing/recovering/landing stacks, or editing delivery contracts.
cluster: objective-system
---

# Objective delivery — the façade, train journal, and stacked-roadmap mechanics

`shared/contracts.md` §8.42–§8.56 and §8.66 are the normative statements of stacked delivery
(policy, journal, train projection, handoff gate, publish, sync, recovery, transfer,
cancellation, landing, the ready continuation). This doc carries only the cross-cutting *why*,
the traps the naive shapes hide, the test design that catches them, and the dated proof bounds.

## Distillation

- `Delivery` from `resolve_delivery(repo_root)` is the one operation boundary — "The seam map".
- Appends are read-back-verified (ambiguous rescan = no retry, complete-carrier scan, lineage is
  not identity); a shared carrier gets ONE positional dispatcher — "Journal append discipline".
- Detect cycles during expansion, memoize the contraction — "Graph contraction".
- Non-identity fake ids, an injected raise is not process death — "Durability test design".
- Every positive classification arm (train, landing readiness) needs POSITIVE evidence; the
  wiring leaf needs its own test lane; argv-level pins for probes — "The train read path".
- Nominal outside/structural inside, complete-or-nothing lazy resolution proved zero-I/O,
  explicit consent, exact export cuts + delegate tests, named-excess ledger — "Façade-slice
  migration pattern".
- Mutation-adjacent reads fail closed, negative assertions + stateful fakes, fetch before
  ancestry checks, live `ls-remote` for the base — "Publish and sync".
- A published helper re-verifies over the whole domain; "ungated by construction" is pinned at
  the real routing boundary — "Handoff gate and ready continuation".
- Producer widenings meet the consumer's firing gate; a removed gate condition transfers its
  burden; `STRUCTURAL_BLOCKER_CODES` is cross-consumer; read specs name the failed AND the
  missing arm — "Recovery, cancellation, transfer, and layer identity".
- "Proof bounds and history (dated)" — open bounds plus the 2026-08-13 live-gate outcomes.

## The seam map

`perk/delivery/facade.py::Delivery`, obtained from `perk/delivery/observe.py::resolve_delivery`
(assignment-only, no I/O), is the canonical repository-scoped operation boundary: callers invoke
`status`/`prepare`/`transfer`/`publish`/`sync`/`recover`/`land` instead of composing persistence,
probes, gateways, and engines. The outside contracts are nominal aggregate ABCs; the production
adapters in `observe.py` and the owned test doubles in `perk/delivery/_fakes.py` evolve together.
The modules behind the façade stay important seams (each docstring names its ownership), never a
caller's entry point.

The reconstruction-era compatibility chain (`TrainReads`, `resolve_train_reads`,
`reconstruct_repo_train`, `resolve_transfer_seams`) is **deleted**: the façade binds its own
status path (`Delivery._reconstruct_train_status`) into the transfer/recover/land engines, and
reconstruction survives only as the package-internal `perk/delivery/train.py::reconstruct_train`.
`tests/test_delivery_facade.py::_RETIRED_EXPORTS` pins the retirement (disjointness + exact
export equality). A behavior change amends §8.43, never bypasses the façade.

## Journal append discipline — the three holes and the shared carrier

§8.43 "Append discipline" is law; the *why* is that the naive "rescan → one retry → typed error"
shape hides three review-caught holes (`perk/delivery/persistence.py::TrainPersistence` is the
two-POST core shared by operation events and ready stamps):

1. **A failed rescan is itself ambiguous** — a read-back that raises proves neither presence nor
   absence and converts to the typed ambiguous error with **no retry**; only a rescan that
   *proved absence* earns the one bounded retry.
2. **Read-back is a complete carrier scan** — a first-match return misses a *conflicting*
   duplicate later in the scan from a concurrent writer.
3. **Lineage equality is not an identity gate** — predecessor and successor objectives *share* a
   `delivery_lineage`, so the append cross-checks the record's `objective_id` separately.

Adding a SECOND grammar (the ready stamp) to the journal's shared carrier taught:

- **Whole-body substring detection is safe only on carriers perk *solely* owns.** The objective
  carrier also holds mutable human prose, so it needs ONE routing dispatcher over EVERY scan path
  that recognizes a record only when the marker sits on the body's **first nonblank line**
  (`perk/delivery/journal.py::parse_carrier_comment`). Accepted trade: prose PREPENDED to a real
  event makes it *unrecognized*, not corruption — equivalent to out-of-band deletion — while the
  fail-safe directions hold (orphaned outcomes fold as corruption, a vanished stamp degrades
  toward `unstamped`/`stale`, never falsely ready). Pinned by `tests/test_delivery_journal.py` +
  `tests/test_delivery_persistence.py`, whose fake's `edited_at` seed is load-bearing.
- **Marker-embedded values take allowlists derived from the encoding's delimiters**
  (`[A-Za-z0-9._-]+` — the HTML-comment `-->` is exactly the miss a denylist makes); narrowing is a
  contracts-typed refusal, never a silent skip (node ids outside the allowlist can never stamp).
- **Exact-shape validators on serialized output use `re.fullmatch`** — a `$` anchor admits a
  trailing newline that can POST before read-back catches it.
- **The disciplines are reusable**: dual-encoding markers, complete-scan read-back, and
  rescan-one-retry ambiguity are instantiated twice — the journal and
  `perk/learn/dream_companion.py::persist_parts` (dual-candidate byte identity there, canonical
  payload equality here).
- **Cross-backend byte identity is proven by round-tripping a rendered body through the real
  `to_linear_markdown`** (the transcoder rewrites only the marker); engagement exclusion needed
  zero new code — the generic `perk:*` sentinel classifier already drops journal comments.

## Graph contraction over a filtered node set

- **Cycles among filtered-out nodes vanish under edge contraction** — a cycle entirely among
  `SKIPPED` nodes collapses to an empty dep set the Kahn pass never sees. Detect cycles **during
  expansion**; keep validate-first symmetry (`perk/objective/graph.py::validate_stacked_roadmap`
  reports what `delivery_order` raises).
- **Memoize inside contract-valid bounds** — the bound is on nodes, not paths; a shared skipped
  subgraph goes exponential unmemoized (fibonacci-shaped pin in
  `tests/test_objective.py::test_delivery_order_shared_skipped_subgraph_is_not_exponential`).

## Durability test design

- **Identity-valued fakes hide routing bugs** — with `carrier_id == objective_id` defaults a
  predecessor-routing test passes when the adapter posts to the objective id (the distinction that
  matters on Linear Projects, where the sentinel issue ≠ the objective); use non-identity ids.
- **An injected raise is not process death** — Python still runs `finally` blocks, so cleanup
  erases the residue a kill leaves; model death by constructing the post-crash durable state and
  rerunning the public recovery surface.

## The train read path

The canonical read is `resolve_delivery(repo_root).status(...)`: the façade owns wiring and
delegates projection to the pure core (`train.py`); `perk/github/stacks.py` is the wire adapter
and `observe.py` the production conversion leaf (§8.44 owns axes, findings, corroboration).

- **Fail-open classification arms are the recurring trap in projection pipelines.** Every
  *positive* arm needs POSITIVE evidence; absence or an unknown probe (`None`, a half checkpoint
  pair, an unavailable membership read) **degrades the classification** even when the probe
  failure itself stays an information finding — audit each positive arm for "what if this input
  is absent/None" before review does (four independent findings shared that shape). Landing
  readiness (§8.55) follows the same rule: the train is the authority, blockers and membership
  are never re-derived, every enrichment read failure maps to a *specific* fail-closed blocker.
- **A deliberately split design leaves the wiring leaf with zero coverage by default** —
  `observe.py` was executed by nothing until review caught it. The wiring leaf needs its **own
  test lane** (`tests/test_delivery_observe.py`: real repo + bare remote for the git arms).
- **The stable/preview GraphQL query split.** `perk/github/stacks.py::pr_stack` reads the
  public-preview stack fields in a query separate from the stable PR facts (`pr_delivery_facts`),
  so a preview-schema rejection can never poison the stable read; every *selected* wire field is
  REQUIRED in the lenient parse models, so a partial payload degrades (`available=False`) or raises
  instead of defaulting into a fake observation (`docs/learned/workflow/pydantic-boundary-models.md`).
- **Argv-level pins are the contract test for "this exact flag set IS the contract"** — the
  bare-remote integration test of the atomic-push probe stays green if `--atomic` or `--dry-run`
  is dropped (a no-op probe becomes a false positive or a real push), so
  `tests/test_git.py::test_probe_atomic_push_pins_the_exact_no_op_command` pins the complete argv
  + timeout of `perk/substrate/git.py::probe_atomic_push`.

## Façade-slice migration pattern

Each operation-family migration follows one repeatable cut, never an adapter shim over the old
composition (generic seam-design rules: `docs/learned/pi/extension-seams.md` § "Door→typed-op
extraction craft"; this doc owns the delivery cut and the slice scope/review economics).

- **Nominal outside, structural inside.** Nominal aggregate ABCs at the façade make capability and
  ownership explicit; pure cores depend on narrow structural Protocols; one aggregate authority may
  satisfy several narrow seams directly — an adapter translating it back into the old bundle
  preserves complexity.
- **Resolve lazily, cache only complete success.** `perk/delivery/observe.py::RepoDeliveryPersistence`
  caches the store/backend/persistence tuple only after every member resolves and the backend ids
  agree — a partial cache turns a transient failure into a permanently split authority graph. Call
  authority methods at the point of need so refusals and dry projections are provably zero-I/O,
  and **prove it by monkeypatching every substrate entry point to record or raise** — a fake that
  returns no data cannot show a read was skipped.
- **Bound errors at the façade.** `DeliveryError` refuses codes outside the one wide vocabulary
  (`_DELIVERY_ERROR_TYPES`); `status` alone owns a narrower subset (`_STATUS_ERROR_TYPES`) and
  re-raises out-of-subset reconstruction errors raw; the mutating operations map adapter
  exceptions onto the wide vocabulary (unknown reconstruction code → `github_error`).
- **Consent and blank-input policy are explicit.** Consent on a mutating operation is mandatory
  input, never a default sentinel. The mutating request dataclasses (prepare/publish/sync/recover/
  land) validate nonblank invariants in `__post_init__`, so every CLI boundary normalizes blank
  text to absence or returns typed `invalid_input` *before* construction — one missed caller breaks
  the JSON envelope with a raw constructor error.
- **Pin exports and drive production delegates.** An export cut is an exact-list contract — assert
  the added, removed, and retained sets (a broad import smoke test cannot prove a retired seam
  disappeared). Every ABC addition gets a production-adapter delegation test and one public-path
  test stays on the real default runtime; when tests swap the runtime, patch the module symbol the
  public path resolves and retain the real-default lane.

### Slice scope + review economics (the door→typed-op train)

- **Typed-seam introduction lands net-positive** (+150–250 LOC per slice; the wire-identical
  details rebuild is the chronically underestimated item). Acceptance is a **named-excess ledger**
  with operator PR approval as the recorded gesture; review-mandated hardening inside named
  invariant classes rides outside the size bar.
- **Zero-policy seams die at review**: a pure passthrough typed op is a plan-time smell; a
  transition step with no decision content is padding; plan-mandated defensive machinery still
  faces the YAGNI bar. **The counterpart**: seam-proving slices legitimately decline YAGNI findings
  when the structure IS the deliverable — pre-arm the decline in the plan.

## Publish and sync — posture traps the contracts don't state

§8.47 (publish) and §8.49 (sync) are normative; the review findings on the decision-complete
publish slice were all *posture* traps:

- **Mutation-adjacent authority reads fail closed — convenience defaults are fail-open traps.** A
  JSON-read default of `[]` turned a failed stack-membership read into "not in a stack", which
  could trigger a spurious create-stack mutation; only a literal empty payload means absence.
  Same class: merged-at is required-but-nullable (omission is wire drift). Audit every defaulted
  JSON read near a mutation.
- **Happy-path write-ordering assertions don't pin no-persist-before-verification** — fail-closed
  paths need *negative* assertions (`tests/test_delivery_publish.py::assert_nothing_persisted`);
  crash-window resume tests need *stateful* fakes whose reconstruction reflects prior writes
  (fail-once after each write, rerun, same operation completes, no duplicate mutation).
- **Two ancestry traps** (sync): fetch recorded checkpoint objects *before* the ancestry check (a
  missing object looks like divergence), and validate the stored parent edge for *every* claimed
  source including unchanged layers (a corrupt unchanged checkpoint becomes a rebase upstream).
- **Base advancement needs a live `ls-remote` read, never the fetched remote-tracking ref** —
  plain `git fetch` has no `--prune`, so a deleted remote base still resolves locally. Status
  degrades tolerantly (`base_unobserved` INFO); the mutator's `--base` fails closed. The
  checkpoint-claimed mutation universe (never `published_prefix_len`) is §8.49's.

## Handoff gate and ready continuation (§8.46 / §8.66)

- **Publishing a private helper makes its documented contract load-bearing** — re-verify it over
  the WHOLE input domain, not the slice its old callers reached (the skipped-only-cycle hole
  surfaced this way and its fix hardened `delivery_order` too).
- **"Structurally ungated by construction" is pinned only at the real routing boundary** — drive
  `Delivery.publish` with a layer request through the one route both `/submit` and the address
  finalize reach, forcing the handoff axis into its blocking states
  (`tests/test_delivery_publish.py::test_publication_never_reads_the_predecessor_handoff`
  parametrizes `UNSTAMPED` and `STALE`). Record ordering is §8.43's; dry-run honesty §8.46's.

## Recovery, cancellation, transfer, and layer identity

- **`STRUCTURAL_BLOCKER_CODES` is a cross-consumer contract, not a doctor list**
  (`perk/delivery/train.py::STRUCTURAL_BLOCKER_CODES`, consumed by sync, layer, transfer, recover,
  and the stacked-selection seam) — growing it changes every gate; re-check each consumer.
  Cancellation contraction and race-aware repair are §8.54's; the repair's post-write reread is
  an effect-boundary call writer fakes must model.
- **A delivery-plane artifact needed by both train and landing gets its own neutral module**
  (`perk/delivery/land_records.py::join_completed_land_operations`, §8.56), and a pure module
  that observation wiring imports is placed after tracing the import chain — the remote-writer
  seam is the dependency-leaf `writers.py` because `land → sync → observe → land` would cycle.
- **A producer widening must meet the consumer's firing gate.** Recover's close-then-evidence
  repair truthfully returns `objective_closed: false` when re-emitting evidence for an already
  closed objective, so the TypeScript consumer gates on evidence presence, never the close flag
  (`extension/delivery/stackReconcile.ts::decideStackReconcile` decides;
  `extension/pi/v1/delivery/stackDrive.ts::driveStackReconcile` drives the minted evidence).
- **Removing one condition transfers its safety burden.** Once the drive stopped requiring
  `objective_closed`, "a failed aggregate close emits no evidence" became safety-critical (the
  compound gate had guarded it twice) —
  `tests/test_delivery_recover.py::test_failed_aggregate_close_never_emits_evidence` pins it. When
  a compound gate loses a condition, enumerate every path it suppressed and prove the survivor
  still suppresses each.
- **Repair re-emission is at-least-once** (`perk/delivery/recover.py::_converge_finalization`),
  safe only because objective reconcile is idempotent — producer frequency and consumer idempotency
  are one load-bearing design.
- **Recovery proves fresh product state in *both* terminal directions, never compares refs**, and
  best-effort cleanup is protocol output — every cleanup failure travels as structured notes
  through every outcome arm (residue lives in the filesystem AND Git's worktree-admin inventory).
- **Never-authoritative revision records pass an immutability shape check, not a resolvability
  check.** The `layer-context.json` reader (`perk/state/cache.py::read_layer_parent_sha`) is
  fail-soft; its consumer (`perk/cli/commands/plan/watch_cmd.py::_resolve_diff_base`) accepts only
  a full 40-hex id resolving to itself — movable refs, abbreviations, and tags *resolve* today but
  silently re-pin later reads.
- **Transfer (§8.53) interruption tests inject fail-once at store-internal write granularity**
  (`tests/test_delivery_transfer_linear.py`), not just between top-level steps.
- **The branch-resolution asymmetry is deliberate** (`perk/delivery/layer.py::derive_layer_context`):
  the *predecessor* branch is observed (stored header else convention); a layer's *own* branch is
  always the canonical `plan-<N>` because both creation paths create exactly that branch.
- **"A failed read fails the save" must name the missing/None arm, not just the exception arm.**
  A store exception was treated as failure while objective-not-found `None` fell through
  fail-soft, defeating fail-before-write (a child layer could branch from the wrong parent).
  Shipped: missing-as-failure (`perk/delivery/facade.py::_prepare_plan_identity` raises
  `objective_not_found`). "Failed" and "missing" read identically in prose; they are different
  code paths.

## Proof bounds and history (dated)

- The machine-local `flock` (`perk/delivery/oplock.py`) serializes sync/recover/land per machine
  only — cross-machine overlap is detected, not prevented. The build-readiness veto set is
  fail-closed and coarse — the refinement lever is attribution (which veto fired), not loosening.
  Linear's comment-size limit is undocumented; the shared journal cap assumes it is ≥ that. The
  live stacked remote-runner arm (`position_branch`'s stacked path) remains deliberately unrun,
  pinned by `tests/test_run_worker.py` + `tests/test_delivery_cross_machine.py`.
- **2026-08-13 — the live stacked-publication gate** (`docs/design/archive/stacked-publication-dogfood.md`):
  stack-create first fires at layer 2 and append at layer 3, so a live proof needs ≥3 layers;
  capability preflight is host-schema evidence only — per-repo enrollment is proven by the first
  stack-create itself; the warm `/submit` envelope and a headless exit-0 are never publication
  evidence (the journal is); a read-back failure after the mutation took effect converges by
  rescan, not re-mutation; cascade-rewritten heads carry a CANCELLED superseded check-run beside
  the SUCCESS run — expect `optional_check_failed` noise in landing dry-runs after a cascade.
- **2026-08-13 — sync and landing live complements** proved atomic multi-ref acceptance and
  merge-async on one host (second-clone recovery, never host-level cross-machine independence);
  branch-protection acceptance, the breach→`sync --base`→`land` route, and retained conflicts stay
  hermetic-only.

## Cross-references

- `shared/contracts.md` §8.42–§8.56, §8.66 — the normative delivery contracts (point, never restate)
- `docs/learned/workflow/objective-store.md` — the three objective stores the adapter aligns with
- `docs/learned/workflow/linear-backend.md` — the Linear transcoder + project-backed store
- `docs/learned/pi/extension-seams.md` § "Door→typed-op extraction craft" — the seam-design half
