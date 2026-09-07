// The pr-review wave entrypoint's suite: lane construction (the angle vocabulary + the uniform
// directive suffix), the report-schema pin (the wave's `outputSchema`), and the bounded-retry
// policy matrix — all driven through the in-memory adapter (per-spawn `aggregates` FIFO for the
// two-wave scenarios), mirroring reportWave.test.ts conventions.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Compile } from "typebox/compile";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import {
  buildPrReviewAssignments,
  directiveSuffix,
  isPrReviewAngle,
  PR_REVIEW_ANGLES,
  PR_REVIEW_REPORT_SCHEMA,
  type PrReviewAngle,
  type PrReviewWaveOptions,
  reviewTargetSuffix,
  runPrReviewWave as runPrReviewWaveBase,
} from "./prReviewWave.ts";
import { type ReportWaveRequest, type ReportWaveResult, reportWaveOver } from "./reportWave.ts";
import type { WaveAdapter } from "./transport.ts";

const TWO_ANGLES: PrReviewAngle[] = ["plan-fidelity", "correctness"];
const PONYTAIL_TASK =
  "angle: ponytail — exclusively review standalone YAGNI, deletion, dead flexibility, dependencies/configuration to remove, and materially smaller/native replacements.";
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const runPrReviewWave = (
  adapter: WaveAdapter,
  opts: Omit<PrReviewWaveOptions, "pr"> & { pr?: number },
) =>
  runPrReviewWaveBase(reportWaveOver(adapter), {
    pr: opts.pr ?? 42,
    ...opts,
    requiredSkillPreflight: PREFLIGHT_OK,
  });

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

/** Parse the lane items back out of a rendered wave script (the shared slice helper). */
function laneItemsOf(script: string): Array<{
  key: string;
  agent: string;
  task: string;
  label: string;
  phase?: string;
  skill?: string;
}> {
  return waveScriptItems(script) as Array<{
    key: string;
    agent: string;
    task: string;
    label: string;
    phase?: string;
    skill?: string;
  }>;
}

// -------------------------------------------------------------------------- lane construction

test("runPrReviewWave builds selected lanes plus one final Ponytail lane", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript).map(
    ({ key, agent, task, label, phase, skill }) => ({
      key,
      agent,
      task,
      label,
      phase,
      ...(skill === undefined ? {} : { skill }),
    }),
  );
  assert.deepEqual(items, [
    ...TWO_ANGLES.map((angle) => ({
      key: angle,
      agent: "perk.pr-reviewer",
      task: `${PR_REVIEW_ANGLES[angle]}${reviewTargetSuffix(42)}`,
      label: angle,
      phase: "review",
    })),
    {
      key: "ponytail",
      agent: "perk.pr-reviewer",
      task: `${PONYTAIL_TASK}${reviewTargetSuffix(42)}`,
      label: "ponytail",
      phase: "review",
      skill: "ponytail-review",
    },
  ]);
});

test("runPrReviewWave appends ONE uniform directive suffix to EVERY lane task when set", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  await runPrReviewWave(adapter, {
    angles: TWO_ANGLES,
    directive: "focus on the dignified-python skill",
    timeoutMs: 5_000,
  });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript);
  assert.equal(items.length, 3);
  for (const item of items) {
    const opener =
      item.key === "ponytail" ? PONYTAIL_TASK : PR_REVIEW_ANGLES[item.key as PrReviewAngle];
    assert.ok(item.task.startsWith(opener), `${item.key} keeps the vocabulary`);
    assert.match(item.task, /Operator focus \(DATA from the human/);
    assert.match(item.task, /emphasis within your assigned angle only/);
    assert.match(item.task, /focus on the dignified-python skill/);
    assert.match(item.task, /perk pr review-context --expected-pr 42 --json/);
  }
  // The suffix is identical across lanes (one uniform DATA note, never per-lane re-scoping).
  const suffixes = items.map((item) => {
    const opener =
      item.key === "ponytail" ? PONYTAIL_TASK : PR_REVIEW_ANGLES[item.key as PrReviewAngle];
    return item.task.slice(opener.length);
  });
  assert.equal(new Set(suffixes).size, 1);
});

