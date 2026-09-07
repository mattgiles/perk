import assert from "node:assert/strict";
import { getEventListeners } from "node:events";
import { test } from "node:test";
import type { DraftReviewRegistration } from "../../../session/draftReviewState.ts";
import { recordingDraftRegistration } from "../../../testing/draftReview.ts";
import {
  createPlannotatorBridge,
  type PlannotatorBus,
  type PlannotatorTimers,
  queryPlannotatorReviewStatus,
  requestPlannotatorPlanReview,
} from "./plannotator.ts";
import { startPlannotatorPlanReview } from "./plannotatorHandoff.ts";

type Envelope = {
  requestId: string;
  action: string;
  payload: unknown;
  respond(value: unknown): void;
};
const pending = { status: "handled", result: { status: "pending", reviewId: "review" } };
const decision = { reviewId: "review", approved: true, feedback: " \n雪 feedback\n " };
const completed = { status: "handled", result: { status: "completed", ...decision } };
function timers() {
  const pending = new Map<ReturnType<typeof setTimeout>, { callback(): void; ms: number }>();
  const delays: number[] = [];
  const clock: PlannotatorTimers = {
    setTimeout(callback, ms) {
      // Handles carry identity only; no wall-clock timer is allocated.
      const handle = {} as ReturnType<typeof setTimeout>;
      pending.set(handle, { callback, ms });
      delays.push(ms);
      return handle;
    },
    clearTimeout(handle) {
      assert.ok(pending.delete(handle), "each timer disposed once");
    },
  };
  return {
    clock,
    pending,
    delays,
    fire() {
      const entry = pending.values().next().value;
      assert.ok(entry);
      entry.callback();
    },
  };
}
function fixture() {
  const requests: Envelope[] = [];
  const listeners = new Set<(value: unknown) => void>();
  const trace: string[] = [];
  const timer = timers();
  const abort = new AbortController();
  let onRequest: (request: Envelope) => void = (request) => {
    if (request.action === "plan-review") request.respond(pending);
  };
  let duringSubscribe: (() => void) | undefined;
  let disposed = 0;
  const bus: PlannotatorBus = {
    emit(channel, raw) {
      assert.equal(channel, "plannotator:request");
      const request = raw as Envelope;
      requests.push(request);
      trace.push(request.action);
      onRequest(request);
    },
    on(channel, listener) {
      assert.equal(channel, "plannotator:review-result");
      trace.push("subscribe");
      listeners.add(listener);
      duringSubscribe?.();
      return () => {
        disposed++;
        listeners.delete(listener);
      };
    },
  };
  const registration: DraftReviewRegistration = {
    open() {
      trace.push("open");
      return { ok: true };
    },
    attach() {
      trace.push("attach");
      return { ok: true };
    },
    invalidateOpening(_id, reason) {
      trace.push(reason);
      return { ok: true };
    },
    subscriptionFailed() {
      trace.push("subscription-failed");
      return { ok: true };
    },
    diagnostic(code) {
      trace.push(`diagnostic:${code}`);
    },
  };
  const live = (value: unknown = decision) => {
    for (const listener of [...listeners]) listener(value);
  };
  return {
    bus,
    registration,
    requests,
    trace,
    timer,
    abort,
    live,
    listeners,
    get disposed() {
      return disposed;
    },
    request(handler: typeof onRequest) {
      onRequest = handler;
    },
    subscribe(handler: () => void) {
      duringSubscribe = handler;
    },
    start() {
      return requestPlannotatorPlanReview(
        bus,
        "# Exact 雪\n",
        registration,
        abort.signal,
        timer.clock,
      );
    },
    clean() {
      assert.equal(timer.pending.size, 0);
      assert.equal(listeners.size, 0);
      assert.equal(getEventListeners(abort.signal, "abort").length, 0);
    },
  };
}

