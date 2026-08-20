# Orchestration and worker platform options

This note compares platform roles after separating the system into a conductor, durable execution
ledger, and ephemeral bounded workers. It is a direction-setting comparison, not a vendor choice.

## First principle: assign platform roles

“Where does the agent run?” actually contains three decisions:

1. **Conductor:** who advances the durable multi-step state machine and waits between actions?
2. **Ledger:** where are execution/action/decision receipts stored with conditional updates?
3. **Worker:** where does one Pi recipe get a checkout, credentials, model access, CPU, and time?

One product may fill multiple roles, but the core should not require that. An ephemeral worker is
not a ledger. An agent framework is not automatically a durable multi-step workflow. A workflow
engine does not provide a repository sandbox by itself.

## Options at a glance

| Direction | Conductor | Worker | Integration effort | Durability posture | Best fit |
| --- | --- | --- | --- | --- | --- |
| Local attached | Perk process loops over `step()` | In-process Pi SDK | Lowest after core refactor | Process may die; ledger enables resume | Dogfood and development |
| GitHub Actions controller | Explicit dispatches from perk or a small controller | GHA job per recipe | Low; current adapter exists | Jobs durable enough; controller/ledger still needed | First remote implementation |
| Cloudflare Workflows + Sandbox | Workflow instance | Sandbox container or another worker host | Medium/high | Strong persisted steps and waits; sandbox itself ephemeral | Managed durable conductor |
| External workflow + Fly Machines | Workflow/controller service | Fly Machine per recipe | Medium/high | Depends on external ledger; machines/root FS ephemeral | Flexible VM-shaped workers |
| Flue plus workflow engine | Durable Flue agent submissions and conversations | Flue sandbox adapter | High and overlapping | Agent call durable; surrounding sequence still needs workflow | New agent-service architecture |
| Cloud PTY automation | Any controller | TUI inside VM/container | Superficially low, operationally high | Presentation state is fragile | Compatibility escape hatch only |

## Local attached execution

After the core is stepwise resumable, the fastest useful product is a local command that starts an
execution and repeatedly calls `step()` until handoff or halt. It can use the existing in-process Pi
SDK worker.

This is “attached” only as an operator experience. Correctness still comes from committed action
receipts. If the laptop sleeps or the process dies, the next invocation resumes from the ledger and
canonical GitHub state.

This direction proves the policy and state machine without prematurely solving cloud identity,
sandbox persistence, and hosted secret management.

## GitHub Actions

GitHub Actions is the most incremental remote worker because perk already has a runner adapter and
a [`workflow_dispatch` worker](../../../.github/workflows/perk-run.yml). Keep jobs bounded to one
recipe and dispatch them explicitly by `RunIntent`.

