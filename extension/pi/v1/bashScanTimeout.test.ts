// The bash scan-timeout guard's Pi hooks, driven directly through a fake `pi` (fully offline,
// the toolGating.test.ts fixture pattern): the `tool_call` injection contract and the
// `tool_result` steer. The pure classifier matrix lives in substrate/bashScanTimeout.test.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerBashScanTimeout } from "./bashScanTimeout.ts";

type Hook = (
  event: {
    toolName: string;
    toolCallId?: string;
    input: Record<string, unknown>;
    content?: { type: string; text?: string }[];
    isError?: boolean;
  },
  ctx: ExtensionContext,
) => Promise<{ block?: boolean; content?: { type: string; text?: string }[] } | undefined>;

/**
 * Run `fn` with `console.error` captured (the fail-open path REPORTS, never throws); returns the
 * captured lines. Restores the real `console.error` even when `fn` rejects.
 */
async function capturingErrors(fn: () => Promise<void>): Promise<string[]> {
  const lines: string[] = [];
  const real = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    await fn();
  } finally {
    console.error = real;
  }
  return lines;
}

/** A bash input whose `command` read throws — the induced failure that reaches a hook's `catch`. */
function throwingInput(): Record<string, unknown> {
  return Object.defineProperty({} as Record<string, unknown>, "command", {
    enumerable: true,
    get() {
      throw new Error("induced");
    },
  });
}

function fixture() {
  const hooks = new Map<string, Hook>();
  const pi = {
    on: (name: string, hook: Hook) => {
      hooks.set(name, hook);
    },
  } as unknown as ExtensionAPI;
  registerBashScanTimeout(pi);
  const ctx = {} as ExtensionContext;
  return {
    hooks,
    call: (name: string, event: Parameters<Hook>[0]) => {
      const hook = hooks.get(name);
      assert.ok(hook, `hook ${name} registered`);
      return hook(event, ctx);
    },
  };
}

test("registers exactly the two hooks", () => {
  assert.deepEqual([...fixture().hooks.keys()].sort(), ["tool_call", "tool_result"]);
});

// --- tool_call injection ----------------------------------------------------------------------

test("tool_call: a scan without a timeout gets the default; the hook never blocks", async () => {
  const h = fixture();
  const input: Record<string, unknown> = { command: "grep -rn foo ." };
  const result = await h.call("tool_call", { toolName: "bash", input });
  assert.equal(result, undefined);
  assert.equal(input.timeout, 30);
});

test("tool_call: an explicit timeout is the override — any value, untouched", async () => {
  const h = fixture();
  const large: Record<string, unknown> = { command: "grep -rn foo .", timeout: 600 };
  await h.call("tool_call", { toolName: "bash", input: large });
  assert.equal(large.timeout, 600);
  const small: Record<string, unknown> = { command: "grep -rn foo .", timeout: 5 };
  await h.call("tool_call", { toolName: "bash", input: small });
  assert.equal(small.timeout, 5);
});

test("tool_call: a non-scan command and a non-bash tool are untouched", async () => {
  const h = fixture();
  const plain: Record<string, unknown> = { command: "grep -n foo f" };
  await h.call("tool_call", { toolName: "bash", input: plain });
  assert.equal("timeout" in plain, false);
  const read: Record<string, unknown> = { command: "grep -rn foo .", path: "x" };
  await h.call("tool_call", { toolName: "read", input: read });
  assert.equal("timeout" in read, false);
});

test("tool_call: malformed input neither throws nor injects", async () => {
  const h = fixture();
  const notString: Record<string, unknown> = { command: 42 };
  assert.equal(await h.call("tool_call", { toolName: "bash", input: notString }), undefined);
  assert.equal("timeout" in notString, false);
  const bare = Object.create(null) as Record<string, unknown>;
  assert.equal(await h.call("tool_call", { toolName: "bash", input: bare }), undefined);
  assert.equal("timeout" in bare, false);
});