test("runPrReviewWave keeps lane tasks bound to one expected PR when no directive is set", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("tests"), okEntry("ponytail")],
    },
  });
  await runPrReviewWave(adapter, { angles: ["plan-fidelity", "tests"], timeoutMs: 5_000 });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = laneItemsOf(spawn.workflowScript);
  assert.equal(items[0]?.task, `${PR_REVIEW_ANGLES["plan-fidelity"]}${reviewTargetSuffix(42)}`);
  assert.equal(items[1]?.task, `${PR_REVIEW_ANGLES.tests}${reviewTargetSuffix(42)}`);
  assert.match(items[2]?.task ?? "", /^angle: ponytail/);
  assert.equal(items[2]?.skill, "ponytail-review");
});

test("runPrReviewWave spawn params carry the report schema as outputSchema and the threaded model", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
    },
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

test("isPrReviewAngle narrows the seven slugs and rejects prototype names", () => {
  for (const slug of [
    "plan-fidelity",
    "correctness",
    "tests",
    "quality",
    "api-design",
    "code-organization",
    "idioms",
  ]) {
    assert.equal(isPrReviewAngle(slug), true);
  }
  assert.equal(isPrReviewAngle("security"), false);
  assert.equal(isPrReviewAngle("toString"), false);
});

test("directiveSuffix is byte-identical to the suffix buildPrReviewAssignments appends (and empty unset)", () => {
  assert.equal(directiveSuffix(undefined), "");
  const directive = "focus on the decode edges";
  const [lane] = buildPrReviewAssignments(["plan-fidelity"], 42, directive);
  assert.ok(lane);
  assert.equal(
    lane.task,
    `${PR_REVIEW_ANGLES["plan-fidelity"]}${reviewTargetSuffix(42)}${directiveSuffix(directive)}`,
    "the exported suffix is the exact bytes the lane builder appends",
  );
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
    allOf: unknown[];
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ["angle", "verdict", "findings", "fyi"]);
  assert.deepEqual(s.properties.angle.enum, [
    "plan-fidelity",
    "correctness",
    "tests",
    "quality",
    "api-design",
    "code-organization",
    "idioms",
    "ponytail",
  ]);
  assert.deepEqual(s.properties.verdict.enum, ["clean", "actionable", "blocked"]);
  assert.equal(s.properties.findings.items.additionalProperties, false);
  assert.deepEqual(s.properties.findings.items.required, ["path", "line", "body"]);
  assert.equal(s.properties.findings.items.properties.line.type, "integer");
  assert.equal(s.properties.fyi.items.type, "string");
  assert.equal(s.allOf.length, 2);
  const validator = Compile(PR_REVIEW_REPORT_SCHEMA);
  const base = { angle: "plan-fidelity", verdict: "clean", findings: [], fyi: [] };
  const finding = { path: "a.ts", line: 1, body: "fix" };
  for (const [overrides, valid] of [
    [{}, true],
    [{ findings: [finding] }, false],
    [{ verdict: "actionable", findings: [finding] }, true],
    [{ verdict: "blocked", fyi: ["no_plan_ref"] }, true],
    [{ verdict: "blocked", fyi: ["  missing\n evidence  "] }, true],
    [{ verdict: "blocked", fyi: [] }, false],
    [{ verdict: "blocked", fyi: [""] }, false],
    [{ verdict: "blocked", fyi: [" \n\t"] }, false],
    [{ verdict: "blocked", fyi: ["blocker", " "] }, false],
    [{ verdict: "blocked", fyi: ["blocker"], findings: [finding] }, false],
    [{ verdict: "blocked", fyi: null }, false],
    [{ verdict: "blocked", fyi: [1] }, false],
    [{ verdict: "other" }, false],
  ] as const)
    assert.equal(validator.Check({ ...base, ...overrides }), valid, JSON.stringify(overrides));
  assert.equal(validator.Check({ angle: base.angle, verdict: "blocked", findings: [] }), false);
});

