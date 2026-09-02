// The report-wave module's own suite: the exact rendered-script pin (the tested workflowScript
// is the module's headline artifact — observed through the adapter seam's spawn params, since the
// renderer is module-private), the hostile-task embedding proof, and the full lifecycle
// normalization matrix driven through the in-memory adapter (wrapped via `reportWaveOver`) —
// every `ReportWaveFailureReason` arm plus both completeness policies, with zero event buses,
// child processes, or temp dirs. The attempt receipts get their own matrix: one receipt per
// terminal arm, lane-agent enrichment, and the behavior-parity proof that receipts never alter
// `complete`/`reports`/`failures`. The opaque start/collect lifecycle gets its own matrix:
// ref+telemetry starts, grace-raced collects (the `PERK_WAVE_COLLECT_GRACE_MS` env idiom — the
// ONE grace seam), instance-owned pending state, and delete-as-claim drain-once.

import assert from "node:assert/strict";
import { test } from "node:test";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter, type MemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import { PONYTAIL_CORE_SKILL } from "./ponytail.ts";
import {
  type CollectWaveResult,
  type ReportAssignment,
  type ReportWaveRequest,
  type ReportWaveResult,
  reportWaveOver,
  toAttemptReceipt,
} from "./reportWave.ts";
import {
  startWaveScript,
  WAVE_ACCEPTANCE,
  WAVE_TIMEOUT_MS,
  type WaveAdapter,
  type WaveChildReceipt,
  type WaveCompletion,
  type WaveScriptSpec,
} from "./transport.ts";

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

