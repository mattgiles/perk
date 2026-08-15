import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { UnitSource } from "./src/source.ts";
import {
  createSourceLoader,
  type FetchLike,
  loadUnitSource,
  type ResponseLike,
  type SourceLoadState,
} from "./src/sourceLoad.ts";

const SOURCE: UnitSource = {
  unit: "managed:repo-agents",
  path: "AGENTS.md",
  kind: "managed-prose",
  content: "# AGENTS\n",
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

test("loadUnitSource loads a valid 200 payload and encodes the unit id", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, SOURCE));
  };
  const outcome = await loadUnitSource("typescript-tool:plan/review", fetchFn);
  assert.deepEqual(outcome, { status: "loaded", source: SOURCE });
  assert.deepEqual(urls, ["/api/source?unit=typescript-tool%3Aplan%2Freview"]);
});

test("loadUnitSource maps a 404 with a string detail to refused", async () => {
  const outcome = await loadUnitSource("u", fetchOnce(respond(404, { detail: "unknown unit" })));
  assert.deepEqual(outcome, { status: "refused", detail: "unknown unit" });
});

test("loadUnitSource fails a 404 without a string detail", async () => {
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respond(404, { detail: 7 }))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respond(404, "gone"))), {
    status: "failed",
  });
});

test("loadUnitSource fails a non-ok status other than 404", async () => {
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respond(500, { detail: "boom" }))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respond(403, { detail: "no" }))), {
    status: "failed",
  });
});

test("loadUnitSource fails invalid JSON on both the 200 and 404 arms", async () => {
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respondInvalidJson(200))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respondInvalidJson(404))), {
    status: "failed",
  });
});

test("loadUnitSource fails an ill-shaped or unknown-kind 200 payload", async () => {
  assert.deepEqual(await loadUnitSource("u", fetchOnce(respond(200, { unit: "u" }))), {
    status: "failed",
  });
  assert.deepEqual(
    await loadUnitSource("u", fetchOnce(respond(200, { ...SOURCE, kind: "latin" }))),
    { status: "failed" },
  );
});

test("loadUnitSource fails a rejecting fetch (network error)", async () => {
  const outcome = await loadUnitSource("u", () => Promise.reject(new TypeError("offline")));
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

test("createSourceLoader emits loading then the outcome for one selection", async () => {
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchOnce(respond(200, SOURCE)));
  loader.select(SOURCE.unit);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", source: SOURCE }]);
});

test("createSourceLoader drops an out-of-order stale response", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchFn);

  loader.select("unit-a");
  loader.select("unit-b");
  const requestA = requests.get("/api/source?unit=unit-a");
  const requestB = requests.get("/api/source?unit=unit-b");
  assert.ok(requestA !== undefined && requestB !== undefined);

  // The newer selection resolves first...
  requestB.resolve(respond(200, { ...SOURCE, unit: "unit-b" }));
  await tick();
  // ...then the superseded one arrives late: it must never surface.
  requestA.resolve(respond(200, { ...SOURCE, unit: "unit-a" }));
  await tick();

  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", source: { ...SOURCE, unit: "unit-b" } },
  ]);
});

test("createSourceLoader drops a stale refusal after a newer selection", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchFn);

  loader.select("unit-a");
  loader.select("unit-b");
  const requestA = requests.get("/api/source?unit=unit-a");
  const requestB = requests.get("/api/source?unit=unit-b");
  assert.ok(requestA !== undefined && requestB !== undefined);

  requestA.resolve(respond(404, { detail: "source not found" }));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loading" }]);

  requestB.resolve(respond(200, SOURCE));
  await tick();
  assert.deepEqual(states.at(-1), { status: "loaded", source: SOURCE });
});

test("createSourceLoader drops outcomes arriving after dispose", async () => {
  const request = deferred();
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader(
    (state) => states.push(state),
    () => request.promise,
  );
  loader.select(SOURCE.unit);
  loader.dispose();
  request.resolve(respond(200, SOURCE));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
