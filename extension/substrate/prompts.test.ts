import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { parse } from "./miniYaml.ts";
import { render } from "./prompts.ts";
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
