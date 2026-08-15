import assert from "node:assert/strict";
import test from "node:test";
import { parseSearch, type SearchResults } from "./src/search.ts";

// The happy wire shape: all five result kinds, null and non-null units, a matched
// list per hit — and one empty matched array (a filter-only browse matches no field).
const RESULTS: SearchResults = {
  total: 945,
  results: [
    {
      kind: "capability",
      id: "review",
      label: "Review",
      breadcrumb: [{ id: "review", label: "Review" }],
      unit: null,
      matched: ["capability-label"],
    },
    {
      kind: "session-shape",
      id: "plan.cold",
      label: "Plan authoring — cold door",
      breadcrumb: [{ id: "planning", label: "Planning" }],
      unit: null,
      matched: ["shape-label"],
    },
    {
      kind: "unit",
      id: "typescript-tool:plan_review",
      label: "typescript-tool:plan_review",
      breadcrumb: [
        { id: "review", label: "Review" },
        { id: "review.drafts", label: "Draft review" },
      ],
      unit: {
        id: "typescript-tool:plan_review",
        kind: "typescript-tool",
        path: "extension/factories/planReview.ts",
      },
      matched: ["unit-id", "source-path", "tool-name"],
    },
    {
      kind: "fragment",
      id: "cluster:pi-extension",
      label: "pi-extension routing cue",
      breadcrumb: [{ id: "knowledge", label: "Knowledge" }],
      unit: {
        id: "ambient:learned-routing",
        kind: "ambient-routing",
        path: ".pi/APPEND_SYSTEM.md",
      },
      matched: ["fragment-label"],
    },
    {
      kind: "concern",
      id: "review-first-save",
      label: "Review-first save",
      breadcrumb: [{ id: "planning", label: "Planning" }],
      unit: {
        id: "markdown:prompts/contexts/plan-authoring.md",
        kind: "markdown",
        path: "prompts/contexts/plan-authoring.md",
      },
      matched: [],
    },
  ],
};

function clone(): Record<string, unknown> {
  return structuredClone(RESULTS) as unknown as Record<string, unknown>;
}

test("parseSearch accepts the exact happy shape", () => {
  assert.deepEqual(parseSearch(clone()), RESULTS);
});

test("parseSearch accepts an empty result list", () => {
  assert.deepEqual(parseSearch({ total: 0, results: [] }), { total: 0, results: [] });
});

test("parseSearch rejects non-record payloads and missing fields", () => {
  assert.equal(parseSearch(null), null);
  assert.equal(parseSearch([]), null);
  assert.equal(parseSearch({ total: 1 }), null);
  assert.equal(parseSearch({ results: [] }), null);
});

test("parseSearch rejects a negative or non-integer total", () => {
  assert.equal(parseSearch({ ...clone(), total: -1 }), null);
  assert.equal(parseSearch({ ...clone(), total: 1.5 }), null);
  assert.equal(parseSearch({ ...clone(), total: "9" }), null);
});

test("parseSearch rejects an unknown result kind", () => {
  const payload = clone();
  payload.results = [{ ...RESULTS.results[0], kind: "assembly" }];
  assert.equal(parseSearch(payload), null);
});

test("parseSearch rejects unknown matched-field vocabulary", () => {
  const payload = clone();
  payload.results = [{ ...RESULTS.results[2], matched: ["unit-id", "relevance"] }];
  assert.equal(parseSearch(payload), null);
});

test("parseSearch rejects malformed result entries", () => {
  const missingLabel = clone();
  missingLabel.results = [{ ...RESULTS.results[0], label: undefined }];
  assert.equal(parseSearch(missingLabel), null);

  const badBreadcrumb = clone();
  badBreadcrumb.results = [{ ...RESULTS.results[0], breadcrumb: [{ id: "review" }] }];
  assert.equal(parseSearch(badBreadcrumb), null);

  const badUnit = clone();
  badUnit.results = [{ ...RESULTS.results[2], unit: { id: "u", kind: "latin", path: "p" } }];
  assert.equal(parseSearch(badUnit), null);

  const undefinedUnit = clone();
  undefinedUnit.results = [{ ...RESULTS.results[0], unit: undefined }];
  assert.equal(parseSearch(undefinedUnit), null);
});
