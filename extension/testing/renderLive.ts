// The TS side of the live cross-engine parity tier (dev-only; excluded from the published tarball
// via the `!extension/testing/` rule in package.json `files`). NOT a `.test.ts` — it is never
// picked up by `node --test "extension/**/*.test.ts"`; it is invoked once, as a subprocess, by the
// Python-owned `tests/test_prompt_parity.py`.
//
// Reads the real-template var manifest at prompts/_fixtures/live.yaml, renders every entry with the
// vendored mini-jinja renderer (the TS plane's render seam), and prints the rendered strings as a
// JSON array on stdout IN MANIFEST ORDER. The Python test renders the same manifest with jinja2 and
// asserts byte-equality per template — proving the two engines agree without any committed prose.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { parse } from "../substrate/miniYaml.ts";
import { render } from "../substrate/prompts.ts";
import { promptsDir } from "../substrate/resources.ts";

interface Case {
  template: string;
  vars: Record<string, unknown>;
}

function loadCases(): Case[] {
  const text = readFileSync(join(promptsDir(), "_fixtures", "live.yaml"), "utf8");
  return parse(text) as Case[];
}

const results = loadCases().map((c) => render(c.template, c.vars));
process.stdout.write(JSON.stringify(results));
