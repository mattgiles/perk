# Stamp stacked objective nodes ready

## Problem statement

Incremental objectives inherit the ordinary plan lifecycle without qualification:

```text
implement → review → address → land
```

Landing is both the plan's integration boundary and the objective's progression boundary. It
merges the accepted implementation, marks the linked roadmap node done, reconciles the objective
against what actually landed, and allows dependent nodes to move forward.

Stacked objectives cannot use that boundary per node. Their layers are deliberately held apart as
review units and integrated together at the objective boundary, so ordinary `/land` must refuse an
individual layer. Today the practical per-layer lifecycle therefore ends after implementation,
review, and address. As soon as a predecessor is remotely published, perk considers the next layer
buildable and may plan it, even if the predecessor's review loop has not reached an explicit human
handoff:

```text
implement → review → address → ?
```

This is more than a missing gesture. It means stacked objective progression has a weaker contract
than incremental progression:

- publication is doing double duty as both a Git prerequisite and an implicit workflow approval;
- downstream planning can outrun review and address work on its roadmap dependencies;
- objective reconciliation waits until the whole train lands, too late to reshape untouched
  future work while the objective is being discovered layer by layer; and
- the cold doors disagree about what is next: some use the live delivery train, some use roadmap
  status alone, and stacked dry-runs intentionally decline to check live build readiness.

`/ready` is the natural missing boundary. It already names an explicit human handoff and already
changes a draft PR to ready-for-review, but ordinary plans often skip it because it does not
otherwise advance the workflow. Stacked objectives give that gesture meaningful work without
requiring a second meaning for `/land` or changing the ordinary incremental path.

## Statement of intent

For a plan belonging to a stacked objective, `/ready` should mean:

> This exact published layer head has completed its implementation, review, and address loop and
> may satisfy direct roadmap dependencies for further objective work.

The gesture should continue to make the PR non-draft, and it should also persist a **ready stamp**
for the exact verified published head. The stamp is a reversible, head-sensitive workflow fact. It
is not a new objective node status, does not mark the node done, and does not claim that the layer
has landed. Nodes remain `in_progress` until objective-scoped landing finalizes them.

The three relevant facts must remain distinct:

1. **Published/buildable:** the layer has a verified remote branch and PR, so a successor can be
   based on it technically.
2. **Stamped ready:** the current published head has crossed the stacked objective's human handoff,
   so it may unblock direct roadmap dependents.
3. **Landable:** the whole train satisfies the existing objective-scoped merge checks, reviews,
   and GitHub rules.

Publication remains necessary for building the train, but is no longer sufficient for progressing
through dependency-bound objective work. Conversely, the ready stamp is a planning-control signal,
not another atomic-landing prerequisite.

## Required behavior

### A head-bound, stacked-only handoff

- The additional stamp exists only for stacked objective layers. Incremental plans retain today's
  `/ready` behavior and lifecycle meaning.
- The stamp names the exact current published head. An out-of-band GitHub ready-for-review action
  is not a perk ready stamp and does not unblock objective planning. Running `/ready` on an already
  non-draft stacked PR must still be able to stamp its current head.
- Repeating `/ready` at the same head is mutation-idempotent. It remains a deliberate request to
  run reconciliation again, so it is also the recovery path when an earlier reconcile continuation
  did not run.
- A user- or agent-authored change to a stamped layer makes that layer's stamp stale until
  `/ready` is run again.
- A perk-controlled mechanical rewrite may carry an existing stamp to the verified replacement
  head only when perk can prove that the layer's own delta was preserved. This covers clean
  cascades and equivalent automated re-anchoring without making routine automation strand layers
  as unready. Automation must never promote a layer that was not already stamped ready.
- Adoption, human conflict resolution, or any other operation that accepts content not proven to
  preserve the layer delta invalidates the affected layer's stamp. Mechanically rewritten
  successors may still preserve their own prior stamps when their deltas are proven unchanged.

The ready stamp must be reconstructable from durable backend and remote facts in a fresh clone. A
session, worktree, local selector, or machine-local cache may help perform the gesture but must not
be its authority.

### Dependency and execution gating

A stacked node may be planned only when each of its **direct resolved roadmap dependencies** is
one of:

- `done` or `skipped`; or
- published with a ready stamp matching its current verified head.

This uses the objective's real dependency graph, including sequential dependencies inferred when
the roadmap does not declare explicit edges. It does not serialize independent nodes merely
because the delivery train gives them a total order.

Readiness is deliberately evaluated at direct dependency edges. A dependency's own current stamp
is authoritative for its dependents even if one of that dependency's ancestors later becomes
unready; readiness is not recursively withdrawn through the entire DAG. The stale ancestor still
blocks any node that depends on it directly.

If an upstream stamp becomes stale after downstream plans already exist, perk should pause **new
plans and fresh implementation starts** whose direct dependencies are no longer ready. It should
not strand work already underway: submit, address, synchronization, conflict repair, and re-ready
paths must remain available so the train can converge. Supervisors should direct attention to the
earliest actionable repair rather than launching more fresh work across the stale boundary.

An explicitly `blocked` node remains blocked regardless of ready stamps. Ready is a dependency
satisfaction fact, not an override for roadmap status or train drift.

### Reconcile while future work is still fluid

After a stacked ready stamp succeeds, perk should immediately continue into
`/objective-reconcile` for that exact objective, node, PR, and stamped head. The pass examines the
layer's incremental PR diff, the current objective, and human engagement. It reconciles the
objective against what is now accepted for the train, without pretending that the layer has
already landed.