test("exact open → emit → attach → subscribe → status; separately minted request IDs; status catches missed event", async () => {
  const f = fixture();
  f.request((request) => {
    if (request.action === "plan-review") {
      request.respond(pending);
      f.live();
    } else request.respond(completed);
  });
  assert.deepEqual(await f.start(), { status: "completed", ...decision });
  assert.deepEqual(f.trace, ["open", "plan-review", "attach", "subscribe", "review-status"]);
  const [open, query] = f.requests;
  assert.ok(open && query);
  assert.deepEqual(Object.keys(open), ["requestId", "action", "payload", "respond"]);
  assert.deepEqual(open.payload, { planContent: "# Exact 雪\n", origin: "perk" });
  assert.deepEqual(query.payload, { reviewId: "review" });
  assert.notEqual(open.requestId, query.requestId);
  for (const request of f.requests) assert.match(request.requestId, /^[0-9a-f-]{36}$/);
  assert.deepEqual(f.timer.delays, [5000, 5000]);
  assert.equal(f.disposed, 1);
  f.clean();
});

for (const first of ["live", "status"] as const)
  test(`first settle wins conflicting ${first} → other, duplicates and post-candidate abort`, async () => {
    const f = fixture();
    f.request((request) => {
      if (request.action === "plan-review") {
        request.respond(pending);
        return;
      }
      if (first === "live") f.live({ ...decision, approved: false });
      request.respond(completed);
      f.live({ ...decision, approved: false });
      request.respond(completed);
      f.abort.abort();
    });
    assert.deepEqual(await f.start(), {
      status: "completed",
      ...decision,
      approved: first === "status",
    });
    f.clean();
  });

test("synchronous delivery inside on() settles and disposes its late-returned handle; no status query", async () => {
  const f = fixture();
  f.subscribe(() => f.live());
  assert.deepEqual(await f.start(), { status: "completed", ...decision });
  assert.equal(f.requests.length, 1);
  assert.equal(f.disposed, 1);
  f.clean();
});

for (const [phase, hook] of [
  ["open", "open"],
  ["attach", "attach"],
  ["invalidate", "invalidateOpening"],
  ["subscribe", "subscriptionFailed"],
] as const) {
  for (const throws of [false, true])
    test(`${phase} ${throws ? "throw" : "refusal"} is typed and never falls through`, async () => {
      const f = fixture();
      f.registration[hook] = () => {
        if (throws) throw new Error("hook");
        return { ok: false, reason: "busy", detail: "retained" };
      };
      if (phase === "invalidate") f.request((request) => request.respond(null));
      if (phase === "subscribe")
        f.bus.on = () => {
          throw new Error("on failed");
        };
      const outcome = await f.start();
      assert.equal(outcome.status, "refused");
      if (outcome.status !== "refused") assert.fail("must refuse");
      assert.equal(outcome.phase, phase);
      assert.equal(outcome.code, throws ? "persistence-failed" : "busy");
      assert.equal(f.requests.length, phase === "open" ? 0 : 1);
      f.clean();
    });
}

for (const response of [
  null,
  "handled",
  1,
  [],
  {},
  { status: "handled", result: { status: "pending", reviewId: " " } },
  { status: "error", error: "failure" },
  { status: "unavailable" },
  Object.defineProperty({}, "status", {
    get() {
      throw new Error("getter");
    },
  }),
]) {
  test(`malformed/error handshake invalidates, never subscribes: ${String(response)}`, async () => {
    const f = fixture();
    f.request((request) => request.respond(response));
    assert.equal((await f.start()).status, "unavailable");
    assert.deepEqual(f.trace, ["open", "plan-review", "handshake-failed"]);
    f.clean();
  });
}

test("request emit throw and handshake deadline both invalidate and clear resources", async () => {
  for (const mode of ["throw", "timeout"]) {
    const f = fixture();
    f.request(() => {
      if (mode === "throw") throw Object.create(null);
    });
    const wait = f.start();
    if (mode === "timeout") f.timer.fire();
    assert.equal((await wait).status, "unavailable");
    assert.equal(f.trace.at(-1), "handshake-failed");
    f.clean();
  }
});

