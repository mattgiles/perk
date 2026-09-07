// Tests for the review-wave tool pair (registered live in `extension/index.ts`). The strict
// decoder is pinned directly; the start/collect execute cores are driven through the injected
// in-memory adapter (the `runLearnAnalystWave` test posture — no session needed); registration +
// the real tool-boundary threading (config model → spawn, decode refusal, launch → collect
// round-trip) run against a REAL bound session via the T1 harness (the harness binds perk's
// extension, so the pair is present) with a fake pi-subagents RPC responder on pi.events.
// Offline like everything here.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PERK_TOOLS, STAGE_TOOLS } from "../../../substrate/toolGating.ts";
import {
  createFakeSubagents,
  type FakeSubagents,
  waveScriptItems,
} from "../../../testing/fakeSubagents.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../../../testing/harness.ts";
import { createMemoryWaveAdapter } from "../../../testing/memoryAdapter.ts";
import type { AdversarialReviewAngle } from "../../../waves/adversarialReviewWave.ts";
import { reportWaveOver } from "../../../waves/reportWave.ts";
import {
  createAnnotationState,
  executePushAnnotations,
  primeAnnotationSurface,
  type ReviewFinding,
} from "../providers/annotations.ts";
import {
  decodeStartReviewWaveParams,
  executeCollectReviewWave,
  executeStartReviewWave as executeStartReviewWaveBase,
  installReviewWaveBindings,
  type ReviewWaveState,
} from "./reviewWave.ts";

const TWO_ANGLES: AdversarialReviewAngle[] = ["claimed-intent", "correctness"];
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const executeStartReviewWave = (...args: Parameters<typeof executeStartReviewWaveBase>) =>
  executeStartReviewWaveBase(args[0], args[1], args[2], {
    ...args[3],
    requiredSkillPreflight: PREFLIGHT_OK,
  });

/** A fresh per-test pending-ref slot (what a registration owns in its closure). */
function freshState(): ReviewWaveState {
  return { pending: null };
}

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string): unknown {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, summary: "solid", findings: [], fyi: [], streamed: false },
  };
}

/** A minimal `ReportTarget` capturing notifies (severity-aware). */
function fakeTarget(): {
  target: { hasUI: boolean; ui: { notify(message: string, type?: string): void } };
  notified: { message: string; severity?: string }[];
} {
  const notified: { message: string; severity?: string }[] = [];
  return {
    target: {
      hasUI: true,
      ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    },
    notified,
  };
}

/** The captured tool-def slice the fake pi records (guidelines + mode + the loose execute). */
interface CapturedTool {
  description?: string;
  promptGuidelines?: string[];
  executionMode?: string;
  execute: (
    toolCallId: string,
    params: unknown,
    signal: undefined,
    onUpdate: undefined,
    ctx: unknown,
  ) => Promise<unknown>;
}

/** A captured-`registerTool` fake pi (the module never touches anything else at register time). */
function fakePi(): {
  pi: ExtensionAPI;
  tools: Map<string, CapturedTool>;
} {
  const tools = new Map<string, CapturedTool>();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
    events: {
      emit() {},
      on() {
        return () => {};
      },
    },
  } as unknown as ExtensionAPI;
  return { pi, tools };
}

const START_OPTS = { angles: TWO_ANGLES, pr: 42, worktree: "/abs/wt" };

