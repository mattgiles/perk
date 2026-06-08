// Node 2.3 — the tombell plan adapter shim: injection under a `tombell-plan` selection, inert (+
// stale-marker strip) under the default selection. Driven through a REAL bound AgentSession
// (offline) via the shared harness. See planAdapterTombell.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { isTombellPlanSelected, PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE } from "./planAdapterTombell.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

function selectTombell(cwd: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[providers]\nplan = "tombell-plan"\n', "utf8");
}

test("isTombellPlanSelected: true only when [providers] plan = tombell-plan", () => {
  const def = scaffoldRepo();
  assert.equal(isTombellPlanSelected(def), false);
  const sel = scaffoldRepo();
  selectTombell(sel);
  assert.equal(isTombellPlanSelected(sel), true);
});

test("tombell selected: before_agent_start injects the plan-adapter bridge context", async () => {
  const cwd = scaffoldRepo();
  selectTombell(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE &&
          String(m.content).includes("[PLAN ADAPTER: TOMBELL]") &&
          String(m.content).includes("/plan-save"),
      ),
      "the bridge context is injected (directs free-form prose → /plan-save)",
    );
  } finally {
    h.dispose();
  }
});

test("default selection: shim injects nothing and strips a stale bridge marker", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // No injection under the default (perk-plan) selection.
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
      ),
      false,
      "no bridge context injected on the default path",
    );
    // A stale bridge marker (custom entry + a leaked user turn) is stripped from context.
    const stale = [
      { customType: PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE, content: "[PLAN ADAPTER: TOMBELL]\nstale" },
      { role: "user", content: "[PLAN ADAPTER: TOMBELL] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE),
      false,
      "stale bridge custom message stripped on the default path",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[PLAN ADAPTER: TOMBELL]")),
      false,
      "stale bridge marker stripped from user turns on the default path",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});
