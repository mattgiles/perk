// Claim-bound save composition, not yet wired into live tool/browser completion.
import type { GistBackend } from "../../authoring/gist/save.ts";
import type { ObjectiveApprovalSaveDeps } from "../../authoring/objective/save.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import type { PlanApprovalSaveDeps } from "../../authoring/plan/save.ts";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import type { DraftReviewCapability } from "./draftReviewDecisions.ts";

/** Only patch/linkage effects are delegated. No global owner flag or reentrant acquisition. */
function ownedReviewSession(
  session: WorkflowSession,
  capability: DraftReviewCapability,
): WorkflowSession {
  return {
    get runId() {
      return session.runId;
    },
    currentRunIdentity: () => session.currentRunIdentity(),
    draftReviewContext: () => session.draftReviewContext(),
    readArtifact: (name) => session.readArtifact(name, { provenance: "strict" }),
    nodeClaim: () => session.nodeClaim(),
    activeObjective: () => session.activeObjective(),
    reviewPosts: () => session.reviewPosts(),
    writeArtifact(name, content) {
      if (name !== PLAN_DRAFT_ARTIFACT)
        throw new Error("review capability permits only the plan patch");
      return capability.writePlan(content);
    },
    apply(change) {
      if (
        change.kind !== "link-plan-ref" &&
        change.kind !== "link-objective" &&
        change.kind !== "clear-node-claim"
      )
        throw new Error("review capability permits only save linkage");
      return capability.apply(change);
    },
  };
}

function receiptGate(gate: ApprovalGate) {
  return () => {
    if (gate.isActive()) gate.exit();
  };
}

/** Called inside dispatch; the backend wrapper runs AFTER savePlan's awaited title generation. */
export function boundPlanSaveDeps(
  deps: PlanApprovalSaveDeps,
  capability: DraftReviewCapability,
): PlanApprovalSaveDeps {
  return {
    ...deps,
    session: ownedReviewSession(deps.session, capability),
    backend: {
      save: (request) =>
        capability.save(async ({ source, warmNodeClaim }) => {
          const value = await deps.backend.save({
            ...request,
            plan: source.trim(),
            // The fingerprint captured these exact inputs. Absent retains the cold handoff fallback.
            objectiveId: warmNodeClaim?.objective,
            nodeId: warmNodeClaim?.node,
          });
          return {
            value,
            receipt: value.status === "saved" ? { id: value.ref.pr_id, url: value.ref.url } : null,
          };
        }, receiptGate(deps.gate)),
    },
    gate: { isActive: () => deps.gate.isActive(), exit: receiptGate(deps.gate) },
  };
}

/** Preserve the structured objective save/dream-report policy; fence its actual backend port. */
export function boundObjectiveSaveDeps(
  deps: ObjectiveApprovalSaveDeps,
  capability: DraftReviewCapability,
): ObjectiveApprovalSaveDeps {
  return {
    ...deps,
    session: ownedReviewSession(deps.session, capability),
    backend: {
      create: (request) =>
        capability.save(async () => {
          const value = await deps.backend.create(request);
          return {
            value,
            receipt: value.status === "saved" ? { id: value.id, url: value.url } : null,
          };
        }, receiptGate(deps.gate)),
    },
    gate: { isActive: () => deps.gate.isActive(), exit: receiptGate(deps.gate) },
  };
}

/** Gist retains its own scope/title/structured-source policy and has no linkage operation. */
export function boundGistSaveDeps(
  deps: { session: WorkflowSession; backend: GistBackend; gate: ApprovalGate },
  capability: DraftReviewCapability,
) {
  return {
    ...deps,
    session: ownedReviewSession(deps.session, capability),
    backend: {
      save: (request: Parameters<GistBackend["save"]>[0]) =>
        capability.save(async () => {
          const value = await deps.backend.save(request);
          return {
            value,
            receipt: value.status === "saved" ? { id: value.id, url: value.url } : null,
          };
        }, receiptGate(deps.gate)),
    },
    gate: { isActive: () => deps.gate.isActive(), exit: receiptGate(deps.gate) },
  };
}
