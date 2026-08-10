// The dynamic-review entrypoint's suite. Three tiers, all offline:
// 1. renderer string pins — the JSON-embedded constants and the hostile-text discipline;
// 2. SCRIPT-EXECUTION tests — the rendered script is real code, so the normalization policy is
//    pinned by RUNNING it (the `AsyncFunction` constructor + a scripted fake `runs` global that
//    records calls and resolves configurable per-key results): every fallback/filter/dedupe/cap
//    arm, the concurrency shape, the bias control, and the `{selection, lanes}` aggregate shape;
// 3. runner tests over `createMemoryWaveAdapter` — defensive re-validation, strict completeness
//    over the effective selection, and the bounded-retry matrix (static failed-lanes retry, full
//    dynamic re-run, none on unavailable/cancelled), mirroring prReviewWave.test.ts conventions.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import {
  buildCustomLaneTask,
  customReportSchema,
  DYNAMIC_ADDITIONAL_ANGLES,
  DYNAMIC_FALLBACK_ANGLES,
  REVIEW_ANGLE_SELECTOR_SCHEMA,
  renderDynamicReviewScript,
  runPrReviewDynamicWave,
} from "./prReviewDynamicWave.ts";
import { directiveSuffix, PR_REVIEW_ANGLES, PR_REVIEW_REPORT_SCHEMA } from "./prReviewWave.ts";

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor as new (
  ...args: string[]
) => (runs: unknown) => Promise<unknown>;

/** A schema-valid selector report (override fields per test; empty strings = no custom). */
function selectorReport(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    change_profile: "a test change",
    selected_angles: ["correctness", "tests"],
    risk_flags: [],
    rationale: "test routing",
    confidence: "high",
    custom_angle_slug: "",
    custom_angle_scope: "",
    ...overrides,
  };
}

function cleanReport(key: string): Record<string, unknown> {
  return { angle: key, verdict: "clean", findings: [], fyi: [] };
}

interface ExecConfig {
  /** The selector's structuredOutput (ignored when selectorReject is set). */
  report?: unknown;
  /** When set, the selector's `runs.run` REJECTS with this message (the engine's failure arm). */
  selectorReject?: string;
  /** When set, plan-fidelity's `runs.run` REJECTS with this message. */
  planFidelityReject?: string;
  /** Fan-out keys that resolve `ok: false` in the all-settled batch. */
  reviewerFail?: string[];
}

interface ExecOutcome {
  value: {
    selection: {
      source: string;
      effective: string[];
      forced: string[];
      custom: { slug: string; scope: string } | null;
      selector_ok: boolean;
      selector_error: string | null;
      report: unknown;
    };
    lanes: { key: string; ok: boolean; error: string | null; report: unknown }[];
  };
  /** Ordered event log: run:<key>, selector-settled, all:<keys>, plan-fidelity-resolved. */
  events: string[];
  /** Every `runs.run(key, params)` call. */
  runCalls: { key: string; params: Record<string, unknown> }[];
  /** Every `runs.all(items)` batch. */
  allBatches: Record<string, unknown>[][];
}

/**
 * Execute a rendered dynamic script against a scripted fake `runs` global. Plan-fidelity is held
 * pending until the fan-out `runs.all` has been issued — so the recorded event order proves the
 * concurrency shape (fan-out launched while plan-fidelity is still running).
 */
async function execScript(script: string, config: ExecConfig = {}): Promise<ExecOutcome> {
  const events: string[] = [];
  const runCalls: ExecOutcome["runCalls"] = [];
  const allBatches: ExecOutcome["allBatches"] = [];
  let releasePlanFidelity: (() => void) | null = null;
  const runs = {
    run(key: string, params: Record<string, unknown>): Promise<unknown> {
      runCalls.push({ key, params });
      events.push(`run:${key}`);
      if (key === "plan-fidelity") {
        if (config.planFidelityReject !== undefined) {
          return Promise.reject(new Error(config.planFidelityReject));
        }
        return new Promise((resolve) => {
          releasePlanFidelity = () => {
            events.push("plan-fidelity-resolved");
            resolve({ key, ok: true, error: null, structuredOutput: cleanReport(key) });
          };
        });
      }
      if (config.selectorReject !== undefined) {
        events.push("selector-settled");
        return Promise.reject(new Error(config.selectorReject));
      }
      events.push("selector-settled");
      return Promise.resolve({ key, ok: true, error: null, structuredOutput: config.report });
    },
    all(items: Record<string, unknown>[]): Promise<unknown[]> {
      allBatches.push(items);
      events.push(`all:${items.map((item) => item.key).join(",")}`);
      const entries = items.map(({ key }) =>
        (config.reviewerFail ?? []).includes(key as string)
          ? { key, ok: false, error: "reviewer exploded", structuredOutput: undefined }
          : { key, ok: true, error: null, structuredOutput: cleanReport(key as string) },
      );
      // Release plan-fidelity only now — the script must have fanned out while it was pending.
      queueMicrotask(() => releasePlanFidelity?.());
      return Promise.resolve(entries);
    },
  };
  const fn = new AsyncFunction("runs", script);
  const value = (await fn(runs)) as ExecOutcome["value"];
  return { value, events, runCalls, allBatches };
}

