// The registration seam with FAKE tools: pass-through of results and definition fields, and the
// registration-time rejections. Kept in its own file — node --test runs each file in its own
// process — so the fakes never reach the census/parity/fixture suites' catalog.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  gatedToolsFor,
  isPerkTool,
  LOADOUT_HOST_NAME,
  perkToolPolicy,
  stageToolsFor,
  type ToolPolicy,
} from "../substrate/toolPolicy.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  LOADOUT_HOST_POLICY,
  type PerkToolDefinition,
  registerLoadoutHost,
  registerPerkTool,
} from "./perkTool.ts";

type Captured = Record<string, unknown>;

/** A stub `pi` that records each `registerTool` definition verbatim. */
function capturingPi(): { pi: ExtensionAPI; captured: Captured[] } {
  const captured: Captured[] = [];
  const pi = { registerTool: (def: Captured) => captured.push(def) } as unknown as ExtensionAPI;
  return { pi, captured };
}

const EMPTY_PARAMS = { type: "object", additionalProperties: false, properties: {} } as const;

function fakeDefinition(
  name: string,
  result: { content: { type: "text"; text: string }[]; details: unknown; terminate?: boolean },
): PerkToolDefinition {
  return {
    name,
    label: name,
    description: `fake ${name}`,
    promptSnippet: `fake ${name} snippet`,
    parameters: EMPTY_PARAMS,
    executionMode: "sequential",
    async execute() {
      return result as never;
    },
  };
}

test("the seam adds only the derived metadata: every original field passes through untouched", () => {
  const { pi, captured } = capturingPi();
  const def = fakeDefinition("seam_fields_action", {
    content: [{ type: "text", text: "x" }],
    details: {},
  });
  registerPerkTool(pi, def, { stages: ["plan"], gated: "allowed", kind: "action" });
  const def2 = fakeDefinition("seam_fields_terminal", {
    content: [{ type: "text", text: "x" }],
    details: {},
  });
  registerPerkTool(pi, def2, { stages: ["plan"], gated: "blocked", kind: "terminal" });
  assert.equal(captured.length, 2);
  const [first, second] = captured;
  assert.deepEqual(
    Object.keys(first ?? {}).sort(),
    [...Object.keys(def), "annotations", "exposure"].sort(),
  );
  for (const key of Object.keys(def)) {
    assert.equal(first?.[key], (def as unknown as Captured)[key], key);
  }
  assert.equal(first?.exposure, "direct");
  assert.deepEqual(first?.annotations, { readOnlyHint: true });
  assert.deepEqual(Object.keys(second ?? {}).sort(), [...Object.keys(def2), "exposure"].sort());
  assert.equal(second?.exposure, "model-only");
});

test("registration-time rejections: deferred model-only kinds, policy-owned fields, unknown stages, divergent re-registration", () => {
  const { pi, captured } = capturingPi();
  const result = { content: [{ type: "text" as const, text: "x" }], details: {} };
  for (const kind of ["terminal", "interactive", "orchestration"] as const) {
    assert.throws(
      () =>
        registerPerkTool(pi, fakeDefinition(`seam_def_${kind}`, result), {
          stages: ["plan"],
          gated: "allowed",
          kind,
          declared: "deferred",
        }),
      /perk tool policy: seam_def_\w+ — declared: "deferred" requires kind query or action/,
    );
  }
  for (const field of ["exposure", "annotations", "defaultActive", "prepareLoadout"]) {
    const def = { ...fakeDefinition(`seam_field_${field}`, result), [field]: undefined };
    assert.throws(
      () =>
        registerPerkTool(pi, def as PerkToolDefinition, {
          stages: [],
          gated: "allowed",
          kind: "query",
        }),
      new RegExp(`must not set \`${field}\``),
    );
  }
  assert.throws(
    () =>
      registerPerkTool(pi, fakeDefinition("seam_unknown_stage", result), {
        stages: ["not-a-stage"],
        gated: "allowed",
        kind: "query",
      }),
    /unknown stage id "not-a-stage"/,
  );
  // Nothing rejected reached Pi or the catalog.
  assert.equal(captured.length, 0);
  assert.equal(isPerkTool("seam_unknown_stage"), false);

  const policy: ToolPolicy = { stages: ["implement"], gated: "blocked", kind: "action" };
  registerPerkTool(pi, fakeDefinition("seam_dup", result), policy);
  registerPerkTool(pi, fakeDefinition("seam_dup", result), { ...policy, stages: ["implement"] });
  assert.equal(captured.length, 2, "an identical re-registration still registers with Pi");
  assert.throws(
    () => registerPerkTool(pi, fakeDefinition("seam_dup", result), { ...policy, gated: "allowed" }),
    /perk tool policy: seam_dup — re-registered with a divergent policy/,
  );
  assert.equal(captured.length, 2);
  assert.deepEqual(perkToolPolicy("seam_dup"), policy);
});

