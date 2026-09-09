// Tests for the warm `/objective-review-browser` door. The pure `objectiveReviewBrowserGuidance`
// + `observeObjectiveReviewReadiness` are pinned directly (fake pi/ctx slices); the decision
// routing is a COMPOSITION over the real draft-review slot in a real git repo (the
// objectiveSave.test.ts fakeApprovalPi recipe for the approve→save path — the four guards are
// exercised end to end, the git-config incident included); the background open runs over fake
// `StartBrowserDeps` + a fake bus; the command's entry gates / draft resolve / injection run
// against a REAL bound session via the T1 harness, OFFLINE (a fake plannotator extension
// registers the presence-probe command + the plan-review handshake listener).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_DRAFT_ARTIFACT, renderObjectiveDraft } from "../../authoring/objective/draft.ts";
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
  fakePerk,
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
import {
  type ObjectiveReviewDoorSession,
  objectiveReviewBrowserGuidance,
  observeObjectiveReviewReadiness,
  openObjectiveReviewAndGuide,
  openObjectiveReviewSurface,
  routeObjectiveReviewDecision,
} from "./objectiveReviewBrowser.ts";
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

// --------------------------------------------------------------- objectiveReviewBrowserGuidance

test("guidance: names the companion tools + objective semantics, no plan_draft, no URL", () => {
  const text = objectiveReviewBrowserGuidance({});
  assert.match(text, /start_draft_review_wave/, "the fan-out is the launch tool");
  assert.match(text, /collect_draft_review_wave/, "completion rides the collect tool");
  assert.match(text, /push_annotations/, "annotation delivery rides the push tool");
  assert.match(text, /Native-wake relay/, "the objective door relays native batches");
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
  // The objective decision semantics.
  assert.match(text, /objective_draft/, "the revise tool is objective_draft");
  assert.match(text, /Direct Edits are NEVER auto-applied/, "the objective carve-out is pinned");
  assert.match(text, /Do NOT call `plan_review`/, "the mid-review exclusion is pinned");
  assert.match(text, /never save on your own/);
  // The plan-door vocabulary must not leak: no plan_draft, and the objective_save tool name is
  // never dangled (the /objective-save command spelling is the human failsafe, not named here).
  assert.doesNotMatch(text, /\bplan_draft\b/);
  assert.doesNotMatch(text, /\bobjective_save\b/);
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
  const withCustom = objectiveReviewBrowserGuidance({ custom: "check the dependency story" });
  assert.match(withCustom, /custom review lane/i);
  assert.match(withCustom, /check the dependency story/);
  assert.match(withCustom, /do NOT re-encode it/);
  const bare = objectiveReviewBrowserGuidance({});
  assert.doesNotMatch(bare, /custom review lane/i);
  assert.doesNotMatch(bare, /re-encode/);
});

test("guidance: no hardcoded perk-objective-review-browser skill pointer (the binding suffix delivers it)", () => {
  for (const opts of [{}, { custom: "lens" }]) {
    assert.doesNotMatch(
      objectiveReviewBrowserGuidance(opts),
      /Follow the `perk-objective-review-browser` skill/,
    );
  }
});

// ------------------------------------------------------- observeObjectiveReviewReadiness

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
function currentSession(): ObjectiveReviewDoorSession {
  return { degraded: false, current: () => true };
}

