// The plannotator plan adapter (augment posture, injection + bridge only):
// injection only when (gate active AND plannotator-plan selected) — three content flavors, one
// customType (the plan bridge context; the objective flavor in an objective-authoring session —
// objective-author OR objective-save; the gist flavor in a gist-author session) —
// stale-marker strip on deselect (all flavors), and the pure event-bus bridge core — the bounded handshake
// (timeout / unavailable), the human decision (approved / denied + feedback), the turn-abort
// path, and the per-review result-listener lifecycle (disposed via the `bus.on` unsubscribe).
// Fully offline: the fake plannotator is a test listener on an event bus that calls
// `respond(...)` and emits `plannotator:review-result`. The `plan_review` TOOL (dispatch, soft
// skips, the approved→save arm) is tested in planReview.test.ts. See plannotator.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_CONTEXT_TYPE } from "../../../authoring/plan/prose.ts";
import { loadPerkSession, plantRawSession, scaffoldRepo } from "../../../testing/harness.ts";
import { reviewOutcomeResult } from "../planReview.ts";
import {
  createPlannotatorBridge,
  extractDirectEdits,
  GIST_ADAPTER_PLANNOTATOR_CONTEXT,
  hasDirectEditsHeading,
  OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT,
  PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
  type PlannotatorBus,
  requestPlannotatorPlanReview,
} from "./plannotator.ts";
import { isPlannotatorPlanSelected } from "./selection.ts";

function selectPlannotator(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[providers]\nplan = "plannotator-plan"\n',
    "utf8",
  );
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
      return () => {
        handlers.set(
          channel,
          (handlers.get(channel) ?? []).filter((h) => h !== handler),
        );
      };
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

test("objective-author session: the OBJECTIVE-flavored bridge context is injected", async () => {
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
    const injected = await h.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "exactly one bridge context injected");
    const content = String(bridge[0]?.content);
    assert.equal(content, OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT);
    assert.ok(content.includes("[OBJECTIVE ADAPTER: PLANNOTATOR]"), "the objective marker");
    assert.ok(content.includes("objective_draft"), "directs the objective_draft rewrite loop");
    // Surface delta only (§8.57): the Direct-Edits fold guidance stays; the base contract's
    // save/failsafe endings are never restated here.
    assert.ok(content.includes("Direct Edits"), "carries the Direct-Edits fold guidance");
    assert.equal(
      content.includes("[PLAN ADAPTER: PLANNOTATOR]"),
      false,
      "the plan marker is not injected in an objective-author session",
    );
  } finally {
    h.dispose();
  }
});

test("objective-save session: the OBJECTIVE flavor is injected (not the plan flavor)", async () => {
  // plan_review routes BOTH objective stages to the objective review arm, so the adapter
  // context (the carrier of the objective review-surface delta) must reach objective-save too.
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-save" },
  });
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "exactly one bridge context injected");
    const content = String(bridge[0]?.content);
    assert.equal(content, OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT, "the objective flavor");
    assert.equal(
      content.includes("[PLAN ADAPTER: PLANNOTATOR]"),
      false,
      "the plan flavor is not injected in an objective-save session",
    );
  } finally {
    h.dispose();
  }
});

test("gist-author session: the GIST-flavored bridge context is injected", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "gist-author" },
  });
  selectPlannotator(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "exactly one bridge context injected");
    const content = String(bridge[0]?.content);
    assert.equal(content, GIST_ADAPTER_PLANNOTATOR_CONTEXT);
    assert.ok(content.includes("[GIST ADAPTER: PLANNOTATOR]"), "the gist marker");
    assert.ok(content.includes("gist_draft"), "directs the gist_draft rewrite loop");
    // The field-aware Direct-Edits fold mapping (§8.23's gist arm).
    assert.match(content, /`# <title>` heading hunk → `title`/, "the title mapping");
    assert.match(content, /`Scope:` line\s+hunk → `scope`/, "the scope mapping");
    assert.match(content, /prose hunks → `prose`/, "the prose mapping");
    assert.equal(
      content.includes("[PLAN ADAPTER: PLANNOTATOR]"),
      false,
      "the plan marker is not injected in a gist-author session",
    );
    assert.equal(
      content.includes("[OBJECTIVE ADAPTER: PLANNOTATOR]"),
      false,
      "the objective marker is not injected in a gist-author session",
    );
  } finally {
    h.dispose();
  }
});

