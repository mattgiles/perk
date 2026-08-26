// The report-wave module's own suite: the exact rendered-script pin (the tested workflowScript
// is the node's headline artifact), the hostile-task embedding proof, and the full runner
// normalization matrix driven through the in-memory adapter — every `WaveFailureReason` arm plus
// both completeness policies, with zero event buses, child processes, or temp dirs. The attempt
// receipts get their own matrix: one receipt per terminal arm, lane-agent enrichment, and the
// behavior-parity proof that receipts never alter `complete`/`reports`/`failures`.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import { PONYTAIL_CORE_SKILL } from "./ponytail.ts";
import {
  renderWaveScript,
  runReportWave,
  startReportWave,
  startWaveScript,
  toAttemptReceipt,
  WAVE_ACCEPTANCE,
  WAVE_TIMEOUT_MS,
  type WaveChildReceipt,
  type ReportAssignment,
  type WaveScriptSpec,
  type WaveSpec,
} from "./reportWave.ts";

const ASSIGNMENTS: ReportAssignment[] = [
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
    assignments: ASSIGNMENTS,
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
  assert.equal(renderWaveScript(ASSIGNMENTS), expected);
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

test("renderWaveScript renders a per-lane outputSchema on exactly the lanes that carry one", () => {
  const laneSchema = { type: "object", properties: { angle: { enum: ["custom-scope"] } } };
  const script = renderWaveScript([
    {
      key: "custom-scope",
      agent: "perk.pr-reviewer",
      task: "review the scope",
      outputSchema: laneSchema,
    },
    { key: "plain", agent: "perk.pr-reviewer", task: "review plainly" },
  ]);
  const start = script.indexOf("runs.all(") + "runs.all(".length;
  const end = script.indexOf(");\nreturn");
  const items = JSON.parse(script.slice(start, end)) as Array<Record<string, unknown>>;
  assert.deepEqual(items[0]?.outputSchema, laneSchema);
  assert.equal(
    "outputSchema" in (items[1] ?? {}),
    false,
    "a schema-less lane renders without the field",
  );
});

test("renderWaveScript serializes opted-in skill but never required-skill metadata", () => {
  const script = renderWaveScript([
    {
      key: "ponytail",
      agent: "perk.pr-reviewer",
      task: "review minimally",
      skill: "ponytail",
      requiredSkill: PONYTAIL_CORE_SKILL,
    },
    { key: "plain", agent: "perk.pr-reviewer", task: "review plainly" },
  ]);
  const start = script.indexOf("runs.all(") + "runs.all(".length;
  const end = script.indexOf(");\nreturn");
  const items = JSON.parse(script.slice(start, end)) as Array<Record<string, unknown>>;
  assert.equal(items[0]?.skill, "ponytail");
  assert.equal("requiredSkill" in (items[0] ?? {}), false);
  assert.equal("skill" in (items[1] ?? {}), false);
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

test("renderWaveScript rejects lane keys outside the pi-subagents run-key contract", () => {
  // The upstream pattern is enforced only inside the live workflow worker, where an invalid
  // key fails the WHOLE wave at dispatch (`run-failed`) — the renderer must reject it up
  // front as a programmer error instead.
  for (const bad of [
    "has@at",
    "a/slash",
    "-leading-dash",
    "",
    `x${"y".repeat(128)}`, // 129 chars
  ]) {
    assert.throws(
      () => renderWaveScript([{ key: bad, agent: "a", task: "t" }]),
      /violates the pi-subagents run-key contract|at least one lane/,
    );
  }
  // Boundary: 128 chars of the allowed charset passes.
  const maxKey = `k${"a".repeat(125)}.z`;
  assert.equal(maxKey.length, 128);
  assert.match(renderWaveScript([{ key: maxKey, agent: "a", task: "t" }]), /runs\.all/);
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
    receipt: {
      runId: "wave-async-1",
      asyncDir: "/memory/wave-async-1",
      state: "complete",
      children: [],
    },
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
    acceptance: WAVE_ACCEPTANCE,
    outputSchema: spec.outputSchema,
    model: "anthropic/claude-sonnet-4",
    timeoutMs: 1_234,
  });
});

test("runReportWave: failed required-skill preflight skips only that lane and stays uncovered", async () => {
  const assignments: ReportAssignment[] = [
    ASSIGNMENTS[0] as ReportAssignment,
    {
      key: "ponytail",
      agent: "perk.pr-reviewer",
      task: "review minimally",
      skill: "ponytail",
      requiredSkill: PONYTAIL_CORE_SKILL,
    },
  ];
  let preflights = 0;
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity", { verdict: "clean" })],
    },
  });
  const result = await runReportWave(
    adapter,
    makeSpec({
      assignments,
      requiredSkillPreflight: async () => {
        preflights++;
        return { ok: false, detail: "exact Ponytail source missing" };
      },
    }),
  );
  assert.equal(preflights, 1);
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    { key: "ponytail", reason: "skill-unavailable", detail: "exact Ponytail source missing" },
  ]);
  const spawned = adapter.calls.spawn[0];
  assert.ok(spawned !== undefined);
  assert.doesNotMatch(spawned.workflowScript, /ponytail/);
  const attempt = toAttemptReceipt(
    "pr-review",
    1,
    assignments.map((assignment) => assignment.key),
    result.receipt,
  );
  assert.deepEqual(attempt.requestedKeys, ["plan-fidelity", "ponytail"]);
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

