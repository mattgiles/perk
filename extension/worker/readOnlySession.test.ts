// Fully-offline coverage for the in-process read-only child session: the pure cap/extract
// helpers, the SDK-level read-only guarantee proven STRUCTURALLY via getActiveToolNames() with no
// prompt (and with API-key envs unset, to prove the no* flags keep loader resolution offline), and
// the handoff contract (double-delivery, route-don't-relay, write→verify→pass-path, fail-closed)
// exercised through an injected runTask so no model turn / network ever happens. See
// readOnlySession.ts.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { getModel } from "@earendil-works/pi-ai/compat";
import type { AgentSession } from "@earendil-works/pi-coding-agent";
import { AGENT_SCRATCH_CONTEXT_TYPE } from "../substrate/agentScratch.ts";
import {
  type ChildHandoff,
  capForModel,
  createReadOnlySession,
  DEFAULT_MODEL_VISIBLE_CAP,
  extractFinalAssistantText,
  runReadOnlyChild,
  SDK_READ_ONLY_TOOLS,
} from "./readOnlySession.ts";

function tmpCwd(): string {
  return mkdtempSync(join(tmpdir(), "perk-ro-cwd-"));
}

// --- pure helpers: capForModel ----------------------------------------------------------

test("capForModel: under cap is unchanged, truncated:false", () => {
  const text = "hello world";
  const r = capForModel(text, DEFAULT_MODEL_VISIBLE_CAP);
  assert.equal(r.shown, text);
  assert.equal(r.truncated, false);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.equal(r.bytesShown, r.bytesTotal);
});

test("capForModel: over cap truncates with bytesShown <= cap and a scratch-pointing notice", () => {
  const text = "x".repeat(5000);
  const r = capForModel(text, 1000, "/tmp/scratch/child.md");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 1000, `bytesShown ${r.bytesShown} should be <= cap`);
  assert.equal(r.bytesTotal, 5000);
  assert.ok(r.shown.includes("[Output truncated"));
  assert.ok(r.shown.includes("/tmp/scratch/child.md"));
});

test("capForModel: UTF-8 multibyte boundary safe (never splits a code point)", () => {
  // "💎" is 4 UTF-8 bytes; a cap landing mid-character must trim to a whole char.
  const text = "💎".repeat(100);
  const r = capForModel(text, 10);
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 10);
  // The shown prefix (before the notice) must be valid (no replacement char from a split).
  const prefix = r.shown.split("\n\n[Output truncated")[0] ?? "";
  assert.ok(!prefix.includes("\uFFFD"));
  assert.equal(Buffer.byteLength(prefix, "utf8") % 4, 0);
});

test("capForModel: tail mode under cap is unchanged, truncated:false", () => {
  const text = "hello world";
  const r = capForModel(text, DEFAULT_MODEL_VISIBLE_CAP, null, "tail");
  assert.equal(r.shown, text);
  assert.equal(r.truncated, false);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.equal(r.bytesShown, r.bytesTotal);
});

test("capForModel: tail mode keeps the LAST cap bytes with a prepended notice", () => {
  const text = `${"x".repeat(5000)}FINAL-TAIL-MARKER`;
  const r = capForModel(text, 1000, "/tmp/scratch/child.md", "tail");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 1000, `bytesShown ${r.bytesShown} should be <= cap`);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.ok(r.shown.endsWith("FINAL-TAIL-MARKER"), "shown must end with the original tail");
  assert.ok(r.shown.startsWith("[Output truncated"), "notice must be a prefix in tail mode");
  assert.ok(r.shown.includes("/tmp/scratch/child.md"));
});

test("capForModel: tail mode UTF-8 multibyte boundary safe (never splits a code point)", () => {
  // "💎" is 4 UTF-8 bytes; a cap landing mid-character must trim to a whole char.
  const text = "💎".repeat(100);
  const r = capForModel(text, 10, null, "tail");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 10);
  // The shown suffix (after the prepended notice) must be valid (no lone surrogate from a split).
  const suffix = r.shown.slice(r.shown.indexOf("\n\n") + 2);
  assert.ok(!suffix.includes("\uFFFD"));
  assert.equal(Buffer.byteLength(suffix, "utf8") % 4, 0);
});

// --- pure helpers: extractFinalAssistantText --------------------------------------------

test("extractFinalAssistantText: returns the last assistant message's first text part", () => {
  const messages = [
    { role: "user", content: "ask" },
    { role: "assistant", content: [{ type: "text", text: "first" }] },
    { role: "user", content: "again" },
    { role: "assistant", content: [{ type: "text", text: "final" }] },
  ];
  assert.equal(extractFinalAssistantText(messages), "final");
});

test("extractFinalAssistantText: '' when no assistant text exists", () => {
  assert.equal(extractFinalAssistantText([{ role: "user", content: "hi" }]), "");
  assert.equal(extractFinalAssistantText([]), "");
  assert.equal(extractFinalAssistantText([{ role: "assistant", content: [] }]), "");
});

// --- SDK read-only is structural AND offline (no prompt, API keys unset) ----------------

