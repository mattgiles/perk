// Tests for the draft-review wave tool pair (registered live in `extension/index.ts`; the
// `pi/v1/codeReview/reviewWave.test.ts` mirror). The strict decoder is pinned directly; the start/collect
// execute cores are driven through the injected in-memory adapter over door-primed module
// state; registration + the real tool-boundary threading (config model → spawn, decode refusal,
// launch → collect round-trip) run against a REAL bound session via the T1 harness with a fake
// pi-subagents RPC responder on pi.events. Offline like everything here.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  clearDraftReviewContext,
  createDraftReviewWaveState,
  type DraftReviewWaveState,
  primeDraftReviewContext,
} from "../../authoring/review/draftContext.ts";
import { PERK_TOOLS, STAGE_TOOLS } from "../../substrate/toolGating.ts";
import {
  createFakeSubagents,
  type FakeSubagents,
  waveScriptItems,
} from "../../testing/fakeSubagents.ts";
import {
  fakePerk,
  loadPerkSession,
  type PerkSession,
  scaffoldRepo,
} from "../../testing/harness.ts";
import { createMemoryWaveAdapter } from "../../testing/memoryAdapter.ts";
import type { DraftReviewAngle } from "../../waves/draftReviewWave.ts";
import { reportWaveOver } from "../../waves/reportWave.ts";
import {
  decodeStartDraftReviewWaveParams,
  executeCollectDraftReviewWave,
  executeStartDraftReviewWave as executeStartDraftReviewWaveBase,
  registerDraftReviewWaveTools,
} from "./draftReviewWaveTools.ts";

const TWO_ANGLES: DraftReviewAngle[] = ["grounding", "risk"];
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const executeStartDraftReviewWave = (...args: Parameters<typeof executeStartDraftReviewWaveBase>) =>
  executeStartDraftReviewWaveBase(args[0], args[1], args[2], {
    ...args[3],
    requiredSkillPreflight: PREFLIGHT_OK,
  });

