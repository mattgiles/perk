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

Measured with the same command on 2026-10-02, Pi 0.99.2, at `5f0cb619` (the four family flags,
the cohort join, the primers and the acceptance tests). The nonparticipant arm reproduces §1
byte-for-byte except `stack-review` (+10 bytes: `open_stack_review`'s guideline reworded from
"stream findings via push_annotations" to "stream findings into the browser as it directs" after
the deferred rule's carrier census flagged it). Re-run at the decision commit before the decision.

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
| objective-author | 38246 | 33418 | 4828 |
| objective-save | 30718 | 25890 | 4828 |
| objective-plan | 30235 | 25407 | 4828 |
| plan | 23728 | 18900 | 4828 |
| save | 18822 | 13994 | 4828 |
| implement | 51093 | 45542 | 5551 |
| submit | 51093 | 45542 | 5551 |
| address | 51093 | 45542 | 5551 |
| land | 51093 | 45542 | 5551 |
| learn | 51093 | 45542 | 5551 |
| audit | 6811 | 7504 | -693 |
| objective-refine | 9287 | 9980 | -693 |
| stack-review | 19649 | 14827 | 4822 |
```

The D1 run (case 6, same invocation; `details.loaded` in rank order):

```text
D1 implement "collect the adversarial review wave reports" → ["collect_review_wave","collect_draft_review_wave","push_annotations","objective_stack_status"]
D1 implement "push findings to the browser as annotations" → ["push_annotations"]
D1 implement "stacked delivery train status" → ["objective_stack_status"]
D1 plan "collect the draft review wave reports" → ["collect_draft_review_wave","collect_review_wave","push_annotations","objective_stack_status"]
```

The nested probe (case 7, `PERK_PRINT_DISCOVERY_CENSUS=1 node --test
extension/substrate/discoveryNested.test.ts`) — the records Pi persisted on the parent tool result:

```text
cancelled record: {"calls":[{"id":"call-fixture_nested_probe/1","name":"objective_stack_status","status":"error","arguments":{"objective":"7"},"durationMs":0,"error":"Operation aborted"}],"complete":true}
oversized record: {"calls":[{"id":"call-fixture_nested_probe/1","name":"push_annotations","status":"error","argumentsBytes":9103,"durationMs":2,"error":"push_annotations failed: no annotation surface is primed — push_annotations only works inside a door-opened plannotator review flow (the door primes the surface when the browser opens)"}],"complete":false}
```

## §3 Live-leg ledger

Pending — each leg is human-typed in a cohort worktree session and recorded from declared-tools /
transcript facts (never model self-report), with its commit SHA and PASS / NOT PASSED.

| Leg | Session kind | Commit | Observed | Result |
|---|---|---|---|---|
| D3 — review door → `start_review_wave` → `collect_review_wave` → `push_annotations`/`submit_pr_review` | cohort worktree | — | — | NOT PASSED (unobserved) |
| D4 — `objective_stack_status` found through `tool_search` on the first query | cohort implement | — | — | NOT PASSED (unobserved) |
| D5 — `/plan` → `plan_draft` → `plan_review` → wave chooser → collect | cohort worktree | — | — | NOT PASSED (unobserved) |
| P4 live — `perk learn evidence --render` over the nested-probe transcript | — | — | — | NOT PASSED (unobserved) |
