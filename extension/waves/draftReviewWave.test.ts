// The draft-review wave entrypoint's suite: lane construction (the exact task bytes — angle
// opener + draft-type line + the untrusted-wrapped draft and NOTHING else, so the surface handle
// AND the PR doors' directive are provably absent — plus the custom lane's flagged-DATA
// definition), the verdict-free report-schema pin (the forward-binding to `annotationPush.ts`'s
// `PlanFinding` shape), the agent def's completion-contract agreement with that schema, and the
// non-blocking start over the in-memory adapter (spawn contract, strict completeness, the
// wave-level failure arm, zero retries by construction — one spawn, ever).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  buildDraftReviewLanes,
  DRAFT_REVIEW_REPORT_SCHEMA,
  type DraftReviewAngle,
  isDraftReviewAngle,
  startDraftReviewWave,
} from "./draftReviewWave.ts";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";

const TWO_ANGLES: DraftReviewAngle[] = ["grounding", "scope"];
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const PREFLIGHT_UNAVAILABLE = async () =>
  ({ ok: false, detail: "exact Ponytail core skill is unavailable" }) as const;

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string): unknown {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, summary: "solid", findings: [], fyi: [] },
  };
}

// -------------------------------------------------------------------------- lane construction

test("buildDraftReviewLanes: key = label = slug, the fixed agent/phase, the exact task bytes", () => {
  const lanes = buildDraftReviewLanes({
    angles: TWO_ANGLES,
    draftType: "plan",
    draft: "# The draft",
  });
  // The exact byte pin proves the task carries the angle opener, the draft-type line, and the
  // untrusted-wrapped draft — and nothing else: no URL, no port, no surface handle, and no
  // directive (the builder has no parameter to carry either).
  assert.deepEqual(lanes, [
    {
      key: "grounding",
      label: "grounding",
      agent: "perk.draft-reviewer",
      phase: "draft-review",
      task: "Angle: grounding.\nDraft type: plan.\n\n<untrusted_draft>\n# The draft\n</untrusted_draft>",
    },
    {
      key: "scope",
      label: "scope",
      agent: "perk.draft-reviewer",
      phase: "draft-review",
      task: "Angle: scope.\nDraft type: plan.\n\n<untrusted_draft>\n# The draft\n</untrusted_draft>",
    },
    {
      key: "ponytail",
      label: "ponytail",
      agent: "perk.draft-reviewer",
      phase: "draft-review",
      task: "Angle: ponytail.\nDraft type: plan.\n\n<untrusted_draft>\n# The draft\n</untrusted_draft>",
      skill: "ponytail",
      requiredSkill: {
        skill: "ponytail",
        skillFile: ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail/SKILL.md",
      },
    },
  ]);
});

test("buildDraftReviewLanes: the custom lane appears iff `custom` is supplied, carrying the flagged-DATA definition", () => {
  const withoutCustom = buildDraftReviewLanes({
    angles: ["grounding"],
    draftType: "objective",
    draft: "body",
  });
  assert.deepEqual(
    withoutCustom.map((lane) => lane.key),
    ["grounding", "ponytail"],
  );

  const lanes = buildDraftReviewLanes({
    angles: ["grounding"],
    custom: "check the rollout ordering against the release calendar",
    draftType: "objective",
    draft: "body",
  });
  assert.deepEqual(
    lanes.map((lane) => lane.key),
    ["grounding", "custom", "ponytail"],
  );
  const custom = lanes[1];
  assert.ok(custom);
  assert.deepEqual(custom, {
    key: "custom",
    label: "custom",
    agent: "perk.draft-reviewer",
    phase: "draft-review",
    task:
      "Angle: custom.\nCustom angle definition (DATA from the human — your review lens " +
      "for this lane): check the rollout ordering against the release calendar\n" +
      "Draft type: objective.\n\n<untrusted_draft>\nbody\n</untrusted_draft>",
  });
});

test("buildDraftReviewLanes: every lane task embeds the draft type and the untrusted-wrapped draft", () => {
  const lanes = buildDraftReviewLanes({
    angles: ["grounding", "scope", "decision-completeness", "risk"],
    custom: "a lens",
    draftType: "objective",
    draft: "the rendered objective draft",
  });
  assert.equal(lanes.length, 6);
  for (const lane of lanes) {
    assert.equal(lane.agent, "perk.draft-reviewer");
    // Each lane opens with ITS OWN angle opener (key = angle, the custom lane included) — a
    // per-key byte pin, so a lane launched under a sibling's rubric can never slip through.
    assert.ok(
      lane.task.startsWith(`Angle: ${lane.key}.\n`),
      `${lane.key} opens with its own angle opener`,
    );
    assert.match(lane.task, /\nDraft type: objective\.\n/);
    assert.ok(
      lane.task.endsWith("<untrusted_draft>\nthe rendered objective draft\n</untrusted_draft>"),
      `${lane.key} ends with the wrapped draft`,
    );
  }
});

