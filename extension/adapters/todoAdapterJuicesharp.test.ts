// The juicesharp todo adapter shim: injection under a `juicesharp-todo` selection + an
// active workflow, inert otherwise (default selection or inactive workflow), plus a stale-marker
// strip under the default selection. Driven through a REAL bound AgentSession (offline) via the
// shared harness. See todoAdapterJuicesharp.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "../substrate/cache.ts";
import type { WorkflowState } from "../substrate/workflowState.ts";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  isJuicesharpTodoSelected,
  TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
} from "./todoAdapterJuicesharp.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};
const ACTIVE: Partial<WorkflowState> = {
  run_id: "01RID",
  mode: "read-write",
  active_plan_ref: REF,
};

function selectJuicesharp(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[providers]\ntodo = "juicesharp-todo"\n',
    "utf8",
  );
}

test("isJuicesharpTodoSelected: true only when [providers] todo = juicesharp-todo", () => {
  const def = scaffoldRepo();
  assert.equal(isJuicesharpTodoSelected(def), false);
  const sel = scaffoldRepo();
  selectJuicesharp(sel);
  assert.equal(isJuicesharpTodoSelected(sel), true);
});

test("juicesharp selected + active workflow: before_agent_start injects the bridge context", async () => {
  const cwd = scaffoldRepo();
  selectJuicesharp(cwd);
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE &&
          String(m.content).includes("[TODO ADAPTER: JUICESHARP]") &&
          String(m.content).includes("## Steps"),
      ),
      "the bridge context is injected (carries the progress discipline onto the overlay)",
    );
  } finally {
    h.dispose();
  }
});

test("juicesharp selected but NO active workflow: before_agent_start injects nothing", async () => {
  const cwd = scaffoldRepo();
  selectJuicesharp(cwd);
  // No workflow-state entries -> no active plan -> the active-workflow gate suppresses injection.
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
      ),
      false,
      "no bridge context injected without an active workflow",
    );
  } finally {
    h.dispose();
  }
});

test("bridge context dedups against a prior copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  selectJuicesharp(cwd);
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: ACTIVE } },
    {
      custom: {
        type: TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
        data: { content: "[TODO ADAPTER: JUICESHARP]\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE),
      false,
      "prior [TODO ADAPTER: JUICESHARP] copy on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("default selection: shim injects nothing and strips a stale bridge marker", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // No injection under the default (perk-checkpoints) selection, even with an active workflow.
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
      ),
      false,
      "no bridge context injected on the default path",
    );
    // A stale bridge marker (custom entry + a leaked user turn) is stripped from context.
    const stale = [
      {
        customType: TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
        content: "[TODO ADAPTER: JUICESHARP]\nstale",
      },
      { role: "user", content: "[TODO ADAPTER: JUICESHARP] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE),
      false,
      "stale bridge custom message stripped on the default path",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[TODO ADAPTER: JUICESHARP]")),
      false,
      "stale bridge marker stripped from user turns on the default path",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});
