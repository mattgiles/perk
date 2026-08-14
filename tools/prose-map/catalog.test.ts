import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  scanRepository,
  TOOL_FIELD_POLICIES,
  type TypeScriptCatalog,
  validateToolFieldPolicies,
} from "./catalog.ts";

async function scanFixture(source: string): Promise<TypeScriptCatalog> {
  const root = await mkdtemp(path.join(tmpdir(), "perk-prose-map-"));
  try {
    const extension = path.join(root, "extension");
    await mkdir(extension);
    await writeFile(path.join(extension, "sample.ts"), source, "utf-8");
    return scanRepository(root);
  } finally {
    await rm(root, { force: true, recursive: true });
  }
}

test("the production tool field policy is valid and blank exclusions fail closed", () => {
  assert.doesNotThrow(() => validateToolFieldPolicies(TOOL_FIELD_POLICIES));
  assert.throws(
    () =>
      validateToolFieldPolicies({
        excluded: { kind: "non-prose", reason: " \t " },
      }),
    /^Error: tool field policy excluded has a blank non-prose reason$/,
  );
});

test("discovers every governed ToolDefinition field without changing logical fragments", async () => {
  const catalog = await scanFixture(`
export const PERK_TOOLS: readonly string[] = ["demo"];

export function install(pi: any): void {
  pi.registerTool({
    name: "demo",
    label: "Demo",
    description: "Do the bounded thing.",
    promptSnippet: "Do it",
    promptGuidelines: ["Stay bounded.", "Return a report."],
    parameters: {
      type: "object",
      properties: {
        focus: { type: "string", description: "Optional focus data." },
      },
    },
    constrainedSampling: true,
    renderShell: false,
    prepareArguments(args: unknown) { return args; },
    executionMode: "command",
    async execute() { return { content: [] }; },
    renderCall() { return undefined; },
    renderResult() { return undefined; },
  });
  pi.sendUserMessage("Continue with the bounded thing.");
}
`);

  assert.deepEqual(catalog.governed_tools, ["demo"]);
  assert.deepEqual(catalog.tool_field_issues, []);
  const tool = catalog.candidates.find((candidate) => candidate.id === "typescript-tool:demo");
  assert.ok(tool);
  assert.deepEqual(tool.fragments, [
    {
      id: "description",
      label: "description",
      selector: "tool:demo.description",
    },
    {
      id: "promptSnippet",
      label: "promptSnippet",
      selector: "tool:demo.promptSnippet",
    },
    {
      id: "promptGuidelines.0",
      label: "promptGuidelines item 1",
      selector: "tool:demo.promptGuidelines.0",
    },
    {
      id: "promptGuidelines.1",
      label: "promptGuidelines item 2",
      selector: "tool:demo.promptGuidelines.1",
    },
    {
      id: "parameters.properties.focus.description",
      label: "parameters.properties.focus.description",
      selector: "tool:demo.parameters.properties.focus.description",
    },
  ]);
  assert.ok(
    catalog.candidates.some(
      (candidate) =>
        candidate.path === "extension/sample.ts" &&
        candidate.selector.includes("call:sendUserMessage"),
    ),
  );
});

test("promptGuidelines identifiers and shorthand stay one field-level fragment", async () => {
  const catalog = await scanFixture(`
export const PERK_TOOLS: readonly string[] = ["identifier", "shorthand"];
const GUIDELINES = ["Stay bounded."];
const promptGuidelines = GUIDELINES;

export function install(pi: any): void {
  pi.registerTool({
    name: "identifier",
    promptGuidelines: GUIDELINES,
  });
  pi.registerTool({
    name: "shorthand",
    promptGuidelines,
  });
}
`);

  assert.deepEqual(catalog.tool_field_issues, []);
  for (const name of ["identifier", "shorthand"]) {
    const tool = catalog.candidates.find((candidate) => candidate.id === `typescript-tool:${name}`);
    assert.ok(tool);
    assert.deepEqual(tool.fragments, [
      {
        id: "promptGuidelines",
        label: "promptGuidelines",
        selector: `tool:${name}.promptGuidelines`,
      },
    ]);
  }
});

test("only governed registrations report unclassified fields", async () => {
  const catalog = await scanFixture(`
export const PERK_TOOLS: readonly string[] = ["governed"];

export function install(pi: any): void {
  pi.registerTool({
    name: "governed",
    description: "Known prose.",
    promptEpilogue: "New model-facing prose.",
  });
  pi.registerTool({
    name: "outside-census",
    description: "Known prose.",
    promptEpilogue: "New model-facing prose.",
  });
}
`);

  assert.deepEqual(
    catalog.candidates
      .filter((candidate) => candidate.kind === "typescript-tool")
      .map((candidate) => candidate.id),
    ["typescript-tool:governed", "typescript-tool:outside-census"],
  );
  assert.deepEqual(catalog.tool_field_issues, [
    {
      kind: "unclassified",
      field: "promptEpilogue",
      reason: "unclassified-field",
      tool: "governed",
      path: "extension/sample.ts",
      selector: "tool:governed.promptEpilogue",
    },
  ]);
});

test("opaque members use all-member indexes while static computed names are inventoried", async () => {
  const catalog = await scanFixture(`
export const PERK_TOOLS: readonly string[] = ["opaque"];
const spreadFields = {};
const dynamicField = "promptEpilogue";

export function install(pi: any): void {
  pi.registerTool({
    name: "opaque",
    description: "Known prose.",
    ...spreadFields,
    [dynamicField]: "Hidden prose.",
    ["label"]: "Opaque demo",
    [0]: "Statically named but not classified.",
    ["promptSnippet"]: "Known computed prose.",
  });
}
`);

  assert.deepEqual(catalog.tool_field_issues, [
    {
      kind: "unclassified",
      field: "0",
      reason: "unclassified-field",
      tool: "opaque",
      path: "extension/sample.ts",
      selector: "tool:opaque.0",
    },
    {
      kind: "opaque",
      field: null,
      reason: "spread-assignment",
      tool: "opaque",
      path: "extension/sample.ts",
      selector: "tool:opaque/member:2",
    },
    {
      kind: "opaque",
      field: null,
      reason: "dynamic-computed-property",
      tool: "opaque",
      path: "extension/sample.ts",
      selector: "tool:opaque/member:3",
    },
  ]);
  const tool = catalog.candidates.find((candidate) => candidate.id === "typescript-tool:opaque");
  assert.ok(tool);
  assert.deepEqual(
    tool.fragments.map((fragment) => fragment.id),
    ["description", "promptSnippet"],
  );
});

test("an unknown governed field reports independently when no candidate can be emitted", async () => {
  const catalog = await scanFixture(`
export const PERK_TOOLS: readonly string[] = ["empty"];

export function install(pi: any): void {
  pi.registerTool({
    name: "empty",
    promptEpilogue: "The only possible prose.",
  });
}
`);

  assert.equal(
    catalog.candidates.some((candidate) => candidate.id === "typescript-tool:empty"),
    false,
  );
  assert.deepEqual(catalog.tool_field_issues, [
    {
      kind: "unclassified",
      field: "promptEpilogue",
      reason: "unclassified-field",
      tool: "empty",
      path: "extension/sample.ts",
      selector: "tool:empty.promptEpilogue",
    },
  ]);
});
