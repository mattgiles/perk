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
import { GIST_DRAFT_ARTIFACT } from "../authoring/gist/draft.ts";
import {
  readSessionArtifact,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./objectiveDraft.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import {
  applyPlannotatorDirectEdits,
  chooseReviewLaunch,
  executeObjectiveReview,
  executePlanReview,
  type GistReviewArm,
  type PlanReviewUI,
  type ReviewLaunchUI,
  type ReviewOutcome,
  registerPlanReview,
  type WaveLaunch,
} from "./planReview.ts";

function selectPlanProvider(cwd: string, id: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[providers]\nplan = "${id}"\n`, "utf8");
}

// ------------------------------------------------------------------------------ shared fakes

/** The injected gist arm — throws on invocation: these tests never run the gist stage. */
const noGistArm: GistReviewArm = async () => {
  throw new Error("the gist arm must not be invoked outside the gist stage");
};

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
    noGistArm,
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
  await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    noGistArm,
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
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    noGistArm,
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
      noGistArm,
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
      noGistArm,
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
      noGistArm,
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
      noGistArm,
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
      noGistArm,
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
      noGistArm,
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
    noGistArm,
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
    noGistArm,
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
    noGistArm,
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
    noGistArm,
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
  await executePlanReview(
    fakeColdDoorPi(branch, { stdout: PLAN_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    noGistArm,
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
      noGistArm,
      {},
      undefined,
      wave,
    );
    assert.equal(s.ui.selects.length, 0, "no chooser");
    assert.deepEqual(bridge.reviewed, [CHOOSER_DRAFT], "the plain review ran unchanged");
  }
});

test("chooser: an abort landing during the awaited opener -> aborted, never wave_launched", async () => {
  // The one execute-level abort smoke (the dialog-by-dialog precedence matrix lives in the
  // chooseReviewLaunch unit test below): the turn is interrupted while the opener is in flight
  // — the resolved guidance must never be reported as a successful launch.
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
    noGistArm,
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

test("gist stage: routes to the INJECTED gist arm (plan param ignored; no chooser; no plan path)", async () => {
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
  const armCalls: { bridge: unknown; gating: unknown }[] = [];
  const observingArm: GistReviewArm = async (armPi, _armCtx, armGating, armBridge) => {
    armCalls.push({ bridge: armBridge, gating: armGating });
    assert.equal(armPi, pi, "the arm receives the door's pi");
    return { content: [{ type: "text", text: "ARM RESULT" }], details: { ok: true } };
  };
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    bridge,
    observingArm,
    { plan: "# A plan param (never a source here)" },
    undefined,
    wave,
  );
  assert.equal(armCalls.length, 1, "the injected arm was called exactly once");
  assert.equal(armCalls[0]?.bridge, bridge, "the door's bridge is threaded into the arm");
  assert.equal(armCalls[0]?.gating, gating, "the door's gating is threaded into the arm");
  assert.equal(result.content[0]?.text, "ARM RESULT", "the arm's result is returned verbatim");
  assert.equal(ui.selects.length, 0, "no chooser on the gist stage");
  assert.equal(wave.planCalls.length, 0);
  assert.equal(wave.objectiveCalls.length, 0);
  assert.equal(bridge.reviewed.length, 0, "the plan path never ran");
});

// ----------------------------------------------------------- chooseReviewLaunch (unit, pure ui)

test("chooseReviewLaunch: Esc arms, trim behavior, and every abort re-check point", async () => {
  // Esc at the select -> plain (the flavor choice, never a cancel).
  {
    const ui = fakeUI({ select: [undefined] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan"), { launch: "plain" });
  }
  // The plain pick -> plain; no input dialog.
  {
    const ui = fakeUI({ select: [LAUNCH_PLAIN] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan"), { launch: "plain" });
    assert.equal(ui.inputs.length, 0);
  }
  // The wave pick + a padded custom -> trimmed custom; the caller's signal is FORWARDED to
  // both dialogs (a dropped signal would leave a real pending dialog un-dismissable on abort).
  {
    const controller = new AbortController();
    const ui = fakeUI({ select: [LAUNCH_WAVE], input: ["  the angle  "] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Objective", controller.signal), {
      launch: "wave",
      custom: "the angle",
    });
    assert.equal(ui.selects[0]?.title, "Objective review launch", "the subject noun titles it");
    assert.equal(ui.selects[0]?.opts?.signal, controller.signal, "the select gets the signal");
    assert.equal(ui.inputs[0]?.opts?.signal, controller.signal, "the input gets the signal");
  }
  // The wave pick + blank/Esc input -> wave with NO custom key.
  for (const typed of ["   ", undefined]) {
    const ui = fakeUI({ select: [LAUNCH_WAVE], input: [typed] });
    const choice = await chooseReviewLaunch(ui, "Plan");
    assert.equal(choice.launch, "wave");
    assert.equal("custom" in choice, false);
  }
  // Abort at entry: no dialog is ever opened.
  {
    const controller = new AbortController();
    controller.abort();
    const ui = fakeUI({ select: [LAUNCH_WAVE] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
    assert.equal(ui.selects.length, 0);
  }
  // Abort landing during the select outranks the resolved selection.
  {
    const controller = new AbortController();
    const ui = fakeUI({});
    ui.select = async (title: string, options: string[]) => {
      ui.selects.push({ title, options });
      controller.abort();
      return LAUNCH_WAVE;
    };
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
    assert.equal(ui.inputs.length, 0, "the input is never reached");
  }
  // Abort landing during the input outranks the resolved text.
  {
    const controller = new AbortController();
    const ui = fakeUI({ select: [LAUNCH_WAVE] });
    ui.input = async (title: string) => {
      ui.inputs.push({ title });
      controller.abort();
      return "typed text";
    };
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
  }
});

// ---------------------------------------------------------------- the registration pins

/** A recording fake pi capturing `registerTool` definitions (events stubbed for the bridge). */
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
  } as unknown as ExtensionAPI;
}

test("registerPlanReview: the tool description + a guideline name the wave arm (wave_launched)", () => {
  const defs: RegisteredToolDef[] = [];
  registerPlanReview(recordingPi(defs), fakeGating(true), noGistArm);
  const def = defs.find((d) => d.name === "plan_review");
  assert.ok(def, "plan_review registered");
  assert.match(String(def?.description), /reviewer wave/, "the description names the wave arm");
  assert.match(String(def?.description), /wave_launched/, "…and the result status");
  assert.ok(
    (def?.promptGuidelines ?? []).some((g) => g.includes("wave_launched")),
    "a guideline covers the wave_launched follow-through",
  );
});

test("registerPlanReview: the injected wave deps thread through the registered tool (composition pin)", async () => {
  // The wave param is optional, so a dropped index.ts composition (or a registration that
  // forgets to forward it into execute) would compile and leave the direct-injection tests
  // green while the chooser never appears in the product — invoke the CAPTURED tool definition
  // with the deps injected at registration to pin the forwarding end-to-end.
  const defs: RegisteredToolDef[] = [];
  const wave = fakeWave({});
  registerPlanReview(recordingPi(defs), fakeGating(true), noGistArm, wave);
  const def = defs.find((d) => d.name === "plan_review");
  assert.ok(def?.execute, "plan_review registered with an execute");
  const s = chooserScaffold({ select: [LAUNCH_WAVE], input: [undefined] });
  const result = await def?.execute?.("t1", {}, undefined, undefined, s.ctx);
  assert.equal(s.ui.selects.length, 1, "the chooser fired through the registered tool");
  assert.deepEqual(wave.planCalls, [{ draft: CHOOSER_DRAFT }], "the registered wave deps ran");
  assert.equal(result?.details.status, "wave_launched");
  assert.equal(result?.content[0]?.text, "PLAN WAVE GUIDANCE", "the opener's guidance returned");
});
