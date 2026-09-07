// Interface-level coverage for the stage-execution seam: every behavior is proven through
// `runStage` over an INJECTED runtime (`StageRunDeps` — no model turn / network ever) plus the
// `initialPromptForWorktree` prompt derivation over written plan-refs. The suite carries the
// runStage terminal-classification matrix, the two frozen-RunOutcome lockstep literals
// (reciprocal of tests/test_run_report.py), the budget/abort watchdog with exact `>=` thresholds,
// the seam's never-throws contract under adversarial fakes, the structured run-event stream, and
// the cross-plane prompt-parity invariant (reciprocal of tests/test_worker_prompt_parity.py).
// The adapter-owned helpers (translateEvent, the drive-session handle,
// resolveAuth/resolveWorkerModel) are covered in sdkAdapter.test.ts; the real-factory tier lives
// in stageExecutionE2e.test.ts. See stageExecution.ts.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { PlanRef } from "../substrate/cache.ts";
import { planRefPath, runEventsPath, workflowDir } from "../substrate/cache.ts";
import { readSessionPointers } from "../substrate/sessionPointers.ts";
// The nominal model token is adapter-owned; tests mint it deliberately.
import { WorkerModelSelection } from "./sdkAdapter.ts";
import {
  type DriveEvent,
  type DriveRuntimeLike,
  type DriveSessionLike,
  initialPromptForWorktree,
  type RunEvent,
  runStage,
} from "./stageExecution.ts";

// The cross-plane prompt-parity invariant: these substrings MUST appear in BOTH the TS worker
// prompt output and the Python `perk/run/launch.py` prompts. The same literals live in
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

/** Scaffold a prepared worktree carrying the given plan-ref (the seam reads `cache.plan-ref`). */
function writePlanRef(ref: PlanRef): string {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-planref-"));
  mkdirSync(workflowDir(worktree), { recursive: true });
  writeFileSync(planRefPath(worktree), JSON.stringify(ref), "utf8");
  return worktree;
}

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

/** The `perk:workflow-state` branch entry carrying `last_review_batch` (address completion). */
function lastReviewBatchEntry(): unknown {
  return {
    type: "custom",
    customType: "perk:workflow-state",
    data: { last_review_batch: { pr: 7, actionable: 1 } },
  };
}

const baseBudget = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

/** Drive one stage over a scripted fake with a fixed clock (the matrix tests' shared shape). */
function driveFake(
  session: FakeSession,
  stage: "implement" | "address" = "implement",
): ReturnType<typeof runStage> {
  return runStage(
    { worktree: "/tmp/wt", stage, initialPrompt: "go", budget: baseBudget },
    { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
  );
}

// --- drive: happy path via injected runtime -----------------------------------------------------

test("runStage: implement happy path → completed with pr, disposes, never throws", async () => {
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 10, output: 5 } } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 42, url: "https://x/pr/42" } } },
    });
  });
  const runtime = fakeRuntime(session);
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
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

// --- the runStage terminal-classification matrix -------------------------------------------------
// One test per natural-idle classification arm, each a scripted FakeSession through the seam.
// The implement successful-submit arm is the happy-path test above; the implement idle-without-PR
// arm is the frozen failed-RunOutcome lockstep test below.

test("runStage: implement with an unmergeable submit → failed/agent_idle_incomplete", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: {
        details: { ok: true, pr: { number: 7, url: "https://x/pr/7" }, mergeable: false },
      },
    });
  });
  const outcome = await driveFake(session);
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
  assert.equal(outcome.pr, null);
  assert.match(outcome.error?.message ?? "", /unmergeable PR \(merge conflicts unresolved\)/);
});

for (const resubmit of ["none", "clean", "conflicted", "failed"]) {
  test(`scripted resolver success cannot finish the worker without canonical submit: ${resubmit}`, async () => {
    const session = new FakeSession((emit) => {
      const conflicted = { ok: true, pr: { number: 7, url: "https://x/pr/7" }, mergeable: false };
      emit({ type: "tool_execution_end", toolName: "submit", result: { details: conflicted } });
      emit({
        type: "tool_execution_end",
        toolName: "resolve_submit_conflicts",
        result: { details: { ok: true, kind: "resolved" } },
      });
      if (resubmit !== "none") {
        emit({
          type: "tool_execution_end",
          toolName: "submit",
          result: {
            details:
              resubmit === "failed"
                ? { ok: false }
                : { ...conflicted, mergeable: resubmit === "clean" },
          },
        });
      }
    });
    assert.equal((await driveFake(session)).status, resubmit === "clean" ? "completed" : "failed");
  });
}

