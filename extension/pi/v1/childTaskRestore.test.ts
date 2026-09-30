// The report child's task-restore hooks, end-to-end over a REAL bound AgentSession (offline): the
// floored runner env binds perk; compacted branches are planted and read through the test-owned
// `SessionManager` (the contextEvidence.test.ts pattern — a user `Task: …` message, an assistant
// kept tail, and a compaction that evicts the task); the gate is driven through the runner's own
// `tool_call` emission; and two faux-runtime turns exercise Pi's REAL post-run compaction — the
// accepted-report ordering that must never restart a lane, and its not-yet-reported control. The
// ordered verdict table itself is pinned in substrate/childTaskRestore.test.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import {
  structuredOutputHoldReason,
  TASK_RESTORE_MAX_ATTEMPTS,
  TASK_RESTORE_MAX_BYTES,
  TASK_RESTORE_PREAMBLE,
  TASK_RESTORE_TYPE,
} from "../../substrate/childTaskRestore.ts";
import {
  fauxModelRuntime,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
} from "../../testing/harness.ts";

type Harness = Awaited<ReturnType<typeof loadPerkSession>>;

const runnerPacket = {
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: '{"perk.parent-restrictions/1":{"readOnly":true}}',
};

const PROMPT =
  "Task: Angle: grounding\n\n<untrusted_draft>\n# Move the ingest domain code\n\n" +
  "## Steps\n\n1. Move `ingest/`.\n</untrusted_draft>";

const HELD = structuredOutputHoldReason({ kind: "held" });

/** Append any runtime message through the real API (shape-agnostic cast at the test boundary). */
function appendMessage(manager: SessionManager, message: Record<string, unknown>): string {
  return manager.appendMessage(message as never);
}

function user(content: unknown): Record<string, unknown> {
  return { role: "user", content, timestamp: Date.now() };
}

function assistant(text: string): Record<string, unknown> {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    api: "test",
    provider: "test",
    model: "test",
    usage: {},
    stopReason: "stop",
    timestamp: Date.now(),
  };
}

/** The task, then an assistant kept tail, then a compaction that evicts the task. */
function plantCompacted(manager: SessionManager, prompt: string): void {
  appendMessage(manager, user(prompt));
  compactKeepingTail(manager);
}

/** Append an assistant turn and a compaction keeping only it — whatever came before is evicted. */
function compactKeepingTail(manager: SessionManager): void {
  const keptId = appendMessage(manager, assistant("working through the draft"));
  manager.appendCompaction("the lane reviewed sections 1-3 so far", keptId, 1000);
}

interface RestoreEntry {
  id: string;
  content: unknown;
  display: boolean;
}

function restoreEntries(manager: SessionManager): RestoreEntry[] {
  const found: RestoreEntry[] = [];
  for (const entry of manager.getBranch()) {
    if (entry.type === "custom_message" && entry.customType === TASK_RESTORE_TYPE) {
      found.push({ id: entry.id, content: entry.content, display: entry.display });
    }
  }
  return found;
}

function restored(prompt: string): unknown {
  return [{ type: "text", text: `${TASK_RESTORE_PREAMBLE}\n\n${prompt}` }];
}

function compactionCount(manager: SessionManager): number {
  return manager.getBranch().filter((entry) => entry.type === "compaction").length;
}

async function session(
  opts: { floor?: boolean; extraExtensions?: ((pi: ExtensionAPI) => void)[] } = {},
): Promise<{ h: Harness; manager: SessionManager }> {
  const cwd = scaffoldRepo();
  const manager = SessionManager.inMemory(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: opts.floor === false ? {} : runnerPacket,
    headful: false,
    extraExtensions: opts.extraExtensions,
  });
  return { h, manager };
}

const report = (h: Harness) => h.emitToolCall("structured_output", { value: {} });
const compacted = (h: Harness) => h.emitLifecycle({ type: "session_compact" });

/**
 * A stand-in for pi-subagents' `structured_output`: `capture` returns its success shape
 * (`terminate: true`), `reject` throws the way a schema rejection does.
 */
