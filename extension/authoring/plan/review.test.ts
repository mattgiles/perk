// Direct feature tests for reviewPlanDraft — memory session, scripted PlanDraftReviewer,
// deterministic fake backend + gate; no Pi, no browser, no editor. Pins the routing law
// (approved/direct-edits/unparseable/implement-here/refusal/passthrough), the abort
// checkpoints, and the artifact-wins resolution.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlanRef } from "../../substrate/cache.ts";
import {
  type MemoryWorkflowSession,
  openMemoryWorkflowSession,
} from "../../testing/memoryWorkflowSession.ts";
import { resumePlanDraft, revisePlanDraft } from "./draft.ts";
import {
  applyReviewerEdits,
  type PlanDraftReviewer,
  type PlanReviewOutcome,
  type ReviewPlanDraftDeps,
  reviewPlanDraft,
} from "./review.ts";
import type { PlanBackend, PlanBackendSaveResult, PlanGate } from "./save.ts";

const PLAN = "# A plan\n\n## Steps\n\n1. Do the thing.\n";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
  base: null,
};

/** A unified diff editing PLAN's first line (applies cleanly via the strict ladder). */
const GOOD_DIFF = "@@ -1,1 +1,1 @@\n-# A plan\n+# A plan (edited)\n";
const EDITED_PLAN = PLAN.replace("# A plan", "# A plan (edited)");

function fakeBackend(result?: PlanBackendSaveResult): PlanBackend & {
  requests: Parameters<PlanBackend["save"]>[0][];
} {
  const backend = {
    requests: [] as Parameters<PlanBackend["save"]>[0][],
    async save(req: Parameters<PlanBackend["save"]>[0]) {
      backend.requests.push(req);
      return (
        result ?? {
          status: "saved" as const,
          ref: REF,
          existed: false,
          updated: false,
          cached: true,
          nodeLink: null,
        }
      );
    },
  };
  return backend;
}

function fakeGate(active: boolean): PlanGate & { exits: number } {
  const gate = {
    exits: 0,
    isActive: () => active,
    exit() {
      gate.exits += 1;
    },
  };
  return gate;
}

/** A scripted reviewer: returns the canned result; `seen` records the reviewed bytes. */
function scriptedReviewer(
  outcome: PlanReviewOutcome,
  opts: { plan?: string; edited?: boolean; onReview?: () => void } = {},
): PlanDraftReviewer & { seen: string[] } {
  const reviewer = {
    seen: [] as string[],
    async review(plan: string) {
      reviewer.seen.push(plan);
      opts.onReview?.();
      return { outcome, plan: opts.plan ?? plan, edited: opts.edited ?? false };
    },
  };
  return reviewer;
}

function depsFor(
  session: MemoryWorkflowSession,
  reviewer: PlanDraftReviewer,
  opts: {
    backend?: PlanBackend;
    gate?: PlanGate;
    explicit?: string;
    allowImplementHere?: boolean;
  } = {},
): ReviewPlanDraftDeps {
  return {
    session,
    reviewer,
    backend: opts.backend ?? fakeBackend(),
    gate: opts.gate ?? fakeGate(true),
    async generateTitle() {
      return null;
    },
    capturePlanningPointer() {},
    ...(opts.explicit !== undefined ? { explicit: opts.explicit } : {}),
    allowImplementHere: opts.allowImplementHere ?? true,
  };
}

function draftedSession(plan = PLAN): MemoryWorkflowSession {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const revised = revisePlanDraft({ plan }, session);
  assert.ok(revised.status === "revised" || revised.status === "unchanged");
  return session;
}

// -------------------------------------------------------------------------------- resolution

test("reviewPlanDraft: nothing resolvable → noPlan; the reviewer never runs", async () => {
  const reviewer = scriptedReviewer({ status: "approved" });
  const result = await reviewPlanDraft(
    depsFor(openMemoryWorkflowSession({ runId: "RID" }), reviewer),
  );
  assert.deepEqual(result, { status: "noPlan" });
  assert.equal(reviewer.seen.length, 0);
});

test("reviewPlanDraft: the artifact wins over the explicit param; paramMismatch rides the flags", async () => {
  const session = draftedSession();
  const reviewer = scriptedReviewer({ status: "approved" });
  const backend = fakeBackend();
  const result = await reviewPlanDraft(
    depsFor(session, reviewer, { backend, explicit: "# A different param plan" }),
  );
  assert.deepEqual(reviewer.seen, [PLAN], "the validated artifact bytes were reviewed");
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.paramMismatch, true);
  assert.equal(backend.requests[0]?.plan, PLAN.trim());
});

// ---------------------------------------------------------------------------------- approved

