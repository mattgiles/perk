import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { parse } from "./miniYaml.ts";
import { planReadInstruction, render } from "./prompts.ts";
import { promptsDir } from "./resources.ts";

interface Case {
  template: string;
  vars: Record<string, unknown>;
  golden: string;
}

function loadCases(): Case[] {
  const text = readFileSync(join(promptsDir(), "_fixtures", "cases.yaml"), "utf8");
  return parse(text) as Case[];
}

test("golden parity: vendored mini-jinja render == the committed jinja2 golden bytes", () => {
  const cases = loadCases();
  assert.ok(cases.length > 0, "cases.yaml must list at least one case");
  for (const c of cases) {
    const out = render(c.template, c.vars);
    const golden = readFileSync(join(promptsDir(), c.golden), "utf8");
    assert.equal(out, golden, `golden mismatch for ${c.template}`);
  }
});

test("throwOnUndefined: a missing required var throws", () => {
  assert.throws(() => render("_fixtures/templates/hello.md", {}));
});

test("planReadInstruction: three arms (github / linear / fallback)", () => {
  assert.equal(planReadInstruction("github", "42", "https://x/42"), "gh issue view 42 --comments");
  const linear = planReadInstruction("linear", "uuid-1", "https://linear.app/x/ENG-1");
  assert.ok(linear.includes("use the `linear_get_issue` tool (id `uuid-1`)"));
  assert.ok(linear.includes("then `linear_list_comments`"));
  assert.ok(linear.includes("the plan body is the first comment"));
  assert.ok(
    linear.includes("if the linear tools are unavailable, open https://linear.app/x/ENG-1"),
  );
  assert.equal(planReadInstruction("gitlab", "9", "https://gl/x"), "open https://gl/x");
});