for (const gap of [
  "pre",
  "open",
  "handshake",
  "known-id",
  "attach",
  "subscribe",
  "status",
] as const)
  test(`abort at ${gap} boundary obeys known-ID ordering`, async () => {
    const f = fixture();
    if (gap === "pre") f.abort.abort();
    if (gap === "open") {
      const open = f.registration.open;
      f.registration.open = (id) => {
        const result = open(id);
        f.abort.abort();
        return result;
      };
    }
    if (gap === "handshake" || gap === "known-id")
      f.request((request) => {
        if (gap === "known-id") request.respond(pending);
        f.abort.abort();
        request.respond(pending);
      });
    if (gap === "attach") {
      const attach = f.registration.attach;
      f.registration.attach = (id, review) => {
        const result = attach(id, review);
        f.abort.abort();
        return result;
      };
    }
    if (gap === "subscribe") f.subscribe(() => f.abort.abort());
    if (gap === "status")
      f.request((request) => {
        if (request.action === "plan-review") request.respond(pending);
        else f.abort.abort();
      });
    assert.deepEqual(await f.start(), { status: "aborted" });
    if (gap === "pre") assert.deepEqual(f.trace, []);
    else if (gap === "open" || gap === "handshake") assert.equal(f.trace.at(-1), "opening-aborted");
    else assert.ok(f.trace.includes("attach"), "known correlation attached before abort");
    if (["known-id", "attach"].includes(gap)) assert.ok(!f.trace.includes("subscribe"));
    f.clean();
  });

test("subscription that emits then throws never returns its unregistered candidate", async () => {
  const f = fixture();
  let callback: ((value: unknown) => void) | undefined;
  f.bus.on = (_channel, listener) => {
    callback = listener;
    listener(decision);
    throw new Error("setup failed");
  };
  assert.equal((await f.start()).status, "unavailable");
  assert.ok(f.trace.includes("subscription-failed"));
  callback?.(decision);
  f.clean();
});

test("aborted opening cleanup refusal overrides aborted; late handshake getters are ignored", async () => {
  const f = fixture();
  f.request(() => {});
  f.registration.invalidateOpening = () => ({
    ok: false,
    reason: "persistence-failed",
    detail: "unverified invalidation",
  });
  const wait = f.start();
  f.abort.abort();
  const outcome = await wait;
  assert.equal(outcome.status, "refused");
  if (outcome.status !== "refused") assert.fail("cleanup must override abort");
  assert.equal(outcome.phase, "invalidate");
  let accessed = false;
  f.requests[0]?.respond({
    get status() {
      accessed = true;
      throw new Error("late");
    },
  });
  assert.equal(accessed, false);
  f.clean();
});

test("subscription failure invalidates pending; successful cleanup preserves unavailable", async () => {
  const f = fixture();
  f.bus.on = () => {
    throw new Error("subscribe");
  };
  assert.equal((await f.start()).status, "unavailable");
  assert.deepEqual(f.trace, ["open", "plan-review", "attach", "subscription-failed"]);
  f.clean();
});

const statusCases: [unknown, unknown][] = [
  [completed, { status: "completed", ...decision }],
  [{ status: "handled", result: { status: "pending" } }, { status: "pending" }],
  [{ status: "handled", result: { status: "missing" } }, { status: "missing" }],
  [{ status: "unavailable" }, { status: "failed", code: "unavailable" }],
  [{ status: "error" }, { status: "failed", code: "transport-error" }],
  ...[
    null,
    7,
    [],
    "completed",
    {},
    { status: "handled" },
    { status: "handled", result: { status: "completed", reviewId: "other", approved: true } },
    { status: "handled", result: { status: "completed", reviewId: "review", approved: "yes" } },
    Object.defineProperty({}, "status", {
      get() {
        throw new Error("getter");
      },
    }),
    {
      status: "handled",
      get result() {
        throw new Error("nested getter");
      },
    },
    {
      status: "handled",
      result: {
        status: "completed",
        reviewId: "review",
        get approved() {
          throw new Error("approved getter");
        },
      },
    },
  ].map((input): [unknown, unknown] => [input, { status: "failed", code: "malformed" }]),
];
for (const [index, [response, expected]] of statusCases.entries())
  test(`public status query exact boundary case ${index}`, async () => {
    const f = fixture();
    f.request((request) => request.respond(response));
    assert.deepEqual(
      await queryPlannotatorReviewStatus(f.bus, "review", f.abort.signal, f.timer.clock),
      expected,
    );
    assert.deepEqual(f.requests[0]?.payload, { reviewId: "review" });
    assert.equal(f.requests[0]?.action, "review-status");
    f.clean();
  });

