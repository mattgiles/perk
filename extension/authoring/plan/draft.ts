// The plan working-draft feature: the fixed artifact constant and the two draft operations over
// the WorkflowSession seam. Unlike the gist sibling there is NO encode/decode layer — the
// artifact is raw plan markdown (no JSON envelope), so a revision is the bytes themselves.
//
// Carve-out doctrine (mirrors `authoring/gist/`): the artifact name is the fixed constant
// `PLAN_DRAFT_ARTIFACT` and every byte flows through the session seam (file + verified
// `session_artifacts` pointer), so the only thing the draft ops can ever touch is the one
// working-plan artifact in the current run's data dir (gitignored scratch). A revision is a
// WHOLE-VALUE replacement — full rewrite per call, never a save (`plan_save`/`/plan-save` still
// persist to GitHub).

import type { SessionArtifactReceipt, WorkflowSession } from "../../session/workflowSession.ts";

/** The fixed working-plan artifact name (NOT `plan.md` — `cache.plan` is a different file). */
export const PLAN_DRAFT_ARTIFACT = "plan-draft.md";

/**
 * The revise outcome. `rejected` splits by `reason` so the adapter renders the exact failure
 * taxonomy it always had: `blank_plan` (input refused), `no_identity` (an identity-less
 * session), and `write_refused` (the seam refused before any effect); `unverified` means an
 * effect may have landed but the read-back proof failed. `problem` carries the caller-facing
 * message bytes.
 */
export type RevisePlanDraftResult =
  | { status: "revised"; receipt: SessionArtifactReceipt; bytes: number }
  | { status: "unchanged"; receipt: SessionArtifactReceipt; bytes: number }
  | { status: "rejected"; reason: "blank_plan" | "no_identity" | "write_refused"; problem: string }
  | { status: "unverified"; problem: string };

/**
 * Rewrite the working plan draft (a whole-value replacement) through the session seam.
 * Diagnostic precedence preserved: a blank plan is refused FIRST, missing identity second (the
 * identity-optional session classifies `runId: null` — an identity-less caller still opens),
 * then the verified artifact write. A byte-identical rewrite short-circuits `unchanged` (the
 * session engine owns the probe). Never throws.
 */
export function revisePlanDraft(
  input: { plan: string },
  session: WorkflowSession,
): RevisePlanDraftResult {
  if (!input.plan.trim()) {
    return {
      status: "rejected",
      reason: "blank_plan",
      problem: "no plan markdown to write (pass the full working draft)",
    };
  }
  if (session.runId === null) {
    return {
      status: "rejected",
      reason: "no_identity",
      problem: "session has no run_id — cannot write the plan-draft artifact",
    };
  }
  const bytes = Buffer.byteLength(input.plan, "utf8");
  const written = session.writeArtifact(PLAN_DRAFT_ARTIFACT, input.plan);
  switch (written.status) {
    case "applied":
      return { status: "revised", receipt: written.receipt, bytes };
    case "unchanged":
      return { status: "unchanged", receipt: written.receipt, bytes };
    case "rejected":
      return {
        status: "rejected",
        reason: "write_refused",
        problem: `could not write the ${PLAN_DRAFT_ARTIFACT} artifact (see warnings)`,
      };
    case "unverified":
      return {
        status: "unverified",
        problem: `could not write the ${PLAN_DRAFT_ARTIFACT} artifact (see warnings)`,
      };
  }
}

/**
 * Resume the working plan draft from the session. Fail-open `null` everywhere: `absent` is the
 * silent no-draft arm; `invalid` was already warned by the seam. Raw markdown — blankness is
 * the RESOLVER's concern (`resolvePlanSource` treats a blank draft as no draft). Never throws.
 */
export function resumePlanDraft(session: WorkflowSession): string | null {
  const read = session.readArtifact(PLAN_DRAFT_ARTIFACT);
  return read.status === "found" ? read.content : null;
}
