---
title: Objective delivery — the Delivery façade, migration slices, journals, trains, sync, recovery, and landing
read_when: You are changing the Delivery façade or adapters/fakes, migrating a delivery operation, reading trains, syncing/recovering/landing stacks, or editing delivery contracts.
cluster: objective-system
---

# Objective delivery — the façade, train journal, and stacked-roadmap mechanics

`shared/contracts.md` **§8.42** (the stored domain contract) and **§8.43** (the operation journal
+ train persistence) are the normative statements — this doc points at them and carries only the
cross-cutting *why*: the traps the naive shapes hide, the test design that catches them, and the
history a future delivery/recovery node should not re-derive.

## Distillation

- §8.42/§8.43 are normative; this doc carries the cross-cutting *why*. Module ownership of
  `src/perk/delivery/` — "The seam map"; `Delivery` from `resolve_delivery(repo_root)` is the
  canonical operation boundary (compat seams deleted, retirement guard-pinned).
- The naive "rescan → one retry → typed error" journal shape hides three append-discipline
  holes — "The three append-discipline holes".
- A second comment grammar on a shared carrier needs ONE routing dispatcher over EVERY scan
  path, delimiter-derived allowlists, and `re.fullmatch` validators — "The ready-stamp grammar
  beside the operation grammar".
- Published helpers re-verify their contract over the whole domain; decode cohorts are
  facts-only; pure record construction precedes the first mutation — "The handoff gate (§8.46)
  and the ready continuation (§8.66)".
- Train reads enter through `Delivery.status` and reconstruct from stored facts plus fresh
  probes — "The train read path (through `Delivery.status`)".
- The stacked `/submit` publish operation has five posture traps — "The stacked `/submit`
  publish operation — five posture traps".
- The sync cascade is transactional: journal-first, ONE atomic leased multi-ref push, bounded
  settle, bottom→top checkpoints — "The transactional sync-cascade invariants".
- Landing readiness composes the train as authority, fail-closed — never re-deriving blockers —
  "Landing readiness (§8.55) — composition rules".
- Interrupted-LAND gotchas: the neutral-module rule, evidence-gated closes, producer/consumer
  firing gates — "Interrupted-LAND recovery (§8.51/§8.56) — gotchas".
- Recovery proves fresh product state in both terminal directions — "Recovery proof is a fresh
  product-state proof, not a ref comparison (§8.51)".
- "Residual proof bounds" is the register of open proof bounds (dated one-liners).
- Façade migrations use narrow internal Protocols, complete-or-nothing laziness, bounded error
  subsets, explicit consent, real-runtime tests, and exact export cuts; typed-seam slices land
  net-positive under a named-excess ledger, and zero-policy passthrough seams are a plan-time
  smell — "Façade-slice migration pattern".

## The seam map

`src/perk/delivery/facade.py` is the canonical repository-scoped operation boundary. Callers obtain
one `Delivery` with `resolve_delivery(repo_root)` and invoke status, prepare, transfer, publish,
sync, recover, or land instead of composing persistence, probes, gateways, and engines themselves.
The outside contracts are nominal aggregate ABCs; their production adapters and the matching owned
test doubles in `src/perk/delivery/_fakes.py` evolve together.

The modules below remain important implementation seams, but they are behind the façade:

- `journal.py` and `persistence.py` own the event grammar, fail-closed fold, backend-aligned
  persistence, and `journal_carrier_id` resolution.
- `objective/graph.py`, `objective/render.py`, and `plan.py` own delivery ordering and stored
  header mechanics.
- `train.py`, `observe.py`, `github/stacks.py`, and `capability.py` own pure train
  classification, production observations, wire probing, and capability checks.
- `sync.py` and `continuation.py` own transactional suffix synchronization and retained
  conflicts; `transfer.py` and `recover.py` own replan transfer and operation conclusion.
- `land.py`, `landing.py`, and `finalize.py` own landing readiness, journaled atomic mutation,
  and final bookkeeping.

The reconstruction-era compatibility chain (`observe.TrainReads`, `observe.resolve_train_reads`,
`observe.reconstruct_repo_train`, `transfer.resolve_transfer_seams`) is **deleted** — the façade
constructs its transfer/recover seams directly in `facade.py` (binding
`_reconstruct_train_status` for roll-forward), and train reconstruction survives only as the
package-internal `train.reconstruct_train` (no out-of-package caller, retired from the export
ledger). The retirement is guard-pinned by `tests/test_delivery_facade.py`'s `_RETIRED_EXPORTS`
disjointness assertion and recorded in `docs/planning/archive/stacked-prs/final-census.md`. New callers
start at `Delivery`. Operation work still depends on §8.43's exact journal semantics — amend the
contract with behavior changes rather than bypassing the façade.

