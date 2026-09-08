// The shared refinement save seam + the review completion routing over deterministic fakes:
// the EXACT draft bytes reach the backend with the explicit run id, the gate exits only after a
// verified save, and every non-save arm is a fail-closed stop with nothing invoked.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import type { ApprovalGate } from "../review/approvalGate.ts";
import { GOLDEN_CONTEXT, GOLDEN_RUN } from "./context.test.ts";
import {
  importRefinementContext,
  REFINEMENT_CONTEXT_ARTIFACT,
  validateContextTransfer,
} from "./context.ts";
import { REFINEMENT_DRAFT_ARTIFACT, reviseRefinementDraft } from "./draft.ts";
import { completeRefinementReview, reviewRefinement } from "./review.ts";
import {
  type RefinementBackend,
  type RefinementBackendSaveResult,
  refinementApprovalSave,
} from "./save.ts";

const SAVED: RefinementBackendSaveResult = {
  status: "saved",
  commentId: "cmt-10",
  carrierUrl: "https://linear.app/x/issue/ENG-23",
  carrierIdentifier: "ENG-23",
  objectiveId: "proj-1",
  objectiveRunId: "01OBJRUN",
  nodeId: "2.3",
  bodyDigest: "e".repeat(64),
  savedAt: "2026-09-07T12:30:00Z",
  authoredAt: "2026-09-07T12:00:00Z",
};
const FAILED: RefinementBackendSaveResult = {
  status: "failed",
  message: "stale",
  errorType: "stale_refinement",
  writeAttempted: false,
  commentIds: ["cmt-9"],
};

function fakeBackend(result: RefinementBackendSaveResult) {
  const calls: { runId: string; draftRaw: string }[] = [];
  const backend: RefinementBackend = {
    async save(req) {
      calls.push(req);
      return result;
    },
  };
  return { backend, calls };
}

function fakeGate(active: boolean) {
  let isActive = active;
  const exits: number[] = [];
  const gate: ApprovalGate = {
    isActive: () => isActive,
    exit() {
      exits.push(1);
      isActive = false;
    },
  };
  return { gate, exits };
}

function grounded(withDraft: boolean) {
  const session = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  const validated = validateContextTransfer(GOLDEN_CONTEXT, { runId: GOLDEN_RUN });
  assert.ok(validated.ok);
  importRefinementContext(session, validated.read);
  if (withDraft) reviseRefinementDraft({ markdown: "## Refinement\n\nbody\n" }, session);
  return session;
}

test("seam: saves the EXACT draft bytes with the run id; gate exits only after the verified save", async () => {
  const session = grounded(true);
  const stored = session.readArtifact(REFINEMENT_DRAFT_ARTIFACT, { provenance: "strict" });
  assert.ok(stored.status === "found");
  const { backend, calls } = fakeBackend(SAVED);
  const { gate, exits } = fakeGate(true);
  const outcome = await refinementApprovalSave({ session, backend, gate });
  assert.equal(outcome.status, "saved");
  assert.ok(outcome.status === "saved" && outcome.gateExited === true);
  assert.deepEqual(calls, [{ runId: GOLDEN_RUN, draftRaw: stored.content }]);
  assert.equal(exits.length, 1);
});

test("seam: a failed backend result leaves the gate ON and relays the worker diagnostics", async () => {
  const session = grounded(true);
  const { backend, calls } = fakeBackend(FAILED);
  const { gate, exits } = fakeGate(true);
  const outcome = await refinementApprovalSave({ session, backend, gate });
  assert.ok(outcome.status === "save-failed" && outcome.gateExited === false);
  assert.ok(outcome.status === "save-failed" && outcome.save.commentIds[0] === "cmt-9");
  assert.equal(calls.length, 1);
  assert.equal(exits.length, 0);
  assert.equal(gate.isActive(), true);
});

