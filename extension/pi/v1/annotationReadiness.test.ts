// One shared completion-before-readiness regression over the real readiness observers. No
// model inference: assert the continuation, then drive its instructed sequential tool call.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createDraftReviewWaveState } from "../../authoring/review/draftContext.ts";
import { createMemoryWaveAdapter } from "../../testing/memoryAdapter.ts";
import { reportWaveOver } from "../../waves/reportWave.ts";
import { observeBrowserReadiness } from "./codeReview/browser.ts";
import { observeObjectiveReviewReadiness } from "./objectiveReviewBrowser.ts";
import { observePlanReviewReadiness } from "./planReviewBrowser.ts";
import {
  type AnnotationMode,
  clearAnnotationSurface,
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
  type FetchResponseLike,
  primeAnnotationSurface,
} from "./providers/annotations.ts";

function deferred<T>() {
  const controls: {
    resolve?: (value: T | PromiseLike<T>) => void;
    reject?: (reason: unknown) => void;
  } = {};
  const promise = new Promise<T>((resolve, reject) => {
    controls.resolve = resolve;
    controls.reject = reject;
  });
  assert.ok(controls.resolve);
  assert.ok(controls.reject);
  return { promise, resolve: controls.resolve, reject: controls.reject };
}

function fixture(mode: AnnotationMode, idle: boolean) {
  const annotations = createAnnotationState();
  const surface = { mode, url: "http://127.0.0.1:45001" };
  primeAnnotationSurface(annotations, surface);
  const readiness = deferred<"ready">();
  const started = {
    ...surface,
    port: 45001,
    readiness: readiness.promise,
    bridgePromise: new Promise<never>(() => {}),
  };
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    sendUserMessage(message: string, options?: { deliverAs?: "steer" | "followUp" }) {
      sent.push({ message, options });
    },
  };
  const ctx = { hasUI: true, ui: { notify() {} }, isIdle: () => idle };
  const finding =
    mode === "review"
      ? { path: "src/a.ts", line: 3, body: "Final concern", severity: "major", confidence: "high" }
      : { phrase: "the draft", body: "Final concern", severity: "major", confidence: "high" };
  const calls: { url: string; method: string; body?: string }[] = [];
  let up = false;
  const fetchLike: FetchLike = async (url, init) => {
    if (!up) throw new Error("server not bound");
    calls.push({ url, method: init.method, body: init.body });
    return {
      ok: true,
      status: init.method === "POST" ? 201 : 200,
      text: async () =>
        JSON.stringify(init.method === "POST" ? { ids: ["final-id"] } : { removed: 1 }),
    };
  };
  return {
    annotations,
    surface,
    readiness,
    started,
    sent,
    pi,
    ctx,
    finding,
    calls,
    fetchLike,
    makeReady() {
      up = true;
      readiness.resolve("ready");
    },
  };
}
type Fixture = ReturnType<typeof fixture>;
const observers: { name: string; mode: AnnotationMode; observe(f: Fixture): Promise<void> }[] = [
  {
    name: "PR/stack",
    mode: "review",
    observe: (f) => observeBrowserReadiness(f.pi, f.ctx, f.started, f.annotations),
  },
  {
    name: "plan",
    mode: "plan",
    observe: (f) =>
      observePlanReviewReadiness(
        f.pi,
        f.ctx,
        f.started,
        createDraftReviewWaveState(),
        f.annotations,
      ),
  },
  {
    name: "objective",
    mode: "plan",
    observe: (f) =>
      observeObjectiveReviewReadiness(
        f.pi,
        f.ctx,
        f.started,
        createDraftReviewWaveState(),
        f.annotations,
      ),
  },
];

