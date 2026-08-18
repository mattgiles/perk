import assert from "node:assert/strict";
import test from "node:test";
import {
  type AssemblyBoundaryLayer,
  type AssemblyFailureLayer,
  type AssemblyOptions,
  type AssemblyOwnedLayer,
  type AssemblyRender,
  assemblyRenderMatchesRequest,
  concatenatedText,
  parseAssemblyOptions,
  parseAssemblyRender,
  resolvedPresentation,
  visibleLayers,
} from "./src/assembly.ts";

const SCENARIO_WARM = {
  id: "scenario:warm",
  label: "Warm defaults",
  variables: { objective: "Ship the preview", plan: "42" },
  include_ambient: true,
  include_tools: true,
};

const SCENARIO_COLD = {
  id: "scenario:cold",
  label: "Cold minimal",
  variables: {},
  include_ambient: false,
  include_tools: false,
};

const OPTIONS: AssemblyOptions = {
  assembly: "plan-authoring",
  scenarios: [SCENARIO_WARM, SCENARIO_COLD],
};

const BOUNDARY: AssemblyBoundaryLayer = {
  type: "boundary",
  presentation: {
    position: 1,
    label: "System boundary",
    presence: "always",
    presence_label: null,
    visibility_control: null,
  },
  boundary: "pi-system",
  owner: "pi",
};

const OWNED: AssemblyOwnedLayer = {
  type: "owned",
  presentation: {
    position: 2,
    label: null,
    presence: "varies",
    presence_label: "Presence varies by session shape or runtime.",
    visibility_control: "ambient",
  },
  unit: { id: "unit:skill", kind: "markdown", path: "skill.md" },
  content_kind: "rendered-template",
  parts: [
    { fragment: null, text: "Hello " },
    { fragment: { id: "body", label: "Body" }, text: "world\n" },
  ],
};

const FAILURE: AssemblyFailureLayer = {
  type: "failure",
  presentation: {
    position: 3,
    label: "Tool contract",
    presence: "always",
    presence_label: null,
    visibility_control: "tools",
  },
  unit: { id: "unit:tool", kind: "typescript-tool", path: "tool.ts" },
  problems: [
    {
      fragment: { id: "description", label: "Description" },
      reason: "selector-not-found",
      detail: "A catalog fragment no longer resolves in the current source.",
    },
  ],
};

const RENDER: AssemblyRender = {
  assembly: "plan-authoring",
  scenario: SCENARIO_WARM,
  presentation: { include_ambient: true, include_tools: true },
  layers: [BOUNDARY, OWNED, FAILURE],
};

const REQUEST = {
  assembly: "plan-authoring",
  scenario: SCENARIO_WARM.id,
  presentation: { include_ambient: null, include_tools: null },
};

function withScenario(scenario: unknown): unknown {
  return { assembly: "plan-authoring", scenarios: [scenario] };
}

function withLayer(layer: unknown): unknown {
  return { ...RENDER, layers: [layer] };
}

test("parseAssemblyOptions accepts the exact wire shape", () => {
  assert.deepEqual(parseAssemblyOptions(structuredClone(OPTIONS)), OPTIONS);
});

test("parseAssemblyOptions rejects non-object and ill-rooted input", () => {
  assert.equal(parseAssemblyOptions(null), null);
  assert.equal(parseAssemblyOptions(undefined), null);
  assert.equal(parseAssemblyOptions("options"), null);
  assert.equal(parseAssemblyOptions([OPTIONS]), null);
  assert.equal(parseAssemblyOptions({ scenarios: OPTIONS.scenarios }), null);
  assert.equal(parseAssemblyOptions({ assembly: "", scenarios: OPTIONS.scenarios }), null);
  assert.equal(parseAssemblyOptions({ assembly: 7, scenarios: OPTIONS.scenarios }), null);
  assert.equal(parseAssemblyOptions({ assembly: "plan-authoring" }), null);
  assert.equal(parseAssemblyOptions({ assembly: "plan-authoring", scenarios: {} }), null);
});

test("parseAssemblyOptions rejects an empty scenarios array", () => {
  assert.equal(parseAssemblyOptions({ assembly: "plan-authoring", scenarios: [] }), null);
});

const SCENARIO_KEYS = ["id", "label", "variables", "include_ambient", "include_tools"] as const;

for (const key of SCENARIO_KEYS) {
  test(`parseAssemblyOptions rejects a scenario missing ${key}`, () => {
    const { [key]: _omitted, ...rest } = SCENARIO_WARM;
    assert.equal(parseAssemblyOptions(withScenario(rest)), null);
  });
}

