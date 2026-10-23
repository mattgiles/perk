// The worker's typed run envelope — the `RunOutcome` shape (docs/design/headless-worker.md §B)
// and the structured run-event stream (contracts §8.12) — plus the SDK-free helpers that assemble
// an outcome and deliver events.
//
// SDK-free on purpose: the thin worker entry (`workerMain.ts`) imports this module STATICALLY so
// it can refuse a non-admitted SDK through the same typed outcome and the same `run_started` /
// `run_finished` pair before any SDK-bearing module links (§8.11 *The entry admission*). The drive
// seam (`stageExecution.ts`) uses the same helpers for every exit of a real drive.

import { appendFileSync } from "node:fs";
import { env } from "node:process";
import { ensureRunScratch, runEventsPath } from "../substrate/cache.ts";
import { capForModel } from "../substrate/modelVisible.ts";

// --- contract types (additive-stable; §B of docs/design/headless-worker.md) ---------------------

/** The two read-write stages with `doors.cold_remote: true` (shared/registry.yaml). */
export type DriveStage = "implement" | "address";

/** Terminal run status (audit §B outcome shape). */
export type RunStatus = "completed" | "failed" | "aborted" | "budget_exhausted";

/** The first-of terminal signal that ended the drive (audit §B). */
export type TerminalSignal =
  | "submit_tool"
  | "address_resolved"
  | "agent_idle_incomplete"
  | "budget"
  | "external_abort"
  | "model_error";

/** The budget/timeout watchdog inputs (Gap 2). */
export interface DriveBudget {
  maxTurns: number;
  maxTokens: number;
  wallClockMs: number;
}

/** The outcome's model identity: the session's selection beside its dispatch census. */
export interface RunModelIdentity {
  /** The session's selection as `provider/id`; `null` = the session exposes no selection. */
  selected: string | null;
  /**
   * Successful responses by physical identity (`usageLedger.ts::physicalKey`), first-seen order;
   * `[]` = none recorded.
   */
  dispatched: { model: string; responses: number }[];
}

/** The outcome's once-counted usage ledger (`usageLedger.ts::UsageTotals`). */
export interface RunUsage {
  records: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  /** Σ Pi's recorded `cost.total` (USD); an unpriced model records 0 — a number, never absent. */
  cost: number;
}

/**
 * The structured run outcome (audit §B). **Additive-stable**: later fields may be added; existing
 * fields keep their meaning. Never thrown — `runStage` always resolves with one of these.
 *
 * Invariant: whenever `usage !== null`, `budget.tokens === usage.input + usage.output` (the ledger
 * and the budget fold the same records at the same boundaries; cache and cost are carried, never
 * budgeted).
 */
export interface RunOutcome {
  run_id: string;
  stage: DriveStage;
  status: RunStatus;
  terminal_signal: TerminalSignal;
  pr: { number: number; url: string } | null;
  budget: { turns: number; tokens: number; elapsed_ms: number };
  /**
   * Model identity. The availability boundary is SESSION CONSTRUCTION: `null` = no session was
   * constructed (the pre-construction exits — an entry sample that is already aborted, a runtime
   * factory that rejects, a selection refusal); an object from the moment a session exists, even
   * when the drive never ran a turn (a bind failure, the terminating-tool preflight, a pre-prompt
   * abort). `null` means unavailable, never "none".
   */
  model: RunModelIdentity | null;
  /** The once-counted usage ledger; `null` = no usage record was observed (unavailable, not 0). */
  usage: RunUsage | null;
  error: { type: string; message: string; summary: string } | null;
}

// --- structured run-event stream (§8.12) ----------------------------------------------

/**
 * The structured run-event stream (contracts §8.12). A small, JSON-serializable,
 * **additive-stable** discriminated union keyed on `kind` (distinct from `DriveEvent.type`). Every
 * event carries a monotonic `seq` (0-based) and `t` (elapsed ms, same basis as
 * `RunOutcome.budget.elapsed_ms`). Future nodes may add variants/fields; existing ones keep
 * meaning — including deprecated variants that are no longer emitted (see `step_marker`).
 */
