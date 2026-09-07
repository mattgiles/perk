import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { renderObjectiveDraft } from "../../authoring/objective/draft.ts";
import { createDraftReviewWaveState } from "../../authoring/review/draftContext.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { readDraftReview } from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { gitInit, scaffoldRepo } from "../../testing/harness.ts";
import { createDraftReviewActivation } from "./draftReviewActivation.ts";
import { executeObjectiveReview } from "./objectiveReview.ts";
import { openObjectiveReviewSurface } from "./objectiveReviewBrowser.ts";
import { planSaveDepsFor } from "./plan.ts";
import { runPlanReviewV1 } from "./planReview.ts";
import { openPlanReviewSurface } from "./planReviewBrowser.ts";
import { createAnnotationState } from "./providers/annotations.ts";
import { createPlannotatorBridge } from "./providers/plannotator.ts";
import type { StartBrowserDeps } from "./providers/plannotatorHandoff.ts";
import type { WaveLaunch } from "./review.ts";

function deferred<T>() {
  let resolve = (_value: T): void => {
    throw new Error("uninitialized deferred");
  };
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}
type Subject = "plan" | "objective";
type Request = {
  action: string;
  requestId: string;
  payload: { reviewId?: string };
  respond(value: unknown): void;
};
type Blocks = { type: "text"; text: string }[];
const objective = {
  schema_version: 1,
  title: "Title",
  prose: "# Original\n",
  base: "main",
  delivery: "incremental" as const,
  roadmap: [{ id: "1.1", description: "One" }],
};
const directEdits =
  "# Direct Edits\n\n```diff\n--- plan.md\n+++ plan.md\n@@ -1 +1 @@\n-# Original\n+# Edited\n```\n\n---\n\nKeep this exact feedback.";