test("bridge context dedups against a prior plan-flavor copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "plan" },
      },
    },
    {
      custom: {
        type: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        data: { content: "[PLAN ADAPTER: PLANNOTATOR]\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE),
      false,
      "prior plan-flavor copy on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("per-flavor dedup: a prior PLAN-flavor copy does not suppress the OBJECTIVE flavor", async () => {
  const cwd = scaffoldRepo();
  selectPlannotator(cwd);
  // The dedup key is the flavor's MARKER, not the shared customType: a stage change must still
  // deliver the missing flavor while a prior copy of the other flavor sits on the branch.
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "objective-author" },
      },
    },
    {
      custom: {
        type: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        data: { content: "[PLAN ADAPTER: PLANNOTATOR]\nprior plan-flavor copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "the objective flavor still injects");
    assert.equal(String(bridge[0]?.content), OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT);
  } finally {
    h.dispose();
  }
});

test("active-window dedup: the GIST and PLAN flavors re-inject post-compaction; OBJECTIVE does not", async () => {
  // The gist AND plan flavors dedup on the compaction-active window (contracts §8.31), so a
  // compaction that drops the live copy re-delivers each; the objective flavor keeps the
  // whole-branch scan (one copy per session) until the objective flows migrate.
  const plant = (cwd: string, stage: string, marker: string, fileName: string) =>
    plantRawSession(
      cwd,
      [
        {
          custom: {
            type: "perk:workflow-state",
            data: { run_id: "01RID", mode: "read-only", stage },
          },
        },
        {
          custom: {
            type: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
            data: { content: `${marker}\nprior copy` },
          },
        },
        { assistant: "recent work that survives compaction" },
      ],
      { fileName },
    );

  const gistCwd = scaffoldRepo();
  selectPlannotator(gistCwd);
  const gistFile = plant(gistCwd, "gist-author", "[GIST ADAPTER: PLANNOTATOR]", "gist.jsonl");
  const gistSessions = SessionManager.open(gistFile);
  const gistKept = gistSessions.getEntries().at(-1)?.id;
  assert.ok(gistKept !== undefined);
  gistSessions.appendCompaction("summary without a live bridge copy", gistKept, 100);
  const gistH = await loadPerkSession({
    cwd: gistCwd,
    sessionManager: gistSessions,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await gistH.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "the gist flavor re-injects after compaction dropped it");
    assert.equal(String(bridge[0]?.content), GIST_ADAPTER_PLANNOTATOR_CONTEXT);
  } finally {
    gistH.dispose();
  }

  const planCwd = scaffoldRepo();
  selectPlannotator(planCwd);
  const planFile = plant(planCwd, "plan", "[PLAN ADAPTER: PLANNOTATOR]", "plan.jsonl");
  const planSessions = SessionManager.open(planFile);
  const planKept = planSessions.getEntries().at(-1)?.id;
  assert.ok(planKept !== undefined);
  planSessions.appendCompaction("summary without a live bridge copy", planKept, 100);
  const planH = await loadPerkSession({
    cwd: planCwd,
    sessionManager: planSessions,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await planH.emitBeforeAgentStart();
    const bridge = injected.filter((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
    assert.equal(bridge.length, 1, "the plan flavor re-injects after compaction dropped it");
    assert.match(String(bridge[0]?.content), /\[PLAN ADAPTER: PLANNOTATOR\]/);
  } finally {
    planH.dispose();
  }

  const objCwd = scaffoldRepo();
  selectPlannotator(objCwd);
  const objFile = plant(
    objCwd,
    "objective-author",
    "[OBJECTIVE ADAPTER: PLANNOTATOR]",
    "obj.jsonl",
  );
  const objSessions = SessionManager.open(objFile);
  const objKept = objSessions.getEntries().at(-1)?.id;
  assert.ok(objKept !== undefined);
  objSessions.appendCompaction("summary without a live bridge copy", objKept, 100);
  const objH = await loadPerkSession({
    cwd: objCwd,
    sessionManager: objSessions,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await objH.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE),
      false,
      "the objective flavor keeps whole-branch dedup — no post-compaction re-injection",
    );
  } finally {
    objH.dispose();
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
      { role: "user", content: "[OBJECTIVE ADAPTER: PLANNOTATOR] leaked into a user turn" },
      { role: "user", content: "[GIST ADAPTER: PLANNOTATOR] leaked into a user turn" },
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
      "stale plan bridge marker stripped from user turns on the default path",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[OBJECTIVE ADAPTER: PLANNOTATOR]")),
      false,
      "stale objective bridge marker stripped from user turns on the default path",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[GIST ADAPTER: PLANNOTATOR]")),
      false,
      "stale gist bridge marker stripped from user turns on the default path",
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

// ------------------------------------- adversarial payload narrowing + emit containment

test("bridge: a malformed handshake payload degrades to the invalid-response arm (no throw)", async () => {
  for (const payload of [null, "handled", 42, ["handled"]]) {
    const bus = fakeBus();
    bus.on("plannotator:request", (data) => {
      (data as RequestEnvelope).respond(payload);
    });
    const outcome = await createPlannotatorBridge(bus).review("# A plan");
    assert.equal(outcome.status, "unavailable");
    assert.match((outcome as { warning: string }).warning, /an invalid response/);
  }
});

test("bridge: an adversarial handshake getter is contained (fail-open, never a throw)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const trap = Object.defineProperty({}, "status", {
      get() {
        throw new Error("adversarial getter");
      },
      enumerable: true,
    });
    (data as RequestEnvelope).respond(trap);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.equal(outcome.status, "unavailable");
  assert.match((outcome as { warning: string }).warning, /an invalid response/);
});

test("bridge: malformed decision payloads are ignored; a later well-formed decision resolves", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({
      status: "handled",
      result: { status: "pending", reviewId: "rev-m" },
    });
    setTimeout(() => {
      bus.emit("plannotator:review-result", null);
      bus.emit("plannotator:review-result", "approved");
      bus.emit("plannotator:review-result", { approved: true }); // no reviewId
      bus.emit(
        "plannotator:review-result",
        Object.defineProperty({}, "reviewId", {
          get() {
            throw new Error("adversarial getter");
          },
          enumerable: true,
        }),
      );
      bus.emit("plannotator:review-result", { reviewId: "rev-m", approved: true });
    }, 10);
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.deepEqual(outcome, { status: "completed", approved: true, reviewId: "rev-m" });
});

test("bridge: a malformed approved field never completes the review — the wait stays pending", async () => {
  // The narrowing contract: a decision is a human verdict, so a matching reviewId with a
  // missing / non-boolean / adversarial-getter `approved` is a MALFORMED payload — ignored
  // (never coerced into a premature DENY); a later well-formed decision still completes.
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({
      status: "handled",
      result: { status: "pending", reviewId: "rev-n" },
    });
  });
  const bridge = createPlannotatorBridge(bus);
  const pending = bridge.review("# A plan");
  let settled = false;
  void pending.then(() => {
    settled = true;
  });
  await new Promise((resolve) => setTimeout(resolve, 5));
  bus.emit("plannotator:review-result", { reviewId: "rev-n" }); // approved missing
  bus.emit("plannotator:review-result", { reviewId: "rev-n", approved: "yes" }); // non-boolean
  bus.emit("plannotator:review-result", { reviewId: "rev-n", approved: 1 }); // non-boolean
  bus.emit(
    "plannotator:review-result",
    Object.defineProperty({ reviewId: "rev-n" }, "approved", {
      get() {
        throw new Error("adversarial approved getter");
      },
      enumerable: true,
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(settled, false, "malformed decisions are ignored — the review stays pending");
  assert.equal(
    (bus.handlers.get("plannotator:review-result") ?? []).length,
    1,
    "the per-review listener is still live after the malformed payloads",
  );
  bus.emit("plannotator:review-result", { reviewId: "rev-n", approved: true, feedback: "   " });
  const outcome = await pending;
  // Blank feedback is still dropped on the well-formed decision.
  assert.deepEqual(outcome, { status: "completed", approved: true, reviewId: "rev-n" });
});

test("bridge: a synchronous emit throw is contained as unavailable (timer actually cancelled)", async (t) => {
  // Deterministic timer observation: record every setTimeout handle the bridge allocates and
  // every clearTimeout it issues — deleting the emit-throw arm's `clearTimeout` fails HERE
  // (an elapsed-time bound cannot see a still-scheduled 5s timer).
  const setSpy = t.mock.method(globalThis, "setTimeout");
  const clearSpy = t.mock.method(globalThis, "clearTimeout");
  const bus = fakeBus();
  bus.on("plannotator:request", () => {
    throw new Error("foreign handler exploded");
  });
  const outcome = await createPlannotatorBridge(bus).review("# A plan");
  assert.equal(outcome.status, "unavailable");
  assert.match((outcome as { warning: string }).warning, /foreign handler exploded/);
  const allocated = setSpy.mock.calls.map((c) => c.result);
  assert.equal(allocated.length, 1, "the bridge allocated exactly the handshake timer");
  const clearedHandles = clearSpy.mock.calls.map((c) => c.arguments[0]);
  assert.ok(
    clearedHandles.includes(allocated[0]),
    "the handshake timer was cancelled on the emit-throw arm",
  );
});

test("bridge: a turn abort DURING the handshake wait settles aborted promptly (timer cancelled)", async (t) => {
  // The pending handshake is connected to cancellation: plannotator never invokes `respond`,
  // the turn aborts, and the bridge settles `aborted` immediately — never parked on the
  // handshake timeout — with the timer deterministically cancelled and the abort listener
  // removed (observed via the signal's listener effect: a second abort is inert).
  const setSpy = t.mock.method(globalThis, "setTimeout");
  const clearSpy = t.mock.method(globalThis, "clearTimeout");
  const bus = fakeBus();
  let sawRequest = false;
  bus.on("plannotator:request", () => {
    sawRequest = true; // never responds — the handshake stays pending
  });
  const controller = new AbortController();
  const pending = createPlannotatorBridge(bus).review("# A plan", controller.signal);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(sawRequest, true, "the request was emitted before the abort");
  controller.abort();
  const outcome = await pending;
  assert.deepEqual(outcome, { status: "aborted" });
  const bridgeTimer = setSpy.mock.calls
    .map((c) => c.result)
    .find((handle) => !clearSpy.mock.calls.some((c) => c.arguments[0] === handle));
  assert.equal(bridgeTimer, undefined, "every allocated timer was cancelled on the abort path");
  assert.equal(
    (bus.handlers.get("plannotator:review-result") ?? []).length,
    0,
    "no decision listener was ever registered on the aborted-handshake path",
  );
});

// ------------------------------------------- the per-review result-listener lifecycle

test("requestPlannotatorPlanReview: the decision disposes the result listener (unsubscribe)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const req = data as RequestEnvelope;
    req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-5" } });
    setTimeout(() => {
      assert.equal(
        (bus.handlers.get("plannotator:review-result") ?? []).length,
        1,
        "the per-review listener is live while the decision is pending",
      );
      bus.emit("plannotator:review-result", { reviewId: "rev-5", approved: true });
    }, 10);
  });
  const outcome = await requestPlannotatorPlanReview(bus, "# A plan");
  assert.equal(outcome.status, "completed");
  assert.equal(
    (bus.handlers.get("plannotator:review-result") ?? []).length,
    0,
    "the result listener is disposed once the decision arrives",
  );
});

