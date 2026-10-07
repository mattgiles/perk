// End-to-end worker tests: drive a FULL stage headlessly via the REAL runtime factory.
//
// Unlike `stageExecution.test.ts` (which injects a hand-rolled `FakeSession` via
// `deps.createRuntime`), this tier drives a full `implement`/`address` stage through the
// production `defaultCreateRuntime` —
// real Pi session, the real `@mgiles/perk` extension loaded from a temp worktree's `.pi/settings.json`,
// the real bind/subscribe loop — driven by a FAUX pi-ai model that scripts the terminating tool
// calls, with NO live GitHub (the terminating tools' Python delegation is stubbed via PERK_BIN).
// Asserts both the structured run-event stream (§8.12) and the terminal `RunOutcome`
// (§8.11). The model-selection scenarios plant a project-tier provider extension and drive a
// bare hermetic runtime, so registration really happens through the production order (services →
// selection → admission → construction). The model-accounting scenarios register a recording faux
// classifier on the injected runtime and plant model-using tools plus Pi's real codemode, pinning
// `budget.tokens` against Pi's own session census. The builtin-factory scenarios read the live
// session on a real request: the worker's own `tool_search`/`codemode` builtins (activation,
// opt-out, disable, replacement) and the absence of any MCP handler. The compaction and retry
// scenarios drive the settings-following behavior on real sessions: an in-drive compaction counted
// at its boundary, a project opt-out, a compaction that trips the token cap with no further
// provider request, and retried, exhausted and non-retryable provider errors.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { type TestContext, test } from "node:test";
import {
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
  getCurrentTools,
  isRetryableAssistantError,
} from "@earendil-works/pi-ai";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { agentScratchDir, type PlanRef, runEventsPath } from "../substrate/cache.ts";
import {
  bareModelRuntime,
  fakePerkRouter,
  fauxModelRuntime,
  plantMcpRegistrar,
  plantWorkerModelTools,
  plantWorkerProviderExtension,
  recordingClassifier,
  scaffoldWorkerWorktree,
} from "../testing/harness.ts";
import { MODEL_CALL_REFUSAL_PREFIX } from "./modelCallPolicy.ts";
// Test-side adapter import: the E2E tier mints the nominal request deliberately (an injected
// runtime + pattern ride the SAME production `defaultCreateRuntime` path).
import { type DriveRuntimeLike, defaultCreateRuntime, WorkerModelRequest } from "./sdkAdapter.ts";
import {
  type DriveBudget,
  type DriveStage,
  type RunEvent,
  type RunOutcome,
  runStage,
} from "./stageExecution.ts";

// Extension delivery is the PRODUCTION load path: `defaultCreateRuntime` layers disk settings
// (`SettingsManager.create(worktree, throwawayAgentDir)`), so the scaffold's `.pi/settings.json`
// `packages` list — the live checkout by absolute local path — is load-bearing. This tier is the
// offline pin of that resolution (local-path package ⇒ no npm ⇒ no network); `PI_OFFLINE=1` is set
// belt-and-suspenders so an accidental `npm:` entry would skip, not hit the network.

// Auth: by default the faux provider registers NATIVELY on a hermetic `ModelRuntime` (its apiKey
// auth always resolves as configured — no key, no network; see `fauxModelRuntime`) and the drive
// selects it with an explicit pattern. The model-selection scenarios instead pass a bare runtime
// (`bareModelRuntime`) and plant the provider as a project extension.

/** A trailing idle message (D6): a continued loop never hits "no more faux responses queued". */
const idle = () => fauxAssistantMessage([fauxText("done")], { stopReason: "stop" });

const BUDGET: DriveBudget = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

let runCounter = 0;

/**
 * The live-session slice the loaded-extension scenarios read (structural; Pi's `AgentSession`):
 * every registered tool with its provenance, and the runner's loaded extension paths (a builtin
 * loads as `builtin:<name>`). Test-side only — the worker's `DriveSessionLike` stays narrow.
 */
interface LiveSession {
  getAllTools(): { name: string; sourceInfo: { path: string; source: string } }[];
  extensionRunner: { getExtensionPaths(): string[] };
}

