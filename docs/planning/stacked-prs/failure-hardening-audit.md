# Failure-hardening audit — the stacked-delivery proof ledger

The node 6.1 proof ledger: every named failure class in the node maps to concrete, named
evidence tests (pre-existing or added by the hardening pass), and every irreversible boundary
in the four journaled mutation protocols maps to a kill-at-the-boundary cell. Rows that were
already discharged by the Phase 1–5 suites cite them; the hardening pass added tests only for
the genuinely-unenforced cells (the audit-first discipline of
`docs/learned/workflow/execution-path-parity.md`).

**The hermetic/live split:** everything here is offline — real git substrate (bare-remote
fixtures, real clones, real leases) composed with stateful fake backends. Live wire proofs
(real GitHub native stacks, real merge-async, branch protection) belong to node 6.2's dogfood
and are deliberately absent from this ledger.

> **Live complement (2026-08-13):** node 6.2's
> [`stacked-delivery-dogfood.md`](../../design/stacked-delivery-dogfood.md) **PASSED**. Real
> GitHub accepted the 3-layer stack merge; an out-of-process journal watcher SIGKILLed the land
> worker after `accepted` and before terminal observation (the L3 boundary); cold recover from
> a second clone classified `all_after` and rolled the original operation forward through
> finalization, objective close, and reconcile evidence. The same run proved one live
> lower-layer feedback suffix cascade. Branch protection, retained conflict, and external-prefix
> breach routes did not fire and remain exactly bounded by this offline ledger.

## The death-simulation technique rule

An injected raise is **not** process death — Python still runs `finally` blocks and exception
handlers. The standard technique is **post-crash durable-state construction**: build the exact
durable state the boundary leaves behind (journal records, remote refs on a fixture remote,
real residue), then run the public rerun/recovery surface. A fail-once raise is permitted
**per cell** only where the audit verified no exception-path cleanup mutates durable state
between the boundary and process exit. Each matrix row names its technique:

- **construct** — post-crash durable-state construction + public-surface rerun/recover.
- **raise** — fail-once injected raise + same-surface rerun. Verified faithful for:
  - *publish*: `_run_protocol`/`_complete_publication`/`_converge_stack` have no
    exception-path cleanup that mutates durable state.
  - *sync completion-side cells (S4/S4b/S5)*: faithful **for the durable axes only** —
    sync's `finally` cleanup (`_cleanup`) touches machine-local residue (temp refs,
    isolated worktrees), which is exactly S1's separately-proven cell. This caveat is
    pinned in the suite comment above the S-cells.
  - *transfer over Linear*: injection at GraphQL-mutation granularity; the transfer
    protocol has no exception-path durable cleanup.
- No subprocess/SIGKILL harness anywhere (nondeterministic, slow — deliberately rejected).

## Named-proof table

One row per failure class named in the node text. `file::test` citations; parametrized tests
cover every listed arm.

