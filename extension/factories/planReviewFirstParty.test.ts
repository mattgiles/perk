// Split from planReview.test.ts: the execute path (plannotator + first-party), the
// runFirstPartyReview pure-core arms, and the reviewOutcomeResult / approvedSaveResult
// mappers. A sibling file so Node's --test cross-file parallelism runs it as its own child.

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
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import {
  approvedSaveResult,
  executePlanReview,
  type PlanReviewUI,
  type ReviewOutcome,
  reviewOutcomeResult,
  runFirstPartyReview,
} from "./planReview.ts";
import type { ApprovalSaveOutcome, SaveResult } from "./planSave.ts";

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
  assert.match(String(result.content[0]?.text), /plan_draft/);
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
  const wbDetails = result.details as { ok?: boolean; status?: string; error_type?: string };
  assert.equal(wbDetails.status, "unavailable");
  assert.equal(wbDetails.ok, false);
  assert.equal(wbDetails.error_type, "unavailable");
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
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
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
    {},
  );
  assert.deepEqual(
    ui.selects[0]?.options,
    [APPROVE, IMPLEMENT_HERE, DENY_OPT, SKIP_OPT],
    "the 4-option select, implement-here adjacent to approve",
  );
  assert.equal(result.terminate, undefined, "implement-here never terminates");
  assert.equal(gating.exits, 1, "the gate exited via the implementHereExit seam");
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
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(DENIED),
    {},
  );
  assert.deepEqual(
    ui.selects[0]?.options,
    [APPROVE, DENY_OPT, SKIP_OPT],
    "no implement-here option in an objective-node planning session",
  );
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

test("runFirstPartyReview: the implementHere verdict returns the implement-here outcome", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: ["Impl here"] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    verdicts: { approve: "A", deny: "D", skip: "S", implementHere: "Impl here" },
  });
  assert.equal(r.outcome.status, "implement-here");
  assert.ok((r.outcome as { reviewId: string }).reviewId, "a reviewId was minted");
  assert.deepEqual(
    ui.selects[0]?.options,
    ["A", "Impl here", "D", "S"],
    "implement-here sits between approve and deny",
  );

  // A dismissed select (undefined) with implement-here offered is still dismissed — the
  // undefined-verdict comparison never matches the optional option.
  const esc = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [undefined] }),
    plan: "# Plan",
    writeDraft: noopWrite,
    verdicts: { approve: "A", deny: "D", skip: "S", implementHere: "Impl here" },
  });
  assert.deepEqual(esc.outcome, { status: "dismissed" });
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
  assert.deepEqual(result.details, { ok: true, status: "skipped", reason: "dismissed" });
});

test("reviewOutcomeResult: the defensive implement-here arm maps to a skip shape", () => {
  const result = reviewOutcomeResult({ status: "implement-here", reviewId: "rev-i" });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /nothing saved/);
  assert.deepEqual(result.details, { ok: true, status: "skipped", reason: "implement-here" });
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
  assert.equal(details.ok, true);
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
  assert.equal(details.ok, false);
  assert.equal(details.error, "gh exploded");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal((details.save as { ok?: boolean }).ok, false);
});

test("approvedSaveResult: the defensively-unreachable no-plan arm maps to the failed shape", () => {
  const result = approvedSaveResult(APPROVED_FB, { status: "no-plan" }, { paramMismatch: false });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no plan source resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "no plan source resolved");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});
