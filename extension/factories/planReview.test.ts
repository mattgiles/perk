// The backend-neutral `plan_review` review door (Node 2.5): the tool-boundary soft skips
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
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { ReportTarget } from "../report.ts";
import { type SessionDataCtx, writeSessionArtifact } from "../sessionData.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import type { ToolGating } from "../toolGating.ts";
import type { EntrySink } from "../workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "../workflowState.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./objectiveDraft.ts";
import type { ObjectiveApprovalSaveOutcome, ObjectiveSaveResult } from "./objectiveSave.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import {
  approvedObjectiveSaveResult,
  approvedSaveResult,
  executeObjectiveReview,
  executePlanReview,
  objectiveReviewOutcomeResult,
  type PlanReviewUI,
  type ReviewOutcome,
  reviewOutcomeResult,
  runFirstPartyReview,
} from "./planReview.ts";
import type { ApprovalSaveOutcome, SaveResult } from "./planSave.ts";

function selectPlanProvider(cwd: string, id: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), `[providers]\nplan = "${id}"\n`, "utf8");
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

// ------------------------------------------------ the objective review arm (#352 Node 2.2)

const OBJECTIVE_APPROVE = "Approve — auto-save to GitHub";
const OBJECTIVE_DENY = "Deny — send feedback for revision";
const OBJECTIVE_SKIP = "Skip — decide later (manual /objective-save)";

const OBJECTIVE_STATE = { run_id: "RID", mode: "read-only", stage: "objective-author" };

const OBJECTIVE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  objective: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  dry_run: false,
});
const OBJECTIVE_PAYLOAD = `${JSON.stringify({
  schema_version: 1,
  title: "Conform planning",
  prose: "The why and the design.\n",
  roadmap: [{ id: "1.1", description: "first node", depends_on: ["0.9"] }],
})}\n`;

/** Plant the objective-draft artifact (file + pointer) on a live branch. */
function plantObjectiveDraft(
  ctx: SessionDataCtx & ReportTarget,
  branch: unknown[],
  content = OBJECTIVE_PAYLOAD,
): string {
  const written = writeSessionArtifact(fakeSink(branch), ctx, OBJECTIVE_DRAFT_ARTIFACT, content);
  assert.ok(written, "the objective draft artifact landed");
  return written;
}

test("objective arm: no draft -> skipped/no_objective_draft, no backend invoked", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: "# A plan param (never a source here)" },
  );
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "no_objective_draft");
  assert.equal(bridge.reviewed.length, 0, "the bridge was never invoked");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.match(String(result.content[0]?.text), /write the working objective with objective_draft/);
});

test("objective arm: plannotator selected -> the bridge receives the RENDERED markdown", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantObjectiveDraft(ctx, branch);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    {},
  );
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed once");
  const reviewed = String(bridge.reviewed[0]);
  assert.match(reviewed, /# Conform planning/);
  assert.match(reviewed, /The why and the design\./);
  assert.match(reviewed, /\| 1\.1 \| first node \| 0\.9 \| pending \|/, "a roadmap table row");
  assert.doesNotMatch(reviewed, /schema_version/, "never raw JSON");
  assert.match(String(result.content[0]?.text), /objective DENIED/);
});

