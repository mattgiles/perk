// The librarian writer's engine: engine presence and the native worktree default (read once at
// construction), then ONE foreground dispatch of `perk.librarian` through the shared transport.
// No lock and no read-only refusal — the parent session is allowed to stay gated; only the child
// writes, and the adapter's end-state bracket proves where.
import { LIBRARIAN_RECORD_SCHEMA } from "../../library/librarian.ts";
import {
  type DelegationEvents,
  type DelegationTuple,
  dispatchForeground,
  type ForegroundOutcome,
  nativeWorktreeConfigPath,
  readNativeWorktreeDefault,
} from "./foregroundDelegation.ts";

export const LIBRARIAN_AGENT = "perk.librarian";

export interface LibrarianEngineOptions {
  events: DelegationEvents;
  /** Pi's public tool census says pi-subagents' `subagent` tool is registered. */
  enginePresent: () => boolean;
  /** Offline seam: construction-only, never model/tool input. */
  configPath?: string;
}

export interface LibrarianRefusal {
  kind: "refused";
  reason: "unavailable" | "incompatible-worktree-default";
  nativeWorktreeConfig?: { path: string; observed: string };
}

export type LibrarianDispatch = LibrarianRefusal | { kind: "outcome"; outcome: ForegroundOutcome };

export interface LibrarianEngine {
  /** Presence then the native verdict; `null` = a dispatch may launch. */
  preflight(): LibrarianRefusal | null;
  dispatch(
    launch: { task: string; cwd: string; model?: string },
    tuple: DelegationTuple,
    signal: AbortSignal,
  ): Promise<LibrarianDispatch>;
}

export function createLibrarianEngine(
  options: LibrarianEngineOptions,
): LibrarianEngine & { shutdown(): Promise<void> } {
  const configPath = options.configPath ?? nativeWorktreeConfigPath();
  const nativeWorktree = readNativeWorktreeDefault(configPath);
  const active = new Map<AbortController, Promise<LibrarianDispatch>>();
  function preflight(): LibrarianRefusal | null {
    let present: boolean;
    try {
      present = options.enginePresent();
    } catch {
      present = false;
    }
    if (!present) return { kind: "refused", reason: "unavailable" };
    if (!nativeWorktree.compatible)
      return {
        kind: "refused",
        reason: "incompatible-worktree-default",
        nativeWorktreeConfig: { path: configPath, observed: nativeWorktree.observed },
      };
    return null;
  }
  async function run(
    launch: { task: string; cwd: string; model?: string },
    tuple: DelegationTuple,
    signal: AbortSignal,
  ): Promise<LibrarianDispatch> {
    // The pre-launch cancellation guard at the engine boundary; the transport repeats it.
    if (signal.aborted)
      return {
        kind: "outcome",
        outcome: { failure: "cancelled", release: true, termination: "not-requested" },
      };
    const refused = preflight();
    if (refused) return refused;
    const outcome = await dispatchForeground(
      options.events,
      {
        agent: LIBRARIAN_AGENT,
        task: launch.task,
        cwd: launch.cwd,
        schema: LIBRARIAN_RECORD_SCHEMA,
        ...(launch.model !== undefined ? { model: launch.model } : {}),
      },
      tuple,
      signal,
    );
    return { kind: "outcome", outcome };
  }
  return {
    preflight,
    dispatch(launch, tuple, signal) {
      const controller = new AbortController();
      const result = run(launch, tuple, AbortSignal.any([signal, controller.signal]));
      active.set(controller, result);
      void result.finally(() => active.delete(controller));
      return result;
    },
    async shutdown() {
      for (const c of active.keys()) c.abort();
      await Promise.all(active.values());
    },
  };
}
