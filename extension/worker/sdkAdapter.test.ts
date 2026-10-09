// Fully-offline coverage for the private SDK adapter's owned helpers: the SDK→perk event
// translation (translateEvent), the drive-session handle's bind/rebind structural contract, the
// worker's fixed extension inputs (the policy hook, the builtin identity) and bind-time error
// formatting, and the model selection ladder's pure steps (resolveWorkerModel and
// selectWorkerModel over stub runtimes — deterministic, no ModelRuntime.create host reads), plus
// the native-provider saved-credential case over a REAL hermetic ModelRuntime (in-memory
// credential store, no models.json). The seam-side policy fold and the drive orchestration are
// covered in stageExecution.test.ts.

import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  createAgentSession,
  createCodemodeExtension,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { loadSdkPiAi } from "../testing/harness.ts";
import { MODEL_CALL_REFUSAL_PREFIX } from "./modelCallPolicy.ts";
import {
  createDriveSession,
  type DriveEvent,
  type DriveSessionLike,
  type DriveTurn,
  formatExtensionError,
  formatWorkerSettingsLine,
  resolveWorkerModel,
  type StageEvent,
  selectWorkerModel,
  translateEvent,
  workerBuiltinExtensions,
  workerPolicyExtension,
} from "./sdkAdapter.ts";

// --- pure: translateEvent -------------------------------------------------------------------------

test("translateEvent: turn_end → turn_ended with the clamped input+output sum", () => {
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 10, output: 5 } },
    }),
    { kind: "turn_ended", freshTokens: 15, modelError: null },
  );
  // Negative components clamp to 0; absent usage sums to 0.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 3, output: -9 } },
    }),
    { kind: "turn_ended", freshTokens: 3, modelError: null },
  );
  assert.deepEqual(translateEvent({ type: "turn_end", message: { role: "assistant" } }), {
    kind: "turn_ended",
    freshTokens: 0,
    modelError: null,
  });
});

test("translateEvent: usage.reasoning is NOT summed — it is a subset of output on every pi-ai provider", () => {
  // The double-count pin: pi-ai normalizes `reasoning` as a breakdown already inside `output`
  // (anthropic thinking_tokens, google thoughtsTokenCount, openai reasoning_tokens — verified
  // @ 0.80.5), so the fresh-work sum stays `input + output` exactly.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 10, output: 20, reasoning: 15 } },
    }),
    { kind: "turn_ended", freshTokens: 30, modelError: null },
  );
});

test("translateEvent: turn_end sums every tool result's reported usage onto the assistant's", () => {
  // Pi folds a tool's nested calls onto its result's usage before turn_end, so the tool results
  // are the one place tool-driven model usage is read.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 10, output: 5 } },
      toolResults: [
        { usage: { input: 700, output: 300 } },
        {}, // a tool result without usage adds 0
        { usage: { input: 20, output: -4, reasoning: 50 } }, // negatives clamp; reasoning excluded
      ],
    }),
    { kind: "turn_ended", freshTokens: 15 + 1_000 + 20, modelError: null },
  );
  // An error/aborted assistant turn carries no tool results: the assistant usage alone.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 4, output: 2 } },
      toolResults: [],
    }),
    { kind: "turn_ended", freshTokens: 6, modelError: null },
  );
  // Tool usage counts even when the assistant message carries none.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant" },
      toolResults: [{ usage: { input: 3, output: 4 } }],
    }),
    { kind: "turn_ended", freshTokens: 7, modelError: null },
  );
});

test("translateEvent: tool_execution_end → tool_ended (details.ok wins, !isError fallback, error text)", () => {
  assert.deepEqual(
    translateEvent({
      type: "tool_execution_end",
      toolName: "submit",
      // The structured shape every perk result carries: isError false beside details.ok true.
      isError: false,
      result: {
        details: { ok: true, pr: { number: 1, url: "u" } },
        structuredContent: { ok: true, pr: { number: 1, url: "u" } },
      },
    }),
    {
      kind: "tool_ended",
      tool: "submit",
      ok: true,
      details: { ok: true, pr: { number: 1, url: "u" } },
      errorText: null,
    },
  );
  // No details.ok boolean → fall back to !isError; no details block → null.
  assert.deepEqual(
    translateEvent({ type: "tool_execution_end", toolName: "read", isError: false }),
    { kind: "tool_ended", tool: "read", ok: true, details: null, errorText: null },
  );
  // Failure carries pre-cap error text: details.error → string result → generic fallback.
  assert.deepEqual(
    translateEvent({
      type: "tool_execution_end",
      toolName: "submit",
      isError: true,
      result: { details: { ok: false, error: "boom" } },
    }),
    {
      kind: "tool_ended",
      tool: "submit",
      ok: false,
      details: { ok: false, error: "boom" },
      errorText: "boom",
    },
  );
  assert.deepEqual(
    translateEvent({ type: "tool_execution_end", toolName: "bash", isError: true }),
    {
      kind: "tool_ended",
      tool: "bash",
      ok: false,
      details: null,
      errorText: "tool bash failed",
    },
  );
});

