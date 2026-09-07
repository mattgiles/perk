// The automated-review policy matrix — Pi-free feature tests over deterministic fakes
// (resolver/reviewer/publisher) plus the production in-memory WorkflowSession double. The full
// state-machine transition table runs through the two ops (the holder has no method API):
// null → pending → recorded → consumed, the eligibility refusals, the stale_review_wave
// demotion, verdict/coverage rules, the recorded minimum-verdict floor (derivation + the
// review_verdict_conflict refusal + snapshot isolation), the standalone-post arm, array-copy
// isolation, and the AbortSignal passthrough into the reviewer request. Retry precedence is the
// wave suite's; registered-tool composition is the adapter suite's.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../testing/memoryWorkflowSession.ts";
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

/** Silence the strict-append seam's loud stderr report for a deliberately induced failure. */
async function quietly<T>(fn: () => Promise<T>): Promise<T> {
  const original = console.error;
  console.error = () => {};
  try {
    return await fn();
  } finally {
    console.error = original;
  }
}

function okResolver(): ReviewTargetResolver {
  return { resolve: () => Promise.resolve({ ok: true, target: TARGET }) };
}

function failResolver(): ReviewTargetResolver {
  return {
    resolve: () => Promise.resolve({ ok: false, message: "target vanished", errorType: "no_pr" }),
  };
}

const COVERED = ["plan-fidelity", "tests", "ponytail"];

/** A schema-valid per-lane report (the engine-validated shape the wave hands back). */
function report(
  angle: string,
  overrides: { verdict?: string; findings?: unknown[]; fyi?: string[] } = {},
): { key: string; report: { angle: string; verdict: string; findings: unknown[]; fyi: string[] } } {
  return {
    key: angle,
    report: {
      angle,
      verdict: overrides.verdict ?? "clean",
      findings: overrides.findings ?? [],
      fyi: overrides.fyi ?? [],
    },
  };
}

const FINDING = { path: "a.ts", line: 12, body: "fix this" };

/**
 * A realistic complete outcome: every covered key carries a real clean report by default (so
 * the recorded floor is derived from evidence, never from an unrealistic empty report set).
 * Negative fixtures supply their own divergent reports explicitly.
 */