for (const parentReadOnly of [false, true]) {
  test(`all automated lanes and retries stay caller-read-only over parent ${parentReadOnly}`, async () => {
    let captures = 0;
    const adapter = createMemoryWaveAdapter({
      aggregates: [
        {
          state: "complete",
          value: [
            okEntry("plan-fidelity"),
            failedEntry("correctness", "retry"),
            failedEntry("ponytail", "retry"),
          ],
        },
        { state: "complete", value: [okEntry("correctness"), okEntry("ponytail")] },
      ],
    });
    const wave = reportWaveOver(adapter, () => {
      captures++;
      return parentReadOnly;
    });
    const outcome = await runPrReviewWaveBase(wave, {
      pr: 42,
      angles: TWO_ANGLES,
      requiredSkillPreflight: PREFLIGHT_OK,
    });
    assert.equal(outcome.complete, true);
    assert.equal(captures, 2);
    for (const spawn of adapter.calls.spawn) {
      for (const item of waveScriptItems(spawn.workflowScript)) {
        assert.equal(item.worktree, false);
        assert.deepEqual(item.extensionBindings, {
          "perk.parent-restrictions/1": { readOnly: true },
        });
        for (const field of ["async", "cwd", "extensions", "workflowAwaitAsync", "execution"])
          assert.equal(field in item, false);
      }
    }
  });
}

// -------------------------------------------------------------------- blocked assessments

function blockedEntry(key: string, fyi: string[]) {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, verdict: "blocked", findings: [], fyi },
  };
}

for (const notes of [
  ["no_plan_ref: caller plan reference missing"],
  ["review_target_changed: expected PR 42"],
  ["context transport failed: command exited 1"],
  ["plan_body: null prevents plan-fidelity assessment"],
  [
    "mandatory caller check unfinished: missing evidence",
    "partial, unassessed, diagnostic-only: a.ts:9 possible race",
  ],
]) {
  for (const recovers of [true, false]) {
    test(`blocked lane ${notes[0]}: retry ${recovers ? "recovers" : "stays uncovered"}`, async () => {
      const adapter = createMemoryWaveAdapter({
        aggregates: [
          {
            state: "complete",
            value: [
              blockedEntry("plan-fidelity", notes),
              okEntry("correctness"),
              okEntry("ponytail"),
            ],
          },
          {
            state: "complete",
            value: [recovers ? okEntry("plan-fidelity") : blockedEntry("plan-fidelity", notes)],
          },
        ],
      });
      const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES });
      assert.equal(outcome.complete, recovers);
      assert.deepEqual(outcome.retried, ["plan-fidelity"]);
      assert.deepEqual(
        outcome.covered,
        recovers ? ["plan-fidelity", "correctness", "ponytail"] : ["correctness", "ponytail"],
      );
      assert.deepEqual(
        outcome.reports.map(({ key }) => key),
        outcome.covered,
      );
      assert.deepEqual(
        outcome.failures,
        recovers
          ? []
          : [
              {
                key: "plan-fidelity",
                reason: "lane-failed",
                detail: `reviewer blocked:\n${notes.join("\n")}`,
              },
            ],
      );
      assert.equal(adapter.calls.spawn.length, 2);
      const retry = adapter.calls.spawn[1];
      assert.ok(retry);
      assert.deepEqual(
        waveScriptItems(retry.workflowScript).map(({ key }) => key),
        ["plan-fidelity"],
      );
      assert.match(retry.workflowScript, /--expected-pr 42 --json/);
      assert.equal(outcome.attempts.length, 2);
    });
  }
}

