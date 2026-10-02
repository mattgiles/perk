# Native-discovery pilot: cohort, criteria, measurements, decision

**Status:** binding record (Objective #2634, Node 3.2). **Decision: ADOPT** (§7) — every pinned
criterion passed, the four live legs included, run from this PR's own delivery flow. The raw evidence (verbatim census tables, the
live-leg ledger) is [`archive/native-discovery-pilot-dogfood.md`](./archive/native-discovery-pilot-dogfood.md);
the cross-plane contract is `shared/contracts.md` §8.40 **The discovery pilot**.

## 1. Context

- **Pi** 0.99.2 (the installed `@earendil-works/pi-coding-agent`, re-checked at implement start);
  **perk** 3.9.0.
- **Baseline commit** `4912cc12` — the census over the unchanged catalog (no tool deferred), on
  the behaviour-neutral harness lift `d7d7f17b` over the base `eb3c526d`.
- **Measured commit** `5f0cb619` — the pilot runtime (`f29bf9d9`), the primers (`d06f6a62`), the
  prompt guard's deferred rule (`288d5483`), the opt-in (`ff468b97`) and the acceptance tests
  (`5f0cb619`). **Decision commit** `1045863d` (after the review fixes): §5 re-measured there,
  byte-identical per tool and per stage; D1 unchanged.
- The question the pilot answers: does deferring a small, optional family of perk tools behind
  Pi's builtin `tool_search` save enough per request, at a small enough fixed cost, without
  dead-ending any flow — measured, not estimated.

## 2. The cohort and the nonparticipants

A session joins the **discovery cohort** iff its host has Pi's builtin `tool_search` registered
**and** active at `session_start` (`isDiscoveryHost`; a foreign `tool_search` namesake never
qualifies). The opt-in is the hand-written `defaultTools: ["+tool_search"]` entry in this repo's
tracked `.pi/settings.json` — the only placement that reaches worktree stage sessions; `perk init`
tolerates it and never converges it (P5).

In the cohort, perk re-registers the family deferred at `session_start` (before the first sync),
switches it off in that same single install, and thereafter keeps a member exactly while it is
active and eligible. A member comes back only by **primed activation** (a door or launcher whose
carrier names it) or by `tool_search` / a `/tree` restore.

**Nonparticipants by construction** keep today's always-declared loadout: a session without the
opt-in or with a foreign namesake, the headless worker (its runtime loads no `tool_search`
factory), `/btw`'s side session (`sideSessionTools` carries no extension builtin) and every spawned
report child (it registers no perk tool).

## 3. The family and its selection

The candidate population is the catalog's `query`/`action` tools registered in a census session —
17 production names. Bytes are measured in an implement session (request = JSON
`{description, parameters}`; prompt = snippet + guidelines), verbatim from the case 8 census:

| Tool | Kind | Gated | Stages | Request B | Prompt B | Self-guarding refusal | Primer(s) / why not in the family |
|---|---|---|---|---|---|---|---|
| `objective_stack_status` | query | blocked | worktree | 422 | 244 | `no_objective` (a read) | `STACK_STATUS_PRIMES` (`/objective-sync`, `/objective-land`) |
| `collect_review_wave` | action | blocked | worktree, stack-review | 436 | 1191 | `no_wave` (the pending-wave guard) | `REVIEW_BROWSER_PRIMES`, `REVIEW_TERMINAL_PRIMES`, `REVIEW_LAUNCH_PRIMES` |
| `collect_draft_review_wave` | action | allowed (mode over stage) | plan family, objective | 430 | 1191 | `no_wave` (the pending-wave guard) | `DRAFT_REVIEW_DOOR_PRIMES`, `DRAFT_LAUNCH_PRIMES` |
| `push_annotations` | action | allowed (mode over stage) | plan family, objective, worktree, stack-review | 1914 | 1850 | `no_surface` | `REVIEW_BROWSER_PRIMES`, `DRAFT_REVIEW_DOOR_PRIMES` |
| `plan_draft` | action | carve-out | plan family | 436 | 341 | — | carve-out (deferral refused by policy) |
| `objective_draft` | action | carve-out | objective | 4237 | 592 | — | carve-out |
| `gist_draft` | action | carve-out | gist | 865 | 504 | — | carve-out |
| `objective_refinement_draft` | action | carve-out | objective-refine | 705 | 634 | — | carve-out |
| `objective_node` | action | carve-out | objective, objective-plan, worktree | 1232 | 532 | — | carve-out |
| `run_ci` | action | blocked | worktree | 511 | 946 | — | named by the cold implement seed (nothing on that plane primes) |
| `objective_stack_adopt` | action | blocked | worktree | 746 | 276 | — | outside the bounded family |
| `objective_stack_recover` | action | blocked | worktree | 1225 | 735 | — | outside the bounded family |
| `objective_stack_land` | action | blocked | worktree | 829 | 538 | — | outside the bounded family |
| `post_pr_review` | action | blocked | worktree | 1965 | 2228 | — | outside the bounded family |
| `submit_pr_review` | action | blocked | worktree, stack-review | 2199 | 1690 | — | outside the bounded family |
| `reconcile_objective` | action | blocked | objective, objective-plan, worktree | 687 | 569 | — | outside the bounded family |
| `add_objective_node` | action | blocked | objective, objective-plan, worktree | 1227 | 783 | — | outside the bounded family |

