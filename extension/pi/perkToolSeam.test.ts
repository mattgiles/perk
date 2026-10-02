// The registration seam with FAKE tools: pass-through of definition fields, the structured
// `execute` wrapper (derived `structuredContent`/`isError`, every other result field untouched),
// and the registration-time rejections. Kept in its own file — node --test runs each file in its own
// process — so the fakes never reach the census/parity/fixture suites' catalog.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { createCodemodeExtension, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { failFor, ok } from "../substrate/result.ts";
import {
  gatedToolsFor,
  isPerkTool,
  LOADOUT_HOST_NAME,
  perkToolPolicy,
  stageToolsFor,
  type ToolPolicy,
} from "../substrate/toolPolicy.ts";
import { fauxModelRuntime, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  deferDiscoveryFamily,
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
  result: {
    content: { type: "text"; text: string }[];
    details: unknown;
    terminate?: boolean;
    isError?: boolean;
  },
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

test("the seam adds only the derived metadata and wraps execute: every other field passes through by reference", () => {
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
  const def3 = fakeDefinition("seam_fields_query", {
    content: [{ type: "text", text: "x" }],
    details: { ok: true, n: 1 },
  });
  registerPerkTool(pi, def3, {
    stages: ["plan"],
    gated: "allowed",
    kind: "query",
    result: { properties: { n: { type: "number" } }, required: ["n"] },
  });
  assert.equal(captured.length, 3);
  const [first, second, third] = captured;
  const samePassThrough = (registered: Captured | undefined, original: PerkToolDefinition) => {
    for (const key of Object.keys(original)) {
      if (key === "execute") continue;
      assert.equal(registered?.[key], (original as unknown as Captured)[key], key);
    }
    assert.equal(typeof registered?.execute, "function");
    assert.notEqual(registered?.execute, original.execute, "execute is wrapped");
  };
  assert.deepEqual(
    Object.keys(first ?? {}).sort(),
    [...Object.keys(def), "annotations", "exposure"].sort(),
  );
  samePassThrough(first, def);
  assert.equal(first?.exposure, "direct");
  assert.deepEqual(first?.annotations, { readOnlyHint: true });
  assert.deepEqual(Object.keys(second ?? {}).sort(), [...Object.keys(def2), "exposure"].sort());
  samePassThrough(second, def2);
  assert.equal(second?.exposure, "model-only");
  assert.deepEqual(
    Object.keys(third ?? {}).sort(),
    [...Object.keys(def3), "annotations", "exposure", "outputSchema"].sort(),
  );
  samePassThrough(third, def3);
  assert.deepEqual(
    (third?.outputSchema as { anyOf: { properties: object }[] }).anyOf[0]?.properties,
    { ok: { const: true }, n: { type: "number" } },
  );
});

test("registration-time rejections: deferred model-only kinds, policy-owned fields, the result descriptor, unknown stages, divergent re-registration", () => {
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
  for (const field of [
    "exposure",
    "annotations",
    "defaultActive",
    "prepareLoadout",
    "outputSchema",
  ]) {
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
  assert.throws(
    () =>
      registerPerkTool(pi, fakeDefinition("seam_query_no_result", result), {
        stages: [],
        gated: "allowed",
        kind: "query",
      }),
    /perk tool policy: seam_query_no_result — a query tool must declare its success details \(result\)/,
  );
  assert.throws(
    () =>
      registerPerkTool(pi, fakeDefinition("seam_action_result", result), {
        stages: [],
        gated: "allowed",
        kind: "action",
        result: { properties: {} },
      }),
    /perk tool policy: seam_action_result — `result` is declared by query tools only — a action tool is never a script API/,
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

test("a deferred query registers direct (the registered default) and rides both activation views outside the cohort", () => {
  const { pi, captured } = capturingPi();
  registerPerkTool(
    pi,
    fakeDefinition("seam_deferred_query", { content: [{ type: "text", text: "x" }], details: {} }),
    {
      stages: ["plan"],
      gated: "allowed",
      kind: "query",
      declared: "deferred",
      result: { properties: {} },
    },
  );
  assert.equal(captured[0]?.exposure, "direct");
  assert.ok(gatedToolsFor("plan").includes("seam_deferred_query"));
  assert.ok((stageToolsFor("plan") ?? []).includes("seam_deferred_query"));
});

test("a deferred carve-out writer is refused at the seam", () => {
  const { pi, captured } = capturingPi();
  assert.throws(
    () =>
      registerPerkTool(pi, fakeDefinition("seam_deferred_carve", { content: [], details: {} }), {
        stages: ["plan"],
        gated: { carveOut: "the draft file" },
        kind: "action",
        declared: "deferred",
      }),
    /perk tool policy: seam_deferred_carve — declared: "deferred" requires gated allowed or blocked — the read-only context names carve-out writers, and an undeclared writer would dead-end/,
  );
  assert.equal(captured.length, 0);
  assert.equal(isPerkTool("seam_deferred_carve"), false);
});

/**
 * A stub `pi` with a live-ish registry: `registerTool` replaces by name and `getAllTools` reports
 * each registered definition's exposure (Pi's own shape), optionally failing one name.
 */
function registryPi(failing?: string): {
  pi: ExtensionAPI;
  registrations: Captured[];
} {
  const registry = new Map<string, Captured>();
  const registrations: Captured[] = [];
  const pi = {
    registerTool(def: Captured) {
      if (def.name === failing && def.exposure === "deferred") throw new Error("host refused");
      registrations.push(def);
      registry.set(def.name as string, def);
    },
    getAllTools: () =>
      [...registry.values()].map((def) => ({ name: def.name, exposure: def.exposure ?? "direct" })),
  } as unknown as ExtensionAPI;
  return { pi, registrations };
}

test("deferDiscoveryFamily: re-registers this activation's own family members deferred, once; another activation's pi re-registers nothing; a per-name failure is skipped", () => {
  const family = ["seam_family_a", "seam_family_b"];
  const result = { content: [{ type: "text" as const, text: "x" }], details: {} };
  const member: ToolPolicy = {
    stages: ["implement"],
    gated: "blocked",
    kind: "action",
    declared: "deferred",
  };
  const own = registryPi();
  for (const name of family) registerPerkTool(own.pi, fakeDefinition(name, result), member);
  registerPerkTool(own.pi, fakeDefinition("seam_family_plain", result), {
    ...member,
    declared: "always",
  });
  // A second activation in the same process: it registered nothing through the seam, so the
  // family is not its to re-register.
  const other = registryPi();
  assert.deepEqual(deferDiscoveryFamily(other.pi), []);
  assert.equal(other.registrations.length, 0);

  const before = own.registrations.length;
  assert.deepEqual(deferDiscoveryFamily(own.pi), family);
  const redone = own.registrations.slice(before);
  assert.deepEqual(
    redone.map((def) => [def.name, def.exposure]),
    family.map((name) => [name, "deferred"]),
  );
  // The retained definition is re-registered: the same wrapped execute, only the exposure differs.
  const first = own.registrations.find((def) => def.name === "seam_family_a");
  assert.equal(redone[0]?.execute, first?.execute);
  // A re-emitted session_start: already deferred → nothing re-registered, same names returned.
  assert.deepEqual(deferDiscoveryFamily(own.pi), family);
  assert.equal(own.registrations.length, before + family.length);

  // A failing name is reported and skipped; the rest still defer.
  const flaky = registryPi("seam_family_a");
  for (const name of family) registerPerkTool(flaky.pi, fakeDefinition(name, result), member);
  const errors: unknown[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => errors.push(args.join(" "));
  try {
    assert.deepEqual(deferDiscoveryFamily(flaky.pi), ["seam_family_b"]);
  } finally {
    console.error = original;
  }
  assert.equal(errors.length, 1);
  assert.match(String(errors[0]), /^perk: could not defer seam_family_a — Error: host refused$/);
});

test("a live session: results gain only structuredContent (= details) and isError (ok === false, else the tool's own flag); exposure is derived", async () => {
  const terminal = {
    content: [{ type: "text" as const, text: "terminal done" }],
    details: { ok: true, n: 1 },
    terminate: true,
  };
  const failed = {
    content: [{ type: "text" as const, text: "fake failed: nope" }],
    details: { ok: false, error: "nope", error_type: "fake_error" },
  };
  const flagged = {
    content: [{ type: "text" as const, text: "odd but ok" }],
    details: { ok: true },
    isError: true,
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
        registerPerkTool(pi, fakeDefinition("seam_live_flagged", flagged), {
          stages: ["implement"],
          gated: "blocked",
          kind: "action",
        });
      },
    ],
  });
  try {
    const terminalResult = await h.invokeTool("seam_live_terminal", {});
    assert.deepEqual(terminalResult, { ...terminal, structuredContent: terminal.details });
    assert.equal(terminalResult.structuredContent, terminal.details, "the same reference");
    assert.equal(terminalResult.terminate, true);
    assert.equal("isError" in terminalResult, false, "absent stays absent");
    const failedResult = await h.invokeTool("seam_live_action", {});
    assert.deepEqual(failedResult, {
      ...failed,
      structuredContent: failed.details,
      isError: true,
    });
    const flaggedResult = await h.invokeTool("seam_live_flagged", {});
    assert.deepEqual(flaggedResult, { ...flagged, structuredContent: flagged.details });
    assert.equal(flaggedResult.isError, true, "a tool-set isError survives beside ok: true");
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
  // Keep the host discoverable between opt-in runs: the prose map sees only a static-string `name`
  // and treats a spread member as opaque. The authoritative check is the opt-in
  // `tests/test_prose_map.py` (never run by CI); this is the CI-gated tripwire.
  const source = readFileSync(new URL("./perkTool.ts", import.meta.url), "utf8");
  const hostFn = source.indexOf("export function registerLoadoutHost");
  const callStart = source.indexOf("pi.registerTool({", hostFn);
  assert.ok(hostFn >= 0 && callStart > hostFn, "the host registers through pi.registerTool");
  let depth = 0;
  let callEnd = -1;
  for (let i = callStart + "pi.registerTool".length; i < source.length; i++) {
    if (source[i] === "(") depth++;
    else if (source[i] === ")" && --depth === 0) {
      callEnd = i + 1;
      break;
    }
  }
  assert.ok(callEnd > callStart, "the host registration call closes");
  const registration = source.slice(callStart, callEnd);
  assert.ok(registration.includes('name: "perk_stage",'), "a literal host name");
  assert.equal(registration.includes("..."), false, "no spread in the host registration");
});

test("a real codemode script: an action soft failure rejects (catchable), an action success resolves to text, a query soft failure resolves to its structured value", async () => {
  const reg = await fauxModelRuntime();
  const h = await loadPerkSession({
    cwd: scaffoldRepo(),
    headful: false,
    model: reg.getModel(),
    modelRuntime: reg.modelRuntime,
    extraExtensions: [
      createCodemodeExtension({ mode: "on" }),
      (pi) => {
        registerPerkTool(
          pi,
          {
            name: "probe_action",
            label: "probe_action",
            description: "test-only action that soft-fails on demand",
            parameters: {
              type: "object",
              additionalProperties: false,
              properties: { fail: { type: "boolean" } },
            } as never,
            async execute(_id, params, _signal, _onUpdate, ctx) {
              if ((params as { fail?: boolean }).fail === true) {
                return failFor(ctx, "probe_action")("boom", "test_failure");
              }
              return ok("fine", {});
            },
          },
          { stages: [], gated: "allowed", kind: "action" },
        );
        registerPerkTool(
          pi,
          {
            name: "probe_query",
            label: "probe_query",
            description: "test-only query that always soft-fails",
            parameters: EMPTY_PARAMS,
            async execute(_id, _params, _signal, _onUpdate, ctx) {
              return failFor(ctx, "probe_query")("nope", "test_failure");
            },
          },
          { stages: [], gated: "allowed", kind: "query", result: { properties: {}, required: [] } },
        );
      },
    ],
  });
  try {
    h.session.setActiveToolsByName([
      ...new Set([...h.session.getActiveToolNames(), "codemode", "probe_action", "probe_query"]),
    ]);
    const script = [
      "const out = {};",
      "try { await tools.probe_action({ fail: true }); out.action = 'resolved'; }",
      "catch (e) { out.action = 'rejected: ' + e.message; }",
      "out.ok = await tools.probe_action({});",
      "out.query = await tools.probe_query({});",
      "return out;",
    ].join("\n");
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("codemode", { code: script })], {
        stopReason: "toolUse",
      }),
      fauxAssistantMessage([fauxText("done")], { stopReason: "stop" }),
    ]);
    await h.session.prompt("run the script");
    const codemodeResult = h.session.sessionManager
      .getBranch()
      .flatMap((entry) =>
        entry.type === "message" &&
        entry.message.role === "toolResult" &&
        entry.message.toolName === "codemode"
          ? [entry.message]
          : [],
      )
      .at(-1);
    assert.ok(codemodeResult !== undefined, "the codemode script ran");
    assert.equal(codemodeResult.isError, false, "the script itself completed");
    const text = codemodeResult.content.map((c) => (c.type === "text" ? c.text : "")).join("\n");
    const json = text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1);
    const out = JSON.parse(json) as { action?: string; ok?: unknown; query?: unknown };
    assert.deepEqual(Object.keys(out).sort(), ["action", "ok", "query"], "the script continued");
    assert.ok(out.action?.startsWith("rejected: "), `action: ${out.action}`);
    assert.ok(out.action?.includes("probe_action failed: boom"), `action: ${out.action}`);
    assert.equal(out.ok, "fine");
    assert.deepEqual(out.query, { ok: false, error: "nope", error_type: "test_failure" });
  } finally {
    h.dispose();
  }
});