function makeSpec(overrides: Partial<ReportWaveRequest> = {}): ReportWaveRequest {
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

/** The exact rendered script for `ASSIGNMENTS` — the module's headline artifact, byte-pinned. */
const TWO_ASSIGNMENT_SCRIPT = `const reports = await runs.all([
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

const PREFLIGHT_OK = async (): Promise<{ ok: true }> => ({ ok: true });

/** The blocking form over a fresh wave instance (the suite's shorthand — one wave per run). */
function runReportWave(
  adapter: WaveAdapter,
  request: ReportWaveRequest,
  signal?: AbortSignal,
): Promise<ReportWaveResult> {
  return reportWaveOver(adapter).run(request, { signal });
}

/**
 * Render through the seam: the renderer is module-private, so the script bytes are observed the
 * only way production can — as the spawned `workflowScript` on the adapter's spawn params.
 */
async function renderedScript(overrides: Partial<ReportWaveRequest>): Promise<string> {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runReportWave(adapter, makeSpec({ completeness: "best-effort", ...overrides }));
  const script = adapter.calls.spawn[0]?.workflowScript;
  assert.ok(script !== undefined, "the wave spawned no script");
  return script;
}

// ---------------------------------------------------- the rendered script (through the seam)

test("the wave renders the exact two-assignment script", async () => {
  assert.equal(await renderedScript({}), TWO_ASSIGNMENT_SCRIPT);
});

test("the rendered script keeps hostile task text inside the array literal", async () => {
  const hostile = `end"}]); process.exit(1); //\n\`rm -rf ~\` \${process.env.HOME} \\" done`;
  const script = await renderedScript({
    assignments: [
      { key: "hostile", agent: "perk.pr-reviewer", task: hostile },
      { key: "tame", agent: "perk.pr-reviewer", task: "review calmly" },
    ],
  });
  // The array literal is exactly the JSON between `runs.all(` and the closing `);` before the
  // return line — parse it back and prove the hostile text arrived intact as DATA.
  const items = waveScriptItems(script) as Array<{ key: string; task: string }>;
  assert.equal(items.length, 2);
  assert.equal(items[0]?.task, hostile);
  assert.equal(items[1]?.task, "review calmly");
});

test("the rendered script carries a per-assignment outputSchema on exactly the assignments that carry one", async () => {
  const laneSchema = { type: "object", properties: { angle: { enum: ["custom-scope"] } } };
  const script = await renderedScript({
    assignments: [
      {
        key: "custom-scope",
        agent: "perk.pr-reviewer",
        task: "review the scope",
        outputSchema: laneSchema,
      },
      { key: "plain", agent: "perk.pr-reviewer", task: "review plainly" },
    ],
  });
  const items = waveScriptItems(script);
  assert.deepEqual(items[0]?.outputSchema, laneSchema);
  assert.equal(
    "outputSchema" in (items[1] ?? {}),
    false,
    "a schema-less lane renders without the field",
  );
});

test("the rendered script serializes opted-in skill but never required-skill metadata", async () => {
  const script = await renderedScript({
    assignments: [
      {
        key: "ponytail",
        agent: "perk.pr-reviewer",
        task: "review minimally",
        skill: "ponytail",
        requiredSkill: PONYTAIL_CORE_SKILL,
      },
      { key: "plain", agent: "perk.pr-reviewer", task: "review plainly" },
    ],
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  const items = waveScriptItems(script);
  assert.equal(items[0]?.skill, "ponytail");
  assert.equal("requiredSkill" in (items[0] ?? {}), false);
  assert.equal("skill" in (items[1] ?? {}), false);
});

test("the wave throws on duplicate assignment keys and empty assignments", async () => {
  await assert.rejects(
    runReportWave(
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
  await assert.rejects(
    runReportWave(createMemoryWaveAdapter({}), makeSpec({ assignments: [] })),
    /at least one lane/,
  );
});

test("the wave rejects assignment keys outside the pi-subagents run-key contract", async () => {
  // The upstream pattern is enforced only inside the live workflow worker, where an invalid
  // key fails the WHOLE wave at dispatch (`run-failed`) — the wave must reject it up
  // front as a programmer error instead.
  for (const bad of [
    "has@at",
    "a/slash",
    "-leading-dash",
    "",
    `x${"y".repeat(128)}`, // 129 chars
  ]) {
    await assert.rejects(
      runReportWave(
        createMemoryWaveAdapter({}),
        makeSpec({ assignments: [{ key: bad, agent: "a", task: "t" }] }),
      ),
      /violates the pi-subagents run-key contract|at least one lane/,
    );
  }
  // Boundary: 128 chars of the allowed charset passes.
  const maxKey = `k${"a".repeat(125)}.z`;
  assert.equal(maxKey.length, 128);
  assert.match(
    await renderedScript({ assignments: [{ key: maxKey, agent: "a", task: "t" }] }),
    /runs\.all/,
  );
});

test("wave.start validates the whole manifest BEFORE any preflight runs", async () => {
  // A malformed manifest is a programmer error even when a required skill would have been
  // partitioned out — the preflight spy must never fire.
  let preflights = 0;
  const spy = async (): Promise<{ ok: true }> => {
    preflights++;
    return { ok: true };
  };
  await assert.rejects(
    reportWaveOver(createMemoryWaveAdapter({})).start(
      makeSpec({
        assignments: [
          {
            key: "same",
            agent: "a",
            task: "t1",
            skill: "ponytail",
            requiredSkill: PONYTAIL_CORE_SKILL,
          },
          { key: "same", agent: "a", task: "t2" },
        ],
        requiredSkillPreflight: spy,
      }),
    ),
    /duplicate lane key 'same'/,
  );
  await assert.rejects(
    reportWaveOver(createMemoryWaveAdapter({})).start(
      makeSpec({
        assignments: [
          {
            key: "bad@key",
            agent: "a",
            task: "t",
            skill: "ponytail",
            requiredSkill: PONYTAIL_CORE_SKILL,
          },
        ],
        requiredSkillPreflight: spy,
      }),
    ),
    /violates the pi-subagents run-key contract/,
  );
  assert.equal(preflights, 0);
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
    workflowScript: TWO_ASSIGNMENT_SCRIPT,
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
    workflowScript: TWO_ASSIGNMENT_SCRIPT,
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

test("startWaveScript: a FOREIGN completion is ignored; only the matching identity settles", async () => {
  const value = [okEntry("plan-fidelity", { angle: "plan-fidelity" })];
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: { state: "complete", value },
  });
  const start = await startWaveScript(adapter, makeScriptSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  // Another run on the same channel completes first — the wave must NOT settle on it.
  adapter.emitCompletion({ asyncId: "foreign-run", asyncDir: "/memory/foreign-run" });
  assert.equal(await settlesWithin(start.result, 30), false);
  adapter.emitCompletion({ asyncId: start.handle.asyncId, asyncDir: start.handle.asyncDir });
  const result = await start.result;
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.value, value);
});

/** Wrap an adapter's `onComplete` with an active-subscription counter (no adapter API growth). */
function countingSubscriptions(adapter: MemoryWaveAdapter): {
  adapter: WaveAdapter;
  active(): number;
} {
  let active = 0;
  const wrapped: WaveAdapter = {
    ...adapter,
    onComplete(handler: (completion: WaveCompletion) => void): () => void {
      const off = adapter.onComplete(handler);
      active++;
      let released = false;
      return () => {
        if (!released) {
          released = true;
          active--;
        }
        off();
      };
    },
  };
  return { adapter: wrapped, active: () => active };
}

test("the runner releases its completion subscription on every settle arm", async () => {
  // Normal completion.
  const normal = countingSubscriptions(
    createMemoryWaveAdapter({
      aggregate: {
        state: "complete",
        value: [
          okEntry("plan-fidelity", { verdict: "clean" }),
          okEntry("correctness", { verdict: "clean" }),
        ],
      },
    }),
  );
  await runReportWave(normal.adapter, makeSpec());
  assert.equal(normal.active(), 0);

  // Timeout.
  const timedOut = countingSubscriptions(createMemoryWaveAdapter({ completion: false }));
  await runReportWave(timedOut.adapter, makeSpec({ timeoutMs: 20 }));
  assert.equal(timedOut.active(), 0);

  // Post-launch cancel.
  const cancelled = countingSubscriptions(createMemoryWaveAdapter({ completion: false }));
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 10);
  await runReportWave(cancelled.adapter, makeSpec(), controller.signal);
  assert.equal(cancelled.active(), 0);

  // Pre-spawn failure: the runner subscribes before spawning, so a rejected spawn must release.
  const spawnFailed = countingSubscriptions(createMemoryWaveAdapter({ spawnError: "no session" }));
  await runReportWave(spawnFailed.adapter, makeSpec());
  assert.equal(spawnFailed.active(), 0);
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

test("wave.start: the ok arm carries ref + identity telemetry; collect settles into normalization + strict completeness + receipt enrichment", async () => {
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
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  // Identity telemetry only (receipt vocabulary) — never an operable handle.
  assert.equal(start.runId, "wave-async-1");
  assert.equal(start.asyncDir, "/memory/wave-async-1");
  assert.deepEqual(start.launch, {
    requested: ["plan-fidelity", "correctness"],
    runnable: ["plan-fidelity", "correctness"],
    preflightFailures: [],
  });
  // Unsettled under a tiny grace: the ref stays pending (`running`), never dropped.
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  try {
    assert.deepEqual(await wave.collect(start.ref), { kind: "running" });
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
  adapter.emitCompletion({
    asyncId: start.runId,
    asyncDir: start.asyncDir,
    children: [{ key: "plan-fidelity", runId: "child-1" }],
  });
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.deepEqual(collected.keys, ["plan-fidelity", "correctness"]);
  const result = collected.result;
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, [{ key: "plan-fidelity", report: { verdict: "clean" } }]);
  assert.deepEqual(result.failures, [
    { key: "correctness", reason: "lane-failed", detail: "lane exploded" },
  ]);
  // The settle enriches the receipt children's agent from the Perk-owned lane specs.
  assert.deepEqual(result.receipt.children, [
    { key: "plan-fidelity", agent: "perk.pr-reviewer", runId: "child-1" },
  ]);
  // Drain-once: the ref is spent.
  assert.deepEqual(await wave.collect(start.ref), { kind: "none" });
});

test("wave.start: the launch-failure arm returns an already-settled normalized ReportWaveResult", async () => {
  const start = await reportWaveOver(createMemoryWaveAdapter({ ping: null })).start(makeSpec());
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

test("wave.start: launch reports ordered partial preflight omissions truthfully", async () => {
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
  const wave = reportWaveOver(
    createMemoryWaveAdapter({
      aggregate: {
        state: "complete",
        value: [okEntry("plan-fidelity", { verdict: "clean" })],
      },
    }),
  );
  const start = await wave.start(
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
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  // The collect keys are the REQUESTED manifest snapshot (the preflight-omitted key included).
  assert.deepEqual(collected.keys, ["plan-fidelity", "ponytail"]);
  assert.deepEqual(collected.result.failures, [failure]);
});

test("wave.start: all preflight-skipped returns unavailable without a synthetic wave failure", async () => {
  const assignments: ReportAssignment[] = ["ponytail-first", "ponytail-second"].map((key) => ({
    key,
    agent: "perk.pr-reviewer",
    task: "review minimally",
    skill: "ponytail",
    requiredSkill: PONYTAIL_CORE_SKILL,
  }));
  const adapter = createMemoryWaveAdapter({});
  const start = await reportWaveOver(adapter).start(
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
    key: assignment.key,
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

test("wave.start: spawn failure retains the full runnable launch manifest", async () => {
  const start = await reportWaveOver(createMemoryWaveAdapter({ spawnError: "no session" })).start(
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

test("wave.start: duplicate lane keys throw (programmer error preserved)", async () => {
  await assert.rejects(
    reportWaveOver(createMemoryWaveAdapter({})).start(
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

// ------------------------------------------------- the opaque collect lifecycle (wave-owned)

/** A request whose two lanes both settle clean (the collect matrix's common aggregate). */
function collectableAdapter(
  overrides: Partial<Parameters<typeof createMemoryWaveAdapter>[0] & object> = {},
): MemoryWaveAdapter {
  return createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("plan-fidelity", { verdict: "clean" }),
        okEntry("correctness", { verdict: "clean" }),
      ],
    },
    ...overrides,
  });
}

test("collect: running retains the ref; the later collect drains once; a second collect is none", async () => {
  // The retained-then-drained arc ported from the retired doors/pendingWave.ts suite,
  // re-expressed against wave.collect (grace via the PERK_WAVE_COLLECT_GRACE_MS env idiom —
  // the ONE grace seam; there is no per-call grace parameter).
  const adapter = collectableAdapter({ completion: false });
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  try {
    assert.deepEqual(
      await wave.collect(start.ref),
      { kind: "running" },
      "an unsettled wave is RETAINED, never dropped",
    );
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
  adapter.emitCompletion({ asyncId: start.runId, asyncDir: start.asyncDir });
  const drained = await wave.collect(start.ref);
  assert.equal(drained.kind, "settled");
  if (drained.kind !== "settled") return;
  assert.deepEqual(drained.keys, ["plan-fidelity", "correctness"]);
  assert.equal(drained.result.complete, true);
  // Drain-once: the following collect is none.
  assert.deepEqual(await wave.collect(start.ref), { kind: "none" });
});

test("collect grace: PERK_WAVE_COLLECT_GRACE_MS overrides; invalid values fall back (never a zero grace)", async () => {
  // The env knob is the one grace seam (the collectGraceMs default is module-private, so the
  // 15s default and the invalid-value fallback are pinned behaviorally): an unsettled wave
  // answers `running` under a tiny valid override, while an INVALID override falls back to the
  // module default — a result settling ~50ms in wins the race instead of a zero/NaN grace
  // expiring first.
  const adapter = collectableAdapter({ completion: false });
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const prev = process.env.PERK_WAVE_COLLECT_GRACE_MS;
  try {
    process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
    assert.deepEqual(await wave.collect(start.ref), { kind: "running" });
    process.env.PERK_WAVE_COLLECT_GRACE_MS = "nope";
    setTimeout(
      () => adapter.emitCompletion({ asyncId: start.runId, asyncDir: start.asyncDir }),
      50,
    );
    const settled = await wave.collect(start.ref);
    assert.equal(settled.kind, "settled", "an invalid override falls back to the module grace");
  } finally {
    if (prev === undefined) delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
    else process.env.PERK_WAVE_COLLECT_GRACE_MS = prev;
  }
});

test("collect: two overlapping collects of one settling ref yield exactly one settled winner", async () => {
  // NEW coverage (not a port): the delete-as-claim makes drain-once exact even under
  // concurrent collectors — both race the same unsettled result, both observe the settlement,
  // and the map delete awards `settled` to exactly one.
  const adapter = collectableAdapter({ completion: false });
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const first = wave.collect(start.ref);
  const second = wave.collect(start.ref);
  adapter.emitCompletion({ asyncId: start.runId, asyncDir: start.asyncDir });
  const outcomes = await Promise.all([first, second]);
  const kinds = outcomes.map((o) => o.kind).sort();
  assert.deepEqual(kinds, ["none", "settled"], "exactly one collector wins the drain");
  const winner = outcomes.find((o) => o.kind === "settled");
  assert.ok(winner !== undefined && winner.kind === "settled");
  assert.equal(winner.result.complete, true);
});

test("collect: pending state is instance-owned — a foreign instance's ref collects none", async () => {
  // NEW coverage (not a port): the module-contracts sentence made structural — each factory
  // result owns its pending WeakMap, so waveB.collect(refFromA) is `none` while waveA still
  // drains its own ref.
  const waveA = reportWaveOver(collectableAdapter());
  const waveB = reportWaveOver(collectableAdapter());
  const start = await waveA.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  assert.deepEqual(await waveB.collect(start.ref), { kind: "none" });
  const drained = await waveA.collect(start.ref);
  assert.equal(drained.kind, "settled", "the owning instance still drains its ref");
});

test("collect: draining ref A never affects a concurrently pending ref B", async () => {
  // NEW coverage (unrepresentable against the retired one-slot PendingWaveState): two live
  // refs on ONE instance; draining the first leaves the second pending and collectable.
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregates: [
      { state: "complete", value: [okEntry("plan-fidelity", { verdict: "clean" })] },
      { state: "complete", value: [okEntry("correctness", { verdict: "clean" })] },
    ],
  });
  const wave = reportWaveOver(adapter);
  const a = await wave.start(makeSpec({ assignments: [ASSIGNMENTS[0] as ReportAssignment] }));
  const b = await wave.start(makeSpec({ assignments: [ASSIGNMENTS[1] as ReportAssignment] }));
  assert.equal(a.ok, true);
  assert.equal(b.ok, true);
  if (!a.ok || !b.ok) return;
  adapter.emitCompletion({ asyncId: a.runId, asyncDir: a.asyncDir });
  const drainedA = await wave.collect(a.ref);
  assert.equal(drainedA.kind, "settled");
  if (drainedA.kind !== "settled") return;
  assert.deepEqual(drainedA.keys, ["plan-fidelity"]);
  // B is untouched: still pending under a tiny grace…
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  try {
    assert.deepEqual(await wave.collect(b.ref), { kind: "running" });
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
  // …and drains independently once it settles.
  adapter.emitCompletion({ asyncId: b.runId, asyncDir: b.asyncDir });
  const drainedB = await wave.collect(b.ref);
  assert.equal(drainedB.kind, "settled");
  if (drainedB.kind !== "settled") return;
  assert.deepEqual(drainedB.keys, ["correctness"]);
});

test("collect: the grace timer is cleared on the settled-immediately arm (no timer leak)", async () => {
  // NEW coverage (not a port): the finally-scoped clearTimeout — a collect whose result is
  // already settled must not leave its grace timer live (observed by patching the global
  // timer functions around exactly the collect call).
  const adapter = collectableAdapter();
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  // Let the auto-emitted completion (a macrotask) settle the wave before collecting.
  await new Promise((resolve) => setTimeout(resolve, 20));
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const live = new Set<unknown>();
  globalThis.setTimeout = ((fn: () => void, ms?: number) => {
    const timer = originalSetTimeout(fn, ms);
    live.add(timer);
    return timer;
  }) as typeof setTimeout;
  globalThis.clearTimeout = ((timer: Parameters<typeof clearTimeout>[0]) => {
    live.delete(timer);
    return originalClearTimeout(timer);
  }) as typeof clearTimeout;
  try {
    const collected = await wave.collect(start.ref);
    assert.equal(collected.kind, "settled");
  } finally {
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
  }
  assert.equal(live.size, 0, "the settled-immediately collect cleared its grace timer");
});

test("collect keys are a frozen snapshot — mutating the returned launch manifest changes nothing", async () => {
  // NEW coverage (not a port): the pending record's keys are copied (and frozen) at start,
  // never an alias of StartWaveResult.launch.
  const adapter = collectableAdapter();
  const wave = reportWaveOver(adapter);
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  start.launch.requested.push("intruder");
  start.launch.requested.splice(0, 1);
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  assert.deepEqual(collected.keys, ["plan-fidelity", "correctness"]);
  assert.ok(Object.isFrozen(collected.keys), "the snapshot is frozen against caller mutation");
});

test("ReportWaveRef is nominal — a structural forgery is a compile-time error (and collects none)", async () => {
  const wave = reportWaveOver(collectableAdapter());
  // @ts-expect-error — the declared unique-symbol brand has no forgeable member, so a plain
  // object literal is not assignable where a ReportWaveRef is required.
  const forged: Promise<CollectWaveResult> = wave.collect({});
  assert.deepEqual(await forged, { kind: "none" });
  // The ref type exposes no operational members: nothing to await, stop, or read through.
  const start = await wave.start(makeSpec());
  assert.equal(start.ok, true);
  if (!start.ok) return;
  // @ts-expect-error — no `result` promise rides the ref (the wave owns pending execution).
  start.ref.result;
  const drained = await wave.collect(start.ref);
  assert.equal(drained.kind, "settled");
});