test("runReportWave: Ponytail preflight success without a report stays uncovered", async () => {
  const ponytail: ReportAssignment = {
    key: "ponytail",
    agent: "perk.pr-reviewer",
    task: "review minimally",
    skill: "ponytail-review",
    requiredSkill: PONYTAIL_CORE_SKILL,
  };
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        { key: "ponytail", ok: true, error: null, report: null },
      ],
    },
  });
  const result = await runReportWave(
    adapter,
    makeSpec({
      assignments: [ASSIGNMENTS[0] as ReportAssignment, ponytail],
      requiredSkillPreflight: async () => ({ ok: true }),
    }),
  );
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    {
      key: "ponytail",
      reason: "lane-failed",
      detail: "lane 'ponytail' resolved without a schema-valid report",
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

test("runReportWave: an abort arriving during the ping await cancels before spawn", async () => {
  const adapter = createMemoryWaveAdapter({});
  const controller = new AbortController();
  // The abort fires while `ping()` is pending — the post-ping re-check must catch it; the
  // pre-launch check alone would let this wave proceed to subscribe/spawn.
  const delayedPingAdapter = {
    ...adapter,
    async ping() {
      await new Promise((resolve) => setTimeout(resolve, 0));
      controller.abort();
      return adapter.ping();
    },
  };
  const result = await runReportWave(delayedPingAdapter, makeSpec(), controller.signal);
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
        assignments: [
          { key: "same", agent: "a", task: "t1" },
          { key: "same", agent: "a", task: "t2" },
        ],
      }),
    ),
    /duplicate lane key 'same'/,
  );
});

// ------------------------------------------------------------------- the attempt receipts

test("receipt: unavailable (null ping) — no handle, no children", async () => {
  const result = await runReportWave(createMemoryWaveAdapter({ ping: null }), makeSpec());
  assert.deepEqual(result.receipt, { state: "unavailable", children: [] });
});

test("receipt: spawn-failed — no handle, no children", async () => {
  const result = await runReportWave(
    createMemoryWaveAdapter({ spawnError: "no session" }),
    makeSpec(),
  );
  assert.deepEqual(result.receipt, { state: "spawn-failed", children: [] });
});

test("receipt: timed-out preserves the spawn handle (no completion, empty children)", async () => {
  const result = await runReportWave(
    createMemoryWaveAdapter({ completion: false }),
    makeSpec({ timeoutMs: 20 }),
  );
  assert.deepEqual(result.receipt, {
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "timed-out",
    children: [],
  });
});

test("receipt: post-spawn cancel preserves the spawn handle", async () => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 10);
  const result = await runReportWave(adapter, makeSpec(), controller.signal);
  assert.deepEqual(result.receipt, {
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "cancelled",
    children: [],
  });
});

