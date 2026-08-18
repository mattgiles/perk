import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import {
  CHECK_POLL_INTERVAL_MS,
  type CheckRunView,
  type CheckSessionState,
  createCheckSession,
} from "./src/checkSession.ts";
import type { CheckRun } from "./src/checks.ts";
import type { DocumentLike } from "./src/mutationRequest.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

function run(overrides: Partial<CheckRun> = {}): CheckRun {
  return {
    run: "run-1",
    check: "prose-map",
    label: "Prose map check",
    command: "uv run --no-sync perk-dev prose-map check",
    status: "running",
    exit_code: null,
    output: "",
    next_offset: 0,
    truncated: false,
    ...overrides,
  };
}

function viewOf(source: CheckRun, overrides: Partial<CheckRunView> = {}): CheckRunView {
  return {
    run: source.run,
    check: source.check,
    label: source.label,
    command: source.command,
    status: source.status,
    exitCode: source.exit_code,
    output: source.output,
    truncated: source.truncated,
    ...overrides,
  };
}

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

type PendingRequest = {
  url: string;
  init: RequestInit | undefined;
  respond: (response: ResponseLike) => void;
  fail: (error: Error) => void;
};

function documentWithToken(token: string | null): DocumentLike {
  return {
    querySelector: (selector) =>
      selector === 'meta[name="csrf-token"]' && token !== null
        ? { getAttribute: () => token }
        : null,
  };
}

function harness(token: string | null = "test-token") {
  const pending: PendingRequest[] = [];
  const fetchFn: FetchLike = (url, init) => {
    let respondWith!: (response: ResponseLike) => void;
    let fail!: (error: Error) => void;
    const promise = new Promise<ResponseLike>((resolve, reject) => {
      respondWith = resolve;
      fail = reject;
    });
    pending.push({ url, init, respond: respondWith, fail });
    return promise;
  };
  const scheduled: { callback: () => void; ms: number }[] = [];
  const states: CheckSessionState[] = [];
  const session = createCheckSession({
    onState: (state) => states.push(state),
    fetchFn,
    documentRoot: documentWithToken(token),
    schedule: (callback, ms) => scheduled.push({ callback, ms }),
  });
  return { session, states, pending, scheduled };
}

function lastState(states: CheckSessionState[]): CheckSessionState {
  const state = states[states.length - 1];
  assert.ok(state !== undefined, "no state emitted");
  return state;
}

function lastRequest(pending: PendingRequest[]): PendingRequest {
  const request = pending[pending.length - 1];
  assert.ok(request !== undefined, "no request issued");
  return request;
}

function runScheduled(h: ReturnType<typeof harness>): void {
  const next = h.scheduled.shift();
  assert.ok(next !== undefined, "no poll scheduled");
  assert.equal(next.ms, CHECK_POLL_INTERVAL_MS);
  next.callback();
}

test("start adopts the run, polls with the growing offset, and retires on terminal", async () => {
  const h = harness();
  h.session.start("prose-map");
  const post = lastRequest(h.pending);
  assert.equal(post.url, "/api/checks/run");
  assert.equal(post.init?.method, "POST");
  assert.equal((post.init?.headers as Record<string, string>)["X-Prose-Review-Csrf"], "test-token");
  assert.deepEqual(JSON.parse(String(post.init?.body)), { check: "prose-map" });

  post.respond(respond(200, run({ output: "a\n", next_offset: 2 })));
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: viewOf(run(), { output: "a\n" }),
    history: [],
    notice: null,
  });

  runScheduled(h);
  const firstPoll = lastRequest(h.pending);
  assert.equal(firstPoll.url, "/api/checks/run/run-1?offset=2");
  firstPoll.respond(respond(200, run({ output: "b\n", next_offset: 4 })));
  await tick();
  assert.equal(lastState(h.states).active?.output, "a\nb\n");

  runScheduled(h);
  const finalPoll = lastRequest(h.pending);
  assert.equal(finalPoll.url, "/api/checks/run/run-1?offset=4");
  finalPoll.respond(
    respond(200, run({ status: "passed", exit_code: 0, output: "", next_offset: 4 })),
  );
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(run(), { status: "passed", exitCode: 0, output: "a\nb\n" })],
    notice: null,
  });
  assert.equal(h.scheduled.length, 0, "terminal runs stop scheduling");
});