| # | Failure class | Evidence | Notes |
| --- | --- | --- | --- |
| 1 | Gateway eventual consistency (journal append/read-back) | `tests/test_delivery_persistence.py::TestAppendPrepared` — `test_ambiguous_landed_recovers_without_duplicate`, `test_ambiguous_lost_retries_once_and_lands`, `test_ambiguous_lost_twice_is_typed_and_bounded`, `test_invisible_read_back_retries_once_then_converges`, `test_invisible_read_back_twice_is_typed_and_bounded`, `test_read_back_conflict_is_corruption`, `test_idempotent_re_append`, `test_conflicting_re_append_is_corruption` | The one-bounded-retry read-back discipline. The Linear carrier's end-to-end equivalents: `tests/test_linear_journal.py` plus the new `tests/test_delivery_transfer_linear.py::test_journal_append_post_failure_earns_the_one_bounded_retry` and `::test_journal_append_landed_but_raised_is_proven_present_never_duplicated`. |
| 1b | Gateway eventual consistency (PR facts settling after a push) | `tests/test_delivery_sync.py::test_pr_settle_poll_converges_on_a_stale_then_current_read`, `::test_pr_still_stale_after_the_poll_is_pr_drift`, `tests/test_delivery_publish.py::test_remote_settling_timeout_when_pr_never_reflects_the_push` | Bounded settle-polls with injected no-op sleeps; exhaustion is typed drift, never a false success. |
| 2 | Preview removal / stack-read degradation | `tests/test_github_stacks.py::test_pr_stack_schema_rejection_degrades_to_unavailable`, `::test_pr_stack_malformed_payload_degrades_to_unavailable`, `::test_pr_stack_malformed_entry_degrades_to_unavailable`, `::test_pr_stack_missing_page_info_degrades_to_unavailable`; `tests/test_delivery_observe.py::TestRepoDeliveryGitHub::test_pr_stack_failure_degrades_to_unavailable`, `::test_pr_stack_unavailable_passthrough`; `tests/test_delivery_train.py::TestMembership::test_unavailable_preview_read_is_information_only` | The preview read degrades to `available=False` without poisoning stable reads; status stays information-only. |
| 3 | Exact-lease races | Real bare remote: `tests/test_git.py::test_push_with_exact_lease_stale_expect_is_rejected`, `::test_push_with_exact_lease_absence_lease_rejected_when_ref_exists`, `::test_push_atomic_with_leases_rejects_stale_then_moves_all_refs` (all-or-nothing on a genuinely stale lease). Hermetic operation-level arms: `tests/test_delivery_publish.py::test_lease_rejection_leaves_the_operation_unresolved`, `tests/test_delivery_sync.py::test_push_rejected_all_before_abandons_with_proof`, `::test_push_rejected_mixed_observation_is_sync_drift_unresolved`, `::test_push_rejected_unreadable_refetch_is_postcondition_unverified` | The remote arbitrates; a rejected lease leaves a recoverable unresolved operation, never a partial push. |
| 4 | Atomic-push refusal (unsupported capability) | Real Git: `tests/test_git.py::test_probe_atomic_push_refuses_a_capability_suppressed_transport`, `::test_push_atomic_with_leases_capability_suppressed_transport_moves_no_ref`. Façade operation gate: `tests/test_delivery_sync.py::test_atomic_push_unsupported`; adapter conversion: `tests/test_delivery_observe.py::TestRepoDeliveryGit::test_atomic_push_converts_success_and_expected_failure`. | The real refusal transport is `receive.advertiseAtomic=false` — the server stops advertising the capability and the *client* refuses (`does not support --atomic`), which is the named class. A `pre-receive` hook rejection would prove policy refusal, a different class — never recorded against this cell. The Git authority owns the probe; private `capability.py` only formats the stable caveat rows. |
| 5 | Process death at every irreversible boundary | The four matrices below | — |
| 6 | Stale prepared records (corroboration, **no age policy**) | Blocking: `tests/test_delivery_land.py::test_zero_layers_with_an_unresolved_operation_is_blocked` (all five kinds), `::test_any_unresolved_operation_kind_blocks`, `tests/test_delivery_publish.py::test_foreign_unresolved_operation_refuses` (all five kinds), `tests/test_delivery_sync.py::test_foreign_unresolved_kind_refuses` (publish/transfer/land), `tests/test_delivery_transfer.py::test_unresolved_foreign_kind_refuses_with_the_owning_resume`. Drifted-world corroboration: `tests/test_delivery_recover.py::test_republish_record_with_a_deleted_branch_is_mixed_never_abandonable`, `::test_sync_record_with_a_deleted_branch_is_mixed_never_abandonable`, `tests/test_delivery_sync.py::test_resume_deleted_branch_is_sync_drift_fail_closed`, `::test_resume_corroboration_drift_rows`. Foreign lineage: `tests/test_delivery_sync.py::test_resume_foreign_lineage_record_is_sync_drift`, **new** `tests/test_delivery_recover.py::test_publish_record_with_a_foreign_lineage_classifies_mixed` | User-confirmed: the proof is corroboration, not expiry — strict decode, fresh-authority corroboration, one-unresolved-per-lineage blocking; never blind trust, never silent discard. |
| 6b | The honest null-before nuance | `tests/test_delivery_recover.py::test_fresh_publish_record_with_a_deleted_branch_is_all_before_by_design` (with the positive PR-absence proof: `::test_publish_all_before_with_no_recorded_pr_requires_positive_pr_absence`, `::test_publish_all_before_accepts_a_positively_absent_pr`) | A fresh-publish record (`before.branch.sha = null`) whose branch was pushed then deleted is byte-for-byte the recorded all-before state. The classifier's `all_before` is **correct**: deletion is indistinguishable from never-pushed without a history/tombstone authority, which this scope forbids. Pinned as design, not gap. |
| 6c | Foreign-objective records | `tests/test_delivery_persistence.py::TestAppendPrepared::test_objective_identity_mismatch_fails_closed`, `::TestAppendPrepared::test_lineage_mismatch_fails_closed`, `::TestReadJournal::test_foreign_lineage_event_never_folds` | Enforced structurally at the append gate (per-objective carrier + the §8.43 objective-id cross-check); recovery reads only the objective's own carrier. No recovery-time objective-identity check is invented. |
| 6d | LAND pre-handle age arms | `tests/test_delivery_recover.py::test_no_handle_async_young_is_monotonic_only_with_the_remaining_wait`, `::test_no_handle_unknown_age_is_monotonic_only_never_a_crash`, `::test_no_handle_async_aged_is_observation_authoritative` | The one existing time-based rule (LAND's 24-hour merge-request lifetime) — cited, not extended. Unknown age fails closed young. |
| 7 | Dirty / active / absent worktrees | Axis derivation: `tests/test_delivery_train.py::TestGitAxis::test_writer_axis_from_worktrees`, real inspection `tests/test_delivery_observe.py::TestRepoDeliveryGit::test_worktree_branches_maps_the_writer_axis`. Refusals: `tests/test_delivery_sync.py::test_dirty_worktree_refuses`, `::test_clean_active_worktree_does_not_block`, `::test_active_remote_writer_refuses`, `::test_writer_probe_failure_fails_closed`, `tests/test_delivery_land.py::test_dirty_worktree_blocks`, `::test_active_clean_worktree_is_information_only`, `::test_active_remote_writer_blocks_naming_the_plans`, `::test_landed_layer_writer_state_never_blocks`, `tests/test_delivery_transfer.py::test_dirty_worktree_refuses_on_the_stacked_path`, `::test_dirty_worktree_refuses_on_the_incremental_path`, `::test_active_writer_refuses`, `tests/test_delivery_sync.py::test_continue_dirty_claimed_worktree_refuses_and_retains` | Absent worktrees are the normal (never-blocking) state; residue worktrees are owned by the sweep (`tests/test_delivery_recover.py::test_sweep_removes_unprotected_residue_refs_then_worktrees_then_prune`, real residue in `tests/test_delivery_sync_integration.py::test_orphan_sweep_removes_real_residue_and_prunes`). |
| 8 | Cross-machine continuation | **New lane** `tests/test_delivery_cross_machine.py`: `::test_sync_all_after_concludes_from_a_fresh_clone`, `::test_sync_all_before_abandons_with_proof_from_a_fresh_clone`, `::test_publish_bottom_layer_all_after_reports_then_submit_resume_completes`, `::test_publish_non_bottom_partial_reports_mixed_then_submit_resume_converges`, `::test_land_accepted_handle_concludes_from_a_fresh_clone`, `::test_transfer_manifest_rolls_forward_on_fresh_seams`, `::test_machines_share_no_local_state` | One real bare origin + two real clones; machine B is a separately created fresh clone with separately constructed seams (every git seam asserts its own clone root — A's tree is structurally unreachable). The shared durable authorities are exactly the origin's refs and the stateful fake backend (journal, PRs, stack, objectives). **ADOPT is deliberately not a separate arm**: it shares SYNC's record-recovery core (the §8.51 region of `sync.py`); its classification/roll-forward arms are `tests/test_delivery_sync.py::test_resume_adopt_all_after_rolls_forward_record_driven`, `::test_resume_adopt_all_before_abandons_then_fresh_takes_the_invocation_flags`, `tests/test_delivery_recover.py::test_adopt_record_rolls_forward_identically` — this row maps ADOPT onto that evidence. |
| 9 | Linear partial transfers | **New lane** `tests/test_delivery_transfer_linear.py` (real `LinearProjectObjectiveStore` + `LinearIssueBackend` over `FakeLinearWorkspace`, fail-once injection at GraphQL-mutation granularity): `::test_uninterrupted_transfer_converges_over_the_real_linear_stack`, `::test_pre_sentinel_death_leaves_an_inert_project_and_the_rerun_stays_safe`, `::test_partial_ownership_death_rolls_forward_via_recover_without_duplicates`, `::test_interrupted_fresh_node_attachment_is_resumed_by_the_found_arm`, `::test_journal_append_post_failure_earns_the_one_bounded_retry`, `::test_journal_append_landed_but_raised_is_proven_present_never_duplicated` | The store-internal write granularity `docs/learned/workflow/objective-delivery.md` requires. No duplicated objectives, plans, comments, or journal events across every window; an inert pre-sentinel Project is tolerated, never adopted. |
| 10 | Remote-runner parity | `tests/test_run_worker.py::test_positioning_parity_local_launch_vs_remote_worker`, `::test_positioning_parity_stacked_local_create_vs_remote_position`, `::test_position_branch_stacked_not_ready_is_a_typed_refusal` | Plus row 8's lane, which discharges the fresh-checkout posture itself: a separately initialized clone concluding a real delivery operation from durable authorities only — the remote runner's exact position. |
| 11 | Async merge timeouts / ambiguity | `tests/test_delivery_landing.py::test_poll_timeout_stays_pending_with_accepted_and_no_terminal`, `::test_still_ambiguous_submit_stays_pending`, `::test_discordant_submit_replies_stay_ambiguous`, `::test_unparseable_2xx_submit_is_ambiguous_not_success`, `::test_enqueued_stops_immediately_as_unexpected_enqueued`, `::test_per_tick_poll_failures_are_tolerated_within_budget`, `::test_ambiguous_submit_retries_exactly_once_then_409_recovers_the_handle`, `::test_retry_side_rejection_never_abandons_a_possibly_applied_first_attempt`; recovery side: `tests/test_delivery_recover.py::test_live_probe_is_in_flight_for_every_shape`, `::test_unreadable_probe_is_monotonic_only`, `::test_probe_merged_with_uncorroborated_observation_is_in_flight_never_mixed` | An unconcludable landing stays an honest unresolved `pending` — never re-submitted, never falsely terminal. |
| 12 | External prefix merges | `tests/test_delivery_recover.py::test_terminal_probe_prefix_classifies_external_prefix`, `::test_accept_prefix_journals_the_breach_and_finalizes_the_prefix_only`, `::test_accept_prefix_membership_change_after_confirmation_is_accept_blocked`, `::test_accept_prefix_on_a_non_external_target_is_accept_blocked`, `::test_accept_prefix_declined_journals_nothing`, `::test_drifted_remainder_head_is_mixed_not_external_prefix`, `::test_non_prefix_drift_arms_are_mixed_and_journal_nothing` | The contiguous-prefix acceptance is explicit (`--accept-prefix` + confirm) and journaled as a degraded-atomicity breach; anything non-prefix is mixed, fail closed. |
| 13 | Post-merge bookkeeping failures | `tests/test_delivery_landing.py::test_completed_append_failure_degrades_to_merged_with_note`, `::test_completed_append_store_failure_degrades_to_merged_with_note`, `::test_finalize_failure_notes_and_remaining_layers_still_finalize`, `::test_consumed_learn_read_failure_finalizes_without_it`, `::test_aggregate_close_fail_open`; convergence: `tests/test_delivery_recover.py::test_roll_forward_finalize_failure_is_isolated_and_loud`, `::test_roll_forward_completed_append_failure_degrades_and_the_rerun_converges`, `::test_convergence_refinalizes_every_covered_corroborated_layer` | Bookkeeping failures degrade loudly and converge on a later recover pass; the merge itself is never re-attempted. The L7 close-then-evidence window was the one real hole — fixed by this pass (see the LAND matrix). |
| 14 | Absent delivery metadata follows the existing paths | `tests/test_objective.py::test_delivery_policy_classifier`, `::test_objective_header_delivery_omitted_when_absent`; `tests/test_objective_cmd.py::test_create_no_delivery_flag_stores_both_none`, `::test_create_explicit_incremental_behaves_like_absent`; `tests/test_objective_shared.py::test_incremental_objective_returns_none_without_reconstructing`, `::test_junk_delivery_policy_fails_closed`; `tests/test_delivery_train.py::TestPolicy::test_incremental_objective_is_a_successful_no_train`, `::test_junk_delivery_policy_fails_closed`. **New guard:** `tests/test_delivery_policy_guard.py` | The guard (a `tests/test_write_guard.py`-recipe source scan per `docs/learned/workflow/source-scan-guards.md`) pins the census: the quoted `delivery` header-key literal appears in exactly four production homes — `objective/parse.py` (the **single reader**: `delivery_policy`), `objective/render.py` (emission), `objective/_models.py` (field census), `delivery/transfer.py` (manifest payload) — so policy consumption cannot silently grow a scattered compatibility branch. Textual, not semantic: a regression backstop, not a completeness proof. The seven production `delivery_policy` call sites at audit time: `delivery/train.py`; `cli/commands/objective/create_cmd.py`, `plan_cmd.py`, `replan_cmd.py`, `run_cmd.py`, `shared.py`; `cli/commands/plan/save_cmd.py`. |

## Irreversible-boundary matrices

One row per actual mutator boundary (verified against `_run_protocol`/`_complete_publication`/
`_converge_stack` in `publish.py`; `_fresh`/`_execute`/`_push`/`_persist_completion` in
`sync.py`; `_land`/`_land_async`/`_land_singleton`/`_verify_and_finalize`/`_finalize_layers`/
`state_aware_close` in `landing.py`; and `recover.py`'s convergence pass). Convergence
assertions per cell: exactly one `prepared` + one terminal record per operation, converged
identity/checkpoints, and **no duplicate non-idempotent remote effect** (PR creation, reopen,
base retarget, stack create/append, merge submission), while the resume contract's named
idempotent re-upserts (the PR create/discovery pass, `update_pr_body`, checkpoint
merge-writes) are allowed and never asserted to zero.

### PUBLISH (`tests/test_delivery_publish.py`; **raise**-technique except P7 — verified no exception-path durable cleanup)

Every behavioral row now enters through `Delivery.publish(PublishRequest(kind="layer"))` over the
aggregate-backed world and a scoped private runtime; only pure payload/proof helpers retain direct
internal calls. `test_lower_layer_publish_enters_the_bound_sync_lock_exactly_once` additionally
proves the nested bound sync dispatcher enters the non-reentrant operation lock exactly once.

| Cell | Died… | Evidence |
| --- | --- | --- |
| P1 | after `append_prepared`, before the leased push | `test_crash_before_the_leased_push_retries_under_the_same_operation` (retry under the SAME operation) |
| P2 | after `_push_with_lease`, before any PR effect | `test_crash_after_push_before_pr_effects_rolls_forward_the_same_operation` |
| P3a | after the fresh PR create | `test_crash_after_fresh_pr_create_resumes_via_idempotent_discovery` (rediscovery by head — never a second PR) |
| P3b | after reopening a reused CLOSED PR | `test_crash_after_reopen_never_repeats_the_reopen` |
| P3c | after the PR base retarget | `test_crash_after_base_retarget_never_repeats_the_retarget` |
| P3d | after `update_pr_body`, before the stack mutation | `test_crash_after_body_update_completes_stack_work_exactly_once` |
| P4a | after the stack **create** (layer 2), before the refetch | `test_crash_after_stack_create_before_refetch_resumes_without_second_mutation` |
| P4b | after a stack **append** (layer ≥ 3), before the refetch | `test_crash_after_stack_append_before_refetch_resumes_without_second_append` |
| P5 | after the plan-header identity write | `test_crash_after_identity_write_resumes_without_duplicate_mutation` (pre-existing) |
| P6 | after the checkpoint write, before `completed` | `test_crash_before_the_completed_append_converges_on_rerun`; the checkpoint-write window itself: `test_crash_at_checkpoint_write_resumes_idempotently` (pre-existing) |
| P7 | after `completed` | `test_rerun_after_completed_is_a_converged_noop` (construct — a genuine full run + ordinary rerun, no injected raise; the SYNC S5 row's technique) |

The publish stateful fake grew fail-once hooks at each PR-effect and stack-mutation seam
(`push_boom`, `create_pr_boom`, `after_effect_boom{reopen,retarget,body}`, `outcome_boom`,
stateful `write_checkpoints`) — it previously had none at P3a–P3d.

Cross-machine variants (construct-technique, real origin; clone B resumes through the same
`Delivery.publish` façade):
`tests/test_delivery_cross_machine.py::test_publish_bottom_layer_all_after_reports_then_submit_resume_completes`
(P2/P3a-shaped death; recover's conclude-only report + the resume completing from clone B) and
`::test_publish_non_bottom_partial_reports_mixed_then_submit_resume_converges` (P3d-shaped
death; the honest MIXED report — a non-bottom `after` includes stack membership — then the
cross-machine stack convergence).

### SYNC (`tests/test_delivery_sync.py` unless noted)

| Cell | Died… | Technique | Evidence |
| --- | --- | --- | --- |
| S1 | during candidate calculation (temp refs + isolated-worktree residue) | construct (real residue) | `tests/test_delivery_sync_integration.py::test_orphan_sweep_removes_real_residue_and_prunes`; hermetic sweep ordering `tests/test_delivery_recover.py::test_sweep_removes_unprotected_residue_refs_then_worktrees_then_prune`; the conflict-retention path `test_rebase_conflict_retains_residue_under_a_manifest`, `test_continuation_gate_refuses_a_fresh_sync`. Never raise-based — sync's `finally` cleanup would destroy exactly this residue. |
| S2 | after `append_prepared`, before the atomic push (all-before) | construct | `test_resume_all_before_abandons_with_proof_and_prepares_fresh`; recover report `tests/test_delivery_recover.py::test_sync_all_before_is_reported_with_the_owning_command_hint`; cross-machine `tests/test_delivery_cross_machine.py::test_sync_all_before_abandons_with_proof_from_a_fresh_clone` (real origin proves the refs never moved) |
| S3 | after the atomic push, before verification (all-after) | construct | `test_resume_all_after_rolls_forward_under_the_same_operation`; recover `tests/test_delivery_recover.py::test_sync_all_after_target_rolls_forward_automatically`; cross-machine `tests/test_delivery_cross_machine.py::test_sync_all_after_concludes_from_a_fresh_clone` (a real atomic-leased push from clone A, concluded from clone B) |
| S4 | after some-but-not-all checkpoint writes in `_persist_completion` | raise (durable-axes-faithful; see the technique rule) | `test_crash_mid_checkpoint_writes_rolls_forward_on_rerun` |
| S4b | after all checkpoints, before `completed` | raise | `test_crash_after_all_checkpoints_before_completed_converges_on_rerun` |
| S5 | after `completed` | construct (a genuine full rerun) | `test_rerun_after_completed_is_the_typed_noop` |

ADOPT rides this table (same `_execute`/`_push`/`_persist_completion` core); its record-driven
arms: `test_resume_adopt_all_after_rolls_forward_record_driven`,
`test_resume_adopt_all_before_abandons_then_fresh_takes_the_invocation_flags`,
`tests/test_delivery_recover.py::test_adopt_record_rolls_forward_identically`.

### LAND (`tests/test_delivery_landing.py` / `tests/test_delivery_recover.py`; all construct-technique — the recover suites seed the exact post-crash journal + observation state)

| Cell | Died… | Evidence |
| --- | --- | --- |
| L1 | after `append_prepared` (read back), before the merge-async submit | recover's pre-handle rows: `test_no_handle_async_young_is_monotonic_only_with_the_remaining_wait`, `test_no_handle_unknown_age_is_monotonic_only_never_a_crash`, `test_terminal_probe_all_before_classifies_all_before` |
| L2 | after a submit with a pending reply, before the `accepted` append | same pre-handle window (no handle exists): `test_no_handle_async_aged_is_observation_authoritative` (the 24h lifetime turns observation authoritative), `test_no_handle_async_young_is_monotonic_only_with_the_remaining_wait` |
| L2m | after a submit whose reply is immediately `merged` (no `accepted` ever), before verification | `test_no_handle_async_aged_is_observation_authoritative` + prefix/all-after classification from pure observation; the handle×shape completeness pin `test_handle_by_shape_table_is_complete` |
| L2s | after the dynamic singleton's `merge_direct` mutation (no handle exists on this path), before verification | the non-dry convergence proof `test_singleton_merge_direct_death_before_verification_concludes_on_recover` (post-crash merged-singleton state → real recover rolls forward: one completed under the same operation, finalize, close — and no probe/accepted/re-submission, which the recover surface cannot even express); classification arms `test_singleton_record_is_observation_authoritative_and_never_prefix`, `test_singleton_handle_row_is_observation_authoritative` |
| L3 | after `accepted`, before the poll concludes | `test_live_probe_is_in_flight_for_every_shape` (probe in-flight → monotonic only), `tests/test_delivery_cross_machine.py::test_land_accepted_handle_concludes_from_a_fresh_clone` (probe merged → concluded from clone B); in-process analogue `tests/test_delivery_landing.py::test_poll_timeout_stays_pending_with_accepted_and_no_terminal` |
| L4 | after per-PR merged verification, before `completed` | `test_land_all_after_rolls_forward_automatically`, `test_land_all_after_with_probe_merged_records_the_reported_sha`; the degrade arm `test_roll_forward_completed_append_failure_degrades_and_the_rerun_converges` |
| L5 | after `completed`, mid per-layer finalization | `test_convergence_refinalizes_every_covered_corroborated_layer` (also proves the close conclusion), `test_roll_forward_finalize_failure_is_isolated_and_loud`; in-process analogue `tests/test_delivery_landing.py::test_finalize_failure_notes_and_remaining_layers_still_finalize` |
| L6 | after finalization, before the aggregate close | the convergence pass closes on rerun: `test_convergence_refinalizes_every_covered_corroborated_layer` (`objective_closed is True`); the in-process fail-open `tests/test_delivery_landing.py::test_aggregate_close_fail_open`, `::test_aggregate_close_skipped_while_nodes_remain` |
| **L7** | **after `store.close_objective` succeeds, before reconcile evidence is emitted** | **New — the one real recovery hole this audit's planning pass found, fixed by this pass** (production edit #2): `test_death_after_close_reemits_reconcile_evidence_on_recover` (the landing-close arm), `test_death_after_nothing_to_land_close_reemits_the_journal_history` (the `NOTHING_TO_LAND` arm), the honest at-least-once pin `test_death_after_close_reemission_repeats_on_every_recover`, and the fail-closed negatives `test_reemission_waits_for_a_converged_journal`, `test_reemission_requires_every_node_terminal`, `test_reemission_never_rides_a_dry_run` |
| — | rerun after terminal | `test_no_unresolved_and_no_residue_is_a_clean_report`, `test_convergence_excludes_layers_concluded_this_invocation`, `test_convergence_close_on_a_closed_objective_reports_false` |

**The L7 fix (contracts §8.51/§8.56, amended in the same turn):** before this pass, both
`landing.py` and `recover.py`'s convergence pass ran the aggregate close **before** assembling
reconcile evidence, and evidence attached only on a *real* close transition — so death after
`store.close_objective` suppressed the reconcile drive **permanently** (a rerun saw "already
closed" and never re-assembled). `recover.py` now re-emits fresh-fold evidence for an
already-closed, journal-complete objective (all nodes terminal, no unresolved LAND), with a
loud at-least-once note; `objective_closed` stays honestly `false` on re-emission, so the
extension's `driveStackReconcile` gate widened from `objective_closed === true` to evidence
presence (`extension/doors/objectiveStack.test.ts` pins the drives-anyway case). Deferred
fail-closed while any LAND is unresolved or any node non-terminal; never on `--dry-run`.

### TRANSFER (`tests/test_delivery_transfer.py` — pre-existing exhaustive matrix; ledger mapping only)

| Window | Evidence |
| --- | --- |
| Interrupted mid-protocol, same-run rerun | `test_rerun_same_run_rolls_forward_from_the_recorded_manifest`, `test_interrupted_transfer_reruns_to_completion_without_duplicates` |
| Different run, live successor | `test_rerun_different_run_with_a_live_successor_refuses_transfer_incomplete` |
| No successor materialized | `test_rerun_with_no_successor_abandons_with_proof_then_completes_fresh` |
| Non-journaled conversion windows | `test_non_journaled_conversion_interrupted_mid_ownership_converges_by_construction`, `test_non_journaled_conversion_interrupted_after_the_finalize_stamp_re_finalizes`, `test_interrupted_conversion_rerun_converges_the_clear_writes` |
| Verification-side failures stay unresolved | `test_infra_failure_during_verification_propagates_and_stays_unresolved`, `test_verification_catches_a_never_materialized_carried_plan`, `test_verification_catches_a_diverged_successor_projection` |
| Recover-owned conclusions | `tests/test_delivery_recover.py::test_transfer_all_after_rolls_forward_to_completion`, `::test_transfer_all_before_abandons_with_proof_confirmed`, `::test_transfer_corroboration_mismatch_is_mixed`, `::test_transfer_corrupt_manifest_is_a_report_only_row` |
| Composed-backend (Linear) windows | row 9 of the named-proof table (`tests/test_delivery_transfer_linear.py`) |
| Cross-machine conclusion | `tests/test_delivery_cross_machine.py::test_transfer_manifest_rolls_forward_on_fresh_seams` (fresh backend-only `TransferSeams`; ownership/finalize/completion each exactly once) |

## Envelope conclusions

- **Exactly two production edits shipped, both named in the plan:**
  1. `objective doctor --json` promoted to the schema-snapshotted `ObjectiveDoctorOut`
     (`shared/schemas/outputs/objective-doctor.schema.json`) — **byte-identical emission**,
     deliberately a pin and not a normalization. The only conditional key, `RepairAction.error`
     (§8.54: present on the failed action only), is preserved by a wrap serializer with a
     direct omission test (`tests/test_objective_doctor_cmd.py::test_fix_manifest_action_serialization_preserves_the_conditional_error_key`);
     the pre-existing `test_objective_doctor_cmd.py` key-order pins passing **unchanged** is
     the no-drift acceptance. *Recorded caveat:* Pydantic's serialization-mode JSON schema
     still declares `error` as a nullable property — it cannot express conditional omission —
     so the snapshot is a **drift tripwire, not an instance validator**.
  2. The L7 close-then-evidence fix above — **cross-plane, two seams**: recover's
     `reconcile_evidence` **population rule** widened (no new envelope field;
     `ObjectiveStackRecoverOut` already carried it), **and** the warm consumer's
     `driveStackReconcile` gate widened from `objective_closed === true` to evidence
     presence (`extension/doors/objectiveStack.ts`). The gate widening is the re-fire the
     plan's Key change 3 mandates ("the attached evidence re-fires the existing
     `driveStackReconcile` consumer exactly as a fresh close transition would"): the
     re-emission honestly reports `objective_closed: false`, so without the consumer-side
     widening the repair would be dead code. Recorded on the plan issue as the edit's
     cross-plane scope (contracts §8.51/§8.56 amended in the same turn).
- Every other enumerated proof is expressible in the existing `status`/`sync`/`recover`/`land`
  envelopes — no envelope shape changed anywhere else.
- **Out of scope (observed, recorded):** the doctor envelope was not the repo's only
  unsnapshotted hand-built `--json` envelope — `objective/create_cmd.py`, `run_cmd.py`,
  `next_cmd.py`, `show_cmd.py`, and `gist/*_cmd.py` also hand-build JSON. This pass promoted
  only the envelope its proofs touch; the rest are a candidate census for a future pass.
- **No additional production defects surfaced** by the new proofs beyond the L7 hole the
  planning pass had already identified; nothing was fixed ad hoc outside the two named edits.
