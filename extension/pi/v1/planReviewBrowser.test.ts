// Tests for the warm `/plan-review-browser` door. The pure `planReviewBrowserGuidance` +
// `observePlanReviewReadiness` are pinned directly (fake pi/ctx slices); the decision routing is
// a COMPOSITION over the real draft-review slot in a real git repo (the planSave.test.ts
// fakeColdDoorPi recipe with PERK_NO_LLM=1 for the approve→save path — the four guards are
// exercised end to end, the git-config incident included); the background open runs over fake
// `StartBrowserDeps` + a fake bus; the command's entry gates / draft resolve / injection run
// against a REAL bound session via the T1 harness, OFFLINE (a fake plannotator extension
// registers the presence-probe command + the plan-review handshake listener).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT, revisePlanDraft } from "../../authoring/plan/draft.ts";
import {
  clearDraftReviewContext,
  createDraftReviewWaveState,
  primeDraftReviewContext,
} from "../../authoring/review/draftContext.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import type { ReportTarget } from "../../surfaces/report.ts";
import { seedBrowserReview } from "../../testing/draftReview.ts";
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
import {
  DRAFT_CHANGED_NOTE,
  type DraftReviewSlot,
  type OpenDraftReview,
  SUPERSEDED_DECISION_WARNING,
} from "./draftReview.ts";
import { executeStartDraftReviewWave } from "./draftReviewWaveTools.ts";
import { installPlanBindings } from "./plan.ts";
import {
  observePlanReviewReadiness,
  openPlanReviewAndGuide,
  openPlanReviewSurface,
  type PlanReviewDoorSession,
  planReviewBrowserGuidance,
  routePlanReviewDecision,
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

/** The always-current door-session token (the default `observe()` session). */
function currentSession(): PlanReviewDoorSession {
  return { degraded: false, current: () => true };
}

async function observe(
  started: StartedSurface<ReviewOutcome>,
  opts?: { idle?: boolean; session?: PlanReviewDoorSession },
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
    opts?.session ?? currentSession(),
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

test("observer: a superseded review's observer is inert — timeout → no report, no notice, both surfaces untouched, session not degraded", async () => {
  // Review A's observer times out AFTER review B opened (and re-primed the surfaces for ITS
  // session): A must not inject the fallback, clear B's surfaces, or flip its own session.
  primeBoth();
  const session: PlanReviewDoorSession = { degraded: false, current: () => false };
  const { notifies, sent } = await observe(fakeStarted("timeout"), { session });
  assert.equal(notifies.length, 0, "no error report");
  assert.equal(sent.length, 0, "no degrade notice");
  assert.equal(await annotationMode(), "plan", "the newer review's annotation surface survives");
  assert.equal(await draftContextPrimed(), true, "…and its draft-review context");
  assert.equal(session.degraded, false, "the superseded session is never flipped");
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

test("observer: bridge settled unavailable for a superseded review → silent (no report, no notice, surfaces untouched)", async () => {
  primeBoth();
  const session: PlanReviewDoorSession = { degraded: false, current: () => false };
  const { notifies, sent } = await observe(
    fakeStarted("bridge_settled", { status: "unavailable", warning: "boom" }),
    { session },
  );
  assert.equal(notifies.length, 0);
  assert.equal(sent.length, 0);
  assert.equal(await annotationMode(), "plan");
  assert.equal(await draftContextPrimed(), true);
  assert.equal(session.degraded, false);
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

test("observer: ready for a superseded review → no announce", async () => {
  primeBoth();
  const { notifies, sent } = await observe(fakeStarted("ready"), {
    session: { degraded: false, current: () => false },
  });
  assert.equal(notifies.length, 0, "a superseded review never announces 'plannotator is up'");
  assert.equal(sent.length, 0);
  assert.equal(await annotationMode(), "plan", "the ready arm never clears either way");
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

test("observer: superseded WHILE the bridge wait is pending → the post-await currency re-check stays silent (no report, no notice, surfaces untouched)", async () => {
  // The review is still current when readiness settles `bridge_settled` (the first fence
  // passes), a newer review opens while the observer awaits the bridge, then the bridge settles
  // `unavailable`: the SECOND fence — after the await — must stop the degrade.
  primeBoth();
  let checks = 0;
  const session: PlanReviewDoorSession = {
    degraded: false,
    current: () => {
      checks += 1;
      return checks === 1; // current at the first fence, superseded by the second
    },
  };
  let settleBridge: (out: ReviewOutcome) => void = () => {};
  const started: StartedSurface<ReviewOutcome> = {
    url: "http://127.0.0.1:45001",
    port: 45001,
    bridgePromise: new Promise<ReviewOutcome>((resolve) => {
      settleBridge = resolve;
    }),
    readiness: Promise.resolve("bridge_settled"),
  };
  const observing = observe(started, { session });
  // Let the observer pass the first fence and park on the bridge await before superseding.
  await new Promise((r) => setImmediate(r));
  assert.equal(checks, 1, "the observer passed the first fence while still current");
  settleBridge({ status: "unavailable", warning: "boom" });
  const { notifies, sent } = await observing;
  assert.equal(checks, 2, "the post-await re-check ran");
  assert.equal(notifies.length, 0, "no error report");
  assert.equal(sent.length, 0, "no degrade notice");
  assert.equal(await annotationMode(), "plan", "the newer review's annotation surface survives");
  assert.equal(await draftContextPrimed(), true, "…and its draft-review context");
  assert.equal(session.degraded, false, "the superseded session is never flipped");
  clearAnnotationSurface(annotations);
  clearDraftReviewContext(draftReview);
});

// --------------------------------------------------------------- routePlanReviewDecision

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

const FAIL_JSON = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
});

const DE_BASE = "# The draft\n\nStep one.\nStep two.\n";
const DE_PATCHED = "# The draft\n\nStep one (edited by reviewer).\nStep two.\n";
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
const DE_FEEDBACK = `${DE_SECTION}\n\n---\n\nAlso add a rollback note.`;

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
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

const APPROVE_OUT: ReviewOutcome = { status: "completed", approved: true, reviewId: "rev-a" };

/**
 * The decision-routing scaffold: a fake pi (cold door + injections) over a live plan-stage
 * branch in a REAL git repo with one `origin` remote (the destination fence needs a verifiable
 * checkout), the draft artifact written through the session, and the real slot. `open()` is the
 * door's slot open (the review token the decision task holds); `git()` runs git in the cwd.
 */
function decisionScaffold(opts: { saveJson?: string; saveCode?: number; idle?: boolean } = {}): {
  cwd: string;
  pi: ExtensionAPI;
  ctx: ExtensionContext;
  gating: ToolGating & { exits: number };
  slot: DraftReviewSlot;
  argvs: string[][];
  injected: { message: string; options?: { deliverAs?: string } }[];
  notified: { message: string; severity?: string }[];
  drafted: string;
  save: { json: string; code: number };
  open(draft?: string): OpenDraftReview;
  git(...args: string[]): void;
  route(out: ReviewOutcome, review: OpenDraftReview): Promise<void>;
} {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only", stage: "plan" })];
  const argvs: string[][] = [];
  const injected: { message: string; options?: { deliverAs?: string } }[] = [];
  const notified: { message: string; severity?: string }[] = [];
  const save = { json: opts.saveJson ?? PLAN_JSON, code: opts.saveCode ?? 0 };
  const pi = {
    appendEntry(customType: string, data?: unknown) {
      branch.push({ type: "custom", customType, data });
    },
    async exec(_cmd: string, args: string[]) {
      argvs.push(args);
      return { stdout: save.json, stderr: "", code: save.code, killed: false };
    },
    sendUserMessage(message: string, options?: { deliverAs?: string }) {
      injected.push(options === undefined ? { message } : { message, options });
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: true,
    ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    isIdle: () => opts.idle ?? true,
  } as unknown as ExtensionContext;
  const slot = seedBrowserReview(pi, ctx, "plan", DE_BASE);
  const gating = fakeGating(true);
  return {
    cwd,
    pi,
    ctx,
    gating,
    slot,
    argvs,
    injected,
    notified,
    drafted: join(sessionDataDir(cwd, "RID"), PLAN_DRAFT_ARTIFACT),
    save,
    open(draft = DE_BASE) {
      const opened = slot.open(ctx, {
        subject: "plan",
        source: "artifact",
        raw: draft,
        markdown: draft,
      });
      assert.ok(opened.ok, JSON.stringify(opened));
      return opened.review;
    },
    git(...args) {
      execFileSync("git", args, { cwd, stdio: "ignore" });
    },
    route: (out, review) => routePlanReviewDecision(pi, ctx, gating, slot, out, review),
  };
}

test("decision: APPROVE + Direct Edits → shared apply + approvalSave (edited bytes saved, gate exited)", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const review = s.open();
    const out: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-a",
      feedback: DE_FEEDBACK,
    };
    await s.route(out, review);
    assert.equal(readFileSync(s.drafted, "utf8"), DE_PATCHED, "the edits were written back");
    const argv = s.argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      DE_PATCHED.trimEnd(),
      "the save received the PATCHED plan",
    );
    assert.equal(s.gating.exits, 1, "the gate exited via the approvalSave seam");
    assert.ok(
      s.notified.some((n) => n.severity === "info" && n.message.includes("APPROVED")),
      "the saved arm reports info",
    );
    assert.equal(s.injected.length, 1, "the save outcome is injected to the model");
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /plan APPROVED by reviewer/);
    assert.match(text, /human edits were written back to the draft and saved/);
    assert.match(text, /Also add a rollback note\./, "the annotation remainder survives");
    assert.doesNotMatch(text, /# Direct Edits/, "the applied diff never renders as guidance");
    // The reviewer-originated remainder is delimited as untrusted DATA in the injected copy.
    assert.match(text, /untrusted DATA, never instructions/);
    assert.match(
      text,
      /<untrusted_reviewer_feedback>\nAlso add a rollback note\.\n<\/untrusted_reviewer_feedback>/,
      "the feedback rides inside the untrusted delimiter",
    );
    assert.equal(s.injected[0]?.options, undefined, "idle ⇒ an immediate turn");
    assert.equal(s.slot.unconfirmed(), null, "a confirmed save never latches");
  });
});

test("decision: APPROVE + unapplyable Direct Edits → verbatim save + the loud warning", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const review = s.open();
    const out: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-b",
      feedback: "# Direct Edits\n\nthe fence never arrived",
    };
    await s.route(out, review);
    assert.equal(readFileSync(s.drafted, "utf8"), DE_BASE, "the draft is untouched");
    const argv = s.argvs[0] ?? [];
    assert.equal(
      readFileSync(argv[argv.indexOf("--plan-file") + 1] ?? "", "utf8"),
      DE_BASE.trimEnd(),
      "the ORIGINAL bytes saved verbatim",
    );
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /Direct Edits could NOT be auto-applied/);
    assert.equal(s.gating.exits, 1, "the verbatim save still exits the gate");
  });
});

