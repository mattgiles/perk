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
the deferred rule's carrier census flagged it). Re-run at the decision commit `1045863d` (after
the review fixes): both tables and the D1 results are byte-identical to the ones below.

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
| D3 — review door → `start_review_wave` → `collect_review_wave` → `push_annotations`/`submit_pr_review` | cohort implement session `01a0fd25-a296-72f2-bfff-2896927c1fe9` (after `/reload`), `/pr-review-browser` active arm on PR #2650 | `89a77fcc` | The transcript's tool-change entry adding `collect_review_wave` + `push_annotations` precedes the door's guidance and the model's first call. `start_review_wave` ok (4/4 lanes runnable, run `f1a6801b-d625-404e-905d-58eab4a1a240`), `collect_review_wave` ok (complete, 4/4 covered, no failures), four `push_annotations` calls ok (none held). Zero `tool_search` calls, zero dead-end turns. The human posted a COMMENT review from the browser; perk posted nothing. | PASS |
| D4 — `objective_stack_status` found through `tool_search` on the first query | the same cohort implement session (`objective_stack_status` deferred and inactive since the reload; no door primed it) | `4a83ebb6` | The human asked "What's the stacked delivery status of objective 2634?" without naming a tool. The model's first call was `tool_search` ("objective stacked delivery train status") → `details.loaded = ["objective_stack_status"]`; the transcript's tool-change entry added it; the next call `objective_stack_status {objective: 2634}` returned `ok: true` ("this objective uses incremental delivery; no delivery train exists"). Zero dead-end turns. Caveat: the model had authored the pilot in this session and knew the tool's name and D1's pinned queries, so this leg proves the live search-and-activate path more than naive discoverability (D1 carries the scored discoverability). | PASS |
| D5 — `/plan` → `plan_draft` → `plan_review` → wave chooser → collect | the same cohort implement session, under the `/plan` toggle (read-only) | `54022d2e` | `plan_draft` ok, `plan_review` → the chooser's "Browser review + reviewer wave" arm. Its result is followed by the transcript's tool-change entry adding `collect_draft_review_wave` (`push_annotations` was still active from D3 and gate-allowed) before the model's next call. `start_draft_review_wave` ok (3/3 lanes, run `cad11001-e5e9-42ad-af62-beb0325717cb`), `collect_draft_review_wave` ok (complete, 3/3 covered, no failures, no findings), three `push_annotations` (empty, `replace: true`) accepted. Zero `tool_search` calls, zero dead-end turns. The human then approved by accident, which saved the throwaway draft as plan #2651 and exited the gate (the collector left the active set — ineligible read-write in implement, as planned). | PASS |
| P4 live — `perk learn evidence --render` over the nested-probe transcript | the case 7 probe session (`discoveryNested.test.ts`, cohort implement) | `d6de65da` | `perk learn evidence` gathers only a plan's own linked sessions, so the leg runs its render step — `perk.learn.normalize.render_evidence`, the function `--render` calls — over the probe JSONL. The chunk carries three `<nested_calls>` blocks: `complete="true"` with `objective_stack_status` `status="ok"` and its args; `complete="true"` with `status="error"` and `<error>Operation aborted</error>`; `complete="false"` with `push_annotations` `args_omitted_bytes="9103"` and the tool's `no_surface` refusal (excerpt §5). The render also counted one malformed line: Pi's `role: "system"` message entry, which the session parser does not recognize — an unrelated parser gap. | PASS |

## §4 `/perk-selfcheck` in the cohort sessions

The implement session `01a0fd25-a296-72f2-bfff-2896927c1fe9`, after `/reload` at `89a77fcc`:

```text
  tools: 35 active / 66 registered; schemas=39008c; guidelines=0c; snippets=4502c
  discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)
```

The reload's transcript tool-change entry: added `tool_search`; removed `objective_stack_status`,
`collect_review_wave`, `push_annotations` (the join's one-time deactivation; `collect_draft_review_wave`
is not eligible in a read-write implement session, so it was never active there).

## §5 The P4 render excerpt

`render_evidence` over the case 7 probe session (its three probe turns' tool results):

```text
<nested_calls complete="true">
<nested_call id="call-fixture_nested_probe/1" name="objective_stack_status" status="ok" ms="336"><args>{&quot;objective&quot;: &quot;7&quot;}</args></nested_call>
</nested_calls></tool_result>
…
<nested_calls complete="true">
<nested_call id="call-fixture_nested_probe/1" name="objective_stack_status" status="error" ms="1"><args>{&quot;objective&quot;: &quot;7&quot;}</args><error>Operation aborted</error></nested_call>
</nested_calls></tool_result>
…
<nested_calls complete="false">
<nested_call id="call-fixture_nested_probe/1" name="push_annotations" status="error" ms="3" args_omitted_bytes="9103"><error>push_annotations failed: no annotation surface is primed — push_annotations only works inside a door-opened plannotator review flow (the door primes the surface when the browser opens)</error></nested_call>
</nested_calls></tool_result>
```
