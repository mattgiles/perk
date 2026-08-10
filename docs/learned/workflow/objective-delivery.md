---
title: Objective delivery trains — the operation journal, TrainPersistence, and stacked-roadmap mechanics
read_when: You are touching src/perk/delivery/ (journal, TrainPersistence, train/stack probes, stacked /submit publication), delivery_order, a delivery/recovery node, or stacked-delivery headers.
---

# Objective delivery trains — the operation journal, TrainPersistence, and stacked-roadmap mechanics

`shared/contracts.md` **§8.42** (the stored domain contract) and **§8.43** (the operation journal
+ train persistence) are the normative statements — this doc points at them and carries only the
cross-cutting *why*: the traps the naive shapes hide, the test design that catches them, and the
history a future delivery/recovery node should not re-derive.

## The seam map

- `src/perk/delivery/journal.py` — the event grammar, the fold, and the fail-closed
  `JournalCorruptionError` posture.
- `src/perk/delivery/persistence.py` — `TrainPersistence`, the backend-aligned adapter;
  `journal_carrier_id` resolution across the three stores.
- `src/perk/objective/graph.py` — `delivery_order` / `validate_stacked_roadmap` (the stacked
  roadmap's contraction + topological ordering).
- `src/perk/objective/render.py` + `src/perk/plan.py` — the conditional/stripping header emission
  (the additive stored-field recipe; see `workflow/plan-ref-lifecycle.md`).
- `src/perk/delivery/train.py` / `src/perk/delivery/observe.py` / `src/perk/github/stacks.py` /
  `src/perk/delivery/capability.py` — the train read path + stack status/capability probes (see
  "The train read path" below).

Future consumers: the operation nodes and recovery work of objective #1431 depend on §8.43's
*exact* semantics — amend the contract, not just the code.

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

## Why cross-backend byte-identity works

Idempotency equality is **canonical-serialization equality** (an `OutputModel` dump through
sorted-keys-off YAML), and the Linear transcoder rewrites **only the marker**, never the fenced
payload — proven by round-tripping the rendered body through the real `to_linear_markdown` in
tests. The engagement-exclusion requirement needed **zero new code**: the generic `perk:*`
sentinel classifier already drops journal comments from human-engagement inputs (pinned by tests
only).

## The train read path (reconstruction + stack status probes)

The read path splits deliberately: `src/perk/delivery/train.py` is the pure classification core
(tested with in-memory Protocol fakes), `src/perk/github/stacks.py` the wire adapter
(fake-subprocess tests), and `src/perk/delivery/observe.py` the production wiring leaf (probe
conversions; the hard-fail vs. tolerant-degrade split).

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

- The `pr_wrong_head` blocker: open PRs corroborate their head ref/OID against the layer branch
  and the observed/recorded head; a mismatch disqualifies publication. The base-ref comparison
  runs *before* the terminal MERGED/CLOSED arms, so a merged-into-wrong-base PR still reports
  `pr_wrong_base`.
- Residual (discharged): the preview stack shapes were fixture-proven only until a production
  stacked train existed — a production stacked train (three layers, create + append) ran live at
  the stacked-publication dogfood gate. The tolerant read (`available=False`) remains the
  designed containment if the live preview drifts.

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

## What the live stacked-publication dogfood gate proved

The full record is `docs/design/stacked-publication-dogfood.md` — point, don't restate. The
durable distillations:

- **Two layers never exercise append**: stack-create first fires at layer 2, append at layer 3 —
  a live proof needs ≥3 layers to cover both native REST mutations.
- **Capability preflight is host-schema evidence only; per-repo enrollment is proven by the
  first stack-create mutation itself** — design a blocked disposition for its failure.
- **The warm `/submit` envelope is never publication evidence** — the warm decoder drops
  operation ids and discards raw stdout; read operation ids + prepared→completed transitions
  from the objective issue's journal comments, PR facts from `gh pr view`, train facts from
  `perk objective stack status --json`. Headless implement exit-0 proves nothing either.
- **A read-back failure after the mutation took effect converges by rescan, not re-mutation** —
  re-running `/submit` rescans the durable journal and converges idempotently (exactly one
  prepared/completed pair, no duplicate PR or stack membership).
- **Parent-aware execution works from durable authorities** — a pristine clone with no
  worktrees/local stack metadata/dispatch cache derived the parent branch at its published SHA
  from the reconstructed train; the session-scoped layer-context file is operational-only
  evidence. (A pristine clone still needs its own `npm ci` — the `worktree-node-modules` trap
  applies to clones too.)

The `PERK_DEV_STACKED_DELIVERY` development write gate was retired with the gate pass.

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

## Residuals (flagged, owned by later nodes)

- `before`/`after`/`observed` are opaque validated mappings — kind-specific shapes belong to the
  operation nodes; only the envelope is pinned.
- Linear's comment-size limit is undocumented — the shared 60,000-char cap assumes it is ≥ that.
- There is **no recovery engine**: the fold *exposes* unresolved operations; interpreting partial
  remote states is later-node territory.
- Widening the `accepted`-gated-to-`land` rule requires an explicit schema revision.
- The build-readiness veto set is deliberately fail-closed and coarse — expect over-blocking
  pressure; the refinement lever is attribution (naming which veto fired), not loosening.
- The session-scoped layer-context file is never authoritative.
- The live remote-runner stacked arm is unproven (deferred at the dogfood gate).
- Published-suffix sync, atomic landing, and a stacked-lineage refusal in `perk pr land` do not
  exist yet — landing one layer individually can tear the train (documentation is the only
  mitigation until that node lands).

## Cross-references

- `shared/contracts.md` §8.42 / §8.43 — the normative delivery contracts (point, never restate)
- `docs/learned/workflow/objective-store.md` — the three objective stores the adapter aligns with
- `docs/learned/workflow/objective-lifecycle.md` — node status transitions + reconcile mechanics
- `docs/learned/workflow/linear-backend.md` — the Linear transcoder + project-backed store
- `docs/learned/workflow/plan-ref-lifecycle.md` — the additive stored-field recipe the header
  emission follows
