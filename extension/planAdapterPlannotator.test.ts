// The plannotator plan adapter (augment posture): injection only when (gate active AND
// plannotator-plan selected AND not objective-author), stale-marker strip on deselect, and the
// `plan_review` bridge tool's full path matrix — soft skips (not selected / headless /
// objective-author / no plan), the file-first resolution (artifact → param, NEVER transcript),
// the bounded handshake (timeout / unavailable), the human decision (approved → the approvalSave
// seam / denied + feedback), and the turn-abort path. Fully offline: the fake plannotator is a
// test listener on an event bus that calls `respond(...)` and emits `plannotator:review-result`;
// the execute core runs over a fake bridge + a fake gating + a fake cold-door pi (the
// planSave.test.ts recipe). See planAdapterPlannotator.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  approvedSaveResult,
  createPlannotatorBridge,
  executePlanReview,
  isPlannotatorPlanSelected,
  PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
  type PlannotatorBus,
  type ReviewOutcome,
  reviewOutcomeResult,
} from "./planAdapterPlannotator.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import { PLAN_CONTEXT_TYPE } from "./planMode.ts";
import type { ApprovalSaveOutcome, SaveResult } from "./planSave.ts";
import type { ReportTarget } from "./report.ts";
import { type SessionDataCtx, writeSessionArtifact } from "./sessionData.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";
import type { ToolGating } from "./toolGating.ts";
import type { EntrySink } from "./workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

function selectPlannotator(cwd: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[providers]\nplan = "plannotator-plan"\n', "utf8");
}

/** A minimal in-memory event bus (the fake `pi.events` for the pure bridge tests). */
function fakeBus(): PlannotatorBus & { handlers: Map<string, ((data: unknown) => void)[]> } {
  const handlers = new Map<string, ((data: unknown) => void)[]>();
  return {
    handlers,
    emit(channel, data) {
      for (const h of handlers.get(channel) ?? []) h(data);
    },
    on(channel, handler) {
      handlers.set(channel, [...(handlers.get(channel) ?? []), handler]);
    },
  };
}

/** The plannotator:request envelope the fake listener receives (pinned, see the adapter header). */
interface RequestEnvelope {
  requestId: string;
  action: string;
  payload: { planContent: string; origin?: string };
  respond: (response: unknown) => void;
}

test("isPlannotatorPlanSelected: true only when [providers] plan = plannotator-plan", () => {
  const def = scaffoldRepo();
  assert.equal(isPlannotatorPlanSelected(def), false);
  const sel = scaffoldRepo();
  selectPlannotator(sel);
  assert.equal(isPlannotatorPlanSelected(sel), true);
});

// --------------------------------------------------------------------------- injection / strip

test("plannotator selected + gate active: bridge context injected alongside plan context", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE &&
          String(m.content).includes("[PLAN ADAPTER: PLANNOTATOR]") &&
          String(m.content).includes("plan_review"),
      ),
      "the bridge context is injected (directs the plan_review review step)",
    );
  } finally {
    h.dispose();
  }
});

test("plannotator selected but gate off: no bridge context injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
      ),
      false,
      "no bridge context while the read-only gate is off",
    );
  } finally {
    h.dispose();
  }
});

test("objective-author session: the bridge context defers (objectiveAuthor owns that session)", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(
      (await h.emitBeforeAgentStart()).some(
        (m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
      ),
      false,
      "no bridge context in an objective-author session (mirrors planMode's stage exception)",
    );
  } finally {
    h.dispose();
  }
});

test("default selection: shim injects nothing and strips a stale bridge marker", async () => {
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
      "perk's own plan context still injects on the default path",
    );
    assert.equal(
      injected.some((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE),
      false,
      "no bridge context injected on the default path",
    );
    const stale = [
      {
        customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        content: "[PLAN ADAPTER: PLANNOTATOR]\nstale",
      },
      { role: "user", content: "[PLAN ADAPTER: PLANNOTATOR] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE),
      false,
      "stale bridge custom message stripped on the default path",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[PLAN ADAPTER: PLANNOTATOR]")),
      false,
      "stale bridge marker stripped from user turns on the default path",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});

// -------------------------------------------------------------- the plan_review tool (soft skips)

test("plan_review: not plannotator-selected -> soft skip", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", { plan: "# A plan" });
    assert.equal((result.details as { status?: string }).status, "skipped");
    assert.match(String(result.content[0]?.text), /no external review surface configured/);
  } finally {
    h.dispose();
  }
});

