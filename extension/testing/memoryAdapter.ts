// The in-memory `WaveAdapter` test double — a FIRST-CLASS deliverable, living under
// `extension/testing/` (dev-only: outside the production corpus, the guard scans, and the npm
// tarball): the wave module's own tests and the flow tests drive the whole lifecycle through it
// (wrapped via `reportWaveOver`) with no event bus, no child processes, and no temp dirs. Every
// operational failure arm is reachable through a config knob, and the recorded calls let tests
// assert the spawn contract (`mission: false`, `context: "fresh"`, the rendered script) and the
// stop-on-timeout/cancel behavior (the stop request plus the one terminal-proof read).
//
// It honors the same sequencing contract as the production adapter: `onComplete()` before a
// successful `ping()` throws (the async-complete channel is advertised by ping, not pinned).

import type {
  WaveAdapter,
  WaveAggregate,
  WaveCompletion,
  WavePing,
  WaveRunHandle,
  WaveSpawnParams,
  WaveStopOutcome,
  WaveTerminationProof,
} from "../waves/transport.ts";

type CompletionDetail = Omit<WaveCompletion, "asyncId" | "asyncDir">;

/**
 * The engine's immediate post-stop proof shape (dispatch still open) — the default `terminalProof`
 * answer, mirroring what pi-subagents 0.76.1's `status` reports right after a stop request.
 */
export const MEMORY_DEFAULT_TERMINAL_PROOF: WaveTerminationProof = {
  state: "pending",
  reason: "Workflow dispatch is still open.",
};

// A handle this adapter never spawned answers like the RPC adapter over the real engine: the
// engine's typed `stop` refusal, and the `status` miss projected as `unavailable`.
const UNKNOWN_RUN_STOP: WaveStopOutcome = {
  acknowledged: false,
  reason:
    "not_found: Async run not found or already completed; stop requires a live async run directory.",
};
const UNKNOWN_RUN_PROOF: WaveTerminationProof = {
  state: "unavailable",
  reason: "execution_failed: Async run not found. Provide id or dir.",
};

export interface MemoryWaveAdapterConfig {
  /** The ping outcome; null exercises the unavailable arm. Defaults to a valid ping. */
  ping?: WavePing | null;
  /** When set, spawn throws this message (the spawn-failed arm). */
  spawnError?: string;
  /**
   * Delivery ordering of the auto-completion relative to the spawn reply. The default delivers
   * after the reply settles; `complete-then-reply` delivers synchronously inside spawn — the
   * real completion-before-reply race the runner must buffer through.
   */
  ordering?: "reply-then-complete" | "complete-then-reply";
  /** `false` ⇒ the run never completes (tests pair this with a tiny `spec.timeoutMs`). */
  completion?: false;
  /** What `readAggregate` returns. Defaults to a complete run with an empty aggregate. */
  aggregate?: WaveAggregate;
  /**
   * Per-spawn aggregate FIFO for multi-wave tests (e.g. the pr-review retry): each spawn assigns
   * the next queued aggregate to its handle (keyed by `asyncDir`), and `readAggregate(handle)`
   * returns the handle's assigned aggregate. When the queue is exhausted (or absent), reads fall
   * back to the single `aggregate`/`setAggregate` staging — the knob is purely additive.
   */
  aggregates?: WaveAggregate[];
  /** When true, `readAggregate` throws (the aggregate-unreadable arm). */
  aggregateError?: boolean;
  /**
   * Completion fields, including the separate partial carrier, merged into auto-delivery.
   * Defaults unchanged: identity-only completions (the absence case).
   */
  completionDetail?: CompletionDetail;
  /**
   * Per-spawn completion-detail FIFO for multi-wave tests (mirrors `aggregates`): each spawn's
   * auto-emitted completion merges the next queued detail; when the queue is exhausted (or
   * absent), spawns fall back to the single `completionDetail` — purely additive.
   */
  completionDetails?: CompletionDetail[];
  /** What `stop` answers for a spawned run. Defaults to an acknowledged request. */
  stopOutcome?: WaveStopOutcome;
  /** What `terminalProof` answers for a spawned run. Defaults to `MEMORY_DEFAULT_TERMINAL_PROOF`. */
  terminalProof?: WaveTerminationProof;
}