async function injectedOutcome(result: ReportWaveResult) {
  const requests: ReportWaveRequest[] = [];
  const wave = reportWaveOver(createMemoryWaveAdapter({}));
  const outcome = await runPrReviewWaveBase(
    {
      ...wave,
      async run(request) {
        requests.push(request);
        return result;
      },
    },
    {
      pr: 42,
      angles: ["plan-fidelity", "correctness", "tests", "quality"],
      requiredSkillPreflight: PREFLIGHT_OK,
    },
  );
  return { outcome, requests };
}

const RECEIPT: ReportWaveResult["receipt"] = { state: "complete", runId: "attempt", children: [] };

for (const fyi of [undefined, null, "not an array", [null, 4, "", " \n\t"]]) {
  test(`blocked defensive FYI fallback: ${JSON.stringify(fyi)}`, async () => {
    const { outcome } = await injectedOutcome({
      complete: true,
      reports: [{ key: "plan-fidelity", report: { verdict: "blocked", fyi } }],
      failures: [],
      receipt: RECEIPT,
    });
    assert.deepEqual(outcome.failures, [
      {
        key: "plan-fidelity",
        reason: "lane-failed",
        detail: "reviewer blocked:\nrequired review assessment could not complete",
      },
    ]);
    assert.equal(outcome.complete, false);
    assert.deepEqual(outcome.covered, []);
    assert.deepEqual(outcome.retried, ["plan-fidelity"]);
  });
}

test("normalization preserves diagnostic bytes, report order and existing-failures-first ordering", async () => {
  const existing: ReportWaveResult["failures"] = [
    { key: null, reason: "cancelled", detail: "cancelled; no retry" },
    { key: "quality", reason: "lane-failed", detail: "existing" },
  ];
  const surviving = [
    { key: "correctness", report: { verdict: "clean", fyi: ["blocked is diagnostic text only"] } },
    { key: "ponytail", report: { verdict: "actionable" } },
  ] as const;
  const notes = [
    "  no_plan_ref\n",
    "duplicate",
    "duplicate",
    "\npartial, unassessed, diagnostic-only: a.ts:1  \n",
  ];
  const result: ReportWaveResult = {
    complete: false,
    reports: [
      surviving[0],
      {
        key: "tests",
        report: { angle: "wrong-angle", verdict: "blocked", fyi: [null, ...notes, " \t", 2] },
      },
      surviving[1],
      { key: "plan-fidelity", report: { verdict: "blocked", fyi: ["second blocked"] } },
    ],
    failures: existing,
    receipt: RECEIPT,
  };
  const { outcome, requests } = await injectedOutcome(result);
  assert.equal(requests.length, 1, "cancellation stays non-retryable");
  assert.deepEqual(outcome.reports, surviving);
  assert.deepEqual(outcome.failures, [
    ...existing,
    { key: "tests", reason: "lane-failed", detail: `reviewer blocked:\n${notes.join("\n")}` },
    { key: "plan-fidelity", reason: "lane-failed", detail: "reviewer blocked:\nsecond blocked" },
  ]);
  assert.equal(outcome.failures[0], existing[0]);
  assert.equal(outcome.failures[1], existing[1]);
  assert.equal(result.receipt, RECEIPT);
  assert.equal(outcome.attempts[0]?.children, RECEIPT.children);
  assert.equal(result.reports.length, 4, "input is not mutated");
});

test("only non-null non-array objects with exact blocked verdict are reclassified", async () => {
  const reports = ["plan-fidelity", "correctness", "tests", "quality", "ponytail"].map(
    (key, i) => ({
      key,
      report: [null, [], "blocked", { verdict: "BLOCKED" }, { fyi: ["blocked"] }][i],
    }),
  );
  const { outcome, requests } = await injectedOutcome({
    complete: false,
    reports,
    failures: [
      { key: null, reason: "cancelled", detail: "preserve failure even with all reports" },
    ],
    receipt: RECEIPT,
  });
  assert.deepEqual(outcome.reports, reports);
  assert.equal(outcome.complete, false, "all effective reports cannot erase surviving failures");
  assert.equal(requests.length, 1);
});