function fakeStructuredOutput(behavior: "capture" | "reject", executions: unknown[]) {
  return (pi: ExtensionAPI) => {
    pi.registerTool({
      name: "structured_output",
      label: "Structured Output",
      description: "fake pi-subagents completion tool (test)",
      parameters: { type: "object", properties: { value: {} } } as never,
      async execute(_id, params) {
        executions.push(params);
        if (behavior === "reject") throw new Error("Structured output validation failed: fake");
        return {
          content: [{ type: "text", text: "Structured output captured." }],
          details: {},
          terminate: true,
        };
      },
    });
  };
}

// ------------------------------------------------------------------------- the gate + the hook

test("the gate re-delivers when nothing is in flight (a reload onto a compacted branch)", async () => {
  const { h, manager } = await session();
  try {
    plantCompacted(manager, PROMPT);
    assert.deepEqual(await report(h), { block: true, reason: HELD });
    const restores = restoreEntries(manager);
    assert.equal(restores.length, 1);
    assert.deepEqual(restores[0]?.content, restored(PROMPT));
    assert.equal(restores[0]?.display, true, "a visible steer, not a hidden injection");
    assert.equal(await report(h), undefined, "the restored task is live: the report is allowed");
    assert.equal(restoreEntries(manager).length, 1);
  } finally {
    h.dispose();
  }
});

test("session_compact restores once per compaction; the gate then allows", async () => {
  const { h, manager } = await session();
  try {
    plantCompacted(manager, PROMPT);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, 1);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, 1, "a live restore is not repeated");
    assert.equal(await report(h), undefined);

    // A later compaction that evicts the restore itself restores again.
    compactKeepingTail(manager);
    await compacted(h);
    const restores = restoreEntries(manager);
    assert.equal(restores.length, 2);
    assert.deepEqual(restores[1]?.content, restored(PROMPT));
    assert.equal(await report(h), undefined);
  } finally {
    h.dispose();
  }
});

test("an in-flight restore holds the gate without re-queueing", async () => {
  const { h, manager } = await session();
  // Mid-run Pi queues a steer instead of appending it; record the send without delivering it.
  const sent: { message: { customType?: string; display?: boolean }; options: unknown }[] = [];
  const live = h.session as unknown as {
    sendCustomMessage: (message: never, options?: unknown) => Promise<void>;
  };
  live.sendCustomMessage = async (message, options) => {
    sent.push({ message, options });
  };
  try {
    plantCompacted(manager, PROMPT);
    await compacted(h);
    assert.equal(sent.length, 1);
    assert.equal(sent[0]?.message.customType, TASK_RESTORE_TYPE);
    assert.equal(sent[0]?.message.display, true);
    assert.deepEqual(sent[0]?.options, { deliverAs: "steer" });
    assert.deepEqual(await report(h), { block: true, reason: HELD });
    assert.equal(sent.length, 1, "held: a restore for this compaction is already in flight");
    assert.equal(restoreEntries(manager).length, 0);
  } finally {
    h.dispose();
  }
});

test("an omitted restore re-queues from the gate, bounded by the attempt cap", async (t) => {
  const errors = t.mock.method(console, "error", () => {});
  const { h, manager } = await session();
  try {
    plantCompacted(manager, PROMPT);
    await compacted(h);
    for (let attempt = 2; attempt <= TASK_RESTORE_MAX_ATTEMPTS; attempt++) {
      const last = restoreEntries(manager).at(-1);
      assert.ok(last);
      manager.appendContextEdit(last.id, null);
      assert.deepEqual(await report(h), { block: true, reason: HELD });
      assert.equal(restoreEntries(manager).length, attempt);
      assert.equal(await report(h), undefined, `attempt ${attempt} restored the task`);
    }

    const last = restoreEntries(manager).at(-1);
    assert.ok(last);
    manager.appendContextEdit(last.id, null);
    const exhausted = structuredOutputHoldReason({ kind: "exhausted" });
    assert.deepEqual(await report(h), { block: true, reason: exhausted });
    await compacted(h);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, TASK_RESTORE_MAX_ATTEMPTS, "no further restores");
    const refusals = errors.mock.calls.filter((call) =>
      String(call.arguments[0]).startsWith("perk: task restore refused"),
    );
    assert.equal(refusals.length, 1, "one operator line per activation");
  } finally {
    h.dispose();
  }
});

