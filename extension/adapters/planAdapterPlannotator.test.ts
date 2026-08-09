// The plannotator plan adapter (augment posture, injection + bridge only):
// injection only when (gate active AND plannotator-plan selected) — two content flavors, one
// customType (the plan bridge context; the objective flavor in an objective-author session) —
// stale-marker strip on deselect (both flavors), and the pure event-bus bridge core — the bounded handshake
// (timeout / unavailable), the human decision (approved / denied + feedback), the turn-abort
// path, and the per-review result-listener lifecycle (disposed via the `bus.on` unsubscribe).
// Fully offline: the fake plannotator is a test listener on an event bus that calls
// `respond(...)` and emits `plannotator:review-result`. The `plan_review` TOOL (dispatch, soft
// skips, the approved→save arm) is tested in planReview.test.ts. See planAdapterPlannotator.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_CONTEXT_TYPE } from "../factories/planMode.ts";
import { reviewOutcomeResult } from "../factories/planReview.ts";
import { loadPerkSession, plantRawSession, scaffoldRepo } from "../testing/harness.ts";
import {
  createPlannotatorBridge,
  extractDirectEdits,
  hasDirectEditsHeading,
  isPlannotatorPlanSelected,
  OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT,
  PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
  type PlannotatorBus,
  requestPlannotatorPlanReview,
} from "./planAdapterPlannotator.ts";

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
    // Thin delta over the co-injected objective-authoring contract: approval auto-saves; the
    // failsafe arms keep the /objective-save mention.
    assert.equal(content.includes("nothing is saved yet"), false, "the interim posture is gone");
    assert.ok(content.includes("Approval auto-saves"), "approval auto-saves as usual");
    assert.ok(content.includes("/objective-save"), "the failsafe arms direct /objective-save");
    assert.equal(
      content.includes("[PLAN ADAPTER: PLANNOTATOR]"),
      false,
      "the plan marker is not injected in an objective-author session",
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
