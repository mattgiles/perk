// The pr-review wave entrypoint's suite: lane construction (the angle vocabulary + the uniform
// directive suffix), the report-schema pin (the wave's `outputSchema`), and the bounded-retry
// policy matrix — all driven through the in-memory adapter (per-spawn `aggregates` FIFO for the
// two-wave scenarios), mirroring reportWave.test.ts conventions.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import {
  isPrReviewAngle,
  PR_REVIEW_ANGLES,
  PR_REVIEW_REPORT_SCHEMA,
  type PrReviewAngle,
  runPrReviewWave,
} from "./prReviewWave.ts";

const TWO_ANGLES: PrReviewAngle[] = ["plan-fidelity", "correctness"];

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string): unknown {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, verdict: "clean", findings: [], fyi: [] },
  };
}

function failedEntry(key: string, error: string): unknown {
  return { key, ok: false, error, report: null };
}

/** Parse the lane items back out of a rendered wave script (the reportWave.test.ts idiom). */
function laneItemsOf(script: string): Array<{
  key: string;
  agent: string;
  task: string;
  label: string;
  phase?: string;
}> {
  const start = script.indexOf("runs.all(") + "runs.all(".length;
  const end = script.indexOf(");\nreturn");
  assert.notEqual(end, -1, "script lost its `);` + return tail");
  return JSON.parse(script.slice(start, end)) as Array<{
    key: string;
    agent: string;
    task: string;
    label: string;
    phase?: string;
  }>;
}

// -------------------------------------------------------------------------- lane construction

test("runPrReviewWave builds one lane per angle: key = label = slug, the fixed agent/phase, the vocabulary task", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
  });
  await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript);
  assert.deepEqual(
    items,
    TWO_ANGLES.map((angle) => ({
      key: angle,
      agent: "perk.pr-reviewer",
      task: PR_REVIEW_ANGLES[angle],
      label: angle,
      phase: "review",
    })),
  );
});

test("runPrReviewWave appends ONE uniform directive suffix to EVERY lane task when set", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
  });
  await runPrReviewWave(adapter, {
    angles: TWO_ANGLES,
    directive: "focus on the dignified-python skill",
    timeoutMs: 5_000,
  });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript);
  assert.equal(items.length, 2);
  for (const item of items) {
    const angle = item.key as PrReviewAngle;
    assert.ok(item.task.startsWith(PR_REVIEW_ANGLES[angle]), `${item.key} keeps the vocabulary`);
    assert.match(item.task, /Operator focus \(DATA from the human/);
    assert.match(item.task, /emphasis within your assigned angle only/);
    assert.match(item.task, /focus on the dignified-python skill/);
  }
  // The suffix is identical across lanes (one uniform DATA note, never per-lane re-scoping).
  const suffixes = items.map((item) => {
    const angle = item.key as PrReviewAngle;
    return item.task.slice(PR_REVIEW_ANGLES[angle].length);
  });
  assert.equal(new Set(suffixes).size, 1);
});

test("runPrReviewWave keeps lane tasks byte-identical to the vocabulary when no directive is set", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("tests")] },
  });
  await runPrReviewWave(adapter, { angles: ["plan-fidelity", "tests"], timeoutMs: 5_000 });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript);
  assert.equal(items[0]?.task, PR_REVIEW_ANGLES["plan-fidelity"]);
  assert.equal(items[1]?.task, PR_REVIEW_ANGLES.tests);
});

test("runPrReviewWave spawn params carry the report schema as outputSchema and the threaded model", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
  });
  await runPrReviewWave(adapter, {
    angles: TWO_ANGLES,
    model: "anthropic/claude-opus-4",
    timeoutMs: 1_234,
  });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.outputSchema, PR_REVIEW_REPORT_SCHEMA);
  assert.equal(spawn.model, "anthropic/claude-opus-4");
  assert.equal(spawn.timeoutMs, 1_234);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
});