test("a deferred query registers with exposure deferred and stays out of both activation views", () => {
  const { pi, captured } = capturingPi();
  registerPerkTool(
    pi,
    fakeDefinition("seam_deferred_query", { content: [{ type: "text", text: "x" }], details: {} }),
    { stages: ["plan"], gated: "allowed", kind: "query", declared: "deferred" },
  );
  assert.equal(captured[0]?.exposure, "deferred");
  assert.ok(!gatedToolsFor("plan").includes("seam_deferred_query"));
  assert.ok(!(stageToolsFor("plan") ?? []).includes("seam_deferred_query"));
});

test("a live session: terminate and failed results pass through byte-identical; exposure is derived", async () => {
  const terminal = {
    content: [{ type: "text" as const, text: "terminal done" }],
    details: { ok: true, n: 1 },
    terminate: true,
  };
  const failed = {
    content: [{ type: "text" as const, text: "fake failed: nope" }],
    details: { ok: false, error: "nope", error_type: "fake_error" },
  };
  const h = await loadPerkSession({
    cwd: scaffoldRepo(),
    extraExtensions: [
      (pi) => {
        registerPerkTool(pi, fakeDefinition("seam_live_terminal", terminal), {
          stages: ["implement"],
          gated: "blocked",
          kind: "terminal",
        });
        registerPerkTool(pi, fakeDefinition("seam_live_action", failed), {
          stages: ["implement"],
          gated: "blocked",
          kind: "action",
        });
      },
    ],
  });
  try {
    assert.deepEqual(await h.invokeTool("seam_live_terminal", {}), terminal);
    assert.deepEqual(await h.invokeTool("seam_live_action", {}), failed);
    const info = (name: string) => h.session.getAllTools().find((t) => t.name === name);
    assert.equal(info("seam_live_terminal")?.exposure, "model-only");
    assert.equal(info("seam_live_terminal")?.annotations, undefined);
    assert.equal(info("seam_live_action")?.exposure, "direct");
  } finally {
    h.dispose();
  }
});

test("registerLoadoutHost: a catalogued model-only host with the one prepareLoadout; registerPerkTool refuses both", () => {
  const { pi, captured } = capturingPi();
  const hook = () => ({ hiddenDeclarations: [LOADOUT_HOST_NAME] });
  registerLoadoutHost(pi, hook);
  const [host] = captured;
  assert.ok(host !== undefined);
  assert.equal(host.name, LOADOUT_HOST_NAME);
  assert.equal(host.exposure, "model-only");
  assert.deepEqual(host.annotations, { readOnlyHint: true });
  assert.equal(host.prepareLoadout, hook);
  assert.equal(host.promptSnippet, undefined, "never in the system prompt");
  assert.equal(host.promptGuidelines, undefined);
  assert.deepEqual(perkToolPolicy(LOADOUT_HOST_NAME), LOADOUT_HOST_POLICY);
  assert.equal(isPerkTool(LOADOUT_HOST_NAME), true);
  // The seam never registers a host or a hook.
  assert.throws(
    () =>
      registerPerkTool(pi, fakeDefinition("seam_host", { content: [], details: {} }), {
        stages: [],
        gated: "allowed",
        kind: "host",
      }),
    /the loadout host registers through registerLoadoutHost/,
  );
  assert.throws(
    () =>
      registerPerkTool(
        pi,
        {
          ...fakeDefinition("seam_hook", { content: [], details: {} }),
          prepareLoadout: hook,
        } as never,
        { stages: [], gated: "allowed", kind: "query" },
      ),
    /must not set `prepareLoadout`/,
  );
  assert.equal(captured.length, 1);
});
