// The automated-review policy matrix — Pi-free feature tests over deterministic fakes
// (resolver/reviewer/publisher) plus the production in-memory WorkflowSession double. The full
// state-machine transition table runs through the two ops (the holder has no method API):
// null → pending → recorded → consumed, the eligibility refusals, the stale_review_wave
// demotion, verdict/coverage rules, the standalone-post arm, array-copy isolation, and the
// AbortSignal passthrough into the reviewer request.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../session/memoryWorkflowSession.ts";
import {
  type AutomatedPost,
  type ChangeReviewer,
  type ChangeReviewOutcome,
  type ChangeReviewRequest,
  type PostOk,
  type PublishOutcome,
  publishAutomatedReview,
  type ReviewPassHolder,
  type ReviewPublisher,
  type ReviewSelection,
  type ReviewTargetResolver,
  runAutomatedReview,
} from "./automated.ts";

const TARGET = { number: 42, url: "https://github.test/o/r/pull/42" };

function okResolver(): ReviewTargetResolver {
  return { resolve: () => Promise.resolve({ ok: true, target: TARGET }) };
}

function failResolver(): ReviewTargetResolver {
  return {
    resolve: () => Promise.resolve({ ok: false, message: "target vanished", errorType: "no_pr" }),
  };
}

function waveOutcome(overrides: Partial<ChangeReviewOutcome> = {}): ChangeReviewOutcome {
  return {
    complete: true,
    covered: ["plan-fidelity", "tests", "ponytail"],
    retried: [],
    reports: [],
    failures: [],
    attempts: [],
    ...overrides,
  };
}

function fakeReviewer(outcome?: ChangeReviewOutcome): {
  reviewer: ChangeReviewer;
  requests: ChangeReviewRequest[];
} {
  const requests: ChangeReviewRequest[] = [];
  return {
    requests,
    reviewer: {
      review(request) {
        requests.push(request);
        return Promise.resolve(outcome ?? waveOutcome());
      },
    },
  };
}

const POST_OK: PostOk = { pr: 42, mode: "review", verdict: "actionable", comment_count: 2 };

function fakePublisher(outcome?: PublishOutcome): {
  publisher: ReviewPublisher;
  batches: Parameters<ReviewPublisher["publish"]>[0][];
} {
  const batches: Parameters<ReviewPublisher["publish"]>[0][] = [];
  return {
    batches,
    publisher: {
      publish(batch) {
        batches.push(batch);
        return Promise.resolve(outcome ?? { ok: true, data: { ...POST_OK } });
      },
    },
  };
}

const SELECTION: ReviewSelection = { angles: ["plan-fidelity", "tests"] };

function post(overrides: Partial<AutomatedPost> = {}): AutomatedPost {
  return { verdict: "actionable", summary: "issues", ...overrides };
}

function publishDeps(
  state: ReviewPassHolder,
  outcome?: PublishOutcome,
): {
  publisher: ReviewPublisher;
  state: ReviewPassHolder;
  session: ReturnType<typeof openMemoryWorkflowSession>;
  batches: Parameters<ReviewPublisher["publish"]>[0][];
} {
  const { publisher, batches } = fakePublisher(outcome);
  return { publisher, state, session: openMemoryWorkflowSession({ runId: "RID" }), batches };
}

// --- runAutomatedReview: the pass state machine -------------------------------------------------

test("a pass invalidates old evidence first; a resolution failure leaves the state pending", async () => {
  const state: ReviewPassHolder = {
    current: { state: "recorded", pr: 41, complete: true, attempted: [], covered: [] },
  };
  const { reviewer, requests } = fakeReviewer();
  const result = await runAutomatedReview(SELECTION, {
    resolver: failResolver(),
    reviewer,
    state,
  });
  assert.deepEqual(result, { kind: "no_target", message: "target vanished", errorType: "no_pr" });
  assert.deepEqual(state.current, { state: "pending" }, "old evidence is gone, state pending");
  assert.equal(requests.length, 0, "no reviewer dispatch without a target");
});

test("a complete pass records the PR-bound manifest with attempted = angles + ponytail", async () => {
  const state: ReviewPassHolder = { current: null };
  const { reviewer } = fakeReviewer();
  const result = await runAutomatedReview(SELECTION, { resolver: okResolver(), reviewer, state });
  assert.equal(result.kind, "reviewed");
  assert.ok(result.kind === "reviewed");
  assert.equal(result.pr, 42);
  assert.deepEqual(result.attempted, ["plan-fidelity", "tests", "ponytail"]);
  assert.equal(result.incompleteWarning, null);
  assert.deepEqual(state.current, {
    state: "recorded",
    pr: 42,
    complete: true,
    attempted: ["plan-fidelity", "tests", "ponytail"],
    covered: ["plan-fidelity", "tests", "ponytail"],
  });
});