test("objective arm: default selection -> first-party VIEW-ONLY; approval auto-saves the artifact", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ui = fakeUI({ editor: ["# Edited by the human\n"], select: [OBJECTIVE_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const drafted = plantObjectiveDraft(ctx, branch);
  const bridge = cannedBridge(APPROVED);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: OBJECTIVE_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    {},
  );
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the editor dialog opened once");
  assert.match(String(ui.editors[0]?.title), /Objective review \(view only/);
  assert.match(String(ui.editors[0]?.prefill), /# Conform planning/, "the rendered draft shown");
  assert.deepEqual(ui.selects[0]?.options, [OBJECTIVE_APPROVE, OBJECTIVE_DENY, OBJECTIVE_SKIP]);
  assert.equal(
    readFileSync(drafted, "utf8"),
    OBJECTIVE_PAYLOAD,
    "view-only: the edited editor return is NEVER written back to the artifact",
  );
  // Approved wires into the objectiveApprovalSave seam (#352 Node 2.3): the STRUCTURED artifact
  // is the save source (never the editor's view-only return, never the rendered markdown).
  assert.equal(result.terminate, true, "a saved approval terminates the turn");
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "objective");
  assert.equal(argv[1], "create");
  assert.equal(
    argv[argv.indexOf("--roadmap") + 1],
    JSON.stringify([{ id: "1.1", description: "first node", depends_on: ["0.9"] }]),
    "the draft's structured roadmap rode --roadmap",
  );
  assert.equal(argv[argv.indexOf("--title") + 1], "Conform planning", "the draft's title");
  const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
  assert.equal(
    readFileSync(bodyFile, "utf8"),
    "The why and the design.",
    "the artifact's prose was staged (saveObjective trims) — not the editor return",
  );
  assert.equal(gating.exits, 1, "the gate was exited once (via the objectiveApprovalSave seam)");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal(details.subject, "objective");
  assert.equal(details.approved, true);
  assert.equal(details.edited, undefined, "edited never set on the objective path");
  assert.match(String(result.content[0]?.text), /objective APPROVED by reviewer/);
  assert.match(String(result.content[0]?.text), /Saved objective #7/);
  assert.doesNotMatch(String(result.content[0]?.text), /nothing is saved yet/);
});

test("objective arm: approved but the cold door fails -> non-terminating, gate stays on, failsafe", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ui = fakeUI({ editor: ["# whatever was shown"], select: [OBJECTIVE_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  plantObjectiveDraft(ctx, branch);
  const pi = fakeColdDoorPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
    {},
  );
  assert.equal(result.terminate, undefined, "a failed auto-save never terminates");
  assert.equal(gating.exits, 0, "the gate stays on");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, false);
  assert.equal(details.subject, "objective");
  const text = String(result.content[0]?.text);
  assert.match(text, /objective APPROVED by reviewer, but the auto-save FAILED/);
  assert.match(text, /gh exploded/);
  assert.match(text, /\/objective-save \(the manual failsafe\)/);
});

test("objective arm: approved via the plannotator bridge -> the same seam path saves the artifact", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantObjectiveDraft(ctx, branch);
  const bridge = cannedBridge(APPROVED);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: OBJECTIVE_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    {},
  );
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed the RENDERED markdown");
  assert.match(String(bridge.reviewed[0]), /# Conform planning/);
  // The save used the structured artifact, never the rendered bytes the bridge reviewed.
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "objective");
  const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
  assert.equal(readFileSync(bodyFile, "utf8"), "The why and the design.");
  assert.equal(result.terminate, true);
  assert.equal(gating.exits, 1);
  assert.equal((result.details as { saved?: boolean }).saved, true);
});

test("objective arm: denied + feedback -> objective_draft redirect, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ui = fakeUI({
    editor: ["# whatever was shown", "the roadmap is too coarse"],
    select: [OBJECTIVE_DENY],
  });
  const ctx = headfulCtx(cwd, branch, ui);
  plantObjectiveDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
    {},
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /objective DENIED/);
  assert.match(text, /rewrite the working draft with objective_draft/);
  assert.match(text, /call plan_review again/);
  assert.match(text, /the roadmap is too coarse/);
  assert.equal(argvs.length, 0, "no save on a deny");
  assert.equal((result.details as { subject?: string }).subject, "objective");
});

test("objective arm: headless -> the standard skipResult", async () => {
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const cwd = scaffoldRepo();
  const ctx = { ...headfulCtx(cwd, branch), hasUI: false };
  const result = await executeObjectiveReview(
    fakeColdDoorPi(branch, { stdout: OBJECTIVE_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
  );
  assert.equal((result.details as { status?: string }).status, "skipped");
  assert.match(String(result.content[0]?.text), /no interactive review surface available/);
});

test("objective arm: mistyped plan param still -> bad_input (decode-first order pinned)", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(OBJECTIVE_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantObjectiveDraft(ctx, branch);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: 5 },
  );
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "bad_input");
  assert.equal(bridge.reviewed.length, 0, "nothing reviewed");
});

