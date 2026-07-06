// Offline tests for the plan-steps consumer: pure `sanitizeSteps`/`llmStepsEnabled`, plus
// `generatePlanSteps` driven by a faux pi-ai provider (happy path, gate-on, schema-invalid).

import assert from "node:assert/strict";
import { test } from "node:test";
import { type Api, fauxAssistantMessage, fauxToolCall, type Model } from "@earendil-works/pi-ai";
import { registerFauxProvider } from "@earendil-works/pi-ai/compat";
import type { ModelAuthContext } from "../substrate/structuredOutput.ts";
import { generatePlanSteps, llmStepsEnabled, sanitizeSteps } from "./planSteps.ts";

test("sanitizeSteps: strips echoed list markers and collapses whitespace", () => {
  assert.deepEqual(
    sanitizeSteps(["1. Add the   helper", "2) Wire it\n  in", "- Add a test", "* Run CI"]),
    ["Add the helper", "Wire it in", "Add a test", "Run CI"],
  );
});

test("sanitizeSteps: drops empties and truncates over-long steps", () => {
  const long = "x".repeat(300);
  const out = sanitizeSteps(["  ", "one step", long]);
  assert.ok(out);
  assert.equal(out.length, 2);
  assert.equal(out[1]?.length, 200);
});

test("sanitizeSteps: caps at 12 items", () => {
  const out = sanitizeSteps(Array.from({ length: 20 }, (_, i) => `step ${i + 1}`));
  assert.ok(out);
  assert.equal(out.length, 12);
});

test("sanitizeSteps: null when fewer than 2 survive", () => {
  assert.equal(sanitizeSteps([]), null);
  assert.equal(sanitizeSteps(["only one"]), null);
  assert.equal(sanitizeSteps(["  ", "\n", "one"]), null);
});

test("llmStepsEnabled: true when PERK_NO_LLM unset, false when set", () => {
  assert.equal(llmStepsEnabled({} as NodeJS.ProcessEnv), true);
  assert.equal(llmStepsEnabled({ PERK_NO_LLM: "1" } as NodeJS.ProcessEnv), false);
});

function fakeCtx(
  reg: ReturnType<typeof registerFauxProvider>,
  auth: { ok: true; apiKey?: string } | { ok: false; error: string },
): ModelAuthContext {
  return {
    model: reg.getModel() as unknown as Model<Api>,
    modelRegistry: { getApiKeyAndHeaders: async () => auth },
  };
}

/** Run a callback with PERK_NO_LLM forced to a value (restoring the prior value after). */
async function withGate(value: string | undefined, fn: () => Promise<void>): Promise<void> {
  const prev = process.env.PERK_NO_LLM;
  if (value === undefined) delete process.env.PERK_NO_LLM;
  else process.env.PERK_NO_LLM = value;
  try {
    await fn();
  } finally {
    if (prev === undefined) delete process.env.PERK_NO_LLM;
    else process.env.PERK_NO_LLM = prev;
  }
}

test("generatePlanSteps: happy path returns the sanitized steps", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage(
        [fauxToolCall("set_plan_steps", { steps: ["1. Add the module", "Wire it in", "Test it"] })],
        { stopReason: "toolUse" },
      ),
    ]);
    await withGate(undefined, async () => {
      const steps = await generatePlanSteps(fakeCtx(reg, { ok: true }), "the plan body");
      assert.deepEqual(steps, ["Add the module", "Wire it in", "Test it"]);
    });
  } finally {
    reg.unregister();
  }
});

test("generatePlanSteps: gated by PERK_NO_LLM → null, no model call", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("set_plan_steps", { steps: ["a", "b"] })], {
        stopReason: "toolUse",
      }),
    ]);
    await withGate("1", async () => {
      const steps = await generatePlanSteps(fakeCtx(reg, { ok: true }), "the plan body");
      assert.equal(steps, null);
      assert.equal(reg.state.callCount, 0);
    });
  } finally {
    reg.unregister();
  }
});

test("generatePlanSteps: unresolved auth → null, no model call", async () => {
  const reg = registerFauxProvider();
  try {
    await withGate(undefined, async () => {
      const steps = await generatePlanSteps(
        fakeCtx(reg, { ok: false, error: "no key" }),
        "the plan body",
      );
      assert.equal(steps, null);
      assert.equal(reg.state.callCount, 0);
    });
  } finally {
    reg.unregister();
  }
});

test("generatePlanSteps: schema-invalid tool args → null", async () => {
  const reg = registerFauxProvider();
  try {
    // `steps` missing entirely — fails schema validation.
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("set_plan_steps", { wrong: true })], {
        stopReason: "toolUse",
      }),
    ]);
    await withGate(undefined, async () => {
      const steps = await generatePlanSteps(fakeCtx(reg, { ok: true }), "the plan body");
      assert.equal(steps, null);
    });
  } finally {
    reg.unregister();
  }
});
