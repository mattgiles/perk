// The review-classifier wave entrypoint's offline suite (memory adapter): the exact schema pin
// (root-level `counts` required under a closed root — the regression the motivating transcription
// failure produced), the single-lane spec/spawn contract, the strict-completeness failure arms,
// and the def↔schema lockstep (the wave fails any lane without a schema-valid `structured_output`
// call, so the agent def and the schema must agree). The runner's own matrix lives in
// reportWave.test.ts.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import { WAVE_ACCEPTANCE } from "./transport.ts";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import {
  CLASSIFY_ASSIGNMENT_KEY,
  REVIEW_CLASSIFIER_FLOW,
  REVIEW_CLASSIFIER_REPORT_SCHEMA,
  runReviewClassifierWave,
} from "./reviewClassifierWave.ts";

/** A schema-shaped classification (the engine already validated it — shape only matters here). */
function classifierReport(): unknown {
  return {
    pr: 42,
    review_threads: [],
    discussion_comments: [],
    counts: { actionable: 0, informational: 0, praise: 0, question: 0 },
  };
}

function okAggregate(): { state: string; value: unknown } {
  return {
    state: "complete",
    value: [{ key: CLASSIFY_ASSIGNMENT_KEY, ok: true, error: null, report: classifierReport() }],
  };
}

// ------------------------------------------------------------------------- the schema pin

test("REVIEW_CLASSIFIER_REPORT_SCHEMA is pinned in FULL (every unasserted piece is a green-test regression)", () => {
  // ONE whole-schema deepEqual: the memory adapter and the fake RPC responder never apply the
  // schema, so a drifted property type/enum would otherwise leave every test green while real
  // children reject valid reports (or accept wrong shapes). The motivating failure nested
  // `counts` inside `discussion_comments` — under `additionalProperties: false` that makes
  // EVERY payload invalid; root-level `counts` required is the exact regression this pin kills.
  const classification = {
    type: "string",
    enum: ["actionable", "informational", "praise", "question"],
  };
  assert.deepEqual(REVIEW_CLASSIFIER_REPORT_SCHEMA, {
    type: "object",
    additionalProperties: false,
    required: ["pr", "review_threads", "discussion_comments", "counts"],
    properties: {
      pr: { type: "integer" },
      review_threads: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          required: ["thread_id", "classification", "path", "line", "summary"],
          properties: {
            thread_id: { type: "string" },
            classification,
            path: { type: ["string", "null"] },
            line: { type: ["integer", "null"] },
            summary: { type: "string" },
          },
        },
      },
      discussion_comments: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          required: ["comment_id", "classification", "summary"],
          properties: {
            comment_id: { type: "integer" },
            classification,
            summary: { type: "string" },
          },
        },
      },
      counts: {
        type: "object",
        additionalProperties: false,
        required: ["actionable", "informational", "praise", "question"],
        properties: {
          actionable: { type: "integer" },
          informational: { type: "integer" },
          praise: { type: "integer" },
          question: { type: "integer" },
        },
      },
    },
  });
});

// -------------------------------------------------------------------- the spec/spawn contract

test("runReviewClassifierWave: ONE lane with the fixed flow/key/agent/task, module contract + acceptance-none", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: okAggregate() });
  const result = await runReviewClassifierWave(adapter, {
    model: "anthropic/claude-haiku-4-5",
    timeoutMs: 1_234,
  });
  assert.equal(result.complete, true);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    [CLASSIFY_ASSIGNMENT_KEY],
  );
  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn !== undefined);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.deepEqual(spawn.acceptance, WAVE_ACCEPTANCE);
  assert.equal(spawn.outputSchema, REVIEW_CLASSIFIER_REPORT_SCHEMA);
  assert.equal(spawn.model, "anthropic/claude-haiku-4-5");
  assert.equal(spawn.timeoutMs, 1_234);
  // The single lane, byte-pinned: the fixed code-owned task carries NOTHING model-relayed
  // (the child fetches the feedback itself via `perk pr feedback --json`).
  const items = waveScriptItems(spawn.workflowScript);
  assert.deepEqual(items, [
    {
      key: "classify",
      agent: "perk.review-classifier",
      task: "Fetch + classify the review feedback on this plan's PR.",
      label: "classify",
      phase: "address",
    },
  ]);
  assert.equal(REVIEW_CLASSIFIER_FLOW, "review-classifier");
});

test("runReviewClassifierWave: no configured model → no model key on the spawn", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: okAggregate() });
  await runReviewClassifierWave(adapter);
  assert.ok(adapter.calls.spawn[0] !== undefined && !("model" in adapter.calls.spawn[0]));
});

// ------------------------------------------------------------------------ the failure arms

test("runReviewClassifierWave: a failed lane is incomplete under strict (no retry — one spawn, ever)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: CLASSIFY_ASSIGNMENT_KEY, ok: false, error: "perk pr feedback failed", report: null },
      ],
    },
  });
  const result = await runReviewClassifierWave(adapter);
  assert.equal(result.complete, false);
  assert.deepEqual(result.reports, []);
  assert.deepEqual(result.failures, [
    { key: CLASSIFY_ASSIGNMENT_KEY, reason: "lane-failed", detail: "perk pr feedback failed" },
  ]);
  assert.equal(adapter.calls.spawn.length, 1);
});

test("runReviewClassifierWave: an unavailable adapter degrades loudly (wave-level failure)", async () => {
  const result = await runReviewClassifierWave(createMemoryWaveAdapter({ ping: null }));
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
  assert.deepEqual(result.receipt, { state: "unavailable", children: [] });
});

// --------------------------------------------------------------------- def↔schema lockstep

test("the agent def completes via structured_output with the schema's root fields — no fenced-JSON completion", () => {
  // The wave fails any lane without a schema-valid `structured_output` call, so the def and the
  // schema must agree — the memory-adapter tests never exercise the def, making this pin the
  // guard against drift in either direction.
  const defPath = join(import.meta.dirname, "..", "..", "agents", "review-classifier.md");
  const def = readFileSync(defPath, "utf8");
  assert.match(
    def,
    /call to the engine-injected \*\*`structured_output`\*\* tool/,
    "the completion step must instruct a structured_output call",
  );
  const schema = REVIEW_CLASSIFIER_REPORT_SCHEMA as { required: string[] };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  // The fenced-JSON completion form is explicitly rejected — the report travels only through
  // the tool call.
  assert.match(def, /never print a\s+fenced JSON block/);
  assert.doesNotMatch(def, /```json/, "no fenced-JSON completion template in the def");
  // The delivered `.pi/agents/perk/` mirror stays byte-identical (the same-commit convergence).
  const mirror = join(
    import.meta.dirname,
    "..",
    "..",
    ".pi",
    "agents",
    "perk",
    "review-classifier.md",
  );
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});