test("receipt: pre-launch cancel yields a handle-less cancelled receipt", async () => {
  const controller = new AbortController();
  controller.abort();
  const result = await runReportWave(createMemoryWaveAdapter({}), makeSpec(), controller.signal);
  assert.deepEqual(result.receipt, { state: "cancelled", children: [] });
});

test("receipt: a non-complete terminal state is failed, retaining handle + completion children", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "failed", error: "workflow script threw", value: undefined },
    completionDetail: {
      state: "failed",
      success: false,
      children: [{ key: "plan-fidelity", runId: "child-1", success: false }],
    },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(result.receipt, {
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "failed",
    children: [
      { key: "plan-fidelity", agent: "perk.pr-reviewer", runId: "child-1", success: false },
    ],
  });
});

test("receipt: aggregate-unreadable retains the completion identity (success false ⇒ failed)", async () => {
  const failed = await runReportWave(
    createMemoryWaveAdapter({
      aggregateError: true,
      completionDetail: { success: false, children: [{ key: "correctness", runId: "child-2" }] },
    }),
    makeSpec(),
  );
  assert.equal(failed.receipt.state, "failed");
  assert.deepEqual(failed.receipt.children, [
    { key: "correctness", agent: "perk.pr-reviewer", runId: "child-2" },
  ]);

  const completeish = await runReportWave(
    createMemoryWaveAdapter({ aggregateError: true, completionDetail: { success: true } }),
    makeSpec(),
  );
  assert.equal(completeish.receipt.state, "complete");
  // The authoritative failure reason stays in failures[] — the receipt is a correlation label.
  assert.deepEqual(
    completeish.failures.map((f) => [f.key, f.reason]),
    [[null, "aggregate-unreadable"]],
  );
});

test("receipt: complete run enriches child agents from the lane specs by key", async () => {
  const children: WaveChildReceipt[] = [
    { key: "plan-fidelity", runId: "child-1", success: true, outputState: "present" },
    { key: "correctness", runId: "child-2", success: true, agent: "already-set" },
    { key: "mystery", runId: "child-3" },
  ];
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("correctness", { verdict: "clean" }),
      ],
    },
    completionDetail: { state: "complete", success: true, children },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.deepEqual(result.receipt.children, [
    {
      key: "plan-fidelity",
      runId: "child-1",
      success: true,
      outputState: "present",
      agent: "perk.pr-reviewer",
    },
    // A pre-set agent is never overwritten; an unknown key stays unset (never synthesized).
    { key: "correctness", runId: "child-2", success: true, agent: "already-set" },
    { key: "mystery", runId: "child-3" },
  ]);
});

test("receipt: an identity-only completion yields empty children on a complete run", async () => {
  const adapter = createMemoryWaveAdapter({
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
  assert.deepEqual(result.receipt.children, []);
});

test("receipt: completion-before-reply buffering retains the receipt detail", async () => {
  const adapter = createMemoryWaveAdapter({
    ordering: "complete-then-reply",
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("correctness", { verdict: "clean" }),
      ],
    },
    completionDetail: { state: "complete", success: true, children: [{ key: "plan-fidelity" }] },
  });
  const result = await runReportWave(adapter, makeSpec());
  assert.equal(result.complete, true);
  assert.deepEqual(result.receipt.children, [{ key: "plan-fidelity", agent: "perk.pr-reviewer" }]);
});

test("receipt data never alters complete/reports/failures (behavior parity)", async () => {
  const aggregate = {
    state: "complete",
    value: [
      okEntry("plan-fidelity", { verdict: "clean" }),
      okEntry("correctness", { verdict: "clean" }),
    ],
  };
  const identityOnly = await runReportWave(createMemoryWaveAdapter({ aggregate }), makeSpec());
  // A completion whose children CLAIM failure changes nothing — the durable aggregate is the
  // sole authority for reports and completeness.
  const contradicting = await runReportWave(
    createMemoryWaveAdapter({
      aggregate,
      completionDetail: {
        state: "failed",
        success: false,
        children: [
          { key: "plan-fidelity", success: false },
          { key: "correctness", success: false },
        ],
      },
    }),
    makeSpec(),
  );
  assert.deepEqual(
    {
      complete: contradicting.complete,
      reports: contradicting.reports,
      failures: contradicting.failures,
    },
    {
      complete: identityOnly.complete,
      reports: identityOnly.reports,
      failures: identityOnly.failures,
    },
  );
});

