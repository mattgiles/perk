// The App-lifetime check session: offset-polling client state for the CheckRunner
// (the assemblySession posture — pure, injectable, node:test-covered). Every internal
// transition emits one complete immutable state snapshot through onState. The polling
// loop is the ONE writer of run state: start adoption seeds it, the cancel response
// body is ignored, and a monotonic generation counter makes every async completion
// latest-wins across dispose and re-adoption.

import {
  type CheckId,
  type CheckNotice,
  type CheckRun,
  type CheckRunStatus,
  parseCheckRun,
  parseLatestCheck,
} from "./checks.ts";
import { type DocumentLike, mutationHeaders } from "./mutationRequest.ts";
import type { FetchLike } from "./sourceLoad.ts";

// Production polling cadence; tests inject a manual scheduler.
export const CHECK_POLL_INTERVAL_MS = 500;
// The drawer's client-session record bound, newest-first.
export const CHECK_HISTORY_LIMIT = 20;

// "lost" is a client-only presentation state: the server no longer serves the run
// record (evicted or restarted), so its accumulated view is retired to history as-is.
export type CheckRunView = {
  run: string;
  check: CheckId;
  label: string;
  command: string;
  status: CheckRunStatus | "lost";
  exitCode: number | null;
  output: string;
  truncated: boolean;
};

export type CheckSessionState = {
  active: CheckRunView | null;
  history: CheckRunView[];
  notice: CheckNotice | null;
};

export type CheckSessionDeps = {
  onState: (state: CheckSessionState) => void;
  fetchFn?: FetchLike;
  documentRoot?: DocumentLike;
  schedule?: (callback: () => void, ms: number) => void;
};

export type CheckSession = {
  start: (check: CheckId) => void;
  cancel: () => void;
  adoptLatest: () => void;
  getState: () => CheckSessionState;
  dispose: () => void;
};

function view(run: CheckRun): CheckRunView {
  return {
    run: run.run,
    check: run.check,
    label: run.label,
    command: run.command,
    status: run.status,
    exitCode: run.exit_code,
    output: run.output,
    truncated: run.truncated,
  };
}

