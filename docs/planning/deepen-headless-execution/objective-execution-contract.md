# Objective execution contract

This note sketches the durable contract an unattended objective conductor needs. Names and storage
are provisional; the invariants are the important part.

## Outcome boundary

One execution takes a stacked objective from its current canonical state to this handoff:

- every node that was in scope has a saved plan;
- every layer has a draft PR;
- every draft PR has consumed exactly one automated `/pr-review` round;
- every actionable result has completed its `/address` action, including the existing stack
  cascade;
- no PR has been marked ready or landed;
- reconcile and learn have not run.

The conductor must not redefine objective nodes as `done` to represent this boundary. “Draft stack
prepared for whole-stack human review” is execution state, not objective roadmap truth.

## Authorities

Avoid a second mutable copy of domain truth:

| Fact | Authority |
| --- | --- |
| Objective intent, nodes, dependencies, statuses | Objective store |
| Saved plan and node backlink | Issue backend |
| Branch ancestry and commits | Git |
| PR existence, base, draft state, reviews, feedback | GitHub |
| Stack membership and recoverable stack mutations | Existing stack coordinator and journal |
| Which unattended actions were attempted/consumed | Objective execution ledger |
| Why an unattended decision was made | Decision receipt in that ledger |

The ledger is an orchestration record. On resume it should combine its receipts with fresh canonical
state rather than replaying a stale world snapshot as truth.

## Deep exterior module

Introduce one Python module—provisionally `ObjectiveExecutionEngine`—whose narrow public interface
is independent of a hosting platform:

```python
start(objective_id, policy) -> ExecutionRef
step(execution_ref) -> StepResult
status(execution_ref) -> ExecutionSnapshot
cancel(execution_ref, reason) -> ExecutionSnapshot
```

`step()` advances at most one logical action. It may observe an existing action, reconcile a lost
receipt, dispatch a new bounded run, or record completion. It never contains a long-lived polling
loop as a correctness requirement.

A convenience `run()` command may repeatedly call `step()` while attached. A durable workflow may
call `step()` once per workflow step. Both use the same implementation and ledger.

The module hides:

- objective and stacked build-readiness projection;
- next-action selection;
- action idempotency and leases;
- canonical-state reconciliation;
- run dispatch and observation;
- unattended-policy enforcement;
- completion and halt classification.

This gives the module depth: a small interface conceals the complexity that currently leaks across
CLI control flow, run discovery, transient workflow state, and human gates.

## Run intent

Generalize remote dispatch from “stage plus plan” to a bounded, versioned run intent:

```text
RunIntent
  intent_id                 stable idempotency key
  execution_id
  objective_id
  node_id
  kind                      objective-plan | implement | pr-review | address
  plan_ref?                 absent before a plan is saved
  pr_ref?
  positioning              base, stack parent, worktree/branch expectation
  seed_handoff?             objective-plan context
  policy_ref                unattended policy name + version
  budget
  expected_preconditions    digests/SHAs/identifiers
```

The runner adapter gets a run intent and returns a handle. The interior worker returns a normalized
run outcome. GitHub Actions, Fly Machines, or another worker host remain implementation details.

The intent should not contain a general shell command or arbitrary prompt. Each `kind` resolves to a
first-party recipe, so policy and terminal conditions stay reviewable.

## Ledger model

Use append-only or monotonic receipts under an objective-scoped `execution_id`. A minimal logical
model is:

```text
Execution
  execution_id
  objective_id
  policy_ref
  created_at
  state                     running | handoff_ready | halted | cancelled
  next_sequence

ActionReceipt
  sequence
  action_id                 deterministic per execution/node/kind/round
  node_id
  kind
  status                    prepared | dispatched | observed | committed | failed
  attempt
  run_handle?
  expected_preconditions
  result
  started_at / finished_at

DecisionReceipt
  action_id
  decision_id
  kind                      ask-user | plan-review
  request_digest
  presented_choices/findings
  resolution/dispositions
  actor                     unattended-policy
  policy_ref
  warning?
  created_at
```

“Append-only” does not require one physical append-only file. It means committed facts are not
silently rewritten. A storage adapter may use conditional updates while preserving monotonic
sequences and prior receipts.

## Idempotency and crash reconciliation

Exactly-once execution of external effects is not generally available. The contract should instead
provide at-least-once attempts with exactly-once logical commitment:

1. derive `action_id` deterministically;
2. persist `prepared` before dispatch or mutation;
3. dispatch using `action_id` as the external idempotency key where possible;
4. persist the run handle;
5. after a crash, search the runner and canonical systems using identifiers from the prepared
   receipt;
6. verify the recipe-specific postcondition;
7. commit one terminal receipt.

Examples:

- if dispatch succeeded but persisting the GitHub Actions run handle failed, discover the run by
  `intent_id` before redispatching;
- if plan save succeeded but the worker died, find the node backlink and saved plan, then synthesize
  the successful canonical result;
- if posting a review succeeded but the session died, find the review marker and commit the review
  receipt without running another wave;