async function observe(
  started: StartedSurface<ReviewOutcome>,
  opts?: { idle?: boolean; session?: ObjectiveReviewDoorSession },
): Promise<{
  notifies: { message: string; severity?: string }[];
  sent: { message: string; options?: { deliverAs?: string } }[];
}> {
  const notifies: { message: string; severity?: string }[] = [];
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  await observeObjectiveReviewReadiness(
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
  primeDraftReviewContext(draftReview, { draftType: "objective", draft: "# The objective\n" });
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
  assert.match(sent[0]?.message ?? "", /\/objective-save/, "the objective failsafe is named");
  assert.doesNotMatch(sent[0]?.message ?? "", /\/plan-save/, "never the plan failsafe");
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
  const session: ObjectiveReviewDoorSession = { degraded: false, current: () => false };
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
  const session: ObjectiveReviewDoorSession = { degraded: false, current: () => false };
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

// --------------------------------------------------------------- routeObjectiveReviewDecision

const PROSE = "# Ship retries\n\nThe gateway needs retries.\n";
const ROADMAP = [{ id: "1.1", description: "first" }];
const DRAFT_PAYLOAD = `${JSON.stringify(
  { schema_version: 1, title: "Ship retries", prose: PROSE, roadmap: ROADMAP },
  null,
  2,
)}\n`;

const CREATE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  objective: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  dry_run: false,
});

const FAIL_JSON = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
});

const DE_FEEDBACK = [
  "# Direct Edits",
  "",
  "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:",
  "",
  "```diff",
  "--- objective.md (original)",
  "+++ objective.md (edited)",
  "@@ -1,1 +1,1 @@",
  "-# Ship retries",
  "+# Ship retries (edited)",
  "```",
  "",
  "---",
  "",
  "Also settle the rollout order.",
].join("\n");

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

const RENDERED = renderObjectiveDraft({ title: "Ship retries", prose: PROSE, roadmap: ROADMAP });
const APPROVE_OUT: ReviewOutcome = { status: "completed", approved: true, reviewId: "rev-a" };