test("reviewer definition and managed mirror pin assessment and exact context acceptance", () => {
  const def = readFileSync(new URL("../../agents/pr-reviewer.md", import.meta.url), "utf8");
  assert.equal(
    readFileSync(new URL("../../.pi/agents/perk/pr-reviewer.md", import.meta.url), "utf8"),
    def,
  );
  for (const field of PR_REVIEW_REPORT_SCHEMA.required)
    assert.ok(def.includes(`\`${field}\``), field);
  for (const verdict of PR_REVIEW_REPORT_SCHEMA.properties.verdict.enum)
    assert.ok(def.includes(`\`${verdict}\``), verdict);
  for (const field of [
    "success",
    "error_type",
    "message",
    "pr",
    "branch",
    "base_ref",
    "head_ref",
    "title",
    "body",
    "diff",
    "plan_body",
  ])
    assert.ok(def.includes(`\`${field}\``), field);
  for (const rule of [
    /command exits zero and its entire stdout parses as one non-null\s+JSON object, not an array/,
    /Every field below must be present/,
    /never coerce\s+strings, numbers, booleans, or nulls/,
    /`success` \| Exactly `true`/,
    /`error_type`, `message` \| Both exactly `null`/,
    /Positive safe integer, exactly equal to the task's expected PR number/,
    /`branch`, `base_ref`, `head_ref` \| Each a string containing at least one non-whitespace character/,
    /`title` \| String containing at least one non-whitespace character/,
    /`body`, `diff` \| Each a string; empty and whitespace-only strings are permitted/,
    /`plan_body` \| String or `null`; additionally, `plan-fidelity` requires a string containing at least one non-whitespace character/,
    /Whitespace checks do not rewrite accepted text/,
    /Ignore unknown extra fields/,
    /missing `plan_body`\s+is malformed for every lane/,
    /explicit `null` or blank string is valid optional evidence for\s+non-plan-fidelity lanes/,
    /No other listed field is optional/,
    /Do not compare\s+them to the current local branch/,
    /infer a different PR, add head-SHA binding, or fetch again/,
    /failure code\/message where available/,
    /failed field\/check/,
    /perk pr review-context --expected-pr <n> --json/,
    /Never weaken or retry without `--expected-pr`/,
    /applicable mandatory checks/,
    /evidence necessary to evaluate a material concern/,
    /partial assessment is not promoted to `actionable`/,
    /optional supporting file\/caller/,
    /empty diff is not\s+by itself a block/,
    /On `clean` or `blocked`, `findings` is \*\*empty\*\*/,
    /Put the blocker first/,
    /partial, unassessed, diagnostic-only/,
    /These are not\s+postable findings/,
    /at least one string is required and every string must contain a\s+non-whitespace character/,
    /`structured_output` exactly once as your final action/,
    /no fenced JSON block/,
    /is your \*\*first action\*\*, before fetching review context/,
    /terminate without calling\s+`structured_output`/,
    /never resolve a same-named\s+project\/user skill/,
  ])
    assert.match(def, rule);
  assert.doesNotMatch(def, /state it in an `fyi` note|plan body not found.*note/);
});

// -------------------------------------------------------------------- the bounded-retry matrix

test("happy path: complete, all effective angles covered, no retry, ONE spawn", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "ponytail"]);
  assert.deepEqual(outcome.retried, []);
  assert.equal(outcome.reports.length, 3);
  assert.deepEqual(outcome.failures, []);
  assert.equal(adapter.calls.spawn.length, 1);
});

