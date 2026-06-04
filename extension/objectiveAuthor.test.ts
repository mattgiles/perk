// P3.T2 — the objective-authoring context injection + the planMode coupling break, driven through
// a REAL bound AgentSession (offline). An objective-author session is read-only AND carries
// `stage: objective-author`; objectiveAuthor injects its own context there and planMode DEFERS, so
// exactly one authoring context is present. A normal plan read-only session is unaffected.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_AUTHOR_CONTEXT_TYPE } from "./objectiveAuthor.ts";
import { PLAN_CONTEXT_TYPE } from "./planMode.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("objective-author session injects objective-authoring context; planMode defers", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal(h.workflowState().stage, "objective-author", "stage recorded at claim");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("[OBJECTIVE AUTHORING]"),
      ),
      "objective-authoring context injected",
    );
    assert.equal(
      injected.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "planMode defers — no plan-authoring context in an objective-author session",
    );
  } finally {
    h.dispose();
  }
});

test("a normal plan read-only session injects plan context, not objective-authoring", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      "plan-authoring context injected for a plan session",
    );
    assert.equal(
      injected.some((m) => m.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE),
      false,
      "no objective-authoring context outside an objective-author session",
    );
  } finally {
    h.dispose();
  }
});

test("objective-authoring marker is stripped from context when not authoring", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "objective-save" },
  });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const stale = [
      { customType: OBJECTIVE_AUTHOR_CONTEXT_TYPE, content: "[OBJECTIVE AUTHORING]\nstale" },
      { role: "user", content: "[OBJECTIVE AUTHORING] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE),
      false,
      "objective-author custom message stripped when not authoring",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[OBJECTIVE AUTHORING]")),
      false,
      "marker stripped from user turns",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});
