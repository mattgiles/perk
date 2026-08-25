// The branch/file WorkflowSession backing: identity from the rebuilt `perk:workflow-state`
// (`activeSessionRunId`), artifact ops delegating to `substrate/sessionData.ts`'s classified
// cores — one artifact-discipline implementation, two consumers (this seam + the legacy
// null-collapsing wrappers) — and the workflow-state ops delegating to the strict-append seam
// (`appendWorkflowState`) with the exact scope/failure strings the plan-save surfaces always
// used (the append helper's loud `report()` warning path is unchanged and remains the loudness
// channel). The reporting slice arrives through `SessionArtifactCtx`, so this module never
// imports `surfaces/`.

import {
  activeSessionRunId,
  readSessionArtifactClassified,
  type SessionArtifactCtx,
  writeSessionArtifactClassified,
} from "../substrate/sessionData.ts";
import {
  appendWorkflowState,
  branchOf,
  type EntrySink,
  nodeClaimsEqual,
  planRefsEqual,
  readNodeClaim,
  rebuildWorkflowState,
} from "../substrate/workflowState.ts";
import type {
  ReadArtifactResult,
  WorkflowChange,
  WorkflowChangeResult,
  WorkflowSession,
} from "./workflowSession.ts";

/**
 * Open the branch-backed session for the current context — ALWAYS opens; `runId: null` is the
 * identity-less arm (the classified artifact cores refuse writes and read `absent` without a
 * run_id; the workflow-state ops are branch-backed and identity-independent). Artifact ops
 * re-derive validation state from the live branch per call — the classified cores own the
 * digest/pointer discipline.
 */
export function openBranchWorkflowSession(
  sink: EntrySink,
  source: SessionArtifactCtx,
): WorkflowSession {
  return {
    runId: activeSessionRunId(source),
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
    writeArtifact(name: string, content: string) {
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
    nodeClaim() {
      return readNodeClaim(source);
    },
    apply(change: WorkflowChange): WorkflowChangeResult {
      switch (change.kind) {
        case "link-plan-ref": {
          const ref = change.ref;
          if (planRefsEqual(rebuildWorkflowState(branchOf(source)).active_plan_ref ?? null, ref)) {
            return { status: "unchanged" };
          }
          const failure = `plan-ref read-back failed for ${ref.provider}:${ref.pr_id}`;
          const ok = appendWorkflowState(sink, source, {
            data: { active_plan_ref: ref },
            field: "active_plan_ref",
            expected: ref,
            scope: "plan-save",
            failure,
            equals: planRefsEqual,
          });
          // appendWorkflowState never distinguishes refused-before-effect from a read-back
          // miss (both are its loud false), so the branch backing classifies every failure
          // `unverified` — the honest arm: an append may have landed unproven.
          return ok ? { status: "applied" } : { status: "unverified", problem: failure };
        }
        case "clear-node-claim": {
          const claim = change.claim;
          // Never clobber an unrelated claim: clear only when the LIVE claim matches BOTH
          // fields (same-node/different-objective stays untouched).
          if (!nodeClaimsEqual(readNodeClaim(source), claim)) return { status: "unchanged" };
          const failure = `objective_node_claim clear read-back failed for node ${claim.node}`;
          const ok = appendWorkflowState(sink, source, {
            data: { objective_node_claim: null },
            field: "objective_node_claim",
            expected: null,
            scope: "plan-save",
            failure,
            equals: nodeClaimsEqual,
          });
          return ok ? { status: "applied" } : { status: "unverified", problem: failure };
        }
      }
    },
  };
}