function render(overrides: Parameters<typeof renderDynamicReviewScript>[0] = { forceAngles: [] }) {
  return renderDynamicReviewScript(overrides);
}

// ------------------------------------------------------------------- renderer string pins

test("renderDynamicReviewScript embeds the seven-angle task map and forced angles as parseable JSON", () => {
  const script = render({ forceAngles: ["quality"] });
  const tasksStart = script.indexOf("const TASKS = ") + "const TASKS = ".length;
  const tasksEnd = script.indexOf(";\nconst FORCED");
  const tasks = JSON.parse(script.slice(tasksStart, tasksEnd)) as Record<string, string>;
  assert.deepEqual(Object.keys(tasks).sort(), [
    "api-design",
    "code-organization",
    "correctness",
    "idioms",
    "plan-fidelity",
    "quality",
    "tests",
  ]);
  for (const [angle, task] of Object.entries(PR_REVIEW_ANGLES)) {
    assert.equal(tasks[angle], task, `${angle} task is byte-identical to the vocabulary`);
  }
  assert.ok(script.includes('const FORCED = ["quality"];'));
});

test("renderDynamicReviewScript embeds the selector item with its own outputSchema and model", async () => {
  const script = render({
    forceAngles: [],
    selectorModel: "test-selector-model",
    reviewerModel: "test-reviewer-model",
  });
  const { runCalls } = await execScript(script, { report: selectorReport() });
  const selector = runCalls.find((call) => call.key === "angle-selector");
  assert.ok(selector);
  assert.equal(selector.params.agent, "perk.review-angle-selector");
  assert.deepEqual(selector.params.outputSchema, REVIEW_ANGLE_SELECTOR_SCHEMA);
  assert.equal(selector.params.model, "test-selector-model");
  assert.equal(selector.params.label, "angle-selector");
  assert.equal(selector.params.phase, "select");
});

test("renderDynamicReviewScript omits the selector model when unset (frontmatter fallback)", async () => {
  const { runCalls } = await execScript(render({ forceAngles: [], reviewerModel: "rm" }), {
    report: selectorReport(),
  });
  const selector = runCalls.find((call) => call.key === "angle-selector");
  assert.ok(selector);
  assert.equal("model" in selector.params, false);
});

test("renderDynamicReviewScript threads the reviewer model onto plan-fidelity and every fan-out item", async () => {
  const { runCalls, allBatches } = await execScript(
    render({ forceAngles: [], reviewerModel: "test-reviewer-model" }),
    { report: selectorReport() },
  );
  const pf = runCalls.find((call) => call.key === "plan-fidelity");
  assert.equal(pf?.params.model, "test-reviewer-model");
  assert.equal(pf?.params.agent, "perk.pr-reviewer");
  assert.equal(pf?.params.task, PR_REVIEW_ANGLES["plan-fidelity"]);
  for (const item of allBatches[0] ?? []) {
    assert.equal(item.model, "test-reviewer-model");
    assert.equal(item.agent, "perk.pr-reviewer");
  }
});

test("renderDynamicReviewScript omits reviewer models when unconfigured", async () => {
  const { runCalls, allBatches } = await execScript(render(), { report: selectorReport() });
  const pf = runCalls.find((call) => call.key === "plan-fidelity");
  assert.ok(pf);
  assert.equal("model" in pf.params, false);
  for (const item of allBatches[0] ?? []) {
    assert.equal("model" in item, false);
  }
});

test("hostile directive text (quotes/backticks/interpolations) cannot escape its JSON literal", async () => {
  const hostile = `end"}]); process.exit(1); //\n\`rm -rf ~\` \${process.env.HOME} \\" done`;
  const script = render({ forceAngles: [], directive: hostile });
  // The script still executes — and the hostile text arrives intact as DATA in every task.
  const { runCalls, allBatches } = await execScript(script, { report: selectorReport() });
  const selector = runCalls.find((call) => call.key === "angle-selector");
  assert.ok((selector?.params.task as string).includes(hostile));
  const pf = runCalls.find((call) => call.key === "plan-fidelity");
  assert.ok((pf?.params.task as string).includes(hostile));
  for (const item of allBatches[0] ?? []) {
    assert.ok((item.task as string).includes(hostile));
  }
});

