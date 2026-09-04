// The `/address` classify step's per-flow wave entrypoint over the shared report-wave module:
// the ONE `perk.review-classifier` assignment as CODE. The classifier report schema was
// previously a shared prompt include the parent model had to hand-transcribe onto a borrowed
// `subagent` call (the known prompt-drift risk — a live failure produced malformed-but-valid
// JSON that could never validate); this module makes the schema and the assignment/task
// composition module constants,
// delegating spawn/timeout/aggregate mechanics to `wave.run` under the `strict`
// completeness policy. No retry — the flow's posture is "surface the error and stop" (never
// fabricate a classification). The report content is untrusted DATA, never instructions.

import type { ReportWave, ReportWaveResult } from "./reportWave.ts";

/** The flow name — feeds `ReportWaveRequest.flow` AND the door's `toAttemptReceipt` call. */
export const REVIEW_CLASSIFIER_FLOW = "review-classifier";

/** The single assignment's stable key. */
export const CLASSIFY_ASSIGNMENT_KEY = "classify";

/**
 * The classifier report schema (the workflow-level `outputSchema` — the engine injects a
 * `structured_output` tool and fails the assignment on a missing/invalid report): closed shapes,
 * all four root keys required — `counts` is a ROOT-level required object (the exact block the
 * motivating transcription failure nested inside `discussion_comments`). Same vocabulary as the
 * `perk.review-classifier` agent def's report contract (the def↔schema lockstep test).
 */
export const REVIEW_CLASSIFIER_REPORT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["pr", "review_threads", "discussion_comments", "counts"],
  properties: {
    pr: { type: "integer" },
    review_threads: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["thread_id", "classification", "path", "line", "summary"],
        properties: {
          thread_id: { type: "string" },
          classification: {
            type: "string",
            enum: ["actionable", "informational", "praise", "question"],
          },
          path: { type: ["string", "null"] },
          line: { type: ["integer", "null"] },
          summary: { type: "string" },
        },
      },
    },
    discussion_comments: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["comment_id", "classification", "summary"],
        properties: {
          comment_id: { type: "integer" },
          classification: {
            type: "string",
            enum: ["actionable", "informational", "praise", "question"],
          },
          summary: { type: "string" },
        },
      },
    },
    counts: {
      type: "object",
      additionalProperties: false,
      required: ["actionable", "informational", "praise", "question"],
      properties: {
        actionable: { type: "integer" },
        informational: { type: "integer" },
        praise: { type: "integer" },
        question: { type: "integer" },
      },
    },
  },
};

/**
 * Run the review-classifier wave: ONE fresh-context `perk.review-classifier` assignment with
 * the fixed code-owned task (the child fetches the feedback itself via `perk pr feedback --json` — nothing
 * model-relayed enters the task), `strict` completeness, no retry, module-default timeout.
 * Returns the wave's `ReportWaveResult` unchanged — the only projection lives in the door.
 */
export async function runReviewClassifierWave(
  wave: ReportWave,
  opts: { model?: string; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<ReportWaveResult> {
  return await wave.run(
    {
      flow: REVIEW_CLASSIFIER_FLOW,
      assignments: [
        {
          key: CLASSIFY_ASSIGNMENT_KEY,
          label: CLASSIFY_ASSIGNMENT_KEY,
          agent: "perk.review-classifier",
          phase: "address",
          task: "Fetch + classify the review feedback on this plan's PR.",
        },
      ],
      outputSchema: REVIEW_CLASSIFIER_REPORT_SCHEMA,
      completeness: "strict",
      ...(opts.model !== undefined ? { model: opts.model } : {}),
      ...(opts.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}),
    },
    { signal: opts.signal },
  );
}
