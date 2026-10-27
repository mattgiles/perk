// Durable characterization — P7 (capabilities bind to the assignment and are enforced at the
// operation), docs/design/pi-durable-v2-foundations.md §3 P7. Two enforcement points Perk builds
// on: `beforeTool` gates a call before its intent is recorded, so a `replay: "safe"` tool that a
// crash interrupted reruns `execute` without asking the hook again (and an unsafe one is not rerun
// at all); and the built-in `read` tool touches files only through the call's execution
// environment, with no filesystem fallback when none is configured.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin): src/harness/tool.ts::ToolTask
// (`beforeTool` runs only in the `call` phase); src/tools/read.ts::createReadTool (`requireEnv`,
// `resolveReadToolPath`, `env.openBinaryReader`);
// test/harness-tools-recovery.test.ts::"reruns a tool only when both the stored and the current
// replay policy are safe"; test/tools.test.ts::"durable tools/read". No upstream test asserts that
// a recovered safe tool skips `beforeTool` — D8 pins it.

import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, hook, MemoryStorage, ToolTask } from "@earendil-works/pi-durable";
import { NodeExecutionEnv } from "@earendil-works/pi-durable/env/node";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { createReadTool } from "@earendil-works/pi-durable/tools";
import {
  aborted,
  allEntries,
  CASE_TIMEOUT_MS,
  context,
  DONE,
  deferred,
  fauxSetup,
  installTools,
  open,
  resultText,
  sqlitePath,
  tempDir,
  toolCall,
  toolResults,
} from "../testing/durable.ts";

/**
 * Run one call of a `work` tool declared `replay`, interrupt it mid-`execute` by closing the
 * Harness (its intent is already committed), reopen, and let the run finish. Every hook call,
 * execution and lifecycle step goes to one log.
 */
async function interruptAndRecover(t: TestContext, replay: "safe" | "unsafe") {
  const log: string[] = [];
  const started = deferred();
  let runs = 0;
  const work = defineTool({
    name: "work",
    description: "Work that blocks until cancelled on its first run",
    parameters: Type.Object({}),
    replay,
    execute: async (_args, api, callContext) => {
      runs++;
      log.push("execute");
      api.output("run\n");
      if (runs === 1) {
        started.resolve();
        const signal = callContext.abortSignal;
        if (signal === undefined) throw new Error("the call carries no abort signal");
        await aborted(signal);
      }
      return {};
    },
  });
  const gate = hook(ToolTask, {
    beforeTool: () => {
      log.push("beforeTool");
      return undefined;
    },
  });
  const setup = fauxSetup();
  installTools(setup, "work", [work], [gate]);
  setup.faux.setResponses([toolCall("work"), DONE]);
  const path = await sqlitePath(t);

  const first = await open(t, await openNodeSqliteStorage(path), setup);
  await first.root.configure({ tools: [work] }, context);
  first.harness.resume();
  const { id } = await first.root.submit({ type: "input", content: "go" }, context);
  await started.promise;
  log.push("close");
  await first.dispose();

  const second = await open(t, await openNodeSqliteStorage(path), setup);
  log.push("reopen");
  second.harness.resume();
  const submission = await second.harness.submission(id, context);
  assert.ok(submission, "the submission is reacquirable after reopen");
  const settled = await submission.wait(context);
  return { log, settled, results: toolResults(await allEntries(second.root)) };
}

test('D8 (P7): a recovered replay:"safe" tool runs execute without beforeTool', {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { log, settled, results } = await interruptAndRecover(t, "safe");
  assert.equal(settled.status, "done");
  assert.deepEqual(log, ["beforeTool", "execute", "close", "reopen", "execute"]);
  assert.equal(results.length, 1);
  const [result] = results;
  assert.ok(result);
  assert.notEqual(result.isError, true);
  assert.equal(resultText(result), "run\n", "the result is the rerun's own output");
});

test('D8c (P7): an interrupted replay:"unsafe" tool is not rerun', {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { log, settled, results } = await interruptAndRecover(t, "unsafe");
  assert.equal(settled.status, "done");
  assert.deepEqual(log, ["beforeTool", "execute", "close", "reopen"]);
  assert.equal(results.length, 1);
  const [result] = results;
  assert.ok(result);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /was interrupted and may have partially run/);
});

/** A work directory holding `notes.txt`, and a file outside it. */
async function readFixture(t: TestContext) {
  const workdir = await tempDir(t, "perk-v2-read-root-");
  await writeFile(join(workdir, "notes.txt"), "hello durable");
  const outside = join(await tempDir(t, "perk-v2-read-outside-"), "outside.txt");
  await writeFile(outside, "beyond the root");
  return { workdir, outside };
}

test("D9 (P7): built-in read touches files only through the call's environment", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { workdir, outside } = await readFixture(t);
  const log: string[] = [];
  const env = new NodeExecutionEnv({ cwd: workdir });
  t.after(() => env.cleanup(context));
  // Every environment method call is logged with its first argument, then applied on the real env.
  const recorded = new Proxy(env, {
    get(target, property) {
      const value: unknown = Reflect.get(target, property, target);
      if (typeof value !== "function") return value;
      return (...args: unknown[]) => {
        log.push(`env:${String(property)}:${String(args[0])}`);
        return Reflect.apply(value, target, args);
      };
    },
  });
  const setup = fauxSetup();
  installTools(setup, "read", [createReadTool()]);
  setup.faux.setResponses([
    toolCall("read", { path: "notes.txt" }, "r1"),
    toolCall("read", { path: outside }, "r2"),
    DONE,
  ]);
  const { harness, root } = await open(t, new MemoryStorage(), setup, { env: () => recorded });
  harness.resume();

  const settled = await (await root.submit({ type: "input", content: "read" }, context)).wait(
    context,
  );
  assert.equal(settled.status, "done");
  const results = toolResults(await allEntries(root));
  assert.equal(results.length, 2);
  const [inside, beyond] = results;
  assert.ok(inside && beyond);
  assert.notEqual(inside.isError, true);
  assert.notEqual(beyond.isError, true);
  assert.match(resultText(inside), /hello durable/);
  assert.match(resultText(beyond), /beyond the root/);

  const notes = join(workdir, "notes.txt");
  for (const call of [
    "env:absolutePath:notes.txt",
    `env:exists:${notes}`,
    `env:openBinaryReader:${notes}`,
    // The out-of-root absolute path is still routed through the environment: containment is the
    // environment's job, not the tool's.
    `env:absolutePath:${outside}`,
    `env:openBinaryReader:${outside}`,
  ]) {
    assert.ok(log.includes(call), `the environment saw ${call}; it saw: ${log.join(", ")}`);
  }
});

test("D9c (P7): read without an environment has no filesystem fallback", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { workdir } = await readFixture(t);
  const setup = fauxSetup();
  installTools(setup, "read", [createReadTool()]);
  setup.faux.setResponses([toolCall("read", { path: "notes.txt" }), DONE]);
  const { harness, root } = await open(t, new MemoryStorage(), setup);
  // A fallback would have a real directory to read from.
  await root.configure({ cwd: workdir }, context);
  harness.resume();

  const settled = await (await root.submit({ type: "input", content: "read" }, context)).wait(
    context,
  );
  assert.equal(settled.status, "done");
  const results = toolResults(await allEntries(root));
  assert.equal(results.length, 1);
  const [result] = results;
  assert.ok(result);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /No execution environment is configured/);
  assert.ok(
    results.every((message) => message.isError || !resultText(message).includes("hello durable")),
    "no result read the file",
  );
});
