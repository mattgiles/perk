// The browser-operation owner, pinned at its interface with pure fakes (fast tier): a fake
// handoff (deferred readiness/bridge, the recorded start signal, the real bridge's abort
// posture), a recording annotation fetch, a ctx whose every member throws once `stale()` (Pi's
// invalidated ctx), and a controllable budget clock. The real-handoff preset-window pin lives in
// `providers/plannotatorHandoff.test.ts`; the door compositions live in the door suites.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createPerkStatus } from "../../surfaces/surfaces.ts";
import {
  type BrowserLaunch,
  type BrowserOperationSpec,
  CONSOLE_QUIET_MS,
  createBrowserOperationOwner,
  DECISION_DRAIN_BUDGET_MS,
  DETACH_MARKER_BUDGET_MS,
  decisionDrainExpiredWarning,
  detachedDecisionWarning,
  postDegradeDecisionWarning,
  QUIESCE_BUDGET_MS,
  settleReviewOutcome,
} from "./browserOperation.ts";
import {
  type AnnotationState,
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
  type FetchResponseLike,
} from "./providers/annotations.ts";
import type { BrowserReadiness, StartedSurface } from "./providers/plannotatorHandoff.ts";
import { reviewDetachedStatus } from "./providers/waveStatus.ts";
import type { ReviewOutcome } from "./reviewOutcome.ts";

// ------------------------------------------------------------------ fixtures

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: unknown): void;
  settled(): boolean;
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  let done = false;
  const promise = new Promise<T>((res, rej) => {
    resolve = (value) => {
      done = true;
      res(value);
    };
    reject = (reason) => {
      done = true;
      rej(reason);
    };
  });
  return { promise, resolve, reject, settled: () => done };
}

/** Drain the microtask/macrotask queue a few times (background tasks run between awaits). */
async function flush(rounds = 6): Promise<void> {
  for (let i = 0; i < rounds; i++) await new Promise((resolve) => setImmediate(resolve));
}

const SCOPE = "plan-review-browser";
const URL_A = "http://127.0.0.1:45001";
const URL_B = "http://127.0.0.1:45002";
const URL_C = "http://127.0.0.1:45003";
const COMPLETED: ReviewOutcome = { status: "completed", approved: true, reviewId: "r-1" };
const DEGRADE_NOTICE = "DEGRADE NOTICE (test)";
const PRIMES = ["collect_draft_review_wave", "push_annotations"] as const;

/**
 * A fake handoff flavor: deferred readiness + bridge and the recorded start signal. By default
 * it honours an abort the way the real handoff does — the bridge settles `aborted` and the
 * readiness poll settles `aborted` (each only if still pending).
 */
function fakeHandoff(opts: { url?: string; remote?: boolean; honourAbort?: boolean } = {}) {
  const readiness = deferred<BrowserReadiness>();
  const bridge = deferred<ReviewOutcome>();
  const rec = {
    readiness,
    bridge,
    calls: 0,
    signal: null as AbortSignal | null,
    onStart: (_launch: BrowserLaunch) => {},
    gate: null as Deferred<void> | null,
    fail: null as Error | null,
  };
  const honour = opts.honourAbort ?? true;
  const start = async (launch: BrowserLaunch): Promise<StartedSurface<ReviewOutcome>> => {
    rec.calls += 1;
    rec.signal = launch.signal;
    rec.onStart(launch);
    if (rec.gate !== null) await rec.gate.promise;
    if (rec.fail !== null) throw rec.fail;
    if (honour) {
      const onAbort = (): void => {
        if (!bridge.settled()) bridge.resolve({ status: "aborted" });
        if (!readiness.settled()) readiness.resolve("aborted");
      };
      if (launch.signal.aborted) onAbort();
      else launch.signal.addEventListener("abort", onAbort, { once: true });
    }
    return {
      url: opts.url ?? URL_A,
      port: Number((opts.url ?? URL_A).split(":").at(-1)),
      remote: opts.remote ?? false,
      readiness: readiness.promise,
      bridgePromise: bridge.promise,
    };
  };
  return Object.assign(rec, { rec, start });
}

/** A ctx/pi pair whose every member throws once `stale()` is called (Pi's invalidate()). */
function fakeSession(opts: { idle?: boolean; signal?: AbortSignal } = {}) {
  const notifies: { message: string; severity?: string }[] = [];
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  let stale = false;
  const guard = (): void => {
    if (stale) throw new Error("This extension ctx is stale after session replacement");
  };
  let idle = opts.idle ?? true;
  const ui = {
    notify: (message: string, severity?: string) => notifies.push({ message, severity }),
    setStatus: () => {},
  };
  const ctx = {
    get hasUI() {
      guard();
      return true;
    },
    get ui() {
      guard();
      return ui;
    },
    isIdle: () => {
      guard();
      return idle;
    },
    get signal() {
      guard();
      return opts.signal;
    },
  };
  const pi = {
    sendUserMessage(message: string, options?: { deliverAs?: "steer" | "followUp" }) {
      guard();
      sent.push(options === undefined ? { message } : { message, options });
    },
  };
  return {
    ctx,
    pi,
    notifies,
    sent,
    stale() {
      stale = true;
    },
    setIdle(value: boolean) {
      idle = value;
    },
  };
}

