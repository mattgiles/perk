// The two-session isolation regression suite (the shared-state defect this node deletes): two
// REAL bound sessions in ONE process, each with its own fake pi-subagents responder, must share
// NO pending-wave or draft-review-context state — a launch in session B while session A's wave
// is pending must not cross-refuse `wave_active` or clobber A's slot, and each session's collect
// must drain ITS OWN aggregate. The draft pair additionally proves CONTEXT isolation: session A
// primed with a plan draft and session B with an objective draft each spawn a wave carrying
// their own primed bytes. (Pre-fix, both pairs kept module-global slots — the second session's
// launch refused or erased the first's.)

import assert from "node:assert/strict";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runScratchDir } from "../../substrate/cache.ts";
import {
  createFakeSubagents,
  type FakeSubagents,
  waveScriptItems,
} from "../../testing/fakeSubagents.ts";
import {
  fakePerk,
  fakePerkRouter,
  loadPerkSession,
  type PerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../testing/harness.ts";
import {
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
  primeAnnotationSurface,
} from "./providers/annotations.ts";

/** The shared fake in dynamic mode, watermarking every report with the session's marker. */
function markedFake(marker: string): FakeSubagents {
  return createFakeSubagents([
    {
      executeScript: async (script) =>
        waveScriptItems(script).map(({ key }) => ({
          key,
          ok: true,
          error: null,
          report: { angle: key, summary: marker, findings: [], fyi: [], streamed: false },
        })),
    },
  ]);
}

function installPonytailSkill(cwd: string, skillName: string): void {
  const root = join(cwd, ".pi", "npm", "node_modules", "@dietrichgebert", "ponytail");
  const skillDir = join(root, "skills", skillName);
  mkdirSync(skillDir, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "@dietrichgebert/ponytail", pi: { skills: ["./skills"] } }),
    "utf8",
  );
  writeFileSync(join(skillDir, "SKILL.md"), `---\nname: ${skillName}\n---\n`, "utf8");
}

test("two sessions share no review-wave pending state (launch/collect isolate per session)", async () => {
  const openSession = async (marker: string): Promise<{ h: PerkSession; fake: FakeSubagents }> => {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
    installPonytailSkill(cwd, "ponytail-review");
    const fake = markedFake(marker);
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID" },
      extraExtensions: [fake.extension],
    });
    return { h, fake };
  };
  const a = await openSession("session A sound");
  const b = await openSession("session B sound");
  try {
    const startA = await a.h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt-a",
    });
    assert.equal((startA.details as { ok: boolean }).ok, true);

    // Session B launches WHILE A's wave is pending: no wave_active cross-refusal, no clobber.
    const startB = await b.h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "quality"],
      pr: 7,
      worktree: "/abs/wt-b",
    });
    assert.equal(
      (startB.details as { ok: boolean }).ok,
      true,
      "B's launch must not see A's pending wave",
    );
    assert.equal(a.fake.spawns.length, 1, "A's responder saw exactly A's spawn");
    assert.equal(b.fake.spawns.length, 1, "B's responder saw exactly B's spawn");

    // Each collect drains its OWN aggregate (the watermark proves no cross-drain).
    const collectedA = await a.h.invokeTool("collect_review_wave", {});
    const detailsA = collectedA.details as {
      ok: boolean;
      covered?: string[];
      reports?: { report: { summary?: string } }[];
    };
    assert.equal(detailsA.ok, true);
    assert.deepEqual(detailsA.covered, ["claimed-intent", "tests", "ponytail"]);
    assert.equal(detailsA.reports?.[0]?.report.summary, "session A sound");

    const collectedB = await b.h.invokeTool("collect_review_wave", {});
    const detailsB = collectedB.details as {
      ok: boolean;
      covered?: string[];
      reports?: { report: { summary?: string } }[];
    };
    assert.equal(detailsB.ok, true);
    assert.deepEqual(detailsB.covered, ["claimed-intent", "quality", "ponytail"]);
    assert.equal(detailsB.reports?.[0]?.report.summary, "session B sound");

    // Drain-once stays per-session: both slots are now empty.
    for (const h of [a.h, b.h]) {
      const drained = await h.invokeTool("collect_review_wave", {});
      assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
    }
  } finally {
    a.h.dispose();
    b.h.dispose();
  }
});

// --- the draft pair: pending-state AND primed-context isolation -------------------------------

