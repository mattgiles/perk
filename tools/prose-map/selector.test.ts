import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { promisify } from "node:util";
import ts from "typescript";

import { scanRepository } from "./catalog.ts";
import {
  enumerateSelectorSites,
  parseDiagnosticsFor,
  resolveSelectors,
  type SelectorResponse,
} from "./selector.ts";

const execFileAsync = promisify(execFile);
const ROOT = path.resolve(import.meta.dirname, "../..");
const SELECTOR_SCRIPT = path.join(ROOT, "tools/prose-map/selector.ts");

function ok(source: string, selectors: string[]): Extract<SelectorResponse, { status: "ok" }> {
  const response = resolveSelectors(source, selectors);
  assert.equal(response.status, "ok");
  return response;
}

function result(source: string, selector: string) {
  return ok(source, [selector]).results[0];
}

function focus(source: string, selector: string): string {
  const resolved = result(source, selector);
  assert.ok(resolved);
  assert.equal(resolved.status, "resolved");
  return [...source].slice(resolved.start, resolved.end).join("");
}

function interpolation(name: string): string {
  return `$` + `{${name}}`;
}

async function withRequest(
  request: unknown,
  invoke: (requestPath: string) => Promise<void>,
): Promise<void> {
  const directory = await mkdtemp(path.join(tmpdir(), "perk-selector-test-"));
  try {
    const requestPath = path.join(directory, "request.json");
    await writeFile(requestPath, JSON.stringify(request), "utf-8");
    await invoke(requestPath);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("CLI accepts one strict temp request and emits one newline-terminated JSON response", async () => {
  await withRequest(
    {
      version: 1,
      source: 'pi.registerTool({ name: "demo", description: "hello 😀" });\n',
      selectors: ["tool:demo.description"],
    },
    async (requestPath) => {
      const completed = await execFileAsync(process.execPath, [SELECTOR_SCRIPT, requestPath], {
        cwd: ROOT,
      });
      assert.equal(completed.stdout.endsWith("\n"), true);
      assert.equal(completed.stdout.trim().split("\n").length, 1);
      assert.deepEqual(JSON.parse(completed.stdout), {
        version: 1,
        status: "ok",
        results: [
          {
            selector: "tool:demo.description",
            status: "resolved",
            start: 45,
            end: 54,
          },
        ],
      });
    },
  );
});

test("CLI rejects usage, malformed JSON, wrong versions, types, and unknown keys on stderr", async () => {
  await assert.rejects(
    execFileAsync(process.execPath, [SELECTOR_SCRIPT], { cwd: ROOT }),
    (error: unknown) => {
      assert.equal((error as { code?: unknown }).code, 2);
      assert.match(
        String((error as { stderr?: unknown }).stderr),
        /usage: node tools\/prose-map\/selector\.ts <request-json-path>/,
      );
      return true;
    },
  );

  const invalidRequests: unknown[] = [
    { version: 2, source: "", selectors: [] },
    { version: 1, source: 1, selectors: [] },
    { version: 1, source: "", selectors: [1] },
    { version: 1, source: "", selectors: [], extra: true },
    [],
  ];
  for (const request of invalidRequests) {
    await withRequest(request, async (requestPath) => {
      await assert.rejects(
        execFileAsync(process.execPath, [SELECTOR_SCRIPT, requestPath], { cwd: ROOT }),
        (error: unknown) => {
          assert.equal((error as { code?: unknown }).code, 1);
          assert.notEqual(String((error as { stderr?: unknown }).stderr).trim(), "");
          assert.equal(String((error as { stdout?: unknown }).stdout), "");
          return true;
        },
      );
    });
  }
});

test("empty selector batches still report the first parser diagnostic", () => {
  const response = resolveSelectors("const broken = ;\n", []);
  assert.deepEqual(response, { version: 1, status: "invalid-source", line: 1, column: 16 });
});

test("the pinned private parseDiagnostics seam exists and is shape checked", () => {
  const valid = ts.createSourceFile(
    "<prose-review-source.ts>",
    "const value = 1;",
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  assert.deepEqual(parseDiagnosticsFor(valid), []);
  const malformed = ts.createSourceFile(
    "<prose-review-source.ts>",
    "const broken = ;",
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  assert.equal(parseDiagnosticsFor(malformed).length, 1);
  assert.throws(
    () => parseDiagnosticsFor({ parseDiagnostics: null } as unknown as ts.SourceFile),
    /parseDiagnostics is unavailable/,
  );
  assert.throws(
    () => parseDiagnosticsFor({ parseDiagnostics: [{}] } as unknown as ts.SourceFile),
    /invalid diagnostic/,
  );
});

test("enumeration parses supplied source only and never constructs a Program", async () => {
  const implementation = await readFile(SELECTOR_SCRIPT, "utf-8");
  assert.match(
    implementation,
    /ts\.createSourceFile\(\s*"<prose-review-source\.ts>",\s*source,\s*ts\.ScriptTarget\.ES2022,\s*true,\s*ts\.ScriptKind\.TS/s,
  );
  assert.doesNotMatch(implementation, /ts\.createProgram\(/);
  assert.match(
    implementation,
    /checker\(name, ts\.ScriptTarget\.ES2022, ts\.LanguageVariant\.Standard\)/,
  );
});

test("bare module symbols focus full named declarations and reject excluded forms", () => {
  const source = [
    "@sealed",
    "export class Demo { value = 1; }",
    "export async function run() { return 1; }",
    "export const single = `text`;",
    "const first = 1, multi = 2;",
    "const { destructured } = value;",
    "function outer() { function nested() {} }",
  ].join("\n");
  assert.equal(focus(source, "symbol:Demo"), "@sealed\nexport class Demo { value = 1; }");
  assert.equal(focus(source, "symbol:run"), "export async function run() { return 1; }");
  assert.equal(focus(source, "symbol:single"), "export const single = `text`;");
  for (const selector of [
    "symbol:module",
    "symbol:multi",
    "symbol:destructured",
    "symbol:nested",
  ]) {
    const unresolved = result(source, selector);
    assert.ok(unresolved);
    assert.equal(unresolved.status, "unresolved");
    assert.equal(
      unresolved.reason,
      selector === "symbol:module" ? "unsupported-selector" : "selector-not-found",
    );
  }
});

test("bare symbol duplicate reports the second Unicode code-point location", () => {
  const source = 'const prefix = "😀"; function same() {}\nclass same {}\n';
  assert.deepEqual(result(source, "symbol:same"), {
    selector: "symbol:same",
    status: "unresolved",
    reason: "selector-ambiguous",
    line: 2,
    column: 1,
  });
});

test("exact raw tool selector identity wins for dotted names and collisions fail closed", () => {
  const dotted = 'pi.registerTool({ name: "demo.tool", description: "direct" });';
  assert.equal(focus(dotted, "tool:demo.tool.description"), '"direct"');

  const collision = `
pi.registerTool({
  name: "demo",
  parameters: {
    "properties.focus": { description: "dotted" },
    properties: { focus: { description: "nested" } },
  },
});`;
  const ambiguous = result(collision, "tool:demo.parameters.properties.focus.description");
  assert.ok(ambiguous);
  assert.equal(ambiguous.status, "unresolved");
  assert.equal(ambiguous.reason, "selector-ambiguous");
  assert.deepEqual([ambiguous.line, ambiguous.column], [6, 41]);
});

test("numeric static keys, array indexes, duplicate keys, and registrations never guess", () => {
  const source = `
pi.registerTool({
  name: "same",
  parameters: {
    items: [{ description: "array" }],
    "items.0": { description: "numeric" },
  },
  description: "first",
  description: "second",
});
pi.registerTool({ name: "same", description: "third" });`;
  for (const selector of ["tool:same.parameters.items.0.description", "tool:same.description"]) {
    const ambiguous = result(source, selector);
    assert.ok(ambiguous);
    assert.equal(ambiguous.status, "unresolved");
    assert.equal(ambiguous.reason, "selector-ambiguous");
  }
});

test("tool traversal distinguishes explicit sites, opaque siblings, drift, and indirection", () => {
  const source = `
const promptGuidelines = ["indirect"];
const spread = {};
pi.registerTool({
  name: "demo",
  description: "direct",
  promptSnippet: helper(),
  promptGuidelines,
  parameters: {
    ...spread,
    properties: { focus: { description: \`nested \${value}\` } },
  },
});`;
  assert.equal(focus(source, "tool:demo.description"), '"direct"');
  assert.equal(
    focus(source, "tool:demo.parameters.properties.focus.description"),
    "`nested " + interpolation("value") + "`",
  );
  for (const selector of ["tool:demo.promptSnippet", "tool:demo.promptGuidelines"]) {
    const unsupported = result(source, selector);
    assert.ok(unsupported);
    assert.equal(unsupported.status, "unresolved");
    assert.equal(unsupported.reason, "unsupported-source-shape");
  }
  const missing = result(source, "tool:demo.parameters.properties.missing.description");
  assert.ok(missing);
  assert.equal(missing.status, "unresolved");
  assert.equal(missing.reason, "selector-not-found");
});

test("model call ordinals are owner-isolated, depth-first, and canonical", () => {
  const source = `
function owner() {
  pi.sendUserMessage("first");
  if (ready) pi.sendUserMessage("second");
  client.complete("third");
  agent.session.prompt("fourth");
}
function other() { pi.sendUserMessage("other"); }`;
  assert.equal(focus(source, "symbol:owner/call:sendUserMessage/0/argument:0"), '"first"');
  assert.equal(focus(source, "symbol:owner/call:sendUserMessage/1/argument:0"), '"second"');
  assert.equal(focus(source, "symbol:owner/call:complete/0/argument:0"), '"third"');
  assert.equal(focus(source, "symbol:owner/call:prompt/0/argument:0"), '"fourth"');
  assert.equal(focus(source, "symbol:other/call:sendUserMessage/0/argument:0"), '"other"');
  const leadingZero = result(source, "symbol:owner/call:sendUserMessage/01/argument:0");
  assert.ok(leadingZero);
  assert.equal(leadingZero.status, "unresolved");
  assert.equal(leadingZero.reason, "unsupported-selector");
});

test("delimiter-bearing owners resolve by exact identity before fallback parsing", () => {
  const source = 'const holder = { ["a/b"]() { pi.sendUserMessage("text"); } };';
  const sourceFile = ts.createSourceFile(
    "x.ts",
    source,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  const selectors = enumerateSelectorSites(sourceFile).sites.map((site) => site.selector);
  assert.equal(selectors.length, 1);
  assert.equal(focus(source, selectors[0] ?? ""), '"text"');
});

test("completeStructured duplicates are ambiguous and each supported field is exact", () => {
  const source = `
function owner() {
  completeStructured({
    toolDescription: "tool",
    system: \`system\`,
    instruction: "instruction",
    schema: schemaRef,
  });
  completeStructured({ system: "duplicate" });
}`;
  assert.equal(focus(source, "symbol:owner/call:completeStructured/toolDescription"), '"tool"');
  const duplicate = result(source, "symbol:owner/call:completeStructured/system");
  assert.ok(duplicate);
  assert.equal(duplicate.status, "unresolved");
  assert.equal(duplicate.reason, "selector-ambiguous");
  const schema = result(source, "symbol:owner/call:completeStructured/schema");
  assert.ok(schema);
  assert.equal(schema.status, "unresolved");
  assert.equal(schema.reason, "unsupported-source-shape");
});

test("event handlers and workflow properties use exact callback and initializer targets", () => {
  const source = `
function install() {
  pi.on("before_agent_start", ((event) => ({ event })) satisfies Handler);
  pi.on("before_agent_start");
  pi.on("before_agent_start", handler);
  return { workflowScript: "run workflow" };
}`;
  assert.equal(
    focus(source, "symbol:install/event:before_agent_start/0/handler"),
    "((event) => ({ event })) satisfies Handler",
  );
  for (const ordinal of [1, 2]) {
    const unsupported = result(
      source,
      `symbol:install/event:before_agent_start/${ordinal}/handler`,
    );
    assert.ok(unsupported);
    assert.equal(unsupported.status, "unresolved");
    assert.equal(unsupported.reason, "unsupported-source-shape");
  }
  assert.equal(focus(source, "symbol:install/property:workflowScript/0"), '"run workflow"');
});

test("direct prose accepts literals, templates, plus builders, and transparent wrappers only", () => {
  const source = `
function owner() {
  client.complete("quoted");
  client.complete(\`plain\`);
  client.complete(\`hello \${name}\`);
  client.complete((("prefix " + dynamic()) as string)!);
  client.complete(left + right);
  client.complete(identifier);
  client.complete(call());
  client.complete({ text: "nested" });
  client.complete(["nested"]);
}`;
  assert.equal(focus(source, "symbol:owner/call:complete/0/argument:0"), '"quoted"');
  assert.equal(focus(source, "symbol:owner/call:complete/1/argument:0"), "`plain`");
  assert.equal(
    focus(source, "symbol:owner/call:complete/2/argument:0"),
    "`hello " + interpolation("name") + "`",
  );
  assert.equal(
    focus(source, "symbol:owner/call:complete/3/argument:0"),
    '(("prefix " + dynamic()) as string)!',
  );
  for (let ordinal = 4; ordinal <= 8; ordinal += 1) {
    const unsupported = result(source, `symbol:owner/call:complete/${ordinal}/argument:0`);
    assert.ok(unsupported);
    assert.equal(unsupported.status, "unresolved");
    assert.equal(unsupported.reason, "unsupported-source-shape");
  }
});

test("fallback grammar separates unsupported selectors from stale supported selectors", () => {
  const source = "const untouched = 1;";
  const notFound = [
    "tool:demo.description",
    "symbol:owner/call:complete/0/argument:0",
    "symbol:owner/call:completeStructured/system",
    "symbol:owner/event:before_agent_start/0/handler",
    "symbol:owner/property:workflowScript/0",
  ];
  for (const selector of notFound) {
    const unresolved = result(source, selector);
    assert.ok(unresolved);
    assert.equal(unresolved.status, "unresolved");
    assert.equal(unresolved.reason, "selector-not-found");
    assert.equal(unresolved.line, null);
    assert.equal(unresolved.column, null);
  }
  for (const selector of [
    "",
    "tool:demo",
    "symbol:module",
    "symbol:owner/call:unknown/0/argument:0",
    "symbol:owner/property:workflowScript/00",
  ]) {
    const unresolved = result(source, selector);
    assert.ok(unresolved);
    assert.equal(unresolved.status, "unresolved");
    assert.equal(unresolved.reason, "unsupported-selector");
  }
});

test("ranges and locations normalize UTF-16 to Unicode code points", () => {
  const source =
    'const prefix = "😀"; pi.sendUserMessage(`inside ��� ' + interpolation("value") + "`);\n";
  const selector = "symbol:module/call:sendUserMessage/0/argument:0";
  const resolved = result(source, selector);
  assert.ok(resolved);
  assert.equal(resolved.status, "resolved");
  assert.equal(
    [...source].slice(resolved.start, resolved.end).join(""),
    "`inside ��� " + interpolation("value") + "`",
  );
  assert.equal(resolved.start, [...source.slice(0, source.indexOf("`inside"))].length);

  const invalid = resolveSelectors('const prefix = "😀";\r\nconst broken = ;\n', []);
  assert.deepEqual(invalid, { version: 1, status: "invalid-source", line: 2, column: 16 });
});

test("diagnostic locations honor every TypeScript line break and EOF insertion", () => {
  for (const lineBreak of ["\n", "\r", "\r\n", "\u2028", "\u2029"]) {
    const invalid = resolveSelectors(`const ok = 1;${lineBreak}const broken = ;`, []);
    assert.deepEqual(invalid, { version: 1, status: "invalid-source", line: 2, column: 16 });
  }
  const eof = resolveSelectors("const broken =", []);
  assert.deepEqual(eof, { version: 1, status: "invalid-source", line: 1, column: 15 });
});

test("real discovery output stays resolver-covered and all resolved ranges recompose", async () => {
  const catalog = scanRepository(ROOT);
  assert.equal(catalog.candidates.length, 94);
  const byPath = new Map<string, string[]>();
  for (const candidate of catalog.candidates) {
    for (const fragment of candidate.fragments) {
      const selectors = byPath.get(candidate.path) ?? [];
      selectors.push(fragment.selector);
      byPath.set(candidate.path, selectors);
    }
  }

  for (const [relative, selectors] of byPath) {
    const source = await readFile(path.join(ROOT, relative), "utf-8");
    const response = resolveSelectors(source, selectors);
    assert.equal(response.status, "ok", relative);
    if (response.status !== "ok") {
      continue;
    }
    assert.equal(response.results.length, selectors.length, relative);
    response.results.forEach((current, index) => {
      assert.equal(current.selector, selectors[index], relative);
      if (current.status === "resolved") {
        const before = [...source].slice(0, current.start).join("");
        const selected = [...source].slice(current.start, current.end).join("");
        const after = [...source].slice(current.end).join("");
        assert.equal(before + selected + after, source, relative);
      } else {
        assert.equal(
          current.reason,
          "unsupported-source-shape",
          `${relative}: ${current.selector}`,
        );
      }
    });
  }
});
