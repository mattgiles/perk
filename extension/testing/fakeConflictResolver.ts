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
/** A consistent `published` librarian record (the child's untrusted report) for `slug`. */
export function publishedLibrarianRecord(
  slug: string,
  action: "add-docs" | "refresh-docs" = "add-docs",
) {
  return {
    action,
    outcome: "published",
    slug,
    published_path: `docs/library/documentation/${slug}`,
    pages_published: 3,
    failures_accepted: 0,
    summary: "Crawled 3 pages, pruned none, no failures.",
  };
}
/** The slug + action a librarian task names (the code-authored `Entry slug:`/action lines). */
export function librarianTaskFacts(task: unknown): {
  slug: string;
  action: "add-docs" | "refresh-docs";
} {
  const text = typeof task === "string" ? task : "";
  const slug = /^Entry slug: (.+)$/m.exec(text)?.[1] ?? "";
  const action = /^LIBRARIAN TASK — action: refresh-docs\.$/m.test(text)
    ? "refresh-docs"
    : "add-docs";
  return { slug, action };
}
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
/**
 * The engine's delegation-request field census and `intercomBridge` rules, as read at
 * pi-subagents 0.76.1 (`parseSubagentDelegationRequest` + `validateIntercomBridgeConfig`): any
 * top-level key outside these fifteen is rejected `invalid_request` ("Unsupported delegation
 * field: <key>."); a present `intercomBridge` must be a non-array object whose keys are a subset
 * of `mode|instructionFile|resultDelivery`, with `mode` OPTIONAL but one of `off|fork-only|always`
 * when present, `instructionFile` a string of at most 1 KiB UTF-8 when present, and
 * `resultDelivery` a boolean when present — so `{}` is valid. Mirrored so a transport field the
 * engine would reject fails offline instead of completing; re-read on every pi-subagents bump.
 */
const DELEGATION_REQUEST_FIELDS = new Set([
  "requestId",
  "ownerRunId",
  "nodeId",
  "agent",
  "task",
  "context",
  "cwd",
  "model",
  "thinking",
  "timeoutMs",
  "toolBudget",
  "skill",
  "artifacts",
  "intercomBridge",
  "result",
]);
const INTERCOM_BRIDGE_FIELDS = new Set(["mode", "instructionFile", "resultDelivery"]);
const INTERCOM_BRIDGE_MODES = new Set(["off", "fork-only", "always"]);
const INSTRUCTION_FILE_MAX_BYTES = 1024;

/** The engine's rejection error for `r`, or `undefined` when the engine would accept it. */
function delegationRequestRejection(r: Record<string, unknown>): string | undefined {
  const unsupported = Object.keys(r).find((key) => !DELEGATION_REQUEST_FIELDS.has(key));
  if (unsupported !== undefined) return `Unsupported delegation field: ${unsupported}.`;
  if (r.intercomBridge === undefined) return undefined;
  const bridge = r.intercomBridge;
  if (typeof bridge !== "object" || bridge === null || Array.isArray(bridge))
    return "intercomBridge must be an object.";
  const fields = bridge as Record<string, unknown>;
  const stray = Object.keys(fields).find((key) => !INTERCOM_BRIDGE_FIELDS.has(key));
  if (stray !== undefined) return `intercomBridge.${stray} is not supported.`;
  if (fields.mode !== undefined && !INTERCOM_BRIDGE_MODES.has(fields.mode as string))
    return "intercomBridge.mode is invalid.";
  if (fields.instructionFile !== undefined && typeof fields.instructionFile !== "string")
    return "intercomBridge.instructionFile must be a string.";
  if (fields.resultDelivery !== undefined && typeof fields.resultDelivery !== "boolean")
    return "intercomBridge.resultDelivery must be a boolean.";
  if (
    typeof fields.instructionFile === "string" &&
    Buffer.byteLength(fields.instructionFile, "utf8") > INSTRUCTION_FILE_MAX_BYTES
  )
    return "intercomBridge.instructionFile exceeds 1 KiB when UTF-8 encoded.";
  return undefined;
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
 * session. The tool itself is never the transport. Like the engine, it first validates each
 * request against `DELEGATION_REQUEST_FIELDS` and the `intercomBridge` rules and answers a
 * rejected one `invalid_request` (identity fields + `error`) — neither the script nor the
 * default completion runs for it.
 */
export function fakeConflictResolver(
  cwd: string,
  script?: (bus: DelegationEvents, request: Record<string, unknown>) => void,
) {
  const requests: Record<string, unknown>[] = [];
  return {
    requests,
    resolverEngine: { configPath: join(cwd, "absent-native-config.json") },
    librarianEngine: { configPath: join(cwd, "absent-native-config.json") },
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
        const rejection = delegationRequestRejection(r);
        if (rejection !== undefined)
          pi.events.emit(DELEGATION_EVENTS.response, {
            requestId: r.requestId,
            ownerRunId: r.ownerRunId,
            nodeId: r.nodeId,
            status: "invalid_request",
            error: rejection,
          });
        else if (script) script(pi.events, r);
        else
          pi.events.emit(DELEGATION_EVENTS.response, {
            requestId: r.requestId,
            ownerRunId: r.ownerRunId,
            nodeId: r.nodeId,
            status: "completed",
            result: {
              kind: "structured",
              value:
                r.nodeId === "librarian"
                  ? (() => {
                      const facts = librarianTaskFacts(r.task);
                      return publishedLibrarianRecord(facts.slug, facts.action);
                    })()
                  : r.nodeId === "retained-conflict"
                    ? completedRetainedResolution
                    : completedResolution,
            },
          });
      });
    },
  };
}