/** Drive a full stage through the real factory + a faux model; return outcome + captured events. */
async function runDrive(opts: {
  stage: DriveStage;
  /**
   * Scripted replies for the default faux runtime; a function reply receives the request context
   * (it may record it). Ignored when `model` is given (a planted provider scripts its own).
   */
  responses?: unknown[];
  routes?: Record<string, { json: unknown; code?: number }>;
  initialPrompt?: string;
  planRef?: PlanRef;
  /** Settings `packages` override (e.g. `[]` for the no-extension-tools negative scenario). */
  packages?: string[];
  /** Use the production default NDJSON file sink (no injected array sink) and read it back. */
  fileSink?: boolean;
  /** Capture cold-door command keys in invocation order. */
  captureArgv?: boolean;
  /** The drive budget (default: the generous `BUDGET`). */
  budget?: DriveBudget;
  /** The external abort signal threaded into `runStage`. */
  signal?: AbortSignal;
  /** Observe each event as the injected array sink receives it (e.g. to abort mid-drive). */
  onEvent?: (event: RunEvent) => void;
  /** Settings `defaultTools` for the scaffold (Pi's startup active-set preference). */
  defaultTools?: string[];
  /** Observe the PRODUCTION runtime (built by `defaultCreateRuntime`) once constructed. */
  onRuntime?: (runtime: DriveRuntimeLike) => void;
  /**
   * Receive the production runtime's session as the structural slice the loaded-extension
   * scenarios read (`LiveSession`). Read it only while the session lives — inside a scripted
   * response: `runStage` disposes the runtime before `runDrive` returns.
   */
  liveSession?: (session: LiveSession) => void;
  /**
   * The model request verbatim (runtime + optional `--model` pattern). Absent ⇒ the default faux
   * runtime selected by its explicit `provider/id` pattern.
   */
  model?: { runtime: ModelRuntime; pattern?: string };
  /** Extra project settings merged into the scaffold (e.g. `defaultProvider`/`defaultModel`). */
  extraSettings?: Record<string, unknown>;
  /** Plant a project-tier provider extension into the scaffold (`plantWorkerProviderExtension`). */
  plantProviders?: Parameters<typeof plantWorkerProviderExtension>[1];
  /** Plant the model-using tools / Pi's real codemode into the scaffold (`plantWorkerModelTools`). */
  plantModelTools?: Parameters<typeof plantWorkerModelTools>[1];
  /** Plant arbitrary project files into the scaffolded worktree before the drive. */
  plant?: (cwd: string) => void;
  /**
   * Called with the default faux runtime right after it is built (the `model`-absent path), so a
   * scenario can register its recording classifier on it before the drive.
   */
  onModelRuntime?: (modelRuntime: ModelRuntime) => void;
  /**
   * The default faux model's context window (the `model`-absent path). A small window lets a
   * long prompt cross Pi's compaction threshold offline.
   */
  contextWindow?: number;
}) {
  const runId = `01JE2E${String(runCounter++).padStart(20, "0")}`;
  const cwd = scaffoldWorkerWorktree({
    runId,
    stage: opts.stage,
    planRef: opts.planRef,
    packages: opts.packages,
    defaultTools: opts.defaultTools,
    extraSettings: opts.extraSettings,
  });
  if (opts.plantProviders !== undefined) plantWorkerProviderExtension(cwd, opts.plantProviders);
  if (opts.plantModelTools !== undefined) plantWorkerModelTools(cwd, opts.plantModelTools);
  opts.plant?.(cwd);

  const savedEnv = new Map<string, string | undefined>();
  const setEnv = (key: string, value: string) => {
    savedEnv.set(key, process.env[key]);
    process.env[key] = value;
  };
  const argvFile = join(cwd, "perk-argv.txt");
  setEnv("PERK_RUN_ID", runId);
  setEnv("PERK_BIN", fakePerkRouter(cwd, opts.routes ?? {}, opts.captureArgv ? { argvFile } : {}));
  setEnv("PI_OFFLINE", "1");
  // A per-drive global agent dir: nothing a drive resolves through `getAgentDir()` (sessions, a
  // factory's global-dir default) ever lands in the operator's real one.
  const globalAgentDir = mkdtempSync(join(tmpdir(), "perk-e2e-global-"));
  setEnv("PI_CODING_AGENT_DIR", globalAgentDir);

  let request: WorkerModelRequest;
  let providerCalls = (): number => 0;
  if (opts.model !== undefined) {
    request = new WorkerModelRequest({
      modelRuntime: opts.model.runtime,
      pattern: opts.model.pattern,
    });
  } else {
    const reg = await fauxModelRuntime(
      opts.contextWindow !== undefined ? { contextWindow: opts.contextWindow } : {},
    );
    opts.onModelRuntime?.(reg.modelRuntime);
    reg.setResponses(opts.responses ?? []);
    const model = reg.getModel() as { provider: string; id: string };
    request = new WorkerModelRequest({
      modelRuntime: reg.modelRuntime,
      pattern: `${model.provider}/${model.id}`,
    });
    providerCalls = () => reg.callCount();
  }

  const events: RunEvent[] = [];
  try {
    const outcome = await runStage(
      {
        worktree: cwd,
        stage: opts.stage,
        initialPrompt: opts.initialPrompt ?? `Drive the ${opts.stage} stage.`,
        model: request,
        budget: opts.budget ?? BUDGET,
        signal: opts.signal,
      },
      // When `fileSink`, omit the array sink so the production default NDJSON file sink runs; then
      // parse it back into `events` (the default sink is a no-op unless PERK_RUN_ID is set, which it is).
      {
        ...(opts.fileSink
          ? {}
          : {
              eventSink: (e: RunEvent) => {
                events.push(e);
                opts.onEvent?.(e);
              },
            }),
        ...(opts.onRuntime !== undefined || opts.liveSession !== undefined
          ? {
              createRuntime: async (o: { worktree: string; model?: WorkerModelRequest }) => {
                assert.ok(o.model !== undefined, "the E2E tier always passes its model request");
                const built = await defaultCreateRuntime(o.worktree, o.model);
                assert.ok(built.ok, "an observed runtime is never a selection refusal");
                opts.onRuntime?.(built.runtime);
                opts.liveSession?.(built.runtime.session as unknown as LiveSession);
                return built.runtime;
              },
            }
          : {}),
      },
    );
    if (opts.fileSink) {
      for (const line of readFileSync(runEventsPath(cwd, runId), "utf8").trim().split("\n")) {
        events.push(JSON.parse(line) as RunEvent);
      }
    }
    const argv = opts.captureArgv
      ? readFileSync(argvFile, "utf8").trim().split("\n").filter(Boolean)
      : [];
    return {
      outcome,
      events,
      cwd,
      runId,
      argv,
      providerCalls: providerCalls(),
      globalAgentDir,
    };
  } finally {
    // No global registry teardown needed: the faux provider lives on the per-run ModelRuntime.
    for (const [key, value] of savedEnv) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

/** Assert the captured event stream's `seq` is a monotonic 0..n run. */
function assertMonotonicSeq(events: RunEvent[]): void {
  events.forEach((e, i) => {
    assert.equal(e.seq, i, `seq[${i}] should be ${i}`);
  });
}

/** One scripted request as the live session saw it. */
interface LiveSnapshot {
  /** The tool names the request declared to the model. */
  declared: string[];
  /** Every registered tool's provenance, by name. */
  tools: Map<string, { path: string; source: string }>;
  /** The runner's loaded extension paths. */
  extensionPaths: string[];
}

/**
 * Observe the live session from inside scripted replies: pass `liveSession` to `runDrive`, wrap a
 * reply with `at(reply)` to snapshot that request (declared tools, registered provenance, loaded
 * extension paths) before replying, and read the snapshots after the drive.
 */
function observeLive(): {
  liveSession: (session: LiveSession) => void;
  at: (reply: unknown) => (context: { messages: never }) => unknown;
  snapshots: LiveSnapshot[];
  /** The first snapshot (asserts one was taken). */
  first: () => LiveSnapshot;
} {
  let live: LiveSession | undefined;
  const snapshots: LiveSnapshot[] = [];
  return {
    liveSession: (session) => {
      live = session;
    },
    at: (reply) => (context) => {
      assert.ok(live, "the live session was observed before the first request");
      snapshots.push({
        declared: getCurrentTools(context.messages).map((t) => t.name),
        tools: new Map(
          live
            .getAllTools()
            .map((t) => [t.name, { path: t.sourceInfo.path, source: t.sourceInfo.source }]),
        ),
        extensionPaths: live.extensionRunner.getExtensionPaths(),
      });
      return reply;
    },
    snapshots,
    first: () => {
      const first = snapshots[0];
      assert.ok(first, "the first request was observed");
      return first;
    },
  };
}

/** Record every `console.error` line for the rest of the test (the original still prints). */
function captureStderr(t: TestContext): () => string[] {
  const spy = t.mock.method(console, "error");
  return () => spy.mock.calls.map((call) => call.arguments.map(String).join(" "));
}

// --- Scenario 1: implement HAPPY (the load-bearing assumption) ----------------------------------

const implementHappyRoutes = {
  "pr submit": {
    json: {
      success: true,
      pr: { number: 42, url: "https://github.com/x/pull/42", is_draft: true, existed: false },
      branch: "b",
      issue: 148,
      plan_embedded: true,
    },
  },
};

const implementHappyResponses = () => [
  fauxAssistantMessage(
    [fauxText("begin [WIP:1] doing the work, then finish [DONE:1]"), fauxToolCall("submit", {})],
    { stopReason: "toolUse" as const },
  ),
  idle(),
];

/** The throwaway agentDir prefix `defaultCreateRuntime` mints under tmpdir (dispose removes it). */
function throwawayAgentDirs(): Set<string> {
  return new Set(readdirSync(tmpdir()).filter((name) => name.startsWith("perk-worker-agent-")));
}

test("e2e: implement HAPPY — faux model calls submit → completed/submit_tool + full event stream", async () => {
  const dirsBefore = throwawayAgentDirs();
  const { outcome, events, cwd, runId } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: implementHappyResponses(),
  });

  // The dispose-time removal: the drive's throwaway agentDir no longer exists afterwards (no
  // NEW perk-worker-agent-* entry survives the drive; pre-existing entries are outside scope).
  const leaked = [...throwawayAgentDirs()].filter((name) => !dirsBefore.has(name));
  assert.deepEqual(leaked, [], "the throwaway agentDir is removed at dispose");

  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
  assert.deepEqual(outcome.pr, { number: 42, url: "https://github.com/x/pull/42" });
  assert.equal(outcome.error, null);
  assert.equal(
    existsSync(agentScratchDir(cwd, runId)),
    true,
    "the production extension path provisioned agent scratch for the faux model turn",
  );

  const kinds = events.map((e) => e.kind);
  assert.equal(kinds[0], "run_started");
  assert.equal(kinds.at(-1), "run_finished");
  // The faux prose deliberately carries [WIP:1]/[DONE:1]: the REAL runtime path must emit none.
  assert.ok(!kinds.includes("step_marker"), "step markers are never emitted (deprecated)");
  assertMonotonicSeq(events);

  // A `submit` tool_outcome with ok:true.
  const submit = events.find((e) => e.kind === "tool_outcome" && e.tool === "submit");
  assert.ok(submit && submit.kind === "tool_outcome" && submit.ok === true, "submit ran ok");

  // Terminal run_finished carries the completed outcome.
  const finished = events.at(-1);
  assert.ok(finished?.kind === "run_finished" && finished.outcome.status === "completed");
});

test("e2e: implement HAPPY (file sink) — the production NDJSON sink writes the same stream shape", async () => {
  // Drive the SAME scenario with NO injected sink so the default `runEventsPath` NDJSON sink runs;
  // `runDrive({ fileSink: true })` reads it back into `events`.
  const { outcome, events } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: implementHappyResponses(),
    fileSink: true,
  });
  assert.equal(outcome.status, "completed");
  assert.equal(events[0]?.kind, "run_started");
  assert.equal(events.at(-1)?.kind, "run_finished");
  assert.ok(
    events.some((e) => e.kind === "tool_outcome" && e.tool === "submit" && e.ok === true),
    "the file sink captured the submit tool_outcome",
  );
  assertMonotonicSeq(events);
});

// --- Scenario 2: address HAPPY -----------------------------------------------------------------

test("e2e: address HAPPY — finalize_address ok → completed/address_resolved", async () => {
  const { outcome, events, argv } = await runDrive({
    stage: "address",
    captureArgv: true,
    routes: {
      "pr submit": {
        json: {
          success: true,
          pr: { number: 42, url: "https://github.com/x/pull/42", is_draft: false, existed: true },
          branch: "b",
          issue: 148,
          plan_embedded: true,
          base: "main",
          mergeable: true,
          conflicts: [],
        },
      },
      "pr resolve-threads": {
        // The full per-row contract shape — the decode is strict on comment_added.
        json: {
          success: true,
          results: [{ thread_id: "T1", success: true, comment_added: true, error: null }],
        },
      },
    },
    responses: [
      fauxAssistantMessage(
        [
          fauxToolCall("finalize_address", {
            threads: [{ thread_id: "T1", comment: "done" }],
            pr: 42,
          }),
        ],
        { stopReason: "toolUse" },
      ),
      fauxAssistantMessage([fauxText("finalized")], { stopReason: "stop" }),
    ],
  });

  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "address_resolved");
  assert.deepEqual(argv, ["pr submit", "pr resolve-threads"]);

  const finalize = events.find((e) => e.kind === "tool_outcome" && e.tool === "finalize_address");
  assert.ok(
    finalize && finalize.kind === "tool_outcome" && finalize.ok === true,
    "finalizer ran ok",
  );
  assertMonotonicSeq(events);
});

// --- Scenario 3: implement PREMATURE-IDLE ------------------------------------------------------

test("e2e: implement PREMATURE-IDLE — model goes idle without submit → failed/agent_idle_incomplete", async () => {
  const { outcome, events } = await runDrive({
    stage: "implement",
    responses: [
      fauxAssistantMessage([fauxText("I looked but did nothing")], { stopReason: "stop" }),
    ],
  });

  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
  assert.equal(outcome.error?.type, "incomplete");

  const kinds = events.map((e) => e.kind);
  assert.equal(kinds[0], "run_started");
  assert.equal(kinds.at(-1), "run_finished");
  assert.ok(!kinds.includes("tool_outcome"), "no tool ran on a premature-idle drive");
  assertMonotonicSeq(events);
});

// --- Scenario 4: FAILING-TOOL (route-don't-relay) -----------------------------------------------

