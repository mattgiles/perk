# Python test-suite speedup, phase 4 — slow re-classification

A **classification** record for the plan branch `plan-2589`: the testing guide's `slow` threshold
rule ("serially measured own-cost median ≥ 1.0 s") re-applied to a suite that grew from 6,966
cases (the phase-3 classification) to 7,633. The phase-3 method is reused unchanged; only the
candidate shortlist is new. Marking changes nothing the full default suite runs — every `slow`
case still runs in every full gate — so there is **no speed claim** here. Compact tables only;
the raw TSVs, logs, JUnit XML and the temporary timing plugin stayed under
`/tmp/perk-plan2589-phase4/` and are not committed.

## 1. Scope and revisions

| Item | Value |
|---|---|
| Measured revision | `ba1b4ed5` — clean (`git status --porcelain` empty) before the shortlist and after the last serial run; `git rev-parse HEAD` identical before and after every run |
| Host | macOS (Darwin 25.5.0, arm64, Apple M3 Pro, 11 cores), an uncontrolled shared workstation |
| Tools | Python 3.13.9 · pytest 9.0.3 · uv 0.12.3 |
| Environment | `PERK_PROSE_REVIEW_TESTS` and `PYTEST_ADDOPTS` unset — the opt-in prose suites were never collected |
| Before | full 7,633 · slow 23 · fast 7,610 |

## 2. Method