export function createCheckSession(deps: CheckSessionDeps): CheckSession {
  const fetchFn = deps.fetchFn ?? fetch;
  const schedule =
    deps.schedule ??
    ((callback: () => void, ms: number): void => {
      setTimeout(callback, ms);
    });
  // Bumped on every adoption (a new active-run identity) and on dispose — never on
  // a mere start attempt, so a refused start cannot kill the active run's polling.
  let generation = 0;
  let state: CheckSessionState = { active: null, history: [], notice: null };
  let nextOffset = 0;
  // Every run id this session has already recorded (active, history, or lost) — the
  // latest-reconciliation read adopts only runs outside this set.
  const knownRuns = new Set<string>();

  function emit(next: CheckSessionState): void {
    state = next;
    deps.onState(next);
  }

  function headers(): Record<string, string> | null {
    return mutationHeaders(deps.documentRoot ?? globalThis.document);
  }

  function retire(retired: CheckRunView, notice: CheckNotice | null): void {
    emit({
      active: null,
      history: [retired, ...state.history].slice(0, CHECK_HISTORY_LIMIT),
      notice,
    });
  }

  function adoptRun(run: CheckRun): void {
    knownRuns.add(run.run);
    generation += 1;
    const adopted = view(run);
    if (run.status === "running") {
      nextOffset = run.next_offset;
      emit({ active: adopted, history: state.history, notice: null });
      schedulePoll(generation);
      return;
    }
    // A run that went terminal before the client could observe it running lands
    // straight in history with its full output (adoption reads start at offset 0).
    emit({
      active: null,
      history: [adopted, ...state.history].slice(0, CHECK_HISTORY_LIMIT),
      notice: null,
    });
  }

  function markLost(): void {
    const active = state.active;
    if (active === null) {
      return;
    }
    retire({ ...active, status: "lost" }, "run-lost");
  }

  function schedulePoll(current: number): void {
    schedule(() => {
      void poll(current);
    }, CHECK_POLL_INTERVAL_MS);
  }

  async function poll(current: number): Promise<void> {
    if (generation !== current || state.active === null) {
      return;
    }
    const active = state.active;
    try {
      const response = await fetchFn(
        `/api/checks/run/${encodeURIComponent(active.run)}?offset=${nextOffset}`,
      );
      if (response.status === 404) {
        // Terminal-unrecoverable: the record is gone — never an endless 404 loop.
        if (generation !== current || state.active?.run !== active.run) {
          return;
        }
        markLost();
        return;
      }
      if (!response.ok) {
        throw new Error(`unexpected status ${response.status}`);
      }
      const parsed = parseCheckRun(await response.json());
      if (parsed === null || parsed.run !== active.run) {
        throw new Error("ill-shaped check run payload");
      }
      if (generation !== current || state.active?.run !== active.run) {
        return;
      }
      const merged: CheckRunView = {
        ...state.active,
        status: parsed.status,
        exitCode: parsed.exit_code,
        output: state.active.output + parsed.output,
        truncated: parsed.truncated,
      };
      nextOffset = parsed.next_offset;
      if (parsed.status === "running") {
        emit({ ...state, active: merged });
        schedulePoll(current);
        return;
      }
      retire(merged, state.notice);
    } catch {
      // Transient transport/parse failure: skip the update and keep polling (GET
      // never mutates, and the server run always terminates by timeout).
      if (generation !== current || state.active?.run !== active.run) {
        return;
      }
      schedulePoll(current);
    }
  }

  // Start is a mutation — the slot may be occupied even when the response is
  // unusable, so 409 and every failure/malformed arm reconcile through latest.
  async function reconcileStart(current: number, fallback: CheckNotice): Promise<void> {
    try {
      const response = await fetchFn("/api/checks/latest");
      if (!response.ok) {
        throw new Error(`unexpected status ${response.status}`);
      }
      const parsed = parseLatestCheck(await response.json());
      if (parsed === null) {
        throw new Error("ill-shaped latest payload");
      }
      if (generation !== current) {
        return;
      }
      if (parsed.run !== null && !knownRuns.has(parsed.run.run)) {
        adoptRun(parsed.run);
        return;
      }
      emit({ ...state, notice: fallback });
    } catch {
      if (generation !== current) {
        return;
      }
      emit({ ...state, notice: fallback });
    }
  }

  return {
    start(check: CheckId): void {
      const mutation = headers();
      if (mutation === null) {
        emit({ ...state, notice: "not-sent" });
        return;
      }
      const current = generation;
      void (async () => {
        try {
          const response = await fetchFn("/api/checks/run", {
            method: "POST",
            headers: mutation,
            body: JSON.stringify({ check }),
          });
          if (response.ok) {
            const parsed = parseCheckRun(await response.json());
            if (parsed === null) {
              await reconcileStart(current, "start-failed");
              return;
            }
            if (generation !== current) {
              return;
            }
            adoptRun(parsed);
            return;
          }
          await reconcileStart(current, response.status === 409 ? "busy" : "start-failed");
        } catch {
          await reconcileStart(current, "start-failed");
        }
      })();
    },
    cancel(): void {
      const active = state.active;
      if (active === null) {
        return;
      }
      const mutation = headers();
      if (mutation === null) {
        emit({ ...state, notice: "not-sent" });
        return;
      }
      const current = generation;
      void (async () => {
        try {
          const response = await fetchFn(
            `/api/checks/run/${encodeURIComponent(active.run)}/cancel`,
            { method: "POST", headers: mutation },
          );
          if (response.status === 404) {
            if (generation !== current || state.active?.run !== active.run) {
              return;
            }
            markLost();
          }
          // Every other response body is ignored: the polling loop remains the only
          // writer of run state (no duplicate or dropped output, no double record).
        } catch {
          // Ignored: polling resolves the run's fate.
        }
      })();
    },
    adoptLatest(): void {
      // Called once on App mount: re-adopt a still-running run after a page reload.
      // A terminal or null result is ignored (history is client-session state).
      const current = generation;
      void (async () => {
        try {
          const response = await fetchFn("/api/checks/latest");
          if (!response.ok) {
            return;
          }
          const parsed = parseLatestCheck(await response.json());
          if (parsed === null || parsed.run === null || parsed.run.status !== "running") {
            return;
          }
          if (generation !== current || state.active !== null) {
            return;
          }
          adoptRun(parsed.run);
        } catch {
          // Reload recovery is best-effort.
        }
      })();
    },
    getState(): CheckSessionState {
      return state;
    },
    dispose(): void {
      generation += 1;
    },
  };
}
