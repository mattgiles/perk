import assert from "node:assert/strict";
import test from "node:test";
import { placedShapeLayerSelection, shapeSelection, sourceSelectionKey } from "./src/selection.ts";
import { type AssemblyLayer, type CapabilityTree, parseTree, parseUnitRef } from "./src/tree.ts";

const UNIT_LAYER: AssemblyLayer = {
  position: 2,
  optional: false,
  label: "Bound plan skill",
  unit: {
    id: "markdown:skills/perk-plan/SKILL.md",
    kind: "markdown",
    path: "skills/perk-plan/SKILL.md",
    fragments: [{ id: "body", label: "Document body" }],
  },
  boundary: null,
};

const BOUNDARY_LAYER: AssemblyLayer = {
  position: 1,
  optional: false,
  label: null,
  unit: null,
  boundary: "pi-system",
};

const WIRE: CapabilityTree = {
  capabilities: [
    {
      id: "planning",
      label: "Planning",
      units: [
        {
          id: "markdown:docs/plan.md",
          kind: "markdown",
          path: "docs/plan.md",
          fragments: [
            { id: "section:one", label: "One" },
            { id: "section:two", label: "Two" },
          ],
        },
      ],
      session_shapes: [],
      children: [
        {
          id: "planning.plan",
          label: "Plan",
          units: [],
          session_shapes: [
            {
              id: "plan.warm",
              label: "Warm",
              delivery: "warm",
              assembly: "plan-authoring",
              layers: [BOUNDARY_LAYER, UNIT_LAYER],
            },
          ],
          children: [],
        },
      ],
    },
  ],
};

function withLayer(layer: unknown): unknown {
  return {
    capabilities: [
      {
        ...WIRE.capabilities[0],
        children: [
          {
            id: "planning.plan",
            label: "Plan",
            units: [],
            session_shapes: [
              {
                id: "plan.warm",
                label: "Warm",
                delivery: "warm",
                assembly: "plan-authoring",
                layers: [layer],
              },
            ],
            children: [],
          },
        ],
      },
    ],
  };
}

test("parseTree accepts the exact wire shape", () => {
  assert.deepEqual(parseTree(WIRE), WIRE);
});

test("parseTree rejects non-object input", () => {
  assert.equal(parseTree(null), null);
  assert.equal(parseTree(undefined), null);
  assert.equal(parseTree("tree"), null);
  assert.equal(parseTree(7), null);
  assert.equal(parseTree([WIRE]), null);
});

test("parseTree rejects missing capabilities", () => {
  assert.equal(parseTree({}), null);
  assert.equal(parseTree({ capabilities: {} }), null);
});

const NODE_KEYS = ["id", "label", "units", "session_shapes", "children"] as const;

for (const key of NODE_KEYS) {
  test(`parseTree rejects a node missing ${key}`, () => {
    const node = WIRE.capabilities[0];
    assert.ok(node !== undefined);
    const { [key]: _omitted, ...rest } = node;
    assert.equal(parseTree({ capabilities: [rest] }), null);
  });
}

test("parseTree rejects ill-typed node fields", () => {
  const node = WIRE.capabilities[0];
  assert.ok(node !== undefined);
  assert.equal(parseTree({ capabilities: [{ ...node, id: 1 }] }), null);
  assert.equal(parseTree({ capabilities: [{ ...node, label: null }] }), null);
  assert.equal(parseTree({ capabilities: [{ ...node, units: {} }] }), null);
  assert.equal(parseTree({ capabilities: [{ ...node, session_shapes: "none" }] }), null);
  assert.equal(parseTree({ capabilities: [{ ...node, children: [null] }] }), null);
});

test("parseTree retains fragment arrays for direct and assembly units", () => {
  const parsed = parseTree(WIRE);
  assert.ok(parsed !== null);
  assert.deepEqual(parsed.capabilities[0]?.units[0]?.fragments, [
    { id: "section:one", label: "One" },
    { id: "section:two", label: "Two" },
  ]);
  assert.deepEqual(
    parsed.capabilities[0]?.children[0]?.session_shapes[0]?.layers[1]?.unit?.fragments,
    [{ id: "body", label: "Document body" }],
  );
});

test("parsed shape data supplies authored breadcrumb and placed selections", () => {
  const parsed = parseTree(WIRE);
  assert.ok(parsed !== null);
  const planning = parsed.capabilities[0];
  const plan = planning?.children[0];
  const shape = plan?.session_shapes[0];
  const layer = shape?.layers[1];
  assert.ok(planning !== undefined);
  assert.ok(plan !== undefined);
  assert.ok(shape !== undefined);
  assert.ok(layer?.unit !== null && layer?.unit !== undefined);
  const breadcrumb = [
    { id: planning.id, label: planning.label },
    { id: plan.id, label: plan.label },
  ];
  assert.deepEqual(shapeSelection(shape, breadcrumb).breadcrumb, breadcrumb);
  assert.equal(
    sourceSelectionKey(placedShapeLayerSelection(shape, layer.position, layer.unit)),
    JSON.stringify([JSON.stringify([layer.unit.id, null, null]), "plan.warm", 2]),
  );
});

