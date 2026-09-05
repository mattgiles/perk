// The adversarial-review wave entrypoint's suite: lane construction (the exact task line — angle
// + PR + worktree and NOTHING else, so the surface handle is provably absent — plus the uniform
// directive suffix), the verdict-free report-schema pin, the agent def's completion-contract
// agreement with that schema, and the non-blocking start over the in-memory adapter (spawn
// contract, strict completeness, the wave-level failure arm, zero retries by construction —
// one spawn, ever).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { Compile } from "typebox/compile";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import {
  ADVERSARIAL_REVIEW_ANGLES,
  ADVERSARIAL_REVIEW_REPORT_SCHEMA,
  type AdversarialReviewAngle,
  buildAdversarialReviewAssignments,
  isAdversarialReviewAngle,
  startAdversarialReviewWave,
} from "./adversarialReviewWave.ts";
import { reportWaveOver } from "./reportWave.ts";

const TWO_ANGLES: AdversarialReviewAngle[] = ["claimed-intent", "correctness"];
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const PREFLIGHT_UNAVAILABLE = async () =>
  ({ ok: false, detail: "exact Ponytail review skill is unavailable" }) as const;

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string): unknown {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, summary: "solid", findings: [], fyi: [], streamed: false },
  };
}

// -------------------------------------------------------------------------- lane construction

test("buildAdversarialReviewAssignments: key = label = slug, the fixed agent/phase, the exact task line", () => {
  const lanes = buildAdversarialReviewAssignments({
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
  });
  // The exact byte pin proves the task names the angle, the PR, and the worktree — and nothing
  // else: no URL, no port, no surface handle (the builder has no parameter to carry one).
  assert.deepEqual(lanes, [
    {
      key: "claimed-intent",
      label: "claimed-intent",
      agent: "perk.adversarial-reviewer",
      phase: "review",
      task: "Angle: claimed-intent. Review PR #42 at /abs/wt.",
    },
    {
      key: "correctness",
      label: "correctness",
      agent: "perk.adversarial-reviewer",
      phase: "review",
      task: "Angle: correctness. Review PR #42 at /abs/wt.",
    },
    {
      key: "ponytail",
      label: "ponytail",
      agent: "perk.adversarial-reviewer",
      phase: "review",
      task: "Angle: ponytail. Review PR #42 at /abs/wt.",
      skill: "ponytail-review",
      requiredSkill: {
        skill: "ponytail-review",
        skillFile: ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail-review/SKILL.md",
      },
    },
  ]);
});

test("buildAdversarialReviewAssignments stack mode: per-key task pins + the no-stack byte-identity", () => {
  // The stack discriminator swaps ONLY the subject sentence — the exact per-key pin proves the
  // task names the stack top, the combined-diff framing, and the --stack context fetch, and
  // still carries no URL/surface handle.
  const lanes = buildAdversarialReviewAssignments({
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
    stack: true,
  });
  const subject =
    "Review the PR stack topped by PR #42 (combined diff) at /abs/wt. " +
    "Fetch context with `perk pr review-context --pr 42 --stack`.";
  assert.deepEqual(
    lanes.map((lane) => [lane.key, lane.task]),
    [
      ["claimed-intent", `Angle: claimed-intent. ${subject}`],
      ["correctness", `Angle: correctness. ${subject}`],
      ["ponytail", `Angle: ponytail. ${subject}`],
    ],
  );
  // Without stack (absent OR false), tasks are byte-identical to the single-PR form.
  const plain = buildAdversarialReviewAssignments({
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
  });
  const explicitFalse = buildAdversarialReviewAssignments({
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
    stack: false,
  });
  assert.deepEqual(explicitFalse, plain);
  assert.equal(plain[0]?.task, "Angle: claimed-intent. Review PR #42 at /abs/wt.");
});