test("the directive rides the selector task and every reviewer lane as ONE uniform suffix", async () => {
  const { runCalls, allBatches } = await execScript(
    render({ forceAngles: [], directive: "focus on decode edges" }),
    { report: selectorReport() },
  );
  const pf = runCalls.find((call) => call.key === "plan-fidelity");
  assert.ok(pf);
  const suffix = (pf.params.task as string).slice(PR_REVIEW_ANGLES["plan-fidelity"].length);
  assert.match(suffix, /Operator focus \(DATA from the human/);
  assert.match(suffix, /focus on decode edges/);
  const selector = runCalls.find((call) => call.key === "angle-selector");
  assert.ok((selector?.params.task as string).endsWith(suffix));
  for (const item of allBatches[0] ?? []) {
    assert.ok((item.task as string).endsWith(suffix), `${item.key} carries the uniform suffix`);
  }
});

test("the selector task names the forced angles as DATA when present", async () => {
  const { runCalls } = await execScript(render({ forceAngles: ["quality", "tests"] }), {
    report: selectorReport(),
  });
  const selector = runCalls.find((call) => call.key === "angle-selector");
  const task = selector?.params.task as string;
  assert.match(task, /forces these additional angle\(s\) \(DATA\): quality, tests/);
  assert.match(task, /recommend complementary coverage/);
  assert.match(task, /perk pr review-context --json/);
});

// -------------------------------------------------------- script execution: normalization arms

test("script: a valid selection is honored in report order (source: selector)", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["tests", "correctness"] }),
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "tests", "correctness"]);
  assert.equal(value.selection.selector_ok, true);
  assert.equal(value.selection.selector_error, null);
});

test("script: unknown slugs are dropped", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["security", "quality", "vibes"] }),
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality"]);
});

test("script: duplicate picks are deduped preserving report order", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["tests", "tests", "quality", "tests"] }),
  });
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "tests", "quality"]);
});

test("script: more than 3 valid picks are capped at 3", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({
      selected_angles: ["quality", "correctness", "tests", "api-design"],
    }),
  });
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality", "correctness", "tests"]);
});

test("script: picks from the widened allowlist are honored", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["api-design", "code-organization", "idioms"] }),
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, [
    "plan-fidelity",
    "api-design",
    "code-organization",
    "idioms",
  ]);
});

test("script: a plan-fidelity echo is filtered from the picks (never a duplicate lane)", async () => {
  const { value, allBatches } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["plan-fidelity", "tests"] }),
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "tests"]);
  assert.deepEqual(
    (allBatches[0] ?? []).map((item) => item.key),
    ["tests"],
    "plan-fidelity never enters the fan-out",
  );
});

test("script: confidence 'low' falls back to correctness+tests even with valid picks", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["quality"], confidence: "low" }),
  });
  assert.equal(value.selection.source, "fallback");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "correctness", "tests"]);
  assert.equal(value.selection.selector_ok, true, "a low-confidence report is still a report");
});

test("script: a selector lane failure falls back (selector_ok false, error captured)", async () => {
  const { value } = await execScript(render(), { selectorReject: "selector lane exploded" });
  assert.equal(value.selection.source, "fallback");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "correctness", "tests"]);
  assert.equal(value.selection.selector_ok, false);
  assert.match(value.selection.selector_error ?? "", /selector lane exploded/);
  assert.equal(value.selection.report, null);
});

test("script: zero valid picks after filtering falls back", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["plan-fidelity", "security"] }),
  });
  assert.equal(value.selection.source, "fallback");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "correctness", "tests"]);
});

test("script: forced angles come first and cap the additional set with selector picks", async () => {
  const { value } = await execScript(render({ forceAngles: ["quality"] }), {
    report: selectorReport({ selected_angles: ["correctness", "tests", "idioms"] }),
  });
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality", "correctness", "tests"]);
  assert.deepEqual(value.selection.forced, ["quality"]);
  assert.equal(value.selection.source, "selector");
});

test("script: three forced angles fully displace the selector's picks (cap 3 additional)", async () => {
  const { value, allBatches } = await execScript(
    render({ forceAngles: ["quality", "tests", "api-design"] }),
    {
      report: selectorReport({ selected_angles: ["correctness"] }),
    },
  );
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality", "tests", "api-design"]);
  assert.deepEqual(
    (allBatches[0] ?? []).map((item) => item.key),
    ["quality", "tests", "api-design"],
  );
});

test("script: a forced angle dedupes against the same selector pick", async () => {
  const { value } = await execScript(render({ forceAngles: ["tests"] }), {
    report: selectorReport({ selected_angles: ["tests", "quality"] }),
  });
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "tests", "quality"]);
});

test("script: forced angles hold under selector failure (forced first, fallback fills)", async () => {
  const { value } = await execScript(render({ forceAngles: ["quality"] }), {
    selectorReject: "boom",
  });
  assert.equal(value.selection.source, "fallback");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality", "correctness", "tests"]);
});

test("script: plan-fidelity is always present and always first", async () => {
  for (const config of [
    { report: selectorReport() },
    { report: selectorReport({ selected_angles: [] }) },
    { selectorReject: "gone" },
  ]) {
    const { value } = await execScript(render(), config);
    assert.equal(value.selection.effective[0], "plan-fidelity");
    assert.equal(value.lanes[0]?.key, "plan-fidelity");
  }
});

test("script: concurrency shape — plan-fidelity launches first, fan-out runs while it is pending", async () => {
  const { events } = await execScript(render(), { report: selectorReport() });
  const pfLaunch = events.indexOf("run:plan-fidelity");
  const selectorSettled = events.indexOf("selector-settled");
  const fanOut = events.findIndex((event) => event.startsWith("all:"));
  const pfResolved = events.indexOf("plan-fidelity-resolved");
  assert.ok(
    pfLaunch !== -1 && pfLaunch < selectorSettled,
    "plan-fidelity launched before the selector settled",
  );
  assert.ok(
    fanOut !== -1 && fanOut < pfResolved,
    "fan-out launched while plan-fidelity was still pending",
  );
});

