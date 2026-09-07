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
import {
  createDraftReviewActivation,
  draftReviewRefusalResult,
  type PreparedDraftReview,
} from "./draftReviewActivation.ts";
import { planSaveDepsFor } from "./plan.ts";
import { runPlanReviewV1 } from "./planReview.ts";
import { openPlanReviewSurface } from "./planReviewBrowser.ts";
import { createAnnotationState } from "./providers/annotations.ts";
import { createPlannotatorBridge, type PlannotatorBus } from "./providers/plannotator.ts";
import type { ReviewOutcome, ToolResult } from "./review.ts";

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
  const events = new Map<string, (event: unknown, ctx: ExtensionContext) => void>();
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
    on(name: string, handler: (event: unknown, ctx: ExtensionContext) => void) {
      assert.ok(name === "session_shutdown" || name === "turn_end");
      events.set(name, handler);
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
    branch,
    events,
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
      events.get("session_shutdown")?.({}, ctx);
    },
    dispose() {
      events.get("session_shutdown")?.({}, ctx);
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

async function attached(f: ReturnType<typeof fixture>, signal?: AbortSignal, approved = false) {
  const prepared = f.reviews.prepare(f.ctx, undefined, signal);
  assert.ok(prepared.ok);
  const review = prepared.value;
  const wait = f.bridge.review(review.snapshot.markdown, review.registration, review.signal);
  await f.flush();
  const reviewId = f.record().correlation.review_id;
  assert.ok(reviewId);
  for (const listener of f.listeners)
    listener({ reviewId, approved, feedback: "  Feedback\nverbatim  " });
  const outcome = await wait;
  assert.equal(outcome.status, "completed");
  if (outcome.status !== "completed") assert.fail("expected transport completion");
  return { review, outcome };
}
const revision: ToolResult = {
  content: [{ type: "text", text: "Revise the reviewed draft." }],
  details: { ok: true, status: "revision" },
};
function toolCompletion(
  review: PreparedDraftReview,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
) {
  return review.complete(outcome, {
    effect: "revision",
    carrier: { kind: "tool", tool_call_id: "actual-call" },
    execute: async () => revision,
  });
}
function persistTool(
  f: ReturnType<typeof fixture>,
  result: ToolResult,
  overrides: Record<string, unknown> = {},
) {
  const entry = {
    type: "message",
    id: "tool-entry",
    message: {
      role: "toolResult",
      toolName: "plan_review",
      toolCallId: "actual-call",
      ...result,
      ...overrides,
    },
  };
  f.branch.push(entry);
}

test("activation completion binds verified request/review IDs and observes only persisted exact tool entries at turn_end", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f);
    const wrong = await toolCompletion(review, { ...outcome, reviewId: "arbitrary" });
    assert.ok(!wrong.ok && wrong.reason === "superseded");
    assert.equal(f.record().consumption.state, "pending");
    const result = await toolCompletion(review, outcome);
    assert.ok(result.ok && "content" in result.value);
    assert.equal(f.record().consumption.state, "dispatch");
    assert.equal(f.events.has("message_end"), false);
    f.events.get("turn_end")?.({}, f.ctx);
    assert.equal(f.record().consumption.state, "dispatch", "return is not evidence");
    for (const override of [
      { role: "assistant" },
      { toolCallId: "other" },
      { toolName: "other" },
      { content: [{ type: "text", text: "altered" }] },
      { details: {} },
    ])
      persistTool(f, result.value, override);
    f.events.get("turn_end")?.({}, f.ctx);
    assert.equal(f.record().consumption.state, "dispatch");
    persistTool(f, result.value);
    f.events.get("turn_end")?.({}, f.ctx);
    assert.equal(f.record().consumption.state, "consumed");
    assert.deepEqual(await toolCompletion(review, outcome), {
      ok: true,
      value: { status: "consumed" },
      saveReceipt: null,
      gateExited: false,
      completedResult: null,
    });
  } finally {
    f.dispose();
  }
});

test("persisted revision is consumed before synchronous draft mutation, without checking original source/target again", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f);
    const result = await toolCompletion(review, outcome);
    assert.ok(result.ok && "content" in result.value);
    persistTool(f, result.value);
    writeFileSync(join(f.cwd, ".perk", "config.toml"), "# changed after dispatch\n");
    let called = false;
    const changed = f.reviews.mutate(
      f.ctx,
      "source-changed",
      (session) => {
        called = true;
        assert.equal(f.record().consumption.state, "consumed");
        return session.writeArtifact("plan-draft.md", "# New draft\n");
      },
      { draft: { subject: "plan", content: "# New draft\n" } },
    );
    assert.ok(changed.ok && called);
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