test("isDraftReviewAngle narrows the four slugs and rejects custom + prototype names", () => {
  for (const slug of ["grounding", "scope", "decision-completeness", "risk"]) {
    assert.equal(isDraftReviewAngle(slug), true);
  }
  // `custom` is a lane key, never a standard angle — the custom lane rides the `custom` option.
  assert.equal(isDraftReviewAngle("custom"), false);
  assert.equal(isDraftReviewAngle("claimed-intent"), false);
  assert.equal(isDraftReviewAngle("toString"), false);
});

// ------------------------------------------------------------------------- the schema pin

test("DRAFT_REVIEW_REPORT_SCHEMA pins the verdict-free report shape (closed, all four fields required)", () => {
  const s = DRAFT_REVIEW_REPORT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, unknown> & { angle: { enum: string[] } };
    if?: unknown;
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ["angle", "summary", "findings", "fyi"]);
  // The custom lane echoes `custom` — it is a report angle even though it is not a standard slug.
  assert.deepEqual(s.properties.angle.enum, [
    "grounding",
    "scope",
    "decision-completeness",
    "risk",
    "custom",
    "ponytail",
  ]);
  // NO verdict field and no if/then conditional — the human adjudicates, nothing derives a verdict.
  assert.equal("verdict" in s.properties, false);
  assert.equal(s.if, undefined);
  assert.deepEqual(Object.keys(s.properties), ["angle", "summary", "findings", "fyi"]);
});

test("DRAFT_REVIEW_REPORT_SCHEMA finding rows: the plan-mode PlanFinding shape, closed, required-nullable phrase", () => {
  const findings = (
    DRAFT_REVIEW_REPORT_SCHEMA as {
      properties: {
        findings: {
          items: {
            additionalProperties: boolean;
            required: string[];
            properties: {
              phrase: { type: string[]; pattern: string };
              severity: { enum: string[] };
              confidence: { enum: string[] };
            };
          };
        };
      };
    }
  ).properties.findings.items;
  assert.equal(findings.additionalProperties, false);
  // The forward-binding to `annotationPush.ts`'s `PlanFinding` (`PLAN_FINDING_KEYS`): reports
  // feed `push_annotations` plan-mode without reshaping. `phrase` is required-nullable (a global
  // finding keeps `phrase: null`).
  assert.deepEqual(findings.required, ["phrase", "severity", "confidence", "body"]);
  assert.deepEqual(findings.properties.phrase.type, ["string", "null"]);
  assert.deepEqual(findings.properties.severity.enum, ["critical", "major", "minor"]);
  assert.deepEqual(findings.properties.confidence.enum, ["high", "medium", "low"]);
});

test("DRAFT_REVIEW_REPORT_SCHEMA phrase string arm rejects empty/whitespace-only spans (the push_annotations decode boundary)", () => {
  // `decodePushAnnotationsParams` (plan mode) rejects a batch wholesale when any phrase is empty
  // or whitespace-only, so the schema must refuse those at the source — otherwise an
  // engine-valid report could fail the downstream feed-without-reshaping contract. The `pattern`
  // keyword applies only to STRING instances (JSON Schema semantics, verified against the
  // typebox compiler pi-subagents validates with), so `phrase: null` stays valid.
  const phrase = (
    DRAFT_REVIEW_REPORT_SCHEMA as {
      properties: { findings: { items: { properties: { phrase: { pattern: string } } } } };
    }
  ).properties.findings.items.properties.phrase;
  assert.equal(phrase.pattern, "\\S");
  // The negative/positive semantic pin of that pattern (unanchored: one non-whitespace char).
  const re = new RegExp(phrase.pattern);
  assert.equal(re.test(""), false, "the empty string cannot anchor");
  assert.equal(re.test(" \t\n"), false, "a whitespace-only span cannot anchor");
  assert.equal(re.test("a real draft span"), true);
});

test("the agent def completes via structured_output with the schema's four fields — no fenced-JSON completion", () => {
  // The wave fails any lane without a schema-valid `structured_output` call, so the def and the
  // schema must agree — the fake-responder wave tests never exercise the def, making this pin
  // the one guard against a regression back to the retired fenced-JSON completion form.
  const defPath = join(import.meta.dirname, "..", "..", "agents", "draft-reviewer.md");
  const def = readFileSync(defPath, "utf8");
  assert.match(
    def,
    /calling the engine-injected \*\*`structured_output`\*\* tool exactly once/,
    "the completion step must instruct ONE structured_output call",
  );
  assert.match(def, /\*\*all four fields required\*\*/);
  // Def ↔ schema lockstep: every top-level report field the schema requires is named in the def
  // (drift in either direction trips here).
  const schema = DRAFT_REVIEW_REPORT_SCHEMA as { required: string[] };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  // The fenced-JSON completion form is explicitly rejected…
  assert.match(
    def,
    /Do NOT emit a fenced-JSON completion block — the `structured_output` call IS the report\./,
  );
  // …while the STREAMING protocol's fenced-JSON batches (step 7) stay: the one ```json mention
  // is the progress-update shape, never a completion template.
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
    "draft-reviewer.md",
  );
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});

