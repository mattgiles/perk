// One shared completion-before-readiness regression over the ONE real readiness observer — the
// browser-operation owner's — in both of its flavors: the code-review spec the PR/stack doors
// open (mode `review`, no companion, no applicability fence) and the draft doors' plan-review
// spec. No model inference: assert the continuation, then drive its instructed sequential tool
// call.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createPerkStatus } from "../../surfaces/surfaces.ts";
import { createMemoryWaveAdapter } from "../../testing/memoryAdapter.ts";
import { reportWaveOver } from "../../waves/reportWave.ts";
import {
  type BrowserOperationOwner,
  createBrowserOperationOwner,
  settleCodeReviewOutcome,
  settleReviewOutcome,
} from "./browserOperation.ts";
import {
  type AnnotationMode,
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
  type FetchResponseLike,
} from "./providers/annotations.ts";
import type { CodeReviewOutcome } from "./providers/plannotatorHandoff.ts";
import type { ReviewOutcome } from "./reviewOutcome.ts";

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

/**
 * The shared fixture. The annotation surface starts unprimed — the owner primes it at `open`.
 * `started` carries a controllable code-review bridge (the PR/stack spec); `draftStarted` the
 * same address with a controllable plan-review bridge (the draft doors' spec).
 */
function fixture(mode: AnnotationMode, idle: boolean) {
  const annotations = createAnnotationState();
  const surface = { mode, url: "http://127.0.0.1:45001" };
  const readiness = deferred<"ready">();
  const bridge = deferred<ReviewOutcome>();
  const codeBridge = deferred<CodeReviewOutcome>();
  const started = {
    url: surface.url,
    port: 45001,
    remote: false,
    readiness: readiness.promise,
    bridgePromise: codeBridge.promise,
  };
  const draftStarted = { ...started, bridgePromise: bridge.promise };
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    sendUserMessage(message: string, options?: { deliverAs?: "steer" | "followUp" }) {
      sent.push({ message, options });
    },
  };
  const ctx = {
    hasUI: true,
    ui: { notify() {}, setStatus() {} },
    isIdle: () => idle,
    signal: undefined,
  };
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
    bridge,
    codeBridge,
    started,
    draftStarted,
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

/** Drain the queue a few times (the owner's observer runs between awaits). */
async function flush(): Promise<void> {
  for (let i = 0; i < 6; i++) await new Promise((resolve) => setImmediate(resolve));
}

/** A real owner over the fixture (budgets expire immediately; pushes use its fetch). */
function ownerFor(f: Fixture): BrowserOperationOwner {
  return createBrowserOperationOwner(f.pi, {
    annotations: f.annotations,
    gating: { primeDeferred: (names) => [...names] },
    status: createPerkStatus(),
    annotationDeps: { fetchLike: f.fetchLike },
    sleep: async () => {},
  });
}

/** Open one draft-door operation over `started` (the owner primes the plan-mode surface). */
async function openThrough(
  owner: BrowserOperationOwner,
  f: Fixture,
  started: Fixture["draftStarted"] = f.draftStarted,
): Promise<void> {
  const opened = await owner.open(f.ctx, {
    scope: "plan-review-browser",
    start: async () => started,
    mode: "plan",
    primes: [],
    degradeNotice: "unavailable (test)",
    settle: settleReviewOutcome,
    onDecision: async () => {},
  });
  assert.deepEqual(opened, { kind: "opened", url: f.surface.url });
}

/**
 * Open one PR/stack-door operation over `started`: the code-review spec (mode `review`, no
 * companion, no applicability fence) — the owner primes the review-mode surface.
 */
async function openReviewThrough(
  owner: BrowserOperationOwner,
  f: Fixture,
  started: Fixture["started"] = f.started,
): Promise<void> {
  const opened = await owner.open(f.ctx, {
    scope: "pr-review-browser",
    start: async () => started,
    mode: "review",
    primes: [],
    degradeNotice: "unavailable (test)",
    settle: settleCodeReviewOutcome,
    onDecision: async () => {},
  });
  assert.deepEqual(opened, { kind: "opened", url: f.surface.url });
}

/**
 * Start observing: the owner's observer after `open` primed the flavor's surface. Resolves to
 * `done` — the promise the case awaits once readiness lands (wrapped, so awaiting the start
 * never awaits readiness itself).
 */
const observers: {
  name: string;
  mode: AnnotationMode;
  observe(f: Fixture): Promise<{ done: Promise<void> }>;
}[] = [
  {
    name: "PR/stack (owner)",
    mode: "review",
    observe: async (f) => {
      await openReviewThrough(ownerFor(f), f);
      return { done: f.readiness.promise.then(flush) };
    },
  },
  {
    name: "draft doors (owner)",
    mode: "plan",
    observe: async (f) => {
      await openThrough(ownerFor(f), f);
      return { done: f.readiness.promise.then(flush) };
    },
  },
];