for (const hasUI of [true, false]) {
  test(`collect disclosure preserves coverage and lane order (hasUI=${hasUI})`, async (t) => {
    const finding = {
      path: "a.ts",
      line: 1,
      severity: "major",
      confidence: "high",
      body: "defect",
    };
    const entries = [
      {
        key: "claimed-intent",
        ok: true,
        error: null,
        report: {
          angle: "claimed-intent",
          summary: "partial delivery",
          findings: [finding],
          fyi: ["A later supervisor call failed"],
          streamed: true,
        },
      },
      {
        key: "correctness",
        ok: true,
        error: null,
        report: {
          angle: "correctness",
          summary: "no defects",
          findings: [],
          fyi: [],
          streamed: false,
        },
      },
      { key: "tests", ok: false, error: "lane exploded", report: null },
      {
        key: "ponytail",
        ok: true,
        error: null,
        report: {
          angle: "ponytail",
          summary: "completion only",
          findings: [finding],
          fyi: ["contact_supervisor absent"],
          streamed: false,
        },
      },
    ];
    const adapter = createMemoryWaveAdapter({ aggregate: { state: "complete", value: entries } });
    const wave = reportWaveOver(adapter);
    const state = freshState();
    const { target, notified } = fakeTarget();
    target.hasUI = hasUI;
    const stderr: unknown[][] = [];
    t.mock.method(console, "error", (...args: unknown[]) => stderr.push(args));
    await executeStartReviewWave(state, wave, target, {
      ...START_OPTS,
      angles: ["claimed-intent", "correctness", "tests"],
    });
    const collected = await executeCollectReviewWave(state, wave, target);
    assert.equal(collected.details.ok, true);
    if (!collected.details.ok) return;
    assert.equal(collected.details.complete, false);
    assert.deepEqual(collected.details.covered, ["claimed-intent", "correctness", "ponytail"]);
    assert.deepEqual(
      collected.details.reports.map((r) => r.report),
      entries.filter((e) => e.ok).map((e) => e.report),
    );
    assert.deepEqual(collected.details.failures, [
      { key: "tests", reason: "lane-failed", detail: "lane exploded" },
    ]);
    assert.equal(collected.details.attempts.length, 1);
    assert.equal(adapter.calls.spawn.length, 1);
    const text = collected.content[0]?.text ?? "";
    assert.match(text, /no provisional batches \(no findings\): correctness/);
    assert.match(text, /completion-only findings; no provisional batches: ponytail/);
    assert.match(text, /A later supervisor call failed/);
    assert.match(text, /contact_supervisor absent/);
    if (hasUI) {
      assert.ok(
        notified.some(
          (n) => n.severity === "info" && n.message.includes("no findings): correctness"),
        ),
      );
      assert.ok(
        notified.some(
          (n) => n.severity === "warning" && n.message.includes("no provisional batches: ponytail"),
        ),
      );
    } else {
      assert.equal(notified.length, 0);
      assert.match(JSON.stringify(stderr), /no findings\): correctness/);
      assert.match(JSON.stringify(stderr), /no provisional batches: ponytail/);
    }
  });
}

// --- decodeStartReviewWaveParams: strict whole-refusal decode --------------------------------

test("decodeStartReviewWaveParams accepts valid 2- and 3-angle selections (+ trimmed directive)", () => {
  assert.deepEqual(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt",
    }),
    { angles: ["claimed-intent", "tests"], pr: 42, worktree: "/abs/wt" },
  );
  assert.deepEqual(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "correctness", "quality"],
      pr: 7,
      worktree: "/abs/wt",
      directive: "  focus on the CI edits  ",
    }),
    {
      angles: ["claimed-intent", "correctness", "quality"],
      pr: 7,
      worktree: "/abs/wt",
      directive: "focus on the CI edits",
    },
  );
});

test("decodeStartReviewWaveParams: stack is an optional boolean — anything else refuses whole", () => {
  assert.deepEqual(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt",
      stack: true,
    }),
    { angles: ["claimed-intent", "tests"], pr: 42, worktree: "/abs/wt", stack: true },
  );
  assert.deepEqual(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt",
      stack: false,
    }),
    { angles: ["claimed-intent", "tests"], pr: 42, worktree: "/abs/wt", stack: false },
  );
  // A mistyped stack refuses the WHOLE call — never a silent single-PR downgrade.
  assert.equal(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt",
      stack: "true",
    }),
    null,
  );
});

test("decodeStartReviewWaveParams refuses out-of-bounds angle selections (whole refusal)", () => {
  assert.equal(decodeStartReviewWaveParams({ pr: 1, worktree: "/wt" }), null); // missing
  assert.equal(
    decodeStartReviewWaveParams({ angles: ["claimed-intent"], pr: 1, worktree: "/wt" }),
    null,
  ); // 1 angle
  assert.equal(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "correctness", "tests", "quality"],
      pr: 1,
      worktree: "/wt",
    }),
    null,
  ); // 4 angles
  assert.equal(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "claimed-intent"],
      pr: 1,
      worktree: "/wt",
    }),
    null,
  ); // duplicate
  assert.equal(
    decodeStartReviewWaveParams({
      angles: ["claimed-intent", "plan-fidelity"],
      pr: 1,
      worktree: "/wt",
    }),
    null,
  ); // unknown slug (the pr-review vocabulary is a different flow)
  assert.equal(
    decodeStartReviewWaveParams({ angles: ["correctness", "tests"], pr: 1, worktree: "/wt" }),
    null,
  ); // no claimed-intent
  assert.equal(
    decodeStartReviewWaveParams({ angles: "claimed-intent,tests", pr: 1, worktree: "/wt" }),
    null,
  ); // not an array
});

