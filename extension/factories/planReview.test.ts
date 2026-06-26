// The backend-neutral `plan_review` review door: the tool-boundary soft skips
// (bad_input / objective-author / headless / no_plan), the file-first resolution (artifact →
// param, NEVER transcript), the backend DISPATCH (plannotator-selected → the event-bus bridge;
// ANY other selection → the first-party in-TUI editor review), the first-party flow (display →
// optional edit write-back via writePlanDraft → approve/deny/skip verdict → deny-feedback
// editor; Esc anywhere = fail-open skip), the approved→approvalSave arm (either backend), and
// the pure mappers. Fully offline: a fake UI drives the first-party dialogs, a recording bridge
// stands in for plannotator, and a fake pi returns the canned cold-door payload (the
// planSave.test.ts recipe; scaffoldRepo for provider selection — planAdapterPlannotator.test.ts's
// scaffold recipe). See planReview.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type SessionDataCtx, writeSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import { executePlanReview, type PlanReviewUI, type ReviewOutcome } from "./planReview.ts";

function selectPlanProvider(cwd: string, id: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[providers]\nplan = "${id}"\n`, "utf8");
}

// ------------------------------------------------------------------------------ shared fakes

const PLAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { id: "42", url: "https://gh/o/r/issues/42", existed: false },
  plan_ref: {
    provider: "github",
    pr_id: "42",
    url: "https://gh/o/r/issues/42",
    labels: ["perk:plan"],
    objective_id: null,
  },
  cached: true,
  dry_run: false,
});

/** A recording bridge: captures the reviewed bytes, returns the canned outcome. */
function cannedBridge(outcome: ReviewOutcome): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
  reviewed: string[];
} {
  const reviewed: string[] = [];
  return {
    reviewed,
    async review(plan: string) {
      reviewed.push(plan);
      return outcome;
    },
  };
}

/** A ToolGating fake recording exits; `active` is the isActive snapshot. */
function fakeGating(active: boolean): ToolGating & { exits: number } {
  const g = {
    exits: 0,
    syncFromState() {},
    enter() {},
    exit() {
      g.exits += 1;
    },
    isActive: () => active,
  };
  return g;
}

/** An ExtensionAPI fake: appendEntry lands on the branch; exec returns the canned payload. */
function fakeColdDoorPi(
  branch: unknown[],
  opts: { stdout: string; code?: number; argvs?: string[][] },
): ExtensionAPI {
  return {
    appendEntry(customType: string, data?: unknown) {
      branch.push({ type: "custom", customType, data });
    },
    async exec(_cmd: string, args: string[]) {
      opts.argvs?.push(args);
      return { stdout: opts.stdout, stderr: "", code: opts.code ?? 0, killed: false };
    },
  } as unknown as ExtensionAPI;
}

/** A recording first-party UI: scripted editor/select answers, captured prompts. */
function fakeUI(script: {
  editor?: (string | undefined)[];
  select?: (string | undefined)[];
}): PlanReviewUI & {
  editors: { title: string; prefill: string | undefined }[];
  selects: { title: string; options: string[] }[];
} {
  const editorAnswers = [...(script.editor ?? [])];
  const selectAnswers = [...(script.select ?? [])];
  const ui = {
    editors: [] as { title: string; prefill: string | undefined }[],
    selects: [] as { title: string; options: string[] }[],
    async editor(title: string, prefill?: string) {
      ui.editors.push({ title, prefill });
      return editorAnswers.shift();
    },
    async select(title: string, options: string[]) {
      ui.selects.push({ title, options });
      return selectAnswers.shift();
    },
  };
  return ui;
}

const APPROVE = "Approve — auto-save to GitHub";
const DENY_OPT = "Deny — send feedback for revision";
const SKIP_OPT = "Skip — decide later (manual /plan-save)";

/** A headful `SessionDataCtx & ReportTarget` over a live branch array, with a scripted ui. */
function headfulCtx(
  cwd: string,
  branch: unknown[],
  ui: unknown = { notify() {} },
): SessionDataCtx & ReportTarget {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: true,
    ui: { notify() {}, ...(ui as object) },
  } as SessionDataCtx & ReportTarget;
}

function fakeSink(branch: unknown[]): EntrySink {
  return {
    appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
  };
}

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

const APPROVED: ReviewOutcome = { status: "completed", approved: true, reviewId: "rev-a" };
const DENIED: ReviewOutcome = {
  status: "completed",
  approved: false,
  reviewId: "rev-d",
  feedback: "needs work",
};

// ------------------------------------------------- registered-tool soft skips (harness-driven)

test("plan_review: headless -> soft skip (fail-open; never wedges a CI/supervisor run)", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({
    cwd,
    headful: false,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", { plan: "# A plan" });
    assert.equal((result.details as { status?: string }).status, "skipped");
    assert.match(String(result.content[0]?.text), /no interactive review surface available/);
  } finally {
    h.dispose();
  }
});

test("plan_review: no plannotator listener -> handshake timeout -> loud unavailable skip", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_PLANNOTATOR_HANDSHAKE_MS: "50" },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", { plan: "# A plan" });
    assert.equal((result.details as { status?: string }).status, "unavailable");
    assert.match(String(result.content[0]?.text), /WARNING/);
    assert.match(String(result.content[0]?.text), /handshake timeout/);
  } finally {
    h.dispose();
  }
});

test("plan_review: missing plan + no draft -> skipped with reason no_plan", async () => {
  // An absent `plan` param is fine (the draft artifact is the preferred source), but with NO
  // draft either there is nothing reviewable — the transcript is never reviewed.
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_PLANNOTATOR_HANDSHAKE_MS: "50" },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", {});
    const details = result.details as { status?: string; reason?: string };
    assert.equal(details.status, "skipped");
    assert.equal(details.reason, "no_plan");
    assert.match(String(result.content[0]?.text), /write the working draft with plan_draft/);
  } finally {
    h.dispose();
  }
});

test("plan_review: mistyped plan -> skipped with reason bad_input", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", { plan: 5 });
    const details = result.details as { status?: string; reason?: string };
    assert.equal(details.status, "skipped");
    assert.equal(details.reason, "bad_input");
  } finally {
    h.dispose();
  }
});

// ------------------------------------------------------------ the backend dispatch (execute)

test("dispatch: plannotator selected -> the bridge runs, the first-party UI is never invoked", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: "# Param plan" },
  );
  assert.deepEqual(bridge.reviewed, ["# Param plan"], "the bridge reviewed the bytes");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.match(String(result.content[0]?.text), /DENIED/);
  assert.match(String(result.content[0]?.text), /needs work/);
});

test("dispatch: default perk-plan selection -> first-party runs with the draft bytes", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({ editor: ["# The draft\n"], select: [SKIP_OPT] });
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
    "the draft artifact landed",
  );
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  await executePlanReview(pi, ctx as unknown as ExtensionContext, fakeGating(true), bridge, {});
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the editor dialog opened once");
  assert.equal(ui.editors[0]?.prefill, "# The draft\n", "the draft bytes were displayed");
  assert.match(String(ui.editors[0]?.title), /Esc: skip/);
  assert.deepEqual(ui.selects[0]?.options, [APPROVE, DENY_OPT, SKIP_OPT]);
});

test("dispatch: a foreign non-plannotator selection (tombell) -> first-party runs", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "tombell-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({ editor: [undefined] });
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: "# Param plan" },
  );
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the first-party editor opened");
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "dismissed");
});
