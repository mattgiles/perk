// The shared fake pi-subagents responder (dev-only; `testing/` is excluded from the guard
// corpus and the published tarball) — ONE implementation of the v1 request/reply envelope the
// door/pi suites previously hand-rolled per file. It answers `ping` with the advertised
// capabilities, answers `spawn` by materializing a durable `status.json` aggregate in a real
// temp `asyncDir` and replying with the run handle, records `stop` requests, and delivers the
// async-complete event per the spawn's `FakeSpawnPlan` delivery mode:
//
//   - `"auto"` (default): the completion is emitted on a post-reply macrotask — the ordinary
//     "run finished after the spawn reply" shape every happy-path suite drives.
//   - `"manual"`: nothing is emitted until the test calls `complete(index)` — paired with
//     `emit(...)` (arbitrary payloads, e.g. a FOREIGN completion first) this drives the
//     correlation assertions deterministically.
//   - `"never"`: no completion, ever — paired with a tiny wave `timeoutMs` this drives the
//     timeout→stop assertion without timer races.
//
// Plans apply per spawn, FIFO, with the LAST entry repeating (a single plan serves every
// spawn); `executeScript` is the dynamic-review mode — the test supplies the
// AsyncFunction-over-fake-`runs` evaluator and the returned value becomes the aggregate's
// `workflow.value` (state `"complete"`).
//
// Transport vocabulary (`WAVE_RPC_*`, the envelope shape) is deliberately confined here + the
// `waves/`-internal suites: no suite outside `waves/` and `testing/` names a raw RPC channel or
// envelope literal (guard-enforced token census).

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";

/** One spawn's scripted behavior (FIFO across spawns; the last entry repeats). */
export interface FakeSpawnPlan {
  /** The durable aggregate written to the run's `status.json` (default: complete + empty). */
  aggregate?: { state: string; error?: string; value: unknown };
  /** Completion delivery mode; default `"auto"` (the post-reply macrotask). */
  delivery?: "auto" | "manual" | "never";
  /**
   * Dynamic mode: the test-supplied script evaluator (the AsyncFunction-over-fake-`runs`
   * idiom); the returned value becomes the aggregate's `workflow.value` (state `"complete"`),
   * superseding `aggregate`.
   */
  executeScript?: (script: string) => Promise<unknown>;
}

/** The minimal bus surface the fake binds to (pi's EventBus / the adapter's `WaveBus`). */
interface FakeBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): () => void;
}

export interface FakeSubagents {
  /** Bind as a pi extension factory (the harness's `extraExtensions` slot). */
  extension: (pi: ExtensionAPI) => void;
  /** Bind to a bare fake bus (the runner-over-real-RPC-adapter suites); returns unsubscribe. */
  attach(bus: FakeBus): () => void;
  /** The sunk spawn params, in spawn order. */
  spawns: Array<Record<string, unknown>>;
  /** The recorded stop requests, in order. */
  stops: Array<{ id: string }>;
  /** Deliver spawn `index`'s completion (the `"manual"` delivery mode). */
  complete(index: number): void;
  /** Emit an arbitrary payload on the advertised async-complete channel (e.g. FOREIGN runs). */
  emit(payload: Record<string, unknown>): void;
}