test("plan_review: headless -> soft skip (fail-open; never wedges a CI/supervisor run)", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    headful: false,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    const result = await h.invokeTool("plan_review", { plan: "# A plan" });
    assert.equal((result.details as { status?: string }).status, "skipped");
  } finally {
    h.dispose();
  }
});

test("plan_review: no plannotator listener -> handshake timeout -> loud unavailable skip", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
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

// ------------------------------------------------------- the bridge core (fake plannotator bus)

test("bridge: an `unavailable` handshake response -> unavailable outcome with the error detail", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({ status: "unavailable", error: "no browser" });
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.equal(outcome.status, "unavailable");
  assert.match((outcome as { warning: string }).warning, /unavailable: no browser/);
  const result = reviewOutcomeResult(outcome);
  assert.equal((result.details as { status?: string }).status, "unavailable");
  assert.match(String(result.content[0]?.text), /Present the complete plan to the user/);
});

test("bridge: approved decision -> completed outcome (the execute path saves; not rendered here)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const req = data as RequestEnvelope;
    assert.equal(req.action, "plan-review");
    assert.equal(req.payload.planContent, "# A plan");
    assert.equal(req.payload.origin, "perk");
    req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-1" } });
    // The human decision arrives later on the result channel.
    setTimeout(() => {
      bus.emit("plannotator:review-result", {
        reviewId: "rev-1",
        approved: true,
        feedback: "ship it; also note the edge case",
      });
    }, 10);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.deepEqual(outcome, {
    status: "completed",
    approved: true,
    feedback: "ship it; also note the edge case",
    reviewId: "rev-1",
  });
});

test("bridge: denied decision -> result says DENIED + revise + the feedback", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const req = data as RequestEnvelope;
    req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-2" } });
    setTimeout(() => {
      bus.emit("plannotator:review-result", {
        reviewId: "rev-2",
        approved: false,
        feedback: "step 3 is underspecified",
      });
    }, 10);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.equal(outcome.status, "completed");
  assert.equal((outcome as { approved: boolean }).approved, false);
  const result = reviewOutcomeResult(outcome);
  const text = String(result.content[0]?.text);
  assert.match(text, /DENIED/);
  assert.match(text, /rewrite the working draft with plan_draft/);
  assert.match(text, /call plan_review again/);
  assert.match(text, /step 3 is underspecified/);
});

test("bridge: a mismatched reviewId on the result channel is ignored (no resolution)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const req = data as RequestEnvelope;
    req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-3" } });
    setTimeout(() => {
      bus.emit("plannotator:review-result", { reviewId: "other", approved: true });
      bus.emit("plannotator:review-result", { reviewId: "rev-3", approved: true });
    }, 10);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.equal(outcome.status, "completed");
  assert.equal((outcome as { reviewId: string }).reviewId, "rev-3");
});

test("bridge: a turn abort while awaiting the decision -> aborted outcome", async () => {
  const bus = fakeBus();
  const controller = new AbortController();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({
      status: "handled",
      result: { status: "pending", reviewId: "rev-4" },
    });
    // No decision ever arrives — the turn is interrupted instead.
    setTimeout(() => controller.abort(), 10);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan", controller.signal);
  assert.deepEqual(outcome, { status: "aborted" });
  const result = reviewOutcomeResult(outcome);
  assert.equal((result.details as { status?: string }).status, "aborted");
});

test("bridge: an already-aborted signal short-circuits before emitting", async () => {
  const bus = fakeBus();
  let emitted = false;
  bus.on("plannotator:request", () => {
    emitted = true;
  });
  const controller = new AbortController();
  controller.abort();
  const outcome = await createPlannotatorBridge(bus).review("# A plan", controller.signal);
  assert.deepEqual(outcome, { status: "aborted" });
  assert.equal(emitted, false, "no request emitted after an abort");
});

