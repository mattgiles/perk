// btw tests — the extracted pure core (offline): system-prompt footer stripping, text extraction,
// thread/tool-arg formatting, the gate-mirror `sideSessionTools` invariant, and the §5-conformed
// themed glyphs (`✗`/`▸`, never `❌`/`⚙`) under the D9 never-exceed-`width` law. Plus a registration
// smoke that binds the real perk extension and asserts `/btw` registers without throwing.

import assert from "node:assert/strict";
import { test } from "node:test";
import { visibleWidth } from "@earendil-works/pi-tui";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
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