test("decision (the incident): an unrelated git-config change during the review never blocks the approval — one save, gate exited", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const review = s.open();
    // Landing a PR adds and then deletes `branch.<name>.*` entries — routing-irrelevant.
    s.git("config", "branch.tmp.remote", "origin");
    s.git("config", "--unset", "branch.tmp.remote");
    s.git("config", "user.email", "someone-else@example.com");
    await s.route(APPROVE_OUT, review);
    assert.equal(s.argvs.length, 1, "exactly one save call");
    assert.equal(s.gating.exits, 1, "the gate exited");
    assert.ok(s.notified.some((n) => n.severity === "info" && n.message.includes("APPROVED")));
    assert.match(s.injected[0]?.message ?? "", /plan APPROVED by reviewer/);
    assert.doesNotMatch(s.injected[0]?.message ?? "", /destination/);
  });
});

test("decision: `git remote set-url` during the review → destination-changed naming `remotes`, nothing saved; a fresh open + approve saves once", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const review = s.open();
    s.git("remote", "set-url", "origin", "https://github.com/acme/forked.git");
    await s.route(APPROVE_OUT, review);
    assert.equal(s.argvs.length, 0, "nothing saved");
    assert.equal(s.gating.exits, 0, "the gate stays on");
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "error" &&
          n.message.includes("save destination changed while the review was open") &&
          n.message.includes("changed: remotes"),
      ),
      `the fence reports loudly: ${JSON.stringify(s.notified)}`,
    );
    assert.equal(s.injected.length, 1, "the model is told nothing was saved");
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /The human APPROVED the plan, but the save destination changed/);
    assert.match(text, /\(changed: remotes\)/);
    assert.doesNotMatch(text, /forked/, "component names only — never values");
    assert.match(text, /call plan_review to open a fresh review against the current destination/);
    // The human re-runs the door: the fresh open captures the new destination and saves once.
    const fresh = s.open();
    await s.route(APPROVE_OUT, fresh);
    assert.equal(s.argvs.length, 1, "one save call from the fresh review");
    assert.equal(s.gating.exits, 1);
  });
});

