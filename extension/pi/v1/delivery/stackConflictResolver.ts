// Immediate, activation-local authority; preparation alone owns the on-disk session claim
// and counter. Neither this controller nor its delivery guard owns execution-lock cleanup.
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type {
  ConflictResolutionRequest,
  ConflictResolutionResult,
  ConflictResolver,
  RetainedConflictResolutionRequest,
} from "../../../delivery/conflictResolution.ts";
import type { SyncResolutionOutcome } from "../../../delivery/stackConflict.ts";
import { planningStageRefusal } from "../../../session/lifecycleGates.ts";
import { subagentModel } from "../../../substrate/config.ts";
import {
  branchOf,
  conflictResolutionAttempts,
  rebuildWorkflowState,
} from "../../../substrate/workflowState.ts";

type Prepared = Extract<SyncResolutionOutcome, { kind: "dispatched" }>;
export type StackResolutionOutcome =
  | (Exclude<SyncResolutionOutcome, Prepared> & { isCurrent(): boolean })
  | {
      kind: "executed";
      dispatch: Prepared["dispatch"];
      attempt: number;
      cap: number;
      resolution: ConflictResolutionResult;
      /** Valid after settlement too: delivery is a separate, revocable side effect. */
      isCurrent(): boolean;
    };
export interface StackConflictResolver {
  run(
    ctx: ExtensionContext,
    prepare: (isCurrent: () => boolean) => Promise<SyncResolutionOutcome>,
    signal?: AbortSignal,
  ): Promise<StackResolutionOutcome>;
  authorized(request: ConflictResolutionRequest): boolean;
  setContext(ctx: ExtensionContext): void;
  shutdown(): void;
}
interface Identity {
  sessionId: string;
  runId: string;
  cwd: string;
}
interface Invocation {
  controller: AbortController;
  isCurrent(): boolean;
  request?: RetainedConflictResolutionRequest;
}

export function createStackConflictResolver(
  resolver: ConflictResolver,
  readOnly: () => boolean,
): StackConflictResolver {
  let current: ExtensionContext | undefined;
  let generation = 0;
  let closed = false;
  let active: Invocation | undefined;
  function identity(ctx: ExtensionContext): Identity | null {
    const state = rebuildWorkflowState(branchOf(ctx));
    const sessionId = ctx.sessionManager.getSessionId();
    if (
      !state.run_id ||
      !sessionId ||
      state.mode !== "read-write" ||
      planningStageRefusal(ctx, "objective-sync") !== null
    )
      return null;
    return { sessionId, runId: state.run_id, cwd: ctx.cwd };
  }
  function matches(ctx: ExtensionContext, parent: Identity): boolean {
    const now = identity(ctx);
    return (
      now !== null &&
      now.cwd === parent.cwd &&
      now.sessionId === parent.sessionId &&
      now.runId === parent.runId
    );
  }
  return {
    setContext(ctx) {
      generation++;
      current = ctx;
      active?.controller.abort();
    },
    shutdown() {
      closed = true;
      generation++;
      current = undefined;
      active?.controller.abort();
    },
    authorized(request) {
      return (
        request.mode === "retained-continuation" &&
        active !== undefined &&
        active.request === request &&
        active.isCurrent()
      );
    },
    async run(ctx, prepare, signal) {
      const refusal = (reason: string): StackResolutionOutcome => ({
        kind: "state_error",
        reason,
        isCurrent: () => false,
      });
      // Refuse overlap before another status read, claim or increment.
      if (active)
        return refusal("retained resolver authorization refused: invocation already active");
      let parent: Identity | null;
      try {
        parent = identity(ctx);
      } catch {
        parent = null;
      }
      if (parent === null)
        return refusal(
          "retained resolver authorization refused: missing identity or non-writing/planning context",
        );
      const snapshot = Object.freeze(parent);
      const epoch = generation;
      let attempt: number | undefined;
      const controller = new AbortController();
      const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
      const isCurrent = () => {
        try {
          return (
            !closed &&
            !combined.aborted &&
            generation === epoch &&
            !readOnly() &&
            current !== undefined &&
            matches(current, snapshot) &&
            matches(ctx, snapshot) &&
            (attempt === undefined ||
              (conflictResolutionAttempts(current) === attempt &&
                conflictResolutionAttempts(ctx) === attempt))
          );
        } catch {
          return false;
        }
      };
      const revoked = () => (signal?.aborted ? ("cancelled" as const) : ("unauthorized" as const));
      if (!isCurrent()) return refusal(`retained resolver preparation ${revoked()}`);
      const invocation: Invocation = { controller, isCurrent };
      active = invocation;
      try {
        const prepared = await prepare(isCurrent);
        if (prepared.kind !== "dispatched") return { ...prepared, isCurrent };
        attempt = prepared.attempt;
        const dispatch = Object.freeze({ ...prepared.dispatch });
        const request: RetainedConflictResolutionRequest = Object.freeze({
          ...dispatch,
          mode: "retained-continuation",
          parent: Object.freeze({ sessionId: snapshot.sessionId, runId: snapshot.runId }),
          model: subagentModel(snapshot.cwd, "conflict-resolver"),
        });
        invocation.request = request;
        const received = await resolver.resolve(request, combined);
        const resolution: ConflictResolutionResult = !isCurrent()
          ? { kind: "failed", reason: revoked(), receipt: received.receipt }
          : received.kind === "resolved"
            ? { kind: "failed", reason: "malformed-result", receipt: received.receipt }
            : received;
        return { kind: "executed", dispatch, attempt, cap: prepared.cap, resolution, isCurrent };
      } finally {
        active = undefined;
      }
    },
  };
}