test("buildAdversarialReviewAssignments appends ONE uniform directive suffix to EVERY lane task when set", () => {
  const lanes = buildAdversarialReviewAssignments({
    angles: ["claimed-intent", "tests", "quality"],
    pr: 7,
    worktree: "/abs/wt",
    directive: "focus on the CI workflow edits",
  });
  assert.equal(lanes.length, 4);
  for (const lane of lanes) {
    const angle = lane.key;
    const opener =
      angle === "ponytail"
        ? "Angle: ponytail."
        : ADVERSARIAL_REVIEW_ANGLES[angle as AdversarialReviewAngle];
    const base = `${opener} Review PR #7 at /abs/wt.`;
    assert.ok(lane.task.startsWith(base), `${lane.key} keeps the vocabulary`);
    assert.match(lane.task, /Operator focus \(DATA from the human/);
    assert.match(lane.task, /emphasis within your assigned angle only/);
    assert.match(lane.task, /focus on the CI workflow edits/);
  }
  // The suffix is identical across lanes (one uniform DATA note, never per-lane re-scoping).
  const suffixes = lanes.map((lane) => {
    const angle = lane.key;
    const opener =
      angle === "ponytail"
        ? "Angle: ponytail."
        : ADVERSARIAL_REVIEW_ANGLES[angle as AdversarialReviewAngle];
    return lane.task.slice(`${opener} Review PR #7 at /abs/wt.`.length);
  });
  assert.equal(new Set(suffixes).size, 1);
});

test("isAdversarialReviewAngle narrows the four slugs and rejects prototype names", () => {
  for (const slug of ["claimed-intent", "correctness", "tests", "quality"]) {
    assert.equal(isAdversarialReviewAngle(slug), true);
  }
  assert.equal(isAdversarialReviewAngle("plan-fidelity"), false);
  assert.equal(isAdversarialReviewAngle("security"), false);
  assert.equal(isAdversarialReviewAngle("toString"), false);
});

// ------------------------------------------------------------------------- the schema pin

test("ADVERSARIAL_REVIEW_REPORT_SCHEMA pins the verdict-free report shape (closed, all fields required)", () => {
  const s = ADVERSARIAL_REVIEW_REPORT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, unknown> & { angle: { enum: string[] } };
    if?: unknown;
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ["angle", "summary", "findings", "fyi", "streamed"]);
  assert.deepEqual(s.properties.angle.enum, [
    "claimed-intent",
    "correctness",
    "tests",
    "quality",
    "ponytail",
  ]);
  // NO verdict field and no if/then conditional — the human triages, nothing derives a verdict.
  assert.equal("verdict" in s.properties, false);
  assert.equal(s.if, undefined);
  assert.deepEqual(Object.keys(s.properties), ["angle", "streamed", "summary", "findings", "fyi"]);
});

test("ADVERSARIAL_REVIEW_REPORT_SCHEMA finding rows: closed, required-nullable line, optional side, the triage enums", () => {
  const findings = (
    ADVERSARIAL_REVIEW_REPORT_SCHEMA as {
      properties: {
        findings: {
          items: {
            additionalProperties: boolean;
            required: string[];
            properties: {
              line: { type: string[] };
              side: { enum: string[] };
              severity: { enum: string[] };
              confidence: { enum: string[] };
            };
          };
        };
      };
    }
  ).properties.findings.items;
  assert.equal(findings.additionalProperties, false);
  // `side` is deliberately NOT required (omitted ⇒ RIGHT); `line` is required-nullable (the
  // unanchorable-finding arm), the same expression LEARN_ANALYST_REPORT_SCHEMA.target uses.
  assert.deepEqual(findings.required, ["path", "line", "severity", "confidence", "body"]);
  assert.deepEqual(findings.properties.line.type, ["integer", "null"]);
  assert.deepEqual(findings.properties.side.enum, ["LEFT", "RIGHT"]);
  assert.deepEqual(findings.properties.severity.enum, ["critical", "major", "minor"]);
  assert.deepEqual(findings.properties.confidence.enum, ["high", "medium", "low"]);
});