test("parseTree rejects malformed or missing fragment arrays", () => {
  assert.equal(
    parseTree({
      capabilities: [
        {
          ...WIRE.capabilities[0],
          units: [{ id: "u", kind: "markdown", path: "p" }],
          children: [],
        },
      ],
    }),
    null,
  );
  assert.equal(
    parseTree({
      capabilities: [
        {
          ...WIRE.capabilities[0],
          units: [
            {
              id: "u",
              kind: "markdown",
              path: "p",
              fragments: [{ id: "body" }],
            },
          ],
          children: [],
        },
      ],
    }),
    null,
  );
});

test("parseUnitRef keeps the compact search/inspect shape unchanged", () => {
  assert.deepEqual(parseUnitRef({ id: "u", kind: "markdown", path: "p" }), {
    id: "u",
    kind: "markdown",
    path: "p",
  });
});

test("parseTree rejects an unknown unit kind", () => {
  assert.equal(
    parseTree({
      capabilities: [
        {
          ...WIRE.capabilities[0],
          units: [{ id: "u", kind: "latin", path: "p", fragments: [] }],
          children: [],
        },
      ],
    }),
    null,
  );
});

test("parseTree rejects an unknown delivery mode", () => {
  const shape = {
    id: "plan.warm",
    label: "Warm",
    delivery: "tepid",
    assembly: "plan-authoring",
    layers: [],
  };
  assert.equal(
    parseTree({
      capabilities: [{ ...WIRE.capabilities[0], session_shapes: [shape], children: [] }],
    }),
    null,
  );
});

function withShape(shape: unknown): unknown {
  return {
    capabilities: [{ ...WIRE.capabilities[0], session_shapes: [shape], children: [] }],
  };
}

test("parseTree accepts and retains the shape's assembly id", () => {
  const parsed = parseTree(WIRE);
  assert.ok(parsed !== null);
  assert.equal(parsed.capabilities[0]?.children[0]?.session_shapes[0]?.assembly, "plan-authoring");
});

test("parseTree rejects a shape with a missing, empty, or ill-typed assembly", () => {
  const shape = {
    id: "plan.warm",
    label: "Warm",
    delivery: "warm",
    assembly: "plan-authoring",
    layers: [],
  };
  const { assembly: _omitted, ...missing } = shape;
  assert.equal(parseTree(withShape(missing)), null);
  assert.equal(parseTree(withShape({ ...shape, assembly: "" })), null);
  assert.equal(parseTree(withShape({ ...shape, assembly: null })), null);
  assert.equal(parseTree(withShape({ ...shape, assembly: 7 })), null);
  assert.notEqual(parseTree(withShape(shape)), null);
});

test("parseTree rejects an unknown boundary kind", () => {
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, boundary: "dmz" })), null);
});

test("parseTree rejects ill-formed layer positions", () => {
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, position: 0 })), null);
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, position: -1 })), null);
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, position: 1.5 })), null);
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, position: "1" })), null);
});

test("parseTree rejects a layer with both unit and boundary null", () => {
  assert.equal(parseTree(withLayer({ ...BOUNDARY_LAYER, boundary: null })), null);
});

test("parseTree rejects a layer with both unit and boundary set", () => {
  assert.equal(parseTree(withLayer({ ...UNIT_LAYER, boundary: "pi-system" })), null);
});

test("parseTree rejects a layer with ill-typed optional or label", () => {
  assert.equal(parseTree(withLayer({ ...UNIT_LAYER, optional: "no" })), null);
  assert.equal(parseTree(withLayer({ ...UNIT_LAYER, label: 3 })), null);
});

const LAYER_KEYS = ["position", "optional", "label", "unit", "boundary"] as const;

for (const key of LAYER_KEYS) {
  test(`parseTree rejects a layer missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = UNIT_LAYER;
    assert.equal(parseTree(withLayer(rest)), null);
  });
}

test("parseTree rejects an ill-shaped nested shape entry", () => {
  assert.equal(
    parseTree({
      capabilities: [
        {
          ...WIRE.capabilities[0],
          session_shapes: [{ id: "plan.warm", label: "Warm" }],
          children: [],
        },
      ],
    }),
    null,
  );
});

test("parseTree rejects an ill-shaped nested child entry", () => {
  assert.equal(
    parseTree({
      capabilities: [{ ...WIRE.capabilities[0], children: [{ id: "child" }] }],
    }),
    null,
  );
});
