import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { SaveDestination } from "../../session/saveDestination.ts";
import {
  digestSessionData,
  REFINEMENT_CONTEXT_ARTIFACT,
  type WorkflowSession,
} from "../../session/workflowSession.ts";
import {
  checkDraftReviewDecision,
  createDraftReviewSlot,
  DESTINATION_UNAVAILABLE_DETAIL,
  DRAFT_CHANGED_NOTE,
  type DraftReviewPorts,
  type DraftReviewSlot,
  destinationChangedResult,
  injectDraftReviewResult,
  MANUAL_SAVE_COMMANDS,
  type OpenDraftReview,
  openRefusedResult,
  REVIEW_SUBJECT_ARTIFACTS,
  recordSaveOutcome,
  SUPERSEDED_DECISION_WARNING,
  saveUnconfirmedResult,
  staleApprovalResult,
  withDraftChangedNote,
} from "./draftReview.ts";

// ----------------------------------------------------------------------------------- scaffolding

type Stage = "plan" | "objective-author" | "gist-author" | "objective-refine";

/** A mutable stand-in for the branch: what `draftReviewContext()` / `readArtifact` observe. */
interface World {
  runId: string | null;
  stage: Stage;
  nodeClaim: { objective: string; node: string } | null;
  artifacts: Map<string, string>;
  destination: SaveDestination | null;
  destinationCalls: number;
}

function world(over: Partial<World> = {}): World {
  return {
    runId: "RID",
    stage: "plan",
    nodeClaim: null,
    artifacts: new Map(),
    destination: { issues: "i1", remotes: "r1", node_claim: "n1" },
    destinationCalls: 0,
    ...over,
  };
}

function stubSession(w: World): WorkflowSession {
  const subject =
    w.stage === "objective-author"
      ? "objective"
      : w.stage === "gist-author"
        ? "gist"
        : w.stage === "objective-refine"
          ? "refinement"
          : "plan";
  return {
    runId: w.runId,
    draftReviewContext() {
      if (w.runId === null) return { ok: false, reason: "no-identity" };
      return {
        ok: true,
        runId: w.runId,
        subject,
        warmNodeClaim: subject === "plan" ? w.nodeClaim : null,
      };
    },
    readArtifact(name: string) {
      const content = w.artifacts.get(name);
      return content === undefined ? { status: "absent" } : { status: "found", content };
    },
  } as unknown as WorkflowSession;
}

function ports(w: World): DraftReviewPorts {
  return {
    session: () => stubSession(w),
    destination: () => {
      w.destinationCalls++;
      return w.destination;
    },
  };
}

function fakePi(): ExtensionAPI & { sent: { text: string; options?: unknown }[] } {
  const sent: { text: string; options?: unknown }[] = [];
  return {
    sent,
    sendUserMessage(text: string, options?: unknown) {
      sent.push({ text, options });
    },
  } as unknown as ExtensionAPI & { sent: { text: string; options?: unknown }[] };
}

function ctxFor(idle = true): ExtensionContext {
  return { cwd: "/repo", isIdle: () => idle } as unknown as ExtensionContext;
}

function slotFor(w: World): DraftReviewSlot {
  return createDraftReviewSlot(fakePi(), ports(w));
}

function opened(
  slot: DraftReviewSlot,
  w: World,
  snapshot: Partial<Parameters<DraftReviewSlot["open"]>[1]> = {},
): OpenDraftReview {
  const r = slot.open(ctxFor(), {
    subject: "plan",
    source: "artifact",
    raw: "# Plan",
    markdown: "# Plan",
    ...snapshot,
  });
  assert.ok(r.ok, `open refused: ${r.ok ? "" : r.detail}`);
  if (
    !w.artifacts.has(REVIEW_SUBJECT_ARTIFACTS[r.review.subject]) &&
    r.review.source === "artifact"
  )
    w.artifacts.set(REVIEW_SUBJECT_ARTIFACTS[r.review.subject], r.review.raw);
  return r.review;
}

// ---------------------------------------------------------------------------------------- the slot

test("open: sets the current review, digests the RAW bytes, captures the destination at open", () => {
  const w = world({ nodeClaim: { objective: "7", node: "1.2" } });
  const slot = slotFor(w);
  const review = opened(slot, w, { raw: '{"a":1}', markdown: "rendered" });
  assert.equal(review.isCurrent(), true);
  assert.equal(review.runId, "RID");
  assert.equal(review.reviewedDigest, digestSessionData('{"a":1}'));
  assert.notEqual(review.reviewedDigest, digestSessionData("rendered"));
  assert.equal(review.contextDigest, null);
  assert.deepEqual(review.destination, w.destination);
  assert.equal(w.destinationCalls, 1);
});

