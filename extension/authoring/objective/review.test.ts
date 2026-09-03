// `reviewObjectiveDraft` over a scripted `ObjectiveDraftReviewer` + memory session: the
// resume→render→review→route pipeline, the abort checkpoint (a verdict resolving after the
// signal aborts produces NO effect), the approvedDirectEdits revise-round refusal (nothing
// saved), and the passthrough arms.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./draft.ts";
import {
  type ObjectiveDraftReviewer,
  type ObjectiveReviewOutcome,
  reviewObjectiveDraft,
} from "./review.ts";

const PROSE = "# Objective\n\nThe why.\n";

/** A save-outcome twin richer than the structural shape (proves the generic passthrough). */
type FakeSaveOutcome =
  | { status: "no-draft" }
  | { status: "refused-draft"; problem: string }
  | { status: "saved"; rendered: string; gateExited: boolean }
  | { status: "save-failed"; rendered: string; gateExited: false };

function sessionWithDraft(): ReturnType<typeof openMemoryWorkflowSession> {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const content = `${JSON.stringify(
    { schema_version: 1, title: "T", prose: PROSE, roadmap: [{ id: "1.1", description: "d" }] },
    null,
    2,
  )}\n`;
  assert.equal(session.writeArtifact(OBJECTIVE_DRAFT_ARTIFACT, content).status, "applied");
  return session;
}

/** A scripted reviewer recording the rendered bytes it was handed. */
function scriptedReviewer(outcome: ObjectiveReviewOutcome): {
  reviewer: ObjectiveDraftReviewer;
  seen: string[];
} {
  const seen: string[] = [];
  return {
    reviewer: {
      review: (rendered) => {
        seen.push(rendered);
        return Promise.resolve(outcome);
      },
    },
    seen,
  };
}

/** An approvalSave thunk with call observation. */
function fakeApprovalSave(outcome: FakeSaveOutcome): {
  approvalSave: () => Promise<FakeSaveOutcome>;
  calls: () => number;
} {
  let calls = 0;
  return {
    approvalSave: () => {
      calls += 1;
      return Promise.resolve(outcome);
    },
    calls: () => calls,
  };
}

test("review: no draft ⇒ noDraft — the reviewer is never consulted", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { reviewer, seen } = scriptedReviewer({ status: "approved" });
  const save = fakeApprovalSave({ status: "no-draft" });
  const result = await reviewObjectiveDraft({
    session,
    reviewer,
    approvalSave: save.approvalSave,
  });
  assert.deepEqual(result, { status: "noDraft" });
  assert.equal(seen.length, 0);
  assert.equal(save.calls(), 0);
});

test("review: refused draft ⇒ refusedDraft — the reviewer is never consulted", async () => {
  const session = sessionWithDraft();
  session.corruptContent(OBJECTIVE_DRAFT_ARTIFACT);
  const { reviewer, seen } = scriptedReviewer({ status: "approved" });
  const save = fakeApprovalSave({ status: "no-draft" });
  const quiet = console.error;
  console.error = () => {};
  try {
    const result = await reviewObjectiveDraft({
      session,
      reviewer,
      approvalSave: save.approvalSave,
    });
    assert.deepEqual(result, {
      status: "refusedDraft",
      problem: `session artifact ${OBJECTIVE_DRAFT_ARTIFACT} digest mismatch (rewound or modified)`,
    });
  } finally {
    console.error = quiet;
  }
  assert.equal(seen.length, 0, "nothing reviewed");
  assert.equal(save.calls(), 0, "nothing saved");
});

test("review: approved ⇒ the widened refused-draft save shape passes through verbatim", async () => {
  const session = sessionWithDraft();
  const { reviewer } = scriptedReviewer({ status: "approved", feedback: "f", reviewId: "r2" });
  const save = fakeApprovalSave({ status: "refused-draft", problem: "corrupted at save time" });
  const result = await reviewObjectiveDraft({
    session,
    reviewer,
    approvalSave: save.approvalSave,
  });
  assert.deepEqual(result, {
    status: "approvedSave",
    save: { status: "refused-draft", problem: "corrupted at save time" },
    feedback: "f",
    reviewId: "r2",
  });
});

