import assert from "node:assert/strict";
import test from "node:test";
import {
  COMPARISON_RELATIONS,
  type ComparisonChoice,
  type ComparisonOptions,
  type ComparisonPlacement,
  comparisonOptionsMatchRequest,
  comparisonPlacementKey,
  parseComparisonOptions,
} from "./src/comparison.ts";

const CANONICAL: ComparisonPlacement = {
  provenance: "canonical",
  unit: { id: "unit:a", kind: "markdown", path: "a.md" },
  breadcrumb: [{ id: "planning", label: "Planning" }],
  shape: null,
  assembly: null,
  position: null,
  label: "unit:a",
};

const UNSHAPED: ComparisonPlacement = {
  provenance: "assembly",
  unit: { id: "unit:b", kind: "managed-prose", path: "map.yaml" },
  breadcrumb: [{ id: "delivery", label: "Delivery" }],
  shape: null,
  assembly: "implementation",
  position: 2,
  label: "Bound skill",
};

const SHAPED: ComparisonPlacement = {
  provenance: "shape",
  unit: { id: "unit:a", kind: "markdown", path: "a.md" },
  breadcrumb: [
    { id: "planning", label: "Planning" },
    { id: "planning.plan", label: "Plan authoring" },
  ],
  shape: { id: "plan.warm", label: "Plan warm", delivery: "warm" },
  assembly: "plan-authoring",
  position: 3,
  label: "Bound plan skill",
};

const CHOICE: ComparisonChoice = {
  label: "Bound plan skill",
  detail: "Plan warm · plan-authoring #3 · Bound plan skill",
  target: SHAPED,
};

const OPTIONS: ComparisonOptions = {
  origin: CANONICAL,
  groups: COMPARISON_RELATIONS.map((relation) => ({
    relation,
    label: `${relation} label`,
    choices: [CHOICE],
  })),
};

test("parseComparisonOptions accepts all five relations and three placement variants", () => {
  const wire = {
    groups: [
      { relation: "delivery-sibling", label: "Delivery siblings", choices: [CHOICE] },
      {
        relation: "adjacent-layer",
        label: "Adjacent assembly layers",
        choices: [{ ...CHOICE, target: UNSHAPED }],
      },
      { relation: "alias-consumer", label: "Alias consumers", choices: [CHOICE] },
      { relation: "concern-relative", label: "Concern relatives", choices: [CHOICE] },
      {
        relation: "capability-parent-child",
        label: "Capability parent / child",
        choices: [{ ...CHOICE, target: CANONICAL }],
      },
    ],
    origin: CANONICAL,
  };
  assert.deepEqual(parseComparisonOptions(wire), { origin: CANONICAL, groups: wire.groups });
});

test("parseComparisonOptions accepts an empty top-level options list", () => {
  assert.deepEqual(parseComparisonOptions({ origin: CANONICAL, groups: [] }), {
    origin: CANONICAL,
    groups: [],
  });
});

test("parseComparisonOptions rejects missing or ill-typed top-level fields", () => {
  assert.equal(parseComparisonOptions(null), null);
  assert.equal(parseComparisonOptions({ groups: [] }), null);
  assert.equal(parseComparisonOptions({ origin: CANONICAL }), null);
  assert.equal(parseComparisonOptions({ origin: CANONICAL, groups: {} }), null);
});

test("parseComparisonOptions rejects every incoherent placement nullability shape", () => {
  const invalid = [
    { ...CANONICAL, shape: SHAPED.shape },
    { ...CANONICAL, assembly: "plan-authoring" },
    { ...CANONICAL, position: 3 },
    { ...SHAPED, assembly: null },
    { ...SHAPED, position: null },
    { ...SHAPED, position: 0 },
    { ...SHAPED, position: 1.5 },
  ];
  for (const origin of invalid) {
    assert.equal(parseComparisonOptions({ origin, groups: [] }), null);
  }
});

test("parseComparisonOptions enforces non-empty copy, breadcrumbs, and emitted groups", () => {
  assert.equal(
    parseComparisonOptions({ origin: { ...CANONICAL, breadcrumb: [] }, groups: [] }),
    null,
  );
  assert.equal(parseComparisonOptions({ origin: { ...CANONICAL, label: "  " }, groups: [] }), null);
  assert.equal(
    parseComparisonOptions({
      origin: CANONICAL,
      groups: [{ relation: "alias-consumer", label: "Alias consumers", choices: [] }],
    }),
    null,
  );
  assert.equal(
    parseComparisonOptions({
      origin: CANONICAL,
      groups: [
        {
          relation: "alias-consumer",
          label: "Alias consumers",
          choices: [{ ...CHOICE, detail: "" }],
        },
      ],
    }),
    null,
  );
});

test("parseComparisonOptions rejects unknown relations and malformed nested fields", () => {
  assert.equal(
    parseComparisonOptions({
      origin: CANONICAL,
      groups: [{ relation: "similar", label: "Similar", choices: [CHOICE] }],
    }),
    null,
  );
  assert.equal(
    parseComparisonOptions({
      origin: CANONICAL,
      groups: [
        {
          relation: "alias-consumer",
          label: "Alias consumers",
          choices: [
            { ...CHOICE, target: { ...SHAPED, shape: { ...SHAPED.shape, delivery: "x" } } },
          ],
        },
      ],
    }),
    null,
  );
});

test("request matching distinguishes canonical and exact placed origins", () => {
  assert.equal(
    comparisonOptionsMatchRequest(OPTIONS, { unit: "unit:a", shape: null, position: null }),
    true,
  );
  assert.equal(
    comparisonOptionsMatchRequest(
      { ...OPTIONS, origin: SHAPED },
      { unit: "unit:a", shape: "plan.warm", position: 3 },
    ),
    true,
  );
  assert.equal(
    comparisonOptionsMatchRequest(
      { ...OPTIONS, origin: SHAPED },
      { unit: "unit:a", shape: "plan.cold", position: 3 },
    ),
    false,
  );
  assert.equal(
    comparisonOptionsMatchRequest(
      { ...OPTIONS, origin: SHAPED },
      { unit: "unit:a", shape: null, position: null },
    ),
    false,
  );
});

test("placement keys retain exact source provenance", () => {
  assert.equal(
    comparisonPlacementKey(SHAPED),
    JSON.stringify(["unit:a", "plan.warm", "plan-authoring", 3]),
  );
  assert.equal(
    comparisonPlacementKey(UNSHAPED),
    JSON.stringify(["unit:b", null, "implementation", 2]),
  );
  assert.equal(comparisonPlacementKey(CANONICAL), JSON.stringify(["unit:a", null, null, null]));
});