type FetchMode = "ok" | "network" | "reject" | "hang";

/** A recording annotation fetch; `mode` is switchable, `hang` parks every call on `release`. */
function recordingFetch(annotations: AnnotationState) {
  const calls: { method: string; url: string; body?: string; primedAt: string | null }[] = [];
  const state = { mode: "ok" as FetchMode, hung: [] as Deferred<FetchResponseLike>[] };
  const fetchLike: FetchLike = async (url, init) => {
    calls.push({
      method: init.method,
      url,
      body: init.body,
      primedAt: annotations.surface?.url ?? null,
    });
    if (state.mode === "network") throw new Error("ECONNREFUSED");
    if (state.mode === "hang") {
      const parked = deferred<FetchResponseLike>();
      state.hung.push(parked);
      return parked.promise;
    }
    if (state.mode === "reject") {
      return { ok: false, status: 500, text: async () => "boom" };
    }
    return {
      ok: true,
      status: init.method === "POST" ? 201 : 200,
      text: async () => (init.method === "POST" ? '{"ids":["m-1"]}' : '{"removed":0}'),
    };
  };
  return { calls, state, fetchLike };
}

/** A controllable budget clock: timers resolve only when the test expires their duration. */
function budgetClock() {
  const pending: { ms: number; resolve: () => void }[] = [];
  return {
    pending,
    sleep(ms: number): Promise<void> {
      return new Promise<void>((resolve) => pending.push({ ms, resolve }));
    },
    expire(ms: number): void {
      for (const timer of pending.filter((t) => t.ms === ms)) timer.resolve();
    },
  };
}

/** One owner over fresh state, with recorders for everything it touches. */
function harness(opts: { idle?: boolean; signal?: AbortSignal } = {}) {
  const annotations = createAnnotationState();
  const primes: string[][] = [];
  const gating = {
    primeDeferred(names: readonly string[]) {
      primes.push([...names]);
      return [...names];
    },
  };
  const fetch = recordingFetch(annotations);
  const clock = budgetClock();
  const session = fakeSession(opts);
  const owner = createBrowserOperationOwner(session.pi, {
    annotations,
    gating,
    status: createPerkStatus(),
    annotationDeps: { fetchLike: fetch.fetchLike },
    sleep: (ms) => clock.sleep(ms),
  });
  return { annotations, primes, fetch, clock, session, owner, ctx: session.ctx };
}

/** A spec over `ReviewOutcome` with a spy companion and a recording/deferrable `onDecision`. */
function makeSpec(
  start: BrowserOperationSpec<ReviewOutcome>["start"],
  opts: {
    scope?: string;
    applicable?: () => boolean;
    onDecision?: (out: ReviewOutcome) => Promise<void>;
  } = {},
) {
  const decisions: ReviewOutcome[] = [];
  const companion = {
    primes: 0,
    clears: 0,
    prime() {
      companion.primes += 1;
    },
    clear() {
      companion.clears += 1;
    },
  };
  const spec: BrowserOperationSpec<ReviewOutcome> = {
    scope: opts.scope ?? SCOPE,
    start,
    mode: "plan",
    primes: PRIMES,
    companion,
    ...(opts.applicable !== undefined ? { applicable: opts.applicable } : {}),
    degradeNotice: DEGRADE_NOTICE,
    settle: settleReviewOutcome,
    onDecision: async (out) => {
      decisions.push(out);
      await opts.onDecision?.(out);
    },
  };
  return { spec, decisions, companion };
}

/** The detach pushes recorded for a URL: the source-scoped DELETE then the marker POST. */
function markerCalls<C extends { url: string }>(calls: C[], url: string): C[] {
  return calls.filter((c) => c.url.startsWith(url));
}

const PLAN_FINDING = { phrase: "the draft", severity: "major", confidence: "high", body: "x" };

// ------------------------------------------------------------------ the marker texts

test("reviewDetachedStatus: the three causes share the two facts; only the cause and the cue differ", () => {
  const facts =
    "Reviewer findings will not arrive here and a decision here will not reach the session; ";
  assert.equal(
    reviewDetachedStatus("replaced"),
    `Perk detached this review — a newer browser review replaced it. ${facts}decide in the newer review.`,
  );
  assert.equal(
    reviewDetachedStatus("interrupted"),
    `Perk detached this review — its wait was interrupted (the turn was aborted). ${facts}re-run the door to review again.`,
  );
  assert.equal(
    reviewDetachedStatus("session-ended"),
    `Perk detached this review — the session reloaded or was replaced. ${facts}re-run the door from the current session.`,
  );
});

