import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  DELEGATION_EVENTS,
  type DelegationEvents,
} from "../pi/v1/delivery/conflictResolverEngine.ts";

export const completedResolution = {
  mode: "pr-rebase",
  outcome: "completed",
  verification: "passed",
  push: "succeeded",
  summary: "Offline checks passed.",
};
export const RETAINED_OPERATION = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
export const completedRetainedResolution = {
  mode: "retained-continuation",
  outcome: "completed",
  verification: "passed",
  summary: "Offline checks passed.",
};
export function retainedDispatch(worktree: string) {
  return {
    operationId: RETAINED_OPERATION,
    worktree,
    manifestPath: join(worktree, "sync-continuations/01LIN.json"),
    objective: "7",
    node: "2.1",
    branch: "plan-91",
    pr: 91,
  };
}
export class FakeDelegationBus implements DelegationEvents {
  handlers = new Map<string, Set<(data: unknown) => void>>();
  sent: { event: string; data: unknown }[] = [];
  on(event: string, handler: (data: unknown) => void): () => void {
    const set = this.handlers.get(event) ?? new Set();
    this.handlers.set(event, set);
    set.add(handler);
    return () => {
      set.delete(handler);
    };
  }
  emit(event: string, data: unknown) {
    this.sent.push({ event, data });
    for (const handler of this.handlers.get(event) ?? []) handler(data);
  }
  count() {
    return [...this.handlers.values()].reduce((sum, s) => sum + s.size, 0);
  }
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
/**
 * The fake engine: answers on the public delegation event bus and registers an inert `subagent`
 * tool so the production presence predicate (Pi's tool census) composes through every harness
 * session. The tool itself is never the transport.
 */
export function fakeConflictResolver(
  cwd: string,
  script?: (bus: DelegationEvents, request: Record<string, unknown>) => void,
) {
  const requests: Record<string, unknown>[] = [];
  return {
    requests,
    resolverEngine: { configPath: join(cwd, "absent-native-config.json") },
    extension(pi: ExtensionAPI) {
      pi.registerTool({
        name: "subagent",
        label: "subagent",
        description: "fake pi-subagents tool (test) — presence only",
        parameters: { type: "object", properties: {} },
        async execute() {
          throw new Error("the fake engine answers on the event bus, never through the tool");
        },
      });
      pi.events.on(DELEGATION_EVENTS.request, (data) => {
        const r = data as Record<string, unknown>;
        requests.push(r);
        if (script) script(pi.events, r);
        else
          pi.events.emit(DELEGATION_EVENTS.response, {
            requestId: r.requestId,
            ownerRunId: r.ownerRunId,
            nodeId: r.nodeId,
            status: "completed",
            result: {
              kind: "structured",
              value:
                r.nodeId === "retained-conflict"
                  ? completedRetainedResolution
                  : completedResolution,
            },
          });
      });
    },
  };
}
