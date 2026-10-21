// The read-only floor against MCP, proven on REAL Pi sessions that register an MCP tool
// (contracts.md §8.40). Pi's own MCP builtin (`createMcpExtension`, loaded through the
// `builtin:mcp` path) connects to an in-memory server and registers `mcp__docs__search` with
// `sourceInfo.source: "builtin"` — a name outside the builtin rows, so perk classifies it
// `unknown`: hidden and blocked under the gate. Pi keeps MCP tools registered under a `tools`
// allowlist that names no `mcp__` entry and leaves codemode/deferred ones callable through nested
// execution, so a child def's `tools:` list is NOT an MCP exclusion — the `tool_call` backstop is
// the control. Every arm counts the server's `tools/call` requests: 0 under the floor and the
// gate (the escape oracle), ≥ 1 in the read-write controls (the vector physically reaches the
// server, so the block is not vacuous).
//
// Its own file so the probe fixture's catalog registration never enters the census process
// (`discoveryNested.test.ts`). The in-memory transport pair is Pi's own
// (`@earendil-works/pi-mcp/testing`, hoisted top-level by the lockfile — a test-only import; a
// nested layout would need `import.meta.resolve`-based loading).

import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { before, test } from "node:test";
import {
  type AgentToolResult,
  createCodemodeExtension,
  createMcpExtension,
  type InlineExtension,
} from "@earendil-works/pi-coding-agent";
import { createInMemoryTransportPair } from "@earendil-works/pi-mcp/testing";
import { registerPerkTool } from "../pi/perkTool.ts";
import {
  COHORT_SETTINGS,
  loadAt,
  type PerkSession,
  recordingRuntime,
  scaffoldRepo,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";

before(ensureToolCatalog);

const MCP_TOOL = "mcp__docs__search";
const PROBE = "fixture_mcp_probe";
const PARENT_ID = `call-${PROBE}`;
const BLOCKED = `perk read-only mode: ${MCP_TOOL} is blocked (tool not allowlisted).`;

/** The def-shaped allowlist: what pi-subagents forwards as the SDK `tools` for a perk report def. */
const DEF_TOOLS = ["read", "grep", "find", "ls", "bash"];

/** The floored report-child shape: a runner child carrying the read-only restriction binding. */
const CHILD_ENV = {
  PERK_RUN_ID: undefined,
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: JSON.stringify({
    "perk.parent-restrictions/1": { readOnly: true },
  }),
};

type Exposure = "codemode" | "deferred" | "direct" | "hidden";

/** One in-memory MCP server behind Pi's real MCP builtin, with its request counters. */
type McpFixture = {
  extension: InlineExtension;
  /** `tools/call` requests the server answered — the escape oracle. */
  calls: () => number;
  /** `tools/list` requests the server answered — proof the connection completed. */
  lists: () => number;
};

/**
 * Pi's MCP builtin over a test-written JSON-RPC responder: `initialize` (echoing the client's
 * protocol version), `tools/list` (one `search` tool), `tools/call` (counted, answers `ok`),
 * `ping`; notifications are ignored and unknown methods answer -32601.
 */
function mcpFixture(
  opts: { exposure?: Exposure; toolExposure?: Record<string, Exposure> } = {},
): McpFixture {
  let calls = 0;
  let lists = 0;
  const factory = createMcpExtension({
    loadConfig: () => ({
      servers: [
        {
          name: "docs",
          config: {
            url: "http://unused.invalid",
            ...(opts.exposure !== undefined ? { exposure: opts.exposure } : {}),
            ...(opts.toolExposure !== undefined ? { toolExposure: opts.toolExposure } : {}),
          },
          source: "fixture",
        },
      ],
      errors: [],
    }),
    createTransport: () => {
      const { client, server } = createInMemoryTransportPair();
      const reply = (id: unknown, body: Record<string, unknown>): void => {
        void server.send({ jsonrpc: "2.0", id, ...body } as never);
      };
      server.onMessage((raw) => {
        const message = raw as { id?: unknown; method?: string; params?: Record<string, unknown> };
        if (message.id === undefined || message.method === undefined) return;
        switch (message.method) {
          case "initialize":
            reply(message.id, {
              result: {
                protocolVersion: message.params?.protocolVersion,
                capabilities: { tools: {} },
                serverInfo: { name: "docs", version: "1.0.0" },
              },
            });
            return;
          case "tools/list":
            lists++;
            reply(message.id, {
              result: {
                tools: [
                  {
                    name: "search",
                    description: "Search the docs.",
                    inputSchema: {
                      type: "object",
                      properties: { query: { type: "string" } },
                      required: ["query"],
                    },
                  },
                ],
              },
            });
            return;
          case "tools/call":
            calls++;
            reply(message.id, { result: { content: [{ type: "text", text: "ok" }] } });
            return;
          case "ping":
            reply(message.id, { result: {} });
            return;
          default:
            reply(message.id, { error: { code: -32601, message: "method not found" } });
        }
      });
      void server.start();
      return client;
    },
    logPath: join(mkdtempSync(join(tmpdir(), "perk-mcp-floor-")), "mcp.log"),
  });
  return {
    extension: { name: "mcp", factory, builtin: true },
    calls: () => calls,
    lists: () => lists,
  };
}

/** Bounded wait on real timers (registration arrives after Pi's MCP builtin connects). */
async function until(done: () => boolean, label: string, ms = 5_000): Promise<void> {
  const start = Date.now();
  while (!done() && Date.now() - start < ms) {
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.ok(done(), `${label} within ${ms}ms`);
}

/** Wait for the server to list its tools, then for the registration to land (or not). */
async function connected(h: PerkSession, mcp: McpFixture): Promise<void> {
  await until(() => mcp.lists() > 0, "the MCP server listed its tools");
  await until(() => h.toolInfo(MCP_TOOL) !== null, `${MCP_TOOL} registered`);
}

type Observed = { isError: boolean; text: string };

/**
 * A gate-allowed perk action tool that calls `name` through Pi's nested-execution API
 * (`ctx.executeTool`) and records the outcome.
 */
function nestedProbe(observed: Observed[]): InlineExtension {
  return {
    name: "perk-mcp-probe",
    factory: (pi) => {
      registerPerkTool(
        pi,
        {
          name: PROBE,
          label: PROBE,
          description: "Call the MCP tool through nested execution (test-only).",
          parameters: { type: "object", additionalProperties: false, properties: {} } as never,
          async execute(_id, _params, _signal, _onUpdate, ctx) {
            const outcome = await ctx.executeTool(MCP_TOOL, { query: "x" });
            const result = outcome.result as AgentToolResult<unknown>;
            observed.push({
              isError: outcome.isError,
              text: result.content.map((c) => (c.type === "text" ? c.text : "")).join(""),
            });
            return { content: [{ type: "text" as const, text: "probed" }], details: {} };
          },
        },
        { stages: ["plan", "implement"], gated: "allowed", kind: "action" },
      );
    },
  };
}

/** Capture every nested `tool_call` (one carrying a `parentToolCallId`) and its verdict. */
function spyNested(h: PerkSession): { toolName: string; parent?: string; reason?: string }[] {
  const seen: { toolName: string; parent?: string; reason?: string }[] = [];
  const runner = h.session.extensionRunner;
  const emit = runner.emitToolCall.bind(runner);
  runner.emitToolCall = async (event) => {
    const result = await emit(event);
    const parent = (event as { parentToolCallId?: string }).parentToolCallId;
    if (parent !== undefined) {
      seen.push({
        toolName: event.toolName,
        parent,
        reason: (result as { reason?: string } | undefined)?.reason,
      });
    }
    return result;
  };
  return seen;
}

/** The text of the persisted tool result answering `toolCallId`. */
function toolResultText(h: PerkSession, toolCallId: string): string {
  const entries = h.session.sessionManager.getBranch() as unknown as {
    type: string;
    message?: { role?: string; toolCallId?: string; content?: { type: string; text?: string }[] };
  }[];
  const result = entries.find(
    (e) =>
      e.type === "message" &&
      e.message?.role === "toolResult" &&
      e.message.toolCallId === toolCallId,
  );
  assert.ok(result !== undefined, `a tool result answers ${toolCallId}`);
  return (result.message?.content ?? []).map((c) => c.text ?? "").join("");
}

// --- T1: the registration path on Pi's selector semantics ----------------------------------------

test("registration: a def-shaped allowlist naming no mcp__ entry keeps the MCP tool registered (builtin provenance), nested-callable and inactive; Pi's denylist removes it", async () => {
  // (a) The report-def shape: the allowlist filters Pi's builtins, never the MCP tool.
  {
    const mcp = mcpFixture();
    const h = await loadAt(scaffoldRepo(), {
      headful: false,
      tools: [...DEF_TOOLS, PROBE],
      extraExtensions: [mcp.extension, nestedProbe([])],
    });
    try {
      await connected(h, mcp);
      const info = h.session.getAllTools().find((t) => t.name === MCP_TOOL);
      assert.equal(info?.sourceInfo.source, "builtin");
      assert.equal(info?.sourceInfo.path, "builtin:mcp");
      // MCP's default `codemode` exposure registers as tool exposure `deferred` (Pi's
      // `toToolExposure`): never declared, callable through nested execution.
      assert.equal(info?.exposure, "deferred", "Pi's default MCP exposure, as a tool exposure");
      assert.ok(h.session.getCallableToolNames().includes(MCP_TOOL), "nested-callable");
      assert.ok(!h.session.getActiveToolNames().includes(MCP_TOOL), "inactive");
      const registered = h.session.getAllTools().map((t) => t.name);
      for (const name of ["edit", "write"]) {
        assert.ok(!registered.includes(name), `${name} filtered by the allowlist`);
      }
      // Not activatable either: without a matching allowlist entry it is codemode/search-only.
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), MCP_TOOL]);
      assert.ok(!h.session.getActiveToolNames().includes(MCP_TOOL), "never activated");
      assert.equal(mcp.calls(), 0);
    } finally {
      h.dispose();
    }
  }
  // (b) An allowlist that DOES name an mcp__ entry: registered and activatable.
  {
    const mcp = mcpFixture();
    const h = await loadAt(scaffoldRepo(), {
      headful: false,
      tools: [...DEF_TOOLS, PROBE, MCP_TOOL],
      extraExtensions: [mcp.extension, nestedProbe([])],
    });
    try {
      await connected(h, mcp);
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), MCP_TOOL]);
      assert.ok(h.session.getActiveToolNames().includes(MCP_TOOL), "activatable");
      assert.equal(mcp.calls(), 0);
    } finally {
      h.dispose();
    }
  }
  // (c) Pi SDK denylist control — what Pi's `--exclude-tools` does to a registered MCP tool. NOT
  // what a perk def's frontmatter `excludeTools` would do: pi-subagents applies a def's
  // `excludeTools` by exact-name set membership and forwards it to the SDK only when the def has
  // no explicit `tools:` allowlist; every perk def has one, so that key would be inert.
  {
    const mcp = mcpFixture();
    const h = await loadAt(scaffoldRepo(), {
      headful: false,
      excludeTools: ["mcp__*"],
      extraExtensions: [mcp.extension],
    });
    try {
      await until(() => mcp.lists() > 0, "the MCP server listed its tools");
      // Registration runs right after the listing; give it the same window it gets above.
      await new Promise((resolve) => setTimeout(resolve, 100));
      assert.equal(h.toolInfo(MCP_TOOL), null, "the denylist removes it");
      assert.equal(mcp.calls(), 0);
    } finally {
      h.dispose();
    }
  }
});

