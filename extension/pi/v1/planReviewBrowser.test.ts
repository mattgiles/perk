// Tests for the warm `/plan-review-browser` door. The pure `planReviewBrowserGuidance` +
// `observePlanReviewReadiness` + `routePlanReviewDecision` are pinned directly (fake pi/ctx
// slices; the planSave.test.ts fakeColdDoorPi recipe with PERK_NO_LLM=1 for the approve→save
// composition); the background open runs over fake `StartBrowserDeps` + a fake bus; the
// command's entry gates / draft resolve / injection run against a REAL bound session via the
// T1 harness, OFFLINE (a fake plannotator extension registers the presence-probe command + the
// plan-review handshake listener).

import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import {
  clearDraftReviewContext,
  createDraftReviewWaveState,
  primeDraftReviewContext,
} from "../../authoring/review/draftContext.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import type { ReportTarget } from "../../surfaces/report.ts";
import { seedBrowserReviews } from "../../testing/draftReview.ts";
import {
  gitInit,
  loadPerkSession,
  type PerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../testing/harness.ts";
import { createMemoryWaveAdapter } from "../../testing/memoryAdapter.ts";
import { reportWaveOver } from "../../waves/reportWave.ts";
import { executeStartDraftReviewWave } from "./draftReviewWaveTools.ts";
import {
  observePlanReviewReadiness,
  openPlanReviewAndGuide,
  openPlanReviewSurface,
  planReviewBrowserGuidance,
} from "./planReviewBrowser.ts";
import {
  clearAnnotationSurface,
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
  primeAnnotationSurface,
} from "./providers/annotations.ts";
import type { StartedSurface } from "./providers/plannotatorHandoff.ts";
import type { ReviewOutcome } from "./review.ts";

// ------------------------------------------------------------------ surface probes (shared)

/** Probe the annotation surface's primed mode: `findings: []` with nothing held makes NO fetch. */
async function annotationMode(): Promise<string | null> {
  const never: FetchLike = async () => {
    throw new Error("the probe must not fetch");
  };
  const target = { hasUI: false, ui: undefined } as unknown as Parameters<
    typeof executePushAnnotations
  >[1];
  const result = await executePushAnnotations(
    annotations,
    target,
    { angle: "probe", findings: [] },
    { fetchLike: never },
  );
  if (!result.details.ok) return null;
  return (result.details as { mode?: string }).mode ?? null;
}

/** The suite-owned draft-review state, threaded exactly where index.ts threads its own. */
const draftReview = createDraftReviewWaveState();

/** The suite-owned annotation state, threaded exactly where index.ts threads its own. */
const annotations = createAnnotationState();

/** Probe the draft-review context: a ping-null start is `unavailable` iff a context is primed. */
async function draftContextPrimed(): Promise<boolean> {
  const target = { hasUI: false, ui: undefined } as unknown as ReportTarget;
  const result = await executeStartDraftReviewWave(
    draftReview,
    reportWaveOver(createMemoryWaveAdapter({ ping: null })),
    target,
    {
      angles: ["grounding", "risk"],
    },
  );
  return (result.details as { error_type?: string }).error_type !== "no_draft_context";
}

/** Probe the SESSION's annotation state through the registered tool (null = unprimed). */
async function sessionAnnotationMode(h: PerkSession): Promise<string | null> {
  const result = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
  if (!(result.details as { ok: boolean }).ok) return null;
  return (result.details as { mode?: string }).mode ?? null;
}

/**
 * Probe a bound SESSION's registration-owned draft-review context through its registered tool
 * (the closure state is deliberately unreachable — per-registration isolation). When primed the
 * probe launches into a ping that no responder answers — pin PERK_WAVE_RPC_PING_MS small in
 * sessions that expect a primed probe.
 */
async function sessionDraftContextPrimed(h: PerkSession): Promise<boolean> {
  const result = await h.invokeTool("start_draft_review_wave", { angles: ["grounding", "risk"] });
  return (result.details as { error_type?: string }).error_type !== "no_draft_context";
}

// ------------------------------------------------------------------ planReviewBrowserGuidance

test("guidance: names the three companion tools + the relay loop, no fan-out mechanics, no URL", () => {
  const text = planReviewBrowserGuidance({});
  assert.match(text, /start_draft_review_wave/, "the fan-out is the launch tool");
  assert.match(text, /collect_draft_review_wave/, "completion rides the collect tool");
  assert.match(text, /push_annotations/, "annotation delivery rides the push tool");
  assert.match(text, /Native-wake relay/, "the draft door relays native batches");
  assert.match(text, /grounding/, "the four angles are named");
  assert.match(text, /decision-completeness/);
  assert.match(text, /byte-exact/, "the phrase discipline is pinned");
  assert.match(text, /replace: true/, "the reconcile reshape is the tool's replace");
  assert.match(text, /First clear every uncovered source/);
  assert.match(text, /disjoint final per-angle arrays/);
  assert.match(text, /author label names the owning lane/);
  assert.match(text, /valid custom contribution may instead appear in merged text/);
  assert.match(text, /NOT a degrade/, "a held result ≠ a degrade");
  assert.match(text, /untrusted DATA/);
  assert.match(text, /\{complete, covered, reports, failures\}/, "the typed aggregate");
  assert.match(text, /never papered over/, "incompleteness is surfaced honestly");
  assert.match(text, /Do NOT call `plan_review`/, "the mid-review exclusion is pinned");
  assert.match(text, /never save on your own/);
  // The model-authored mechanics and the surface handle are unrepresentable — including the URL
  // itself: the model never sees the server address.
  for (const gone of [
    /workflowScript/,
    /runs\.all/,
    /outputSchema/,
    /subagent_wait|bg_wait|hold your turn open|timeout expiry IS the streaming cadence/,
    /external-annotations/,
    /curl/,
    /127\.0\.0\.1/,
    /localhost/,
    /PLANNOTATOR_PORT/,
  ]) {
    assert.doesNotMatch(text, gone, `mechanics must not appear: ${gone}`);
  }
});

test("guidance: the custom arm renders/omits (primed lane, never re-encoded)", () => {
  const withCustom = planReviewBrowserGuidance({ custom: "check the rollback story" });
  assert.match(withCustom, /custom review lane/i);
  assert.match(withCustom, /check the rollback story/);
  assert.match(withCustom, /do NOT re-encode it/);
  const bare = planReviewBrowserGuidance({});
  assert.doesNotMatch(bare, /custom review lane/i);
  assert.doesNotMatch(bare, /re-encode/);
});

test("guidance: no hardcoded perk-plan-review-browser skill pointer (the binding suffix delivers it)", () => {
  for (const opts of [{}, { custom: "lens" }]) {
    assert.doesNotMatch(
      planReviewBrowserGuidance(opts),
      /Follow the `perk-plan-review-browser` skill/,
    );
  }
});

// ------------------------------------------------------- observePlanReviewReadiness

const COMPLETED: ReviewOutcome = { status: "completed", approved: true, reviewId: "r1" };

function fakeStarted(
  readiness: "ready" | "timeout" | "bridge_settled" | "aborted",
  bridge: ReviewOutcome = COMPLETED,
): StartedSurface<ReviewOutcome> {
  return {
    url: "http://127.0.0.1:45001",
    port: 45001,
    bridgePromise: Promise.resolve(bridge),
    readiness: Promise.resolve(readiness),
  };
}

async function observe(
  started: StartedSurface<ReviewOutcome>,
  opts?: { idle?: boolean },
): Promise<{
  notifies: { message: string; severity?: string }[];
  sent: { message: string; options?: { deliverAs?: string } }[];
}> {
  const notifies: { message: string; severity?: string }[] = [];
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  await observePlanReviewReadiness(
    {
      sendUserMessage: (message: string, options?: { deliverAs?: "steer" | "followUp" }) => {
        sent.push(options === undefined ? { message } : { message, options });
      },
    },
    {
      hasUI: true,
      ui: { notify: (message: string, severity?: string) => notifies.push({ message, severity }) },
      isIdle: () => opts?.idle ?? true,
    },
    started,
    draftReview,
    annotations,
    { degraded: false },
    () => true,
    () => ({ ok: true }),
  );
  return { notifies, sent };
}

/** Prime BOTH door surfaces (the pre-degrade state). */
function primeBoth(): void {
  primeAnnotationSurface(annotations, { mode: "plan", url: "http://127.0.0.1:45001" });
  primeDraftReviewContext(draftReview, { draftType: "plan", draft: "# The draft\n" });
}

test("observer: ready without pending annotation work → info only, surfaces untouched", async () => {
  primeBoth();
  const { notifies, sent } = await observe(fakeStarted("ready"));
  assert.equal(sent.length, 0);
  assert.equal(notifies.length, 1);
  assert.match(notifies[0]?.message ?? "", /plannotator is up at http:\/\/127\.0\.0\.1:45001/);
  assert.equal(notifies[0]?.severity, "info");
  assert.equal(await annotationMode(), "plan", "the ready arm never clears");
  assert.equal(await draftContextPrimed(), true);
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

test("observer: timeout → loud error + the degrade notice (idle → immediate) + BOTH surfaces cleared", async () => {
  primeBoth();
  const { notifies, sent } = await observe(fakeStarted("timeout"));
  assert.equal(notifies.length, 1);
  assert.equal(notifies[0]?.severity, "error");
  assert.match(notifies[0]?.message ?? "", /did not become ready at http:\/\/127\.0\.0\.1:45001/);
  assert.equal(sent.length, 1, "the degrade notice is injected");
  assert.match(sent[0]?.message ?? "", /plan-review browser is unavailable/);
  assert.match(sent[0]?.message ?? "", /surface the draft-review wave's findings/);
  assert.match(sent[0]?.message ?? "", /push_annotations` now refuses \(`no_surface`\)/);
  assert.match(sent[0]?.message ?? "", /\/plan-save/);
  assert.equal(sent[0]?.options, undefined, "idle ⇒ an immediate turn");
  assert.equal(await annotationMode(), null, "the degrade arm clears the annotation surface");
  assert.equal(await draftContextPrimed(), false, "…and the draft-review context");
});

test("observer: timeout while streaming → the degrade notice rides followUp", async () => {
  const { sent } = await observe(fakeStarted("timeout"), { idle: false });
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0]?.options, { deliverAs: "followUp" });
});

test("observer: bridge settled unavailable → degrade + clear; completed/aborted → silent", async () => {
  primeBoth();
  const degraded = await observe(
    fakeStarted("bridge_settled", { status: "unavailable", warning: "boom" }),
  );
  assert.equal(degraded.notifies.length, 1);
  assert.equal(degraded.notifies[0]?.severity, "error");
  assert.equal(degraded.sent.length, 1, "the degrade notice is injected");
  assert.equal(await annotationMode(), null, "the unavailable settle clears both surfaces");
  assert.equal(await draftContextPrimed(), false);

  // The decision task owns the settled outcomes — the observer stays silent and never clears.
  primeBoth();
  const completed = await observe(fakeStarted("bridge_settled", COMPLETED));
  assert.equal(completed.notifies.length, 0, "the decision task routes the completed arm");
  assert.equal(completed.sent.length, 0);
  assert.equal(await annotationMode(), "plan", "the completed arm never clears");
  assert.equal(await draftContextPrimed(), true);

  const aborted = await observe(fakeStarted("bridge_settled", { status: "aborted" }));
  assert.equal(aborted.notifies.length, 0);
  assert.equal(aborted.sent.length, 0);

  const turnAborted = await observe(fakeStarted("aborted"));
  assert.equal(turnAborted.notifies.length, 0, "an aborted turn stays silent");
  assert.equal(turnAborted.sent.length, 0);
  assert.equal(await annotationMode(), "plan", "aborted arms leave the surfaces primed");
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

// Decision-policy composition is covered by draftReviewBrowsers.test.ts with real claims.

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

// ------------------------------------------------- openPlanReviewAndGuide (fake deps + bus)

/** A minimal in-process event bus (the pi.events shape the bridge speaks). */
function fakeBus(): {
  emit(name: string, data?: unknown): void;
  on(name: string, handler: (data: unknown) => void): () => void;
} {
  const handlers = new Map<string, Set<(data: unknown) => void>>();
  return {
    emit(name, data) {
      const request = data as { action?: string; respond(value: unknown): void };
      if (name === "plannotator:request" && request.action === "review-status") {
        request.respond({ status: "handled", result: { status: "pending" } });
        return;
      }
      for (const handler of [...(handlers.get(name) ?? [])]) handler(data);
    },
    on(name, handler) {
      let set = handlers.get(name);
      if (set === undefined) {
        set = new Set();
        handlers.set(name, set);
      }
      set.add(handler);
      return () => set?.delete(handler);
    },
  };
}

test("open: a post-degrade decision is ignored loudly (never routed into a save)", async () => {
  const cwd = scaffoldRepo();
  const bus = fakeBus();
  const injected: string[] = [];
  const notified: { message: string; severity?: string }[] = [];
  bus.on("plannotator:request", (raw) => {
    const req = raw as { respond: (r: unknown) => void };
    req.respond({ status: "handled", result: { status: "pending", reviewId: "r-9" } });
  });
  const pi = {
    events: bus,
    sendUserMessage(message: string | { type: "text"; text: string }[]) {
      injected.push(typeof message === "string" ? message : message.map((b) => b.text).join("\n"));
    },
    appendEntry() {},
    async exec() {
      throw new Error("a post-degrade decision must never reach the save path");
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => [] },
    hasUI: true,
    ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    isIdle: () => true,
    signal: undefined,
  } as unknown as ExtensionContext;

  // probe:false + a tiny budget → the readiness poll times out → the degrade arm fires.
  await openPlanReviewAndGuide(
    pi,
    ctx,
    fakeGating(true),
    { draft: "# The draft\n" },
    draftReview,
    annotations,
    seedBrowserReviews(pi, ctx, "plan", "# The draft\n"),
    {
      pickFreePort: async () => 45002,
      probe: async () => false,
      intervalMs: 1,
      budgetMs: 3,
      sleep: async () => {},
    },
  );
  const start = Date.now();
  while (
    !injected.some((m) => m.includes("plan-review browser is unavailable")) &&
    Date.now() - start < 2000
  ) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(
    injected.some((m) => m.includes("plan-review browser is unavailable")),
    "the degrade notice landed",
  );
  // A LATE approval arrives after the degrade — ignored loudly, never saved/injected.
  bus.emit("plannotator:review-result", { reviewId: "r-9", approved: true });
  const settle = Date.now();
  while (
    !notified.some((n) => n.message.includes("after local readiness suppression")) &&
    Date.now() - settle < 2000
  ) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(
    notified.some(
      (n) =>
        n.severity === "warning" &&
        n.message.includes("decision arrived after local readiness suppression"),
    ),
    "the late decision is ignored loudly",
  );
  assert.ok(
    !injected.some((m) => m.includes("APPROVED")),
    "no approval text reaches the model post-degrade",
  );
});

test("open core: primes BOTH surfaces with the deterministic URL/plan mode, RETURNS URL-free guidance (nothing sent), clears on settle", async () => {
  const cwd = scaffoldRepo();
  const bus = fakeBus();
  const injected: string[] = [];
  const notified: { message: string; severity?: string }[] = [];
  const requests: { payload?: { planContent?: string }; portAtEmit?: string }[] = [];
  // The fake plannotator: answer the plan-review handshake pending (reviewId r-1).
  bus.on("plannotator:request", (raw) => {
    const req = raw as { payload?: { planContent?: string }; respond: (r: unknown) => void };
    requests.push({ payload: req.payload, portAtEmit: process.env.PLANNOTATOR_PORT });
    req.respond({ status: "handled", result: { status: "pending", reviewId: "r-1" } });
  });
  const pi = {
    events: bus,
    sendUserMessage(message: string | { type: "text"; text: string }[]) {
      injected.push(typeof message === "string" ? message : message.map((b) => b.text).join("\n"));
    },
    appendEntry() {},
    async exec() {
      throw new Error("no save expected in this test");
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => [] },
    hasUI: true,
    ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    isIdle: () => true,
    signal: undefined,
  } as unknown as ExtensionContext;

  const guidance = await openPlanReviewSurface(
    pi,
    ctx,
    fakeGating(false),
    { draft: "# The draft\n", custom: "check the rollback story" },
    draftReview,
    annotations,
    seedBrowserReviews(pi, ctx, "plan", "# The draft\n"),
    {
      pickFreePort: async () => 45001,
      probe: async () => true,
      intervalMs: 1,
      budgetMs: 50,
      sleep: async () => {},
    },
  );
  assert.equal(typeof guidance, "string");
  if (typeof guidance !== "string") throw new Error("expected launch guidance");
  // Both surfaces primed with the deterministic handle the moment the open returns.
  assert.equal(await annotationMode(), "plan", "the annotation surface is primed in plan mode");
  assert.equal(await draftContextPrimed(), true, "the draft-review context is primed");
  // The handshake saw the preset port and the EXACT draft bytes.
  assert.equal(requests.length, 1);
  assert.equal(requests[0]?.portAtEmit, "45001");
  assert.equal(requests[0]?.payload?.planContent, "# The draft\n");
  // The core RETURNS the guidance (template launch line + the binding suffix) and sends nothing
  // itself — delivery belongs to the caller (the door wrapper / plan_review's wave arm).
  assert.equal(
    injected.length,
    0,
    "the caller owns seed guidance, and no pending annotations need a readiness continuation",
  );
  assert.match(guidance ?? "", /start_draft_review_wave/, "the template launch line");
  assert.match(
    guidance ?? "",
    /Follow the `perk-plan-review-browser` skill/,
    "the command:plan-review-browser binding suffix rides the returned guidance",
  );
  assert.match(guidance ?? "", /check the rollback story/);
  assert.doesNotMatch(guidance ?? "", /127\.0\.0\.1|localhost|45001/);
  assert.ok(
    notified.some(
      (n) => n.severity === "info" && n.message.includes("custom lane: check the rollback story"),
    ),
    "the entry line names the custom focus",
  );
  // The readiness observer saw `ready` and named the URL (human-facing only).
  const start = Date.now();
  while (
    !notified.some((n) => n.message.includes("plannotator is up")) &&
    Date.now() - start < 2000
  ) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(
    notified.some((n) => n.message.includes("plannotator is up at http://127.0.0.1:45001")),
  );

  // The human decides (DENY): the bridge settles, the deny turn injects, BOTH surfaces clear.
  bus.emit("plannotator:review-result", { reviewId: "r-1", approved: false, feedback: "fix X" });
  const settleStart = Date.now();
  while ((await annotationMode()) !== null && Date.now() - settleStart < 2000) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.equal(await annotationMode(), null, "the settle clears the annotation surface");
  assert.equal(await draftContextPrimed(), false, "…and the draft-review context");
  assert.ok(
    injected.some((m) => m.includes("DENIED") && m.includes("fix X")),
    "the deny feedback injected",
  );
  // The env preset was restored once the poll ended.
  assert.equal(process.env.PLANNOTATOR_PORT, undefined);
});

// ------------------------------------------------- the command flow through the harness

/** The plannotator:request envelope the fake plan-review listener records. */
interface PlanReviewEnvelope {
  requestId: string;
  action: string;
  payload: { planContent?: string; origin?: string };
  respond: (response: unknown) => void;
}

interface FakePlannotatorSink {
  envelopes: PlanReviewEnvelope[];
  envAtEmit: (string | undefined)[];
  emitDecision: (decision: Record<string, unknown>) => void;
}

/**
 * A fake plannotator extension: registers the `plannotator-review` presence-probe target and a
 * bus listener that records each `plan-review` envelope (+ `PLANNOTATOR_PORT` at emit time) and
 * answers the handshake pending — the decision is emitted later via `emitDecision`.
 */
function fakePlannotator(sink: FakePlannotatorSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    sink.emitDecision = (decision) => pi.events.emit("plannotator:review-result", decision);
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      const envelope = data as PlanReviewEnvelope;
      if (envelope.action === "review-status") {
        envelope.respond({ status: "handled", result: { status: "pending" } });
        return;
      }
      sink.envelopes.push(envelope);
      sink.envAtEmit.push(process.env.PLANNOTATOR_PORT);
      envelope.respond({
        status: "handled",
        result: { status: "pending", reviewId: `r-${sink.envelopes.length}` },
      });
    });
  };
}

function newSink(): FakePlannotatorSink {
  return { envelopes: [], envAtEmit: [], emitDecision: () => {} };
}

/** Settle every recorded bridge (DENY) and wait for the poll's env restore (bounded). */
async function settleBridges(sink: FakePlannotatorSink): Promise<void> {
  for (let i = 0; i < sink.envelopes.length; i++) {
    sink.emitDecision({ reviewId: `r-${i + 1}`, approved: false, feedback: "settle" });
  }
  const start = Date.now();
  while ("PLANNOTATOR_PORT" in process.env) {
    if (Date.now() - start > 5000) break; // bounded — never hang a test on cleanup
    await new Promise((r) => setTimeout(r, 25));
  }
}

const DRAFT_MD = "# The working draft\n\nStep one.\n";

test("/plan-review-browser: headless → the headless-specific refusal, nothing executed (no prime, no bridge)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "plan" } });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    headful: false,
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    assert.ok(h.registeredCommands().includes("plan-review-browser"), "the command is registered");
    // Seed a VALID draft so every later gate would pass — the hasUI gate is then the ONLY
    // refusing gate, and the headless-specific message proves it fired (a fall-through to the
    // no-draft refusal can no longer fake this test green).
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    const errors: string[] = [];
    const prevError = console.error;
    console.error = (...args: unknown[]) => {
      errors.push(args.map(String).join(" "));
    };
    try {
      await h.runCommandHandler("plan-review-browser", "");
    } finally {
      console.error = prevError;
    }
    assert.ok(
      errors.some((line) => line.includes("requires an interactive session")),
      "the headless-specific refusal fired (report() routes to stderr headless)",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
    assert.equal(await sessionAnnotationMode(h), null, "no surface primed");
    assert.equal(await sessionDraftContextPrimed(h), false, "no context primed");
  } finally {
    h.dispose();
  }
});

test("/plan-review-browser: plannotator absent → the pinned provider-selection refusal, no work", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "plan" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("plan-review-browser", "");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("the plannotator extension is not loaded") &&
          n.includes("select the plannotator plan provider (`[providers] plan = ") &&
          n.includes('"plannotator-plan"`), run `perk init`, then restart pi'),
      ),
      "the refusal names the fix",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(await sessionDraftContextPrimed(h), false, "no context primed");
  } finally {
    h.dispose();
  }
});

test("/plan-review-browser: wrong/absent stage → the stage-gate refusal, nothing executed", async () => {
  // `objective-refine` rides the same gate: a refinement session never routes an (old, valid)
  // plan draft into the plan browser door.
  for (const stage of ["implement", "objective-refine", undefined]) {
    const cwd = scaffoldRepo({
      handoff: { runId: "01RID", mode: "read-write", ...(stage !== undefined ? { stage } : {}) },
    });
    const sink = newSink();
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID" },
      extraExtensions: [fakePlannotator(sink)],
    });
    const injected = spyInjections(h);
    try {
      await h.runCommandHandler("plan-review-browser", "");
      assert.ok(
        h.notifies.some((n) => n.includes("only runs inside a plan-authoring session")),
        `the refusal names the requirement (stage=${stage})`,
      );
      assert.equal(injected.length, 0, "nothing injected");
      assert.equal(sink.envelopes.length, 0, "no bridge emitted");
      assert.equal(await sessionDraftContextPrimed(h), false, "no context primed");
    } finally {
      h.dispose();
    }
  }
});

test("/plan-review-browser: no working draft → the plan_draft redirect, nothing executed", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("plan-review-browser", "");
    assert.ok(
      h.notifies.some(
        (n) => n.includes("no working plan draft") && n.includes("write it with plan_draft"),
      ),
      "the refusal directs plan_draft",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
    assert.equal(await sessionDraftContextPrimed(h), false, "no context primed");
  } finally {
    h.dispose();
  }
});

