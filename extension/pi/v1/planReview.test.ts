// The backend-neutral `plan_review` review door: the tool-boundary soft skips (bad_input /
// headless / no_plan), the file-first resolution (artifact → param, NEVER transcript), the
// backend DISPATCH (plannotator-selected → the event-bus bridge; ANY other selection → the
// first-party in-TUI editor review), the first-party flow (display → optional edit write-back
// via the session seam → approve/deny/skip verdict → deny-feedback editor; Esc anywhere =
// fail-open skip), the approved→save arm (either backend), the plannotator Direct-Edits arms,
// the launch chooser, the gist/objective stage routing, and the plan-flavor mappers. Fully
// offline: a fake UI drives the first-party dialogs, a recording bridge stands in for
// plannotator, and a fake pi returns the canned cold-door payload — the deps bag is the REAL
// production composition (`planSaveDepsFor`) over those fakes. See planReview.ts.

import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { GIST_DRAFT_ARTIFACT } from "../../authoring/gist/draft.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import { PLANNOTATOR_REVIEW_COMMAND } from "../../doors/plannotatorHandoff.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "../../factories/objectiveDraft.ts";
import {
  readSessionArtifact,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type EntrySink, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import type { ReportTarget } from "../../surfaces/report.ts";
import { loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import { executeObjectiveReview } from "./objectiveReview.ts";
import { installPlanBindings, planSaveDepsFor } from "./plan.ts";
import {
  applyPlannotatorDirectEdits,
  approvedSaveResult,
  executePlanReview,
  type PlanReviewV1Deps,
  reviewOutcomeResult,
} from "./planReview.ts";
import type { PlanReviewUI, ReviewLaunchUI, ReviewOutcome, WaveLaunch } from "./review.ts";

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

const FAIL_ENVELOPE = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
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

/** The production deps bag over the fakes — the ONE composition point, exercised as shipped. */
function depsFor(
  pi: ExtensionAPI,
  ctx: SessionDataCtx & ReportTarget,
  gating: ToolGating,
): PlanReviewV1Deps {
  return planSaveDepsFor(pi, ctx as unknown as ExtensionContext, gating);
}

/** A recording first-party UI: scripted editor/select/input answers, captured prompts + opts. */
function fakeUI(script: {
  editor?: (string | undefined)[];
  select?: (string | undefined)[];
  input?: (string | undefined)[];
}): PlanReviewUI &
  ReviewLaunchUI & {
    editors: { title: string; prefill: string | undefined }[];
    selects: { title: string; options: string[]; opts?: { signal?: AbortSignal } }[];
    inputs: { title: string; opts?: { signal?: AbortSignal } }[];
  } {
  const editorAnswers = [...(script.editor ?? [])];
  const selectAnswers = [...(script.select ?? [])];
  const inputAnswers = [...(script.input ?? [])];
  const ui = {
    editors: [] as { title: string; prefill: string | undefined }[],
    selects: [] as { title: string; options: string[]; opts?: { signal?: AbortSignal } }[],
    inputs: [] as { title: string; opts?: { signal?: AbortSignal } }[],
    async editor(title: string, prefill?: string) {
      ui.editors.push({ title, prefill });
      return editorAnswers.shift();
    },
    async select(title: string, options: string[], opts?: { signal?: AbortSignal }) {
      ui.selects.push({ title, options, opts });
      return selectAnswers.shift();
    },
    async input(title: string, _placeholder?: string, opts?: { signal?: AbortSignal }) {
      ui.inputs.push({ title, opts });
      return inputAnswers.shift();
    },
  };
  return ui;
}

const APPROVE = "Approve — auto-save to GitHub";
const DENY_OPT = "Deny — send feedback for revision";
const SKIP_OPT = "Skip — decide later (manual /plan-save)";
const IMPLEMENT_HERE = "Implement here — no issue saved";

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

function assistantEntry(text: string): unknown {
  return { type: "message", message: { role: "assistant", content: text } };
}

/** Run `fn` with PERK_NO_LLM pinned on (deterministic: no title generation path). */
async function withNoLlm(fn: () => Promise<void>): Promise<void> {
  const prev = process.env.PERK_NO_LLM;
  process.env.PERK_NO_LLM = "1";
  try {
    await fn();
  } finally {
    if (prev === undefined) delete process.env.PERK_NO_LLM;
    else process.env.PERK_NO_LLM = prev;
  }
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
    const details = result.details as { ok?: boolean; status?: string };
    assert.equal(details.status, "skipped");
    assert.equal(details.ok, true, "the sanctioned fail-open skip is ok:true");
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
    const details = result.details as { ok?: boolean; status?: string; error_type?: string };
    assert.equal(details.status, "unavailable");
    assert.equal(details.ok, false, "an unavailable review surface is a genuine failure");
    assert.equal(details.error_type, "unavailable");
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
    const details = result.details as {
      ok?: boolean;
      status?: string;
      reason?: string;
      error_type?: string;
    };
    assert.equal(details.status, "skipped");
    assert.equal(details.reason, "no_plan");
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_plan");
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
    const details = result.details as {
      ok?: boolean;
      status?: string;
      reason?: string;
      error_type?: string;
    };
    assert.equal(details.status, "skipped");
    assert.equal(details.reason, "bad_input");
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});

// ------------------------------------------------------------ the backend dispatch (execute)

test("execute: no draft + no param NEVER reviews the transcript -> skipped/no_plan", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" }), assistantEntry("# Scraped plan")];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
    {},
  );
  const details = result.details as {
    ok?: boolean;
    status?: string;
    reason?: string;
    error_type?: string;
  };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "no_plan");
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "no_plan");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.equal(bridge.reviewed.length, 0, "the bridge never reviewed the transcript");
  assert.match(String(result.content[0]?.text), /plan_draft/);
});

test("dispatch: plannotator selected -> the bridge runs, the first-party UI is never invoked", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
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
  const gating = fakeGating(true);
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
    {},
  );
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the editor dialog opened once");
  assert.equal(ui.editors[0]?.prefill, "# The draft\n", "the draft bytes were displayed");
  assert.match(String(ui.editors[0]?.title), /Esc: skip/);
  // The plan arm offers the 4th implement-here verdict (§8.23) — no node claim here.
  assert.deepEqual(ui.selects[0]?.options, [APPROVE, IMPLEMENT_HERE, DENY_OPT, SKIP_OPT]);
});