test("requestPlannotatorPlanReview: a turn abort disposes the result listener likewise", async () => {
  const bus = fakeBus();
  const controller = new AbortController();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({
      status: "handled",
      result: { status: "pending", reviewId: "rev-6" },
    });
    // No decision ever arrives — the turn is interrupted instead.
    setTimeout(() => controller.abort(), 10);
  });
  const outcome = await requestPlannotatorPlanReview(bus, "# A plan", controller.signal);
  assert.deepEqual(outcome, { status: "aborted" });
  assert.equal(
    (bus.handlers.get("plannotator:review-result") ?? []).length,
    0,
    "the result listener is disposed on the abort",
  );
});

test("requestPlannotatorPlanReview: an abort during the pending handshake registers no listener", async () => {
  const bus = fakeBus();
  const controller = new AbortController();
  bus.on("plannotator:request", (data) => {
    const req = data as RequestEnvelope;
    // Abort FIRST, while the handshake is still pending; the handshake then succeeds late.
    // Without the post-handshake abort re-check this would install a decision listener on an
    // already-aborted signal (whose abort event never re-fires) and wedge the promise forever.
    setTimeout(() => {
      controller.abort();
      req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-7" } });
    }, 10);
  });
  const outcome = await requestPlannotatorPlanReview(bus, "# A plan", controller.signal);
  assert.deepEqual(outcome, { status: "aborted" });
  assert.equal(
    bus.handlers.get("plannotator:review-result"),
    undefined,
    "no result listener was ever registered after the mid-handshake abort",
  );
});