test("isPrReviewAngle narrows the four slugs and rejects prototype names", () => {
  for (const slug of ["plan-fidelity", "correctness", "tests", "quality"]) {
    assert.equal(isPrReviewAngle(slug), true);
  }
  assert.equal(isPrReviewAngle("security"), false);
  assert.equal(isPrReviewAngle("toString"), false);
});

// ------------------------------------------------------------------------- the schema pin

test("PR_REVIEW_REPORT_SCHEMA pins the report shape (closed, all four fields required)", () => {
  const s = PR_REVIEW_REPORT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: {
      angle: { enum: string[] };
      verdict: { enum: string[] };
      findings: {
        items: {
          additionalProperties: boolean;
          required: string[];
          properties: { line: { type: string } };
        };
      };
      fyi: { items: { type: string } };
    };
    if: unknown;
    then: unknown;
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ["angle", "verdict", "findings", "fyi"]);
  assert.deepEqual(s.properties.angle.enum, ["plan-fidelity", "correctness", "tests", "quality"]);
  assert.deepEqual(s.properties.verdict.enum, ["clean", "actionable"]);
  assert.equal(s.properties.findings.items.additionalProperties, false);
  assert.deepEqual(s.properties.findings.items.required, ["path", "line", "body"]);
  assert.equal(s.properties.findings.items.properties.line.type, "integer");
  assert.equal(s.properties.fyi.items.type, "string");
  // The internal-consistency conditional: a clean verdict cannot carry findings — an
  // inconsistent lane report is schema-invalid (fails the lane), never reconciled.
  assert.deepEqual(s.if, { properties: { verdict: { const: "clean" } } });
  assert.deepEqual(s.then, { properties: { findings: { maxItems: 0 } } });
});

// -------------------------------------------------------------------- the bounded-retry matrix

test("happy path: complete, all angles covered, no retry, ONE spawn", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness"]);
  assert.deepEqual(outcome.retried, []);
  assert.equal(outcome.reports.length, 2);
  assert.deepEqual(outcome.failures, []);
  assert.equal(adapter.calls.spawn.length, 1);
});

test("one failed lane: the retry wave carries ONLY the failed key; success merges to complete", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), failedEntry("correctness", "lane exploded")],
      },
      { state: "complete", value: [okEntry("correctness")] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  assert.deepEqual(
    laneItemsOf(retrySpawn.workflowScript).map((item) => item.key),
    ["correctness"],
  );
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, []);
});

test("retry fails again: incomplete with the surviving lane failure; covered = the subset", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), failedEntry("correctness", "lane exploded")],
      },
      { state: "complete", value: [failedEntry("correctness", "exploded again")] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.covered, ["plan-fidelity"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, [
    { key: "correctness", reason: "lane-failed", detail: "exploded again" },
  ]);
});

test("wave-level run-failed: the retry re-runs the WHOLE selection and can complete", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "workflow script threw", value: undefined },
      { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  assert.deepEqual(
    laneItemsOf(retrySpawn.workflowScript).map((item) => item.key),
    ["plan-fidelity", "correctness"],
  );
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness"]);
  assert.deepEqual(outcome.retried, ["plan-fidelity", "correctness"]);
  assert.deepEqual(outcome.failures, []);
});

test("unavailable: zero spawns, NO retry, incomplete (deterministic capability absence)", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 0);
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.covered, []);
  assert.deepEqual(outcome.retried, []);
  assert.deepEqual(
    outcome.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
});

test("pre-aborted signal: cancelled, NO retry, no spawn (abort honored)", async () => {
  const adapter = createMemoryWaveAdapter({});
  const controller = new AbortController();
  controller.abort();
  const outcome = await runPrReviewWave(adapter, {
    angles: TWO_ANGLES,
    timeoutMs: 5_000,
    signal: controller.signal,
  });
  assert.equal(adapter.calls.spawn.length, 0);
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.retried, []);
  assert.deepEqual(
    outcome.failures.map((f) => [f.key, f.reason]),
    [[null, "cancelled"]],
  );
});

