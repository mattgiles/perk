// The draft-subject vocabulary: the four stage-derived working-draft kinds, each with the session
// artifact it lives in and the ONE model-facing writer that authors it. Shared by the draft-review
// guards (reviewed-bytes compare) and the `/draft-and-compact` checkpoint (baseline digest + the
// writer its guidance names).

import type { WorkflowSession } from "../../session/workflowSession.ts";
import { GIST_DRAFT_ARTIFACT } from "../gist/draft.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "../objective/draft.ts";
import { PLAN_DRAFT_ARTIFACT } from "../plan/draft.ts";
import { REFINEMENT_DRAFT_ARTIFACT } from "../refinement/draft.ts";

/** The stage-derived draft kind — structurally bound to the session seam's routing read
 * (`WorkflowSession.draftReviewContext`), so a new subject there fails to compile here. */
export type DraftSubject = Extract<
  ReturnType<WorkflowSession["draftReviewContext"]>,
  { ok: true }
>["subject"];

/** Subject → the session artifact holding its working draft. */
export const DRAFT_SUBJECT_ARTIFACTS: Readonly<Record<DraftSubject, string>> = {
  plan: PLAN_DRAFT_ARTIFACT,
  objective: OBJECTIVE_DRAFT_ARTIFACT,
  gist: GIST_DRAFT_ARTIFACT,
  refinement: REFINEMENT_DRAFT_ARTIFACT,
};

/** Subject → the ONE model-facing writer that authors its artifact (the tool the guidance names). */
export const DRAFT_SUBJECT_WRITERS: Readonly<Record<DraftSubject, string>> = {
  plan: "plan_draft",
  objective: "objective_draft",
  gist: "gist_draft",
  refinement: "objective_refinement_draft",
};
