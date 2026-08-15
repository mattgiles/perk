import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { UnitInspect } from "./src/inspect.ts";
import { createInspectLoader, type InspectLoadState, loadUnitInspect } from "./src/inspectLoad.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

const INSPECT: UnitInspect = {
  id: "typescript-tool:plan_review",
  kind: "typescript-tool",
  path: "extension/factories/planReview.ts",
  selector: "tool:plan_review",
  audience: "shipped",
  role: "tool-contract",
  breadcrumb: [{ id: "review", label: "Review" }],
  capability_children: [],
  consumers: [],
  shapes: [],
  concerns: [],
  lineage: [],
};

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function respondInvalidJson(status: number): ResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("invalid json")),
  };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

test("loadUnitInspect loads a valid 200 payload and encodes the unit id", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, INSPECT));
  };
  const outcome = await loadUnitInspect("typescript-tool:plan/review", fetchFn);
  assert.deepEqual(outcome, { status: "loaded", detail: INSPECT });
  assert.deepEqual(urls, ["/api/inspect?unit=typescript-tool%3Aplan%2Freview"]);
});

test("loadUnitInspect maps a 404 with a string detail to refused", async () => {
  const outcome = await loadUnitInspect("u", fetchOnce(respond(404, { detail: "unknown unit" })));
  assert.deepEqual(outcome, { status: "refused", detail: "unknown unit" });
});

test("loadUnitInspect fails a 404 without a string detail", async () => {
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respond(404, { detail: 7 }))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respond(404, "gone"))), {
    status: "failed",
  });
});

test("loadUnitInspect fails a non-ok status other than 404", async () => {
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respond(500, { detail: "boom" }))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respond(422, { detail: "no" }))), {
    status: "failed",
  });
});

test("loadUnitInspect fails invalid JSON on both the 200 and 404 arms", async () => {
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respondInvalidJson(200))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respondInvalidJson(404))), {
    status: "failed",
  });
});

test("loadUnitInspect fails an ill-shaped or unknown-enum 200 payload", async () => {
  assert.deepEqual(await loadUnitInspect("u", fetchOnce(respond(200, { id: "u" }))), {
    status: "failed",
  });
  assert.deepEqual(
    await loadUnitInspect("u", fetchOnce(respond(200, { ...INSPECT, role: "boss" }))),
    { status: "failed" },
  );
});

test("loadUnitInspect fails a rejecting fetch (network error)", async () => {
  const outcome = await loadUnitInspect("u", () => Promise.reject(new TypeError("offline")));
  assert.deepEqual(outcome, { status: "failed" });
});

type Deferred = {
  promise: Promise<ResponseLike>;
  resolve: (response: ResponseLike) => void;
};

function deferred(): Deferred {
  let resolve!: (response: ResponseLike) => void;
  const promise = new Promise<ResponseLike>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

test("createInspectLoader emits loading then the outcome for one selection", async () => {
  const states: InspectLoadState[] = [];
  const loader = createInspectLoader(
    (state) => states.push(state),
    fetchOnce(respond(200, INSPECT)),
  );
  loader.select(INSPECT.id);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", detail: INSPECT }]);
});

test("createInspectLoader drops an out-of-order stale response", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: InspectLoadState[] = [];
  const loader = createInspectLoader((state) => states.push(state), fetchFn);

  loader.select("unit-a");
  loader.select("unit-b");
  const requestA = requests.get("/api/inspect?unit=unit-a");
  const requestB = requests.get("/api/inspect?unit=unit-b");
  assert.ok(requestA !== undefined && requestB !== undefined);

  // The newer selection resolves first...
  requestB.resolve(respond(200, { ...INSPECT, id: "unit-b" }));
  await tick();
  // ...then the superseded one arrives late: it must never surface.
  requestA.resolve(respond(200, { ...INSPECT, id: "unit-a" }));
  await tick();

  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", detail: { ...INSPECT, id: "unit-b" } },
  ]);
});

test("createInspectLoader drops outcomes arriving after dispose", async () => {
  const request = deferred();
  const states: InspectLoadState[] = [];
  const loader = createInspectLoader(
    (state) => states.push(state),
    () => request.promise,
  );
  loader.select(INSPECT.id);
  loader.dispose();
  request.resolve(respond(200, INSPECT));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
