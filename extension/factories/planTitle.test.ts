// Offline tests for the plan-title consumer: pure `sanitizeTitle`/`llmTitlesEnabled`, plus
// `generatePlanTitle` driven by a faux pi-ai provider (happy path, gate-on, no-auth).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type Api,
  fauxAssistantMessage,
  fauxToolCall,
  type Model,
  registerFauxProvider,
} from "@earendil-works/pi-ai";
import type { ModelAuthContext } from "../substrate/structuredOutput.ts";
import { generatePlanTitle, llmTitlesEnabled, sanitizeTitle } from "./planTitle.ts";

test("sanitizeTitle: strips a leading heading marker", () => {
  assert.equal(sanitizeTitle("# Add a retry to the gateway"), "Add a retry to the gateway");
});

test("sanitizeTitle: strips surrounding quotes and backticks", () => {
  assert.equal(sanitizeTitle('"Fix the parser"'), "Fix the parser");
  assert.equal(sanitizeTitle("`Fix the parser`"), "Fix the parser");
  assert.equal(sanitizeTitle("'Fix the parser'"), "Fix the parser");
});

test("sanitizeTitle: collapses internal whitespace and newlines", () => {
  assert.equal(sanitizeTitle("Add\n  retry   logic"), "Add retry logic");
});

test("sanitizeTitle: truncates over-long input on a word boundary", () => {
  const long = `${"word ".repeat(40)}end`;
  const out = sanitizeTitle(long);
  assert.ok(out);
  assert.ok((out as string).length <= 120);
  assert.ok(!(out as string).endsWith(" "));
});

test("sanitizeTitle: returns null for empty/whitespace", () => {
  assert.equal(sanitizeTitle(""), null);
  assert.equal(sanitizeTitle("   \n  "), null);
  assert.equal(sanitizeTitle("#   "), null);
});

test("llmTitlesEnabled: true when PERK_NO_LLM unset, false when set", () => {
  assert.equal(llmTitlesEnabled({} as NodeJS.ProcessEnv), true);
  assert.equal(llmTitlesEnabled({ PERK_NO_LLM: "1" } as NodeJS.ProcessEnv), false);
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

test("generatePlanTitle: happy path returns the sanitized title", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage(
        [fauxToolCall("set_plan_title", { title: "# Add structured output", category: "feature" })],
        { stopReason: "toolUse" },
      ),
    ]);
    await withGate(undefined, async () => {
      const title = await generatePlanTitle(fakeCtx(reg, { ok: true }), "the plan body");
      assert.equal(title, "Add structured output");
    });
  } finally {
    reg.unregister();
  }
});

test("generatePlanTitle: gated by PERK_NO_LLM → null, no model call", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("set_plan_title", { title: "x", category: "fix" })], {
        stopReason: "toolUse",
      }),
    ]);
    await withGate("1", async () => {
      const title = await generatePlanTitle(fakeCtx(reg, { ok: true }), "the plan body");
      assert.equal(title, null);
      assert.equal(reg.state.callCount, 0);
    });
  } finally {
    reg.unregister();
  }
});

test("generatePlanTitle: unresolved auth → null", async () => {
  const reg = registerFauxProvider();
  try {
    await withGate(undefined, async () => {
      const title = await generatePlanTitle(
        fakeCtx(reg, { ok: false, error: "no key" }),
        "the plan body",
      );
      assert.equal(title, null);
      assert.equal(reg.state.callCount, 0);
    });
  } finally {
    reg.unregister();
  }
});
