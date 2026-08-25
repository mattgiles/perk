// The objective-authoring context injection + the planMode coupling break, driven through
// a REAL bound AgentSession (offline). An objective-author session is read-only AND carries
// `stage: objective-author`; objectiveAuthor injects its own context there and planMode DEFERS, so
// exactly one authoring context is present. A normal plan read-only session is unaffected.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_CONTEXT_TYPE } from "../authoring/plan/prose.ts";
import { loadPerkSession, plantRawSession, scaffoldRepo } from "../testing/harness.ts";
import {
  OBJECTIVE_AUTHOR_CONTEXT_TYPE,
  OBJECTIVE_AUTHORING_CONTEXT,
  objectiveAuthoringContextContent,
} from "./objectiveAuthor.ts";

const ADDENDUM_TOML = '[workflow]\nplan_authoring = "House rule: cite a file path per change."\n';

function writeAddendumConfig(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), ADDENDUM_TOML, "utf8");
}

test("objectiveAuthoringContextContent: carries the authoring contract; appends the config addendum", () => {
  const cwd = scaffoldRepo();
  const base = objectiveAuthoringContextContent(cwd);
  assert.match(base, /\[OBJECTIVE AUTHORING\]/);
  assert.equal(base, OBJECTIVE_AUTHORING_CONTEXT, "no addendum without config");

  writeAddendumConfig(cwd);
  const withAddendum = objectiveAuthoringContextContent(cwd);
  assert.match(withAddendum, /House rule: cite a file path per change\./);
});

test("OBJECTIVE_AUTHORING_CONTEXT is live state + pointers only (§8.57)", () => {
  // The injected context names the working-draft artifact, the review tool, and the bound
  // skill — it never restates the flow (the launch statement's job), the delivery-ask step,
  // or the save/failsafe endings, and it carries no skill read path (binding-delivered).
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /\[OBJECTIVE AUTHORING\]/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /objective_draft/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /plan_review/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /perk-objective-author/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /ask_user_question/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /incremental as the first, recommended option/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /\/objective-save/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /rendered objective/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /\.agents\/skills/);
});

test("objective-author session injects objective-authoring context; planMode defers", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  writeAddendumConfig(cwd);
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
    assert.ok(
      injected.some(
        (m) =>
          m.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("House rule: cite a file path per change."),
      ),
      "the [workflow] plan_authoring addendum flows into the injected context per-event",
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

test("objective-author context dedups against a prior copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "objective-author" },
      },
    },
    {
      custom: {
        type: OBJECTIVE_AUTHOR_CONTEXT_TYPE,
        data: { content: "[OBJECTIVE AUTHORING]\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "objective-author");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE),
      false,
      "prior [OBJECTIVE AUTHORING] copy on branch → no re-injection",
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