test("createReadOnlySession: active tools ⊆ SDK_READ_ONLY_TOOLS (structural, offline)", async () => {
  // Guard the masked-isolation-gap failure mode: with API-key envs unset, loader resolution must
  // still succeed (the no* flags keep it offline). Save/restore so we don't leak into other tests.
  const keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"];
  const saved = new Map(keys.map((k) => [k, process.env[k]]));
  for (const k of keys) delete process.env[k];
  const cwd = tmpCwd();
  let session: AgentSession | null = null;
  try {
    const model = getModel("anthropic", "claude-sonnet-4-5") ?? undefined;
    const created = await createReadOnlySession({ cwd, model });
    session = created.session;
    const active = session.getActiveToolNames();
    for (const name of active) {
      assert.ok(SDK_READ_ONLY_TOOLS.includes(name), `unexpected active tool: ${name}`);
    }
    for (const banned of ["edit", "write", "bash"]) {
      assert.ok(!active.includes(banned), `${banned} must not be active`);
    }
    assert.equal(
      session.state.messages.some(
        (message) => (message as { customType?: string }).customType === AGENT_SCRATCH_CONTEXT_TYPE,
      ),
      false,
      "the noExtensions SDK child receives no agent-scratch guidance",
    );
    assert.deepEqual(session.extensionRunner.getRegisteredCommands(), []);
  } finally {
    session?.dispose();
    for (const [k, v] of saved) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
});

// --- handoff contract: double-delivery + route-don't-relay ------------------------------

test("runReadOnlyChild: double-delivery + route-don't-relay (full output only in scratch)", async () => {
  const cwd = tmpCwd();
  const head = "BEGIN-".repeat(100);
  const tail = "SECRET-TAIL-MARKER";
  const full = `${head}${"x".repeat(2000)}${tail}`;
  const handoff: ChildHandoff = await runReadOnlyChild(
    { cwd, task: "explore", modelVisibleCap: 500 },
    {
      createSession: async () => ({ session: { dispose() {} } as unknown as AgentSession }),
      runTask: async () => full,
    },
  );
  assert.equal(handoff.success, true);
  assert.ok(handoff.scratchPath);
  // The scratch file holds the FULL content.
  assert.equal(readFileSync(handoff.scratchPath as string, "utf8"), full);
  // The prose is capped and does NOT contain the raw tail (route-don't-relay).
  assert.ok(!handoff.prose.includes(tail));
  assert.ok(handoff.prose.includes("[Output truncated"));
  assert.equal(handoff.structured.success, true);
  assert.equal(handoff.structured.truncated, true);
  assert.equal(handoff.structured.scratchPath, handoff.scratchPath);
  assert.ok(handoff.structured.bytesTotal > handoff.structured.bytesShown);
});

test("runReadOnlyChild: run-scoped scratch path under .perk/workflow when runId given", async () => {
  const cwd = tmpCwd();
  const handoff = await runReadOnlyChild(
    { cwd, task: "explore", runId: "01RID", step: "ci" },
    {
      createSession: async () => ({ session: { dispose() {} } as unknown as AgentSession }),
      runTask: async () => "small output",
    },
  );
  assert.equal(handoff.success, true);
  assert.ok(
    (handoff.scratchPath as string).endsWith(
      join(".perk", "workflow", "scratch", "runs", "01RID", "ci.md"),
    ),
    handoff.scratchPath ?? "(null)",
  );
  assert.equal(handoff.structured.truncated, false);
});

// --- verify-the-handoff failure ---------------------------------------------------------

test("runReadOnlyChild: scratch-write/verify failure ⇒ success:false, error in both", async () => {
  // Point cwd at a non-existent path that resolveScratchPath cannot create (a file as a parent).
  const file = join(tmpCwd(), "iam-a-file");
  writeFileSync(file, "x");
  const handoff = await runReadOnlyChild(
    { cwd: file, task: "explore" },
    {
      createSession: async () => ({ session: { dispose() {} } as unknown as AgentSession }),
      runTask: async () => "output",
    },
  );
  assert.equal(handoff.success, false);
  assert.equal(handoff.scratchPath, null);
  assert.ok(handoff.prose.length > 0);
  assert.ok(handoff.structured.error && handoff.structured.error.length > 0);
});

// --- graceful failure + dispose ---------------------------------------------------------

test("runReadOnlyChild: runTask throw ⇒ success:false, error surfaced, session disposed", async () => {
  const cwd = tmpCwd();
  let disposed = false;
  const handoff = await runReadOnlyChild(
    { cwd, task: "explore" },
    {
      createSession: async () => ({
        session: {
          dispose() {
            disposed = true;
          },
        } as unknown as AgentSession,
      }),
      runTask: async () => {
        throw new Error("boom");
      },
    },
  );
  assert.equal(handoff.success, false);
  assert.equal(handoff.scratchPath, null);
  assert.ok(handoff.prose.includes("boom"));
  assert.equal(handoff.structured.error, "boom");
  assert.equal(disposed, true, "session must be disposed in finally");
});

test("runReadOnlyChild: aborted signal short-circuits before start", async () => {
  const cwd = tmpCwd();
  const controller = new AbortController();
  controller.abort();
  const handoff = await runReadOnlyChild(
    { cwd, task: "explore", signal: controller.signal },
    {
      createSession: async () => {
        throw new Error("should not create");
      },
    },
  );
  assert.equal(handoff.success, false);
  assert.equal(handoff.structured.error, "aborted");
});