test("translateEvent: failed-tool error text precedence — details.error → string → text content → generic", () => {
  const errorTextOf = (result: unknown): string | null => {
    const translated = translateEvent({
      type: "tool_execution_end",
      toolName: "codemode",
      isError: true,
      result,
    });
    assert.ok(translated?.kind === "tool_ended");
    return translated.errorText;
  };
  const content = [
    { type: "text", text: "Script failed" },
    { type: "image", data: "x", mimeType: "image/png" },
    { type: "text", text: "Script error:\nReferenceError" },
  ];
  // details.error wins over text content.
  assert.equal(errorTextOf({ content, details: { error: "from details" } }), "from details");
  // A bare string result wins over the generic fallback.
  assert.equal(errorTextOf("bare failure"), "bare failure");
  // Text content: every text block, joined by newlines (a blocked call's reason, a script error).
  assert.equal(
    errorTextOf({ content, details: {} }),
    "Script failed\nScript error:\nReferenceError",
  );
  // An empty details.error / no text blocks fall through to the generic fallback.
  assert.equal(
    errorTextOf({ content: [{ type: "image" }], details: { error: "" } }),
    "tool codemode failed",
  );
  assert.equal(errorTextOf({ content: [{ type: "text", text: "" }] }), "tool codemode failed");
  assert.equal(errorTextOf({ content: "not an array" }), "tool codemode failed");
});

test("translateEvent: an error turn_end carries its error; a normal turn carries null", () => {
  // Pi's turn_end carries the turn's assistant message for error turns too (no tool results).
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: {
        role: "assistant",
        stopReason: "error",
        errorMessage: "overloaded",
        usage: { input: 8, output: 0 },
      },
      toolResults: [],
    }),
    { kind: "turn_ended", freshTokens: 8, modelError: { message: "overloaded" } },
  );
  assert.deepEqual(
    translateEvent({ type: "turn_end", message: { role: "assistant", stopReason: "error" } }),
    { kind: "turn_ended", freshTokens: 0, modelError: { message: "model error" } },
  );
  for (const stopReason of ["stop", "toolUse", "aborted", "length"]) {
    const translated = translateEvent({
      type: "turn_end",
      message: { role: "assistant", stopReason },
    });
    assert.ok(translated?.kind === "turn_ended");
    assert.equal(translated.modelError, null, `${stopReason} is not a model error`);
  }
});

test("translateEvent: message_end is no longer observed (the error rides turn_end); unobserved types → null", () => {
  for (const stopReason of ["error", "stop"]) {
    assert.equal(
      translateEvent({
        type: "message_end",
        message: { role: "assistant", stopReason, errorMessage: "net" },
      }),
      null,
    );
  }
  assert.equal(translateEvent({ type: "agent_settled" }), null);
  // Hoisted const: `aborted` is not a `DriveEvent` field (the worker deliberately ignores it), so
  // a plain object (not a typed literal) carries Pi's settle flag past structural typing.
  const settledAborted = { type: "agent_settled", aborted: true };
  assert.equal(translateEvent(settledAborted), null, "Pi's abort flag never becomes a verdict");
  assert.equal(translateEvent({ type: "compaction_start", reason: "threshold" }), null);
  assert.equal(translateEvent({ type: "auto_retry_end" }), null);
});

test("translateEvent: compaction_end → compaction_ended with the summarization usage (clamped), reason carried", () => {
  assert.deepEqual(
    translateEvent({
      type: "compaction_end",
      reason: "threshold",
      result: { summary: "s", usage: { input: 900, output: 100, reasoning: 40 } },
    }),
    { kind: "compaction_ended", freshTokens: 1_000, reason: "threshold" },
  );
  assert.deepEqual(
    translateEvent({
      type: "compaction_end",
      reason: "overflow",
      result: { summary: "s", usage: { input: 50, output: -7 } },
    }),
    { kind: "compaction_ended", freshTokens: 50, reason: "overflow" },
  );
  // An aborted or failed compaction carries no result (Pi persists no entry): 0 tokens.
  assert.deepEqual(translateEvent({ type: "compaction_end", reason: "manual" }), {
    kind: "compaction_ended",
    freshTokens: 0,
    reason: "manual",
  });
  // A result without usage (an extension-supplied compaction may omit it) also counts 0.
  assert.deepEqual(
    translateEvent({ type: "compaction_end", reason: "threshold", result: { summary: "s" } }),
    { kind: "compaction_ended", freshTokens: 0, reason: "threshold" },
  );
});