test("objectiveReviewOutcomeResult: the non-completed arms carry subject + objective texts", () => {
  const unavailable = objectiveReviewOutcomeResult({ status: "unavailable", warning: "no bus" });
  assert.match(String(unavailable.content[0]?.text), /WARNING: no bus/);
  assert.match(
    String(unavailable.content[0]?.text),
    /Present the complete objective \+ structured roadmap/,
  );
  assert.deepEqual(unavailable.details, { status: "unavailable", subject: "objective" });

  const aborted = objectiveReviewOutcomeResult({ status: "aborted" });
  assert.match(String(aborted.content[0]?.text), /objective review aborted \(turn interrupted\)/);
  assert.deepEqual(aborted.details, { status: "aborted", subject: "objective" });

  const dismissed = objectiveReviewOutcomeResult({ status: "dismissed" });
  assert.match(String(dismissed.content[0]?.text), /\/objective-save \(the manual failsafe\)/);
  assert.deepEqual(dismissed.details, {
    status: "skipped",
    reason: "dismissed",
    subject: "objective",
  });
});

test("objectiveReviewOutcomeResult: completed renders DENIED only (approved routes elsewhere)", () => {
  // Approved-first routing: the execute path sends approved outcomes to
  // approvedObjectiveSaveResult BEFORE this mapper — completed here is the DENIED rendering.
  const result = objectiveReviewOutcomeResult({
    status: "completed",
    approved: false,
    reviewId: "rev-o",
    feedback: "tighten phase 2",
  });
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /objective DENIED/);
  assert.match(text, /rewrite the working draft with objective_draft/);
  assert.match(text, /tighten phase 2/);
  assert.deepEqual(result.details, {
    status: "completed",
    approved: false,
    feedback: "tighten phase 2",
    reviewId: "rev-o",
    subject: "objective",
  });
});

// ------------------------------------------ the approvedObjectiveSaveResult pure mapper arms

const OBJECTIVE_APPROVED_FB: Extract<ReviewOutcome, { status: "completed" }> = {
  status: "completed",
  approved: true,
  reviewId: "rev-of",
  feedback: "phase 3 can shrink",
};

function okObjectiveSave(gateExited: boolean): ObjectiveApprovalSaveOutcome {
  const result: ObjectiveSaveResult = {
    content: [{ type: "text", text: "Saved objective #7 → https://gh/o/r/issues/7" }],
    details: {
      ok: true,
      objective: { id: "7", url: "https://gh/o/r/issues/7" },
      existed: false,
    },
    terminate: true,
  };
  return { status: "saved", result, gateExited };
}

function failedObjectiveSave(): ObjectiveApprovalSaveOutcome {
  const result: ObjectiveSaveResult = {
    content: [{ type: "text", text: "objective-save failed: gh exploded" }],
    details: { ok: false, error: "gh exploded", error_type: "github_error" },
  };
  return { status: "save-failed", result, gateExited: false };
}

test("approvedObjectiveSaveResult: saved -> terminating, feedback as guidance, save text relayed", () => {
  const result = approvedObjectiveSaveResult(OBJECTIVE_APPROVED_FB, okObjectiveSave(true));
  assert.equal(result.terminate, true);
  const text = String(result.content[0]?.text);
  assert.match(text, /objective APPROVED by reviewer\./);
  assert.match(
    text,
    /Reviewer feedback \(implementation guidance — the approved objective was saved verbatim\)/,
  );
  assert.match(text, /phase 3 can shrink/);
  assert.match(text, /Saved objective #7 → https:\/\/gh\/o\/r\/issues\/7/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.status, "completed");
  assert.equal(details.approved, true);
  assert.equal(details.reviewId, "rev-of");
  assert.equal(details.feedback, "phase 3 can shrink");
  assert.equal(details.subject, "objective");
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal((details.save as { ok?: boolean }).ok, true);
});

test("approvedObjectiveSaveResult: save-failed -> non-terminating, error surfaced, failsafe directed", () => {
  const result = approvedObjectiveSaveResult(OBJECTIVE_APPROVED_FB, failedObjectiveSave());
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /auto-save FAILED \(gh exploded\)/);
  assert.match(text, /\/objective-save \(the manual failsafe\)/);
  assert.match(text, /phase 3 can shrink/, "feedback still surfaced");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, false);
  assert.equal(details.subject, "objective");
  assert.equal((details.save as { ok?: boolean }).ok, false);
});