test("decodeStartReviewWaveParams refuses a missing/non-positive-integer pr", () => {
  const base = { angles: ["claimed-intent", "tests"], worktree: "/wt" };
  assert.equal(decodeStartReviewWaveParams(base), null); // missing
  assert.equal(decodeStartReviewWaveParams({ ...base, pr: 1.5 }), null); // non-integer
  assert.equal(decodeStartReviewWaveParams({ ...base, pr: 0 }), null); // zero
  assert.equal(decodeStartReviewWaveParams({ ...base, pr: -3 }), null); // negative
  assert.equal(decodeStartReviewWaveParams({ ...base, pr: "42" }), null); // string
});

test("decodeStartReviewWaveParams refuses a missing/empty worktree and a blank directive", () => {
  const base = { angles: ["claimed-intent", "tests"], pr: 42 };
  assert.equal(decodeStartReviewWaveParams(base), null); // missing worktree
  assert.equal(decodeStartReviewWaveParams({ ...base, worktree: "" }), null); // empty
  assert.equal(decodeStartReviewWaveParams({ ...base, worktree: 7 }), null); // mistyped
  assert.equal(decodeStartReviewWaveParams({ ...base, worktree: "/wt", directive: 7 }), null);
  assert.equal(decodeStartReviewWaveParams({ ...base, worktree: "/wt", directive: "" }), null);
  // Whitespace-only would ride every lane as a dangling, contentless operator-focus suffix.
  assert.equal(decodeStartReviewWaveParams({ ...base, worktree: "/wt", directive: "   " }), null);
  assert.equal(decodeStartReviewWaveParams("not an object"), null);
});

// --- the execute cores over the injected memory adapter --------------------------------------

test("executeStartReviewWave: happy path stores the pending wave and returns the run handle", async () => {
  const state = freshState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const result = await executeStartReviewWave(state, wave, target, START_OPTS);
  assert.equal(result.details.ok, true);
  const details = result.details as {
    asyncId?: string;
    asyncDir?: string;
    launch?: { requested: string[]; runnable: string[]; preflightFailures: unknown[] };
  };
  assert.equal(details.asyncId, "wave-async-1");
  assert.equal(details.asyncDir, "/memory/wave-async-1");
  assert.deepEqual(details.launch, {
    requested: ["claimed-intent", "correctness", "ponytail"],
    runnable: ["claimed-intent", "correctness", "ponytail"],
    preflightFailures: [],
  });
  const text = result.content[0]?.text ?? "";
  assert.match(text, /claimed-intent, correctness/);
  assert.match(text, /end the turn/);
  assert.match(text, /matching native workflow-completion notice/);
  assert.match(text, /collect_review_wave/);

  // The pending ref is stored: a second start refuses with wave_active…
  const second = await executeStartReviewWave(state, wave, target, START_OPTS);
  assert.equal(second.details.ok, false);
  assert.equal((second.details as { error_type?: string }).error_type, "wave_active");
  assert.match(second.content[0]?.text ?? "", /collect_review_wave first/);

  // …and collect drains it (clearing pending — a following collect is no_wave).
  const collected = await executeCollectReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true);
  const drained = await executeCollectReviewWave(state, wave, target);
  assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
});