test("requestPlannotatorPlanReview: a failed handshake never registers a result listener", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as RequestEnvelope).respond({ status: "unavailable", error: "no browser" });
  });
  const outcome = await requestPlannotatorPlanReview(bus, "# A plan");
  assert.equal(outcome.status, "unavailable");
  assert.equal(
    bus.handlers.get("plannotator:review-result"),
    undefined,
    "no result listener was ever registered",
  );
});

// -------------------------------------------------- the Direct Edits feedback extraction

// Mirrors `buildDirectEditsSection` (plannotator packages/editor/directEdits.ts @ v0.26.1):
// heading + blank + preamble + blank + a ```diff fence of the trimEnd()'d patch.
const PREAMBLE_DIRECT =
  "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:";
const PREAMBLE_CONVERTED =
  "The user edited a markdown conversion of the original source. This diff describes the desired content changes (it is not a literal patch to a file on disk):";
const PATCH = [
  "===================================================================",
  "--- plan.md (original)",
  "+++ plan.md (edited)",
  "@@ -1,3 +1,3 @@",
  " # Plan",
  "-old step",
  "+new step",
  " done",
].join("\n");

function directEditsSection(preamble: string): string {
  return ["# Direct Edits", "", preamble, "", "```diff", PATCH, "```"].join("\n");
}

