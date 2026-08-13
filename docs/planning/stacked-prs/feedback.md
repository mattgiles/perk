## Verdict

  No, you are not off the rails.

  This is fucking excellent engineering—but it is not yet a finished, proven product. Scope
  gained mass, mostly through necessary safety depth rather than feature creep. The original
  architectural elegance survived.

  Current state:

  - 15 of 18 objective nodes done.
  - 15 merged PRs: 54,818 additions / 2,948 deletions.
  - Active recovery PR #1664 (https://github.com/mattgiles/perk/pull/1664): another 5,660
    additions.

  - Every merged PR had clean checks.
  - Main: 4,891 Python tests pass; the full Node suite passes after dependency sync.
  - The 5.4 draft’s targeted recovery suite: 694 tests pass.

  ## What went exceptionally well

  The implementation honored the canonical docs/planning/stacked-prs/objective.md:23 and docs/
  planning/stacked-prs/architecture.md:33:

  - Stacking remained an objective policy coordinating ordinary plans.
  - Durable truth is reconstructable without local stack metadata.
  - Git, GitHub, backend, and roadmap authorities remain distinct.
  - Python owns durable operations; TypeScript only drives and renders them.
  - GitHub instability is localized in one native adapter.
  - Sync uses isolated candidate work, exact leases, and atomic pushes.
  - Landing uses one atomic GitHub operation—no dishonest sequential fallback.
  - Recovery is journaled, idempotent, cross-machine, and fail-closed.
  - The CLI stayed narrow: status, sync, recover, land.
  - Contracts, user docs, schemas, and tests moved with behavior.

  The early recommendation’s chain-only model, stack_parent, and worktree-mutating cascade
  were intentionally superseded by better decisions: arbitrary DAGs with derived order, stable
  predecessor-plan identity, and isolated transactional synchronization. That is refinement,
  not drift.

  Review discipline is also real. The merged PRs accumulated 166 review submissions. For
  example, PR #1631 (https://github.com/mattgiles/perk/pull/1631) received 12 actionable
  findings—including genuinely dangerous async-merge ambiguity—and then landed a dedicated
  correction commit.

  ## Did scope bloat?

  There is scope mass, but little scope drift.

  The meaningful expansions were:

  - Phase 5 split into readiness, mutation, and recovery.
  - Publication dogfood strengthened from two to three layers.
  - Preview-API ambiguity required strict state tables and scalar-coherent reads.
  - Recovery exposed unavoidable concepts such as landed prefixes and interrupted bookkeeping.

  Those additions deepen the original atomicity/recovery promise. They do not broaden the
  product into merge queues, Graphite compatibility, generic repair, multiple trains, or
  automatic remote adoption. The non-goals held.

  ## Where elegance degraded

  The architecture is elegant; the Python interface is not yet.

  The delivery package currently exposes 113 names and defines 43 Protocols. Entrypoints such
  as src/perk/delivery/publish.py:274 and src/perk/delivery/sync.py:277 expose enormous lists
  of injectable test seams. Internal seams leaked into the external interface instead of
  sitting behind a compact production façade.

  Several operation modules are also huge—sync.py is 2,875 lines; train.py, publish.py, and
  transfer.py exceed 1,600. They have strong locality and excellent internal organization, but
  navigability will deteriorate unless followed by a deliberate interface-deepening pass.

  That is real design debt, not a reason to reject the system.

  ## Why I would not declare victory yet

  The remaining nodes are the ones that turn impressive machinery into a trusted product:

  - PR #1664 (https://github.com/mattgiles/perk/pull/1664) must survive review and full CI.
  - 6.1 must prove the live GitHub failure cases: async recovery, partial external merge,
    retarget timing, native-stack composition, and second-machine operation.

  - 6.2 must deliver a meaningful objective through the entire supported path—including
    feedback cascade and atomic landing.

  Until that happens, the happy path is implemented, but the hardest preview-era claims remain
  hermetically tested rather than operationally proven.

  My blunt assessment: A for architectural fidelity, A for safety discipline, B for interface
  elegance, and incomplete for product proof. Finish 5.4, 6.1, and 6.2 without expanding them.
  Then schedule a separate façade/seam cleanup.

  So: yes, it is fucking excellent. It just isn’t fucking done.


  ---

  I’d use these principles:

  1. Preserve behavior; change only the interface. No new recovery modes, commands, or
     semantics. Finish dogfood first, then refactor against pinned contracts and tests.

  2. Expose domain operations, not mechanisms. The external interface should resemble:

  delivery.status(objective_id)
  delivery.prepare(plan_id)
  delivery.publish(request)
  delivery.sync(request)
  delivery.recover(request)
  delivery.transfer(request)
  delivery.land(request)

  Callers should not know about journal folding, GraphQL probes, sleeps, clocks, leases,
  worktrees, or persistence factories.

  3. Accept user intent as request objects. Replace 20–30 keyword parameters with immutable
     PublishRequest, SyncRequest, RecoverRequest, and LandRequest values. Requests contain
     choices, not injected machinery.

  4. Keep the three real seams. Preserve the architecture’s authorities:

  - Train persistence
  - Git
  - GitHub-native delivery

  Clock, sleep, ID minting, individual gateway functions, and filesystem helpers are internal
  seams—not separately exposed ports.

  5. Centralize production composition. One composition root should resolve the issue backend
     and construct the production adapters. CLI commands should never assemble dependencies
     individually.

  6. Keep internal seams internal. Operation modules may retain narrow Protocols and fakes,
     but those belong inside the delivery implementation. Tests needing them are internal
     tests; workflow callers never see them.

  7. One canonical import path. Empty or drastically shrink src/perk/delivery/__init__.py:1.
     Public callers should import only the façade, requests, results, and stable error
     vocabulary—probably fewer than twenty names.

  8. Return typed outcomes; translate failures once. The module should own infrastructure-to-
     domain translation. Callers receive PublicationResult, SyncResult, etc., or one bounded
     delivery error hierarchy—not GitHub, persistence, journal, and Git exceptions separately.

  9. The façade must earn its existence. It cannot be a permanent pass-through wrapper. It
     should own reconstruction, composition, locking, operation routing, and invariants. Under
     the deletion test, removing it should force substantial complexity back into every
     caller.

  10. Test through the deepest useful seam. Keep:

  - Adapter tests for Git/GitHub/backend parsing.
  - Pure tests for decision tables and projections.
  - Most behavioral tests through the façade.

  As façade coverage becomes equivalent, delete redundant tests coupled to internal call
  graphs. Replace; don’t layer indefinitely.

  11. Do not merge the implementation into one giant file. “One deep module” means one
     coherent interface, not one class or file. train.py, sync.py, landing.py, etc. can remain
     internal operation modules.

  12. Measure success from callers. The cleanup succeeds when submit, ready, land, replan,
     doctor, and stack commands become visibly boring: construct intent, invoke one operation,
     render its result.

  The north star is: three authoritative adapters, one composition root, seven domain
  operations, small immutable request/result vocabulary, and zero delivery mechanics in
  callers.
