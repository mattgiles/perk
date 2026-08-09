// Fully-offline coverage for the headless stage-drive primitive: the pure helpers
// (evaluateTerminal/assembleOutcome/applyEvent/initialPromptFor), the budget/abort watchdog and the
// happy-path drive via an INJECTED runtime (no model turn / network ever), the bind/rebind
// structural contract, the cross-plane prompt-parity invariant (reciprocal of
// tests/test_worker_prompt_parity.py), and the Gap-4 verification (a throwaway agentDir still loads
// + binds the project `@mgiles/perk` extension, with the `session_start` claim engaging). See worker.ts.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { PlanRef } from "../substrate/cache.ts";
import { planRefPath, runEventsPath, workflowDir } from "../substrate/cache.ts";
import { readSessionPointers } from "../substrate/sessionPointers.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  applyEvent,
  assembleOutcome,
  assistantText,
  budgetTripped,
  createBindManager,
  createEventEmitter,
  type DriveCounters,
  type DriveEvent,
  type DriveRuntimeLike,
  type DriveSessionLike,
  driveStage,
  evaluateTerminal,
  extractStepMarkers,
  freshCounters,
  initialPromptFor,
  initialPromptForWorktree,
  missingTerminatingTool,
  type RunEvent,
  resolveAuth,
  resolveWorkerModel,
  toolOutcomeOf,
} from "./worker.ts";

// The cross-plane prompt-parity invariant: these substrings MUST appear in BOTH the TS
// `initialPromptFor` output and the Python `perk/run/launch.py` prompts. The same literals live in
// tests/test_worker_prompt_parity.py, so drift in EITHER plane fails CI.
// The linear plan-read instruction — keep in lockstep with LINEAR_READ_SUBSTRINGS in
// tests/test_worker_prompt_parity.py (the literal fragments of the shared linear arm).
const LINEAR_READ_SUBSTRINGS = [
  "use the `linear_get_issue` tool",
  "then `linear_list_comments`",
  "the plan body is the first comment",
  "if the linear tools are unavailable, open ",
];
const samplePlanRef: PlanRef = {
  provider: "github",
  pr_id: "148",
  url: "https://github.com/mattgiles/perk/issues/148",
  labels: [],
  objective_id: "137",
};

// --- pure: evaluateTerminal ---------------------------------------------------------------------

test("evaluateTerminal: implement with a successful submit → completed/submit_tool + pr", () => {
  const v = evaluateTerminal({
    stage: "implement",
    submitDetails: { ok: true, pr: { number: 7, url: "https://x/pr/7" } },
    resolveSucceeded: false,
    lastReviewBatchPresent: false,
    modelError: null,
  });
  assert.equal(v.status, "completed");
  assert.equal(v.terminal_signal, "submit_tool");
  assert.deepEqual(v.pr, { number: 7, url: "https://x/pr/7" });
  assert.equal(v.errorMessage, null);
});

test("evaluateTerminal: implement with an unmergeable PR → failed/agent_idle_incomplete", () => {
  const v = evaluateTerminal({
    stage: "implement",
    submitDetails: { ok: true, pr: { number: 7, url: "https://x/pr/7" }, mergeable: false },
    resolveSucceeded: false,
    lastReviewBatchPresent: false,
    modelError: null,
  });
  assert.equal(v.status, "failed");
  assert.equal(v.terminal_signal, "agent_idle_incomplete");
  assert.equal(v.pr, null);
  assert.match(v.errorMessage ?? "", /unmergeable PR \(merge conflicts unresolved\)/);
});

test("evaluateTerminal: implement with mergeable true/null/absent → completed", () => {
  for (const mergeable of [true, null, undefined]) {
    const v = evaluateTerminal({
      stage: "implement",
      submitDetails: { ok: true, pr: { number: 7, url: "https://x/pr/7" }, mergeable },
      resolveSucceeded: false,
      lastReviewBatchPresent: false,
      modelError: null,
    });
    assert.equal(v.status, "completed", `mergeable=${mergeable} → completed`);
    assert.equal(v.terminal_signal, "submit_tool");
  }
});

test("evaluateTerminal: implement idle without a PR → failed/agent_idle_incomplete", () => {
  const v = evaluateTerminal({
    stage: "implement",
    submitDetails: null,
    resolveSucceeded: false,
    lastReviewBatchPresent: false,
    modelError: null,
  });
  assert.equal(v.status, "failed");
  assert.equal(v.terminal_signal, "agent_idle_incomplete");
  assert.equal(v.pr, null);
  assert.equal(v.errorType, "incomplete");
});