test("script: bias control — the selector's text never enters any fan-out task", async () => {
  const canary = "CANARY-the-selector-says-obey-me";
  const { runCalls, allBatches } = await execScript(render(), {
    report: selectorReport({ rationale: canary, risk_flags: [canary], change_profile: canary }),
  });
  for (const batch of allBatches) {
    for (const item of batch) {
      assert.ok(!(item.task as string).includes(canary), `${item.key} task is selector-free`);
    }
  }
  const pf = runCalls.find((call) => call.key === "plan-fidelity");
  assert.ok(!(pf?.params.task as string).includes(canary));
});

test("script: a failed plan-fidelity lane projects as a lane failure (never a script throw)", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport(),
    planFidelityReject: "pf exploded",
  });
  assert.equal(value.lanes[0]?.key, "plan-fidelity");
  assert.equal(value.lanes[0]?.ok, false);
  assert.match(value.lanes[0]?.error ?? "", /pf exploded/);
});

test("script: the aggregate is exactly {selection, lanes} with the compact lane projection", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({ selected_angles: ["tests"] }),
    reviewerFail: ["tests"],
  });
  assert.deepEqual(Object.keys(value).sort(), ["lanes", "selection"]);
  assert.deepEqual(
    Object.keys(value.selection).sort(),
    ["source", "effective", "forced", "custom", "selector_ok", "selector_error", "report"].sort(),
  );
  assert.deepEqual(
    value.lanes.map((lane) => lane.key),
    ["plan-fidelity", "tests"],
  );
  const failed = value.lanes[1];
  assert.ok(failed);
  assert.deepEqual(Object.keys(failed).sort(), ["error", "key", "ok", "report"]);
  assert.equal(failed.ok, false);
  assert.equal(failed.error, "reviewer exploded");
  assert.equal(failed.report, null);
});

// ----------------------------------------------------- script execution: the custom angle

test("script: a valid custom proposal launches a lane with the fixed template task and locked schema", async () => {
  const { value, allBatches } = await execScript(
    render({ forceAngles: [], directive: "focus here" }),
    {
      report: selectorReport({
        selected_angles: ["correctness"],
        custom_angle_slug: "cache-invalidation",
        custom_angle_scope: "staleness of the new memoization layer across the write paths",
      }),
    },
  );
  assert.deepEqual(value.selection.custom, {
    slug: "cache-invalidation",
    scope: "staleness of the new memoization layer across the write paths",
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, [
    "plan-fidelity",
    "correctness",
    "cache-invalidation",
  ]);
  const item = (allBatches[0] ?? []).find((entry) => entry.key === "cache-invalidation");
  assert.ok(item);
  assert.equal(item.agent, "perk.pr-reviewer");
  assert.equal(item.label, "cache-invalidation");
  assert.equal(item.phase, "review");
  // Byte-parity with the exported builders: the fixed template + the uniform directive suffix,
  // and the per-item report schema locked to echo the custom slug.
  assert.equal(
    item.task,
    buildCustomLaneTask(
      "cache-invalidation",
      "staleness of the new memoization layer across the write paths",
    ) + directiveSuffix("focus here"),
  );
  assert.deepEqual(item.outputSchema, customReportSchema("cache-invalidation"));
});

test("script: invalid custom slugs are dropped (pattern, reserved names, length)", async () => {
  for (const slug of [
    "Bad_Slug", // pattern (uppercase/underscore)
    "ab", // too short (< 3 chars)
    `a${"b".repeat(32)}`, // too long (> 32 chars)
    "quality", // reserved fixed slug
    "plan-fidelity", // reserved fixed slug (structural)
    "angle-selector", // reserved lane key
    "-leading-dash", // pattern (must start with a letter)
  ]) {
    const { value } = await execScript(render(), {
      report: selectorReport({
        selected_angles: ["tests"],
        custom_angle_slug: slug,
        custom_angle_scope: "a plausible scope",
      }),
    });
    assert.equal(value.selection.custom, null, `${slug} is dropped`);
    assert.deepEqual(
      value.selection.effective,
      ["plan-fidelity", "tests"],
      "the fixed picks proceed unaffected",
    );
  }
});

test("script: the custom scope is whitespace-collapsed; an over-long scope drops the proposal", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({
      custom_angle_slug: " cache-invalidation ",
      custom_angle_scope: "  staleness\n\tacross   the write\n paths  ",
    }),
  });
  assert.deepEqual(value.selection.custom, {
    slug: "cache-invalidation",
    scope: "staleness across the write paths",
  });

  const { value: overlong } = await execScript(render(), {
    report: selectorReport({
      selected_angles: ["tests"],
      custom_angle_slug: "cache-invalidation",
      custom_angle_scope: "x".repeat(301),
    }),
  });
  assert.equal(overlong.selection.custom, null);
  assert.deepEqual(overlong.selection.effective, ["plan-fidelity", "tests"]);
});