test("runStage: implement with mergeable true/null/absent → completed", async () => {
  for (const mergeable of [true, null, undefined]) {
    const details: Record<string, unknown> = {
      ok: true,
      pr: { number: 7, url: "https://x/pr/7" },
    };
    if (mergeable !== undefined) details.mergeable = mergeable;
    const session = new FakeSession((emit) => {
      emit({ type: "tool_execution_end", toolName: "submit", result: { details } });
    });
    const outcome = await driveFake(session);
    assert.equal(outcome.status, "completed", `mergeable=${mergeable} → completed`);
    assert.equal(outcome.terminal_signal, "submit_tool");
  }
});

test("runStage: implement with submit ok:false → failed/agent_idle_incomplete", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: false, error: "boom" } },
    });
  });
  const outcome = await driveFake(session);
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
});

test("runStage: a model error wins over a successful submit → failed/model_error", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
    emit({
      type: "message_end",
      message: { role: "assistant", stopReason: "error", errorMessage: "overloaded" },
    });
  });
  const outcome = await driveFake(session);
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.error?.message, "overloaded");
});

test("runStage: finalized address + batch + mergeable nested submit → completed", async () => {
  // The nested finalizer submit lacks an `ok` marker on its public shape; completion proves the
  // seam restores it when folding the finalizer's evidence.
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "finalize_address",
      result: { details: { ok: true, submit: { mergeable: true } } },
    });
  });
  session.branch = [lastReviewBatchEntry()];
  const outcome = await driveFake(session, "address");
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "address_resolved");
  assert.equal(outcome.pr, null);
});

test("runStage: a finalized address with an unmergeable nested submit → failed", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "finalize_address",
      result: { details: { ok: true, submit: { mergeable: false } } },
    });
  });
  session.branch = [lastReviewBatchEntry()];
  const outcome = await driveFake(session, "address");
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
});

test("runStage: a later clean standalone submit completes an unmergeable finalizer", async () => {
  // The conflict-resolver re-drive shape: the latest submit-bearing evidence supersedes the
  // finalizer's unmergeable nested submit.
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "finalize_address",
      result: { details: { ok: true, submit: { mergeable: false } } },
    });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, mergeable: true } },
    });
  });
  session.branch = [lastReviewBatchEntry()];
  const outcome = await driveFake(session, "address");
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "address_resolved");
});

test("runStage: a later failed standalone submit cannot complete an unmergeable finalizer", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "finalize_address",
      result: { details: { ok: true, submit: { mergeable: false } } },
    });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: false, error: "push failed" } },
    });
  });
  session.branch = [lastReviewBatchEntry()];
  const outcome = await driveFake(session, "address");
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
});

test("runStage: a finalized address without last_review_batch → failed", async () => {
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "finalize_address",
      result: { details: { ok: true, submit: { mergeable: true } } },
    });
  });
  const outcome = await driveFake(session, "address");
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "agent_idle_incomplete");
});

// --- the frozen RunOutcome lockstep literals ------------------------------------------------------

// LOCKSTEP LITERAL (contracts.md §8.11/§8.38): the completed RunOutcome asserted below is pinned
// byte-identically in tests/test_run_report.py (_COMPLETED_OUTCOME_LOCKSTEP), which feeds it
// through the Python remote reporter — a field rename here must break that suite too. Change
// BOTH suites together.
test("runStage: the frozen completed RunOutcome (lockstep with tests/test_run_report.py)", async () => {
  const saved = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = "RID123";
  try {
    let t = 0;
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant", usage: { input: 20, output: 20 } } });
      emit({ type: "turn_end", message: { role: "assistant", usage: { input: 20, output: 20 } } });
      emit({ type: "turn_end", message: { role: "assistant", usage: { input: 10, output: 10 } } });
      emit({
        type: "tool_execution_end",
        toolName: "submit",
        result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
      });
      t = 42;
    });
    const outcome = await runStage(
      { worktree: "/tmp/wt", stage: "implement", initialPrompt: "go", budget: baseBudget },
      { createRuntime: async () => fakeRuntime(session), now: () => t, eventSink: () => {} },
    );
    assert.deepEqual(outcome, {
      run_id: "RID123",
      stage: "implement",
      status: "completed",
      terminal_signal: "submit_tool",
      pr: { number: 7, url: "https://x/pr/7" },
      budget: { turns: 3, tokens: 100, elapsed_ms: 42 },
      error: null,
    });
  } finally {
    if (saved === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = saved;
  }
});

