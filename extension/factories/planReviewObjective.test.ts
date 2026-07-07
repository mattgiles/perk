// Split from planReview.test.ts: the objective review arm plus the
// objectiveReviewOutcomeResult / approvedObjectiveSaveResult pure mappers. A sibling
// file so Node's --test cross-file parallelism runs it as its own child process.

import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type SessionDataCtx, writeSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { scaffoldRepo } from "../testing/harness.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./objectiveDraft.ts";
import type { ObjectiveApprovalSaveOutcome, ObjectiveSaveResult } from "./objectiveSave.ts";
import {
  approvedObjectiveSaveResult,
  executeObjectiveReview,
  executePlanReview,
  objectiveReviewOutcomeResult,
  type PlanReviewUI,
  type ReviewOutcome,
} from "./planReview.ts";

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

// ------------------------------------------------ the defensive objective implement-here arm

test("objectiveReviewOutcomeResult: the defensive implement-here arm maps to a skip shape", () => {
  const result = objectiveReviewOutcomeResult({ status: "implement-here", reviewId: "rev-i" });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /nothing saved/);
  assert.deepEqual(result.details, {
    ok: true,
    status: "skipped",
    reason: "implement-here",
    subject: "objective",
  });
});

// ------------------------------------------------ the objective review arm

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
  const details = result.details as {
    ok?: boolean;
    status?: string;
    reason?: string;
    error_type?: string;
  };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "no_objective_draft");
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "no_objective_draft");
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
  // Approved wires into the objectiveApprovalSave seam: the STRUCTURED artifact
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
  assert.equal(details.ok, true);
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
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "save_failed");
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
  const skipDetails = result.details as { ok?: boolean; status?: string };
  assert.equal(skipDetails.status, "skipped");
  assert.equal(skipDetails.ok, true, "the sanctioned fail-open skip is ok:true");
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
  assert.equal(bridge.reviewed.length, 0, "nothing reviewed");
});

test("objectiveReviewOutcomeResult: the non-completed arms carry subject + objective texts", () => {
  const unavailable = objectiveReviewOutcomeResult({ status: "unavailable", warning: "no bus" });
  assert.match(String(unavailable.content[0]?.text), /WARNING: no bus/);
  assert.match(
    String(unavailable.content[0]?.text),
    /Present the complete objective \+ structured roadmap/,
  );
  assert.deepEqual(unavailable.details, {
    ok: false,
    error: "no bus",
    error_type: "unavailable",
    status: "unavailable",
    subject: "objective",
  });

  const aborted = objectiveReviewOutcomeResult({ status: "aborted" });
  assert.match(String(aborted.content[0]?.text), /objective review aborted \(turn interrupted\)/);
  assert.deepEqual(aborted.details, { ok: true, status: "aborted", subject: "objective" });

  const dismissed = objectiveReviewOutcomeResult({ status: "dismissed" });
  assert.match(String(dismissed.content[0]?.text), /\/objective-save \(the manual failsafe\)/);
  assert.deepEqual(dismissed.details, {
    ok: true,
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
    ok: true,
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
  assert.equal(details.ok, true);
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
  assert.equal(details.ok, false);
  assert.equal(details.error, "gh exploded");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal(details.subject, "objective");
  assert.equal((details.save as { ok?: boolean }).ok, false);
});

test("approvedObjectiveSaveResult: the defensively-unreachable no-draft arm maps to the failed shape", () => {
  const result = approvedObjectiveSaveResult(OBJECTIVE_APPROVED_FB, { status: "no-draft" });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no objective draft resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "no objective draft resolved");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});