// ------------------------------------------------------------------ 13. settleReviewOutcome

test("settleReviewOutcome: completed → decided; unavailable → warning; aborted + the first-party arms → aborted", () => {
  assert.deepEqual(settleReviewOutcome(COMPLETED), { kind: "decided" });
  assert.deepEqual(
    settleReviewOutcome({ status: "completed", approved: false, reviewId: "r", feedback: "x" }),
    { kind: "decided" },
  );
  assert.deepEqual(settleReviewOutcome({ status: "unavailable", warning: "handshake timeout" }), {
    kind: "unavailable",
    warning: "handshake timeout",
  });
  assert.deepEqual(settleReviewOutcome({ status: "aborted" }), { kind: "aborted" });
  assert.deepEqual(settleReviewOutcome({ status: "dismissed" }), { kind: "aborted" });
  assert.deepEqual(settleReviewOutcome({ status: "implement-here", reviewId: "r" }), {
    kind: "aborted",
  });
});

test("budgets: the documented constants", () => {
  assert.equal(CONSOLE_QUIET_MS, 6_000);
  assert.equal(DETACH_MARKER_BUDGET_MS, 2_000);
  assert.equal(QUIESCE_BUDGET_MS, 3_000);
  assert.equal(DECISION_DRAIN_BUDGET_MS, 60_000);
  assert.equal(
    decisionDrainExpiredWarning(SCOPE),
    "a browser decision for /plan-review-browser is still being saved after 60 s — proceeding; " +
      "check the issue backend for this run id before saving again",
  );
  assert.equal(
    postDegradeDecisionWarning(SCOPE),
    "a browser decision arrived after the review degraded — ignored (nothing saved); re-run " +
      "/plan-review-browser to review the current draft",
  );
  assert.equal(
    detachedDecisionWarning("session-ended"),
    "a browser decision arrived for a detached browser review (session ended) — ignored; " +
      "nothing was saved",
  );
});

// ------------------------------------------------------------------ 1. start failure

test("open: a start failure reports the port-pick error, returns null, primes nothing — the predecessor was already detached", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  assert.deepEqual(await h.owner.open(h.ctx, specA.spec), { url: URL_A });
  a.readiness.resolve("ready");
  await flush();

  const b = fakeHandoff({ url: URL_B });
  b.rec.fail = new Error("port 45002 is in use");
  const specB = makeSpec(b.start);
  assert.equal(await h.owner.open(h.ctx, specB.spec), null);

  assert.equal(a.signal?.aborted, true, "detach-before-start: the predecessor was aborted");
  assert.ok(
    h.session.notifies.some(
      (n) => n.severity === "info" && n.message.includes("earlier browser review"),
    ),
    "the replacement line was reported even though the successor then failed",
  );
  const error = h.session.notifies.find((n) => n.severity === "error");
  assert.equal(
    error?.message,
    "perk: plan-review-browser — could not pick a free local port for the plannotator " +
      "plan-review server: port 45002 is in use",
  );
  assert.equal(h.annotations.surface, null, "nothing primed for the failed successor");
  assert.equal(specB.companion.primes, 0, "no companion prime");
  assert.equal(h.primes.length, 1, "only the predecessor primed its deferred tools");

  // `current` was released: a later open replaces nothing.
  const c = fakeHandoff({ url: URL_C });
  const before = h.session.notifies.length;
  assert.deepEqual(await h.owner.open(h.ctx, makeSpec(c.start).spec), { url: URL_C });
  assert.ok(
    !h.session.notifies.slice(before).some((n) => n.message.includes("earlier browser review")),
  );
});

// ------------------------------------------------------------------ 2. ordering

test("open: the predecessor is fully detached BEFORE the successor starts; the successor primes everything before open resolves", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  a.readiness.resolve("ready");
  await flush();

  const b = fakeHandoff({ url: URL_B });
  const atStart: { aAborted?: boolean; aQuiesced?: boolean; surface?: unknown; aClears?: number } =
    {};
  b.rec.onStart = () => {
    atStart.aAborted = a.signal?.aborted;
    atStart.aQuiesced = a.readiness.settled();
    atStart.surface = h.annotations.surface;
    atStart.aClears = specA.companion.clears;
  };
  const specB = makeSpec(b.start);
  const opened = await h.owner.open(h.ctx, specB.spec);
  assert.deepEqual(opened, { url: URL_B });
  assert.deepEqual(atStart, { aAborted: true, aQuiesced: true, surface: null, aClears: 1 });
  assert.deepEqual(h.annotations.surface, { mode: "plan", url: URL_B });
  assert.equal(specB.companion.primes, 1);
  assert.deepEqual(h.primes, [[...PRIMES], [...PRIMES]]);
});