Do not make one job own the whole objective. GitHub documents a six-hour limit for GitHub-hosted
jobs and a 35-day workflow-run limit. Do not construct an arbitrary objective by chaining
`workflow_run`: GitHub limits such chains to three levels and warns that a later privileged workflow
can expose secrets to untrusted prior workflow output. See GitHub's official
[Actions limits](https://docs.github.com/en/actions/reference/limits) and
[workflow event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

A reasonable first remote shape is:

```text
perk objective execute --resume
  -> durable ledger + controller selects one action
  -> workflow_dispatch(run-intent-id)
  -> one GHA job runs one Pi recipe
  -> controller observes receipt/canonical result
  -> next step
```

The controller may initially be invoked repeatedly by a user or scheduled job. It can later move to
a durable workflow engine without changing recipe semantics.

Strengths:

- existing repository checkout, GitHub identity, logs, and runner seam;
- natural isolation per bounded action;
- close to the repositories perk already mutates;
- low migration cost.

Weaknesses:

- not a pleasant high-frequency durable state machine by itself;
- queue latency and job/runtime limits;
- artifacts and run records are diagnostics, not a transactional execution ledger;
- secure handling of fork/untrusted code requires care.

## Cloudflare Workflows and Sandbox

Cloudflare Workflows is a credible durable conductor. Its API provides persisted `step.do`, sleeps,
and external-event waits; waiting instances do not consume concurrency. Cloudflare documents
per-step CPU limits but unbounded wall-clock time while waiting on I/O, along with configurable step
counts. See [Workers API for Workflows](https://developers.cloudflare.com/workflows/build/workers-api/)
and [Workflow limits](https://developers.cloudflare.com/workflows/reference/limits/).

That maps well to:

```text
workflow step: acquire/select/prepare
workflow step: dispatch bounded worker
wait/event or poll: worker settles
workflow step: reconcile/commit
```

Cloudflare Sandbox can supply a Linux worker, but its lifecycle must be treated as ephemeral.
Cloudflare says files and processes disappear when a sandbox stops, and a reused sandbox ID may
refer to a fresh container. Persistent workspace state belongs in Git/remotes or external object
storage such as R2, not in the container. See [Sandbox lifecycle](https://developers.cloudflare.com/sandbox/1-0-preview/lifecycle/),
[sandbox concepts](https://developers.cloudflare.com/sandbox/concepts/sandboxes/), and
[storage mounts](https://developers.cloudflare.com/sandbox/api/storage/).

Strengths:

- first-class durable steps, waits, retries, and event resumption;
- conductor can outlive workers cleanly;
- good fit for stepwise execution and explicit receipts.

Weaknesses:

- new platform, TypeScript Worker integration, identity, and receipt-store design;
- sandbox preview/maturity and runtime limits must be validated with real perk workloads;
- repository/worktree restoration and model credential paths need engineering;
- adopting it before the host-neutral contract risks platform-shaped core APIs.

## Fly Machines

Fly Machines provides API-created, VM-shaped workers with fast starts. Fly documents that a
Machine's root filesystem is ephemeral and starts from its image on startup. Volumes are local to
one host/region, attach to one Machine, and are not automatically replicated. See
[Machines overview](https://fly.io/docs/machines/overview/) and
[Volumes overview](https://fly.io/docs/volumes/overview/).

That makes Fly a plausible worker substrate, especially if Pi or repository tooling needs a more
ordinary VM environment than a serverless sandbox. It does not remove the need for an external
conductor and ledger. A stopped/lost worker must be reconstructable from the run intent, Git, and
durable receipts.

Strengths:

- conventional Linux environment and process model;
- API-controlled worker lifecycle;
- easier accommodation of long-running or unusual toolchains.

Weaknesses:

- conductor, queue, ledger, and events remain perk's responsibility or another service's;
- local volumes tempt accidental workspace authority and require backup/placement design;
- more infrastructure ownership than GitHub Actions.

## Flue

Flue's Agent API offers durable agent submissions and conversation state through `dispatch`,
`init`, and `read`. Its durable-tools model records tool steps while acknowledging the usual
boundary: recording can be exactly once while external effects are at least once and require
idempotency. See Flue's [Agent API](https://flueframework.com/docs/reference/agent-api/) and
[durability guide](https://flueframework.com/docs/guide/durability/).

Flue also separates conversation durability from workspace durability and supports local, virtual,
or remote sandbox adapters. A remote sandbox can reconnect by agent ID. See the
[sandbox guide](https://flueframework.com/docs/guide/sandboxes/).

However, Flue explicitly says it does not make the surrounding multi-step application workflow
durable and recommends a workflow engine such as Cloudflare Workflows, Inngest, or Temporal for
that sequence. See [Flue workflows](https://flueframework.com/docs/guide/workflows/).

For perk, replacing the Pi interior with a Flue agent would duplicate or displace substantial
existing leverage:

- Pi extensions and tools;
- stage-aware resource loading;
- workflow state and terminal signals;
- first-party reviewer waves;
- skill and prompt wiring;
- the existing SDK worker.

The objective conductor is primarily a deterministic state machine coordinating several bounded
agent sessions. It does not need another agent framework to decide the sequence. Flue could be
evaluated later as an outer service or worker adapter if its durable submission/conversation model
solves a concrete operational need, but it should not be the prerequisite for headless objectives.

## Durable workflow engines beyond Cloudflare

Temporal, Inngest, or another engine could implement the same conductor adapter. The evaluation
criteria should be concrete:

- durable timers and external-event waits;
- activity idempotency and retry controls;
- workflow-versioning story for executions that span deployments;
- cancellation and operator visibility;
- secret/identity integration;
- retention and export of execution receipts;
- ability to keep perk's domain state machine in ordinary, testable Python or TypeScript.

There is no reason to select among them until the local `step()` contract and realistic action
durations/failure modes are measured.

## Recommended sequence

1. Build the host-neutral conductor, run intent, receipts, and SDK policy UI.
2. Dogfood through an attached local loop while deliberately killing and resuming it.
3. Generalize the existing GitHub Actions runner to bounded run intents for the first remote path.
4. Measure queue delay, run duration, workspace restoration, retry causes, and ledger write volume.
5. Only then evaluate Cloudflare Workflows, Fly workers, or another workflow/worker combination
   against observed requirements.

This sequence defers a vendor commitment without deferring the architecture that every vendor
would need.

## Decision matrix for the later platform selection

Weight these only after dogfood data exists:

| Criterion | Question |
| --- | --- |
| Recovery | Can a controller die between every action and resume without operator reconstruction? |
| Isolation | What failure or compromise is contained to one recipe? |
| Workspace | Can a fresh worker reconstruct the exact expected branch/worktree cheaply? |
| Identity | Can it use least-privilege GitHub and model credentials without exposing them to untrusted code? |
| Duration | Do planning, implementation, review, and cascade fit the real runtime limits? |
| Observability | Can an operator find intent, logs, receipts, warnings, and canonical effects by execution ID? |
| Cancellation | Can queued and running work be stopped, and can the conductor reconcile what happened? |
| Portability | Is the platform an adapter, or has domain policy leaked into its workflow language? |
| Cost | What do idle waits, concurrent objectives, storage, and repeated checkout/setup cost? |

