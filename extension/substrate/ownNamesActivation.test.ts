// Own-names-only activation, the provenance-posture table and the `perk_stage` loadout host
// (contracts.md §8.40), driven through REAL bound AgentSessions (fully offline). Two fixture modes
// (`extension/testing/harness.ts`): Mode A binds perk as the inline factory from this file's own
// module graph (so test-only perk tools register into the same catalog); Mode B loads perk by
// path beside fake npm packages installed into the user-scope package directory, so every foreign
// tool carries real package provenance — Mode B cases assert only through the live session.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  fakeNpmPackage,
  loadPerkSession,
  PERK_EXTENSION_PATH,
  type PerkSession,
  registerFakeTool,
  scaffoldRepo,
} from "../testing/harness.ts";

/**
 * loadPerkSession with process.cwd() pointed at the scaffold for the load (provider vacating
 * resolves `process.cwd()` at factory time). Restores cwd before returning.
 */
async function loadAt(
  cwd: string,
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> = {},
): Promise<PerkSession> {
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, ...opts });
  } finally {
    process.chdir(savedCwd);
  }
}

/** The ESM source of a fake package registering load-time no-op tools. */
function loadTimeTools(names: readonly string[]): string {
  return `export default function (pi) {
  for (const name of ${JSON.stringify(names)}) {
    pi.registerTool({
      name,
      label: name,
      description: "fake package tool " + name + " (test)",
      parameters: { type: "object", properties: {} },
      async execute() { return { content: [{ type: "text", text: "ok" }], details: {} }; },
    });
  }
}
`;
}

const PROMPT_RUNTIME = "pi-subagents:prompt-runtime";

// --- 0. the spike: the fixture's provenance + order preconditions (a failure here stops the work) -

test("spike (B): a fake package's tool carries its verbatim spec as provenance, and path-loaded perk loads before every package", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, {
    packages: [
      fakeNpmPackage("npm:fake-research@1.0.0", loadTimeTools(["fake_research_query"])),
      fakeNpmPackage("npm:@fake-scope/fake-other@2.3.4", loadTimeTools(["fake_other_query"])),
    ],
  });
  try {
    const info = h.session.getAllTools().find((t) => t.name === "fake_research_query");
    assert.ok(info !== undefined, "the fake package's tool registered");
    assert.equal(info.sourceInfo.source, "npm:fake-research@1.0.0");
    assert.equal(info.sourceInfo.origin, "package");
    const scoped = h.session.getAllTools().find((t) => t.name === "fake_other_query");
    assert.equal(scoped?.sourceInfo.source, "npm:@fake-scope/fake-other@2.3.4");
    // perk itself registered (the path load worked) …
    assert.ok(h.session.getAllTools().some((t) => t.name === "plan_draft"));
    // … and loaded before every fake package (CLI paths precede settings packages).
    const paths = h.session.resourceLoader.getExtensions().extensions.map((e) => e.path);
    const perkAt = paths.indexOf(PERK_EXTENSION_PATH);
    assert.ok(perkAt !== -1, `perk's path is loaded: ${paths.join(", ")}`);
    const packageAts = paths
      .map((path, i) => ({ path, i }))
      .filter(({ path }) => path.includes(`${"npm"}/node_modules/`))
      .map(({ i }) => i);
    assert.equal(packageAts.length, 2, `both fake packages loaded: ${paths.join(", ")}`);
    for (const at of packageAts) assert.ok(perkAt < at, "perk precedes every package");
  } finally {
    h.dispose();
  }
});

test("spike (A): a named inline factory's tool carries its exact synthetic path", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, {
    extraExtensions: [
      {
        name: PROMPT_RUNTIME,
        factory: (pi: ExtensionAPI) => registerFakeTool(pi, "structured_output"),
      },
    ],
  });
  try {
    const info = h.session.getAllTools().find((t) => t.name === "structured_output");
    assert.equal(info?.sourceInfo.path, `<inline:${PROMPT_RUNTIME}>`);
    assert.equal(info?.sourceInfo.source, "inline");
  } finally {
    h.dispose();
  }
});
