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

test("parseTomlSubset: native booleans and numbers", () => {
  const t = parseTomlSubset(
    [
      "[ci]",
      "trusted = true",
      "off = false",
      "[compaction]",
      "reserve_tokens = 16_384",
      "objective_threshold = 0.8",
      "count = 3",
      "exp = 1e3",
    ].join("\n"),
  );
  assert.equal(t.tables.ci?.trusted, true);
  assert.equal(t.tables.ci?.off, false);
  assert.equal(t.tables.compaction?.reserve_tokens, 16384);
  assert.equal(t.tables.compaction?.objective_threshold, 0.8);
  assert.equal(t.tables.compaction?.count, 3);
  assert.equal(t.tables.compaction?.exp, 1000);
});

test("parseTomlSubset: inline comment after an unquoted scalar", () => {
  const t = parseTomlSubset(["[ci]", "trusted = true  # green-lit", "n = 2 # two"].join("\n"));
  assert.equal(t.tables.ci?.trusted, true);
  assert.equal(t.tables.ci?.n, 2);
});

test("parseTomlSubset: non-scalar values are still ignored (subset only)", () => {
  const t = parseTomlSubset(
    ["[workflow]", "date = 2026-07-07", 'list = ["a", "b"]', "inline = { a = 1 }"].join("\n"),
  );
  assert.equal(t.tables.workflow?.date, undefined);
  assert.equal(t.tables.workflow?.list, undefined);
  assert.equal(t.tables.workflow?.inline, undefined);
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

// --- [models.subagents] selection ---

test("loadPerkConfig: [models.subagents] absent -> empty object", () => {
  const cwd = repoWith({ "perk.toml": '[workflow]\nplan_authoring = "x"\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: parses all [models.subagents] agent keys", () => {
  const cwd = repoWith({
    "perk.toml":
      '[models.subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = "a/haiku"\n' +
      'objective-explorer = "a/haiku2"\nconflict-resolver = "a/sonnet2"\n' +
      'learn-analyst = "a/analyst"\nguest-reviewer = "a/guest"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {
    "pr-reviewer": "a/sonnet",
    "review-classifier": "a/haiku",
    "objective-explorer": "a/haiku2",
    "conflict-resolver": "a/sonnet2",
    "learn-analyst": "a/analyst",
    "guest-reviewer": "a/guest",
  });
});

test("loadPerkConfig: blank [models.subagents] value is treated as absent", () => {
  const cwd = repoWith({ "perk.toml": '[models.subagents]\npr-reviewer = "   "\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: unknown [models.subagents] agent key is ignored", () => {
  const cwd = repoWith({ "perk.toml": '[models.subagents]\nbogus = "a/x"\n' });
  assert.deepEqual(loadPerkConfig(cwd).subagents, {});
});

test("loadPerkConfig: perk.local.toml [models.subagents] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[models.subagents]\npr-reviewer = "base/model"\n',
    "perk.local.toml": '[models.subagents]\npr-reviewer = "local/model"\n',
  });
  assert.equal(loadPerkConfig(cwd).subagents["pr-reviewer"], "local/model");
});

// --- [ci] selection ---

test("loadPerkConfig: [ci] absent -> untrusted, empty checks", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).ci, { trusted: false, checks: [] });
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

test("loadPerkConfig: parses [[ci.checks]] rows into an ordered CiCheck[]", () => {
  const cwd = repoWith({
    "perk.toml":
      '[[ci.checks]]\nname = "lint-py"\ncommand = "just lint-py"\nglob = "*.py"\n\n' +
      '[[ci.checks]]\nname = "test"\ncommand = "just test"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).ci.checks, [
    { name: "lint-py", command: "just lint-py", glob: "*.py" },
    { name: "test", command: "just test" },
  ]);
});

test("loadPerkConfig: perk.local.toml [[ci.checks]] replaces perk.toml wholesale (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[[ci.checks]]\nname = "a"\ncommand = "A"\n',
    "perk.local.toml": '[[ci.checks]]\nname = "b"\ncommand = "B"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).ci.checks, [{ name: "b", command: "B" }]);
});

test("loadPerkConfig: [ci] trusted = true (native boolean)", () => {
  const cwd = repoWith({ "perk.toml": "[ci]\ntrusted = true\n" });
  assert.equal(loadPerkConfig(cwd).ci.trusted, true);
});

test('loadPerkConfig: [ci] trusted = "true" (string) is NOT trusted (native-bool only)', () => {
  const cwd = repoWith({ "perk.toml": '[ci]\ntrusted = "true"\n' });
  assert.equal(loadPerkConfig(cwd).ci.trusted, false);
});

test("loadPerkConfig: [ci] trusted = false / absent is untrusted", () => {
  assert.equal(
    loadPerkConfig(repoWith({ "perk.toml": "[ci]\ntrusted = false\n" })).ci.trusted,
    false,
  );
  assert.equal(loadPerkConfig(repoWith({ "perk.toml": "[ci]\n" })).ci.trusted, false);
});

test("loadPerkConfig: perk.local.toml [ci] trusted leaf-merges (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[ci]\ntrusted = false\n\n[[ci.checks]]\nname = "a"\ncommand = "A"\n',
    "perk.local.toml": "[ci]\ntrusted = true\n",
  });
  const ci = loadPerkConfig(cwd).ci;
  assert.equal(ci.trusted, true);
  // The scalar leaf-merge leaves the committed [[ci.checks]] rows intact.
  assert.deepEqual(ci.checks, [{ name: "a", command: "A" }]);
});

