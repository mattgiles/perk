// The learn analyst-wave policy's offline suite (memory adapter): the parse-don't-validate
// angle-policy matrix, the spec/spawn contract (`mission: false`, `context: "fresh"`, the
// flow-owned schema, the composed lane tasks), the best-effort mapping learn rides (lane failure
// = a reported skipped angle, never an incomplete wave), the typed wave-outcome mapping, and the
// cancellation contract (a pre-aborted signal settles as `cancelled` — no spawn issued). The
// runner's own matrix lives in reportWave.test.ts — not re-tested here beyond the wave-level
// arms the flow surfaces.

import assert from "node:assert/strict";
import { test } from "node:test";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import { reportWaveOver } from "../waves/reportWave.ts";
import {
  decodeLearnAnalystReport,
  LEARN_ANALYST_REPORT_SCHEMA,
  LEARN_ANGLES,
  type LearnAngleSelection,
  learnManifestPath,
  parseAngleSelections,
  runLearnAnalystWave,
} from "./analystWave.ts";
import { CAPTURED_DECISIONS } from "./capture.ts";

const BUNDLE_DIR = "/abs/learn-evidence";
const MANIFEST_PATH = "/abs/learn-evidence/manifest.json";

function selections(...angles: string[]): LearnAngleSelection[] {
  const parsed = parseAngleSelections(angles.map((angle) => ({ angle })));
  assert.ok(parsed.ok, `fixture selection must be valid: ${angles.join(", ")}`);
  return parsed.selections;
}

/** A schema-shaped analyst report (the engine already validated it — shape only matters here). */
function analystReport(angle: string): unknown {
  return { angle, verdict: "clean", candidates: [], fyi: [] };
}

// --------------------------------------------------------------- the report decoder boundary

test("decodeLearnAnalystReport: happy typed construction — angle set from the validated key", () => {
  const decoded = decodeLearnAnalystReport("session-deviations", {
    angle: "session-deviations",
    verdict: "actionable",
    candidates: [
      {
        decision: "CAPTURE_LEARN",
        summary: "a durable deviation",
        target: null,
        evidence: "the session transcript",
      },
      { decision: "SKIP", summary: "noise", target: "docs/learned/x.md", evidence: "e" },
    ],
    fyi: ["borderline note"],
  });
  assert.deepEqual(decoded, {
    ok: true,
    report: {
      angle: "session-deviations",
      verdict: "actionable",
      candidates: [
        {
          decision: "CAPTURE_LEARN",
          summary: "a durable deviation",
          target: null,
          evidence: "the session transcript",
        },
        { decision: "SKIP", summary: "noise", target: "docs/learned/x.md", evidence: "e" },
      ],
      fyi: ["borderline note"],
    },
  });
});

test("decodeLearnAnalystReport: unknown extra fields are never copied (whitelist construction)", () => {
  const decoded = decodeLearnAnalystReport("existing-docs", {
    angle: "existing-docs",
    verdict: "clean",
    candidates: [],
    fyi: [],
    smuggled: "instruction-shaped junk",
  });
  assert.deepEqual(decoded, {
    ok: true,
    report: { angle: "existing-docs", verdict: "clean", candidates: [], fyi: [] },
  });
});

test("decodeLearnAnalystReport: a schema-valid report echoing a DIFFERENT angle contradicts its lane", () => {
  const decoded = decodeLearnAnalystReport("session-deviations", analystReport("existing-docs"));
  assert.deepEqual(decoded, {
    ok: false,
    detail:
      "analyst report angle 'existing-docs' contradicts the assigned lane 'session-deviations'",
  });
});

test("decodeLearnAnalystReport: the defensive unknown-key arm (unreachable in production)", () => {
  const decoded = decodeLearnAnalystReport("not-an-angle", analystReport("session-deviations"));
  assert.deepEqual(decoded, {
    ok: false,
    detail: "analyst lane key 'not-an-angle' is not a learn angle",
  });
});

test("decodeLearnAnalystReport: everything else → the ONE stable generic vocabulary detail", () => {
  const generic = {
    ok: false,
    detail: "analyst report for lane 'session-deviations' is outside the report schema vocabulary",
  };
  const base = analystReport("session-deviations") as Record<string, unknown>;
  const candidate = {
    decision: "CAPTURE_LEARN",
    summary: "s",
    target: null,
    evidence: "e",
  };
  for (const [label, report] of [
    ["non-record report", "prose, not an object"],
    ["array report", []],
    ["missing verdict", { ...base, verdict: undefined }],
    ["out-of-enum verdict", { ...base, verdict: "mixed" }],
    ["non-array candidates", { ...base, candidates: "none" }],
    ["non-record candidate", { ...base, candidates: ["nope"] }],
    ["out-of-enum decision", { ...base, candidates: [{ ...candidate, decision: "MERGE" }] }],
    ["non-string summary", { ...base, candidates: [{ ...candidate, summary: 7 }] }],
    ["non-string evidence", { ...base, candidates: [{ ...candidate, evidence: null }] }],
    ["mistyped target", { ...base, candidates: [{ ...candidate, target: 7 }] }],
    ["non-string fyi member", { ...base, fyi: ["ok", 7] }],
    ["non-array fyi", { ...base, fyi: "nope" }],
    ["angle not an angle string", { ...base, angle: "banana" }],
    ["angle mistyped", { ...base, angle: 7 }],
  ] as const) {
    assert.deepEqual(decodeLearnAnalystReport("session-deviations", report), generic, label);
  }
});