/** The minimal fake plannotator peer the browser doors need to prime a session's context. */
interface FakePlannotatorSink {
  emitDecision: (decision: Record<string, unknown>) => void;
}

function fakePlannotator(sink: FakePlannotatorSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    sink.emitDecision = (decision) => pi.events.emit("plannotator:review-result", decision);
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      const envelope = data as { respond: (r: unknown) => void };
      envelope.respond({ status: "handled", result: { status: "pending", reviewId: "r-1" } });
    });
  };
}

/**
 * Settle ONE session's bridge (DENY) and wait for both of its background tasks to end: the
 * decision task (its own completion signal — the injected deny turn) and the readiness poll
 * (its exit is observable as the `PLANNOTATOR_PORT` restore — `expectedPort` names the value
 * the poll's `finally` puts back). The two concurrent doors NEST their save/restore of that
 * process-global (B saved A's port as its prior value), so the caller settles in REVERSE open
 * order — B first (restores A's port), then A (restores absence) — leaving the env clean and
 * provably no poll still running at dispose.
 */
async function settleDoor(
  sink: FakePlannotatorSink,
  injected: string[],
  expectedPort: string | undefined,
): Promise<void> {
  sink.emitDecision({ reviewId: "r-1", approved: false, feedback: "settle" });
  const start = Date.now();
  const done = (): boolean =>
    injected.some((m) => m.includes("DENIED")) && process.env.PLANNOTATOR_PORT === expectedPort;
  while (!done()) {
    if (Date.now() - start > 5000) break; // bounded — never hang a test on cleanup
    await new Promise((r) => setTimeout(r, 25));
  }
  assert.ok(done(), "the door's decision task and readiness poll both ended");
}

const PLAN_DRAFT = "# The session-A plan draft\n\nStep one.\n";
const OBJECTIVE_PROSE = "# Ship retries\n\nThe gateway needs retries.\n";

test("two sessions share no draft-review context: each wave receives its own primed bytes", async () => {
  // Session A: a PLAN draft primed through the real /plan-review-browser door.
  const cwdA = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  installPonytailSkill(cwdA, "ponytail");
  const fakeA = markedFake("draft A");
  const sinkA: FakePlannotatorSink = { emitDecision: () => {} };
  const hA = await loadPerkSession({
    cwd: cwdA,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sinkA), fakeA.extension],
  });
  // Session B: an OBJECTIVE draft primed through the real /objective-review-browser door.
  const cwdB = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  installPonytailSkill(cwdB, "ponytail");
  const fakeB = markedFake("draft B");
  const sinkB: FakePlannotatorSink = { emitDecision: () => {} };
  const hB = await loadPerkSession({
    cwd: cwdB,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sinkB), fakeB.extension],
  });
  const injectedA = spyInjections(hA);
  const injectedB = spyInjections(hB);
  const priorPort = process.env.PLANNOTATOR_PORT;
  let portA: string | undefined;
  try {
    await hA.invokeTool("plan_draft", { plan: PLAN_DRAFT });
    await hA.runCommandHandler("plan-review-browser", "");
    portA = process.env.PLANNOTATOR_PORT; // A's preset — the prior value B's poll will restore
    await hB.invokeTool("objective_draft", {
      prose: OBJECTIVE_PROSE,
      title: "Ship retries",
      roadmap: [{ id: "1.1", description: "first" }],
    });
    await hB.runCommandHandler("objective-review-browser", "");

    // Both sessions launch: no cross-refusal, and EACH wave carries its own primed bytes.
    const startA = await hA.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "risk"],
    });
    assert.equal((startA.details as { ok: boolean }).ok, true);
    const startB = await hB.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "scope"],
    });
    assert.equal(
      (startB.details as { ok: boolean }).ok,
      true,
      "B's launch must not see A's pending wave or context",
    );
    assert.equal(fakeA.spawns.length, 1);
    assert.equal(fakeB.spawns.length, 1);
    const scriptA = String(fakeA.spawns[0]?.workflowScript ?? "");
    const scriptB = String(fakeB.spawns[0]?.workflowScript ?? "");
    assert.match(scriptA, /Draft type: plan\./);
    assert.match(scriptA, /# The session-A plan draft/);
    assert.doesNotMatch(scriptA, /Ship retries/, "A's wave never sees B's primed bytes");
    assert.match(scriptB, /Draft type: objective\./);
    assert.match(scriptB, /Ship retries/);
    assert.doesNotMatch(scriptB, /session-A plan draft/, "B's wave never sees A's primed bytes");

    // Each collect drains its own aggregate.
    const collectedA = await hA.invokeTool("collect_draft_review_wave", {});
    assert.equal(
      (collectedA.details as { reports?: { report: { summary?: string } }[] }).reports?.[0]?.report
        .summary,
      "draft A",
    );
    const collectedB = await hB.invokeTool("collect_draft_review_wave", {});
    assert.equal(
      (collectedB.details as { reports?: { report: { summary?: string } }[] }).reports?.[0]?.report
        .summary,
      "draft B",
    );
  } finally {
    // Reverse open order: B's poll restores A's port, then A's restores the original absence.
    await settleDoor(sinkB, injectedB, portA);
    await settleDoor(sinkA, injectedA, priorPort);
    // Belt-and-braces: the polls' restores are verified above; put back the pre-test value even
    // if a bounded wait broke out early.
    if (priorPort === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = priorPort;
    hA.dispose();
    hB.dispose();
  }
});