test("evaluateTerminal: implement with submit ok:false → failed/agent_idle_incomplete", () => {
  const v = evaluateTerminal({
    stage: "implement",
    submitDetails: { ok: false, error: "boom" },
    resolveSucceeded: false,
    lastReviewBatchPresent: false,
    modelError: null,
  });
  assert.equal(v.status, "failed");
  assert.equal(v.terminal_signal, "agent_idle_incomplete");
});

test("evaluateTerminal: address resolved + last_review_batch → completed/address_resolved", () => {
  const v = evaluateTerminal({
    stage: "address",
    submitDetails: null,
    resolveSucceeded: true,
    lastReviewBatchPresent: true,
    modelError: null,
  });
  assert.equal(v.status, "completed");
  assert.equal(v.terminal_signal, "address_resolved");
  assert.equal(v.pr, null);
});

test("evaluateTerminal: address resolved but no last_review_batch → failed", () => {
  const v = evaluateTerminal({
    stage: "address",
    submitDetails: null,
    resolveSucceeded: true,
    lastReviewBatchPresent: false,
    modelError: null,
  });
  assert.equal(v.status, "failed");
  assert.equal(v.terminal_signal, "agent_idle_incomplete");
});

test("evaluateTerminal: a model error wins over the stage predicate", () => {
  const v = evaluateTerminal({
    stage: "implement",
    submitDetails: { ok: true, pr: { number: 7, url: "https://x/pr/7" } },
    resolveSucceeded: false,
    lastReviewBatchPresent: false,
    modelError: { message: "overloaded" },
  });
  assert.equal(v.status, "failed");
  assert.equal(v.terminal_signal, "model_error");
  assert.equal(v.errorMessage, "overloaded");
});

// --- pure: assembleOutcome ----------------------------------------------------------------------

// LOCKSTEP LITERAL (contracts.md §8.11/§8.38): the completed RunOutcome asserted below is pinned
// byte-identically in tests/test_run_report.py (_COMPLETED_OUTCOME_LOCKSTEP), which feeds it
// through the Python remote reporter — a field rename here must break that suite too. Change
// BOTH suites together.
test("assembleOutcome: completed has error:null and the frozen shape", () => {
  const outcome = assembleOutcome({
    stage: "implement",
    verdict: {
      status: "completed",
      terminal_signal: "submit_tool",
      pr: { number: 7, url: "https://x/pr/7" },
      errorType: null,
      errorMessage: null,
    },
    budget: { turns: 3, tokens: 100, elapsed_ms: 42 },
    runId: "RID123",
  });
  assert.deepEqual(outcome, {
    run_id: "RID123",
    stage: "implement",
    status: "completed",
    terminal_signal: "submit_tool",
    pr: { number: 7, url: "https://x/pr/7" },
    budget: { turns: 3, tokens: 100, elapsed_ms: 42 },
    error: null,
  });
});

// LOCKSTEP LITERAL: the failure shape below (error.summary present) is pinned byte-identically
// in tests/test_run_report.py (_FAILED_OUTCOME_LOCKSTEP) — the failure-report arm's twin.
test("assembleOutcome: a failure carries a capped error.summary", () => {
  const outcome = assembleOutcome({
    stage: "address",
    verdict: {
      status: "failed",
      terminal_signal: "agent_idle_incomplete",
      pr: null,
      errorType: "incomplete",
      errorMessage: "went idle",
    },
    budget: { turns: 1, tokens: 0, elapsed_ms: 1 },
    runId: "RID",
  });
  assert.deepEqual(outcome, {
    run_id: "RID",
    stage: "address",
    status: "failed",
    terminal_signal: "agent_idle_incomplete",
    pr: null,
    budget: { turns: 1, tokens: 0, elapsed_ms: 1 },
    error: { type: "incomplete", message: "went idle", summary: "went idle" },
  });
});