test("dispatch: a foreign non-plannotator selection (tombell) -> first-party runs", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "tombell-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({ editor: [undefined] });
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
    { plan: "# Param plan" },
  );
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the first-party editor opened");
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "dismissed");
});

// --------------------------------- the plannotator execute path (byte-stable)

test("execute: the artifact wins over a differing param; the ignored param is flagged", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlanProvider(cwd, "plannotator-plan");
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const ctx = headfulCtx(cwd, branch);
    assert.ok(
      writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
      "the draft artifact landed",
    );
    const bridge = cannedBridge(APPROVED);
    const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      bridge,
      depsFor(pi, ctx, gating),
      { plan: "# A different param plan" },
    );
    assert.deepEqual(bridge.reviewed, ["# The draft\n"], "the artifact bytes were reviewed");
    assert.match(String(result.content[0]?.text), /APPROVED/);
    assert.match(
      String(result.content[0]?.text),
      /differing plan param ignored — the validated draft was reviewed and saved/,
    );
  });
});

test("execute: approved (bridge) -> auto-save runs, gate exits, result terminates", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlanProvider(cwd, "plannotator-plan");
    const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
    const ctx = headfulCtx(cwd, branch);
    assert.ok(
      writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
      "the draft artifact landed",
    );
    const argvs: string[][] = [];
    const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(APPROVED),
      depsFor(pi, ctx, gating),
      {},
    );
    const argv = argvs[0] ?? [];
    assert.deepEqual(
      argv.slice(0, 2),
      ["plan", "save"],
      "the cold door ran the merged `perk plan save`",
    );
    assert.ok(argv.includes("--json"), "json mode");
    assert.ok(argv.includes("--plan-file"), "the plan rode the stdin channel");
    assert.equal(result.terminate, true, "a saved approval terminates the turn");
    const details = result.details as {
      ok?: boolean;
      saved?: boolean;
      gateExited?: boolean;
      edited?: boolean;
    };
    assert.equal(details.ok, true);
    assert.equal(details.saved, true);
    assert.equal(details.gateExited, true);
    assert.equal(details.edited, undefined, "no edited flag on the bridge path");
    assert.equal(gating.exits, 1, "the gate was exited once (via the approval-save seam)");
    assert.match(String(result.content[0]?.text), /Saved plan #42/);
    assert.doesNotMatch(String(result.content[0]?.text), /human edits were written back/);
  });
});

test("execute: approved but the save fails -> non-terminating, gate stays on, /plan-save failsafe", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlanProvider(cwd, "plannotator-plan");
    const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
    const ctx = headfulCtx(cwd, branch);
    assert.ok(
      writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
      "the draft artifact landed",
    );
    const pi = fakeColdDoorPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(APPROVED),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(result.terminate, undefined, "a failed auto-save never terminates");
    const details = result.details as { ok?: boolean; saved?: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "save_failed");
    assert.equal(details.saved, false);
    assert.equal(gating.exits, 0, "the gate stays on");
    const text = String(result.content[0]?.text);
    assert.match(text, /APPROVED/);
    assert.match(text, /auto-save FAILED/);
    assert.match(text, /gh exploded/);
    assert.match(text, /\/plan-save/);
  });
});

// ------------------------------------------- the first-party execute path (approve/deny/edit)

test("first-party approve, no edits -> the approval save runs with the reviewed bytes, terminating", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
    const ui = fakeUI({ editor: ["# The draft\n"], select: [APPROVE] });
    const ctx = headfulCtx(cwd, branch, ui);
    assert.ok(
      writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
      "the draft artifact landed",
    );
    const argvs: string[][] = [];
    const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(DENIED),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(result.terminate, true, "a saved approval terminates the turn");
    const details = result.details as {
      ok?: boolean;
      saved?: boolean;
      gateExited?: boolean;
      edited?: boolean;
    };
    assert.equal(details.ok, true);
    assert.equal(details.saved, true);
    assert.equal(details.gateExited, true);
    assert.equal(details.edited, undefined, "no edit -> no edited flag");
    assert.equal(gating.exits, 1);
    const planFile = argvs[0]?.[argvs[0].indexOf("--plan-file") + 1];
    assert.ok(planFile, "the plan rode the stdin channel");
    assert.equal(
      readFileSync(planFile, "utf8"),
      "# The draft",
      "the reviewed bytes were saved (savePlan trims)",
    );
    assert.doesNotMatch(String(result.content[0]?.text), /human edits were written back/);
  });
});

test("first-party approve with edits -> write-back to the draft, edited bytes saved + flagged", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
    const ui = fakeUI({ editor: ["# The draft, edited by the human\n"], select: [APPROVE] });
    const ctx = headfulCtx(cwd, branch, ui);
    const drafted = writeSessionArtifact(
      fakeSink(branch),
      ctx,
      PLAN_DRAFT_ARTIFACT,
      "# The draft\n",
    );
    assert.ok(drafted, "the draft artifact landed");
    const argvs: string[][] = [];
    const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(DENIED),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(
      readFileSync(drafted, "utf8"),
      "# The draft, edited by the human\n",
      "the edits were written back to the draft artifact BEFORE the verdict",
    );
    const planFile = argvs[0]?.[argvs[0].indexOf("--plan-file") + 1];
    assert.ok(planFile, "the plan rode the stdin channel");
    assert.equal(
      readFileSync(planFile, "utf8"),
      "# The draft, edited by the human",
      "the approval save received the edited bytes (savePlan trims)",
    );
    const details = result.details as { ok?: boolean; edited?: boolean; saved?: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.edited, true);
    assert.equal(details.saved, true);
    assert.match(
      String(result.content[0]?.text),
      /human edits were written back to the draft and saved/,
    );
  });
});

