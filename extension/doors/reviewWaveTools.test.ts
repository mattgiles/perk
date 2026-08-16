// Tests for the review-wave tool pair (registered live in `extension/index.ts`). The strict
// decoder is pinned directly; the start/collect execute cores are driven through the injected
// in-memory adapter (the `executeLearnWave` test posture — no session needed); registration +
// the real tool-boundary threading (config model → spawn, decode refusal, launch → collect
// round-trip) run against a REAL bound session via the T1 harness (the harness binds perk's
// extension, so the pair is present) with a fake pi-subagents RPC responder on pi.events.
// Offline like everything here.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PERK_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import type { AdversarialReviewAngle } from "../waves/adversarialReviewWave.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";
import {
  decodeStartReviewWaveParams,
  executeCollectReviewWave,
  executeStartReviewWave as executeStartReviewWaveBase,
  registerReviewWaveTools,
  WAVE_COLLECT_GRACE_MS,
} from "./reviewWaveTools.ts";

const TWO_ANGLES: AdversarialReviewAngle[] = ["claimed-intent", "correctness"];
const PREFLIGHT_OK = async () => ({ ok: true }) as const;
const executeStartReviewWave = (...args: Parameters<typeof executeStartReviewWaveBase>) =>
  executeStartReviewWaveBase(args[0], args[1], {
    ...args[2],
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

/** Reset the module's pending-wave state (a fresh registration is a fresh session). */
function resetState(): void {
  registerReviewWaveTools(fakePi().pi);
}

const START_OPTS = { angles: TWO_ANGLES, pr: 42, worktree: "/abs/wt" };

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
  resetState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const result = await executeStartReviewWave(adapter, target, START_OPTS);
  assert.equal(result.details.ok, true);
  const details = result.details as {
    asyncId?: string;
    asyncDir?: string;
    angles?: string[];
  };
  assert.equal(details.asyncId, "wave-async-1");
  assert.equal(details.asyncDir, "/memory/wave-async-1");
  assert.deepEqual(details.angles, ["claimed-intent", "correctness", "ponytail"]);
  const text = result.content[0]?.text ?? "";
  assert.match(text, /claimed-intent, correctness/);
  assert.match(text, /subagent_wait/);
  assert.match(text, /collect_review_wave/);

  // The pending wave is stored: a second start refuses with wave_active…
  const second = await executeStartReviewWave(adapter, target, START_OPTS);
  assert.equal(second.details.ok, false);
  assert.equal((second.details as { error_type?: string }).error_type, "wave_active");
  assert.match(second.content[0]?.text ?? "", /collect_review_wave first/);

  // …and collect drains it (clearing pending — a following collect is no_wave).
  const collected = await executeCollectReviewWave(target);
  assert.equal(collected.details.ok, true);
  const drained = await executeCollectReviewWave(target);
  assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
});

test("executeStartReviewWave: a launch failure soft-fails with the wave reason and the attempt receipt", async () => {
  resetState();
  const { target, notified } = fakeTarget();
  const unavailable = await executeStartReviewWave(
    createMemoryWaveAdapter({ ping: null }),
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
    createMemoryWaveAdapter({ spawnError: "no session" }),
    target,
    START_OPTS,
  );
  assert.equal((spawnFailed.details as { error_type?: string }).error_type, "spawn-failed");
  assert.match((spawnFailed.details as { error?: string }).error ?? "", /no session/);
});

