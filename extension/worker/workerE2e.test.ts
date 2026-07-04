// End-to-end worker tests: drive a FULL stage headlessly via the REAL runtime factory.
//
// Unlike `worker.test.ts` (which injects a hand-rolled `FakeSession` via `deps.createRuntime`), this
// tier drives a full `implement`/`address` stage through the production `defaultCreateRuntime` —
// real Pi session, the real `@mgiles/perk` extension loaded from a temp worktree's `.pi/settings.json`,
// the real bind/subscribe loop — driven by a FAUX pi-ai model that scripts the terminating tool
// calls, with NO live GitHub (the terminating tools' Python delegation is stubbed via PERK_BIN).
// Asserts both the structured run-event stream (§8.12) and the terminal `RunOutcome`
// (§8.11). Test-only: no worker/Python/contract change.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  type Api,
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
  type Model,
} from "@earendil-works/pi-ai";
import { AuthStorage } from "@earendil-works/pi-coding-agent";
import { type PlanRef, runEventsPath } from "../substrate/cache.ts";
import {
  fakePerkRouter,
  fauxModelRegistration,
  scaffoldWorkerWorktree,
} from "../testing/harness.ts";
import { type DriveStage, driveStage, type RunEvent } from "./worker.ts";

// Extension delivery is the PRODUCTION load path: `defaultCreateRuntime` layers disk settings
// (`SettingsManager.create(worktree, throwawayAgentDir)`), so the scaffold's `.pi/settings.json`
// `packages` list — the live checkout by absolute local path — is load-bearing. This tier is the
// offline pin of that resolution (local-path package ⇒ no npm ⇒ no network); `PI_OFFLINE=1` is set
// belt-and-suspenders so an accidental `npm:` entry would skip, not hit the network.

// Auth: the faux provider model carries `provider: "faux"`; the real runtime resolves an API key for it,
// so seed an in-memory key (no network — the faux provider ignores it).
const authStorage = () => AuthStorage.inMemory({ faux: { type: "api_key", key: "x" } });

/** A trailing idle message (D6): a continued loop never hits "no more faux responses queued". */
const idle = () => fauxAssistantMessage([fauxText("done")], { stopReason: "stop" });

const BUDGET = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

let runCounter = 0;

/** Drive a full stage through the real factory + a faux model; return outcome + captured events. */
async function runDrive(opts: {
  stage: DriveStage;
  responses: ReturnType<typeof fauxAssistantMessage>[];
  routes?: Record<string, { json: unknown; code?: number }>;
  initialPrompt?: string;
  planRef?: PlanRef;
  /** Settings `packages` override (e.g. `[]` for the no-extension-tools negative scenario). */
  packages?: string[];
  /** Use the production default NDJSON file sink (no injected array sink) and read it back. */
  fileSink?: boolean;
}) {
  const runId = `01JE2E${String(runCounter++).padStart(20, "0")}`;
  const cwd = scaffoldWorkerWorktree({
    runId,
    stage: opts.stage,
    planRef: opts.planRef,
    packages: opts.packages,
  });

  const savedEnv = new Map<string, string | undefined>();
  const setEnv = (key: string, value: string) => {
    savedEnv.set(key, process.env[key]);
    process.env[key] = value;
  };
  setEnv("PERK_RUN_ID", runId);
  setEnv("PERK_BIN", fakePerkRouter(cwd, opts.routes ?? {}));
  setEnv("PERK_NO_LLM", "1");
  setEnv("PI_OFFLINE", "1");

  const reg = await fauxModelRegistration();
  reg.setResponses(opts.responses);

  const events: RunEvent[] = [];
  try {
    const outcome = await driveStage(
      {
        worktree: cwd,
        stage: opts.stage,
        initialPrompt: opts.initialPrompt ?? `Drive the ${opts.stage} stage.`,
        model: reg.getModel() as unknown as Model<Api>,
        authStorage: authStorage(),
        budget: BUDGET,
      },
      // When `fileSink`, omit the array sink so the production default NDJSON file sink runs; then
      // parse it back into `events` (the default sink is a no-op unless PERK_RUN_ID is set, which it is).
      opts.fileSink ? {} : { eventSink: (e) => events.push(e) },
    );
    if (opts.fileSink) {
      for (const line of readFileSync(runEventsPath(cwd, runId), "utf8").trim().split("\n")) {
        events.push(JSON.parse(line) as RunEvent);
      }
    }
    return { outcome, events, cwd, runId };
  } finally {
    reg.unregister();
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

test("e2e: implement HAPPY — faux model calls submit → completed/submit_tool + full event stream", async () => {
  const { outcome, events } = await runDrive({
    stage: "implement",
    routes: implementHappyRoutes,
    responses: implementHappyResponses(),
  });

  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
  assert.deepEqual(outcome.pr, { number: 42, url: "https://github.com/x/pull/42" });
  assert.equal(outcome.error, null);

  const kinds = events.map((e) => e.kind);
  assert.equal(kinds[0], "run_started");
  assert.equal(kinds.at(-1), "run_finished");
  assert.ok(kinds.includes("step_marker"), "step markers were emitted");
  assertMonotonicSeq(events);

  // The WIP then DONE markers appear in textual appearance order.
  const markers = events.filter((e) => e.kind === "step_marker");
  assert.deepEqual(
    markers.map((m) => (m.kind === "step_marker" ? [m.marker, m.step] : null)),
    [
      ["wip", 1],
      ["done", 1],
    ],
  );

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

test("e2e: address HAPPY — resolve_review_threads ok → completed/address_resolved", async () => {
  const { outcome, events } = await runDrive({
    stage: "address",
    routes: {
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
          fauxToolCall("resolve_review_threads", {
            threads: [{ thread_id: "T1", comment: "done" }],
            pr: 42,
          }),
        ],
        { stopReason: "toolUse" },
      ),
      fauxAssistantMessage([fauxText("resolved")], { stopReason: "stop" }),
    ],
  });

  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "address_resolved");

  const resolve = events.find(
    (e) => e.kind === "tool_outcome" && e.tool === "resolve_review_threads",
  );
  assert.ok(resolve && resolve.kind === "tool_outcome" && resolve.ok === true, "resolve ran ok");
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

// --- Scenario 5: MODEL_ERROR -------------------------------------------------------------------

test("e2e: MODEL_ERROR — assistant message_end stopReason error → failed/model_error", async () => {
  const { outcome } = await runDrive({
    stage: "implement",
    responses: [
      fauxAssistantMessage([fauxText("")], { stopReason: "error", errorMessage: "overloaded" }),
    ],
  });

  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
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