function waveOutcome(overrides: Partial<ChangeReviewOutcome> = {}): ChangeReviewOutcome {
  const covered = overrides.covered ?? COVERED;
  return {
    complete: true,
    covered,
    retried: [],
    reports: covered.map((key) => report(key)),
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

/** Run a pass over `outcome` into a fresh holder, then hand back the recorded state + post deps. */
async function recordedPass(
  outcome: ChangeReviewOutcome,
  publish?: PublishOutcome,
): Promise<ReturnType<typeof publishDeps> & { recorded: ReviewPassHolder["current"] }> {
  const state: ReviewPassHolder = { current: null };
  const { reviewer } = fakeReviewer(outcome);
  const result = await runAutomatedReview(SELECTION, { resolver: okResolver(), reviewer, state });
  assert.equal(result.kind, "reviewed");
  return { ...publishDeps(state, publish), recorded: structuredClone(state.current) };
}

const VERDICT_CONFLICT = {
  kind: "ineligible",
  errorType: "review_verdict_conflict",
  message:
    "the recorded review outcome contains an actionable assessment or surviving findings; a " +
    "clean verdict would contradict that evidence — post a reconciled actionable review or " +
    "post nothing",
} as const;

// --- runAutomatedReview: the pass state machine -------------------------------------------------

test("a pass invalidates old evidence first; a resolution failure leaves the state pending", async () => {
  const state: ReviewPassHolder = {
    current: {
      state: "recorded",
      pr: 41,
      complete: true,
      attempted: [],
      covered: [],
      minimumVerdict: "clean",
    },
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
    minimumVerdict: "clean",
  });
});

test("an incomplete pass records complete: false and derives the loud-warning fields", async () => {
  const state: ReviewPassHolder = { current: null };
  const { reviewer } = fakeReviewer(
    waveOutcome({
      complete: false,
      covered: ["plan-fidelity"],
      failures: [
        // A keyed failure carries an assignment-level reason by type (the discriminated
        // ReportWaveFailure union makes a wave-level reason on a keyed lane unrepresentable).
        { key: "tests", reason: "lane-failed", detail: "no report" },
        { key: null, reason: "run-failed", detail: "boom" },
      ],
    }),
  );
  const result = await runAutomatedReview(SELECTION, { resolver: okResolver(), reviewer, state });
  assert.ok(result.kind === "reviewed");
  assert.deepEqual(result.incompleteWarning, {
    uncovered: ["tests", "ponytail"],
    reasons: "tests: lane-failed — no report; wave: run-failed — boom",
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

// --- the recorded minimum-verdict floor: derivation + review_verdict_conflict -------------------

for (const [label, reports] of [
  [
    "an actionable report with findings",
    [
      report("plan-fidelity"),
      report("tests", { verdict: "actionable", findings: [FINDING] }),
      report("ponytail"),
    ],
  ],
  [
    "an actionable report with EMPTY findings (the verdict alone suffices)",
    [report("plan-fidelity"), report("tests", { verdict: "actionable" }), report("ponytail")],
  ],
  [
    "a contradictory clean report carrying findings below schema validation (findings alone suffice)",
    [report("plan-fidelity"), report("tests", { findings: [FINDING] }), report("ponytail")],
  ],
  [
    "actionable evidence supplied ONLY by the automatic Ponytail lane",
    [report("plan-fidelity"), report("tests"), report("ponytail", { verdict: "actionable" })],
  ],
] as const) {
  test(`complete coverage with ${label}: a clean post is refused with review_verdict_conflict`, async () => {
    const deps = await recordedPass(waveOutcome({ reports: [...reports] }));
    assert.ok(deps.recorded?.state === "recorded");
    assert.equal(deps.recorded.complete, true);
    assert.equal(deps.recorded.minimumVerdict, "actionable");
    const result = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
    assert.deepEqual(result, VERDICT_CONFLICT);
    assert.equal(deps.batches.length, 0, "refused before the publisher");
    assert.deepEqual(deps.state.current, deps.recorded, "the record survives untouched");
    assert.equal(deps.session.lastPrReviewRecord(), null, "nothing recorded");
  });
}

test("complete all-clean reports with nonempty FYI keep a clean floor: clean reaches the publisher PR-bound", async () => {
  const deps = await recordedPass(
    waveOutcome({
      reports: COVERED.map((key) =>
        report(key, { fyi: ["actionable-sounding nit", "findings: none"] }),
      ),
    }),
  );
  assert.ok(deps.recorded?.state === "recorded");
  assert.equal(deps.recorded.minimumVerdict, "clean", "FYI prose never changes the floor");
  const result = await publishAutomatedReview(
    post({ verdict: "clean", summary: "clean", fyi: ["a nit"] }),
    deps,
  );
  assert.ok(result.kind === "posted");
  assert.deepEqual(deps.batches, [
    { verdict: "clean", summary: "clean", fyi: ["a nit"], expectedPr: 42 },
  ]);
  assert.deepEqual(deps.state.current, { state: "consumed" });
});

test("incomplete coverage plus actionable evidence: the existing incomplete_coverage refusal wins", async () => {
  const deps = await recordedPass(
    waveOutcome({
      complete: false,
      covered: ["plan-fidelity", "tests"],
      reports: [
        report("plan-fidelity"),
        report("tests", { verdict: "actionable", findings: [FINDING] }),
      ],
      failures: [{ key: "ponytail", reason: "lane-failed", detail: "no report" }],
    }),
  );
  assert.ok(deps.recorded?.state === "recorded");
  assert.equal(deps.recorded.minimumVerdict, "actionable");
  const result = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
  assert.ok(result.kind === "ineligible" && result.errorType === "incomplete_coverage");
  assert.equal(deps.batches.length, 0);
  assert.deepEqual(deps.state.current, deps.recorded);
});

test("a refused clean followed by a parent-reconciled actionable post: the exact batch lands and consumes once", async () => {
  const deps = await recordedPass(
    waveOutcome({
      reports: [
        report("plan-fidelity"),
        report("tests", { verdict: "actionable", findings: [FINDING] }),
        report("ponytail"),
      ],
    }),
  );
  const refused = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
  assert.deepEqual(refused, VERDICT_CONFLICT);
  // The parent reconciles: its own summary/comments/FYI (the guard never manufactures findings
  // or enforces finding membership — a reconciled actionable post with zero comments is legal).
  const comments = [{ path: "a.ts", line: 12, body: "reconciled: fix this" }];
  const posted = await publishAutomatedReview(
    post({ summary: "one issue", comments, fyi: ["kept in-session"] }),
    deps,
  );
  assert.ok(posted.kind === "posted");
  assert.deepEqual(deps.batches, [
    {
      verdict: "actionable",
      summary: "one issue",
      comments,
      fyi: ["kept in-session"],
      expectedPr: 42,
    },
  ]);
  assert.deepEqual(deps.session.lastPrReviewRecord(), posted.record);
  assert.deepEqual(
    Object.keys(posted.record).sort(),
    ["angles", "at", "comment_count", "covered_angles", "mode", "pr", "verdict"],
    "the durable record carries neither minimumVerdict nor raw reports",
  );
  assert.deepEqual(deps.state.current, { state: "consumed" });
  const duplicate = await publishAutomatedReview(post(), deps);
  assert.ok(duplicate.kind === "ineligible" && duplicate.errorType === "review_wave_consumed");
  assert.equal(deps.batches.length, 1, "consumed exactly once");
});

test("all-clean evidence followed by a parent actionable post: the permissive escalation remains", async () => {
  const deps = await recordedPass(waveOutcome());
  assert.ok(deps.recorded?.state === "recorded" && deps.recorded.minimumVerdict === "clean");
  const posted = await publishAutomatedReview(post({ comments: [FINDING] }), deps);
  assert.ok(posted.kind === "posted");
  assert.deepEqual(deps.batches[0], {
    verdict: "actionable",
    summary: "issues",
    comments: [FINDING],
    expectedPr: 42,
  });
  assert.deepEqual(deps.state.current, { state: "consumed" });
});

test("the minimum is a SNAPSHOT: mutating the recorded source report after the pass never lowers it", async () => {
  const actionable = report("tests", { verdict: "actionable", findings: [FINDING] });
  const outcome = waveOutcome({
    reports: [report("plan-fidelity"), actionable, report("ponytail")],
  });
  const deps = await recordedPass(outcome);
  // The adapter-side outcome (the very object the reviewer returned) is rewritten to look clean.
  actionable.report.verdict = "clean";
  actionable.report.findings.length = 0;
  const result = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
  assert.deepEqual(result, VERDICT_CONFLICT);
  assert.equal(deps.batches.length, 0);
  assert.equal(deps.session.lastPrReviewRecord(), null);
  assert.ok(deps.state.current?.state === "recorded");
  assert.equal(deps.state.current.minimumVerdict, "actionable");
  assert.equal("reports" in deps.state.current, false, "the holder retains no report references");
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
    current: {
      state: "recorded",
      pr: 42,
      complete: false,
      attempted: ["a"],
      covered: [],
      minimumVerdict: "clean",
    },
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
      minimumVerdict: "clean",
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

test("a recorded post threads the COMPLETE batch; success records last_pr_review and consumes", async () => {
  const state: ReviewPassHolder = {
    current: {
      state: "recorded",
      pr: 42,
      complete: true,
      attempted: ["plan-fidelity", "tests", "ponytail"],
      covered: ["plan-fidelity", "tests", "ponytail"],
      minimumVerdict: "actionable",
    },
  };
  const deps = publishDeps(state);
  const comments = [{ path: "a.ts", line: 12, body: "fix this" }];
  const fyi = ["a nit"];
  const result = await publishAutomatedReview(post({ comments, fyi }), deps);
  assert.ok(result.kind === "posted");
  // The WHOLE publisher batch — dropping summary/comments/fyi in the handoff would post a
  // review without its findings while every field-by-field pin stayed green.
  assert.deepEqual(deps.batches[0], {
    verdict: "actionable",
    summary: "issues",
    comments,
    fyi,
    expectedPr: 42,
  });
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
    current: {
      state: "recorded",
      pr: 42,
      complete: true,
      attempted: ["a"],
      covered: ["a"],
      minimumVerdict: "clean",
    },
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
    current: {
      state: "recorded",
      pr: 42,
      complete: true,
      attempted: ["a"],
      covered: ["a"],
      minimumVerdict: "clean",
    },
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

test("a failed actionable publication keeps the actionable minimum — the floor survives for the retry", async () => {
  const deps = await recordedPass(
    waveOutcome({
      reports: [
        report("plan-fidelity"),
        report("tests", { verdict: "actionable", findings: [FINDING] }),
        report("ponytail"),
      ],
    }),
    { ok: false, message: "temporary failure", errorType: "github_error" },
  );
  const failed = await publishAutomatedReview(post({ comments: [FINDING] }), deps);
  assert.equal(failed.kind, "publish_failed");
  assert.deepEqual(deps.state.current, deps.recorded, "the transient failure changes nothing");
  assert.ok(deps.state.current?.state === "recorded");
  assert.equal(deps.state.current.minimumVerdict, "actionable");
  // A clean post after the failure is still refused by the surviving floor.
  const clean = await publishAutomatedReview(post({ verdict: "clean", summary: "clean" }), deps);
  assert.deepEqual(clean, VERDICT_CONFLICT);
  assert.equal(deps.batches.length, 1, "the refused clean never reached the publisher");
  assert.equal(deps.session.lastPrReviewRecord(), null);
});

test("the record's session classification is ignored — a rejected append never fails the post", async () => {
  const state: ReviewPassHolder = { current: null };
  const deps = publishDeps(state);
  deps.session.failNextApply();
  const result = await quietly(() => publishAutomatedReview(post(), deps));
  assert.equal(result.kind, "posted", "the seam owns loudness; the post already succeeded");
  assert.equal(deps.session.lastPrReviewRecord(), null);
});
