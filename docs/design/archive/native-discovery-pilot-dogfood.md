# Native-discovery pilot: dogfood evidence

**Status:** evidence record (Objective #2634, Node 3.2). The binding record — the cohort, the
pinned adopt/retire criteria, the measurements and the decision — is
[`docs/design/native-discovery-pilot.md`](../native-discovery-pilot.md); this file holds the raw
evidence it cites. The archive location is the status signal.

## §1 Baseline census (the unchanged catalog)

Measured with `PERK_PRINT_DISCOVERY_CENSUS=1 node --test extension/substrate/discoveryPilot.test.ts`
(case 8) on 2026-10-02, Pi 0.99.2, on the tree of the commit that introduces this file — its
parent is `d7d7f17b` (the behaviour-neutral harness lift over `eb3c526d`); the catalog is the
base's, so no tool is `declared: "deferred"` yet and both arms declare the same perk tools. The
cohort arm loads the identical extension set plus `defaultTools: ["+tool_search"]`, so the whole
difference is `tool_search`'s own declaration and snippet line (the fixed cost).

Verbatim stderr:

```text
Per-tool census (implement session; request = JSON {description, parameters}; prompt = snippet + guidelines):

| tool | kind | gated | stages | request bytes | prompt bytes |
|---|---|---|---|---|---|
| `plan_draft` | action | carve-out | plan, save, objective-plan | 436 | 341 |
| `objective_draft` | action | carve-out | objective-author, objective-save | 4237 | 592 |
| `gist_draft` | action | carve-out | gist-author, gist-save | 865 | 504 |
| `objective_refinement_draft` | action | carve-out | objective-refine | 705 | 634 |
| `objective_stack_adopt` | action | blocked | implement, submit, address, land, learn | 746 | 276 |
| `objective_stack_recover` | action | blocked | implement, submit, address, land, learn | 1225 | 735 |
| `objective_stack_land` | action | blocked | implement, submit, address, land, learn | 829 | 538 |
| `objective_stack_status` | query | blocked | implement, submit, address, land, learn | 422 | 244 |
| `post_pr_review` | action | blocked | implement, submit, address, land, learn | 1965 | 2228 |
| `submit_pr_review` | action | blocked | implement, submit, address, land, learn, stack-review | 2199 | 1690 |
| `collect_review_wave` | action | blocked | implement, submit, address, land, learn, stack-review | 436 | 1191 |
| `collect_draft_review_wave` | action | allowed | plan, save, objective-plan, objective-author, objective-save | 430 | 1191 |
| `push_annotations` | action | allowed | plan, save, objective-plan, objective-author, objective-save, implement, submit, address, land, learn, stack-review | 1914 | 1850 |
| `run_ci` | action | blocked | implement, submit, address, land, learn | 511 | 946 |
| `objective_node` | action | carve-out | objective-author, objective-save, objective-plan, implement, submit, address, land, learn | 1232 | 532 |
| `reconcile_objective` | action | blocked | objective-author, objective-save, objective-plan, implement, submit, address, land, learn | 687 | 569 |
| `add_objective_node` | action | blocked | objective-author, objective-save, objective-plan, implement, submit, address, land, learn | 1227 | 783 |

Per-stage census request bytes (declared + system prompt), read-write; fixed cost = 693:

| stage | nonparticipant | cohort | net |
|---|---|---|---|
| gist-author | 8443 | 9136 | -693 |
| gist-save | 8443 | 9136 | -693 |
| objective-author | 38246 | 38939 | -693 |
| objective-save | 30718 | 31411 | -693 |
| objective-plan | 30235 | 30928 | -693 |
| plan | 23728 | 24421 | -693 |
| save | 18822 | 19515 | -693 |
| implement | 51093 | 51786 | -693 |
| submit | 51093 | 51786 | -693 |
| address | 51093 | 51786 | -693 |
| land | 51093 | 51786 | -693 |
| learn | 51093 | 51786 | -693 |
| audit | 6811 | 7504 | -693 |
| objective-refine | 9287 | 9980 | -693 |
| stack-review | 19639 | 20332 | -693 |
```

## §2 Cohort census (the pilot family deferred)

Pending — filled from the re-run at the measured commit.

## §3 Live-leg ledger

Pending — each leg is human-typed in a cohort worktree session and recorded from declared-tools /
transcript facts (never model self-report), with its commit SHA and PASS / NOT PASSED.

| Leg | Session kind | Commit | Observed | Result |
|---|---|---|---|---|
| D3 — review door → `start_review_wave` → `collect_review_wave` → `push_annotations`/`submit_pr_review` | cohort worktree | — | — | NOT PASSED (unobserved) |
| D4 — `objective_stack_status` found through `tool_search` on the first query | cohort implement | — | — | NOT PASSED (unobserved) |
| D5 — `/plan` → `plan_draft` → `plan_review` → wave chooser → collect | cohort worktree | — | — | NOT PASSED (unobserved) |
| P4 live — `perk learn evidence --render` over the nested-probe transcript | — | — | — | NOT PASSED (unobserved) |
