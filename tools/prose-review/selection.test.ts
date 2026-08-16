import assert from "node:assert/strict";
import test from "node:test";
import type { SearchResult } from "./src/search.ts";
import {
  fragmentTarget,
  sameSourceTarget,
  searchResultTarget,
  sourceTargetKey,
  wholeUnitTarget,
} from "./src/selection.ts";
import type { UnitRef } from "./src/tree.ts";

const UNIT: UnitRef = {
  id: "ambient:learned-routing",
  kind: "ambient-routing",
  path: "docs/learned/clusters.yaml",
};

function result(kind: SearchResult["kind"]): SearchResult {
  return {
    kind,
    id: kind === "fragment" ? "cluster:pi-extension" : UNIT.id,
    label: kind === "fragment" ? "pi-extension routing cue" : UNIT.id,
    breadcrumb: [],
    unit: kind === "capability" || kind === "session-shape" ? null : UNIT,
    matched: [],
  };
}

test("target helpers preserve whole-unit and composite fragment identity", () => {
  const whole = wholeUnitTarget(UNIT);
  const fragment = fragmentTarget(UNIT, {
    id: "cluster:pi-extension",
    label: "pi-extension routing cue",
  });
  assert.deepEqual(whole, { unit: UNIT, fragment: null });
  assert.deepEqual(fragment, {
    unit: UNIT,
    fragment: { id: "cluster:pi-extension", label: "pi-extension routing cue" },
  });
  assert.notEqual(sourceTargetKey(whole), sourceTargetKey(fragment));
  assert.equal(sameSourceTarget(fragment, structuredClone(fragment)), true);
  assert.equal(
    sameSourceTarget(fragment, {
      ...fragment,
      fragment: { ...fragment.fragment, label: "Changed label" },
    }),
    false,
  );
});

test("search fragment rows project to exact composite targets", () => {
  assert.deepEqual(searchResultTarget(result("fragment")), {
    unit: UNIT,
    fragment: { id: "cluster:pi-extension", label: "pi-extension routing cue" },
  });
});

test("search unit and concern rows project to whole-unit targets", () => {
  assert.deepEqual(searchResultTarget(result("unit")), { unit: UNIT, fragment: null });
  assert.deepEqual(searchResultTarget(result("concern")), { unit: UNIT, fragment: null });
});

test("informational search rows have no source target", () => {
  assert.equal(searchResultTarget(result("capability")), null);
  assert.equal(searchResultTarget(result("session-shape")), null);
});
