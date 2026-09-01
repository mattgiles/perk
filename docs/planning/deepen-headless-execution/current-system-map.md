# Current system map

This note records the seams that already exist in perk and the specific pressure that an
unattended objective executor would place on them. It is descriptive, not a proposed contract.

## The two planes today

Perk deliberately splits ownership across two planes:

| Plane | Lifecycle it owns | Relevant implementation |
| --- | --- | --- |
| Python session exterior | Objective and plan selection, worktrees, GitHub state, remote dispatch, run discovery, stack operations | [`src/perk/`](../../../src/perk/) |
| TypeScript session interior | Pi tools, doors, stage transitions, workflow state, reviewer waves, terminal signals | [`extension/`](../../../extension/) |
| Shared static contract | Stage vocabulary and behavior both planes must interpret the same way | [`shared/`](../../../shared/) |

That boundary is directionally right for unattended execution. An objective outlives any one Pi
session, process, container, worktree, or CI job, so objective-level scheduling belongs in the
exterior. The interior should execute one bounded session recipe and return a typed outcome.

## Existing exterior capabilities

### Objective supervision

[`objective run`](../../../src/perk/cli/commands/objective/run_cmd.py) is already a deterministic
supervisor, but intentionally advances at most one autonomously safe step and then exposes a human
gate. It can:

- select the build-ready node, including stacked readiness;
- discover an in-flight remote run and optionally wait for it;
- dispatch `implement` or `address` when the stage permits cold remote execution;
- reconstruct current plan and PR state after a run settles;
- classify repair, review, merge, learn, and completion conditions;
- avoid landing a stack autonomously.

The useful asset is its state-derived decision posture. The missing capability is a durable policy
that can consume some of today's human gates and continue until the objective reaches a defined
handoff condition.

### Remote runner seam

[`Runner`](../../../src/perk/run/runner.py) abstracts dispatch, observation, cancellation, retry, and
discovery. The only implementation is currently GitHub Actions. Its dispatch vocabulary is coupled
to a saved plan and a stage:

```text
dispatch(stage, plan_ref, run_id, base, repo_root)
```

The [workflow](../../../.github/workflows/perk-run.yml) accepts `run_id`, `stage`, `plan`, and
`base`, then launches the worker for `implement` or `address`. This is enough for those two cold
stages, but cannot faithfully position an `objective-plan` session or express a command-like
`pr-review` recipe. Both need richer inputs than a `PlanRef`.

The runner seam should remain about placing and observing bounded work. Objective policy,
next-action selection, and durable receipts should not move into the GitHub Actions adapter.

### Plan resumption

[`resume.py`](../../../src/perk/run/resume.py) derives the next plan action from canonical plan, PR,
feedback, and learn state. That remains valuable evidence for a conductor, but its result vocabulary
encodes the current human-in-the-loop workflow. It does not record that a particular unattended
execution has consumed its one permitted PR-review round.

### Stacked delivery journal

Stack operations already have an objective-first operation journal and published-prefix
checkpoints. That journal protects multi-PR mutations such as publish, sync, recover, and land. It
is not an objective execution ledger: it does not record policy decisions, bounded session
receipts, or the one-review-per-node invariant.

The two records should stay distinct:

- the stack operation journal makes a specific stack mutation recoverable;
- the objective execution ledger makes orchestration decisions and session effects replay-safe.

An `address` action may trigger the existing automatic up-stack cascade. The conductor should
treat the cascade as part of the one logical address action and wait for its terminal receipt; it
should not reproduce cascade mechanics.

## Existing interior capabilities

### SDK worker

[`extension/worker/stageExecution.ts`](../../../extension/worker/stageExecution.ts) already embeds Pi through its
SDK. It creates a session with project resources, excludes global resources, disables automatic
retry and compaction, enforces budgets, and watches for stage-specific terminal tool calls.

Its current recipe model is narrow:

```text
DriveStage = implement | address
```

The worker binds the extension in `json` mode with no UI context. Consequently `ctx.hasUI` is
false, which correctly suppresses interactive extensions but also removes
`ask_user_question`. Generalizing the driver is more important than adding a terminal emulator.