// --- T2: a direct call under the child floor and under the /plan gate ---------------------------

test("direct call: the floored report child and the /plan gate block the MCP tool as not allowlisted; read-write does not block", async () => {
  {
    const mcp = mcpFixture();
    const h = await loadAt(scaffoldRepo(), {
      headful: false,
      env: CHILD_ENV,
      tools: [...DEF_TOOLS, PROBE],
      extraExtensions: [mcp.extension, nestedProbe([])],
    });
    try {
      assert.equal(h.workflowState().mode, "read-only");
      await connected(h, mcp);
      assert.deepEqual(await h.emitToolCall(MCP_TOOL, { query: "x" }), {
        block: true,
        reason: BLOCKED,
      });
      // Pi's resource tools are MCP names too (registered only for servers with resources).
      if (h.toolInfo("list_mcp_resources") !== null) {
        assert.equal((await h.emitToolCall("list_mcp_resources", {}))?.block, true);
      }
      assert.equal(mcp.calls(), 0);
    } finally {
      h.dispose();
    }
  }
  for (const mode of ["read-only", "read-write"] as const) {
    const mcp = mcpFixture();
    const h = await staged("plan", mode, { headful: false, extraExtensions: [mcp.extension] });
    try {
      assert.equal(h.workflowState().mode, mode);
      await connected(h, mcp);
      const verdict = await h.emitToolCall(MCP_TOOL, { query: "x" });
      if (mode === "read-only") assert.deepEqual(verdict, { block: true, reason: BLOCKED });
      else assert.equal(verdict?.block, undefined, "read-write never blocks it");
      assert.equal(mcp.calls(), 0, "the hook path never reaches the server");
    } finally {
      h.dispose();
    }
  }
});