test("one failed lane: the retry wave carries ONLY the failed key; success merges to complete", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [
          okEntry("plan-fidelity"),
          failedEntry("correctness", "lane exploded"),
          okEntry("ponytail"),
        ],
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
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "ponytail"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, []);
});

test("retry fails again: incomplete with the surviving lane failure; covered = the subset", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [
          okEntry("plan-fidelity"),
          failedEntry("correctness", "lane exploded"),
          okEntry("ponytail"),
        ],
      },
      { state: "complete", value: [failedEntry("correctness", "exploded again")] },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "ponytail"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, [
    { key: "correctness", reason: "lane-failed", detail: "exploded again" },
  ]);
});

test("wave-level run-failed: the retry re-runs the WHOLE effective selection and can complete", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "workflow script threw", value: undefined },
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
      },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  assert.deepEqual(
    laneItemsOf(retrySpawn.workflowScript).map((item) => item.key),
    ["plan-fidelity", "correctness", "ponytail"],
  );
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "ponytail"]);
  assert.deepEqual(outcome.retried, ["plan-fidelity", "correctness", "ponytail"]);
  assert.deepEqual(outcome.failures, []);
});

test("skill-unavailable is non-retryable while an ordinary failed lane still retries", async () => {
  let preflightCalls = 0;
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), failedEntry("correctness", "retry me")],
      },
      { state: "complete", value: [okEntry("correctness")] },
    ],
  });
  const outcome = await runPrReviewWaveBase(reportWaveOver(adapter), {
    pr: 42,
    angles: TWO_ANGLES,
    timeoutMs: 5_000,
    requiredSkillPreflight: async () => {
      preflightCalls += 1;
      return { ok: false, detail: "exact Ponytail source is absent" };
    },
  });
  assert.equal(preflightCalls, 1, "the source is checked once for the whole pass");
  assert.equal(adapter.calls.spawn.length, 2);
  const firstSpawn = adapter.calls.spawn[0];
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(firstSpawn);
  assert.ok(retrySpawn);
  assert.deepEqual(
    laneItemsOf(firstSpawn.workflowScript).map((item) => item.key),
    ["plan-fidelity", "correctness"],
  );
  assert.deepEqual(
    laneItemsOf(retrySpawn.workflowScript).map((item) => item.key),
    ["correctness"],
  );
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, [
    {
      key: "ponytail",
      reason: "skill-unavailable",
      detail: "exact Ponytail source is absent",
    },
  ]);
  assert.deepEqual(outcome.attempts[0]?.requestedKeys, [
    "plan-fidelity",
    "correctness",
    "ponytail",
  ]);
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
    /at least one selected angle/,
  );
});

// ---------------------------------------------------------------------- the attempt receipts

test("attempts: a one-wave success records ONE complete attempt over the effective angles", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
    },
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
      requestedKeys: ["plan-fidelity", "correctness", "ponytail"],
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
        value: [
          okEntry("plan-fidelity"),
          failedEntry("correctness", "lane exploded"),
          okEntry("ponytail"),
        ],
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
    [1, ["plan-fidelity", "correctness", "ponytail"], "wave-async-1", "complete"],
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
      {
        state: "complete",
        value: [okEntry("plan-fidelity"), okEntry("correctness"), okEntry("ponytail")],
      },
    ],
  });
  const outcome = await runPrReviewWave(adapter, { angles: TWO_ANGLES, timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(
    outcome.attempts.map((a) => [a.attempt, a.state, a.runId, a.requestedKeys]),
    [
      [1, "failed", "wave-async-1", ["plan-fidelity", "correctness", "ponytail"]],
      [2, "complete", "wave-async-2", ["plan-fidelity", "correctness", "ponytail"]],
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
      requestedKeys: ["plan-fidelity", "correctness", "ponytail"],
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
      requestedKeys: ["plan-fidelity", "correctness", "ponytail"],
      state: "cancelled",
      children: [],
    },
  ]);
});
