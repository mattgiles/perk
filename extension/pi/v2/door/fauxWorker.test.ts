// V7 — the production faux worker (docs/design/pi-durable-v2-foundations.md §12, contracts.md
// §8.77): a fixture worker prompt gets one `report` call over the prompt's tree, a transcript that
// already holds a tool result gets `done`, anything else gets a provider error; the catalog serves
// `faux/faux-1` and never runs dry, even under many requests shifted before any step runs.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { AssistantMessage, Message, ToolCall } from "@earendil-works/pi-ai";
import {
  FIXTURE_WORKER_QUEUE_DEPTH,
  FIXTURE_WORKER_SUMMARY,
  fixtureWorkerModels,
  fixtureWorkerResponse,
} from "../durable/fauxWorker.ts";
import { FIXTURE_MODEL, FIXTURE_REPORT_TOOL, fixtureWorkerPrompt } from "../kernel/fixture.ts";
import { T1, T2 } from "../testing/binding.ts";

function user(content: string | { type: "text"; text: string }[]): Message {
  return { role: "user", content, timestamp: 0 };
}

function toolResult(): Message {
  return {
    role: "toolResult",
    toolCallId: "report-1",
    toolName: FIXTURE_REPORT_TOOL,
    content: [{ type: "text", text: "accepted" }],
    isError: false,
    timestamp: 0,
  };
}

function toolCalls(message: AssistantMessage): ToolCall[] {
  return message.content.filter((part): part is ToolCall => part.type === "toolCall");
}

function assertError(message: AssistantMessage, label: string): void {
  assert.equal(message.stopReason, "error", label);
  assert.equal(message.errorMessage, "not a fixture worker prompt", label);
  assert.deepEqual(toolCalls(message), [], `${label}: no tool call`);
}

test("V7: a fixture worker prompt gets one report call over the prompt's tree", () => {
  for (const [role, tree] of [
    ["a", T1],
    ["b", T2],
  ] as const) {
    const answer = fixtureWorkerResponse([user(fixtureWorkerPrompt(role, tree))]);
    assert.equal(answer.stopReason, "toolUse");
    const calls = toolCalls(answer);
    assert.equal(calls.length, 1, "exactly one call");
    assert.equal(calls[0]?.name, FIXTURE_REPORT_TOOL);
    assert.equal(calls[0]?.id, "report-1");
    assert.deepEqual(calls[0]?.arguments, {
      subjectDigest: tree,
      summary: FIXTURE_WORKER_SUMMARY,
      findings: [],
    });
  }
  // The prompt as text parts reads the same.
  const prompt = fixtureWorkerPrompt("a", T1);
  const parts = fixtureWorkerResponse([
    user([
      { type: "text", text: prompt.slice(0, 10) },
      { type: "text", text: prompt.slice(10) },
    ]),
  ]);
  assert.equal(toolCalls(parts)[0]?.arguments.subjectDigest, T1);
});

test("V7: a transcript holding a tool result gets the final text", () => {
  const answer = fixtureWorkerResponse([user(fixtureWorkerPrompt("a", T1)), toolResult()]);
  assert.deepEqual(toolCalls(answer), []);
  assert.deepEqual(
    answer.content.map((part) => (part.type === "text" ? part.text : part.type)),
    ["done"],
  );
});

test("V7: a non-fixture or malformed prompt gets a provider error", () => {
  assertError(fixtureWorkerResponse([]), "no user message");
  assertError(fixtureWorkerResponse([user("hello")]), "a non-fixture prompt");
  assertError(
    fixtureWorkerResponse([user("Review subject not-a-tree as reviewer a.")]),
    "a malformed tree",
  );
  assertError(
    fixtureWorkerResponse([user(`Review subject ${T1} as reviewer A!.`)]),
    "a malformed role",
  );
  assertError(fixtureWorkerResponse([user(`${fixtureWorkerPrompt("a", T1)} `)]), "trailing text");
  // A later fixture prompt does not rescue a non-fixture first user message.
  assertError(
    fixtureWorkerResponse([user("hello"), user(fixtureWorkerPrompt("a", T1))]),
    "the first user message decides",
  );
});

test("V7: the catalog serves faux/faux-1 and never runs dry", async () => {
  const models = fixtureWorkerModels();
  const model = models.getModel(FIXTURE_MODEL.provider, FIXTURE_MODEL.modelId);
  assert.ok(model !== undefined, "faux/faux-1 resolves");
  // Rounds of a full queue's worth of requests, all shifted before any step runs: each step
  // replenishes the queue, so every round is answered in full.
  for (let round = 0; round < 3; round++) {
    const answers: AssistantMessage[] = await Promise.all(
      Array.from({ length: FIXTURE_WORKER_QUEUE_DEPTH }, (_, i) =>
        models.completeSimple(model, {
          messages: [user(fixtureWorkerPrompt(i % 2 === 0 ? "a" : "b", T1))],
        }),
      ),
    );
    for (const answer of answers) {
      assert.equal(answer.stopReason, "toolUse", `round ${round}: ${answer.errorMessage}`);
      assert.equal(toolCalls(answer)[0]?.arguments.subjectDigest, T1);
    }
  }
});