for (const evidence of [false, true]) {
  for (const end of ["abort", "shutdown"] as const) {
    test(`${end} checks persisted evidence first (present=${evidence}) and never sends twice`, async () => {
      const f = fixture();
      try {
        const abort = new AbortController();
        const { review, outcome } = await attached(f, abort.signal);
        const result = await review.complete(outcome, {
          effect: "revision",
          carrier: { kind: "user" },
          execute: async () => revision,
        });
        assert.ok(result.ok && "content" in result.value);
        assert.equal(f.messages.length, 1);
        assert.equal(f.record().consumption.state, "dispatch");
        if (evidence) {
          const entry = {
            type: "message",
            id: "user-entry",
            message: { role: "user", content: result.value.content },
          };
          f.branch.push(entry);
        }
        if (end === "abort") abort.abort();
        else f.close();
        const record = f.record();
        assert.equal(record.consumption.state, evidence ? "consumed" : "uncertain");
        if (record.consumption.state === "uncertain")
          assert.equal(record.consumption.reason, "delivery-unconfirmed");
        assert.equal(f.messages.length, 1);
        if (!evidence && end === "abort") {
          const next = f.reviews.prepare(f.ctx);
          assert.ok(next.ok);
          const refused = await f.bridge.review(
            next.value.snapshot.markdown,
            next.value.registration,
            next.value.signal,
          );
          assert.ok(refused.status === "refused" && refused.code === "unresolved-dispatch");
        }
      } finally {
        f.dispose();
      }
    });
  }
}

test("user send throw preserves typed receipt and definitive gate/result facts; no replay or retry guidance", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f, undefined, true);
    let saves = 0;
    f.pi.sendUserMessage = () => {
      throw new Error("queue failed");
    };
    const saved: ToolResult = {
      content: [{ type: "text", text: "Saved #42" }],
      details: { ok: true, status: "saved" },
      terminate: true,
    };
    const result = await review.complete(outcome, {
      effect: "save",
      carrier: { kind: "user" },
      execute: async (cap) => {
        await cap.save(
          async () => {
            saves++;
            return { value: 42, receipt: { id: "42", url: "https://example.test/42" } };
          },
          () => ({ gateExited: true }),
        );
        return saved;
      },
    });
    assert.ok(!result.ok && result.reason === "unresolved-dispatch");
    assert.equal(saves, 1);
    assert.deepEqual(result.saveReceipt, { id: "42", url: "https://example.test/42" });
    assert.equal(result.gateExited, true);
    assert.equal(result.completedResult, saved);
    const record = f.record();
    assert.ok(record.consumption.state === "uncertain");
    assert.equal(record.consumption.reason, "delivery-unconfirmed");
    assert.equal(record.consumption.attempt.save.state, "confirmed");
    const refused = draftReviewRefusalResult(
      { status: "refused", code: result.reason, phase: "open", detail: result.detail },
      result,
    );
    assert.match(refused.content[0]?.text ?? "", /Confirmed save: 42.*gate/);
    assert.match(refused.content[0]?.text ?? "", /Do not retry a save/);
    assert.equal(refused.details.gate_exited, true);
    assert.equal((await toolCompletion(review, outcome)).ok, false);
    assert.equal(saves, 1);
  } finally {
    f.dispose();
  }
});

test("registration and post-intent receipt writes fail closed with retained claim and no speculative repair", async () => {
  for (const phase of ["open", "receipt"] as const) {
    const f = fixture();
    try {
      const opened = phase === "receipt" ? await attached(f, undefined, true) : null;
      let appends = 0;
      const append = f.pi.appendEntry;
      f.pi.appendEntry = (type, data) => {
        appends++;
        if (phase === "open" || appends === 3) return;
        append(type, data);
      };
      if (opened === null) {
        const prepared = f.reviews.prepare(f.ctx);
        assert.ok(prepared.ok);
        const outcome = await f.bridge.review(
          prepared.value.snapshot.markdown,
          prepared.value.registration,
          prepared.value.signal,
        );
        assert.ok(outcome.status === "refused" && outcome.code === "persistence-failed");
        assert.equal(f.requests.length, 0);
        assert.equal(appends, 1);
      } else {
        let effects = 0;
        const result = await opened.review.complete(opened.outcome, {
          effect: "save",
          carrier: { kind: "tool", tool_call_id: "actual-call" },
          execute: async (cap) => {
            await cap.save(
              async () => ({ value: 1, receipt: { id: "1", url: "https://example.test/1" } }),
              () => ({ gateExited: true }),
            );
            effects++;
            return revision;
          },
        });
        assert.ok(!result.ok && result.reason === "persistence-failed");
        assert.equal(result.saveReceipt?.id, "1");
        assert.equal(result.gateExited, true);
        assert.equal(appends, 3, "no uncertain repair after rejected receipt pointer");
        assert.equal(effects, 0);
      }
      assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
    } finally {
      f.dispose();
    }
  }
});

