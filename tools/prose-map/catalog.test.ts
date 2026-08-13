import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { scanRepository } from "./catalog.ts";

test("discovers governed tool fragments and direct model delivery structurally", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "perk-prose-map-"));
  try {
    const extension = path.join(root, "extension");
    await mkdir(extension);
    await writeFile(
      path.join(extension, "sample.ts"),
      `
export const PERK_TOOLS: readonly string[] = ["demo"];

export function install(pi: any): void {
  pi.registerTool({
    name: "demo",
    description: "Do the bounded thing.",
    promptSnippet: "Do it",
    promptGuidelines: ["Stay bounded.", "Return a report."],
    parameters: {
      type: "object",
      properties: {
        focus: { type: "string", description: "Optional focus data." },
      },
    },
  });
  pi.sendUserMessage("Continue with the bounded thing.");
}
`,
      "utf-8",
    );

    const catalog = scanRepository(root);
    assert.deepEqual(catalog.governed_tools, ["demo"]);
    const tool = catalog.candidates.find((candidate) => candidate.id === "typescript-tool:demo");
    assert.ok(tool);
    assert.deepEqual(
      tool.fragments.map((fragment) => fragment.id),
      [
        "description",
        "promptSnippet",
        "promptGuidelines.0",
        "promptGuidelines.1",
        "parameters.properties.focus.description",
      ],
    );
    assert.ok(
      catalog.candidates.some(
        (candidate) =>
          candidate.path === "extension/sample.ts" &&
          candidate.selector.includes("call:sendUserMessage"),
      ),
    );
  } finally {
    await rm(root, { force: true, recursive: true });
  }
});