export interface MemoryWaveAdapter extends WaveAdapter {
  calls: { spawn: WaveSpawnParams[]; stop: WaveRunHandle[] };
  /** The handles `terminalProof` was asked about, in order. */
  proofs: WaveRunHandle[];
  /** Deliver a completion to the subscribed handlers (contract-suite plumbing). */
  emitCompletion(completion: WaveCompletion): void;
  /** Replace the staged aggregate (contract-suite plumbing). */
  setAggregate(aggregate: WaveAggregate): void;
}

export function createMemoryWaveAdapter(config: MemoryWaveAdapterConfig = {}): MemoryWaveAdapter {
  const ping =
    config.ping === undefined ? { asyncCompleteEvent: "subagent:async-complete" } : config.ping;
  let aggregate = config.aggregate ?? { state: "complete", value: [] as unknown[] };
  const aggregateQueue = [...(config.aggregates ?? [])];
  const completionDetailQueue = [...(config.completionDetails ?? [])];
  const assignedAggregates = new Map<string, WaveAggregate>();
  const spawnedIds = new Set<string>();
  let pinged = false;
  let spawnCount = 0;
  const handlers = new Set<(completion: WaveCompletion) => void>();
  const calls: MemoryWaveAdapter["calls"] = { spawn: [], stop: [] };
  const proofs: WaveRunHandle[] = [];

  const deliver = (completion: WaveCompletion): void => {
    for (const handler of handlers) handler(completion);
  };

  return {
    calls,
    proofs,
    emitCompletion: deliver,
    setAggregate(next): void {
      aggregate = next;
    },

    async ping(): Promise<WavePing | null> {
      if (ping !== null) pinged = true;
      return ping;
    },

    async spawn(params: WaveSpawnParams): Promise<WaveRunHandle> {
      calls.spawn.push(params);
      if (config.spawnError !== undefined) throw new Error(config.spawnError);
      spawnCount += 1;
      const handle = {
        asyncId: `wave-async-${spawnCount}`,
        asyncDir: `/memory/wave-async-${spawnCount}`,
      };
      spawnedIds.add(handle.asyncId);
      const queued = aggregateQueue.shift();
      if (queued !== undefined) assignedAggregates.set(handle.asyncDir, queued);
      if (config.completion !== false) {
        const detail = completionDetailQueue.shift() ?? config.completionDetail ?? {};
        const completion = { asyncId: handle.asyncId, asyncDir: handle.asyncDir, ...detail };
        if (config.ordering === "complete-then-reply") {
          // Deliver BEFORE the spawn promise resolves — the buffered-completion race.
          deliver(completion);
        } else {
          // Deliver strictly after the caller's `await spawn(...)` continuation has run
          // (a macrotask — a microtask would still beat the awaiting continuation).
          setTimeout(() => deliver(completion), 0);
        }
      }
      return handle;
    },

    onComplete(handler: (completion: WaveCompletion) => void): () => void {
      if (!pinged) {
        throw new Error(
          "onComplete requires a successful ping first (the async-complete channel is advertised, not pinned)",
        );
      }
      handlers.add(handler);
      return () => handlers.delete(handler);
    },

    async stop(handle: WaveRunHandle): Promise<WaveStopOutcome> {
      calls.stop.push(handle);
      if (!spawnedIds.has(handle.asyncId)) return UNKNOWN_RUN_STOP;
      return config.stopOutcome ?? { acknowledged: true };
    },

    async terminalProof(handle: WaveRunHandle): Promise<WaveTerminationProof> {
      proofs.push(handle);
      if (!spawnedIds.has(handle.asyncId)) return UNKNOWN_RUN_PROOF;
      return config.terminalProof ?? MEMORY_DEFAULT_TERMINAL_PROOF;
    },

    async readAggregate(handle: WaveRunHandle): Promise<WaveAggregate> {
      if (config.aggregateError === true) {
        throw new Error("simulated unreadable status.json");
      }
      return assignedAggregates.get(handle.asyncDir) ?? aggregate;
    },
  };
}