test("a missing token is not-sent: no fetch leaves the browser", () => {
  const h = harness(null);
  h.session.start("ruff");
  assert.equal(h.pending.length, 0);
  assert.deepEqual(lastState(h.states), { active: null, history: [], notice: "not-sent" });
});

test("409 adopts an unknown latest run as active and polls it", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(409, { detail: "check already running" }));
  await tick();
  const reconcile = lastRequest(h.pending);
  assert.equal(reconcile.url, "/api/checks/latest");
  const foreign = run({ run: "foreign-1", output: "busy work\n", next_offset: 10 });
  reconcile.respond(respond(200, { run: foreign }));
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: viewOf(foreign),
    history: [],
    notice: null,
  });
  runScheduled(h);
  assert.equal(lastRequest(h.pending).url, "/api/checks/run/foreign-1?offset=10");
});

test("409 adopts an unknown terminal latest run straight into history", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(409, { detail: "check already running" }));
  await tick();
  const foreign = run({ run: "foreign-2", status: "failed", exit_code: 1, output: "boom\n" });
  lastRequest(h.pending).respond(respond(200, { run: foreign }));
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(foreign)],
    notice: null,
  });
  assert.equal(h.scheduled.length, 0);
});

test("409 with an already-known latest run is the busy notice", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run()));
  await tick();

  h.session.start("ruff");
  lastRequest(h.pending).respond(respond(409, { detail: "check already running" }));
  await tick();
  lastRequest(h.pending).respond(respond(200, { run: run() }));
  await tick();
  const state = lastState(h.states);
  assert.equal(state.notice, "busy");
  assert.equal(state.active?.run, "run-1", "the active run survives a refused start");
});

test("an indeterminate start reconciles through latest before reporting failure", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).fail(new Error("network down"));
  await tick();
  const reconcile = lastRequest(h.pending);
  assert.equal(reconcile.url, "/api/checks/latest");
  // The fast run went terminal before the client could ask: adopted, not an error.
  const fast = run({ run: "fast-1", status: "passed", exit_code: 0, output: "done\n" });
  reconcile.respond(respond(200, { run: fast }));
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(fast)],
    notice: null,
  });
});

test("a failed start with no latest run is the start-failed notice", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(500, { detail: "boom" }));
  await tick();
  lastRequest(h.pending).respond(respond(200, { run: null }));
  await tick();
  assert.deepEqual(lastState(h.states), { active: null, history: [], notice: "start-failed" });
});

test("the cancel response body is ignored: polling stays the one writer", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run({ output: "a\n", next_offset: 2 })));
  await tick();
  const emitted = h.states.length;

  h.session.cancel();
  const cancelPost = lastRequest(h.pending);
  assert.equal(cancelPost.url, "/api/checks/run/run-1/cancel");
  assert.equal(cancelPost.init?.method, "POST");
  // A hostile/duplicate body must not double-record or drop output.
  cancelPost.respond(
    respond(200, run({ status: "cancelled", output: "REPLACED", next_offset: 8 })),
  );
  await tick();
  assert.equal(h.states.length, emitted, "cancel acknowledgment emits nothing");

  runScheduled(h);
  lastRequest(h.pending).respond(
    respond(200, run({ status: "cancelled", output: "", next_offset: 2 })),
  );
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(run(), { status: "cancelled", output: "a\n" })],
    notice: null,
  });
});

test("a poll 404 retires the run as lost with the run-lost notice", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run({ output: "a\n", next_offset: 2 })));
  await tick();
  runScheduled(h);
  lastRequest(h.pending).respond(respond(404, { detail: "unknown check run" }));
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(run(), { status: "lost", output: "a\n" })],
    notice: "run-lost",
  });
  assert.equal(h.scheduled.length, 0, "a lost run never re-polls");
});