test("the agent def completes via structured_output with the schema's required fields — no fenced-JSON completion", () => {
  // The wave fails any lane without a schema-valid `structured_output` call, so the def and the
  // schema must agree — the fake-responder wave tests never exercise the def, making this pin
  // the one guard against a regression back to the retired fenced-JSON completion form.
  const defPath = join(import.meta.dirname, "..", "..", "agents", "adversarial-reviewer.md");
  const def = readFileSync(defPath, "utf8");
  assert.match(
    def,
    /calling the engine-injected \*\*`structured_output`\*\* tool exactly once/,
    "the completion step must instruct ONE structured_output call",
  );
  assert.match(def, /\*\*required fields:/);
  assert.match(def, /send no empty batch and return `streamed: false`/);
  assert.match(def, /absent or streaming fails/);
  assert.match(def, /Put a short factual explanation in `fyi`/);
  assert.doesNotMatch(def, /skip streaming silently/);
  // Def ↔ schema lockstep: every top-level report field the schema requires is named in the def
  // (drift in either direction trips here).
  const schema = ADVERSARIAL_REVIEW_REPORT_SCHEMA as { required: string[] };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  // The stack-mode paragraph stays in lockstep with the lane task's --stack pointer: the def
  // must teach the --stack context fetch and combined-diff-coordinate reporting.
  assert.match(def, /perk pr review-context --pr <n> --stack --json/);
  assert.match(def, /\*\*combined-diff coordinates\*\*/);
  assert.match(def, /routing findings to individual member PRs is the\s+parent's job/i);
  // The retired fenced-JSON completion form is explicitly rejected…
  assert.match(
    def,
    /Do NOT emit a fenced-JSON completion block — the `structured_output` call IS the report\./,
  );
  assert.doesNotMatch(def, /emit a fenced JSON block and stop/i, "the old step-8 form is gone");
  // …while the STREAMING protocol's fenced-JSON batches (step 7) stay: the one remaining
  // ```json mention is the progress-update shape, never a completion template.
  const fencedJsonMentions = def.match(/```json/g) ?? [];
  assert.equal(fencedJsonMentions.length, 1, "only the streamed-batch shape mentions ```json");
  assert.match(def, /contact_supervisor\(\{reason: "progress_update", message\}\)/);
  // The delivered `.pi/agents/perk/` mirror stays byte-identical (the same-commit convergence).
  const mirror = join(
    import.meta.dirname,
    "..",
    "..",
    ".pi",
    "agents",
    "perk",
    "adversarial-reviewer.md",
  );
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});

test("streamed is a required boolean, not a truthy default", () => {
  const validator = Compile(ADVERSARIAL_REVIEW_REPORT_SCHEMA);
  const base = { angle: "claimed-intent", summary: "solid", findings: [], fyi: [] };
  for (const streamed of [true, false]) {
    assert.equal(validator.Check({ ...base, streamed }), true);
  }
  assert.equal(validator.Check(base), false);
  for (const streamed of [null, "false", 0, 1]) {
    assert.equal(validator.Check({ ...base, streamed }), false);
  }
});

// ------------------------------------------------------------------- the non-blocking start

test("startAdversarialReviewWave: spawn params pin the module contract, the schema, and the threaded model", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const start = await startAdversarialReviewWave(wave, {
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
    model: "anthropic/claude-opus-4",
    timeoutMs: 1_234,
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.equal(result.complete, true);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["claimed-intent", "correctness", "ponytail"],
  );
  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.equal(spawn.outputSchema, ADVERSARIAL_REVIEW_REPORT_SCHEMA);
  assert.equal(spawn.model, "anthropic/claude-opus-4");
  assert.equal(spawn.timeoutMs, 1_234);
});

test("startAdversarialReviewWave: failed Ponytail preflight omits only that child and stays incomplete without retry", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness")],
    },
  });
  const wave = reportWaveOver(adapter);
  const start = await startAdversarialReviewWave(wave, {
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
    requiredSkillPreflight: PREFLIGHT_UNAVAILABLE,
  });
  assert.equal(start.ok, true, "ordinary lanes still launch");
  if (!start.ok) return;
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.reports.map((report) => report.key),
    ["claimed-intent", "correctness"],
  );
  assert.deepEqual(result.failures, [
    {
      key: "ponytail",
      reason: "skill-unavailable",
      detail: "exact Ponytail review skill is unavailable",
    },
  ]);
  assert.equal(adapter.calls.spawn.length, 1, "zero-retry wave launches once");
  const script = adapter.calls.spawn[0]?.workflowScript ?? "";
  assert.doesNotMatch(script, /"key":\s*"ponytail"/, "the unavailable child never spawns");
  assert.match(script, /"key":\s*"claimed-intent"/);
  assert.match(script, /"key":\s*"correctness"/);
});

test("startAdversarialReviewWave: strict completeness — a failed lane leaves the wave incomplete (zero retries)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("claimed-intent"),
        { key: "correctness", ok: false, error: "lane exploded", report: null },
        okEntry("ponytail"),
      ],
    },
  });
  const wave = reportWaveOver(adapter);
  const start = await startAdversarialReviewWave(wave, {
    angles: TWO_ANGLES,
    pr: 42,
    worktree: "/abs/wt",
    timeoutMs: 5_000,
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const collected = await wave.collect(start.ref);
  assert.equal(collected.kind, "settled");
  if (collected.kind !== "settled") return;
  const result = collected.result;
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["claimed-intent", "ponytail"],
  );
  assert.deepEqual(result.failures, [
    { key: "correctness", reason: "lane-failed", detail: "lane exploded" },
  ]);
  // Zero retries — honest incompleteness for the human triage: ONE spawn, ever.
  assert.equal(adapter.calls.spawn.length, 1);
});

test("startAdversarialReviewWave: the wave-level launch failure comes back normalized (ok: false)", async () => {
  const start = await startAdversarialReviewWave(
    reportWaveOver(createMemoryWaveAdapter({ ping: null })),
    {
      angles: TWO_ANGLES,
      pr: 42,
      worktree: "/abs/wt",
      requiredSkillPreflight: PREFLIGHT_OK,
    },
  );
  assert.equal(start.ok, false);
  if (start.ok) return;
  assert.equal(start.result.complete, false);
  assert.deepEqual(
    start.result.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
  assert.deepEqual(start.result.receipt, { state: "unavailable", children: [] });
});

test("startAdversarialReviewWave: duplicate angles throw at start time (programmer error via renderWaveScript)", async () => {
  await assert.rejects(
    startAdversarialReviewWave(reportWaveOver(createMemoryWaveAdapter({})), {
      angles: ["claimed-intent", "claimed-intent"],
      pr: 42,
      worktree: "/abs/wt",
      requiredSkillPreflight: PREFLIGHT_OK,
    }),
    /duplicate lane key 'claimed-intent'/,
  );
});
