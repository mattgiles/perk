// The minimal config port (D1b): the narrow TOML-subset reader + the .perk/config.toml/local
// overlay. Pure, offline, no network. See config.ts.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { loadPerkConfig, parseCiChecks, parseTomlSubset, resolveIssueBackendId } from "./config.ts";

// Map the legacy config filenames the cases still pass to the `.perk/` target locations, so the
// seeding helper writes where the readers now look (`.perk/config.toml` / `.perk/local.toml`).
const NAME_MAP: Record<string, string> = {
  "perk.toml": "config.toml",
  "perk.local.toml": "local.toml",
};

function repoWith(files: Record<string, string>): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    writeFileSync(join(cwd, ".perk", NAME_MAP[name] ?? name), content, "utf8");
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

// --- [subagents] selection ---

test("loadPerkConfig: [subagents] absent -> empty object", () => {
  const cwd = repoWith({ "perk.toml": '[workflow]\nplan_authoring = "x"\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: parses all [subagents] agent keys", () => {
  const cwd = repoWith({
    "perk.toml":
      '[subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = "a/haiku"\n' +
      'objective-explorer = "a/haiku2"\nconflict-resolver = "a/sonnet2"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {
    "pr-reviewer": "a/sonnet",
    "review-classifier": "a/haiku",
    "objective-explorer": "a/haiku2",
    "conflict-resolver": "a/sonnet2",
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

// --- [[ci]] selection ---

test("loadPerkConfig: [[ci]] absent -> empty array", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).ci, []);
});

test("parseCiChecks: keeps order; keeps glob; ill-typed/blank rows dropped", () => {
  const checks = parseCiChecks([
    { name: "lint", command: "just lint", glob: "*.py" },
    { name: "test", command: "just test" }, // no glob
    { name: "", command: "x" }, // blank name -> dropped
    { command: "only-command" } as Record<string, string>, // missing name -> dropped
    { name: "only-name" } as Record<string, string>, // missing command -> dropped
    { name: "blankglob", command: "c", glob: "  " }, // blank glob -> omitted
  ]);
  assert.deepEqual(checks, [
    { name: "lint", command: "just lint", glob: "*.py" },
    { name: "test", command: "just test" },
    { name: "blankglob", command: "c" },
  ]);
});

test("loadPerkConfig: parses [[ci]] rows into an ordered CiCheck[]", () => {
  const cwd = repoWith({
    "perk.toml":
      '[[ci]]\nname = "lint-py"\ncommand = "just lint-py"\nglob = "*.py"\n\n' +
      '[[ci]]\nname = "test"\ncommand = "just test"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).ci, [
    { name: "lint-py", command: "just lint-py", glob: "*.py" },
    { name: "test", command: "just test" },
  ]);
});

test("loadPerkConfig: perk.local.toml [[ci]] replaces perk.toml wholesale (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[[ci]]\nname = "a"\ncommand = "A"\n',
    "perk.local.toml": '[[ci]]\nname = "b"\ncommand = "B"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).ci, [{ name: "b", command: "B" }]);
});

// --- [providers] selection ---

test("loadPerkConfig: [providers] absent -> empty selection", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).providers, {});
});

test("loadPerkConfig: parses [providers] plan/todo/askuser/footer/web strings", () => {
  const cwd = repoWith({
    "perk.toml":
      '[providers]\nplan = "tombell-plan"\ntodo = "perk-checkpoints"\naskuser = "juicesharp-ask-user"\nfooter = "pi-bar-footer"\nweb = "ollama-web-search"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).providers, {
    plan: "tombell-plan",
    todo: "perk-checkpoints",
    askuser: "juicesharp-ask-user",
    footer: "pi-bar-footer",
    web: "ollama-web-search",
  });
});

test("loadPerkConfig: perk.local.toml [providers] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[providers]\nplan = "perk-plan"\n',
    "perk.local.toml": '[providers]\nplan = "tombell-plan"\n',
  });
  assert.equal(loadPerkConfig(cwd).providers.plan, "tombell-plan");
});

// --- [trust] selection ---

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

// --- resolveIssueBackendId (fail-safe, committed-only) ------------

test("resolveIssueBackendId: absent config falls safe to github", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.equal(resolveIssueBackendId(cwd), "github");
});

test('resolveIssueBackendId: committed "linear" is returned', () => {
  const cwd = repoWith({ "perk.toml": '[issues]\nbackend = "linear"\n' });
  assert.equal(resolveIssueBackendId(cwd), "linear");
});

test("resolveIssueBackendId: committed unknown value falls safe to github", () => {
  const cwd = repoWith({ "perk.toml": '[issues]\nbackend = "jira"\n' });
  assert.equal(resolveIssueBackendId(cwd), "github");
});

test("resolveIssueBackendId: a perk.local.toml-only selection is ignored (committed-only)", () => {
  const cwd = repoWith({ "perk.local.toml": '[issues]\nbackend = "linear"\n' });
  assert.equal(resolveIssueBackendId(cwd), "github");
});

test("resolveIssueBackendId: a malformed file falls safe to github", () => {
  const cwd = repoWith({ "perk.toml": "[issues\nbackend = " });
  assert.equal(resolveIssueBackendId(cwd), "github");
});
