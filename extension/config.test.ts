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
  assert.equal(t.tables[""]?.top, "root");
  assert.equal(t.tables.workflow?.plan_authoring, "be concise");
});

test("parseTomlSubset: multi-line basic string", () => {
  const t = parseTomlSubset(
    ["[workflow]", 'plan_authoring = """', "line one", "line two", '"""'].join("\n"),
  );
  assert.equal(t.tables.workflow?.plan_authoring, "line one\nline two");
});

test("parseTomlSubset: ignores non-string scalars (subset only)", () => {
  const t = parseTomlSubset(["[workflow]", "count = 3", "flag = true"].join("\n"));
  assert.equal(t.tables.workflow?.count, undefined);
  assert.equal(t.tables.workflow?.flag, undefined);
});

test("parseTomlSubset: [[bindings]] array-of-tables -> arrays.bindings", () => {
  const t = parseTomlSubset(
    [
      "[[bindings]]",
      'trigger = "stage:plan"',
      'skill = "house-style"',
      'mode = "transclude"',
      "",
      "[[bindings]]",
      'trigger = "command:learn-docs"',
      'skill = "docs"',
      'mode = "nudge"',
    ].join("\n"),
  );
  assert.deepEqual(t.arrays.bindings, [
    { trigger: "stage:plan", skill: "house-style", mode: "transclude" },
    { trigger: "command:learn-docs", skill: "docs", mode: "nudge" },
  ]);
});

test("loadPerkConfig: parses [[bindings]] into config.bindings", () => {
  const cwd = repoWith({
    "perk.toml":
      '[[bindings]]\ntrigger = "stage:plan"\nskill = "house-style"\nmode = "transclude"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).bindings, [
    {
      trigger: "stage:plan",
      kind: "stage",
      targetId: "plan",
      skill: "house-style",
      mode: "transclude",
    },
  ]);
});

test("loadPerkConfig: local [[bindings]] replaces the committed array (whole-array)", () => {
  const cwd = repoWith({
    "perk.toml": '[[bindings]]\ntrigger = "stage:plan"\nskill = "committed"\nmode = "nudge"\n',
    "perk.local.toml":
      '[[bindings]]\ntrigger = "stage:implement"\nskill = "local"\nmode = "nudge"\n',
  });
  assert.deepEqual(
    loadPerkConfig(cwd).bindings.map((b) => [b.trigger, b.skill]),
    [["stage:implement", "local"]],
  );
});

test("loadPerkConfig: no [[bindings]] -> empty bindings", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).bindings, []);
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

// --- [subagents] selection (#196) ---

test("loadPerkConfig: [subagents] absent -> empty object", () => {
  const cwd = repoWith({ "perk.toml": '[workflow]\nplan_authoring = "x"\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: parses all three [subagents] agent keys", () => {
  const cwd = repoWith({
    "perk.toml":
      '[subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = "a/haiku"\n' +
      'objective-explorer = "a/haiku2"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {
    "pr-reviewer": "a/sonnet",
    "review-classifier": "a/haiku",
    "objective-explorer": "a/haiku2",
  });
});

test("loadPerkConfig: blank [subagents] value is treated as absent", () => {
  const cwd = repoWith({ "perk.toml": '[subagents]\npr-reviewer = "   "\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: unknown [subagents] agent key is ignored", () => {
  const cwd = repoWith({ "perk.toml": '[subagents]\nbogus = "a/x"\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: perk.local.toml [subagents] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[subagents]\npr-reviewer = "base/model"\n',
    "perk.local.toml": '[subagents]\npr-reviewer = "local/model"\n',
  });
  assert.equal(loadPerkConfig(cwd).subagents["pr-reviewer"], "local/model");
});

// --- [providers] selection (Node 2.1) ---

test("loadPerkConfig: [providers] absent -> empty selection", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).providers, {});
});

test("loadPerkConfig: parses [providers] plan/todo strings", () => {
  const cwd = repoWith({
    "perk.toml": '[providers]\nplan = "tombell-plan"\ntodo = "perk-checkpoints"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).providers, {
    plan: "tombell-plan",
    todo: "perk-checkpoints",
  });
});

test("loadPerkConfig: perk.local.toml [providers] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[providers]\nplan = "perk-plan"\n',
    "perk.local.toml": '[providers]\nplan = "tombell-plan"\n',
  });
  assert.equal(loadPerkConfig(cwd).providers.plan, "tombell-plan");
});

// --- [trust] selection (#214) ---

test("loadPerkConfig: [trust] absent -> empty selection", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).trust, {});
});

test('loadPerkConfig: parses [trust] ci = "true"', () => {
  const cwd = repoWith({ "perk.toml": '[trust]\nci = "true"\n' });
  assert.equal(loadPerkConfig(cwd).trust.ci, true);
});

test('loadPerkConfig: [trust] ci = "false" / blank is treated as absent', () => {
  assert.deepEqual(loadPerkConfig(repoWith({ "perk.toml": '[trust]\nci = "false"\n' })).trust, {});
  assert.deepEqual(loadPerkConfig(repoWith({ "perk.toml": '[trust]\nci = "  "\n' })).trust, {});
});

test("loadPerkConfig: perk.local.toml [trust] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[trust]\nci = "false"\n',
    "perk.local.toml": '[trust]\nci = "true"\n',
  });
  assert.equal(loadPerkConfig(cwd).trust.ci, true);
});