test("parseAssemblyOptions rejects ill-typed scenario fields", () => {
  assert.equal(parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, id: "" })), null);
  assert.equal(parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, label: 3 })), null);
  assert.equal(
    parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, include_ambient: "yes" })),
    null,
  );
  assert.equal(parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, include_tools: null })), null);
});

test("parseAssemblyOptions rejects non-string variables values and ill-shaped mappings", () => {
  assert.equal(
    parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, variables: { plan: 42 } })),
    null,
  );
  assert.equal(
    parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, variables: { plan: null } })),
    null,
  );
  assert.equal(parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, variables: null })), null);
  assert.equal(parseAssemblyOptions(withScenario({ ...SCENARIO_WARM, variables: ["plan"] })), null);
});

test("parseAssemblyOptions preserves variables in received key order", () => {
  const parsed = parseAssemblyOptions(structuredClone(OPTIONS));
  assert.ok(parsed !== null);
  assert.deepEqual(Object.keys(parsed.scenarios[0].variables), ["objective", "plan"]);
});

test("parseAssemblyRender accepts the exact wire shape with all three layer variants", () => {
  const parsed = parseAssemblyRender(structuredClone(RENDER));
  assert.deepEqual(parsed, RENDER);
  assert.deepEqual(
    parsed?.layers.map((layer) => layer.type),
    ["boundary", "owned", "failure"],
  );
});

test("parseAssemblyRender rejects ill-rooted payloads", () => {
  assert.equal(parseAssemblyRender(null), null);
  assert.equal(parseAssemblyRender({ ...RENDER, assembly: "" }), null);
  assert.equal(parseAssemblyRender({ ...RENDER, scenario: null }), null);
  assert.equal(parseAssemblyRender({ ...RENDER, presentation: { include_ambient: true } }), null);
  assert.equal(
    parseAssemblyRender({
      ...RENDER,
      presentation: { include_ambient: 1, include_tools: true },
    }),
    null,
  );
  assert.equal(parseAssemblyRender({ ...RENDER, layers: {} }), null);
  const { layers: _omitted, ...missingLayers } = RENDER;
  assert.equal(parseAssemblyRender(missingLayers), null);
});

test("parseAssemblyRender rejects an unknown or missing layer type", () => {
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, type: "mystery" })), null);
  const { type: _omitted, ...untyped } = OWNED;
  assert.equal(parseAssemblyRender(withLayer(untyped)), null);
});

test("parseAssemblyRender rejects ill-typed layer presentation fields", () => {
  const presentation = OWNED.presentation;
  const cases: unknown[] = [
    { ...presentation, position: 0 },
    { ...presentation, position: 1.5 },
    { ...presentation, label: 3 },
    { ...presentation, presence: "sometimes" },
    { ...presentation, presence_label: 3 },
    { ...presentation, visibility_control: "weather" },
  ];
  for (const broken of cases) {
    assert.equal(parseAssemblyRender(withLayer({ ...OWNED, presentation: broken })), null);
  }
  const { position: _omitted, ...missing } = presentation;
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, presentation: missing })), null);
});

test("parseAssemblyRender rejects defective owned layers", () => {
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, unit: null })), null);
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, unit: { id: "u" } })), null);
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, content_kind: "carved" })), null);
  assert.equal(parseAssemblyRender(withLayer({ ...OWNED, parts: {} })), null);
  assert.equal(
    parseAssemblyRender(withLayer({ ...OWNED, parts: [{ fragment: null, text: 3 }] })),
    null,
  );
  assert.equal(
    parseAssemblyRender(withLayer({ ...OWNED, parts: [{ fragment: { id: "x" }, text: "t" }] })),
    null,
  );
});

test("parseAssemblyRender rejects defective boundary layers", () => {
  assert.equal(parseAssemblyRender(withLayer({ ...BOUNDARY, boundary: "dmz" })), null);
  assert.equal(parseAssemblyRender(withLayer({ ...BOUNDARY, owner: "someone" })), null);
  const { owner: _omitted, ...missing } = BOUNDARY;
  assert.equal(parseAssemblyRender(withLayer(missing)), null);
});

