// Durable characterization — P6 (acceptance is semantic), docs/design/pi-durable-v2-foundations.md
// §3 P6. A tool can end a run with a structured, schema-validated result: when every result of the
// round sets `control.terminate`, the run is done with no further model request — the answer is
// the tool-calling assistant entry, not a model-written recap.
//
// A model-issued call's structured output is checked against the tool's schema and then kept
// nowhere (the model reads only `output`); a missing or invalid one is dropped and reported to the
// host, while the text result and the termination still stand. So the host report channel is the
// only witness that the structured output was accepted, and D7 asserts it stayed silent.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin):
// src/harness/generation.ts::finishToolRound; src/harness/tool.ts::finalResult;
// test/harness-tools.test.ts::"applies addTools and terminates only when every result of the round
// asks to".

import assert from "node:assert/strict";
import { test } from "node:test";
import { Type } from "@earendil-works/pi-ai";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { defineTool, MemoryStorage } from "@earendil-works/pi-durable";
import {
  allEntries,
  CASE_TIMEOUT_MS,
  context,
  fauxSetup,
  installTools,
  open,
  resultText,
  toolCall,
  toolResults,
} from "../testing/durable.ts";

const report = defineTool({
  name: "report",
  description: "Report the verdict and end the run",
  parameters: Type.Object({ verdict: Type.String() }),
  structuredOutputSchema: Type.Object({ verdict: Type.String(), accepted: Type.Boolean() }),
  execute: async (args) => ({
    output: [{ type: "text", text: "accepted" }],
    structuredOutput: { verdict: args.verdict, accepted: true },
    control: { terminate: true },
  }),
});

test("D7 (P6): structured tool output + control.terminate ends a run without a recap", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const setup = fauxSetup();
  installTools(setup, "report", [report]);
  setup.faux.setResponses([
    toolCall("report", { verdict: "ok" }),
    fauxAssistantMessage("RECAP — must never be requested"),
  ]);
  const { harness, root } = await open(t, new MemoryStorage(), setup);
  await root.configure({ tools: [report] }, context);
  harness.resume();

  const submission = await root.submit({ type: "input", content: "judge" }, context);
  const settled = await submission.wait(context);
  assert.equal(settled.status, "done");
  assert.equal(setup.faux.state.callCount, 1, "one model request: no recap was asked for");
  assert.equal(setup.faux.getPendingResponseCount(), 1, "the recap response stayed unused");

  const entries = await allEntries(root);
  assert.equal(entries.at(-1)?.kind, "pi.tool-result", "the transcript ends on the tool result");
  const [result] = toolResults(entries);
  assert.ok(result, "the round has a tool result");
  assert.notEqual(result.isError, true);
  assert.equal(resultText(result), "accepted");
  // A dropped structured output would surface here as an `extension_error` report.
  assert.deepEqual(setup.infos, [], "the structured output passed its schema: nothing reported");
  assert.deepEqual(setup.reports, []);

  assert.ok(settled.type === "input" && settled.status === "done");
  const answer = entries.find((entry) => entry.id === settled.answer);
  assert.equal(answer?.kind, "pi.assistant");
  const message = answer?.model?.[0];
  assert.ok(message?.role === "assistant", "the answer carries the assistant message");
  assert.ok(
    message.content.some((block) => block.type === "toolCall" && block.name === "report"),
    "the answer is the tool-calling message, not a recap",
  );

  const tasks = await harness.commit(
    (tx) => tx.scanTasks({ conversationId: root.id }, 20),
    context,
  );
  assert.ok(tasks.items.length > 0);
  assert.ok(
    tasks.items.every((task) => task.state.status === "terminal"),
    "every task of the run is terminal",
  );
});
