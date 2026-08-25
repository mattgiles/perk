import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { SearchResults } from "./src/search.ts";
import {
  createSearchLoader,
  loadSearch,
  type SearchLoadState,
  type SearchParams,
} from "./src/searchLoad.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

const RESULTS: SearchResults = {
  total: 1,
  results: [
    {
      kind: "unit",
      id: "typescript-tool:plan_review",
      label: "typescript-tool:plan_review",
      breadcrumb: [{ id: "review", label: "Review" }],
      unit: {
        id: "typescript-tool:plan_review",
        kind: "typescript-tool",
        path: "extension/pi/v1/plan.ts",
      },
      matched: ["unit-id", "tool-name"],
    },
  ],
};

const PARAMS: SearchParams = { q: "plan_review", audience: null, role: null, kind: null };

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

test("loadSearch loads a valid 200 payload with only the set params in the URL", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, RESULTS));
  };
  const outcome = await loadSearch(PARAMS, fetchFn);
  assert.deepEqual(outcome, { status: "loaded", results: RESULTS });
  assert.deepEqual(urls, ["/api/search?q=plan_review"]);
});

test("loadSearch URL-encodes the query and appends every set filter", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, { total: 0, results: [] }));
  };
  await loadSearch(
    { q: "a&b c", audience: "shipped", role: "tool-contract", kind: "typescript-tool" },
    fetchFn,
  );
  assert.deepEqual(urls, [
    "/api/search?q=a%26b+c&audience=shipped&role=tool-contract&kind=typescript-tool",
  ]);
});

test("loadSearch fails any non-ok status (the endpoint has no fixed 404)", async () => {
  assert.deepEqual(await loadSearch(PARAMS, fetchOnce(respond(404, { detail: "gone" }))), {
    status: "failed",
  });
  assert.deepEqual(await loadSearch(PARAMS, fetchOnce(respond(500, { detail: "boom" }))), {
    status: "failed",
  });
});

test("loadSearch fails invalid JSON and parse-rejected payloads", async () => {
  const invalidJson: ResponseLike = {
    ok: true,
    status: 200,
    json: () => Promise.reject(new SyntaxError("invalid json")),
  };
  assert.deepEqual(await loadSearch(PARAMS, fetchOnce(invalidJson)), { status: "failed" });
  assert.deepEqual(await loadSearch(PARAMS, fetchOnce(respond(200, { total: -1, results: [] }))), {
    status: "failed",
  });
});

test("loadSearch fails a rejecting fetch (network error)", async () => {
  const outcome = await loadSearch(PARAMS, () => Promise.reject(new TypeError("offline")));
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

test("createSearchLoader emits loading then the outcome for one request", async () => {
  const states: SearchLoadState[] = [];
  const loader = createSearchLoader(
    (state) => states.push(state),
    fetchOnce(respond(200, RESULTS)),
  );
  loader.select(PARAMS);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", results: RESULTS }]);
});

test("createSearchLoader drops an out-of-order stale response", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: SearchLoadState[] = [];
  const loader = createSearchLoader((state) => states.push(state), fetchFn);

  loader.select({ ...PARAMS, q: "first" });
  loader.select({ ...PARAMS, q: "second" });
  const requestA = requests.get("/api/search?q=first");
  const requestB = requests.get("/api/search?q=second");
  assert.ok(requestA !== undefined && requestB !== undefined);

  requestB.resolve(respond(200, RESULTS));
  await tick();
  requestA.resolve(respond(200, { total: 0, results: [] }));
  await tick();

  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", results: RESULTS },
  ]);
});

test("createSearchLoader clear() drops an in-flight response without emitting", async () => {
  const request = deferred();
  const states: SearchLoadState[] = [];
  const loader = createSearchLoader(
    (state) => states.push(state),
    () => request.promise,
  );
  loader.select(PARAMS);
  loader.clear();
  // The response resolves after clear(): nothing may be emitted — an in-flight
  // response must never reopen a closed panel.
  request.resolve(respond(200, RESULTS));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});

test("createSearchLoader select after clear starts a fresh winning generation", async () => {
  const requests: Deferred[] = [];
  const fetchFn: FetchLike = () => {
    const request = deferred();
    requests.push(request);
    return request.promise;
  };
  const states: SearchLoadState[] = [];
  const loader = createSearchLoader((state) => states.push(state), fetchFn);

  loader.select(PARAMS);
  loader.clear();
  loader.select({ ...PARAMS, q: "again" });
  const [cleared, fresh] = requests;
  assert.ok(cleared !== undefined && fresh !== undefined);

  cleared.resolve(respond(200, { total: 0, results: [] }));
  fresh.resolve(respond(200, RESULTS));
  await tick();

  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", results: RESULTS },
  ]);
});

test("createSearchLoader drops outcomes arriving after dispose", async () => {
  const request = deferred();
  const states: SearchLoadState[] = [];
  const loader = createSearchLoader(
    (state) => states.push(state),
    () => request.promise,
  );
  loader.select(PARAMS);
  loader.dispose();
  request.resolve(respond(200, RESULTS));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
