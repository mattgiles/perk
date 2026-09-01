// Direct feature tests for the one-entry reviewGist op — memory session, scripted reviewer,
// fake backend, fake gate; no Pi.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { MemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { GIST_DRAFT_ARTIFACT, reviseGistDraft } from "./draft.ts";
import { type GistDraftReviewer, type GistReviewOutcome, reviewGist } from "./review.ts";
import type { GistBackend, GistGate } from "./save.ts";

const PROSE = "The intent and the why.\n";

function memorySession(runId = "RID"): MemoryWorkflowSession {
  const opened = openMemoryWorkflowSession({ runId });
  if (opened.status !== "opened") throw new Error("unreachable");
  return opened.session;
}

function draftedSession(): MemoryWorkflowSession {
  const session = memorySession();
  assert.equal(
    reviseGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" }, session).status,
    "revised",
  );
  return session;
}

/** A scripted reviewer recording the reviewed bytes. */
function scriptedReviewer(outcome: GistReviewOutcome): GistDraftReviewer & { reviewed: string[] } {
  const reviewer = {
    reviewed: [] as string[],
    async review(rendered: string) {
      reviewer.reviewed.push(rendered);
      return outcome;
    },
  };
  return reviewer;
}

function fakeBackend(fail = false): GistBackend & { calls: number } {
  const backend = {
    calls: 0,
    async save() {
      backend.calls += 1;
      return fail
        ? { status: "failed" as const, message: "gh exploded", errorType: "github_error" }
        : {
            status: "saved" as const,
            id: "7",
            url: "https://gh/o/r/issues/7",
            existed: false,
            scope: "plan",
          };
    },
  };
  return backend;
}

function fakeGate(active = true): GistGate & { exits: number } {
  const gate = {
    exits: 0,
    isActive: () => active,
    exit() {
      gate.exits += 1;
    },
  };
  return gate;
}

const APPROVED: GistReviewOutcome = {
  status: "approved",
  reviewId: "rev-a",
};

test("no draft → noDraft; the reviewer is never invoked", async () => {
  const reviewer = scriptedReviewer(APPROVED);
  const result = await reviewGist({
    session: memorySession(),
    reviewer,
    backend: fakeBackend(),
    gate: fakeGate(),
  });
  assert.deepEqual(result, { status: "noDraft" });
  assert.equal(reviewer.reviewed.length, 0);
});

test("the reviewer receives the RENDERED markdown, never raw JSON", async () => {
  const reviewer = scriptedReviewer({
    status: "denied",
    feedback: "needs work",
    reviewId: "rev-d",
  });
  await reviewGist({
    session: draftedSession(),
    reviewer,
    backend: fakeBackend(),
    gate: fakeGate(),
  });
  assert.equal(reviewer.reviewed.length, 1);
  const rendered = String(reviewer.reviewed[0]);
  assert.match(rendered, /# Faster reviews/);
  assert.match(rendered, /Scope: plan/);
  assert.match(rendered, /The intent and the why\./);
  assert.doesNotMatch(rendered, /schema_version/);
});

test("approved → saved: the artifact is re-read at save time; gate released only on saved", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const result = await reviewGist({
    session,
    reviewer: scriptedReviewer({ ...APPROVED, feedback: "ship it" }),
    backend,
    gate,
  });
  assert.equal(result.status, "approvedSaved");
  assert.ok(result.status === "approvedSaved");
  assert.equal(result.save.gateExited, true);
  assert.equal(result.save.save.id, "7");
  assert.equal(result.feedback, "ship it");
  assert.equal(result.reviewId, "rev-a");
  assert.equal(backend.calls, 1);
  assert.equal(gate.exits, 1);
});

test("approved → save failed: the gate stays on", async () => {
  const gate = fakeGate(true);
  const result = await reviewGist({
    session: draftedSession(),
    reviewer: scriptedReviewer(APPROVED),
    backend: fakeBackend(true),
    gate,
  });
  assert.equal(result.status, "approvedSaveFailed");
  assert.ok(result.status === "approvedSaveFailed");
  assert.equal(result.save.gateExited, false);
  assert.equal(result.save.save.message, "gh exploded");
  assert.equal(gate.exits, 0, "the gate stays on");
});

test("approved + direct edits → the revise round: NO save, gate untouched", async () => {
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const result = await reviewGist({
    session: draftedSession(),
    reviewer: scriptedReviewer({
      status: "approvedDirectEdits",
      feedback: "# Direct Edits\n\n…the diff…",
      reviewId: "rev-de",
    }),
    backend,
    gate,
  });
  assert.deepEqual(result, {
    status: "directEditsRevise",
    feedback: "# Direct Edits\n\n…the diff…",
    reviewId: "rev-de",
  });
  assert.equal(backend.calls, 0, "nothing saved");
  assert.equal(gate.exits, 0, "the gate stays untouched");
});

test("approved but the draft vanished between reads → approvedNoDraft (defensive)", async () => {
  const session = draftedSession();
  const backend = fakeBackend();
  const reviewer: GistDraftReviewer = {
    async review() {
      // Simulate the draft vanishing between the review read and the save-time re-read.
      session.dropContent(GIST_DRAFT_ARTIFACT);
      return APPROVED;
    },
  };
  const quiet = console.error;
  console.error = () => {};
  try {
    const result = await reviewGist({ session, reviewer, backend, gate: fakeGate() });
    assert.equal(result.status, "approvedNoDraft");
  } finally {
    console.error = quiet;
  }
  assert.equal(backend.calls, 0);
});

test("denied / dismissed / aborted / unavailable pass through typed", async () => {
  const denied = await reviewGist({
    session: draftedSession(),
    reviewer: scriptedReviewer({
      status: "denied",
      feedback: "say what bounds it",
      reviewId: "rev-d",
    }),
    backend: fakeBackend(),
    gate: fakeGate(),
  });
  assert.deepEqual(denied, { status: "denied", feedback: "say what bounds it", reviewId: "rev-d" });

  for (const [outcome, expected] of [
    [{ status: "dismissed" }, { status: "dismissed" }],
    [{ status: "aborted" }, { status: "aborted" }],
    [
      { status: "unavailable", warning: "no bus" },
      { status: "unavailable", warning: "no bus" },
    ],
  ] as const) {
    const result = await reviewGist({
      session: draftedSession(),
      reviewer: scriptedReviewer(outcome as GistReviewOutcome),
      backend: fakeBackend(),
      gate: fakeGate(),
    });
    assert.deepEqual(result, expected);
  }
});