test("first-party: a failed edit write-back aborts the review fail-open, nothing saved", async () => {
  // No run_id ⇒ the draft write rejects (no identity); the plan param is the reviewed source (no
  // artifact needs a run_id to resolve), so the review reaches the editor — then the edit
  // write-back fails and the review aborts BEFORE any verdict.
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({})];
  const ui = fakeUI({ editor: ["# Edited\n"], select: [APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    depsFor(pi, ctx, gating),
    { plan: "# Param plan" },
  );
  const wbDetails = result.details as { ok?: boolean; status?: string; error_type?: string };
  assert.equal(wbDetails.status, "unavailable");
  assert.equal(wbDetails.ok, false);
  assert.equal(wbDetails.error_type, "unavailable");
  const text = String(result.content[0]?.text);
  assert.match(text, /WARNING/);
  assert.match(text, /could not write the edited draft back/);
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(argvs.length, 0, "the approval save was never called");
});

test("first-party deny + feedback -> DENIED text with the feedback + plan_draft redirect, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({
    editor: ["# Param plan", "step 3 is underspecified"],
    select: [DENY_OPT],
  });
  const ctx = headfulCtx(cwd, branch, ui);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(APPROVED),
    depsFor(pi, ctx, gating),
    { plan: "# Param plan" },
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /DENIED/);
  assert.match(text, /rewrite the working draft with plan_draft/);
  assert.match(text, /step 3 is underspecified/);
  assert.equal((result.details as { ok?: boolean }).ok, true, "a deny is a successful review");
  assert.equal(argvs.length, 0, "no save on a deny");
  assert.equal(ui.editors[1]?.title.includes("Deny feedback"), true);
});

test("first-party: editor dismissed (Esc) -> skipped/dismissed, no verdict, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ui = fakeUI({ editor: [undefined] });
  const ctx = headfulCtx(cwd, branch, ui);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(APPROVED),
    depsFor(pi, ctx, gating),
    { plan: "# Param plan" },
  );
  const details = result.details as { ok?: boolean; status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "dismissed");
  assert.equal(details.ok, true, "a dismissal is a sanctioned fail-open skip");
  assert.match(String(result.content[0]?.text), /\/plan-save \(the manual failsafe\)/);
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(argvs.length, 0, "no save");
});

// ------------------------------------------- the first-party implement-here verdict (§8.23)

test("first-party implement-here -> gate exited, NON-terminating guidance result, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ui = fakeUI({ editor: ["# The draft\n"], select: [IMPLEMENT_HERE] });
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
    "the draft artifact landed",
  );
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.deepEqual(
    ui.selects[0]?.options,
    [APPROVE, IMPLEMENT_HERE, DENY_OPT, SKIP_OPT],
    "the 4-option select, implement-here adjacent to approve",
  );
  assert.equal(result.terminate, undefined, "implement-here never terminates");
  assert.equal(gating.exits, 1, "the gate exited via the implement-here seam");
  assert.equal(argvs.length, 0, "NO save — no cold door invoked");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.status, "implement-here");
  assert.equal(details.saved, false);
  assert.equal(details.gateExited, true);
  assert.ok(details.reviewId, "a reviewId was minted");
  assert.equal(details.edited, undefined, "no edit -> the edited key is absent");
  const text = String(result.content[0]?.text);
  assert.match(text, /IMPLEMENT HERE/);
  assert.match(text, /Do NOT commit, branch, or push/);
  assert.match(text, /\/plan-save can still create the canonical issue later/);
  assert.doesNotMatch(text, /implement THESE final bytes/, "no inlined plan without edits");
});

test("first-party edited then implement-here -> the final reviewed bytes are inlined", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ui = fakeUI({ editor: ["# The draft, edited by the human\n"], select: [IMPLEMENT_HERE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const drafted = writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n");
  assert.ok(drafted, "the draft artifact landed");
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.equal(
    readFileSync(drafted, "utf8"),
    "# The draft, edited by the human\n",
    "the edits were still written back to the draft BEFORE the verdict",
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /The human edited the plan during review; implement THESE final bytes:/);
  assert.match(text, /# The draft, edited by the human/);
  assert.equal((result.details as { edited?: boolean }).edited, true);
});

test("first-party: a seeded node claim suppresses implement-here (the 3-option select)", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [
    stateEntry({
      run_id: "RID",
      mode: "read-only",
      objective_node_claim: { objective: "115", node: "1.2" },
    }),
  ];
  const ui = fakeUI({ editor: ["# The draft\n"], select: [SKIP_OPT] });
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
    "the draft artifact landed",
  );
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.deepEqual(
    ui.selects[0]?.options,
    [APPROVE, DENY_OPT, SKIP_OPT],
    "no implement-here option in an objective-node planning session",
  );
});

test("first-party: the COLD-claim record suppresses implement-here too", async () => {
  // The cold objective-plan claim (session_start persists objective_node_claim from the
  // handoff's objective_id/node_id alongside run_id/mode/stage) reaches the same suppression:
  // no 4th verdict in a cold factory session.
  const cwd = scaffoldRepo();
  const branch: unknown[] = [
    stateEntry({
      run_id: "01RID",
      mode: "read-only",
      stage: "objective-plan",
      objective_node_claim: { objective: "7", node: "2.3" },
    }),
  ];
  const ui = fakeUI({ editor: ["# The draft\n"], select: [SKIP_OPT] });
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
    "the draft artifact landed",
  );
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.deepEqual(
    ui.selects[0]?.options,
    [APPROVE, DENY_OPT, SKIP_OPT],
    "no implement-here option in a cold objective-plan session",
  );
});

test("bridge implement-here under a node claim -> the REFUSED arm (the structural backstop)", async () => {
  // The UX layer suppresses the verdict, but a bridge outcome can still carry implement-here —
  // the feature's `allowImplementHere: false` refusal must hold: nothing saved, gate untouched,
  // a loud non-terminating warning.
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [
    stateEntry({
      run_id: "RID",
      mode: "read-only",
      objective_node_claim: { objective: "115", node: "1.2" },
    }),
  ];
  const ctx = headfulCtx(cwd, branch);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
    "the draft artifact landed",
  );
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge({ status: "implement-here", reviewId: "rev-ih" }),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.equal(result.terminate, undefined, "the refusal never terminates");
  assert.equal(gating.exits, 0, "the gate stays on");
  assert.equal(argvs.length, 0, "nothing saved");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "implement_here_refused");
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "implement_here_refused");
  const text = String(result.content[0]?.text);
  assert.match(text, /WARNING: implement-here refused/);
  assert.match(text, /objective-node planning session/);
  assert.match(text, /approve the plan via plan_review or ask the user to run \/plan-save/);
});

// ------------------------------------------- the plannotator Direct Edits arm (plan subject)

const DE_BASE = "# The draft\n\nStep one.\nStep two.\n";
const DE_PATCHED = "# The draft\n\nStep one (edited by reviewer).\nStep two.\n";

