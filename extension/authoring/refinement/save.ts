// The objective-refinement SAVE feature: the narrow exterior `RefinementBackend` port (one
// production adapter — the `perk objective refinement-save` cold door in pi/v1 — plus
// deterministic fakes in the tests) and the shared save seam `refinementApprovalSave` both
// persistence gestures run: the APPROVED `plan_review` refinement arm and the human
// `/objective-refinement-save` command (contracts.md §8.67).
//
// The seam strict-resumes the (draft, context) pair and hands the backend the draft's EXACT
// bytes (never the rendered markdown, never in-hand bytes) with the explicit run id; the gate
// exits only after a verified save (D1a). A caller that showed a human a specific pair passes
// its `reviewed` digests: the resumed pair must equal them byte for byte (draft) and digest for
// digest (context), or the seam stops with `source-changed` — an approval never transfers to a
// replacement artifact written during the human wait. There is no linkage, budget, claim or
// cache effect: a successful save carries the backend's verified facts for the caller to relay,
// and the caller says advisory content — not an executable plan — was saved.

import type { WorkflowSession } from "../../session/workflowSession.ts";
import { type ApprovalGate, saveThroughApprovalGate } from "../review/approvalGate.ts";
import { type RefinementDraftPair, resumeRefinementDraft } from "./draft.ts";

/** The verified save facts (the worker's success envelope) or a typed failure. */
export type RefinementBackendSaveResult =
  | {
      status: "saved";
      commentId: string;
      carrierUrl: string;
      carrierIdentifier: string;
      objectiveId: string;
      objectiveRunId: string;
      nodeId: string;
      bodyDigest: string;
      savedAt: string;
      authoredAt: string;
    }
  | {
      status: "failed";
      message: string;
      errorType: string;
      /** The worker's diagnostics when it reported them (read back, never blindly retry). */
      writeAttempted: boolean | null;
      commentIds: string[];
    };

/** The narrow exterior port: the exact draft bytes + the run whose context they bind to. */
export interface RefinementBackend {
  save(req: { runId: string; draftRaw: string }): Promise<RefinementBackendSaveResult>;
}

/**
 * The pair a reviewer actually judged: the draft's exact bytes and the context artifact's digest
 * (the two inputs the rendering is a pure function of — identical rendering over a re-prepared
 * context still names a different pair). Callers capture it BEFORE display and hand it to the
 * seam AFTER the verdict.
 */
export interface ReviewedRefinementPair {
  draftRaw: string;
  contextDigest: string;
}

/** The exact digests of a resumed pair, for a later `reviewed` comparison. */
export function reviewedPairOf(pair: RefinementDraftPair): ReviewedRefinementPair {
  return { draftRaw: pair.draftRaw, contextDigest: pair.context.digest };
}

/** The save-seam outcome. The four non-save arms are fail-closed stops: nothing saved, the
 * gate never touched, with the exact guidance the caller renders. */
export type RefinementApprovalSaveOutcome =
  | { status: "no-draft" }
  | { status: "no-context" }
  | { status: "refused-draft"; problem: string }
  | {
      /** The resumed pair is valid but is not the pair the approval was given for. */
      status: "source-changed";
      changed: "draft" | "context";
    }
  | {
      status: "saved";
      save: Extract<RefinementBackendSaveResult, { status: "saved" }>;
      pair: RefinementDraftPair;
      gateExited: boolean;
    }
  | {
      status: "save-failed";
      save: Extract<RefinementBackendSaveResult, { status: "failed" }>;
      pair: RefinementDraftPair;
      gateExited: false;
    };

/**
 * The shared save seam: strict-resume the pair at save time (a `mismatch` is a refused draft —
 * it names the rewrite; `no-context` names the grounding pass), compare it with the `reviewed`
 * pair when one was captured (the context first: a re-prepared context also rebinds any draft
 * written against it), stage the EXACT draft bytes through the backend with the session's run
 * id, and exit the gate only on a verified save (`saveThroughApprovalGate`: snapshot before,
 * exit after success while read-only, a failed save leaves the gate ON). Never throws.
 */
export async function refinementApprovalSave(deps: {
  session: WorkflowSession;
  backend: RefinementBackend;
  gate: ApprovalGate;
  reviewed?: ReviewedRefinementPair;
}): Promise<RefinementApprovalSaveOutcome> {
  const resumed = resumeRefinementDraft(deps.session);
  if (resumed.kind === "absent") return { status: "no-draft" };
  if (resumed.kind === "no-context") return { status: "no-context" };
  if (resumed.kind === "refused" || resumed.kind === "mismatch")
    return { status: "refused-draft", problem: resumed.problem };
  const pair = resumed.pair;
  if (deps.reviewed !== undefined) {
    if (pair.context.digest !== deps.reviewed.contextDigest)
      return { status: "source-changed", changed: "context" };
    if (pair.draftRaw !== deps.reviewed.draftRaw)
      return { status: "source-changed", changed: "draft" };
  }
  const { outcome: save, gateExited } = await saveThroughApprovalGate(deps.gate, () =>
    deps.backend.save({ runId: pair.draft.run_id, draftRaw: pair.draftRaw }),
  );
  if (save.status !== "saved") return { status: "save-failed", save, pair, gateExited: false };
  return { status: "saved", save, pair, gateExited };
}
