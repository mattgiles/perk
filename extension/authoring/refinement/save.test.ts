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
import {
  REFINEMENT_DRAFT_ARTIFACT,
  resumeRefinementDraft,
  reviseRefinementDraft,
} from "./draft.ts";
import { completeRefinementReview } from "./review.ts";
import {
  type RefinementBackend,
  type RefinementBackendSaveResult,
  refinementApprovalSave,
  reviewedPairOf,
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
  const stored = session.readArtifact(REFINEMENT_DRAFT_ARTIFACT);
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

test("seam: the reviewed pair fences the save — a draft or context rewritten after display stops with source-changed", async () => {
  const session = grounded(true);
  const before = resumeRefinementDraft(session);
  assert.ok(before.kind === "valid");
  const reviewed = reviewedPairOf(before.pair);
  const { backend, calls } = fakeBackend(SAVED);
  const { gate, exits } = fakeGate(true);

  // Identical bytes: the reviewed pair IS the current pair — the save proceeds.
  const same = await refinementApprovalSave({ session, backend, gate, reviewed });
  assert.equal(same.status, "saved");
  assert.equal(calls.length, 1);

  // The draft rewritten (through the sanctioned seam) during the wait: valid, but not the
  // reviewed draft — nothing invoked, the gate untouched.
  const replaced = grounded(true);
  const { gate: gate2, exits: exits2 } = fakeGate(true);
  const revised = reviseRefinementDraft({ markdown: "## Replacement\n" }, replaced);
  assert.equal(revised.status, "revised");
  const stale = await refinementApprovalSave({ session: replaced, backend, gate: gate2, reviewed });
  assert.deepEqual(stale, { status: "source-changed", changed: "draft" });

  // The context re-prepared (a new grounding pass) with the draft re-bound to it: the CONTEXT
  // arm wins even though the draft bytes also differ (the pass, not the prose, moved).
  const regrounded = grounded(true);
  regrounded.writeArtifact(
    REFINEMENT_CONTEXT_ARTIFACT,
    GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["w",'),
  );
  assert.equal(
    reviseRefinementDraft({ markdown: "## Refinement\n\nbody\n" }, regrounded).status,
    "revised",
  );
  const moved = await refinementApprovalSave({
    session: regrounded,
    backend,
    gate: gate2,
    reviewed,
  });
  assert.deepEqual(moved, { status: "source-changed", changed: "context" });
  assert.equal(calls.length, 1, "no backend invocation on a changed pair");
  assert.equal(exits.length, 1);
  assert.equal(exits2.length, 0, "no gate exit on a changed pair");

  // Without a captured pair (the human failsafe), the seam saves the current artifact.
  const { backend: backend2, calls: calls2 } = fakeBackend(SAVED);
  const manual = await refinementApprovalSave({
    session: replaced,
    backend: backend2,
    gate: gate2,
  });
  assert.equal(manual.status, "saved");
  assert.equal(calls2.length, 1);

  // Completion routes the stop to its approved-* twin: nothing saved, the verdict carried.
  const routed = await completeRefinementReview(
    { status: "approved", reviewId: "fp" },
    async () => ({ status: "source-changed" as const, changed: "draft" as const }),
  );
  assert.deepEqual(routed, { status: "approvedSourceChanged", changed: "draft", reviewId: "fp" });
});