test("translateEvent: auto_retry_start → model_retrying with its fields", () => {
  assert.deepEqual(
    translateEvent({
      type: "auto_retry_start",
      attempt: 2,
      maxAttempts: 3,
      delayMs: 4_000,
      errorMessage: "rate limit",
    }),
    { kind: "model_retrying", attempt: 2, maxAttempts: 3, delayMs: 4_000, message: "rate limit" },
  );
});

test("StageEvent: the drive vocabulary is exactly these kinds (compile-time pin)", () => {
  // `satisfies` checks both directions: a missing kind and an extra one (e.g. a standalone
  // model-error kind — a turn's provider error rides `turn_ended`) both fail type-checking.
  const kinds = {
    turn_ended: true,
    tool_ended: true,
    compaction_ended: true,
    model_retrying: true,
  } satisfies Record<StageEvent["kind"], true>;
  assert.deepEqual(Object.keys(kinds), [
    "turn_ended",
    "tool_ended",
    "compaction_ended",
    "model_retrying",
  ]);
});

test("formatWorkerSettingsLine: the merged compaction/retry posture as one stderr line", () => {
  assert.equal(
    formatWorkerSettingsLine(
      { enabled: true, reserveTokens: 16_384, keepRecentTokens: 20_000 },
      { enabled: true, maxRetries: 3, baseDelayMs: 2_000 },
    ),
    "perk worker: compaction on (reserve 16384, keep 20000); retry on (max 3, base 2000 ms)",
  );
  assert.equal(
    formatWorkerSettingsLine(
      { enabled: false, reserveTokens: 60_000, keepRecentTokens: 0 },
      { enabled: false, maxRetries: 1, baseDelayMs: 1 },
    ),
    "perk worker: compaction off (reserve 60000, keep 0); retry off (max 1, base 1 ms)",
  );
  assert.equal(
    formatWorkerSettingsLine(
      { enabled: true, reserveTokens: 1, keepRecentTokens: 2 },
      { enabled: false, maxRetries: 0, baseDelayMs: 5 },
    ),
    "perk worker: compaction on (reserve 1, keep 2); retry off (max 0, base 5 ms)",
  );
});

// --- the drive-session handle: bind/rebind structural --------------------------------------------

class FakeSession implements DriveSessionLike {
  bindCalls = 0;
  abortCalls = 0;
  branch: unknown[] = [];
  private listeners: ((e: DriveEvent) => void)[] = [];
  private readonly script: (emit: (e: DriveEvent) => void) => Promise<void> | void;
  constructor(script: (emit: (e: DriveEvent) => void) => Promise<void> | void) {
    this.script = script;
  }
  async bindExtensions(): Promise<void> {
    this.bindCalls++;
  }
  subscribe(listener: (e: DriveEvent) => void): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }
  private emit = (e: DriveEvent): void => {
    for (const l of this.listeners) l(e);
  };
  async prompt(): Promise<void> {
    await this.script(this.emit);
  }
  async abort(): Promise<void> {
    this.abortCalls++;
  }
  dispose(): void {}
  sessionManager = {
    getBranch: (): unknown[] => this.branch,
  };
}

test("createDriveSession: rebindIfReplaced unsubscribes the prior listener (no double-count) and re-binds", async () => {
  const seen: StageEvent[] = [];
  const turn = (emit: (e: DriveEvent) => void) =>
    emit({ type: "turn_end", message: { role: "assistant" } });
  const s1 = new FakeSession(turn);
  const s2 = new FakeSession(turn);
  const runtime: { session: DriveSessionLike; dispose(): void } = {
    session: s1,
    dispose() {},
  };
  const handle = createDriveSession(runtime, (e) => seen.push(e));
  await handle.bind();
  assert.equal(await handle.rebindIfReplaced(), false, "an unchanged session never rebinds");

  runtime.session = s2; // the mid-drive replacement
  assert.equal(await handle.rebindIfReplaced(), true, "a replaced session rebinds");
  // s1's listener is detached: driving s1 must NOT reach the (single) listener.
  await s1.prompt();
  assert.equal(seen.length, 0, "prior listener was unsubscribed on rebind");
  // The live binding is s2: driving it reaches the listener exactly once — translated.
  await s2.prompt();
  assert.deepEqual(seen, [{ kind: "turn_ended", freshTokens: 0, modelError: null }]);
  assert.equal(s1.bindCalls, 1);
  assert.equal(s2.bindCalls, 1);
  await handle.dispose();
});

test("createDriveSession: abort is idempotent — repeated trips launch exactly one SDK abort", async () => {
  const session = new FakeSession(() => {});
  const handle = createDriveSession({ session, dispose() {} }, () => {});
  handle.abort();
  handle.abort();
  handle.abort();
  assert.equal(session.abortCalls, 1, "later aborts are no-ops once one is retained");
  await handle.dispose();
});

// --- the turn-boundary gate over the agent's finishTurn ------------------------------------------