for (const observer of observers) {
  for (const idle of [true, false]) {
    test(`${observer.name}: completion before readiness resumes held final replace and empty clear (idle=${idle})`, async () => {
      const f = fixture(observer.mode, idle);
      const observing = observer.observe(f);
      const adapter = createMemoryWaveAdapter({
        completion: false,
        aggregate: {
          state: "complete",
          value: [{ key: "correctness", ok: true, error: null, report: { findings: [f.finding] } }],
        },
      });
      const wave = reportWaveOver(adapter);
      const start = await wave.start({
        flow: "readiness-regression",
        assignments: [{ key: "correctness", agent: "test", task: "Review" }],
        outputSchema: { type: "object" },
        completeness: "strict",
      });
      assert.ok(start.ok);
      adapter.emitCompletion({ asyncId: start.runId, asyncDir: start.asyncDir });
      const collected = await wave.collect(start.ref);
      assert.equal(collected.kind, "settled");
      assert.equal(f.sent.length, 0, "readiness is still withheld after collection");
      const final = await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding], replace: true },
        { fetchLike: f.fetchLike },
      );
      assert.equal(final.details.ok, true);
      const clear = await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "ponytail", findings: [], replace: true },
        { fetchLike: f.fetchLike },
      );
      assert.equal(clear.details.ok, true);
      if (!clear.details.ok) return;
      assert.equal(clear.details.held, 1);
      assert.equal(clear.details.held_batches, 2);
      assert.equal(f.annotations.inFlight.count, 0);
      f.makeReady();
      await observing;
      assert.equal(
        f.sent.length,
        1,
        "one readiness continuation without another batch/completion or human input",
      );
      assert.deepEqual(f.sent[0]?.options, idle ? undefined : { deliverAs: "followUp" });
      assert.match(f.sent[0]?.message ?? "", /findings: \[\].*replace omitted/);
      assert.match(
        f.sent[0]?.message ?? "",
        /held final replacements or source clears after wave collection/,
      );
      assert.match(f.sent[0]?.message ?? "", /NOT workflow completion/);
      assert.match(
        f.sent[0]?.message ?? "",
        /Do not repeat reconciliation or resend final\/provisional findings/,
      );
      assert.doesNotMatch(f.sent[0]?.message ?? "", /127\.0\.0\.1|45001/);
      assert.equal(f.calls.length, 0, "observer does not become a concurrent queue writer");
      const flushed = await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [] },
        { fetchLike: f.fetchLike },
      );
      assert.equal(flushed.details.ok, true);
      if (!flushed.details.ok) return;
      assert.equal(flushed.details.held_batches, 0);
      assert.equal(flushed.details.pushed, 1);
      assert.equal(f.annotations.inFlight.count, 0);
      assert.deepEqual(
        f.calls.map((c) => c.method),
        ["DELETE", "POST", "DELETE"],
      );
      assert.match(f.calls[0]?.url ?? "", /source=perk%3Acorrectness$/);
      assert.match(f.calls[2]?.url ?? "", /source=perk%3Aponytail$/);
      assert.match(f.calls[1]?.body ?? "", /Final concern/);
      assert.equal(f.annotations.ledger.size, 1);
      assert.equal(adapter.calls.spawn.length, 1);
      // A repeated empty flush cannot repeat the final replace/delete effects.
      await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [] },
        { fetchLike: f.fetchLike },
      );
      assert.equal(f.calls.length, 3);
    });
  }
}

test("a held final pure clear wakes on readiness even with zero held findings", async () => {
  const f = fixture("plan", true);
  const observing = observePlanReviewReadiness(
    f.pi,
    f.ctx,
    f.started,
    createDraftReviewWaveState(),
    f.annotations,
  );
  const held = await executePushAnnotations(
    f.annotations,
    f.ctx,
    { angle: "ponytail", findings: [], replace: true },
    { fetchLike: f.fetchLike },
  );
  assert.equal(held.details.ok, true);
  if (!held.details.ok) return;
  assert.equal(held.details.held, 0);
  assert.equal(held.details.held_batches, 1);
  f.makeReady();
  await observing;
  assert.equal(f.sent.length, 1);
  const flushed = await executePushAnnotations(
    f.annotations,
    f.ctx,
    { angle: "ponytail", findings: [] },
    { fetchLike: f.fetchLike },
  );
  assert.equal(flushed.details.ok, true);
  if (flushed.details.ok) assert.equal(flushed.details.held_batches, 0);
  assert.deepEqual(
    f.calls.map((c) => c.method),
    ["DELETE"],
  );
});

test("readiness also queues a continuation while a pre-bind request is still in flight", async () => {
  const f = fixture("review", false);
  const observing = observeBrowserReadiness(f.pi, f.ctx, f.started, f.annotations);
  const request = deferred<FetchResponseLike>();
  const pushing = executePushAnnotations(
    f.annotations,
    f.ctx,
    { angle: "correctness", findings: [f.finding], replace: true },
    { fetchLike: () => request.promise },
  );
  assert.equal(f.annotations.held.length, 0);
  f.makeReady();
  await observing;
  assert.equal(f.sent.length, 1, "checking held.length here would lose the continuation");
  assert.deepEqual(f.sent[0]?.options, { deliverAs: "followUp" });
  request.reject(new Error("pre-bind request failed"));
  await pushing;
  assert.equal(f.annotations.held.length, 1);
  const flushed = await executePushAnnotations(
    f.annotations,
    f.ctx,
    { angle: "correctness", findings: [] },
    { fetchLike: f.fetchLike },
  );
  assert.equal(flushed.details.ok, true);
  if (flushed.details.ok) assert.equal(flushed.details.held_batches, 0);
  assert.deepEqual(
    f.calls.map((c) => c.method),
    ["DELETE", "POST"],
  );
});

for (const change of ["close", "reprime"] as const) {
  test(`late readiness does not wake a ${change === "close" ? "closed" : "superseded same-URL"} review`, async () => {
    const f = fixture("review", true);
    const observing = observeBrowserReadiness(f.pi, f.ctx, f.started, f.annotations);
    if (change === "close") {
      const request = deferred<FetchResponseLike>();
      const pushing = executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding] },
        { fetchLike: () => request.promise },
      );
      clearAnnotationSurface(f.annotations);
      request.reject(new Error("late failure after close"));
      await pushing;
    } else {
      primeAnnotationSurface(f.annotations, f.surface);
      await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding] },
        { fetchLike: f.fetchLike },
      );
    }
    assert.equal(
      f.annotations.held.length,
      1,
      "pending work makes the identity refusal non-vacuous",
    );
    assert.equal(f.annotations.inFlight.count, 0, "old calls cannot decrement the reset counter");
    f.makeReady();
    await observing;
    assert.equal(f.sent.length, 0);
    assert.equal(f.calls.length, 0);
  });
}
