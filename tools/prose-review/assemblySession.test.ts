import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { AssemblyOptions, AssemblyRender, AssemblyScenario } from "./src/assembly.ts";
import { type AssemblySessionState, createAssemblySession } from "./src/assemblySession.ts";
import type { WorkspaceBufferExport } from "./src/editWorkspace.ts";
import type { DocumentLike } from "./src/mutationRequest.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

const WARM: AssemblyScenario = {
  id: "scenario:warm",
  label: "Warm defaults",
  variables: { plan: "42" },
  include_ambient: true,
  include_tools: true,
};

const COLD: AssemblyScenario = {
  id: "scenario:cold",
  label: "Cold minimal",
  variables: {},
  include_ambient: false,
  include_tools: false,
};

const OPTIONS: AssemblyOptions = { assembly: "plan-authoring", scenarios: [WARM, COLD] };

function render(scenario: AssemblyScenario): AssemblyRender {
  return {
    assembly: "plan-authoring",
    scenario,
    presentation: {
      include_ambient: scenario.include_ambient,
      include_tools: scenario.include_tools,
    },
    layers: [],
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

function harness(
  buffersFn: () => WorkspaceBufferExport[] = () => [],
  token: string | null = "test-token",
) {
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
  const states: AssemblySessionState[] = [];
  const session = createAssemblySession({
    onState: (state) => states.push(state),
    buffersFn,
    fetchFn,
    documentRoot: documentWithToken(token),
  });
  return { session, states, pending };
}

function requestBody(request: PendingRequest): unknown {
  return JSON.parse(String(request.init?.body));
}

function lastState(states: AssemblySessionState[]): AssemblySessionState {
  const state = states[states.length - 1];
  assert.ok(state !== undefined, "no state emitted");
  return state;
}

async function openToReady(h: ReturnType<typeof harness>): Promise<void> {
  h.session.open("plan-authoring");
  const options = h.pending[h.pending.length - 1];
  assert.ok(options !== undefined);
  options.respond(respond(200, structuredClone(OPTIONS)));
  await tick();
}

test("open loads options, auto-selects the first scenario, and auto-renders", async () => {
  const buffers: WorkspaceBufferExport[] = [{ path: "a.md", text: "alpha\n" }];
  const h = harness(() => buffers.map((buffer) => ({ ...buffer })));
  h.session.open("plan-authoring");
  assert.deepEqual(h.states, [{ status: "loading-options", assembly: "plan-authoring" }]);
  assert.equal(h.pending[0]?.url, "/api/assembly/options?assembly=plan-authoring");

  h.pending[0]?.respond(respond(200, structuredClone(OPTIONS)));
  await tick();
  assert.deepEqual(lastState(h.states), {
    status: "ready",
    assembly: "plan-authoring",
    options: OPTIONS,
    scenarioId: WARM.id,
    overrides: { ambient: null, tools: null },
    render: { status: "rendering" },
  });
  assert.equal(h.states.length, 2, "the ready establishment is one visible emission");

  assert.equal(h.pending[1]?.url, "/api/assembly/render");
  assert.deepEqual(requestBody(h.pending[1] as PendingRequest), {
    assembly: "plan-authoring",
    scenario: WARM.id,
    presentation: { include_ambient: null, include_tools: null },
    buffers: [{ path: "a.md", text: "alpha\n" }],
  });

  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  const final = lastState(h.states);
  assert.equal(final.status, "ready");
  assert.deepEqual(final.status === "ready" ? final.render : null, {
    status: "rendered",
    render: render(WARM),
  });
});

test("stale options completions after a newer open are dropped entirely", async () => {
  const h = harness();
  h.session.open("assembly-a");
  h.session.open("assembly-b");
  assert.equal(h.pending.length, 2);

  h.pending[0]?.respond(
    respond(200, { assembly: "assembly-a", scenarios: [structuredClone(WARM)] }),
  );
  await tick();
  assert.deepEqual(lastState(h.states), { status: "loading-options", assembly: "assembly-b" });
  assert.equal(h.pending.length, 2, "a stale options completion must not issue a render");

  h.pending[1]?.respond(
    respond(200, { assembly: "assembly-b", scenarios: [structuredClone(WARM)] }),
  );
  await tick();
  const final = lastState(h.states);
  assert.equal(final.status === "ready" ? final.assembly : null, "assembly-b");
});

test("clear and dispose drop in-flight render completions", async () => {
  const h = harness();
  await openToReady(h);
  h.session.clear();
  assert.deepEqual(lastState(h.states), { status: "idle" });
  const emitted = h.states.length;
  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  assert.equal(h.states.length, emitted, "a superseded render must not re-emit");

  const disposed = harness();
  await openToReady(disposed);
  disposed.session.dispose();
  const disposedEmissions = disposed.states.length;
  disposed.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  assert.equal(disposed.states.length, disposedEmissions);
});

test("chooseScenario resets both overrides, re-renders, and drops the stale render", async () => {
  const h = harness();
  await openToReady(h);
  h.session.setOverride("ambient", false);
  h.session.chooseScenario(COLD.id);
  const chosen = lastState(h.states);
  assert.equal(chosen.status, "ready");
  if (chosen.status === "ready") {
    assert.equal(chosen.scenarioId, COLD.id);
    assert.deepEqual(chosen.overrides, { ambient: null, tools: null });
    assert.deepEqual(chosen.render, { status: "rendering" });
  }
  assert.equal(h.pending.length, 3);
  assert.deepEqual(requestBody(h.pending[2] as PendingRequest), {
    assembly: "plan-authoring",
    scenario: COLD.id,
    presentation: { include_ambient: null, include_tools: null },
    buffers: [],
  });

  // The first (superseded) render lands late: dropped, the slot stays rendering.
  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  const afterStale = lastState(h.states);
  assert.deepEqual(afterStale.status === "ready" ? afterStale.render : null, {
    status: "rendering",
  });

  h.pending[2]?.respond(respond(200, structuredClone(render(COLD))));
  await tick();
  const final = lastState(h.states);
  assert.deepEqual(final.status === "ready" ? final.render : null, {
    status: "rendered",
    render: render(COLD),
  });
});

test("setOverride emits state without fetching", async () => {
  const h = harness();
  await openToReady(h);
  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  const requests = h.pending.length;
  const emissions = h.states.length;
  h.session.setOverride("tools", false);
  assert.equal(h.pending.length, requests);
  assert.equal(h.states.length, emissions + 1);
  const state = lastState(h.states);
  assert.deepEqual(state.status === "ready" ? state.overrides : null, {
    ambient: null,
    tools: false,
  });
  assert.equal(state.status === "ready" ? state.render.status : null, "rendered");
});

test("a same-generation override survives an in-flight render landing", async () => {
  const h = harness();
  await openToReady(h);
  h.session.setOverride("tools", false);
  const midFlight = lastState(h.states);
  assert.deepEqual(midFlight.status === "ready" ? midFlight.render : null, {
    status: "rendering",
  });

  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  const final = lastState(h.states);
  assert.equal(final.status, "ready");
  if (final.status === "ready") {
    assert.deepEqual(final.overrides, { ambient: null, tools: false });
    assert.deepEqual(final.render, { status: "rendered", render: render(WARM) });
  }
});

test("rerender retries after a transient render failure", async () => {
  const h = harness();
  await openToReady(h);
  h.pending[1]?.respond(respond(500, { detail: "boom" }));
  await tick();
  const failed = lastState(h.states);
  assert.deepEqual(failed.status === "ready" ? failed.render : null, {
    status: "render-failed",
  });

  h.session.rerender();
  assert.equal(h.pending.length, 3);
  h.pending[2]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();
  const final = lastState(h.states);
  assert.deepEqual(final.status === "ready" ? final.render : null, {
    status: "rendered",
    render: render(WARM),
  });
});

test("refreshBuffers no-ops on identical exports and re-renders on changes", async () => {
  let buffers: WorkspaceBufferExport[] = [{ path: "a.md", text: "alpha\n" }];
  const h = harness(() => buffers.map((buffer) => ({ ...buffer })));
  await openToReady(h);
  h.pending[1]?.respond(respond(200, structuredClone(render(WARM))));
  await tick();

  h.session.refreshBuffers();
  assert.equal(h.pending.length, 2, "identical exports must not re-render");

  buffers = [{ path: "a.md", text: "alpha edited\n" }];
  h.session.refreshBuffers();
  assert.equal(h.pending.length, 3);
  assert.deepEqual(requestBody(h.pending[2] as PendingRequest), {
    assembly: "plan-authoring",
    scenario: WARM.id,
    presentation: { include_ambient: null, include_tools: null },
    buffers: [{ path: "a.md", text: "alpha edited\n" }],
  });

  // The refreshed fingerprint is the newly issued one: an immediate second poke
  // with the same exports is a no-op.
  h.session.refreshBuffers();
  assert.equal(h.pending.length, 3);
});

test("refreshBuffers is a no-op outside ready", () => {
  const h = harness();
  h.session.refreshBuffers();
  assert.equal(h.pending.length, 0);
  h.session.open("plan-authoring");
  h.session.refreshBuffers();
  assert.equal(h.pending.length, 1, "loading-options must not issue renders");
});

test("options failure arms map to refused and failed states", async () => {
  const refused = harness();
  refused.session.open("missing");
  refused.pending[0]?.respond(respond(404, { detail: "unknown assembly" }));
  await tick();
  assert.deepEqual(lastState(refused.states), {
    status: "options-refused",
    assembly: "missing",
    detail: "unknown assembly",
  });

  const failed = harness();
  failed.session.open("plan-authoring");
  failed.pending[0]?.respond(respond(500, { detail: "boom" }));
  await tick();
  assert.deepEqual(lastState(failed.states), {
    status: "options-failed",
    assembly: "plan-authoring",
  });

  const empty = harness();
  empty.session.open("plan-authoring");
  empty.pending[0]?.respond(respond(200, { assembly: "plan-authoring", scenarios: [] }));
  await tick();
  assert.deepEqual(lastState(empty.states), {
    status: "options-failed",
    assembly: "plan-authoring",
  });
});

test("render failure arms map to the right slots", async () => {
  const refused = harness();
  await openToReady(refused);
  refused.pending[1]?.respond(respond(409, { detail: "catalog stale" }));
  await tick();
  const refusedState = lastState(refused.states);
  assert.deepEqual(refusedState.status === "ready" ? refusedState.render : null, {
    status: "render-refused",
    detail: "catalog stale",
  });

  const thrown = harness();
  await openToReady(thrown);
  thrown.pending[1]?.fail(new TypeError("offline"));
  await tick();
  const thrownState = lastState(thrown.states);
  assert.deepEqual(thrownState.status === "ready" ? thrownState.render : null, {
    status: "render-failed",
  });

  const tokenless = harness(() => [], null);
  await openToReady(tokenless);
  await tick();
  const notSent = lastState(tokenless.states);
  assert.deepEqual(notSent.status === "ready" ? notSent.render : null, {
    status: "render-not-sent",
  });
  assert.equal(tokenless.pending.length, 1, "a missing token must not fetch the render");
});
