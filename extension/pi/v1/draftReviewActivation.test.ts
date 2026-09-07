import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createDraftReviewWaveState } from "../../authoring/review/draftContext.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { DRAFT_REVIEW_ARTIFACT, readDraftReview } from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import { acquireDraftReviewLock } from "../../substrate/draftReviewLock.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { gitInit, scaffoldRepo } from "../../testing/harness.ts";
import { createDraftReviewActivation } from "./draftReviewActivation.ts";
import { planSaveDepsFor } from "./plan.ts";
import { runPlanReviewV1 } from "./planReview.ts";
import { openPlanReviewSurface } from "./planReviewBrowser.ts";
import { createAnnotationState } from "./providers/annotations.ts";
import { createPlannotatorBridge, type PlannotatorBus } from "./providers/plannotator.ts";

type Request = {
  requestId: string;
  action: string;
  payload: unknown;
  respond(value: unknown): void;
};
function fixture() {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const branch: BranchEntry[] = [
    {
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { run_id: "RID", stage: "plan", mode: "read-only" },
    },
  ];
  const requests: Request[] = [];
  const listeners = new Set<(value: unknown) => void>();
  const shutdown: (() => void)[] = [];
  const messages: string[] = [];
  const notices: string[] = [];
  const bus: PlannotatorBus = {
    emit(_channel, raw) {
      const request = raw as Request;
      requests.push(request);
      request.respond({
        status: "handled",
        result:
          request.action === "plan-review"
            ? { status: "pending", reviewId: request.requestId }
            : { status: "pending" },
      });
    },
    on(_channel, listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
  const pi = {
    events: bus,
    on(name: string, handler: () => void) {
      assert.equal(name, "session_shutdown");
      shutdown.push(handler);
    },
    appendEntry(customType: string, data: Record<string, unknown>) {
      branch.push({ type: "custom", customType, data });
    },
    sendUserMessage(message: string) {
      messages.push(message);
    },
    exec() {
      assert.fail("no backend effect in transport tests");
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    signal: undefined,
    isIdle: () => true,
    sessionManager: { getBranch: () => branch, getSessionId: () => "session" },
    ui: {
      notify(message: string) {
        notices.push(message);
      },
    },
  } as unknown as ExtensionContext;
  const gating = {
    isActive: () => true,
    exit: () => assert.fail("gate stays active"),
  } as unknown as ToolGating;
  const reviews = createDraftReviewActivation(pi);
  const bridge = { ...createPlannotatorBridge(bus), ...reviews };
  const session = openBranchWorkflowSession(pi, ctx);
  assert.equal(session.writeArtifact("plan-draft.md", "# Draft\n").status, "applied");
  const waves = createDraftReviewWaveState();
  const annotations = createAnnotationState();
  const browser = () =>
    openPlanReviewSurface(pi, ctx, gating, { draft: "# Draft\n" }, waves, annotations, reviews, {
      pickFreePort: async () => 45678,
      probe: async () => true,
    });
  const tool = () => runPlanReviewV1(ctx, bridge, planSaveDepsFor(pi, ctx, gating), undefined);
  const record = () => {
    const result = readDraftReview(session);
    assert.ok(result.ok && result.record);
    return result.record;
  };
  const flush = async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  };
  return {
    cwd,
    pi,
    ctx,
    session,
    reviews,
    bridge,
    browser,
    tool,
    waves,
    annotations,
    requests,
    listeners,
    messages,
    notices,
    record,
    flush,
    close() {
      for (const stop of shutdown) stop();
    },
    dispose() {
      for (const stop of shutdown) stop();
      rmSync(cwd, { recursive: true, force: true });
    },
  };
}

test("production tool → browser: verified opening replaces record and detaches predecessor only after claim release", async () => {
  const f = fixture();
  try {
    assert.equal(f.requests.length, 0, "construction makes no query or request");
    const tool = f.tool();
    await f.flush();
    assert.equal(f.record().consumption.state, "pending");
    const old = f.record().request_id;
    assert.equal(f.listeners.size, 1);
    const lock = acquireDraftReviewLock(f.cwd, {
      sessionId: "competitor",
      runId: "RID",
      requestId: "11111111-1111-4111-8111-111111111111",
    });
    assert.equal(lock.kind, "acquired");
    if (lock.kind !== "acquired") assert.fail("claim is released during human wait");
    const refused = await f.browser();
    assert.ok(refused !== null && typeof refused !== "string");
    assert.equal(refused.code, "busy");
    assert.equal(f.record().request_id, old);
    assert.equal(f.listeners.size, 1, "refused new registration preserves old wait");
    assert.equal(f.waves.context, null);
    assert.equal(f.annotations.surface, null);
    lock.claim.finish("release");
    const launched = await f.browser();
    assert.equal(typeof launched, "string");
    assert.equal((await tool).details.status, "aborted");
    assert.notEqual(f.record().request_id, old);
    assert.equal(f.record().consumption.state, "pending");
    assert.equal(f.listeners.size, 1);
    assert.ok(f.waves.context);
    assert.ok(f.annotations.surface);
    assert.equal(f.requests.filter((request) => request.action === "plan-review").length, 2);
    f.close();
    await f.flush();
    assert.equal(f.listeners.size, 0);
    assert.equal(
      f.record().consumption.state,
      "pending",
      "shutdown does not cancel upstream or erase known correlation",
    );
    assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), DRAFT_REVIEW_ARTIFACT)));
  } finally {
    f.dispose();
  }
});

test("production browser → tool: predecessor teardown does not clear another entry's companion resources", async () => {
  const f = fixture();
  try {
    assert.equal(typeof (await f.browser()), "string");
    await f.flush();
    const prior = f.record().request_id;
    const annotation = f.annotations.surface;
    const wave = f.waves.context;
    const tool = f.tool();
    await f.flush();
    assert.notEqual(f.record().request_id, prior);
    assert.equal(f.listeners.size, 1);
    assert.equal(f.annotations.surface, annotation, "detachment owns only the old transport");
    assert.equal(f.waves.context, wave);
    f.close();
    assert.equal((await tool).details.status, "aborted");
    assert.equal(f.messages.length, 0, "no predecessor feedback replay");
  } finally {
    f.dispose();
  }
});

test("production preparation refuses broken provenance without opening browser or returning null port fallback", async () => {
  const f = fixture();
  try {
    writeFileSync(
      join(sessionDataDir(f.cwd, "RID"), "plan-draft.md"),
      "changed without provenance",
    );
    const opened = await f.browser();
    assert.ok(opened !== null && typeof opened !== "string");
    assert.equal(opened.code, "invalid-state");
    assert.equal(f.requests.length, 0);
    assert.equal(f.waves.context, null);
    assert.equal(f.annotations.surface, null);
  } finally {
    f.dispose();
  }
});