test("review: the reviewed bytes are the RENDERED markdown, never the JSON artifact", async () => {
  const session = sessionWithDraft();
  const { reviewer, seen } = scriptedReviewer({ status: "dismissed" });
  await reviewObjectiveDraft({
    session,
    reviewer,
    approvalSave: fakeApprovalSave({ status: "no-draft" }).approvalSave,
  });
  assert.equal(seen.length, 1);
  assert.ok(seen[0]?.startsWith("# T\n\n**Delivery: incremental**"), "rendered review surface");
  assert.ok(!seen[0]?.includes("schema_version"), "raw JSON never reaches the reviewer");
});

test("review: approved ⇒ approvalSave; the richer save twin passes through verbatim", async () => {
  const session = sessionWithDraft();
  const { reviewer } = scriptedReviewer({
    status: "approved",
    feedback: "ship it",
    reviewId: "r1",
  });
  const save = fakeApprovalSave({
    status: "saved",
    rendered: "Saved objective #7",
    gateExited: true,
  });
  const result = await reviewObjectiveDraft({
    session,
    reviewer,
    approvalSave: save.approvalSave,
  });
  assert.deepEqual(result, {
    status: "approvedSave",
    save: { status: "saved", rendered: "Saved objective #7", gateExited: true },
    feedback: "ship it",
    reviewId: "r1",
  });
  assert.equal(save.calls(), 1);
});

test("review: approvedDirectEdits ⇒ the revise-round refusal — NOTHING saved", async () => {
  const session = sessionWithDraft();
  const { reviewer } = scriptedReviewer({
    status: "approvedDirectEdits",
    rawFeedback: "# Direct Edits\n\nchange X",
    reviewId: "r2",
  });
  const save = fakeApprovalSave({ status: "saved", rendered: "x", gateExited: true });
  const result = await reviewObjectiveDraft({
    session,
    reviewer,
    approvalSave: save.approvalSave,
  });
  assert.deepEqual(result, {
    status: "approvedDirectEdits",
    rawFeedback: "# Direct Edits\n\nchange X",
    reviewId: "r2",
  });
  assert.equal(save.calls(), 0, "the revise round never saves");
});

test("review: abort-after-approval — a verdict resolving after abort produces NO effect", async () => {
  const session = sessionWithDraft();
  const controller = new AbortController();
  const reviewer: ObjectiveDraftReviewer = {
    review: (_rendered, signal) => {
      // The reviewer resolves APPROVED, but the turn was interrupted while it ran.
      assert.equal(signal, controller.signal, "the signal threads through");
      controller.abort();
      return Promise.resolve({ status: "approved" });
    },
  };
  const save = fakeApprovalSave({ status: "saved", rendered: "x", gateExited: true });
  const result = await reviewObjectiveDraft(
    { session, reviewer, approvalSave: save.approvalSave },
    controller.signal,
  );
  assert.deepEqual(result, { status: "aborted" });
  assert.equal(save.calls(), 0, "approvalSave never called after abort");
});

test("review: an already-aborted signal short-circuits before the resume", async () => {
  const session = sessionWithDraft();
  const controller = new AbortController();
  controller.abort();
  const { reviewer, seen } = scriptedReviewer({ status: "approved" });
  const result = await reviewObjectiveDraft(
    { session, reviewer, approvalSave: fakeApprovalSave({ status: "no-draft" }).approvalSave },
    controller.signal,
  );
  assert.deepEqual(result, { status: "aborted" });
  assert.equal(seen.length, 0);
});

test("review: denied/dismissed/aborted/unavailable pass through verbatim", async () => {
  for (const [outcome, expected] of [
    [
      { status: "denied", feedback: "tighten scope", reviewId: "r3" },
      { status: "denied", feedback: "tighten scope", reviewId: "r3" },
    ],
    [{ status: "denied" }, { status: "denied" }],
    [{ status: "dismissed" }, { status: "dismissed" }],
    [{ status: "aborted" }, { status: "aborted" }],
    [
      { status: "unavailable", warning: "no review backend" },
      { status: "unavailable", warning: "no review backend" },
    ],
  ] as const) {
    const session = sessionWithDraft();
    const { reviewer } = scriptedReviewer(outcome as ObjectiveReviewOutcome);
    const save = fakeApprovalSave({ status: "no-draft" });
    const result = await reviewObjectiveDraft({
      session,
      reviewer,
      approvalSave: save.approvalSave,
    });
    assert.deepEqual(result, expected);
    assert.equal(save.calls(), 0);
  }
});
