// The in-memory `WaveAdapter` test double — a FIRST-CLASS deliverable: the runner's own tests
// and the future flow tests drive the whole wave lifecycle through it with no event bus, no
// child processes, and no temp dirs. Every failure arm of `runReportWave` is reachable through
// a config knob, and the recorded calls let tests assert the spawn contract (`mission: false`,
// `context: "fresh"`, the rendered script) and the stop-on-timeout/cancel behavior.
//
// It honors the same sequencing contract as the production adapter: `onComplete()` before a
// successful `ping()` throws (the async-complete channel is advertised by ping, not pinned).

import type {
  WaveAdapter,
  WaveCompletion,
  WavePing,
  WaveRunHandle,
  WaveSpawnParams,
} from "./reportWave.ts";

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
  aggregate?: { state: string; error?: string; value: unknown };
  /** When true, `readAggregate` throws (the aggregate-unreadable arm). */
  aggregateError?: boolean;
}

export interface MemoryWaveAdapter extends WaveAdapter {
  calls: { spawn: WaveSpawnParams[]; stop: WaveRunHandle[] };
  /** Deliver a completion to the subscribed handlers (contract-suite plumbing). */
  emitCompletion(completion: WaveCompletion): void;
  /** Replace the staged aggregate (contract-suite plumbing). */
  setAggregate(aggregate: { state: string; error?: string; value: unknown }): void;
}

export function createMemoryWaveAdapter(config: MemoryWaveAdapterConfig = {}): MemoryWaveAdapter {
  const ping =
    config.ping === undefined ? { asyncCompleteEvent: "subagent:async-complete" } : config.ping;
  let aggregate = config.aggregate ?? { state: "complete", value: [] as unknown[] };
  let pinged = false;
  let spawnCount = 0;
  const handlers = new Set<(completion: WaveCompletion) => void>();
  const calls: MemoryWaveAdapter["calls"] = { spawn: [], stop: [] };

  const deliver = (completion: WaveCompletion): void => {
    for (const handler of handlers) handler(completion);
  };

  return {
    calls,
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
      if (config.completion !== false) {
        const completion = { asyncId: handle.asyncId, asyncDir: handle.asyncDir };
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

    async stop(handle: WaveRunHandle): Promise<void> {
      calls.stop.push(handle);
    },

    async readAggregate(): Promise<{ state: string; error?: string; value: unknown }> {
      if (config.aggregateError === true) {
        throw new Error("simulated unreadable status.json");
      }
      return aggregate;
    },
  };
}
