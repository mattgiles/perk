// The report-wave module's own suite: the exact rendered-script pin (the tested workflowScript
// is the node's headline artifact), the hostile-task embedding proof, and the full runner
// normalization matrix driven through the in-memory adapter — every `WaveFailureReason` arm plus
// both completeness policies, with zero event buses, child processes, or temp dirs.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import {
  renderWaveScript,
  runReportWave,
  WAVE_TIMEOUT_MS,
  type WaveLane,
  type WaveSpec,
} from "./reportWave.ts";

const LANES: WaveLane[] = [
  {
    key: "plan-fidelity",
    agent: "perk.pr-reviewer",
    task: "angle: plan-fidelity — review ONLY plan fidelity & completeness.",
    phase: "review",
  },
  {
    key: "correctness",
    agent: "perk.pr-reviewer",
    task: "angle: correctness — review ONLY correctness & regressions.",
    label: "correctness-lane",
    phase: "review",
  },
];

function makeSpec(overrides: Partial<WaveSpec> = {}): WaveSpec {
  return {
    flow: "pr-review",
    lanes: LANES,
    outputSchema: { type: "object", properties: { verdict: { type: "string" } } },
    completeness: "strict",
    timeoutMs: 5_000,
    ...overrides,
  };
}

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string, report: unknown): unknown {
  return { key, ok: true, error: null, report };
}

// ------------------------------------------------------------------------------ the renderer

test("renderWaveScript pins the exact two-lane script", () => {
  const expected = `const reports = await runs.all([
  {
    "key": "plan-fidelity",
    "agent": "perk.pr-reviewer",
    "task": "angle: plan-fidelity — review ONLY plan fidelity & completeness.",
    "label": "plan-fidelity",
    "phase": "review"
  },
  {
    "key": "correctness",
    "agent": "perk.pr-reviewer",
    "task": "angle: correctness — review ONLY correctness & regressions.",
    "label": "correctness-lane",
    "phase": "review"
  }
]);
return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));`;
  assert.equal(renderWaveScript(LANES), expected);
});

test("renderWaveScript keeps hostile task text inside the array literal", () => {
  const hostile = `end"}]); process.exit(1); //\n\`rm -rf ~\` \${process.env.HOME} \\" done`;
  const script = renderWaveScript([
    { key: "hostile", agent: "perk.pr-reviewer", task: hostile },
    { key: "tame", agent: "perk.pr-reviewer", task: "review calmly" },
  ]);
  // The array literal is exactly the JSON between `runs.all(` and the closing `);` before the
  // return line — parse it back and prove the hostile text arrived intact as DATA.
  const start = script.indexOf("runs.all(") + "runs.all(".length;
  const end = script.indexOf(");\nreturn");
  assert.notEqual(end, -1, "script lost its `);` + return tail");
  const items = JSON.parse(script.slice(start, end)) as Array<{ key: string; task: string }>;
  assert.equal(items.length, 2);
  assert.equal(items[0]?.task, hostile);
  assert.equal(items[1]?.task, "review calmly");
});

test("renderWaveScript throws on duplicate lane keys and empty lanes", () => {
  assert.throws(
    () =>
      renderWaveScript([
        { key: "same", agent: "a", task: "t1" },
        { key: "same", agent: "a", task: "t2" },
      ]),
    /duplicate lane key 'same'/,
  );
  assert.throws(() => renderWaveScript([]), /at least one lane/);
});

// -------------------------------------------------------------------------- the runner matrix

test("runReportWave: happy path yields reports under lane keys and complete", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("correctness", { verdict: "actionable" }),
      ],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(result, {
    complete: true,
    reports: [
      { key: "plan-fidelity", report: { verdict: "clean" } },
      { key: "correctness", report: { verdict: "actionable" } },
    ],
    failures: [],
  });
});

test("runReportWave: spawn params carry the fixed module contract + spec fields", async () => {
  const spec = makeSpec({ model: "anthropic/claude-sonnet-4", timeoutMs: 1_234 });
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [] },
  });
  await runReportWave(adapter, spec);
  assert.equal(adapter.calls.spawn.length, 1);
  assert.deepEqual(adapter.calls.spawn[0], {
    workflowScript: renderWaveScript(spec.lanes),
    async: true,
    mission: false,
    context: "fresh",
    outputSchema: spec.outputSchema,
    model: "anthropic/claude-sonnet-4",
    timeoutMs: 1_234,
  });
});