test("e2e: FAILING-TOOL — submit fails → capped tool_outcome summary + failed/agent_idle_incomplete", async () => {
  const { outcome, events } = await runDrive({
    stage: "implement",
    routes: {
      "pr submit": {
        json: { success: false, error_type: "github_error", message: "X".repeat(5000) },
      },
    },
    responses: [
      fauxAssistantMessage([fauxToolCall("submit", {})], { stopReason: "toolUse" }),
      idle(),
    ],
  });

  const submit = events.find((e) => e.kind === "tool_outcome" && e.tool === "submit");
  assert.ok(submit && submit.kind === "tool_outcome", "a submit tool_outcome was emitted");
  if (submit.kind === "tool_outcome") {
    assert.equal(submit.ok, false);
    assert.ok(submit.summary, "a failure summary is present");
    assert.ok(
      submit.summary && submit.summary.length < 5000,
      "summary is capped (route-don't-relay)",
    );
    assert.ok(submit.summary?.includes("[Output truncated"), "carries the truncation notice");
  }

  // submit details.ok false ⇒ no completion.
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
});

// --- Scenario 5: MODEL_ERROR (non-retryable) ----------------------------------------------------
//
// A retryable error is retried per Pi's settings (the retry scenarios below); a non-retryable one
// ends the drive on its first turn.

test("e2e: MODEL_ERROR — a non-retryable provider error → failed/model_error, no retry", async () => {
  const observed = observeSessionEvents();
  const invalid = fauxAssistantMessage([fauxText("")], {
    stopReason: "error",
    errorMessage: "invalid request: malformed tool schema",
  });
  assert.equal(isRetryableAssistantError(invalid), false, "the scripted error is not retryable");
  const result = await runDrive({
    stage: "implement",
    responses: [invalid, idle()],
    onRuntime: observed.onRuntime,
  });
  const { outcome } = result;

  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.error?.type, "model_error");
  assert.equal(outcome.error?.message, "invalid request: malformed tool schema");
  assert.equal(result.providerCalls, 1, "never retried");
  assert.deepEqual(observed.ofType("auto_retry_start"), [], "Pi scheduled no retry");
  assert.equal(outcome.budget.turns, 1);
  assertAccounted(result, observed.runtime());
});

// --- Scenario 6: NO-EXTENSION-TOOLS (the terminating-tool preflight) -----------------------------

test("e2e: NO-EXTENSION-TOOLS — empty packages list → zero-turn failed/no_extension_tools", async () => {
  // A `.pi/settings.json` with `packages: []` resolves zero extensions — the silent-zero arm the
  // preflight exists for. Zero faux responses queued: the drive must fail BEFORE prompting.
  const { outcome, events } = await runDrive({
    stage: "implement",
    responses: [],
    packages: [],
  });

  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.error?.type, "no_extension_tools");
  assert.ok(outcome.error?.message.includes("submit"), "names the missing terminating tool");
  assert.equal(outcome.budget.turns, 0, "zero turns — the model never ran");

  assert.deepEqual(
    events.map((e) => e.kind),
    ["run_started", "run_finished"],
    "a well-formed zero-turn event pair",
  );
  assertMonotonicSeq(events);
});

// --- Scenario 7: EXTERNAL ABORT on the real runtime ---------------------------------------------
//
// `stageExecution.test.ts` covers the abort routes over a FakeSession; this is the real-runtime
// arm: the signal fires mid-drive (on the first `tool_outcome` — the first event after the entry
// sample) and the real `session.abort()` ends the prompt.

test("e2e: EXTERNAL-ABORT — a mid-drive abort ends the real session → aborted/external_abort", async () => {
  const controller = new AbortController();
  const { outcome, events } = await runDrive({
    stage: "implement",
    responses: [
      fauxAssistantMessage([fauxToolCall("read", { path: ".pi/settings.json" })], {
        stopReason: "toolUse",
      }),
      fauxAssistantMessage([fauxToolCall("submit", {})], { stopReason: "toolUse" }),
      idle(),
    ],
    routes: implementHappyRoutes,
    signal: controller.signal,
    onEvent: (event) => {
      if (event.kind === "tool_outcome") controller.abort();
    },
  });

  assert.equal(outcome.status, "aborted");
  assert.equal(outcome.terminal_signal, "external_abort");
  assert.equal(outcome.error?.type, "external_abort");
  assert.equal(outcome.pr, null);
  const tools = events.flatMap((e) => (e.kind === "tool_outcome" ? [e.tool] : []));
  assert.deepEqual(tools, ["read"], "the drive stopped before the scripted submit");
  // Asserted here, not in the sink: the emitter swallows a throwing sink by design.
  assert.ok(
    events.some((e) => e.kind === "tool_outcome" && e.ok),
    "the read executed",
  );
  assert.equal(events.at(-1)?.kind, "run_finished");
  assertMonotonicSeq(events);
});

// --- Scenario 8: BUDGET TRIP on the real runtime ------------------------------------------------

test("e2e: BUDGET — the turn cap trips the watchdog on the real session → budget_exhausted/budget", async () => {
  const maxTurns = 1;
  const { outcome, events, providerCalls } = await runDrive({
    stage: "implement",
    responses: [
      fauxAssistantMessage([fauxToolCall("read", { path: ".pi/settings.json" })], {
        stopReason: "toolUse",
      }),
      fauxAssistantMessage([fauxToolCall("submit", {})], { stopReason: "toolUse" }),
      idle(),
    ],
    routes: implementHappyRoutes,
    budget: { ...BUDGET, maxTurns },
  });

  assert.equal(outcome.status, "budget_exhausted");
  assert.equal(outcome.terminal_signal, "budget");
  assert.equal(outcome.error?.type, "budget");
  // Pi's agent loop does not re-check the abort signal between turns, so an abort on the cap's
  // turn_end alone would still start one more turn. The finishTurn gate ends the run AT the cap:
  // the counters stop there and the scripted second response is never requested.
  assert.equal(outcome.budget.turns, maxTurns);
  assert.equal(providerCalls, maxTurns, "no provider request past the cap");
  const tools = events.flatMap((e) => (e.kind === "tool_outcome" ? [e.tool] : []));
  assert.deepEqual(tools, ["read"], "no tool past the cap executed");
  assertMonotonicSeq(events);
});

// --- Model selection after extension registration -----------------------------------------------
//
// The worker resolves its model only after `createAgentSessionServices` loaded the worktree's
// project extensions and applied their provider / virtual-model registrations. Each scenario
// plants a project-tier provider extension (`plantWorkerProviderExtension`): a credential-gated
// faux native provider `ext-faux` scripted with the implement-HAPPY replies, plus an optional
// virtual model. Happy paths and `model_auth` drive a REAL bare runtime and assert only on the
// fixture provider; the order pins use a recording stub runtime because a real runtime's
// availability snapshot is ambient-sensitive (builtin providers resolve env keys).

const EXT_PROVIDER = "ext-faux";
const extProviders = (virtual?: {
  provider: string;
  id: string;
}): Parameters<typeof plantWorkerProviderExtension>[1] => ({
  provider: EXT_PROVIDER,
  models: ["m-1", "m-2"],
  ...(virtual !== undefined ? { virtual } : {}),
});

/**
 * A recording stub runtime (typed `as never` at the use site): logs every registration and every
 * availability-snapshot read into one ordered `calls` list, so the test can prove registration
 * happens BEFORE selection. `snapshot` overrides the (empty) availability read.
 */
function recordingStubRuntime(opts: { snapshot?: () => unknown[] } = {}) {
  const calls: string[] = [];
  const registered: string[] = [];
  const runtime = {
    registerProvider(name: string) {
      calls.push(`registerProvider:${name}`);
      registered.push(name);
    },
    registerNativeProvider(provider: { id: string }) {
      calls.push(`registerNativeProvider:${provider.id}`);
      registered.push(provider.id);
    },
    registerVirtualModel(definition: { provider: string; id: string }) {
      calls.push(`registerVirtualModel:${definition.provider}/${definition.id}`);
    },
    async refresh() {},
    getModels: () => [],
    getAvailableSnapshot: () => {
      calls.push("getAvailableSnapshot");
      return opts.snapshot ? opts.snapshot() : [];
    },
    getRegisteredProviderIds: () => [...registered],
    hasConfiguredAuth: () => false,
    checkAuth: async () => undefined,
  };
  return { runtime: runtime as never as ModelRuntime, calls };
}

/** The shared zero-turn refusal shape: the event pair, no turns, and no leaked agentDir. */
function assertZeroTurnRefusal(
  result: { outcome: Awaited<ReturnType<typeof runDrive>>["outcome"]; events: RunEvent[] },
  dirsBefore: Set<string>,
  errorType: string,
): void {
  const { outcome, events } = result;
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.error?.type, errorType);
  assert.ok((outcome.error?.summary.length ?? 0) > 0, "a non-empty capped summary");
  assert.equal(outcome.budget.turns, 0, "zero turns — the model never ran");
  assert.deepEqual(
    events.map((e) => e.kind),
    ["run_started", "run_finished"],
  );
  assertMonotonicSeq(events);
  const leaked = [...throwawayAgentDirs()].filter((name) => !dirsBefore.has(name));
  assert.deepEqual(leaked, [], "the throwaway agentDir is removed on a refusal");
}

/** The assistant message entries recorded on a session branch (provider/model as recorded). */
function assistantEntries(runtime: DriveRuntimeLike): { provider: string; model: string }[] {
  return runtime.session.sessionManager.getBranch().flatMap((entry) => {
    const e = entry as {
      type?: string;
      message?: { role?: string; provider?: string; model?: string };
    };
    return e.type === "message" && e.message?.role === "assistant"
      ? [{ provider: e.message.provider ?? "", model: e.message.model ?? "" }]
      : [];
  });
}