test("executeStartReviewWave: a launch failure soft-fails with the wave reason and the attempt receipt", async () => {
  const state = freshState();
  const { target, notified } = fakeTarget();
  const unavailable = await executeStartReviewWave(
    state,
    reportWaveOver(createMemoryWaveAdapter({ ping: null })),
    target,
    START_OPTS,
  );
  assert.equal(unavailable.details.ok, false);
  const u = unavailable.details as { error_type?: string; attempts?: unknown };
  assert.equal(u.error_type, "unavailable");
  // The pre-spawn capability failure is preserved as an attempt receipt in the fail extras.
  assert.deepEqual(u.attempts, [
    {
      flow: "adversarial-review",
      attempt: 1,
      requestedKeys: ["claimed-intent", "correctness", "ponytail"],
      state: "unavailable",
      children: [],
    },
  ]);
  assert.ok(
    notified.some((n) => n.severity === "error" && n.message.includes("start_review_wave")),
    "the failure is reported loudly through the report seam",
  );
  // A failed launch leaves nothing pending — the next start is not wave_active.
  const spawnFailed = await executeStartReviewWave(
    state,
    reportWaveOver(createMemoryWaveAdapter({ spawnError: "no session" })),
    target,
    START_OPTS,
  );
  assert.equal((spawnFailed.details as { error_type?: string }).error_type, "spawn-failed");
  assert.match((spawnFailed.details as { error?: string }).error ?? "", /no session/);
});

test("executeCollectReviewWave: no_wave without a launch; wave_running retains the pending wave", async () => {
  const state = freshState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const none = await executeCollectReviewWave(state, wave, target);
  assert.equal(none.details.ok, false);
  assert.equal((none.details as { error_type?: string }).error_type, "no_wave");
  assert.match(none.content[0]?.text ?? "", /start_review_wave/);

  // Launch a wave that never completes on its own; an early collect (a tiny env-driven grace —
  // the one grace seam) soft-fails wave_running and RETAINS the pending ref.
  const start = await executeStartReviewWave(state, wave, target, START_OPTS);
  assert.equal(start.details.ok, true);
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  let running: Awaited<ReturnType<typeof executeCollectReviewWave>>;
  try {
    running = await executeCollectReviewWave(state, wave, target);
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
  assert.equal(running.details.ok, false);
  assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
  assert.match(running.content[0]?.text ?? "", /pending retained/);
  assert.match(running.content[0]?.text ?? "", /stop for owner diagnosis/);

  // Once the run completes, the retained wave collects normally (default grace).
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true);
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    reports?: { key: string }[];
    failures?: unknown[];
    attempts?: { flow: string; attempt: number; requestedKeys: string[]; state: string }[];
  };
  assert.equal(details.complete, true);
  assert.deepEqual(details.covered, ["claimed-intent", "correctness", "ponytail"]);
  assert.deepEqual(
    details.reports?.map((r) => r.key),
    ["claimed-intent", "correctness", "ponytail"],
  );
  assert.deepEqual(details.failures, []);
  assert.deepEqual(details.attempts, [
    {
      flow: "adversarial-review",
      attempt: 1,
      requestedKeys: ["claimed-intent", "correctness", "ponytail"],
      runId: "wave-async-1",
      asyncDir: "/memory/wave-async-1",
      state: "complete",
      children: [],
    },
  ]);
  const text = collected.content[0]?.text ?? "";
  assert.match(text, /Review wave complete: covered 3\/3 angle\(s\)/);
  assert.match(text, /untrusted DATA/);
  assert.equal(text.includes("attempts"), false, "receipts never enter the model-facing prose");
});