test("plan_review: missing plan + no draft -> skipped with reason no_plan, bridge not invoked", async () => {
  // Node 2.4: an absent `plan` param is fine (the draft artifact is the preferred source), but
  // with NO draft either there is nothing reviewable — the transcript is never reviewed.
  // Plannotator IS selected and a short handshake window is set: had the bridge been invoked,
  // the outcome would be a loud `unavailable` after the handshake timeout — `skipped`/`no_plan`
  // proves the resolution refused before the bridge.
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
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
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_PLANNOTATOR_HANDSHAKE_MS: "50" },
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

// --- Node 2.4: the execute core (file-first resolution + the approved→save arm, offline) ----
// Fakes per the planSave.test.ts recipe: a recording bridge stands in for plannotator, a fake
// ToolGating records exits, and a fake pi returns the canned cold-door payload — no LLM /
// network / gh / Python.

const PLAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { number: 42, url: "https://gh/o/r/issues/42", existed: false },
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

/** A headful `SessionDataCtx & ReportTarget` over a live branch array (notify is a no-op). */
function headfulCtx(cwd: string, branch: unknown[]): SessionDataCtx & ReportTarget {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: true,
    ui: { notify() {} },
  };
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

test("execute: the artifact wins over a differing param; the ignored param is flagged", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlannotator(cwd);
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

test("execute: no draft -> the plan param is the reviewed fallback", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  const branch: unknown[] = [stateEntry({ run_id: "RID" })];
  const ctx = headfulCtx(cwd, branch);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: "# Param plan" },
  );
  assert.deepEqual(bridge.reviewed, ["# Param plan"], "the param bytes were reviewed");
  assert.match(String(result.content[0]?.text), /DENIED/);
  assert.match(String(result.content[0]?.text), /needs work/);
});

test("execute: no draft + no param NEVER reviews the transcript -> skipped/no_plan", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  const branch: unknown[] = [stateEntry({ run_id: "RID" }), assistantEntry("# Scraped plan")];
  const ctx = headfulCtx(cwd, branch);
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
  assert.equal(bridge.reviewed.length, 0, "the bridge was never invoked");
  assert.match(String(result.content[0]?.text), /plan_draft/);
});

test("execute: approved -> auto-save runs, gate exits, result terminates", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlannotator(cwd);
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
    const details = result.details as { saved?: boolean; gateExited?: boolean };
    assert.equal(details.saved, true);
    assert.equal(details.gateExited, true);
    assert.equal(gating.exits, 1, "the gate was exited once (via the approvalSave seam)");
    assert.match(String(result.content[0]?.text), /Saved plan #42/);
  });
});

test("execute: approved but the save fails -> non-terminating, gate stays on, /plan-save failsafe", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    selectPlannotator(cwd);
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

test("execute: objective-author stage -> skipped/objective-author, bridge not invoked", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  const branch: unknown[] = [
    stateEntry({ run_id: "RID", mode: "read-only", stage: "objective-author" }),
  ];
  const ctx = headfulCtx(cwd, branch);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: PLAN_JSON });
  const result = await executePlanReview(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
    { plan: "# A plan" },
  );
  const details = result.details as { status?: string; reason?: string };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "objective-author");
  assert.equal(bridge.reviewed.length, 0, "the bridge was never invoked");
  assert.match(String(result.content[0]?.text), /objective_save/);
});

// --- Node 2.4: the approvedSaveResult pure mapper arms --------------------------------------

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
      issue: { number: 42, url: "https://gh/o/r/issues/42" },
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
  const details = result.details as Record<string, unknown>;
  assert.equal(details.status, "completed");
  assert.equal(details.approved, true);
  assert.equal(details.reviewId, "rev-f");
  assert.equal(details.feedback, "ship it; watch the edge case");
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal((details.save as { ok?: boolean }).ok, true);
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