test("reviewPlanDraft: approved → planApprovalSave with the reviewed bytes; edited rides", async () => {
  const session = draftedSession();
  // The first-party reviewer writes edits back INSIDE the reviewer; model that here.
  const reviewer = scriptedReviewer(
    { status: "approved", feedback: "note the edge case", reviewId: "rev-a" },
    {
      plan: EDITED_PLAN,
      edited: true,
      onReview: () => {
        assert.equal(revisePlanDraft({ plan: EDITED_PLAN }, session).status, "revised");
      },
    },
  );
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const result = await reviewPlanDraft(depsFor(session, reviewer, { backend, gate }));
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.save.gateExited, true);
  assert.equal(gate.exits, 1);
  assert.equal(result.edited, true);
  assert.equal(result.feedback, "note the edge case");
  assert.equal(result.reviewId, "rev-a");
  assert.equal(result.directEditsFailed, false);
  // The written-back artifact wins resolution inside the approval save.
  assert.equal(backend.requests[0]?.plan, EDITED_PLAN.trim());
});

test("reviewPlanDraft: approved but the backend fails → approvedSaveFailed; gate stays ON", async () => {
  const session = draftedSession();
  const gate = fakeGate(true);
  const result = await reviewPlanDraft(
    depsFor(session, scriptedReviewer({ status: "approved" }), {
      backend: fakeBackend({ status: "failed", message: "gh exploded", errorType: "github_error" }),
      gate,
    }),
  );
  assert.equal(result.status, "approvedSaveFailed");
  if (result.status !== "approvedSaveFailed") return;
  assert.equal(result.save.gateExited, false);
  assert.equal(gate.exits, 0);
  assert.equal(result.save.result.message, "gh exploded");
});

// ------------------------------------------------------------------------------- direct edits

test("reviewPlanDraft: approvedDirectEdits applies the diff, saves the EDITED bytes, writes back", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const result = await reviewPlanDraft(
    depsFor(
      session,
      scriptedReviewer({
        status: "approvedDirectEdits",
        diff: GOOD_DIFF,
        remainder: "also consider caching",
        rawFeedback: "# Direct Edits\n…full section…",
        reviewId: "rev-de",
      }),
      { backend },
    ),
  );
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.edited, true);
  assert.equal(result.directEditsFailed, false);
  assert.equal(result.feedback, "also consider caching", "remainder-only feedback");
  assert.equal(backend.requests[0]?.plan, EDITED_PLAN.trim(), "the PATCHED bytes were saved");
  assert.equal(resumePlanDraft(session), EDITED_PLAN, "the draft artifact carries the edits");
});

test("reviewPlanDraft: an unapplyable diff falls open — verbatim save + directEditsFailed", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const result = await reviewPlanDraft(
    depsFor(
      session,
      scriptedReviewer({
        status: "approvedDirectEdits",
        diff: "@@ -99,1 +99,1 @@\n-nowhere\n+nothing\n",
        rawFeedback: "# Direct Edits\nfull original feedback",
        reviewId: "rev-df",
      }),
      { backend },
    ),
  );
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.directEditsFailed, true);
  assert.equal(result.edited, false);
  assert.equal(result.feedback, "# Direct Edits\nfull original feedback", "FULL feedback kept");
  assert.equal(backend.requests[0]?.plan, PLAN.trim(), "the ORIGINAL bytes were saved verbatim");
  assert.equal(resumePlanDraft(session), PLAN, "the draft is untouched");
});

test("reviewPlanDraft: a failed ladder write-back falls open the same way", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  session.failNextWrite(); // the ladder's write-back refuses; the verbatim save still runs
  const result = await reviewPlanDraft(
    depsFor(
      session,
      scriptedReviewer({
        status: "approvedDirectEdits",
        diff: GOOD_DIFF,
        rawFeedback: "raw",
      }),
      { backend },
    ),
  );
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.directEditsFailed, true);
  assert.equal(backend.requests[0]?.plan, PLAN.trim());
});

test("reviewPlanDraft: approvedEditsUnparseable saves verbatim with the FULL raw feedback", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const result = await reviewPlanDraft(
    depsFor(
      session,
      scriptedReviewer({
        status: "approvedEditsUnparseable",
        rawFeedback: "# Direct Edits\n\nthe fence never arrived",
        reviewId: "rev-du",
      }),
      { backend },
    ),
  );
  assert.equal(result.status, "approvedSaved");
  if (result.status !== "approvedSaved") return;
  assert.equal(result.directEditsFailed, true);
  assert.equal(result.feedback, "# Direct Edits\n\nthe fence never arrived");
  assert.equal(backend.requests[0]?.plan, PLAN.trim());
});

// ---------------------------------------------------------------------------- implement-here

test("reviewPlanDraft: implementHere exits the gate WITHOUT saving; the draft survives", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const result = await reviewPlanDraft(
    depsFor(
      session,
      scriptedReviewer({ status: "implementHere", reviewId: "rev-ih" }, { edited: false }),
      { backend, gate },
    ),
  );
  assert.deepEqual(result, {
    status: "implementHere",
    reviewId: "rev-ih",
    gateExited: true,
    plan: PLAN,
    edited: false,
  });
  assert.equal(gate.exits, 1);
  assert.equal(backend.requests.length, 0, "nothing saved");
  assert.equal(resumePlanDraft(session), PLAN, "the draft artifact is left intact");
});