test("native relay seam: push before completion, then resolve aggregate and drain once", async (t) => {
  const adapter = createMemoryWaveAdapter({ completion: false });
  const aggregate = {
    state: "complete",
    value: [
      {
        key: "claimed-intent",
        ok: true,
        error: null,
        report: {
          angle: "claimed-intent",
          summary: "provisional concern withdrawn",
          findings: [],
          fyi: [],
          streamed: true,
        },
      },
      okEntry("correctness"),
      okEntry("ponytail"),
    ],
  };
  let release = (_value: typeof aggregate): void => {
    throw new Error("not initialized");
  };
  const deferredAggregate = new Promise<typeof aggregate>((resolve) => {
    release = resolve;
  });
  t.after(() => {
    adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
    release(aggregate);
  });
  let reading = (): void => {
    throw new Error("not initialized");
  };
  const aggregateRequested = new Promise<void>((resolve) => {
    reading = resolve;
  });
  adapter.readAggregate = () => {
    reading();
    return deferredAggregate;
  };
  const wave = reportWaveOver(adapter);
  const state = freshState();
  const { target } = fakeTarget();
  const start = await executeStartReviewWave(state, wave, target, START_OPTS);
  assert.equal(start.details.ok, true);
  const annotations = createAnnotationState();
  primeAnnotationSurface(annotations, { mode: "review", url: "http://127.0.0.1:7777" });
  const finding: ReviewFinding = {
    path: "a.ts",
    line: 1,
    severity: "major",
    confidence: "high",
    body: "defect",
  };
  const methods: string[] = [];
  const fetchLike: NonNullable<Parameters<typeof executePushAnnotations>[3]>["fetchLike"] = async (
    _url,
    init,
  ) => {
    methods.push(init.method);
    return {
      ok: true,
      status: init.method === "POST" ? 201 : 200,
      text: async () =>
        JSON.stringify(init.method === "POST" ? { ids: ["one"] } : { ok: true, removed: 1 }),
    };
  };
  const push = await executePushAnnotations(
    annotations,
    target,
    { angle: "claimed-intent", findings: [finding] },
    { fetchLike },
  );
  assert.equal(push.details.ok, true, JSON.stringify(push));
  assert.deepEqual(methods, ["POST"], "real push seam succeeds with completion withheld");
  assert.notEqual(state.pending, null);
  // Native completion can precede aggregate resolution. The collector waits inside its grace,
  // not in a parent polling loop, and only drains after the authoritative value is available.
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  await aggregateRequested;
  const collecting = executeCollectReviewWave(state, wave, target);
  release(aggregate);
  const final = await collecting;
  assert.equal(final.details.ok, true);
  const replacement = await executePushAnnotations(
    annotations,
    target,
    { angle: "claimed-intent", findings: [], replace: true },
    { fetchLike },
  );
  assert.equal(replacement.details.ok, true);
  assert.deepEqual(methods, ["POST", "DELETE"]);
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const again = await executeCollectReviewWave(state, wave, target);
  assert.equal(again.details.ok, false);
  if (!again.details.ok) assert.equal(again.details.error_type, "no_wave");
  assert.equal(adapter.calls.spawn.length, 1);
});

test("executeCollectReviewWave: an incomplete wave is an ok result with the loud warning", async () => {
  const state = freshState();
  const { target, notified } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("claimed-intent"),
        { key: "correctness", ok: false, error: "lane exploded", report: null },
        okEntry("ponytail"),
      ],
    },
  });
  const wave = reportWaveOver(adapter);
  await executeStartReviewWave(state, wave, target, START_OPTS);
  const collected = await executeCollectReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true, "honest incompleteness is an ok result, never a throw");
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    failures?: { key: string | null; reason: string }[];
  };
  assert.equal(details.complete, false);
  assert.deepEqual(details.covered, ["claimed-intent", "ponytail"]);
  assert.deepEqual(
    details.failures?.map((f) => [f.key, f.reason]),
    [["correctness", "lane-failed"]],
  );
  assert.match(collected.content[0]?.text ?? "", /Review wave INCOMPLETE: covered 2\/3 angle\(s\)/);
  assert.ok(
    notified.some(
      (n) =>
        n.severity === "warning" &&
        n.message.includes("uncovered angle(s): correctness") &&
        n.message.includes("lane exploded"),
    ),
    "the warning names the uncovered angle and the reason",
  );
});

