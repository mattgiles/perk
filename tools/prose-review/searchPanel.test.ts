import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import type { SearchResults } from "./src/search.ts";
import { createSearchPanel, NO_FILTERS, type PanelState, panelHint } from "./src/searchPanel.ts";
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
        path: "extension/factories/planReview.ts",
      },
      matched: ["unit-id", "tool-name"],
    },
  ],
};

const EMPTY: SearchResults = { total: 0, results: [] };

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

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

test("refresh with a query opens the panel: loading then loaded", async () => {
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => Promise.resolve(respond(200, RESULTS)),
  );
  panel.refresh("plan_review", NO_FILTERS);
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "loaded", results: RESULTS }]);
});

test("refresh with an empty trimmed query and no filters goes idle without firing", async () => {
  let fetched = 0;
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => {
      fetched += 1;
      return Promise.resolve(respond(200, RESULTS));
    },
  );
  panel.refresh("   ", NO_FILTERS);
  await tick();
  assert.deepEqual(states, [{ status: "idle" }]);
  assert.equal(fetched, 0);
});

test("a filter-only browse fires with the filter param and an empty query", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, RESULTS));
  };
  const states: PanelState[] = [];
  const panel = createSearchPanel((state) => states.push(state), fetchFn);
  panel.refresh("", { ...NO_FILTERS, kind: "typescript-tool" });
  await tick();
  assert.deepEqual(urls, ["/api/search?q=&kind=typescript-tool"]);
  assert.deepEqual(states.at(-1), { status: "loaded", results: RESULTS });
});

test("the idle transition cancels an in-flight request: a late response never reopens the panel", async () => {
  const request = deferred();
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => request.promise,
  );
  panel.refresh("plan", NO_FILTERS);
  // Clearing the query while the request is in flight closes the panel...
  panel.refresh("", NO_FILTERS);
  assert.deepEqual(states, [{ status: "loading" }, { status: "idle" }]);
  // ...and the response landing afterwards must emit nothing.
  request.resolve(respond(200, RESULTS));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "idle" }]);
});

test("close() (result selection) goes idle and drops the in-flight response", async () => {
  const request = deferred();
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => request.promise,
  );
  panel.refresh("plan_review", NO_FILTERS);
  panel.close();
  request.resolve(respond(200, RESULTS));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }, { status: "idle" }]);
});

test("a zero-match response keeps the panel open in loaded (never a silent idle)", async () => {
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => Promise.resolve(respond(200, EMPTY)),
  );
  panel.refresh("zzz-no-such-entity", NO_FILTERS);
  await tick();
  const last = states.at(-1);
  assert.deepEqual(last, { status: "loaded", results: EMPTY });
  assert.ok(last !== undefined);
  assert.equal(panelHint(last), "No matches.");
});

test("panelHint pins the fixed copy for every non-result state", () => {
  assert.equal(panelHint({ status: "loading" }), "Searching…");
  assert.equal(panelHint({ status: "failed" }), "Search failed.");
  assert.equal(panelHint({ status: "loaded", results: EMPTY }), "No matches.");
  assert.equal(panelHint({ status: "loaded", results: RESULTS }), null);
  assert.equal(panelHint({ status: "idle" }), null);
});

test("dispose drops outcomes arriving afterwards", async () => {
  const request = deferred();
  const states: PanelState[] = [];
  const panel = createSearchPanel(
    (state) => states.push(state),
    () => request.promise,
  );
  panel.refresh("plan", NO_FILTERS);
  panel.dispose();
  request.resolve(respond(200, RESULTS));
  await tick();
  assert.deepEqual(states, [{ status: "loading" }]);
});