test("executeCollectReviewWave: no_wave without a launch; wave_running retains the pending wave", async () => {
  resetState();
  const { target } = fakeTarget();
  const none = await executeCollectReviewWave(target);
  assert.equal(none.details.ok, false);
  assert.equal((none.details as { error_type?: string }).error_type, "no_wave");
  assert.match(none.content[0]?.text ?? "", /start_review_wave/);

  // Launch a wave that never completes on its own; an early collect (tiny injected grace)
  // soft-fails wave_running and RETAINS the pending wave.
  const adapter = createMemoryWaveAdapter({
    completion: false,
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  const start = await executeStartReviewWave(adapter, target, START_OPTS);
  assert.equal(start.details.ok, true);
  const running = await executeCollectReviewWave(target, { graceMs: 20 });
  assert.equal(running.details.ok, false);
  assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
  assert.match(running.content[0]?.text ?? "", /keep looping subagent_wait/);

  // Once the run completes, the retained wave collects normally.
  adapter.emitCompletion({ asyncId: "wave-async-1", asyncDir: "/memory/wave-async-1" });
  const collected = await executeCollectReviewWave(target, { graceMs: 1_000 });
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

test("executeCollectReviewWave: an incomplete wave is an ok result with the loud warning", async () => {
  resetState();
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
  await executeStartReviewWave(adapter, target, START_OPTS);
  const collected = await executeCollectReviewWave(target);
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

test("WAVE_COLLECT_GRACE_MS: the module default with the env override (the waveTimeoutMs idiom)", async () => {
  assert.equal(WAVE_COLLECT_GRACE_MS, 15_000);
  resetState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({ completion: false });
  // Bound the never-completing wave's module timeout so its timer never outlives the test
  // (the settled-by-timeout result also proves an uncollected wave never rejects unhandled).
  process.env.PERK_WAVE_TIMEOUT_MS = "200";
  process.env.PERK_WAVE_COLLECT_GRACE_MS = "20";
  try {
    await executeStartReviewWave(adapter, target, START_OPTS);
    // No injected graceMs: the env override keeps the never-completing wave from stalling 15s.
    const running = await executeCollectReviewWave(target);
    assert.equal((running.details as { error_type?: string }).error_type, "wave_running");
    // After the module timeout fires, the retained wave drains into the timeout failure.
    const drained = await executeCollectReviewWave(target, { graceMs: 2_000 });
    assert.equal(drained.details.ok, true);
    const details = drained.details as { complete?: boolean; failures?: { reason: string }[] };
    assert.equal(details.complete, false);
    assert.equal(details.failures?.[0]?.reason, "timeout");
  } finally {
    delete process.env.PERK_WAVE_TIMEOUT_MS;
    delete process.env.PERK_WAVE_COLLECT_GRACE_MS;
    resetState();
  }
});

// --- registration -----------------------------------------------------------------------------

test("registerReviewWaveTools registers exactly the two tools and resets the pending state", async () => {
  // Seed a pending wave through the core…
  resetState();
  const { target } = fakeTarget();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry("claimed-intent"), okEntry("correctness"), okEntry("ponytail")],
    },
  });
  await executeStartReviewWave(adapter, target, START_OPTS);

  // …then a fresh registration wipes it (a fresh registration is a fresh session).
  const { pi, tools } = fakePi();
  registerReviewWaveTools(pi);
  assert.deepEqual(
    [...tools.keys()].sort(),
    ["collect_review_wave", "start_review_wave"],
    "exactly the two flow-scoped tools",
  );
  const cleared = await executeCollectReviewWave(target);
  assert.equal((cleared.details as { error_type?: string }).error_type, "no_wave");

  // Both promptGuidelines carry the relay-loop discipline.
  const startDef = tools.get("start_review_wave");
  const collectDef = tools.get("collect_review_wave");
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
  registerReviewWaveTools(pi);
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

/** The spawn params the fake responder observes (the tool-boundary threading assertions). */
interface SpawnSink {
  spawns: { workflowScript?: string; model?: string; outputSchema?: unknown }[];
}

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
 * A fake pi-subagents responder bound as a bus peer (the prReview.test.ts idiom): answers
 * ping/spawn on `pi.events` with the v1 envelope, writes a terminal `status.json` carrying one
 * schema-valid adversarial report per lane into a real temp `asyncDir`, and emits the advertised
 * completion event. Offline like everything here.
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
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-review-wave-e2e-"));
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
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    const started = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "quality"],
      pr: 42,
      worktree: "/abs/wt",
      directive: "focus on the workflow edits",
    });
    const startDetails = started.details as { ok: boolean; asyncId?: string; angles?: string[] };
    assert.equal(startDetails.ok, true);
    assert.ok(startDetails.asyncId);
    assert.deepEqual(startDetails.angles, ["claimed-intent", "quality", "ponytail"]);
    // The tool-boundary threading pins: the configured model and the directive both reached the
    // actual spawn (config → execute → startAdversarialReviewWave → adapter).
    assert.equal(sink.spawns.length, 1);
    assert.equal(sink.spawns[0]?.model, "test-adv-model");
    const script = sink.spawns[0]?.workflowScript ?? "";
    const lanes = JSON.parse(
      script.slice(script.indexOf("runs.all(") + "runs.all(".length, script.indexOf(");\nreturn")),
    ) as Array<{ key: string; agent: string; task: string; skill?: string }>;
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

test("tools: start_review_wave ignores an already-aborted per-call signal (the wave outlives the call)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakeSubagentsResponder(sink)],
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
    assert.equal(sink.spawns.length, 1, "the wave really spawned");
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
