// The learn wave entrypoint's offline suite (memory adapter): the angle-policy matrix, the
// spec/spawn contract (`mission: false`, `context: "fresh"`, the flow-owned schema, the composed
// lane tasks), and the best-effort mapping learn rides (lane failure = a reported skipped angle,
// never an incomplete wave). The runner's own matrix lives in reportWave.test.ts — not re-tested
// here beyond the one wave-level arm the flow surfaces (`unavailable`).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  angleSelectionError,
  LEARN_ANALYST_REPORT_SCHEMA,
  LEARN_ANGLES,
  type LearnAngleSelection,
  runLearnWave,
} from "./learnWave.ts";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";

const OPTS = {
  manifestPath: "/abs/learn-evidence/manifest.json",
  bundleDir: "/abs/learn-evidence",
};

function selections(...angles: string[]): LearnAngleSelection[] {
  return angles.map((angle) => ({ angle }));
}

/** A schema-shaped analyst report (the engine already validated it — shape only matters here). */
function analystReport(angle: string): unknown {
  return { angle, verdict: "clean", candidates: [], fyi: [] };
}

// ------------------------------------------------------------------------- the angle policy

test("angleSelectionError: valid 2/3/4-angle selections (session-deviations included) pass", () => {
  assert.equal(angleSelectionError(selections("session-deviations", "existing-docs")), null);
  assert.equal(
    angleSelectionError(
      selections("session-deviations", "plan-vs-implementation", "existing-docs"),
    ),
    null,
  );
  assert.equal(angleSelectionError(selections(...LEARN_ANGLES)), null);
});

test("angleSelectionError: count violations name the 2–4 rule", () => {
  assert.match(angleSelectionError(selections("session-deviations")) ?? "", /2–4 angles \(got 1\)/);
  const five = selections(...LEARN_ANGLES, "session-deviations");
  assert.match(angleSelectionError(five) ?? "", /2–4 angles \(got 5\)/);
});

test("angleSelectionError: a duplicate angle is named", () => {
  const err = angleSelectionError(selections("session-deviations", "session-deviations"));
  assert.match(err ?? "", /duplicate angle 'session-deviations'/);
});

test("angleSelectionError: an unknown slug names the valid four", () => {
  const err = angleSelectionError(selections("session-deviations", "vibes"));
  assert.match(err ?? "", /unknown angle 'vibes'/);
  for (const angle of LEARN_ANGLES) {
    assert.match(err ?? "", new RegExp(angle));
  }
});

test("angleSelectionError: a selection missing session-deviations is rejected", () => {
  const err = angleSelectionError(selections("plan-vs-implementation", "existing-docs"));
  assert.match(err ?? "", /'session-deviations' angle is mandatory/);
});

// -------------------------------------------------------------------- the spec/spawn contract

test("runLearnWave: the spawn carries the module contract + the flow-owned schema", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnWave(adapter, {
    ...OPTS,
    selections: selections("session-deviations", "existing-docs"),
    model: "google/gemini-3.5-flash",
  });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn !== undefined);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.equal(spawn.async, true);
  assert.equal(spawn.outputSchema, LEARN_ANALYST_REPORT_SCHEMA);
  assert.equal(spawn.model, "google/gemini-3.5-flash");
  // The rendered script names every angle key and the analyst agent.
  assert.match(spawn.workflowScript, /"key": "session-deviations"/);
  assert.match(spawn.workflowScript, /"key": "existing-docs"/);
  assert.match(spawn.workflowScript, /"agent": "perk\.learn-analyst"/);
  assert.match(spawn.workflowScript, /"phase": "learn"/);
});

test("runLearnWave: no configured model → no model key on the spawn", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnWave(adapter, {
    ...OPTS,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.ok(adapter.calls.spawn[0] !== undefined && !("model" in adapter.calls.spawn[0]));
});

test("runLearnWave: the composed task carries the manifest path, bundle dir, and emphasis verbatim", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnWave(adapter, {
    ...OPTS,
    selections: [
      { angle: "session-deviations", emphasis: "the agent misread the adapter seam & looped" },
      { angle: "existing-docs" },
    ],
  });
  const script = adapter.calls.spawn[0]?.workflowScript ?? "";
  const start = script.indexOf("runs.all(") + "runs.all(".length;
  const end = script.indexOf(");\nreturn");
  const items = JSON.parse(script.slice(start, end)) as Array<{ key: string; task: string }>;
  const deviations = items.find((i) => i.key === "session-deviations");
  assert.ok(deviations !== undefined);
  assert.match(deviations.task, /angle: session-deviations/);
  assert.ok(deviations.task.includes(OPTS.manifestPath), "task names the manifest path");
  assert.ok(deviations.task.includes(OPTS.bundleDir), "task names the bundle dir");
  assert.ok(
    deviations.task.includes("the agent misread the adapter seam & looped"),
    "the parent's emphasis is appended verbatim",
  );
  const docs = items.find((i) => i.key === "existing-docs");
  assert.ok(docs !== undefined);
  assert.doesNotMatch(docs.task, /Emphasis:/);
});

// --------------------------------------------------------------------- best-effort mapping

test("runLearnWave: a failed lane leaves the wave complete (skipped angle, never a failed pass)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: "session-deviations",
          ok: true,
          error: null,
          report: analystReport("session-deviations"),
        },
        { key: "existing-docs", ok: false, error: "lane exploded", report: null },
      ],
    },
  });
  const result = await runLearnWave(adapter, {
    ...OPTS,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(result.complete, true);
  assert.deepEqual(result.reports, [
    { key: "session-deviations", report: analystReport("session-deviations") },
  ]);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [["existing-docs", "lane-failed"]],
  );
});

test("runLearnWave: a non-object report is malformed-report; a missing key is missing-lane", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: "session-deviations", ok: true, error: null, report: "prose, not an object" }],
    },
  });
  const result = await runLearnWave(adapter, {
    ...OPTS,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(result.complete, true);
  assert.deepEqual(result.reports, []);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [
      ["session-deviations", "malformed-report"],
      ["existing-docs", "missing-lane"],
    ],
  );
});

test("runLearnWave: a null ping is a wave-level unavailable failure (complete: false)", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const result = await runLearnWave(adapter, {
    ...OPTS,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
});
