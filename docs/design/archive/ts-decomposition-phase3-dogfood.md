# Dogfood record: ts-decomposition Phase 3 gate (stage-execution confinement)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-3
close: *a real worker-backed stage through the current SDK adapter, whose resulting session state
drives the next ordinary workflow transition* — after the stage-execution confinement (Node 3.1:
`worker.ts` → `stageExecution.ts` + the private `sdkAdapter.ts` drive-session handle, the
plan-read gate absorbed into `substrate/prompts.ts`, the dead read-only runner deleted,
`workerMain.ts` guard-enforced as the only execution root).

Executed **2026-08-25** against the branch under test:

- **Implement worktree (the branch under test):**
  `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2097` (branch `plan-2097`)
- **Tested commit SHA:** `d6b6f462` (`origin/plan-2097` at gate time — the confinement + guards +
  contracts + prose-map reconciliation all committed; this evidence-record commit follows it)
- **Stack ordering rule honored:** `perk objective stack status` before the gate showed the
  published prefix 3/16 intact (layers 1.1/1.2/2.1 ready) and `origin/main` an ancestor of the
  train tip — **no base advance to absorb**, so no `stack sync --base` was needed and the gate ran
  against the as-is train.
- **Session shapes:** (1) the worker drive — the production `perk run-worker` exterior spawning
  `node <this worktree>/extension/workerMain.ts` (via `PERK_WORKER_ENTRY`; entry source `env`)
  with cwd = a **disposable GitHub clone** at `/tmp/perk-phase3-gate-clone` (never the train
  worktrees), the driven session loading the clone's own positioned extension (the sacrificial
  branch forked from `plan-2097`, so the extension under test = this branch's) — the exact §8.14
  positioning+drive path, run locally; (2) the address arm — a **headless SDK session** in the
  same positioned clone (the `docs/learned/pi/headless-session-drive.md` recipe: disk-layered
  `SettingsManager.create(clone, throwawayAgentDir)`, `ModelRuntime.create()`,
  `bindExtensions({ mode: "json" })`, `PERK_RUN_ID` = a freshly minted address run id whose
  handoff blob recorded `{stage: "address", mode: "read-write"}` — byte-identical to what the
  cold address door writes) driving the ordinary **warm `/address` command**. Both sessions SDK-resolved
  `anthropic/claude-opus-4-8` from the user auth store (no env keys).

## Fixture (pinned by the plan)

- Sacrificial plan: issue **#2098** ("Worker gate fixture: create the Phase-3 gate fixture
  file"), saved from the disposable clone via `perk plan save --plan-file … --json`. Its body
  instructed exactly: create `docs/scratch/worker-gate-fixture.md` containing the single line
  `This file validates the Phase-3 worker gate.` (plus trailing newline).
- **Base pin (stacked-train correctness):** the sacrificial plan's header pinned
  `base: plan-2097` via a clone-local `.perk/local.toml` `[workflow] base` overlay at save time —
  so the driven submit opened the sacrificial PR **against `plan-2097`** (diff = exactly the one
  fixture file), never a main-based PR dragging the unpublished train diff. No committed config
  was touched; no train worktree or the main checkout was involved in the save.
- Pinned review comment for the address arm:
  `Change "validates" to "exercises" in docs/scratch/worker-gate-fixture.md.`

## Arm 1 — the worker-backed implement drive (this branch's `runStage`)

Command (cwd = the disposable clone; run id minted by `perk state new-run`):

```
PERK_WORKER_ENTRY=<implement-worktree>/extension/workerMain.ts \
perk run-worker --run-id 01M0VBSTCMMAXP5KSG8EC3G6DK --stage implement --plan 2098 --base plan-2097
```

Observed (all pinned checks pass):

- **Positioning:** `run-worker` created `plan-2098` from `origin/plan-2097` (the incremental
  fresh-branch arm with the dispatched `--base`), materialized handoff/plan-ref/plan-body,
  delivered skills, and spawned the worker (`worker entry=…/plan-2097/extension/workerMain.ts
  (env)`).
- **`RunOutcome` (stdout, verbatim):** `{"run_id":"01M0VBSTCMMAXP5KSG8EC3G6DK","stage":
  "implement","status":"completed","terminal_signal":"submit_tool","pr":{"number":2099,"url":
  "https://github.com/mattgiles/perk/pull/2099"},"budget":{"turns":4,"tokens":508,
  "elapsed_ms":53831},"error":null}` — exit code **0** forwarded by `run-worker`.