export function createFakeSubagents(
  plans: FakeSpawnPlan[] = [],
  opts: { asyncCompleteEvent?: string; methods?: string[] } = {},
): FakeSubagents {
  const asyncCompleteEvent = opts.asyncCompleteEvent ?? "subagent:async-complete";
  const methods = opts.methods ?? [
    "ping",
    "status",
    "spawn",
    "steer",
    "interrupt",
    "stop",
    "resume",
  ];
  const spawns: Array<Record<string, unknown>> = [];
  const stops: Array<{ id: string }> = [];
  const buses: FakeBus[] = [];
  const launched: ({ asyncId: string; asyncDir: string; state: string } | undefined)[] = [];

  const emit = (payload: Record<string, unknown>): void => {
    for (const bus of buses) bus.emit(asyncCompleteEvent, payload);
  };

  const complete = (index: number): void => {
    const run = launched[index];
    if (run === undefined) {
      throw new Error(`fakeSubagents: spawn ${index} has not launched (no completion to deliver)`);
    }
    emit({ id: run.asyncId, asyncDir: run.asyncDir, state: run.state });
  };

  const handleRequest = (bus: FakeBus, raw: unknown): void => {
    const request = raw as {
      requestId: string;
      method: string;
      params?: Record<string, unknown>;
    };
    const reply = (payload: Record<string, unknown>): void => {
      bus.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, {
        version: WAVE_RPC_PROTOCOL_VERSION,
        requestId: request.requestId,
        method: request.method,
        ...payload,
      });
    };
    if (request.method === "ping") {
      reply({
        success: true,
        data: {
          version: WAVE_RPC_PROTOCOL_VERSION,
          methods,
          capabilities: { asyncSpawn: true },
          events: { asyncComplete: asyncCompleteEvent },
          session: {},
        },
      });
      return;
    }
    if (request.method === "spawn") {
      const params = request.params ?? {};
      const index = spawns.length;
      spawns.push(params);
      const plan = plans[Math.min(index, plans.length - 1)] ?? {};
      // Async on purpose: the dynamic mode awaits the evaluator, and the reply must follow the
      // durable status.json write (the real responder's ordering).
      void (async () => {
        const aggregate =
          plan.executeScript !== undefined
            ? {
                state: "complete",
                value: await plan.executeScript(String(params.workflowScript ?? "")),
              }
            : (plan.aggregate ?? { state: "complete", value: [] as unknown[] });
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-fake-subagents-"));
        const asyncId = basename(asyncDir);
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({
            runId: asyncId,
            mode: "workflow",
            state: aggregate.state,
            startedAt: 0,
            ...(aggregate.error !== undefined ? { error: aggregate.error } : {}),
            workflow: { value: aggregate.value },
          }),
        );
        launched[index] = { asyncId, asyncDir, state: aggregate.state };
        reply({
          success: true,
          data: { text: "Started async run.", details: { asyncId, asyncDir } },
        });
        if ((plan.delivery ?? "auto") === "auto") {
          // Deliver strictly after the caller's awaited spawn continuation (a macrotask) — the
          // subscribed-before-spawn runner observes an ordinary post-reply completion.
          setTimeout(() => complete(index), 0);
        }
      })();
      return;
    }
    if (request.method === "stop") {
      const id = request.params?.id;
      stops.push({ id: typeof id === "string" ? id : String(id) });
      reply({ success: true, data: {} });
      return;
    }
    reply({
      success: false,
      error: { code: "not_found", message: `fake responder rejects ${request.method}` },
    });
  };

  const attach = (bus: FakeBus): (() => void) => {
    buses.push(bus);
    const off = bus.on(WAVE_RPC_REQUEST_EVENT, (raw) => handleRequest(bus, raw));
    return () => {
      off();
      const at = buses.indexOf(bus);
      if (at >= 0) buses.splice(at, 1);
    };
  };

  return {
    extension: (pi) => {
      attach(pi.events as FakeBus);
    },
    attach,
    spawns,
    stops,
    complete,
    emit,
  };
}

/**
 * Parse the items array out of a module-rendered static wave script (the `runs.all(`-slice
 * idiom previously duplicated across the suites): everything between `runs.all(` and the
 * explicit-return marker is the JSON-embedded item list. Throws on a non-matching script — a
 * failed parse is a failed assertion, never a silent empty list.
 */
export function waveScriptItems(script: string): Array<Record<string, unknown>> {
  const start = script.indexOf("runs.all(");
  const end = script.indexOf(");\nreturn");
  if (start < 0 || end < 0) {
    throw new Error("waveScriptItems: the script carries no runs.all(...) items slice");
  }
  return JSON.parse(script.slice(start + "runs.all(".length, end)) as Array<
    Record<string, unknown>
  >;
}