test("/plan-review-browser: a BLANK validated draft → the same refusal (drafts-only, param-never)", async () => {
  const cwd = scaffoldRepo();
  const blank = "   \n";
  const runId = "01RIDBLANK";
  // Plant a session whose workflow state carries a VALID pointer to blank artifact bytes.
  const dataDir = sessionDataDir(cwd, runId);
  const { mkdirSync } = await import("node:fs");
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(join(dataDir, PLAN_DRAFT_ARTIFACT), blank, "utf8");
  const file = plantSession(cwd, [
    {
      run_id: runId,
      mode: "read-only",
      stage: "plan",
      session_artifacts: {
        [PLAN_DRAFT_ARTIFACT]: {
          run_id: runId,
          name: PLAN_DRAFT_ARTIFACT,
          path: join(dataDir, PLAN_DRAFT_ARTIFACT),
          digest: digestSessionData(blank),
          at: new Date().toISOString(),
        },
      },
    },
  ]);
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("plan-review-browser", "");
    assert.ok(
      h.notifies.some((n) => n.includes("no working plan draft")),
      "a blank draft refuses like a missing one",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/plan-review-browser: happy path — primes both surfaces, injects URL-free guidance, decision routes + clears", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  gitInit(cwd, { dirty: false });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    // The primed-context probe launches into a ping no responder answers — keep it snappy.
    env: { PERK_RUN_ID: "01RID", PERK_WAVE_RPC_PING_MS: "20" },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    await h.runCommandHandler("plan-review-browser", "check the rollback story");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("working plan draft → plannotator browser review") &&
          n.includes("custom lane: check the rollback story"),
      ),
      "the info line names the flow + custom focus",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /start_draft_review_wave/);
    assert.match(text, /check the rollback story/);
    assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
    const marker =
      "Follow the `perk-plan-review-browser` skill (read `.agents/skills/perk-plan-review-browser/SKILL.md`).";
    assert.equal(
      text.split(marker).length - 1,
      1,
      "exactly one command:plan-review-browser pointer",
    );
    // The bridge saw the EXACT draft bytes with the preset port.
    assert.equal(sink.envelopes.length, 1, "the plan-review bridge request was emitted");
    assert.equal(sink.envelopes[0]?.action, "plan-review");
    assert.equal(sink.envelopes[0]?.payload.planContent, DRAFT_MD);
    assert.match(sink.envAtEmit[0] ?? "", /^\d+$/, "PLANNOTATOR_PORT preset at emit time");
    // Both companion surfaces primed.
    assert.equal(
      await sessionAnnotationMode(h),
      "plan",
      "the annotation surface is primed in plan mode",
    );
    assert.equal(await sessionDraftContextPrimed(h), true, "the draft-review context is primed");

    // The human DENIES: the feedback injects a revision turn and both surfaces clear.
    sink.emitDecision({ reviewId: "r-1", approved: false, feedback: "tighten the rollout step" });
    const start = Date.now();
    while ((await sessionAnnotationMode(h)) !== null && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionAnnotationMode(h), null, "the settle clears the annotation surface");
    assert.equal(await sessionDraftContextPrimed(h), false, "…and the draft-review context");
    assert.ok(
      injected.some((m) => m.includes("DENIED") && m.includes("tighten the rollout step")),
      "the deny feedback injected verbatim",
    );
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});