/** A fake agent whose `finishTurn` is the session's own hook (records calls, returns `inner`). */
function gatedSession(inner: unknown): {
  session: FakeSession & { agent: { finishTurn?(turn: DriveTurn, signal?: AbortSignal): unknown } };
  innerCalls: DriveTurn[];
  sessionHook: (turn: DriveTurn) => unknown;
} {
  const innerCalls: DriveTurn[] = [];
  const sessionHook = (turn: DriveTurn): unknown => {
    innerCalls.push(turn);
    return inner;
  };
  const session = Object.assign(new FakeSession(() => {}), { agent: { finishTurn: sessionHook } });
  return { session, innerCalls, sessionHook };
}

const usageTurn = (input: number, output: number): DriveTurn => ({
  message: { role: "assistant", usage: { input, output, reasoning: 99 } },
});

test("createDriveSession: the gate runs the session's finishTurn first, then ends the run on the seam's verdict", async () => {
  const { session, innerCalls } = gatedSession(undefined);
  const asked: number[] = [];
  const handle = createDriveSession(
    { session, dispose() {} },
    () => {},
    (turn) => {
      asked.push(turn.freshTokens);
      return turn.freshTokens >= 10;
    },
  );
  await handle.bind();
  const finishTurn = session.agent.finishTurn;
  assert.ok(finishTurn);
  assert.equal(
    await finishTurn(usageTurn(2, 3)),
    undefined,
    "below the verdict: normal scheduling",
  );
  assert.deepEqual(await finishTurn(usageTurn(4, 6)), { action: "end" });
  assert.deepEqual(asked, [5, 10], "fresh tokens = input + output (reasoning excluded)");
  assert.equal(innerCalls.length, 2, "the session's own hook (the turn_end boundary) always runs");
  await handle.dispose();
});

test("createDriveSession: an earlier `end` decision stands and a `continue` survives a false verdict", async () => {
  const ended = gatedSession({ action: "end" });
  let asked = 0;
  const h1 = createDriveSession(
    { session: ended.session, dispose() {} },
    () => {},
    () => {
      asked += 1;
      return false;
    },
  );
  await h1.bind();
  assert.deepEqual(await ended.session.agent.finishTurn?.(usageTurn(1, 1)), { action: "end" });
  assert.equal(asked, 0, "the verdict is not consulted once the run already ends");
  await h1.dispose();

  const continued = gatedSession({ action: "continue" });
  const h2 = createDriveSession(
    { session: continued.session, dispose() {} },
    () => {},
    () => false,
  );
  await h2.bind();
  assert.deepEqual(await continued.session.agent.finishTurn?.(usageTurn(1, 1)), {
    action: "continue",
  });
  await h2.dispose();
});

test("createDriveSession: dispose and rebind restore the session's own finishTurn", async () => {
  const first = gatedSession(undefined);
  const second = gatedSession(undefined);
  const runtime: { session: DriveSessionLike; dispose(): void } = {
    session: first.session,
    dispose() {},
  };
  const handle = createDriveSession(
    runtime,
    () => {},
    () => true,
  );
  await handle.bind();
  assert.notEqual(first.session.agent.finishTurn, first.sessionHook, "installed on bind");
  runtime.session = second.session;
  assert.equal(await handle.rebindIfReplaced(), true);
  assert.equal(
    first.session.agent.finishTurn,
    first.sessionHook,
    "the replaced session is restored",
  );
  assert.notEqual(second.session.agent.finishTurn, second.sessionHook, "the replacement is gated");
  await handle.dispose();
  assert.equal(second.session.agent.finishTurn, second.sessionHook, "dispose restores it");
});

test("createDriveSession: no verdict or no agent leaves the session untouched", async () => {
  const { session, sessionHook } = gatedSession(undefined);
  const ungated = createDriveSession({ session, dispose() {} }, () => {});
  await ungated.bind();
  assert.equal(session.agent.finishTurn, sessionHook, "no verdict → no wrapper");
  await ungated.dispose();

  const agentless = new FakeSession(() => {});
  const handle = createDriveSession(
    { session: agentless, dispose() {} },
    () => {},
    () => true,
  );
  await handle.bind();
  assert.equal("agent" in agentless, false, "an agentless (fake) session is never patched");
  await handle.dispose();
});