test("the collect grace rides PERK_WAVE_COLLECT_GRACE_MS (the one grace seam — no per-call knob)", async () => {
  const state = freshState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({ completion: false });
  const wave = reportWaveOver(adapter);
  // Bound the never-completing wave's module timeout so its timer never outlives the test
  // (the settled-by-timeout result also proves an uncollected wave never rejects unhandled).
  process.env.PERK_WAVE_TIMEOUT_MS = "200";
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  try {
    await executeStartReviewWave(state, wave, target, START_OPTS);
    // The env override keeps the never-completing wave from stalling 15s.
    const running = await executeCollectReviewWave(state, wave, target);
    assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
    // After the module timeout fires, the retained wave drains into the timeout failure.
    process.env.PERK_WAVE_COLLECT_GRACE_MS = "2000";
    const drained = await executeCollectReviewWave(state, wave, target);
    assert.equal(drained.details.ok, true);
    const details = drained.details as { complete?: boolean; failures?: { reason: string }[] };
    assert.equal(details.complete, false);
    assert.equal(details.failures?.[0]?.reason, "timeout");
  } finally {
    delete process.env.PERK_WAVE_TIMEOUT_MS;
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
});

// --- registration -----------------------------------------------------------------------------

test("installReviewWaveBindings registers exactly the two tools over registration-owned state", async () => {
  // Seed a pending wave in a SEPARATE test-owned slot through the core…
  const seeded = freshState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const seededWave = reportWaveOver(adapter);
  await executeStartReviewWave(seeded, seededWave, target, START_OPTS);

  // …then a registration owns its OWN fresh closure slot: its collect sees no wave.
  const { pi, tools } = fakePi();
  installReviewWaveBindings(pi, reportWaveOver(createMemoryWaveAdapter({})));
  assert.deepEqual(
    [...tools.keys()].sort(),
    ["collect_review_wave", "start_review_wave"],
    "exactly the two flow-scoped tools",
  );
  const startDef = tools.get("start_review_wave");
  const collectDef = tools.get("collect_review_wave");
  assert.ok(startDef && collectDef);
  const ctx = { cwd: mkdtempSync(join(tmpdir(), "perk-rwt-")), ...target };
  const cleared = (await collectDef.execute("tc", {}, undefined, undefined, ctx)) as {
    details: { error_type?: string };
  };
  assert.equal(cleared.details.error_type, "no_wave");
  // …and the seeded slot is untouched by the registration (no shared module state).
  const collected = await executeCollectReviewWave(seeded, seededWave, target);
  assert.equal(collected.details.ok, true);

  // Both promptGuidelines carry the relay-loop discipline.
  // Sequential execution is load-bearing for the one-pending-wave invariant: concurrent starts
  // could both pass the `pending === null` check before either stores the launched wave.
  assert.equal(startDef.executionMode, "sequential");
  assert.equal(collectDef.executionMode, "sequential");
  const startText = (startDef.promptGuidelines ?? []).join("\n");
  const collectText = (collectDef.promptGuidelines ?? []).join("\n");
  for (const pin of [
    /end the turn/,
    /Keep the Pi session open/,
    /workflow identity and manifest/,
    /queues into an active turn/,
    /co-delivered progress/,
    /not a child completion/,
    /unrelated run, result preview, or elapsed time/,
    /Never parse status.json/,
    /No artificial wait calls or empty heartbeat batches/,
  ])
    assert.match(startText, pin);
  for (const pin of [
    /relay already-delivered provisional batches first/,
    /pre-completion wave_running/,
    /retains pending/,
    /stop the automatic flow for owner diagnosis/,
    /no polling retry chain/,
    /reconcile exactly once/,
    /Ignore duplicate\/late notices/,
    /over finalized findings/,
    /no_wave\/drain-once/,
    /never changes coverage/,
  ])
    assert.match(collectText, pin);
  for (const def of [startDef, collectDef]) {
    assert.match(def.description ?? "", /matching native workflow-completion notice/);
    assert.doesNotMatch(
      `${def.description}\n${def.promptGuidelines?.join("\n")}`,
      /subagent_wait|bg_wait|hold your turn open/i,
    );
  }
  assert.match(startText, /untrusted provisional DATA/);
  assert.match((collectDef.promptGuidelines ?? []).join("\n"), /untrusted DATA/);
  assert.match((collectDef.promptGuidelines ?? []).join("\n"), /honestly/);
});

test("the review-wave pair is in the tool census (PERK_TOOLS + every worktree stage list)", () => {
  for (const name of ["start_review_wave", "collect_review_wave"]) {
    assert.ok(PERK_TOOLS.includes(name), `${name} must be in PERK_TOOLS`);
    for (const stage of ["implement", "submit", "address", "land", "learn"]) {
      assert.ok(STAGE_TOOLS[stage]?.includes(name), `${stage} must carry ${name}`);
    }
  }
});

test("registered start_review_wave: a bad selection decodes to bad_input before any spawn", async () => {
  const { pi, tools } = fakePi();
  installReviewWaveBindings(pi, reportWaveOver(createMemoryWaveAdapter({})));
  const def = tools.get("start_review_wave");
  assert.ok(def);
  const { target, notified } = fakeTarget();
  const ctx = { cwd: mkdtempSync(join(tmpdir(), "perk-rwt-")), ...target };
  const result = (await def.execute(
    "tc",
    { angles: ["claimed-intent"] },
    undefined,
    undefined,
    ctx,
  )) as {
    content: { text?: string }[];
    details: { ok: boolean; error_type?: string };
  };
  assert.equal(result.details.ok, false);
  assert.equal(result.details.error_type, "bad_input");
  assert.match(result.content[0]?.text ?? "", /claimed-intent mandatory/);
  assert.ok(notified.some((n) => n.severity === "error"));
});

// --- the registered pair end-to-end (real session, fake RPC responder) ------------------------

function installPonytailReviewSkill(cwd: string): void {
  const root = join(cwd, ".pi", "npm", "node_modules", "@dietrichgebert", "ponytail");
  const skillDir = join(root, "skills", "ponytail-review");
  mkdirSync(skillDir, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "@dietrichgebert/ponytail", pi: { skills: ["./skills"] } }),
    "utf8",
  );
  writeFileSync(join(skillDir, "SKILL.md"), "---\nname: ponytail-review\n---\n", "utf8");
}

