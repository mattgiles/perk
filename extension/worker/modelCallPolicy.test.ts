// Offline coverage for the worker's model-call policy: the advisory textual screen
// (`refusedModelCallIn`), the typed refusal reasons, and the hard-layer constant.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MODEL_CALL_REFUSAL_PREFIX,
  modelCallRefusalReason,
  type RefusedModelCall,
  refusedModelCallIn,
  WORKER_CODEMODE_MODELS,
} from "./modelCallPolicy.ts";

const CASES: { name: string; code: string; expected: RefusedModelCall | null }[] = [
  {
    name: "a classifier call",
    code: 'const r = await models.classify({ provider: "p", id: "c" }, ctx);',
    expected: "classifier",
  },
  {
    name: "an image-generation call",
    code: "await models.generateImages(model, { input: [] });",
    expected: "image_generation",
  },
  {
    name: "both — the first by position (image first)",
    code: "await models.generateImages(m, c);\nawait models.classify(m, c);",
    expected: "image_generation",
  },
  {
    name: "both — the first by position (classifier first)",
    code: "await models.classify(m, c);\nawait models.generateImages(m, c);",
    expected: "classifier",
  },
  {
    name: "whitespace inside the member access and before the call",
    code: "await models . classify (m, c);",
    expected: "classifier",
  },
  {
    name: "a newline inside the member access",
    code: "await models\n  .generateImages(m, c);",
    expected: "image_generation",
  },
  {
    name: "a catalog read alone (unmetered, never refused)",
    code: 'const list = await models.getAvailableOfType("classifier");',
    expected: null,
  },
  {
    name: "the other catalog reads",
    code: 'models.getModelsOfType("chat"); await models.getModelOfType("classifier", "p", "c");',
    expected: null,
  },
  { name: "a property read that is not a call", code: "return models.length;", expected: null },
  {
    name: "the member named without a call",
    code: "const f = models.classify;",
    expected: null,
  },
  {
    name: "a longer identifier ending in `models`",
    code: "mymodels.classify(m, c);",
    expected: null,
  },
  {
    name: "the documented alias bypass (the hard layer's job)",
    code: "const m = models; await m.classify(ref, ctx);",
    expected: null,
  },
  { name: "empty code", code: "", expected: null },
];

for (const { name, code, expected } of CASES) {
  test(`refusedModelCallIn: ${name} → ${String(expected)}`, () => {
    assert.equal(refusedModelCallIn(code), expected);
  });
}

test("refusedModelCallIn: repeated calls are stable (no shared regex state)", () => {
  const code = "await models.classify(m, c);";
  assert.equal(refusedModelCallIn(code), "classifier");
  assert.equal(refusedModelCallIn(code), "classifier");
  assert.equal(refusedModelCallIn("nothing here"), null);
});

test("modelCallRefusalReason: every reason starts with the typed prefix + kind + `)`", () => {
  for (const kind of ["image_generation", "classifier"] as const) {
    const reason = modelCallRefusalReason(kind);
    assert.ok(
      reason.startsWith(`${MODEL_CALL_REFUSAL_PREFIX}${kind})`),
      `the ${kind} reason carries the typed prefix`,
    );
    assert.ok(reason.includes("do not retry the call"), "the reason is actionable");
  }
  assert.ok(modelCallRefusalReason("image_generation").includes("`models.generateImages`"));
  assert.ok(modelCallRefusalReason("classifier").includes("`models.classify`"));
});

test("WORKER_CODEMODE_MODELS: the worker-owned codemode has no `models` namespace", () => {
  assert.equal(WORKER_CODEMODE_MODELS, false);
});
