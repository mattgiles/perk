import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import {
  type ComparisonOptions,
  type ComparisonPlacement,
  type ComparisonRequest,
  comparisonRequest,
} from "./src/comparison.ts";
import {
  type ComparisonLoadState,
  createComparisonLoader,
  loadComparisonOptions,
} from "./src/comparisonLoad.ts";
import { placedFragmentSelection, placedShapeLayerSelection } from "./src/selection.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";
import type { SessionShape, UnitRef } from "./src/tree.ts";

const UNIT: UnitRef = { id: "unit:a/b", kind: "markdown", path: "a.md" };
const WARM: SessionShape = {
  id: "plan.warm",
  label: "Plan warm",
  delivery: "warm",
  layers: [],
};
const COLD: SessionShape = { ...WARM, id: "plan.cold", label: "Plan cold", delivery: "cold" };

function options(shape: SessionShape | null = null): ComparisonOptions {
  const common = {
    unit: UNIT,
    breadcrumb: [{ id: "planning", label: "Planning" }],
  };
  const origin: ComparisonPlacement =
    shape === null
      ? {
          ...common,
          provenance: "canonical",
          shape: null,
          assembly: null,
          position: null,
          label: UNIT.id,
        }
      : {
          ...common,
          provenance: "shape",
          shape: { id: shape.id, label: shape.label, delivery: shape.delivery },
          assembly: "plan-authoring",
          position: 3,
          label: "Bound plan skill",
        };
  return { origin, groups: [] };
}

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

const CANONICAL: ComparisonRequest = { unit: UNIT.id, shape: null, position: null };
const PLACED: ComparisonRequest = { unit: UNIT.id, shape: WARM.id, position: 3 };

test("loadComparisonOptions uses deterministic encoded query ordering", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, options(WARM)));
  };
  assert.deepEqual(await loadComparisonOptions(PLACED, fetchFn), {
    status: "loaded",
    options: options(WARM),
  });
  assert.deepEqual(urls, ["/api/compare?unit=unit%3Aa%2Fb&shape=plan.warm&position=3"]);

  const canonicalUrls: string[] = [];
  await loadComparisonOptions(CANONICAL, (url) => {
    canonicalUrls.push(url);
    return Promise.resolve(respond(200, options()));
  });
  assert.deepEqual(canonicalUrls, ["/api/compare?unit=unit%3Aa%2Fb"]);
});

test("loadComparisonOptions classifies a fixed-detail 404 as refused", async () => {
  assert.deepEqual(
    await loadComparisonOptions(
      CANONICAL,
      fetchOnce(respond(404, { detail: "unknown comparison subject" })),
    ),
    { status: "refused", detail: "unknown comparison subject" },
  );
  assert.deepEqual(await loadComparisonOptions(CANONICAL, fetchOnce(respond(404, { detail: 4 }))), {
    status: "failed",
  });
});

test("loadComparisonOptions fails non-ok, network, JSON, and parser errors", async () => {
  assert.deepEqual(
    await loadComparisonOptions(CANONICAL, fetchOnce(respond(500, { detail: "boom" }))),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadComparisonOptions(CANONICAL, () => Promise.reject(new TypeError("offline"))),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadComparisonOptions(
      CANONICAL,
      fetchOnce({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError("bad")) }),
    ),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadComparisonOptions(CANONICAL, fetchOnce(respond(200, { origin: {} }))),
    { status: "failed" },
  );
});

test("loadComparisonOptions rejects a valid response for the wrong origin", async () => {
  assert.deepEqual(await loadComparisonOptions(CANONICAL, fetchOnce(respond(200, options(WARM)))), {
    status: "failed",
  });
  assert.deepEqual(await loadComparisonOptions(PLACED, fetchOnce(respond(200, options(COLD)))), {
    status: "failed",
  });
  assert.deepEqual(
    await loadComparisonOptions(
      PLACED,
      fetchOnce(
        respond(200, {
          ...options(WARM),
          origin: { ...options(WARM).origin, unit: { ...UNIT, id: "unit:other" } },
        }),
      ),
    ),
    { status: "failed" },
  );
});

type Deferred = {
  promise: Promise<ResponseLike>;
  resolve: (response: ResponseLike) => void;
};

function deferred(): Deferred {
  let resolve!: (response: ResponseLike) => void;
  const promise = new Promise<ResponseLike>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

test("createComparisonLoader emits loading then loaded", async () => {
  const states: ComparisonLoadState[] = [];
  const loader = createComparisonLoader(
    (state) => states.push(state),
    fetchOnce(respond(200, options())),
  );
  loader.select(CANONICAL);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", options: options() }]);
});

test("warm to cold on one unit is latest-wins while fragment-only requests are identical", async () => {
  const requests = new Map<string, Deferred>();
  const states: ComparisonLoadState[] = [];
  const loader = createComparisonLoader(
    (state) => states.push(state),
    (url) => {
      const request = deferred();
      requests.set(url, request);
      return request.promise;
    },
  );
  const warmSelection = placedShapeLayerSelection(WARM, 3, UNIT);
  const coldSelection = placedShapeLayerSelection(COLD, 3, UNIT);
  const fragmentSelection = placedFragmentSelection(WARM, 3, UNIT, {
    id: "body",
    label: "Body",
  });
  assert.deepEqual(comparisonRequest(warmSelection), comparisonRequest(fragmentSelection));

  loader.select(comparisonRequest(warmSelection));
  loader.select(comparisonRequest(coldSelection));
  const warm = requests.get("/api/compare?unit=unit%3Aa%2Fb&shape=plan.warm&position=3");
  const cold = requests.get("/api/compare?unit=unit%3Aa%2Fb&shape=plan.cold&position=3");
  assert.ok(warm !== undefined && cold !== undefined);
  cold.resolve(respond(200, options(COLD)));
  await tick();
  warm.resolve(respond(200, options(WARM)));
  await tick();
  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", options: options(COLD) },
  ]);
});

test("clear invalidates in-flight work, emits idle, and permits a fresh generation", async () => {
  const requests: Deferred[] = [];
  const states: ComparisonLoadState[] = [];
  const loader = createComparisonLoader(
    (state) => states.push(state),
    () => {
      const request = deferred();
      requests.push(request);
      return request.promise;
    },
  );
  loader.select(CANONICAL);
  loader.clear();
  loader.select(CANONICAL);
  const [stale, fresh] = requests;
  assert.ok(stale !== undefined && fresh !== undefined);
  stale.resolve(respond(200, options()));
  fresh.resolve(respond(200, options()));
  await tick();
  assert.deepEqual(states, [
    { status: "loading" },
    { status: "idle" },
    { status: "loading" },
    { status: "loaded", options: options() },
  ]);
});

test("dispose drops late outcomes without emitting", async () => {
  const request = deferred();
  const states: ComparisonLoadState[] = [];
  const loader = createComparisonLoader(
    (state) => states.push(state),
    () => request.promise,
  );
  loader.select(CANONICAL);
  loader.dispose();
  request.resolve(respond(200, options()));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