// LOCKSTEP LITERAL: the failure shape below (error.summary present) is pinned byte-identically
// in tests/test_run_report.py (_FAILED_OUTCOME_LOCKSTEP) — the failure-report arm's twin. This
// test doubles as the implement idle-without-PR classification arm.
test("runStage: the frozen failed RunOutcome (lockstep with tests/test_run_report.py)", async () => {
  const saved = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = "RID";
  try {
    let t = 0;
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant" } });
      t = 1;
    });
    const outcome = await runStage(
      { worktree: "/tmp/wt", stage: "implement", initialPrompt: "go", budget: baseBudget },
      { createRuntime: async () => fakeRuntime(session), now: () => t, eventSink: () => {} },
    );
    assert.deepEqual(outcome, {
      run_id: "RID",
      stage: "implement",
      status: "failed",
      terminal_signal: "agent_idle_incomplete",
      pr: null,
      budget: { turns: 1, tokens: 0, elapsed_ms: 1 },
      error: {
        type: "incomplete",
        message: "implement drive went idle without an opened PR (no successful submit).",
        summary: "implement drive went idle without an opened PR (no successful submit).",
      },
    });
  } finally {
    if (saved === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = saved;
  }
});

// --- the terminating-tool preflight ---------------------------------------------------------------

test("runStage: preflight — zero registered tools → fast no_extension_tools failure, no prompt", async () => {
  let promptRan = false;
  const session = new FakeSession(() => {
    promptRan = true;
  });
  session.extensionRunner = { getAllRegisteredTools: () => [] };
  const runtime = fakeRuntime(session);
  const events: RunEvent[] = [];
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
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

test("runStage: preflight — the terminating tool present → the drive proceeds to completion", async () => {
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
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
    },
    { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
  );
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.terminal_signal, "submit_tool");
});

test("runStage: preflight — an address drive without finalize_address names it, no prompt", async () => {
  let promptRan = false;
  const session = new FakeSession(() => {
    promptRan = true;
  });
  session.extensionRunner = {
    getAllRegisteredTools: () => [{ definition: { name: "submit" } }],
  };
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "address",
      initialPrompt: "go",
      budget: baseBudget,
    },
    { createRuntime: async () => fakeRuntime(session), now: () => 1000 },
  );
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.error?.type, "no_extension_tools");
  assert.ok(outcome.error?.message.includes("finalize_address"), "names the missing tool");
  assert.equal(promptRan, false, "the drive never prompted");
});

// --- session pointers -----------------------------------------------------------------------------

test("runStage: implement records the implementation/worker session pointer", async () => {
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
    await runStage(
      {
        worktree: wt,
        stage: "implement",
        initialPrompt: "go",
        budget: baseBudget,
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

test("runStage: a non-implement stage records no worker pointer", async () => {
  const wt = mkdtempSync(join(tmpdir(), "perk-worker-cap-"));
  const session = new FakeSession(() => {});
  session.sessionFile = "/sessions/addr.jsonl";
  const saved = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = "01RID_A";
  try {
    await runStage(
      {
        worktree: wt,
        stage: "address",
        initialPrompt: "go",
        budget: baseBudget,
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

// --- the budget/abort watchdog --------------------------------------------------------------------

test("runStage: exactly maxTurns turn_ends trip → budget_exhausted/budget + abort called", async () => {
  // The exact `>=` threshold: two turn_ends against maxTurns: 2 trip the watchdog once.
  // Repeated-trip abort idempotence is pinned at the adapter tier (sdkAdapter.test.ts
  // "abort is idempotent").
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant" } });
    emit({ type: "turn_end", message: { role: "assistant" } });
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTurns: 2 },
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
  assert.equal(outcome.terminal_signal, "budget");
  assert.equal(session.abortCalls, 1);
});

test("runStage: one turn below maxTurns never trips → completed", async () => {
  // The false side of the exact `>=` turn threshold: an off-by-one trip (maxTurns - 1) would
  // surface here as budget_exhausted instead of completed.
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant" } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTurns: 2 },
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.budget.turns, 1);
  assert.equal(session.abortCalls, 0, "the watchdog never tripped below the limit");
});

test("runStage: turns summing exactly maxTokens trip → budget_exhausted", async () => {
  // The exact `>=` threshold: 60 + 40 fresh tokens against maxTokens: 100.
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 30, output: 30 } } });
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 20, output: 20 } } });
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTokens: 100 },
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
});

