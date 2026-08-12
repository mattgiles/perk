// Offline tests for the structured-output substrate. A faux pi-ai provider scripts
// deterministic assistant messages (tool calls / text) so `completeStructured` is exercised with no
// network. `resolveModelAuth` is unit-tested with fake contexts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type Api,
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
  type Model,
  Type,
} from "@earendil-works/pi-ai";
import { registerFauxProvider } from "@earendil-works/pi-ai/compat";
import { generatePlanTitle } from "../factories/planTitle.ts";
import { completeStructured, type ModelAuthContext, resolveModelAuth } from "./structuredOutput.ts";

const Schema = Type.Object({
  title: Type.String({ minLength: 1 }),
  category: Type.String(),
});

function model(reg: ReturnType<typeof registerFauxProvider>): Model<Api> {
  return reg.getModel() as unknown as Model<Api>;
}

test("completeStructured returns the validated tool-call arguments", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage(
        [
          fauxToolCall("set_plan_title", {
            title: "Add retry to the gateway",
            category: "feature",
          }),
        ],
        { stopReason: "toolUse" },
      ),
    ]);
    const outcome = await completeStructured({
      model: model(reg),
      schema: Schema,
      toolName: "set_plan_title",
      toolDescription: "Set the title.",
      instruction: "Choose a title.",
      input: "some plan",
    });
    assert.equal(outcome.ok, true);
    assert.equal(outcome.value?.title, "Add retry to the gateway");
    assert.equal(outcome.value?.category, "feature");
  } finally {
    reg.unregister();
  }
});

test("completeStructured fails when the model returns no tool call", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([fauxAssistantMessage([fauxText("just some prose")], { stopReason: "stop" })]);
    const outcome = await completeStructured({
      model: model(reg),
      schema: Schema,
      toolName: "set_plan_title",
      toolDescription: "Set the title.",
      instruction: "Choose a title.",
      input: "some plan",
    });
    assert.equal(outcome.ok, false);
    assert.match(outcome.error ?? "", /no tool call/);
  } finally {
    reg.unregister();
  }
});

test("completeStructured fails when tool-call arguments violate the schema", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage(
        // Missing the required `title` field.
        [fauxToolCall("set_plan_title", { category: "feature" })],
        { stopReason: "toolUse" },
      ),
    ]);
    const outcome = await completeStructured({
      model: model(reg),
      schema: Schema,
      toolName: "set_plan_title",
      toolDescription: "Set the title.",
      instruction: "Choose a title.",
      input: "some plan",
    });
    assert.equal(outcome.ok, false);
  } finally {
    reg.unregister();
  }
});

test("completeStructured fails on a provider error message", async () => {
  const reg = registerFauxProvider();
  try {
    reg.setResponses([
      fauxAssistantMessage([fauxText("")], { stopReason: "error", errorMessage: "boom" }),
    ]);
    const outcome = await completeStructured({
      model: model(reg),
      schema: Schema,
      toolName: "set_plan_title",
      toolDescription: "Set the title.",
      instruction: "Choose a title.",
      input: "some plan",
    });
    assert.equal(outcome.ok, false);
    assert.equal(outcome.error, "boom");
  } finally {
    reg.unregister();
  }
});

test("resolveModelAuth: no model → ok:false", async () => {
  const ctx: ModelAuthContext = {
    model: undefined,
    modelRegistry: { getApiKeyAndHeaders: async () => ({ ok: true }) },
  };
  const auth = await resolveModelAuth(ctx);
  assert.equal(auth.ok, false);
});

test("resolveModelAuth: resolves the model + apiKey", async () => {
  const reg = registerFauxProvider();
  try {
    const ctx: ModelAuthContext = {
      model: model(reg),
      modelRegistry: { getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "k" }) },
    };
    const auth = await resolveModelAuth(ctx);
    assert.equal(auth.ok, true);
    if (auth.ok) assert.equal(auth.apiKey, "k");
  } finally {
    reg.unregister();
  }
});

test("resolveModelAuth: propagates an auth failure", async () => {
  const reg = registerFauxProvider();
  try {
    const ctx: ModelAuthContext = {
      model: model(reg),
      modelRegistry: { getApiKeyAndHeaders: async () => ({ ok: false, error: "no key" }) },
    };
    const auth = await resolveModelAuth(ctx);
    assert.equal(auth.ok, false);
    if (!auth.ok) assert.equal(auth.error, "no key");
  } finally {
    reg.unregister();
  }
});