// ------------------------------------------------------------------------- the angle policy

test("parseAngleSelections: valid 2/3/4-angle selections (session-deviations included) narrow", () => {
  for (const angles of [
    ["session-deviations", "existing-docs"],
    ["session-deviations", "plan-vs-implementation", "existing-docs"],
    [...LEARN_ANGLES],
  ]) {
    const parsed = parseAngleSelections(angles.map((angle) => ({ angle })));
    assert.ok(parsed.ok);
    assert.deepEqual(
      parsed.selections,
      angles.map((angle) => ({ angle })),
      "the ok arm carries the narrowed selections in input order",
    );
  }
});

test("parseAngleSelections: the emphasis rides the narrowed selection verbatim", () => {
  const parsed = parseAngleSelections([
    { angle: "session-deviations", emphasis: "the loop" },
    { angle: "existing-docs" },
  ]);
  assert.ok(parsed.ok);
  assert.deepEqual(parsed.selections, [
    { angle: "session-deviations", emphasis: "the loop" },
    { angle: "existing-docs" },
  ]);
});

test("parseAngleSelections: count violations name the 2–4 rule", () => {
  const one = parseAngleSelections([{ angle: "session-deviations" }]);
  assert.ok(!one.ok);
  assert.match(one.message, /2–4 angles \(got 1\)/);
  const five = parseAngleSelections(
    [...LEARN_ANGLES, "session-deviations"].map((angle) => ({ angle })),
  );
  assert.ok(!five.ok);
  assert.match(five.message, /2–4 angles \(got 5\)/);
});

test("parseAngleSelections: a duplicate angle is named", () => {
  const dup = parseAngleSelections([
    { angle: "session-deviations" },
    { angle: "session-deviations" },
  ]);
  assert.ok(!dup.ok);
  assert.match(dup.message, /duplicate angle 'session-deviations'/);
});

test("parseAngleSelections: an unknown slug names the valid four", () => {
  const unknown = parseAngleSelections([{ angle: "session-deviations" }, { angle: "vibes" }]);
  assert.ok(!unknown.ok);
  assert.match(unknown.message, /unknown angle 'vibes'/);
  for (const angle of LEARN_ANGLES) {
    assert.match(unknown.message, new RegExp(angle));
  }
});

test("parseAngleSelections: a selection missing session-deviations is rejected", () => {
  const missing = parseAngleSelections([
    { angle: "plan-vs-implementation" },
    { angle: "existing-docs" },
  ]);
  assert.ok(!missing.ok);
  assert.match(missing.message, /'session-deviations' angle is mandatory/);
});

// ------------------------------------------------------------------ the derived vocabularies

test("learnManifestPath: the one derivation point for <bundle_dir>/manifest.json", () => {
  assert.equal(learnManifestPath(BUNDLE_DIR), MANIFEST_PATH);
});

test("LEARN_ANALYST_REPORT_SCHEMA: enums are derived from the vocabulary constants", () => {
  const schema = LEARN_ANALYST_REPORT_SCHEMA as {
    required: string[];
    properties: {
      angle: { enum: string[] };
      candidates: { items: { required: string[]; properties: { decision: { enum: string[] } } } };
    };
  };
  assert.deepEqual(schema.required, ["angle", "verdict", "candidates", "fyi"]);
  assert.deepEqual(schema.properties.angle.enum, [...LEARN_ANGLES]);
  assert.deepEqual(schema.properties.candidates.items.properties.decision.enum, [
    ...CAPTURED_DECISIONS,
    "SKIP",
  ]);
  assert.deepEqual(schema.properties.candidates.items.required, [
    "decision",
    "summary",
    "target",
    "evidence",
  ]);
});

// -------------------------------------------------------------------- the spec/spawn contract

test("runLearnAnalystWave: the spawn carries the module contract + the flow-owned schema", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
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

test("runLearnAnalystWave: no configured model → no model key on the spawn", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.ok(adapter.calls.spawn[0] !== undefined && !("model" in adapter.calls.spawn[0]));
});

