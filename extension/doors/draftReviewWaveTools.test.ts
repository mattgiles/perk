// Tests for the draft-review wave tool pair (registered live in `extension/index.ts`; the
// `reviewWaveTools.test.ts` mirror). The strict decoder is pinned directly; the start/collect
// execute cores are driven through the injected in-memory adapter over door-primed module
// state; registration + the real tool-boundary threading (config model → spawn, decode refusal,
// launch → collect round-trip) run against a REAL bound session via the T1 harness with a fake
// pi-subagents RPC responder on pi.events. Offline like everything here.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PERK_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import type { DraftReviewAngle } from "../waves/draftReviewWave.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";
import {
  clearDraftReviewContext,
  decodeStartDraftReviewWaveParams,
  executeCollectDraftReviewWave,
  executeStartDraftReviewWave,
  primeDraftReviewContext,
  registerDraftReviewWaveTools,
} from "./draftReviewWaveTools.ts";

const TWO_ANGLES: DraftReviewAngle[] = ["grounding", "risk"];

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

/** Reset the module's pending-wave + primed-context state, then prime a plan draft. */
function primePlan(custom?: string): void {
  registerDraftReviewWaveTools(fakePi().pi);
  primeDraftReviewContext({
    draftType: "plan",
    draft: "# The draft\n\nStep one.\n",
    ...(custom !== undefined ? { custom } : {}),
  });
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
  registerDraftReviewWaveTools(fakePi().pi); // reset: no context primed
  const { target, notified } = fakeTarget();
  const adapter = createMemoryWaveAdapter();
  const result = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
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
  primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("grounding"), okEntry("risk")] },
  });
  const result = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(result.details.ok, true);
  const details = result.details as { asyncId?: string; asyncDir?: string; lanes?: string[] };
  assert.equal(details.asyncId, "wave-async-1");
  assert.deepEqual(details.lanes, ["grounding", "risk"]);
  const text = result.content[0]?.text ?? "";
  assert.match(text, /grounding, risk/);
  assert.match(text, /subagent_wait/);
  assert.match(text, /collect_draft_review_wave/);
  // The primed draft (never a tool param) reached the lane tasks.
  const script = (adapter.calls.spawn[0]?.workflowScript as string) ?? "";
  assert.match(script, /# The draft/);
  assert.match(script, /Draft type: plan\./);

  // The pending wave is stored: a second start refuses with wave_active…
  const second = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(second.details.ok, false);
  assert.equal((second.details as { error_type?: string }).error_type, "wave_active");
  assert.match(second.content[0]?.text ?? "", /collect_draft_review_wave first/);

  // …and collect drains it (clearing pending — a following collect is no_wave).
  const collected = await executeCollectDraftReviewWave(target);
  assert.equal(collected.details.ok, true);
  const drained = await executeCollectDraftReviewWave(target);
  assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
});

test("executeStartDraftReviewWave: a primed custom lane rides the launch and the covered set", async () => {
  primePlan("check the rollback story");
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("grounding"), okEntry("risk"), okEntry("custom")],
    },
  });
  const result = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(result.details.ok, true);
  assert.deepEqual((result.details as { lanes?: string[] }).lanes, ["grounding", "risk", "custom"]);
  assert.match(
    result.content[0]?.text ?? "",
    /grounding, risk, custom/,
    "the ok text names the custom lane",
  );
  const script = (adapter.calls.spawn[0]?.workflowScript as string) ?? "";
  assert.match(script, /check the rollback story/, "the primed custom definition reached the lane");

  const collected = await executeCollectDraftReviewWave(target);
  const details = collected.details as { complete?: boolean; covered?: string[] };
  assert.equal(details.complete, true);
  assert.deepEqual(
    details.covered,
    ["grounding", "risk", "custom"],
    "covered includes the custom lane",
  );
});