for (const code of [
  "pending",
  "missing",
  "unavailable",
  "malformed",
  "timeout",
  "transport-error",
] as const)
  test(`${code} query leaves cancellable live wait; later real completion remains eligible`, async () => {
    const f = fixture();
    f.request((request) => {
      if (request.action === "plan-review") {
        request.respond(pending);
        return;
      }
      if (code === "transport-error") throw new Error("query transport");
      if (code === "timeout") return;
      request.respond(
        code === "unavailable"
          ? { status: "unavailable" }
          : code === "malformed"
            ? null
            : { status: "handled", result: { status: code } },
      );
    });
    const wait = f.start();
    await Promise.resolve();
    if (code === "timeout") f.timer.fire();
    assert.equal(f.listeners.size, 1);
    assert.equal(f.trace.filter((item) => item === `diagnostic:${code}`).length, 1);
    for (const malformed of [
      null,
      [],
      {},
      { reviewId: "other", approved: true },
      { ...decision, approved: "true" },
      {
        ...decision,
        get feedback() {
          throw new Error("getter");
        },
      },
    ])
      f.live(malformed);
    assert.equal(f.listeners.size, 1);
    f.live();
    assert.deepEqual(await wait, { status: "completed", ...decision });
    f.clean();
  });

test("status timeout is fixed at 5s, independent from handshake override; pending/missing never reconstruct approval", async () => {
  const prior = process.env.PERK_PLANNOTATOR_HANDSHAKE_MS;
  process.env.PERK_PLANNOTATOR_HANDSHAKE_MS = "37";
  try {
    const f = fixture();
    const wait = f.start();
    await Promise.resolve();
    assert.deepEqual(f.timer.delays, [37, 5000]);
    f.timer.fire();
    assert.equal(f.listeners.size, 1);
    f.abort.abort();
    assert.deepEqual(await wait, { status: "aborted" });
    f.clean();
  } finally {
    if (prior === undefined) delete process.env.PERK_PLANNOTATOR_HANDSHAKE_MS;
    else process.env.PERK_PLANNOTATOR_HANDSHAKE_MS = prior;
  }
});

test("query pre-abort emits nothing; in-flight abort clears deadline and ignores late getters", async () => {
  for (const pre of [true, false]) {
    const f = fixture();
    if (pre) f.abort.abort();
    const query = queryPlannotatorReviewStatus(f.bus, "review", f.abort.signal, f.timer.clock);
    f.abort.abort();
    assert.deepEqual(await query, { status: "aborted" });
    let read = false;
    f.requests[0]?.respond({
      get status() {
        read = true;
        throw new Error("late getter");
      },
    });
    assert.equal(read, false);
    assert.equal(f.requests.length, pre ? 0 : 1);
    f.clean();
  }
});

test("diagnostic sink throw is reported safely, never a verdict or broken live wait", async (t) => {
  const logged: unknown[][] = [];
  t.mock.method(console, "error", (...args: unknown[]) => logged.push(args));
  const f = fixture();
  f.registration.diagnostic = () => {
    throw new Error("sink");
  };
  f.request((request) => request.respond(request.action === "plan-review" ? pending : null));
  const wait = f.start();
  await Promise.resolve();
  assert.equal(logged.length, 1);
  f.live();
  assert.equal((await wait).status, "completed");
  f.clean();
});

test("bridge factory threads mandatory hooks; browser start captures sync open refusal before probing", async () => {
  const f = fixture();
  f.registration.open = () => ({ ok: false, reason: "busy", detail: "retained lock" });
  const expected = { status: "refused", code: "busy", detail: "retained lock", phase: "open" };
  assert.deepEqual(await createPlannotatorBridge(f.bus).review("draft", f.registration), expected);
  const prior = process.env.PLANNOTATOR_PORT;
  const started = await startPlannotatorPlanReview(
    f.bus,
    { plan: "draft", registration: f.registration },
    {
      pickFreePort: async () => 12345,
      probe: async () => {
        assert.fail("refusal must not probe");
      },
    },
  );
  assert.deepEqual(started, expected);
  assert.equal(process.env.PLANNOTATOR_PORT, prior);
  assert.equal(f.requests.length, 0);
});

test("browser start hook throw becomes persistence-failed, not port failure", async () => {
  const f = fixture();
  const { registration } = recordingDraftRegistration();
  registration.open = () => {
    throw new Error("storage");
  };
  const started = await startPlannotatorPlanReview(
    f.bus,
    { plan: "draft", registration },
    { pickFreePort: async () => 12345, probe: async () => assert.fail("no probe") },
  );
  assert.ok("status" in started);
  assert.equal(started.code, "persistence-failed");
  assert.equal(started.phase, "open");
});