test("assembleOutcome: run_id falls back to PERK_RUN_ID then ''", () => {
  const saved = process.env.PERK_RUN_ID;
  try {
    process.env.PERK_RUN_ID = "ENVRID";
    const a = assembleOutcome({
      stage: "implement",
      verdict: {
        status: "completed",
        terminal_signal: "submit_tool",
        pr: null,
        errorType: null,
        errorMessage: null,
      },
      budget: { turns: 0, tokens: 0, elapsed_ms: 0 },
    });
    assert.equal(a.run_id, "ENVRID");
    delete process.env.PERK_RUN_ID;
    const b = assembleOutcome({
      stage: "implement",
      verdict: {
        status: "completed",
        terminal_signal: "submit_tool",
        pr: null,
        errorType: null,
        errorMessage: null,
      },
      budget: { turns: 0, tokens: 0, elapsed_ms: 0 },
    });
    assert.equal(b.run_id, "");
  } finally {
    if (saved === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = saved;
  }
});

// --- pure: applyEvent ---------------------------------------------------------------------------

test("applyEvent: counts turns, sums assistant tokens, captures terminal tool details + model error", () => {
  const c = freshCounters();
  applyEvent(c, {
    type: "turn_end",
    message: { role: "assistant", usage: { input: 10, output: 5 } },
  });
  applyEvent(c, {
    type: "turn_end",
    message: { role: "assistant", usage: { input: 3, output: -9 } },
  });
  assert.equal(c.turns, 2);
  assert.equal(c.tokens, 18); // 15 + 3 (negative output clamped to 0)

  applyEvent(c, {
    type: "tool_execution_end",
    toolName: "submit",
    result: { details: { ok: true, pr: { number: 1, url: "u" } } },
  });
  assert.deepEqual(c.submitDetails, { ok: true, pr: { number: 1, url: "u" } });

  applyEvent(c, {
    type: "tool_execution_end",
    toolName: "resolve_review_threads",
    result: { details: { ok: true } },
  });
  assert.deepEqual(c.resolveDetails, { ok: true });

  applyEvent(c, {
    type: "message_end",
    message: { role: "assistant", stopReason: "error", errorMessage: "net" },
  });
  assert.deepEqual(c.modelError, { message: "net" });
});

test("applyEvent: usage.reasoning is NOT summed — it is a subset of output on every pi-ai provider", () => {
  // The double-count pin: pi-ai normalizes `reasoning` as a breakdown already inside `output`
  // (anthropic thinking_tokens, google thoughtsTokenCount, openai reasoning_tokens — verified
  // @ 0.80.5), so the budget sum stays `input + output` exactly.
  const c = freshCounters();
  applyEvent(c, {
    type: "turn_end",
    message: { role: "assistant", usage: { input: 10, output: 20, reasoning: 15 } },
  });
  assert.equal(c.tokens, 30);
});

test("budgetTripped: trips on turns OR tokens", () => {
  const budget = { maxTurns: 3, maxTokens: 100, wallClockMs: 1000 };
  assert.equal(budgetTripped({ ...freshCounters(), turns: 2, tokens: 10 }, budget), false);
  assert.equal(budgetTripped({ ...freshCounters(), turns: 3, tokens: 10 }, budget), true);
  assert.equal(budgetTripped({ ...freshCounters(), turns: 1, tokens: 100 }, budget), true);
});

// --- a fake runtime/session for the drive tests -------------------------------------------------

class FakeSession implements DriveSessionLike {
  bindCalls = 0;
  abortCalls = 0;
  disposed = false;
  branch: unknown[] = [];
  sessionFile: string | null = null;
  /** Unset by default — the preflight is presence-gated, so most fakes skip it unchanged. */
  extensionRunner?: { getAllRegisteredTools(): { definition: { name: string } }[] };
  private listeners: ((e: DriveEvent) => void)[] = [];
  private readonly script: (emit: (e: DriveEvent) => void) => Promise<void> | void;
  constructor(script: (emit: (e: DriveEvent) => void) => Promise<void> | void) {
    this.script = script;
  }
  async bindExtensions(): Promise<void> {
    this.bindCalls++;
  }
  subscribe(listener: (e: DriveEvent) => void): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }
  private emit = (e: DriveEvent): void => {
    for (const l of this.listeners) l(e);
  };
  async prompt(): Promise<void> {
    await this.script(this.emit);
  }
  async abort(): Promise<void> {
    this.abortCalls++;
  }
  dispose(): void {
    this.disposed = true;
  }
  sessionManager = {
    getBranch: (): unknown[] => this.branch,
    getSessionFile: (): string | null => this.sessionFile,
  };
}

interface FakeRuntime extends DriveRuntimeLike {
  session: FakeSession;
  disposed: boolean;
}

function fakeRuntime(session: FakeSession): FakeRuntime {
  const runtime: FakeRuntime = {
    session,
    disposed: false,
    async dispose(): Promise<void> {
      runtime.disposed = true;
    },
  };
  return runtime;
}

const baseBudget = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

// --- drive: happy path via injected runtime -----------------------------------------------------

test("driveStage: implement happy path → completed with pr, disposes, never throws", async () => {
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 10, output: 5 } } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 42, url: "https://x/pr/42" } } },
    });
  });
  const runtime = fakeRuntime(session);
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
      model: {} as never,
    },
    { createRuntime: async () => runtime, now: () => 1000 },
  );
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
  assert.deepEqual(outcome.pr, { number: 42, url: "https://x/pr/42" });
  assert.equal(outcome.budget.turns, 1);
  assert.equal(outcome.budget.tokens, 15);
  assert.equal(session.bindCalls, 1);
  assert.equal(runtime.disposed, true);
});