/** A schema-valid aggregate entry as the rendered script's projection produces it. */
function okEntry(key: string): unknown {
  return {
    key,
    ok: true,
    error: null,
    report: { angle: key, summary: "solid", findings: [], fyi: [] },
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

/** A fresh per-test state primed with a plan draft (what a door prime leaves behind). */
function primePlan(custom?: string): DraftReviewWaveState {
  const state = createDraftReviewWaveState();
  primeDraftReviewContext(state, {
    draftType: "plan",
    draft: "# The draft\n\nStep one.\n",
    ...(custom !== undefined ? { custom } : {}),
  });
  return state;
}

// --- decodeStartDraftReviewWaveParams: strict whole-refusal decode ----------------------------

test("decodeStartDraftReviewWaveParams accepts valid 2- and 3-angle selections (none mandatory)", () => {
  assert.deepEqual(decodeStartDraftReviewWaveParams({ angles: ["grounding", "scope"] }), {
    angles: ["grounding", "scope"],
  });
  assert.deepEqual(
    decodeStartDraftReviewWaveParams({ angles: ["scope", "decision-completeness", "risk"] }),
    { angles: ["scope", "decision-completeness", "risk"] },
  );
});

test("decodeStartDraftReviewWaveParams refuses out-of-bounds selections (whole refusal)", () => {
  assert.equal(decodeStartDraftReviewWaveParams({}), null); // missing
  assert.equal(decodeStartDraftReviewWaveParams({ angles: ["grounding"] }), null); // 1 angle
  assert.equal(
    decodeStartDraftReviewWaveParams({
      angles: ["grounding", "scope", "decision-completeness", "risk"],
    }),
    null,
  ); // 4 angles
  assert.equal(decodeStartDraftReviewWaveParams({ angles: ["risk", "risk"] }), null); // duplicate
  assert.equal(decodeStartDraftReviewWaveParams({ angles: ["grounding", "claimed-intent"] }), null); // unknown slug (the adversarial-review vocabulary is a different flow)
  assert.equal(decodeStartDraftReviewWaveParams({ angles: ["grounding", "custom"] }), null); // the custom lane is door-primed, never a pick
  assert.equal(decodeStartDraftReviewWaveParams({ angles: "grounding,risk" }), null); // not an array
  assert.equal(decodeStartDraftReviewWaveParams("not an object"), null);
});

test("decodeStartDraftReviewWaveParams refuses ANY extra param (no pr/worktree/directive/custom exist)", () => {
  for (const extra of [
    { pr: 42 },
    { worktree: "/wt" },
    { directive: "focus" },
    { custom: "my lens" },
    { draft: "# substituted" },
  ]) {
    assert.equal(
      decodeStartDraftReviewWaveParams({ angles: ["grounding", "risk"], ...extra }),
      null,
      `extra param must whole-refuse: ${Object.keys(extra)[0]}`,
    );
  }
});

// --- the execute cores over the injected memory adapter --------------------------------------

test("executeStartDraftReviewWave: unprimed context -> loud no_draft_context (nothing launched)", async () => {
  const state = createDraftReviewWaveState(); // no context primed
  const { target, notified } = fakeTarget();
  const adapter = createMemoryWaveAdapter();
  const result = await executeStartDraftReviewWave(state, reportWaveOver(adapter), target, {
    angles: TWO_ANGLES,
  });
  assert.equal(result.details.ok, false);
  assert.equal((result.details as { error_type?: string }).error_type, "no_draft_context");
  assert.match(
    result.content[0]?.text ?? "",
    /run \/plan-review-browser or \/objective-review-browser first/,
  );
  assert.equal(adapter.calls.spawn.length, 0, "nothing launched");
  assert.ok(notified.some((n) => n.severity === "error"));
});

test("executeStartDraftReviewWave: happy path stores the pending wave; the wave receives the primed draft", async () => {
  const state = primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const result = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(result.details.ok, true);
  const details = result.details as {
    asyncId?: string;
    asyncDir?: string;
    launch?: { requested: string[]; runnable: string[]; preflightFailures: unknown[] };
  };
  assert.equal(details.asyncId, "wave-async-1");
  assert.deepEqual(details.launch, {
    requested: ["grounding", "risk", "ponytail"],
    runnable: ["grounding", "risk", "ponytail"],
    preflightFailures: [],
  });
  const text = result.content[0]?.text ?? "";
  assert.match(text, /grounding, risk/);
  assert.match(text, /subagent_wait/);
  assert.match(text, /collect_draft_review_wave/);
  // The primed draft (never a tool param) reached the lane tasks.
  const script = (adapter.calls.spawn[0]?.workflowScript as string) ?? "";
  assert.match(script, /# The draft/);
  assert.match(script, /Draft type: plan\./);

  // The pending ref is stored: a second start refuses with wave_active…
  const second = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(second.details.ok, false);
  assert.equal((second.details as { error_type?: string }).error_type, "wave_active");
  assert.match(second.content[0]?.text ?? "", /collect_draft_review_wave first/);

  // …and collect drains it (clearing pending — a following collect is no_wave).
  const collected = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true);
  const drained = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
});

test("executeStartDraftReviewWave: a primed custom lane rides the launch and the covered set", async () => {
  const state = primePlan("check the rollback story");
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("custom"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const result = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(result.details.ok, true);
  assert.deepEqual(
    (
      result.details as {
        launch?: { requested: string[]; runnable: string[]; preflightFailures: unknown[] };
      }
    ).launch,
    {
      requested: ["grounding", "risk", "custom", "ponytail"],
      runnable: ["grounding", "risk", "custom", "ponytail"],
      preflightFailures: [],
    },
  );
  assert.match(
    result.content[0]?.text ?? "",
    /grounding, risk, custom, ponytail/,
    "the ok text names the custom lane",
  );
  const script = (adapter.calls.spawn[0]?.workflowScript as string) ?? "";
  assert.match(script, /check the rollback story/, "the primed custom definition reached the lane");

  const collected = await executeCollectDraftReviewWave(state, wave, target);
  const details = collected.details as { complete?: boolean; covered?: string[] };
  assert.equal(details.complete, true);
  assert.deepEqual(
    details.covered,
    ["grounding", "risk", "custom", "ponytail"],
    "covered includes the custom and Ponytail lanes",
  );
});

test("primeDraftReviewContext resets the pending wave (a new browser session supersedes)", async () => {
  const state = primePlan("focus the phasing");
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  await executeStartDraftReviewWave(state, wave, target, { angles: TWO_ANGLES });
  // Re-prime (a second /plan-review-browser): the pending slot is wiped — a new start launches.
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft v2\n" });
  const second = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(second.details.ok, true, "priming reset the pending wave");
  const script = (adapter.calls.spawn[1]?.workflowScript as string) ?? "";
  assert.match(script, /# Draft v2/, "the new session's draft rides the new wave");
  // The re-prime replaces the context wholesale: the first session's custom lane is gone, and a
  // prime without `custom` leaves no custom key at all (the key-absence representation the
  // execute cores key their custom-lane inclusion on).
  assert.deepEqual(
    state.context,
    { draftType: "plan", draft: "# Draft v2\n" },
    "the stale custom lane does not survive a re-prime",
  );
});

test("a supersede during the collect's await never erases the NEW pending wave", async () => {
  // The latent-erasure regression (ported from the retired doors/pendingWave.ts suite,
  // re-expressed against the identity-guarded clear in the collect core): a collect awaits
  // wave 1; meanwhile a re-prime + new launch stores wave 2's ref. The stale collect must
  // return wave 1's settled result WITHOUT clearing wave 2's ref, and a following collect
  // drains wave 2.
  const state = primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregates: [
      {
        state: "complete",
        value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
      },
      {
        state: "complete",
        value: [okEntry("scope"), okEntry("risk"), okEntry("ponytail")],
      },
    ],
  });
  const wave = reportWaveOver(adapter);
  await executeStartDraftReviewWave(state, wave, target, { angles: TWO_ANGLES });

  // The stale collect is in flight, awaiting wave 1's unsettled result…
  const staleCollect = executeCollectDraftReviewWave(state, wave, target);
  // …while the supersede lands: a re-prime wipes the slot and a new start stores wave 2's ref.
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft v2\n" });
  const second = await executeStartDraftReviewWave(state, wave, target, {
    angles: ["scope", "risk"],
  });
  assert.equal(second.details.ok, true, "the superseding start launches");

  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const stale = await staleCollect;
  assert.equal(stale.details.ok, true, "the stale collect returns wave 1's settled result");
  assert.deepEqual((stale.details as { covered?: string[] }).covered, [
    "grounding",
    "risk",
    "ponytail",
  ]);

  // Wave 2 SURVIVES the stale collect's clear — the following collect drains it.
  adapter.emitCompletion({ asyncId: "wave-async-2", asyncDir: "/memory/wave-async-2" });
  const next = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(next.details.ok, true, "the NEW pending wave stayed collectable");
  assert.deepEqual((next.details as { covered?: string[] }).covered, ["scope", "risk", "ponytail"]);
  const drained = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
});

test("clearDraftReviewContext leaves an already-launched wave collectable (the early-decision edge)", async () => {
  // The door clears the context when the bridge settles (an early human decision mid-wave);
  // the still-pending wave must stay collectable — clearing must NOT null the pending slot
  // (only priming a NEW session does that).
  const state = primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const start = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(start.details.ok, true);
  clearDraftReviewContext(state);
  // A late start refuses no_draft_context (the context is gone)…
  const late = await executeStartDraftReviewWave(state, wave, target, { angles: TWO_ANGLES });
  assert.equal((late.details as { error_type?: string }).error_type, "no_draft_context");
  // …but the launched wave completes and collects normally.
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true, "the cleared context never orphans the pending wave");
  const details = collected.details as { complete?: boolean; covered?: string[] };
  assert.equal(details.complete, true);
  assert.deepEqual(details.covered, ["grounding", "risk", "ponytail"]);
});

test("executeStartDraftReviewWave: a launch failure soft-fails with the wave reason and the attempt receipt", async () => {
  const state = primePlan("extra lens");
  const { target, notified } = fakeTarget();
  const unavailable = await executeStartDraftReviewWave(
    state,
    reportWaveOver(createMemoryWaveAdapter({ ping: null })),
    target,
    { angles: TWO_ANGLES },
  );
  assert.equal(unavailable.details.ok, false);
  const u = unavailable.details as { error_type?: string; attempts?: unknown };
  assert.equal(u.error_type, "unavailable");
  // The pre-spawn capability failure is preserved as an attempt receipt in the fail extras —
  // requestedKeys include the primed custom lane.
  assert.deepEqual(u.attempts, [
    {
      flow: "draft-review",
      attempt: 1,
      requestedKeys: ["grounding", "risk", "custom", "ponytail"],
      state: "unavailable",
      children: [],
    },
  ]);
  assert.ok(
    notified.some((n) => n.severity === "error" && n.message.includes("start_draft_review_wave")),
    "the failure is reported loudly through the report seam",
  );
  // A failed launch leaves nothing pending — the next start is not wave_active.
  const spawnFailed = await executeStartDraftReviewWave(
    state,
    reportWaveOver(createMemoryWaveAdapter({ spawnError: "no session" })),
    target,
    { angles: TWO_ANGLES },
  );
  assert.equal((spawnFailed.details as { error_type?: string }).error_type, "spawn-failed");
  assert.match((spawnFailed.details as { error?: string }).error ?? "", /no session/);
});

test("executeCollectDraftReviewWave: no_wave without a launch; wave_running retains the pending wave", async () => {
  const state = primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
    },
  });
  const wave = reportWaveOver(adapter);
  const none = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(none.details.ok, false);
  assert.equal((none.details as { error_type?: string }).error_type, "no_wave");
  assert.match(none.content[0]?.text ?? "", /start_draft_review_wave/);

  // Launch a wave that never completes on its own; an early collect (a tiny env-driven grace —
  // the one grace seam) soft-fails wave_running and RETAINS the pending ref.
  const start = await executeStartDraftReviewWave(state, wave, target, {
    angles: TWO_ANGLES,
  });
  assert.equal(start.details.ok, true);
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  let running: Awaited<ReturnType<typeof executeCollectDraftReviewWave>>;
  try {
    running = await executeCollectDraftReviewWave(state, wave, target);
  } finally {
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
  }
  assert.equal(running.details.ok, false);
  assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
  assert.match(running.content[0]?.text ?? "", /keep looping subagent_wait/);

  // Once the run completes, the retained wave collects normally (attempts in details only).
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true);
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    reports?: { key: string }[];
    failures?: unknown[];
    attempts?: { flow: string; requestedKeys: string[]; state: string }[];
  };
  assert.equal(details.complete, true);
  assert.deepEqual(details.covered, ["grounding", "risk", "ponytail"]);
  assert.deepEqual(details.failures, []);
  assert.equal(details.attempts?.[0]?.flow, "draft-review");
  const text = collected.content[0]?.text ?? "";
  assert.match(text, /Draft-review wave complete: covered 3\/3 lane\(s\)/);
  assert.match(text, /untrusted DATA/);
  assert.equal(text.includes("attempts"), false, "receipts never enter the model-facing prose");
});

