// #129 — offline tests for the structured-output substrate. A faux pi-ai provider scripts
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
  registerFauxProvider,
  Type,
} from "@earendil-works/pi-ai";
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
