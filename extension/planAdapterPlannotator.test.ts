// The plannotator plan adapter (augment posture, injection + bridge only as of Node 2.5):
// injection only when (gate active AND plannotator-plan selected AND not objective-author),
// stale-marker strip on deselect, and the pure event-bus bridge core — the bounded handshake
// (timeout / unavailable), the human decision (approved / denied + feedback), and the turn-abort
// path. Fully offline: the fake plannotator is a test listener on an event bus that calls
// `respond(...)` and emits `plannotator:review-result`. The `plan_review` TOOL (dispatch, soft
// skips, the approved→save arm) is tested in planReview.test.ts. See planAdapterPlannotator.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  createPlannotatorBridge,
  isPlannotatorPlanSelected,
  PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
  type PlannotatorBus,
} from "./planAdapterPlannotator.ts";
import { PLAN_CONTEXT_TYPE } from "./planMode.ts";
import { reviewOutcomeResult } from "./planReview.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

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