**Shortlist (this plan's heuristic — the guide prescribes no shortlist step).** One full-suite run
under the default configuration (`uv run pytest -q --durations=0`, six xdist workers, fresh
`--basetemp`): `7633 passed in 214.70s`. For every currently unmarked case, its `setup` and `call`
phase lines were summed; every case with setup + call ≥ 0.7 s became a candidate — **282 cases**.
Broad-scoped fixture setup is charged by `--durations` to its first consumer, so the shortlist
over-includes by design; the serial attribution below separates shared from own cost.
**Sampling limitation:** one parallel sample is not a bound on a serial median — a case that
measured under 0.7 s in the shortlist run but has a serial own-cost median ≥ 1.0 s would be
missed. The shortlist ran under host contention (1-minute load average 8.4 at start, 16.0 at the
end), which inflates parallel timings and so widens rather than narrows the net, but it is a
stated limitation, not a guarantee.

**Own cost (the phase-3 method).** Three serial `-n0` runs of the 282-case candidate set (node ids
passed through a pytest `@file` argument), each with its own `--basetemp` and `--junitxml`, under
a temporary plugin wrapping `pytest_fixture_setup` — pytest resolves a fixture's dependencies
before that hook fires, so each wrapped duration is that fixture's own function — plus
`pytest_runtest_logreport` phase durations. Own cost = `call` + Σ function-scoped fixture setup
attributed to the case; broad-scoped setup is attributed to the fixture and reported once as shared
cost; `teardown` is excluded from own cost and its raw median recorded instead.

| Run | Result | Wall s | Host load (1 min) start → end |
|---|---|---|---|
| 1 | `282 passed in 238.57s` | 244 | 13.5 → 5.1 |
| 2 | `282 passed in 221.87s` | 225 | 5.1 → 5.4 |
| 3 | `282 passed in 207.02s` | 208 | 5.4 → 4.9 |

**Rule.** `@pytest.mark.slow` on every case whose own-cost median is ≥ 1.0 s (on the test, or on
the parameter case via `pytest.param(..., marks=pytest.mark.slow)` when only one parameter case
qualifies — never on a fixture); every other candidate stays unmarked (a fast-keep).

## 3. Measurement and verdict

Own cost is the median over the three runs with min–max; setup/teardown are raw phase medians. The
shortlist column is the one parallel setup + call sample that nominated the case.

### Marked `slow` (threshold) — 57 cases

| Node id (`tests/…`) | Shortlist setup+call s | Own cost s | Setup / teardown s |
|---|---|---|---|
| `test_dot_directory_dogfood.py::test_dot_directory_fresh_drift_repair_story` | 3.12 | **2.48** (2.38–2.94) | 0.27 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_refresh_rewrites_the_patch` | 3.80 | **2.47** (2.19–2.62) | 0.09 / 0.00 |
| `test_delivery_cross_machine.py::test_publish_bottom_layer_all_after_reports_then_submit_resume_completes` | 13.73 | **2.37** (1.78–2.38) | 0.00 / 0.00 |
| `test_upgrade_notice.py::test_cli_emits_notice_on_stale_store` | 16.28 | **2.30** (0.37–3.81) | 0.34 / 0.00 |
| `test_delivery_cross_machine.py::test_sync_all_after_concludes_from_a_fresh_clone` | 12.67 | **2.22** (2.13–2.28) | 0.00 / 0.00 |
| `test_delivery_cross_machine.py::test_publish_non_bottom_partial_reports_mixed_then_submit_resume_converges` | 13.10 | **2.10** (2.00–2.26) | 0.00 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_diff_failure_refuses_before_mutation` | 2.49 | **1.96** (1.80–2.33) | 0.07 / 0.00 |
| `test_linear_lifecycle.py::test_full_lifecycle` | 2.38 | **1.80** (1.58–2.03) | 0.00 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_probe_false_or_indeterminate_preserves_existing_checkout[False]` | 2.13 | **1.76** (1.64–1.77) | 0.09 / 0.00 |
| `test_pr_review_context_cmd.py::test_stack_context_two_workers_interleaved_ref_isolation` | 2.43 | **1.71** (1.71–2.04) | 0.09 / 0.00 |
| `test_doctor.py::test_library_readme_managed_check_and_fix` | 2.14 | **1.71** (1.61–1.75) | 0.04 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_success_snapshot_envelope` | 2.42 | **1.71** (1.63–1.85) | 0.08 / 0.00 |
| `test_refinement_cross_backend_gate.py::test_phase2_gate_github_refinement_doors` | 2.26 | **1.70** (1.54–1.90) | 0.00 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_probe_false_or_indeterminate_preserves_existing_checkout[None]` | 2.59 | **1.69** (1.69–1.79) | 0.09 / 0.00 |
| `test_delivery_cross_machine.py::test_sync_all_before_abandons_with_proof_from_a_fresh_clone` | 10.49 | **1.66** (1.58–1.77) | 0.00 / 0.00 |
| `test_git.py::test_push_atomic_with_leases_rejects_stale_then_moves_all_refs` | 1.77 | **1.60** (1.29–1.62) | 0.00 / 0.00 |
| `test_doctor.py::test_skills_manifest_drift_detected_and_fixed` | 2.20 | **1.58** (1.40–1.66) | 0.05 / 0.00 |
| `test_doctor.py::test_models_drift_detected_and_fixed` | 2.11 | **1.54** (1.33–1.70) | 0.05 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_objective_arm_routes_to_objective_resolver` | 1.95 | **1.53** (1.45–1.60) | 0.06 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_warn_and_are_removed_by_fix` | 2.84 | **1.48** (1.46–1.48) | 0.04 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_fix_refuses_missing_shipped_replacement` | 2.77 | **1.46** (1.45–1.69) | 0.05 / 0.00 |
| `test_tooling.py::test_subprocess_run_only_in_sanctioned_wrappers_with_check_and_timeout` | 1.44 | **1.42** (1.07–1.51) | 0.00 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_drift_note_warns_not_refuses` | 2.28 | **1.41** (1.31–1.53) | 0.07 / 0.00 |
| `test_run_worker.py::test_positioning_parity_stacked_local_create_vs_remote_position` | 2.20 | **1.41** (1.08–1.88) | 0.08 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_base_not_ancestor_of_bottom_refuses` | 1.88 | **1.39** (1.33–1.47) | 0.09 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_remote_tracking_only_base` | 2.37 | **1.38** (1.38–1.47) | 0.08 / 0.00 |
| `test_objective_refine_cmd.py::test_refinement_save_worker_saves_the_comment_and_only_the_comment` | 1.64 | **1.34** (1.20–1.42) | 0.00 / 0.00 |
| `test_doctor.py::test_fix_converges_repo_skills_drift` | 1.54 | **1.33** (1.29–2.13) | 0.04 / 0.00 |
| `test_linear_lifecycle.py::test_gist_lifecycle` | 1.63 | **1.28** (1.26–1.36) | 0.00 / 0.00 |
| `test_perk_dev_bump.py::test_cli_bump_integration` | 1.72 | **1.27** (0.95–3.53) | 0.00 / 0.00 |
| `test_doctor.py::test_legacy_tracked_plan_md_is_repaired` | 1.88 | **1.27** (1.21–1.33) | 0.05 / 0.00 |
| `test_doctor.py::test_fix_backfills_state_file_and_is_idempotent` | 1.29 | **1.24** (0.98–1.24) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_reports_conflict_when_legacy_and_target_differ` | 1.82 | **1.23** (1.21–1.28) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_removes_orphaned_git_clone` | 1.74 | **1.23** (1.13–1.47) | 0.05 / 0.00 |
| `test_doctor.py::test_subagents_builtins_drift_detected_and_fixed` | 1.88 | **1.22** (1.13–1.29) | 0.05 / 0.00 |
| `test_doctor.py::test_required_perk_version_drift_detected_and_fixed` | 2.20 | **1.21** (1.21–1.25) | 0.05 / 0.00 |
| `test_doctor.py::test_drift_detected_and_fixed_idempotently` | 2.47 | **1.20** (1.17–1.42) | 0.04 / 0.00 |
| `test_git.py::test_push_atomic_with_leases_capability_suppressed_transport_moves_no_ref` | 1.61 | **1.20** (0.96–1.51) | 0.00 / 0.00 |
| `test_delivery_cross_machine.py::test_transfer_manifest_rolls_forward_on_fresh_seams` | 7.89 | **1.20** (0.96–1.22) | 0.00 / 0.00 |
| `test_pr_review_checkout_cmd.py::test_checkout_success_json` | 2.24 | **1.19** (0.83–1.25) | 0.09 / 0.00 |
| `test_doctor.py::test_tracked_subagent_artifacts_are_untracked` | 2.05 | **1.19** (1.06–1.27) | 0.05 / 0.00 |
| `test_doctor.py::test_native_consumer_ordering_drift_detected_and_fixed` | 1.64 | **1.17** (1.11–1.20) | 0.05 / 0.00 |
| `test_doctor.py::test_migrate_legacy_workflow_cache` | 1.84 | **1.16** (1.04–1.28) | 0.05 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_topology_broken_fails_closed` | 1.68 | **1.13** (1.01–1.44) | 0.09 / 0.00 |
| `test_doctor.py::test_fix_repo_skills_errors_land_on_fix_errors` | 1.20 | **1.11** (0.99–1.21) | 0.04 / 0.00 |
| `test_doctor.py::test_compaction_drift_detected_and_fixed` | 1.71 | **1.10** (1.09–1.11) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_migrates_legacy_repo_skill_when_target_absent` | 1.92 | **1.10** (1.03–1.14) | 0.05 / 0.00 |
| `test_delivery_cross_machine.py::test_machines_share_no_local_state` | 8.03 | **1.10** (1.05–1.25) | 0.00 / 0.00 |
| `test_doctor.py::test_fix_migrates_legacy_only_config_secret_safely` | 1.61 | **1.09** (0.99–1.21) | 0.04 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_fix_refuses_unexpected_entries[<lambda>-nested/ (directory)]` | 1.74 | **1.09** (0.87–1.33) | 0.05 / 0.00 |
| `test_doctor.py::test_missing_config_is_reseeded` | 1.42 | **1.07** (0.92–1.12) | 0.05 / 0.00 |
| `test_pr_review_checkout_cmd.py::test_checkout_reaps_stale_review_worktrees_only` | 2.06 | **1.06** (1.02–1.56) | 0.07 / 0.00 |
| `test_launch_restore.py::test_restore_refuses_divergent_local_branch_without_touching_it` | 1.38 | **1.03** (0.83–1.47) | 0.10 / 0.00 |
| `test_delivery_cross_machine.py::test_land_accepted_handle_concludes_from_a_fresh_clone` | 4.91 | **1.03** (0.92–1.21) | 0.00 / 0.00 |
| `test_git.py::test_rebase_onto_clean_transplant` | 1.35 | **1.02** (0.97–1.68) | 0.00 / 0.00 |
| `test_pr_review_context_cmd.py::test_stack_context_topology_broken_refuses` | 1.33 | **1.02** (0.95–1.03) | 0.09 / 0.00 |
| `test_doctor.py::test_legacy_workflow_check_warns_then_ok_after_fix` | 1.88 | **1.00** (0.96–1.10) | 0.05 / 0.00 |

Two parameter cases of `test_stack_checkout_probe_false_or_indeterminate_preserves_existing_checkout`
qualified (`[False]`, `[None]` — every parameter case), so the function carries the mark; of
`test_legacy_agent_defs_fix_refuses_unexpected_entries` only the `nested/ (directory)` case
qualified (1.09 s against 0.92 s for `notes.txt`), so the mark rides that `pytest.param` alone.

### Fast-keeps — 225 candidates under 1.0 s

| Node id (`tests/…`) | Shortlist setup+call s | Own cost s | Setup / teardown s |
|---|---|---|---|
| `test_pr_review_context_cmd.py::test_pinned_stack_context_diffs_the_exact_pins_with_no_fetch` | 1.26 | 1.00 (0.88–1.11) | 0.03 / 0.00 |
| `test_doctor.py::test_ref_drift_detected_and_fixed` | 1.20 | 0.98 (0.88–1.04) | 0.04 / 0.00 |
| `test_doctor.py::test_artifact_health_malformed_state_warns_then_fix_rewrites` | 1.27 | 0.98 (0.90–1.43) | 0.04 / 0.00 |
| `test_doctor.py::test_subagent_package_scope_engine_story` | 1.83 | 0.98 (0.89–1.11) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_invokes_sync_under_verify` | 1.04 | 0.98 (0.81–0.99) | 0.04 / 0.00 |
| `test_doctor.py::test_missing_workflow_subdir_is_fixed` | 1.83 | 0.98 (0.85–1.09) | 0.05 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_symlinked_component_is_refused[.pi]` | 1.67 | 0.97 (0.88–1.04) | 0.05 / 0.00 |
| `test_objective_refine_cmd.py::test_dry_run_resolves_online_reports_and_touches_nothing` | 0.97 | 0.95 (0.87–1.43) | 0.00 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_symlinked_component_is_refused[.pi/agents/perk]` | 1.69 | 0.95 (0.86–1.16) | 0.05 / 0.00 |
| `test_git.py::test_remote_tag_commit` | 1.02 | 0.95 (0.64–1.01) | 0.00 / 0.00 |
| `test_doctor.py::test_fix_removes_identical_legacy_config` | 1.56 | 0.95 (0.95–0.99) | 0.03 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_empty_diff_with_distinct_commits_refuses` | 1.28 | 0.95 (0.89–1.12) | 0.09 / 0.00 |
| `test_pr_review_checkout_cmd.py::test_checkout_refreshes_existing_to_current_head` | 1.92 | 0.95 (0.84–0.95) | 0.10 / 0.00 |
| `test_doctor.py::test_fix_creates_linear_labels` | 1.54 | 0.94 (0.92–0.99) | 0.05 / 0.00 |
| `test_doctor.py::test_fix_reports_conflict_when_legacy_repo_skill_differs` | 1.28 | 0.94 (0.88–0.99) | 0.05 / 0.00 |
| `test_launch_restore.py::test_restore_refuses_ahead_local_branch_without_touching_it` | 1.39 | 0.93 (0.88–1.21) | 0.10 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_fix_refuses_unexpected_entries[<lambda>-notes.txt (not a .md file)]` | 1.71 | 0.92 (0.91–1.08) | 0.05 / 0.00 |
| `test_pr_review_context_cmd.py::test_stack_context_sections_and_combined_diff` | 1.52 | 0.91 (0.90–0.93) | 0.09 / 0.00 |
| `test_doctor.py::test_fix_linear_label_failure_lands_on_fix_errors` | 1.70 | 0.91 (0.89–0.95) | 0.04 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_nested_symlink_is_refused` | 1.64 | 0.91 (0.89–1.17) | 0.05 / 0.00 |
| `test_run_worker.py::test_position_branch_existing_remote_branch_resets_to_the_remote_tip` | 1.73 | 0.91 (0.89–1.12) | 0.10 / 0.00 |
| `test_objective_stack_cmd.py::test_orphaned_residue_counts_render_with_the_recover_hint` | 1.26 | 0.91 (0.70–1.16) | 0.00 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_symlinked_component_is_refused[.pi/agents]` | 1.78 | 0.91 (0.84–1.17) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_materializes_perk_extension_install[absent]` | 1.06 | 0.88 (0.74–0.94) | 0.04 / 0.00 |
| `test_launch_restore.py::test_restore_fast_forwards_only_a_provably_behind_branch` | 1.29 | 0.87 (0.68–0.89) | 0.08 / 0.00 |
| `test_plan_watch.py::test_missing_worktree_real_run_restores_and_stacked_base_is_exact` | 2.31 | 0.86 (0.84–0.91) | 0.07 / 0.00 |
| `test_doctor.py::test_fix_verify_stays_healthy_with_stubbed_sync` | 1.11 | 0.85 (0.85–0.92) | 0.06 / 0.00 |
| `test_learn_dream_cmd.py::test_flagged_index_is_refused` | 1.21 | 0.83 (0.79–0.88) | 0.00 / 0.00 |
| `test_doctor.py::test_fix_reports_conflict_on_deep_nested_difference` | 1.19 | 0.83 (0.64–0.85) | 0.03 / 0.00 |
| `test_launch_restore.py::test_equivalent_resolved_path_is_accepted` | 1.09 | 0.82 (0.59–0.85) | 0.08 / 0.00 |
| `test_refinement_cross_backend_gate.py::test_github_error_translation_at_the_refinement_doors` | 1.18 | 0.82 (0.79–0.86) | 0.00 / 0.00 |
| `test_doctor.py::test_fix_materializes_perk_extension_install[mismatch]` | 1.06 | 0.81 (0.78–0.88) | 0.04 / 0.00 |
| `test_launch.py::test_stacked_resumed_layer_keeps_the_ordinary_resume_arm` | 1.48 | 0.81 (0.74–1.10) | 0.08 / 0.00 |
| `test_doctor.py::test_no_silent_pass_on_unverifiable_check` | 1.16 | 0.80 (0.76–0.82) | 0.04 / 0.00 |
| `test_objective_refine_cmd.py::test_selection_is_delivery_independent_and_never_reconstructs_the_train[stacked]` | 0.86 | 0.79 (0.69–0.83) | 0.00 / 0.00 |
| `test_learn_docs_scan.py::test_max_findings_truncation_duplicate_groups` | 2.07 | 0.79 (0.68–1.07) | 0.00 / 0.00 |
| `test_launch_restore.py::test_stacked_restore_rebuilds_layer_context_from_checkpoint_pair` | 1.31 | 0.78 (0.75–0.99) | 0.09 / 0.00 |
| `test_git.py::test_diff_range_pins_color_algorithm_and_rename_detection` | 0.84 | 0.78 (0.66–1.25) | 0.04 / 0.00 |
| `test_doctor.py::test_fix_sync_failure_carried_on_fix_errors` | 1.02 | 0.78 (0.75–0.84) | 0.05 / 0.00 |
| `test_launch_restore.py::test_restored_setup_fails_then_retries_end_to_end` | 1.27 | 0.77 (0.74–0.84) | 0.10 / 0.00 |
| `test_doctor.py::test_fix_skips_linear_repair_without_selection` | 1.52 | 0.77 (0.75–0.83) | 0.05 / 0.00 |
| `test_launch_restore.py::test_bare_id_canonicalization_restores_the_canonical_branch` | 1.13 | 0.77 (0.66–0.86) | 0.08 / 0.00 |
| `test_launch_restore.py::test_valid_reuse_performs_no_mutating_or_network_git_ops` | 0.98 | 0.76 (0.74–1.04) | 0.10 / 0.00 |
| `test_git.py::test_rebase_onto_conflict_is_retained_mid_rebase` | 0.98 | 0.76 (0.72–1.22) | 0.03 / 0.00 |
| `test_git.py::test_rebase_onto_non_conflict_failure_raises` | 1.12 | 0.74 (0.61–0.77) | 0.00 / 0.00 |
| `test_linear_lifecycle.py::test_doctor_detects_and_fixes_deleted_milestone` | 1.09 | 0.74 (0.74–0.93) | 0.00 / 0.00 |
| `test_launch_restore.py::test_restore_creates_local_branch_from_remote_tip` | 1.18 | 0.74 (0.73–0.95) | 0.11 / 0.00 |
| `test_worktree_wipe.py::test_wipe_deletes_remote_branches` | 1.32 | 0.74 (0.73–0.75) | 0.07 / 0.00 |
| `test_pr_review_context_cmd.py::test_pinned_stack_context_topology_refusals` | 1.00 | 0.73 (0.62–0.93) | 0.03 / 0.00 |
| `test_launch_restore.py::test_stacked_restore_bottom_layer_parent_branch_is_the_base` | 1.30 | 0.73 (0.72–0.76) | 0.08 / 0.00 |
| `test_launch_restore.py::test_restore_attaches_equal_local_branch` | 1.28 | 0.73 (0.67–1.14) | 0.08 / 0.00 |
| `test_objective_refine_cmd.py::test_target_refusals_are_typed_and_write_nothing` | 0.76 | 0.73 (0.67–1.01) | 0.00 / 0.00 |
| `test_librarian_cmd.py::test_remove_ok_and_not_found` | 0.93 | 0.72 (0.72–0.76) | 0.04 / 0.00 |
| `test_objective_refine_cmd.py::test_selection_is_delivery_independent_and_never_reconstructs_the_train[None]` | 0.83 | 0.72 (0.71–0.96) | 0.00 / 0.00 |
| `test_worktree_wipe.py::test_wipe_remote_blind_batch_tolerates_already_gone` | 1.09 | 0.72 (0.67–0.95) | 0.09 / 0.00 |
| `test_objective_refine_cmd.py::test_refinement_save_worker_refuses_missing_mismatched_and_ineligible_inputs` | 1.05 | 0.71 (0.66–0.82) | 0.00 / 0.00 |
| `test_git.py::test_push_with_exact_lease_correct_expect_succeeds` | 1.05 | 0.70 (0.57–0.74) | 0.00 / 0.00 |
| `test_refinement_cross_backend_gate.py::test_sync_that_flips_the_route_to_github_selects_over_github_fresh_adapters` | 0.87 | 0.70 (0.65–0.78) | 0.00 / 0.00 |
| `test_doctor.py::test_subagent_untrack_failure_carried_on_fix_errors` | 1.34 | 0.70 (0.65–0.76) | 0.05 / 0.00 |
| `test_perk_dev_release_tag.py::test_push_lands_tag_in_origin_and_repush_noops` | 0.86 | 0.70 (0.66–0.73) | 0.11 / 0.00 |
| `test_change_stats.py::test_resolve_range_offline_prefers_origin_then_local` | 4.33 | 0.70 (0.47–0.86) | 0.09 / 0.00 |
| `test_git.py::test_tags_pointing_at` | 0.76 | 0.70 (0.59–0.87) | 0.00 / 0.00 |
| `test_change_stats.py::test_summarize_materializes_and_partitions_every_entry` | 5.49 | 0.69 (0.50–0.77) | 0.03 / 0.00 |
| `test_git.py::test_rewrite_force_with_lease_succeeds` | 1.00 | 0.69 (0.58–0.79) | 0.00 / 0.00 |
| `test_doctor.py::test_legacy_agent_defs_fix_keeps_user_agents_and_gitkeep` | 1.18 | 0.69 (0.65–0.87) | 0.05 / 0.00 |
| `test_objective_stack_cmd.py::test_handoff_axis_rides_the_envelope_and_the_render` | 0.81 | 0.68 (0.66–0.88) | 0.00 / 0.00 |
| `test_learn_dream_cmd.py::test_origin_lookup_failure_is_fail_closed` | 0.93 | 0.68 (0.68–0.92) | 0.00 / 0.00 |
| `test_git.py::test_pr_merge_base_diff_renders_the_merge_base_diff_and_cleans_up` | 1.18 | 0.68 (0.64–0.94) | 0.09 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracked_artifacts[sessions/session.jsonl]` | 0.82 | 0.68 (0.38–0.79) | 0.04 / 0.00 |
| `test_git.py::test_diff_entries_parses_every_status_with_regular_file_blobs` | 0.75 | 0.67 (0.55–0.83) | 0.04 / 0.00 |
| `test_worktree_wipe.py::test_wipe_stranded_branch_remote_delete` | 0.89 | 0.66 (0.47–0.69) | 0.08 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[settings.json.lock]` | 0.81 | 0.66 (0.64–0.67) | 0.04 / 0.00 |
| `test_change_stats.py::test_summarize_counts_committed_bytes_despite_archive_attributes` | 1.46 | 0.66 (0.53–0.71) | 0.03 / 0.00 |
| `test_doctor.py::test_fix_mixed_legacy_repo_skills_in_one_pass` | 1.27 | 0.65 (0.64–0.69) | 0.05 / 0.00 |
| `test_doctor.py::test_skills_delivery_self_repo_stale_fails` | 0.78 | 0.65 (0.50–0.95) | 0.04 / 0.00 |
| `test_objective_refine_cmd.py::test_real_launch_prepares_after_the_one_sync_and_launches_with_the_post_sync_config` | 0.78 | 0.65 (0.61–0.83) | 0.00 / 0.00 |
| `test_launch_restore.py::test_restore_refuses_branch_checked_out_elsewhere` | 0.95 | 0.65 (0.60–0.67) | 0.08 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[sessions/]` | 0.96 | 0.65 (0.56–1.02) | 0.04 / 0.00 |
| `test_launch_restore.py::test_prunable_registered_entry_refuses_with_repair_remediation` | 0.93 | 0.64 (0.62–0.78) | 0.09 / 0.00 |
| `test_doctor.py::test_fix_removes_legacy_repo_skill_when_identical` | 1.21 | 0.64 (0.63–0.71) | 0.05 / 0.00 |
| `test_pr_review_stack_checkout.py::test_non_stack_envelope_byte_compat_pin` | 1.49 | 0.64 (0.62–0.93) | 0.09 / 0.00 |
| `test_doctor.py::test_fix_config_absent_seeds_template_without_migration` | 1.18 | 0.64 (0.61–0.73) | 0.04 / 0.00 |
| `test_launch.py::test_create_bases_off_fresh_origin_trunk` | 0.92 | 0.63 (0.53–0.66) | 0.08 / 0.00 |
| `test_launch_restore.py::test_restore_refuses_stale_registration_with_prune_remediation` | 1.20 | 0.63 (0.61–0.70) | 0.10 / 0.00 |
| `test_doctor.py::test_runner_githuberror_degrades` | 1.13 | 0.63 (0.59–0.67) | 0.00 / 0.00 |
| `test_doctor.py::test_ponytail_compat_is_registered_in_doctor_report` | 1.18 | 0.63 (0.55–0.74) | 0.04 / 0.00 |
| `test_launch.py::test_create_bases_off_pinned_plan_base` | 1.12 | 0.62 (0.61–0.70) | 0.09 / 0.00 |
| `test_perk_dev_release.py::test_gather_marker_states` | 0.81 | 0.62 (0.50–0.87) | 0.11 / 0.00 |
| `test_launch.py::test_explicit_ref_with_directory_override_stays_on_plan_branch` | 1.13 | 0.62 (0.59–0.78) | 0.10 / 0.00 |
| `test_change_stats.py::test_summarize_maps_other_cloc_errors` | 1.80 | 0.62 (0.33–0.63) | 0.03 / 0.00 |
| `test_pr_review_context_cmd.py::test_pinned_stack_context_option_grammar` | 0.90 | 0.61 (0.52–0.62) | 0.04 / 0.00 |
| `test_git.py::test_push_with_exact_lease_stale_expect_is_rejected` | 0.74 | 0.60 (0.49–0.63) | 0.00 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[trust.json]` | 1.15 | 0.58 (0.49–0.66) | 0.03 / 0.00 |
| `test_git.py::test_pr_merge_base_diff_unrelated_history_raises_and_leaves_no_refs` | 0.81 | 0.58 (0.48–0.83) | 0.08 / 0.00 |
| `test_change_stats.py::test_resolve_range_fetch_uses_the_fetched_remote` | 7.25 | 0.58 (0.34–0.68) | 0.07 / 0.00 |
| `test_git.py::test_push_tag` | 0.78 | 0.57 (0.50–1.04) | 0.00 / 0.00 |
| `test_change_stats.py::test_summarize_aggregates_rows_across_languages` | 3.22 | 0.57 (0.53–0.61) | 0.03 / 0.00 |
| `test_doctor.py::test_untrack_failure_carried_on_fix_errors` | 1.29 | 0.57 (0.53–0.67) | 0.05 / 0.00 |
| `test_doctor.py::test_self_vs_consumer_dual_mode` | 0.74 | 0.57 (0.53–0.62) | 0.05 / 0.00 |
| `test_launch_restore.py::test_stacked_restore_refuses_non_ancestor_parent_checkpoint` | 0.86 | 0.56 (0.49–0.69) | 0.07 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[models-store.json]` | 1.22 | 0.56 (0.49–0.72) | 0.04 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracked_artifacts[auth.json]` | 0.78 | 0.56 (0.46–0.60) | 0.05 / 0.00 |
| `test_run_worker.py::test_positioning_parity_local_launch_vs_remote_worker` | 0.96 | 0.56 (0.55–0.69) | 0.10 / 0.00 |
| `test_change_stats.py::test_summarize_symlink_side_degrades_to_add_or_remove` | 1.75 | 0.55 (0.33–0.62) | 0.03 / 0.00 |
| `test_delivery_sync_integration.py::test_orphan_sweep_removes_real_residue_and_prunes` | 2.53 | 0.55 (0.54–0.59) | 0.04 / 0.00 |
| `test_boundary_discipline.py::TestBoundaryDiscipline::test_no_module_subclasses_raw_pydantic_outside_boundary` | 5.52 | 0.55 (0.54–1.53) | 0.00 / 0.00 |
| `test_learn_dream_cmd.py::test_from_is_rejected_in_both_spellings` | 0.70 | 0.55 (0.50–0.92) | 0.00 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[settings.json]` | 0.98 | 0.54 (0.48–0.59) | 0.06 / 0.00 |
| `test_objective_stack_recover_cmd.py::test_typed_refusals_exit_one_verbatim` | 0.86 | 0.54 (0.44–0.65) | 0.00 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[auth.json.lock]` | 0.99 | 0.54 (0.49–0.58) | 0.04 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_every_volatile_class_needs_ignore_coverage[auth.json]` | 1.32 | 0.53 (0.48–0.79) | 0.05 / 0.00 |
| `test_change_stats.py::test_summarize_maps_blob_read_failures` | 1.92 | 0.53 (0.40–0.54) | 0.04 / 0.00 |
| `test_launch_restore.py::test_stacked_restore_refuses_drifted_published_head` | 0.91 | 0.52 (0.51–1.26) | 0.09 / 0.00 |
| `test_output.py::test_log_step_call_sites_confined_to_the_output_module` | 0.76 | 0.52 (0.51–0.53) | 0.00 / 0.00 |
| `test_linear_lifecycle.py::test_objective_run_resolves_in_flight_over_an_eng_backlink` | 0.79 | 0.51 (0.50–0.88) | 0.00 / 0.00 |
| `test_pr_review_checkout_cmd.py::test_checkout_refresh_removal_failure_is_enveloped` | 1.48 | 0.51 (0.50–0.70) | 0.07 / 0.00 |
| `test_git.py::test_probe_atomic_push_refuses_a_capability_suppressed_transport` | 0.76 | 0.51 (0.46–0.54) | 0.00 / 0.00 |
| `test_refinement_cross_backend_gate.py::test_node_engagement_json_and_seed_pointer_shape_parity_across_backends[linear]` | 0.82 | 0.51 (0.50–0.52) | 0.00 / 0.00 |
| `test_library_ops.py::test_step_b_failure_on_replace_restores_the_prior_revision` | 0.94 | 0.51 (0.46–0.70) | 0.05 / 0.00 |
| `test_git.py::test_push_with_exact_lease_absence_lease_rejected_when_ref_exists` | 0.74 | 0.50 (0.44–0.61) | 0.00 / 0.00 |
| `test_pr_review_stack_checkout.py::test_stack_checkout_empty_combined_diff_refuses` | 0.86 | 0.50 (0.48–0.70) | 0.08 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracks_literal_directory_names[agent[1]]` | 0.81 | 0.50 (0.43–0.65) | 0.05 / 0.00 |
| `test_launch.py::test_reuse_does_not_fetch_or_rebase` | 0.73 | 0.49 (0.42–0.53) | 0.08 / 0.00 |
| `test_library_ops.py::test_step_c_failure_on_replace_restores_both` | 0.91 | 0.48 (0.48–0.48) | 0.05 / 0.00 |
| `test_worktree_wipe.py::test_wipe_happy_path` | 0.70 | 0.48 (0.40–0.52) | 0.03 / 0.00 |
| `test_git.py::test_fetch_refspecs_pull_ref_and_bare_branch` | 0.74 | 0.48 (0.47–0.51) | 0.09 / 0.00 |
| `test_git.py::test_detect_merge_conflicts_conflicting` | 0.75 | 0.47 (0.47–0.47) | 0.09 / 0.00 |
| `test_change_stats.py::test_real_cloc_counts_a_rename_once_under_its_new_path` | 4.15 | 0.46 (0.46–1.07) | 0.02 / 0.00 |
| `test_pr_review_context_cmd.py::test_pinned_stack_context_missing_object_refuses` | 0.80 | 0.46 (0.46–0.68) | 0.03 / 0.00 |
| `test_git.py::test_create_annotated_tag` | 0.74 | 0.46 (0.38–0.58) | 0.00 / 0.00 |
| `test_worktree_wipe.py::test_wipe_force_deletes_branch_ahead_of_trunk` | 0.70 | 0.46 (0.40–0.85) | 0.03 / 0.00 |
| `test_doctor.py::test_skills_delivery_fails_on_tracked_conflict` | 0.81 | 0.46 (0.41–0.55) | 0.05 / 0.00 |
| `test_git.py::test_worktree_add_with_base` | 0.73 | 0.45 (0.34–0.47) | 0.07 / 0.00 |
| `test_git.py::test_detect_merge_conflicts_clean` | 0.82 | 0.45 (0.44–0.47) | 0.09 / 0.00 |
| `test_objective_stack_cmd.py::test_pending_continuation_block_and_next_steps` | 0.83 | 0.45 (0.44–0.62) | 0.00 / 0.00 |
| `test_github_refinement.py::test_phase2_gate_github_refinement_persistence[stacked]` | 0.79 | 0.45 (0.40–0.55) | 0.00 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracked_artifacts[trust.json]` | 0.96 | 0.44 (0.40–0.62) | 0.04 / 0.00 |
| `test_launch_restore.py::test_fresh_create_setup_fails_then_retries_end_to_end` | 0.76 | 0.44 (0.40–0.52) | 0.09 / 0.00 |
| `test_launch_restore.py::test_stacked_restore_without_checkpoint_pair_refuses` | 0.81 | 0.43 (0.40–0.77) | 0.09 / 0.00 |
| `test_doctor.py::test_subagent_compat_version_mismatch_is_warn_never_fail` | 0.89 | 0.43 (0.39–0.46) | 0.05 / 0.00 |
| `test_perk_dev_changelog.py::test_gather_marker_discovery` | 1.37 | 0.43 (0.33–0.47) | 0.28 / 0.00 |
| `test_delivery_continuation.py::TestImportOrder::test_cache_first_import_order` | 2.81 | 0.43 (0.39–0.44) | 0.00 / 0.00 |
| `test_delivery_continuation.py::TestImportOrder::test_continuation_never_imports_perk_state` | 3.51 | 0.43 (0.37–1.22) | 0.00 / 0.00 |
| `test_delivery_continuation.py::TestImportOrder::test_delivery_first_import_order` | 2.65 | 0.43 (0.38–0.43) | 0.00 / 0.00 |
| `test_launch_materialize.py::test_implement_materializes_worktree_and_is_idempotent` | 0.74 | 0.43 (0.42–0.58) | 0.03 / 0.00 |
| `test_perk_dev_release.py::test_gather_remote_probed_even_without_local_tag` | 0.79 | 0.42 (0.41–0.47) | 0.00 / 0.00 |
| `test_git.py::test_diff_range_never_executes_configured_diff_helpers` | 0.73 | 0.42 (0.38–0.48) | 0.03 / 0.00 |
| `test_launch.py::test_remote_branch_exists_bases_off_tracking` | 0.74 | 0.42 (0.38–0.44) | 0.08 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_is_ancestor_arms` | 4.32 | 0.41 (0.41–0.42) | 0.09 / 0.00 |
| `test_library_ops.py::test_a_replace_killed_between_displace_and_swap_recovers_by_rerunning_it` | 0.80 | 0.41 (0.40–0.49) | 0.04 / 0.00 |
| `test_perk_dev_release.py::test_gather_tag_on_remote_true` | 0.77 | 0.41 (0.41–0.79) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_fetch_and_remote_branch_sha` | 2.75 | 0.41 (0.38–0.49) | 0.09 / 0.00 |
| `test_doctor.py::test_migrate_legacy_workflow_cache_keeps_present_target` | 0.82 | 0.40 (0.37–0.42) | 0.04 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_base_head_deleted_base_beats_the_stale_tracking_ref` | 3.57 | 0.39 (0.36–0.60) | 0.09 / 0.00 |
| `test_repo_blueprints.py::test_remote_git_repo_factory_keeps_origins_inside_each_copy` | 0.72 | 0.39 (0.34–0.51) | 0.00 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracked_artifacts[None]` | 0.87 | 0.38 (0.35–0.59) | 0.05 / 0.00 |
| `test_library_ops.py::test_step_c_failure_on_adopt_restores_the_directory` | 0.83 | 0.38 (0.30–0.56) | 0.03 / 0.00 |
| `test_pr_review_checkout_cmd.py::test_checkout_fetch_failure_leaves_existing_worktree` | 0.92 | 0.38 (0.26–0.40) | 0.06 / 0.00 |
| `test_git.py::test_delete_remote_branches_happy_path` | 0.70 | 0.38 (0.31–0.50) | 0.09 / 0.00 |
| `test_delivery_continuation.py::TestLineageSafety::test_hostile_lineages_are_refused_everywhere` | 0.92 | 0.37 (0.35–0.43) | 0.00 / 0.00 |
| `test_run_worker.py::test_positioning_parity_explicit_ref_launch_vs_remote_worker` | 0.90 | 0.37 (0.33–0.53) | 0.09 / 0.00 |
| `test_objective_stack_cmd.py::test_planning_gate_ready_arm` | 0.76 | 0.35 (0.34–0.49) | 0.00 / 0.00 |
| `test_doctor.py::test_git_identity_check_present_under_verify` | 0.83 | 0.35 (0.33–0.52) | 0.04 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_tracks_literal_directory_names[agent?]` | 0.79 | 0.35 (0.34–0.84) | 0.04 / 0.00 |
| `test_doctor.py::test_git_identity_check_absent_without_verify` | 1.90 | 0.34 (0.33–0.37) | 0.05 / 0.00 |
| `test_upgrade_notice.py::test_cli_shows_both_surfaces_together` | 5.67 | 0.34 (0.24–1.31) | 0.03 / 0.00 |
| `test_library_guard.py::test_refused_publish_symlinked_root_leaves_no_trace` | 0.76 | 0.33 (0.20–0.40) | 0.04 / 0.00 |
| `test_delivery_oplock.py::test_linked_worktree_contends_on_the_main_checkout_lock` | 2.18 | 0.33 (0.31–0.46) | 0.00 / 0.00 |
| `test_doctor.py::test_healthy_after_init` | 1.89 | 0.32 (0.32–0.33) | 0.05 / 0.00 |
| `test_change_stats.py::test_summarize_maps_cloc_missing` | 2.41 | 0.32 (0.32–0.35) | 0.03 / 0.00 |
| `test_worktree_wipe.py::test_wipe_recovers_broken_worktree` | 0.78 | 0.32 (0.31–0.35) | 0.02 / 0.00 |
| `test_library_ops.py::test_step_c_failure_on_fresh_publish_restores_staging` | 0.86 | 0.31 (0.30–0.56) | 0.05 / 0.00 |
| `test_doctor.py::test_cli_version_check_in_json_report` | 0.75 | 0.30 (0.28–0.35) | 0.05 / 0.00 |
| `test_cli_stages.py::test_worktree_create_list_remove` | 4.23 | 0.30 (0.19–0.39) | 0.03 / 0.00 |
| `test_doctor.py::test_pi_agent_dir_check_auth_only_ignore_rule_is_not_safe` | 0.71 | 0.30 (0.27–0.52) | 0.05 / 0.00 |
| `test_run_worker.py::test_position_branch_fresh_incremental_creates_from_origin_base` | 0.74 | 0.30 (0.29–0.46) | 0.09 / 0.00 |
| `test_change_stats.py::test_summarize_skips_a_non_utf8_name_instead_of_failing` | 3.00 | 0.29 (0.29–0.39) | 0.03 / 0.00 |
| `test_upgrade_notice.py::test_cli_stays_silent_on_current_store` | 4.59 | 0.29 (0.22–0.38) | 0.02 / 0.00 |
| `test_config.py::test_issues_selection_anchors_to_main_checkout_from_worktree` | 2.47 | 0.28 (0.27–0.29) | 0.04 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_base_head_is_the_authoritative_live_read` | 3.45 | 0.27 (0.26–0.29) | 0.09 / 0.00 |
| `test_perk_dev_release_tag.py::test_dry_run_still_fails_on_conflict` | 0.80 | 0.26 (0.24–0.44) | 0.00 / 0.00 |
| `test_cli_stages.py::test_learn_is_dedicated_hybrid_group` | 1.10 | 0.26 (0.18–0.58) | 0.04 / 0.00 |
| `test_plan_watch.py::test_backend_native_plan_id_is_carried_verbatim` | 0.94 | 0.25 (0.24–0.27) | 0.08 / 0.00 |
| `test_perk_dev_changelog.py::test_cli_json` | 0.80 | 0.25 (0.16–0.31) | 0.00 / 0.00 |
| `test_plan_watch.py::test_linked_worktree_invocation_resolves_under_the_main_root` | 0.94 | 0.25 (0.24–0.27) | 0.09 / 0.00 |
| `test_library_ops.py::test_publish_fresh` | 0.82 | 0.24 (0.24–0.26) | 0.04 / 0.00 |
| `test_cli_stages.py::test_implement_remote_dry_run_is_dispatch_preview` | 1.20 | 0.23 (0.15–0.25) | 0.04 / 0.00 |
| `test_cache_guard.py::TestCachePathGuard::test_no_production_module_builds_scratch_paths_directly` | 3.85 | 0.22 (0.19–0.25) | 0.00 / 0.00 |
| `test_config.py::test_save_key_anchors_to_main_checkout_from_worktree` | 1.28 | 0.22 (0.22–0.23) | 0.03 / 0.00 |
| `test_cli.py::test_init_via_cli` | 1.16 | 0.22 (0.19–0.35) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_worktree_branches_maps_the_writer_axis` | 3.22 | 0.21 (0.21–0.45) | 0.06 / 0.00 |
| `test_cli_stages.py::test_merged_command_launcher_default` | 1.21 | 0.20 (0.20–0.42) | 0.03 / 0.00 |
| `test_plan_watch.py::test_hash_prefixed_id_resolves_the_plain_worktree` | 0.71 | 0.18 (0.17–0.26) | 0.09 / 0.00 |
| `test_perk_dev_changelog.py::test_gather_release_fallback` | 0.87 | 0.17 (0.17–0.17) | 0.00 / 0.00 |
| `test_delivery_continuation.py::TestMainRootAnchoring::test_worktree_write_is_visible_from_the_main_checkout` | 1.39 | 0.17 (0.17–0.18) | 0.04 / 0.00 |
| `test_resolve.py::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly` | 2.43 | 0.17 (0.14–0.17) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_prepare_git_probes_propagate_unexpected_errors` | 10.22 | 0.17 (0.12–0.37) | 1.12 / 0.00 |
| `test_delivery_oplock.py::test_contention_and_reacquisition_after_release` | 1.53 | 0.17 (0.16–0.17) | 0.00 / 0.00 |
| `test_doctor.py::test_issues_check_fails_on_linear_without_team` | 0.79 | 0.16 (0.10–0.33) | 0.05 / 0.00 |
| `test_delivery_policy_guard.py::TestDeliveryPolicyGuard::test_no_production_module_touches_the_delivery_key_outside_the_census` | 1.85 | 0.15 (0.13–0.19) | 0.00 / 0.00 |
| `test_objective_doctor_cmd.py::test_human_render_train_fix_summary_and_failure` | 0.81 | 0.15 (0.15–0.32) | 0.00 / 0.00 |
| `test_cli_stages.py::test_implement_explicit_plan_backend_failure_maps_github_error` | 0.74 | 0.11 (0.09–0.12) | 0.04 / 0.00 |
| `test_objective_node_engagement_cmd.py::test_human_no_engagement_note` | 0.81 | 0.11 (0.09–0.15) | 0.00 / 0.00 |
| `test_objective_node_engagement_cmd.py::test_json_payload_shape` | 0.82 | 0.10 (0.10–0.13) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_base_head_read_failure_degrades_into_the_failure_arm` | 2.18 | 0.10 (0.09–0.11) | 0.10 / 0.00 |
| `test_cli_stages.py::test_plan_is_dedicated_hybrid_group` | 0.70 | 0.10 (0.09–0.10) | 0.03 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_sync_git_methods_are_direct_substrate_delegates` | 2.47 | 0.09 (0.09–0.11) | 0.09 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_fetch_failure_is_typed_git_error` | 2.05 | 0.09 (0.08–0.10) | 0.09 / 0.00 |
| `test_objective_dream_save_cmd.py::test_cross_run_transfer_refuses` | 0.72 | 0.09 (0.09–0.55) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_resolve_commit_failure_preserves_raw_cause` | 6.77 | 0.09 (0.09–0.09) | 0.09 / 0.00 |
| `test_objective_dream_save_cmd.py::test_companion_ambiguous_maps_to_its_error_type` | 0.80 | 0.09 (0.08–0.10) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_sync_git_mutation_errors_reuse_raw_substrate_types` | 2.41 | 0.08 (0.08–0.10) | 0.08 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_trunk_failure_is_typed_git_error` | 7.26 | 0.08 (0.06–0.10) | 0.08 / 0.00 |
| `test_cli_stages.py::test_plan_save_merged_json_routes_to_worker` | 0.73 | 0.08 (0.08–0.09) | 0.03 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_push_urls_converts_success_and_expected_failure` | 7.27 | 0.08 (0.06–0.12) | 0.08 / 0.00 |
| `test_config.py::test_save_key_unverifiable_ignore_probe_refuses` | 2.92 | 0.07 (0.07–0.14) | 0.02 / 0.00 |
| `test_cli_stages.py::test_objective_author_is_dedicated_and_local_only` | 0.79 | 0.07 (0.06–0.07) | 0.03 / 0.00 |
| `test_perk_dev_changelog.py::test_gather_marker_unresolvable` | 1.09 | 0.07 (0.07–0.10) | 0.00 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_remote_branch_sha_failure_is_typed_git_error` | 2.30 | 0.07 (0.06–0.08) | 0.07 / 0.00 |
| `test_delivery_observe.py::TestRepoDeliveryGit::test_atomic_push_converts_success_and_expected_failure` | 2.47 | 0.06 (0.06–0.06) | 0.06 / 0.00 |
| `test_cli_stages.py::test_plan_save_merged_launcher_default` | 0.96 | 0.06 (0.06–0.07) | 0.03 / 0.00 |
| `test_doctor.py::test_providers_check_ok_on_default_repo` | 0.84 | 0.05 (0.05–0.07) | 0.04 / 0.00 |
| `test_objective_engagement_cmd.py::test_not_a_repo_exit_2` | 0.73 | 0.03 (0.02–0.03) | 0.00 / 0.00 |
| `test_perk_dev_changelog.py::test_gather_changelog_not_found` | 1.06 | 0.02 (0.02–0.03) | 0.00 / 0.00 |
| `test_contracts_anchors.py::test_every_heading_is_cited_somewhere` | 25.79 | 0.01 (0.01–0.01) | 8.97 / 0.00 |

No candidate had a raw teardown median ≥ 0.1 s (the maximum was 0.005 s).

Shared cost (broad-scoped fixture setup, charged to the fixture once per run; median):
`source_corpus` [session] 8.94 · `_remote_git_template` [session] 0.95 ·
`changelog_repo_factory` [session] 0.28 · `_unborn_git_template` [session] 0.18 ·
`_committed_git_template` [session] 0.13 · `release_repo_factory` [session] 0.11 ·
`release_tag_repo_factory` [session] 0.10. The first-consumer effect in one line:
`test_contracts_anchors.py::test_every_heading_is_cited_somewhere` topped the shortlist at 25.79 s
of `setup` — the whole session-scoped `source_corpus` build — against an own cost of 0.01 s.

## 4. Selection accounting

`uv run pytest -n0 --collect-only -q`, node-id lines sorted: full **7,633** · slow **80** · fast
**7,553**; `comm -12 slow fast` empty; `sort -u slow fast` equals full; the newly slow set (slow
after minus slow before) is exactly the 57 marked cases above;
`tests/test_packaging.py::test_every_build_consumer_is_slow` is in the fast set. The 15 edited test
modules plus `tests/test_packaging.py` and `tests/test_pytest_tiers.py` pass under the default
configuration (`618 passed`).

## 5. Observations and limitations

- **The rule's result is larger than phase 3's.** 57 new threshold cases against phase 3's five:
  the suite has grown real-git integration coverage (`test_doctor.py` convergence stories,
  `test_pr_review_stack_checkout.py`, `test_delivery_cross_machine.py`), and many of those cases
  sit just above the line — eleven medians fall in 1.00–1.10 s. A quieter host would likely move
  some of them under 1.0 s; the classification records the measured truth on this host.
- **Host contention.** Run 1 started at a 1-minute load average of 13.5 (other sessions were
  running) and the series ended at 4.9; run 1 is the slowest, but the verdict uses the median, and
  the noisiest rows (`test_upgrade_notice.py::test_cli_emits_notice_on_stale_store` 0.37–3.81,
  `test_perk_dev_bump.py::test_cli_bump_integration` 0.95–3.53) have medians well clear of or
  just above the threshold.
- **Transparency note.** During run 2 a `CHANGELOG.md` working-tree edit existed for about a
  minute and was reverted before the run ended; no candidate reads the checkout's `CHANGELOG.md`
  (the changelog tests build fixture repositories), and the tree was clean before the shortlist and
  after the last run.
- **Sampling:** n = 3 serial samples; the shortlist's single parallel sample is the stated
  sampling limitation in §2.