The family (owner decision in planning) satisfies all three selection properties: **optional** —
each is opened only by a carrier a primer serves; **self-guarding** — each execute core refuses
outside its flow, so making it nested-callable while undeclared widens nothing a script could not
reach when it was an active direct tool; **schema-heavy** — 7,678 bytes of request + prompt
together (the table's columns summed). A carve-out writer can never be deferred: the read-only context names carve-out writers,
and an undeclared one would dead-end (`validateToolPolicy` refuses it).

## 4. Adopt/retire criteria (pinned before measurement)

Verbatim from the plan; the status column is filled from the evidence named.

| Id | Criterion | Evidence | Status |
|---|---|---|---|
| S1 | `net(stage) ≥ 4,096` bytes per census request in every stage where a family member is eligible read-write (the five worktree stages, `plan`/`save`/`objective-plan`, `objective-author`/`objective-save`, `stack-review`) | case 8 | PASS (min 4,822 — `stack-review`) |
| S2 | the cohort's fixed cost (`tool_search`'s declaration + snippet, measured as `−net` in a stage with no eligible member) `≤ 1,024` bytes | case 8 | PASS (693) |
| D1 | each family member is `tool_search`'s top-1 hit for its pinned query where eligible — **scored on the four queries pinned in case 6 exactly as written**; a miss is NOT PASSED; a query may be changed only by an owner-approved amendment recorded in the design record (date, reason, old → new) BEFORE the amended run is scored, and any other reworded query is an exploratory observation, never D1's result | case 6 | PASS (4/4) |
| D2 | an ineligible search is hidden on the next request, deactivated at the next prompt, blocked under the gate | case 5 | PASS |
| D3 (live) | in a cohort worktree session on this PR (after the preliminary `/submit` has opened the draft PR), a review door (`/pr-review-browser` or `/pr-review-terminal`) → `start_review_wave` → `collect_review_wave` → `push_annotations`/`submit_pr_review` with every guidance-named tool declared before the model's first call; zero dead-end turns | ledger | PASS (`89a77fcc`, ledger §3) |
| D4 (live) | in a cohort implement session the model finds `objective_stack_status` through `tool_search` on its first query and the call succeeds | ledger | PASS (`4a83ebb6`, ledger §3; see its caveat) |
| D5 (live) | the `/plan` toggle in the worktree session → `plan_draft` → `plan_review` → the chooser's "Browser review + reviewer wave" (the `plan_review` wave arm runs `openPlanReviewSurface`; `/plan-review-browser` itself refuses worktree stages, so it is NOT the entry point): `collect_draft_review_wave` and `push_annotations` are declared on the next request and the wave collects — the carried dogfood-gate item | ledger | PASS (`54022d2e`, ledger §3) |
| P1 | nonparticipant preservation — warm sessions without an active builtin `tool_search`, a foreign namesake, the two-session isolation, the headless worker, `/btw` | cases 2, 9, 10 | PASS |
| P2 | the bare-session zero-call guarantee holds for nonparticipants; a cohort startup is one perk install; a re-emitted `session_start` installs nothing | cases 1, 2 | PASS |
| P3 | primed activation: no-op outside the cohort; skips ineligible/unregistered; doors and launchers prime exactly their constants; survives every reconciliation point while eligible; resume/fork reset, `/tree` restores | cases 3, 4 + the door tests | PASS |
| P4 | nested path: a deferred inactive member is callable and recorded `ok`; cancellation, oversized arguments (`argumentsBytes`, `complete: false`) and gated denial with `parentToolCallId` behave as pinned; `perk learn evidence --render` over the probe transcript shows the `<nested_calls>` block | case 7 + ledger | PASS (offline case 7; render leg `d6de65da`, ledger §3) |
| P5 | `perk init` preserves the opt-in entry twice over; `settings-wiring` reports no drift | `test_init_preserves_local_default_tools_opt_in` | PASS |
| P6 | the prompt guard's deferred rule passes on both planes, launcher carriers included | (7) | PASS |
| C1 | the codemode gated read-path rule is recorded in §8.40 and the record | (11) | PASS (§6 here; §8.40 **The codemode composition limit**) |