// --- pure: resolveAuth — the model pick is deferred to the SDK ----------------------------------

function resolveAuthOpts(model: unknown, available: unknown[]): Parameters<typeof resolveAuth>[0] {
  return {
    worktree: "/tmp/wt",
    stage: "implement",
    initialPrompt: "go",
    budget: baseBudget,
    model: model as never,
    authStorage: {} as never,
    modelRegistry: { getAvailable: () => available } as never,
  };
}

test("resolveAuth: an explicit model passes through untouched", () => {
  const explicit = { provider: "anthropic", id: "claude-sonnet-4-5" };
  const r = resolveAuth(resolveAuthOpts(explicit, []));
  assert.ok(r);
  assert.equal(r.model, explicit);
});

test("resolveAuth: no explicit model → model stays undefined (the SDK picks at session creation)", () => {
  // getAvailable() sorts alphabetically, so pre-pinning [0] would select the OLDEST model of the
  // first provider (a since-removed dated claude-3-5-haiku pin 404'd a whole remote drive).
  const r = resolveAuth(
    resolveAuthOpts(undefined, [{ id: "claude-3-5-haiku-20241022" }, { id: "claude-sonnet-4-5" }]),
  );
  assert.ok(r);
  assert.equal(r.model, undefined);
});

test("resolveAuth: no explicit model and an empty registry → null (the no_model fail-fast)", () => {
  assert.equal(resolveAuth(resolveAuthOpts(undefined, [])), null);
});

// --- pure: resolveWorkerModel — `--model` resolves with pi's CLI semantics ----------------------

// `resolveCliModel` consults `getAll()` + `hasConfiguredAuth()` (NOT `getAvailable()`):
// unauthenticated models resolve by design, matching an interactive pi launch.
const SONNET = { provider: "anthropic", id: "claude-sonnet-4-5" };
const HAIKU = { provider: "anthropic", id: "claude-haiku-4-5" };

function stubRegistry(models: unknown[]): Parameters<typeof resolveWorkerModel>[1] {
  return { getAll: () => models, hasConfiguredAuth: () => true } as never;
}

test("resolveWorkerModel: exact provider/id resolves", () => {
  const r = resolveWorkerModel("anthropic/claude-sonnet-4-5", stubRegistry([SONNET, HAIKU]));
  assert.equal(r.model, SONNET);
  assert.equal(r.thinkingLevel, undefined);
  assert.equal(r.warning, undefined);
  assert.equal(r.error, undefined);
});

test("resolveWorkerModel: a bare partial id resolves (fuzzy matching parity)", () => {
  const r = resolveWorkerModel("sonnet", stubRegistry([SONNET, HAIKU]));
  assert.equal(r.model, SONNET);
  assert.equal(r.error, undefined);
});

test("resolveWorkerModel: a `:thinking` suffix yields the model + the parsed level", () => {
  const r = resolveWorkerModel("anthropic/claude-sonnet-4-5:high", stubRegistry([SONNET, HAIKU]));
  assert.equal(r.model, SONNET);
  assert.equal(r.thinkingLevel, "high");
  assert.equal(r.error, undefined);
});

test("resolveWorkerModel: an unknown pattern ⇒ error set, model undefined (fail-fast, never guess)", () => {
  const r = resolveWorkerModel("totally-unknown-model-zzz", stubRegistry([SONNET, HAIKU]));
  assert.equal(r.model, undefined);
  assert.equal(typeof r.error, "string");
});

test("resolveWorkerModel: undefined raw ⇒ all-undefined (the SDK default-resolution deferral)", () => {
  const r = resolveWorkerModel(undefined, stubRegistry([SONNET]));
  assert.deepEqual(r, {
    model: undefined,
    thinkingLevel: undefined,
    warning: undefined,
    error: undefined,
  });
});

// --- pure: missingTerminatingTool + drive: the terminating-tool preflight -----------------------

test("missingTerminatingTool: names the stage's terminating tool when absent, null when present", () => {
  assert.equal(missingTerminatingTool("implement", []), "submit");
  assert.equal(missingTerminatingTool("implement", ["read", "bash"]), "submit");
  assert.equal(missingTerminatingTool("implement", ["submit"]), null);
  assert.equal(missingTerminatingTool("address", ["submit"]), "resolve_review_threads");
  assert.equal(missingTerminatingTool("address", ["resolve_review_threads"]), null);
});