// --- the automated review pass: per-activation post-state isolation ---------------------------

/** The shared fake in dynamic mode answering pr-review lanes with schema-valid clean reports. */
function prReviewFake(): FakeSubagents {
  return createFakeSubagents([
    {
      executeScript: async (script) =>
        waveScriptItems(script).map(({ key }) => ({
          key,
          ok: true,
          error: null,
          report: { angle: key, verdict: "clean", findings: [], fyi: [] },
        })),
    },
  ]);
}

function prUrlJson(pr: number): Record<string, unknown> {
  return {
    success: true,
    error_type: null,
    message: null,
    branch: `plan-${pr}`,
    pr: { number: pr, url: `https://github.test/o/r/pull/${pr}`, base_ref: "main" },
  };
}

// PERK_BIN is process-global (the harness applies env to process.env), so BOTH sessions share
// ONE fake router — the isolation proof rides the per-session angle manifests, not the PR.
const SHARED_PR = 42;

function cleanPostJson(pr: number): Record<string, unknown> {
  return {
    success: true,
    error_type: null,
    message: null,
    dry_run: false,
    pr,
    mode: "reaction",
    verdict: "clean",
    fyi: [],
    next_command: "/land",
    comment_count: 0,
  };
}

function latestReviewBatch(cwd: string): Record<string, unknown> {
  const dir = runScratchDir(cwd, "01RID");
  const files = readdirSync(dir)
    .filter((name) => name.startsWith("review-post-") && name.endsWith(".json"))
    .sort();
  const latest = files.at(-1);
  assert.ok(latest, "review-post staged a cold-door batch");
  return JSON.parse(readFileSync(join(dir, latest), "utf8")) as Record<string, unknown>;
}

test("two sessions share no review-pass state (record/post/consume isolate per activation)", async () => {
  // ONE router serves both sessions (PERK_BIN is process-global); the isolation proof is the
  // per-session recorded MANIFESTS and the per-session single-use consume.
  const routerCwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerkRouter(routerCwd, {
    "pr url": { json: prUrlJson(SHARED_PR) },
    "pr review-post": { json: cleanPostJson(SHARED_PR) },
  });
  const openSession = async (): Promise<{ h: PerkSession; cwd: string; fake: FakeSubagents }> => {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
    installPonytailSkill(cwd, "ponytail-review");
    const fake = prReviewFake();
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
      extraExtensions: [fake.extension],
    });
    return { h, cwd, fake };
  };
  const a = await openSession();
  const b = await openSession();
  try {
    // A records a wave; B records ITS OWN wave — pre-fix the module-global slot meant B's
    // record clobbered A's (A's later post would record B's manifests).
    const waveA = await a.h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "tests"],
    });
    assert.equal((waveA.details as { ok: boolean }).ok, true);
    const waveB = await b.h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "quality"],
    });
    assert.equal((waveB.details as { ok: boolean }).ok, true);

    // A's post records A's manifests (unclobbered by B's later wave).
    const postA = await a.h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal((postA.details as { ok: boolean }).ok, true);
    assert.equal(latestReviewBatch(a.cwd).expected_pr, SHARED_PR);
    const recordA = a.h.workflowState().last_pr_review as { pr?: number; angles?: string[] };
    assert.equal(recordA.pr, SHARED_PR);
    assert.deepEqual(recordA.angles, ["plan-fidelity", "tests", "ponytail"]);

    // A's consume never consumes B's recorded outcome: B's post still lands with B's manifests.
    const postB = await b.h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal(
      (postB.details as { ok: boolean }).ok,
      true,
      "A's consumed state must not refuse B's post",
    );
    assert.equal(latestReviewBatch(b.cwd).expected_pr, SHARED_PR);
    const recordB = b.h.workflowState().last_pr_review as { pr?: number; angles?: string[] };
    assert.equal(recordB.pr, SHARED_PR);
    assert.deepEqual(recordB.angles, ["plan-fidelity", "quality", "ponytail"]);

    // Single-use stays per-session: each session's duplicate refuses on ITS OWN consumed state.
    for (const h of [a.h, b.h]) {
      const duplicate = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "dup" });
      assert.equal(
        (duplicate.details as { error_type?: string }).error_type,
        "review_wave_consumed",
      );
    }
  } finally {
    a.h.dispose();
    b.h.dispose();
  }
});

