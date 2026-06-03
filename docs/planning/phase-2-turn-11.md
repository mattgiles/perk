# Phase 2 · Turn 11 — objective reconciliation after landing

> The decision-complete plan lives on GitHub issue
> [#23](https://github.com/mattgiles/perk/issues/23) (`plan-body` block). This doc records the
> per-turn decisions in brief + the as-built **outcomes** once landed.

## Summary

Close the objective loop: when a PR linked to an objective node merges, the roadmap reconciles
against what was *actually* built. Two seams matching the D9 section-boundary typing:

- **T11a — Mechanical (deterministic, on land).** The cold land path auto-marks the objective
  node(s) backlinked to the just-merged plan `done` — **fail-open** (the merge already succeeded;
  objective tracking never blocks landing) and **deliberately non-audited**.
- **T11b — Reconcilable (LLM judgment, post-merge, warm).** A `/objective-reconcile` surface + a
  `perk-objective-reconcile` skill drive the model to reconcile stale objective **prose** (and node
  descriptions) against the real diff. The objective-body prose gains a marker-bounded
  **Reconcilable** region; the Mechanical roadmap table and any **Immutable** notes are structurally
  protected — the splice can only rewrite the Reconcilable region.

## Decisions (as planned)

- **D1** — `objective.nodes_for_pr` (pure): canonicalize PR numbers to `"#<n>"` and match node `pr`
  backlinks. `objective.replace_reconcilable_section` (pure): splice between the
  `perk:objective-reconcilable` markers; `None` when absent. `render_body_comment` now emits the
  Reconcilable markers (empty + non-empty prose).
- **D2** — `pr_land_cmd._reconcile_objective_on_land` (never raises): parse `objective_id` → skip
  reasons (`no_objective_link` / `bad_objective_id` / `objective_not_found` / `no_linked_node`,
  `error:<exc>` on any failure logged to stderr). Called in the non-dry-run land branch after
  `set_marker(PENDING_LEARN)`; dry-run sets an inert `dry_run` update. `_result_to_dict` always
  carries `objective`; `_render_human` adds a marked-node line.
- **D3** — `github.update_objective_body` + `ObjectiveBodyUpdate`: read `objective_comment_id`,
  fetch comment, `replace_reconcilable_section`, PATCH; raise `GitHubError` (`no body comment` /
  `no reconcilable region`) on a missing target.
- **D4** — `perk objective reconcile NUMBER --body @FILE [--dry-run] [--json]`: cold worker mapping
  the two missing-target errors to `reconcile_target_missing`. Node-description reconciliation reuses
  the existing `objective node --description`.
- **D5** — `extension/objectivePlan.ts`: `description?` on the `objective_node` tool
  (`buildObjectiveNodeArgs` relaxed so a `description`-only call is valid; `status:"done"` audit
  gate unchanged); a `reconcile_objective` warm tool (scratch-file delegate, never throws); a
  `/objective-reconcile` command with three-tier resolution (`resolveReconcileObjective`: arg →
  active → `plan_ref.objective_id`).
- **D6** — `extension/land.ts`: surface `objective.nodes_marked` + a copy-pasteable
  `/objective-reconcile #<n>` nudge; carry `objective` into `details`.
- **D7** — `land` registry I/O gains `github.objective` in both `reads` and `writes`.
- **D8** — `skills/perk-objective-reconcile/SKILL.md`: the judgment layer (untrusted DATA inputs,
  Mechanical/Reconcilable/Immutable boundary, contradiction taxonomy, skip-if-stale,
  never-delegate). `shared/contracts.md` §8.3 + §8.4 amended; the §8.4 D9 "deferred to T11" residue
  flipped to "implemented in P2.T11".

## Outcomes (as built)

- Implemented exactly as planned. All eight key-change areas landed: `perk/objective.py`
  (`nodes_for_pr`, `canonical_pr`, `OBJECTIVE_RECONCILABLE_MARKER_*`, `replace_reconcilable_section`,
  Reconcilable-wrapping `render_body_comment`), `perk/github.py` (`ObjectiveBodyUpdate`,
  `update_objective_body`), `perk/cli/commands/pr_land_cmd.py` (`ObjectiveLandUpdate`,
  `_reconcile_objective_on_land`, threaded onto `PrLandResult` + `_result_to_dict` + `_render_human`),
  `perk/cli/commands/objective_cmd.py` (`objective reconcile`), `extension/objectivePlan.ts`
  (`description` param, `reconcile_objective` tool, `/objective-reconcile`, `resolveReconcileObjective`),
  `extension/land.ts` (objective surfacing + nudge), `shared/registry.yaml` (land I/O),
  `skills/perk-objective-reconcile/SKILL.md`, `shared/contracts.md` (§8.3/§8.4 + deferral flip).
- **Deviation:** the `/objective-reconcile` three-tier resolution was extracted into an **exported
  pure `resolveReconcileObjective(args, ctx)`** so it is unit-testable offline (the command handler's
  `pi.sendUserMessage` triggers a real model turn, which the harness cannot exercise without an API
  key). This is a small, test-driven refactor of the inline resolution; behavior is identical.
- **Offline boundary (dogfood/manual gate, not CI):** the live merge→mechanical-node-done and the
  live `/objective-reconcile` model turn need a real GitHub + model — recorded here when exercised
  (mirrors T7/T9/T10).
- Hard gate: `scripts/verify-p2-t11.sh` (9 checks, all offline) green; wired into `just verify`
  after `verify-p2-t10.sh`.