**Decision rule:** ADOPT iff every row is PASS (an unobserved live leg is NOT PASSED); otherwise
RETIRE.

**The D1 scoring rule.** Exactly these four queries, run through the real `tool_search` in a
fresh cohort session of the named stage, scored on `details.loaded[0]`:

| Stage | Member | Query | `details.loaded` (measured) |
|---|---|---|---|
| implement | `collect_review_wave` | "collect the adversarial review wave reports" | `collect_review_wave`, `collect_draft_review_wave`, `push_annotations`, `objective_stack_status` |
| implement | `push_annotations` | "push findings to the browser as annotations" | `push_annotations` |
| implement | `objective_stack_status` | "stacked delivery train status" | `objective_stack_status` |
| plan | `collect_draft_review_wave` | "collect the draft review wave reports" | `collect_draft_review_wave`, `collect_review_wave`, `push_annotations`, `objective_stack_status` |

No amendment has been made.

## 5. Measurements

Per-stage census request bytes (declared tools + system prompt), read-write, one census request per
arm; `net = nonparticipant − cohort`. Measured at `5f0cb619`, re-measured byte-identical at
`1045863d`:

| Stage | Baseline (`4912cc12`) | Nonparticipant | Cohort | Net |
|---|---|---|---|---|
| gist-author | 8443 | 8443 | 9136 | −693 |
| gist-save | 8443 | 8443 | 9136 | −693 |
| objective-author | 38246 | 38246 | 33418 | 4828 |
| objective-save | 30718 | 30718 | 25890 | 4828 |
| objective-plan | 30235 | 30235 | 25407 | 4828 |
| plan | 23728 | 23728 | 18900 | 4828 |
| save | 18822 | 18822 | 13994 | 4828 |
| implement | 51093 | 51093 | 45542 | 5551 |
| submit | 51093 | 51093 | 45542 | 5551 |
| address | 51093 | 51093 | 45542 | 5551 |
| land | 51093 | 51093 | 45542 | 5551 |
| learn | 51093 | 51093 | 45542 | 5551 |
| audit | 6811 | 6811 | 7504 | −693 |
| objective-refine | 9287 | 9287 | 9980 | −693 |
| stack-review | 19639 | 19649 | 14827 | 4822 |

**Fixed cost:** 693 bytes — exactly `tool_search`'s declaration plus its snippet line (it carries
no guidelines), equal in every stage where no member is eligible.

**The preservation cross-check:** the nonparticipant arm reproduces the baseline byte-for-byte in
14 of 15 stages. The `stack-review` +10 bytes is one deliberate carrier rewording: the deferred
rule's census found `open_stack_review`'s guideline naming `push_annotations`, so "stream findings
via push_annotations" became "stream findings into the browser as it directs" (the returned
guidance, primed by the same open, still names it). No other nonparticipant byte moved.

**An observation, not a criterion:** `tool_search` activates every positive-scoring match up to its
default limit of 8, not only the top hit. The broad collector query in implement loads all four
members; the ineligible one is hidden and deactivated at the next prompt (D2), but the eligible
ones stay until the session resets, so a broad search spends part of the saving for the rest of
that session.