function fixture(subject: Subject) {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const branch: unknown[] = [
    {
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: {
        run_id: "RID",
        stage: subject === "plan" ? "plan" : "objective-author",
        mode: "read-only",
      },
    },
  ];
  const events = new Map<string, (event: unknown, ctx: ExtensionContext) => void>();
  const listeners = new Set<(value: unknown) => void>();
  const requests: Request[] = [];
  const sends: { content: Blocks; options: unknown }[] = [];
  const notices: string[] = [];
  const fallbacks: string[] = [];
  const fallbackOptions: unknown[] = [];
  const calls: { args: string[]; body: string | null }[] = [];
  const completed = deferred<void>();
  const queried = deferred<void>();
  const abort = new AbortController();
  let backend: (() => Promise<void>) | undefined;
  let sendThrows = false;
  let failNotice = false;
  let failState: string | undefined;
  let corruptPatch = false;
  let writeHook: (() => void) | undefined;
  let idle = true;
  let exits = 0;
  let saveSuccess = true;
  let statusHook: ((request: Request) => void) | undefined;
  let handshakeHook: ((request: Request) => void) | undefined;
  let subscriptionFails = false;
  const pi = {
    events: {
      emit(_name: string, request: Request) {
        requests.push(request);
        if (request.action === "plan-review") {
          if (handshakeHook !== undefined) handshakeHook(request);
          else
            request.respond({
              status: "handled",
              result: { status: "pending", reviewId: request.requestId },
            });
        } else {
          statusHook?.(request);
          queried.resolve();
        }
      },
      on(_name: string, listener: (value: unknown) => void) {
        if (subscriptionFails) throw new Error("controlled subscription failure");
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    },
    on(name: string, handler: (event: unknown, ctx: ExtensionContext) => void) {
      events.set(name, handler);
    },
    appendEntry(customType: string, data: Record<string, unknown>) {
      if (data.session_artifacts !== undefined) {
        const path = join(sessionDataDir(cwd, "RID"), "draft-review.json");
        if (existsSync(path)) {
          const state = JSON.parse(readFileSync(path, "utf8")).consumption;
          if (
            state.state === failState ||
            (failState === "delivery" && state.attempt?.delivery != null)
          )
            return;
          if (state.state === "dispatch" && writeHook !== undefined) {
            const hook = writeHook;
            writeHook = undefined;
            hook();
          }
        }
        const draftPath = join(sessionDataDir(cwd, "RID"), "plan-draft.md");
        if (
          corruptPatch &&
          existsSync(draftPath) &&
          readFileSync(draftPath, "utf8") === "# Edited\n"
        ) {
          writeFileSync(draftPath, "# Unverified corrupt bytes\n");
          return;
        }
      }
      branch.push({ type: "custom", customType, data });
    },
    sendUserMessage(content: Blocks | string, options: unknown) {
      if (typeof content === "string") {
        const state = record().consumption;
        assert.ok(
          state.state === "invalidated" &&
            ["degraded", "handshake-failed", "subscription-failed"].includes(state.reason),
          "fallback requires verified readiness or transport invalidation",
        );
        fallbacks.push(content);
        fallbackOptions.push(options);
        return;
      }
      const state = record().consumption;
      assert.equal(state.state, "dispatch", "verified intent before send");
      if (state.state === "dispatch")
        assert.ok(state.attempt.delivery, "full expectation before send");
      sends.push({ content, options });
      if (sendThrows) throw new Error("controlled send failure");
    },
    async exec(_cmd: string, args: string[]) {
      const bodyIndex = args.findIndex((arg) => arg === "--plan-file" || arg === "--prose-file");
      calls.push({
        args,
        body: bodyIndex < 0 ? null : readFileSync(args[bodyIndex + 1] ?? "", "utf8"),
      });
      const state = record().consumption;
      assert.ok(state.state === "dispatch" && state.attempt.save.state === "started");
      await backend?.();
      return {
        code: saveSuccess ? 0 : 1,
        killed: false,
        stderr: "",
        stdout: JSON.stringify(
          saveSuccess
            ? subject === "plan"
              ? {
                  success: true,
                  issue: { id: "42", url: "https://example.test/42", existed: false },
                  plan_ref: {
                    provider: "github",
                    pr_id: "42",
                    url: "https://example.test/42",
                    labels: ["perk:plan"],
                    objective_id: null,
                  },
                }
              : {
                  success: true,
                  objective: { id: "7", url: "https://example.test/7", existed: false },
                }
            : { success: false, error_type: "backend", message: "unconfirmed" },
        ),
      };
    },
    getCommands: () => [{ name: "plannotator-review" }],
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    signal: abort.signal,
    isIdle: () => idle,
    sessionManager: { getBranch: () => branch, getSessionId: () => "browser-session" },
    ui: {
      notify(text: string) {
        notices.push(text);
        if (failNotice && /APPROVED in the browser — saved/.test(text)) {
          failNotice = false;
          throw new Error("controlled save notice failure");
        }
        if (/browser decision dispatched|Draft review stopped/.test(text)) completed.resolve();
      },
      select: async () => "Browser review + reviewer wave",
      input: async () => "",
    },
  } as unknown as ExtensionContext;
  const gating = {
    isActive: () => true,
    exit() {
      exits++;
    },
    enter() {},
    syncFromState() {},
  } satisfies ToolGating;
  const reviews = createDraftReviewActivation(pi);
  const bridge = { ...createPlannotatorBridge(pi.events), ...reviews };
  const session = openBranchWorkflowSession(pi, ctx);
  const name = subject === "plan" ? "plan-draft.md" : "objective-draft.json";
  const raw = subject === "plan" ? "# Original\n" : JSON.stringify(objective);
  const markdown = subject === "plan" ? raw : renderObjectiveDraft(objective);
  assert.equal(session.writeArtifact(name, raw).status, "applied");
  const waves = createDraftReviewWaveState();
  const annotations = createAnnotationState();
  const deps: StartBrowserDeps = { pickFreePort: async () => 45001, probe: async () => true };
  function open() {
    return subject === "plan"
      ? openPlanReviewSurface(
          pi,
          ctx,
          gating,
          { draft: markdown },
          waves,
          annotations,
          reviews,
          deps,
        )
      : openObjectiveReviewSurface(
          pi,
          ctx,
          gating,
          { rendered: markdown, artifactRaw: raw },
          waves,
          annotations,
          reviews,
          deps,
        );
  }
  const wave: WaveLaunch = { present: () => true, plan: open, objective: open };
  function record() {
    const result = readDraftReview(session);
    assert.ok(result.ok && result.record);
    return result.record;
  }
  function event(approved: boolean, feedback?: string, reviewId = record().correlation.review_id) {
    for (const listener of [...listeners]) listener({ reviewId, approved, feedback });
  }
  function persist(content = sends[0]?.content, role = "user", id = "entry-1") {
    assert.ok(content);
    branch.push({ type: "message", id, message: { role, content } });
  }
  return {
    cwd,
    pi,
    ctx,
    session,
    reviews,
    requests,
    listeners,
    sends,
    notices,
    fallbacks,
    fallbackOptions,
    calls,
    waves,
    annotations,
    deps,
    open,
    event,
    record,
    persist,
    abort,
    queried: queried.promise,
    completed: completed.promise,
    chooser: () =>
      subject === "plan"
        ? runPlanReviewV1(
            ctx,
            bridge,
            planSaveDepsFor(pi, ctx, gating),
            undefined,
            undefined,
            wave,
            "chooser-tool",
          )
        : executeObjectiveReview(pi, ctx, gating, bridge, undefined, wave, "chooser-tool"),
    observe: () => events.get("turn_end")?.({}, ctx),
    shutdown: () => events.get("session_shutdown")?.({}, ctx),
    lock: () => existsSync(join(sessionDataDir(cwd, "RID"), "draft-review.lock")),
    exits: () => exits,
    setBackend(work: () => Promise<void>) {
      backend = work;
    },
    setStatus(work: (request: Request) => void) {
      statusHook = work;
    },
    setHandshake(work: (request: Request) => void) {
      handshakeHook = work;
    },
    failSubscription() {
      subscriptionFails = true;
    },
    setWriteHook(work: () => void) {
      writeHook = work;
    },
    setFailure(phase: string) {
      failState = phase;
    },
    setSendThrow() {
      sendThrows = true;
    },
    setNoticeThrow() {
      failNotice = true;
    },
    setCorruptPatch() {
      corruptPatch = true;
    },
    failSave() {
      saveSuccess = false;
    },
    stream() {
      idle = false;
    },
    change() {
      return reviews.mutate(
        ctx,
        "source-changed",
        (owned) =>
          owned.writeArtifact(
            name,
            subject === "plan" ? "# Changed\n" : JSON.stringify({ ...objective, base: "release" }),
          ),
        { draft: { subject } },
      );
    },
    text: () => sends.map((send) => send.content.map((block) => block.text).join("\n")).join("\n"),
    dispose() {
      events.get("session_shutdown")?.({}, ctx);
      rmSync(cwd, { recursive: true, force: true });
    },
  };
}

for (const subject of ["plan", "objective"] as const) {
  for (const failure of [
    "handshake-unavailable",
    "handshake-timeout",
    "subscription-failed",
  ] as const) {
    for (const readiness of ["sleeping", "ready"] as const) {
      test(`${subject}: ${failure} reaches fallback once with readiness ${readiness}`, async (t) => {
        const f = fixture(subject);
        const requested = deferred<Request>();
        const probing = deferred<void>();
        const sleeping = deferred<void>();
        const releaseSleep = deferred<void>();
        const disposed = deferred<void>();
        if (failure === "handshake-timeout") {
          const previous = process.env.PERK_PLANNOTATOR_HANDSHAKE_MS;
          delete process.env.PERK_PLANNOTATOR_HANDSHAKE_MS;
          t.after(() => {
            if (previous === undefined) delete process.env.PERK_PLANNOTATOR_HANDSHAKE_MS;
            else process.env.PERK_PLANNOTATOR_HANDSHAKE_MS = previous;
          });
          t.mock.timers.enable({ apis: ["setTimeout"] });
        }
        try {
          f.setHandshake(requested.resolve);
          if (failure === "subscription-failed") f.failSubscription();
          if (readiness === "sleeping") f.stream();
          f.deps.probe = async (_url, signal) => {
            assert.ok(signal);
            signal.addEventListener("abort", () => disposed.resolve(), { once: true });
            probing.resolve();
            return readiness === "ready";
          };
          f.deps.sleep = async () => {
            sleeping.resolve();
            await releaseSleep.promise;
          };
          assert.equal(typeof (await f.open()), "string");
          await probing.promise;
          if (readiness === "sleeping") await sleeping.promise;
          else await new Promise<void>((resolve) => setImmediate(resolve));
          const request = await requested.promise;
          if (failure === "handshake-timeout") t.mock.timers.tick(5_000);
          else
            request.respond(
              failure === "subscription-failed"
                ? { status: "handled", result: { status: "pending", reviewId: request.requestId } }
                : { status: "unavailable", error: "controlled unavailable bridge" },
            );
          await disposed.promise;
          assert.equal(
            f.fallbacks.length,
            1,
            "fallback is attempted before disposal aborts the poll",
          );
          assert.deepEqual(
            f.fallbackOptions[0],
            readiness === "sleeping" ? { deliverAs: "followUp" } : undefined,
          );
          assert.match(f.fallbacks[0] ?? "", new RegExp(`/${subject}-save`));
          assert.doesNotMatch(f.fallbacks[0] ?? "", /never became ready/);
          assert.deepEqual(
            f.record().consumption,
            {
              state: "invalidated",
              reason:
                failure === "subscription-failed" ? "subscription-failed" : "handshake-failed",
            },
            "fallback reuses the verified invalidation without rewriting its reason",
          );
          assert.equal(f.annotations.surface, null);
          assert.equal(f.waves.context, null);
          assert.equal(f.calls.length, 0);
          assert.equal(f.sends.length, 0);
          assert.equal(f.exits(), 0);
          assert.equal(f.lock(), false);
          assert.equal(f.listeners.size, 0);
          releaseSleep.resolve();
          await new Promise<void>((resolve) => setImmediate(resolve));
          assert.equal(f.fallbacks.length, 1, "late readiness cannot repeat the fallback");
        } finally {
          releaseSleep.resolve();
          await new Promise<void>((resolve) => setImmediate(resolve));
          f.dispose();
        }
      });
    }
  }

  test(`${subject}: failed transport invalidation never permits fallback`, async () => {
    const f = fixture(subject);
    const requested = deferred<Request>();
    const sleeping = deferred<void>();
    const releaseSleep = deferred<void>();
    const disposed = deferred<void>();
    try {
      f.setHandshake(requested.resolve);
      f.deps.probe = async (_url, signal) => {
        assert.ok(signal);
        signal.addEventListener("abort", () => disposed.resolve(), { once: true });
        return false;
      };
      f.deps.sleep = async () => {
        sleeping.resolve();
        await releaseSleep.promise;
      };
      await f.open();
      await sleeping.promise;
      f.setFailure("invalidated");
      (await requested.promise).respond({ status: "unavailable" });
      await disposed.promise;
      releaseSleep.resolve();
      await new Promise<void>((resolve) => setImmediate(resolve));
      assert.equal(f.fallbacks.length, 0);
      assert.equal(f.calls.length, 0);
      assert.equal(f.sends.length, 0);
      assert.equal(f.lock(), true);
      assert.ok(f.notices.some((text) => text.includes("persistence-failed")));
    } finally {
      releaseSleep.resolve();
      await new Promise<void>((resolve) => setImmediate(resolve));
      f.dispose();
    }
  });

  for (const order of ["event-first", "status-first"] as const)
    test(`${subject} chooser/browser: ${order}, one save/send, exact later persisted receipt`, async () => {
      const f = fixture(subject);
      try {
        f.stream();
        f.setStatus((request) => {
          const live = () => f.event(true, "verbatim feedback");
          const status = () =>
            request.respond({
              status: "handled",
              result: {
                status: "completed",
                reviewId: request.payload.reviewId,
                approved: true,
                feedback: "verbatim feedback",
              },
            });
          if (order === "event-first") {
            live();
            status();
          } else {
            status();
            live();
          }
        });
        const launched = await f.chooser();
        assert.equal(launched.details.status, "wave_launched");
        await f.completed;
        assert.equal(f.calls.length, 1);
        assert.equal(f.exits(), 1);
        assert.equal(f.sends.length, 1);
        assert.deepEqual(f.sends[0]?.options, { deliverAs: "followUp" });
        assert.equal(f.lock(), false, "no claim held for queued delivery");
        const state = f.record().consumption;
        assert.equal(state.state, "dispatch");
        if (state.state !== "dispatch") assert.fail();
        assert.equal(state.attempt.save.state, "confirmed");
        assert.equal(
          f.sends[0]?.content.at(-1)?.text,
          `<!-- perk:draft-review-dispatch:${state.attempt.dispatch_id} -->`,
        );
        assert.match(
          f.text(),
          /<untrusted_reviewer_feedback>\nverbatim feedback\n<\/untrusted_reviewer_feedback>/,
        );
        f.persist(undefined, "assistant", "wrong-role");
        f.observe();
        assert.equal(f.record().consumption.state, "dispatch");
        f.persist(
          [{ type: "text", text: state.attempt.delivery?.marker ?? "" }],
          "user",
          "wrong-content",
        );
        f.observe();
        assert.equal(f.record().consumption.state, "dispatch");
        f.persist();
        f.observe();
        assert.equal(f.record().consumption.state, "consumed");
        f.observe();
        assert.equal(f.calls.length, 1);
        assert.equal(f.sends.length, 1);
        await Promise.resolve();
        assert.equal(f.waves.context, null);
        assert.equal(f.annotations.surface, null);
      } finally {
        f.dispose();
      }
    });

  for (const feedback of ["denied exact DATA", directEdits])
    test(`${subject} stale ${feedback === directEdits ? "Direct Edits" : "denial"}: participating change gives diagnostic DATA once`, async () => {
      const f = fixture(subject);
      try {
        await f.open();
        await f.queried;
        assert.ok(f.change().ok);
        f.event(feedback === directEdits, feedback);
        await f.completed;
        assert.equal(f.calls.length, 0);
        assert.equal(f.exits(), 0);
        assert.equal(f.sends.length, 1);
        assert.match(f.text(), /diagnostic DATA only/);
        assert.ok(f.text().includes(feedback));
        assert.doesNotMatch(
          f.text(),
          /revise per this feedback|Fold the Direct Edits|then call plan_review/,
        );
        f.event(true, feedback);
        assert.equal(f.sends.length, 1);
        f.persist();
        assert.ok(f.change().ok, "persisted revision is observed before next writer");
        assert.equal(f.record().consumption.state, "consumed");
      } finally {
        f.dispose();
      }
    });

  test(`${subject} decision owns claim inside intent/backend boundaries; new open and mutations cannot win`, async () => {
    const f = fixture(subject);
    const entered = deferred<void>();
    const release = deferred<void>();
    try {
      await f.open();
      await f.queried;
      f.setWriteHook(() => {
        const mutation = f.reviews.mutate(f.ctx, "degraded", () => assert.fail("no fallback"));
        assert.ok(!mutation.ok && mutation.reason === "busy");
      });
      f.setBackend(async () => {
        entered.resolve();
        await release.promise;
      });
      f.event(true);
      await entered.promise;
      assert.equal(f.lock(), true);
      const changed = f.change();
      assert.ok(!changed.ok && changed.reason === "busy");
      const next = await f.open();
      assert.ok(next !== null && typeof next !== "string" && next.code === "busy");
      assert.equal(f.requests.filter((r) => r.action === "plan-review").length, 1);
      release.resolve();
      await f.completed;
      assert.equal(f.calls.length, 1);
      assert.equal(f.exits(), 1);
      assert.equal(f.sends.length, 1);
    } finally {
      release.resolve();
      f.dispose();
    }
  });

  test(`${subject} new opening wins before event: predecessor has no effects and cannot clear successor surfaces`, async () => {
    const f = fixture(subject);
    try {
      await f.open();
      await f.queried;
      const oldId = f.record().correlation.review_id;
      await f.open();
      f.event(true, "old", oldId);
      assert.equal(f.sends.length, 0);
      assert.equal(f.calls.length, 0);
      assert.ok(f.waves.context);
      f.event(false, "current");
      await f.completed;
      assert.equal(f.sends.length, 1);
      assert.match(f.text(), /current/);
      assert.doesNotMatch(f.text(), /\nold\n/);
    } finally {
      f.dispose();
    }
  });

  for (const failure of ["send", "queue", "notice", "backend", "delivery"] as const)
    test(`${subject} ${failure} uncertainty never replays; typed receipt and gate facts survive`, async () => {
      const f = fixture(subject);
      try {
        await f.open();
        await f.queried;
        if (failure === "send") f.setSendThrow();
        if (failure === "notice") f.setNoticeThrow();
        if (failure === "backend") f.failSave();
        if (failure === "delivery") f.setFailure("delivery");
        f.event(true);
        await f.completed;
        assert.equal(f.calls.length, 1);
        assert.equal(f.exits(), failure === "backend" ? 0 : 1);
        if (failure === "queue") {
          assert.equal(f.record().consumption.state, "dispatch");
          assert.equal(f.lock(), false);
          f.shutdown();
        }
        if (failure !== "delivery") {
          const state = f.record().consumption;
          assert.equal(state.state, "uncertain");
          if (state.state !== "uncertain") assert.fail();
          assert.equal(state.attempt.save.state, failure === "backend" ? "started" : "confirmed");
          if (failure !== "queue" && failure !== "backend")
            assert.match(f.notices.join("\n"), /Confirmed save:.*successful save already exited/);
        } else {
          assert.equal(f.lock(), true);
          assert.match(f.notices.join("\n"), /persistence-failed.*Confirmed save:/);
        }
        const next = await f.open();
        assert.ok(next !== null && typeof next !== "string");
        assert.equal(f.calls.length, 1);
        assert.doesNotMatch(f.notices.join("\n"), /manual failsafe.*retry|nothing saved/);
      } finally {
        f.dispose();
      }
    });
}

test("plan Direct Edits uses the shared completion: verified patch saves edited bytes; corrupt write-back saves frozen original", async () => {
  for (const corrupt of [false, true]) {
    const f = fixture("plan");
    try {
      await f.open();
      await f.queried;
      if (corrupt) f.setCorruptPatch();
      f.event(true, directEdits);
      await f.completed;
      assert.equal(f.calls.length, 1);
      assert.equal(f.exits(), 1);
      assert.equal(f.calls[0]?.body, corrupt ? "# Original" : "# Edited");
      assert.match(f.text(), /Keep this exact feedback/);
      if (!corrupt) assert.doesNotMatch(f.text(), /# Direct Edits/);
      else assert.match(f.text(), /Direct Edits could NOT/);
    } finally {
      f.dispose();
    }
  }
});

test("objective Direct Edits is a guarded structured revision; no backend or gate exit", async () => {
  const f = fixture("objective");
  try {
    await f.open();
    await f.queried;
    f.event(true, directEdits);
    await f.completed;
    assert.equal(f.calls.length, 0);
    assert.equal(f.exits(), 0);
    assert.match(f.text(), /Fold the Direct Edits diff/);
    assert.match(f.text(), /<untrusted_reviewer_feedback>\n# Direct Edits/);
    f.persist();
    f.observe();
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

for (const subject of ["plan", "objective"] as const) {
  for (const failed of [false, true])
    test(`${subject} readiness winner: verified invalidation before fallback, failed write retains local suppression only (${failed})`, async () => {
      const f = fixture(subject);
      const probe = deferred<boolean>();
      try {
        f.deps.probe = () => probe.promise;
        f.deps.budgetMs = 1;
        f.deps.intervalMs = 1;
        f.deps.sleep = async () => {};
        await f.open();
        await f.queried;
        if (failed) f.setFailure("invalidated");
        probe.resolve(false);
        for (let i = 0; i < 30; i++) await Promise.resolve();
        if (failed) {
          assert.equal(f.lock(), true);
          assert.equal(f.fallbacks.length, 0);
          assert.match(f.notices.join("\n"), /persistence-failed/);
          const strict = readDraftReview(f.session);
          assert.ok(!strict.ok, "no durable invalidation is claimed for broken provenance");
        } else {
          const state = f.record().consumption;
          assert.ok(state.state === "invalidated" && state.reason === "degraded");
          assert.equal(f.fallbacks.length, 1);
          assert.equal(f.lock(), false);
        }
        const request = f.requests.find((r) => r.action === "plan-review");
        f.event(true, "late approval", request?.requestId);
        for (let i = 0; i < 30; i++) await Promise.resolve();
        assert.equal(f.calls.length, 0);
        assert.equal(f.sends.length, 0);
        assert.equal(f.exits(), 0);
        assert.equal(f.waves.context, null);
        assert.equal(f.annotations.surface, null);
      } finally {
        f.dispose();
      }
    });

  test(`${subject} decision winner cannot be rolled back by readiness during backend await`, async () => {
    const f = fixture(subject);
    const probe = deferred<boolean>();
    const entered = deferred<void>();
    const release = deferred<void>();
    try {
      f.deps.probe = () => probe.promise;
      f.deps.budgetMs = 1;
      f.deps.intervalMs = 1;
      f.deps.sleep = async () => {};
      await f.open();
      await f.queried;
      f.setBackend(async () => {
        entered.resolve();
        await release.promise;
      });
      f.event(true);
      await entered.promise;
      probe.resolve(false);
      for (let i = 0; i < 30; i++) await Promise.resolve();
      assert.equal(f.fallbacks.length, 0);
      assert.equal(f.record().consumption.state, "dispatch");
      release.resolve();
      for (let i = 0; i < 50; i++) await Promise.resolve();
      assert.equal(f.calls.length, 1);
      assert.equal(f.exits(), 1);
      assert.equal(f.sends.length, 1);
      f.persist();
      f.observe();
      assert.equal(f.record().consumption.state, "consumed");
    } finally {
      release.resolve();
      f.dispose();
    }
  });

  test(`${subject} registration refusal never primes surfaces or takes chooser's null fallback`, async () => {
    const f = fixture(subject);
    try {
      f.setFailure("opening");
      const result = await f.chooser();
      assert.equal(result.details.status, "refused");
      assert.equal(result.details.reason, "persistence-failed");
      assert.equal(f.requests.length, 0);
      assert.equal(f.waves.context, null);
      assert.equal(f.annotations.surface, null);
      assert.equal(f.lock(), true);
      assert.equal(f.calls.length, 0);
      assert.equal(f.sends.length, 0);
    } finally {
      f.dispose();
    }
  });
}

test("plan browser title await fences routing/source drift before actual backend dispatch", async () => {
  for (const drift of ["source", "target"] as const) {
    const f = fixture("plan");
    const entered = deferred<void>();
    const release = deferred<void>();
    const old = process.env.PERK_NO_LLM;
    try {
      delete process.env.PERK_NO_LLM;
      Object.assign(f.ctx, {
        model: {},
        modelRegistry: {
          async getApiKeyAndHeaders() {
            entered.resolve();
            await release.promise;
            return undefined;
          },
        },
      });
      await f.open();
      await f.queried;
      f.event(true);
      await entered.promise;
      assert.equal(f.lock(), true);
      const competitor = f.change();
      assert.ok(!competitor.ok && competitor.reason === "busy");
      if (drift === "source") f.session.writeArtifact("plan-draft.md", "# External change\n");
      else
        writeFileSync(
          join(f.cwd, ".perk", "config.toml"),
          '[providers]\nplan = "plannotator-plan"\n# external config change\n',
        );
      release.resolve();
      await f.completed;
      assert.equal(f.calls.length, 0);
      assert.equal(f.sends.length, 0);
      assert.equal(f.exits(), 0);
      assert.equal(f.record().consumption.state, "uncertain");
    } finally {
      release.resolve();
      if (old === undefined) delete process.env.PERK_NO_LLM;
      else process.env.PERK_NO_LLM = old;
      f.dispose();
    }
  }
});
