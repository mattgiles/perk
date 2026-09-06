// The session-auditor agent-def ↔ verdict-schema lockstep pins (the analystDef.test.ts
// sibling): the fake-responder wave tests never exercise the def, so this is the one guard
// against def/schema drift — the frontmatter contract, the ONE-`structured_output` completion
// contract, every schema-required report field, the no-fenced-JSON rejection, and the judgment
// framing the fold relies on. (No `.pi/agents/perk/` mirror pin — the perk-dev def is
// repo-local, never delivered by `perk init`.)

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { AUDIT_VERDICT_SCHEMA } from "./audit.ts";

const DEF_PATH = join(
  import.meta.dirname,
  "..",
  "..",
  ".pi",
  "agents",
  "perk-dev",
  "session-auditor.md",
);

test("the session-auditor def completes via structured_output with the schema's fields — no fenced-JSON completion", () => {
  // The wave fails any lane without a schema-valid structured_output call, so the repo-local
  // def and AUDIT_VERDICT_SCHEMA must agree.
  const def = readFileSync(DEF_PATH, "utf8");
  // Frontmatter: the runtime name perk-dev.session-auditor + the read-only tool surface.
  assert.match(def, /^name: session-auditor$/m);
  assert.match(def, /^package: perk-dev$/m);
  assert.match(def, /^model: openai\/gpt-5\.6-luna$/m);
  assert.match(def, /^ {2}- openai\/gpt-5\.6-terra$/m);
  assert.match(def, /^tools: read, grep, find, ls, bash$/m);
  assert.match(def, /^systemPromptMode: replace$/m);
  assert.match(def, /^async: true$/m);
  assert.match(def, /^inheritGlobalContext: false$/m);
  assert.doesNotMatch(def, /^(extensions|subagentOnlyExtensions):/m);
  assert.match(def, /^inheritProjectContext: false$/m);
  assert.match(def, /^inheritSkills: false$/m);
  // The completion contract.
  assert.match(
    def,
    /calling the\s+engine-injected \*\*`structured_output`\*\* tool exactly once/,
    "the completion step must instruct ONE structured_output call",
  );
  const schema = AUDIT_VERDICT_SCHEMA as { required: string[] };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  assert.match(
    def,
    /Do NOT emit a fenced-JSON completion block — the\s+`structured_output` call IS the report\./,
  );
  assert.doesNotMatch(def, /```json/, "no fenced-JSON completion form anywhere in the def");
  // The judgment framing the fold relies on.
  assert.match(def, /lead, not a proof/);
  assert.match(def, /\*\*REQUIRES citations\*\*/);
  assert.match(def, /earned, not defaulted/);
});