test("script: low confidence drops the custom proposal along with the picks", async () => {
  const { value } = await execScript(render(), {
    report: selectorReport({
      selected_angles: ["quality"],
      confidence: "low",
      custom_angle_slug: "cache-invalidation",
      custom_angle_scope: "a plausible scope",
    }),
  });
  assert.equal(value.selection.custom, null);
  assert.equal(value.selection.source, "fallback");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "correctness", "tests"]);
});

test("script: the custom angle is ordered last and sliced off by the 3-additional cap (custom ⇒ null)", async () => {
  const { value, allBatches } = await execScript(render({ forceAngles: ["quality", "tests"] }), {
    report: selectorReport({
      selected_angles: ["correctness", "idioms"],
      custom_angle_slug: "cache-invalidation",
      custom_angle_scope: "a plausible scope",
    }),
  });
  // forced → picks → custom, capped at 3: the custom did not launch, so custom is null.
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "quality", "tests", "correctness"]);
  assert.equal(value.selection.custom, null);
  assert.deepEqual(
    (allBatches[0] ?? []).map((item) => item.key),
    ["quality", "tests", "correctness"],
  );
});

test("script: a custom-only selection runs WITHOUT fallback padding (source: selector)", async () => {
  const { value, allBatches } = await execScript(render(), {
    report: selectorReport({
      selected_angles: [],
      custom_angle_slug: "release-artifacts",
      custom_angle_scope: "completeness of the packaging changes",
    }),
  });
  assert.equal(value.selection.source, "selector");
  assert.deepEqual(value.selection.effective, ["plan-fidelity", "release-artifacts"]);
  assert.deepEqual(value.selection.custom, {
    slug: "release-artifacts",
    scope: "completeness of the packaging changes",
  });
  assert.deepEqual(
    (allBatches[0] ?? []).map((item) => item.key),
    ["release-artifacts"],
  );
});

// ------------------------------------------------------------- runner over the memory adapter

/** A dynamic-shape aggregate value as the rendered script returns it. */
function dynamicValue(
  effective: string[],
  laneOverrides: Record<string, { ok: boolean; error?: string; report?: unknown }> = {},
  selectionOverrides: Record<string, unknown> = {},
): unknown {
  return {
    selection: {
      source: "selector",
      effective,
      forced: [],
      custom: null,
      selector_ok: true,
      selector_error: null,
      report: selectorReport(),
      ...selectionOverrides,
    },
    lanes: effective.map((key) => {
      const override = laneOverrides[key];
      if (override === undefined) {
        return { key, ok: true, error: null, report: cleanReport(key) };
      }
      return {
        key,
        ok: override.ok,
        error: override.error ?? null,
        report: override.report ?? null,
      };
    }),
  };
}

test("runner: happy path — complete, covered = the effective selection, ONE spawn, no retry", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: dynamicValue(["plan-fidelity", "correctness", "tests"]),
    },
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "tests"]);
  assert.deepEqual(outcome.retried, []);
  assert.deepEqual(outcome.failures, []);
  assert.equal(outcome.selection?.source, "selector");
  assert.equal(adapter.calls.spawn.length, 1);
  // The dynamic spawn: reviewer schema as the workflow-level default, NO workflow-level model.
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.outputSchema, PR_REVIEW_REPORT_SCHEMA);
  assert.equal(spawn.model, undefined);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
});

test("runner: a malformed value shape is aggregate-unreadable — then ONE full dynamic re-run", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "complete", value: { nonsense: true } },
      { state: "complete", value: dynamicValue(["plan-fidelity", "quality"]) },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "quality"]);
  // The re-run's whole effective selection is what was retried; its selection supersedes.
  assert.deepEqual(outcome.retried, ["plan-fidelity", "quality"]);
  assert.equal(outcome.selection?.effective.join(","), "plan-fidelity,quality");
});

test("runner: selection drift (out-of-allowlist / missing plan-fidelity / >4 / dupes) is aggregate-unreadable", async () => {
  for (const effective of [
    ["plan-fidelity", "security"],
    ["correctness", "tests"],
    ["plan-fidelity", "correctness", "tests", "quality", "idioms"],
    ["plan-fidelity", "tests", "tests"],
  ]) {
    const adapter = createMemoryWaveAdapter({
      aggregates: [
        { state: "complete", value: dynamicValue(effective) },
        { state: "complete", value: dynamicValue(effective) },
      ],
    });
    const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
    assert.equal(outcome.complete, false, `${effective.join(",")} is upstream drift`);
    assert.equal(outcome.selection, null);
    assert.deepEqual(
      outcome.failures.map((f) => [f.key, f.reason]),
      [[null, "aggregate-unreadable"]],
    );
  }
});

test("runner: a valid custom selection round-trips (parseDynamicValue accepts it)", async () => {
  const custom = { slug: "cache-invalidation", scope: "staleness of the new cache" };
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: dynamicValue(["plan-fidelity", "correctness", "cache-invalidation"], {}, { custom }),
    },
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "cache-invalidation"]);
  assert.deepEqual(outcome.selection?.custom, custom);
});