test("parseAssemblyRender rejects defective failure layers", () => {
  assert.equal(parseAssemblyRender(withLayer({ ...FAILURE, unit: 3 })), null);
  assert.equal(parseAssemblyRender(withLayer({ ...FAILURE, problems: {} })), null);
  const problem = FAILURE.problems[0];
  assert.ok(problem !== undefined);
  assert.equal(
    parseAssemblyRender(withLayer({ ...FAILURE, problems: [{ ...problem, reason: "" }] })),
    null,
  );
  assert.equal(
    parseAssemblyRender(withLayer({ ...FAILURE, problems: [{ ...problem, reason: 3 }] })),
    null,
  );
  assert.equal(
    parseAssemblyRender(withLayer({ ...FAILURE, problems: [{ ...problem, detail: 3 }] })),
    null,
  );
  assert.equal(
    parseAssemblyRender(
      withLayer({ ...FAILURE, problems: [{ ...problem, fragment: { id: "x" } }] }),
    ),
    null,
  );
});

test("parseAssemblyRender accepts an open non-empty problem reason", () => {
  const problem = FAILURE.problems[0];
  assert.ok(problem !== undefined);
  const parsed = parseAssemblyRender(
    withLayer({ ...FAILURE, problems: [{ ...problem, reason: "brand-new-server-reason" }] }),
  );
  assert.ok(parsed !== null);
});

test("assemblyRenderMatchesRequest pins the echoed subject identity", () => {
  assert.equal(assemblyRenderMatchesRequest(RENDER, REQUEST), true);
  assert.equal(
    assemblyRenderMatchesRequest(RENDER, { ...REQUEST, assembly: "other-assembly" }),
    false,
  );
  assert.equal(
    assemblyRenderMatchesRequest(RENDER, { ...REQUEST, scenario: SCENARIO_COLD.id }),
    false,
  );
});

test("resolvedPresentation resolves override ?? scenario default", () => {
  assert.deepEqual(resolvedPresentation(SCENARIO_WARM, { ambient: null, tools: null }), {
    include_ambient: true,
    include_tools: true,
  });
  assert.deepEqual(resolvedPresentation(SCENARIO_WARM, { ambient: false, tools: null }), {
    include_ambient: false,
    include_tools: true,
  });
  assert.deepEqual(resolvedPresentation(SCENARIO_COLD, { ambient: null, tools: true }), {
    include_ambient: false,
    include_tools: true,
  });
});

test("visibleLayers hides exactly the control-matching layers", () => {
  const layers = [BOUNDARY, OWNED, FAILURE];
  assert.deepEqual(visibleLayers(layers, { include_ambient: true, include_tools: true }), layers);
  assert.deepEqual(visibleLayers(layers, { include_ambient: false, include_tools: true }), [
    BOUNDARY,
    FAILURE,
  ]);
  assert.deepEqual(visibleLayers(layers, { include_ambient: true, include_tools: false }), [
    BOUNDARY,
    OWNED,
  ]);
  assert.deepEqual(visibleLayers(layers, { include_ambient: false, include_tools: false }), [
    BOUNDARY,
  ]);
});

test("visibility_control null is never hidden and presence never affects visibility", () => {
  const variesUncontrolled: AssemblyBoundaryLayer = {
    ...BOUNDARY,
    presentation: {
      ...BOUNDARY.presentation,
      presence: "varies",
      presence_label: "Presence varies by session shape or runtime.",
      visibility_control: null,
    },
  };
  assert.deepEqual(
    visibleLayers([variesUncontrolled], { include_ambient: false, include_tools: false }),
    [variesUncontrolled],
  );
});

test("concatenatedText joins owned parts and emits the exact fixed markers", () => {
  assert.equal(
    concatenatedText([BOUNDARY, OWNED, FAILURE]),
    "[[ boundary: System boundary · owner: pi ]]\n\nHello world\n\n\n[[ layer failed: unit:tool ]]",
  );
});

test("concatenatedText falls back to the boundary kind when the label is null", () => {
  const unlabeled: AssemblyBoundaryLayer = {
    ...BOUNDARY,
    presentation: { ...BOUNDARY.presentation, label: null },
  };
  assert.equal(concatenatedText([unlabeled]), "[[ boundary: pi-system · owner: pi ]]");
});

test("concatenatedText over visibleLayers excludes toggle-hidden layers", () => {
  const visible = visibleLayers([BOUNDARY, OWNED, FAILURE], {
    include_ambient: false,
    include_tools: true,
  });
  assert.equal(
    concatenatedText(visible),
    "[[ boundary: System boundary · owner: pi ]]\n\n[[ layer failed: unit:tool ]]",
  );
});
