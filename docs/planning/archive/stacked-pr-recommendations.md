## Recommendation

  Treat “stacked” as an objective-level delivery mode, implemented by one deep Python module
  that coordinates objective state, plan branches, worktrees, PRs, and GitHub’s stack APIs.

  Do not make local gh stack metadata the foundation. Perk already owns one worktree per plan,
  whereas GitHub explicitly positions gh stack link—which has no local tracking—as the path
  for separate worktrees. Perk should preserve its worktree model and interact directly with
  GitHub’s REST and async merge APIs.

  Objective roadmap         Git branches/worktrees       GitHub
  (intent + ordering)       (implementation ancestry)    (review + merge truth)
          \                         |                         /
           \                        |                        /
                    ObjectiveStackCoordinator
               inspect · prepare · publish · sync · land

  ## Why this is not just a submit flag

  Three existing assumptions must change deliberately:

  - Dependencies currently unblock only when they are terminal (done or skipped) in src/perk/
    objective/_models.py:126. That intentionally serializes objective nodes.

  - A plan’s base currently serves as both its PR target and worktree start point in src/perk/
    plan.py:293. In a stack, the ultimate target (main) and immediate parent (plan-123) are
    different facts.

  - Individual /land couples the merge with plan closure, learning state, node completion, and
    objective reconciliation in src/perk/cli/commands/pr/land_cmd.py:128. A stack merge needs
    to perform one merge and then finalize several plans.

  Trying to encode stacking by passing implement --base would bypass objective scheduling,
  planning context, resumption, address propagation, and batch landing.

  ## Most important design goals

  1. Preserve the plan as the unit of work. Every node still emits an ordinary plan with its
     own branch, PR, review, CI, address cycle, and learn state.

  2. Keep one authority for each fact.

      Fact                                         Authority
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━
      Objective intent and dependency order        Objective roadmap
     ───────────────────────────────────────────  ──────────────────────
      Ultimate integration branch                  Objective base
     ───────────────────────────────────────────  ──────────────────────
      Immediate layer parent                       Plan metadata
     ───────────────────────────────────────────  ──────────────────────
      Git ancestry                                 Branch refs
     ───────────────────────────────────────────  ──────────────────────
      Stack membership, position, review, merge    GitHub
     ───────────────────────────────────────────  ──────────────────────
      Local stack/worktree state                   Derivable cache only

  3. Separate “build-ready” from “landed.” A stacked successor becomes plannable when its
     predecessor has a published PR/branch, while objective completion continues to require
     done/skipped. Do not weaken the meaning of terminal status.

  4. Plan against the code that will actually be inherited. Successor planning must run from a
     detached read-only checkout of its parent branch, not today’s default-branch checkout.

  5. Make history rewriting safe. Cascading updates must preflight all affected worktrees, use
     explicit old-parent SHAs, force-with-lease, rollback on failure, and refuse unpublished
     or dirty upstack work.

  6. Be honest about landing semantics. Direct stack merge is currently documented as atomic;
     merge queues enqueue the stack together but can process it across groups. Report merged
     versus enqueued accurately. See GitHub’s current Merge API
     (https://github.com/github/gh-stack/blob/main/docs/src/content/docs/reference/merge-api.md).

  7. Remain reconstructable from a fresh clone. A missing .git/gh-stack file must be
     irrelevant.

  ## Core model

  Add an objective header field:

  delivery: serial   # default, existing behavior
  # or
  delivery: stacked

  For plans, retain base as the ultimate integration target and add:

  base: main
  stack_parent: plan-123   # null for the bottom layer

  The effective worktree/PR base becomes:

  stack_parent ?? base ?? repository default

  This avoids overloading base and keeps non-stacked plans byte-compatible apart from the
  additive null field.

  Do not persist stack number or position in objective metadata. Those are observable GitHub
  facts and would become another drift surface. Derive the remote stack through a member PR.

  Initially, require a stacked objective to be a genuine chain. The default inferred objective
  graph already is one in src/perk/objective/graph.py:198. Reject explicit DAGs with fan-out,
  fan-in, or independent nodes rather than silently imposing an artificial total order.
  Multiple stacks can be designed later if that proves valuable.

  ## The deep module

  I would introduce ObjectiveStackCoordinator in the Python exterior. Its small interface
  should be approximately:

  inspect(objective_id) -> StackSnapshot
  prepare(node_id) -> LayerContext
  publish(plan_ref, pr) -> PublishResult
  sync(objective_id, changed_branch) -> SyncResult
  land(objective_id, merge_action) -> LandResult

  It hides:

  - Objective graph validation and layer projection.
  - Node → plan issue → plan branch → PR resolution.
  - Planning/implementation base selection.
  - GitHub stack creation and extension.
  - Worktree-aware cascading rebases.
  - Merge preflight and async polling.
  - Post-merge batch finalization.

  The TypeScript interior should only provide warm doors and decode these Python worker
  results, following today’s submit/land delegation pattern. Stack mechanics span sessions and
  worktrees, so the repo’s own docs/design/first-principles/cli-vs-pi.md place them squarely in the
  exterior.

  ## End-to-end workflow

  1. The bottom node plans and implements normally from the objective’s trunk.
  2. /submit opens its draft PR. It is not yet a native stack—GitHub requires at least two
     PRs.

  3. That published branch makes the next node build-ready.
  4. /objective-plan launches in a detached, read-only worktree at the parent branch tip.
  5. The child plan saves with stack_parent=plan-<parent-plan-id>.
  6. implement creates plan-<child-id> from origin/<stack_parent>.
  7. /submit creates or retargets the PR against its immediate parent, then creates/extends
     the GitHub stack through the REST API.

  8. Review proceeds concurrently, bottom-up. Every PR must be explicitly marked ready.
  9. perk objective land <id> or /objective-land validates the complete objective stack and
     merges through the top PR.

  10. After GitHub confirms the merge, perk finalizes every plan and node idempotently, closes
     the objective, schedules the existing per-plan learn passes, and drives one cumulative
     objective reconciliation.

  The explicit objective-level land surface is important. Ordinary /land should not
  unexpectedly merge several PRs.

  ## GitHub integration

  Add stack operations to the existing Python GitHub gateway:

  - Read stack membership from PR resources.
  - Create a stack from ordered PR numbers.
  - Append PRs to an existing stack.
  - Update an existing PR’s base when necessary.
  - Submit and poll merge-async.
  - Probe feature availability.

  This avoids requiring the gh-stack extension locally or in remote runners. The installed
  environment currently has compatible gh and Git versions but not the extension, which
  reinforces using gh api like the rest of perk’s gateway.

  perk pr submit should remain responsible for the plan-specific PR body and header updates.
  The coordinator should then register the resulting PR with the remote stack. If registration
  fails, the ordinary chained PR remains recoverable and retrying converges.

  ## The hardest implementation: stack synchronization

  Feedback on a lower PR invalidates every branch above it. This must be a first-class
  operation, not an incidental git rebase.

  The coordinator should:

  1. Fetch all stack branches and capture local and remote SHAs.
  2. Require every affected worktree to be clean.
  3. Refuse upstack branches containing unpublished commits unless explicitly included.
  4. Rebase each child in its own worktree using:

     git rebase --onto <new-parent-tip> <old-parent-tip> <child>

  5. Roll back every locally rewritten branch if any layer conflicts.
  6. Push all rewritten refs with explicit leases, preferably atomically.
  7. Revalidate PR bases and GitHub stack composition.

  This is where perk can improve on erk. Erk’s Graphite design accumulated dual-source cache
  divergence and skipped branches checked out in other worktrees. Perk should make worktree
  awareness part of the stack module’s invariant rather than an exception.

  ## Landing and finalization

  Extract an idempotent finalize_merged_plan(...) from individual land. Both ordinary land and
  stack land should reuse it for:

  - Plan-issue closure.
  - Canonical learn_state.
  - Node completion.
  - Learn-consumption bookkeeping.
  - Activity emission.

  Stack land then becomes:

  preflight whole stack
  → async merge top PR with expected head SHA
  → poll/observe
  → refetch every PR
  → finalize confirmed merged plans
  → close objective when all nodes terminal
  → one objective reconcile

  If GitHub reports enqueued, do not mark anything done yet. A later invocation observes
  actual merged PRs and resumes finalization.

  ## Suggested delivery sequence

  1. Add the delivery and stack_parent contracts plus a read-only inspect projection.
  2. Support two-layer stack creation through plan, implement, and submit.
  3. Add detached parent-based planning and supervisor selection.
  4. Add worktree-aware cascade synchronization and address propagation.
  5. Add objective-level async land and shared post-merge finalization.
  6. Add doctor checks, remote-runner coverage, user docs, contract amendments, and CI
     guidance.

  The essential architectural decision is: an objective stack is not a new kind of plan or a
  wrapper around gh stack; it is a delivery strategy coordinating ordinary plans through one
  deep exterior module. That preserves perk’s strongest invariants while giving the objective
  a genuine all-nodes review and landing boundary.