test("seam: no draft / no context / refused / mismatched drafts stop before any backend call", async () => {
  const { backend, calls } = fakeBackend(SAVED);
  const { gate, exits } = fakeGate(true);
  assert.deepEqual(await refinementApprovalSave({ session: grounded(false), backend, gate }), {
    status: "no-draft",
  });
  const bare = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  bare.writeArtifact(
    REFINEMENT_DRAFT_ARTIFACT,
    '{"schema_version":1,"run_id":"01AUTHRUN","context_digest":"sha256:' +
      "0".repeat(64) +
      '","markdown":"x"}\n',
    {
      provenance: "strict",
    },
  );
  assert.deepEqual(await refinementApprovalSave({ session: bare, backend, gate }), {
    status: "no-context",
  });
  const corrupt = grounded(true);
  corrupt.corruptContent(REFINEMENT_DRAFT_ARTIFACT);
  const refused = await refinementApprovalSave({ session: corrupt, backend, gate });
  assert.equal(refused.status, "refused-draft");
  const stale = grounded(true);
  stale.writeArtifact(
    REFINEMENT_CONTEXT_ARTIFACT,
    GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["w",'),
    {
      provenance: "strict",
    },
  );
  const mismatch = await refinementApprovalSave({ session: stale, backend, gate });
  assert.ok(mismatch.status === "refused-draft" && mismatch.problem.includes("re-prepared"));
  assert.equal(calls.length, 0, "no backend invocation on any stop");
  assert.equal(exits.length, 0, "no gate exit on any stop");
});

test("completion: Direct Edits approval is one revise round (no save); plain approval saves; others route", async () => {
  let saves = 0;
  const approvalSave = async () => {
    saves += 1;
    return {
      status: "saved" as const,
      save: SAVED,
      pair: {
        draft: { run_id: GOLDEN_RUN, context_digest: "sha256:x", markdown: "m" },
        draftRaw: "",
        context: { context: {} as never, raw: "", digest: "" },
      },
      gateExited: true,
    };
  };
  const direct = await completeRefinementReview(
    { status: "approvedDirectEdits", feedback: "# Direct Edits\n--- a\n+++ b", reviewId: "r1" },
    approvalSave,
  );
  assert.deepEqual(direct, {
    status: "directEditsRevise",
    feedback: "# Direct Edits\n--- a\n+++ b",
    reviewId: "r1",
  });
  assert.equal(saves, 0, "Direct Edits never saves");
  const approved = await completeRefinementReview(
    { status: "approved", feedback: "ok", reviewId: "r2" },
    approvalSave,
  );
  assert.ok(
    approved.status === "approvedSaved" && approved.feedback === "ok" && approved.reviewId === "r2",
  );
  assert.equal(saves, 1);
  assert.deepEqual(
    await completeRefinementReview({ status: "denied", feedback: "fix" }, approvalSave),
    {
      status: "denied",
      feedback: "fix",
    },
  );
  assert.deepEqual(await completeRefinementReview({ status: "dismissed" }, approvalSave), {
    status: "dismissed",
  });
  assert.deepEqual(await completeRefinementReview({ status: "aborted" }, approvalSave), {
    status: "aborted",
  });
  assert.deepEqual(
    await completeRefinementReview({ status: "unavailable", warning: "w" }, approvalSave),
    {
      status: "unavailable",
      warning: "w",
    },
  );
  assert.equal(saves, 1, "skipped / denied / dismissed / unavailable outcomes never save");
  // The approval-time arms of the seam route to their approved-* twins.
  const noDraft = await completeRefinementReview({ status: "approved" }, async () => ({
    status: "no-draft" as const,
  }));
  assert.deepEqual(noDraft, { status: "approvedNoDraft" });
  const noContext = await completeRefinementReview({ status: "approved" }, async () => ({
    status: "no-context" as const,
  }));
  assert.ok(noContext.status === "approvedRefusedDraft" && noContext.problem.includes("vanished"));
  const refused = await completeRefinementReview({ status: "approved" }, async () => ({
    status: "refused-draft" as const,
    problem: "bad",
  }));
  assert.deepEqual(refused, { status: "approvedRefusedDraft", problem: "bad" });
});

test("reviewRefinement: resumes the pair FIRST, reviews the RENDERED surface, routes; stops never touch the reviewer", async () => {
  const session = grounded(true);
  const { backend, calls } = fakeBackend(SAVED);
  const { gate } = fakeGate(true);
  const seen: string[] = [];
  const result = await reviewRefinement({
    session,
    backend,
    gate,
    reviewer: {
      async review(rendered) {
        seen.push(rendered);
        return { status: "approved", reviewId: "fp" };
      },
    },
  });
  assert.equal(result.status, "approvedSaved");
  assert.ok(
    seen[0]?.startsWith("# Refinement — objective proj-1 · node 2.3"),
    "the rendered pair, never raw JSON",
  );
  assert.equal(calls.length, 1);

  let reviewed = 0;
  const reviewer = {
    async review() {
      reviewed += 1;
      return { status: "approved" as const };
    },
  };
  assert.deepEqual(await reviewRefinement({ session: grounded(false), backend, gate, reviewer }), {
    status: "noDraft",
  });
  const corrupt = grounded(true);
  corrupt.corruptContent(REFINEMENT_DRAFT_ARTIFACT);
  assert.equal(
    (await reviewRefinement({ session: corrupt, backend, gate, reviewer })).status,
    "refusedDraft",
  );
  const aborted = new AbortController();
  aborted.abort();
  assert.deepEqual(
    await reviewRefinement({ session: grounded(true), backend, gate, reviewer }, aborted.signal),
    {
      status: "aborted",
    },
  );
  assert.equal(reviewed, 0, "no reviewer call on any stop");
});