## 6. The codemode gated read-path rule (recorded, not built)

Three statements, kept apart because they are different contracts:

1. **What a script receives** is unchanged — a `kind: query` tool resolves to its structured value,
   an action to its text, and an action's soft failure rejects.
2. **Read-write script callability** is unchanged — every active direct tool and every
   deferred/codemode-exposed tool is nested-callable, actions included.
3. **The gated read path** — the only rule this node adds: if codemode is ever un-suspended under
   the read-only gate, a script may reach only `kind: query` perk tools eligible under the gate
   plus the gate-allowed builtin reads, every foreign tool by its posture, and a foreign
   `annotations.readOnlyHint` is never a grant.

Today the gate-eligible query set is **empty** (`objective_stack_status` is `gated: blocked`), so
no gated codemode path is built and the suspension stands. Un-suspension waits for a gate-allowed
`kind: query` tool and is its own node, never a side effect of this one.

## 7. Decision

**ADOPT.** Every row of §4 is PASS: S1, S2, D1, D2, P1–P6 and C1 offline, and the live legs D3,
D4, D5 and P4's render leg recorded in the evidence ledger (archive §3) with their commits.

What it authorizes: the opt-in entry stays committed in this repo's `.pi/settings.json`; the four
tools stay `declared: deferred`; the cohort join, the primers and the prompt guard's deferred rule
ship as specified in §8.40. It does **not** authorize converging the entry into consumer repos —
that is the follow-up plan below.

The PR review's one correctness finding was fixed before the decision commit: a member whose
deferred re-registration failed is still `direct` and unsearchable, so the session now treats only
the members that actually deferred as deferred (the rest stay always-declared), and it does not
join the cohort when nothing deferred.

## 8. Falsified planning-time assumptions

- **Byte estimates.** Planning estimated ~6.6 KB worktree, ~5.9 KB plan/objective and ~0.6 KB fixed
  cost (source reading). Measured: 6,244 B gross / 5,551 B net worktree, 5,521 B gross / 4,828 B net
  plan and objective, 693 B fixed.
- **Family order.** The plan's expected selfcheck line listed the family as `collect_review_wave,
  collect_draft_review_wave, push_annotations, objective_stack_status`; `discoveryFamily()` is
  catalog (registration) order — `objective_stack_status, collect_review_wave,
  collect_draft_review_wave, push_annotations` — because the status read registers first.
- **The carrier census.** The plan pinned the two wave launchers as the only tools whose own text
  names a deferred member; `open_stack_review`'s guideline did too. It was reworded (it primes
  through the shared browser core anyway) rather than given a third row.
- **The draft launcher's installer** is `registerDraftReviewWaveTools`, not
  `installDraftReviewWaveBindings`; `gating` is threaded there.
- **`tool_search` loads every match** up to its limit, not one tool (§5's observation).
- **A failed re-registration was safe.** Planning assumed skipping a member that could not be
  re-registered was harmless; the PR review showed cohort-wide reconciliation would then strand it
  (dropped at gate entry, never restored, invisible to `tool_search`). Fixed before the decision.
- **`perk init` in this checkout** exits 2 on a pre-existing skills-sync conflict, and the
  recorded `settings-wiring` hash in `.perk/managed-state.toml` was already stale before the
  opt-in. The opt-in moves neither: the observed and desired hashes are identical with and without
  the key, and `.pi/settings.json` stays byte-identical across the run.

## 9. Follow-ups

- **The adoption follow-up:** a plan for `perk init` convergence of
  `defaultTools: ["+tool_search"]` and the matching `perk-expert` reference update (not performed
  here — the node forbids it before an adopt decision).
- **Broad searches spend the saving** (§5's observation): worth a look if `tool_search` gains a
  per-call cap, or if family growth makes over-activation costly.
- **The session parser** counts Pi's `role: "system"` message entries as malformed lines (found
  during P4's render leg) — a `/learn` evidence-pipeline gap, unrelated to the pilot.
- **To `/learn`:** `docs/learned/workflow/warm-door-commands.md` (Law 1/4 still name
  `READ_ONLY_TOOLS`/`STAGE_TOOLS`) and its Law 4 corollary — a carrier naming a deferred tool must
  be primed.
