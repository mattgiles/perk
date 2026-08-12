// The gist-authoring context injection + the planMode coupling break, driven through a REAL
// bound AgentSession (offline) — the gist mirror of objectiveAuthor.test.ts. A gist-author
// session is read-only AND carries `stage: gist-author`; gistAuthor injects its own context there
// and planMode DEFERS, so exactly one authoring context is present.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, plantRawSession, scaffoldRepo } from "../testing/harness.ts";
import {
  GIST_AUTHOR_CONTEXT_TYPE,
  GIST_AUTHORING_CONTEXT,
  gistAuthoringContextContent,
} from "./gistAuthor.ts";
import { PLAN_CONTEXT_TYPE } from "./planMode.ts";

const ADDENDUM_TOML = '[workflow]\nplan_authoring = "House rule: cite a file path per change."\n';

function writeAddendumConfig(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), ADDENDUM_TOML, "utf8");
}

test("gistAuthoringContextContent: carries the authoring contract; appends the config addendum", () => {
  const cwd = scaffoldRepo();
  const base = gistAuthoringContextContent(cwd);
  assert.match(base, /\[GIST AUTHORING\]/);
  assert.equal(base, GIST_AUTHORING_CONTEXT, "no addendum without config");

  writeAddendumConfig(cwd);
  const withAddendum = gistAuthoringContextContent(cwd);
  assert.match(withAddendum, /House rule: cite a file path per change\./);
});

test("GIST_AUTHORING_CONTEXT is live state + pointers only (§8.57)", () => {
  // The injected context names the working-draft artifact, the review tool, and the bound
  // skill — it never restates the flow (the launch statement's job), the artifact's lightness
  // detail, or the save/failsafe endings, and it carries no skill read path (binding-delivered).
  assert.match(GIST_AUTHORING_CONTEXT, /\[GIST AUTHORING\]/);
  assert.match(GIST_AUTHORING_CONTEXT, /gist_draft/);
  assert.match(GIST_AUTHORING_CONTEXT, /plan_review/);
  assert.match(GIST_AUTHORING_CONTEXT, /perk-gist-author/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /no steps, no roadmap, no estimates/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /\/gist-save/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /\.agents\/skills/);
});

test("gist-author session injects gist-authoring context; planMode defers", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "gist-author" },
  });
  writeAddendumConfig(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal(h.workflowState().stage, "gist-author", "stage recorded at claim");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === GIST_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("[GIST AUTHORING]"),
      ),
      "gist-authoring context injected",
    );
    assert.ok(
      injected.some(
        (m) =>
          m.customType === GIST_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("House rule: cite a file path per change."),
      ),
      "the [workflow] plan_authoring addendum flows into the injected context per-event",
    );
    assert.equal(
      injected.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "planMode defers — no plan-authoring context in a gist-author session",
    );
  } finally {
    h.dispose();
  }
});

test("gist-author context dedups against a prior copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "gist-author" },
      },
    },
    {
      custom: {
        type: GIST_AUTHOR_CONTEXT_TYPE,
        data: { content: "[GIST AUTHORING]\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "gist-author");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "prior [GIST AUTHORING] copy on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("a normal plan read-only session injects plan context, not gist-authoring", async () => {
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
      injected.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "no gist-authoring context outside a gist-author session",
    );
  } finally {
    h.dispose();
  }
});

test("gist-authoring marker is stripped from context when not authoring", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "gist-save" },
  });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const stale = [
      { customType: GIST_AUTHOR_CONTEXT_TYPE, content: "[GIST AUTHORING]\nstale" },
      { role: "user", content: "[GIST AUTHORING] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "gist-author custom message stripped when not authoring",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[GIST AUTHORING]")),
      false,
      "marker stripped from user turns",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});