test("a cancel 404 retires the run as lost like a poll 404", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run()));
  await tick();
  h.session.cancel();
  lastRequest(h.pending).respond(respond(404, { detail: "unknown check run" }));
  await tick();
  const state = lastState(h.states);
  assert.equal(state.active, null);
  assert.equal(state.history[0]?.status, "lost");
  assert.equal(state.notice, "run-lost");
});

test("transient poll failures skip the update and keep polling", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run({ output: "a\n", next_offset: 2 })));
  await tick();
  const emitted = h.states.length;

  runScheduled(h);
  lastRequest(h.pending).fail(new Error("connection reset"));
  await tick();
  assert.equal(h.states.length, emitted, "a skipped update emits nothing");

  runScheduled(h);
  lastRequest(h.pending).respond(respond(500, { detail: "boom" }));
  await tick();
  runScheduled(h);
  lastRequest(h.pending).respond(respond(200, { nonsense: true }));
  await tick();
  assert.equal(h.states.length, emitted);

  runScheduled(h);
  lastRequest(h.pending).respond(
    respond(200, run({ status: "passed", exit_code: 0, output: "b\n", next_offset: 4 })),
  );
  await tick();
  assert.deepEqual(lastState(h.states), {
    active: null,
    history: [viewOf(run(), { status: "passed", exitCode: 0, output: "a\nb\n" })],
    notice: null,
  });
});

test("dispose makes every scheduled poll and in-flight completion a no-op", async () => {
  const h = harness();
  h.session.start("prose-map");
  lastRequest(h.pending).respond(respond(200, run({ output: "a\n", next_offset: 2 })));
  await tick();
  runScheduled(h);
  const inFlight = lastRequest(h.pending);

  h.session.dispose();
  const requests = h.pending.length;
  const emitted = h.states.length;
  inFlight.respond(
    respond(200, run({ status: "passed", exit_code: 0, output: "b\n", next_offset: 4 })),
  );
  await tick();
  assert.equal(h.states.length, emitted, "an in-flight completion after dispose is dropped");
  assert.equal(h.pending.length, requests, "no further requests after dispose");
});

test("adoptLatest adopts only a running run and ignores terminal or null", async () => {
  const terminalHarness = harness();
  terminalHarness.session.adoptLatest();
  lastRequest(terminalHarness.pending).respond(
    respond(200, { run: run({ status: "passed", exit_code: 0 }) }),
  );
  await tick();
  assert.equal(terminalHarness.states.length, 0, "terminal latest is ignored on mount");

  const nullHarness = harness();
  nullHarness.session.adoptLatest();
  lastRequest(nullHarness.pending).respond(respond(200, { run: null }));
  await tick();
  assert.equal(nullHarness.states.length, 0);

  const reloadHarness = harness();
  reloadHarness.session.adoptLatest();
  const live = run({ run: "reloaded-1", output: "mid-run\n", next_offset: 8 });
  lastRequest(reloadHarness.pending).respond(respond(200, { run: live }));
  await tick();
  assert.deepEqual(lastState(reloadHarness.states), {
    active: viewOf(live),
    history: [],
    notice: null,
  });
  runScheduled(reloadHarness);
  assert.equal(lastRequest(reloadHarness.pending).url, "/api/checks/run/reloaded-1?offset=8");
});

test("getState returns the current snapshot and history is capped at 20", async () => {
  const h = harness();
  assert.deepEqual(h.session.getState(), { active: null, history: [], notice: null });
  for (let index = 0; index < 23; index += 1) {
    h.session.start("ruff");
    lastRequest(h.pending).respond(
      respond(200, run({ run: `run-${index}`, check: "ruff", status: "passed", exit_code: 0 })),
    );
    await tick();
  }
  const state = h.session.getState();
  assert.equal(state.history.length, 20);
  assert.equal(state.history[0]?.run, "run-22", "history is newest-first");
  assert.equal(state.history[19]?.run, "run-3");
  assert.deepEqual(h.session.getState(), lastState(h.states));
});