test("executeCollectDraftReviewWave: an incomplete wave is an ok result with the loud warning", async () => {
  const state = primePlan("extra lens");
  const { target, notified } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("grounding"),
        okEntry("risk"),
        { key: "custom", ok: false, error: "lane exploded", report: null },
        okEntry("ponytail"),
      ],
    },
  });
  const wave = reportWaveOver(adapter);
  await executeStartDraftReviewWave(state, wave, target, { angles: TWO_ANGLES });
  const collected = await executeCollectDraftReviewWave(state, wave, target);
  assert.equal(collected.details.ok, true, "honest incompleteness is an ok result, never a throw");
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    failures?: { key: string | null; reason: string }[];
  };
  assert.equal(details.complete, false);
  assert.deepEqual(details.covered, ["grounding", "risk", "ponytail"]);
  assert.deepEqual(
    details.failures?.map((f) => [f.key, f.reason]),
    [["custom", "lane-failed"]],
  );
  assert.match(
    collected.content[0]?.text ?? "",
    /Draft-review wave INCOMPLETE: covered 3\/4 lane\(s\)/,
  );
  assert.ok(
    notified.some(
      (n) =>
        n.severity === "warning" &&
        n.message.includes("uncovered lane(s): custom") &&
        n.message.includes("lane exploded"),
    ),
    "the warning names the uncovered lane and the reason",
  );
});

