// Subject-specific save composition. Mutation saves are live; Plannotator dispatch completion
// remains uncomposed. Both use explicit claimed sessions/capabilities, never competing guards.
import type { GistBackend } from "../../authoring/gist/save.ts";
import type { ObjectiveApprovalSaveDeps } from "../../authoring/objective/save.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import type { PlanApprovalSaveDeps } from "../../authoring/plan/save.ts";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import type { SaveReceipt } from "../../session/draftReviewState.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import type { DraftReviewConfirmedFacts } from "./draftReviewActivation.ts";
import type { DraftReviewCapability } from "./draftReviewDecisions.ts";

/** Receipt facts survive failed linkage. This is not a dispatch record or a retry protocol. */
function mutationReceipt(
  session: WorkflowSession,
  gate: ApprovalGate,
  mode: "manual" | "approval",
  facts: DraftReviewConfirmedFacts,
) {
  const wasActive = mode === "approval" && gate.isActive();
  const exit = () => {
    if (!wasActive || facts.gateExited === true) return;
    // The mutation session expires on release and checks owned exclusion on every call.
    if (!session.currentRunIdentity().ok) throw new Error("save mutation identity unavailable");
    gate.exit();
    facts.gateExited = true;
  };
  return {
    confirm(receipt: SaveReceipt) {
      facts.saveReceipt = receipt;
      if (!session.currentRunIdentity().ok) throw new Error("save mutation identity unavailable");
      // Approval's successful-save gate outcome must precede fallible linkage bookkeeping.
      exit();
    },
    gate: { isActive: () => wasActive, exit },
  };
}

export function mutationPlanSaveDeps(
  deps: PlanApprovalSaveDeps,
  session: WorkflowSession,
  facts: DraftReviewConfirmedFacts,
  mode: "manual" | "approval",
): PlanApprovalSaveDeps {
  const receipt = mutationReceipt(session, deps.gate, mode, facts);
  return {
    ...deps,
    session,
    gate: receipt.gate,
    backend: {
      async save(request) {
        const value = await deps.backend.save(request);
        if (value.status === "saved") receipt.confirm({ id: value.ref.pr_id, url: value.ref.url });
        return value;
      },
    },
  };
}

export function mutationObjectiveSaveDeps(
  deps: ObjectiveApprovalSaveDeps,
  session: WorkflowSession,
  facts: DraftReviewConfirmedFacts,
  mode: "manual" | "approval",
): ObjectiveApprovalSaveDeps {
  const receipt = mutationReceipt(session, deps.gate, mode, facts);
  return {
    ...deps,
    session,
    gate: receipt.gate,
    backend: {
      async create(request) {
        const value = await deps.backend.create(request);
        if (value.status === "saved") receipt.confirm({ id: value.id, url: value.url });
        return value;
      },
    },
  };
}

export function mutationGistSaveDeps(
  deps: { session: WorkflowSession; backend: GistBackend; gate: ApprovalGate },
  facts: DraftReviewConfirmedFacts,
  mode: "manual" | "approval",
) {
  const receipt = mutationReceipt(deps.session, deps.gate, mode, facts);
  return {
    ...deps,
    gate: receipt.gate,
    backend: {
      async save(request: Parameters<GistBackend["save"]>[0]) {
        const value = await deps.backend.save(request);
        if (value.status === "saved") receipt.confirm({ id: value.id, url: value.url });
        return value;
      },
    },
  };
}

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
    const active = gate.isActive();
    if (active) gate.exit();
    return { gateExited: active };
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