- **Model line:** `perk worker: model anthropic/claude-opus-4-8` (the SDK's own pick — the
  adapter's post-creation log).
- **`events.ndjson`** (the clone's `.perk/workflow/scratch/runs/<runId>/`): well-formed NDJSON,
  monotonic `seq` 0–6, `run_started` first, **exactly one `run_finished`** (carrying the frozen
  outcome above), and incremental `tool_outcome` events for the drive's real tools
  (`read`, `bash`, `write`, `bash`, `submit` — all `ok: true`).
- **§8.35 pointer capture:** the run's `session-pointers.json` carried BOTH slots —
  `implementation.worker` (written by the seam's `runStage` at capture-site `worker`) and
  `implementation.main` (the inner driven session's own `session_start` claim), pointing at the
  same inner session file.
- **run_report:** the started/terminal reporter posted on the sacrificial issue #2098 (the
  `perk:run-report:<runId>` terminal comment: "perk remote **implement** finished").
- **Sacrificial PR #2099:** draft, head `plan-2098`, **base `plan-2097`**, files = exactly
  `docs/scratch/worker-gate-fixture.md`, diff = the single byte-exact line + trailing newline.

## Arm 2 — the next ordinary transition (warm `/address` from the worker-written state)

1. `gh pr ready 2099` (the ordinary human step — the remote-runner dogfood precedent: drafts
   never fetch feedback).
2. Posted the pinned review comment as an inline review thread on
   `docs/scratch/worker-gate-fixture.md:1`.
3. Drove the ordinary warm **`/address`** in the positioned clone (headless SDK session, above).
   The door reported `address — classify → fix → resolve`, injected its guidance via
   `sendUserMessage`, and the triggered review loop ran end-to-end:
   `read` → **`classify_review_feedback`** (the read-only classifier child through the
   pi-subagents RPC wave, model `openai/gpt-5.6-sol` from `[models.subagents]`) → `bash` →
   `read` → `edit` → `bash` (commit) → **`finalize_address`** (`isError=false`).
   The door drove from the **worker-written** plan-ref (`.perk/workflow/plan-ref.json`
   materialized by arm 1's positioning) — the address session's own claim was only the fresh
   address handoff.
4. Verified on GitHub: the fix commit
   (`docs: reword worker-gate fixture (validates → exercises)`, head `7169724`) pushed to
   `plan-2098`; the review thread **resolved** with the reply
   `Done — reworded to "exercises" in the fixture documentation.`; the fixture on the branch then
   read `…exercises the Phase-3 worker gate.\n` (byte-verified).

**Probe-recipe note (durable):** `session.prompt("/address")` spans only the command execution —
the `sendUserMessage`-triggered review-loop turn runs AFTER the command prompt settles, so the
probe must wait for the loop's terminating `finalize_address` `tool_execution_end` (bounded)
before disposing. The first probe attempt exited at "prompt settled" with zero loop turns; the
corrected probe (wait-for-finalize) ran the loop to completion. No product defect — a
headless-drive recipe fact.

## Teardown (all pinned)

- PR #2099 closed **unmerged** with `--delete-branch` (remote `plan-2098` deleted — the fixture
  file reached no durable branch).
- Sacrificial issue #2098 closed with a comment linking this record.
- The disposable clone (`/tmp/perk-phase3-gate-clone`, including its `.perk/local.toml` base pin
  and run scratch) removed; probe scripts lived under the implement run's gitignored agent
  scratch.

## Skipped arms

None. (The warm `/address` ran in a headless SDK session rather than an interactive TUI — a
session-shape note in the phase-1 record's tradition, not a skipped arm: the ordinary `/address`
command handler, the real classify wave, the real finalizer, and the worker-written state were
all exercised; the TUI adds no observable to this gate's claims.)

## Defect log

Empty — every observation matched the expected behavior; no product defects surfaced. (The one
probe-side correction is recorded above; it is a test-harness recipe fact, not a worker defect.)

## Claim → evidence checklist

| Claim (the node's gate enumeration) | Evidence |
|---|---|
| A real worker-backed stage ran via the production `perk run-worker` path | Arm 1: positioning log + `worker entry=… (env)` + the forwarded exit 0 |
| The driving primitive was this branch's `runStage`, the extension the train's | `PERK_WORKER_ENTRY` at this worktree's `workerMain.ts`; the clone positioned on `plan-2098` forked from `plan-2097` (its `..` package = this branch's extension) |
| `RunOutcome` completed/`submit_tool` with a PR | the verbatim stdout outcome above (PR #2099) |
| `events.ndjson` well-formed, exactly one `run_finished`, incremental `tool_outcome`s | the seq-0–6 stream above |
| §8.35 `.worker` session pointer | `session-pointers.json`: both `implementation.worker` (site `worker`) and the inner `.main` |
| run_report comments on the sacrificial issue | the `perk:run-report` terminal comment on #2098 |
| Next ordinary transition from the resulting session state | Arm 2: `gh pr ready` → pinned review comment → warm `/address` → `finalize_address` ok, thread resolved, fix pushed |
| Teardown | PR closed unmerged + branch deleted; issue closed with the record link; clone removed |
