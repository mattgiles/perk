# Gate record: objective-node refinement — the GitHub carrier (offline)

**Status:** validation record (the archive gate/evidence genre) for Objective *Consume node
refinements in planning and enable the GitHub carrier*, its GitHub phase — the persistence
(§8.67, the GitHub arm), the authoring doors (§8.68) and the planning-time consumption (§8.26)
of node refinements on the GitHub issue backend, where every node's carrier is the objective
issue itself.

**Gate verdict:** **PASS (offline)** — closed by explicit owner decision with **no live GitHub
run**. Every criterion below is either **offline-pinned** (a named test, green at the record's
tested commit) or **unobserved — NOT PASSED**; nothing is classified observed-live.

**What this record proves and what it does not.** It proves the real resolvers, the real
`GitHubObjectiveStore` + `GitHubIssueBackend`, the real `perk.objective.refinement.service`, and
the real CLI doors and workers over the stateful `gh` fake (`tests/_github_fakes.py::
FakeGitHubIssues` — the external `gh` transport only, never the service; two-item pages so every
cursor loop runs on real data; an additive fault hook for transport failures), plus the
backend-neutral session interior through the Linear two-plane end-to-end case and the
GitHub-bound first-party approve-label case. It does **not** prove any live GitHub behavior: no
authenticated `gh`, no real repository, no real comment was touched.

## Context