// --- registration -----------------------------------------------------------------------------

test("registerDraftReviewWaveTools registers exactly the two tools over registration-owned state", async () => {
  // Seed a pending wave AND a primed context in a SEPARATE test-owned state through the cores…
  const seeded = primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("ponytail")],
    },
  });
  const seededWave = reportWaveOver(adapter);
  await executeStartDraftReviewWave(seeded, seededWave, target, { angles: TWO_ANGLES });

  // …then a registration owns its OWN fresh state: no wave pending, no context primed.
  const { pi, tools } = fakePi();
  registerDraftReviewWaveTools(
    pi,
    createDraftReviewWaveState(),
    reportWaveOver(createMemoryWaveAdapter({})),
  );
  assert.deepEqual(
    [...tools.keys()].sort(),
    ["collect_draft_review_wave", "start_draft_review_wave"],
    "exactly the two flow-scoped tools",
  );
  const startDef = tools.get("start_draft_review_wave");
  const collectDef = tools.get("collect_draft_review_wave");
  assert.ok(startDef && collectDef);
  const ctx = { cwd: mkdtempSync(join(tmpdir(), "perk-drwt-")), ...target };
  const cleared = (await collectDef.execute("tc", {}, undefined, undefined, ctx)) as {
    details: { error_type?: string };
  };
  assert.equal(cleared.details.error_type, "no_wave");
  const unprimed = (await startDef.execute(
    "tc",
    { angles: ["grounding", "risk"] },
    undefined,
    undefined,
    ctx,
  )) as { details: { error_type?: string } };
  assert.equal(
    unprimed.details.error_type,
    "no_draft_context",
    "the registration's own state starts unprimed",
  );
  // …and the seeded state is untouched by the registration (no shared module slot).
  const collected = await executeCollectDraftReviewWave(seeded, seededWave, target);
  assert.equal(collected.details.ok, true);

  // Both promptGuidelines carry the relay-loop discipline.
  // Sequential execution is load-bearing for the one-pending-wave invariant: concurrent starts
  // could both pass the `pending === null` check before either stores the launched wave.
  assert.equal(startDef.executionMode, "sequential");
  assert.equal(collectDef.executionMode, "sequential");
  assert.match(
    (startDef.promptGuidelines ?? []).join("\n"),
    /subagent_wait\(\{timeoutMs: 30000\}\)/,
  );
  assert.match((startDef.promptGuidelines ?? []).join("\n"), /untrusted DATA/);
  assert.match(
    (startDef.promptGuidelines ?? []).join("\n"),
    /required automatic final source-bound Ponytail lane/,
  );
  assert.match((startDef.promptGuidelines ?? []).join("\n"), /launch\.requested/);
  assert.match((collectDef.promptGuidelines ?? []).join("\n"), /untrusted DATA/);
  assert.match((collectDef.promptGuidelines ?? []).join("\n"), /honestly/);
});

