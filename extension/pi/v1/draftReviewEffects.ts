// Subject-specific save composition with explicit claimed sessions/capabilities, never competing guards.
import type { GistBackend } from "../../authoring/gist/save.ts";
import type { ObjectiveApprovalSaveDeps } from "../../authoring/objective/save.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import type { PlanApprovalSaveDeps } from "../../authoring/plan/save.ts";
import { decodeRefinementDraft } from "../../authoring/refinement/draft.ts";
import type {
  RefinementBackend,
  RefinementBackendSaveResult,
  ReviewedRefinementPair,
} from "../../authoring/refinement/save.ts";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import type { SaveReceipt } from "../../session/draftReviewState.ts";
import {
  digestSessionData,
  REFINEMENT_CONTEXT_ARTIFACT,
  type WorkflowSession,
} from "../../session/workflowSession.ts";
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

/**
 * The worker's typed failure, retained OUTSIDE the capability callback: the capability itself
 * only sees "no receipt" and stops conservatively (unresolved dispatch), so the caller relays
 * these facts beside the stop for reconciliation. Never a retry license.
 */
export interface RefinementSaveDiagnostics {
  failure?: Extract<RefinementBackendSaveResult, { status: "failed" }>;
}

/** The mutation-boundary refinement save (the human command and the first-party approval):
 * exact draft bytes + explicit run id; the receipt is the verified comment id + carrier URL
 * (never an invented deep link). An optional `reviewed` pair rides through to the seam, which
 * refuses to save a replacement of what the human judged. No linkage operation exists. */
export function mutationRefinementSaveDeps(
  deps: {
    session: WorkflowSession;
    backend: RefinementBackend;
    gate: ApprovalGate;
    reviewed?: ReviewedRefinementPair;
  },
  facts: DraftReviewConfirmedFacts,
  mode: "manual" | "approval",
) {
  const receipt = mutationReceipt(deps.session, deps.gate, mode, facts);
  return {
    ...deps,
    gate: receipt.gate,
    backend: {
      async save(request: Parameters<RefinementBackend["save"]>[0]) {
        const value = await deps.backend.save(request);
        if (value.status === "saved")
          receipt.confirm({ id: value.commentId, url: value.carrierUrl });
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
    activeSessionPlanRef: () => session.activeSessionPlanRef(),
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
  let result: { gateExited: boolean } | undefined;
  return () => {
    if (result !== undefined) return result;
    const active = gate.isActive();
    if (active) gate.exit();
    result = { gateExited: active };
    return result;
  };
}

/** Called inside dispatch; the backend wrapper runs AFTER savePlan's awaited title generation. */
export function boundPlanSaveDeps(
  deps: PlanApprovalSaveDeps,
  capability: DraftReviewCapability,
): PlanApprovalSaveDeps {
  const exit = receiptGate(deps.gate);
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
        }, exit),
    },
    gate: { isActive: () => deps.gate.isActive(), exit },
  };
}

/** Preserve the structured objective save/dream-report policy; fence its actual backend port. */
export function boundObjectiveSaveDeps(
  deps: ObjectiveApprovalSaveDeps,
  capability: DraftReviewCapability,
): ObjectiveApprovalSaveDeps {
  const exit = receiptGate(deps.gate);
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
        }, exit),
    },
    gate: { isActive: () => deps.gate.isActive(), exit },
  };
}

/**
 * Refinement fences the reviewed (draft, context) pair: immediately before the worker, the
 * staged draft bytes must decode, belong to this run and name the CURRENT bound context's digest
 * — a known pre-invocation failure returns a typed failure WITHOUT entering the capability save
 * (no save-started, no uncertainty, no gate exit). Inside the capability the bytes handed to the
 * worker are the capability-selected reviewed source (which the seam's strict resume must
 * equal — the `source-changed` fence already guards the artifact). A worker failure inside the
 * capability is recorded on `diagnostics` BEFORE the capability sees the missing receipt, so
 * the conservative unresolved-dispatch stop it raises can be rendered with the worker's typed
 * facts. No linkage operation exists.
 */
export function boundRefinementSaveDeps(
  deps: { session: WorkflowSession; backend: RefinementBackend; gate: ApprovalGate },
  capability: DraftReviewCapability,
  diagnostics: RefinementSaveDiagnostics = {},
) {
  const exit = receiptGate(deps.gate);
  return {
    ...deps,
    session: ownedReviewSession(deps.session, capability),
    backend: {
      save: async (request: Parameters<RefinementBackend["save"]>[0]) => {
        const refused = (message: string): Awaited<ReturnType<RefinementBackend["save"]>> => ({
          status: "failed",
          message,
          errorType: "refinement_draft_invalid",
          writeAttempted: false,
          commentIds: [],
        });
        const decoded = decodeRefinementDraft(request.draftRaw);
        if (!decoded.ok) return refused(decoded.problem);
        const identity = deps.session.currentRunIdentity();
        if (
          !identity.ok ||
          decoded.draft.run_id !== identity.runId ||
          request.runId !== identity.runId
        )
          return refused("the staged refinement draft does not belong to this run");
        const context = deps.session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT, {
          provenance: "strict",
        });
        if (context.status !== "found")
          return refused("the refinement context is missing or invalid at save time");
        if (decoded.draft.context_digest !== digestSessionData(context.content))
          return refused(
            "the staged refinement draft is bound to an earlier context (rewrite it with " +
              "objective_refinement_draft against the current context)",
          );
        return capability.save(async ({ source }) => {
          if (source !== request.draftRaw)
            throw new Error("the reviewed refinement source and the staged draft bytes diverged");
          const value = await deps.backend.save({ runId: request.runId, draftRaw: source });
          if (value.status === "failed") diagnostics.failure = value;
          return {
            value,
            receipt:
              value.status === "saved" ? { id: value.commentId, url: value.carrierUrl } : null,
          };
        }, exit);
      },
    },
    gate: { isActive: () => deps.gate.isActive(), exit },
  };
}

/** Gist retains its own scope/title/structured-source policy and has no linkage operation. */
export function boundGistSaveDeps(
  deps: { session: WorkflowSession; backend: GistBackend; gate: ApprovalGate },
  capability: DraftReviewCapability,
) {
  const exit = receiptGate(deps.gate);
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
        }, exit),
    },
    gate: { isActive: () => deps.gate.isActive(), exit },
  };
}
