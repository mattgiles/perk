---
title: Planning-time facts decay — plan currency, budgets, baselines, count pins
read_when: You are authoring or implementing a plan with numeric budgets/line caps, measured baselines, count pins, or field lists — or a sibling PR landed after the plan was saved.
cluster: plan-lifecycle
---

# Planning-time facts decay

A plan is a snapshot of facts gathered at one commit: which files exist, how many lines a passage
has, what a suite measures, which contract section carries a rule. Every one of those facts starts
decaying the moment the plan is saved — sibling PRs land, files shrink, catalogs grow. This doc
collects the recurring ways an implementation session was bitten by a fact that was true at
planning time and false at execution time, and the disciplines that catch the decay early. It is
the *authoring and implementing* companion to `workflow/plan-ref-lifecycle.md` (the artifact) and
`workflow/mergeability-and-conflict-resolution.md` (the branch).

## A plan is only as current as the commit it was verified against

- **Re-investigate before writing code when a sibling PR touching the subsystem landed after
  plan-save.** PR #2313 (a persisted draft-review coordinator) was closed as *superseded*: a
  sibling had replaced the very mechanism the plan extended. PR #2317 added a trailing `diff_source`
  field to a review-context envelope — every plan that had pinned that envelope's field order or its
  JSON goldens was silently invalidated. The cheap check at implementation start: `git log
  --oneline <plan-base>..main -- <the paths the plan names>`; a non-empty result means the plan's
  premises need re-reading against live source before the first edit.
- **Verify contract `§` numbers at edit time**, not from the plan text. `shared/contracts.md`
  sections are appended and occasionally renumbered; a plan that says "amend §8.42" may be pointing
  at a neighbour by the time it is implemented. `tests/test_contracts_anchors.py` pins that cited
  anchors *exist* — it cannot know the plan meant a different one.
- **Named delegates may have been deleted.** A learning or plan that names helper modules as the
  edit site should be checked with `rg` first; the surviving *insight* often has a different home
  than the one the text names.

## Numeric caps are hard acceptance constraints enforced only by the fidelity lane

A plan that says "≤ 30 lines" or "the section stays under N bytes" has stated an acceptance
criterion that **no tool enforces** — `perk learn docs-check` enforces its own thresholds
(distillation shape, cue length, byte gates) and `test_contracts_anchors` enforces anchor existence;
neither reads the plan's caps. Only the plan-fidelity review lane will notice, after the fact.

- **Count the replacement passage before committing** (`wc -l`, `wc -c`, or a Python one-liner over
  the section), not after the review flags it.
- **Prose-budget estimates on contract paragraphs overrun.** A "one paragraph" estimate for a
  `contracts.md` rule reliably becomes three once the precedence order, the failure arms, and the
  test pointer are written. When the honest passage exceeds the cap, surface it under the
  stop-and-re-scope rule rather than compressing the rule into ambiguity.
- **A follow-up plan under a budgeted node carries its own explicit remaining allowance.** "Node
  3.2 has 40 lines left of its 120-line budget" belongs in the follow-up's `## Assumptions`, or the
  follow-up will spend the whole budget again.

## Re-measure baselines and counts live

- **Distinguish the historical objective baseline from the live planning baseline.** An objective's
  opening record measured files at *its* start; by the time a later node is planned, sibling nodes
  have already shrunk them. A plan that promises "reduce `foo.py` by 30 %" against the objective's
  baseline may already be met — or impossible — at the live one. State which baseline a number
  refers to.
- **Planning-time collection counts are estimates; run the census at closeout.** "34 learn issues",
  "22 stale pointers", "11 unrouted units" are what the scan said on the day; the closeout
  verification re-runs the scan and reports the live count, never repeats the plan's.
- **Count pins over a global projection are re-measured after regeneration, never computed from
  your delta.** A pin like `len(catalog.governed_tools) == 39` sits over a projection that other
  landed work also moves (`workflow/prose-review-workbench.md`'s `sync` sweep is the sharpest case);
  regenerate, then read the real number.

## Line count is a poor proxy for duplication

A deduplication that replaces N hand-built test cases with one production-shaped harness trades
*case* count for *fixture, matrix, and formatter* bulk — the file often grows. Budget that bulk
explicitly when the plan sets a line target. If the line target is a **real requirement**, make it a
measured gate with a re-scope checkpoint (measure at the midpoint; stop and re-plan if the trend is
wrong); if it is a hope, report the measured outcome and do not contort the code to hit a number.
`workflow/test-pin-sweeps.md` covers the sweep mechanics; `workflow/binding-design-records.md`
covers recording a measurement honestly (including a no-improvement verdict).

## Scope prose yields to an in-session human decision — absorb it with discipline

The operator can, and does, redirect scope mid-implementation: enable the last gated case, absorb a
sibling's drift, fix a latent bug the submit surfaced. Honour it — but absorb it with the same
discipline the planned work gets:

- **Extend the guard test in the same turn** the scope changes; a guard that still encodes the old
  scope is now a false pass.
- **Reconcile the objective's non-goal honestly** — a PASS row with the reasoning, or a named
  deviation in the plan's `## Assumptions`, never a silent widening.
- **Attach no unmeasured claim** to the absorbed work ("also faster", "also safer") — if it was not
  measured under the plan's own gate, it is not a result.
- **A docs-only plan may need a minimal, operator-authorized out-of-scope code fix** when submitting
  surfaces a real latent bug (a guard that was vacuous, a pin that never bit). The fix ships with its
  contracts amendment and test pin in the same turn and is recorded as a deviation; it does not
  become a licence for further code changes under the docs plan.

## A review that re-litigates a settled Assumption gets intent documentation, not re-architecture

When a reviewer questions a decision the plan's `## Assumptions` already records (why the seam
methods are public, why the allowlist was deleted rather than widened, why the fake fails closed),
the right response is to make the *intent* visible where the reviewer looked — a docstring or a
one-line comment carrying the "why" — not to redesign under review pressure. If the Assumption was
wrong, that is a new plan; if it was right but invisible, that is a documentation fix. Re-architecting
mid-review discards the evidence the Assumption was built on and produces a change nobody planned.

## Cross-references

- `docs/learned/workflow/plan-ref-lifecycle.md` — the plan artifact and its linkage
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — when the branch, not the plan, has decayed
- `docs/learned/workflow/test-pin-sweeps.md` — sweeping count/format pins after a projection changes
- `docs/learned/workflow/prose-review-workbench.md` — the whole-projection `sync` and its count pins
- `docs/learned/workflow/binding-design-records.md` — measurement honesty in the durable record
