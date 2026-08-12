// The gist review arm plus the gistReviewOutcomeResult / approvedGistSaveResult pure mappers —
// the gist sibling of planReviewObjective.test.ts. A sibling file so Node's --test cross-file
// parallelism runs it as its own child process.

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
import { GIST_DRAFT_ARTIFACT } from "./gistDraft.ts";
import type { GistApprovalSaveOutcome, GistSaveResult } from "./gistSave.ts";
import {
  approvedGistSaveResult,
  executeGistReview,
  executePlanReview,
  gistReviewOutcomeResult,
  type PlanReviewUI,
  type ReviewOutcome,
} from "./planReview.ts";

function selectPlanProvider(cwd: string, id: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[providers]\nplan = "${id}"\n`, "utf8");
}

// ------------------------------------------------------------------------------ shared fakes

const GIST_JSON = JSON.stringify({
  success: true,
  error_type: null,
  gist: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  scope: "plan",
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

// -------------------------------------------------------------------------- the gist review arm

const GIST_APPROVE = "Approve — auto-save to GitHub";
const GIST_DENY = "Deny — send feedback for revision";
const GIST_SKIP = "Skip — decide later (manual /gist-save)";

const GIST_STATE = { run_id: "RID", mode: "read-only", stage: "gist-author" };

const GIST_PAYLOAD = `${JSON.stringify({
  schema_version: 1,
  title: "Faster reviews",
  scope: "plan",
  prose: "The intent and the why.\n",
})}\n`;

/** Plant the gist-draft artifact (file + pointer) on a live branch. */
function plantGistDraft(
  ctx: SessionDataCtx & ReportTarget,
  branch: unknown[],
  content = GIST_PAYLOAD,
): string {
  const written = writeSessionArtifact(fakeSink(branch), ctx, GIST_DRAFT_ARTIFACT, content);
  assert.ok(written, "the gist draft artifact landed");
  return written;
}

test("gist arm: no draft -> skipped/no_gist_draft, no backend invoked", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON });
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
  assert.equal(details.reason, "no_gist_draft");
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "no_gist_draft");
  assert.equal(bridge.reviewed.length, 0, "the bridge was never invoked");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.match(String(result.content[0]?.text), /write the working gist with gist_draft/);
});

test("gist arm: plannotator selected -> the bridge receives the RENDERED markdown", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    {},
  );
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed once");
  const reviewed = String(bridge.reviewed[0]);
  assert.match(reviewed, /# Faster reviews/);
  assert.match(reviewed, /Scope: plan/);
  assert.match(reviewed, /The intent and the why\./);
  assert.doesNotMatch(reviewed, /schema_version/, "never raw JSON");
  assert.match(String(result.content[0]?.text), /gist DENIED/);
});

// ------------------------------------------- the plannotator Direct Edits revise arm

test("gist arm: approved via the bridge + Direct Edits -> NO save, non-terminating revise round", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const directEditsFeedback = [
    "# Direct Edits",
    "",
    "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:",
    "",
    "```diff",
    "@@ -1,1 +1,1 @@",
    "-# Faster reviews",
    "+# Faster reviews (edited)",
    "```",
  ].join("\n");
  const bridge = cannedBridge({
    status: "completed",
    approved: true,
    reviewId: "rev-gde",
    feedback: directEditsFeedback,
  });
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const gating = fakeGating(true);
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    {},
  );
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed the rendered draft");
  assert.equal(argvs.length, 0, "the gistApprovalSave seam was NEVER invoked");
  assert.equal(gating.exits, 0, "the gate stays read-only");
  assert.equal(result.terminate, undefined, "the revise round never terminates");
  assert.deepEqual(result.details, {
    ok: true,
    status: "revise",
    reason: "direct_edits",
    approved: true,
    feedback: directEditsFeedback,
    reviewId: "rev-gde",
    subject: "gist",
  });
  const text = String(result.content[0]?.text);
  assert.match(text, /gist APPROVED with direct browser edits/);
  assert.match(text, /nothing was saved/);
  assert.match(text, /`# <title>` heading hunk → title/, "the field-aware title mapping");
  assert.match(text, /`Scope:`\s+line hunk → scope/, "the field-aware scope mapping");
  assert.match(text, /prose hunks → prose/, "the field-aware prose mapping");
  assert.match(text, /call plan_review again to\s+confirm/);
  assert.match(text, /# Direct Edits/, "the FULL feedback (diff included) reaches the model");
});