test("createDriveSession: the gate decides on assistant + tool-result usage — the same sum turn_ended carries", async () => {
  const { session } = gatedSession(undefined);
  const asked: number[] = [];
  const handle = createDriveSession(
    { session, dispose() {} },
    () => {},
    (turn) => {
      asked.push(turn.freshTokens);
      return turn.freshTokens >= 1_000;
    },
  );
  await handle.bind();
  const finishTurn = session.agent.finishTurn;
  assert.ok(finishTurn);
  // Below the cap on the assistant alone; the tool result's usage carries it over.
  const turn: DriveTurn = {
    message: { role: "assistant", usage: { input: 5, output: 5 } },
    toolResults: [{ usage: { input: 600, output: 390 } }, {}],
  };
  assert.deepEqual(await finishTurn(turn), { action: "end" }, "the combined sum ends the run");
  assert.equal(
    await finishTurn({ message: turn.message, toolResults: [] }),
    undefined,
    "the assistant alone stays below the cap",
  );
  assert.deepEqual(asked, [1_000, 10]);
  // The turn_ended translation of the same turn carries the identical sum.
  assert.deepEqual(translateEvent({ type: "turn_end", ...turn }), {
    kind: "turn_ended",
    freshTokens: 1_000,
    modelError: null,
  });
  await handle.dispose();
});

// --- the worker's hidden policy extension ------------------------------------------------------

/** Load `workerPolicyExtension` into a fake `pi` and return its one `tool_call` handler. */
function policyToolCallHandler(): (event: {
  toolName: string;
  input: Record<string, unknown>;
}) => unknown {
  const extension = workerPolicyExtension();
  assert.ok(typeof extension === "object", "a named inline extension");
  assert.equal(extension.name, "perk-worker-policy");
  assert.equal(extension.hidden, true, "hidden from the startup Extensions list");
  const handlers = new Map<string, (event: never) => unknown>();
  const fakePi = {
    on(event: string, handler: (event: never) => unknown) {
      assert.equal(handlers.has(event), false, `one ${event} handler`);
      handlers.set(event, handler);
    },
  };
  void extension.factory(fakePi as never);
  assert.deepEqual([...handlers.keys()], ["tool_call"], "the extension registers one hook");
  const handler = handlers.get("tool_call");
  assert.ok(handler);
  return (event) => handler({ type: "tool_call", toolCallId: "c1", ...event } as never);
}

test("workerPolicyExtension: a codemode script naming a metered model call is blocked with the typed reason", () => {
  const onToolCall = policyToolCallHandler();
  const images = onToolCall({
    toolName: "codemode",
    input: { code: "await models.generateImages(m, { input: [] });" },
  }) as { block?: boolean; reason?: string; terminate?: boolean };
  assert.equal(images.block, true);
  assert.ok(images.reason?.startsWith(`${MODEL_CALL_REFUSAL_PREFIX}image_generation)`));
  assert.equal(images.terminate, undefined, "a refusal never terminates the batch");

  const classify = onToolCall({
    toolName: "codemode",
    input: { code: "return await models.classify(ref, ctx);" },
  }) as { block?: boolean; reason?: string };
  assert.equal(classify.block, true);
  assert.ok(classify.reason?.startsWith(`${MODEL_CALL_REFUSAL_PREFIX}classifier)`));
});

test("workerPolicyExtension: plain scripts, other tools and non-string code pass untouched", () => {
  const onToolCall = policyToolCallHandler();
  assert.equal(onToolCall({ toolName: "codemode", input: { code: 'return "ok";' } }), undefined);
  assert.equal(
    onToolCall({ toolName: "bash", input: { command: "echo models.classify(x)" } }),
    undefined,
    "only codemode calls are screened",
  );
  assert.equal(
    onToolCall({ toolName: "codemode", input: { code: 42 } }),
    undefined,
    "a non-string script is left to the tool's own validation",
  );
  assert.equal(onToolCall({ toolName: "codemode", input: {} }), undefined);
});

// --- the worker's builtin tool extensions --------------------------------------------------------

/** A tool definition as a fake `pi` records it from `registerTool`. */
type RegisteredDefinition = { name: string; description: string; defaultActive?: boolean };

/** Run an extension factory against a recording fake `pi`; return the tools it registered. */
function registeredBy(factory: (pi: never) => unknown): RegisteredDefinition[] {
  const tools: RegisteredDefinition[] = [];
  const fakePi = {
    registerTool(definition: RegisteredDefinition) {
      tools.push(definition);
    },
    appendEntry() {},
    getAllTools: () => [],
    getSettings: () => ({}),
  };
  void factory(fakePi as never);
  return tools;
}