// --- the annotation push: per-activation surface/ledger isolation ------------------------------

/** The minimal fake plannotator peer the PR browser door needs (the code-review bridge). */
interface FakeBrowserSink {
  envelopes: { respond: (r: unknown) => void }[];
}

function fakeCodeReviewPlannotator(sink: FakeBrowserSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      sink.envelopes.push(data as { respond: (r: unknown) => void });
    });
  };
}

/** Probe a SESSION's annotation state through its registered tool (no fetch on a pure probe). */
async function sessionSurfacePrimed(h: PerkSession): Promise<boolean> {
  const result = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
  return (result.details as { ok: boolean }).ok;
}

test("two sessions share no annotation-push state (prime/clear isolate per activation)", async () => {
  const checkoutJson = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    path: "/wt/review-77",
    pr: 77,
    url: "https://github.com/o/r/pull/77",
    head_sha: "aaaabbbbccccddddeeeeffff0000111122223333",
    base_sha: "0123456789abcdef0123456789abcdef01234567",
    base_ref: "main",
  });
  const cwdA = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const binA = fakePerk(cwdA, { stdout: checkoutJson });
  const sinkA: FakeBrowserSink = { envelopes: [] };
  const hA = await loadPerkSession({
    cwd: cwdA,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: binA },
    extraExtensions: [fakeCodeReviewPlannotator(sinkA)],
  });
  const cwdB = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const hB = await loadPerkSession({ cwd: cwdB, env: { PERK_RUN_ID: "01RID" } });
  const priorPort = process.env.PLANNOTATOR_PORT;
  try {
    // A opens the PR browser door (foreign arm) — priming A's surface, and ONLY A's.
    await hA.runCommandHandler("pr-review-browser", "77");
    assert.equal(await sessionSurfacePrimed(hA), true, "A's open primed A's surface");
    assert.equal(
      await sessionSurfacePrimed(hB),
      false,
      "B never sees A's primed surface (pre-fix the module-global surface leaked across)",
    );
    // A's bridge settle clears A's surface — and never touches B's unprimed refusal.
    for (const envelope of sinkA.envelopes) {
      envelope.respond({ status: "handled", result: { approved: true } });
    }
    const start = Date.now();
    while ((await sessionSurfacePrimed(hA)) && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionSurfacePrimed(hA), false, "the settle cleared A's surface");
  } finally {
    if (priorPort === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = priorPort;
    hA.dispose();
    hB.dispose();
  }
});

// --- the annotation push: per-activation LEDGER/HELD/ALTERNATES isolation (behavioral) ---------

/** A minimal scriptable endpoint (the annotations.test.ts fakeEndpoint shape, sized to here). */
function annotationEndpoint(): {
  fetchLike: FetchLike;
  posts: { source: string; count: number }[];
  setDown(down: boolean): void;
} {
  const posts: { source: string; count: number }[] = [];
  let down = false;
  let seq = 0;
  const fetchLike: FetchLike = async (_url, init) => {
    if (down) throw new Error("connect ECONNREFUSED 127.0.0.1");
    if (init.method === "DELETE") {
      return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, removed: 1 }) };
    }
    const batch = JSON.parse(init.body ?? "{}") as { annotations: { source?: string }[] };
    posts.push({ source: batch.annotations[0]?.source ?? "", count: batch.annotations.length });
    const ids = batch.annotations.map(() => `id-${++seq}`);
    return { ok: true, status: 201, text: async () => JSON.stringify({ ids }) };
  };
  return {
    fetchLike,
    posts,
    setDown(next: boolean) {
      down = next;
    },
  };
}