test("decision: a superseded review's decision is ignored loudly — one TUI warning, no injection, no save", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const first = s.open();
    const second = s.open(); // another surface (or a re-run door) opened a newer review
    assert.equal(first.isCurrent(), false);
    assert.equal(second.isCurrent(), true);
    await s.route(APPROVE_OUT, first);
    assert.equal(s.argvs.length, 0, "nothing saved");
    assert.equal(s.gating.exits, 0);
    assert.equal(s.injected.length, 0, "nothing injected");
    assert.equal(s.notified.length, 1, "exactly one TUI warning");
    assert.equal(s.notified[0]?.severity, "warning");
    assert.ok(s.notified[0]?.message.endsWith(SUPERSEDED_DECISION_WARNING));
    // The current review still routes normally.
    await s.route(APPROVE_OUT, second);
    assert.equal(s.argvs.length, 1);
    assert.equal(s.gating.exits, 1);
  });
});

test("decision: a plan_draft write during the review → stale-approval (nothing saved, gate ON); a DENY proceeds with the draft-changed note", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold();
    const review = s.open();
    // A concurrent plan_draft write lands while the browser review is open.
    const revised = revisePlanDraft(
      { plan: "# A newer, unreviewed draft\n" },
      openBranchWorkflowSession(s.pi, s.ctx),
    );
    assert.equal(revised.status, "revised");
    await s.route(APPROVE_OUT, review);
    assert.equal(s.argvs.length, 0, "nothing saved");
    assert.equal(s.gating.exits, 0, "the gate stays on");
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "error" &&
          n.message.includes("working draft changed after the review opened"),
      ),
      "the stale refusal reports loudly",
    );
    assert.equal(s.injected.length, 1, "the model is told the approval did not save");
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /The human APPROVED the plan, but the working draft changed/);
    assert.match(text, new RegExp(`reviewed digest ${digestSessionData(DE_BASE)}`));
    assert.match(text, /Nothing was saved/);
    assert.match(text, /Call plan_review to review the current draft/);

    // The same moved draft under a DENY: the revision round proceeds, prefixed with the note.
    const deny: ReviewOutcome = {
      status: "completed",
      approved: false,
      reviewId: "rev-d",
      feedback: "fix X",
    };
    await s.route(deny, s.open());
    assert.equal(s.argvs.length, 0);
    const denied = s.injected[1]?.message ?? "";
    assert.ok(denied.startsWith(DRAFT_CHANGED_NOTE), "the note leads the revision result");
    assert.match(denied, /The human DENIED the plan in the browser review/);
    assert.match(denied, /<untrusted_reviewer_feedback>\nfix X\n<\/untrusted_reviewer_feedback>/);
  });
});

