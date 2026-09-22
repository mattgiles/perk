// btw tests — the extracted pure core (offline): system-prompt footer stripping, text extraction,
// thread/tool-arg formatting, the gate-mirror `sideSessionTools` invariant, and the §5-conformed
// themed glyphs (`✗`/`▸`, never `❌`/`⚙`) under the D9 never-exceed-`width` law. Plus a registration
// smoke that binds the real perk extension and asserts `/btw` registers without throwing, and the
// seed-through-the-manager / registry-stream summary construction pins against the real SDK.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type AssistantMessage,
  type FauxResponseFactory,
  fauxAssistantMessage,
  fauxText,
  type Message,
} from "@earendil-works/pi-ai";
import { AgentSession, ModelRegistry, SessionManager } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import {
  AGENT_SCRATCH_CONTEXT_TYPE,
  renderAgentScratchBlock,
} from "../../substrate/agentScratch.ts";
import { registerToolGating } from "../../substrate/toolGating.ts";
import { fauxModelRuntime, loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import {
  BTW_SUMMARY_PROMPT,
  buildSeedMessages,
  createBtwAgentSession,
  liveModelRuntime,
  type ProjectedMessage,
  registerBtw,
  seedSessionManager,
  summarizeBtwThread,
} from "./btw.ts";
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

function seedOf(manager: SessionManager, thread: Parameters<typeof buildSeedMessages>[1] = []) {
  return buildSeedMessages(
    { sessionManager: manager } as unknown as Parameters<typeof buildSeedMessages>[0],
    thread,
  );
}

test("btw seed selection over the parent's live projection: keeps user turns + foreign customs; drops scratch customs, `system` messages, and context-edited (omitted) turns", () => {
  const manager = SessionManager.inMemory("/repo");
  const block = renderAgentScratchBlock("/repo", "RID");
  manager.appendCustomMessageEntry(AGENT_SCRATCH_CONTEXT_TYPE, block.content, false);
  manager.appendCustomMessageEntry("test:keep", "keep me", false);
  manager.appendMessage({ role: "user", content: "a main-session question", timestamp: 1 });
  manager.appendMessage({
    role: "system",
    content: "parent prompt",
    toolsAdded: [{ name: "bash", description: "run", parameters: { type: "object" } }],
    timestamp: 2,
  } as never);
  const omitted = manager.appendMessage({ role: "user", content: "omitted later", timestamp: 3 });
  manager.appendContextEdit(omitted, null);

  const seed = seedOf(manager);
  assert.deepEqual(
    seed.map((m) => (m.role === "custom" ? `custom:${m.customType}` : m.role)),
    ["custom:test:keep", "user"],
    "scratch, system and the omitted turn are gone; order is Pi's",
  );
  assert.equal(
    (seed[1] as { content?: unknown }).content,
    "a main-session question",
    "the surviving user turn is the live one, byte-for-byte",
  );
});

test("seedSessionManager persists one of every projected role as canonical entries; the side projection reproduces them in order (system absent)", () => {
  const seed: ProjectedMessage[] = [
    { role: "compactionSummary", summary: "earlier history", tokensBefore: 1234, timestamp: 10 },
    { role: "user", content: "a question", timestamp: 11 },
    {
      role: "assistant",
      content: [{ type: "text", text: "an answer" }],
      api: "openai-responses",
      provider: "faux",
      model: "faux-1",
      usage: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      },
      stopReason: "stop",
      timestamp: 12,
    },
    {
      role: "toolResult",
      toolCallId: "tc-1",
      toolName: "read",
      content: [{ type: "text", text: "file body" }],
      isError: false,
      timestamp: 13,
    },
    {
      role: "bashExecution",
      command: "echo hi",
      output: "hi",
      exitCode: 0,
      cancelled: false,
      truncated: false,
      timestamp: 14,
    },
    { role: "custom", customType: "test:keep", content: "keep me", display: false, timestamp: 15 },
    { role: "branchSummary", summary: "an abandoned branch", fromId: null, timestamp: 16 },
    { role: "system", content: "never side authority", timestamp: 17 } as ProjectedMessage,
  ];
  const manager = SessionManager.inMemory("/side");
  seedSessionManager(manager, seed);
  const projected = manager.buildSessionProjection().messages;
  assert.deepEqual(
    projected.map((m) => m.role),
    [
      "compactionSummary",
      "user",
      "assistant",
      "toolResult",
      "bashExecution",
      "custom",
      "branchSummary",
    ],
    "every role round-trips through its canonical entry kind; system is skipped",
  );
  const summary = projected[0];
  assert.ok(summary?.role === "compactionSummary");
  assert.equal(summary.summary, "earlier history");
  assert.equal(summary.tokensBefore, 1234);
  const branch = projected[6];
  assert.ok(branch?.role === "branchSummary");
  assert.equal(branch.summary, "an abandoned branch");
  // Message entries keep their bytes and timestamps.
  assert.deepEqual(projected[1], seed[1]);
  assert.deepEqual(projected[2], seed[2]);
  assert.deepEqual(projected[5], seed[5]);
  // An empty manager's root compaction captures no system message.
  assert.equal(
    projected.some((m) => m.role === "system"),
    false,
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
    getAllTools: () => [],
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

test("createBtwAgentSession seeds THROUGH the manager: the provider sees the seed before the prompt, no parent system content, and persistence continues normally (the reproduced-defect regression)", async () => {
  // Pi ≥ 0.87 rebuilds `context.messages` from the session manager on every request, so a seed
  // assigned onto `agent.state.messages` is silently dropped. Discriminating: the faux factory
  // captures the exact transcript the provider received.
  const reg = await fauxModelRuntime();
  let seen: Message[] | null = null;
  const factory: FauxResponseFactory = (context) => {
    seen = context.messages;
    return fauxAssistantMessage([fauxText("reply")], { stopReason: "stop" });
  };
  reg.setResponses([factory]);
  const seed: ProjectedMessage[] = [
    { role: "user", content: "seeded main-session fact", timestamp: 1 },
    { role: "custom", customType: "test:keep", content: "keep me", display: false, timestamp: 2 },
  ];
  const session = await createBtwAgentSession(fakeBtwCtx(reg), {
    thinkingLevel: "off",
    tools: ["read"],
    seed,
  });
  try {
    await session.prompt("q", { source: "extension" });
    assert.ok(seen, "the provider was never called");
    const transcript = seen as Message[];
    const texts = transcript.map((m) =>
      typeof m.content === "string"
        ? m.content
        : m.content
            .map((part) => ("text" in part && typeof part.text === "string" ? part.text : ""))
            .join(""),
    );
    const seededAt = texts.findIndex((t) => t.includes("seeded main-session fact"));
    const keptAt = texts.findIndex((t) => t.includes("keep me"));
    const promptAt = texts.indexOf("q");
    assert.ok(seededAt >= 0, "the seeded user turn reached the provider");
    assert.ok(keptAt > seededAt, "the seeded custom (converted by Pi) followed it");
    assert.ok(promptAt > keptAt, "the new prompt came AFTER the seed");
    assert.equal(transcript[keptAt]?.role, "user", "Pi converts a custom to a user turn");
    for (const m of transcript) {
      if (m.role !== "system") continue;
      assert.equal(
        typeof m.content === "string" && m.content.includes("You are the main session."),
        false,
        "no parent system content is seeded",
      );
    }
    // Subsequent persistence is normal: seed + prompt + reply live in the side session's state
    // (Pi also persists the side session's OWN structured system message on the first turn — it
    // carries the side prompt, never the parent's).
    const persisted = session.state.messages;
    assert.deepEqual(
      persisted.filter((m) => m.role !== "system").map((m) => m.role),
      ["user", "custom", "user", "assistant"],
    );
    const ownSystem = persisted.find((m) => m.role === "system");
    assert.ok(ownSystem && typeof ownSystem.content === "string");
    assert.equal(ownSystem.content.includes("Current date: 2026-01-01"), false);
  } finally {
    session.dispose();
  }
});

test("summarizeBtwThread: one tool-free request through the registry stream (BTW_SUMMARY_PROMPT alone, the formatted thread, no reasoning)", async () => {
  const reg = await fauxModelRuntime();
  const items = [
    {
      question: "q",
      answer: "a",
      timestamp: 1,
      provider: "faux",
      model: "faux-1",
      thinkingLevel: "off",
    },
  ] as const satisfies Parameters<typeof summarizeBtwThread>[1];
  let captured: { messages: Message[]; reasoning: unknown } | null = null;
  const factory: FauxResponseFactory = (context, options) => {
    captured = { messages: context.messages, reasoning: options?.reasoning };
    return fauxAssistantMessage([fauxText("the summary")], { stopReason: "stop" });
  };
  reg.setResponses([factory]);
  const ctx = fakeBtwCtx(reg);
  assert.equal(await summarizeBtwThread(ctx, items), "the summary");
  assert.ok(captured, "the provider was never called");
  const { messages, reasoning } = captured as { messages: Message[]; reasoning: unknown };
  const system = messages[0];
  assert.ok(system?.role === "system", "a leading system message carries the prompt");
  assert.equal(system.content, BTW_SUMMARY_PROMPT, "the system prompt is BTW_SUMMARY_PROMPT alone");
  assert.equal(system.toolsAdded, undefined, "no tools declared");
  assert.deepEqual(
    messages.slice(1).map((m) => ({ role: m.role, content: m.content })),
    [{ role: "user", content: formatThread(items) }],
    "exactly one user message: the formatted thread",
  );
  assert.equal(reasoning, undefined, "thinking off = reasoning omitted");

  // An error-stopped response rejects with its message (request-time auth failures ride here).
  reg.setResponses([
    fauxAssistantMessage([], { stopReason: "error", errorMessage: "No API key found" }),
  ]);
  await assert.rejects(summarizeBtwThread(ctx, items), /No API key found/);

  // An empty `stop` response yields the placeholder.
  reg.setResponses([fauxAssistantMessage([], { stopReason: "stop" })]);
  assert.equal(await summarizeBtwThread(ctx, items), "(No summary generated)");

  // An already-aborted signal rejects.
  const aborted = new AbortController();
  aborted.abort();
  reg.setResponses([fauxAssistantMessage([fauxText("late")], { stopReason: "stop" })]);
  await assert.rejects(summarizeBtwThread(ctx, items, { signal: aborted.signal }));

  // No model selected.
  await assert.rejects(
    summarizeBtwThread({ ...ctx, model: undefined } as never, items),
    /No active model selected/,
  );
});