test("driveStage: preflight — zero registered tools → fast no_extension_tools failure, no prompt", async () => {
  let promptRan = false;
  const session = new FakeSession(() => {
    promptRan = true;
  });
  session.extensionRunner = { getAllRegisteredTools: () => [] };
  const runtime = fakeRuntime(session);
  const events: RunEvent[] = [];
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
      model: {} as never,
    },
    { createRuntime: async () => runtime, now: () => 1000, eventSink: (e) => events.push(e) },
  );
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.error?.type, "no_extension_tools");
  assert.ok(outcome.error?.message.includes("submit"), "names the missing tool");
  assert.ok(outcome.error?.message.includes(".pi/settings.json"), "points at the settings file");
  assert.equal(outcome.budget.turns, 0);
  assert.equal(promptRan, false, "the drive never prompted");
  assert.equal(runtime.disposed, true, "the runtime is still disposed");
  assert.deepEqual(
    events.map((e) => e.kind),
    ["run_started", "run_finished"],
    "a well-formed zero-turn event pair",
  );
});

test("driveStage: preflight — the terminating tool present → the drive proceeds to completion", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 9, url: "https://x/pr/9" } } },
    });
  });
  session.extensionRunner = {
    getAllRegisteredTools: () => [{ definition: { name: "submit" } }],
  };
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
  );
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
});

test("driveStage: implement records the implementation/worker session pointer", async () => {
  const wt = mkdtempSync(join(tmpdir(), "perk-worker-cap-"));
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
  });
  session.sessionFile = "/sessions/worker-xyz.jsonl";
  const saved = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = "01RID_I";
  try {
    await driveStage(
      {
        worktree: wt,
        stage: "implement",
        initialPrompt: "go",
        budget: baseBudget,
        model: {} as never,
      },
      { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
    );
    const record = readSessionPointers(wt, "01RID_I");
    assert.ok(record !== null, "the worker recorded a session-pointers record");
    assert.equal(record.implementation.worker?.pi_session_id, "worker-xyz.jsonl");
    assert.equal(record.implementation.worker?.session_file, "/sessions/worker-xyz.jsonl");
    // The worker writes only the .worker slot; the inner session_start owns .main.
    assert.equal(record.implementation.main, null);
  } finally {
    if (saved === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = saved;
    rmSync(wt, { recursive: true, force: true });
  }
});

test("driveStage: a non-implement stage records no worker pointer", async () => {
  const wt = mkdtempSync(join(tmpdir(), "perk-worker-cap-"));
  const session = new FakeSession(() => {});
  session.sessionFile = "/sessions/addr.jsonl";
  const saved = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = "01RID_A";
  try {
    await driveStage(
      {
        worktree: wt,
        stage: "address",
        initialPrompt: "go",
        budget: baseBudget,
        model: {} as never,
      },
      { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
    );
    assert.equal(readSessionPointers(wt, "01RID_A"), null);
  } finally {
    if (saved === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = saved;
    rmSync(wt, { recursive: true, force: true });
  }
});

test("driveStage: maxTurns budget trips → budget_exhausted/budget + abort called", async () => {
  const session = new FakeSession((emit) => {
    for (let i = 0; i < 5; i++) emit({ type: "turn_end", message: { role: "assistant" } });
  });
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTurns: 2 },
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
  assert.equal(outcome.terminal_signal, "budget");
  assert.ok(session.abortCalls >= 1);
});

test("driveStage: maxTokens budget trips → budget_exhausted", async () => {
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 60, output: 60 } } });
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 60, output: 60 } } });
  });
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTokens: 100 },
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
});

test("driveStage: an external abort signal → aborted/external_abort + abort called", async () => {
  const controller = new AbortController();
  controller.abort();
  const session = new FakeSession(() => {});
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
      signal: controller.signal,
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "aborted");
  assert.equal(outcome.terminal_signal, "external_abort");
  assert.ok(session.abortCalls >= 1);
});

test("driveStage: a wall-clock timeout trips → budget_exhausted", async () => {
  const session = new FakeSession(async () => {
    await new Promise((r) => setTimeout(r, 40));
  });
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, wallClockMs: 1 },
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
  assert.equal(outcome.terminal_signal, "budget");
});

test("driveStage: no model available → failed/no_model, never throws", async () => {
  // Inject an empty registry/auth so the path is deterministic regardless of the dev machine's
  // ambient provider keys (resolveAuth returns null when getAvailable() is empty).
  const emptyRegistry = { getAvailable: () => [] } as never;
  const emptyAuth = {} as never;
  const outcome = await driveStage({
    worktree: "/tmp/wt",
    stage: "implement",
    initialPrompt: "go",
    budget: baseBudget,
    authStorage: emptyAuth,
    modelRegistry: emptyRegistry,
  });
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.error?.type, "no_model");
});

// --- bind/rebind structural ---------------------------------------------------------------------