// ----------------------------------------------------------- the non-blocking start/settle split

function makeScriptSpec(overrides: Partial<WaveScriptSpec> = {}): WaveScriptSpec {
  return {
    flow: "adversarial-review",
    workflowScript: renderWaveScript(ASSIGNMENTS),
    outputSchema: { type: "object", properties: { angle: { type: "string" } } },
    timeoutMs: 5_000,
    ...overrides,
  };
}

/** Probe whether a promise settles within `ms` (the still-pending assertion helper). */
async function settlesWithin(promise: Promise<unknown>, ms: number): Promise<boolean> {
  return await Promise.race([
    promise.then(() => true),
    new Promise<boolean>((resolve) => setTimeout(() => resolve(false), ms)),
  ]);
}

test("startWaveScript: the ok arm returns the handle while result is still pending; the emitted completion settles it", async () => {
  const value = [okEntry("plan-fidelity", { angle: "plan-fidelity" })];
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: { state: "complete", value },
  });
  const start = await startWaveScript(adapter, makeScriptSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  assert.deepEqual(start.handle, { asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  // The launch returned but the run has not completed — `result` must still be pending.
  assert.equal(await settlesWithin(start.result, 30), false);
  adapter.emitCompletion({ asyncId: start.handle.asyncId, asyncDir: start.handle.asyncDir });
  const result = await start.result;
  assert.deepEqual(result, {
    ok: true,
    value,
    receipt: {
      runId: "wave-async-1",
      asyncDir: "/memory/wave-async-1",
      state: "complete",
      children: [],
    },
  });
});

test("startWaveScript: pre-spawn failures take the ok:false arm with the blocking runner's values", async () => {
  const unavailable = await startWaveScript(
    createMemoryWaveAdapter({ ping: null }),
    makeScriptSpec(),
  );
  assert.equal(unavailable.ok, false);
  if (unavailable.ok) return;
  assert.equal(unavailable.failure.reason, "unavailable");
  assert.equal(unavailable.failure.key, null);
  assert.deepEqual(unavailable.receipt, { state: "unavailable", children: [] });

  const spawnAdapter = createMemoryWaveAdapter({ spawnError: "no session" });
  const spawnFailed = await startWaveScript(spawnAdapter, makeScriptSpec());
  assert.equal(spawnFailed.ok, false);
  if (spawnFailed.ok) return;
  assert.equal(spawnFailed.failure.reason, "spawn-failed");
  assert.match(spawnFailed.failure.detail, /no session/);
  assert.deepEqual(spawnFailed.receipt, { state: "spawn-failed", children: [] });

  const controller = new AbortController();
  controller.abort();
  const preAborted = createMemoryWaveAdapter({});
  const cancelled = await startWaveScript(preAborted, makeScriptSpec(), controller.signal);
  assert.equal(cancelled.ok, false);
  if (cancelled.ok) return;
  assert.equal(cancelled.failure.reason, "cancelled");
  assert.deepEqual(cancelled.receipt, { state: "cancelled", children: [] });
  assert.equal(preAborted.calls.spawn.length, 0);
});

test("startWaveScript: timeout settles result with the best-effort stop recorded", async () => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const start = await startWaveScript(adapter, makeScriptSpec({ timeoutMs: 20 }));
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const result = await start.result;
  assert.equal(result.ok, false);
  if (result.ok) return;
  assert.equal(result.failure.reason, "timeout");
  assert.match(result.failure.detail, /timed out after 20ms/);
  assert.equal(result.receipt.state, "timed-out");
  assert.equal(adapter.calls.stop.length, 1);
  assert.equal(adapter.calls.stop[0]?.asyncId, "wave-async-1");
});