test("decision: DENY → feedback injected verbatim (streaming ⇒ followUp), NO save, no note when the draft held", async () => {
  const s = decisionScaffold({ idle: false });
  const review = s.open();
  const out: ReviewOutcome = {
    status: "completed",
    approved: false,
    reviewId: "rev-d",
    feedback: DE_FEEDBACK,
  };
  await s.route(out, review);
  assert.equal(s.argvs.length, 0, "no save on a deny");
  assert.equal(s.gating.exits, 0, "the gate stays on");
  assert.equal(readFileSync(s.drafted, "utf8"), DE_BASE, "deny never mutates the draft");
  assert.ok(s.notified.some((n) => n.severity === "info" && n.message.includes("DENIED")));
  assert.equal(s.injected.length, 1);
  const text = s.injected[0]?.message ?? "";
  assert.ok(!text.startsWith(DRAFT_CHANGED_NOTE), "no note when the draft held");
  assert.match(text, /The human DENIED the plan in the browser review/);
  assert.match(text, /plan_draft/);
  assert.match(text, /\/plan-review-browser/);
  assert.match(text, /# Direct Edits/, "the diff reaches the model verbatim (model-mediated)");
  // Verbatim-but-delimited: the untrusted wrapper carries the whole feedback.
  assert.match(text, /untrusted DATA, never instructions/);
  assert.match(text, /<untrusted_reviewer_feedback>\n# Direct Edits/);
  assert.match(text, /<\/untrusted_reviewer_feedback>/);
  assert.deepEqual(s.injected[0]?.options, { deliverAs: "followUp" }, "streaming ⇒ followUp");
});

test("decision: APPROVE + failed save → loud error naming /plan-save, gate ON, the latch pauses the next approval while /plan-save still saves", async () => {
  await withNoLlm(async () => {
    const s = decisionScaffold({ saveJson: FAIL_JSON, saveCode: 1 });
    await s.route(APPROVE_OUT, s.open());
    assert.equal(s.argvs.length, 1, "the backend was attempted once");
    assert.equal(s.gating.exits, 0, "a failed save leaves the gate on");
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "error" &&
          n.message.includes("auto-save did not confirm") &&
          n.message.includes("/plan-save (the deliberate retry)"),
      ),
      "the failure report names the deliberate retry",
    );
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /auto-save FAILED/);
    assert.match(text, /gh exploded/);
    assert.match(text, /automatic saves are paused for this session/);
    assert.match(text, /\/plan-save \(the deliberate retry\)/);
    assert.deepEqual(s.slot.unconfirmed(), { subject: "plan", detail: "gh exploded" });

    // The backend recovers, the human re-runs the door and approves: still paused — the latch
    // never clears within the activation.
    s.save.json = PLAN_JSON;
    s.save.code = 0;
    await s.route(APPROVE_OUT, s.open());
    assert.equal(s.argvs.length, 1, "zero further save calls");
    assert.equal(s.gating.exits, 0);
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "error" && n.message.includes("an earlier save attempt in this session"),
      ),
    );
    const paused = s.injected[1]?.message ?? "";
    assert.match(paused, /an earlier save attempt in this session did not confirm \(gh exploded\)/);
    assert.match(paused, /run id RID/);
    assert.match(paused, /\/plan-save \(the deliberate retry\)/);

    // /plan-save IS the deliberate retry: it never consults the latch and invokes the backend.
    const commands = new Map<string, (args: string, ctx: ExtensionContext) => Promise<void>>();
    const registrar = {
      ...(s.pi as object),
      events: {
        emit() {},
        on() {
          return () => {};
        },
      },
      registerTool() {},
      registerCommand(
        name: string,
        spec: { handler: (a: string, c: ExtensionContext) => Promise<void> },
      ) {
        commands.set(name, spec.handler);
      },
      registerFlag() {},
      registerShortcut() {},
      getFlag() {
        return false;
      },
      on() {},
    } as unknown as ExtensionAPI;
    installPlanBindings(registrar, s.gating, s.slot, () => false);
    const planSave = commands.get("plan-save");
    assert.ok(planSave, "/plan-save registered");
    await planSave("", s.ctx);
    assert.equal(s.argvs.length, 2, "the manual retry reached the backend");
    assert.equal(s.gating.exits, 1, "the verified manual save exits the gate");
  });
});