/**
 * The shared fake pi-subagents responder in dynamic mode: parse the module-rendered script's
 * lane keys and answer each with a schema-valid adversarial report. Offline like everything
 * here.
 */
function adversarialFake(): FakeSubagents {
  return createFakeSubagents([
    {
      executeScript: async (script) =>
        waveScriptItems(script).map(({ key }) => ({
          key,
          ok: true,
          error: null,
          report: {
            angle: key,
            summary: `${String(key)} looks sound`,
            findings: [],
            fyi: [],
            streamed: false,
          },
        })),
    },
  ]);
}

test("tools: start_review_wave threads the configured model + directive; collect drains the aggregate", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  // The configured adversarial-reviewer model must reach the wave as its workflow-level default.
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nadversarial-reviewer = "test-adv-model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: "{}" });
  const fake = adversarialFake();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fake.extension],
  });
  try {
    const started = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "quality"],
      pr: 42,
      worktree: "/abs/wt",
      directive: "focus on the workflow edits",
    });
    const startDetails = started.details as {
      ok: boolean;
      asyncId?: string;
      launch?: { requested: string[]; runnable: string[]; preflightFailures: unknown[] };
    };
    assert.equal(startDetails.ok, true);
    assert.ok(startDetails.asyncId);
    assert.deepEqual(startDetails.launch, {
      requested: ["claimed-intent", "quality", "ponytail"],
      runnable: ["claimed-intent", "quality", "ponytail"],
      preflightFailures: [],
    });
    // The tool-boundary threading pins: the configured model and the directive both reached the
    // actual spawn (config → execute → startAdversarialReviewWave → adapter).
    assert.equal(fake.spawns.length, 1);
    assert.equal(fake.spawns[0]?.model, "test-adv-model");
    const lanes = waveScriptItems(String(fake.spawns[0]?.workflowScript ?? "")) as Array<{
      key: string;
      agent: string;
      task: string;
      skill?: string;
    }>;
    assert.deepEqual(
      lanes.map((lane) => lane.key),
      ["claimed-intent", "quality", "ponytail"],
    );
    for (const lane of lanes) {
      assert.equal(lane.agent, "perk.adversarial-reviewer");
      assert.match(lane.task, /Review PR #42 at \/abs\/wt\./);
      assert.match(lane.task, /focus on the workflow edits/);
    }
    assert.equal(lanes.at(-1)?.skill, "ponytail-review");

    const collected = await h.invokeTool("collect_review_wave", {});
    const details = collected.details as {
      ok: boolean;
      complete?: boolean;
      covered?: string[];
      reports?: { key: string; report: { angle?: string; summary?: string } }[];
      failures?: unknown[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["claimed-intent", "quality", "ponytail"]);
    assert.equal(details.reports?.[0]?.report.angle, "claimed-intent");
    assert.deepEqual(details.failures, []);
  } finally {
    h.dispose();
  }
});