test("runtime async mutation owns exclusion only through bounded effects; editor wait starts after release", async () => {
  const f = fixture();
  try {
    const { review } = await attached(f);
    let resolve: () => void = () => assert.fail("not started");
    const wait = new Promise<void>((done) => {
      resolve = done;
    });
    let entered: () => void = () => assert.fail("not started");
    const started = new Promise<void>((done) => {
      entered = done;
    });
    const work = f.reviews.mutateAsync(f.ctx, "manual-save", async () => {
      assert.equal(f.record().consumption.state, "invalidated");
      entered();
      await wait;
      return 1;
    });
    await started;
    assert.deepEqual(
      f.reviews.mutate(f.ctx, "first-party-review", () => assert.fail("busy callback")).ok,
      false,
    );
    resolve();
    assert.deepEqual(await work, { ok: true, value: 1 });
    const invalidated = f.reviews.mutate(
      f.ctx,
      "first-party-review",
      () => "open editor after return",
    );
    assert.ok(invalidated.ok);
    const competitor = acquireDraftReviewLock(f.cwd, {
      sessionId: "editor-wait",
      runId: "RID",
      requestId: "11111111-1111-4111-8111-111111111111",
    });
    assert.equal(competitor.kind, "acquired");
    if (competitor.kind === "acquired") competitor.claim.finish("release");
    review.dispose();
  } finally {
    f.dispose();
  }
});

test("queued user delivery never holds exclusion while waiting for persistence", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f);
    const queued: unknown[] = [];
    f.pi.sendUserMessage = (content, options) => {
      queued.push({ content, options });
    };
    const ctx = { ...f.ctx, isIdle: () => false };
    // Refresh only the same identity's live context, without changing the prepared correlation.
    assert.ok(f.reviews.prepare(ctx).ok);
    const result = await review.complete(outcome, {
      effect: "revision",
      carrier: { kind: "user" },
      execute: async () => revision,
    });
    assert.ok(result.ok && "content" in result.value);
    assert.deepEqual(queued, [
      { content: result.value.content, options: { deliverAs: "followUp" } },
    ]);
    const competitor = acquireDraftReviewLock(f.cwd, {
      sessionId: "queued",
      runId: "RID",
      requestId: "11111111-1111-4111-8111-111111111111",
    });
    assert.equal(competitor.kind, "acquired");
    if (competitor.kind === "acquired") competitor.claim.finish("release");
    assert.equal(f.record().consumption.state, "dispatch", "queued delivery is not acknowledged");
    const mutation = f.reviews.mutate(f.ctx, "manual-save", () =>
      assert.fail("undelivered intent blocks"),
    );
    assert.ok(!mutation.ok && mutation.reason === "unresolved-dispatch");
  } finally {
    f.dispose();
  }
});

for (const approved of [false, true]) {
  test(`attached parameter plus identical new artifact permits only stale DATA once (approved=${approved})`, async () => {
    const f = fixture();
    try {
      // A fresh run has genuinely absent parameter-source provenance, not a deleted pointer.
      f.branch.push({ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "PARAM" } });
      const prepared = f.reviews.prepare(f.ctx, "# Parameter\n");
      assert.ok(prepared.ok);
      const review = prepared.value;
      const wait = f.bridge.review(review.snapshot.markdown, review.registration, review.signal);
      await f.flush();
      assert.equal(f.session.writeArtifact("plan-draft.md", "# Parameter\n").status, "applied");
      const reviewId = f.record().correlation.review_id;
      assert.ok(reviewId);
      const feedback = "  # Direct Edits\n```diff\n-old\n+new\n```  ";
      for (const listener of f.listeners) listener({ reviewId, approved, feedback });
      const outcome = await wait;
      assert.ok(outcome.status === "completed");
      // Returned snapshot mutation must not alter the captured diagnostic digest/subject.
      const digest = review.snapshot.sourceDigest;
      review.snapshot.sourceDigest = "forged";
      review.snapshot.binding.subject = "gist";
      const result = await review.complete(outcome, {
        effect: approved ? "save" : "revision",
        carrier: { kind: "tool", tool_call_id: "actual-call" },
        execute: async () => assert.fail("stale cannot patch/save/revise"),
      });
      assert.ok(result.ok && "content" in result.value);
      assert.equal(result.value.details.status, "stale-reference");
      assert.equal(result.value.details.reviewed_digest, digest);
      assert.equal(result.value.details.subject, "plan");
      assert.ok(result.value.content[0]?.text.includes(feedback));
      const second = await toolCompletion(review, outcome);
      assert.ok(!second.ok && second.reason === "unresolved-dispatch");
      persistTool(f, result.value);
      f.events.get("turn_end")?.({}, f.ctx);
      const duplicate = await toolCompletion(review, outcome);
      assert.ok(
        duplicate.ok && "status" in duplicate.value && duplicate.value.status === "consumed",
      );
    } finally {
      f.dispose();
    }
  });
}