/** A hand-built section mirroring plannotator's buildDirectEditsSection (v0.26.1 format pin). */
const DE_SECTION = [
  "# Direct Edits",
  "",
  "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:",
  "",
  "```diff",
  "===================================================================",
  "--- plan.md (original)",
  "+++ plan.md (edited)",
  "@@ -1,4 +1,4 @@",
  " # The draft",
  " ",
  "-Step one.",
  "+Step one (edited by reviewer).",
  " Step two.",
  "```",
].join("\n");

const DE_ANNOTATIONS = "Also add a rollback note.";
const DE_FEEDBACK_WITH_ANNOTATIONS = `${DE_SECTION}\n\n---\n\n${DE_ANNOTATIONS}`;

/** The Direct-Edits scaffold: plannotator selected, draft planted, argv-recording pi. */
function directEditsScaffold(draft = DE_BASE): {
  ctx: SessionDataCtx & ReportTarget;
  pi: ExtensionAPI;
  gating: ToolGating & { exits: number };
  argvs: string[][];
  drafted: string;
} {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = headfulCtx(cwd, branch);
  const drafted = writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, draft);
  assert.ok(drafted, "the draft artifact landed");
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  return { ctx, pi, gating: fakeGating(true), argvs, drafted };
}

test("plannotator approve + Direct Edits -> applied, written back, edited bytes saved, remainder-only feedback", async () => {
  await withNoLlm(async () => {
    const { ctx, pi, gating, argvs, drafted } = directEditsScaffold();
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de",
      feedback: DE_FEEDBACK_WITH_ANNOTATIONS,
    };
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(
      readFileSync(drafted, "utf8"),
      DE_PATCHED,
      "the applied edits were written back to the draft artifact BEFORE the save",
    );
    const argv = argvs[0] ?? [];
    const planFile = argv[argv.indexOf("--plan-file") + 1];
    assert.ok(planFile, "the plan rode the stdin channel");
    assert.equal(
      readFileSync(planFile, "utf8"),
      DE_PATCHED.trimEnd(),
      "the save received the PATCHED plan (savePlan trims)",
    );
    assert.equal(result.terminate, true, "a saved approval terminates the turn");
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, true);
    assert.equal(details.saved, true);
    assert.equal(details.edited, true, "the applied edits ride the edited detail");
    assert.equal(details.direct_edits_applied, undefined, "no failure flag on the applied arm");
    assert.equal(details.feedback, DE_ANNOTATIONS, "only the remainder survives as feedback");
    const text = String(result.content[0]?.text);
    assert.match(text, /human edits were written back to the draft and saved/);
    assert.match(text, /Also add a rollback note\./, "the annotation remainder is surfaced");
    assert.doesNotMatch(text, /# Direct Edits/, "the applied diff never renders as guidance");
    assert.doesNotMatch(text, /```diff/);
    assert.equal(gating.exits, 1, "the gate exited via the approval-save seam");
  });
});

test("plannotator approve + edits-only Direct Edits -> no remainder, no reviewer-feedback block", async () => {
  await withNoLlm(async () => {
    const { ctx, pi, gating, argvs, drafted } = directEditsScaffold();
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de2",
      feedback: DE_SECTION,
    };
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(readFileSync(drafted, "utf8"), DE_PATCHED, "edits written back");
    const argv = argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      DE_PATCHED.trimEnd(),
    );
    const details = result.details as Record<string, unknown>;
    assert.equal(details.edited, true);
    assert.equal(details.feedback, null, "edits-only feedback leaves no remainder");
    assert.doesNotMatch(String(result.content[0]?.text), /Reviewer feedback/);
  });
});

test("plannotator approve + unapplyable Direct Edits -> verbatim save + loud warning + details flag", async () => {
  await withNoLlm(async () => {
    // The diff targets different base bytes than the reviewed draft -> strict apply -> null.
    const { ctx, pi, gating, argvs, drafted } = directEditsScaffold("# A different draft\n");
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de3",
      feedback: DE_FEEDBACK_WITH_ANNOTATIONS,
    };
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(readFileSync(drafted, "utf8"), "# A different draft\n", "the draft is untouched");
    const argv = argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      "# A different draft",
      "the ORIGINAL reviewed bytes were saved verbatim",
    );
    assert.equal(result.terminate, true, "the verbatim save still terminates");
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, true);
    assert.equal(details.edited, undefined, "nothing was applied");
    assert.equal(details.direct_edits_applied, false, "the failure flag is mirrored in details");
    assert.equal(details.feedback, DE_FEEDBACK_WITH_ANNOTATIONS, "the FULL feedback survives");
    const text = String(result.content[0]?.text);
    assert.match(text, /Direct Edits could NOT be auto-applied/);
    assert.match(text, /saved WITHOUT them/);
    assert.match(text, /# Direct Edits/, "the diff remains in the surfaced feedback");
  });
});

test("plannotator approve + heading but unparseable section -> verbatim save + warning", async () => {
  await withNoLlm(async () => {
    const { ctx, pi, gating, drafted } = directEditsScaffold();
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de4",
      feedback: "# Direct Edits\n\nthe fence never arrived",
    };
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(readFileSync(drafted, "utf8"), DE_BASE, "the draft is untouched");
    const details = result.details as Record<string, unknown>;
    assert.equal(details.direct_edits_applied, false);
    assert.match(String(result.content[0]?.text), /Direct Edits could NOT be auto-applied/);
  });
});

test("plannotator approve + Direct Edits + failed write-back -> verbatim save + warning", async () => {
  await withNoLlm(async () => {
    // No run_id ⇒ the draft artifact tier is unreadable AND the draft write rejects; the plan
    // param is the reviewed source, the diff applies cleanly, but the write-back failure must
    // fall open to the verbatim path (never save bytes the artifact doesn't carry).
    const cwd = scaffoldRepo();
    selectPlanProvider(cwd, "plannotator-plan");
    const branch: unknown[] = [stateEntry({})];
    const ctx = headfulCtx(cwd, branch);
    const argvs: string[][] = [];
    const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de5",
      feedback: DE_SECTION,
    };
    const gating = fakeGating(true);
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      { plan: DE_BASE },
    );
    const argv = argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      DE_BASE.trimEnd(),
      "the ORIGINAL reviewed bytes were saved verbatim",
    );
    const details = result.details as Record<string, unknown>;
    assert.equal(details.edited, undefined);
    assert.equal(details.direct_edits_applied, false);
    assert.match(String(result.content[0]?.text), /Direct Edits could NOT be auto-applied/);
  });
});

test("plannotator approve + ordinary feedback -> byte-stable (no edits machinery engaged)", async () => {
  await withNoLlm(async () => {
    const { ctx, pi, gating, argvs, drafted } = directEditsScaffold();
    const outcome: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de6",
      feedback: "ship it; also note the edge case",
    };
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      gating,
      cannedBridge(outcome),
      depsFor(pi, ctx, gating),
      {},
    );
    assert.equal(readFileSync(drafted, "utf8"), DE_BASE, "the draft is untouched");
    const argv = argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      DE_BASE.trimEnd(),
    );
    const details = result.details as Record<string, unknown>;
    assert.equal(details.edited, undefined);
    assert.equal(details.direct_edits_applied, undefined);
    assert.equal(details.feedback, "ship it; also note the edge case");
    const text = String(result.content[0]?.text);
    assert.match(text, /Reviewer feedback \(implementation guidance/);
    assert.doesNotMatch(text, /Direct Edits/);
  });
});

test("plannotator deny + Direct Edits -> feedback passes through untouched (model-mediated)", async () => {
  const { ctx, pi, gating, argvs, drafted } = directEditsScaffold();
  const outcome: ReviewOutcome = {
    status: "completed",
    approved: false,
    reviewId: "rev-de7",
    feedback: DE_FEEDBACK_WITH_ANNOTATIONS,
  };
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(outcome),
    depsFor(pi, ctx, gating),
    {},
  );
  assert.equal(readFileSync(drafted, "utf8"), DE_BASE, "deny never mutates the draft");
  assert.equal(argvs.length, 0, "no save on a deny");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.feedback, DE_FEEDBACK_WITH_ANNOTATIONS, "the FULL feedback passes through");
  const text = String(result.content[0]?.text);
  assert.match(text, /DENIED/);
  assert.match(text, /# Direct Edits/, "the diff reaches the model for the plan_draft rewrite");
  assert.match(text, /Also add a rollback note\./);
});

// -------------------------------------- applyPlannotatorDirectEdits (the shared apply helper)

test("applyPlannotatorDirectEdits: approved + section -> patched/edited/remainder; bad section -> failed verbatim; non-approved -> pass-through", () => {
  const { ctx, pi, drafted } = directEditsScaffold();
  // approved + a clean section: the patched bytes come back, the draft is written back, and
  // only the annotation remainder survives as feedback.
  const approved: Extract<ReviewOutcome, { status: "completed" }> = {
    status: "completed",
    approved: true,
    reviewId: "rev-h1",
    feedback: DE_FEEDBACK_WITH_ANNOTATIONS,
  };
  const applied = applyPlannotatorDirectEdits(
    pi,
    ctx as unknown as ExtensionContext,
    approved,
    DE_BASE,
  );
  assert.equal(applied.reviewedPlan, DE_PATCHED);
  assert.equal(applied.edited, true);
  assert.equal(applied.directEditsFailed, false);
  assert.equal(applied.outcome.feedback, DE_ANNOTATIONS, "only the remainder survives");
  assert.equal(readFileSync(drafted, "utf8"), DE_PATCHED, "the patched bytes were written back");

  // approved + a seen-but-unhonorable heading: verbatim plan, the failure flag set, feedback
  // untouched (the diff stays surfaced for the manual follow-up).
  const bad: Extract<ReviewOutcome, { status: "completed" }> = {
    status: "completed",
    approved: true,
    reviewId: "rev-h2",
    feedback: "# Direct Edits\n\nthe fence never arrived",
  };
  const failed = applyPlannotatorDirectEdits(pi, ctx as unknown as ExtensionContext, bad, DE_BASE);
  assert.equal(failed.reviewedPlan, DE_BASE, "the plan stays verbatim");
  assert.equal(failed.edited, false);
  assert.equal(failed.directEditsFailed, true);
  assert.equal(failed.outcome, bad, "the outcome passes through untouched");

  // non-approved (DENY): the helper never inspects the feedback — everything passes through.
  const denied: Extract<ReviewOutcome, { status: "completed" }> = {
    status: "completed",
    approved: false,
    reviewId: "rev-h3",
    feedback: DE_FEEDBACK_WITH_ANNOTATIONS,
  };
  const passed = applyPlannotatorDirectEdits(
    pi,
    ctx as unknown as ExtensionContext,
    denied,
    DE_BASE,
  );
  assert.equal(passed.reviewedPlan, DE_BASE);
  assert.equal(passed.edited, false);
  assert.equal(passed.directEditsFailed, false);
  assert.equal(passed.outcome, denied);
});

// ------------------------------------------------- the launch chooser (the plannotator wave arm)

const LAUNCH_WAVE = "Browser review + reviewer wave";
const LAUNCH_PLAIN = "Browser review only";

/** A recording WaveLaunch fake: scripted presence + canned opener guidance (null = port fail). */
function fakeWave(opts: {
  present?: boolean;
  planGuidance?: string | null;
  objectiveGuidance?: string | null;
}): WaveLaunch & {
  planCalls: { draft: string; custom?: string }[];
  objectiveCalls: { rendered: string; artifactRaw: string; custom?: string }[];
} {
  const wave = {
    planCalls: [] as { draft: string; custom?: string }[],
    objectiveCalls: [] as { rendered: string; artifactRaw: string; custom?: string }[],
    present: () => opts.present ?? true,
    async plan(_ctx: ExtensionContext, o: { draft: string; custom?: string }) {
      wave.planCalls.push(o);
      return opts.planGuidance === undefined ? "PLAN WAVE GUIDANCE" : opts.planGuidance;
    },
    async objective(
      _ctx: ExtensionContext,
      o: { rendered: string; artifactRaw: string; custom?: string },
    ) {
      wave.objectiveCalls.push(o);
      return opts.objectiveGuidance === undefined
        ? "OBJECTIVE WAVE GUIDANCE"
        : opts.objectiveGuidance;
    },
  };
  return wave;
}

const CHOOSER_DRAFT = "# The working draft\n\nStep one.\n";

/** The chooser scaffold: plannotator selected, plan draft planted, scripted ui + wave. */
function chooserScaffold(script: {
  select?: (string | undefined)[];
  input?: (string | undefined)[];
}): {
  ctx: SessionDataCtx & ReportTarget;
  pi: ExtensionAPI;
  gating: ToolGating & { exits: number };
  ui: ReturnType<typeof fakeUI>;
} {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ui = fakeUI(script);
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, CHOOSER_DRAFT),
    "the draft artifact landed",
  );
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  return { ctx, pi, gating: fakeGating(true), ui };
}

test("chooser: eligible round offers the two launch flavors; 'Browser review only' -> the plain bridge review", async () => {
  const s = chooserScaffold({ select: [LAUNCH_PLAIN] });
  const wave = fakeWave({});
  const bridge = cannedBridge(DENIED);
  const result = await executePlanReview(
    s.pi,
    s.ctx as unknown as ExtensionContext,
    s.gating,
    bridge,
    depsFor(s.pi, s.ctx, s.gating),
    {},
    undefined,
    wave,
  );
  assert.equal(s.ui.selects.length, 1, "the chooser select opened once");
  assert.equal(s.ui.selects[0]?.title, "Plan review launch");
  assert.deepEqual(s.ui.selects[0]?.options, [LAUNCH_WAVE, LAUNCH_PLAIN]);
  assert.equal(s.ui.inputs.length, 0, "the plain flavor never asks for a custom angle");
  assert.equal(wave.planCalls.length, 0, "no wave launch");
  assert.deepEqual(bridge.reviewed, [CHOOSER_DRAFT], "the plain blocking review ran");
  assert.match(String(result.content[0]?.text), /DENIED/, "the existing outcome mapping held");
});

test("chooser: the wave choice -> opener runs (trimmed custom), non-terminating wave_launched, bridge never runs", async () => {
  const s = chooserScaffold({
    select: [LAUNCH_WAVE],
    input: ["  check the rollback story  "],
  });
  const wave = fakeWave({});
  const bridge = cannedBridge(DENIED);
  const result = await executePlanReview(
    s.pi,
    s.ctx as unknown as ExtensionContext,
    s.gating,
    bridge,
    depsFor(s.pi, s.ctx, s.gating),
    {},
    undefined,
    wave,
  );
  assert.equal(s.ui.inputs.length, 1, "the custom-angle input opened");
  assert.match(s.ui.inputs[0]?.title ?? "", /Custom review angle/);
  assert.deepEqual(wave.planCalls, [{ draft: CHOOSER_DRAFT, custom: "check the rollback story" }]);
  assert.equal(bridge.reviewed.length, 0, "the blocking bridge review never ran");
  assert.equal(result.terminate, undefined, "the wave result is NON-terminating");
  assert.equal(result.content[0]?.text, "PLAN WAVE GUIDANCE", "the opener's guidance verbatim");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.status, "wave_launched");
  assert.equal(details.subject, undefined, "the plan arm carries no subject key");
  assert.equal(s.gating.exits, 0, "the gate is untouched — the decision routes later");
});

test("chooser: a null opener return (port-pick failure) -> falls through to the plain review in the same call", async () => {
  const s = chooserScaffold({ select: [LAUNCH_WAVE], input: [undefined] });
  const wave = fakeWave({ planGuidance: null });
  const bridge = cannedBridge(DENIED);
  const result = await executePlanReview(
    s.pi,
    s.ctx as unknown as ExtensionContext,
    s.gating,
    bridge,
    depsFor(s.pi, s.ctx, s.gating),
    {},
    undefined,
    wave,
  );
  assert.equal(wave.planCalls.length, 1, "the opener was attempted");
  assert.deepEqual(bridge.reviewed, [CHOOSER_DRAFT], "the plain blocking review ran as fallback");
  const details = result.details as { status?: string };
  assert.equal(details.status, "completed", "the fallback review's outcome is the result");
});

test("chooser: param-tier source -> no chooser, plain review (the drafts-only law)", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const wave = fakeWave({});
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const gating = fakeGating(true);
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
    { plan: "# Param plan" },
    undefined,
    wave,
  );
  assert.equal(ui.selects.length, 0, "no chooser on a param-tier source");
  assert.equal(wave.planCalls.length, 0);
  assert.deepEqual(bridge.reviewed, ["# Param plan"]);
});

test("chooser: present() false OR wave undefined -> no chooser, byte-stable plain review", async () => {
  for (const wave of [fakeWave({ present: false }), undefined]) {
    const s = chooserScaffold({});
    const bridge = cannedBridge(DENIED);
    await executePlanReview(
      s.pi,
      s.ctx as unknown as ExtensionContext,
      s.gating,
      bridge,
      depsFor(s.pi, s.ctx, s.gating),
      {},
      undefined,
      wave,
    );
    assert.equal(s.ui.selects.length, 0, "no chooser");
    assert.deepEqual(bridge.reviewed, [CHOOSER_DRAFT], "the plain review ran unchanged");
  }
});

test("chooser: an abort landing during the awaited opener -> aborted, never wave_launched", async () => {
  // The one execute-level abort smoke (the dialog-by-dialog precedence matrix lives in
  // review.test.ts's chooseReviewLaunch unit): the turn is interrupted while the opener is in
  // flight — the resolved guidance must never be reported as a successful launch.
  const controller = new AbortController();
  const s = chooserScaffold({ select: [LAUNCH_WAVE], input: [undefined] });
  const wave = fakeWave({});
  wave.plan = async (_ctx: ExtensionContext, o: { draft: string; custom?: string }) => {
    wave.planCalls.push(o);
    controller.abort(); // the interruption lands mid-open
    return "PLAN WAVE GUIDANCE"; // a resolved open the abort must outrank
  };
  const bridge = cannedBridge(DENIED);
  const result = await executePlanReview(
    s.pi,
    s.ctx as unknown as ExtensionContext,
    s.gating,
    bridge,
    depsFor(s.pi, s.ctx, s.gating),
    {},
    controller.signal,
    wave,
  );
  const details = result.details as { status?: string };
  assert.equal(details.status, "aborted", "never wave_launched after the abort");
  assert.equal(result.terminate, undefined);
  assert.equal(bridge.reviewed.length, 0, "no blocking review after the abort");
});

// ---------------------------------------------------- the objective wave arm (baseline ordering)

/**
 * Measure how many `getBranch` calls ONE validated artifact read makes (self-adapting to seam
 * refactors) so the ordering pin below can swap the world exactly between the two reads.
 */
function measureArtifactReadCalls(): number {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const setupCtx = headfulCtx(cwd, branch);
  assert.ok(writeSessionArtifact(fakeSink(branch), setupCtx, OBJECTIVE_DRAFT_ARTIFACT, "{}"));
  let calls = 0;
  const countingCtx = {
    cwd,
    sessionManager: {
      getBranch: () => {
        calls += 1;
        return branch;
      },
    },
  } as unknown as SessionDataCtx;
  assert.ok(readSessionArtifact(countingCtx, OBJECTIVE_DRAFT_ARTIFACT) !== null);
  assert.ok(calls > 0, "the read consults the branch");
  return calls;
}

const OBJ_V1 = JSON.stringify({ schema_version: 1, prose: "Baseline prose (v1)." });
const OBJ_V2 = JSON.stringify({ schema_version: 1, prose: "Newer prose (v2)." });

test("objective wave arm: the stale-guard baseline is captured BEFORE the validated read (ordering pin)", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const setupCtx = headfulCtx(cwd, branch);
  const path = writeSessionArtifact(fakeSink(branch), setupCtx, OBJECTIVE_DRAFT_ARTIFACT, OBJ_V1);
  assert.ok(path, "v1 landed");
  const branchV1 = [...branch];
  assert.ok(
    writeSessionArtifact(fakeSink(branch), setupCtx, OBJECTIVE_DRAFT_ARTIFACT, OBJ_V2),
    "v2 landed",
  );
  const branchV2 = [...branch];
  // Rewind the world to v1; a concurrent objective_draft write (-> v2, file + pointer together)
  // fires between the two reads — after exactly one full artifact read's worth of branch reads.
  writeFileSync(path ?? "", OBJ_V1, "utf8");
  const perRead = measureArtifactReadCalls();
  let calls = 0;
  const ui = fakeUI({ select: [LAUNCH_WAVE], input: [undefined] });
  const ctx = {
    cwd,
    sessionManager: {
      getBranch: () => {
        calls += 1;
        if (calls === perRead + 1) writeFileSync(path ?? "", OBJ_V2, "utf8");
        return calls <= perRead ? branchV1 : branchV2;
      },
    },
    hasUI: true,
    ui: { notify() {}, ...ui },
  } as unknown as ExtensionContext;
  const wave = fakeWave({});
  const bridge = cannedBridge(DENIED);
  const result = await executeObjectiveReview(
    fakeColdDoorPi(branch, { stdout: PLAN_JSON }),
    ctx,
    fakeGating(true),
    bridge,
    undefined,
    wave,
  );
  assert.equal(wave.objectiveCalls.length, 1, "the objective opener launched");
  const call = wave.objectiveCalls[0];
  assert.equal(
    call?.artifactRaw,
    OBJ_V1,
    "artifactRaw is the FIRST read's bytes — the pre-validated-read baseline, never a re-read",
  );
  assert.match(
    call?.rendered ?? "",
    /Newer prose \(v2\)\./,
    "the render derives from the later read",
  );
  assert.doesNotMatch(call?.rendered ?? "", /Baseline prose/);
  assert.equal(bridge.reviewed.length, 0, "no blocking review on the wave arm");
  assert.equal(result.terminate, undefined, "non-terminating");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.status, "wave_launched");
  assert.equal(details.ok, true);
  assert.equal(details.subject, "objective");
  assert.equal(result.content[0]?.text, "OBJECTIVE WAVE GUIDANCE");
});

test("objective wave arm: a null opener return (port-pick failure) -> falls through to the plain review", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ui = fakeUI({ select: [LAUNCH_WAVE], input: [undefined] });
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, OBJECTIVE_DRAFT_ARTIFACT, OBJ_V1),
    "the objective draft landed",
  );
  const wave = fakeWave({ objectiveGuidance: null });
  const bridge = cannedBridge(DENIED);
  const result = await executeObjectiveReview(
    fakeColdDoorPi(branch, { stdout: PLAN_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    undefined,
    wave,
  );
  assert.equal(wave.objectiveCalls.length, 1, "the opener was attempted");
  assert.equal(bridge.reviewed.length, 1, "the plain blocking review ran as fallback");
  assert.match(bridge.reviewed[0] ?? "", /Baseline prose \(v1\)\./, "the RENDERED draft reviewed");
  const details = result.details as { status?: string; subject?: string };
  assert.equal(details.status, "completed", "the fallback review's outcome is the result");
  assert.equal(details.subject, "objective");
  assert.match(String(result.content[0]?.text), /DENIED/);
});

// ------------------------------------------------------------- the gist stage routing (direct)

test("gist stage: routes to runGistReviewV1 (plan param ignored; no chooser; no plan path)", async () => {
  // The injected-arm indirection died with the factories home — `pi/v1` siblings import
  // directly, so the routing pin observes the REAL gist arm: plannotator selected + a gist
  // draft planted ⇒ the bridge reviews the RENDERED gist markdown and the result carries the
  // gist subject key; the plan param never becomes a source and the plan chooser never opens.
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [
    stateEntry({ run_id: "RID", mode: "read-only", stage: "gist-author" }),
  ];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  assert.ok(
    writeSessionArtifact(
      fakeSink(branch),
      ctx,
      GIST_DRAFT_ARTIFACT,
      JSON.stringify({ schema_version: 1, prose: "A gist." }),
    ),
    "the gist draft landed",
  );
  const wave = fakeWave({});
  const bridge = cannedBridge(DENIED);
  const gating = fakeGating(true);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    depsFor(pi, ctx, gating),
    { plan: "# A plan param (never a source here)" },
    undefined,
    wave,
  );
  assert.equal(bridge.reviewed.length, 1, "the gist arm's bridge review ran");
  assert.match(bridge.reviewed[0] ?? "", /A gist\./, "the RENDERED gist draft was reviewed");
  assert.doesNotMatch(bridge.reviewed[0] ?? "", /never a source here/, "the plan param ignored");
  const details = result.details as { subject?: string; status?: string };
  assert.equal(details.subject, "gist", "the gist subject key rides the result");
  assert.equal(details.status, "completed");
  assert.equal(ui.selects.length, 0, "no chooser on the gist stage");
  assert.equal(wave.planCalls.length, 0);
  assert.equal(wave.objectiveCalls.length, 0);
});

// -------------------------------------------------------- the plan-flavor mapper delegations

test("reviewOutcomeResult/approvedSaveResult: the plan-flavor delegations hold (thin pins)", () => {
  // The full mapper-arm matrix lives in review.test.ts (the subject cores); these pin the
  // plan-flavor delegation — including the no-plan → no-source discriminant mapping.
  const dismissed = reviewOutcomeResult({ status: "dismissed" });
  assert.match(String(dismissed.content[0]?.text), /plan review dismissed/);
  assert.deepEqual(dismissed.details, { ok: true, status: "skipped", reason: "dismissed" });

  const noPlan = approvedSaveResult(
    { status: "completed", approved: true, reviewId: "rev-f" },
    { status: "no-plan" },
    { paramMismatch: false },
  );
  assert.match(String(noPlan.content[0]?.text), /auto-save FAILED \(no plan source resolved\)/);
  assert.equal((noPlan.details as { save?: unknown }).save, null);
});

// ---------------------------------------------------------------- the registration pins

/** A recording fake pi capturing `registerTool` definitions (everything else stubbed). */
interface RegisteredToolDef {
  name?: string;
  description?: string;
  promptGuidelines?: string[];
  execute?: (
    toolCallId: string,
    params: unknown,
    signal: AbortSignal | undefined,
    onUpdate: unknown,
    ctx: unknown,
  ) => Promise<{ details: Record<string, unknown>; content: { text?: string }[] }>;
}

function recordingPi(defs: RegisteredToolDef[]): ExtensionAPI {
  return {
    events: {
      emit() {},
      on() {
        return () => {};
      },
    },
    registerTool(def: unknown) {
      defs.push(def as RegisteredToolDef);
    },
    registerCommand() {},
    registerFlag() {},
    registerShortcut() {},
    getFlag() {
      return false;
    },
    on() {},
    appendEntry() {},
    async exec() {
      return { stdout: PLAN_JSON, stderr: "", code: 0, killed: false };
    },
    sendUserMessage() {},
  } as unknown as ExtensionAPI;
}

test("installPlanBindings: the injected wave deps thread through the registered tool (composition pin)", async () => {
  // The wave param is optional, so a dropped index.ts composition (or a registration that
  // forgets to forward it into execute) would compile and leave the direct-injection tests
  // green while the chooser never appears in the product — invoke the CAPTURED tool definition
  // with the deps injected at registration to pin the forwarding end-to-end.
  const s = chooserScaffold({ select: [LAUNCH_WAVE], input: [undefined] });
  const defs: RegisteredToolDef[] = [];
  const wave = fakeWave({});
  // installPlanMode resolves the provider from process.cwd() at registration time — point it at
  // the plannotator-selected scaffold so the host repo's config never skews the tier.
  const savedCwd = process.cwd();
  process.chdir((s.ctx as { cwd: string }).cwd);
  try {
    installPlanBindings(recordingPi(defs), fakeGating(true), wave);
  } finally {
    process.chdir(savedCwd);
  }
  const def = defs.find((d) => d.name === "plan_review");
  assert.ok(def?.execute, "plan_review registered with an execute");
  const result = await def?.execute?.("t1", {}, undefined, undefined, s.ctx);
  assert.equal(s.ui.selects.length, 1, "the chooser fired through the registered tool");
  assert.deepEqual(wave.planCalls, [{ draft: CHOOSER_DRAFT }], "the registered wave deps ran");
  assert.equal(result?.details.status, "wave_launched");
  assert.equal(result?.content[0]?.text, "PLAN WAVE GUIDANCE", "the opener's guidance returned");
});

test("index.ts composition: the REAL root wiring reaches wave_launched through plan_review", async () => {
  // The end-to-end pin the direct-injection tests above cannot give: the harness loads the REAL
  // extension root (index.ts), so the wave deps observed here are the ones index.ts composes —
  // deleting `installPlanBindings`'s third argument at the root turns this into the plain
  // plannotator review (no chooser, no wave_launched) and fails these asserts. The fake
  // plannotator extension supplies presence (the `plannotator-review` command), completes the
  // handshake, and immediately DENIES — so the REAL `openPlanReviewSurface` open core runs —
  // port pick included — and every background task (decision routing, readiness observer)
  // settles on its silent arm without a browser or a server.
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const selects: { title: string; options: string[] }[] = [];
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
    extraExtensions: [
      (pi) => {
        pi.registerCommand(PLANNOTATOR_REVIEW_COMMAND, {
          description: "fake plannotator (presence probe target)",
          handler: async () => {},
        });
        pi.events.on("plannotator:request", (data) => {
          const req = data as { respond?: (r: unknown) => void };
          req.respond?.({ status: "handled", result: { status: "pending", reviewId: "rev-root" } });
          setTimeout(() => {
            pi.events.emit("plannotator:review-result", {
              reviewId: "rev-root",
              approved: false,
              feedback: "root-pin deny",
            });
          }, 0);
        });
      },
    ],
  });
  try {
    // The draft artifact is the wave-eligibility requirement (drafts-only chooser).
    const written = await h.invokeTool("plan_draft", { plan: "# The composed plan\n" });
    assert.equal((written.details as { ok?: boolean }).ok, true, "the draft landed");
    const result = await h.invokeTool(
      "plan_review",
      {},
      {
        ui: {
          select: async (title: string, options: string[]) => {
            selects.push({ title, options });
            return options.find((o) => /reviewer wave/.test(o));
          },
          input: async () => undefined,
        },
      },
    );
    assert.equal(selects.length, 1, "the launch chooser appeared (wave deps present at the root)");
    assert.ok(
      selects[0]?.options.some((o) => /reviewer wave/.test(o)),
      "the chooser offered the wave flavor",
    );
    const details = result.details as { ok?: boolean; status?: string };
    assert.equal(details.status, "wave_launched", "the root-composed wave deps launched");
    assert.equal(details.ok, true);
    assert.match(
      String(result.content[0]?.text),
      /review/i,
      "the door's real guidance text returned through the tool",
    );
    // The real door's background decision task routes the deny — wait for its info report so no
    // task touches the disposed session after the test ends.
    for (let i = 0; i < 40 && !h.notifies.some((n) => /DENIED/.test(n)); i++) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    assert.ok(
      h.notifies.some((n) => /DENIED/.test(n)),
      "the browser decision routed through the real door's background task",
    );
  } finally {
    h.dispose();
  }
});
