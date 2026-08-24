// The branch/file WorkflowSession backing: identity from the rebuilt `perk:workflow-state`
// (`activeSessionRunId`), artifact ops delegating to `substrate/sessionData.ts`'s classified
// cores — one artifact-discipline implementation, two consumers (this seam + the legacy
// null-collapsing wrappers). The reporting slice arrives through `SessionArtifactCtx`, so this
// module never imports `surfaces/`.

import {
  activeSessionRunId,
  readSessionArtifactClassified,
  type SessionArtifactCtx,
  writeSessionArtifactClassified,
} from "../substrate/sessionData.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import type { OpenWorkflowSession, ReadArtifactResult, WriteArtifactResult } from "./workflowSession.ts";

/**
 * Open the branch-backed session for the current context: `absent` without a `run_id` (a
 * session exists only with identity). Artifact ops re-derive validation state from the live
 * branch per call — the classified cores own the digest/pointer discipline.
 */
export function openBranchWorkflowSession(
  sink: EntrySink,
  source: SessionArtifactCtx,
): OpenWorkflowSession {
  const runId = activeSessionRunId(source);
  if (runId === null) return { status: "absent" };
  return {
    status: "opened",
    session: {
      runId,
      readArtifact(name: string): ReadArtifactResult {
        const result = readSessionArtifactClassified(source, name);
        switch (result.status) {
          case "found":
            return { status: "found", content: result.content };
          case "absent":
            return { status: "absent" };
          case "invalid":
            return { status: "invalid", problem: result.problem };
        }
      },
      writeArtifact(name: string, content: string): WriteArtifactResult {
        const result = writeSessionArtifactClassified(sink, source, name, content);
        switch (result.status) {
          case "applied":
            return { status: "applied", pointer: result.pointer };
          case "unchanged":
            return { status: "unchanged", pointer: result.pointer };
          case "unverified":
            return { status: "unverified", problem: result.problem };
          case "rejected":
            return { status: "rejected", problem: result.problem };
        }
      },
    },
  };
}