/** The live session's selection, read once the production runtime is constructed. */
interface ObservedSession {
  runtime: DriveRuntimeLike | undefined;
  model: string | undefined;
  thinkingLevel: string | undefined;
}

function observeSession(): { observed: ObservedSession; onRuntime: (r: DriveRuntimeLike) => void } {
  const observed: ObservedSession = {
    runtime: undefined,
    model: undefined,
    thinkingLevel: undefined,
  };
  return {
    observed,
    onRuntime: (runtime) => {
      const session = runtime.session as unknown as {
        model?: { provider: string; id: string };
        thinkingLevel?: string;
      };
      observed.runtime = runtime;
      observed.model = session.model ? `${session.model.provider}/${session.model.id}` : undefined;
      observed.thinkingLevel = session.thinkingLevel;
    },
  };
}

test("e2e: no_model is decided AFTER extension registration (order pin) → zero-turn failed/no_model", async () => {
  const dirsBefore = throwawayAgentDirs();
  const stub = recordingStubRuntime();
  const result = await runDrive({
    stage: "implement",
    packages: [],
    plantProviders: extProviders({ provider: "router", id: "auto" }),
    model: { runtime: stub.runtime },
  });
  assertZeroTurnRefusal(result, dirsBefore, "no_model");
  const firstRead = stub.calls.indexOf("getAvailableSnapshot");
  assert.ok(firstRead !== -1, "the availability snapshot was read");
  for (const registration of [
    `registerNativeProvider:${EXT_PROVIDER}`,
    "registerVirtualModel:router/auto",
  ]) {
    const at = stub.calls.indexOf(registration);
    assert.ok(at !== -1 && at < firstRead, `${registration} precedes the first snapshot read`);
  }
  assert.ok(
    result.outcome.error?.message.includes(EXT_PROVIDER),
    "the message names the extension-registered providers",
  );
});

test("e2e: a throwing availability read after services → zero-turn runtime_init, agentDir removed", async () => {
  const dirsBefore = throwawayAgentDirs();
  const stub = recordingStubRuntime({
    snapshot: () => {
      throw new Error("auth store unreadable");
    },
  });
  const result = await runDrive({
    stage: "implement",
    packages: [],
    plantProviders: extProviders(),
    model: { runtime: stub.runtime },
  });
  assertZeroTurnRefusal(result, dirsBefore, "runtime_init");
  assert.ok(result.outcome.error?.message.includes("auth store unreadable"), "names the cause");
});

test("e2e: explicit --model selects an extension-registered provider with a saved credential → completed", async () => {
  const { observed, onRuntime } = observeSession();
  const { outcome } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    plantProviders: extProviders(),
    model: {
      runtime: await bareModelRuntime({ credentials: { [EXT_PROVIDER]: "k" } }),
      pattern: `${EXT_PROVIDER}/m-2`,
    },
    onRuntime,
  });
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
  assert.equal(observed.model, `${EXT_PROVIDER}/m-2`);
  assert.ok(observed.runtime);
  const recorded = assistantEntries(observed.runtime);
  assert.ok(recorded.length > 0, "the branch recorded assistant messages");
  assert.deepEqual(recorded[0], { provider: EXT_PROVIDER, model: "m-2" });
});

test("e2e: default selection honours a saved non-first default from an extension provider → completed", async () => {
  // The old order failed `no_model` here (the provider did not exist yet); a first-available
  // fallback would have picked m-1.
  const { observed, onRuntime } = observeSession();
  const { outcome } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    plantProviders: extProviders(),
    extraSettings: { defaultProvider: EXT_PROVIDER, defaultModel: "m-2" },
    model: { runtime: await bareModelRuntime({ credentials: { [EXT_PROVIDER]: "k" } }) },
    onRuntime,
  });
  assert.equal(outcome.status, "completed");
  assert.equal(observed.model, `${EXT_PROVIDER}/m-2`);
});

test("e2e: an explicit model whose provider has no configured auth → zero-turn failed/model_auth", async () => {
  const dirsBefore = throwawayAgentDirs();
  const result = await runDrive({
    stage: "implement",
    packages: [],
    plantProviders: extProviders(),
    model: { runtime: await bareModelRuntime(), pattern: `${EXT_PROVIDER}/m-1` },
  });
  assertZeroTurnRefusal(result, dirsBefore, "model_auth");
  const message = result.outcome.error?.message ?? "";
  for (const fragment of [EXT_PROVIDER, "auth.json", "--model"]) {
    assert.ok(message.includes(fragment), `the guidance names ${fragment}`);
  }
});

test("e2e: an unknown explicit model → zero-turn failed/model_not_found", async () => {
  const dirsBefore = throwawayAgentDirs();
  const result = await runDrive({
    stage: "implement",
    packages: [],
    plantProviders: extProviders(),
    model: {
      runtime: await bareModelRuntime({ credentials: { [EXT_PROVIDER]: "k" } }),
      pattern: "nope/zzz",
    },
  });
  assertZeroTurnRefusal(result, dirsBefore, "model_not_found");
  assert.ok(result.outcome.error?.message.includes("nope/zzz"), "names the requested pattern");
});

test("e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp", () => {
  // A cold process through `extension/workerMain.ts` itself (no resolve hook — the real installed
  // SDK): the entry admits it, links the seam, and the explicit `--model` drive completes. A PATH
  // `pi` printing a below-floor version and a bogus CLI stamp change nothing — the worker reads
  // only the SDK it loaded. Minimal env: no operator credentials; the provider key lives in the
  // scratch agent dir's auth.json, read by the production `ModelRuntime.create()`.
  const runId = `01JE2E${String(runCounter++).padStart(20, "0")}`;
  const cwd = scaffoldWorkerWorktree({ runId, stage: "implement" });
  plantWorkerProviderExtension(cwd, extProviders());
  const agentDir = mkdtempSync(join(tmpdir(), "perk-e2e-global-"));
  writeFileSync(
    join(agentDir, "auth.json"),
    `${JSON.stringify({ [EXT_PROVIDER]: { type: "api_key", key: "k" } })}\n`,
    "utf8",
  );
  const bin = mkdtempSync(join(tmpdir(), "perk-e2e-bin-"));
  writeFileSync(join(bin, "pi"), "#!/bin/sh\necho 0.0.1\n", "utf8");
  chmodSync(join(bin, "pi"), 0o755);
  const childTmp = mkdtempSync(join(tmpdir(), "perk-e2e-tmp-"));
  const entry = resolve(import.meta.dirname, "..", "workerMain.ts");

  const result = spawnSync(
    process.execPath,
    [entry, "implement", "--worktree", cwd, "--model", `${EXT_PROVIDER}/m-2`],
    {
      env: {
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        HOME: mkdtempSync(join(tmpdir(), "perk-e2e-home-")),
        TMPDIR: childTmp,
        PERK_RUN_ID: runId,
        PERK_BIN: fakePerkRouter(cwd, implementHappyRoutes),
        PERK_CLI_VERSION: "9.9.9-not-real",
        PI_OFFLINE: "1",
        PI_CODING_AGENT_DIR: agentDir,
      },
      encoding: "utf8",
      timeout: 120_000,
    },
  );

  assert.equal(result.status, 0, result.stderr);
  const outcome = JSON.parse(result.stdout.trim().split("\n").at(-1) ?? "") as RunOutcome;
  assert.equal(outcome.run_id, runId);
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
  assert.deepEqual(outcome.pr, { number: 42, url: "https://github.com/x/pull/42" });
  assert.match(result.stderr, new RegExp(`perk worker: model ${EXT_PROVIDER}/m-2`));
  const events = readFileSync(runEventsPath(cwd, runId), "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as RunEvent);
  assert.equal(events[0]?.kind, "run_started");
  const last = events.at(-1);
  assert.ok(last?.kind === "run_finished");
  assert.deepEqual(last.outcome, outcome);
  assertMonotonicSeq(events);
  // The child's throwaway agent dir lived under ITS OWN TMPDIR and was removed at dispose.
  assert.deepEqual(
    readdirSync(childTmp).filter((name) => name.startsWith("perk-worker-agent-")),
    [],
  );
});

test("e2e: a virtual model routes to a physical target with a different identity → completed", async () => {
  const { observed, onRuntime } = observeSession();
  const { outcome } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    plantProviders: extProviders({ provider: "router", id: "auto" }),
    model: {
      runtime: await bareModelRuntime({ credentials: { [EXT_PROVIDER]: "k" } }),
      pattern: "router/auto",
    },
    onRuntime,
  });
  assert.equal(outcome.status, "completed");
  assert.equal(observed.model, "router/auto", "the selection names the virtual model");
  assert.ok(observed.runtime);
  const recorded = assistantEntries(observed.runtime);
  assert.ok(recorded.length > 0, "the branch recorded assistant messages");
  assert.deepEqual(
    recorded[0],
    { provider: EXT_PROVIDER, model: "m-1" },
    "the assistant message records the physical target",
  );
});

test("e2e: a `:thinking` suffix on --model survives the reorder → session thinking level applied", async () => {
  const { observed, onRuntime } = observeSession();
  const { outcome } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    plantProviders: extProviders(),
    model: {
      runtime: await bareModelRuntime({ credentials: { [EXT_PROVIDER]: "k" } }),
      pattern: `${EXT_PROVIDER}/m-1:high`,
    },
    onRuntime,
  });
  assert.equal(outcome.status, "completed");
  assert.equal(observed.model, `${EXT_PROVIDER}/m-1`);
  assert.equal(observed.thinkingLevel, "high");
});