// --- T3: a nested call under the child floor and under the /plan gate ----------------------------

test("nested call: ctx.executeTool on the MCP tool meets the backstop (parent call id kept) under the child floor and the /plan gate; the read-write controls reach the server", async () => {
  type Arm = {
    label: string;
    load: (
      mcp: McpFixture,
      observed: Observed[],
      rt: Awaited<ReturnType<typeof recordingRuntime>>,
    ) => Promise<PerkSession>;
    gated: boolean;
  };
  const arms: Arm[] = [
    {
      label: "the floored report child",
      gated: true,
      load: (mcp, observed, rt) =>
        loadAt(scaffoldRepo(), {
          headful: false,
          model: rt.reg.getModel(),
          modelRuntime: rt.reg.modelRuntime,
          env: CHILD_ENV,
          tools: [...DEF_TOOLS, PROBE],
          extraExtensions: [mcp.extension, nestedProbe(observed)],
        }),
    },
    {
      label: "the /plan gate",
      gated: true,
      load: (mcp, observed, rt) =>
        staged("plan", "read-only", {
          headful: false,
          model: rt.reg.getModel(),
          modelRuntime: rt.reg.modelRuntime,
          extraExtensions: [mcp.extension, nestedProbe(observed)],
        }),
    },
    {
      label: "the read-write /plan landing",
      gated: false,
      load: (mcp, observed, rt) =>
        staged("plan", "read-write", {
          headful: false,
          model: rt.reg.getModel(),
          modelRuntime: rt.reg.modelRuntime,
          extraExtensions: [mcp.extension, nestedProbe(observed)],
        }),
    },
    {
      label: "the bare unscoped session",
      gated: false,
      load: (mcp, observed, rt) =>
        loadAt(scaffoldRepo(), {
          headful: false,
          model: rt.reg.getModel(),
          modelRuntime: rt.reg.modelRuntime,
          env: { PERK_RUN_ID: undefined },
          extraExtensions: [mcp.extension, nestedProbe(observed)],
        }),
    },
  ];
  for (const arm of arms) {
    const mcp = mcpFixture();
    const observed: Observed[] = [];
    const rt = await recordingRuntime();
    const h = await arm.load(mcp, observed, rt);
    const seen = spyNested(h);
    try {
      await connected(h, mcp);
      assert.ok(h.session.getCallableToolNames().includes(MCP_TOOL), `${arm.label}: callable`);
      rt.callThenStop(PROBE, {});
      await h.session.prompt("probe the MCP tool");
      assert.equal(observed.length, 1, `${arm.label}: the probe ran`);
      if (arm.gated) {
        assert.equal(observed[0]?.isError, true, `${arm.label}: ${observed[0]?.text}`);
        assert.deepEqual(seen, [{ toolName: MCP_TOOL, parent: PARENT_ID, reason: BLOCKED }]);
        assert.equal(mcp.calls(), 0, `${arm.label}: the server was never reached`);
      } else {
        assert.equal(observed[0]?.isError, false, `${arm.label}: ${observed[0]?.text}`);
        assert.equal(observed[0]?.text, "ok");
        assert.deepEqual(seen, [{ toolName: MCP_TOOL, parent: PARENT_ID, reason: undefined }]);
        assert.equal(mcp.calls(), 1, `${arm.label}: the nested vector reaches the server`);
      }
    } finally {
      h.dispose();
    }
  }
});