| item | value |
|---|---|
| record date | 2026-09-10 |
| tested commit | `3a143001a679d1e668b966827a35975f79f5ac04` (the implementation + suites; this record's commit follows it) |
| worktree | `.worktrees/plan-2376` |
| commands | `uv run pytest tests/test_github_refinement.py tests/test_refinement_cross_backend_gate.py -v -n0` · `node --test extension/pi/v1/objectiveRefinement.test.ts` |
| Python / pytest / Node | `3.13.9` / `9.0.3` / `v26.3.0` |

## Criteria

| id | criterion | classification | named test |
|---|---|---|---|
| O1 | persistence on the objective issue: select → save → read → replace (same comment id) → retry (no mutation); the exhaustive paginated scan; unchanged roadmap block / header / objective-body comment / issue body; the 65,536-character refusal (`backend_error`, `write_attempted`, record unchanged); plan/refinement interleaving; engagement renders omit the refinement | offline-pinned | `tests/test_github_refinement.py::test_phase2_gate_github_refinement_persistence[incremental]`, `[stacked]` |
| O2 | cold `perk objective refine` binds a GitHub context (no Linear read clause), the warm `refine-context` worker returns byte-identical bytes, the save worker lands one comment on the objective issue with typed envelopes (`stale_refinement`; the 65,536-character `backend_error` with `write_attempted: true`; post-claim `node_ineligible`), warm (`node-engagement`) and cold (`objective plan`) consumption over the objective issue, claim before read | offline-pinned | `tests/test_refinement_cross_backend_gate.py::test_phase2_gate_github_refinement_doors` |
| O3 | the warm refinement interior (draft tool, review arm, save seam) is backend-neutral; the first-party approve verdict names the GitHub carrier for a GitHub-bound pair and the Linear label is not an approval there | offline-pinned | `tests/test_objective_refine_cmd.py::test_refinement_loop_end_to_end_over_a_fake_linear_objective` (the two-plane interior, Linear-seeded); `extension/pi/v1/objectiveRefinement.test.ts` "first-party approve label names the bound carrier per backend — a GitHub-bound pair approves only under the GitHub label", "refinementSaveDestination: Linear and GitHub carriers by name; an unrecognized backend id renders verbatim" |
| O4 | plan/refinement interleaving on the single-issue carrier: the planning claim re-renders the roadmap block and body-comment table while the refinement comment stays byte-untouched | offline-pinned | O1's gate; `test_phase2_gate_github_refinement_doors` step 9 |
| O5 | negative-effect proofs: the roadmap block / objective body / header at the store (O1's gate); the `perk objective show --json` bytes and the rendered `perk objective engagement` at the CLI surfaces (the `--json` census carries the refinement as a `perk`-authored row, unfiltered by design) | offline-pinned | O1's gate; `test_phase2_gate_github_refinement_doors` step 6 |
| O6 | the 65,536-character refusal: the service-level shape (O1) and the save worker's envelope (`backend_error`, gh's diagnostic, `write_attempted: true`, `comment_ids`, one PATCH attempted, record unchanged) | offline-pinned | O1's gate; `test_phase2_gate_github_refinement_doors` step 7 |
| O7 | GitHub error translation at the doors: non-numeric id → `backend_error`; missing objective → `objective_not_found`; unknown / claimed node → `node_not_found` / `node_ineligible`; a `gh` 401 → `backend_error` with gh's diagnostic, nothing minted or launched; a Linear-bound retained context → `invalid_input` before any read; never `github_error` / `github_unauthed` | offline-pinned | `tests/test_refinement_cross_backend_gate.py::test_github_error_translation_at_the_refinement_doors` |
| O8 | both-backend shape parity: the `node-engagement --json` key sets and the plan seed's refinement pointer are identical on Linear and GitHub | offline-pinned | `tests/test_refinement_cross_backend_gate.py::test_node_engagement_json_and_seed_pointer_shape_parity_across_backends[linear]`, `[github]` |
| O9 | the committed-route flip: a sync that flips `[issues]` from Linear to GitHub selects over fresh GitHub adapters with the post-sync Config and no Linear traffic | offline-pinned | `tests/test_refinement_cross_backend_gate.py::test_sync_that_flips_the_route_to_github_selects_over_github_fresh_adapters` |
| O10 | the exhaustive paginated scan and the coexistence filters (marker finder, plan-body scans, dream-companion scan, engagement renders) over the two-item page | offline-pinned | `tests/test_github_refinement.py::TestGuardedUpsertOverGitHub`, `TestCoexistenceFilters` |
| U1 | comment-body byte preservation on a live repository | unobserved — NOT PASSED | — |
| U2 | the real HTTP 422 shape for the 65,536-character cap | unobserved — NOT PASSED | — |
| U3 | `fullDatabaseId` presence on every live comment | unobserved — NOT PASSED | — |
| U4 | `--paginate --slurp` on the live comments endpoint | unobserved — NOT PASSED | — |
| U5 | `gh` auth / rate-limit failure shapes | unobserved — NOT PASSED | — |
| U6 | a live warm `/objective-refine` on a GitHub objective | unobserved — NOT PASSED | — |
| U7 | a released-artifact (non-spoofed) consumer install | unobserved — NOT PASSED | — |

## Transcript (the tested commit's tree)

```
$ uv run pytest tests/test_github_refinement.py tests/test_refinement_cross_backend_gate.py -v -n0
============================= test session starts ==============================
platform darwin -- Python 3.13.9, pytest-9.0.3, pluggy-1.6.0
collected 28 items

tests/test_github_refinement.py::TestCommentIdentity::test_read_comments_ids_are_the_stringified_database_id PASSED [  3%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_no_objective_header_is_none PASSED [  7%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_two_header_blocks_are_ambiguous_before_any_parse PASSED [ 10%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_malformed_header_and_unreadable_run_id_are_malformed PASSED [ 14%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_two_roadmap_blocks_are_ambiguous_even_when_each_is_valid PASSED [ 17%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_malformed_roadmap_is_malformed PASSED [ 21%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_duplicate_node_id_is_ambiguous PASSED [ 25%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_roadmap_free_objective_has_zero_targets PASSED [ 28%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_happy_path_identity_source_order_and_normalization PASSED [ 32%]
tests/test_github_refinement.py::TestRefinementTargetRead::test_store_read_over_the_fake PASSED [ 35%]
tests/test_github_refinement.py::TestGuardedUpsertOverGitHub::test_create_update_convergence_identity_transcode PASSED [ 39%]
tests/test_github_refinement.py::TestGuardedUpsertOverGitHub::test_duplicate_owners_across_pages_and_a_sole_owner_on_the_last_page PASSED [ 42%]
tests/test_github_refinement.py::TestGuardedUpsertOverGitHub::test_too_long_bodies_are_backend_error_with_the_diagnostic PASSED [ 46%]
tests/test_github_refinement.py::TestGuardedUpsertOverGitHub::test_preflight_refusals_dry_run_and_the_ordinary_path PASSED [ 50%]
tests/test_github_refinement.py::TestCoexistenceFilters::test_marker_finder_skips_a_refinement_quoting_the_marker PASSED [ 53%]
tests/test_github_refinement.py::TestCoexistenceFilters::test_objective_body_recovery_backfills_the_real_comment PASSED [ 57%]
tests/test_github_refinement.py::TestCoexistenceFilters::test_plan_body_scans_skip_a_refinement_carrying_a_plan_example PASSED [ 60%]
tests/test_github_refinement.py::TestCoexistenceFilters::test_dream_companion_scan_skips_a_refinement_quoting_its_marker PASSED [ 64%]
tests/test_github_refinement.py::TestCoexistenceFilters::test_engagement_renders_omit_the_refinement_and_node_engagement_stays_empty PASSED [ 67%]
tests/test_github_refinement.py::TestServiceOverGitHub::test_select_save_read_replace_and_retry PASSED [ 71%]
tests/test_github_refinement.py::TestServiceOverGitHub::test_node_context_assembly_present_absent_and_ambiguous PASSED [ 75%]
tests/test_github_refinement.py::test_phase2_gate_github_refinement_persistence[incremental] PASSED [ 78%]
tests/test_github_refinement.py::test_phase2_gate_github_refinement_persistence[stacked] PASSED [ 82%]
tests/test_refinement_cross_backend_gate.py::test_phase2_gate_github_refinement_doors PASSED [ 85%]
tests/test_refinement_cross_backend_gate.py::test_github_error_translation_at_the_refinement_doors PASSED [ 89%]
tests/test_refinement_cross_backend_gate.py::test_node_engagement_json_and_seed_pointer_shape_parity_across_backends[linear] PASSED [ 92%]
tests/test_refinement_cross_backend_gate.py::test_node_engagement_json_and_seed_pointer_shape_parity_across_backends[github] PASSED [ 96%]
tests/test_refinement_cross_backend_gate.py::test_sync_that_flips_the_route_to_github_selects_over_github_fresh_adapters PASSED [100%]

============================== 28 passed in 5.31s ==============================
```

```
$ node --test extension/pi/v1/objectiveRefinement.test.ts
✔ golden: the Python-serialized context decodes strictly and its digest is the pinned sha256
✔ decode: every structural defect is a classified refusal naming the path
✔ validateContextTransfer: digest over the EXACT bytes, run binding, malformed digests
✔ import + resume: the UNCHANGED raw bytes land as the session artifact (byte identity), re-import is unchanged
✔ resume: absent / corrupt / dropped / foreign-run / wrong-run artifacts classify, never fall back
✔ cold import: only the actual objective-refine claim imports; every defect refuses fail-closed
✔ parseRefineCommandArgs: positional + --node forms; every extra/duplicate/missing shape refuses
✔ decodeRefinementDraftParams: exactly { markdown: string }
✔ decideWarmRefinementAdmission: the strict admission table
✔ registration: exactly one model tool (objective_refinement_draft), two commands; NO objective_refinement_save
✔ objective_refinement_draft: writes the context-bound envelope; unchanged on identical bytes; classified refusals
✔ objective_refinement_draft: refuses outside a refinement session (wrong_stage) regardless of the gate; no context → refinement_context_missing
✔ plan-graph surfaces refuse inside a refinement session: tools → wrong_stage, commands → warning; nothing executed
✔ /objective-refinement-save: saves the EXACT draft bytes through the worker; labelled a manual human save; gate exits
✔ /objective-refinement-save: no args only; wrong_stage; busy; no draft / no context / refused draft stop without a worker call
✔ /objective-refinement-save: a failed worker keeps the gate ON and relays the typed diagnostics
✔ /objective-refinement-save: the deliberate retry — a failed save latches automatic saves off, the manual command still runs the worker
✔ plan_review in a refinement session: no draft → no_refinement_draft; a well-typed plan param is ignored
✔ plan_review first-party approval saves the artifact bytes through the worker and terminates; deny/skip never save
✔ refinementSaveDestination: Linear and GitHub carriers by name; an unrecognized backend id renders verbatim
✔ first-party approve label names the bound carrier per backend — a GitHub-bound pair approves only under the GitHub label
✔ plan_review first-party: an approval never saves a replacement — draft rewritten, context re-prepared, or binding changed during the human wait
✔ plannotator arm: a plain approval saves the EXACT reviewed draft bytes once through the worker, exits the gate, terminates
✔ plannotator arm: approval carrying Direct Edits is one revise round — no worker call, no gate exit, not terminating
✔ plannotator arm: a denial saves nothing and redirects to the draft tool
✔ plannotator arm: a draft rewritten while the review is pending blocks the late approval — stale-approval, worker never invoked
✔ plannotator arm: a context re-prepared while the review is pending blocks the late approval — the context digest, worker never invoked
✔ plannotator arm: an unrelated TOML edit during the review leaves the approval saving once; a routing edit refuses naming its component
✔ plannotator arm: a failed worker surfaces the feature's typed save failure, latches automatic saves off, gate stays ON
✔ plannotator arm: an APPROVE arriving after a newer review opened is superseded — ignored loudly, worker never invoked, the newer review stays current
✔ /objective-refine (warm): unbound session → worker context imported byte-exact, stage entered, gate scoped, guidance driven
✔ /objective-refine (warm): refusals leave state untouched — bad args, objective_required, bound_session, busy, worker failure, digest mismatch
✔ cold claim: an objective-refine handoff imports the run-scratch transfer once, byte-exact; the gate + flavor follow the stage
✔ cold claim: a contaminated objective-refine handoff is refused before claiming; a digest mismatch imports nothing
✔ warm /objective-refine (harness): an idle unbound session with an active objective enters refinement and injects the flavored contexts
✔ warm /objective-refine (harness): plan-mode contexts ALREADY injected before the transition are stripped — only the refinement flavors direct the model afterwards
✔ warm /objective-refine (harness): a worker envelope bound to ANOTHER run is refused fail-closed — nothing imported, nothing driven
ℹ tests 37
ℹ pass 37
ℹ fail 0
```

## Cross-references

- [objective-refinement-linear-persistence.md](objective-refinement-linear-persistence.md) — the
  Linear persistence gate (offline).
- [objective-refinement-linear-planning-dogfood.md](objective-refinement-linear-planning-dogfood.md)
  — the authenticated Linear refine→plan run; its first residual (the GitHub carrier) is resolved
  by this record, offline only.
- `shared/contracts.md` §8.67 (persistence, the GitHub arm and both gates) and §8.68 (the doors on
  both backends).