test("an oversized prompt is refused, never restored", async (t) => {
  t.mock.method(console, "error", () => {});
  const { h, manager } = await session();
  const prompt = `Task: ${"x".repeat(TASK_RESTORE_MAX_BYTES)}`;
  try {
    plantCompacted(manager, prompt);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, 0);
    const bytes = Buffer.byteLength(prompt, "utf8");
    const verdict = await report(h);
    assert.deepEqual(verdict, {
      block: true,
      reason: structuredOutputHoldReason({ kind: "oversized", bytes }),
    });
    assert.match(verdict?.reason ?? "", new RegExp(`at ${bytes} bytes`));
    assert.equal(restoreEntries(manager).length, 0);
  } finally {
    h.dispose();
  }
});

test("a live task is left alone: no restore, the gate allows before and after", async () => {
  const { h, manager } = await session();
  try {
    appendMessage(manager, user(PROMPT));
    appendMessage(manager, assistant("working"));
    assert.equal(await report(h), undefined);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, 0);
    assert.equal(await report(h), undefined);
  } finally {
    h.dispose();
  }
});

test("a non-draft brief restores byte-exactly under the same role-neutral preamble", async () => {
  const { h, manager } = await session();
  const brief =
    "Task: Investigate how `extension/waves/` renders lane tasks.\n\n" +
    "Report: findings [{pointer, claim, basis}] — cite file:line; no speculation.\n";
  try {
    plantCompacted(manager, brief);
    await compacted(h);
    assert.deepEqual(
      restoreEntries(manager).map((entry) => entry.content),
      [restored(brief)],
    );
  } finally {
    h.dispose();
  }
});

test("no floor: the hooks are inert", async () => {
  const { h, manager } = await session({ floor: false });
  try {
    plantCompacted(manager, PROMPT);
    await compacted(h);
    assert.equal(restoreEntries(manager).length, 0);
    assert.equal(await report(h), undefined);
    assert.equal(restoreEntries(manager).length, 0);
  } finally {
    h.dispose();
  }
});

test("a floored branch with no user message keeps structured_output allowed", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "RID", mode: "read-write" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: runnerPacket,
    headful: false,
  });
  try {
    assert.equal(await report(h), undefined);
    await compacted(h);
    assert.equal(await report(h), undefined);
  } finally {
    h.dispose();
  }
});

// ------------------------------------------------------------------------- the acceptance latch

test("acceptance latch (idle): an executed report ends restoring; a rejected one does not latch", async () => {
  for (const behavior of ["capture", "reject"] as const) {
    const reg = await fauxModelRuntime();
    const executions: unknown[] = [];
    const cwd = scaffoldRepo();
    const manager = SessionManager.inMemory(cwd);
    const h = await loadPerkSession({
      cwd,
      sessionManager: manager,
      env: runnerPacket,
      headful: false,
      model: reg.getModel(),
      modelRuntime: reg.modelRuntime,
      extraExtensions: [fakeStructuredOutput(behavior, executions)],
    });
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("structured_output", { value: {} })], {
        stopReason: "toolUse",
      }),
      // Only a rejected call continues the turn.
      fauxAssistantMessage([fauxText("could not report")], { stopReason: "stop" }),
    ]);
    try {
      await h.session.prompt(PROMPT);
      assert.equal(executions.length, 1, `${behavior}: the tool executed once`);

      compactKeepingTail(manager);
      await compacted(h);
      if (behavior === "capture") {
        assert.equal(restoreEntries(manager).length, 0, "no restore after an accepted report");
        assert.equal(await report(h), undefined);
      } else {
        assert.deepEqual(
          restoreEntries(manager).map((entry) => entry.content),
          [restored(PROMPT)],
          "an error result is not an accepted report",
        );
      }
    } finally {
      h.dispose();
    }
  }
});

// Pi's real post-run compaction (`_checkCompaction` after the run ended, including after a
// terminating tool). A long task makes the arithmetic robust to system-prompt drift: the faux
// provider's usage counts the prompt as input AND cache write (≈ 2× the context), Pi's
// pre-request estimate counts it once, so a threshold between the two compacts only AFTER a
// request. Summarization requests (Pi issues a history and a split-turn-prefix summary here —
// the read-only context injection follows the task) are answered by a router, so the script
// counts only the lane's own model turns.
const LONG_TASK = `Task: Angle: grounding\n\n<untrusted_draft>\n${"a draft line\n".repeat(9500)}</untrusted_draft>`;
const CONTEXT_WINDOW = 120_000;
const RESERVE_TOKENS = 60_000;