// --- T4: a direct model call and the model-facing presentation ----------------------------------

test("direct model call: read-write declares and runs a direct-exposure MCP tool; the /plan gate hides its declaration and blocks the scripted call", async () => {
  for (const mode of ["read-write", "read-only"] as const) {
    const mcp = mcpFixture({ toolExposure: { search: "direct" } });
    const rt = await recordingRuntime();
    const h = await staged("plan", mode, {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      extraExtensions: [mcp.extension],
    });
    try {
      await connected(h, mcp);
      assert.equal(h.toolInfo(MCP_TOOL)?.exposure, "direct");
      rt.callThenStop(MCP_TOOL, { query: "x" });
      await h.session.prompt("search the docs");
      const declared = rt.requests[0]?.tools ?? [];
      const text = toolResultText(h, `call-${MCP_TOOL}`);
      if (mode === "read-write") {
        assert.ok(declared.includes(MCP_TOOL), "declared to the model");
        assert.equal(text, "ok");
        assert.equal(mcp.calls(), 1);
      } else {
        assert.ok(!declared.includes(MCP_TOOL), "the loadout host hides the declaration");
        assert.equal(text, BLOCKED);
        assert.equal(mcp.calls(), 0);
      }
    } finally {
      h.dispose();
    }
  }
});