test("shutdown during backend wait uses the existing claim to retain uncertainty; late receipt has no new effects", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f, undefined, true);
    let release: () => void = () => assert.fail("not waiting");
    const wait = new Promise<void>((done) => {
      release = done;
    });
    let entered: () => void = () => assert.fail("not entered");
    const started = new Promise<void>((done) => {
      entered = done;
    });
    let gates = 0;
    const completed = review.complete(outcome, {
      effect: "save",
      carrier: { kind: "user" },
      execute: async (cap) => {
        await cap.save(
          async () => {
            entered();
            await wait;
            return { value: 1, receipt: { id: "1", url: "https://example.test/1" } };
          },
          () => {
            gates++;
            return { gateExited: true };
          },
        );
        return revision;
      },
    });
    await started;
    f.close();
    const record = f.record();
    assert.ok(record.consumption.state === "uncertain");
    assert.equal(record.consumption.attempt.save.state, "started");
    release();
    const result = await completed;
    assert.equal(result.ok, false);
    assert.equal(result.saveReceipt?.id, "1", "late backend receipt remains a fact, not authority");
    assert.equal(gates, 0);
    assert.equal(f.messages.length, 0);
    assert.deepEqual(f.record(), record);
  } finally {
    f.dispose();
  }
});

test("an unreadable identity at prepared completion permanently ends local authority without effects", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f);
    const original = f.ctx.sessionManager.getSessionId;
    Object.defineProperty(f.ctx.sessionManager, "getSessionId", {
      configurable: true,
      value: () => {
        throw new Error("identity unavailable");
      },
    });
    const refused = await toolCompletion(review, outcome);
    assert.ok(!refused.ok && refused.reason === "superseded");
    Object.defineProperty(f.ctx.sessionManager, "getSessionId", {
      configurable: true,
      value: original,
    });
    assert.equal(review.signal.aborted, true);
    assert.equal((await toolCompletion(review, outcome)).ok, false);
    assert.equal(f.record().consumption.state, "pending");
  } finally {
    f.dispose();
  }
});

test("runtime missing identity is not permission for an ordinary unclaimed mutation", async () => {
  const f = fixture();
  try {
    f.branch.splice(0);
    const sync = f.reviews.mutate(f.ctx, "manual-save", () => assert.fail("identity required"));
    const asyncResult = await f.reviews.mutateAsync(f.ctx, "manual-save", async () =>
      assert.fail("identity required"),
    );
    assert.ok(!sync.ok && sync.reason === "no-identity");
    assert.ok(!asyncResult.ok && asyncResult.reason === "no-identity");
  } finally {
    f.dispose();
  }
});

for (const change of ["session", "fork", "unavailable"] as const) {
  test(`activation ${change} mismatch never observes old expectations in replacement context`, async () => {
    const f = fixture();
    try {
      const { review, outcome } = await attached(f);
      const result = await toolCompletion(review, outcome);
      assert.ok(result.ok && "content" in result.value);
      persistTool(f, result.value);
      const prior = f.record();
      const branch = [...f.branch];
      if (change === "fork")
        branch.push({ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "RID.1" } });
      const ctx = {
        ...f.ctx,
        sessionManager: {
          getSessionId: () => (change === "session" ? "replacement" : "session"),
          getBranch: () => {
            if (change === "unavailable") throw new Error("unreadable");
            return branch;
          },
        },
      } as unknown as ExtensionContext;
      f.events.get("turn_end")?.({}, ctx);
      assert.deepEqual(f.record(), prior);
      assert.equal(review.signal.aborted, true);
      assert.equal((await toolCompletion(review, outcome)).ok, false);
      assert.equal(
        f.reviews.mutate(f.ctx, "manual-save", () => assert.fail("no replay")).ok,
        false,
      );
      assert.equal(f.messages.length, 0);
    } finally {
      f.dispose();
    }
  });
}

test("fresh activation does not discover or consume previous activation dispatch, even with matching persisted evidence", async () => {
  const f = fixture();
  try {
    const { review, outcome } = await attached(f);
    const result = await toolCompletion(review, outcome);
    assert.ok(result.ok && "content" in result.value);
    persistTool(f, result.value);
    const count = f.requests.length;
    const next = createDraftReviewActivation(f.pi);
    f.events.get("turn_end")?.({}, f.ctx);
    assert.equal(f.record().consumption.state, "dispatch");
    const refused = next.mutate(f.ctx, "manual-save", () => assert.fail("old dispatch blocks"));
    assert.ok(!refused.ok && refused.reason === "unresolved-dispatch");
    assert.equal(f.record().consumption.state, "dispatch");
    assert.equal(f.requests.length, count);
    assert.equal(f.messages.length, 0);
    review.dispose();
  } finally {
    f.dispose();
  }
});
