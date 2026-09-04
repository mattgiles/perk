// The branch/file WorkflowSession binding: the one session engine (`workflowSession.ts`) over
// the production ports — `branchSessionStateStore` (the same workflow-state store the identity
// lifecycle uses: rebuild + strict verified append, with `appendWorkflowStateClassified`'s own
// report() path as the loudness channel) and an fs `ArtifactContentStore` built from
// `substrate/sessionData.ts`'s raw primitives (loud write warnings unchanged). Every content
// operation receives the ENGINE-validated run id and derives its path from that one identity —
// this binding never resolves an identity of its own, so storage, pointer, and receipt can
// never disagree. All policy, classification, and error text live in the engine; this file
// supplies mechanics only. The reporting slice arrives through `SessionArtifactCtx`, so this
// module never imports `surfaces/`.

import { join, relative } from "node:path";
import { sessionDataDir } from "../substrate/cache.ts";
import {
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
    store(runId: string, name: string, content: string): boolean {
      // writeSessionData already warns loudly on every failure tier.
      return writeSessionData(source.cwd, runId, name, content) !== null;
    },
    load(runId: string, name: string): string | null {
      return readSessionData(source.cwd, runId, name);
    },
    displayPath(runId: string, name: string): string {
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
