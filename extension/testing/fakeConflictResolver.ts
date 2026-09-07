import { mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  DELEGATION_EVENTS,
  type DelegationEvents,
  type ResolverPreflightInput,
} from "../pi/v1/delivery/conflictResolverEngine.ts";

export const completedResolution = {
  mode: "pr-rebase",
  outcome: "completed",
  verification: "passed",
  push: "succeeded",
  summary: "Offline checks passed.",
};
export function fakeResolverProfile(cwd: string) {
  const path = join(cwd, ".pi/agents/perk/conflict-resolver.md");
  mkdirSync(join(cwd, ".pi/agents/perk"), { recursive: true });
  writeFileSync(path, "offline fixture (public preflight is injected)\n");
  return {
    ok: true,
    contract: {
      agent: {
        name: "perk.conflict-resolver",
        source: "project",
        filePath: realpathSync(path),
        definitionDigest: "definition",
        shadowedCandidates: [],
      },
      context: "fresh",
      model: "offline/model",
      modelCandidates: ["offline/model"],
      systemPromptMode: "replace",
      inheritProjectContext: true,
      inheritGlobalContext: false,
      inheritSkills: true,
      tools: {
        declaredBuiltin: ["read", "grep", "find", "ls", "bash", "edit", "write"],
        effectiveAllowlist: [
          "read",
          "grep",
          "find",
          "ls",
          "bash",
          "edit",
          "write",
          "structured_output",
        ],
        internalTools: ["structured_output"],
        fanoutAuthorized: false,
        explicitAllowlist: true,
        disableAmbientExtensions: true,
        configuredExtensions: [],
        toolExtensionPaths: [],
        effectiveMcpTools: [],
      },
      roots: { cwd: resolve(cwd) },
      diagnostics: [],
      launchContractDigest: "preflight-digest",
    },
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
export function fakeConflictResolver(
  cwd: string,
  script?: (bus: DelegationEvents, request: Record<string, unknown>) => void,
) {
  const profile = fakeResolverProfile(cwd);
  const requests: Record<string, unknown>[] = [];
  const preflights: ResolverPreflightInput[] = [];
  return {
    requests,
    preflights,
    resolverEngine: {
      configPath: join(cwd, "absent-native-config.json"),
      preflight: async (input: ResolverPreflightInput) => {
        preflights.push(input);
        return profile;
      },
    },
    extension(pi: ExtensionAPI) {
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
            result: { kind: "structured", value: completedResolution },
          });
      });
    },
  };
}