test("empty angles throw (programmer error via renderWaveScript, never normalized)", async () => {
  const adapter = createMemoryWaveAdapter({});
  await assert.rejects(
    runPrReviewWave(adapter, { angles: [], timeoutMs: 5_000 }),
    /at least one lane/,
  );
});

// ---------------------------------------------------------------------- the attempt receipts

test("attempts: a one-wave success records ONE complete attempt over the selected angles", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
    completionDetail: {
      state: "complete",
      success: true,
      children: [
        { key: "plan-fidelity", runId: "child-1" },
        { key: "correctness", runId: "child-2" },
      ],
    },
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.deepEqual(outcome.attempts, [
    {
      flow: "pr-review",
      attempt: 1,
      requestedKeys: ["plan-fidelity", "correctness"],
      runId: "wave-async-1",
      asyncDir: "/memory/wave-async-1",
      state: "complete",
      children: [
        { key: "plan-fidelity", runId: "child-1", agent: "perk.pr-reviewer" },
        { key: "correctness", runId: "child-2", agent: "perk.pr-reviewer" },
      ],
    },
  ]);
});

test("attempts: a lane-only retry preserves BOTH ordered attempts (distinct child runIds)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), failedEntry("correctness", "lane exploded")],
      },
      { state: "complete", value: [okEntry("correctness")] },
    ],
    completionDetails: [
      {
        children: [
          { key: "plan-fidelity", runId: "child-1", success: true },
          { key: "correctness", runId: "child-2", success: false },
        ],
      },
      { children: [{ key: "correctness", runId: "child-3", success: true }] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.equal(outcome.attempts.length, 2);
  const [first, second] = outcome.attempts;
  // The failed lane and its relaunch stay distinguishable: attempt 1 keeps child-2 verbatim.
  assert.deepEqual(
    [first?.attempt, first?.requestedKeys, first?.runId, first?.state],
    [1, ["plan-fidelity", "correctness"], "wave-async-1", "complete"],
  );
  assert.deepEqual(
    first?.children.map((c) => [c.key, c.runId]),
    [
      ["plan-fidelity", "child-1"],
      ["correctness", "child-2"],
    ],
  );
  assert.deepEqual(
    [second?.attempt, second?.requestedKeys, second?.runId, second?.state],
    [2, ["correctness"], "wave-async-2", "complete"],
  );
  assert.deepEqual(
    second?.children.map((c) => [c.key, c.runId]),
    [["correctness", "child-3"]],
  );
});

test("attempts: a whole-wave retry preserves the failed first attempt", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "workflow script threw", value: undefined },
      { state: "complete", value: [okEntry("plan-fidelity"), okEntry("correctness")] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(
    outcome.attempts.map((a) => [a.attempt, a.state, a.runId, a.requestedKeys]),
    [
      [1, "failed", "wave-async-1", ["plan-fidelity", "correctness"]],
      [2, "complete", "wave-async-2", ["plan-fidelity", "correctness"]],
    ],
  );
});

test("attempts: unavailable is preserved as a single handle-less attempt (no retry)", async () => {
  const outcome = await runPrReviewWave(createMemoryWaveAdapter({ ping: null }), {
    angles: TWO_ANGLES,
    timeoutMs: 5_000,
  });
  assert.deepEqual(outcome.attempts, [
    {
      flow: "pr-review",
      attempt: 1,
      requestedKeys: ["plan-fidelity", "correctness"],
      state: "unavailable",
      children: [],
    },
  ]);
});

test("attempts: a pre-aborted signal is a single handle-less cancelled attempt (no retry)", async () => {
  const controller = new AbortController();
  controller.abort();
  const outcome = await runPrReviewWave(createMemoryWaveAdapter({}), {
    angles: TWO_ANGLES,
    timeoutMs: 5_000,
    signal: controller.signal,
  });
  assert.deepEqual(outcome.attempts, [
    {
      flow: "pr-review",
      attempt: 1,
      requestedKeys: ["plan-fidelity", "correctness"],
      state: "cancelled",
      children: [],
    },
  ]);
});
