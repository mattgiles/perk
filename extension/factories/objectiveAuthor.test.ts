// The objective-authoring context injection + the planMode coupling break, driven through
// a REAL bound AgentSession (offline). An objective-author session is read-only AND carries
// `stage: objective-author`; objectiveAuthor injects its own context there and planMode DEFERS, so
// exactly one authoring context is present. A normal plan read-only session is unaffected.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  OBJECTIVE_AUTHOR_CONTEXT_TYPE,
  OBJECTIVE_AUTHORING_CONTEXT,
  objectiveAuthoringContextContent,
} from "./objectiveAuthor.ts";
import { PLAN_CONTEXT_TYPE } from "./planMode.ts";

const ADDENDUM_TOML = '[workflow]\nplan_authoring = "House rule: cite a file path per change."\n';

function writeAddendumConfig(cwd: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), ADDENDUM_TOML, "utf8");
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

test("OBJECTIVE_AUTHORING_CONTEXT speaks the review-first discipline", () => {
  // The draft + review loop replaced the structurally-broken `/plan` off → objective_save ending
  // (the model cannot run /plan; objective_save is hidden while the gate is on).
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /objective_draft/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /call the plan_review tool/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /rendered objective \(the prose \+ a roadmap table\)/);
  // Approval auto-saves — the failsafe arms keep the /objective-save mention.
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /nothing auto-saves yet/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /relay the save outcome instead/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /`\/objective-save` \(the manual failsafe\)/);
  assert.doesNotMatch(
    OBJECTIVE_AUTHORING_CONTEXT,
    /exit read-only mode/,
    "the pre-file-first save instructions are gone",
  );
  assert.doesNotMatch(
    OBJECTIVE_AUTHORING_CONTEXT,
    /call the objective_save tool/,
    "the model is never directed to call objective_save itself",
  );
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