test("open: the start signal composes the owner's abort with the opening turn's (AbortSignal.any)", async () => {
  const already = new AbortController();
  already.abort();
  const h1 = harness({ signal: already.signal });
  const a = fakeHandoff();
  await h1.owner.open(h1.ctx, makeSpec(a.start).spec);
  assert.equal(a.signal?.aborted, true, "an aborted turn at open → an already-aborted start");

  const turn = new AbortController();
  const h2 = harness({ signal: turn.signal });
  const b = fakeHandoff();
  await h2.owner.open(h2.ctx, makeSpec(b.start).spec);
  assert.equal(b.signal?.aborted, false);
  turn.abort();
  assert.equal(b.signal?.aborted, true, "a later turn abort aborts the start signal");
});

// ------------------------------------------------------------------ 3. overlapping opens

test("open: overlapping opens — B retired before it ever starts, A detached once, C starts and primes", async () => {
  const h = harness();
  const a = fakeHandoff();
  await h.owner.open(h.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("ready");
  await flush();
  h.fetch.state.mode = "hang";

  const b = fakeHandoff({ url: URL_B });
  const c = fakeHandoff({ url: URL_C });
  const specC = makeSpec(c.start);
  const openB = h.owner.open(h.ctx, makeSpec(b.start).spec);
  const openC = h.owner.open(h.ctx, specC.spec);
  await flush();
  assert.equal(b.calls, 0, "B never starts while A's marker push hangs");
  assert.equal(c.calls, 0);
  h.clock.expire(DETACH_MARKER_BUDGET_MS);
  assert.equal(await openB, null, "B was retired by C before it started");
  assert.deepEqual(await openC, { url: URL_C });
  assert.equal(b.calls, 0, "B's start was never called");
  assert.equal(c.calls, 1);
  assert.equal(a.signal?.aborted, true);
  assert.equal(
    markerCalls(h.fetch.calls, URL_A).length,
    1,
    "A's detach pushed once (its DELETE hung)",
  );
  assert.deepEqual(h.annotations.surface, { mode: "plan", url: URL_C });
  assert.equal(specC.companion.primes, 1);
});

test("shutdown during a pending start: the start signal aborts, open resolves null once the start returns, nothing primed, nothing reported after stale", async () => {
  const h = harness();
  const a = fakeHandoff();
  a.rec.gate = deferred<void>();
  const specA = makeSpec(a.start);
  const opening = h.owner.open(h.ctx, specA.spec);
  await flush();
  assert.equal(a.calls, 1, "the start is pending");
  const shutting = h.owner.shutdown(h.ctx, "reload");
  await flush();
  assert.equal(a.signal?.aborted, true, "the shutdown aborted the pending start");
  a.rec.gate.resolve();
  assert.equal(await opening, null);
  await shutting;
  h.session.stale();
  await flush();
  assert.equal(h.annotations.surface, null, "nothing primed");
  assert.equal(specA.companion.primes, 0);
  assert.deepEqual(h.primes, []);
  assert.equal(h.fetch.calls.length, 0, "no marker for a never-primed surface");
  assert.deepEqual(h.session.notifies, []);
  assert.deepEqual(h.session.sent, []);
});

// ------------------------------------------------------------------ 4. ready

for (const remote of [false, true]) {
  test(`ready: the up notice (${remote ? "remote" : "local"}) and the readiness flag; no continuation without pending work`, async () => {
    const h = harness();
    const a = fakeHandoff({ remote });
    await h.owner.open(h.ctx, makeSpec(a.start).spec);
    a.readiness.resolve("ready");
    await flush();
    assert.equal(h.session.notifies.length, 1);
    assert.equal(h.session.notifies[0]?.severity, "info");
    assert.match(
      h.session.notifies[0]?.message ?? "",
      /plannotator is up at http:\/\/127\.0\.0\.1:45001/,
    );
    assert.match(
      h.session.notifies[0]?.message ?? "",
      remote ? /tunnel or tailnet/ : /browser opening/,
    );
    assert.equal(h.annotations.ready, true);
    assert.deepEqual(h.session.sent, []);
  });
}

test("ready: one continuation with held work; a non-applicable review neither announces nor continues", async () => {
  for (const applicable of [true, false]) {
    const h = harness();
    const a = fakeHandoff();
    await h.owner.open(h.ctx, makeSpec(a.start, { applicable: () => applicable }).spec);
    h.fetch.state.mode = "network";
    const held = await executePushAnnotations(
      h.annotations,
      h.ctx,
      { angle: "correctness", findings: [PLAN_FINDING], replace: true },
      { fetchLike: h.fetch.fetchLike },
    );
    assert.equal(held.details.ok, true);
    a.readiness.resolve("ready");
    await flush();
    if (applicable) {
      assert.equal(h.session.sent.length, 1, "one continuation");
      assert.equal(h.annotations.ready, true);
    } else {
      assert.deepEqual(h.session.notifies, [], "no announce");
      assert.deepEqual(h.session.sent, [], "no continuation");
      assert.equal(h.annotations.ready, false);
    }
  }
});

// ------------------------------------------------------------------ 5. degrade — timeout

for (const idle of [true, false]) {
  test(`degrade (timeout, idle=${idle}): error + notice + both surfaces cleared; a later decision is ignored loudly`, async () => {
    const h = harness({ idle });
    const a = fakeHandoff();
    const specA = makeSpec(a.start);
    await h.owner.open(h.ctx, specA.spec);
    a.readiness.resolve("timeout");
    await flush();
    assert.equal(h.session.notifies.length, 1);
    assert.equal(h.session.notifies[0]?.severity, "error");
    assert.equal(
      h.session.notifies[0]?.message,
      "perk: plan-review-browser — the plannotator plan-review server did not become ready at " +
        "http://127.0.0.1:45001 — the browser review is unavailable",
    );
    assert.deepEqual(h.session.sent, [
      idle
        ? { message: DEGRADE_NOTICE }
        : { message: DEGRADE_NOTICE, options: { deliverAs: "followUp" } },
    ]);
    assert.equal(h.annotations.surface, null);
    assert.equal(specA.companion.clears, 1);

    a.bridge.resolve(COMPLETED);
    await flush();
    assert.equal(h.session.notifies.length, 2);
    assert.equal(h.session.notifies[1]?.severity, "warning");
    assert.ok(h.session.notifies[1]?.message.endsWith(postDegradeDecisionWarning(SCOPE)));
    assert.deepEqual(specA.decisions, [], "never routed");
  });
}

test("degrade (timeout): a non-applicable review's timeout is inert — no report, no notice, surfaces untouched", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start, { applicable: () => false });
  await h.owner.open(h.ctx, specA.spec);
  a.readiness.resolve("timeout");
  await flush();
  assert.deepEqual(h.session.notifies, []);
  assert.deepEqual(h.session.sent, []);
  assert.deepEqual(h.annotations.surface, { mode: "plan", url: URL_A });
  assert.equal(specA.companion.clears, 0);
});