// --- Tool-driven model usage: counted once, bounded at the worker's own boundaries --------------
//
// A recording faux classifier is registered on the drive's injected runtime (`onModelRuntime`);
// a planted extension supplies a model-using tool and/or Pi's REAL codemode
// (`plantWorkerModelTools`). Every scenario asserts the accounting identity against Pi's own
// census: `outcome.budget.tokens === getSessionStats().tokens.input + output`.

const CLASSIFIER = { provider: "faux-classifier", id: "clf-1" };
const REF = JSON.stringify(CLASSIFIER);
const CTX =
  '{ state: {}, questions: { q: { type: "bool", instructions: "x", criteria: { true: "t", false: "f" } } } }';

/** The session surfaces the accounting scenarios read (structural; Pi's `AgentSession`). */
interface CensusSession {
  getSessionStats(): { tokens: { input: number; output: number } };
  readonly cacheWarmingStatus: unknown;
  readonly autoCompactionEnabled: boolean;
  readonly autoRetryEnabled: boolean;
  subscribe(listener: (event: unknown) => void): () => void;
}

const censusSession = (runtime: DriveRuntimeLike): CensusSession =>
  runtime.session as unknown as CensusSession;

/** Pi's own census of the session's fresh work (input + output over every usage record). */
function piCensus(runtime: DriveRuntimeLike): number {
  const { tokens } = censusSession(runtime).getSessionStats();
  return tokens.input + tokens.output;
}

/** Σ input + output over the branch's message entries of `role`. */
function usageSum(runtime: DriveRuntimeLike, role: "assistant" | "toolResult"): number {
  let sum = 0;
  for (const entry of runtime.session.sessionManager.getBranch()) {
    const e = entry as {
      type?: string;
      message?: { role?: string; usage?: { input?: number; output?: number } };
    };
    if (e.type !== "message" || e.message?.role !== role) continue;
    sum += (e.message.usage?.input ?? 0) + (e.message.usage?.output ?? 0);
  }
  return sum;
}

const toolResultUsageSum = (runtime: DriveRuntimeLike): number => usageSum(runtime, "toolResult");
const assistantUsageSum = (runtime: DriveRuntimeLike): number => usageSum(runtime, "assistant");

/** A raw `tool_execution_update` slice (the codemode progress partials). */
interface ToolUpdate {
  toolName: string;
  partialResult?: { details?: { calls?: { name: string; status: string }[] } } & Record<
    string,
    unknown
  >;
}

/** An `onRuntime` that keeps the production runtime and records codemode progress partials. */
function observeAccounting(): {
  runtime: () => DriveRuntimeLike;
  updates: ToolUpdate[];
  onRuntime: (runtime: DriveRuntimeLike) => void;
  /**
   * Resolves once a codemode progress partial lists at least `n` `models.classify` rows. Codemode
   * publishes a call's row BEFORE the call waits for a limiter slot, so `n` rows means `n` calls
   * entered the limiter. Never rejects — race it against the drive.
   */
  classifyRows: (n: number) => Promise<void>;
} {
  let observed: DriveRuntimeLike | undefined;
  const updates: ToolUpdate[] = [];
  const waiters: { n: number; resolve: () => void }[] = [];
  const rowsIn = (update: ToolUpdate): number =>
    (update.partialResult?.details?.calls ?? []).filter((c) => c.name === "models.classify").length;
  const maxRows = (): number => Math.max(0, ...updates.map(rowsIn));
  return {
    runtime: () => {
      assert.ok(observed, "the production runtime was observed");
      return observed;
    },
    updates,
    onRuntime: (runtime) => {
      observed = runtime;
      censusSession(runtime).subscribe((event) => {
        const e = event as { type?: string } & ToolUpdate;
        if (e.type !== "tool_execution_update" || e.toolName !== "codemode") return;
        updates.push(e);
        const rows = rowsIn(e);
        for (const waiter of waiters.filter((w) => rows >= w.n)) {
          waiters.splice(waiters.indexOf(waiter), 1);
          waiter.resolve();
        }
      });
    },
    classifyRows: (n) =>
      maxRows() >= n ? Promise.resolve() : new Promise((resolve) => waiters.push({ n, resolve })),
  };
}

/** The `details.calls` rows of the branch's last codemode tool result (the script's final record). */
function codemodeResultCalls(runtime: DriveRuntimeLike): { name: string; status: string }[] {
  const results = runtime.session.sessionManager.getBranch().flatMap((entry) => {
    const e = entry as {
      type?: string;
      message?: {
        role?: string;
        toolName?: string;
        details?: { calls?: { name: string; status: string }[] };
      };
    };
    return e.type === "message" &&
      e.message?.role === "toolResult" &&
      e.message.toolName === "codemode"
      ? [e.message.details?.calls ?? []]
      : [];
  });
  return results.at(-1) ?? [];
}

/** The shared well-formedness + accounting identity every scenario here asserts. */
function assertAccounted(
  result: { outcome: Awaited<ReturnType<typeof runDrive>>["outcome"]; events: RunEvent[] },
  runtime: DriveRuntimeLike,
): void {
  assertMonotonicSeq(result.events);
  const finished = result.events.at(-1);
  assert.ok(finished?.kind === "run_finished", "a terminal run_finished");
  assert.deepEqual(finished.outcome, result.outcome);
  assert.equal(
    result.outcome.budget.tokens,
    piCensus(runtime),
    "budget.tokens equals Pi's own census (getSessionStats input + output)",
  );
}

/** A codemode tool call carrying `code`. */
const codemodeCall = (code: string) =>
  fauxAssistantMessage([fauxToolCall("codemode", { code })], { stopReason: "toolUse" as const });

const submitCall = () =>
  fauxAssistantMessage([fauxToolCall("submit", {})], { stopReason: "toolUse" as const });

const codemodeOutcomes = (events: RunEvent[]) =>
  events.flatMap((e) => (e.kind === "tool_outcome" && e.tool === "codemode" ? [e] : []));

test("e2e: MODEL-TOOL direct — a model-using tool's reported usage is counted once; warming off, compaction and retry on Pi's defaults", async () => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 700, output: 300 },
  });
  const observed = observeAccounting();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      fauxAssistantMessage([fauxToolCall("faux_classify_tool", {})], { stopReason: "toolUse" }),
      submitCall(),
      idle(),
    ],
    plantModelTools: { tool: CLASSIFIER },
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assert.deepEqual(
    classifier.calls,
    [{ seq: 1, abortedAtStart: false, stopReason: "stop", usage: { input: 700, output: 300 } }],
    "exactly one classifier request",
  );
  assert.equal(toolResultUsageSum(runtime), 1_000, "the tool result carries the classifier usage");
  assert.equal(
    result.outcome.budget.tokens - assistantUsageSum(runtime),
    1_000,
    "the budget counted the tool usage exactly once",
  );
  // No project compaction/retry keys in the scaffold: Pi's defaults, honoured by the worker.
  assertWorkerKnobs(runtime, { compaction: true, retry: true });
  assertAccounted(result, runtime);
});

test("e2e: MODEL-TOOL nested — a model-using tool called from a codemode script is counted once", async () => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 700, output: 300 },
  });
  const observed = observeAccounting();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      codemodeCall('await tools.faux_classify_tool({});\nreturn "ok";'),
      submitCall(),
      idle(),
    ],
    plantModelTools: { tool: CLASSIFIER, codemode: { models: false } },
    defaultTools: ["+codemode"],
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assert.equal(result.outcome.status, "completed");
  const outcomes = result.events.flatMap((e) =>
    e.kind === "tool_outcome" ? [{ tool: e.tool, ok: e.ok }] : [],
  );
  assert.ok(
    outcomes.some((o) => o.tool === "faux_classify_tool" && o.ok),
    "the nested tool_execution_end really fired (narrative only)",
  );
  assert.ok(
    outcomes.some((o) => o.tool === "codemode" && o.ok),
    "the script completed",
  );
  assert.equal(classifier.calls.length, 1);
  assert.equal(toolResultUsageSum(runtime), 1_000, "Pi folded the nested usage onto the script");
  assert.equal(
    result.outcome.budget.tokens - assistantUsageSum(runtime),
    1_000,
    "counted once — the nested end is never summed",
  );
  assertAccounted(result, runtime);
});