test("tools: missing exact Ponytail skill omits only that child and collects explicit incomplete coverage", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const fake = adversarialFake();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fake.extension],
  });
  try {
    const started = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "correctness"],
      pr: 42,
      worktree: "/abs/wt",
    });
    const startDetails = started.details as {
      ok: boolean;
      launch?: {
        requested: string[];
        runnable: string[];
        preflightFailures: { key: string | null; reason: string }[];
      };
    };
    assert.equal(startDetails.ok, true, "ordinary reviewers still launch");
    assert.deepEqual(startDetails.launch?.requested, ["claimed-intent", "correctness", "ponytail"]);
    assert.deepEqual(startDetails.launch?.runnable, ["claimed-intent", "correctness"]);
    assert.deepEqual(
      startDetails.launch?.preflightFailures.map((failure) => [failure.key, failure.reason]),
      [["ponytail", "skill-unavailable"]],
    );
    const startText = started.content[0]?.text ?? "";
    assert.match(startText, /workflow accepted with 2\/3 post-preflight runnable lane/);
    assert.match(startText, /Preflight skipped: ponytail: skill-unavailable/);
    assert.doesNotMatch(startText, /ponytail.*launched/i);
    assert.equal(fake.spawns.length, 1);
    const script = String(fake.spawns[0]?.workflowScript ?? "");
    assert.doesNotMatch(script, /"key":\s*"ponytail"/, "Ponytail never reaches runs.all");
    assert.match(script, /"key":\s*"claimed-intent"/);
    assert.match(script, /"key":\s*"correctness"/);

    const collected = await h.invokeTool("collect_review_wave", {});
    const details = collected.details as {
      ok: boolean;
      complete?: boolean;
      covered?: string[];
      failures?: { key: string | null; reason: string }[];
      attempts?: { requestedKeys: string[] }[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.complete, false);
    assert.deepEqual(details.covered, ["claimed-intent", "correctness"]);
    assert.deepEqual(
      details.failures?.map((failure) => [failure.key, failure.reason]),
      [["ponytail", "skill-unavailable"]],
    );
    assert.deepEqual(details.attempts?.[0]?.requestedKeys, [
      "claimed-intent",
      "correctness",
      "ponytail",
    ]);
    assert.match(collected.content[0]?.text ?? "", /INCOMPLETE: covered 2\/3 angle\(s\)/);
  } finally {
    h.dispose();
  }
});

test("tools: start_review_wave ignores an already-aborted per-call signal (the wave outlives the call)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  const fake = adversarialFake();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fake.extension],
  });
  try {
    const tool = h.session.extensionRunner
      .getAllRegisteredTools()
      .find((t) => t.definition.name === "start_review_wave");
    assert.ok(tool, "start_review_wave is registered");
    const controller = new AbortController();
    controller.abort();
    const ctx = {
      cwd,
      hasUI: true,
      ui: { notify() {} },
      sessionManager: h.session.sessionManager,
      signal: controller.signal,
      isIdle: () => true,
    } as unknown as Parameters<typeof tool.definition.execute>[4];
    // The per-call signal is deliberately NOT threaded into the wave: an already-aborted signal
    // must neither refuse nor cancel the launch (a regression threading it through would settle
    // the pre-spawn `cancelled` arm here).
    const started = (await tool.definition.execute(
      "tc-start",
      { angles: ["claimed-intent", "tests"], pr: 42, worktree: "/abs/wt" } as never,
      controller.signal,
      undefined,
      ctx,
    )) as { details: unknown };
    const startDetails = started.details as { ok: boolean; asyncId?: string };
    assert.equal(startDetails.ok, true, "an aborted signal must not become a cancelled launch");
    assert.ok(startDetails.asyncId);
    assert.equal(fake.spawns.length, 1, "the wave really spawned");
    // …and the detached wave outlives the aborted call: it stays pending and collectable.
    const collected = await h.invokeTool("collect_review_wave", {});
    const details = collected.details as { ok: boolean; complete?: boolean; covered?: string[] };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["claimed-intent", "tests", "ponytail"]);
  } finally {
    h.dispose();
  }
});

test("tools: an unavailable wave soft-fails loud at start (never a silent fallback)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // No RPC responder bound + a tiny ping timeout → the deterministic `unavailable` arm.
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_WAVE_RPC_PING_MS: "20" },
  });
  try {
    const started = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "correctness"],
      pr: 42,
      worktree: "/abs/wt",
    });
    const details = started.details as {
      ok: boolean;
      error_type?: string;
      attempts?: { state: string }[];
    };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "unavailable");
    assert.equal(details.attempts?.[0]?.state, "unavailable");
    assert.match(started.content[0]?.text ?? "", /start_review_wave failed:/);
    // Nothing pending after a failed launch.
    const collected = await h.invokeTool("collect_review_wave", {});
    assert.equal((collected.details as { error_type?: string }).error_type, "no_wave");
  } finally {
    h.dispose();
  }
});
