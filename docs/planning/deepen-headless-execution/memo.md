# Deepening headless objective execution

## Recommendation

Build headless objective execution as a host-neutral, stepwise-resumable conductor in perk's
Python session exterior, driving bounded Pi recipes through a deeper TypeScript SDK worker.

Do not make a terminal emulator, Flue, GitHub Actions workflow YAML, or any other hosting platform
the architectural center. Perk already has the agent runtime and most of the session-interior
machinery it needs. The missing core is durable orchestration between sessions: explicit run
intents, policy decisions, idempotent action receipts, and recovery from canonical objective,
plan, branch, PR, and stack state.

The first end-to-end target should be deliberately narrow:

```text
trusted maintainer-authorized stacked objective
  -> plan each build-ready node
  -> one autonomous plan-critic wave, then approve/save
  -> implement and publish a draft PR
  -> exactly one /pr-review round
  -> /address iff that round is actionable
  -> continue to the next node
  -> stop with the entire stack still draft for one human review
```

The executor must not mark PRs ready, land, reconcile, learn, or claim objective completion. Its
terminal product is a whole-stack handoff report, not a merged objective.

For the first remote path, deepen the existing GitHub Actions runner after the local contract works.
Keep Cloudflare Workflows, Fly Machines, and similar services as later conductor or worker adapters.
Do not adopt Flue as a prerequisite or replace Pi. No production host decision is needed yet.

The supporting notes contain the detailed evidence and contracts:

- [current system map](deepen-headless-execution/current-system-map.md)
- [Pi session driving](deepen-headless-execution/pi-session-driving.md)
- [objective execution contract](deepen-headless-execution/objective-execution-contract.md)
- [orchestration platform options](deepen-headless-execution/orchestration-platforms.md)

## The high-level architecture

The important decomposition is conductor, ledger, and worker—not “agent in a terminal.”

```text
                       canonical authorities
            objective · plan · git · GitHub PR · stack journal
                                  |
                                  v
                    ObjectiveExecutionEngine
              select · prepare · dispatch · reconcile
                         |                 |
                         v                 v
                 execution ledger      Runner port
              actions + decisions        |
                                 +--------+---------+
                                 |                  |
                         local SDK worker     remote worker
                                 |          (GHA first; others later)
                                 +--------+---------+
                                          v
                                 bounded Pi recipe
                     objective-plan · implement · pr-review · address
```

The Python exterior owns the objective-length lifecycle. The TypeScript interior owns one Pi
session's lifecycle. Shared contracts carry only the static shapes both must agree on. This follows
perk's existing two-plane contract instead of introducing a third source of workflow truth.

“Stepwise resumable” is a domain property, not a deployment choice. Locally, an attached command can
call `step()` repeatedly. In the cloud, a durable workflow can call it across separate jobs and
waits. If either caller dies after any step, the next caller reconstructs progress from durable
receipts and canonical state.

## A. Investment in perk core

### 1. Deepen the exterior into an objective conductor

Introduce one deep module, provisionally `ObjectiveExecutionEngine`, with a small interface such as:

```python
start(objective_id, policy) -> ExecutionRef
step(execution_ref) -> StepResult
status(execution_ref) -> ExecutionSnapshot
cancel(execution_ref, reason) -> ExecutionSnapshot
```

Its implementation should absorb objective/node selection, action idempotency, leases, runner
dispatch and observation, canonical reconciliation, policy gates, and halt/handoff classification.
The CLI, a scheduled controller, and a future durable-workflow adapter should all call the same
interface.

This is an evolution of [`objective run`](../../src/perk/cli/commands/objective/run_cmd.py), not a
parallel orchestration system. The current command already derives one safe next step and refuses
to cross human gates. Extract and generalize that leverage rather than encoding a second decision
tree in a cloud workflow.

The conductor must remain deterministic. Models author plans, implement, and review; they do not
choose which node or lifecycle action comes next.

### 2. Add an objective execution ledger

The conductor needs durable execution facts that no current authority records:

- which unattended policy and version govern the run;
- which logical action was prepared, dispatched, observed, and committed;
- which questions were answered by policy and why;
- whether the one plan-critic wave had full, partial, or zero coverage;
- whether a node consumed its single PR-review round;
- why execution halted or declared the draft stack handoff-ready.

