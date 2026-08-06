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
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
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

// ------------------------------------------- the plannotator Direct Edits arm (plan subject)

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
    assert.equal(gating.exits, 1, "the gate exited via the approvalSave seam");
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
    // No run_id ⇒ the draft artifact tier is unreadable AND writePlanDraft fails (no_run_id);
    // the plan param is the reviewed source, the diff applies cleanly, but the write-back
    // failure must fall open to the verbatim path (never save bytes the artifact doesn't carry).
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
    const result = await executePlanReview(
      pi,
      ctx as unknown as ExtensionContext,
      fakeGating(true),
      cannedBridge(outcome),
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