export type RunEvent =
  | { kind: "run_started"; seq: number; t: number; run_id: string; stage: DriveStage }
  // DEPRECATED — never emitted: the `[WIP:n]`/`[DONE:n]` marker protocol died with the
  // checkpoints removal. Kept for additive-stable grammar — historical `events.ndjson` files
  // may carry the variant (contracts §8.12).
  | { kind: "step_marker"; seq: number; t: number; marker: "wip" | "done"; step: number }
  | {
      kind: "tool_outcome";
      seq: number;
      t: number;
      tool: string;
      ok: boolean;
      summary: string | null;
    }
  | { kind: "run_finished"; seq: number; t: number; outcome: RunOutcome };

/** The injectable delivery seam: default = a run-scoped NDJSON file sink; tests inject an array. */
export type RunEventSink = (event: RunEvent) => void;

/** Distributive `Omit` so each `RunEvent` variant keeps its own fields when `seq`/`t` are stamped. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
type RunEventInput = DistributiveOmit<RunEvent, "seq" | "t">;

/** Per-event free-text cap (route-don't-relay): events carry the narrative, not raw tool payloads. */
export const EVENT_SUMMARY_CAP = 2 * 1024;

/** A terminal classification — the input `assembleOutcome` turns into a `RunOutcome`. */
export interface TerminalVerdict {
  status: RunStatus;
  terminal_signal: TerminalSignal;
  pr: { number: number; url: string } | null;
  errorType: string | null;
  errorMessage: string | null;
}

/**
 * Compose the final `RunOutcome` (pure). `run_id` is read from `PERK_RUN_ID` (inherited from
 * positioning, Gap 7), overridable for tests. On a non-completed status the `error` block carries a
 * capped `error.summary` (route-don't-relay discipline); a completed status has `error: null`.
 * `model` and `usage` default to `null` (unavailable) — the SDK-free entry's refusals construct no
 * session and observe no usage.
 */
export function assembleOutcome(args: {
  stage: DriveStage;
  verdict: TerminalVerdict;
  budget: { turns: number; tokens: number; elapsed_ms: number };
  model?: RunModelIdentity | null;
  usage?: RunUsage | null;
  runId?: string;
}): RunOutcome {
  const { verdict } = args;
  const error =
    verdict.status === "completed" || verdict.errorMessage === null
      ? null
      : {
          type: verdict.errorType ?? "error",
          message: verdict.errorMessage,
          summary: capForModel(verdict.errorMessage).shown,
        };
  return {
    run_id: args.runId ?? env.PERK_RUN_ID ?? "",
    stage: args.stage,
    status: verdict.status,
    terminal_signal: verdict.terminal_signal,
    pr: verdict.pr,
    budget: args.budget,
    model: args.model ?? null,
    usage: args.usage ?? null,
    error,
  };
}

/** The run-event emitter `createEventEmitter` returns. */
export interface RunEventEmitter {
  emit(event: RunEventInput): void;
}

/**
 * The run-event emitter: owns the monotonic `seq` counter and stamps `t = max(0, now() - startMs)`
 * (same basis as `RunOutcome.budget.elapsed_ms`). Fail-soft: a throwing injected sink is caught and
 * swallowed so a broken sink never aborts the drive.
 */
export function createEventEmitter(
  sink: RunEventSink,
  now: () => number,
  startMs: number,
): RunEventEmitter {
  let seq = 0;
  return {
    emit(event: RunEventInput): void {
      const full = { ...event, seq: seq++, t: Math.max(0, now() - startMs) } as RunEvent;
      try {
        sink(full);
      } catch (err) {
        console.error(`perk worker: run-event sink threw — ${String(err)}`);
      }
    },
  };
}

/**
 * The default run-event sink: a fail-soft NDJSON appender to `runEventsPath(worktree, runId)`. A
 * **no-op when `runId` is empty** (keeps the offline drive tests, which set no `PERK_RUN_ID`,
 * write-free). Each append is wrapped so a write error logs and is swallowed.
 */
export function defaultEventSink(worktree: string, runId: string): RunEventSink {
  if (!runId) return () => {};
  let ensured = false;
  const path = runEventsPath(worktree, runId);
  return (event: RunEvent): void => {
    try {
      if (!ensured) {
        ensureRunScratch(worktree, runId);
        ensured = true;
      }
      appendFileSync(path, `${JSON.stringify(event)}\n`, "utf8");
    } catch (err) {
      console.error(`perk worker: run-event sink write failed — ${String(err)}`);
    }
  };
}
