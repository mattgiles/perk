import assert from "node:assert/strict";
import fs, { readFileSync, renameSync, rmSync, symlinkSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { join } from "node:path";
import { test } from "node:test";
import { staleErrorFixture } from "../testing/staleErrorFixture.ts";
import { ADVERSARIAL_REVIEW_REPORT_SCHEMA } from "./adversarialReviewWave.ts";
import { createStaleErrorGuard } from "./staleErrorCompat.ts";

for (const change of ["grow", "replace"] as const) {
  test(`refuses an artifact that changes during a bounded read (${change})`, (t) => {
    const f = staleErrorFixture(t);
    const guard = positive(f);
    const raw = f.raw();
    const inode = fs.statSync(f.outputPath).ino;
    const originalRead = fs.readSync;
    let changed = false;
    t.mock.method(fs, "readSync", (...args: Parameters<typeof fs.readSync>) => {
      const count = originalRead(...args);
      if (!changed && fs.fstatSync(args[0]).ino === inode) {
        changed = true;
        if (change === "grow") fs.appendFileSync(f.outputPath, " ");
        else {
          renameSync(f.outputPath, `${f.outputPath}.old`);
          f.put(f.outputPath, JSON.stringify(f.report));
        }
      }
      return count;
    });
    syncBuiltinESMExports();
    t.after(() => {
      t.mock.restoreAll();
      syncBuiltinESMExports();
    });
    assert.deepEqual(guard?.(f.handle, raw)?.recoveries ?? [], []);
    assert.ok(changed, "mutation must have reached the actual artifact read");
  });
}

type Fixture = ReturnType<typeof staleErrorFixture>;
function event(f: Fixture, type: string) {
  const value = f.events.find((e) => e.type === type);
  assert.ok(value, `missing ${type}`);
  return value;
}
function positive(f: Fixture, guard = createStaleErrorGuard(f.options, f.dependencies)) {
  assert.ok(guard);
  const result = guard(f.handle, f.raw());
  assert.ok(result);
  assert.equal(result.recoveries.length, 1);
  assert.deepEqual(result.value, [
    { ...f.parent.workflow.value[0], ok: true, error: null, report: f.report },
  ]);
  assert.equal(result.recoveries[0]?.originalError, f.parent.workflow.value[0].error);
  assert.equal(result.recoveries[0]?.runId, "child");
  return guard;
}

test("proven retry/capture/settlement corrects only the in-memory row; raw artifacts stay failed", (t) => {
  const f = staleErrorFixture(t);
  const before = [
    f.raw(),
    readFileSync(join(f.childRoot, "status.json"), "utf8"),
    readFileSync(f.outputPath, "utf8"),
  ];
  const guard = positive(f);
  const proof = guard(f.handle, f.raw())?.recoveries[0];
  assert.ok(proof);
  assert.deepEqual(Object.keys(proof).sort(), [
    "eventsHash",
    "key",
    "originalError",
    "reason",
    "reportHash",
    "runId",
    "sourceHash",
  ]);
  for (const hash of [proof.reportHash, proof.eventsHash, proof.sourceHash])
    assert.match(hash, /^[a-f0-9]{64}$/);
  assert.deepEqual(
    [
      f.raw(),
      readFileSync(join(f.childRoot, "status.json"), "utf8"),
      readFileSync(f.outputPath, "utf8"),
    ],
    before,
  );
});

test("first successful retry response may propose capture before native retry-end, but execution follows it", (t) => {
  const f = staleErrorFixture(t);
  const index = f.events.findIndex((e) => e.type === "auto_retry_end");
  const [end] = f.events.splice(index, 1);
  assert.ok(end);
  f.events.splice(index + 1, 0, end);
  f.flush();
  positive(f);
});

test("adversarial schema and a true streaming report use the same proof", (t) => {
  const f = staleErrorFixture(t, {
    key: "claimed-intent",
    agent: "perk.adversarial-reviewer",
    schema: ADVERSARIAL_REVIEW_REPORT_SCHEMA,
  });
  f.report.streamed = true;
  f.flush();
  positive(f);
});

const mutations: [string, (f: Fixture) => void][] = [
  [
    "inconsistent model identity",
    (f) => {
      f.child.steps[0].attemptedModels[0] = "other/model";
    },
  ],
  [
    "malformed termination flag",
    (f) => {
      Object.assign(f.child, { timedOut: "true" });
    },
  ],
  [
    "capture execution before retry confirmation",
    (f) => {
      const end = f.events.splice(5, 1)[0];
      assert.ok(end);
      f.events.splice(7, 0, end);
    },
  ],
  [
    "wrong workflow id",
    (f) => {
      f.parent.runId = "foreign";
    },
  ],
  [
    "non-complete workflow",
    (f) => {
      f.parent.state = "failed";
    },
  ],
  [
    "parent runtime failure",
    (f) => {
      Object.assign(f.parent, { error: "failed" });
    },
  ],
  [
    "parent deadline exceeded",
    (f) => {
      f.parent.deadlineAt = 399;
    },
  ],
  [
    "duplicate aggregate key",
    (f) => {
      f.parent.workflow.value.push(f.parent.workflow.value[0]);
    },
  ],
  [
    "foreign aggregate key",
    (f) => {
      f.parent.workflow.value[0].key = "scope";
    },
  ],
  [
    "duplicate parent step",
    (f) => {
      f.parent.steps.push(f.parent.steps[0]);
    },
  ],
  [
    "foreign parent step",
    (f) => {
      f.parent.steps[0].parentWorkflowRunId = "foreign";
    },
  ],
  [
    "parent error disagrees",
    (f) => {
      f.parent.steps[0].error = "something else";
    },
  ],
  [
    "foreign inventory",
    (f) => {
      f.parent.workflowChildren.workflowRunId = "foreign";
    },
  ],
  [
    "incomplete inventory",
    (f) => {
      f.parent.workflowChildren.inventoryComplete = false;
    },
  ],
  [
    "foreign inventory tool call",
    (f) => {
      f.parent.workflowChildren.parentToolCallId = "foreign";
    },
  ],
  [
    "duplicate inventory child",
    (f) => {
      f.parent.workflowChildren.children.push(f.parent.workflowChildren.children[0]);
    },
  ],
  [
    "path-traversing child id",
    (f) => {
      f.parent.steps[0].runId = "../../secret";
    },
  ],
  [
    "foreign child workflow",
    (f) => {
      f.child.parentWorkflowRunId = "foreign";
    },
  ],
  [
    "foreign child key",
    (f) => {
      f.child.workflowKey = "scope";
    },
  ],
  [
    "foreign child session",
    (f) => {
      f.child.sessionId = "other";
    },
  ],
  [
    "absent session identity",
    (f) => {
      Reflect.deleteProperty(f.parent, "sessionId");
      Reflect.deleteProperty(f.child, "sessionId");
    },
  ],
  [
    "foreign child cwd",
    (f) => {
      f.child.cwd = "/other";
    },
  ],
  [
    "reused child context",
    (f) => {
      f.child.steps[0].context = "fork";
    },
  ],
  [
    "foreign agent",
    (f) => {
      f.child.steps[0].agent = "other";
    },
  ],
  [
    "foreign session file",
    (f) => {
      f.child.steps[0].sessionFile = "/other";
    },
  ],
  [
    "real child timeout",
    (f) => {
      f.child.deadlineAt = 299;
    },
  ],
  [
    "forced termination",
    (f) => {
      Object.assign(f.child, { forcedTermination: true });
    },
  ],
  [
    "runner nonzero exit",
    (f) => {
      f.child.processTerminal.instances[0].exitCode = 1;
    },
  ],
  [
    "runner signal",
    (f) => {
      Object.assign(f.child.processTerminal.instances[0], { signal: "SIGTERM" });
    },
  ],
  [
    "foreign runner process",
    (f) => {
      f.child.processTerminal.runnerProcessInstanceId = "other";
    },
  ],
  [
    "unobserved process exit",
    (f) => {
      f.child.processTerminal.state = "pending";
    },
  ],
  [
    "different terminal error",
    (f) => {
      f.child.steps[0].error = "Unknown error";
    },
  ],
  [
    "model attempt failure differs",
    (f) => {
      f.child.steps[0].modelAttempts[0].error = "Aborted";
    },
  ],
  [
    "fallback model attempts",
    (f) => {
      f.child.steps[0].modelAttempts.push(f.child.steps[0].modelAttempts[0]);
    },
  ],
  [
    "missing-capture diagnostic",
    (f) => {
      f.child.steps[0].effects.settlementDiagnostic.requiredOutput.missing = true;
    },
  ],
  [
    "observed mutation",
    (f) => {
      f.child.steps[0].effects.settlementDiagnostic.mutation.observed = true;
    },
  ],
  [
    "compaction settlement",
    (f) => {
      f.child.steps[0].effects.settlementDiagnostic.afterCompactionSettlement = true;
    },
  ],
  [
    "acceptance failure",
    (f) => {
      f.child.steps[0].acceptance.status = "failed";
    },
  ],
  [
    "false error prose is insufficient",
    (f) => {
      f.parent.workflow.value[0].error = "Request timed out. (probably recovered)";
    },
  ],
  [
    "foreign event identity",
    (f) => {
      event(f, "agent_settled").subagentRunId = "other";
    },
  ],
  [
    "foreign event agent",
    (f) => {
      event(f, "agent_settled").subagentAgent = "other";
    },
  ],
  [
    "out-of-order event time",
    (f) => {
      event(f, "agent_settled").observedAt = 199;
    },
  ],
  [
    "failed retry",
    (f) => {
      event(f, "auto_retry_end").success = false;
    },
  ],
  [
    "foreign retry attempt",
    (f) => {
      event(f, "auto_retry_end").attempt = 2;
    },
  ],
  [
    "missing retry confirmation",
    (f) => {
      f.events = f.events.filter((e) => e.type !== "auto_retry_end");
    },
  ],
  [
    "historical error absent",
    (f) => {
      f.events.splice(2, 1);
    },
  ],
  [
    "error without diagnostic",
    (f) => {
      event(f, "message_end").message = { role: "assistant", stopReason: "error", content: [] };
    },
  ],
  [
    "unrecovered later error",
    (f) => {
      f.events.splice(
        6,
        0,
        f.wire("message_end", {
          message: {
            role: "assistant",
            stopReason: "error",
            errorMessage: "Request timed out.",
            content: [],
          },
        }),
      );
    },
  ],
  [
    "later abort without errorMessage",
    (f) => {
      f.events.splice(
        6,
        0,
        f.wire("message_end", {
          message: { role: "assistant", stopReason: "aborted", content: [] },
        }),
      );
    },
  ],
  [
    "clean text stop already cleared latch",
    (f) => {
      f.events.splice(
        6,
        0,
        f.wire("message_end", {
          message: {
            role: "assistant",
            stopReason: "stop",
            content: [{ type: "text", text: "Done" }],
          },
        }),
      );
    },
  ],
  [
    "execution arguments disagree",
    (f) => {
      event(f, "tool_execution_start").args = { value: {} };
    },
  ],
  [
    "capture execution failed",
    (f) => {
      event(f, "tool_execution_end").isError = true;
    },
  ],
  [
    "capture did not terminate",
    (f) => {
      event(f, "tool_execution_end").result = {};
    },
  ],
  [
    "wrong capture call id",
    (f) => {
      event(f, "tool_execution_end").toolCallId = "foreign";
    },
  ],
  [
    "capture result absent",
    (f) => {
      f.events.splice(9, 1);
    },
  ],
  [
    "extra action after capture",
    (f) => {
      f.events.splice(10, 0, f.wire("turn_start"));
    },
  ],
  [
    "partial assistant message after capture",
    (f) => {
      f.events.splice(10, 0, f.wire("message_start", { message: { role: "assistant" } }));
    },
  ],
  [
    "missing settlement",
    (f) => {
      f.events = f.events.filter((e) => e.type !== "agent_settled");
    },
  ],
  [
    "duplicate settlement",
    (f) => {
      f.events.splice(12, 0, f.wire("agent_settled"));
    },
  ],
  [
    "stopped run event",
    (f) => {
      f.events.push({ type: "subagent.run.stopped", runId: "child", ts: 320 });
    },
  ],
  [
    "unknown runtime failure event",
    (f) => {
      f.events.push({ type: "subagent.runtime.error", runId: "child", ts: 320 });
    },
  ],
  [
    "truncated lifecycle prefix",
    (f) => {
      f.events.shift();
    },
  ],
  [
    "truncated lifecycle suffix",
    (f) => {
      f.events.pop();
    },
  ],
  [
    "wrong lane report",
    (f) => {
      f.report.angle = "scope";
    },
  ],
  [
    "missing streamed",
    (f) => {
      Reflect.deleteProperty(f.report, "streamed");
    },
  ],
  [
    "mistyped streamed",
    (f) => {
      Object.assign(f.report, { streamed: "false" });
    },
  ],
  [
    "extra report field",
    (f) => {
      Object.assign(f.report, { verdict: "clean" });
    },
  ],
  [
    "relaxed artifact schema",
    (f) => {
      Object.assign(f.schema, { additionalProperties: true });
      Object.assign(f.report, { verdict: "clean" });
    },
  ],
];
for (const [name, mutate] of mutations) {
  test(`refuses ${name} without changing the original failure`, (t) => {
    const f = staleErrorFixture(t);
    const guard = positive(f);
    mutate(f);
    // The fixture's event array may be replaced deliberately by a malformed-log case.
    const events = f.events;
    f.flush();
    f.put(
      join(f.childRoot, "events.jsonl"),
      `${events.map((e) => JSON.stringify(e)).join("\n")}\n`,
    );
    const result = guard(f.handle, f.raw());
    assert.deepEqual(result?.recoveries ?? [], []);
    assert.deepEqual(result?.value ?? f.parent.workflow.value, f.parent.workflow.value);
  });
}

for (const [name, damage] of [
  ["missing output (no synthesis from provisional findings)", (f: Fixture) => rmSync(f.outputPath)],
  ["malformed report", (f: Fixture) => f.put(f.outputPath, "{")],
  [
    "capture disagrees with tool call",
    (f: Fixture) => f.put(f.outputPath, JSON.stringify({ ...f.report, summary: "different" })),
  ],
  ["malformed child status", (f: Fixture) => f.put(join(f.childRoot, "status.json"), "null")],
  [
    "malformed event tail",
    (f: Fixture) =>
      f.put(
        join(f.childRoot, "events.jsonl"),
        `${readFileSync(join(f.childRoot, "events.jsonl"), "utf8")}{`,
      ),
  ],
  [
    "non-regular events",
    (f: Fixture) => {
      rmSync(join(f.childRoot, "events.jsonl"));
      symlinkSync(f.root, join(f.childRoot, "events.jsonl"));
    },
  ],
  [
    "escaped event symlink",
    (f: Fixture) => {
      const target = join(f.root, "other.jsonl");
      renameSync(join(f.childRoot, "events.jsonl"), target);
      symlinkSync(target, join(f.childRoot, "events.jsonl"));
    },
  ],
  [
    "escaped capture directory",
    (f: Fixture) => {
      const target = join(f.root, "other-capture");
      renameSync(join(f.childRoot, "structured-output"), target);
      symlinkSync(target, join(f.childRoot, "structured-output"));
    },
  ],
  [
    "escaped parent status",
    (f: Fixture) => {
      const target = join(f.root, "other-status.json");
      renameSync(join(f.handle.asyncDir, "status.json"), target);
      symlinkSync(target, join(f.handle.asyncDir, "status.json"));
    },
  ],
] as const) {
  test(`refuses ${name}`, (t) => {
    const f = staleErrorFixture(t);
    const guard = positive(f);
    damage(f);
    assert.deepEqual(guard(f.handle, f.raw())?.recoveries ?? [], []);
  });
}

for (const [file, limit] of [
  ["parent", 2 * 1024 * 1024],
  ["child", 2 * 1024 * 1024],
  ["events", 16 * 1024 * 1024],
  ["report", 1024 * 1024],
  ["schema", 1024 * 1024],
] as const) {
  test(`${file} read accepts the byte limit and refuses one byte over`, (t) => {
    const f = staleErrorFixture(t);
    const guard = positive(f);
    const path = {
      parent: join(f.handle.asyncDir, "status.json"),
      child: join(f.childRoot, "status.json"),
      events: join(f.childRoot, "events.jsonl"),
      report: f.outputPath,
      schema: f.schemaPath,
    }[file];
    const raw = readFileSync(path, "utf8");
    f.put(path, raw.padEnd(limit, " "));
    positive(f, guard);
    f.put(path, raw.padEnd(limit + 1, " "));
    assert.deepEqual(guard(f.handle, f.raw())?.recoveries ?? [], []);
  });
}

test("source attestation is required at launch AND collection; fixture hashing is not a production bypass", (t) => {
  const f = staleErrorFixture(t);
  assert.equal(
    createStaleErrorGuard(f.options),
    undefined,
    "default SHA256 must reject hash-as-text fixtures",
  );
  assert.equal(
    createStaleErrorGuard({ ...f.options, engineEntry: () => undefined }, f.dependencies),
    undefined,
  );
  const guard = positive(f);
  f.put(join(f.engine, "src/runs/background/run-child-session.ts"), "changed");
  assert.equal(createStaleErrorGuard(f.options, f.dependencies), undefined);
  assert.equal(guard(f.handle, f.raw()), undefined);
});

for (const [name, data] of [
  ["wrong version", JSON.stringify({ name: "pi-subagents", version: "0.65.2" })],
  ["oversized manifest", " ".repeat(64 * 1024 + 1)],
  ["malformed manifest", "{"],
] as const) {
  test(`source attestation refuses ${name}`, (t) => {
    const f = staleErrorFixture(t);
    const guard = positive(f);
    f.put(join(f.engine, "package.json"), data);
    assert.equal(createStaleErrorGuard(f.options, f.dependencies), undefined);
    assert.equal(guard(f.handle, f.raw()), undefined);
  });
}

test("source-file read is bounded even with a dependency that accepts the bytes", (t) => {
  const f = staleErrorFixture(t);
  f.dependencies.sourceDigest = (source) => source.trimEnd();
  const path = join(f.engine, "src/runs/background/run-child-session.ts");
  const raw = readFileSync(path, "utf8");
  f.put(path, raw.padEnd(512 * 1024));
  positive(f);
  f.put(path, raw.padEnd(512 * 1024 + 1));
  assert.equal(createStaleErrorGuard(f.options, f.dependencies), undefined);
});