test("primeDraftReviewContext resets the pending wave (a new browser session supersedes)", async () => {
  primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("grounding"), okEntry("risk")] },
  });
  await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  // Re-prime (a second /plan-review-browser): the pending slot is wiped — a new start launches.
  primeDraftReviewContext({ draftType: "plan", draft: "# Draft v2\n" });
  const second = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(second.details.ok, true, "priming reset the pending wave");
  const script = (adapter.calls.spawn[1]?.workflowScript as string) ?? "";
  assert.match(script, /# Draft v2/, "the new session's draft rides the new wave");
});

test("clearDraftReviewContext leaves an already-launched wave collectable (the early-decision edge)", async () => {
  // The door clears the context when the bridge settles (an early human decision mid-wave);
  // the still-pending wave must stay collectable — clearing must NOT null the pending slot
  // (only priming a NEW session does that).
  primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: { state: "complete", value: [okEntry("grounding"), okEntry("risk")] },
  });
  const start = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(start.details.ok, true);
  clearDraftReviewContext();
  // A late start refuses no_draft_context (the context is gone)…
  const late = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal((late.details as { error_type?: string }).error_type, "no_draft_context");
  // …but the launched wave completes and collects normally.
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectDraftReviewWave(target, { graceMs: 1_000 });
  assert.equal(collected.details.ok, true, "the cleared context never orphans the pending wave");
  const details = collected.details as { complete?: boolean; covered?: string[] };
  assert.equal(details.complete, true);
  assert.deepEqual(details.covered, ["grounding", "risk"]);
});

test("executeStartDraftReviewWave: a launch failure soft-fails with the wave reason and the attempt receipt", async () => {
  primePlan("extra lens");
  const { target, notified } = fakeTarget();
  const unavailable = await executeStartDraftReviewWave(
    createMemoryWaveAdapter({ ping: null }),
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
      requestedKeys: ["grounding", "risk", "custom"],
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
    createMemoryWaveAdapter({ spawnError: "no session" }),
    target,
    { angles: TWO_ANGLES },
  );
  assert.equal((spawnFailed.details as { error_type?: string }).error_type, "spawn-failed");
  assert.match((spawnFailed.details as { error?: string }).error ?? "", /no session/);
});

test("executeCollectDraftReviewWave: no_wave without a launch; wave_running retains the pending wave", async () => {
  primePlan();
  const { target } = fakeTarget();
  const none = await executeCollectDraftReviewWave(target);
  assert.equal(none.details.ok, false);
  assert.equal((none.details as { error_type?: string }).error_type, "no_wave");
  assert.match(none.content[0]?.text ?? "", /start_draft_review_wave/);

  // Launch a wave that never completes on its own; an early collect (tiny injected grace)
  // soft-fails wave_running and RETAINS the pending wave.
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: { state: "complete", value: [okEntry("grounding"), okEntry("risk")] },
  });
  const start = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(start.details.ok, true);
  const running = await executeCollectDraftReviewWave(target, { graceMs: 20 });
  assert.equal(running.details.ok, false);
  assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
  assert.match(running.content[0]?.text ?? "", /keep looping subagent_wait/);

  // Once the run completes, the retained wave collects normally (attempts in details only).
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectDraftReviewWave(target, { graceMs: 1_000 });
  assert.equal(collected.details.ok, true);
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    reports?: { key: string }[];
    failures?: unknown[];
    attempts?: { flow: string; requestedKeys: string[]; state: string }[];
  };
  assert.equal(details.complete, true);
  assert.deepEqual(details.covered, ["grounding", "risk"]);
  assert.deepEqual(details.failures, []);
  assert.equal(details.attempts?.[0]?.flow, "draft-review");
  const text = collected.content[0]?.text ?? "";
  assert.match(text, /Draft-review wave complete: covered 2\/2 lane\(s\)/);
  assert.match(text, /untrusted DATA/);
  assert.equal(text.includes("attempts"), false, "receipts never enter the model-facing prose");
});