/** A quiet ReportTarget (the endpoint outcomes are asserted through details, not notifies). */
const QUIET_TARGET = { hasUI: false, ui: { notify() {} } };

interface PushDetails {
  ok: boolean;
  pushed?: number;
  skipped?: string[];
  held?: number;
  held_batches?: number;
}

test("two activations share no annotation ledger/held/alternates state (behavioral)", async () => {
  // Two per-activation states over their own endpoints — a regression that moved only the
  // surface into AnnotationState (leaving the dedupe ledger, the held queue, or the retained
  // alternates module-global) passes the prime/clear probe test above but fails here.
  const s1 = createAnnotationState();
  const s2 = createAnnotationState();
  const e1 = annotationEndpoint();
  const e2 = annotationEndpoint();
  primeAnnotationSurface(s1, { mode: "review", url: "http://127.0.0.1:7771" });
  primeAnnotationSurface(s2, { mode: "review", url: "http://127.0.0.1:7772" });
  const finding = {
    path: "src/a.ts",
    line: 3,
    severity: "major",
    confidence: "high",
    body: "off-by-one",
  };
  const push = (
    state: ReturnType<typeof createAnnotationState>,
    endpoint: ReturnType<typeof annotationEndpoint>,
    params: unknown,
  ) => executePushAnnotations(state, QUIET_TARGET, params, { fetchLike: endpoint.fetchLike });

  // LEDGER isolation: the same anchor posts in BOTH activations (a shared ledger would skip
  // the second); the within-activation re-push is the skip (the contrast pin).
  const first = await push(s1, e1, { angle: "tests", findings: [finding] });
  assert.equal((first.details as PushDetails).pushed, 1);
  const other = await push(s2, e2, { angle: "tests", findings: [finding] });
  assert.equal((other.details as PushDetails).pushed, 1, "s2's ledger never saw s1's anchor");
  assert.deepEqual((other.details as PushDetails).skipped, []);
  const repeat = await push(s1, e1, { angle: "tests", findings: [finding] });
  assert.equal((repeat.details as PushDetails).pushed, 0);
  assert.equal((repeat.details as PushDetails).skipped?.length, 1, "s1's own dedupe still holds");

  // ALTERNATES isolation: both activations retain a cross-source duplicate (perk:tests owns
  // the anchor in each ledger); s1's release promotes ONLY s1's retained alternate — s2's
  // stays retained (a shared alternates map would have been drained by s1's release).
  const dupe = await push(s1, e1, { angle: "quality", findings: [finding], replace: true });
  assert.equal((dupe.details as PushDetails).skipped?.length, 1, "s1 retains the alternate");
  const s2Dupe = await push(s2, e2, { angle: "quality", findings: [finding], replace: true });
  assert.equal((s2Dupe.details as PushDetails).skipped?.length, 1, "s2 retains ITS OWN alternate");
  const release = await push(s1, e1, { angle: "tests", findings: [], replace: true });
  assert.equal((release.details as PushDetails).ok, true);
  assert.equal((release.details as PushDetails).pushed, 1, "s1's release promoted s1's alternate");
  assert.ok(
    e1.posts.some((p) => p.source === "perk:quality" && p.count === 1),
    "the promoted alternate posts under its own angle in s1",
  );
  assert.equal(s1.alternates.size, 0, "s1's promotion consumed s1's candidate");
  assert.equal(
    s2.alternates.size,
    1,
    "s2 retains ITS OWN alternate — s1's release never drains it",
  );

  // HELD-QUEUE isolation: s1's unreachable endpoint holds its batch; the same anchor still
  // posts through s2 (a shared held queue would veto it or flush s1's batch through e2), and
  // s2's successful call drains nothing of s1's queue.
  const heldFinding = { ...finding, path: "src/b.ts" };
  e1.setDown(true);
  const held = await push(s1, e1, { angle: "quality", findings: [heldFinding] });
  assert.equal((held.details as PushDetails).held, 1);
  assert.equal((held.details as PushDetails).held_batches, 1);
  const unaffected = await push(s2, e2, { angle: "quality", findings: [heldFinding] });
  assert.equal((unaffected.details as PushDetails).pushed, 1, "s2 never carries s1's held work");
  assert.equal((unaffected.details as PushDetails).held, 0);
  assert.equal(s1.held.length, 1, "s2's flush drained nothing of s1's queue");
});