test("runStage: fresh tokens one below maxTokens never trip → completed", async () => {
  // The false side of the exact `>=` token threshold: 99 fresh tokens against maxTokens: 100.
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 60, output: 39 } } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, maxTokens: 100 },
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "completed");
  assert.equal(outcome.budget.tokens, 99);
  assert.equal(session.abortCalls, 0, "the watchdog never tripped below the limit");
});

test("runStage: an external abort signal → aborted/external_abort + abort called", async () => {
  const controller = new AbortController();
  controller.abort();
  const session = new FakeSession(() => {});
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: baseBudget,
      signal: controller.signal,
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "aborted");
  assert.equal(outcome.terminal_signal, "external_abort");
  assert.ok(session.abortCalls >= 1);
});

test("runStage: a wall-clock timeout trips → budget_exhausted", async () => {
  const session = new FakeSession(async () => {
    await new Promise((r) => setTimeout(r, 40));
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { ...baseBudget, wallClockMs: 1 },
    },
    { createRuntime: async () => fakeRuntime(session) },
  );
  assert.equal(outcome.status, "budget_exhausted");
  assert.equal(outcome.terminal_signal, "budget");
});

test("runStage: no model available → failed/no_model, never throws", async () => {
  // Build the nominal selection around an empty-snapshot stub runtime so the path is
  // deterministic regardless of the dev machine's ambient provider keys (resolveAuth returns
  // null when the availability snapshot is empty and no explicit model rides the selection).
  const emptyRuntime = { getAvailableSnapshot: () => [] } as never;
  const outcome = await runStage({
    worktree: "/tmp/wt",
    stage: "implement",
    initialPrompt: "go",
    budget: baseBudget,
    model: new WorkerModelSelection(emptyRuntime),
  });
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.error?.type, "no_model");
});

// --- the never-throws contract under adversarial fakes (contracts.md §8.11) ---------------------

test("runStage: a rejecting session.abort() on a budget trip — frozen outcome, no unhandled rejection", async () => {
  // The abort rejection now has an owner (the adapter handle retains + logs it): the trip's
  // frozen budget_exhausted outcome must still return, and the rejection must never surface as
  // an unhandled rejection (the process-level listener would fail this test loudly).
  const unhandled: unknown[] = [];
  const onUnhandled = (reason: unknown): void => {
    unhandled.push(reason);
  };
  process.on("unhandledRejection", onUnhandled);
  const savedErr = console.error;
  console.error = () => {};
  try {
    const session = new FakeSession((emit) => {
      for (let i = 0; i < 3; i++) emit({ type: "turn_end", message: { role: "assistant" } });
    });
    session.abort = async () => {
      session.abortCalls++;
      throw new Error("abort exploded");
    };
    const outcome = await runStage(
      {
        worktree: "/tmp/wt",
        stage: "implement",
        initialPrompt: "go",
        budget: { ...baseBudget, maxTurns: 1 },
      },
      { createRuntime: async () => fakeRuntime(session) },
    );
    assert.equal(outcome.status, "budget_exhausted");
    assert.equal(outcome.terminal_signal, "budget");
    assert.ok(session.abortCalls >= 1, "abort was fired");
    // Give the loop a tick so a would-be unhandled rejection has surfaced before we assert.
    await new Promise((r) => setImmediate(r));
    assert.deepEqual(unhandled, [], "the abort rejection must never go unhandled");
  } finally {
    console.error = savedErr;
    process.off("unhandledRejection", onUnhandled);
  }
});