The stamp commits before the judgment pass. Reconciliation is fail-open, as it is after landing:
a failed or unavailable reconcile continuation must be reported loudly but must not roll back a
successful ready stamp. Re-running `/ready` should always enter reconciliation again.

Ready-time reconciliation may update reconcilable prose and node descriptions, add newly
discovered nodes, and reshape dependencies or order within the **unpublished suffix**. It must
preserve the identities and order of the published prefix. The permission to reshape future work
is not permission to churn it: changes still require concrete evidence from the accepted layer or
human engagement, and wholesale speculative rewriting remains out of bounds.

The existing whole-train reconcile after objective landing remains. Ready-time reconciliation
keeps future intent current; post-land reconciliation is the final truth pass over what actually
merged and should commonly be a no-op.

### Landing stays objective-scoped

Ordinary `perk land` and `/land` must continue to refuse a stacked layer. They must not merge the
PR, mark the node done, or reinterpret per-layer ready as per-layer landing. Their refusal should
point to the correct next boundary: `/ready` when the layer has not crossed its handoff, or
`/objective-land` when the complete train is ready to integrate.

Atomic objective landing retains its existing rules. It still requires non-draft PRs and applies
the current GitHub review, check, ancestry, composition, and merge-rule gates, but it does **not**
gain a requirement that every head carry perk's planning stamp. The stamp exists to control
objective progression, not to create a second merge-readiness policy.

## Cold-door ergonomics

The warm path is straightforward: stacked `/ready` performs the deterministic stamp and then
drives the reconcile turn in the same session. The shell path should offer the same coherent human
journey without making deterministic workers secretly agentic.

- Top-level `perk ready [PLAN]` remains today's direct operation for an incremental plan. For a
  stacked layer, a successful interactive invocation should continue into the ready-time
  reconciliation pass.
- The `perk pr ready` worker, including its JSON form used by the warm door and automation, stays
  deterministic and non-launching. Its structured result must identify whether the plan was
  stacked and carry the objective, node, PR, stamped head, and whether the stamp advanced, so a
  caller can continue honestly.
- JSON and headless worker invocations never surprise the caller by opening a session. They return
  the continuation facts instead.
- If the stamp succeeds but launching reconciliation fails, the command must report those as two
  separate outcomes. It must not describe the stamp as failed or try to undo it; rerunning
  `perk ready <PLAN>` safely retries the reconcile continuation.
- Dry-runs that claim a stacked planning or readiness result should perform the required live,
  read-only projection. "Unchecked" must not be presented as if it were the action a real run
  would take.

  > **Status (2026-08-22):** deliberately not shipped as written. The landed behavior keeps
  > stacked planning/supervisor dry-runs offline and reports `build_readiness: "unchecked
  > (dry-run)"` honestly (`perk objective plan --dry-run`, `perk objective run --dry-run`) —
  > "No live dry-run projection" is a human-approved cut recorded in objective #1951's
  > Boundaries. The live-read surfaces are `perk objective next`/`show`/`stack status` (and
  > `show` degrades a failed live read as `readiness unchecked (<error>)` rather than
  > pretending). The coherence audit lives in
  > `docs/design/stacked-ready-handoff-dogfood.md`.

The command-line pass is broader than the ready command itself. Every surface that claims to know
the next objective action must consume the same readiness truth:

- `perk objective plan`, including explicit `--node` selection;
- `perk objective next`, `show`, and `run`;
- `perk objective stack status` and its machine envelope;
- stacked planning and supervisor dry-runs; and
- plan-resume, submit/address completion, and land-refusal guidance that tells the user which door
  comes next.

Human output should name the blocking dependency, plan, PR, and observed stamp/head mismatch when
known, then give a copyable `perk ready <PLAN>` remediation. Machine output should distinguish
technical train blockers from a missing or stale dependency handoff. No cold surface should say a
node is next while another surface would refuse to plan it.

## Solution guidance

### Do

- Treat publication, ready handoff, and landing as separate domain facts.
- Keep readiness head-bound, durable, idempotent, and observable in the delivery-train projection.
- Preserve ready intent through proven mechanical rewrites while preserving the distinction
  between "carried forward" and "newly made ready."
- Pass the exact objective/node/PR/head into ready-time reconciliation; do not depend on whichever
  branch or PR happens to be ambient in the session.
- Keep repair paths usable when progression is blocked.
- Let reconciliation refine genuinely untouched future work while protecting the published
  prefix.
- Make status, next-action, dry-run, warm-door, and cold-door language agree.
- When the behavior is built, amend the cross-plane contract, user documentation, and the
  self-contained `perk-expert` reference in the same change.

### Don't

- Do not add `ready` to the objective node-status vocabulary or mark a ready node `done`.
- Do not make `/land` merge an individual stacked layer or overload it as the ready gesture.
- Do not treat GitHub's current non-draft bit alone as proof that perk's handoff occurred.
- Do not recursively invalidate a currently stamped dependency solely because one of its own
  ancestors became stale.
- Do not let automation manufacture ready intent for an unstamped layer or preserve a stamp across
  an unproven content change.
- Do not block submit, address, sync, recovery, or re-ready work needed to repair a stale train.
- Do not allow ready-time reconciliation to reorder or replace the published prefix.
- Do not roll back a successful stamp because the subsequent judgment pass failed.
- Do not add the perk ready stamp to atomic landing's eligibility rules.
- Do not change the meaningful behavior of `/ready` for standalone or incremental plans.