test("startWaveScript: an abort after launch settles the cancelled arm with the handle preserved", async () => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const controller = new AbortController();
  const start = await startWaveScript(adapter, makeScriptSpec(), controller.signal);
  assert.equal(start.ok, true);
  if (!start.ok) return;
  controller.abort();
  const result = await start.result;
  assert.equal(result.ok, false);
  if (result.ok) return;
  assert.equal(result.failure.reason, "cancelled");
  assert.deepEqual(result.receipt, {
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "cancelled",
    children: [],
  });
  assert.equal(adapter.calls.stop.length, 1);
});

test("startWaveScript: a completion arriving before the spawn reply still settles complete", async () => {
  const value = [okEntry("plan-fidelity", { angle: "plan-fidelity" })];
  const adapter = createMemoryWaveAdapter({
    ordering: "complete-then-reply",
    aggregate: { state: "complete", value },
  });
  const start = await startWaveScript(adapter, makeScriptSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const result = await start.result;
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.value, value);
});

test("startWaveScript: result RESOLVES (never rejects) on every post-spawn failure arm", async () => {
  // An uncollected wave must never become an unhandled rejection — each arm normalizes.
  const arms: { adapter: ReturnType<typeof createMemoryWaveAdapter>; reason: string }[] = [
    { adapter: createMemoryWaveAdapter({ aggregateError: true }), reason: "aggregate-unreadable" },
    {
      adapter: createMemoryWaveAdapter({
        aggregate: { state: "failed", error: "workflow script threw", value: undefined },
      }),
      reason: "run-failed",
    },
    {
      adapter: createMemoryWaveAdapter({
        aggregate: { state: "complete", value: "not an array" },
      }),
      reason: "ok", // the raw script result is ok; the array check is the lane-level settle's
    },
  ];
  for (const arm of arms) {
    const start = await startWaveScript(arm.adapter, makeScriptSpec());
    assert.equal(start.ok, true);
    if (!start.ok) continue;
    // A plain await suffices: a rejection here would throw and fail the test.
    const result = await start.result;
    if (arm.reason === "ok") {
      assert.equal(result.ok, true);
    } else {
      assert.equal(result.ok, false);
      if (!result.ok) assert.equal(result.failure.reason, arm.reason);
    }
  }
});

test("startReportWave: the ok arm settles into normalization + strict completeness + receipt enrichment", async () => {
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        { key: "correctness", ok: false, error: "lane exploded", report: null },
      ],
    },
  });
  const start = await startReportWave(adapter, makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  assert.deepEqual(start.launch, {
    requested: ["plan-fidelity", "correctness"],
    runnable: ["plan-fidelity", "correctness"],
    preflightFailures: [],
  });
  assert.equal(await settlesWithin(start.result, 30), false);
  adapter.emitCompletion({
    asyncId: start.handle.asyncId,
    asyncDir: start.handle.asyncDir,
    children: [{ key: "plan-fidelity", runId: "child-1" }],
  });
  const result = await start.result;
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    { key: "correctness", reason: "lane-failed", detail: "lane exploded" },
  ]);
  // The settle enriches the receipt children's agent from the Perk-owned lane specs.
  assert.deepEqual(result.receipt.children, [
    { key: "plan-fidelity", agent: "perk.pr-reviewer", runId: "child-1" },
  ]);
});

test("startReportWave: the launch-failure arm returns an already-settled normalized WaveResult", async () => {
  const start = await startReportWave(createMemoryWaveAdapter({ ping: null }), makeSpec());
  assert.equal(start.ok, false);
  if (start.ok) return;
  assert.deepEqual(start.launch, {
    requested: ["plan-fidelity", "correctness"],
    runnable: ["plan-fidelity", "correctness"],
    preflightFailures: [],
  });
  assert.deepEqual(start.result, {
    complete: false,
    reports: [],
    failures: [
      {
        key: null,
        reason: "unavailable",
        detail:
          "pi-subagents did not advertise the report-wave capabilities (ping failed or incomplete)",
      },
    ],
    receipt: { state: "unavailable", children: [] },
  });
});