test("workerBuiltinExtensions: Pi's codemode then tool-search with the CLI's builtin identity, no MCP", () => {
  const entries = workerBuiltinExtensions().map((entry) => {
    assert.ok(typeof entry === "object", "a named inline extension");
    return entry;
  });
  assert.deepEqual(
    entries.map((e) => e.name),
    ["codemode", "tool-search"],
    "the CLI's order; Pi's mcp and llama.cpp builtins are not supplied",
  );
  for (const entry of entries) {
    assert.equal(entry.builtin, true, `${entry.name} loads as builtin:${entry.name}`);
    assert.equal(entry.replaceable, true, `a project registration of ${entry.name} replaces it`);
    assert.equal(entry.hidden, undefined, "builtin identity alone (Pi hides builtins itself)");
  }
  const [codemode, toolSearch] = entries;
  assert.ok(codemode && toolSearch);
  const codemodeTools = registeredBy(codemode.factory);
  assert.deepEqual(
    codemodeTools.map((t) => [t.name, t.defaultActive]),
    [["codemode", false]],
    "registered inactive: only the resolved defaultTools activate it",
  );
  assert.deepEqual(
    registeredBy(toolSearch.factory).map((t) => [t.name, t.defaultActive]),
    [["tool_search", false]],
  );
  // The worker's codemode is built without the `models` namespace (WORKER_CODEMODE_MODELS): its
  // description carries no `models` reference, which a `models: true` codemode does (the control).
  const control = registeredBy(createCodemodeExtension({ models: true }));
  // Pi names `models` in one Globals line of the codemode description (the type section lives in
  // its codemode docs), so the Globals line is the marker.
  const modelsGlobal = "- `models`:";
  assert.ok(control[0]?.description.includes(modelsGlobal), "control: models:true is observable");
  assert.ok(
    !codemodeTools[0]?.description.includes(modelsGlobal),
    "the worker's codemode: models off",
  );
});

test("formatExtensionError: Pi's ExtensionError renders path, event and message; other values fall back", () => {
  assert.equal(
    formatExtensionError({
      extensionPath: "/wt/.pi/extensions/registrar.ts",
      event: "register_mcp_server",
      error: 'MCP server "inert" is registered, but no loaded extension connects MCP servers',
      stack: "Error: ...",
    }),
    "perk worker: extension error — /wt/.pi/extensions/registrar.ts (register_mcp_server): " +
      'MCP server "inert" is registered, but no loaded extension connects MCP servers',
  );
  assert.equal(
    formatExtensionError(new Error("boom")),
    "perk worker: extension error — Error: boom",
    "not the ExtensionError shape: String(err)",
  );
  assert.equal(
    formatExtensionError({ extensionPath: "/x.ts", event: 1, error: "e" }),
    "perk worker: extension error — [object Object]",
  );
  assert.equal(formatExtensionError(null), "perk worker: extension error — null");
});

// --- resolveWorkerModel — `--model` resolves with pi's CLI semantics -----------------------------

// `resolveCliModel` consults `getModels()` + `hasConfiguredAuth()` (NOT the availability
// snapshot): unauthenticated models resolve by design, matching an interactive pi launch.
const SONNET = { provider: "anthropic", id: "claude-sonnet-4-5" };
const HAIKU = { provider: "anthropic", id: "claude-haiku-4-5" };

function stubRuntime(models: unknown[]): ModelRuntime {
  return { getModels: () => models, hasConfiguredAuth: () => true } as never;
}

test("resolveWorkerModel: exact provider/id resolves", () => {
  const r = resolveWorkerModel("anthropic/claude-sonnet-4-5", stubRuntime([SONNET, HAIKU]));
  assert.ok(r.ok);
  assert.equal(r.model, SONNET);
  assert.equal(r.thinkingLevel, undefined);
  assert.equal(r.warning, undefined);
});

test("resolveWorkerModel: a bare partial id resolves (fuzzy matching parity)", () => {
  const r = resolveWorkerModel("sonnet", stubRuntime([SONNET, HAIKU]));
  assert.ok(r.ok);
  assert.equal(r.model, SONNET);
});

test("resolveWorkerModel: a `:thinking` suffix yields the model + the parsed level", () => {
  const r = resolveWorkerModel("anthropic/claude-sonnet-4-5:high", stubRuntime([SONNET, HAIKU]));
  assert.ok(r.ok);
  assert.equal(r.model, SONNET);
  assert.equal(r.thinkingLevel, "high");
});

test("resolveWorkerModel: an unknown pattern ⇒ ok:false with an error (fail-fast, never guess)", () => {
  const r = resolveWorkerModel("totally-unknown-model-zzz", stubRuntime([SONNET, HAIKU]));
  assert.equal(r.ok, false);
  assert.equal(typeof (r as { error: unknown }).error, "string");
});

test("resolveWorkerModel: undefined pattern ⇒ ok with no model (the SDK deferral)", () => {
  const r = resolveWorkerModel(undefined, stubRuntime([SONNET]));
  assert.deepEqual(r, { ok: true, model: undefined, thinkingLevel: undefined, warning: undefined });
});

test("resolveWorkerModel: '' ≡ omitted (the documented bare `--model` CLI tolerance)", () => {
  // workerMain's flag grammar yields "" for a bare `--model`; the equivalence is deliberate and
  // pinned here — both arms defer the pick to the SDK at session creation.
  const r = resolveWorkerModel("", stubRuntime([SONNET]));
  assert.deepEqual(r, { ok: true, model: undefined, thinkingLevel: undefined, warning: undefined });
});

// --- selectWorkerModel — selection + admission over a post-registration runtime ------------------