test("open: a second open from ANY surface supersedes the first; supersede() clears", () => {
  const w = world();
  const slot = slotFor(w);
  const first = opened(slot, w, { source: "artifact" });
  const second = opened(slot, w, { source: "editor" });
  assert.equal(first.isCurrent(), false);
  assert.equal(second.isCurrent(), true);
  const third = opened(slot, w, { source: "parameter" });
  assert.equal(second.isCurrent(), false);
  assert.equal(third.isCurrent(), true);
  slot.supersede();
  assert.equal(third.isCurrent(), false);
});

test("open: refusals — no identity, subject mismatch, unverifiable destination — set no current review", () => {
  const w = world({ runId: null });
  const slot = slotFor(w);
  const noId = slot.open(ctxFor(), {
    subject: "plan",
    source: "artifact",
    raw: "x",
    markdown: "x",
  });
  assert.deepEqual(noId.ok ? null : noId.reason, "no-identity");

  const w2 = world({ stage: "objective-author" });
  const mismatch = slotFor(w2).open(ctxFor(), {
    subject: "plan",
    source: "artifact",
    raw: "x",
    markdown: "x",
  });
  assert.equal(mismatch.ok ? null : mismatch.reason, "subject-mismatch");
  assert.match(mismatch.ok ? "" : mismatch.detail, /objective session, not a plan session/);

  const w3 = world({ destination: null });
  const unverifiable = slotFor(w3).open(ctxFor(), {
    subject: "plan",
    source: "artifact",
    raw: "x",
    markdown: "x",
  });
  assert.equal(unverifiable.ok ? null : unverifiable.reason, "destination-unavailable");
  assert.equal(unverifiable.ok ? "" : unverifiable.detail, DESTINATION_UNAVAILABLE_DETAIL);

  // A refused open never touches an existing current review.
  const w4 = world();
  const slot4 = slotFor(w4);
  const live = opened(slot4, w4);
  w4.destination = null;
  assert.equal(
    slot4.open(ctxFor(), { subject: "plan", source: "artifact", raw: "y", markdown: "y" }).ok,
    false,
  );
  assert.equal(live.isCurrent(), true);
});

test("open: every subject maps to its stage-derived subject", () => {
  for (const [stage, subject] of [
    ["plan", "plan"],
    ["objective-author", "objective"],
    ["gist-author", "gist"],
    ["objective-refine", "refinement"],
  ] as const) {
    const w = world({ stage });
    const r = slotFor(w).open(ctxFor(), { subject, source: "artifact", raw: "x", markdown: "x" });
    assert.ok(r.ok, `${stage} opens as ${subject}`);
  }
});

test("markUnconfirmed latches first-writer-wins and nothing clears it", () => {
  const slot = slotFor(world());
  assert.equal(slot.unconfirmed(), null);
  slot.markUnconfirmed("plan", "gh exploded");
  slot.markUnconfirmed("objective", "later");
  assert.deepEqual(slot.unconfirmed(), { subject: "plan", detail: "gh exploded" });
  slot.supersede();
  assert.deepEqual(slot.unconfirmed(), { subject: "plan", detail: "gh exploded" });
});

test("recordSaveOutcome: only a non-confirmed outcome latches; blank details get the default", () => {
  const slot = slotFor(world());
  recordSaveOutcome(slot, "gist", { confirmed: true });
  assert.equal(slot.unconfirmed(), null);
  recordSaveOutcome(slot, "gist", { confirmed: false, detail: "  " });
  assert.deepEqual(slot.unconfirmed(), {
    subject: "gist",
    detail: "backend call did not return a receipt",
  });
});

// ------------------------------------------------------------------------------------ the ladder

test("ladder: save + unchanged artifact + same destination → proceed", () => {
  const w = world();
  const slot = slotFor(w);
  const review = opened(slot, w);
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
    kind: "proceed",
    draftChanged: false,
  });
  assert.equal(w.destinationCalls, 2, "the destination is re-captured at approve");
});

test("ladder: save + changed artifact → stale-approval; revision + changed → proceed{draftChanged:true}", () => {
  const w = world();
  const slot = slotFor(w);
  const review = opened(slot, w);
  w.artifacts.set(REVIEW_SUBJECT_ARTIFACTS.plan, "# Plan v2");
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
    kind: "stale-approval",
    reviewedDigest: digestSessionData("# Plan"),
  });
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "revision"), {
    kind: "proceed",
    draftChanged: true,
  });
  // A vanished artifact counts as changed too.
  w.artifacts.delete(REVIEW_SUBJECT_ARTIFACTS.plan);
  assert.equal(checkDraftReviewDecision(slot, ctxFor(), review, "save").kind, "stale-approval");
});