test("createBindManager: a rebind unsubscribes the prior listener (no double-count) and re-binds", async () => {
  const counters: DriveCounters = freshCounters();
  const manager = createBindManager({}, (e) => applyEvent(counters, e));
  const s1 = new FakeSession((emit) => emit({ type: "turn_end", message: { role: "assistant" } }));
  const s2 = new FakeSession((emit) => emit({ type: "turn_end", message: { role: "assistant" } }));
  await manager.bind(s1);
  await manager.bind(s2); // rebind: must unsubscribe s1's listener first
  // s1's listener is detached: driving s1 must NOT reach the (single) listener.
  await s1.prompt();
  assert.equal(counters.turns, 0, "prior listener was unsubscribed on rebind");
  // The live binding is s2: driving it reaches the listener exactly once.
  await s2.prompt();
  assert.equal(counters.turns, 1, "only the live session's listener fires");
  assert.equal(s1.bindCalls, 1);
  assert.equal(s2.bindCalls, 1);
  manager.dispose();
});

// --- prompt parity (reciprocal of tests/test_worker_prompt_parity.py) ---------------------------

test("initialPromptFor: implement output composes the template with the read_cmd", () => {
  // Thin composition guard (the live-parity case proves cross-plane byte-identity of the template;
  // this proves the helper wires body + read_cmd + the inline progress paragraph).
  const prompt = initialPromptFor("implement", samplePlanRef);
  assert.ok(prompt);
  assert.ok(prompt?.startsWith("You are implementing perk plan github #148"));
  assert.ok(prompt?.includes("gh issue view 148 --comments"));
  assert.ok(prompt?.endsWith("where the implementation actually stands."));
});

test("initialPromptFor: linear implement output carries the linear read substrings", () => {
  const linearRef: PlanRef = {
    provider: "linear",
    pr_id: "a1b2c3d4-0000-0000-0000-000000000000",
    url: "https://linear.app/acme/issue/ENG-123",
    labels: [],
    objective_id: null,
  };
  const prompt = initialPromptFor("implement", linearRef);
  assert.ok(prompt);
  for (const s of LINEAR_READ_SUBSTRINGS) assert.ok(prompt?.includes(s), `missing: ${s}`);
  assert.ok(prompt?.includes("open https://linear.app/acme/issue/ENG-123"));
});

// The review-classifier model clause — the parity literal shared with
// tests/test_worker_prompt_parity.py (`_address_prompt(_PLAN_REF, "test/model")`).
const ADDRESS_MODEL_CLAUSE =
  ', passing `model: "test/model"` on that call (the configured [models.subagents] review-classifier model)';

test("initialPromptFor: address injects the classifier model clause when configured", () => {
  const prompt = initialPromptFor("address", samplePlanRef, "test/model");
  assert.ok(prompt?.includes(ADDRESS_MODEL_CLAUSE), "missing the configured model clause");
});