test("the draft-review pair is in the tool census (PERK_TOOLS + the draft-door stage lists)", () => {
  for (const name of ["start_draft_review_wave", "collect_draft_review_wave", "push_annotations"]) {
    assert.ok(PERK_TOOLS.includes(name), `${name} must be in PERK_TOOLS`);
    // The plan-family lists (/plan-review-browser) + the objective lists
    // (/objective-review-browser — gate-OFF coverage after objectiveApprovalSave).
    for (const stage of ["plan", "save", "objective-plan", "objective-author", "objective-save"]) {
      assert.ok(STAGE_TOOLS[stage]?.includes(name), `${stage} must carry ${name}`);
    }
  }
  // The objective door's guidance names plan_review (it routes to the objective review arm
  // there), so the two objective stage lists must carry it (drive coverage).
  for (const stage of ["objective-author", "objective-save"]) {
    assert.ok(STAGE_TOOLS[stage]?.includes("plan_review"), `${stage} must carry plan_review`);
  }
});

test("registered start_draft_review_wave: a bad selection decodes to bad_input before any spawn", async () => {
  const { pi, tools } = fakePi();
  registerDraftReviewWaveTools(
    pi,
    createDraftReviewWaveState(),
    reportWaveOver(createMemoryWaveAdapter({})),
  );
  const def = tools.get("start_draft_review_wave");
  assert.ok(def);
  const { target, notified } = fakeTarget();
  const ctx = { cwd: mkdtempSync(join(tmpdir(), "perk-drwt-")), ...target };
  const result = (await def.execute(
    "tc",
    { angles: ["grounding"] },
    undefined,
    undefined,
    ctx,
  )) as {
    content: { text?: string }[];
    details: { ok: boolean; error_type?: string };
  };
  assert.equal(result.details.ok, false);
  assert.equal(result.details.error_type, "bad_input");
  assert.match(result.content[0]?.text ?? "", /grounding\|scope\|decision-completeness\|risk/);
  assert.ok(notified.some((n) => n.severity === "error"));
});