test("executeCollectDraftReviewWave: an incomplete wave is an ok result with the loud warning", async () => {
  primePlan("extra lens");
  const { target, notified } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        okEntry("grounding"),
        okEntry("risk"),
        { key: "custom", ok: false, error: "lane exploded", report: null },
      ],
    },
  });
  await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  const collected = await executeCollectDraftReviewWave(target);
  assert.equal(collected.details.ok, true, "honest incompleteness is an ok result, never a throw");
  const details = collected.details as {
    complete?: boolean;
    covered?: string[];
    failures?: { key: string | null; reason: string }[];
  };
  assert.equal(details.complete, false);
  assert.deepEqual(details.covered, ["grounding", "risk"]);
  assert.deepEqual(
    details.failures?.map((f) => [f.key, f.reason]),
    [["custom", "lane-failed"]],
  );
  assert.match(
    collected.content[0]?.text ?? "",
    /Draft-review wave INCOMPLETE: covered 2\/3 lane\(s\)/,
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

test("registerDraftReviewWaveTools registers exactly the two tools and resets state", async () => {
  // Seed a pending wave AND a primed context through the cores…
  primePlan();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: { state: "complete", value: [okEntry("grounding"), okEntry("risk")] },
  });
  await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });

  // …then a fresh registration wipes both (a fresh registration is a fresh session).
  const { pi, tools } = fakePi();
  registerDraftReviewWaveTools(pi);
  assert.deepEqual(
    [...tools.keys()].sort(),
    ["collect_draft_review_wave", "start_draft_review_wave"],
    "exactly the two flow-scoped tools",
  );
  const cleared = await executeCollectDraftReviewWave(target);
  assert.equal((cleared.details as { error_type?: string }).error_type, "no_wave");
  const unprimed = await executeStartDraftReviewWave(adapter, target, { angles: TWO_ANGLES });
  assert.equal(
    (unprimed.details as { error_type?: string }).error_type,
    "no_draft_context",
    "registration also clears the primed context",
  );

  // Both promptGuidelines carry the relay-loop discipline.
  const startDef = tools.get("start_draft_review_wave");
  const collectDef = tools.get("collect_draft_review_wave");
  assert.ok(startDef && collectDef);
  // Sequential execution is load-bearing for the one-pending-wave invariant: concurrent starts
  // could both pass the `pending === null` check before either stores the launched wave.
  assert.equal(startDef.executionMode, "sequential");
  assert.equal(collectDef.executionMode, "sequential");
  assert.match(
    (startDef.promptGuidelines ?? []).join("\n"),
    /subagent_wait\(\{timeoutMs: 30000\}\)/,
  );
  assert.match((startDef.promptGuidelines ?? []).join("\n"), /untrusted DATA/);
  assert.match((startDef.promptGuidelines ?? []).join("\n"), /never re-encode it/);
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
  registerDraftReviewWaveTools(pi);
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

/** The spawn params the fake responder observes (the tool-boundary threading assertions). */
interface SpawnSink {
  spawns: { workflowScript?: string; model?: string; outputSchema?: unknown }[];
}

/**
 * A fake pi-subagents responder bound as a bus peer (the reviewWaveTools.test.ts idiom):
 * answers ping/spawn on `pi.events` with the v1 envelope, writes a terminal `status.json`
 * carrying one schema-valid draft report per lane into a real temp `asyncDir`, and emits the
 * advertised completion event. Offline like everything here.
 */
