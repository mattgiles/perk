// P2.T2a — the minimal config port (D1b): the narrow TOML-subset reader + the perk.toml/local
// overlay. Pure, offline, no network. See config.ts.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { loadPerkConfig, parseTomlSubset } from "./config.ts";

function repoWith(files: Record<string, string>): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    writeFileSync(join(cwd, ".pi", name), content, "utf8");
  }
  return cwd;
}

test("parseTomlSubset: sections, basic strings, comments", () => {
  const t = parseTomlSubset(
    [
      "# a comment",
      'top = "root"',
      "",
      "[workflow]",
      'plan_authoring = "be concise"  # inline',
    ].join("\n"),
  );
  assert.equal(t[""]?.top, "root");
  assert.equal(t.workflow?.plan_authoring, "be concise");
});

test("parseTomlSubset: multi-line basic string", () => {
  const t = parseTomlSubset(
    ["[workflow]", 'plan_authoring = """', "line one", "line two", '"""'].join("\n"),
  );
  assert.equal(t.workflow?.plan_authoring, "line one\nline two");
});

test("parseTomlSubset: ignores non-string scalars (subset only)", () => {
  const t = parseTomlSubset(["[workflow]", "count = 3", "flag = true"].join("\n"));
  assert.equal(t.workflow?.count, undefined);
  assert.equal(t.workflow?.flag, undefined);
});

test("loadPerkConfig: no files -> empty config", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.equal(loadPerkConfig(cwd).planAuthoring, undefined);
});

test("loadPerkConfig: reads the [workflow] plan-authoring addendum", () => {
  const cwd = repoWith({
    "perk.toml": '[workflow]\nplan_authoring = "Always cite a file path."\n',
  });
  assert.equal(loadPerkConfig(cwd).planAuthoring, "Always cite a file path.");
});

test("loadPerkConfig: perk.local.toml overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[workflow]\nplan_authoring = "base"\n',
    "perk.local.toml": '[workflow]\nplan_authoring = "local override"\n',
  });
  assert.equal(loadPerkConfig(cwd).planAuthoring, "local override");
});

test("loadPerkConfig: blank/whitespace addendum is treated as absent", () => {
  const cwd = repoWith({ "perk.toml": '[workflow]\nplan_authoring = "   "\n' });
  assert.equal(loadPerkConfig(cwd).planAuthoring, undefined);
});