// --- the registered pair end-to-end (real session, fake RPC responder) ------------------------
//
// The session's draft-review state is registration-owned (created in index.ts activation and
// deliberately unreachable from outside), so the e2e tests prime it the only way production
// does: through the REAL /plan-review-browser door over a fake plannotator peer.

function installPonytailCoreSkill(cwd: string): void {
  const root = join(cwd, ".pi", "npm", "node_modules", "@dietrichgebert", "ponytail");
  const skillDir = join(root, "skills", "ponytail");
  mkdirSync(skillDir, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "@dietrichgebert/ponytail", pi: { skills: ["./skills"] } }),
    "utf8",
  );
  writeFileSync(join(skillDir, "SKILL.md"), "---\nname: ponytail\n---\n", "utf8");
}

/**
 * The shared fake pi-subagents responder in dynamic mode: parse the module-rendered script's
 * lane keys and answer each with a schema-valid draft report. Offline like everything here.
 */
function draftFake(): FakeSubagents {
  return createFakeSubagents([
    {
      executeScript: async (script) =>
        waveScriptItems(script).map(({ key }) => ({
          key,
          ok: true,
          error: null,
          report: { angle: key, summary: `${String(key)} looks sound`, findings: [], fyi: [] },
        })),
    },
  ]);
}

/** The recorded plan-review bridge envelopes (the door-prime plumbing). */
interface FakePlannotatorSink {
  envelopes: { payload?: { planContent?: string }; respond: (r: unknown) => void }[];
  emitDecision: (decision: Record<string, unknown>) => void;
}

/**
 * A fake plannotator extension (the planReviewBrowser.test.ts idiom): registers the
 * `plannotator-review` presence-probe target and answers each `plan-review` handshake pending —
 * enough for the REAL door to prime the session's draft-review context.
 */
function fakePlannotator(sink: FakePlannotatorSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    sink.emitDecision = (decision) => pi.events.emit("plannotator:review-result", decision);
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      const envelope = data as FakePlannotatorSink["envelopes"][number];
      sink.envelopes.push(envelope);
      envelope.respond({
        status: "handled",
        result: { status: "pending", reviewId: `r-${sink.envelopes.length}` },
      });
    });
  };
}