function fakeSubagentsResponder(sink: SpawnSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.events.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const request = raw as {
        requestId: string;
        method: string;
        params?: { workflowScript?: string; model?: string; outputSchema?: unknown };
      };
      const reply = (payload: Record<string, unknown>): void => {
        pi.events.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, {
          version: WAVE_RPC_PROTOCOL_VERSION,
          requestId: request.requestId,
          method: request.method,
          ...payload,
        });
      };
      if (request.method === "ping") {
        reply({
          success: true,
          data: {
            version: WAVE_RPC_PROTOCOL_VERSION,
            methods: ["ping", "status", "spawn", "steer", "interrupt", "stop", "resume"],
            capabilities: { asyncSpawn: true },
            events: { asyncComplete: "subagent:async-complete" },
            session: {},
          },
        });
        return;
      }
      if (request.method === "spawn") {
        if (request.params !== undefined) sink.spawns.push(request.params);
        // Parse the module-rendered script's lane keys and answer each with a schema-valid report.
        const script = request.params?.workflowScript ?? "";
        const start = script.indexOf("runs.all(") + "runs.all(".length;
        const end = script.indexOf(");\nreturn");
        const lanes = JSON.parse(script.slice(start, end)) as Array<{ key: string }>;
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-draft-wave-e2e-"));
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({
            runId: basename(asyncDir),
            mode: "workflow",
            state: "complete",
            startedAt: 0,
            workflow: {
              value: lanes.map(({ key }) => ({
                key,
                ok: true,
                error: null,
                report: { angle: key, summary: `${key} looks sound`, findings: [], fyi: [] },
              })),
            },
          }),
        );
        reply({
          success: true,
          data: { text: "Started async run.", details: { asyncId: basename(asyncDir), asyncDir } },
        });
        // Emitted right after the reply — the runner subscribed before spawn and buffers.
        pi.events.emit("subagent:async-complete", {
          id: basename(asyncDir),
          asyncDir,
          state: "complete",
        });
        return;
      }
      reply({
        success: false,
        error: { code: "not_found", message: `fake responder rejects ${request.method}` },
      });
    });
  };
}

test("tools: start_draft_review_wave threads the configured model over the primed context; collect drains", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // The configured draft-reviewer model must reach the wave as its workflow-level default.
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\ndraft-reviewer = "test-draft-model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: "{}" });
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    // The door primes; the module state is shared with the bound session's registration.
    primeDraftReviewContext({
      draftType: "plan",
      draft: "# The primed draft\n",
      custom: "check the rollback story",
    });
    const started = await h.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "scope"],
    });
    const startDetails = started.details as { ok: boolean; asyncId?: string; lanes?: string[] };
    assert.equal(startDetails.ok, true);
    assert.ok(startDetails.asyncId);
    assert.deepEqual(startDetails.lanes, ["grounding", "scope", "custom"]);
    // The tool-boundary threading pins: the configured model and the primed draft/custom both
    // reached the actual spawn (config → execute → startDraftReviewWave → adapter).
    assert.equal(sink.spawns.length, 1);
    assert.equal(sink.spawns[0]?.model, "test-draft-model");
    const script = sink.spawns[0]?.workflowScript ?? "";
    const lanes = JSON.parse(
      script.slice(script.indexOf("runs.all(") + "runs.all(".length, script.indexOf(");\nreturn")),
    ) as Array<{ key: string; agent: string; task: string }>;
    assert.deepEqual(
      lanes.map((lane) => lane.key),
      ["grounding", "scope", "custom"],
    );
    for (const lane of lanes) {
      assert.equal(lane.agent, "perk.draft-reviewer");
      assert.match(lane.task, /# The primed draft/);
      assert.match(lane.task, /Draft type: plan\./);
    }
    assert.match(lanes[2]?.task ?? "", /check the rollback story/);

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
    assert.deepEqual(details.covered, ["grounding", "scope", "custom"]);
    assert.equal(details.reports?.[0]?.report.angle, "grounding");
    assert.deepEqual(details.failures, []);
  } finally {
    clearDraftReviewContext();
    h.dispose();
  }
});

test("tools: start_draft_review_wave ignores an already-aborted per-call signal (the wave outlives the call)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    primeDraftReviewContext({ draftType: "plan", draft: "# The draft\n" });
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
    assert.equal(sink.spawns.length, 1, "the wave really spawned");
    // …and the detached wave outlives the aborted call: it stays pending and collectable.
    const collected = await h.invokeTool("collect_draft_review_wave", {});
    const details = collected.details as { ok: boolean; complete?: boolean; covered?: string[] };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["grounding", "risk"]);
  } finally {
    clearDraftReviewContext();
    h.dispose();
  }
});