test("ladder: parameter and editor sources skip the byte compare (destination still fenced)", () => {
  for (const source of ["parameter", "editor"] as const) {
    const w = world();
    const slot = slotFor(w);
    const review = opened(slot, w, { source });
    w.artifacts.set(REVIEW_SUBJECT_ARTIFACTS.plan, "# Something else entirely");
    assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
      kind: "proceed",
      draftChanged: false,
    });
    w.destination = { issues: "i1", remotes: "r2", node_claim: "n1" };
    assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
      kind: "destination-changed",
      changed: ["remotes"],
    });
  }
});

test("ladder: refinement context drift → stale-approval even with unchanged draft bytes", () => {
  const w = world({ stage: "objective-refine" });
  w.artifacts.set(REFINEMENT_CONTEXT_ARTIFACT, '{"ctx":1}');
  const slot = slotFor(w);
  const review = opened(slot, w, {
    subject: "refinement",
    raw: '{"draft":1}',
    markdown: "rendered",
    contextDigest: digestSessionData('{"ctx":1}'),
  });
  assert.equal(review.contextDigest, digestSessionData('{"ctx":1}'));
  assert.equal(checkDraftReviewDecision(slot, ctxFor(), review, "save").kind, "proceed");
  w.artifacts.set(REFINEMENT_CONTEXT_ARTIFACT, '{"ctx":2}');
  assert.equal(checkDraftReviewDecision(slot, ctxFor(), review, "save").kind, "stale-approval");
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "revision"), {
    kind: "proceed",
    draftChanged: true,
  });
});

test("ladder: destination drift names the components; a null capture is unverifiable; revision never checks", () => {
  const w = world();
  const slot = slotFor(w);
  const review = opened(slot, w);
  w.destination = { issues: "i2", remotes: "r1", node_claim: "n2" };
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
    kind: "destination-changed",
    changed: ["issues", "node_claim"],
  });
  w.destination = null;
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
    kind: "destination-changed",
    changed: "unverifiable",
  });
  const calls = w.destinationCalls;
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "revision"), {
    kind: "proceed",
    draftChanged: false,
  });
  assert.equal(w.destinationCalls, calls, "a revision never re-captures the destination");
});

test("ladder: the latch fires before the byte compare (save only); revision ignores it", () => {
  const w = world();
  const slot = slotFor(w);
  const review = opened(slot, w);
  slot.markUnconfirmed("objective", "gh exploded");
  w.artifacts.set(REVIEW_SUBJECT_ARTIFACTS.plan, "# moved");
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "save"), {
    kind: "save-unconfirmed",
    subject: "objective",
    detail: "gh exploded",
  });
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), review, "revision"), {
    kind: "proceed",
    draftChanged: true,
  });
});

test("ladder: a superseded token, a run-id drift, or a subject drift → superseded (before everything else)", () => {
  const w = world();
  const slot = slotFor(w);
  const first = opened(slot, w);
  opened(slot, w, { source: "editor" });
  slot.markUnconfirmed("plan", "x");
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), first, "save"), { kind: "superseded" });
  assert.deepEqual(checkDraftReviewDecision(slot, ctxFor(), first, "revision"), {
    kind: "superseded",
  });

  const w2 = world();
  const slot2 = slotFor(w2);
  const review = opened(slot2, w2);
  w2.runId = "OTHER";
  assert.deepEqual(checkDraftReviewDecision(slot2, ctxFor(), review, "revision"), {
    kind: "superseded",
  });
  w2.runId = "RID";
  w2.stage = "gist-author";
  assert.deepEqual(checkDraftReviewDecision(slot2, ctxFor(), review, "revision"), {
    kind: "superseded",
  });
  w2.runId = null;
  assert.deepEqual(checkDraftReviewDecision(slot2, ctxFor(), review, "revision"), {
    kind: "superseded",
  });
});

// ------------------------------------------------------------------------------- the fixed texts