test("tool_call: fail-OPEN — an internal error is reported, never thrown, and the call proceeds", async () => {
  // A thrown `tool_call` handler would escape Pi's dispatch and abort the bash call; the hook
  // must swallow + report instead (this is a performance guard, not a safety gate).
  const h = fixture();
  const input = throwingInput();
  let result: unknown = "unset";
  const lines = await capturingErrors(async () => {
    result = await h.call("tool_call", { toolName: "bash", input });
  });
  assert.equal(result, undefined);
  assert.equal("timeout" in input, false);
  assert.equal(lines.length, 1);
  assert.ok(lines[0]?.startsWith("perk: bash scan-timeout hook failed"), lines[0]);
  assert.ok(lines[0]?.includes("induced"), lines[0]);
});

// --- tool_result note -------------------------------------------------------------------------

const TIMED_OUT = "partial output\n\nCommand timed out after 30 seconds";

function expired(command: string, text = TIMED_OUT) {
  return {
    toolName: "bash",
    isError: true,
    input: { command, timeout: 30 },
    content: [{ type: "text", text }],
  };
}

test("tool_result: an expired recursive grep gets ONE appended steer", async () => {
  const h = fixture();
  const result = await h.call("tool_result", expired("grep -rn foo ."));
  assert.ok(result?.content);
  assert.equal(result.content.length, 2);
  assert.equal(result.content[0]?.text, TIMED_OUT);
  const note = result.content[1]?.text ?? "";
  assert.ok(note.includes("recursive grep"), note);
  assert.ok(note.includes("hit the 30s timeout"), note);
  assert.ok(note.includes("honor `.gitignore`"), note);
  assert.ok(note.includes("explicit `timeout`"), note);
});

test("tool_result: an expired unbounded find names its kind and the parsed seconds", async () => {
  const h = fixture();
  const result = await h.call(
    "tool_result",
    expired("find . -name '*.py'", "x\n\nCommand timed out after 600 seconds"),
  );
  const note = result?.content?.[1]?.text ?? "";
  assert.ok(note.includes("unbounded find"), note);
  assert.ok(note.includes("hit the 600s timeout"), note);
});

test("tool_result: a status-only text block (empty partial output) still matches", async () => {
  const h = fixture();
  const result = await h.call(
    "tool_result",
    expired("grep -rn foo .", "Command timed out after 30 seconds"),
  );
  assert.equal(result?.content?.length, 2);
});

test("tool_result: no note unless it is an error", async () => {
  const h = fixture();
  const result = await h.call("tool_result", { ...expired("grep -rn foo ."), isError: false });
  assert.equal(result, undefined);
});

test("tool_result: no note for a non-timeout error", async () => {
  const h = fixture();
  const result = await h.call(
    "tool_result",
    expired("grep -rn foo .", "nothing\n\nCommand exited with code 1"),
  );
  assert.equal(result, undefined);
});

test("tool_result: the timeout literal mid-output is not a timeout (terminal status only)", async () => {
  const h = fixture();
  const result = await h.call(
    "tool_result",
    expired(
      "grep -rn foo .",
      "Command timed out after 30 seconds\nmore\n\nCommand exited with code 1",
    ),
  );
  assert.equal(result, undefined);
});

test("tool_result: no note when the command is not a scan or the tool is not bash", async () => {
  const h = fixture();
  assert.equal(await h.call("tool_result", expired("grep -n foo f")), undefined);
  assert.equal(
    await h.call("tool_result", { ...expired("grep -rn foo ."), toolName: "read" }),
    undefined,
  );
});

test("tool_result: malformed input neither throws nor patches", async () => {
  const h = fixture();
  const result = await h.call("tool_result", {
    toolName: "bash",
    isError: true,
    input: { command: 42 },
    content: [{ type: "text", text: TIMED_OUT }],
  });
  assert.equal(result, undefined);
});

test("tool_result: fail-OPEN — an internal error is reported, never thrown, and the result stands", async () => {
  const h = fixture();
  let result: unknown = "unset";
  const lines = await capturingErrors(async () => {
    result = await h.call("tool_result", {
      toolName: "bash",
      isError: true,
      input: throwingInput(),
      content: [{ type: "text", text: TIMED_OUT }],
    });
  });
  assert.equal(result, undefined);
  assert.equal(lines.length, 1);
  assert.ok(lines[0]?.startsWith("perk: bash scan-timeout note failed"), lines[0]);
  assert.ok(lines[0]?.includes("induced"), lines[0]);
});