test("runStage: a throwing unsubscribe + rejecting runtime.dispose() cannot replace the outcome", async () => {
  // The cleanup-error-precedence pin: an already-computed RunOutcome survives a finally-arm
  // failure — the guarded dispose catches both, and the runtime dispose is still ATTEMPTED
  // after the unsubscribe threw.
  const savedErr = console.error;
  console.error = () => {};
  try {
    const session = new FakeSession((emit) => {
      emit({
        type: "tool_execution_end",
        toolName: "submit",
        result: { details: { ok: true, pr: { number: 5, url: "https://x/pr/5" } } },
      });
    });
    session.subscribe = (listener) => {
      (session as unknown as { listeners: ((e: DriveEvent) => void)[] }).listeners.push(listener);
      return () => {
        throw new Error("unsubscribe exploded");
      };
    };
    let disposeAttempted = false;
    const runtime: DriveRuntimeLike = {
      session,
      async dispose(): Promise<void> {
        disposeAttempted = true;
        throw new Error("dispose exploded");
      },
    };
    const outcome = await runStage(
      {
        worktree: "/tmp/wt",
        stage: "implement",
        initialPrompt: "go",
        budget: baseBudget,
      },
      { createRuntime: async () => runtime },
    );
    assert.equal(outcome.status, "completed", "the computed outcome survives cleanup failures");
    assert.equal(outcome.terminal_signal, "submit_tool");
    assert.deepEqual(outcome.pr, { number: 5, url: "https://x/pr/5" });
    assert.equal(disposeAttempted, true, "runtime dispose was still attempted");
  } finally {
    console.error = savedErr;
  }
});

// --- prompt parity (reciprocal of tests/test_worker_prompt_parity.py) ---------------------------

test("initialPromptForWorktree: implement output composes the template with the read_cmd", () => {
  // Thin composition guard (the live-parity case proves cross-plane byte-identity of the template;
  // this proves the helper wires body + read_cmd + the inline progress paragraph).
  const prompt = initialPromptForWorktree(writePlanRef(samplePlanRef), "implement");
  assert.ok(prompt);
  assert.ok(prompt?.startsWith("You are implementing perk plan github #148"));
  assert.ok(prompt?.includes("gh issue view 148 --comments"));
  assert.ok(prompt?.endsWith("where the implementation actually stands."));
});

test("initialPromptForWorktree: linear implement output carries the linear read substrings", () => {
  const linearRef: PlanRef = {
    provider: "linear",
    pr_id: "a1b2c3d4-0000-0000-0000-000000000000",
    url: "https://linear.app/acme/issue/ENG-123",
    labels: [],
    objective_id: null,
  };
  const prompt = initialPromptForWorktree(writePlanRef(linearRef), "implement");
  assert.ok(prompt);
  for (const s of LINEAR_READ_SUBSTRINGS) assert.ok(prompt?.includes(s), `missing: ${s}`);
  assert.ok(prompt?.includes("open https://linear.app/acme/issue/ENG-123"));
});