test("staleApprovalResult: text + details pinned; feedback rides the untrusted delimiter", () => {
  const r = staleApprovalResult("objective", "sha256:abc", "ship it");
  const text = r.content[0]?.text ?? "";
  assert.match(
    text,
    /^The human APPROVED the objective, but the working draft changed after the review opened \(reviewed digest sha256:abc\)\. Nothing was saved and the session's mode is unchanged\. Call plan_review to review the current draft\./,
  );
  assert.match(text, /<untrusted_reviewer_feedback>\nship it\n<\/untrusted_reviewer_feedback>/);
  assert.deepEqual(r.details, {
    ok: true,
    status: "stale-approval",
    subject: "objective",
    reviewed_digest: "sha256:abc",
  });
  assert.equal(r.terminate, undefined);
  assert.doesNotMatch(
    staleApprovalResult("plan", "d").content[0]?.text ?? "",
    /untrusted_reviewer_feedback/,
  );
});

test("destinationChangedResult: names components (never values) or 'could not be verified'", () => {
  const named = destinationChangedResult("plan", ["remotes", "node_claim"]);
  assert.match(
    named.content[0]?.text ?? "",
    /^The human APPROVED the plan, but the save destination changed while the review was open \(changed: remotes, node_claim\)\. Nothing was saved; the working draft is unchanged and still editable\. Continue editing if needed, then call plan_review to open a fresh review against the current destination — a fresh human approval is required before any save\./,
  );
  assert.deepEqual(named.details, {
    ok: true,
    status: "destination-changed",
    subject: "plan",
    changed: ["remotes", "node_claim"],
  });
  const unverifiable = destinationChangedResult("gist", "unverifiable", "fb");
  assert.match(unverifiable.content[0]?.text ?? "", /changed: could not be verified\)/);
  assert.match(unverifiable.content[0]?.text ?? "", /<untrusted_reviewer_feedback>\nfb\n/);
  assert.equal(unverifiable.details.changed, "unverifiable");
});

test("saveUnconfirmedResult: names the run id, the Linear caveat and the subject's manual save command", () => {
  for (const subject of ["plan", "objective", "gist", "refinement"] as const) {
    const r = saveUnconfirmedResult(subject, "RID42", "gh exploded");
    const text = r.content[0]?.text ?? "";
    assert.match(
      text,
      new RegExp(
        `^The human APPROVED the ${subject}, but an earlier save attempt in this session did not confirm \\(gh exploded\\), so automatic saves are paused for this session\\. Nothing new was saved\\.`,
      ),
    );
    assert.match(text, new RegExp(`existing ${subject} carrying run id RID42 before retrying`));
    assert.match(
      text,
      /on Linear a partially completed create can leave an issue the retry cannot find/,
    );
    assert.ok(text.includes(`then run ${MANUAL_SAVE_COMMANDS[subject]} (the deliberate retry)`));
    assert.deepEqual(r.details, {
      ok: false,
      error_type: "save_unconfirmed",
      status: "refused",
      subject,
    });
  }
});

test("openRefusedResult, DRAFT_CHANGED_NOTE, SUPERSEDED_DECISION_WARNING and withDraftChangedNote", () => {
  const r = openRefusedResult({ ok: false, reason: "no-identity", detail: "no run_id" });
  assert.equal(
    r.content[0]?.text,
    "cannot open the review: no run_id — fix the cause and call plan_review again",
  );
  assert.deepEqual(r.details, {
    ok: false,
    error_type: "review_open_refused",
    status: "refused",
    reason: "no-identity",
  });
  assert.equal(
    DRAFT_CHANGED_NOTE,
    "Note: the working draft changed after this review opened — weigh the feedback against the current draft.",
  );
  assert.equal(
    SUPERSEDED_DECISION_WARNING,
    "a browser decision arrived for a superseded review — ignored; nothing was saved",
  );
  const base = { content: [{ type: "text" as const, text: "DENIED" }], details: { ok: true } };
  assert.equal(withDraftChangedNote(base, false), base);
  const noted = withDraftChangedNote(base, true);
  assert.equal(noted.content[0]?.text, `${DRAFT_CHANGED_NOTE}\n\nDENIED`);
  assert.equal(base.content[0]?.text, "DENIED", "the input is untouched");
});

test("injectDraftReviewResult: idle → plain user message; busy → followUp; text blocks joined with \\n", () => {
  const idle = fakePi();
  injectDraftReviewResult(idle, ctxFor(true), {
    content: [
      { type: "text", text: "a" },
      { type: "text", text: "b" },
    ],
    details: {},
  });
  assert.deepEqual(idle.sent, [{ text: "a\nb", options: undefined }]);
  const busy = fakePi();
  injectDraftReviewResult(busy, ctxFor(false), {
    content: [{ type: "text", text: "a" }],
    details: {},
  });
  assert.deepEqual(busy.sent, [{ text: "a", options: { deliverAs: "followUp" } }]);
});