test("decision: aborted → silent; unavailable → error report only (the observer owns the notice)", async () => {
  const aborted = decisionScaffold();
  await aborted.route({ status: "aborted" }, aborted.open());
  assert.equal(aborted.injected.length, 0);
  assert.equal(aborted.notified.length, 0);
  assert.equal(aborted.argvs.length, 0);

  const unavailable = decisionScaffold();
  await unavailable.route(
    { status: "unavailable", warning: "handshake timeout" },
    unavailable.open(),
  );
  assert.equal(unavailable.injected.length, 0, "the degrade notice is the observer's job");
  assert.ok(
    unavailable.notified.some((n) => n.severity === "error" && n.message.includes("handshake")),
  );
});

// ------------------------------------------------- openPlanReviewAndGuide (fake deps + bus)

/** A minimal in-process event bus (the pi.events shape the bridge speaks). */
function fakeBus(): {
  emit(name: string, data?: unknown): void;
  on(name: string, handler: (data: unknown) => void): () => void;
} {
  const handlers = new Map<string, Set<(data: unknown) => void>>();
  return {
    emit(name, data) {
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
    appendEntry(customType: string, data?: unknown) {
      branch.push({ type: "custom", customType, data });
    },
    async exec() {
      throw new Error("a post-degrade decision must never reach the save path");
    },
  } as unknown as ExtensionAPI;
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only", stage: "plan" })];
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => branch },
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
    seedBrowserReview(pi, ctx, "plan", "# The draft\n"),
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
    !notified.some((n) => n.message.includes("after the review degraded")) &&
    Date.now() - settle < 2000
  ) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.ok(
    notified.some(
      (n) =>
        n.severity === "warning" &&
        n.message.includes("a browser decision arrived after the review degraded — ignored"),
    ),
    "the late decision is ignored loudly",
  );
  assert.ok(
    !injected.some((m) => m.includes("APPROVED")),
    "no approval text reaches the model post-degrade",
  );
});

