// P2.T2a — perk-owned plan mode: the `/plan` toggle round-trip + `--plan` cold start + the
// plan-authoring context injection/strip, driven through a REAL bound AgentSession (offline).
// See planMode.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { PLAN_CONTEXT_TYPE, planContextContent } from "./planMode.ts";

test("planContextContent: carries the gather-then-plan contract; appends the config addendum", () => {
  const cwd = scaffoldRepo();
  const base = planContextContent(cwd);
  assert.match(base, /\[PLAN AUTHORING\]/);
  assert.match(base, /Discoveries/);
  assert.match(base, /never line numbers/);
  assert.match(base, /docs\/learned/);
  // Node 2.5: the review-first ending — plan_review when decision-complete; /plan-save is the
  // manual failsafe when the review reports skipped/unavailable.
  assert.match(base, /plan_review/);
  assert.match(base, /plan_draft/);
  assert.match(base, /\/plan-save \(the manual failsafe\)/);

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

test("deferral: a foreign [providers] plan selection makes perk NOT register the plan surface", async () => {
  const cwd = scaffoldRepo();
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[providers]\nplan = "tombell-plan"\n', "utf8");
  // Registration-time deferral resolves `process.cwd()` at factory time (the production cwd IS the
  // repo Pi launches in). Point process.cwd() at the scaffold so the factory sees the selection.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // Node 2.3 registration-time deferral: the `/plan` command is not registered at all.
    assert.equal(
      h.registeredCommands().includes("plan"),
      false,
      "perk does not register /plan under a foreign plan selection",
    );
    // The `--plan` flag is not registered either: setting it + reload does NOT flip read-only.
    h.setFlag("plan", true);
    await h.reload();
    assert.notEqual(
      h.workflowState().mode,
      "read-only",
      "--plan is inert (unregistered) under a foreign selection",
    );
    // ...and no plan-authoring context is injected (the before_agent_start handler is unregistered).
    assert.equal(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "no plan-context injected while deferred",
    );
  } finally {
    h.dispose();
    process.chdir(savedCwd);
  }
});

test("partial vacate: a plannotator-plan selection keeps /plan + injection but drops --plan", async () => {
  const cwd = scaffoldRepo();
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[providers]\nplan = "plannotator-plan"\n', "utf8");
  // Registration-time branching resolves `process.cwd()` at factory time — point it at the scaffold.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // Augment posture: perk's `/plan` command IS registered…
    assert.equal(
      h.registeredCommands().includes("plan"),
      true,
      "perk keeps /plan under the plannotator selection",
    );
    // …and the toggle + authoring injection still work end-to-end.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "/plan still flips read-only");
    assert.ok(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      "plan-authoring context still injected",
    );
    await h.invokeCommand("plan");
    // …but the `--plan` flag and the Ctrl+Alt+P shortcut are NOT registered (plannotator owns
    // them exclusively — duplicate flag/shortcut registration is the potentially-fatal collision).
    const runner = h.session.extensionRunner as unknown as {
      getFlags: () => Map<string, unknown>;
      getShortcuts: (kb: Record<string, unknown>) => Map<string, unknown>;
    };
    assert.equal(runner.getFlags().has("plan"), false, "--plan flag not registered");
    assert.equal(runner.getShortcuts({}).size, 0, "no perk shortcut registered");
    // Setting the (unregistered) flag + reload is inert.
    h.setFlag("plan", true);
    await h.reload();
    assert.notEqual(
      h.workflowState().mode,
      "read-only",
      "--plan is inert (unregistered) under the plannotator selection",
    );
  } finally {
    h.dispose();
    process.chdir(savedCwd);
  }
});

test("--plan cold start enters read-only on session_start", async () => {
  const cwd = scaffoldRepo();
  // Registration-time branching resolves `process.cwd()` at factory time — point it at the
  // scaffold so the host repo's committed [providers] selection cannot vacate --plan.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  // Unset PERK_RUN_ID so session_start takes the warm-mint "none" path (ad-hoc `pi --plan`).
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
    process.chdir(savedCwd);
  }
});