// --- T5: a codemode script under the /plan gate (the codemode lift) -----------------------------

test("codemode script: in a cohort /plan gate the MCP builtin's auto-activated codemode stays on (lifted), and its script's MCP call meets the backstop with the codemode parent id; read-write reaches the server", async () => {
  const script = `try {
  const value = await tools.${MCP_TOOL}({ query: "x" });
  return "MCP-RESULT " + JSON.stringify({ ok: true, value });
} catch (error) {
  return "MCP-RESULT " + JSON.stringify({ ok: false, message: String(error.message) });
}`;
  for (const mode of ["read-only", "read-write"] as const) {
    const mcp = mcpFixture();
    const rt = await recordingRuntime();
    const h = await staged("plan", mode, {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      extraExtensions: [
        mcp.extension,
        toolSearch(),
        { name: "codemode", factory: createCodemodeExtension(), builtin: true },
      ],
      settings: COHORT_SETTINGS,
    });
    const seen = spyNested(h);
    try {
      await connected(h, mcp);
      assert.ok(
        h.session.getActiveToolNames().includes("codemode"),
        `${mode}: Pi's MCP builtin auto-activated codemode (and the gate kept it)`,
      );
      rt.callThenStop("codemode", { code: script });
      await h.session.prompt("search the docs from a script");
      const text = toolResultText(h, "call-codemode");
      const match = /MCP-RESULT (\{.*\})/s.exec(text);
      assert.ok(match?.[1] !== undefined, text);
      const outcome = JSON.parse(match[1]) as { ok: boolean; message?: string };
      if (mode === "read-only") {
        assert.equal(outcome.ok, false, text);
        assert.ok(outcome.message?.includes(BLOCKED), outcome.message);
        assert.deepEqual(seen, [{ toolName: MCP_TOOL, parent: "call-codemode", reason: BLOCKED }]);
        assert.equal(mcp.calls(), 0, "the server was never reached");
      } else {
        assert.equal(outcome.ok, true, text);
        assert.deepEqual(seen, [
          { toolName: MCP_TOOL, parent: "call-codemode", reason: undefined },
        ]);
        assert.equal(mcp.calls(), 1, "the script's call reaches the server");
      }
    } finally {
      h.dispose();
    }
  }
});