test("reviewPlanDraft: implementHere with the gate already off → gateExited false", async () => {
  const gate = fakeGate(false);
  const result = await reviewPlanDraft(
    depsFor(draftedSession(), scriptedReviewer({ status: "implementHere", reviewId: "r" }), {
      gate,
    }),
  );
  assert.equal(result.status === "implementHere" ? result.gateExited : null, false);
  assert.equal(gate.exits, 0);
});

test("reviewPlanDraft: implementHere under allowImplementHere: false REFUSES (gate untouched)", async () => {
  // The feature-owned gate-safety backstop: an objective-node planning session must save its
  // node-linked plan — even a scripted reviewer returning the verdict cannot exit the gate.
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const result = await reviewPlanDraft(
    depsFor(draftedSession(), scriptedReviewer({ status: "implementHere", reviewId: "rev-x" }), {
      backend,
      gate,
      allowImplementHere: false,
    }),
  );
  assert.deepEqual(result, { status: "implementHereRefused" });
  assert.equal(gate.exits, 0);
  assert.equal(backend.requests.length, 0);
});

// -------------------------------------------------------------------------------------- abort

test("reviewPlanDraft: an already-aborted signal short-circuits before resolution", async () => {
  const controller = new AbortController();
  controller.abort();
  const reviewer = scriptedReviewer({ status: "approved" });
  const result = await reviewPlanDraft(depsFor(draftedSession(), reviewer), controller.signal);
  assert.deepEqual(result, { status: "aborted" });
  assert.equal(reviewer.seen.length, 0);
});

test("reviewPlanDraft: an abort DURING review outranks the verdict — no save, gate untouched", async () => {
  const controller = new AbortController();
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const reviewer = scriptedReviewer({ status: "approved" }, { onReview: () => controller.abort() });
  const result = await reviewPlanDraft(
    depsFor(draftedSession(), reviewer, { backend, gate }),
    controller.signal,
  );
  assert.deepEqual(result, { status: "aborted" });
  assert.equal(backend.requests.length, 0, "the backend was never called");
  assert.equal(gate.exits, 0);
});

// -------------------------------------------------------------------------------- passthrough

test("reviewPlanDraft: denied/dismissed/aborted/unavailable pass through untouched", async () => {
  const denied = await reviewPlanDraft(
    depsFor(
      draftedSession(),
      scriptedReviewer({ status: "denied", feedback: "needs work", reviewId: "rev-d" }),
    ),
  );
  assert.deepEqual(denied, { status: "denied", feedback: "needs work", reviewId: "rev-d" });

  const dismissed = await reviewPlanDraft(
    depsFor(draftedSession(), scriptedReviewer({ status: "dismissed" })),
  );
  assert.deepEqual(dismissed, { status: "dismissed" });

  const aborted = await reviewPlanDraft(
    depsFor(draftedSession(), scriptedReviewer({ status: "aborted" })),
  );
  assert.deepEqual(aborted, { status: "aborted" });

  const unavailable = await reviewPlanDraft(
    depsFor(draftedSession(), scriptedReviewer({ status: "unavailable", warning: "no bus" })),
  );
  assert.deepEqual(unavailable, { status: "unavailable", warning: "no bus" });
});

// -------------------------------------------------------------------------- applyReviewerEdits

test("applyReviewerEdits: applies + writes back; every rung fails open", () => {
  const session = draftedSession();
  const applied = applyReviewerEdits(session, PLAN, { diff: GOOD_DIFF });
  assert.deepEqual(applied, { status: "applied", plan: EDITED_PLAN });
  assert.equal(resumePlanDraft(session), EDITED_PLAN);

  assert.deepEqual(applyReviewerEdits(session, PLAN, { diff: "not a diff" }), {
    status: "failed",
  });

  const refusing = draftedSession();
  refusing.failNextWrite();
  assert.deepEqual(applyReviewerEdits(refusing, PLAN, { diff: GOOD_DIFF }), { status: "failed" });
  assert.equal(resumePlanDraft(refusing), PLAN, "the draft is untouched on a refused write-back");
});

test("applyReviewerEdits: an unchanged write-back still counts as applied", () => {
  // The reviewer's diff can regenerate the draft's exact current bytes (e.g. a re-review after
  // the same edits were applied) — `unchanged` is success, not a ladder failure.
  const session = draftedSession(EDITED_PLAN);
  const applied = applyReviewerEdits(session, PLAN, { diff: GOOD_DIFF });
  assert.deepEqual(applied, { status: "applied", plan: EDITED_PLAN });
});