## The three append-discipline holes in the naive "rescan → one retry → typed error" shape

All three were review-caught and are now §8.43 law — don't re-derive them:

1. **A failed rescan is itself ambiguous.** A read-back that *raises* proves neither presence nor
   absence and must convert to the typed ambiguous error with **no retry** — only a rescan that
   *proved absence* earns the one bounded retry. The naive shape lets the raw backend error escape
   and can trigger an unwarranted second POST.
2. **Read-back must be a complete carrier scan.** Returning on the first byte-identical match can
   miss a *conflicting* duplicate later in the scan from a concurrent writer — success is declared
   only after the full scan finds no differing payload under the operation key.
3. **Lineage equality is not an identity gate.** Predecessor and successor objectives deliberately
   *share* a `delivery_lineage`, so the append must separately cross-check the record's
   `objective_id` against the objective being appended to — lineage alone lets an event claim
   preparation on the wrong objective and mislead recovery.

## The ready-stamp grammar beside the operation grammar

What adding a SECOND comment grammar (the ready stamp) to the operation journal's shared
carrier taught (#2021, #1996):

- **One routing dispatcher must cover EVERY scan path.** When a shared carrier gains a second
  comment grammar, a single dispatcher (`parse_carrier_comment`, operation-marker precedence)
  routes all scans — including the OLD grammar's rescans, where the fail-closed property
  silently degrades otherwise (§8.43's symmetric rescan posture).
- **Marker-embedded values take allowlists derived from the encoding's delimiters**
  (`[A-Za-z0-9._-]+` — the HTML-comment `-->` is exactly the miss a denylist makes), with
  vocabulary narrowing recorded as a contracts-typed refusal, never a silent skip. Residual:
  roadmap node ids outside the allowlist can never stamp.
- **Exact-shape validators guarding rendered/serialized output use `re.fullmatch`** — a `$`
  anchor admits a trailing newline that can POST before read-back catches it.
- **Pure-fact deterministic payloads trade away head-cycle recovery.** The A→B→A corner
  re-stamps as `existed=True` and the layer stays stale until a genuinely new head — reviewed
  and deliberately declined (an occurrence field would reintroduce non-reconstructable
  provenance); callers surface the corner rather than silently no-op.
- **The journal's persistence disciplines are a reusable discipline, not journal-specific
  machinery.** Dual-encoding markers, dual-candidate byte-identity, complete-scan, and
  rescan-one-retry ambiguity are now instantiated twice (the operation journal +
  `src/perk/objective/dream_companion.py`).

## Graph contraction over a filtered node set hides cycles among the filtered-out nodes

A dependency cycle lying entirely among `SKIPPED` nodes is silently erased by edge contraction —
the back-edge collapses to an empty dep set, and the downstream Kahn pass never sees skipped
nodes. When transitively contracting edges through excluded nodes (skips, tombstones, collapsed
subgraphs), cycle detection must happen **during expansion** (tri-color / in-progress set),
because the later topological sort only sees survivors. Keep the validate-first symmetry:
`validate_stacked_roadmap` reports the same cycle `delivery_order` raises on.

## Recursive expansion needs memoization inside contract-valid bounds

Unmemoized contraction re-expands a shared skipped subgraph once per incoming path — a
contract-valid ≤100-node roadmap goes exponential (the bound is on **nodes, not paths**; "small
bounded input" does not excuse exponential recursion). The regression test pins a
fibonacci-shaped skipped chain that must complete in normal suite time.

## Durability/routing test design

- **Identity-valued fakes hide routing bugs.** With fake carriers defaulting to
  `carrier_id == objective_id`, a predecessor-routing test passes even when the adapter posts to
  the objective id instead of the resolved carrier — the distinction that matters on Linear
  Projects, where the sentinel issue ≠ the objective. Use **non-identity ids** so the wrong path
  *fails*.
- **Hard-wired-success fakes never exercise durability failure modes.** The read side needs a
  programmable read fake (ok / raise / stale-empty view) plus an interleaved ops log to pin
  rescan-failure, visibility-lag (POST → stale rescan → retry → convergence), and the bounded
  two-POST terminal — the core failure modes of any read-back-verified append.
- **An injected raise is not process death.** Python still runs handlers and `finally` blocks;
  sync cleanup can erase exactly the worktree/ref residue that a kill leaves. Model death by
  constructing the post-crash durable state, then rerun the public recovery surface. A raised
  exception is acceptable for an individual cell only after proving that cell's exception path
  does not mutate the durable state under test.
- **Exercise real capability refusal, not a neighboring server error.** On a bare fixture remote,
  `git config receive.advertiseAtomic false` makes the Git client itself refuse `--atomic` as
  unsupported. A rejecting `pre-receive` hook is policy failure while the server still advertises
  support; it cannot prove the unsupported-capability classification.
- **Cross-machine continuation can stay hermetic.** Use one real bare origin, two independently
  initialized clones, and separate seams backed by one shared stateful fake backend. Continue on
  machine B and assert it never receives a path rooted in machine A's checkout; this proves
  durable routing rather than accidental local-state reuse without requiring live infrastructure.

## Why cross-backend byte-identity works

Idempotency equality is **canonical-serialization equality** (an `OutputModel` dump through
sorted-keys-off YAML), and the Linear transcoder rewrites **only the marker**, never the fenced
payload — proven by round-tripping the rendered body through the real `to_linear_markdown` in
tests. The engagement-exclusion requirement needed **zero new code**: the generic `perk:*`
sentinel classifier already drops journal comments from human-engagement inputs (pinned by tests
only).

## The train read path (through `Delivery.status`)

The canonical read begins at `resolve_delivery(repo_root).status(...)`. The façade's nominal status
authority owns repository and backend wiring, then delegates projection to the pure core in
`src/perk/delivery/train.py`. `src/perk/github/stacks.py` remains the wire adapter and
`src/perk/delivery/observe.py` the production conversion leaf, including the hard-fail versus
tolerant-degrade split. There is no public reconstruction seam: `train.reconstruct_train` is
package-internal (the façade's status path calls it), and the old `TrainReads` bundle is deleted.

### Fail-open classification arms are the recurring trap in projection pipelines

Every *positive* classification arm in `train.py` must require POSITIVE evidence. Four
independent review findings shared one shape: absent (vs. differing) join fields passed
corroboration silently; unknown ancestry (`is_ancestor → None`) fell through to a synced
classification; a *half* checkpoint pair could classify as published; and an unknown
stack-membership probe left the published classification and prefix length intact. The fix
pattern: absence/unknown **degrades the classification** (to drift/UNKNOWN) even when the probe
failure itself stays an information finding, not a blocker. When writing a multi-axis classifier,
audit each positive arm for "what if this input is absent/None" before review does.

### A deliberately split design leaves the wiring leaf with zero coverage by default

`train.py` had Protocol fakes, `stacks.py` had fake-subprocess tests, and the CLI stubbed
reconstruction — so `observe.py` was executed by nothing until review caught it. When a design
deliberately splits pure core / wiring leaf / wire adapter, the wiring leaf needs its **own named
test lane** (`tests/test_delivery_observe.py`: real repo + bare remote for the git arms) — it
never falls out of the neighbors' tests.

### The stable/preview GraphQL query split

`src/perk/github/stacks.py` keeps the public-preview native-stack fields in a **separate query**
from the stable PR facts, so a preview-schema rejection can never poison the stable read. Every
*selected* wire field is REQUIRED in the lenient parse models, so a partial/malformed payload
degrades (`available=False`) or raises a labelled error instead of defaulting into a fake
observation (see `pydantic-boundary-models.md` — a model default on a read whose absence has
semantic weight is a fail-open bug).

### Argv-level pins are the contract test for "this exact flag set IS the contract" commands

The hermetic bare-remote integration test for the atomic-push capability probe stays green if
`--atomic` or `--dry-run` is dropped — turning a no-op probe into a false positive or a real
push. Pin the complete argv + timeout (`src/perk/substrate/git.py` /
`src/perk/delivery/capability.py`); keep the integration test alongside for transport reality.

### Notes for future planners

- The PR head/base corroboration blockers and their ordering before the terminal MERGED/CLOSED
  arms are §8.44's.
- Residual (discharged 2026-08-13): the preview-stack fixture-only bound was discharged live at
  the stacked-publication dogfood gate; the tolerant read (`available=False`) remains the
  designed containment.

## Façade-slice migration pattern

Each operation-family migration follows one repeatable cut rather than wrapping old composition in
an adapter shim.

### Nominal outside, structural inside

Expose nominal aggregate ABCs at the façade so caller capability and ownership are explicit. Keep
pure cores dependent on narrow structural Protocols. One aggregate production authority can satisfy
several narrow internal seams directly; an adapter whose only job is translating the aggregate back
into the old bundle preserves complexity instead of removing it. Test doubles belong to the façade
in `_fakes.py`, not scattered beside callers.

### Resolve lazily and cache only complete success

Repository resolution is complete-or-nothing. Resolve the full authority tuple lazily on first use
and cache only after every member succeeds. If any member fails, cache nothing; a partial cache
turns a transient failure into a permanently split authority graph.

Move eager composition inputs into authority methods and call them at the point of need. This makes
early refusals and dry projections provably zero-I/O. Prove the claim by monkeypatching every
substrate entry point to record or raise, then exercising each short-circuit — a fake that simply
returns no data cannot demonstrate that the read was skipped.

### Bound errors per operation

The façade maintains one validated wide vocabulary of delivery error codes, while each operation
accepts only its own private subset for adapter passthrough. An in-vocabulary but out-of-subset code
is a programming error and propagates rather than being flattened into a generic result. Every new
operation or code extends the wide gate and makes an explicit subset decision.

When one slice reuses another's adapter, unwrap a guarded `__cause__` only for the exact legacy error
whose message contract must survive. Classification-and-continue authority calls return frozen,
nested discriminants on the ABC, outside the public export ledger. Avoid import cycles by passing
primitive facts instead of whole authorities. Do not invent a dry-run adapter when dry-run omits the
operation entirely.

### Requests make consent and blank-input policy explicit

Consent on a mutating operation is mandatory input, never a default sentinel. Auto-approval may be
a valid caller decision, but each call site must spell it so mutation cannot appear through a new
default.

Frozen request dataclasses validate nonblank invariants in `__post_init__`. That moves policy to
every CLI boundary: normalize blank text to absence where optional, or return typed
`invalid_input` before request construction. Missing one caller lets a raw constructor error break
the CLI's JSON envelope. Moving an engine behind an adapter also changes exception types at phase
boundaries; sweep every phase-scoped `except` rather than assuming the old catch still applies.

Defaulted internal projection fields may carry already-observed snapshot facts through a pure
pipeline without triggering new reads or growing public output. Describe concurrency honestly:
an observation is not a lease. Supersession is established by the authoritative redirect field,
not inferred from raw id inequality.

### Pin exports and drive production delegates

An export cut is an exact-list contract. Name the added, removed, and retained symbols and assert all
three sets; a broad import smoke test cannot prove a retired seam disappeared or a compatibility
name stayed internal.

After migration, keep at least one public-path test on the real default runtime. Every ABC addition
also gets a production-adapter delegation test; Protocol fakes everywhere leave the actual delegate
unverified. When tests need to swap the runtime, patch the module symbol the public path resolves,
then retain the real-default lane alongside it.

Finally, review against the approved plan as authority. A reviewer preference that contradicts a
settled plan decision is declined with recorded rationale rather than silently redesigning the
slice during review.

### Slice scope + review economics (the door→typed-op train)

- **Typed-seam introduction lands net-*positive*** — expect +150–250 LOC per slice; the
  chronically underestimated item is the wire-identical details rebuild. The working acceptance
  mechanism is a **named-excess ledger** (each excess line class named and justified) with
  operator PR-approval as the recorded acceptance gesture; review-mandated hardening inside named
  invariant classes rides outside the size bar (#2186, #2181, #2184, #2180, #2182).
- **Zero-policy seams die at review.** A typed op that is a pure passthrough over one production
  adapter is a plan-time smell; a transition step with no decision content is padding; and
  plan-mandated defensive machinery still faces the YAGNI bar (#2171, #2182, #2181).
- **The counterpart: seam-proving slices legitimately decline YAGNI findings** when the structure
  IS the plan-mandated deliverable — pre-arm the decline in the plan and record it at review
  (#2169, #2180).
- **Tier fit:** "shared by N adapters" is not the substrate admission test — binding vocabulary
  can land in a tiny feature-home module instead of the substrate tier (#2181).

(The seam-design rules live in `pi/extension-seams.md` § "Door→typed-op extraction craft"; the
move/sweep mechanics in `toolchain/ts-module-moves.md`; the parity-pin shapes in
`workflow/execution-path-parity.md`.)

## The stacked `/submit` publish operation — five posture traps

§8.47 is the normative statement (anchors: `src/perk/delivery/`, the resume/republish/converge
paths). A decision-complete plan produced a ~3.9k-line diff with essentially zero structural
deviation — the review findings were all *posture* traps, the residual risk class even a
maximally specific plan doesn't remove:

1. **While an operation is unresolved, the prepared record is the authority — never re-derive.**
   The resume path pins the resumed op to its *recorded* desired state (lineage, branch ref, PR
   base, stack prefix, own-PR pin); any mismatch is `publication_drift`, fail closed. Authority
   drift while unresolved would silently retarget the publication.
2. **Mutation-adjacent authority reads must fail closed — convenience defaults are fail-open
   traps.** A JSON-read default of `[]` turned a failed stack-membership read into "not in a
   stack", which could trigger a spurious create-stack mutation. Only a literal empty payload
   means absence; empty/malformed output raises. Same class: merged-at became
   required-but-nullable (omission is wire drift, not "not merged"). Audit every defaulted JSON
   read near a mutation.
3. **Put invariant rechecks at the effect seam, not the routing seam.** The capability recheck
   fires immediately before an actual create/append (an already-converged membership never
   probes) — every path covered without rejecting converged states.
4. **A "bounded" error vocabulary isn't bounded if you forward error types verbatim** — either
   map onto the declared vocabulary or explicitly declare the passthrough codes in the contract
   (the fix chose declared passthroughs).
5. **Happy-path write-ordering assertions don't pin a no-persist-before-verification
   invariant.** Fail-closed paths need *negative* assertions (identity + checkpoint recorders
   stay empty); crash-window resume tests need *stateful* fakes whose reconstruction reflects
   prior writes (fail-once after each write, rerun, same operation completes, no duplicate
   mutation). Static-snapshot fakes make roll-forward coverage fictional.

## The transactional sync-cascade invariants (`perk objective stack sync`)

Contracts §8.49 is the normative statement (seams: `src/perk/delivery/sync.py`,
`src/perk/delivery/continuation.py`, the live-base read in `train.py`/`observe.py`). The
invariants below are the ones a naive port of publish's posture would get wrong:

- **The mutation universe is the checkpoint-claimed prefix, never `published_prefix_len`.** The
  train classifier truncates the verified prefix on exactly the discrepancies sync exists to
  diagnose — using it would make the drift refusals unreachable (a drifted bottom layer reads as
  a false no-op; a drifted upper layer silently shrinks a lower cascade). Sync derives the
  maximal contiguous run of fully-claimed layers (plan identity + branch + PR + full checkpoint
  pair) and preflights every one; `published_prefix_len` stays a status fact only (test harnesses
  may set it to 0 without affecting sync).
- **Mutations route through a fresh journal fold, never the projection's
  `unresolved_operation` summary** — the projection field is status color; the fold read is the
  single routing authority. A foreign unresolved kind blocks; only a matching unresolved SYNC on
  the lineage may resume.
- **Journal recovery is operation-specific, not a copy of publish's posture.** Sync's candidates
  live in disposable temp refs that don't survive a crash, and a recomputed rebase yields
  different SHAs — so all-refs-at-before means *prove* the all-before state, append ABANDONED
  with that proof, and prepare a fresh operation; all-at-after rolls forward under the same
  operation; mixed/unreadable stays unresolved, fail closed.
- **Resume corroboration revalidates topology and strictly decodes the prepared payload** —
  identity matching (plan/branch/PR/checkpoint) is not enough; recorded PR bases, contiguous
  order, membership, and base/base-parent consistency all affect safe roll-forward.
- **Two ancestry-validation traps**: localize/fetch recorded checkpoint objects *before* the
  ancestry check (a missing object looks like divergence), and validate the stored parent edge
  for *every* claimed source including unchanged layers (a corrupt unchanged checkpoint otherwise
  becomes a rebase upstream edge).
- **Base advancement needs a live authoritative read (`ls-remote`), never the fetched
  remote-tracking ref** — plain `git fetch` has no `--prune`, so a deleted remote base still
  resolves locally. Posture splits by role: status degrades tolerantly (`base_unobserved` INFO);
  the mutator's `--base` fails closed without positive observation.

## What the live stacked-publication dogfood gate proved

The full record is `docs/design/archive/stacked-publication-dogfood.md` — point, don't restate. The
durable distillations:

- **Two layers never exercise append**: stack-create first fires at layer 2, append at layer 3 —
  a live proof needs ≥3 layers to cover both native REST mutations.
- **Capability preflight is host-schema evidence only; per-repo enrollment is proven by the
  first stack-create mutation itself** — design a blocked disposition for its failure.
- **The warm `/submit` envelope is never publication evidence** — the journal is the operation
  authority; corroborate PR facts with `gh pr view` and train facts with `perk objective stack
  status --json`. Headless implement exit-0 proves nothing either.
- **A read-back failure after the mutation took effect converges by rescan, not re-mutation** —
  re-running `/submit` rescans the durable journal and converges idempotently (exactly one
  prepared/completed pair, no duplicate PR or stack membership).
- **A pristine clone still needs its own `npm ci`** — the `worktree-node-modules` trap applies
  to clones too.
- **Recurring GitHub-side noise:** cascade-rewritten heads can carry a CANCELLED superseded
  check-run beside the SUCCESS run at the same head — expect `optional_check_failed` noise in
  landing dry-runs after a cascade and diagnose before treating it as real (#2027).

The `PERK_DEV_STACKED_DELIVERY` development write gate was retired at the gate pass
(2026-08-13); the code grep is clean.

## The handoff gate (§8.46) and the ready continuation (§8.66)

- **Publishing a private helper makes its documented contract load-bearing.** Re-verify the
  helper's documented invariants over the WHOLE input domain, not the slice its old callers
  reached (the skipped-only-cycle hole in the deps walk, whose fix hardened `delivery_order`
  too) (#2029).
- **"Structurally ungated by construction" is pinned only at the real routing boundary** —
  drive `Delivery.publish(kind="layer")` through the one internal route both `/submit` and the
  address finalize reach, with the gated axis forced into every blocking state (#2029).
- **When a contract says every blocked arm carries the shared blocker rows, the
  defensive/unreachable arms are exactly where the envelope forks** — force each with a fixture
  (#2029).
- **All-or-nothing decode cohorts are facts-only:** presentation strings are derived from
  facts, never load-bearing in the cohort; guard validators are shaped by their real call
  sites (the tail-append guard takes exactly `add_node`'s output; the delivery-order-prefix
  check subsumes the resolved-edge comparison for that shape) (#2028). The continuation's
  announce-after-refusal-arms sequencing is §8.66's.
- The ready-time pass's lease-free bounded mechanics are §8.66's.
- **Order mutations so pure record construction precedes the first mutation**; typed refusals
  flip nothing, and a post-mutation failure carries the completed mutation's facts in the
  typed error (#2024). The `ReadyStampError` field shape is §8.66's.
- **Dry-run honesty (portable dogfood facts):** the plan door's dry-run keeps the OFFLINE
  graph classification and can refuse `objective_in_flight` before the seed composes — the
  reliable carrier of `build_readiness: "unchecked (dry-run)"` is
  `perk objective run --dry-run`; the `stamped ≠ head` sha disclosure is candidate-scoped by
  design (#2027). An offline dry-run must not claim to predict which online arm a real run
  takes — name both (#2024).

## Landing readiness (§8.55) — composition rules

(Seams: `src/perk/delivery/land.py`, `src/perk/delivery/writers.py`.)

- **Check module-scope import chains before adding a pure module that observation wiring must
  import.** The shared fail-closed remote-writer seam moved to a dependency-leaf
  `delivery/writers.py` (with compatibility re-exports) because `land → sync → observe → land`
  would cycle — trace the chain before placing the module, not after the import error.
- **Readiness composes the train as authority, fail-closed.** Blockers, unresolved operations,
  and membership are never re-derived, and every enrichment read failure maps to a *specific*
  fail-closed blocker (can't-verify ⇒ not-ready). Dispositions, blocker composition, and the
  publication-completeness authority axes are §8.55's.
- **Independent fail-closed vetoes, deduped agreeing findings** — independent vetoes so
  contradictory wire states never pass; agreeing reports coalesce to one blocker.

## Cancellation + doctor drift diagnostics

(Seams: `src/perk/delivery/train.py`, the recover/doctor flow.)

- **Absent journal headers prove nothing about remote work.** PUBLISH can push a branch or
  create a PR *before* headers and the terminal outcome are written — cancellation contraction
  requires journal folding + positive remote reads first; anything unprovable stays a
  projection-only canceled layer with blockers, never a silent contraction.
- **Checkpoint metadata is a topology proof, not independent hints** — half-pairs, claims above
  a missing pair, and adjacent parent/head disagreement are each *distinct structural findings*,
  separate from remote drift.
- **`STRUCTURAL_BLOCKER_CODES` is a cross-consumer contract, not a doctor list.** Growing it
  changes the replan/transfer/recover gates; any catalog growth must re-check every gate
  consumer (recover needed an explicit fold-first sole-PUBLISH route ahead of the generic
  structural gate).
- **Race-aware repair ≠ distributed atomicity.** Fresh proof + conditional compare-and-write +
  post-write verification closes *modeled* races only (§8.54 disclaims distributed atomicity).
  And post-write verification adds effect-boundary calls writer fakes must model:
  reconstruct → conditional write → reread → reconstruct → maybe compensate.

## Interrupted-LAND recovery (§8.51/§8.56) — gotchas

(Seams: `src/perk/delivery/land_records.py`, `landing.py`, `recover.py`, `finalize.py`.)

- **The neutral-module rule.** The strict LAND journal read models live in dependency-neutral
  `src/perk/delivery/land_records.py` — the models AND the prepared⋈completed join
  (`join_completed_land_operations`, the ONE canonical import path) — because `train.py` and
  `landing.py` cannot import each other without a cycle; there is deliberately no `landing.py`
  re-export. Durable shape: a delivery-plane artifact needed by both train and landing gets its
  own neutral module.
- **Any close that gates an evidence-bearing drive waits for the evidence's durable record**
  (§8.51/§8.56 own the deferred-close mechanics).
- LANDED's coverage-gated classification (join identity, corroboration, the suppression set) is
  §8.56's.
- **The timestamp trap:** a naive (non-UTC) `created` timestamp must classify `in_flight`,
  never crash the age gate; the no-handle crash-window/`external_prefix` mechanics are
  §8.51/§8.56's.
- **Plan-close/node-terminal is not a completeness proxy** — it cannot observe
  learn-stamp/consume effects; the finalization-convergence mechanics are §8.51/§8.56's.
- **A producer widening must meet the consumer's firing gate.** Recover's close-then-evidence
  repair truthfully returns `objective_closed: false` when re-emitting evidence for an already
  closed objective. The TypeScript consumer in `extension/pi/v1/delivery/stackDrive.ts` therefore
  gates `driveStackReconcile` on evidence presence, not the close-transition flag. Widening what a
  producer populates while its consumer tests another field is dead code by construction.
- **Removing one condition transfers its safety burden.** Once the drive stopped requiring
  `objective_closed`, the producer rule "a failed aggregate close emits no evidence" became
  safety-critical; the old compound gate had guarded it twice. Pin that negative arm explicitly.
  General rule: whenever a compound firing gate loses a condition, enumerate every path that
  condition used to suppress and prove the survivor still suppresses each unsafe case.
- **Repair re-emission is deliberately at-least-once.** Every operator-invoked recover on a
  closed, journal-complete stacked objective may emit the same evidence again. This is safe only
  because objective reconcile is idempotent; the producer frequency and consumer idempotency are
  one load-bearing design, not independent implementation details (`src/perk/delivery/recover.py`).
- **Recovery-hardening kernels from review:** fresh corroboration runs *before* preview
  generation; journal-derived strings are delimited as untrusted DATA.
- **Budgeting note:** a "full consumer sweep" over `LayerPublication.PUBLISHED` consumers was
  mostly an audit — existing non-PUBLISHED skip arms already handled LANDED; the output was
  tests + comments pinning behavior, not code.

## Recovery proof is a fresh product-state proof, not a ref comparison (§8.51)

- **Fresh product-state proof before classification:** complete, kind-specific proof in *both*
  terminal directions, never merely the recorded branch SHA — and a clean detached HEAD alone
  can be a `rebase --abort`/reset state. The PUBLISH/continuation proof enumeration is §8.51's.
- **Best-effort cleanup is still protocol output.** Residue lives in both the filesystem and
  Git's worktree-admin inventory; every cleanup failure travels as structured notes through
  every outcome arm — a nominal success must not hide residue later recovery has to explain.
- **No-op lease semantics:** an unchanged adopted ref cannot carry a server-side lease (Git
  omits no-op updates) — postcondition verification covers it, not a fictitious lease. The
  continuation manifest's authority-boundary mechanics are §8.51's.

## Never-authoritative revision records need an immutability shape check

A never-authoritative revision record (the `layer-context.json` parent-sha reader in
`src/perk/state/cache.py`) must pass an **immutability shape check, not a resolvability check**:
accept only a full 40-hex object id that resolves to itself. Movable refs, abbreviations, and
tags all *resolve* today but silently re-pin later reads; degrade (warn + the fallback arm) on
anything else.

## The transfer protocol's meta-patterns (§8.53)

- **Convergent found-arm claims must be proven at every subordinate-write boundary.** When an
  entity's discovery key is written *after* the entity itself, convergence needs a secondary
  fingerprint over the atomically-created fields (or a pinned ordering invariant) — and
  interruption tests must inject fail-once at store-internal write granularity, not just between
  top-level steps.
- **For machine-authored durable payloads riding mutable storage, validate cross-field
  invariants, not just schema** — envelope↔manifest relationship checks run before any recovery
  write.
- **Two fail-open shapes to watch for in fail-closed designs**: a malformed header treated as
  "no claim" exactly when absence can't be proven (posture: cannot prove absence ⇒ typed
  refusal); and a "ONE classification read" invariant degrading because the snapshot wasn't
  threaded across a boundary — single-read invariants are enforced by *passing the snapshot
  through*, not by convention.
- **Backend-conditional field semantics need boundary enforcement** (per-backend carry-map
  construction), and **a door that stages work must apply the same structural gates as the save
  that consumes it** — otherwise the door stages state the save will refuse.

## Layer identity + the strict-read save guard

(Seams: `src/perk/delivery/` and the stacked-selection seam in
`src/perk/cli/commands/objective/shared.py`.)

- **The branch-resolution asymmetry is deliberate.** The *predecessor* branch is observed
  (stored header else convention), but a layer's *own* branch is always the canonical
  `plan-<N>` — both creation paths (local worktree add, remote checkout) create exactly that
  branch, so resolving one's own branch via header-or-convention could describe a branch that
  was never created.
- **"A failed read fails the save" must enumerate the missing/None arm, not just the exception
  arm.** A store exception was treated as failure while an objective-not-found `None` fell
  through fail-soft — defeating the fail-before-write guarantee (a save proceeding without the
  delivery policy silently skips layer-identity stamping; a child layer could later branch from
  the wrong parent). Shipped rule: missing-as-failure. Planning lesson: fail-closed read specs
  must name both arms — "failed" and "missing" read identically in prose but are different code
  paths.

## Residual proof bounds (façade operation slices already landed)

The façade slices (status/prepare/transfer/publish/sync/recover/land) are current behavior; the
bullets below are open proof bounds and future schema edges.

- `before`/`after`/`observed` are opaque validated mappings — kind-specific shapes belong to the
  operation nodes; only the envelope is pinned.
- Linear's comment-size limit is undocumented — the shared 60,000-char cap assumes it is ≥ that.
- The recovery engine landed (`perk objective stack recover`) — §8.51 owns
  classification/roll-forward/abandon.
- Durable why: TRANSFER routes fold-first because its in-progress ownership writes intentionally
  make the predecessor train look structurally broken.
- Durable bound: the machine-local `flock` (`oplock.py`) serializes sync/recover/land per
  machine only — cross-machine overlap is detected (leases + drift checks), not prevented;
  operator quiescence stays a prerequisite.
- Widening the `accepted`-gated-to-`land` rule requires an explicit schema revision.
- The build-readiness veto set is deliberately fail-closed and coarse — expect over-blocking
  pressure; the refinement lever is attribution (naming which veto fired), not loosening.
- The session-scoped layer-context file is never authoritative.
- The live stacked remote-runner arm remains deliberately unrun; the 2026-08-13 gate passed
  through the second-clone arm (fresh-checkout/durable-authority independence on one host) —
  never misstate that as host-level cross-machine independence; remote positioning stays pinned
  by `tests/test_run_worker.py` + `tests/test_delivery_cross_machine.py`.
- Published-suffix sync, the warm stack doors, and automatic propagation from submit/address
  landed — §8.49/§8.51/§8.52 own the control surface.
- Sync live proof (2026-08-13): real GitHub auth + atomic multi-ref acceptance proven for an
  unprotected base; the retained-conflict arms stay hermetic-pinned; branch-protection
  acceptance remains unproven live.
- Atomic landing, the stacked `pr land`/`/land` refusal, and interrupted-LAND recovery landed —
  §8.55/§8.56/§8.51 own it (including the stacked-lineage fail-closed refusal).
- Live landing complement (2026-08-13): merge-async proved live on a real 3-layer train (SIGKILL
  after durable `accepted`; second-clone `stack recover` completed the SAME operation and
  emitted complete reconcile evidence; the GitHub store's `ObjectiveState.state` lifecycle read
  proved live) — still capture-if-fired/hermetic-only: post-partial-merge/external-prefix
  composition, the breach→`sync --base`→`land` route, retained conflicts, and non-GitHub
  lifecycle reads; an undecodable final record yields `final_base_sha` from the last decoded
  record, evidence marked partial.

## Cross-references

- `shared/contracts.md` §8.42 / §8.43 — the normative delivery contracts (point, never restate)
- `docs/learned/workflow/objective-store.md` — the three objective stores the adapter aligns with
- `docs/learned/workflow/objective-lifecycle.md` — node status transitions + reconcile mechanics
- `docs/learned/workflow/linear-backend.md` — the Linear transcoder + project-backed store
- `docs/learned/workflow/plan-ref-lifecycle.md` — the additive stored-field recipe the header
  emission follows
