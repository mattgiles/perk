// The branch/file WorkflowSession binding: the one session engine (`workflowSession.ts`) over
// the production ports — `branchSessionStateStore` (the same workflow-state store the identity
// lifecycle uses: rebuild + strict verified append, with `appendWorkflowStateClassified`'s own
// report() path as the loudness channel) and an fs `ArtifactContentStore` built from
// `substrate/sessionData.ts`'s raw primitives (loud write warnings unchanged; the display path
// re-derived repo-relative from run_id + name through the seam — never a persisted pointer
// field). All policy, classification, and error text live in the engine; this file supplies
// mechanics only. The reporting slice arrives through `SessionArtifactCtx`, so this module never
// imports `surfaces/`.

import { join, relative } from "node:path";
import { sessionDataDir } from "../substrate/cache.ts";
import {
  activeSessionRunId,
  readSessionData,
  type SessionArtifactCtx,
  writeSessionData,
} from "../substrate/sessionData.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import { branchSessionStateStore } from "./lifecycle.ts";
import {
  type ArtifactContentStore,
  openWorkflowSession,
  type WorkflowSession,
} from "./workflowSession.ts";

/** The fs content port: session-data raw primitives, mechanical results, zero error prose. */
function fsArtifactStore(source: SessionArtifactCtx): ArtifactContentStore {
  return {
    store(name: string, content: string): boolean {
      // writeSessionData already warns loudly on every failure tier.
      return writeSessionData(source, name, content) !== null;
    },
    load(name: string): string | null {
      return readSessionData(source, name);
    },
    displayPath(name: string): string {
      // Re-derived from the safe-narrowed identity — the engine only asks while identity is
      // established, but degrade structurally rather than throw.
      const runId = activeSessionRunId(source);
      if (runId === null) return name;
      return relative(source.cwd, join(sessionDataDir(source.cwd, runId), name));
    },
  };
}

/**
 * Open the branch-backed session for the current context — ALWAYS opens; `runId: null` is the
 * identity-less arm (the engine refuses artifact writes and reads `absent` without a run_id;
 * the workflow-state ops are branch-backed and identity-independent).
 */
export function openBranchWorkflowSession(
  sink: EntrySink,
  source: SessionArtifactCtx,
): WorkflowSession {
  return openWorkflowSession({
    state: branchSessionStateStore(sink, source),
    artifacts: fsArtifactStore(source),
  });
}
