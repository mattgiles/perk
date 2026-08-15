import assert from "node:assert/strict";
import test from "node:test";
import { type AssemblyLayer, type CapabilityTree, parseTree } from "./src/tree.ts";

const UNIT_LAYER: AssemblyLayer = {
  position: 2,
  optional: false,
  label: "Bound plan skill",
  unit: {
    id: "markdown:skills/perk-plan/SKILL.md",
    kind: "markdown",
    path: "skills/perk-plan/SKILL.md",
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
      units: [{ id: "markdown:docs/plan.md", kind: "markdown", path: "docs/plan.md" }],
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
            session_shapes: [{ id: "plan.warm", label: "Warm", delivery: "warm", layers: [layer] }],
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

test("parseTree rejects an unknown unit kind", () => {
  assert.equal(
    parseTree({
      capabilities: [
        {
          ...WIRE.capabilities[0],
          units: [{ id: "u", kind: "latin", path: "p" }],
          children: [],
        },
      ],
    }),
    null,
  );
});

test("parseTree rejects an unknown delivery mode", () => {
  const shape = { id: "plan.warm", label: "Warm", delivery: "tepid", layers: [] };
  assert.equal(
    parseTree({
      capabilities: [{ ...WIRE.capabilities[0], session_shapes: [shape], children: [] }],
    }),
    null,
  );
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
