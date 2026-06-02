// P2.T2a — perk-owned plan mode: the `/plan` toggle round-trip + `--plan` cold start + the
// plan-authoring context injection/strip, driven through a REAL bound AgentSession (offline).
// See planMode.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_CONTEXT_TYPE, planContextContent } from "./planMode.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("planContextContent: carries the gather-then-plan contract; appends the config addendum", () => {
  const cwd = scaffoldRepo();
  const base = planContextContent(cwd);
  assert.match(base, /\[PLAN AUTHORING\]/);
  assert.match(base, /Discoveries/);
  assert.match(base, /never line numbers/);

  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi", "perk.toml"),
    '[workflow]\nplan_authoring = "House rule: cite a file path per change."\n',
    "utf8",
  );
  const withAddendum = planContextContent(cwd);
  assert.match(withAddendum, /House rule: cite a file path per change\./);
});

test("/plan round-trip: on -> read-only + write blocked + plan-context injected; off -> released", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  try {
    // Starts OFF: write allowed, no plan-context injected.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
    assert.equal(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
    );

    // /plan ON -> read-only mode, write blocked, plan-context injected.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "mode flips to read-only");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) => m.customType === PLAN_CONTEXT_TYPE && String(m.content).includes("[PLAN AUTHORING]"),
      ),
      "plan-authoring context injected while on",
    );

    // /plan OFF -> read-write, write allowed, plan-context stripped from context.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write", "mode flips back to read-write");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
    const stale = [
      { customType: PLAN_CONTEXT_TYPE, content: "[PLAN AUTHORING]\nstale" },
      { role: "user", content: "[PLAN AUTHORING] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "plan-context custom message stripped when off",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[PLAN AUTHORING]")),
      false,
      "plan-authoring marker stripped from user turns when off",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});

test("--plan cold start enters read-only on session_start", async () => {
  const cwd = scaffoldRepo();
  // Unset PERK_RUN_ID so session_start takes the no-op "none" path (ad-hoc `pi --plan`, no run).
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // No flag -> read-write by default (no mode entry, gate off).
    assert.notEqual(h.workflowState().mode, "read-only", "default is not read-only");

    // Simulate `pi --plan`: set the flag, then reload to re-fire session_start.
    h.setFlag("plan", true);
    await h.reload();
    assert.equal(h.workflowState().mode, "read-only", "--plan enters read-only on session_start");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
  } finally {
    h.dispose();
  }
});