// ------------------------------------------------------------------ 6. degrade — one owner

test("degrade (unavailable first): the decision task owns the terminal — warning + the degrade once; a later bridge_settled adds nothing", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  a.bridge.resolve({ status: "unavailable", warning: "plannotator reported error: Port in use" });
  await flush();
  assert.deepEqual(
    h.session.notifies.map((n) => [n.severity, n.message]),
    [
      ["error", "perk: plan-review-browser — plannotator reported error: Port in use"],
      [
        "error",
        "perk: plan-review-browser — the plannotator plan-review server did not become ready at " +
          "http://127.0.0.1:45001 — the browser review is unavailable",
      ],
    ],
  );
  assert.deepEqual(h.session.sent, [{ message: DEGRADE_NOTICE }]);
  assert.equal(h.annotations.surface, null);
  assert.equal(specA.companion.clears, 1);
  a.readiness.resolve("bridge_settled");
  await flush();
  assert.equal(h.session.notifies.length, 2, "no second error");
  assert.equal(h.session.sent.length, 1, "no second notice");
});

test("degrade (timeout first): the notice once from the timeout, then only the bridge's warning line", async () => {
  const h = harness();
  const a = fakeHandoff();
  await h.owner.open(h.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("timeout");
  await flush();
  a.bridge.resolve({ status: "unavailable", warning: "handshake timeout" });
  await flush();
  assert.deepEqual(
    h.session.notifies.map((n) => n.message),
    [
      "perk: plan-review-browser — the plannotator plan-review server did not become ready at " +
        "http://127.0.0.1:45001 — the browser review is unavailable",
      "perk: plan-review-browser — handshake timeout",
    ],
  );
  assert.equal(h.session.sent.length, 1, "the notice once");
});

test("bridge_settled + decided/aborted: the observer is silent (the decision task owns the settle)", async () => {
  for (const out of [COMPLETED, { status: "aborted" } as const]) {
    const h = harness();
    const a = fakeHandoff();
    await h.owner.open(h.ctx, makeSpec(a.start).spec);
    a.bridge.resolve(out);
    a.readiness.resolve("bridge_settled");
    await flush();
    assert.deepEqual(h.session.notifies, []);
    assert.deepEqual(h.session.sent, []);
  }
});

// ------------------------------------------------------------------ 7. replacement

for (const mode of ["ok", "reject", "network"] as const) {
  test(`replacement (${mode} push): A's tab gets the replaced marker silently, A's wait is aborted, B's surfaces survive A's close`, async () => {
    const h = harness();
    const a = fakeHandoff();
    const specA = makeSpec(a.start);
    await h.owner.open(h.ctx, specA.spec);
    a.readiness.resolve("ready");
    await flush();
    const baseline = h.session.notifies.length;
    h.fetch.state.mode = mode;

    const b = fakeHandoff({ url: URL_B });
    const specB = makeSpec(b.start);
    assert.deepEqual(await h.owner.open(h.ctx, specB.spec), { url: URL_B });
    h.fetch.state.mode = "ok";
    await flush();

    const pushed = markerCalls(h.fetch.calls, URL_A);
    assert.equal(pushed[0]?.method, "DELETE");
    assert.match(pushed[0]?.url ?? "", /\?source=perk%3Awave$/);
    if (mode === "ok" || mode === "network") {
      // A network failure after readiness retries in-call (no backoff) — the same unit.
      assert.equal(pushed.filter((c) => c.method === "DELETE").length, mode === "ok" ? 1 : 4);
    }
    if (mode === "ok") {
      assert.equal(pushed[1]?.method, "POST");
      const body = JSON.parse(pushed[1]?.body ?? "{}") as { annotations: unknown[] };
      assert.deepEqual(body.annotations, [
        {
          source: "perk:wave",
          author: "perk:wave",
          type: "GLOBAL_COMMENT",
          text: reviewDetachedStatus("replaced"),
        },
      ]);
      assert.equal(pushed.length, 2, "no interrupted push follows the owner's own abort");
    }
    const after = h.session.notifies.slice(baseline);
    assert.deepEqual(
      after.map((n) => [n.severity, n.message]),
      [
        [
          "info",
          "perk: plan-review-browser — the earlier browser review (plan-review-browser) was " +
            "replaced — its tab is marked detached and its decision will not be routed",
        ],
      ],
      "ONE info line; the push itself is muted whatever its outcome",
    );
    assert.equal(a.signal?.aborted, true);
    assert.equal(specA.companion.clears, 1, "A cleared its own companion before B primed");
    assert.deepEqual(h.annotations.surface, { mode: "plan", url: URL_B });
    assert.equal(specB.companion.primes, 1);
    assert.equal(specB.companion.clears, 0, "A's close never touches B's surfaces");

    // B proceeds normally.
    b.readiness.resolve("ready");
    b.bridge.resolve(COMPLETED);
    await flush();
    assert.ok(
      h.session.notifies.some((n) =>
        n.message.includes("plannotator is up at http://127.0.0.1:45002"),
      ),
    );
    assert.deepEqual(specB.decisions, [COMPLETED]);
    assert.deepEqual(specA.decisions, []);
  });
}

test("replacement: a hanging marker push is abandoned at the budget — B's open resolves", async () => {
  const h = harness();
  const a = fakeHandoff();
  await h.owner.open(h.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("ready");
  await flush();
  h.fetch.state.mode = "hang";
  const b = fakeHandoff({ url: URL_B });
  const openB = h.owner.open(h.ctx, makeSpec(b.start).spec);
  await flush();
  assert.equal(b.calls, 0);
  assert.ok(h.clock.pending.some((t) => t.ms === DETACH_MARKER_BUDGET_MS));
  h.clock.expire(DETACH_MARKER_BUDGET_MS);
  assert.deepEqual(await openB, { url: URL_B });
});

test("replacement: a decision racing the cutoff (during A's marker await) is ignored with one warning, never routed", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  a.readiness.resolve("ready");
  await flush();
  h.fetch.state.mode = "hang";
  const b = fakeHandoff({ url: URL_B });
  const openB = h.owner.open(h.ctx, makeSpec(b.start).spec);
  await flush();
  a.bridge.resolve(COMPLETED);
  await flush();
  assert.ok(
    h.session.notifies.some(
      (n) => n.severity === "warning" && n.message.endsWith(detachedDecisionWarning("replaced")),
    ),
  );
  assert.deepEqual(specA.decisions, [], "the cutoff held");
  h.clock.expire(DETACH_MARKER_BUDGET_MS);
  assert.deepEqual(await openB, { url: URL_B });
});

// ------------------------------------------------------------------ 8. external abort

for (const mode of ["ok", "reject", "network"] as const) {
  test(`external abort (${mode} push): silent in-session, the interrupted marker pushed BEFORE the clear, interception restored`, async () => {
    const turn = new AbortController();
    const h = harness({ signal: turn.signal });
    const original = console.error;
    const a = fakeHandoff();
    const specA = makeSpec(a.start);
    await h.owner.open(h.ctx, specA.spec);
    a.readiness.resolve("ready");
    await flush();
    const baseline = h.session.notifies.length;
    assert.notEqual(console.error, original, "interception is installed while the bridge waits");
    h.fetch.state.mode = mode;
    turn.abort();
    await flush(10);
    const pushed = markerCalls(h.fetch.calls, URL_A);
    assert.equal(pushed[0]?.method, "DELETE");
    assert.equal(pushed[0]?.primedAt, URL_A, "pushed while the surface was still primed");
    if (mode === "ok") {
      assert.match(
        pushed[1]?.body ?? "",
        new RegExp(reviewDetachedStatus("interrupted").slice(0, 40)),
      );
    }
    assert.deepEqual(h.session.notifies.slice(baseline), [], "silent in-session");
    assert.deepEqual(h.session.sent, []);
    assert.equal(h.annotations.surface, null, "then cleared");
    assert.equal(specA.companion.clears, 1);
    assert.equal(console.error, original, "interception restored");
  });
}

test("external abort of a REPLACED operation pushes nothing more", async () => {
  const turnA = new AbortController();
  const h = harness();
  const sessionA = fakeSession({ signal: turnA.signal });
  const a = fakeHandoff({ honourAbort: false });
  await h.owner.open(sessionA.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("ready");
  await flush();
  const b = fakeHandoff({ url: URL_B });
  await h.owner.open(h.ctx, makeSpec(b.start).spec);
  const pushes = h.fetch.calls.length;
  turnA.abort();
  a.bridge.resolve({ status: "aborted" });
  await flush();
  assert.equal(h.fetch.calls.length, pushes, "no interrupted push for a detached operation");
  assert.deepEqual(h.annotations.surface, { mode: "plan", url: URL_B });
});

// ------------------------------------------------------------------ 9. shutdown

test("shutdown (reload): the session-ended marker, the wait aborted, surfaces cleared — resolved only once readiness settled; late wakes after stale are silent", async () => {
  const h = harness();
  const a = fakeHandoff({ honourAbort: false });
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  let done = false;
  const shutting = h.owner.shutdown(h.ctx, "reload").then(() => {
    done = true;
  });
  await flush();
  const pushed = markerCalls(h.fetch.calls, URL_A);
  assert.deepEqual(
    pushed.map((c) => c.method),
    ["DELETE", "POST"],
    "the marker is attempted immediately, readiness or not",
  );
  assert.match(pushed[1]?.body ?? "", /the session reloaded or was replaced/);
  assert.equal(a.signal?.aborted, true);
  assert.equal(done, false, "shutdown waits for the readiness poll to quiesce");
  a.readiness.resolve("aborted");
  await shutting;
  assert.equal(h.annotations.surface, null);
  assert.equal(specA.companion.clears, 1);

  h.session.stale();
  a.bridge.resolve(COMPLETED);
  await flush();
  assert.deepEqual(specA.decisions, [], "a post-shutdown decision is never routed");
  assert.deepEqual(h.session.notifies, [], "no stale-ctx call (nothing threw, nothing reported)");
});

test("shutdown (quit): no push, same abort and clear", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  a.readiness.resolve("ready");
  await flush();
  await h.owner.shutdown(h.ctx, "quit");
  assert.equal(h.fetch.calls.length, 0);
  assert.equal(a.signal?.aborted, true);
  assert.equal(h.annotations.surface, null);
  assert.equal(specA.companion.clears, 1);
});

test("shutdown: no live operation → a no-op; a degraded operation → no push, abort + close", async () => {
  const idle = harness();
  await idle.owner.shutdown(idle.ctx, "reload");
  assert.equal(idle.fetch.calls.length, 0);

  const h = harness();
  const a = fakeHandoff();
  await h.owner.open(h.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("timeout");
  await flush();
  await h.owner.shutdown(h.ctx, "reload");
  assert.equal(h.fetch.calls.length, 0, "the degraded surface was already cleared");
  assert.equal(a.signal?.aborted, true);
  // Closed: a second shutdown has nothing to detach.
  await h.owner.shutdown(h.ctx, "reload");
  assert.equal(h.fetch.calls.length, 0);
});

test("shutdown: a hanging marker push resolves within the budget", async () => {
  const h = harness();
  const a = fakeHandoff();
  await h.owner.open(h.ctx, makeSpec(a.start).spec);
  a.readiness.resolve("ready");
  await flush();
  h.fetch.state.mode = "hang";
  const shutting = h.owner.shutdown(h.ctx, "new");
  await flush();
  h.clock.expire(DETACH_MARKER_BUDGET_MS);
  await shutting;
  assert.equal(a.signal?.aborted, true);
  assert.equal(h.annotations.surface, null);
});

// ------------------------------------------------------------------ 10. decision drain

test("drain: an in-flight decision holds shutdown AND a replacing open until it settles", async () => {
  for (const via of ["shutdown", "open"] as const) {
    const h = harness();
    const a = fakeHandoff();
    const saving = deferred<void>();
    const specA = makeSpec(a.start, { onDecision: () => saving.promise });
    await h.owner.open(h.ctx, specA.spec);
    a.readiness.resolve("ready");
    a.bridge.resolve(COMPLETED);
    await flush();
    assert.deepEqual(specA.decisions, [COMPLETED], "the decision was admitted");
    let done = false;
    const b = fakeHandoff({ url: URL_B });
    const pending =
      via === "shutdown"
        ? h.owner.shutdown(h.ctx, "reload")
        : h.owner.open(h.ctx, makeSpec(b.start).spec);
    void pending.then(() => {
      done = true;
    });
    await flush();
    assert.equal(done, false, `${via} waits for the admitted save`);
    assert.equal(b.calls, 0);
    saving.resolve();
    await pending;
    assert.equal(h.fetch.calls.length, 0, "a routed decision closed the op — no marker push");
  }
});

test("drain: a decided outcome after the cutoff (during the quiesce wait) is warned, never routed", async () => {
  const h = harness();
  const a = fakeHandoff({ honourAbort: false });
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  const shutting = h.owner.shutdown(h.ctx, "reload");
  await flush();
  a.bridge.resolve(COMPLETED);
  await flush();
  assert.ok(
    h.session.notifies.some(
      (n) =>
        n.severity === "warning" && n.message.endsWith(detachedDecisionWarning("session-ended")),
    ),
  );
  assert.deepEqual(specA.decisions, []);
  a.readiness.resolve("aborted");
  await shutting;
});

test("drain: a save outliving the budget → one warning naming the run-id check; shutdown proceeds", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start, { onDecision: () => new Promise<void>(() => {}) });
  await h.owner.open(h.ctx, specA.spec);
  a.readiness.resolve("ready");
  a.bridge.resolve(COMPLETED);
  await flush();
  const shutting = h.owner.shutdown(h.ctx, "reload");
  await flush();
  h.clock.expire(DECISION_DRAIN_BUDGET_MS);
  await shutting;
  assert.ok(
    h.session.notifies.some(
      (n) => n.severity === "warning" && n.message.endsWith(decisionDrainExpiredWarning(SCOPE)),
    ),
  );
  assert.equal(a.signal?.aborted, true);
  assert.equal(h.annotations.surface, null, "closed");
});