function newSink(): FakePlannotatorSink {
  return { envelopes: [], emitDecision: () => {} };
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

/** Prime the SESSION's draft-review context through the real door (draft first, then open). */
async function primeThroughDoor(h: PerkSession, custom = ""): Promise<void> {
  await h.invokeTool("plan_draft", { plan: DRAFT_MD });
  await h.runCommandHandler("plan-review-browser", custom);
}

test("tools: start_draft_review_wave threads the configured model over the primed context; collect drains", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  installPonytailCoreSkill(cwd);
  // The configured draft-reviewer model must reach the wave as its workflow-level default.
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\ndraft-reviewer = "test-draft-model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: "{}" });
  const fake = draftFake();
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink), fake.extension],
  });
  try {
    // The REAL door primes the session's registration-owned context (draft + custom lane).
    await primeThroughDoor(h, "check the rollback story");
    const started = await h.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "scope"],
    });
    const startDetails = started.details as {
      ok: boolean;
      asyncId?: string;
      launch?: { requested: string[]; runnable: string[]; preflightFailures: unknown[] };
    };
    assert.equal(startDetails.ok, true);
    assert.ok(startDetails.asyncId);
    assert.deepEqual(startDetails.launch, {
      requested: ["grounding", "scope", "custom", "ponytail"],
      runnable: ["grounding", "scope", "custom", "ponytail"],
      preflightFailures: [],
    });
    // The tool-boundary threading pins: the configured model and the primed draft/custom both
    // reached the actual spawn (config → execute → startDraftReviewWave → adapter).
    assert.equal(fake.spawns.length, 1);
    assert.equal(fake.spawns[0]?.model, "test-draft-model");
    const lanes = waveScriptItems(String(fake.spawns[0]?.workflowScript ?? "")) as Array<{
      key: string;
      agent: string;
      task: string;
      skill?: string;
    }>;
    assert.deepEqual(
      lanes.map((lane) => lane.key),
      ["grounding", "scope", "custom", "ponytail"],
    );
    for (const lane of lanes) {
      assert.equal(lane.agent, "perk.draft-reviewer");
      assert.match(lane.task, /# The working draft/);
      assert.match(lane.task, /Draft type: plan\./);
    }
    assert.match(lanes[2]?.task ?? "", /check the rollback story/);
    assert.equal(lanes[3]?.skill, "ponytail");

    const collected = await h.invokeTool("collect_draft_review_wave", {});
    const details = collected.details as {
      ok: boolean;
      complete?: boolean;
      covered?: string[];
      reports?: { key: string; report: { angle?: string } }[];
      failures?: unknown[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["grounding", "scope", "custom", "ponytail"]);
    assert.equal(details.reports?.[0]?.report.angle, "grounding");
    assert.deepEqual(details.failures, []);
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("tools: missing exact Ponytail core skill omits only that child and collects explicit incomplete coverage", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const fake = draftFake();
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sink), fake.extension],
  });
  try {
    await primeThroughDoor(h);
    const started = await h.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "scope"],
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
    assert.deepEqual(startDetails.launch?.requested, ["grounding", "scope", "ponytail"]);
    assert.deepEqual(startDetails.launch?.runnable, ["grounding", "scope"]);
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
    assert.match(script, /"key":\s*"grounding"/);
    assert.match(script, /"key":\s*"scope"/);

    const collected = await h.invokeTool("collect_draft_review_wave", {});
    const details = collected.details as {
      ok: boolean;
      complete?: boolean;
      covered?: string[];
      failures?: { key: string | null; reason: string }[];
      attempts?: { requestedKeys: string[] }[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.complete, false);
    assert.deepEqual(details.covered, ["grounding", "scope"]);
    assert.deepEqual(
      details.failures?.map((failure) => [failure.key, failure.reason]),
      [["ponytail", "skill-unavailable"]],
    );
    assert.deepEqual(details.attempts?.[0]?.requestedKeys, ["grounding", "scope", "ponytail"]);
    assert.match(collected.content[0]?.text ?? "", /INCOMPLETE: covered 2\/3 lane\(s\)/);
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("tools: start_draft_review_wave ignores an already-aborted per-call signal (the wave outlives the call)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  installPonytailCoreSkill(cwd);
  const fake = draftFake();
  const sink = newSink();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sink), fake.extension],
  });
  try {
    await primeThroughDoor(h);
    const tool = h.session.extensionRunner
      .getAllRegisteredTools()
      .find((t) => t.definition.name === "start_draft_review_wave");
    assert.ok(tool, "start_draft_review_wave is registered");
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
      { angles: ["grounding", "risk"] } as never,
      controller.signal,
      undefined,
      ctx,
    )) as { details: unknown };
    const startDetails = started.details as { ok: boolean; asyncId?: string };
    assert.equal(startDetails.ok, true, "an aborted signal must not become a cancelled launch");
    assert.ok(startDetails.asyncId);
    assert.equal(fake.spawns.length, 1, "the wave really spawned");
    // …and the detached wave outlives the aborted call: it stays pending and collectable.
    const collected = await h.invokeTool("collect_draft_review_wave", {});
    const details = collected.details as { ok: boolean; complete?: boolean; covered?: string[] };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["grounding", "risk", "ponytail"]);
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});