test("e2e: CODEMODE classify across the cap (test-only models:true) — counted once at turn_end, no further request, no usage on partials", async (t) => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 300_000, output: 100_000 },
    failCall: 3,
  });
  const stderr = captureStderr(t);
  const observed = observeAccounting();
  const live = observeLive();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      live.at(
        codemodeCall(
          `const m = models;\nfor (let i = 0; i < 5; i++) await m.classify(${REF}, ${CTX});\nreturn "ran";`,
        ),
      ),
      submitCall(),
      idle(),
    ],
    plantModelTools: { codemode: { models: true } },
    defaultTools: ["+codemode"],
    budget: BUDGET,
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const runtime = observed.runtime();
  // The planted (non-replaceable) project codemode REPLACES the worker's builtin, loudly.
  const first = live.first();
  assert.ok(
    first.tools.get("codemode")?.path.endsWith("worker-model-tools.ts"),
    "the active codemode is the project registration",
  );
  assert.ok(first.declared.includes("codemode"));
  assert.ok(!first.extensionPaths.includes("builtin:codemode"), "the builtin was not loaded");
  assert.ok(first.extensionPaths.includes("builtin:tool-search"), "only codemode was replaced");
  assert.ok(
    stderr().some(
      (line) =>
        line.startsWith("perk worker: extension warning — builtin:codemode: ") &&
        line.includes("built-in extension `codemode` was not loaded"),
    ),
    "the replacement warning reached stderr",
  );
  assert.equal(result.outcome.status, "budget_exhausted");
  assert.equal(result.outcome.terminal_signal, "budget");
  // No mid-script trip exists: all five ran although the cap was crossed during the third.
  assert.deepEqual(
    classifier.calls.map((c) => [c.stopReason, c.abortedAtStart]),
    [
      ["stop", false],
      ["stop", false],
      ["error", false],
      ["stop", false],
      ["stop", false],
    ],
  );
  assert.equal(toolResultUsageSum(runtime), 5 * 400_000, "the failed call's usage counts too");
  assert.equal(result.providerCalls, 1, "the gate ended the run: no provider request past the cap");
  assert.equal(result.outcome.budget.turns, 1);
  // The retirement-condition pin: progress partials carry call rows, never usage.
  assert.ok(
    observed.updates.some((u) => (u.partialResult?.details?.calls?.length ?? 0) > 0),
    "codemode published progress partials with call rows",
  );
  assert.ok(
    observed.updates.every((u) => u.partialResult === undefined || !("usage" in u.partialResult)),
    "no partial carries usage — when Pi starts reporting it, revisit WORKER_CODEMODE_MODELS",
  );
  assertAccounted(result, runtime);
});

/** Abort the drive once `barrier` resolves (never dangles: raced against the drive itself). */
async function abortOnBarrier(
  drive: Promise<Awaited<ReturnType<typeof runDrive>>>,
  barrier: Promise<void>,
  controller: AbortController,
): Promise<{ reached: boolean; result: Awaited<ReturnType<typeof runDrive>> }> {
  const reached = await Promise.race([barrier.then(() => true), drive.then(() => false)]);
  if (reached) controller.abort();
  return { reached, result: await drive };
}

test("e2e: mid-script EXTERNAL abort with a call in flight — the held call is aborted, no call starts after the abort", async () => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 7, output: 3 },
    hold: { from: 3, maxMs: 20_000 },
  });
  const observed = observeAccounting();
  const controller = new AbortController();
  const drive = runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      codemodeCall(
        `const m = models;\nfor (let i = 0; i < 50; i++) await m.classify(${REF}, ${CTX});`,
      ),
      submitCall(),
      idle(),
    ],
    plantModelTools: { codemode: { models: true } },
    defaultTools: ["+codemode"],
    signal: controller.signal,
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
  });
  const { reached, result } = await abortOnBarrier(drive, classifier.started(3), controller);
  const runtime = observed.runtime();
  assert.equal(reached, true, "the third call reached the provider before the abort");
  assert.equal(result.outcome.status, "aborted");
  assert.equal(result.outcome.terminal_signal, "external_abort");
  assert.deepEqual(
    classifier.calls.map((c) => [c.stopReason, c.abortedAtStart]),
    [
      ["stop", false],
      ["stop", false],
      ["aborted", false],
    ],
    "zero provider starts after the abort",
  );
  assert.equal(toolResultUsageSum(runtime), 20, "the completed calls' usage Pi retained counts");
  assert.deepEqual(
    codemodeOutcomes(result.events).map((o) => o.ok),
    [false],
    "the script ended aborted",
  );
  assert.equal(result.providerCalls, 1);
  assert.ok(result.outcome.budget.elapsed_ms < 10_000, "released by the abort, not the guard");
  assertAccounted(result, runtime);
});

test("e2e: mid-script WALL-CLOCK exhaustion — the watchdog aborts a running script", async () => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 7, output: 3 },
    delayMs: 50,
  });
  const observed = observeAccounting();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      codemodeCall(
        `const m = models;\nfor (let i = 0; i < 400; i++) await m.classify(${REF}, ${CTX});`,
      ),
      submitCall(),
      idle(),
    ],
    plantModelTools: { codemode: { models: true } },
    defaultTools: ["+codemode"],
    budget: { ...BUDGET, wallClockMs: 1_500 },
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assert.equal(result.outcome.status, "budget_exhausted");
  assert.equal(result.outcome.terminal_signal, "budget");
  // Timing-tolerant: how many calls ran depends on host load; the shape does not.
  const calls = classifier.calls;
  assert.ok(calls.length < 400, "the script was stopped");
  assert.equal(calls.filter((c) => c.abortedAtStart).length, 0, "no call started after the abort");
  assert.ok(calls.filter((c) => c.stopReason === "aborted").length <= 1, "at most one in flight");
  assert.ok(
    calls.every((c) => c.stopReason === "stop" || c.stopReason === "aborted"),
    "every other call completed normally",
  );
  assert.equal(result.providerCalls, 1);
  assert.ok(result.outcome.budget.elapsed_ms < 10_000, "far below the unaborted ~20 s");
  assertAccounted(result, runtime);
});

test("e2e: queued concurrency after an abort — the queued calls never reach the provider", async () => {
  const classifier = await recordingClassifier({
    ...CLASSIFIER,
    usage: { input: 7, output: 3 },
    hold: { from: 1, maxMs: 20_000 },
  });
  const observed = observeAccounting();
  const controller = new AbortController();
  const drive = runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      codemodeCall(
        `const m = models;\nawait Promise.all(Array.from({ length: 8 }, () => m.classify(${REF}, ${CTX})));`,
      ),
      submitCall(),
      idle(),
    ],
    plantModelTools: { codemode: { models: true } },
    defaultTools: ["+codemode"],
    signal: controller.signal,
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
  });
  // Abort only once all eight calls entered codemode's limiter (eight progress rows) AND its four
  // slots are full at the provider — so exactly four calls are queued when the abort lands.
  const { reached, result } = await abortOnBarrier(
    drive,
    Promise.all([classifier.started(4), observed.classifyRows(8)]).then(() => undefined),
    controller,
  );
  const runtime = observed.runtime();
  assert.equal(reached, true, "eight calls entered the limiter and four reached the provider");
  assert.equal(result.outcome.status, "aborted");
  assert.equal(result.outcome.terminal_signal, "external_abort");
  assert.deepEqual(
    classifier.calls.map((c) => [c.seq, c.stopReason, c.abortedAtStart]),
    [
      [1, "aborted", false],
      [2, "aborted", false],
      [3, "aborted", false],
      [4, "aborted", false],
    ],
    "only the four in-flight calls ever reached the provider; the four queued calls were refused",
  );
  const rows = codemodeResultCalls(runtime).filter((c) => c.name === "models.classify");
  assert.equal(rows.length, 8, "the script's record carries all eight calls");
  assert.ok(
    rows.every((c) => c.status !== "ok"),
    "no call completed",
  );
  assert.equal(toolResultUsageSum(runtime), 0);
  assertAccounted(result, runtime);
});

test("e2e: PRODUCTION SHAPE — the worker's own builtin codemode (models:WORKER_CODEMODE_MODELS) + the typed refusal; refusals are non-terminal", async () => {
  const classifier = await recordingClassifier({ ...CLASSIFIER, usage: { input: 7, output: 3 } });
  const observed = observeAccounting();
  const live = observeLive();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      live.at(
        codemodeCall('await models.generateImages({ provider: "x", id: "y" }, { input: [] });'),
      ),
      codemodeCall(`await models.classify(${REF}, ${CTX});`),
      codemodeCall(`const m = models;\nreturn await m.classify(${REF}, ${CTX});`),
      submitCall(),
      idle(),
    ],
    // A project extension that registers no codemode leaves the worker's builtin in place.
    plantModelTools: { tool: CLASSIFIER },
    defaultTools: ["+codemode"],
    onModelRuntime: (runtime) => runtime.registerNativeProvider(classifier.provider),
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const runtime = observed.runtime();
  const first = live.first();
  assert.deepEqual(
    first.tools.get("codemode"),
    { path: "builtin:codemode", source: "builtin" },
    "the active codemode is the worker's own builtin (WORKER_CODEMODE_MODELS)",
  );
  assert.ok(
    first.declared.includes("codemode"),
    "defaultTools activated it: declared on request 1",
  );
  assert.ok(first.declared.includes("faux_classify_tool"), "the project tool loaded beside it");
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  const outcomes = codemodeOutcomes(result.events);
  assert.deepEqual(
    outcomes.map((o) => o.ok),
    [false, false, false],
  );
  const [images, classify, aliased] = outcomes.map((o) => o.summary ?? "");
  assert.ok(images?.includes(`${MODEL_CALL_REFUSAL_PREFIX}image_generation)`), images);
  assert.ok(classify?.includes(`${MODEL_CALL_REFUSAL_PREFIX}classifier)`), classify);
  // The aliased call passes the advisory screen; the hard layer (no `models` global) holds.
  assert.ok(aliased?.includes("models") && aliased.includes("is not defined"), aliased);
  assert.equal(classifier.calls.length, 0, "no classifier request was ever made");
  assert.equal(toolResultUsageSum(runtime), 0);
  assertAccounted(result, runtime);
});

// --- Pi's builtin factories in the worker: discovery, codemode, and no MCP -----------------------
//
// The worker supplies Pi's `codemode` and `tool-search` builtins (CLI identity) beside its policy
// extension; configuration alone decides activation. Every live-session fact is read inside a
// scripted reply (`observeLive`), before `runStage` disposes the runtime.