test("startReportWave: launch reports ordered partial preflight omissions truthfully", async () => {
  const assignments: ReportAssignment[] = [
    ASSIGNMENTS[0] as ReportAssignment,
    {
      key: "ponytail",
      agent: "perk.pr-reviewer",
      task: "review minimally",
      skill: "ponytail",
      requiredSkill: PONYTAIL_CORE_SKILL,
    },
  ];
  const start = await startReportWave(
    createMemoryWaveAdapter({
      aggregate: {
        state: "complete",
        value: [okEntry("plan-fidelity", { verdict: "clean" })],
      },
    }),
    makeSpec({
      assignments,
      requiredSkillPreflight: async () => ({
        ok: false,
        detail: "exact Ponytail source missing",
      }),
    }),
  );
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const failure = {
    key: "ponytail",
    reason: "skill-unavailable",
    detail: "exact Ponytail source missing",
  } as const;
  assert.deepEqual(start.launch, {
    requested: ["plan-fidelity", "ponytail"],
    runnable: ["plan-fidelity"],
    preflightFailures: [failure],
  });
  const result = await start.result;
  assert.deepEqual(result.failures, [failure]);
});

test("startReportWave: all preflight-skipped returns unavailable without a synthetic wave failure", async () => {
  const assignments: ReportAssignment[] = ["ponytail-first", "ponytail-second"].map((key) => ({
    key,
    agent: "perk.pr-reviewer",
    task: "review minimally",
    skill: "ponytail",
    requiredSkill: PONYTAIL_CORE_SKILL,
  }));
  const adapter = createMemoryWaveAdapter({});
  const start = await startReportWave(
    adapter,
    makeSpec({
      assignments,
      requiredSkillPreflight: async () => ({
        ok: false,
        detail: "exact Ponytail source missing",
      }),
    }),
  );
  assert.equal(start.ok, false);
  if (start.ok) return;
  const failures = assignments.map((assignment) => ({
    key: lane.key,
    reason: "skill-unavailable" as const,
    detail: "exact Ponytail source missing",
  }));
  assert.deepEqual(start.launch, {
    requested: ["ponytail-first", "ponytail-second"],
    runnable: [],
    preflightFailures: failures,
  });
  assert.deepEqual(start.result, {
    complete: false,
    reports: [],
    failures,
    receipt: { state: "unavailable", children: [] },
  });
  assert.equal(adapter.calls.spawn.length, 0);
});

test("startReportWave: spawn failure retains the full runnable launch manifest", async () => {
  const start = await startReportWave(
    createMemoryWaveAdapter({ spawnError: "no session" }),
    makeSpec(),
  );
  assert.equal(start.ok, false);
  if (start.ok) return;
  assert.deepEqual(start.launch, {
    requested: ["plan-fidelity", "correctness"],
    runnable: ["plan-fidelity", "correctness"],
    preflightFailures: [],
  });
  assert.equal(start.result.failures[0]?.reason, "spawn-failed");
});

test("startReportWave: duplicate lane keys throw (programmer error preserved)", async () => {
  await assert.rejects(
    startReportWave(
      createMemoryWaveAdapter({}),
      makeSpec({
        assignments: [
          { key: "same", agent: "a", task: "t1" },
          { key: "same", agent: "a", task: "t2" },
        ],
      }),
    ),
    /duplicate lane key 'same'/,
  );
});

test("toAttemptReceipt copies the pre-launch manifest and spreads the receipt", () => {
  const requested = ["plan-fidelity", "correctness"];
  const attempt = toAttemptReceipt("pr-review", 1, requested, {
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "complete",
    children: [{ key: "plan-fidelity", runId: "child-1" }],
  });
  assert.deepEqual(attempt, {
    flow: "pr-review",
    attempt: 1,
    requestedKeys: ["plan-fidelity", "correctness"],
    runId: "wave-async-1",
    asyncDir: "/memory/wave-async-1",
    state: "complete",
    children: [{ key: "plan-fidelity", runId: "child-1" }],
  });
  // The manifest is copied, never aliased.
  requested.push("mutated");
  assert.deepEqual(attempt.requestedKeys, ["plan-fidelity", "correctness"]);
});