test("runLearnAnalystWave: the composed task derives the manifest path and appends emphasis verbatim", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: [
      { angle: "session-deviations", emphasis: "the agent misread the adapter seam & looped" },
      { angle: "existing-docs" },
    ],
  });
  const script = adapter.calls.spawn[0]?.workflowScript ?? "";
  const items = waveScriptItems(script) as Array<{ key: string; task: string }>;
  const deviations = items.find((i) => i.key === "session-deviations");
  assert.ok(deviations !== undefined);
  assert.match(deviations.task, /angle: session-deviations/);
  assert.ok(deviations.task.includes(MANIFEST_PATH), "task names the derived manifest path");
  assert.ok(deviations.task.includes(BUNDLE_DIR), "task names the bundle dir");
  assert.ok(
    deviations.task.includes("the agent misread the adapter seam & looped"),
    "the parent's emphasis is appended verbatim",
  );
  const docs = items.find((i) => i.key === "existing-docs");
  assert.ok(docs !== undefined);
  assert.doesNotMatch(docs.task, /Emphasis:/);
});

// ------------------------------------------------------- best-effort mapping → typed outcome

test("runLearnAnalystWave: a failed lane maps to a complete outcome with an explicit skipped angle", async () => {
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
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(outcome.kind, "complete");
  assert.deepEqual(outcome.reports, [
    { angle: "session-deviations", report: analystReport("session-deviations") },
  ]);
  assert.deepEqual(outcome.skipped, [
    { angle: "existing-docs", reason: "lane-failed", detail: "lane exploded" },
  ]);
  // ONE attempt, ever — the receipt rides the outcome (observability only).
  assert.equal(outcome.attempts.length, 1);
  assert.equal(outcome.attempts[0]?.flow, "learn");
  assert.equal(outcome.attempts[0]?.attempt, 1);
  assert.deepEqual(outcome.attempts[0]?.requestedKeys, ["session-deviations", "existing-docs"]);
});

test("runLearnAnalystWave: a non-object report is malformed-report; a missing key is missing-lane", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: "session-deviations", ok: true, error: null, report: "prose, not an object" }],
    },
  });
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(outcome.kind, "complete");
  assert.deepEqual(outcome.reports, []);
  assert.deepEqual(
    outcome.skipped.map((s) => [s.angle, s.reason]),
    [
      ["session-deviations", "malformed-report"],
      ["existing-docs", "missing-lane"],
    ],
  );
});

test("runLearnAnalystWave: a decoder refusal moves the lane to skipped/malformed-report, decoder skips first", async () => {
  // Lane 1 echoes the WRONG angle (schema-valid, contradictory); lane 2 fails at the wave
  // level. The decoder skip is appended FIRST (report order), then the wave's lane failure.
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: "session-deviations",
          ok: true,
          error: null,
          report: analystReport("existing-docs"),
        },
        { key: "validation-risk", ok: false, error: "lane exploded", report: null },
      ],
    },
  });
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "validation-risk"),
  });
  assert.equal(outcome.kind, "complete");
  assert.deepEqual(outcome.reports, [], "a contradictory report is never salvaged");
  assert.deepEqual(outcome.skipped, [
    {
      angle: "session-deviations",
      reason: "malformed-report",
      detail:
        "analyst report angle 'existing-docs' contradicts the assigned lane 'session-deviations'",
    },
    { angle: "validation-risk", reason: "lane-failed", detail: "lane exploded" },
  ]);
});

test("runLearnAnalystWave: a null ping maps to wave_failed with reason unavailable", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(outcome.kind, "wave_failed");
  assert.equal(outcome.reason, "unavailable");
  // The receipt known before the failure rides the outcome.
  assert.deepEqual(outcome.attempts, [
    {
      flow: "learn",
      attempt: 1,
      requestedKeys: ["session-deviations", "existing-docs"],
      state: "unavailable",
      children: [],
    },
  ]);
});

test("runLearnAnalystWave: a spawn failure maps to wave_failed with its reason + detail", async () => {
  const adapter = createMemoryWaveAdapter({ spawnError: "no session" });
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
  });
  assert.equal(outcome.kind, "wave_failed");
  assert.equal(outcome.reason, "spawn-failed");
  assert.match(outcome.detail, /no session/);
  assert.equal(outcome.attempts[0]?.state, "spawn-failed");
});

test("runLearnAnalystWave: a pre-aborted signal settles as cancelled — no spawn issued", async () => {
  // The cancellation contract: an abort settles the wave as `cancelled` (normalized, never a
  // throw); pre-aborted means the wave never launches.
  const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: [] } });
  const controller = new AbortController();
  controller.abort();
  const outcome = await runLearnAnalystWave(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    selections: selections("session-deviations", "existing-docs"),
    signal: controller.signal,
  });
  assert.equal(outcome.kind, "wave_failed");
  assert.equal(outcome.reason, "cancelled");
  assert.equal(adapter.calls.spawn.length, 0, "a pre-aborted wave never spawns");
  assert.equal(outcome.attempts[0]?.state, "cancelled");
});