test("approvedObjectiveSaveResult: the defensively-unreachable no-draft arm maps to the failed shape", () => {
  const result = approvedObjectiveSaveResult(OBJECTIVE_APPROVED_FB, { status: "no-draft" });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no objective draft resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});

test("execute: no draft + no param NEVER reviews the transcript -> skipped/no_plan", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID" }), assistantEntry("# Scraped plan")];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    {},
  );
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "no_plan");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.match(String(result.content[0]?.text), /plan_draft/);
});

// --------------------------------- the plannotator execute path (byte-stable from Node 2.4)

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
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      fakeGating(true),
      bridge,
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
      {},
    );
    const argv = argvs[0] ?? [];
    assert.equal(argv[0], "plan-save", "the cold door ran plan-save");
    assert.ok(argv.includes("--json"), "json mode");
    assert.ok(argv.includes("--plan-file"), "the plan rode the stdin channel");
    assert.equal(result.terminate, true, "a saved approval terminates the turn");
    const details = result.details as { saved?: boolean; gateExited?: boolean; edited?: boolean };
    assert.equal(details.saved, true);
    assert.equal(details.gateExited, true);
    assert.equal(details.edited, undefined, "no edited flag on the bridge path");
    assert.equal(gating.exits, 1, "the gate was exited once (via the approvalSave seam)");
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
      {},
    );
    assert.equal(result.terminate, undefined, "a failed auto-save never terminates");
    const details = result.details as { saved?: boolean };
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

test("first-party approve, no edits -> approvalSave runs with the reviewed bytes, terminating", async () => {
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
      {},
    );
    assert.equal(result.terminate, true, "a saved approval terminates the turn");
    const details = result.details as { saved?: boolean; gateExited?: boolean; edited?: boolean };
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
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      fakeGating(true),
      cannedBridge(DENIED),
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
      "approvalSave received the edited bytes (savePlan trims)",
    );
    const details = result.details as { edited?: boolean; saved?: boolean };
    assert.equal(details.edited, true);
    assert.equal(details.saved, true);
    assert.match(
      String(result.content[0]?.text),
      /human edits were written back to the draft and saved/,
    );
  });
});

test("first-party: a failed edit write-back aborts the review fail-open, nothing saved", async () => {
  // No run_id ⇒ writePlanDraft fails (no_run_id); the plan param is the reviewed source (no
  // artifact needs a run_id to resolve), so the review reaches the editor — then the edit
  // write-back fails and the review aborts BEFORE any verdict.
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({})];
  const ui = fakeUI({ editor: ["# Edited\n"], select: [APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON, argvs });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(DENIED),
    { plan: "# Param plan" },
  );
  assert.equal((result.details as { status?: string }).status, "unavailable");
  const text = String(result.content[0]?.text);
  assert.match(text, /WARNING/);
  assert.match(text, /could not write the edited draft back/);
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(argvs.length, 0, "approvalSave was never called");
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
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
    { plan: "# Param plan" },
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /DENIED/);
  assert.match(text, /rewrite the working draft with plan_draft/);
  assert.match(text, /step 3 is underspecified/);
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
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
    { plan: "# Param plan" },
  );
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "dismissed");
  assert.match(String(result.content[0]?.text), /\/plan-save \(the manual failsafe\)/);
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(argvs.length, 0, "no save");
});

// --------------------------------------------------- runFirstPartyReview (the pure core arms)

const noopWrite = (_plan: string): boolean => true;