Use objective-scoped execution IDs, deterministic action IDs, monotonic receipts, and conditional
sequencing or leases. Persist “prepared” before external dispatch, then reconcile after crashes
using the runner and canonical systems. Promise at-least-once attempts with exactly-once logical
commitment, not fictional exactly-once external effects.

Keep this ledger separate from the existing stack operation journal. The stack journal makes
publish/sync/cascade/land mutations recoverable. The execution ledger makes the higher-level
sequence replay-safe. Neither should duplicate objective, plan, Git, or GitHub facts.

The physical storage adapter is an implementation decision still to make. An issue-backed record,
dedicated git ref, external transactional store, or workflow-associated store can be evaluated
against the invariants in the [execution contract](deepen-headless-execution/objective-execution-contract.md#storage-direction).
Do not let the first host silently become the domain model.

### 3. Generalize remote dispatch from stage to run intent

The existing [`Runner`](../../src/perk/run/runner.py) interface and GitHub Actions worker are
plan-and-stage shaped. `objective-plan` exists before a saved plan and needs objective/node seed and
branch positioning. `pr-review` is a bounded command recipe rather than a registry stage.

Replace the dispatch payload with a typed `RunIntent` carrying:

- execution, objective, node, and action identities;
- recipe kind: `objective-plan`, `implement`, `pr-review`, or `address`;
- optional plan and PR refs;
- expected base, stack parent, branch, and head preconditions;
- objective-plan seed/handoff;
- policy version and bounded resource budget.

The runner port remains narrow: dispatch, observe, discover, cancel, and possibly retry one bounded
intent. It does not decide the next action. Its GitHub Actions adapter may translate the intent to
workflow inputs; a Fly or Cloudflare worker adapter may translate the same intent differently.

### 4. Generalize the session interior around bounded recipes

The existing [`worker.ts`](../../extension/worker/worker.ts) is already the right foundation: it
uses Pi's SDK, retains project resources while excluding global resources, disables ambient retry
and compaction, enforces budgets, and recognizes terminal tools. Its current type only permits
`implement | address`.

Deepen that module into a recipe interpreter. Each first-party recipe owns:

- primer and seed/handoff construction;
- resource and tool allowlists;
- positioning preconditions;
- terminal signals and canonical postconditions;
- turn/token/elapsed budgets;
- decision-policy capabilities;
- normalized run, action, and decision receipts.

Do not force command recipes into the stage registry simply to reuse the worker. The static stage
graph and a bounded worker recipe solve different problems. Add shared additive contract shapes
where both planes must agree; keep lifecycle logic in its owning plane.

### 5. Add a narrow unattended decision policy using Pi semantics

Pi's [SDK](../library/pi/sdk.md) is explicitly intended for programmatic sessions. Its
[RPC mode](../library/pi/rpc.md) turns extension UI calls into structured request/response dialogs,
and the [mode matrix](../library/pi/extensions.md) preserves `ctx.hasUI` in RPC while JSON/print do
not.

Use the SDK in-process, but bind an unattended `ExtensionUIContext` with RPC semantics. This lets
the installed `ask_user_question` extension remain active and route its ordinary `select`/`input`
calls through policy. It is not necessary to run a Pi subprocess just to obtain these semantics.

The policy for `ask_user_question` is:

1. select the option visibly labeled `(Recommended)`;
2. for multi-select, select every recommended option;
3. record the complete question, options, selections, policy version, and
   `actor=unattended-policy`;
4. if no recommendation exists, answer through “Type something” with:

   > No recommendation was provided. Please make a recommendation and ask again.

5. permit one corrected re-prompt;
6. if the correction still has no recommendation, halt as a policy violation.

Observe the extension's semantic `rpiv:ask-user:prompt` event and correlate it with the subsequent
dialog. Do not infer questions by scraping prose or dialog titles.

Setting `hasUI=true` can make other UI branches reachable, so the default is fail-closed. Unknown
`confirm`, `select`, `input`, `editor`, custom UI, browser, or TUI interactions halt. There is no
generic “yes,” “accept defaults,” or “choose the first option” policy.

### 6. Reuse review cores, not human surfaces

The [`draftReviewWave`](../../extension/waves/draftReviewWave.ts) used by
`/plan-review-browser` is already browser-independent and returns typed reports. Call it directly
with all four standard lanes—grounding, scope, decision-completeness, and risk—plus Ponytail.

The headless plan gate gets exactly one wave:

- every finding from every completed report receives a disposition: fixed, already covered, or
  rejected with rationale;
- fixes may revise the plan, but do not trigger a second critic wave;
- full coverage approves normally;
- partial, non-zero coverage may approve with a warning naming missing lanes;
- zero valid reports halts;
- the approval/save receipt identifies the unattended policy, never a human.

This reuses the valuable reviewer wave but bypasses Plannotator and the editor/select-based
[`plan_review`](../../extension/factories/planReview.ts) human adapter. Browser automation would
add presentation coupling without adding judgment.

Run the existing fixed `/pr-review` wave once per node and post its normal GitHub result. Commit a
review-round receipt containing the reviewed head SHA, verdict, actionable findings, and
`round_consumed=true`. If actionable, dispatch `/address`; when address changes the head SHA, do
not review again. Retries may finish the same logical address action, but they do not create a new
review round.

### 7. Make halts and the final handoff first-class

Headless must mean “no one is waiting on a hidden prompt,” not “all failures are auto-approved.”
Structured halt reasons should include:

- policy violation or unknown UI request;
- zero plan-review coverage;
- session/model budget exhaustion;
- failed or ambiguous external mutation;
- unresolved stack journal operation;
- branch/PR positioning drift;
- unexpected closed or merged PR;
- cancellation.

At success, emit one objective report showing every node, plan, draft PR, parent/base, current head
SHA, plan-review coverage and warnings, PR-review verdict, address result, and links. That report is
the human entry point for reviewing the entire stack at once.

### 8. Treat security as a core contract

Start only with trusted maintainer-authorized repositories. The unattended identity needs enough
authority to create/update branches and draft PRs and post reviews, but not to mark ready or merge.
Secrets must not flow into untrusted PR code. Only first-party recipe kinds may be dispatched; a run
intent is not an arbitrary shell/prompt envelope.

Authorization, policy version, execution ID, and actor provenance belong in receipts. This keeps
the first implementation narrow without baking “trusted forever” into the design.

## B. Runtime and platform direction

### Primary session-runtime choice: Pi SDK

Use the Pi SDK because perk already depends on Pi's extension ecosystem, tools, skills, resources,
review waves, workflow state, and typed tool events. The SDK gives direct cancellation and session
events and avoids parsing a presentation protocol.

Add a subprocess `pi --mode rpc` adapter later if hard process isolation, independent worker
upgrades, or a non-TypeScript controller justifies it. Normalize both SDK and RPC implementations
to the same recipe outcome. This is a process-topology choice, not a workflow redesign.

### Do not lead with a terminal emulator

A cloud PTY looks attractive because it can run the existing TUI unchanged. It also makes terminal
rendering, dimensions, ANSI frames, focus, and timing part of correctness. Semantic prompts become
heuristics; crash recovery becomes terminal reconstruction; browser and TUI doors become accidental
surface area.

Retain PTY automation only as a compatibility adapter for a future tool that has no SDK, RPC, or
typed event seam. Pi already has those seams.

### Do not replatform the interior onto Flue

Flue has useful durable agent submissions, conversation receipts, and sandbox adapters. Its own
documentation also says that a surrounding multi-step script still needs a durable workflow engine.
See the official [Agent API](https://flueframework.com/docs/reference/agent-api/),
[durability guide](https://flueframework.com/docs/guide/durability/), and
[workflow guidance](https://flueframework.com/docs/guide/workflows/).

Replacing Pi with Flue would recreate or abandon a large amount of working interior leverage while
still leaving the objective conductor to build. The conductor's sequencing problem is deterministic,
not a missing agent abstraction. Flue remains a possible later outer service or worker adapter if a
specific operational requirement makes its durable submission model valuable.

### First remote worker choice: GitHub Actions

After local dogfood, extend the existing GitHub Actions runner to accept bounded run intents. Use one
job per recipe and let the exterior controller explicitly dispatch the next action.

Do not use one monolithic job for the whole objective and do not build an arbitrary node chain out
of `workflow_run`. GitHub documents a six-hour hosted-job limit, a 35-day workflow limit, and only
three levels of `workflow_run` chaining, with security warnings around privilege changes. See
[Actions limits](https://docs.github.com/en/actions/reference/limits) and
[workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

GitHub Actions is the lowest-integration remote worker, not the execution ledger or ideal forever
conductor.

### Strong later conductor candidate: Cloudflare Workflows

Cloudflare Workflows maps well to persisted select/dispatch/wait/reconcile steps. It supports
durable `step.do`, sleeps, and external-event waits; waiting work does not consume active
concurrency. See [Workers API](https://developers.cloudflare.com/workflows/build/workers-api/) and
[limits](https://developers.cloudflare.com/workflows/reference/limits/).

Cloudflare Sandbox could host a worker, but its filesystem and processes disappear when a sandbox
stops, and a reused sandbox ID may get a new container. Git/remotes or external object storage must
remain authoritative. See [Sandbox lifecycle](https://developers.cloudflare.com/sandbox/1-0-preview/lifecycle/).

This is a promising production shape after the core is proven, not a reason to write the conductor
in platform-specific workflow code now.

### Strong later worker candidate: Fly Machines

Fly offers conventional API-created VMs that may suit repository and Pi toolchains. Its root
filesystem is ephemeral; volumes are host-local, single-Machine, and not automatically replicated.
See [Machines](https://fly.io/docs/machines/overview/) and
[Volumes](https://fly.io/docs/volumes/overview/).

Fly therefore solves worker placement, not durable orchestration. Pair it with an external
conductor/ledger and reconstruct every worker from run intent plus Git and durable receipts.

### Attached versus fire-and-forget is not a core fork

The same architecture supports both:

| Operator experience | Conductor lifetime | Worker topology |
| --- | --- | --- |
| Local attached | One process loops over durable `step()` calls | In-process Pi SDK |
| Local resumable | Operator invokes one or several steps at a time | SDK or local RPC subprocess |
| Remote controller | Restartable process dispatches and observes jobs | GitHub Actions |
| Fire-and-forget | Durable workflow owns waits and retries | Cloudflare/Fly/GHA worker adapter |

Build attached first because it is the quickest way to test the domain contract. Deliberately kill
it between every boundary to prove it is not dependent on being attached. A later fire-and-forget
adapter then changes lifetime and hosting, not semantics.

## Alternatives considered

### Script the existing CLI and accept prompts

This has low initial cost but no reliable one-review invariant, decision provenance, idempotency, or
crash reconciliation. It also leaves objective-plan and review gates human-shaped. Useful as a
prototype harness only; not an architecture.

### Put an agent above the terminal

This minimizes changes to session-interior code, but transfers the complexity into brittle UI
interpretation and makes unattended safety harder to audit. Reject as the primary path.

### Make one long-running Pi session own the objective

This preserves conversational continuity but couples objective correctness to one context window,
process, checkout, and lifetime. It also weakens per-node isolation and resumption. Reject; use
bounded sessions with explicit handoffs.

### Make a cloud workflow the domain state machine

This can ship quickly on one host, but duplicates perk's objective classifier and leaks platform
retry semantics into domain policy. Reject until the conductor interface is extracted; later adapt
a workflow engine to it.

### Use Flue for every agent call

Flue's durability is appealing, but it overlaps the existing Pi interior and does not itself make
the objective-length workflow durable. Defer unless measured needs expose a gap Pi plus the runner
port cannot fill.

## Proposed delivery sequence

Each phase should end with ordinary automated coverage and a dogfood gate in which perk drives the
next phase.

### Phase 1: lock the execution contract

- Define `RunIntent`, `RunOutcome`, `ActionReceipt`, `DecisionReceipt`, and halt/handoff shapes in
  the shared contract.
- Specify action IDs, reconciliation rules, policy versioning, and canonical postconditions.
- Add a storage port only after choosing at least the local adapter and the likely remote adapter
  it must support.
- Build model-free contract tests around duplicate delivery, crash points, and stale preconditions.

Dogfood gate: a synthetic execution survives restart before and after each mock external effect
without committing an action twice.

### Phase 2: deepen the Pi worker

- Refactor `worker.ts` from stage-only driving to first-party run recipes.
- Add the fail-closed SDK policy UI with RPC semantics.
- Implement and test recommended single/multi-select, complaint/re-prompt, and unknown-dialog halt.
- Normalize terminal outcomes and diagnostics.

Dogfood gate: an unattended bounded fixture session uses a recommendation and resumes cleanly after
an injected interruption.

### Phase 3: autonomous plan gate

- Add the `objective-plan` recipe and its node/base/stack-parent positioning.
- Invoke all four draft-review lanes plus Ponytail directly.
- Add finding disposition, revision, partial-coverage warning, zero-coverage halt, and unattended
  approval/save receipt.

Dogfood gate: perk autonomously plans the next phase's node, records critic coverage and every
finding disposition, and saves the plan without Plannotator.

### Phase 4: local end-to-end conductor

- Extract/deepen objective-next-action logic into `ObjectiveExecutionEngine`.
- Implement the first ledger adapter and attached loop.
- Add `implement`, one-round `pr-review`, conditional `address`, and handoff-ready projection.
- Exercise stack cascade through its existing coordinator and journal.

Dogfood gate: run a small trusted stacked objective to all-draft handoff, killing and resuming the
controller between nodes and between review/address.

### Phase 5: generalized GitHub Actions adapter

- Dispatch `RunIntent` rather than stage/plan-only inputs.
- Make run names/discovery key off execution and action IDs.
- Reconcile “dispatch happened, handle write failed” and “worker effect happened, outcome was lost.”
- Preserve one bounded recipe per job.

Dogfood gate: the next stacked objective completes to draft handoff with remote workers and a
restartable controller.

### Phase 6: production-host evaluation

- Measure real durations, setup/checkout cost, queue time, retries, wait time, concurrent execution,
  ledger write volume, and failure recovery.
- Evaluate Cloudflare Workflows, Fly Machines, or another engine/worker pair against that data.
- Decide attached service versus fire-and-forget workflow as an adapter and operating-model choice.

Do not make this host selection a prerequisite for phases 1–4.

## Testing and observability bar

The critical tests are state-machine and fault-injection tests, not large model-dependent end-to-end
runs. Cover every crash window around prepare, dispatch, effect, observation, and commit. Verify:

- duplicate `step()` calls do not duplicate logical actions;
- stale leases recover without assuming the action did not happen;
- canonical state can repair a missing success receipt;
- a consumed PR-review round remains consumed after address changes SHA;
- partial plan-review coverage is warned and zero coverage halts;
- all unexpected UI fails closed;
- final success leaves every PR draft and performs no ready/land/reconcile/learn mutation;
- SDK and future RPC worker adapters satisfy the same outcome contract.

Every log, run, receipt, and GitHub marker should carry `execution_id` and `action_id`. The whole-stack
handoff should link back to per-action diagnostics without making those logs the source of truth.

## Decisions this memo makes

- The exterior conductor, not a model or workflow YAML, owns objective sequencing.
- The core is stepwise resumable and host-neutral.
- Pi SDK is the primary session driver; subprocess RPC is an optional isolation adapter.
- Terminal emulation is not the primary contract.
- `ask_user_question` accepts explicitly recommended choices, complains once when none exists, then
  halts on repetition.
- Plan review uses one wave with grounding, scope, decision-completeness, risk, and Ponytail; every
  finding is disposed; partial coverage warns; zero coverage halts.
- Each node receives exactly one `/pr-review` round, followed by `/address` only when actionable,
  with no second review.
- The executor stops at an all-draft whole-stack handoff.
- Trusted maintainer-authorized repositories are the initial security scope.
- GitHub Actions is the first remote adapter to deepen, not the permanent architecture.
- Flue, Cloudflare, Fly, and other services remain optional adapters or later operating choices.

## Open decisions to resolve during implementation planning

These do not block the architectural direction:

1. Which first ledger adapter best satisfies conditional sequencing without introducing a large
   operated dependency?
2. What canonical marker should make a posted PR review discoverable by `action_id` after a crash?
3. Does the first local interface expose only an attached `run`, or both `run` and operator-visible
   one-step `resume` from day one?
4. What exact budget defaults and cumulative objective cap should halt unattended execution?
5. How are policy versions migrated for an execution already in progress?
6. What repository authorization/config flag opts into unattended objective execution?
7. Which warnings make the final whole-stack handoff non-approvable by policy even though execution
   reached its mechanical boundary?

Resolve these in bounded implementation plans after the receipt and state-machine invariants are
accepted. They should not be answered implicitly by whichever cloud product is easiest to launch.