- if address pushed commits but the action outcome was lost, compare the branch/PR and stage
  postcondition before deciding whether a resume is needed.

## Serialization and leases

Only one conductor should select or commit the next action for an execution at a time. The ledger
needs conditional sequencing or a renewable lease:

```text
acquire(execution_id, expected_sequence, holder, expires_at)
commit(receipt, expected_sequence)
release(holder)
```

A lease prevents two controllers from dispatching the same next action. It must not be the only
proof that an external action did or did not happen; expired leases are recovered by reconciliation.

The existing runner's plan-level concurrency and the stack journal remain additional safeguards,
not substitutes for objective-execution serialization.

## Node state machine

The ledger can project each node into execution states without writing them into the objective:

```text
unplanned
  -> planning
  -> plan_reviewing
  -> plan_approved
  -> implementing
  -> draft_published
  -> pr_reviewing
  -> review_consumed_clean ---------------------> handoff_ready
  -> review_consumed_actionable -> addressing --> handoff_ready
```

Any state may transition to `halted` with a structured reason. A retry resumes the same logical
action unless the policy explicitly authorizes a new one.

### One PR-review round

The decisive receipt should include:

```text
node_id
plan_ref
pr_number
reviewed_head_sha
review_post_id
verdict                 clean | actionable
round_consumed          true
actionable_findings
```

Once `round_consumed` is committed, the conductor never dispatches `pr-review` again for that node
in this execution—even if `/address` changes `HEAD`. Address may retry or resume until its own
terminal postcondition, but that does not create another review round.

This execution-local policy is why a GitHub review alone is insufficient. A later head SHA does not
tell the conductor whether the configured round was already consumed against the prior SHA.

## Plan critic and approval receipt

The plan gate requests exactly one wave containing the four standard plan-review angles plus
Ponytail. The receipt records:

```text
draft_digest_before
requested_lanes
completed_lanes
missing_lanes
reports
findings
dispositions             fixed | already_covered | rejected_with_rationale
draft_digest_after
decision                 approved | halted
warning?
```

Rules:

- every finding from every completed report has exactly one disposition;
- fixes may revise the plan before save, but do not trigger a second critic wave;
- one or more completed reports may approve with a warning naming missing lanes;
- zero completed reports halt;
- schema-invalid output counts as a missing report, not as silent approval;
- the approval actor is `unattended-policy`, never `human`.

## Ask-user receipt

Each question produces a receipt with the full presented options and selected recommended labels.
For a missing recommendation, the complaint response is also recorded. The corrected re-prompt
must correlate to the original decision request; a second missing recommendation halts the action.

The policy version is part of every receipt. A resumed execution keeps its original policy version
unless an explicit migration creates an auditable policy-change receipt.

## Whole-objective state machine

The conductor repeatedly projects canonical state plus receipts:

```text
start/resume
  -> reconcile active/prepared action
  -> recover stack operation if required
  -> select next build-ready node
  -> advance one node action
  -> repeat
  -> all scoped nodes handoff_ready
  -> execution.handoff_ready
```

The conductor halts rather than guessing on:

- an unattended-policy violation;
- zero plan-review coverage;
- exhausted model/session budget;
- an unknown or ambiguous canonical state;
- a failed or unresolved stack operation;
- unexpected branch/PR positioning or closed/merged PR;
- an external mutation whose outcome cannot be reconciled;
- cancellation.

At `handoff_ready`, emit a whole-stack report with each node, plan, PR, base, head SHA, plan-review
coverage, PR-review verdict, address result, warnings, and links. This is the artifact a human
reviews at once.

## Storage direction

Do not choose storage merely by choosing a worker host. The ledger needs conditional writes,
durability beyond ephemeral workers, queryability by objective/execution/action id, and a recovery
story.

Plausible adapters include:

| Adapter | Strength | Cost/risk |
| --- | --- | --- |
| Objective/issue-backed record | Visible beside domain work; no new service | Awkward conditional append/query; issue prose is a poor high-frequency log |
| Dedicated git ref/artifact | Repository-portable, inspectable | Concurrency and frequent writes are cumbersome; risks noisy git state |
| External transactional store | Good leases, indexing, and atomic transitions | New operated dependency and identity/retention design |
| Durable workflow state plus receipt store | Natural orchestration checkpoints | Couples recovery semantics to a platform if not kept behind a port |

The first implementation can use the smallest adapter that meets the invariants, but the domain
contract must not name GitHub Actions, Cloudflare, Fly, or a terminal session.

## Security boundary

Unattended execution should initially be limited to trusted, maintainer-authorized repositories.
The execution identity can read repository content, invoke configured models, create branches and
draft PRs, post reviews, and push address changes. It must not:

- approve arbitrary confirmations;
- expose secrets to untrusted PR code;
- mark PRs ready or merge;
- widen repository or organization permissions;
- run arbitrary user-supplied runner commands outside first-party recipes.

Policy violations and missing authorization are terminal, visible outcomes—not prompts waiting in a
headless process.