/** The discovery family members eligible in the drivable read-write stages. */
const FAMILY = ["collect_review_wave", "push_annotations", "objective_stack_status"];

const BUILTIN_TOOL_SEARCH = { path: "builtin:tool-search", source: "builtin" };
const BUILTIN_CODEMODE = { path: "builtin:codemode", source: "builtin" };

test("e2e: discovery opt-in — the worker joins the cohort through its builtin tool_search; a search re-declares a deferred member", async () => {
  const observed = observeAccounting();
  const live = observeLive();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [
      live.at(
        fauxAssistantMessage([fauxToolCall("tool_search", { query: "objective stack status" })], {
          stopReason: "toolUse",
        }),
      ),
      live.at(submitCall()),
      idle(),
    ],
    defaultTools: ["+tool_search"],
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const [first, afterSearch] = live.snapshots;
  assert.ok(first && afterSearch, "both requests were observed");
  assert.deepEqual(first.tools.get("tool_search"), BUILTIN_TOOL_SEARCH);
  assert.ok(first.declared.includes("tool_search"), "the resolved defaultTools activated it");
  for (const name of FAMILY) {
    assert.ok(first.tools.has(name), `${name} is registered`);
    assert.ok(!first.declared.includes(name), `${name} is deferred: not declared on request 1`);
  }
  assert.deepEqual(first.tools.get("codemode"), BUILTIN_CODEMODE, "codemode is registered");
  assert.ok(!first.declared.includes("codemode"), "but not activated by this selection");

  const search = result.events.find((e) => e.kind === "tool_outcome" && e.tool === "tool_search");
  assert.ok(search?.kind === "tool_outcome" && search.ok, "tool_search ran ok");
  assert.ok(
    afterSearch.declared.includes("objective_stack_status"),
    "the search re-declared the deferred member on the next request",
  );
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assertAccounted(result, observed.runtime());
});

test("e2e: discovery opt-out (-tool_search) — the builtin is registered but inactive; the family stays declared", async () => {
  const observed = observeAccounting();
  const live = observeLive();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [live.at(submitCall()), idle()],
    defaultTools: ["-tool_search"],
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const first = live.first();
  assert.deepEqual(first.tools.get("tool_search"), BUILTIN_TOOL_SEARCH);
  assert.ok(!first.declared.includes("tool_search"), "opted out: not declared");
  for (const name of FAMILY) assert.ok(first.declared.includes(name), `${name} is declared`);
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assertAccounted(result, observed.runtime());
});

test("e2e: -builtin:<name> disables a worker builtin — neither loads, even when defaultTools names it", async () => {
  const observed = observeAccounting();
  const live = observeLive();
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [live.at(submitCall()), idle()],
    defaultTools: ["+tool_search", "+codemode"],
    extraSettings: { extensions: ["-builtin:tool-search", "-builtin:codemode"] },
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const first = live.first();
  assert.ok(
    first.extensionPaths.some((path) => path.includes("perk-worker-policy")),
    "the census surface works: the worker's policy extension is listed",
  );
  for (const path of ["builtin:tool-search", "builtin:codemode"]) {
    assert.ok(!first.extensionPaths.includes(path), `${path} is not loaded`);
  }
  assert.ok(!first.tools.has("tool_search") && !first.tools.has("codemode"), "neither registered");
  for (const name of FAMILY) assert.ok(first.declared.includes(name), `${name} is declared`);
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assertAccounted(result, observed.runtime());
});

test("e2e: the worker loads no builtin:mcp — .pi/mcp.json is inert and a project registerMcpServer is reported, never connected", async (t) => {
  const stderr = captureStderr(t);
  const observed = observeAccounting();
  const live = observeLive();
  const server = { command: process.execPath, args: ["-e", "process.exit(0)"] };
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [live.at(submitCall()), idle()],
    plant: (cwd) => {
      writeFileSync(
        join(cwd, ".pi", "mcp.json"),
        `${JSON.stringify({ mcpServers: { inert_file: server } }, null, 2)}\n`,
        "utf8",
      );
      plantMcpRegistrar(cwd);
    },
    onRuntime: observed.onRuntime,
    liveSession: live.liveSession,
  });
  const first = live.first();
  // The positive floor proves the census surface lists builtins at all.
  assert.ok(first.extensionPaths.includes("builtin:tool-search"));
  assert.ok(first.extensionPaths.includes("builtin:codemode"));
  assert.ok(!first.extensionPaths.includes("builtin:mcp"), "the worker supplies no MCP factory");
  assert.ok(
    first.extensionPaths.some((path) => path.endsWith("worker-mcp-registrar.ts")),
    "the registrar loaded",
  );
  assert.deepEqual(
    [...first.tools.keys()].filter((name) => name.startsWith("mcp__")),
    [],
    "no MCP tool is registered",
  );
  assert.deepEqual(
    first.declared.filter((name) => name.startsWith("mcp__")),
    [],
    "no MCP tool is declared",
  );
  const reports = stderr().filter((line) => line.startsWith("perk worker: extension error — "));
  assert.ok(
    reports.some((line) =>
      /worker-mcp-registrar\.ts \(register_mcp_server\): MCP server "inert" is registered, but no loaded extension connects MCP servers/.test(
        line,
      ),
    ),
    `the registration is reported legibly, not connected: ${JSON.stringify(reports)}`,
  );
  assert.ok(!reports.some((line) => line.includes("[object Object]")), "never [object Object]");
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  for (const name of ["mcp.log", "mcp-auth.json"]) {
    assert.equal(existsSync(join(result.globalAgentDir, name)), false, `no ${name} was written`);
  }
  assertAccounted(result, observed.runtime());
});

// --- Compaction and retry follow the settings, counted at their own boundaries -----------------
//
// The worker honours Pi's compaction and retry settings exactly like a warm session (the merged
// view of the throwaway global tier — warming off only — and the worktree's project settings).
// The compaction scenarios reuse the proven compactable recipe (a small faux context window, a
// long prompt, a large reserve and `keepRecentTokens: 0`, so Pi's estimate after the first
// request crosses the threshold and the next request is preceded by a real compaction); a router
// answers Pi's summarization requests so the lane script counts only the drive's own turns.

/** One raw agent-session event as the production session emitted it (type + payload). */
type RawSessionEvent = { type: string } & Record<string, unknown>;

/** An `onRuntime` that keeps the production runtime and records every raw session event in order. */
function observeSessionEvents(): {
  runtime: () => DriveRuntimeLike;
  events: RawSessionEvent[];
  ofType: (type: string) => RawSessionEvent[];
  onRuntime: (runtime: DriveRuntimeLike) => void;
} {
  let observed: DriveRuntimeLike | undefined;
  const events: RawSessionEvent[] = [];
  return {
    runtime: () => {
      assert.ok(observed, "the production runtime was observed");
      return observed;
    },
    events,
    ofType: (type) => events.filter((e) => e.type === type),
    onRuntime: (runtime) => {
      observed = runtime;
      censusSession(runtime).subscribe((event) => {
        events.push(event as RawSessionEvent);
      });
    },
  };
}

/** The branch's `compaction` entries with the summarization usage Pi persisted on each. */
function compactionEntries(
  runtime: DriveRuntimeLike,
): { usage?: { input?: number; output?: number } }[] {
  return runtime.session.sessionManager.getBranch().flatMap((entry) => {
    const e = entry as { type?: string; usage?: { input?: number; output?: number } };
    return e.type === "compaction" ? [e] : [];
  });
}

/** Σ input + output over the branch's compaction entries (Pi's census counts the same usage). */
function compactionUsageSum(runtime: DriveRuntimeLike): number {
  return compactionEntries(runtime).reduce(
    (sum, e) => sum + (e.usage?.input ?? 0) + (e.usage?.output ?? 0),
    0,
  );
}

/** Turn 1's fresh tokens: the first assistant message's `input + output` on the branch. */
function firstAssistantUsage(runtime: DriveRuntimeLike): number {
  for (const entry of runtime.session.sessionManager.getBranch()) {
    const e = entry as {
      type?: string;
      message?: { role?: string; usage?: { input?: number; output?: number } };
    };
    if (e.type === "message" && e.message?.role === "assistant") {
      return (e.message.usage?.input ?? 0) + (e.message.usage?.output ?? 0);
    }
  }
  assert.fail("the branch recorded no assistant message");
}

/** Pi's summarization system prompt — the marker every summarization request carries. */
const SUMMARIZATION_SYSTEM_MARKER = "You are a context summarization assistant.";

/**
 * Route faux requests: a summarization request (it carries Pi's summarization system prompt) gets
 * a fixed summary; every other request takes the next lane reply. An exhausted lane script
 * answers `"unexpected lane turn"` and is counted, never silently absorbed.
 */
function summarizationRouter(laneReplies: unknown[]): {
  responses: unknown[];
  summaries: () => number;
  laneRequests: () => number;
  unexpected: () => number;
} {
  const script = [...laneReplies];
  let summaries = 0;
  let laneRequests = 0;
  let unexpected = 0;
  const route = (context: { messages: unknown[] }) => {
    if (JSON.stringify(context.messages).includes(SUMMARIZATION_SYSTEM_MARKER)) {
      summaries++;
      return fauxAssistantMessage([fauxText("summary: the drive read its settings")]);
    }
    laneRequests++;
    const reply = script.shift();
    if (reply === undefined) {
      unexpected++;
      return fauxAssistantMessage([fauxText("unexpected lane turn")]);
    }
    return reply;
  };
  return {
    responses: Array.from({ length: 16 }, () => route),
    summaries: () => summaries,
    laneRequests: () => laneRequests,
    unexpected: () => unexpected,
  };
}

