import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { SourceTarget } from "./src/selection.ts";
import type { UnitSource } from "./src/source.ts";
import {
  createSourceLoader,
  type FetchLike,
  loadUnitSource,
  type ResponseLike,
  type SourceLoadState,
} from "./src/sourceLoad.ts";
import type { UnitRef } from "./src/tree.ts";

const UNIT: UnitRef = {
  id: "managed:repo-agents",
  kind: "managed-prose",
  path: "AGENTS.md",
};
const FRAGMENT = { id: "section:agents/developing-perk", label: "Developing perk" };
const TARGET: SourceTarget = { unit: UNIT, fragment: FRAGMENT };
const WHOLE_TARGET: SourceTarget = { unit: UNIT, fragment: null };

const SOURCE: UnitSource = {
  unit: UNIT.id,
  fragment: FRAGMENT,
  path: UNIT.path,
  kind: UNIT.kind,
  before: "# AGENTS\n",
  focus: "Focused\n",
  after: "",
  editable: true,
  read_only_reason: null,
};
const WHOLE_SOURCE: UnitSource = {
  unit: UNIT.id,
  fragment: null,
  path: UNIT.path,
  kind: UNIT.kind,
  before: "",
  focus: "# AGENTS\n",
  after: "",
  editable: false,
  read_only_reason: "whole-unit",
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

test("loadUnitSource orders and encodes unit then optional fragment", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, SOURCE));
  };
  assert.deepEqual(await loadUnitSource(TARGET, fetchFn), { status: "loaded", source: SOURCE });
  assert.deepEqual(urls, [
    "/api/source?unit=managed%3Arepo-agents&fragment=section%3Aagents%2Fdeveloping-perk",
  ]);

  urls.length = 0;
  const wholeFetch: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, WHOLE_SOURCE));
  };
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, wholeFetch), {
    status: "loaded",
    source: WHOLE_SOURCE,
  });
  assert.deepEqual(urls, ["/api/source?unit=managed%3Arepo-agents"]);
});

test("loadUnitSource rejects returned composite identity mismatches", async () => {
  assert.deepEqual(
    await loadUnitSource(TARGET, fetchOnce(respond(200, { ...SOURCE, unit: "other" }))),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadUnitSource(
      TARGET,
      fetchOnce(respond(200, { ...SOURCE, fragment: { ...FRAGMENT, id: "other" } })),
    ),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadUnitSource(
      TARGET,
      fetchOnce(respond(200, { ...SOURCE, fragment: { ...FRAGMENT, label: "Other" } })),
    ),
    { status: "failed" },
  );
  assert.deepEqual(await loadUnitSource(TARGET, fetchOnce(respond(200, WHOLE_SOURCE))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(200, SOURCE))), {
    status: "failed",
  });
});

test("loadUnitSource maps a 404 with a string detail to refused", async () => {
  const outcome = await loadUnitSource(
    WHOLE_TARGET,
    fetchOnce(respond(404, { detail: "unknown unit" })),
  );
  assert.deepEqual(outcome, { status: "refused", detail: "unknown unit" });
});

test("loadUnitSource fails malformed responses and network errors", async () => {
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(404, { detail: 7 }))), {
    status: "failed",
  });
  assert.deepEqual(
    await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(500, { detail: "boom" }))),
    { status: "failed" },
  );
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(respondInvalidJson(200))), {
    status: "failed",
  });
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(200, { unit: UNIT.id }))), {
    status: "failed",
  });
  assert.deepEqual(
    await loadUnitSource(WHOLE_TARGET, () => Promise.reject(new TypeError("offline"))),
    { status: "failed" },
  );
});

type Deferred = {
  promise: Promise<ResponseLike>;
  resolve: (response: ResponseLike) => void;
};

function deferred(): Deferred {
  let resolve!: (response: ResponseLike) => void;
  const promise = new Promise<ResponseLike>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function fragmentSource(id: string, label: string): UnitSource {
  return { ...SOURCE, fragment: { id, label } };
}

test("createSourceLoader emits loading then one composite outcome", async () => {
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchOnce(respond(200, SOURCE)));
  loader.select(TARGET);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", source: SOURCE }]);
});

test("createSourceLoader makes fragment-to-fragment changes latest-wins", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchFn);
  const first: SourceTarget = { unit: UNIT, fragment: { id: "first", label: "First" } };
  const second: SourceTarget = { unit: UNIT, fragment: { id: "second", label: "Second" } };

  loader.select(first);
  loader.select(second);
  const firstRequest = requests.get("/api/source?unit=managed%3Arepo-agents&fragment=first");
  const secondRequest = requests.get("/api/source?unit=managed%3Arepo-agents&fragment=second");
  assert.ok(firstRequest !== undefined && secondRequest !== undefined);

  secondRequest.resolve(respond(200, fragmentSource("second", "Second")));
  await tick();
  firstRequest.resolve(respond(200, fragmentSource("first", "First")));
  await tick();

  assert.deepEqual(states, [
    { status: "loading" },
    { status: "loading" },
    { status: "loaded", source: fragmentSource("second", "Second") },
  ]);
});

test("createSourceLoader makes whole-unit to fragment changes latest-wins", async () => {
  const requests = new Map<string, Deferred>();
  const fetchFn: FetchLike = (url) => {
    const request = deferred();
    requests.set(url, request);
    return request.promise;
  };
  const states: SourceLoadState[] = [];
  const loader = createSourceLoader((state) => states.push(state), fetchFn);

  loader.select(WHOLE_TARGET);
  loader.select(TARGET);
  const whole = requests.get("/api/source?unit=managed%3Arepo-agents");
  const fragment = requests.get(
    "/api/source?unit=managed%3Arepo-agents&fragment=section%3Aagents%2Fdeveloping-perk",
  );
  assert.ok(whole !== undefined && fragment !== undefined);
  whole.resolve(respond(200, WHOLE_SOURCE));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loading" }]);
  fragment.resolve(respond(200, SOURCE));
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
  loader.select(TARGET);
  loader.dispose();
  request.resolve(respond(200, SOURCE));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
