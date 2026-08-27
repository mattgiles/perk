// The learn-analyst agent-def ↔ report-schema lockstep pins (the adversarialReviewWave.test.ts
// pattern): the fake-responder wave tests never exercise the def, so this is the one guard
// against def/schema drift — every angle slug, every report field the schema requires, all six
// decision tokens, and the nullable `target` shape must appear in `agents/learn-analyst.md`,
// and the delivered `.pi/agents/perk/` mirror stays byte-identical (same-commit convergence).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { LEARN_ANALYST_REPORT_SCHEMA, LEARN_ANGLES } from "./analystWave.ts";
import { CAPTURED_DECISIONS } from "./capture.ts";

const DEF_PATH = join(import.meta.dirname, "..", "..", "agents", "learn-analyst.md");

test("the agent def names every schema-derived vocabulary member", () => {
  const def = readFileSync(DEF_PATH, "utf8");
  const schema = LEARN_ANALYST_REPORT_SCHEMA as {
    required: string[];
    properties: { candidates: { items: { properties: { decision: { enum: string[] } } } } };
  };
  // Every angle the schema admits is taught in the def.
  for (const angle of LEARN_ANGLES) {
    assert.match(def, new RegExp(`\\*\\*${angle}\\*\\*`), `the def must teach the angle ${angle}`);
  }
  // Def ↔ schema lockstep: every top-level report field the schema requires is named in the def
  // (drift in either direction trips here).
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  // All six decision tokens — the five captured classifications + schema-only SKIP.
  const decisions = schema.properties.candidates.items.properties.decision.enum;
  assert.deepEqual(decisions, [...CAPTURED_DECISIONS, "SKIP"]);
  for (const decision of decisions) {
    assert.match(def, new RegExp(`\`${decision}\``), `the def must teach the decision ${decision}`);
  }
  // The nullable `target` shape: the def must teach that target may be null.
  assert.match(def, /`target` is\s+a\s+routable pointer[\s\S]*?or\s+`null`/i);
  // The completion contract: the report travels only through the structured_output call.
  assert.match(def, /`structured_output`/);
});

test("the .pi/agents/perk mirror stays byte-identical to the def", () => {
  const def = readFileSync(DEF_PATH, "utf8");
  const mirror = join(import.meta.dirname, "..", "..", ".pi", "agents", "perk", "learn-analyst.md");
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});