test("runner: a malformed custom shape is aggregate-unreadable (upstream drift)", async () => {
  for (const custom of [
    "nope", // not an object
    { slug: 7, scope: "x" }, // non-string slug
    { slug: "ok-slug" }, // missing scope
    { slug: "Bad_Slug", scope: "x" }, // pattern violation
    { slug: "quality", scope: "x" }, // reserved fixed slug
    { slug: "angle-selector", scope: "x" }, // reserved lane key
    { slug: "ok-slug", scope: "" }, // empty scope
    { slug: "ok-slug", scope: "x".repeat(301) }, // over-long scope
  ]) {
    const value = dynamicValue(["plan-fidelity", "correctness"], {}, { custom });
    const adapter = createMemoryWaveAdapter({
      aggregates: [
        { state: "complete", value },
        { state: "complete", value },
      ],
    });
    const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
    assert.equal(outcome.complete, false, `${JSON.stringify(custom)} is upstream drift`);
    assert.equal(outcome.selection, null);
    assert.deepEqual(
      outcome.failures.map((f) => [f.key, f.reason]),
      [[null, "aggregate-unreadable"]],
    );
  }
});

test("runner: custom/effective mismatches are aggregate-unreadable", async () => {
  const arms: Array<{ effective: string[]; custom: unknown }> = [
    // an effective slug that is neither a fixed angle nor the custom slug
    {
      effective: ["plan-fidelity", "other-slug"],
      custom: { slug: "cache-invalidation", scope: "x" },
    },
    // a custom that claims to have launched but is absent from effective
    {
      effective: ["plan-fidelity", "correctness"],
      custom: { slug: "cache-invalidation", scope: "x" },
    },
  ];
  for (const arm of arms) {
    const value = dynamicValue(arm.effective, {}, { custom: arm.custom });
    const adapter = createMemoryWaveAdapter({
      aggregates: [
        { state: "complete", value },
        { state: "complete", value },
      ],
    });
    const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
    assert.equal(outcome.complete, false, `${arm.effective.join(",")} is upstream drift`);
    assert.equal(outcome.selection, null);
    assert.deepEqual(
      outcome.failures.map((f) => [f.key, f.reason]),
      [[null, "aggregate-unreadable"]],
    );
  }
});

test("runner: lane-level failure — the retry is a STATIC runs.all carrying exactly the failed keys", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: dynamicValue(["plan-fidelity", "correctness", "tests"], {
          tests: { ok: false, error: "lane exploded" },
        }),
      },
      {
        state: "complete",
        value: [{ key: "tests", ok: true, error: null, report: cleanReport("tests") }],
      },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, {
    reviewerModel: "test-reviewer-model",
    directive: "focus here",
    timeoutMs: 5_000,
  });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  // The retry rides the static renderer: an all-settled runs.all over exactly the failed keys,
  // byte-identical reviewer lanes (vocabulary + uniform directive suffix), the reviewer model as
  // the workflow-level default.
  assert.match(retrySpawn.workflowScript, /^const reports = await runs\.all\(/);
  const start = retrySpawn.workflowScript.indexOf("runs.all(") + "runs.all(".length;
  const end = retrySpawn.workflowScript.indexOf(");\nreturn");
  const items = JSON.parse(retrySpawn.workflowScript.slice(start, end)) as Array<{
    key: string;
    task: string;
  }>;
  assert.deepEqual(
    items.map((item) => item.key),
    ["tests"],
  );
  assert.ok(items[0]?.task.startsWith(PR_REVIEW_ANGLES.tests));
  assert.match(items[0]?.task ?? "", /focus here/);
  assert.equal(retrySpawn.model, "test-reviewer-model");
  assert.equal(retrySpawn.outputSchema, PR_REVIEW_REPORT_SCHEMA);
  // Merge semantics: first-run successes kept for non-retried keys; the retry covers the rest.
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "tests"]);
  assert.deepEqual(outcome.retried, ["tests"]);
  assert.deepEqual(outcome.failures, []);
  assert.equal(outcome.selection?.source, "selector", "the first run's selection is kept");
});

test("runner: a failed custom lane retries statically with the byte-identical task + per-lane schema", async () => {
  const custom = { slug: "cache-invalidation", scope: "staleness of the new cache" };
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: dynamicValue(
          ["plan-fidelity", "cache-invalidation"],
          { "cache-invalidation": { ok: false, error: "lane exploded" } },
          { custom },
        ),
      },
      {
        state: "complete",
        value: [
          {
            key: "cache-invalidation",
            ok: true,
            error: null,
            report: cleanReport("cache-invalidation"),
          },
        ],
      },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, {
    directive: "focus here",
    timeoutMs: 5_000,
  });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  assert.match(retrySpawn.workflowScript, /^const reports = await runs\.all\(/);
  const start = retrySpawn.workflowScript.indexOf("runs.all(") + "runs.all(".length;
  const end = retrySpawn.workflowScript.indexOf(");\nreturn");
  const items = JSON.parse(retrySpawn.workflowScript.slice(start, end)) as Array<
    Record<string, unknown>
  >;
  assert.deepEqual(
    items.map((item) => item.key),
    ["cache-invalidation"],
  );
  // Byte-identical to the in-script custom lane: the fixed template + the uniform suffix, and
  // the per-lane schema locked to the custom slug.
  assert.equal(
    items[0]?.task,
    buildCustomLaneTask(custom.slug, custom.scope) + directiveSuffix("focus here"),
  );
  assert.deepEqual(items[0]?.outputSchema, customReportSchema(custom.slug));
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "cache-invalidation"]);
  assert.deepEqual(outcome.retried, ["cache-invalidation"]);
});