/** The worker's resolved knobs on the live session: warming always off; compaction/retry as set. */
function assertWorkerKnobs(
  runtime: DriveRuntimeLike,
  expected: { compaction: boolean; retry: boolean },
): void {
  const session = censusSession(runtime);
  assert.deepEqual(
    session.cacheWarmingStatus,
    { state: "inactive", reason: "cache warming disabled" },
    "Pi reports warming disabled for the worker session",
  );
  assert.equal(
    session.autoCompactionEnabled,
    expected.compaction,
    "auto-compaction follows settings",
  );
  assert.equal(session.autoRetryEnabled, expected.retry, "auto-retry follows settings");
}

/** The proven compactable drive: a long prompt in a small window with a large compaction reserve. */
const COMPACTION_WINDOW = 120_000;
const LONG_PROMPT = `Drive the implement stage.\n\n<draft>\n${"a draft line\n".repeat(9500)}</draft>`;
const COMPACTION_SETTINGS = { reserveTokens: 60_000, keepRecentTokens: 0 };

/** The compaction scenarios' lane: read a file, submit, go idle. */
const compactionLane = () => [
  fauxAssistantMessage([fauxToolCall("read", { path: ".pi/settings.json" })], {
    stopReason: "toolUse",
  }),
  submitCall(),
  idle(),
];

test("e2e: COMPACTS IN-DRIVE AND COMPLETES — a threshold compaction runs before the next request and is counted once", async (t) => {
  const stderr = captureStderr(t);
  const observed = observeSessionEvents();
  const router = summarizationRouter(compactionLane());
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: router.responses,
    initialPrompt: LONG_PROMPT,
    contextWindow: COMPACTION_WINDOW,
    extraSettings: { compaction: COMPACTION_SETTINGS },
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assert.ok(router.summaries() >= 1, "Pi summarized");
  // `submit` terminates the run, so the trailing idle reply is never requested.
  assert.equal(router.laneRequests(), 2);
  assert.equal(router.unexpected(), 0);
  assert.equal(result.providerCalls, 2 + router.summaries());

  assert.ok(observed.ofType("compaction_start").length >= 1, "a compaction started");
  const ends = observed.ofType("compaction_end");
  const threshold = ends.find((e) => e.reason === "threshold" && e.aborted === false);
  assert.ok(threshold, "a threshold compaction completed");
  const usage = (threshold.result as { usage?: { input?: number; output?: number } } | undefined)
    ?.usage;
  assert.ok((usage?.input ?? 0) + (usage?.output ?? 0) > 0, "the compaction reports usage");
  assert.ok(compactionEntries(runtime).length >= 1, "Pi persisted a compaction entry");
  const endAt = observed.events.indexOf(threshold);
  const submitAt = observed.events.findIndex(
    (e) => e.type === "tool_execution_end" && e.toolName === "submit",
  );
  assert.ok(submitAt !== -1 && endAt < submitAt, "the compaction ran in-drive, before submit");

  assert.equal(
    result.outcome.budget.tokens - assistantUsageSum(runtime) - toolResultUsageSum(runtime),
    compactionUsageSum(runtime),
    "the compaction's usage is counted exactly once",
  );
  assertAccounted(result, runtime);
  assert.ok(
    stderr().some((line) => line.startsWith("perk worker: compaction (threshold) — ")),
    "the compaction is legible on stderr",
  );
});

test("e2e: RETRY RECOVERS — a retryable provider error is retried and the drive completes", async (t) => {
  const stderr = captureStderr(t);
  const observed = observeSessionEvents();
  const overloaded = fauxAssistantMessage([fauxText("")], {
    stopReason: "error",
    errorMessage: "overloaded",
  });
  assert.equal(isRetryableAssistantError(overloaded), true, "the scripted error is retryable");
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [overloaded, submitCall(), idle()],
    extraSettings: { retry: { maxRetries: 2, baseDelayMs: 1 } },
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assert.equal(result.outcome.error, null);
  // The failed attempt and the retried `submit` (which terminates the run; the idle reply is
  // never requested).
  assert.equal(result.providerCalls, 2);
  assert.ok(
    observed.ofType("auto_retry_start").some((e) => e.attempt === 1),
    "Pi scheduled retry attempt 1",
  );
  assert.ok(
    observed.ofType("auto_retry_end").some((e) => e.success === true),
    "the retry succeeded",
  );
  assert.equal(result.outcome.budget.turns, 2, "the failed attempt counts as a turn");
  assert.ok(
    stderr().includes("perk worker: auto-retry 1/2 in 1 ms — overloaded"),
    "the retry is legible on stderr",
  );
  assertAccounted(result, runtime);
});

test("e2e: PROJECT OPT-OUT HONOURED — compaction.enabled false in the project settings → no compaction", async () => {
  const observed = observeSessionEvents();
  const router = summarizationRouter(compactionLane());
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: router.responses,
    initialPrompt: LONG_PROMPT,
    contextWindow: COMPACTION_WINDOW,
    extraSettings: { compaction: { enabled: false, ...COMPACTION_SETTINGS } },
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  assertWorkerKnobs(runtime, { compaction: false, retry: true });
  // The control for the compaction scenario: the same drive compacts only when settings allow.
  assert.equal(router.summaries(), 0, "Pi never summarized");
  assert.deepEqual(observed.ofType("compaction_start"), []);
  assert.deepEqual(compactionEntries(runtime), []);
  assert.equal(result.outcome.status, "completed");
  assert.equal(result.outcome.terminal_signal, "submit_tool");
  assert.equal(result.providerCalls, 2);
  assertAccounted(result, runtime);
});

// Measured on the compaction drive (stable run to run): turn 1 carries 43 805 fresh tokens and its
// compaction 31 613, so a cap inside (43 805, 75 418] survives turn 1 and trips on the compaction.
// The scenario re-validates the window against the live numbers every run: drift fails loudly.
const COMPACTION_TRIP_MAX_TOKENS = 60_000;

test("e2e: COMPACTION TRIPS THE TOKEN CAP — the run ends at the compaction boundary with zero further provider requests", async () => {
  const observed = observeSessionEvents();
  const router = summarizationRouter(compactionLane());
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: router.responses,
    initialPrompt: LONG_PROMPT,
    contextWindow: COMPACTION_WINDOW,
    extraSettings: { compaction: COMPACTION_SETTINGS },
    budget: { ...BUDGET, maxTokens: COMPACTION_TRIP_MAX_TOKENS },
    onRuntime: observed.onRuntime,
  });
  const runtime = observed.runtime();
  const turn1 = firstAssistantUsage(runtime);
  const compaction = compactionUsageSum(runtime);
  assert.ok(
    turn1 < COMPACTION_TRIP_MAX_TOKENS && COMPACTION_TRIP_MAX_TOKENS <= turn1 + compaction,
    `the cap must land on the compaction: turn 1 ${turn1}, compaction ${compaction}`,
  );
  assert.equal(result.outcome.status, "budget_exhausted");
  assert.equal(result.outcome.terminal_signal, "budget");
  assert.equal(compactionEntries(runtime).length, 1);
  assert.ok(router.summaries() >= 1);
  // The no-new-call bar at the compaction boundary: the lane's second request never reached the
  // provider — every provider call is turn 1 or the compaction's own summarization.
  assert.equal(router.laneRequests(), 1);
  assert.equal(result.providerCalls, 1 + router.summaries());
  assert.equal(router.unexpected(), 0);
  assert.ok(
    !result.events.some((e) => e.kind === "tool_outcome" && e.tool === "submit"),
    "submit never ran",
  );
  // The agent loop still reaches its request step after the trip; the aborted signal makes pi-ai
  // refuse the request before dispatch (the provider count above did not move), and the loop
  // records the refusal as a zero-usage error turn — counted like every turn_end.
  const turns = observed.ofType("turn_end").map((e) => {
    const message = e.message as {
      stopReason?: string;
      usage?: { input?: number; output?: number };
    };
    return [message.stopReason, (message.usage?.input ?? 0) + (message.usage?.output ?? 0)];
  });
  assert.deepEqual(turns, [
    ["toolUse", turn1],
    ["error", 0],
  ]);
  assert.equal(result.outcome.budget.turns, 2);
  assert.equal(result.outcome.budget.tokens, turn1 + compaction, "turn 1 plus the compaction");
  assertAccounted(result, runtime);
});

test("e2e: RETRIES EXHAUSTED — the last unrecovered error is terminal → failed/model_error", async () => {
  const observed = observeSessionEvents();
  const overloaded = () =>
    fauxAssistantMessage([fauxText("")], { stopReason: "error", errorMessage: "overloaded" });
  const result = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: [overloaded(), overloaded(), idle()],
    extraSettings: { retry: { maxRetries: 1, baseDelayMs: 1 } },
    onRuntime: observed.onRuntime,
  });
  assert.equal(result.outcome.status, "failed");
  assert.equal(result.outcome.terminal_signal, "model_error");
  assert.equal(result.outcome.error?.message, "overloaded");
  assert.equal(result.providerCalls, 2, "the first attempt and its one retry");
  assert.ok(
    observed.ofType("auto_retry_end").some((e) => e.success === false),
    "Pi gave up",
  );
  assert.equal(result.outcome.budget.turns, 2);
  assertAccounted(result, observed.runtime());
});