/** A stub over exactly the runtime reads the ladder makes (registration already happened). */
function selectionRuntime(opts: {
  models?: unknown[];
  available?: unknown[];
  configured?: boolean;
  check?: unknown;
  registered?: string[];
  onCheck?: () => void;
}): ModelRuntime {
  return {
    getModels: () => opts.models ?? [],
    getAvailableSnapshot: () => opts.available ?? [],
    hasConfiguredAuth: () => opts.configured ?? false,
    checkAuth: async () => {
      opts.onCheck?.();
      return opts.check;
    },
    getRegisteredProviderIds: () => opts.registered ?? [],
  } as never;
}

test("selectWorkerModel: no pattern and an empty snapshot ⇒ no_model naming the registered providers", async () => {
  const pick = await selectWorkerModel(
    undefined,
    selectionRuntime({ registered: ["ext-a", "ext-b"] }),
  );
  assert.equal(pick.ok, false);
  assert.ok(!pick.ok);
  assert.equal(pick.type, "no_model");
  assert.ok(pick.message.includes("after extension registration"));
  assert.ok(pick.message.includes("extension-registered providers: ext-a, ext-b."));

  const none = await selectWorkerModel(undefined, selectionRuntime({}));
  assert.ok(!none.ok);
  assert.ok(none.message.includes("extension-registered providers: none."));
});

test("selectWorkerModel: no pattern and a non-empty snapshot ⇒ a deferred pick (never pre-pinned)", async () => {
  // The availability snapshot sorts alphabetically, so pre-pinning [0] would select the OLDEST
  // model of the first provider (a since-removed dated claude-3-5-haiku pin 404'd a remote drive).
  const pick = await selectWorkerModel(
    undefined,
    selectionRuntime({ available: [{ id: "claude-3-5-haiku-20241022" }, SONNET] }),
  );
  assert.deepEqual(pick, {
    ok: true,
    model: undefined,
    thinkingLevel: undefined,
    warning: undefined,
  });
});

test("selectWorkerModel: '' ≡ absent on both deferred arms", async () => {
  const empty = await selectWorkerModel("", selectionRuntime({}));
  assert.ok(!empty.ok);
  assert.equal(empty.type, "no_model");
  const available = await selectWorkerModel("", selectionRuntime({ available: [SONNET] }));
  assert.ok(available.ok);
  assert.equal(available.model, undefined);
});

test("selectWorkerModel: an explicit model on a configured provider ⇒ ok, no async auth check", async () => {
  let checks = 0;
  const pick = await selectWorkerModel(
    "anthropic/claude-sonnet-4-5:high",
    selectionRuntime({ models: [SONNET, HAIKU], configured: true, onCheck: () => checks++ }),
  );
  assert.ok(pick.ok);
  assert.equal(pick.model, SONNET);
  assert.equal(pick.thinkingLevel, "high");
  assert.equal(checks, 0, "a configured provider short-circuits the async check");
});

test("selectWorkerModel: an explicit model whose provider fails both auth reads ⇒ model_auth", async () => {
  const pick = await selectWorkerModel(
    "anthropic/claude-sonnet-4-5",
    selectionRuntime({ models: [SONNET], configured: false, check: undefined }),
  );
  assert.ok(!pick.ok);
  assert.equal(pick.type, "model_auth");
  for (const fragment of ["anthropic/claude-sonnet-4-5", "'anthropic'", "auth.json", "--model"]) {
    assert.ok(pick.message.includes(fragment), `the guidance names ${fragment}`);
  }
});

test("selectWorkerModel: an unconfigured provider whose async auth check passes ⇒ ok (Pi prompt-time parity)", async () => {
  const pick = await selectWorkerModel(
    "anthropic/claude-sonnet-4-5",
    selectionRuntime({ models: [SONNET], configured: false, check: { type: "api_key" } }),
  );
  assert.ok(pick.ok);
  assert.equal(pick.model, SONNET);
});

test("selectWorkerModel: an unknown pattern ⇒ model_not_found carrying the resolver's text", async () => {
  const pick = await selectWorkerModel(
    "totally-unknown-model-zzz",
    selectionRuntime({ models: [SONNET, HAIKU], configured: true }),
  );
  assert.ok(!pick.ok);
  assert.equal(pick.type, "model_not_found");
  assert.ok(
    pick.message.startsWith(
      "model 'totally-unknown-model-zzz' not found in the registry (resolved after extension registration): ",
    ),
  );
  assert.ok(pick.message.includes("totally-unknown-model-zzz"));
  assert.ok(pick.message.endsWith("."));
  assert.ok(!pick.message.endsWith(".."), "the embedded resolver sentence is re-terminated once");
});