test("initialPromptForWorktree: address names classify_review_feedback — no transcribed mechanics, no model clause", () => {
  const prompt = initialPromptForWorktree(writePlanRef(samplePlanRef), "address") ?? "";
  assert.match(prompt, /classify_review_feedback/);
  assert.match(prompt, /finalize_address/);
  // The tool reads the classifier model at execute time — nothing model-shaped in the prompt.
  assert.doesNotMatch(prompt, /passing `model:/);
  assert.doesNotMatch(prompt, /workflowScript/);
  assert.doesNotMatch(prompt, /outputSchema/);
});

test("initialPromptForWorktree: a non-github implement plan uses the open-url read command", () => {
  const ref: PlanRef = { ...samplePlanRef, provider: "gitlab", url: "https://gl/x" };
  const prompt = initialPromptForWorktree(writePlanRef(ref), "implement");
  assert.ok(prompt?.includes("open https://gl/x"));
});

test("initialPromptForWorktree: an absent plan-ref yields null (nothing to prime)", () => {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-planref-"));
  mkdirSync(workflowDir(worktree), { recursive: true });
  assert.equal(initialPromptForWorktree(worktree, "implement"), null);
  assert.equal(initialPromptForWorktree(worktree, "address"), null);
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

// --- structured run-event stream ------------------------------------------------------

test("RunEvent: the deprecated step_marker variant stays in the grammar (compile-time pin)", () => {
  // Additive-stable §8.12 grammar fact: historical events.ndjson files may carry `step_marker`,
  // so the variant must stay a member of the RunEvent union even though the runtime never emits
  // it (the "[WIP:1]/[DONE:1] emits no step_marker" runStage test pins the runtime negative).
  const historical: RunEvent = { kind: "step_marker", seq: 3, t: 250, marker: "wip", step: 1 };
  assert.equal(historical.kind, "step_marker");
});

const eventBudget = { maxTurns: 100, maxTokens: 1_000_000, wallClockMs: 60_000 };

test("runStage: a happy implement run emits run_started → tool_outcome(submit) → run_finished", async () => {
  const events: RunEvent[] = [];
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant", usage: { input: 1, output: 1 } } });
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
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
  assert.equal(tool.summary, null, "a successful tool_outcome carries no summary");
  const finished = events[2] as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.outcome.status, "completed");
});

test("runStage: run-event t stamps ride the injected clock, relative to the run start", async () => {
  // The event-clock contract: every RunEvent.t is max(0, now() - startMs) on the SAME injected
  // clock basis as RunOutcome.budget.elapsed_ms. A regression to constant stamps (all 0) or to
  // absolute clock values (500/750/900) would fail the exact relative sequence below.
  const events: RunEvent[] = [];
  let t = 500; // a non-zero start pins "relative to run start", not absolute clock readings
  const session = new FakeSession((emit) => {
    t = 750;
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 7, url: "https://x/pr/7" } } },
    });
    t = 900;
  });
  const outcome = await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
    },
    {
      createRuntime: async () => fakeRuntime(session),
      now: () => t,
      eventSink: (e) => events.push(e),
    },
  );
  assert.deepEqual(
    events.map((e) => [e.kind, e.t]),
    [
      ["run_started", 0],
      ["tool_outcome", 250],
      ["run_finished", 400],
    ],
    "t advances with the injected clock from the run start",
  );
  assert.equal(outcome.budget.elapsed_ms, 400, "the outcome shares the event clock basis");
});

test("runStage: a failing tool emits a tool_outcome with ok:false and a capped summary", async () => {
  // The offline twin of the e2e FAILING-TOOL scenario (route-don't-relay): the summary is the
  // capped rendering of the adapter's pre-cap error text, never the raw tool payload.
  const events: RunEvent[] = [];
  const bigErr = "x".repeat(5000);
  const session = new FakeSession((emit) => {
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: false, error: bigErr } },
    });
  });
  await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
    },
    {
      createRuntime: async () => fakeRuntime(session),
      now: () => 0,
      eventSink: (e) => events.push(e),
    },
  );
  const tool = events.find((e) => e.kind === "tool_outcome") as Extract<
    RunEvent,
    { kind: "tool_outcome" }
  >;
  assert.ok(tool, "a tool_outcome was emitted");
  assert.equal(tool.ok, false);
  assert.ok(tool.summary && tool.summary.length < bigErr.length, "summary is capped");
  assert.ok(tool.summary?.includes("[Output truncated"), "carries the truncation notice");
});

test("runStage: assistant prose carrying [WIP:1]/[DONE:1] emits no step_marker events (deprecated)", async () => {
  const events: RunEvent[] = [];
  // Hoisted const: `content` is no longer a `DriveEvent` field, so a plain object (not a typed
  // literal) carries the marker-laden prose past structural typing without a cast.
  const markerTurn = {
    type: "turn_end",
    message: { role: "assistant", content: "begin [WIP:1] and finish [DONE:1]" },
  };
  const session = new FakeSession((emit) => {
    emit(markerTurn);
    emit({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 1, url: "u" } } },
    });
  });
  await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
    },
    {
      createRuntime: async () => fakeRuntime(session),
      now: () => 0,
      eventSink: (e) => events.push(e),
    },
  );
  assert.deepEqual(
    events.filter((e) => e.kind === "step_marker"),
    [],
    "step markers are never emitted (deprecated)",
  );
});

test("runStage: a budget trip emits a terminal run_finished(budget_exhausted)", async () => {
  const events: RunEvent[] = [];
  const session = new FakeSession((emit) => {
    emit({ type: "turn_end", message: { role: "assistant" } });
  });
  await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: { maxTurns: 1, maxTokens: 1_000_000, wallClockMs: 60_000 },
    },
    { createRuntime: async () => fakeRuntime(session), eventSink: (e) => events.push(e) },
  );
  const finished = events.at(-1) as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.kind, "run_finished");
  assert.equal(finished.outcome.status, "budget_exhausted");
});

test("runStage: an external abort emits a terminal run_finished(aborted)", async () => {
  const events: RunEvent[] = [];
  const controller = new AbortController();
  const session = new FakeSession(async () => {
    controller.abort();
    await new Promise((r) => setTimeout(r, 1));
  });
  await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      signal: controller.signal,
    },
    { createRuntime: async () => fakeRuntime(session), eventSink: (e) => events.push(e) },
  );
  const finished = events.at(-1) as Extract<RunEvent, { kind: "run_finished" }>;
  assert.equal(finished.outcome.status, "aborted");
});

test("runStage: the no_model early return still emits run_started + run_finished(failed/no_model)", async () => {
  const events: RunEvent[] = [];
  await runStage(
    {
      worktree: "/tmp/wt",
      stage: "implement",
      initialPrompt: "go",
      budget: eventBudget,
      model: new WorkerModelSelection({ getAvailableSnapshot: () => [] } as never),
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

test("runStage: a throwing injected eventSink never breaks the drive (fail-soft)", async () => {
  const savedErr = console.error;
  console.error = () => {};
  try {
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant", usage: { input: 10, output: 5 } } });
      emit({
        type: "tool_execution_end",
        toolName: "submit",
        result: { details: { ok: true, pr: { number: 3, url: "https://x/pr/3" } } },
      });
    });
    const outcome = await runStage(
      {
        worktree: "/tmp/wt",
        stage: "implement",
        initialPrompt: "go",
        budget: eventBudget,
      },
      {
        createRuntime: async () => fakeRuntime(session),
        now: () => 0,
        eventSink: () => {
          throw new Error("sink boom");
        },
      },
    );
    assert.equal(outcome.status, "completed", "a broken sink never aborts the drive");
    assert.deepEqual(outcome.pr, { number: 3, url: "https://x/pr/3" });
  } finally {
    console.error = savedErr;
  }
});

// --- default file sink (NDJSON under the gitignored run scratch dir) -----------------------------

test("runStage: with no eventSink + a set run_id writes parseable NDJSON to runEventsPath", async () => {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-events-"));
  const runId = "01JEVENTSTREAMTESTRUNID00000";
  const prior = process.env.PERK_RUN_ID;
  process.env.PERK_RUN_ID = runId;
  try {
    // Hoisted like the negative runStage test: marker-laden prose, no `content` field on
    // `DriveEvent` anymore.
    const markerTurn = { type: "turn_end", message: { role: "assistant", content: "[WIP:1]" } };
    const session = new FakeSession((emit) => {
      emit(markerTurn);
      emit({
        type: "tool_execution_end",
        toolName: "submit",
        result: { details: { ok: true, pr: { number: 9, url: "u" } } },
      });
    });
    const outcome = await runStage(
      {
        worktree,
        stage: "implement",
        initialPrompt: "go",
        budget: eventBudget,
      },
      { createRuntime: async () => fakeRuntime(session) },
    );
    assert.equal(outcome.run_id, runId, "the outcome carries the env-inherited run_id");
    const lines = readFileSync(runEventsPath(worktree, runId), "utf8").trim().split("\n");
    const parsed = lines.map((l) => JSON.parse(l) as RunEvent);
    assert.equal(parsed[0]?.kind, "run_started");
    assert.equal(parsed.at(-1)?.kind, "run_finished");
    assert.ok(parsed.some((e) => e.kind === "tool_outcome"));
  } finally {
    if (prior === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = prior;
  }
});

test("runStage: with an empty run_id writes nothing (the no-op default sink)", async () => {
  const worktree = mkdtempSync(join(tmpdir(), "perk-worker-noevents-"));
  const prior = process.env.PERK_RUN_ID;
  delete process.env.PERK_RUN_ID;
  try {
    const session = new FakeSession((emit) => {
      emit({ type: "turn_end", message: { role: "assistant" } });
    });
    const outcome = await runStage(
      {
        worktree,
        stage: "implement",
        initialPrompt: "go",
        budget: eventBudget,
      },
      { createRuntime: async () => fakeRuntime(session) },
    );
    assert.equal(outcome.run_id, "", "an unset PERK_RUN_ID reads as the empty run_id");
    assert.ok(!existsSync(runEventsPath(worktree, "")), "no events file when run_id is empty");
  } finally {
    if (prior === undefined) delete process.env.PERK_RUN_ID;
    else process.env.PERK_RUN_ID = prior;
  }
});