test("runner: a mixed fixed+custom failure retries both in ONE static wave", async () => {
  const custom = { slug: "cache-invalidation", scope: "staleness of the new cache" };
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: dynamicValue(
          ["plan-fidelity", "correctness", "cache-invalidation"],
          {
            correctness: { ok: false, error: "first" },
            "cache-invalidation": { ok: false, error: "second" },
          },
          { custom },
        ),
      },
      {
        state: "complete",
        value: [
          { key: "correctness", ok: true, error: null, report: cleanReport("correctness") },
          {
            key: "cache-invalidation",
            ok: true,
            error: null,
            report: cleanReport("cache-invalidation"),
          },
        ],
      },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  const retrySpawn = adapter.calls.spawn[1];
  assert.ok(retrySpawn);
  const start = retrySpawn.workflowScript.indexOf("runs.all(") + "runs.all(".length;
  const end = retrySpawn.workflowScript.indexOf(");\nreturn");
  const items = JSON.parse(retrySpawn.workflowScript.slice(start, end)) as Array<
    Record<string, unknown>
  >;
  assert.deepEqual(
    items.map((item) => item.key),
    ["correctness", "cache-invalidation"],
  );
  assert.equal(items[0]?.task, PR_REVIEW_ANGLES.correctness);
  assert.equal("outputSchema" in (items[0] ?? {}), false, "fixed lanes ride the workflow default");
  assert.deepEqual(items[1]?.outputSchema, customReportSchema(custom.slug));
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.retried, ["correctness", "cache-invalidation"]);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "cache-invalidation"]);
});

test("runner: a retry that fails again survives as incomplete with the retry's failures", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: dynamicValue(["plan-fidelity", "correctness"], {
          correctness: { ok: false, error: "first" },
        }),
      },
      {
        state: "complete",
        value: [{ key: "correctness", ok: false, error: "again", report: null }],
      },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.covered, ["plan-fidelity"]);
  assert.deepEqual(outcome.retried, ["correctness"]);
  assert.deepEqual(outcome.failures, [
    { key: "correctness", reason: "lane-failed", detail: "again" },
  ]);
});

test("runner: a retryable wave-level failure re-runs the WHOLE dynamic script once (fresh selector)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "workflow script threw", value: undefined },
      {
        state: "complete",
        value: dynamicValue(
          ["plan-fidelity", "correctness", "quality"],
          {},
          {
            source: "fallback",
          },
        ),
      },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  // Both spawns are the DYNAMIC script (the selector re-runs — never the static renderer).
  for (const spawn of adapter.calls.spawn) {
    assert.match(spawn.workflowScript, /angle-selector/);
  }
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.covered, ["plan-fidelity", "correctness", "quality"]);
  assert.deepEqual(outcome.retried, ["plan-fidelity", "correctness", "quality"]);
  assert.equal(outcome.selection?.source, "fallback", "the re-run's selection supersedes");
});

test("runner: a double wave-level failure ends with the second failure and no selection", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "first", value: undefined },
      { state: "failed", error: "second", value: undefined },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(outcome.complete, false);
  assert.equal(outcome.selection, null);
  assert.deepEqual(outcome.retried, []);
  assert.deepEqual(
    outcome.failures.map((f) => [f.key, f.reason]),
    [[null, "run-failed"]],
  );
  assert.match(outcome.failures[0]?.detail ?? "", /second/);
});

test("runner: unavailable — zero spawns, NO retry, incomplete, no selection", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(adapter.calls.spawn.length, 0);
  assert.equal(outcome.complete, false);
  assert.equal(outcome.selection, null);
  assert.deepEqual(outcome.retried, []);
  assert.deepEqual(
    outcome.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
});