test("runReportWave: a failed lane is incomplete under strict, complete under best-effort", async () => {
  const aggregate = {
    state: "complete",
    value: [
      okEntry("plan-fidelity", { verdict: "clean" }),
      { key: "correctness", ok: false, error: "lane exploded", report: null },
    ],
  };
  const strict = await runReportWave(createMemoryWaveAdapter({ aggregate }), makeSpec());
  assert.equal(strict.complete, false);
  assert.deepEqual(strict.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(strict.failures, [
    { key: "correctness", reason: "lane-failed", detail: "lane exploded" },
  ]);

  const bestEffort = await runReportWave(
    createMemoryWaveAdapter({ aggregate }),
    makeSpec({ completeness: "best-effort" }),
  );
  assert.equal(bestEffort.complete, true);
  assert.deepEqual(bestEffort.failures, [
    { key: "correctness", reason: "lane-failed", detail: "lane exploded" },
  ]);
});

test("runReportWave: an ok lane with a null report is lane-failed (no schema-valid report)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        { key: "correctness", ok: true, error: null, report: null },
      ],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.failures, [
    {
      key: "correctness",
      reason: "lane-failed",
      detail: "lane 'correctness' resolved without a schema-valid report",
    },
  ]);
});

test("runReportWave: unusable entry shapes are malformed-report", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: "plan-fidelity", ok: "yes", report: { verdict: "clean" } },
        { key: "correctness", ok: true, error: null, report: "prose instead of an object" },
      ],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, []);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [
      ["plan-fidelity", "malformed-report"],
      ["correctness", "malformed-report"],
    ],
  );
});

test("runReportWave: an absent lane key is missing-lane; unknown extra keys are ignored", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("uninvited-extra", { verdict: "clean" }),
      ],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    {
      key: "correctness",
      reason: "missing-lane",
      detail: "lane 'correctness' is absent from the wave aggregate",
    },
  ]);
});

test("runReportWave: a null ping is a wave-level unavailable failure (loud degrade, no spawn)", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, []);
  assert.equal(result.failures.length, 1);
  assert.equal(result.failures[0]?.key, null);
  assert.equal(result.failures[0]?.reason, "unavailable");
  assert.equal(adapter.calls.spawn.length, 0);
});

test("runReportWave: a rejected spawn is a wave-level spawn-failed failure", async () => {
  const adapter = createMemoryWaveAdapter({ spawnError: "no session" });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "spawn-failed"]],
  );
  assert.match(result.failures[0]?.detail ?? "", /no session/);
});

test("runReportWave: timeout stops the run best-effort and fails the wave", async () => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const result = await runReportWave(adapter, makeSpec({ timeoutMs: 20 }));
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "timeout"]],
  );
  assert.match(result.failures[0]?.detail ?? "", /timed out after 20ms/);
  assert.equal(adapter.calls.stop.length, 1);
  assert.equal(adapter.calls.stop[0]?.asyncId, "wave-async-1");
});

test("runReportWave: PERK_WAVE_TIMEOUT_MS overrides the module default timeout", async () => {
  assert.equal(WAVE_TIMEOUT_MS, 15 * 60_000);
  process.env.PERK_WAVE_TIMEOUT_MS = "20";
  try {
    const adapter = createMemoryWaveAdapter({ completion: false });
    const result = await runReportWave(adapter, makeSpec({ timeoutMs: undefined }));
    assert.deepEqual(
      result.failures.map((f) => [f.key, f.reason]),
      [[null, "timeout"]],
    );
    assert.equal(adapter.calls.spawn[0]?.timeoutMs, 20);
  } finally {
    delete process.env.PERK_WAVE_TIMEOUT_MS;
  }
});

test("runReportWave: an AbortSignal cancels the wave and stops the run best-effort", async () => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 10);
  const result = await runReportWave(adapter, makeSpec(), controller.signal);
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "cancelled"]],
  );
  assert.equal(adapter.calls.stop.length, 1);
});

test("runReportWave: a pre-aborted signal cancels before launch (no spawn)", async () => {
  const adapter = createMemoryWaveAdapter({});
  const controller = new AbortController();
  controller.abort();
  const result = await runReportWave(adapter, makeSpec(), controller.signal);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "cancelled"]],
  );
  assert.equal(adapter.calls.spawn.length, 0);
});

test("runReportWave: a non-complete terminal state is run-failed with the status error", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "failed", error: "workflow script threw", value: undefined },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "run-failed"]],
  );
  assert.match(result.failures[0]?.detail ?? "", /'failed': workflow script threw/);
});

test("runReportWave: an unreadable status.json is aggregate-unreadable", async () => {
  const adapter = createMemoryWaveAdapter({ aggregateError: true });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "aggregate-unreadable"]],
  );
});

test("runReportWave: a non-array workflow.value is aggregate-unreadable", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: "not an array" },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "aggregate-unreadable"]],
  );
});

test("runReportWave: a completion arriving before the spawn reply still resolves", async () => {
  const adapter = createMemoryWaveAdapter({
    ordering: "complete-then-reply",
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("correctness", { verdict: "clean" }),
      ],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, true);
  assert.equal(result.reports.length, 2);
});

test("runReportWave: duplicate lane keys throw (programmer error, never normalized)", async () => {
  const adapter = createMemoryWaveAdapter({});
  await assert.rejects(
    runReportWave(
      adapter,
      makeSpec({
        lanes: [
          { key: "same", agent: "a", task: "t1" },
          { key: "same", agent: "a", task: "t2" },
        ],
      }),
    ),
    /duplicate lane key 'same'/,
  );
});