test("runFirstPartyReview: approve without edits", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: [APPROVE] });
  const r = await runFirstPartyReview({ ui, plan: "# Plan", writeDraft: noopWrite });
  assert.equal(r.outcome.status, "completed");
  assert.equal((r.outcome as { approved: boolean }).approved, true);
  assert.ok((r.outcome as { reviewId: string }).reviewId, "a reviewId was minted");
  assert.equal(r.plan, "# Plan");
  assert.equal(r.edited, false);
});

test("runFirstPartyReview: a blank edit result is treated as no-edit", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["   \n"], select: [APPROVE] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
  });
  assert.equal(writes.length, 0, "no write-back for a blank edit");
  assert.equal(r.plan, "# Plan", "the original bytes stay the reviewed plan");
  assert.equal(r.edited, false);
});

test("runFirstPartyReview: an edit writes back before the verdict; the edited plan is returned", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["# Plan v2"], select: [APPROVE] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
  });
  assert.deepEqual(writes, ["# Plan v2"]);
  assert.equal(r.plan, "# Plan v2");
  assert.equal(r.edited, true);
  assert.equal(r.outcome.status, "completed");
});

test("runFirstPartyReview: write-back failure -> unavailable, no verdict prompt", async () => {
  const ui = fakeUI({ editor: ["# Plan v2"], select: [APPROVE] });
  const r = await runFirstPartyReview({ ui, plan: "# Plan", writeDraft: () => false });
  assert.equal(r.outcome.status, "unavailable");
  assert.match(
    (r.outcome as { warning: string }).warning,
    /could not write the edited draft back .* nothing saved/,
  );
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(r.edited, false);
});

test("runFirstPartyReview: deny -> the feedback editor; blank/dismissed feedback is omitted", async () => {
  const withFeedback = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", "too vague"], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal(withFeedback.outcome.status, "completed");
  assert.equal((withFeedback.outcome as { approved: boolean }).approved, false);
  assert.equal((withFeedback.outcome as { feedback?: string }).feedback, "too vague");

  const blank = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", "  "], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal((blank.outcome as { feedback?: string }).feedback, undefined);

  const dismissed = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", undefined], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal(dismissed.outcome.status, "completed", "a dismissed feedback editor still denies");
  assert.equal((dismissed.outcome as { feedback?: string }).feedback, undefined);
});

test("runFirstPartyReview: viewOnly skips the write-back; custom title/labels rendered", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["# Plan v2 (edited)"], select: ["Custom approve"] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
    viewOnly: true,
    editorTitle: "Custom title",
    verdicts: { approve: "Custom approve", deny: "Custom deny", skip: "Custom skip" },
  });
  assert.equal(writes.length, 0, "viewOnly never writes back");
  assert.equal(r.plan, "# Plan", "the original bytes are returned unchanged");
  assert.equal(r.edited, false);
  assert.equal(r.outcome.status, "completed");
  assert.equal((r.outcome as { approved: boolean }).approved, true);
  assert.equal(ui.editors[0]?.title, "Custom title");
  assert.deepEqual(ui.selects[0]?.options, ["Custom approve", "Custom deny", "Custom skip"]);
});

test("runFirstPartyReview: verdict dismissed or Skip -> dismissed", async () => {
  const esc = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [undefined] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.deepEqual(esc.outcome, { status: "dismissed" });

  const skip = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [SKIP_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.deepEqual(skip.outcome, { status: "dismissed" });
});

test("runFirstPartyReview: an already-aborted signal short-circuits before any dialog", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: [APPROVE] });
  const controller = new AbortController();
  controller.abort();
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    signal: controller.signal,
  });
  assert.deepEqual(r.outcome, { status: "aborted" });
  assert.equal(ui.editors.length, 0, "no dialog after an abort");
});

test("runFirstPartyReview: an abort during the editor dialog wins over its result", async () => {
  const controller = new AbortController();
  const ui: PlanReviewUI = {
    async editor() {
      controller.abort();
      return "# Plan";
    },
    async select() {
      throw new Error("the verdict prompt must never open after an abort");
    },
  };
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    signal: controller.signal,
  });
  assert.deepEqual(r.outcome, { status: "aborted" });
});