### Review waves

The reusable part of plan review already exists independently of Plannotator:

- [`draftReviewWave.ts`](../../../extension/waves/draftReviewWave.ts) starts typed reviewer lanes
  against a draft;
- [`planReview.ts`](../../../extension/factories/planReview.ts) defines the standard plan-review
  angles and assembles the standard lanes plus Ponytail;
- [`planReviewBrowser.ts`](../../../extension/doors/planReviewBrowser.ts) is the human browser
  adapter that primes context, invokes the wave, sends annotations to Plannotator, and accepts a
  human verdict.

The headless path should reuse the wave core, not automate the browser door. The report schema
deliberately has findings rather than an approval verdict, so unattended execution needs an
explicit adjudication step that disposes every finding and records why the plan was approved.

Likewise, [`pi/v1/codeReview/automated.ts`](../../../extension/pi/v1/codeReview/automated.ts) already runs the fixed review wave,
posts the resulting GitHub review, and stores `last_pr_review` in transient workflow state. The
canonical GitHub review is durable evidence, but neither it nor transient workflow state is a
reliable receipt for the policy “one review round in this objective execution, even if address
changes the head SHA.”

### Ask-user-question behavior

The installed `@juicesharp/rpiv-ask-user-question` extension has three important properties:

1. It emits a stable `rpiv:ask-user:prompt` event with question and option metadata.
2. It removes its tool when `ctx.hasUI` is false.
3. In Pi RPC mode it uses the normal dialog UI (`select` or `input`) rather than a custom TUI.

The extension's authoring convention says a recommendation is the first option and its label ends
in `(Recommended)`. Its fallback offers `Type something.` for a custom answer. Those conventions
are enough to define a narrow unattended policy without teaching the conductor how to parse
arbitrary terminal frames.

## Where the current system stops

Today the safe path is approximately:

```text
objective run
  -> plan_required                    human runs /objective-plan
  -> plan review                      human approves in Plannotator
  -> implement                        remote-capable
  -> draft PR                         human invokes /pr-review
  -> actionable feedback              remote-capable /address
  -> ready/awaiting review             human decides what happens next
```

The intended unattended path changes only the middle policy:

```text
select node
  -> objective-plan recipe
  -> one plan-critic wave + explicit dispositions
  -> approve/save plan
  -> implement recipe -> draft PR
  -> exactly one PR-review recipe
  -> address recipe iff actionable
  -> record node handoff-ready
  -> select next build-ready node
```

It stops with every PR still draft. It does not mark ready, land, reconcile, run learn, or close the
objective.

## Investment map

| Area | Keep | Deepen | Avoid |
| --- | --- | --- | --- |
| Objective selection | State-derived exterior classifier | Objective-scoped conductor and execution ledger | An LLM deciding the next node |
| Pi driver | In-process SDK, resource isolation, budgets, terminal signals | Bounded `RunIntent` recipes and policy UI binding | PTY scraping as the primary contract |
| Review | Existing reviewer waves and posting logic | Machine adjudication and durable round receipt | Automating Plannotator |
| Questions | Existing semantic question event/options | Allowlisted recommendation policy | Blanket yes/first-option behavior |
| Remote execution | Runner adapter and run discovery | General run intent independent of `PlanRef` | Encoding objective policy in workflow YAML |
| Stack mechanics | Existing coordinator, journal, and address cascade | Treat stack result as one action receipt | Reimplementing cascade in the conductor |

## The architectural conclusion from the map

The system does not lack an agent runtime. It already has Pi, typed interior tools, review waves,
and an SDK worker. It lacks a durable objective execution contract connecting bounded sessions.

The highest-leverage core work is therefore:

1. deepen the Python exterior into an objective conductor with replay-safe receipts;
2. deepen the TypeScript worker into a recipe-driven Pi session driver;
3. make unattended decisions explicit, narrow, versioned, and auditable;
4. keep hosting and process isolation behind adapters.