test("an incomplete pass records complete: false and derives the loud-warning fields", async () => {
  const state: ReviewPassHolder = { current: null };
  const { reviewer } = fakeReviewer(
    waveOutcome({
      complete: false,
      covered: ["plan-fidelity"],
      failures: [
        { key: "tests", reason: "timeout", detail: "no report" },
        { key: null, reason: "run-failed", detail: "boom" },
      ],
    }),
  );
  const result = await runAutomatedReview(SELECTION, { resolver: okResolver(), reviewer, state });
  assert.ok(result.kind === "reviewed");
  assert.deepEqual(result.incompleteWarning, {
    uncovered: ["tests", "ponytail"],
    reasons: "tests: timeout — no report; wave: run-failed — boom",
  });
  assert.ok(state.current?.state === "recorded" && state.current.complete === false);
});

test("the reviewer request carries pr/angles/directive and the SAME AbortSignal instance", async () => {
  const state: ReviewPassHolder = { current: null };
  const { reviewer, requests } = fakeReviewer();
  const controller = new AbortController();
  await runAutomatedReview(
    { angles: ["plan-fidelity", "quality"], directive: "focus", signal: controller.signal },
    { resolver: okResolver(), reviewer, state },
  );
  assert.equal(requests.length, 1);
  assert.equal(requests[0]?.pr, 42);
  assert.deepEqual(requests[0]?.angles, ["plan-fidelity", "quality"]);
  assert.equal(requests[0]?.directive, "focus");
  assert.equal(requests[0]?.signal, controller.signal, "cancellation ownership rides the request");
});

test("recording COPIES the arrays — mutating the returned outcome never changes the recorded state", async () => {
  const state: ReviewPassHolder = { current: null };
  const outcome = waveOutcome({ covered: ["plan-fidelity", "tests", "ponytail"] });
  const { reviewer } = fakeReviewer(outcome);
  const result = await runAutomatedReview(SELECTION, { resolver: okResolver(), reviewer, state });
  assert.ok(result.kind === "reviewed");
  // Mutate the outcome the adapter received (and the attempted manifest it renders from).
  outcome.covered.length = 0;
  (result.attempted as string[]).length = 0;
  assert.ok(state.current?.state === "recorded");
  assert.deepEqual(state.current.covered, ["plan-fidelity", "tests", "ponytail"]);
  assert.deepEqual(state.current.attempted, ["plan-fidelity", "tests", "ponytail"]);
});

// --- publishAutomatedReview: the eligibility ladder + posting ------------------------------------

test("a pending state refuses with review_wave_unavailable for both verdicts (state untouched)", async () => {
  for (const verdict of ["clean", "actionable"] as const) {
    const state: ReviewPassHolder = { current: { state: "pending" } };
    const deps = publishDeps(state);
    const result = await publishAutomatedReview(post({ verdict }), deps);
    assert.deepEqual(result, {
      kind: "ineligible",
      errorType: "review_wave_unavailable",
      message: "the latest review pass has no recorded outcome; rerun /pr-review before posting",
    });
    assert.deepEqual(state.current, { state: "pending" });
    assert.equal(deps.batches.length, 0);
  }
});

test("a consumed state refuses with review_wave_consumed (state untouched)", async () => {
  const state: ReviewPassHolder = { current: { state: "consumed" } };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(post(), deps);
  assert.deepEqual(result, {
    kind: "ineligible",
    errorType: "review_wave_consumed",
    message:
      "the recorded review outcome has already been posted; rerun /pr-review before posting again",
  });
  assert.deepEqual(state.current, { state: "consumed" });
  assert.equal(deps.batches.length, 0);
});

test("a clean verdict over an incomplete recorded wave refuses with incomplete_coverage", async () => {
  const state: ReviewPassHolder = {
    current: { state: "recorded", pr: 42, complete: false, attempted: ["a"], covered: [] },
  };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
  assert.equal(result.kind, "ineligible");
  assert.ok(result.kind === "ineligible" && result.errorType === "incomplete_coverage");
  assert.match(result.message, /incomplete coverage is never a clean review/);
  assert.ok(state.current?.state === "recorded", "the refusal leaves the state untouched");
  assert.equal(deps.batches.length, 0);
});

test("an actionable post over an incomplete recorded wave still lands (coverage caveat rides the record)", async () => {
  const state: ReviewPassHolder = {
    current: {
      state: "recorded",
      pr: 42,
      complete: false,
      attempted: ["plan-fidelity", "correctness", "ponytail"],
      covered: [],
    },
  };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(
    post({ angles: ["caller-supplied-is-ignored"] }),
    deps,
  );
  assert.ok(result.kind === "posted");
  assert.deepEqual(result.record.angles, ["plan-fidelity", "correctness", "ponytail"]);
  assert.deepEqual(result.record.covered_angles, []);
  assert.deepEqual(state.current, { state: "consumed" });
});