type FauxContext = { messages: { role: string; content?: unknown }[] };
type LaneTurn = (context: FauxContext) => ReturnType<typeof fauxAssistantMessage>;

async function laneWithPostRunCompaction(turns: LaneTurn[]) {
  const reg = await fauxModelRuntime({ contextWindow: CONTEXT_WINDOW });
  const executions: unknown[] = [];
  const cwd = scaffoldRepo();
  const manager = SessionManager.inMemory(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: runnerPacket,
    headful: false,
    model: reg.getModel(),
    modelRuntime: reg.modelRuntime,
    settings: {
      compaction: { enabled: true, reserveTokens: RESERVE_TOKENS, keepRecentTokens: 0 },
    },
    extraExtensions: [fakeStructuredOutput("capture", executions)],
  });
  const script = [...turns];
  const laneRequests: FauxContext[] = [];
  let summaries = 0;
  let unexpected = 0;
  const route = (context: FauxContext) => {
    if (JSON.stringify(context.messages).includes("<conversation>")) {
      summaries++;
      return fauxAssistantMessage([fauxText("summary: the lane reviewed the draft")]);
    }
    laneRequests.push(context);
    const turn = script.shift();
    if (turn === undefined) {
      unexpected++;
      return fauxAssistantMessage([fauxText("unexpected lane turn")]);
    }
    return turn(context);
  };
  reg.setResponses(Array.from({ length: 16 }, () => route));
  return {
    h,
    manager,
    executions,
    laneRequests,
    summaries: () => summaries,
    unexpected: () => unexpected,
  };
}

const callReport: LaneTurn = () =>
  fauxAssistantMessage([fauxToolCall("structured_output", { value: {} })], {
    stopReason: "toolUse",
  });

function carriesRestore(context: FauxContext, prompt: string): boolean {
  const text = `${TASK_RESTORE_PREAMBLE}\n\n${prompt}`;
  return context.messages.some((message) =>
    Array.isArray(message.content)
      ? message.content.some(
          (part: { type?: unknown; text?: unknown }) =>
            part.type === "text" && typeof part.text === "string" && part.text.includes(text),
        )
      : typeof message.content === "string" && message.content.includes(text),
  );
}

test("acceptance latch (active turn): a post-run compaction after the report never restarts the lane", async () => {
  const lane = await laneWithPostRunCompaction([callReport]);
  try {
    await lane.h.session.prompt(LONG_TASK);
    assert.equal(lane.executions.length, 1, "the report executed once");
    assert.equal(compactionCount(lane.manager), 1, "Pi compacted after the terminating tool");
    assert.ok(lane.summaries() >= 1);
    assert.equal(restoreEntries(lane.manager).length, 0, "no restore after an accepted report");
    assert.equal(lane.laneRequests.length, 1, "no agent.continue(): one lane request only");
    assert.equal(lane.unexpected(), 0);
  } finally {
    lane.h.dispose();
  }
});

test("control (active turn): a lane compacted before reporting is continued with its task restored", async () => {
  const lane = await laneWithPostRunCompaction([
    () => fauxAssistantMessage([fauxText("reading the draft")], { stopReason: "stop" }),
    callReport,
  ]);
  try {
    await lane.h.session.prompt(LONG_TASK);
    assert.equal(lane.laneRequests.length, 2, "the post-run compaction continued the lane");
    const [first, continued] = lane.laneRequests;
    assert.ok(first && continued);
    assert.equal(carriesRestore(first, LONG_TASK), false);
    assert.ok(carriesRestore(continued, LONG_TASK), "the continued request carries the restore");
    assert.deepEqual(
      restoreEntries(lane.manager).map((entry) => entry.content),
      [restored(LONG_TASK)],
    );
    assert.equal(lane.executions.length, 1, "the restored lane reported; the gate allowed it");
    assert.ok(compactionCount(lane.manager) >= 1);
    assert.equal(lane.unexpected(), 0, "the accepted report was not restarted either");
  } finally {
    lane.h.dispose();
  }
});