test("extractDirectEdits: a full section recovers the fence body (both preamble variants)", () => {
  for (const preamble of [PREAMBLE_DIRECT, PREAMBLE_CONVERTED]) {
    const section = directEditsSection(preamble);
    assert.equal(hasDirectEditsHeading(section), true);
    const extracted = extractDirectEdits(section);
    assert.ok(extracted !== null, "the section extracts");
    assert.equal(extracted.diff, PATCH, "the fence body is the diff, byte-exact");
    assert.equal(extracted.remainder, undefined, "edits-only feedback has no remainder");
  }
});

test("extractDirectEdits: edits + --- + annotations recovers the remainder", () => {
  // Mirrors composeFeedbackWithDirectEdits: section FIRST, then \n\n---\n\n + annotation text.
  const annotations = "Also tighten step 3.\n\nAnd rename the helper.";
  const feedback = `${directEditsSection(PREAMBLE_DIRECT)}\n\n---\n\n${annotations}`;
  const extracted = extractDirectEdits(feedback);
  assert.ok(extracted !== null);
  assert.equal(extracted.diff, PATCH);
  assert.equal(extracted.remainder, annotations, "one leading separator stripped, rest verbatim");
});

test("extractDirectEdits: plain feedback -> null; heading not detected", () => {
  const plain = "Looks good overall, but step 2 needs a rollback story.";
  assert.equal(extractDirectEdits(plain), null);
  assert.equal(hasDirectEditsHeading(plain), false);
  // A Direct Edits heading NOT at the start is quoted prose, never a section.
  const quoted = `Someone pasted:\n\n# Direct Edits\n\nnot a real section`;
  assert.equal(extractDirectEdits(quoted), null);
  assert.equal(hasDirectEditsHeading(quoted), false);
});

test("extractDirectEdits: heading without a parseable fence -> null, heading still detected", () => {
  for (const broken of [
    "# Direct Edits\n\nno fence at all",
    "# Direct Edits\n\n```diff\nunclosed fence body",
    "# Direct Edits\n\n```diff\n```", // empty fence body
    "# Direct Edits",
  ]) {
    assert.equal(extractDirectEdits(broken), null, `null for: ${JSON.stringify(broken)}`);
    assert.equal(hasDirectEditsHeading(broken), true, "the heading is still detected");
  }
});