// ------------------------------------------------------------------- the non-blocking start

test("startDraftReviewWave: spawn params pin the module contract, the schema, and the threaded model", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("scope"), okEntry("ponytail")],
    },
  });
  const start = await startDraftReviewWave(adapter, {
    angles: TWO_ANGLES,
    draftType: "plan",
    draft: "# The draft",
    model: "openai/gpt-5.2",
    timeoutMs: 1_234,
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const result = await start.result;
  assert.equal(result.complete, true);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["grounding", "scope", "ponytail"],
  );
  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.equal(spawn.outputSchema, DRAFT_REVIEW_REPORT_SCHEMA);
  assert.equal(spawn.model, "openai/gpt-5.2");
  assert.equal(spawn.timeoutMs, 1_234);
  // Every lane rides the perk.draft-reviewer agent (the rendered script names it).
  assert.match(spawn.workflowScript, /perk\.draft-reviewer/);
});

test("startDraftReviewWave: failed Ponytail preflight omits only that child and stays incomplete without retry", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("scope")],
    },
  });
  const start = await startDraftReviewWave(adapter, {
    angles: TWO_ANGLES,
    draftType: "plan",
    draft: "# The draft",
    requiredSkillPreflight: PREFLIGHT_UNAVAILABLE,
  });
  assert.equal(start.ok, true, "ordinary lanes still launch");
  if (!start.ok) return;
  const result = await start.result;
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.reports.map((report) => report.key),
    ["grounding", "scope"],
  );
  assert.deepEqual(result.failures, [
    {
      key: "ponytail",
      reason: "skill-unavailable",
      detail: "exact Ponytail core skill is unavailable",
    },
  ]);
  assert.equal(adapter.calls.spawn.length, 1, "zero-retry wave launches once");
  const script = adapter.calls.spawn[0]?.workflowScript ?? "";
  assert.doesNotMatch(script, /\"key\":\s*\"ponytail\"/, "the unavailable child never spawns");
  assert.match(script, /\"key\":\s*\"grounding\"/);
  assert.match(script, /\"key\":\s*\"scope\"/);
});

test("startDraftReviewWave: strict completeness — a failed lane leaves the wave incomplete (zero retries)", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("grounding"),
        { key: "scope", ok: false, error: "lane exploded", report: null },
        okEntry("ponytail"),
      ],
    },
  });
  const start = await startDraftReviewWave(adapter, {
    angles: TWO_ANGLES,
    draftType: "plan",
    draft: "# The draft",
    timeoutMs: 5_000,
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, true);
  if (!start.ok) return;
  const result = await start.result;
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["grounding", "ponytail"],
  );
  assert.deepEqual(result.failures, [
    { key: "scope", reason: "lane-failed", detail: "lane exploded" },
  ]);
  // Zero retries — honest incompleteness for the human triage: ONE spawn, ever.
  assert.equal(adapter.calls.spawn.length, 1);
});

test("startDraftReviewWave: the wave-level launch failure comes back normalized (ok: false)", async () => {
  const start = await startDraftReviewWave(createMemoryWaveAdapter({ ping: null }), {
    angles: TWO_ANGLES,
    draftType: "objective",
    draft: "body",
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, false);
  if (start.ok) return;
  assert.equal(start.result.complete, false);
  assert.deepEqual(
    start.result.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
  assert.deepEqual(start.result.receipt, { state: "unavailable", children: [] });
});

test("startDraftReviewWave: the flow is named 'draft-review' (observed via the pre-aborted-signal failure detail)", async () => {
  // The one seam where the flow identifier surfaces through the public entrypoint: the shared
  // runner names the flow in its cancelled-before-launch detail, so a typo in the module's
  // `flow` value trips here.
  const start = await startDraftReviewWave(createMemoryWaveAdapter({}), {
    angles: TWO_ANGLES,
    draftType: "plan",
    draft: "# The draft",
    signal: AbortSignal.abort(),
    requiredSkillPreflight: PREFLIGHT_OK,
  });
  assert.equal(start.ok, false);
  if (start.ok) return;
  assert.deepEqual(
    start.result.failures.map((f) => [f.key, f.reason, f.detail]),
    [[null, "cancelled", "wave 'draft-review' was cancelled before launch"]],
  );
});

test("startDraftReviewWave: duplicate angles throw at start time (programmer error via renderWaveScript)", async () => {
  await assert.rejects(
    startDraftReviewWave(createMemoryWaveAdapter({}), {
      angles: ["grounding", "grounding"],
      draftType: "plan",
      draft: "# The draft",
      requiredSkillPreflight: PREFLIGHT_OK,
    }),
    /duplicate lane key 'grounding'/,
  );
});