test("reviewOutcomeResult: the dismissed arm renders the manual-failsafe skip", () => {
  const result = reviewOutcomeResult({ status: "dismissed" });
  assert.match(String(result.content[0]?.text), /plan review dismissed/);
  assert.match(String(result.content[0]?.text), /\/plan-save \(the manual failsafe\)/);
  assert.deepEqual(result.details, { status: "skipped", reason: "dismissed" });
});

// --------------------------------------------------- the approvedSaveResult pure mapper arms

const APPROVED_FB: Extract<ReviewOutcome, { status: "completed" }> = {
  status: "completed",
  approved: true,
  reviewId: "rev-f",
  feedback: "ship it; watch the edge case",
};

function okSave(gateExited: boolean): ApprovalSaveOutcome {
  const result: SaveResult = {
    content: [{ type: "text", text: "Saved plan #42 → https://gh/o/r/issues/42" }],
    details: {
      ok: true,
      issue: { id: "42", url: "https://gh/o/r/issues/42" },
      plan_ref: {
        provider: "github",
        pr_id: "42",
        url: "https://gh/o/r/issues/42",
        labels: ["perk:plan"],
        objective_id: null,
      },
      cached: true,
      existed: false,
      updated: false,
      objective_node: null,
      plan_source: "plan-draft",
    },
    terminate: true,
  };
  return { status: "saved", result, gateExited };
}

function failedSave(): ApprovalSaveOutcome {
  const result: SaveResult = {
    content: [{ type: "text", text: "plan-save failed: gh exploded" }],
    details: { ok: false, error: "gh exploded", error_type: "github_error" },
  };
  return { status: "save-failed", result, gateExited: false };
}

test("approvedSaveResult: saved -> terminating, feedback verbatim, save message relayed", () => {
  const result = approvedSaveResult(APPROVED_FB, okSave(true), { paramMismatch: false });
  assert.equal(result.terminate, true);
  const text = String(result.content[0]?.text);
  assert.match(text, /plan APPROVED by reviewer\./);
  assert.match(text, /Reviewer feedback \(implementation guidance/);
  assert.match(text, /ship it; watch the edge case/);
  assert.match(text, /Saved plan #42 → https:\/\/gh\/o\/r\/issues\/42/);
  assert.doesNotMatch(text, /differing plan param ignored/);
  assert.doesNotMatch(text, /human edits were written back/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.status, "completed");
  assert.equal(details.approved, true);
  assert.equal(details.reviewId, "rev-f");
  assert.equal(details.feedback, "ship it; watch the edge case");
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal(details.edited, undefined);
  assert.equal((details.save as { ok?: boolean }).ok, true);
});

test("approvedSaveResult: edited -> the edits-written-back suffix + details.edited", () => {
  const result = approvedSaveResult(APPROVED_FB, okSave(true), {
    paramMismatch: false,
    edited: true,
  });
  assert.match(
    String(result.content[0]?.text),
    /human edits were written back to the draft and saved/,
  );
  assert.equal((result.details as { edited?: boolean }).edited, true);
});

test("approvedSaveResult: paramMismatch -> the ignored param is flagged in the text", () => {
  const result = approvedSaveResult(APPROVED_FB, okSave(false), { paramMismatch: true });
  assert.match(
    String(result.content[0]?.text),
    /⚠ differing plan param ignored — the validated draft was reviewed and saved\./,
  );
  assert.equal((result.details as { gateExited?: boolean }).gateExited, false);
});

test("approvedSaveResult: save-failed -> non-terminating, error surfaced, failsafe directed", () => {
  const result = approvedSaveResult(APPROVED_FB, failedSave(), { paramMismatch: false });
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /auto-save FAILED \(gh exploded\)/);
  assert.match(text, /\/plan-save \(the manual failsafe\)/);
  assert.match(text, /ship it; watch the edge case/, "feedback still surfaced");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, false);
  assert.equal((details.save as { ok?: boolean }).ok, false);
});

test("approvedSaveResult: the defensively-unreachable no-plan arm maps to the failed shape", () => {
  const result = approvedSaveResult(APPROVED_FB, { status: "no-plan" }, { paramMismatch: false });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no plan source resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});