// ------------------------------------------------------------------ 11. decided / throwing

test("decided → onDecision once, surfaces cleared after; a throwing onDecision → one error report, still cleared, interception restored", async () => {
  const h = harness();
  const a = fakeHandoff();
  const specA = makeSpec(a.start);
  await h.owner.open(h.ctx, specA.spec);
  a.bridge.resolve(COMPLETED);
  await flush();
  assert.deepEqual(specA.decisions, [COMPLETED]);
  assert.equal(h.annotations.surface, null);
  assert.equal(specA.companion.clears, 1);

  const original = console.error;
  const t = harness();
  const b = fakeHandoff();
  const specB = makeSpec(b.start, {
    onDecision: async () => {
      throw new Error("boom");
    },
  });
  await t.owner.open(t.ctx, specB.spec);
  b.bridge.resolve(COMPLETED);
  await flush();
  assert.deepEqual(
    t.session.notifies.map((n) => [n.severity, n.message]),
    [["error", "perk: plan-review-browser — the browser decision task failed: boom"]],
  );
  assert.equal(t.annotations.surface, null);
  assert.equal(specB.companion.clears, 1);
  assert.equal(console.error, original);
});

// ------------------------------------------------------------------ 12. console interception

test("console interception: a setup line while the bridge waits → an info report; restored after settle; after shutdown → the original console.error", async () => {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    const h = harness();
    const a = fakeHandoff();
    await h.owner.open(h.ctx, makeSpec(a.start).spec);
    console.error("x");
    assert.deepEqual(h.session.notifies, [
      { message: "perk: plan-review-browser — x", severity: "info" },
    ]);
    a.bridge.resolve(COMPLETED);
    await flush();
    console.error("after settle");
    assert.deepEqual(lines, ["after settle"], "restored once the bridge settled");

    const s = harness();
    const b = fakeHandoff();
    await s.owner.open(s.ctx, makeSpec(b.start).spec);
    b.readiness.resolve("ready");
    await flush();
    await s.owner.shutdown(s.ctx, "quit");
    s.session.stale();
    console.error("late");
    assert.deepEqual(lines, ["after settle", "late"], "a post-shutdown line reaches the original");
  } finally {
    console.error = original;
  }
});