test("gist arm: default selection -> first-party VIEW-ONLY, 3 verdicts; approval auto-saves the artifact", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({ editor: ["# Edited by the human\n"], select: [GIST_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const drafted = plantGistDraft(ctx, branch);
  const bridge = cannedBridge(APPROVED);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
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
  assert.match(String(ui.editors[0]?.title), /Gist review \(view only/);
  assert.match(String(ui.editors[0]?.prefill), /# Faster reviews/, "the rendered draft shown");
  assert.deepEqual(
    ui.selects[0]?.options,
    [GIST_APPROVE, GIST_DENY, GIST_SKIP],
    "3 verdicts — implement-here is never offered on the gist path",
  );
  assert.equal(
    readFileSync(drafted, "utf8"),
    GIST_PAYLOAD,
    "view-only: the edited editor return is NEVER written back to the artifact",
  );
  // Approved wires into the gistApprovalSave seam: the artifact is the save source (never the
  // editor's view-only return, never the rendered markdown).
  assert.equal(result.terminate, true, "a saved approval terminates the turn");
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "gist");
  assert.equal(argv[1], "create");
  assert.equal(argv[argv.indexOf("--title") + 1], "Faster reviews", "the draft's title");
  assert.equal(argv[argv.indexOf("--scope") + 1], "plan", "the draft's scope");
  const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
  assert.equal(
    readFileSync(bodyFile, "utf8"),
    "The intent and the why.",
    "the artifact's prose was staged (saveGist trims) — not the editor return",
  );
  assert.equal(gating.exits, 1, "the gate was exited once (via the gistApprovalSave seam)");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal(details.subject, "gist");
  assert.equal(details.approved, true);
  assert.equal(details.edited, undefined, "edited never set on the gist path");
  assert.match(String(result.content[0]?.text), /gist APPROVED by reviewer/);
  assert.match(String(result.content[0]?.text), /Saved gist 7/);
  assert.match(
    String(result.content[0]?.text),
    /Consume with: perk plan from 7/,
    "the consumption hint rides the relayed save text",
  );
});

test("gist arm: approved but the cold door fails -> non-terminating, gate stays on, failsafe", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({ editor: ["# whatever was shown"], select: [GIST_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
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
  assert.equal(details.subject, "gist");
  const text = String(result.content[0]?.text);
  assert.match(text, /gist APPROVED by reviewer, but the auto-save FAILED/);
  assert.match(text, /gh exploded/);
  assert.match(text, /\/gist-save \(the manual failsafe\)/);
});

test("gist arm: denied + feedback -> gist_draft redirect, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({
    editor: ["# whatever was shown", "say what bounds it"],
    select: [GIST_DENY],
  });
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
    {},
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /gist DENIED/);
  assert.match(text, /rewrite the working draft with gist_draft/);
  assert.match(text, /call plan_review again/);
  assert.match(text, /say what bounds it/);
  assert.equal(argvs.length, 0, "no save on a deny");
  assert.equal((result.details as { subject?: string }).subject, "gist");
});

test("gist arm: headless -> the standard skipResult", async () => {
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const cwd = scaffoldRepo();
  const ctx = { ...headfulCtx(cwd, branch), hasUI: false };
  const result = await executeGistReview(
    fakeColdDoorPi(branch, { stdout: GIST_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
  );
  const skipDetails = result.details as { ok?: boolean; status?: string };
  assert.equal(skipDetails.status, "skipped");
  assert.equal(skipDetails.ok, true, "the sanctioned fail-open skip is ok:true");
  assert.match(String(result.content[0]?.text), /no interactive review surface available/);
});

// -------------------------------------------------------- the pure mapper arms

test("gistReviewOutcomeResult: the non-completed arms carry subject + gist texts", () => {
  const unavailable = gistReviewOutcomeResult({ status: "unavailable", warning: "no bus" });
  assert.match(String(unavailable.content[0]?.text), /WARNING: no bus/);
  assert.match(String(unavailable.content[0]?.text), /Present the complete gist/);
  assert.deepEqual(unavailable.details, {
    ok: false,
    error: "no bus",
    error_type: "unavailable",
    status: "unavailable",
    subject: "gist",
  });

  const dismissed = gistReviewOutcomeResult({ status: "dismissed" });
  assert.match(String(dismissed.content[0]?.text), /\/gist-save \(the manual failsafe\)/);
  assert.deepEqual(dismissed.details, {
    ok: true,
    status: "skipped",
    reason: "dismissed",
    subject: "gist",
  });

  // The defensive implement-here arm maps to a skip shape (never offered on the gist path).
  const implementHere = gistReviewOutcomeResult({ status: "implement-here", reviewId: "rev-i" });
  assert.match(String(implementHere.content[0]?.text), /nothing saved/);
  assert.deepEqual(implementHere.details, {
    ok: true,
    status: "skipped",
    reason: "implement-here",
    subject: "gist",
  });
});

test("gistReviewOutcomeResult: completed renders DENIED only (approved routes elsewhere)", () => {
  const result = gistReviewOutcomeResult({
    status: "completed",
    approved: false,
    reviewId: "rev-g",
    feedback: "tighten the intent",
  });
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /gist DENIED/);
  assert.match(text, /rewrite the working draft with gist_draft/);
  assert.match(text, /tighten the intent/);
});

const GIST_APPROVED_FB: Extract<ReviewOutcome, { status: "completed" }> = {
  status: "completed",
  approved: true,
  reviewId: "rev-gf",
  feedback: "sharpen the scope",
};

function okGistSave(gateExited: boolean): GistApprovalSaveOutcome {
  const result: GistSaveResult = {
    content: [{ type: "text", text: "Saved gist 7 → https://gh/o/r/issues/7" }],
    details: {
      ok: true,
      gist: { id: "7", url: "https://gh/o/r/issues/7" },
      scope: "plan",
      existed: false,
    },
    terminate: true,
  };
  return { status: "saved", result, gateExited };
}

function failedGistSave(): GistApprovalSaveOutcome {
  const result: GistSaveResult = {
    content: [{ type: "text", text: "gist-save failed: gh exploded" }],
    details: { ok: false, error: "gh exploded", error_type: "github_error" },
  };
  return { status: "save-failed", result, gateExited: false };
}

test("approvedGistSaveResult: saved -> terminating, feedback as guidance, save text relayed", () => {
  const result = approvedGistSaveResult(GIST_APPROVED_FB, okGistSave(true));
  assert.equal(result.terminate, true);
  const text = String(result.content[0]?.text);
  assert.match(text, /gist APPROVED by reviewer\./);
  assert.match(
    text,
    /Reviewer feedback \(implementation guidance — the approved gist was saved verbatim\)/,
  );
  assert.match(text, /sharpen the scope/);
  assert.match(text, /Saved gist 7 → https:\/\/gh\/o\/r\/issues\/7/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.subject, "gist");
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal((details.save as { ok?: boolean }).ok, true);
});

test("approvedGistSaveResult: save-failed -> non-terminating, error surfaced, failsafe directed", () => {
  const result = approvedGistSaveResult(GIST_APPROVED_FB, failedGistSave());
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /auto-save FAILED \(gh exploded\)/);
  assert.match(text, /\/gist-save \(the manual failsafe\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.subject, "gist");
});

test("approvedGistSaveResult: the defensively-unreachable no-draft arm maps to the failed shape", () => {
  const result = approvedGistSaveResult(GIST_APPROVED_FB, { status: "no-draft" });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no gist draft resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "no gist draft resolved");
  assert.equal(details.save, null);
});