// --- [providers] selection ---

test("loadPerkConfig: [providers] absent -> empty selection", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  assert.deepEqual(loadPerkConfig(cwd).providers, {});
});

test("loadPerkConfig: parses [providers] plan/todo/askuser/footer/web/review strings", () => {
  const cwd = repoWith({
    "perk.toml":
      '[providers]\nplan = "tombell-plan"\ntodo = "perk-checkpoints"\naskuser = "juicesharp-ask-user"\nfooter = "pi-bar-footer"\nweb = "ollama-web-search"\nreview = "plannotator-review"\n',
  });
  assert.deepEqual(loadPerkConfig(cwd).providers, {
    plan: "tombell-plan",
    todo: "perk-checkpoints",
    askuser: "juicesharp-ask-user",
    footer: "pi-bar-footer",
    web: "ollama-web-search",
    review: "plannotator-review",
  });
});

test("loadPerkConfig: perk.local.toml [providers] overlays perk.toml (local wins)", () => {
  const cwd = repoWith({
    "perk.toml": '[providers]\nplan = "perk-plan"\n',
    "perk.local.toml": '[providers]\nplan = "tombell-plan"\n',
  });
  assert.equal(loadPerkConfig(cwd).providers.plan, "tombell-plan");
});

// --- [compaction] objective_threshold ---

test("loadPerkConfig: [compaction] objective_threshold parses a native float in (0,1]", () => {
  const cwd = repoWith({ "perk.toml": "[compaction]\nobjective_threshold = 0.8\n" });
  assert.equal(loadPerkConfig(cwd).objectiveCompactThreshold, 0.8);
});

test('loadPerkConfig: [compaction] objective_threshold = "0.8" (string) is ignored', () => {
  const cwd = repoWith({ "perk.toml": '[compaction]\nobjective_threshold = "0.8"\n' });
  assert.equal(loadPerkConfig(cwd).objectiveCompactThreshold, undefined);
});

test("loadPerkConfig: out-of-range [compaction] objective_threshold is ignored", () => {
  for (const value of ["0", "1.5", "-0.2"]) {
    const cwd = repoWith({ "perk.toml": `[compaction]\nobjective_threshold = ${value}\n` });
    assert.equal(loadPerkConfig(cwd).objectiveCompactThreshold, undefined);
  }
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

// --- legacy `.pi/...` config is never consumed (the .perk/ move) ------------

test("loadPerkConfig: a legacy .pi/perk.toml is ignored (reads only .perk/config.toml)", () => {
  // Seed config at BOTH the legacy `.pi/perk.toml` and the new `.perk/config.toml`; the reader
  // resolves only the `.perk/` target, so the legacy value never leaks in.
  const cwd = repoWith({ "perk.toml": '[workflow]\nplan_authoring = "new"\n' });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[workflow]\nplan_authoring = "legacy"\n', "utf8");
  assert.equal(loadPerkConfig(cwd).planAuthoring, "new");
});

test("resolveIssueBackendId: a legacy .pi/perk.toml selection is ignored", () => {
  // The legacy committed file selecting linear must NOT be read — only `.perk/config.toml` counts.
  const cwd = mkdtempSync(join(tmpdir(), "perk-config-"));
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[issues]\nbackend = "linear"\n', "utf8");
  assert.equal(resolveIssueBackendId(cwd), "github");
});
