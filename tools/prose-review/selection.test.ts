import assert from "node:assert/strict";
import test from "node:test";
import type { SearchResult } from "./src/search.ts";
import {
  canonicalFragmentSelection,
  canonicalSourceSelection,
  canonicalUnitSelection,
  comparisonOriginKey,
  fragmentTarget,
  placedFragmentSelection,
  placedShapeLayerSelection,
  sameSourceTarget,
  searchResultTarget,
  shapeSelection,
  sourceSelectionKey,
  sourceTargetKey,
  wholeUnitTarget,
} from "./src/selection.ts";
import type { SessionShape, UnitRef } from "./src/tree.ts";

const UNIT: UnitRef = {
  id: "ambient:learned-routing",
  kind: "ambient-routing",
  path: "docs/learned/clusters.yaml",
};

const SHAPE: SessionShape = {
  id: "plan.warm",
  label: "Plan authoring — warm door",
  delivery: "warm",
  assembly: "plan-authoring",
  layers: [],
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

test("selection factories keep canonical and placed provenance separate", () => {
  const canonical = canonicalUnitSelection(UNIT);
  const canonicalFragment = canonicalFragmentSelection(UNIT, {
    id: "cluster:pi-extension",
    label: "pi-extension routing cue",
  });
  const placed = placedShapeLayerSelection(SHAPE, 3, UNIT);
  const placedFragment = placedFragmentSelection(SHAPE, 3, UNIT, {
    id: "cluster:pi-extension",
    label: "pi-extension routing cue",
  });
  assert.deepEqual(canonical, {
    type: "unit",
    target: { unit: UNIT, fragment: null },
    placement: null,
  });
  assert.deepEqual(canonicalSourceSelection(canonicalFragment.target), canonicalFragment);
  assert.deepEqual(placed, {
    type: "unit",
    target: { unit: UNIT, fragment: null },
    placement: {
      shape: {
        id: "plan.warm",
        label: "Plan authoring — warm door",
        delivery: "warm",
      },
      position: 3,
    },
  });
  assert.deepEqual(placedFragment.placement, placed.placement);
  assert.deepEqual(shapeSelection(SHAPE, [{ id: "planning", label: "Planning" }]), {
    type: "shape",
    shape: SHAPE,
    breadcrumb: [{ id: "planning", label: "Planning" }],
  });
});

test("selection keys distinguish placement while comparison keys ignore fragments", () => {
  const warm = placedShapeLayerSelection(SHAPE, 3, UNIT);
  const cold = placedShapeLayerSelection(
    { ...SHAPE, id: "plan.cold", label: "Plan authoring — cold door", delivery: "cold" },
    3,
    UNIT,
  );
  const warmFragment = placedFragmentSelection(SHAPE, 3, UNIT, {
    id: "cluster:pi-extension",
    label: "pi-extension routing cue",
  });
  assert.notEqual(sourceSelectionKey(warm), sourceSelectionKey(cold));
  assert.notEqual(sourceSelectionKey(warm), sourceSelectionKey(warmFragment));
  assert.notEqual(comparisonOriginKey(warm), comparisonOriginKey(cold));
  assert.equal(comparisonOriginKey(warm), comparisonOriginKey(warmFragment));
  assert.notEqual(comparisonOriginKey(warm), comparisonOriginKey(canonicalUnitSelection(UNIT)));
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