for (const observer of observers) {
  for (const idle of [true, false]) {
    test(`${observer.name}: completion before readiness resumes held final replace and empty clear (idle=${idle})`, async () => {
      const f = fixture(observer.mode, idle);
      const observing = (await observer.observe(f)).done;
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
      assert.match(f.sent[0]?.message ?? "", /held final replacements after wave collection/);
      assert.doesNotMatch(f.sent[0]?.message ?? "", /source clears|provisional/);
      assert.match(f.sent[0]?.message ?? "", /NOT workflow completion/);
      assert.match(
        f.sent[0]?.message ?? "",
        /Do not repeat reconciliation or resend final findings/,
      );
      // The observer's ready arm flips the primed surface's readiness flag (later network
      // failures retry in-call instead of holding immediately).
      assert.equal(f.annotations.ready, true);
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

test("draft doors (owner): a held final pure clear wakes on readiness even with zero held findings", async () => {
  const f = fixture("plan", true);
  await openThrough(ownerFor(f), f);
  const observing = f.readiness.promise.then(flush);
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
  await openReviewThrough(ownerFor(f), f);
  const observing = f.readiness.promise.then(flush);
  const request = deferred<FetchResponseLike>();
  // Readiness lands mid-request, so the eventual failure is retried in-call (the bounded
  // post-readiness schedule — the delays are a no-op here) before the unit is held.
  const slept: number[] = [];
  const pushing = executePushAnnotations(
    f.annotations,
    f.ctx,
    { angle: "correctness", findings: [f.finding], replace: true },
    {
      fetchLike: () => request.promise,
      sleep: async (ms) => {
        slept.push(ms);
      },
    },
  );
  assert.equal(f.annotations.held.length, 0);
  f.makeReady();
  await observing;
  assert.equal(f.sent.length, 1, "checking held.length here would lose the continuation");
  assert.deepEqual(f.sent[0]?.options, { deliverAs: "followUp" });
  request.reject(new Error("pre-bind request failed"));
  await pushing;
  assert.deepEqual(slept, [1_000, 3_000, 6_000], "readiness arrived, so the retries ran");
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

for (const change of ["close", "replace"] as const) {
  test(`PR/stack (owner): late readiness does not wake a ${change === "close" ? "closed" : "replaced same-URL"} review`, async () => {
    const f = fixture("review", true);
    const owner = ownerFor(f);
    await openReviewThrough(owner, f);
    if (change === "close") {
      const request = deferred<FetchResponseLike>();
      const pushing = executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding] },
        { fetchLike: () => request.promise },
      );
      // A decided bridge closes the operation (the human finished before the server answered).
      f.codeBridge.resolve({
        status: "handled",
        approved: true,
        feedback: undefined,
        annotationCount: 0,
        annotations: [],
        exit: false,
      });
      await flush();
      assert.equal(f.annotations.surface, null, "the decided operation closed its surface");
      request.reject(new Error("late failure after close"));
      await pushing;
      // The in-flight push saw its session close: the late failure is `superseded`, so nothing
      // of the dead session is re-held onto the cleared state (the leak the send-time identity
      // fence exists to prevent). The refusal below is therefore on surface identity alone.
      assert.deepEqual(f.annotations.held, [], "a dead session's unit never leaks into held");
    } else {
      // A second open on the SAME URL replaces the first; the successor has pending work.
      const successor = { ...f.started, readiness: deferred<"ready">().promise };
      await openReviewThrough(owner, f, successor);
      await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding] },
        { fetchLike: f.fetchLike },
      );
      assert.equal(
        f.annotations.held.length,
        1,
        "pending work makes the identity refusal non-vacuous",
      );
    }
    assert.equal(f.annotations.inFlight.count, 0, "old calls cannot decrement the reset counter");
    const before = f.calls.length;
    f.makeReady();
    await f.readiness.promise.then(flush);
    assert.equal(f.sent.length, 0, "the retired operation's late readiness wakes nothing");
    assert.equal(f.calls.length, before);
  });
}

for (const change of ["close", "replace"] as const) {
  test(`draft doors (owner): late readiness does not wake a ${change === "close" ? "closed" : "replaced same-URL"} operation`, async () => {
    const f = fixture("plan", true);
    const owner = ownerFor(f);
    await openThrough(owner, f);
    if (change === "close") {
      // A decided bridge closes the operation (the early-decision path).
      f.bridge.resolve({ status: "completed", approved: false, reviewId: "r-1" });
      await flush();
      assert.equal(f.annotations.surface, null, "the decided operation closed its surface");
    } else {
      // A second open on the SAME URL replaces the first; the successor has pending work.
      const successor = { ...f.draftStarted, readiness: deferred<"ready">().promise };
      await openThrough(owner, f, successor);
      await executePushAnnotations(
        f.annotations,
        f.ctx,
        { angle: "correctness", findings: [f.finding] },
        { fetchLike: f.fetchLike },
      );
      assert.equal(
        f.annotations.held.length,
        1,
        "pending work makes the late-readiness refusal non-vacuous",
      );
    }
    const before = f.calls.length;
    f.makeReady();
    await f.readiness.promise.then(flush);
    assert.equal(f.sent.length, 0, "the retired operation's late readiness wakes nothing");
    assert.equal(f.calls.length, before);
  });
}