// --- the selection ladder over a REAL ModelRuntime — the native-provider saved-credential case ---
//
// Each runtime is built inline so nothing sits between `registerNativeProvider` and the first
// snapshot read. On Pi ≤ 0.99.1 `registerNativeProvider` set no provisional entry, so initial
// model selection could read an unconfigured snapshot and fall back or warn (upstream #9962);
// Pi 0.99.2 marks a provider with a stored credential configured synchronously
// (`markProvisionallyConfigured`). The faux provider carries TWO models so a saved non-first
// default is distinguishable from the first-available fallback. These pins drive the runtime
// directly; the production order (extension registration BEFORE selection) is pinned through the
// real factory in stageExecutionE2e.test.ts.

async function twoModelFaux() {
  const piAi = await loadSdkPiAi();
  const faux = piAi.fauxProvider({ models: [{ id: "faux-1" }, { id: "faux-2" }] });
  const providerId = faux.provider.id;
  const [first, second] = faux.models.map((model) => model.id);
  assert.ok(first && second && first !== second, "the faux provider exposes two distinct models");
  return { piAi, faux, providerId, first, second };
}

type NativeProvider = Parameters<ModelRuntime["registerNativeProvider"]>[0];

async function runtimeOver(
  piAi: Awaited<ReturnType<typeof loadSdkPiAi>>,
  storedCredentialFor: string | undefined,
): Promise<ModelRuntime> {
  const store = new piAi.InMemoryCredentialStore();
  if (storedCredentialFor !== undefined) {
    await store.modify(storedCredentialFor, async () => ({ type: "api_key", key: "test-key" }));
  }
  const runtime = await ModelRuntime.create({
    credentials: store,
    modelsPath: null,
    refreshOnCreate: false,
  });
  // Populates the snapshot's `storedProviders` from the credential store.
  await runtime.refresh({ allowNetwork: false });
  return runtime;
}

function availableIds(runtime: ModelRuntime, providerId: string): string[] {
  return runtime
    .getAvailableSnapshot()
    .filter((model) => model.provider === providerId)
    .map((model) => model.id);
}

test("selectWorkerModel (real runtime): a stored-credential native provider is configured synchronously on registration", async () => {
  const { piAi, faux, providerId, first, second } = await twoModelFaux();
  const runtime = await runtimeOver(piAi, providerId);
  runtime.registerNativeProvider(faux.provider as NativeProvider);
  // Synchronous reads — no await between registration and the snapshot.
  assert.deepEqual(availableIds(runtime, providerId), [first, second]);
  assert.equal(runtime.hasConfiguredAuth(providerId), true);
  const pick = await selectWorkerModel(undefined, runtime);
  assert.ok(pick.ok, "no no_model fail-fast");
  assert.equal(pick.model, undefined, "the pick stays deferred to the SDK");
});

test("selectWorkerModel (real runtime) control: without a stored credential the provider is available only after the async refresh", async () => {
  const { piAi, faux, providerId, first, second } = await twoModelFaux();
  const runtime = await runtimeOver(piAi, undefined);
  runtime.registerNativeProvider(faux.provider as NativeProvider);
  assert.deepEqual(availableIds(runtime, providerId), [], "not available synchronously");
  assert.equal(runtime.hasConfiguredAuth(providerId), false);
  await runtime.refresh({ allowNetwork: false });
  assert.deepEqual(availableIds(runtime, providerId), [first, second]);
});

test("initial model selection (real runtime): a saved non-first default is honoured; no default falls back to the first", async () => {
  const { piAi, faux, providerId, first, second } = await twoModelFaux();
  const runtime = await runtimeOver(piAi, providerId);
  runtime.registerNativeProvider(faux.provider as NativeProvider);
  const dir = mkdtempSync(join(tmpdir(), "perk-sdk-adapter-"));
  const sessionFor = async (settings: Parameters<typeof SettingsManager.inMemory>[0]) => {
    const settingsManager = SettingsManager.inMemory(settings);
    // Never reloaded: a fresh DefaultResourceLoader is empty by construction, and
    // createAgentSession reloads only a loader it builds itself.
    const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, settingsManager });
    const { session } = await createAgentSession({
      cwd: dir,
      agentDir: dir,
      modelRuntime: runtime,
      settingsManager,
      sessionManager: SessionManager.inMemory(dir),
      resourceLoader,
    });
    return session;
  };
  const sessions: { dispose(): void }[] = [];
  try {
    const withDefault = await sessionFor({ defaultProvider: providerId, defaultModel: second });
    sessions.push(withDefault);
    const withoutDefault = await sessionFor({});
    sessions.push(withoutDefault);
    assert.deepEqual([withDefault.model?.provider, withDefault.model?.id], [providerId, second]);
    assert.deepEqual(
      [withoutDefault.model?.provider, withoutDefault.model?.id],
      [providerId, first],
      "the control arm takes the first-available fallback",
    );
  } finally {
    for (const session of sessions) session.dispose();
    rmSync(dir, { recursive: true, force: true });
  }
});