test("runner: pre-aborted signal — cancelled, NO retry, no spawn", async () => {
  const adapter = createMemoryWaveAdapter({});
  const controller = new AbortController();
  controller.abort();
  const outcome = await runPrReviewDynamicWave(adapter, {
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

// ------------------------------------------------------------------------- constant pins

test("REVIEW_ANGLE_SELECTOR_SCHEMA pins the seven-field closed report contract", () => {
  const s = REVIEW_ANGLE_SELECTOR_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: {
      change_profile: { type: string };
      selected_angles: { items: { enum: string[] } };
      risk_flags: { items: { type: string } };
      rationale: { type: string };
      confidence: { enum: string[] };
      custom_angle_slug: Record<string, unknown>;
      custom_angle_scope: Record<string, unknown>;
    };
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, [
    "change_profile",
    "selected_angles",
    "risk_flags",
    "rationale",
    "confidence",
    "custom_angle_slug",
    "custom_angle_scope",
  ]);
  assert.equal(s.properties.change_profile.type, "string");
  // Plan-fidelity echoes are schema-TOLERATED (the seven-slug enum) and filtered in normalization.
  assert.deepEqual(s.properties.selected_angles.items.enum, [
    "plan-fidelity",
    "correctness",
    "tests",
    "quality",
    "api-design",
    "code-organization",
    "idioms",
  ]);
  assert.equal(s.properties.risk_flags.items.type, "string");
  assert.equal(s.properties.rationale.type, "string");
  assert.deepEqual(s.properties.confidence.enum, ["high", "medium", "low"]);
  // Deliberately unconstrained plain strings (empty = no proposal): an invalid custom proposal
  // must degrade in normalization, never fail the whole selector lane.
  assert.deepEqual(s.properties.custom_angle_slug, { type: "string" });
  assert.deepEqual(s.properties.custom_angle_scope, { type: "string" });
});

test("the additional-angle vocabulary excludes plan-fidelity; the fallback is correctness+tests", () => {
  assert.deepEqual(
    [...DYNAMIC_ADDITIONAL_ANGLES],
    ["correctness", "tests", "quality", "api-design", "code-organization", "idioms"],
  );
  assert.deepEqual([...DYNAMIC_FALLBACK_ANGLES], ["correctness", "tests"]);
});

// ---------------------------------------------------------------------- the attempt receipts

test("attempts: one dynamic run — pre-launch manifest keys, dynamic agent enrichment", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: dynamicValue(["plan-fidelity", "correctness"]),
    },
    completionDetail: {
      state: "complete",
      success: true,
      children: [
        { key: "plan-fidelity", runId: "child-1" },
        { key: "angle-selector", runId: "child-2" },
        { key: "correctness", runId: "child-3" },
        { key: "custom-slug", runId: "child-4" },
      ],
    },
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.attempts, [
    {
      flow: "pr-review-dynamic",
      attempt: 1,
      // The PRE-LAUNCH manifest: the fan-out keys are unknowable before launch — observed
      // fan-out lanes appear as receipt children only.
      requestedKeys: ["plan-fidelity", "angle-selector"],
      runId: "wave-async-1",
      asyncDir: "/memory/wave-async-1",
      state: "complete",
      children: [
        { key: "plan-fidelity", runId: "child-1", agent: "perk.pr-reviewer" },
        { key: "angle-selector", runId: "child-2", agent: "perk.review-angle-selector" },
        { key: "correctness", runId: "child-3", agent: "perk.pr-reviewer" },
        // EVERY non-selector key enriches to the reviewer agent — the module owns the script,
        // so a runtime custom slug is a reviewer lane too.
        { key: "custom-slug", runId: "child-4", agent: "perk.pr-reviewer" },
      ],
    },
  ]);
});

test("attempts: [dynamic, dynamic-rerun] — both attempts keep the dynamic manifest", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      { state: "failed", error: "workflow script threw", value: undefined },
      { state: "complete", value: dynamicValue(["plan-fidelity", "quality"]) },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.deepEqual(
    outcome.attempts.map((a) => [a.attempt, a.state, a.runId, a.requestedKeys]),
    [
      [1, "failed", "wave-async-1", ["plan-fidelity", "angle-selector"]],
      [2, "complete", "wave-async-2", ["plan-fidelity", "angle-selector"]],
    ],
  );
});

test("attempts: [dynamic, static-retry] — the retry attempt carries the retried angle keys", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregates: [
      {
        state: "complete",
        value: dynamicValue(["plan-fidelity", "tests"], {
          tests: { ok: false, error: "lane exploded" },
        }),
      },
      {
        state: "complete",
        value: [{ key: "tests", ok: true, error: null, report: cleanReport("tests") }],
      },
    ],
    completionDetails: [
      { children: [{ key: "plan-fidelity", runId: "child-1" }] },
      { children: [{ key: "tests", runId: "child-2" }] },
    ],
  });
  const outcome = await runPrReviewDynamicWave(adapter, { timeoutMs: 5_000 });
  assert.equal(outcome.complete, true);
  assert.deepEqual(
    outcome.attempts.map((a) => [a.attempt, a.state, a.requestedKeys]),
    [
      [1, "complete", ["plan-fidelity", "angle-selector"]],
      [2, "complete", ["tests"]],
    ],
  );
  // The static retry's receipt children are lane-enriched by the shared runner.
  assert.deepEqual(outcome.attempts[1]?.children, [
    { key: "tests", runId: "child-2", agent: "perk.pr-reviewer" },
  ]);
});

test("attempts: unavailable — a single handle-less attempt, no retry", async () => {
  const outcome = await runPrReviewDynamicWave(createMemoryWaveAdapter({ ping: null }), {
    timeoutMs: 5_000,
  });
  assert.deepEqual(outcome.attempts, [
    {
      flow: "pr-review-dynamic",
      attempt: 1,
      requestedKeys: ["plan-fidelity", "angle-selector"],
      state: "unavailable",
      children: [],
    },
  ]);
});
