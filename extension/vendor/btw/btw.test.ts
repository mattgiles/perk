// btw tests — the extracted pure core (offline): system-prompt footer stripping, text extraction,
// thread/tool-arg formatting, the gate-mirror `sideSessionTools` invariant, and the §5-conformed
// themed glyphs (`✗`/`▸`, never `❌`/`⚙`) under the D9 never-exceed-`width` law. Plus a registration
// smoke that binds the real perk extension and asserts `/btw` registers without throwing.

import assert from "node:assert/strict";
import { test } from "node:test";
import { type AssistantMessage, fauxAssistantMessage, fauxText } from "@earendil-works/pi-ai";
import { AgentSession, ModelRegistry, SessionManager } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import {
  AGENT_SCRATCH_CONTEXT_TYPE,
  renderAgentScratchBlock,
} from "../../substrate/agentScratch.ts";
import { registerToolGating } from "../../substrate/toolGating.ts";
import { fauxModelRuntime, loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import { buildSeedMessages, createBtwAgentSession, liveModelRuntime, registerBtw } from "./btw.ts";
import {
  extractEventAssistantText,
  extractText,
  formatThread,
  formatToolArgs,
  lastAssistantMessage,
  renderErrorLine,
  renderToolCallLines,
  sideSessionTools,
  stripDynamicSystemPromptFooter,
  type ThemeLike,
  type ToolCallInfo,
} from "./core.ts";

// A passthrough theme: `fg` returns the text verbatim, so width math is real (D9 sweeps).
const passthrough: ThemeLike = { fg: (_color, text) => text };
// A tagging theme: `fg` wraps `[color]text` so a test can assert glyph + §5 color together.
const tagging: ThemeLike = { fg: (color, text) => `[${color}]${text}` };

test("stripDynamicSystemPromptFooter strips the date/cwd trailers (incl. the perk `Current date:` form) and trims", () => {
  const base = "You are a helpful agent.\n\nDo good work.";

  // perk's live prompt footer form: `Current date:` (the conformance fix).
  assert.equal(
    stripDynamicSystemPromptFooter(
      `${base}\nCurrent date: 2026-06-16\nCurrent working directory: /tmp/x`,
    ),
    base,
  );
  // The upstream `Current date and time:` form still strips.
  assert.equal(
    stripDynamicSystemPromptFooter(
      `${base}\nCurrent date and time: 2026-06-16 10:00\nCurrent working directory: /tmp/x`,
    ),
    base,
  );
  // A lone working-directory trailer strips too.
  assert.equal(stripDynamicSystemPromptFooter(`${base}\nCurrent working directory: /tmp/x`), base);
  // No trailer: just trims.
  assert.equal(stripDynamicSystemPromptFooter(`${base}\n`), base);
});

test("extractText joins only the text parts, trimmed", () => {
  assert.equal(
    extractText([
      { type: "text", text: "hello" },
      { type: "tool_use", text: "ignored" },
      { type: "text", text: "world" },
    ]),
    "hello\nworld",
  );
  assert.equal(extractText([]), "");
});

test("extractEventAssistantText returns assistant text and ignores non-assistant / non-array", () => {
  assert.equal(
    extractEventAssistantText({
      role: "assistant",
      content: [
        { type: "text", text: "a" },
        { type: "text", text: "b" },
      ],
    }),
    "a\nb",
  );
  assert.equal(extractEventAssistantText({ role: "user", content: [] }), "");
  assert.equal(extractEventAssistantText(null), "");
  assert.equal(extractEventAssistantText({ role: "assistant", content: "nope" }), "");
});

test("lastAssistantMessage returns the last assistant message or null", () => {
  const messages = [
    { role: "user", id: 1 },
    { role: "assistant", id: 2 },
    { role: "user", id: 3 },
    { role: "assistant", id: 4 },
  ];
  assert.deepEqual(lastAssistantMessage(messages), { role: "assistant", id: 4 });
  assert.equal(lastAssistantMessage([{ role: "user", id: 1 }]), null);
  assert.equal(lastAssistantMessage([]), null);
});

test("formatThread renders the `User:`/`Assistant:` separator form", () => {
  assert.equal(
    formatThread([
      { question: " q1 ", answer: " a1 " },
      { question: "q2", answer: "a2" },
    ]),
    "User: q1\nAssistant: a1\n\n---\n\nUser: q2\nAssistant: a2",
  );
});

test("formatToolArgs truncates the salient argument per tool", () => {
  assert.equal(formatToolArgs("read", { path: "/a/b.ts" }), "/a/b.ts");
  assert.equal(formatToolArgs("bash", { command: "ls -la" }), "ls -la");
  // Truncates a long first-line bash command to ≤ 50 cells.
  const long = formatToolArgs("bash", { command: `echo ${"x".repeat(80)}` });
  assert.ok(visibleWidth(long) <= 50, `bash args not truncated: width ${visibleWidth(long)}`);
  // Default branch: first string value, first line only.
  assert.equal(formatToolArgs("mytool", { q: "first\nsecond" }), "first");
  assert.equal(formatToolArgs("read", null), "");
});

test("sideSessionTools mirrors perk's read-only gate (the gate-mirror invariant)", () => {
  assert.deepEqual(sideSessionTools(true), ["read"]);
  assert.deepEqual(sideSessionTools(false), ["read", "bash", "edit", "write"]);
});

test("renderToolCallLines uses the §5-conformed themed glyphs (✓ success / ▸ accent / ✗ error)", () => {
  const calls: ToolCallInfo[] = [
    { toolCallId: "1", toolName: "read", args: "/a.ts", status: "done" },
    { toolCallId: "2", toolName: "bash", args: "ls", status: "running" },
    { toolCallId: "3", toolName: "edit", args: "/b.ts", status: "error" },
  ];
  const [done, running, errored] = renderToolCallLines(calls, tagging, 200);

  // done → ✓ success
  assert.ok(done?.includes("[success]✓ "), `done glyph wrong: ${done}`);
  // running → ▸ accent (the charter-time `⚙` is conformed)
  assert.ok(running?.includes("[accent]▸ "), `running glyph wrong: ${running}`);
  assert.ok(!running?.includes("⚙"), "running line still uses the non-conformed ⚙");
  // error → ✗ error
  assert.ok(errored?.includes("[error]✗ "), `error glyph wrong: ${errored}`);
});

test("renderErrorLine uses the §5-conformed ✗ (never the non-conformed ❌)", () => {
  const line = renderErrorLine(tagging, "boom");
  assert.ok(line.includes("[error]✗ boom"), `error line wrong: ${line}`);
  assert.ok(!line.includes("❌"), "error line still uses the non-conformed ❌");
});

test("renderToolCallLines obeys the D9 never-exceed-width law across a width sweep", () => {
  const calls: ToolCallInfo[] = [
    { toolCallId: "1", toolName: "bash", args: "x".repeat(60), status: "running" },
    { toolCallId: "2", toolName: "read", args: "/some/long/path/file.ts", status: "done" },
  ];
  for (let width = 1; width <= 60; width++) {
    for (const line of renderToolCallLines(calls, passthrough, width)) {
      assert.ok(
        visibleWidth(line) <= width,
        `line exceeds width ${width}: ${visibleWidth(line)} (${JSON.stringify(line)})`,
      );
    }
  }
});

test("binding the perk extension registers /btw and does not throw on session_start", async () => {
  const cwd = scaffoldRepo();
  const perk = await loadPerkSession({ cwd });
  try {
    assert.ok(
      perk.registeredCommands().includes("btw"),
      "the /btw command was not registered by the perk extension",
    );
  } finally {
    perk.dispose();
  }
});

// --- run-owned scratch delivery + live-runtime session construction -----------------------------

test("btw seed filtering removes every main-session scratch custom before side-session seeding", () => {
  const manager = SessionManager.inMemory("/repo");
  const block = renderAgentScratchBlock("/repo", "RID");
  manager.appendCustomMessageEntry(AGENT_SCRATCH_CONTEXT_TYPE, block.content, false);
  manager.appendCustomMessageEntry("test:keep", "keep me", false);
  const seed = buildSeedMessages(
    { sessionManager: manager } as unknown as Parameters<typeof buildSeedMessages>[0],
    [],
  );
  assert.equal(
    seed.some(
      (message) => (message as { customType?: string }).customType === AGENT_SCRATCH_CONTEXT_TYPE,
    ),
    false,
  );
  assert.equal(
    seed.some((message) => (message as { customType?: string }).customType === "test:keep"),
    true,
    "non-scratch seed context survives",
  );
});

/** A minimal ExtensionContext slice for `createBtwAgentSession` (model + facade + system prompt). */
function fakeBtwCtx(reg: {
  modelRuntime: unknown;
  getModel(): unknown;
}): Parameters<typeof createBtwAgentSession>[0] {
  return {
    model: reg.getModel(),
    modelRegistry: new ModelRegistry(reg.modelRuntime as never),
    getSystemPrompt: () => "You are the main session.\nCurrent date: 2026-01-01",
  } as unknown as Parameters<typeof createBtwAgentSession>[0];
}

test("createBtwAgentSession wires one scratch block into the effective side prompt", async () => {
  const reg = await fauxModelRuntime();
  const block = renderAgentScratchBlock("/repo", "RID");
  const session = await createBtwAgentSession(fakeBtwCtx(reg), {
    thinkingLevel: "off",
    tools: sideSessionTools(false),
    appendSystemPrompt: ["Read-write BTW side session.", block.content],
  });
  try {
    assert.equal(session.systemPrompt.split(block.marker).length - 1, 1);
    assert.match(session.systemPrompt, /Read-write BTW side session\./);
  } finally {
    session.dispose();
  }
});

test("btw retries scratch availability; a controller floor invalidates the side cache and suppresses provisioning", async (t) => {
  const observations: { id: string; tools: string[] }[] = [];
  const prompt = AgentSession.prototype.prompt;
  t.mock.method(
    AgentSession.prototype,
    "prompt",
    function (this: AgentSession, ...args: Parameters<AgentSession["prompt"]>) {
      observations.push({ id: this.sessionId, tools: this.getActiveToolNames() });
      return prompt.apply(this, args);
    },
  );
  const reg = await fauxModelRuntime();
  reg.setResponses([
    fauxAssistantMessage([fauxText("first")], { stopReason: "stop" }),
    fauxAssistantMessage([fauxText("second")], { stopReason: "stop" }),
    fauxAssistantMessage([fauxText("third")], { stopReason: "stop" }),
    fauxAssistantMessage([fauxText("read only")], { stopReason: "stop" }),
    fauxAssistantMessage([fauxText("still read only")], { stopReason: "stop" }),
  ]);
  const block = renderAgentScratchBlock("/repo", "RID");
  let available = false;
  let directoryPresent = false;
  let resolutions = 0;
  const agentScratch = {
    resolve: () => {
      resolutions += 1;
      if (!available) return null;
      directoryPresent = true;
      return block;
    },
  };
  let readOnly = false;
  let handler:
    | ((args: string, ctx: Parameters<typeof createBtwAgentSession>[0]) => Promise<void>)
    | undefined;
  const pi = {
    appendEntry: () => {},
    getActiveTools: () => ["read", "write"],
    setActiveTools: () => {},
    getThinkingLevel: () => "off",
    on: () => {},
    registerCommand: (
      _name: string,
      command: {
        handler: (args: string, ctx: Parameters<typeof createBtwAgentSession>[0]) => Promise<void>;
      },
    ) => {
      handler = command.handler;
    },
  } as unknown as Parameters<typeof registerBtw>[0];
  const gating = registerToolGating(pi, () => readOnly);
  registerBtw(pi, gating, agentScratch);
  assert.ok(handler);
  const ctx = {
    ...fakeBtwCtx(reg),
    hasUI: false,
    isIdle: () => true,
    sessionManager: SessionManager.inMemory("/repo"),
    ui: {},
    waitForIdle: async () => {},
  } as unknown as Parameters<typeof createBtwAgentSession>[0];

  await handler("first question", ctx);
  assert.equal(resolutions, 1);
  assert.equal(directoryPresent, false, "failed provisioning remains unguided");

  available = true;
  await handler("second question", ctx);
  assert.equal(resolutions, 2, "a later turn retries provisioning");
  assert.equal(directoryPresent, true);

  directoryPresent = false;
  await handler("third question", ctx);
  assert.equal(resolutions, 3, "a cached side session still repairs scratch before its next turn");
  assert.equal(directoryPresent, true);

  readOnly = true;
  await handler("read-only question", ctx);
  assert.equal(resolutions, 3, "floor-backed side turns never resolve scratch");
  assert.deepEqual(observations[3]?.tools, ["read"]);
  assert.notEqual(observations[3]?.id, observations[2]?.id, "floor changed the cache key");
  resolutions = 0;
  gating.exit();
  gating.syncFromState("read-write", undefined);
  await handler("still read-only question", ctx);
  assert.equal(resolutions, 0, "weakening attempts never provision scratch");
  assert.equal(
    observations[4]?.id,
    observations[3]?.id,
    "effective floor preserves the read-only cache key",
  );
  assert.deepEqual(observations[4]?.tools, ["read"]);
});

test("liveModelRuntime recovers the live runtime from the real ModelRegistry facade", async () => {
  // Pins the (compile-time-)private `runtime` field the probe depends on: if pi renames it,
  // this fails loudly against the pinned facade instead of btw silently degrading to a
  // default-created runtime with divergent credentials.
  const reg = await fauxModelRuntime();
  const facade = new ModelRegistry(reg.modelRuntime as never);
  assert.equal(liveModelRuntime({ modelRegistry: facade } as never), reg.modelRuntime);
});

test("liveModelRuntime degrades to undefined on a facade without a stream-bearing runtime", () => {
  assert.equal(liveModelRuntime({ modelRegistry: {} } as never), undefined);
  assert.equal(liveModelRuntime({ modelRegistry: { runtime: {} } } as never), undefined);
});

test("createBtwAgentSession (side-chat shape): a reply streams through the LIVE runtime", async () => {
  // Discriminating: the faux provider exists ONLY on the injected live runtime — if the
  // construction stopped passing `modelRuntime`, the default-created runtime could not resolve
  // provider `faux` and the prompt would surface an error stopReason instead of the reply.
  const reg = await fauxModelRuntime();
  reg.setResponses([fauxAssistantMessage([fauxText("side reply")], { stopReason: "stop" })]);
  const session = await createBtwAgentSession(fakeBtwCtx(reg), {
    thinkingLevel: "off",
    tools: sideSessionTools(true),
  });
  try {
    await session.prompt("hello from the main session", { source: "extension" });
    const response = lastAssistantMessage(session.state.messages) as AssistantMessage | null;
    assert.ok(response, "no assistant response captured");
    assert.equal(response.stopReason, "stop");
    assert.equal(extractText(response.content), "side reply");
  } finally {
    session.dispose();
  }
});

test("createBtwAgentSession (summary shape): the summary prompt rides the LIVE runtime too", async () => {
  const reg = await fauxModelRuntime();
  reg.setResponses([fauxAssistantMessage([fauxText("the summary")], { stopReason: "stop" })]);
  const session = await createBtwAgentSession(fakeBtwCtx(reg), {
    thinkingLevel: "off",
    tools: [],
    appendSystemPrompt: ["Summarize this side conversation."],
  });
  try {
    await session.prompt(formatThread([{ question: "q", answer: "a" }]), {
      source: "extension",
    });
    const response = lastAssistantMessage(session.state.messages) as AssistantMessage | null;
    assert.ok(response, "no assistant response captured");
    assert.equal(response.stopReason, "stop");
    assert.equal(extractText(response.content), "the summary");
  } finally {
    session.dispose();
  }
});