test("resolveModelAuth: nullable headers + baseUrl + env pass through unchanged", async () => {
  const reg = registerFauxProvider();
  try {
    const ctx: ModelAuthContext = {
      model: model(reg),
      modelRegistry: {
        getApiKeyAndHeaders: async () => ({
          ok: true,
          apiKey: "k",
          // A null value is pi-ai's header-deletion marker — it must survive untouched.
          headers: { "x-custom": "v", "x-drop": null },
          baseUrl: "https://resolved.example",
          env: { CLOUDFLARE_ACCOUNT_ID: "acct" },
        }),
      },
    };
    const auth = await resolveModelAuth(ctx);
    assert.equal(auth.ok, true);
    if (auth.ok) {
      assert.deepEqual(auth.headers, { "x-custom": "v", "x-drop": null });
      assert.equal(auth.baseUrl, "https://resolved.example");
      assert.deepEqual(auth.env, { CLOUDFLARE_ACCOUNT_ID: "acct" });
    }
  } finally {
    reg.unregister();
  }
});

// --- registry dispatch vs the widened fallback (the two generatePlanTitle auth paths) ------------

/** Run a callback with PERK_NO_LLM forced off (restoring the prior value after). */
async function withoutGate(fn: () => Promise<void>): Promise<void> {
  const prev = process.env.PERK_NO_LLM;
  delete process.env.PERK_NO_LLM;
  try {
    await fn();
  } finally {
    if (prev === undefined) delete process.env.PERK_NO_LLM;
    else process.env.PERK_NO_LLM = prev;
  }
}

test("dispatch path: a registry WITH complete routes through it — no getApiKeyAndHeaders call", async () => {
  const reg = registerFauxProvider();
  try {
    await withoutGate(async () => {
      let dispatchCalls = 0;
      let authCalls = 0;
      const ctx: ModelAuthContext = {
        model: model(reg),
        modelRegistry: {
          getApiKeyAndHeaders: async () => {
            authCalls += 1;
            return { ok: true };
          },
          complete: async () => {
            dispatchCalls += 1;
            return fauxAssistantMessage(
              [fauxToolCall("set_plan_title", { title: "Dispatched title", category: "feature" })],
              { stopReason: "toolUse" },
            );
          },
        },
      };
      const title = await generatePlanTitle(ctx, "the plan body");
      assert.equal(title, "Dispatched title");
      assert.equal(dispatchCalls, 1, "the registry dispatch carried the call");
      assert.equal(authCalls, 0, "resolveModelAuth was skipped entirely");
      assert.equal(reg.state.callCount, 0, "the compat complete path was never hit");
    });
  } finally {
    reg.unregister();
  }
});

test("fallback path: a registry WITHOUT complete resolves auth; env (not baseUrl) reaches complete", async () => {
  const reg = registerFauxProvider();
  try {
    await withoutGate(async () => {
      const captured: Record<string, unknown>[] = [];
      reg.setResponses([
        (_context, options) => {
          captured.push((options ?? {}) as Record<string, unknown>);
          return fauxAssistantMessage(
            [fauxToolCall("set_plan_title", { title: "Fallback title", category: "fix" })],
            { stopReason: "toolUse" },
          );
        },
      ]);
      const ctx: ModelAuthContext = {
        model: model(reg),
        modelRegistry: {
          getApiKeyAndHeaders: async () => ({
            ok: true,
            apiKey: "k",
            headers: { "x-custom": "v", "x-drop": null },
            baseUrl: "https://resolved.example",
            env: { CLOUDFLARE_ACCOUNT_ID: "acct" },
          }),
        },
      };
      const title = await generatePlanTitle(ctx, "the plan body");
      assert.equal(title, "Fallback title");
      const opts = captured[0] ?? {};
      assert.equal(opts.apiKey, "k");
      // Nulls included — pi's migration note: forward ProviderHeaders unchanged.
      assert.deepEqual(opts.headers, { "x-custom": "v", "x-drop": null });
      assert.deepEqual(opts.env, { CLOUDFLARE_ACCOUNT_ID: "acct" });
      // The compat complete has no baseUrl option — the fallback's named limitation.
      assert.ok(!("baseUrl" in opts), "baseUrl must not leak into the compat complete options");
    });
  } finally {
    reg.unregister();
  }
});
