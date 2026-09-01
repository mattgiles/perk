---
title: "Model-facing tools"
description: "The complete guarded census of perk-owned, borrowed-package, and spawned-child tools with their gating and stage-scoping rules."
sidebar:
  order: 3024
---

# Model-facing tools

A model tool is a typed operation the agent can call. Tool registration is distinct from command
registration and from stage-door availability. The three marked tables below are guarded against
the live extension authorities; each row contains exactly one tool name.

## Perk-owned tools

These tools are registered by perk itself. Command-specific semantics live in
[Workflow commands](./workflow-commands.md) and
[Review and authoring](./review-and-authoring.md).

<!-- BEGIN perk tool census -->
| Family | Tool |
| --- | --- |
| Plan authoring | `plan_review` |
| Plan authoring | `plan_save` |
| Plan authoring | `plan_draft` |
| Objective authoring | `objective_save` |
| Objective workflow | `objective_node` |
| Objective workflow | `reconcile_objective` |
| Objective workflow | `add_objective_node` |
| Objective authoring | `objective_draft` |
| Gist authoring | `gist_draft` |
| Gist authoring | `gist_save` |
| Learn lifecycle | `learn` |
| Learn lifecycle | `run_learn_wave` |
| Developer analysis | `run_audit_wave` |
| Learn factories | `run_harvest_wave` |
| Learn factories | `run_dream_wave` |
| PR lifecycle | `land` |
| Automated review | `post_pr_review` |
| PR lifecycle | `ready` |
| Address loop | `classify_review_feedback` |
| Address loop | `finalize_address` |
| Objective workflow | `explore_objective_node` |
| Automated review | `run_pr_review_wave` |
| Human PR review | `submit_pr_review` |
| Human PR review | `start_review_wave` |
| Human PR review | `collect_review_wave` |
| Browser review | `push_annotations` |
| Human PR review | `open_stack_review` |
| Draft review | `start_draft_review_wave` |
| Draft review | `collect_draft_review_wave` |
| Verification | `run_ci` |
| PR lifecycle | `submit` |
| Stacked delivery | `objective_stack_status` |
| Stacked delivery | `objective_stack_sync` |
| Stacked delivery | `objective_stack_adopt` |
| Stacked delivery | `objective_stack_recover` |
| Stacked delivery | `objective_stack_land` |
<!-- END perk tool census -->

The terminating subset ends the current turn on its success path: `plan_save`, `objective_save`,
`gist_save`, `submit`, `ready`, `finalize_address` on full success, `land`, `learn`, and
`plan_review` when approval completes its save. Other perk-owned tools are non-terminating.

## Borrowed-package tools

Perk enumerates the following package/provider names so stage scoping can remove known foreign
schemas deterministically. A name can be inert when its package or provider is not loaded.

<!-- BEGIN borrowed tool census -->
| Group | Tool |
| --- | --- |
| Web research | `web_search` |
| Web research | `code_search` |
| Web research | `fetch_content` |
| Web research | `get_search_content` |
| Web research | `ollama_web_search` |
| Web research | `ollama_web_fetch` |
| Web research | `web_fetch` |
| Linear reads | `linear_whoami` |
| Linear reads | `linear_workspace_metadata` |
| Linear reads | `linear_list_teams` |
| Linear reads | `linear_get_team` |
| Linear reads | `linear_list_users` |
| Linear reads | `linear_get_user` |
| Linear reads | `linear_list_issues` |
| Linear reads | `linear_get_issue` |
| Linear reads | `linear_search_issues` |
| Linear reads | `linear_list_my_issues` |
| Linear reads | `linear_list_projects` |
| Linear reads | `linear_get_project` |
| Linear reads | `linear_list_issue_statuses` |
| Linear reads | `linear_get_issue_status` |
| Linear reads | `linear_list_labels` |
| Linear reads | `linear_list_cycles` |
| Linear reads | `linear_list_documents` |
| Linear reads | `linear_get_document` |
| Linear reads | `linear_list_comments` |
| Linear mutators | `linear_create_issue` |
| Linear mutators | `linear_update_issue` |
| Linear mutators | `linear_create_comment` |
| Linear mutators | `linear_upload_file` |
| Linear mutators | `linear_upload_file_to_issue_comment` |
| Linear mutators | `linear_configure_auth` |
| Delegation | `subagent` |
| Delegation | `wait` |
| Delegation | `subagent_supervisor` |
| Delegation | `intercom` |
| FFF search | `fffind` |
| FFF search | `ffgrep` |
| FFF search | `fff-multi-grep` |
| FFF search | `multi_grep` |
| Checklist/questionnaire | `todo` |
| Checklist/questionnaire | `ask_user_question` |
| Plannotator | `plannotator_submit_plan` |
<!-- END borrowed tool census -->

`ask_user_question` is registered by the questionnaire package only when an interactive UI is
available; a headless session carries no schema for it. Web research, Linear reads, and FFF search
stay available across every known stage. Delegation and the checklist join the worktree-stage
family. Linear mutators and `plannotator_submit_plan` are intentionally absent from every stage
session even though they remain enumerated here; Linear mutations stay in perk's canonical Python
plane and perk bridges review without Plannotator's submit tool. Bare unscoped Pi sessions retain
their package-provided tools.

For package selection, registration timing, and provider fallback behavior, use the
[Providers reference](../providers-and-backends/providers.md).

## Spawned-child tools

These engine tools are not parent-stage tools. They exist only in spawned-child contexts and are
kept reachable when a child adopts a read-only gate.

<!-- BEGIN child tool census -->
| Purpose | Tool |
| --- | --- |
| Schema-validated completion | `structured_output` |
| Child-to-parent coordination | `contact_supervisor` |
| Fan-out waiting | `subagent_wait` |
<!-- END child tool census -->

## Gating and stage scoping

### Structural read-only gate

When read-only mode is active, perk installs `READ_ONLY_TOOLS` as the active set. The gate blocks
Pi's `edit` and `write` builtins structurally and accepts `bash` only when every command segment is
on the read-only sub-allowlist. The sanctioned artifact writers and review/exploration companions
remain available because they write only run-scoped session data, drive local review surfaces, or
spawn read-only analysis. Research and delegation remain available under the documented posture.

A spawned child that adopts a read-only parent state inherits the gate: worktree edits stay blocked
and bash stays sub-allowlisted, while the three child-only engine tools remain usable. Children of
read-write sessions are not gate-restricted.

### Stage tool diet

With the gate off and a known stage active, `STAGE_TOOLS` subtractively filters the scoped universe
`PERK_TOOLS ∪ BORROWED_TOOLS`. Each stage receives its own authoring/lifecycle tools plus the
research family. The five worktree stages — implement, submit, address, land, and learn — share the
whole PR-loop family so a later warm command cannot dead-end in an earlier worktree session. That
shared family includes submission, readiness, CI, review/address, land/learn, reconciliation, and
stack-control operations, plus delegation and the checklist.

Pi owns its builtins (`read`, `edit`, `write`, `bash`, `grep`, `find`, and related host tools); this
reference does not redefine them. Stage scoping is fail-open at compatibility boundaries: a bare
session, an unknown stage id, and an unenumerated foreign tool are not filtered. Read-only mode is
the opposite safety posture for worktree mutation: its tool-call backstop fails closed on internal
errors.

## Related

- **Look up:** [Stages and doors](./stages-and-doors.mdx) — see which stage/door posture activates
  these rules.
- **Look up:** [Review and authoring](./review-and-authoring.md) — follow the review-tool lifecycles.
- **Look up:** [In-session commands & tools](../in-session.md) — return to the complete surface map.