test("open: a still-starting review's late timeout never degrades the review that superseded it (observer record-fence); the newer review saves, the older decision is ignored loudly", async () => {
  await withNoLlm(async () => {
    const cwd = scaffoldRepo();
    const bus = fakeBus();
    const injected: string[] = [];
    const notified: { message: string; severity?: string }[] = [];
    const argvs: string[][] = [];
    // The fake plannotator answers the handshake pending: r-a for the first request, r-b for the
    // second.
    const reviewIds = ["r-a", "r-b"];
    bus.on("plannotator:request", (raw) => {
      const req = raw as { respond: (r: unknown) => void };
      req.respond({
        status: "handled",
        result: { status: "pending", reviewId: reviewIds.shift() ?? "r-unexpected" },
      });
    });
    const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only", stage: "plan" })];
    const pi = {
      events: bus,
      sendUserMessage(message: string | { type: "text"; text: string }[]) {
        injected.push(
          typeof message === "string" ? message : message.map((b) => b.text).join("\n"),
        );
      },
      appendEntry(customType: string, data?: unknown) {
        branch.push({ type: "custom", customType, data });
      },
      async exec(_cmd: string, args: string[]) {
        argvs.push(args);
        return { stdout: PLAN_JSON, stderr: "", code: 0, killed: false };
      },
    } as unknown as ExtensionAPI;
    const ctx = {
      cwd,
      sessionManager: { getBranch: () => branch },
      hasUI: true,
      ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
      isIdle: () => true,
      signal: undefined,
    } as unknown as ExtensionContext;
    const gating = fakeGating(true);
    // ONE slot across both opens — the second open supersedes the first review.
    const slot = seedBrowserReview(pi, ctx, "plan", "# The draft\n");

    // Review A: its single readiness probe is a gate the test releases later (budget = one
    // attempt, so one `false` probe = timeout).
    let releaseA: (ready: boolean) => void = () => {};
    const gateA = new Promise<boolean>((resolve) => {
      releaseA = resolve;
    });
    await openPlanReviewAndGuide(
      pi,
      ctx,
      gating,
      { draft: "# The draft\n" },
      draftReview,
      annotations,
      slot,
      {
        pickFreePort: async () => 45011,
        probe: () => gateA,
        intervalMs: 1,
        budgetMs: 1,
        sleep: async () => {},
      },
    );
    // Review B opens while A is still starting: it re-primes both surfaces for ITS session and
    // comes up immediately.
    await openPlanReviewAndGuide(
      pi,
      ctx,
      gating,
      { draft: "# The draft\n" },
      draftReview,
      annotations,
      slot,
      {
        pickFreePort: async () => 45012,
        probe: async () => true,
        intervalMs: 1,
        budgetMs: 50,
        sleep: async () => {},
      },
    );
    const readyStart = Date.now();
    while (
      !notified.some((n) => n.message.includes("plannotator is up at http://127.0.0.1:45012")) &&
      Date.now() - readyStart < 2000
    ) {
      await new Promise((r) => setTimeout(r, 10));
    }
    assert.ok(
      notified.some((n) => n.message.includes("plannotator is up at http://127.0.0.1:45012")),
      "B announced readiness",
    );

    // A's readiness now times out — AFTER B superseded it. Fenced: no degrade.
    releaseA(false);
    // Give A's observer every chance to (wrongly) fire before asserting it stayed inert.
    for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 5));
    assert.ok(
      !injected.some((m) => m.includes("plan-review browser is unavailable")),
      "A's timeout never injects the degrade notice",
    );
    assert.ok(
      !notified.some((n) => n.message.includes("did not become ready")),
      "A's timeout never reports the error",
    );
    // B's surfaces survive A's timeout: the annotation surface still primed with B's URL, the
    // draft-review context still primed.
    assert.equal(await annotationMode(), "plan", "B's annotation surface is still primed");
    const target = { hasUI: false, ui: undefined } as unknown as Parameters<
      typeof executePushAnnotations
    >[1];
    const seen: string[] = [];
    const fetchLike: FetchLike = async (url) => {
      seen.push(url);
      return { ok: true, status: 201, text: async () => "{}" };
    };
    await executePushAnnotations(
      annotations,
      target,
      {
        angle: "probe",
        findings: [
          {
            phrase: "The draft",
            severity: "minor",
            confidence: "high",
            body: "a finding",
          },
        ],
      },
      { fetchLike },
    );
    assert.ok(
      seen.some((u) => u.startsWith("http://127.0.0.1:45012")),
      `the surface targets B's URL: ${JSON.stringify(seen)}`,
    );
    assert.equal(await draftContextPrimed(), true, "B's draft-review context is still primed");

    // B's approval routes and saves exactly once.
    bus.emit("plannotator:review-result", { reviewId: "r-b", approved: true });
    const saveStart = Date.now();
    while (argvs.length === 0 && Date.now() - saveStart < 4000) {
      await new Promise((r) => setTimeout(r, 10));
    }
    assert.equal(argvs.length, 1, "exactly one save");
    assert.ok(
      notified.some(
        (n) => n.severity === "info" && n.message.includes("plan APPROVED in the browser — saved"),
      ),
      "B's approval saved",
    );
    assert.equal(gating.exits, 1);

    // A's late approval: superseded — ignored loudly, never a second save.
    bus.emit("plannotator:review-result", { reviewId: "r-a", approved: true });
    const lateStart = Date.now();
    while (
      !notified.some((n) => n.message.endsWith(SUPERSEDED_DECISION_WARNING)) &&
      Date.now() - lateStart < 2000
    ) {
      await new Promise((r) => setTimeout(r, 10));
    }
    assert.ok(
      notified.some(
        (n) => n.severity === "warning" && n.message.endsWith(SUPERSEDED_DECISION_WARNING),
      ),
      "A's late decision is ignored loudly",
    );
    assert.ok(
      !notified.some((n) => n.message.includes("after the review degraded")),
      "never the post-degrade arm — A's session was never degraded",
    );
    assert.equal(argvs.length, 1, "still exactly one save");
    assert.equal(process.env.PLANNOTATOR_PORT, undefined, "the env preset was restored");
  });
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
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only", stage: "plan" })];
  const pi = {
    events: bus,
    sendUserMessage(message: string | { type: "text"; text: string }[]) {
      injected.push(typeof message === "string" ? message : message.map((b) => b.text).join("\n"));
    },
    appendEntry(customType: string, data?: unknown) {
      branch.push({ type: "custom", customType, data });
    },
    async exec() {
      throw new Error("no save expected in this test");
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => branch },
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
    seedBrowserReview(pi, ctx, "plan", "# The draft\n"),
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
