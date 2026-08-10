---
title: Objective delivery trains — the operation journal, TrainPersistence, and stacked-roadmap mechanics
read_when: You are touching src/perk/delivery/ (journal, TrainPersistence, train read path / stack status probes), delivery_order/validate_stacked_roadmap, a delivery/recovery node, or stacked-delivery headers.
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
- Residual: the preview stack shapes are fixture-proven only until a production stacked train
  exists; the tolerant read (`available=False`) is the designed containment if the live preview
  drifts.

## Residuals (flagged, owned by later nodes)

- `before`/`after`/`observed` are opaque validated mappings — kind-specific shapes belong to the
  operation nodes; only the envelope is pinned.
- Linear's comment-size limit is undocumented — the shared 60,000-char cap assumes it is ≥ that.
- There is **no recovery engine**: the fold *exposes* unresolved operations; interpreting partial
  remote states is later-node territory.
- Widening the `accepted`-gated-to-`land` rule requires an explicit schema revision.

## Cross-references

- `shared/contracts.md` §8.42 / §8.43 — the normative delivery contracts (point, never restate)
- `docs/learned/workflow/objective-store.md` — the three objective stores the adapter aligns with
- `docs/learned/workflow/objective-lifecycle.md` — node status transitions + reconcile mechanics
- `docs/learned/workflow/linear-backend.md` — the Linear transcoder + project-backed store
- `docs/learned/workflow/plan-ref-lifecycle.md` — the additive stored-field recipe the header
  emission follows