test("a recorded post threads expected_pr; success records last_pr_review and consumes", async () => {
  const state: ReviewPassHolder = {
    current: {
      state: "recorded",
      pr: 42,
      complete: true,
      attempted: ["plan-fidelity", "tests", "ponytail"],
      covered: ["plan-fidelity", "tests", "ponytail"],
    },
  };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(post(), deps);
  assert.ok(result.kind === "posted");
  assert.equal(deps.batches[0]?.expectedPr, 42, "the recorded wave binds the mutation");
  assert.equal(result.record.pr, 42);
  assert.equal(result.record.verdict, "actionable");
  assert.deepEqual(result.record.angles, ["plan-fidelity", "tests", "ponytail"]);
  assert.deepEqual(result.record.covered_angles, ["plan-fidelity", "tests", "ponytail"]);
  assert.equal(result.record.comment_count, 2);
  assert.equal(result.record.mode, "review");
  assert.ok(!Number.isNaN(Date.parse(result.record.at)));
  assert.deepEqual(deps.session.lastPrReviewRecord(), result.record);
  assert.deepEqual(state.current, { state: "consumed" });
});

test("the standalone-post arm (null state) posts without expected_pr; caller angles fill both manifests", async () => {
  const state: ReviewPassHolder = { current: null };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(
    post({ angles: ["plan-fidelity", "correctness"] }),
    deps,
  );
  assert.ok(result.kind === "posted");
  assert.equal(deps.batches[0]?.expectedPr, undefined, "standalone batches omit expected_pr");
  assert.deepEqual(result.record.angles, ["plan-fidelity", "correctness"]);
  assert.deepEqual(result.record.covered_angles, ["plan-fidelity", "correctness"]);
  assert.equal(state.current, null, "a standalone post never consumes");
});

test("the standalone-post arm defaults both manifests to [] when no angles are supplied", async () => {
  const state: ReviewPassHolder = { current: null };
  const deps = publishDeps(state);
  const result = await publishAutomatedReview(post(), deps);
  assert.ok(result.kind === "posted");
  assert.deepEqual(result.record.angles, []);
  assert.deepEqual(result.record.covered_angles, []);
});

test("review_target_changed over a recorded state demotes to pending (stale_review_wave)", async () => {
  const state: ReviewPassHolder = {
    current: { state: "recorded", pr: 42, complete: true, attempted: ["a"], covered: ["a"] },
  };
  const deps = publishDeps(state, {
    ok: false,
    message: "expected PR #42, found PR #43",
    errorType: "review_target_changed",
  });
  const result = await publishAutomatedReview(post(), deps);
  assert.deepEqual(result, {
    kind: "stale",
    errorType: "stale_review_wave",
    message:
      "the active PR changed after this review wave; the recorded reports are stale — rerun " +
      "/pr-review before posting",
  });
  assert.deepEqual(state.current, { state: "pending" });
  assert.equal(deps.session.lastPrReviewRecord(), null, "a refused post records nothing");
});

test("review_target_changed WITHOUT a recorded state passes through as publish_failed", async () => {
  const state: ReviewPassHolder = { current: null };
  const deps = publishDeps(state, {
    ok: false,
    message: "expected PR #42, found PR #43",
    errorType: "review_target_changed",
  });
  const result = await publishAutomatedReview(post(), deps);
  assert.deepEqual(result, {
    kind: "publish_failed",
    message: "expected PR #42, found PR #43",
    errorType: "review_target_changed",
  });
  assert.equal(state.current, null);
});

test("other publisher failures pass through verbatim; the recorded state is retained for retry", async () => {
  const state: ReviewPassHolder = {
    current: { state: "recorded", pr: 42, complete: true, attempted: ["a"], covered: ["a"] },
  };
  const deps = publishDeps(state, {
    ok: false,
    message: "temporary failure",
    errorType: "github_error",
  });
  const result = await publishAutomatedReview(post(), deps);
  assert.deepEqual(result, {
    kind: "publish_failed",
    message: "temporary failure",
    errorType: "github_error",
  });
  assert.ok(state.current?.state === "recorded", "the recorded outcome survives for a retry");
});

test("the record's session classification is ignored — a rejected append never fails the post", async () => {
  const state: ReviewPassHolder = { current: null };
  const deps = publishDeps(state);
  deps.session.failNextApply();
  const result = await publishAutomatedReview(post(), deps);
  assert.equal(result.kind, "posted", "the seam owns loudness; the post already succeeded");
  assert.equal(deps.session.lastPrReviewRecord(), null);
});