test("initialPromptFor: address omits the model clause when unconfigured", () => {
  const prompt = initialPromptFor("address", samplePlanRef);
  assert.doesNotMatch(prompt ?? "", /passing `model:/);
});

test("initialPromptFor: a non-github implement plan uses the open-url read command", () => {
  const ref: PlanRef = { ...samplePlanRef, provider: "gitlab", url: "https://gl/x" };
  const prompt = initialPromptFor("implement", ref);
  assert.ok(prompt?.includes("open https://gl/x"));
});

test("initialPromptFor: a null plan-ref yields null (nothing to prime)", () => {
  assert.equal(initialPromptFor("implement", null), null);
  assert.equal(initialPromptFor("address", null), null);
});

test("initialPromptForWorktree: a corrupt plan-ref reads as absent → null, no throw", () => {
  // The total reader degrades a truncated plan-ref.json to null (loud stderr), so workerMain's
  // pre-drive read takes its existing clean "no plan-ref under …" exit-2 arm instead of crashing.
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-planref-"));
  mkdirSync(workflowDir(worktree), { recursive: true });
  writeFileSync(planRefPath(worktree), '{"provider": "github", "pr_id', "utf8");
  const original = console.error;
  console.error = () => {};
  try {
    assert.equal(initialPromptForWorktree(worktree, "implement"), null);
  } finally {
    console.error = original;
  }
});

// --- Gap-4 verification: throwaway agentDir still loads + binds the project @mgiles/perk extension ---

test("Gap-4: a bound perk session registers the worker's terminal tools and claims its run", async () => {
  const runId = "01JWORKERTESTRUNID000000000";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const perk = await loadPerkSession({
    cwd,
    headful: false,
    mode: "json",
    env: { PERK_RUN_ID: runId },
  });
  try {
    const tools = perk.session.extensionRunner
      .getAllRegisteredTools()
      .map((t) => t.definition.name);
    assert.ok(tools.includes("submit"), "submit tool should be registered");
    assert.ok(
      tools.includes("resolve_review_threads"),
      "resolve_review_threads tool should be registered",
    );
    // The session_start claim path engaged for the planted handoff + PERK_RUN_ID.
    assert.equal(perk.workflowState().run_id, runId);
    assert.equal(perk.sentinel()?.run_id, runId);
  } finally {
    perk.dispose();
  }
});

// --- structured run-event stream ------------------------------------------------------

// --- pure: extractStepMarkers -------------------------------------------------------------------

test("extractStepMarkers: textual appearance order (WIP before DONE in one message)", () => {
  const markers = extractStepMarkers("starting [WIP:2] then finishing [DONE:1] now");
  assert.deepEqual(markers, [
    { marker: "wip", step: 2 },
    { marker: "done", step: 1 },
  ]);
});

test("extractStepMarkers: case-insensitive, mixed, and none", () => {
  assert.deepEqual(extractStepMarkers("[wip:3][DONE:3][Wip:4]"), [
    { marker: "wip", step: 3 },
    { marker: "done", step: 3 },
    { marker: "wip", step: 4 },
  ]);
  assert.deepEqual(extractStepMarkers("no markers here"), []);
});

// --- pure: assistantText ------------------------------------------------------------------------

test("assistantText: string, block-array, and empty content", () => {
  assert.equal(assistantText({ type: "turn_end", message: { content: "hello" } }), "hello");
  assert.equal(
    assistantText({
      type: "turn_end",
      message: {
        content: [{ type: "text", text: "a" }, { type: "tool_use" }, { type: "text", text: "b" }],
      },
    }),
    "a\nb",
  );
  assert.equal(assistantText({ type: "turn_end", message: {} }), "");
  assert.equal(assistantText({ type: "turn_end" }), "");
});

// --- pure: toolOutcomeOf ------------------------------------------------------------------------

test("toolOutcomeOf: ok via details.ok, fallback to !isError, capped error summary", () => {
  assert.deepEqual(
    toolOutcomeOf({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true } },
    }),
    { tool: "submit", ok: true, summary: null },
  );
  // No details.ok boolean → fall back to !isError.
  assert.deepEqual(
    toolOutcomeOf({ type: "tool_execution_end", toolName: "read", isError: false }),
    {
      tool: "read",
      ok: true,
      summary: null,
    },
  );
  const bigErr = "x".repeat(5000);
  const out = toolOutcomeOf({
    type: "tool_execution_end",
    toolName: "submit",
    isError: true,
    result: { details: { ok: false, error: bigErr } },
  });
  assert.equal(out.ok, false);
  assert.ok(out.summary && out.summary.length < bigErr.length, "summary is capped");
  assert.ok(out.summary?.includes("[Output truncated"), "carries the truncation notice");
});

// --- createEventEmitter -------------------------------------------------------------------------

test("createEventEmitter: monotonic seq, t from the injected clock, fail-soft on a throwing sink", () => {
  const seen: RunEvent[] = [];
  let clock = 1000;
  const emitter = createEventEmitter(
    (e) => seen.push(e),
    () => clock,
    1000,
  );
  emitter.emit({ kind: "run_started", run_id: "r", stage: "implement" });
  clock = 1250;
  emitter.emit({ kind: "step_marker", marker: "wip", step: 1 });
  assert.equal(seen[0]?.seq, 0);
  assert.equal(seen[0]?.t, 0);
  assert.equal(seen[1]?.seq, 1);
  assert.equal(seen[1]?.t, 250);

  // A throwing sink is swallowed (does not break emission).
  const thrower = createEventEmitter(
    () => {
      throw new Error("boom");
    },
    () => 0,
    0,
  );
  assert.doesNotThrow(() => thrower.emit({ kind: "step_marker", marker: "done", step: 1 }));
});

// --- driveStage with an injected array sink -----------------------------------------------------

const eventBudget = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

test("driveStage: a happy implement run emits run_started → tool_outcome(submit) → run_finished", async () => {
  const events: RunEvent[] = [];
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 1, output: 1 } } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
  });
  const outcome = await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      model: {} as never,
    },
    {
      createRuntime: async () => fakeRuntime(session),
      now: () => 0,
      eventSink: (e) => events.push(e),
    },
  );
  assert.equal(outcome.status, "completed");
  assert.deepEqual(
    events.map((e) => e.kind),
    ["run_started", "tool_outcome", "run_finished"],
  );
  // seq is monotonic 0..n.
  events.forEach((e, i) => {
    assert.equal(e.seq, i);
  });
  const started = events[0] as Extract<RunEvent, { kind: "run_started" }>;
  assert.equal(started.stage, "implement");
  const tool = events[1] as Extract<RunEvent, { kind: "tool_outcome" }>;
  assert.equal(tool.tool, "submit");
  assert.equal(tool.ok, true);
  const finished = events[2] as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.outcome.status, "completed");
});

test("driveStage: a turn carrying [WIP:1]/[DONE:1] emits ordered step_marker events", async () => {
  const events: RunEvent[] = [];
  const session = new FakeSession((emit) => {
    emit({
      type: "turn_end",
      message: { role: "assistant", content: "begin [WIP:1] and finish [DONE:1]" },
    });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 1, url: "u" } } },
    });
  });
  await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      model: {} as never,
    },
    {
      createRuntime: async () => fakeRuntime(session),
      now: () => 0,
      eventSink: (e) => events.push(e),
    },
  );
  const markers = events.filter((e) => e.kind === "step_marker") as Extract<
    RunEvent,
    { kind: "step_marker" }
  >[];
  assert.deepEqual(
    markers.map((m) => [m.marker, m.step]),
    [
      ["wip", 1],
      ["done", 1],
    ],
  );
});

test("driveStage: a budget trip emits a terminal run_finished(budget_exhausted)", async () => {
  const events: RunEvent[] = [];
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant" } });
  });
  await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { maxTurns: 1, maxTokens: 1_000_000, wallClockMs: 60_000 },
      model: {} as never,
    },
    { createRuntime: async () => fakeRuntime(session), eventSink: (e) => events.push(e) },
  );
  const finished = events.at(-1) as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.kind, "run_finished");
  assert.equal(finished.outcome.status, "budget_exhausted");
});

test("driveStage: an external abort emits a terminal run_finished(aborted)", async () => {
  const events: RunEvent[] = [];
  const controller = new AbortController();
  const session = new FakeSession(async () => {
    controller.abort();
    await new Promise((r) => setTimeout(r, 1));
  });
  await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      model: {} as never,
      signal: controller.signal,
    },
    { createRuntime: async () => fakeRuntime(session), eventSink: (e) => events.push(e) },
  );
  const finished = events.at(-1) as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.outcome.status, "aborted");
});

test("driveStage: the no_model early return still emits run_started + run_finished(failed/no_model)", async () => {
  const events: RunEvent[] = [];
  await driveStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      authStorage: {} as never,
      modelRegistry: { getAvailable: () => [] } as never,
    },
    { eventSink: (e) => events.push(e) },
  );
  assert.deepEqual(
    events.map((e) => e.kind),
    ["run_started", "run_finished"],
  );
  const finished = events[1] as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.outcome.status, "failed");
  assert.equal(finished.outcome.error?.type, "no_model");
  // The terminal failure summary is the capped error.summary.
  assert.ok((finished.outcome.error?.summary?.length ?? 0) > 0);
});

// --- default file sink (NDJSON under the gitignored run scratch dir) -----------------------------

test("driveStage: with no eventSink + a set run_id writes parseable NDJSON to runEventsPath", async () => {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-events-"));
  const runId = "01JEVENTSTREAMTESTRUNID00000";
  const prior = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = runId;
  try {
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant", content: "[WIP:1]" } });
      emit({
        type: "tool_execution_end",
        toolName: "submit",
        result: { details: { ok: true, pr: { number: 9, url: "u" } } },
      });
    });
    await driveStage(
      {
        worktree,
        stage: "implement",
        initialPrompt: "go",
        budget: eventBudget,
        model: {} as never,
      },
      { createRuntime: async () => fakeRuntime(session) },
    );
    const lines = readFileSync(runEventsPath(worktree, runId), "utf8").trim().split("\n");
    const parsed = lines.map((l) => JSON.parse(l) as RunEvent);
    assert.equal(parsed[0]?.kind, "run_started");
    assert.equal(parsed.at(-1)?.kind, "run_finished");
    assert.ok(parsed.some((e) => e.kind === "step_marker"));
  } finally {
    if (prior === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = prior;
  }
});

test("driveStage: with an empty run_id writes nothing (the no-op default sink)", async () => {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-noevents-"));
  const prior = process.env.PERK_RUN_ID;
  delete process.env.PERK_RUN_ID;
  try {
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant" } });
    });
    await driveStage(
      {
        worktree,
        stage: "implement",
        initialPrompt: "go",
        budget: eventBudget,
        model: {} as never,
      },
      { createRuntime: async () => fakeRuntime(session) },
    );
    assert.ok(!existsSync(runEventsPath(worktree, "")), "no events file when run_id is empty");
  } finally {
    if (prior === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = prior;
  }
});