/**
 * The decision-routing scaffold: a fake pi (cold door + injections) over a live
 * objective-author branch in a REAL git repo with one `origin` remote (the destination fence
 * needs a verifiable checkout), the structured draft artifact written through the session, and
 * the real slot. `open()` is the door's slot open (raw artifact bytes + the rendered markdown);
 * `rewrite()` is a concurrent `objective_draft` write; `git()` runs git in the cwd.
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
  save: { json: string; code: number };
  open(): OpenDraftReview;
  rewrite(raw: string): void;
  git(...args: string[]): void;
  route(out: ReviewOutcome, review: OpenDraftReview): Promise<void>;
} {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [
    stateEntry({ run_id: "RID", mode: "read-only", stage: "objective-author" }),
  ];
  const argvs: string[][] = [];
  const injected: { message: string; options?: { deliverAs?: string } }[] = [];
  const notified: { message: string; severity?: string }[] = [];
  const save = { json: opts.saveJson ?? CREATE_JSON, code: opts.saveCode ?? 0 };
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
  const slot = seedBrowserReview(pi, ctx, "objective", DRAFT_PAYLOAD);
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
    save,
    open() {
      const opened = slot.open(ctx, {
        subject: "objective",
        source: "artifact",
        raw: DRAFT_PAYLOAD,
        markdown: RENDERED,
      });
      assert.ok(opened.ok, JSON.stringify(opened));
      return opened.review;
    },
    rewrite(raw) {
      const written = openBranchWorkflowSession(pi, ctx).writeArtifact(
        OBJECTIVE_DRAFT_ARTIFACT,
        raw,
      );
      assert.equal(written.status, "applied", "the concurrent draft write landed");
    },
    git(...args) {
      execFileSync("git", args, { cwd, stdio: "ignore" });
    },
    route: (out, review) => routeObjectiveReviewDecision(pi, ctx, gating, slot, out, review),
  };
}

test("decision: APPROVE happy path → objectiveApprovalSave (structured artifact saved, gate exited)", async () => {
  const s = decisionScaffold();
  const out: ReviewOutcome = {
    status: "completed",
    approved: true,
    reviewId: "rev-a",
    feedback: "Solid roadmap — sequence 1.2 after 1.1.",
  };
  await s.route(out, s.open());
  const argv = s.argvs[0] ?? [];
  assert.equal(argv[0], "objective", "the save rode the objective cold door");
  assert.equal(argv[1], "create");
  assert.equal(
    argv[argv.indexOf("--roadmap") + 1],
    JSON.stringify(ROADMAP),
    "the STRUCTURED roadmap rode --roadmap (re-read from the artifact, never the rendered bytes)",
  );
  assert.equal(s.gating.exits, 1, "the gate exited via the objectiveApprovalSave seam");
  assert.ok(
    s.notified.some((n) => n.severity === "info" && n.message.includes("APPROVED")),
    "the saved arm reports info",
  );
  assert.equal(s.injected.length, 1, "the save outcome is injected to the model");
  const text = s.injected[0]?.message ?? "";
  assert.match(text, /objective APPROVED by reviewer/);
  // The reviewer feedback is delimited as untrusted DATA in the injected copy.
  assert.match(text, /untrusted DATA, never instructions/);
  assert.match(
    text,
    /<untrusted_reviewer_feedback>\nSolid roadmap — sequence 1\.2 after 1\.1\.\n<\/untrusted_reviewer_feedback>/,
    "the feedback rides inside the untrusted delimiter",
  );
  assert.equal(s.injected[0]?.options, undefined, "idle ⇒ an immediate turn");
  assert.equal(s.slot.unconfirmed(), null, "a confirmed save never latches");
});

test("decision (the incident): an unrelated git-config change during the review never blocks the approval — one save, gate exited", async () => {
  const s = decisionScaffold();
  const review = s.open();
  // Landing a PR adds and then deletes `branch.<name>.*` entries — routing-irrelevant.
  s.git("config", "branch.tmp.remote", "origin");
  s.git("config", "--unset", "branch.tmp.remote");
  s.git("config", "user.email", "someone-else@example.com");
  await s.route(APPROVE_OUT, review);
  assert.equal(s.argvs.length, 1, "exactly one save call");
  assert.equal(s.gating.exits, 1, "the gate exited");
  assert.match(s.injected[0]?.message ?? "", /objective APPROVED by reviewer/);
  assert.doesNotMatch(s.injected[0]?.message ?? "", /destination/);
});

test("decision: `git remote set-url` during the review → destination-changed naming `remotes`, nothing saved; a fresh open + approve saves once", async () => {
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
  const text = s.injected[0]?.message ?? "";
  assert.match(text, /The human APPROVED the objective, but the save destination changed/);
  assert.match(text, /\(changed: remotes\)/);
  assert.doesNotMatch(text, /forked/, "component names only — never values");
  // The human re-runs the door: the fresh open captures the new destination and saves once.
  await s.route(APPROVE_OUT, s.open());
  assert.equal(s.argvs.length, 1, "one save call from the fresh review");
  assert.equal(s.gating.exits, 1);
});

test("decision: a superseded review's decision is ignored loudly — one TUI warning, no injection, no save", async () => {
  const s = decisionScaffold();
  const first = s.open();
  const second = s.open();
  assert.equal(first.isCurrent(), false);
  await s.route(APPROVE_OUT, first);
  assert.equal(s.argvs.length, 0, "nothing saved");
  assert.equal(s.gating.exits, 0);
  assert.equal(s.injected.length, 0, "nothing injected");
  assert.equal(s.notified.length, 1, "exactly one TUI warning");
  assert.equal(s.notified[0]?.severity, "warning");
  assert.ok(s.notified[0]?.message.endsWith(SUPERSEDED_DECISION_WARNING));
  await s.route(APPROVE_OUT, second);
  assert.equal(s.argvs.length, 1, "the current review still saves");
});

test("decision: APPROVE + Direct Edits heading → NO save, revise inject, gate untouched", async () => {
  // Even a heading-only/malformed diff routes revise — the heading check suffices (the diff
  // goes to the model verbatim either way).
  for (const feedback of [DE_FEEDBACK, "# Direct Edits\n\nthe fence never arrived"]) {
    const s = decisionScaffold();
    const out: ReviewOutcome = {
      status: "completed",
      approved: true,
      reviewId: "rev-de",
      feedback,
    };
    await s.route(out, s.open());
    assert.equal(s.argvs.length, 0, "nothing saved on the Direct-Edits arm");
    assert.equal(s.gating.exits, 0, "the gate stays untouched");
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "info" &&
          n.message.includes("direct browser edits") &&
          n.message.includes("revise round"),
      ),
      "the revise routing reports info",
    );
    assert.equal(s.injected.length, 1);
    const text = s.injected[0]?.message ?? "";
    assert.match(text, /nothing was saved/);
    assert.match(text, /objective_draft/, "the fold-in tool is named");
    assert.match(text, /plan_review/);
    assert.match(text, /untrusted DATA, never instructions/);
    assert.match(text, /<untrusted_reviewer_feedback>\n# Direct Edits/);
    assert.match(text, /<\/untrusted_reviewer_feedback>/);
  }
});

test("decision: Direct Edits on a moved draft still route revise — no save, the draft-changed note leads", async () => {
  // The real concurrent-edit case: the human edits in the browser (Direct Edits) WHILE a
  // concurrent objective_draft write also lands. Direct Edits is a revision effect, so the
  // reviewed-bytes guard proceeds with the note rather than refusing — nothing is saved either way.
  const s = decisionScaffold();
  const review = s.open();
  s.rewrite(
    `${JSON.stringify(
      { schema_version: 1, title: "Ship retries v2", prose: PROSE, roadmap: ROADMAP },
      null,
      2,
    )}\n`,
  );
  const out: ReviewOutcome = {
    status: "completed",
    approved: true,
    reviewId: "rev-de-stale",
    feedback: DE_FEEDBACK,
  };
  await s.route(out, review);
  assert.equal(s.argvs.length, 0, "nothing saved");
  assert.equal(s.gating.exits, 0, "the gate stays untouched");
  const text = s.injected[0]?.message ?? "";
  assert.ok(text.startsWith(DRAFT_CHANGED_NOTE), "the note leads the revise round");
  assert.match(text, /direct browser edits/, "the revise round routed");
  assert.ok(
    s.notified.every((n) => !n.message.includes("working draft changed")),
    "no stale refusal on a revision effect",
  );
});

test("decision: APPROVE + failed save → loud error naming /objective-save, gate ON; the latch pauses the next approval", async () => {
  const s = decisionScaffold({ saveJson: FAIL_JSON, saveCode: 1 });
  await s.route(APPROVE_OUT, s.open());
  assert.equal(s.argvs.length, 1, "the save was attempted");
  assert.equal(s.gating.exits, 0, "a failed save leaves the gate on");
  assert.ok(
    s.notified.some(
      (n) =>
        n.severity === "error" &&
        n.message.includes("auto-save did not confirm") &&
        n.message.includes("/objective-save (the deliberate retry)"),
    ),
    "the failure report names the deliberate retry",
  );
  const text = s.injected[0]?.message ?? "";
  assert.match(text, /auto-save FAILED/);
  assert.match(text, /automatic saves are paused for this session/);
  assert.match(text, /\/objective-save \(the deliberate retry\)/);
  assert.deepEqual(s.slot.unconfirmed(), { subject: "objective", detail: "gh exploded" });
  // The backend recovers; the human re-runs the door and approves: still paused.
  s.save.json = CREATE_JSON;
  s.save.code = 0;
  await s.route(APPROVE_OUT, s.open());
  assert.equal(s.argvs.length, 1, "zero further save calls");
  const paused = s.injected[1]?.message ?? "";
  assert.match(paused, /an earlier save attempt in this session did not confirm \(gh exploded\)/);
  assert.match(paused, /run id RID/);
  assert.match(paused, /\/objective-save \(the deliberate retry\)/);
});

test("decision: APPROVE with CHANGED raw artifact bytes (render-invisible) → stale-approval", async () => {
  const s = decisionScaffold();
  const review = s.open();
  // A concurrent objective_draft write lands while the browser review is open — changing ONLY
  // `base` (render-invisible: the rendered markdown is byte-identical). The guard compares the
  // save-authoritative RAW artifact bytes, so it still refuses.
  s.rewrite(
    `${JSON.stringify(
      { schema_version: 1, title: "Ship retries", base: "release", prose: PROSE, roadmap: ROADMAP },
      null,
      2,
    )}\n`,
  );
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
  assert.match(text, /The human APPROVED the objective, but the working draft changed/);
  assert.match(text, new RegExp(`reviewed digest ${digestSessionData(DRAFT_PAYLOAD)}`));
  assert.match(text, /Nothing was saved/);
});

test("decision: APPROVE with the artifact missing at decision time → stale-approval, no save", async () => {
  const s = decisionScaffold();
  const review = s.open();
  rmSync(join(sessionDataDir(s.cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT));
  await s.route(APPROVE_OUT, review);
  assert.equal(s.argvs.length, 0, "nothing saved");
  assert.equal(s.gating.exits, 0, "the gate stays on");
  assert.ok(
    s.notified.some((n) => n.severity === "error" && n.message.includes("working draft changed")),
    "a missing artifact refuses like a mismatch",
  );
});

test("decision: DENY → delimited feedback + objective_draft redirect (streaming ⇒ followUp), NO save", async () => {
  const s = decisionScaffold({ idle: false });
  const out: ReviewOutcome = {
    status: "completed",
    approved: false,
    reviewId: "rev-d",
    feedback: DE_FEEDBACK,
  };
  await s.route(out, s.open());
  assert.equal(s.argvs.length, 0, "no save on a deny");
  assert.equal(s.gating.exits, 0, "the gate stays on");
  assert.ok(s.notified.some((n) => n.severity === "info" && n.message.includes("DENIED")));
  assert.equal(s.injected.length, 1);
  const text = s.injected[0]?.message ?? "";
  assert.ok(!text.startsWith(DRAFT_CHANGED_NOTE), "no note when the draft held");
  assert.match(text, /The human DENIED the objective in the browser review/);
  assert.match(text, /objective_draft/);
  assert.match(text, /\/objective-review-browser/);
  assert.match(text, /plan_review/);
  assert.match(text, /# Direct Edits/, "the diff reaches the model verbatim (model-mediated)");
  // Verbatim-but-delimited: the untrusted wrapper carries the whole feedback.
  assert.match(text, /untrusted DATA, never instructions/);
  assert.match(text, /<untrusted_reviewer_feedback>\n# Direct Edits/);
  assert.match(text, /<\/untrusted_reviewer_feedback>/);
  assert.deepEqual(s.injected[0]?.options, { deliverAs: "followUp" }, "streaming ⇒ followUp");
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

// ---------------------------------------------- openObjectiveReviewSurface (fake deps + bus)

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
  const branch: unknown[] = [
    stateEntry({ run_id: "RID", mode: "read-only", stage: "objective-author" }),
  ];
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
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: true,
    ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    isIdle: () => true,
    signal: undefined,
  } as unknown as ExtensionContext;

  // probe:false + a tiny budget → the readiness poll times out → the degrade arm fires.
  await openObjectiveReviewAndGuide(
    pi,
    ctx,
    fakeGating(true),
    { rendered: RENDERED, artifactRaw: DRAFT_PAYLOAD },
    draftReview,
    annotations,
    seedBrowserReview(pi, ctx, "objective", DRAFT_PAYLOAD),
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

test("open core: primes BOTH surfaces (plan mode + objective draft type), RETURNS URL-free guidance (nothing sent), clears on settle", async () => {
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
  const branch: unknown[] = [
    stateEntry({ run_id: "RID", mode: "read-only", stage: "objective-author" }),
  ];
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

  const guidance = await openObjectiveReviewSurface(
    pi,
    ctx,
    fakeGating(false),
    { rendered: RENDERED, artifactRaw: DRAFT_PAYLOAD, custom: "check the dependency story" },
    draftReview,
    annotations,
    seedBrowserReview(pi, ctx, "objective", DRAFT_PAYLOAD),
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
  // The primed wave context carries draftType objective + the RENDERED bytes + the custom lane
  // (probed through a spawn-recording adapter whose spawn fails — nothing stays pending).
  const spawns = createMemoryWaveAdapter({ spawnError: "probe only" });
  const target = { hasUI: false, ui: undefined } as unknown as ReportTarget;
  await executeStartDraftReviewWave(draftReview, reportWaveOver(spawns), target, {
    angles: ["grounding", "risk"],
  });
  const script = spawns.calls.spawn[0]?.workflowScript ?? "";
  assert.match(script, /Draft type: objective\./, "the wave reviews the objective draft type");
  assert.ok(
    script.includes(JSON.stringify(RENDERED).slice(1, -1)),
    "the wave reviews the RENDERED bytes",
  );
  assert.match(script, /check the dependency story/, "the custom lane is threaded");
  // The handshake saw the preset port and the EXACT rendered bytes (never the JSON artifact).
  assert.equal(requests.length, 1);
  assert.equal(requests[0]?.portAtEmit, "45001");
  assert.equal(requests[0]?.payload?.planContent, RENDERED);
  assert.match(requests[0]?.payload?.planContent ?? "", /## Roadmap/);
  assert.doesNotMatch(requests[0]?.payload?.planContent ?? "", /schema_version/);
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
    /Follow the `perk-objective-review-browser` skill/,
    "the command:objective-review-browser binding suffix rides the returned guidance",
  );
  assert.match(guidance ?? "", /check the dependency story/);
  assert.doesNotMatch(guidance ?? "", /127\.0\.0\.1|localhost|45001/);
  assert.ok(
    notified.some(
      (n) => n.severity === "info" && n.message.includes("custom lane: check the dependency story"),
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

test("/objective-review-browser: headless → the headless-specific refusal, nothing executed", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "objective-author" },
  });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    headful: false,
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    assert.ok(
      h.registeredCommands().includes("objective-review-browser"),
      "the command is registered",
    );
    // Seed a VALID draft so every later gate would pass — the hasUI gate is then the ONLY
    // refusing gate, and the headless-specific message proves it fired (a fall-through to the
    // no-draft refusal can no longer fake this test green).
    await h.invokeTool("objective_draft", { prose: PROSE, roadmap: ROADMAP });
    const errors: string[] = [];
    const prevError = console.error;
    console.error = (...args: unknown[]) => {
      errors.push(args.map(String).join(" "));
    };
    try {
      await h.runCommandHandler("objective-review-browser", "");
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

test("/objective-review-browser: plannotator absent → the pinned provider-selection refusal, no work", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "objective-author" },
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("objective-review-browser", "");
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

test("/objective-review-browser: wrong/absent stage → the stage-gate refusal, nothing executed", async () => {
  // `objective-refine` rides the same gate: a refinement session never routes an (old, valid)
  // objective draft into the objective browser door.
  for (const stage of ["plan", "objective-refine", undefined]) {
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
      await h.runCommandHandler("objective-review-browser", "");
      assert.ok(
        h.notifies.some((n) => n.includes("only runs inside an objective-authoring session")),
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

test("/objective-review-browser: no working draft → the objective_draft redirect, nothing executed", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("objective-review-browser", "");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("no working objective draft") && n.includes("write it with objective_draft"),
      ),
      "the refusal directs objective_draft",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
    assert.equal(await sessionDraftContextPrimed(h), false, "no context primed");
  } finally {
    h.dispose();
  }
});

test("/objective-review-browser: a SEAM-invalid artifact (pointer, no file) → the classified rewrite refusal, never the absent arm", async () => {
  const cwd = scaffoldRepo();
  const runId = "01RIDGONEOBJ";
  // Plant a session whose workflow state carries a pointer to a file that does NOT exist — the
  // seam's readArtifact classifies `invalid` (corruption), which must NOT be collapsed into the
  // no-draft message: the door surfaces the seam problem + the rewrite redirect.
  const dataDir = sessionDataDir(cwd, runId);
  const file = plantSession(cwd, [
    {
      run_id: runId,
      mode: "read-only",
      stage: "objective-author",
      session_artifacts: {
        [OBJECTIVE_DRAFT_ARTIFACT]: {
          run_id: runId,
          name: OBJECTIVE_DRAFT_ARTIFACT,
          path: join(dataDir, OBJECTIVE_DRAFT_ARTIFACT),
          digest: digestSessionData("never written"),
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
    await h.runCommandHandler("objective-review-browser", "");
    assert.ok(
      h.notifies.some((n) =>
        n.endsWith(
          "the working objective draft is invalid: session artifact objective-draft.json has a " +
            "pointer but no file — rewrite it with objective_draft, then re-run " +
            "/objective-review-browser",
        ),
      ),
      `a seam-invalid artifact refuses with the classified problem, not the absent message (got ${JSON.stringify(h.notifies)})`,
    );
    assert.ok(
      !h.notifies.some((n) => n.includes("no working objective draft")),
      "the absent arm never fires for seam corruption",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/objective-review-browser: an INVALID artifact (malformed JSON) → the rewrite refusal", async () => {
  const cwd = scaffoldRepo();
  const invalid = "not json at all\n";
  const runId = "01RIDBADOBJ";
  // Plant a session whose workflow state carries a VALID pointer to malformed artifact bytes —
  // the seam's readArtifact succeeds (non-blank, digest ok) but decodeObjectiveDraft refuses.
  const dataDir = sessionDataDir(cwd, runId);
  const { mkdirSync } = await import("node:fs");
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(join(dataDir, OBJECTIVE_DRAFT_ARTIFACT), invalid, "utf8");
  const file = plantSession(cwd, [
    {
      run_id: runId,
      mode: "read-only",
      stage: "objective-author",
      session_artifacts: {
        [OBJECTIVE_DRAFT_ARTIFACT]: {
          run_id: runId,
          name: OBJECTIVE_DRAFT_ARTIFACT,
          path: join(dataDir, OBJECTIVE_DRAFT_ARTIFACT),
          digest: digestSessionData(invalid),
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
    await h.runCommandHandler("objective-review-browser", "");
    assert.ok(
      h.notifies.some((n) =>
        n.endsWith(
          "the working objective draft is invalid: objective-draft.json is not valid JSON — " +
            "refusing the draft — rewrite it with objective_draft, then re-run " +
            "/objective-review-browser",
        ),
      ),
      `an invalid artifact refuses with the classified problem + rewrite redirect (got ${JSON.stringify(h.notifies)})`,
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/objective-review-browser: harness APPROVE — the command's artifact read threads the stale guard and the save runs (gate exits)", async () => {
  // The full command→open→decision composition: the command captures the RAW artifact bytes as
  // the stale baseline (mis-threading e.g. the rendered markdown as artifactRaw would make
  // every real approval stale-refuse), the approval passes the guard, objectiveApprovalSave
  // runs through the cold door, and the D1a gate exit lands (mode flips read-write).
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  gitInit(cwd, { dirty: false });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.invokeTool("objective_draft", {
      prose: PROSE,
      title: "Ship retries",
      roadmap: ROADMAP,
    });
    assert.equal(h.workflowState().mode, "read-only", "the session starts gated");
    await h.runCommandHandler("objective-review-browser", "");
    assert.equal(sink.envelopes.length, 1, "the plan-review bridge request was emitted");

    // The human APPROVES (no Direct Edits): the stale guard passes on the live artifact and
    // the objective save runs.
    sink.emitDecision({ reviewId: "r-1", approved: true, feedback: "ship it" });
    const start = Date.now();
    while (
      !injected.some((m) => m.includes("objective APPROVED by reviewer")) &&
      Date.now() - start < 5000
    ) {
      await new Promise((r) => setTimeout(r, 25));
    }
    const approveText = injected.find((m) => m.includes("objective APPROVED by reviewer")) ?? "";
    assert.ok(approveText, "the approve→save outcome was injected");
    assert.doesNotMatch(
      approveText,
      /STALE bytes/,
      "the real artifactRaw threading passed the guard",
    );
    assert.match(approveText, /Saved objective #7/, "the save outcome is relayed");
    // The cold door really ran with the STRUCTURED roadmap re-read from the artifact.
    const argv = readFileSync(argvFile, "utf8").split("\n");
    assert.equal(argv[0], "objective");
    assert.equal(argv[1], "create");
    assert.equal(argv[argv.indexOf("--roadmap") + 1], JSON.stringify(ROADMAP));
    // The save linked the session and the D1a gate exit landed.
    assert.equal(h.workflowState().active_objective, "7", "active_objective linked");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited on the ok save");
    // The settle clears both companion surfaces.
    const settleStart = Date.now();
    while ((await sessionAnnotationMode(h)) !== null && Date.now() - settleStart < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionAnnotationMode(h), null, "the settle clears the annotation surface");
    assert.equal(await sessionDraftContextPrimed(h), false, "…and the draft-review context");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/objective-review-browser: happy path — RENDERED bytes to the bridge, both surfaces primed, decision routes + clears", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
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
    await h.invokeTool("objective_draft", {
      prose: PROSE,
      title: "Ship retries",
      roadmap: ROADMAP,
    });
    await h.runCommandHandler("objective-review-browser", "check the dependency story");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("working objective draft → plannotator browser review") &&
          n.includes("custom lane: check the dependency story"),
      ),
      "the info line names the flow + custom focus",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /start_draft_review_wave/);
    assert.match(text, /check the dependency story/);
    assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
    const marker =
      "Follow the `perk-objective-review-browser` skill (read `.agents/skills/perk-objective-review-browser/SKILL.md`).";
    assert.equal(
      text.split(marker).length - 1,
      1,
      "exactly one command:objective-review-browser pointer",
    );
    // The bridge saw the RENDERED markdown (prose + Delivery line + roadmap table — never the
    // raw JSON artifact) with the preset port.
    assert.equal(sink.envelopes.length, 1, "the plan-review bridge request was emitted");
    assert.equal(sink.envelopes[0]?.action, "plan-review");
    assert.equal(sink.envelopes[0]?.payload.planContent, RENDERED);
    assert.match(sink.envelopes[0]?.payload.planContent ?? "", /\*\*Delivery: incremental\*\*/);
    assert.match(sink.envelopes[0]?.payload.planContent ?? "", /## Roadmap/);
    assert.doesNotMatch(sink.envelopes[0]?.payload.planContent ?? "", /schema_version/);
    assert.match(sink.envAtEmit[0] ?? "", /^\d+$/, "PLANNOTATOR_PORT preset at emit time");
    // Both companion surfaces primed.
    assert.equal(
      await sessionAnnotationMode(h),
      "plan",
      "the annotation surface is primed in plan mode",
    );
    assert.equal(await sessionDraftContextPrimed(h), true, "the draft-review context is primed");

    // The human DENIES: the feedback injects a revision turn and both surfaces clear.
    sink.emitDecision({ reviewId: "r-1", approved: false, feedback: "tighten node 1.1" });
    const start = Date.now();
    while ((await sessionAnnotationMode(h)) !== null && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionAnnotationMode(h), null, "the settle clears the annotation surface");
    assert.equal(await sessionDraftContextPrimed(h), false, "…and the draft-review context");
    assert.ok(
      injected.some((m) => m.includes("DENIED") && m.includes("tighten node 1.1")),
      "the deny feedback injected verbatim",
    );
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});
