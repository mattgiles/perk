// Node 2.3 + 2.6 — the tombell plan adapter shim: review-first injection under a `tombell-plan`
// selection when a plan authoring mode is on (perk gate read-only OR tombell's own persisted
// `plan-mode-state`; objective-author excepted), inert (+ stale-marker strip) under the default
// selection. Driven through a REAL bound AgentSession (offline) via the shared harness. See
// planAdapterTombell.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, plantSession, scaffoldRepo } from "../testing/harness.ts";
import type { BranchEntry } from "../workflowState.ts";
import {
  isTombellPlanModeEnabled,
  isTombellPlanSelected,
  PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
} from "./planAdapterTombell.ts";

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

test("tombell selected + gate active: injects the review-first bridge context (fallback kept)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  selectTombell(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE &&
          String(m.content).includes("[PLAN ADAPTER: TOMBELL]") &&
          String(m.content).includes("plan_draft") &&
          String(m.content).includes("plan_review") &&
          String(m.content).includes("/plan-save"),
      ),
      "the bridge context is injected (review-first; the /plan-save fail-open fallback survives)",
    );
  } finally {
    h.dispose();
  }
});

test("tombell selected but gate off (no tombell plan mode): no bridge context injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  selectTombell(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
      ),
      false,
      "no bridge context while neither plan authoring mode is on",
    );
  } finally {
    h.dispose();
  }
});

test("tombell selected + tombell's own plan mode on: injection fires despite a read-write gate", async () => {
  const cwd = scaffoldRepo();
  selectTombell(cwd);
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], { planMode: true });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.open(file),
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE &&
          String(m.content).includes("plan_review"),
      ),
      "the bridge context is injected for the ad-hoc tombell /plan arm (plan-mode-state enabled)",
    );
  } finally {
    h.dispose();
  }
});

test("objective-author session: the bridge context defers (objectiveAuthor owns that session)", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  selectTombell(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
      ),
      false,
      "no bridge context in an objective-author session (mirrors the plannotator adapter)",
    );
  } finally {
    h.dispose();
  }
});

test("isTombellPlanModeEnabled: latest plan-mode-state entry wins; malformed ⇒ false", () => {
  const entry = (enabled: unknown): BranchEntry => ({
    type: "custom",
    customType: "plan-mode-state",
    data: { enabled: enabled as never },
  });
  assert.equal(isTombellPlanModeEnabled([]), false, "no entries ⇒ false");
  assert.equal(isTombellPlanModeEnabled([entry(true)]), true, "latest enabled: true ⇒ true");
  assert.equal(
    isTombellPlanModeEnabled([entry(true), entry(false)]),
    false,
    "a later enabled: false defeats an earlier true (latest wins)",
  );
  assert.equal(
    isTombellPlanModeEnabled([{ type: "custom", customType: "plan-mode-state" }]),
    false,
    "missing data ⇒ false",
  );
  assert.equal(isTombellPlanModeEnabled([entry("yes")]), false, "non-boolean enabled ⇒ false");
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
