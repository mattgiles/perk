// Live warm-surface tests for the change-publication bindings (pi/v1/delivery/submit.ts): the
// frozen registration baselines (tool + command), the full-details WIRE baselines captured from
// the pre-migration door (byte-exact on the JSON round-trip — the true wire shape — including
// optional-key absence semantics; the ONE documented delta: `issue` decodes as the opaque
// string the Python boundary actually sends), the moved decode-leniency matrix through the
// registered tool, the run-id argv pin, the pointer-capture set, the counter behaviors, the
// guidance render suite, the drive translation, and the command report-before-drive order pin.
// OFFLINE — no LLM / network / gh / Python.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { CONFLICT_RESOLUTION_ATTEMPT_CAP, submitChange } from "../../../delivery/submit.ts";
import { scratchDir } from "../../../substrate/cache.ts";
import {
  readSessionPointers,
  recordSessionPointer,
  type SessionPointer,
} from "../../../substrate/sessionPointers.ts";
import { rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { REPORT_DETAIL_TYPE } from "../../../surfaces/surfaces.ts";
import {
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import {
  conflictResolutionGuidance,
  driveConflictFollowUp,
  publishDepsFor,
  renderPublishedMessage,
} from "./submit.ts";

// --- a shared in-memory world: fake `pi` (exec + appendEntry + sendUserMessage) + fake ctx -------

interface Entry {
  type: string;
  customType?: string;
  data?: Record<string, unknown>;
}

function world(opts?: {
  cwd?: string;
  idle?: boolean;
  stdout?: string;
  code?: number;
  attempts?: number;
  runId?: string;
  sessionFile?: string;
}) {
  const entries: Entry[] = [];
  if (opts?.attempts !== undefined) {
    entries.push({
      type: "custom",
      customType: "perk:workflow-state",
      data: { conflict_resolution_attempts: opts.attempts },
    });
  }
  if (opts?.runId !== undefined) {
    entries.push({
      type: "custom",
      customType: "perk:workflow-state",
      data: { run_id: opts.runId },
    });
  }
  const messages: { content: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    exec: async () => ({
      code: opts?.code ?? 0,
      killed: false,
      stdout: opts?.stdout ?? "",
      stderr: "",
    }),
    appendEntry: (customType: string, data?: unknown) => {
      entries.push({ type: "custom", customType, data: data as Record<string, unknown> });
    },
    sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
      messages.push({ content, options });
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd: opts?.cwd ?? ".",
    hasUI: false,
    isIdle: () => opts?.idle ?? true,
    sessionManager: { getBranch: () => entries, getSessionFile: () => opts?.sessionFile ?? null },
  } as unknown as ExtensionContext;
  return { pi, ctx, entries, messages };
}

const PUSH_REJECTED_MESSAGE =
  "Push rejected — the remote branch moved unexpectedly.\n" +
  "Fetch/rebase onto the latest origin and re-submit.\n" +
  "! [rejected] plan-7 -> plan-7 (non-fast-forward)";

function submitJson(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
    branch: "plan-7",
    issue: "7",
    plan_embedded: false,
    base: "main",
    mergeable: true,
    conflicts: [],
    ...over,
  });
}

function pushRejectedJson(): string {
  return JSON.stringify({
    success: false,
    error_type: "push_rejected",
    message: PUSH_REJECTED_MESSAGE,
    dry_run: false,
  });
}

/** Invoke the REAL registered submit tool against a fake cold door; JSON round-trip the result
 * (the true wire shape — optional keys carrying `undefined` drop exactly as they do on the wire). */
async function invokeSubmit(opts: { stdout: string; code?: number }) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: opts.stdout, code: opts.code ?? 0 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    return JSON.parse(
      JSON.stringify({
        text: result.content[0]?.text,
        details: result.details,
        terminate: result.terminate ?? null,
      }),
    ) as { text: string; details: Record<string, unknown>; terminate: boolean | null };
  } finally {
    h.dispose();
  }
}

// --- frozen registration baselines ----------------------------------------------------------

const BASELINE_SUBMIT_TOOL = {
  name: "submit",
  label: "Submit PR",
  description:
    "Push the current plan's branch and open a draft pull request linking the plan. " +
    "Terminating: ends the turn on submit. Call only after the implementation is committed.",
  parameters: { type: "object", additionalProperties: false, properties: {} },
  promptSnippet: "Open the draft PR for the committed implementation (terminates the turn)",
  promptGuidelines: [
    "Call submit only after the implementation is committed in this worktree; it pushes the branch and opens the draft PR, then ends the turn.",
    "submit operates on the active plan's worktree — it takes no arguments; the branch and plan come from the local plan-ref.",
  ],
  executionMode: "sequential",
};

test("registration parity: submit tool + /submit command match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(
      h.registeredTool("submit"),
      BASELINE_SUBMIT_TOOL,
      "the COMPLETE submit registration surface must match the frozen baseline",
    );
    assert.deepEqual(h.registeredCommand("submit"), {
      name: "submit",
      description: "Push the branch and open a draft PR for the active plan (implement → submit).",
    });
  } finally {
    h.dispose();
  }
});

// --- full-details wire baselines (captured from the pre-migration door) ----------------------

const BASE_DETAILS = {
  ok: true,
  pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
  branch: "plan-7",
  issue: "7",
  plan_embedded: false,
  base: "main",
  mergeable: true,
  conflicts: [],
};

test("wire baseline: clean success (issue rides as the opaque string id)", async () => {
  const r = await invokeSubmit({ stdout: submitJson() });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 (no plan embed)");
  assert.deepEqual(r.details, BASE_DETAILS);
  assert.equal(r.terminate, true);
});

test("wire baseline: a number-valued issue is dropped (the decode narrows to the string wire)", async () => {
  // The pre-migration decode read `numberField(payload, "issue")` — which never matched the
  // real string payload; the aligned decode never matches a number. Regression both ways.
  const r = await invokeSubmit({ stdout: submitJson({ issue: 7 }) });
  const { issue: _issue, ...withoutIssue } = BASE_DETAILS;
  assert.deepEqual(r.details, withoutIssue);
});

test("wire baseline: conflicted", async () => {
  const r = await invokeSubmit({ stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }) });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 — merge conflicts detected; resolving");
  assert.deepEqual(r.details, { ...BASE_DETAILS, mergeable: false, conflicts: ["a.py"] });
  assert.equal(r.terminate, true);
});

test("wire baseline: stacked facts", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({ delivery: "stacked", stack: { number: 9, size: 3, position: 2 } }),
  });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 (no plan embed) (stack #9, layer 2/3)");
  assert.deepEqual(r.details, {
    ...BASE_DETAILS,
    delivery: "stacked",
    stack: { number: 9, size: 3, position: 2 },
  });
});

test("wire baseline: cascade", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({
      delivery: "stacked",
      operation: {
        kind: "sync",
        operation_id: "op-1",
        abandoned_operation_id: null,
        resumed: false,
        no_op: false,
        affected: [{ node_id: "1.1" }, { node_id: "1.2" }],
        notes: ["concluded unresolved operation old-op"],
      },
    }),
  });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 (no plan embed) (cascaded 2 layer(s))");
  assert.deepEqual(r.details, {
    ...BASE_DETAILS,
    delivery: "stacked",
    operation: {
      kind: "sync",
      operation_id: "op-1",
      no_op: false,
      affected_count: 2,
      notes: ["concluded unresolved operation old-op"],
    },
  });
});

test("wire baseline: no-op cascade", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({
      delivery: "stacked",
      operation: { kind: "sync", operation_id: null, no_op: true, affected: [], notes: [] },
    }),
  });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 (no plan embed) (suffix already in sync)");
  assert.deepEqual(r.details, {
    ...BASE_DETAILS,
    delivery: "stacked",
    operation: { kind: "sync", operation_id: null, no_op: true, affected_count: 0, notes: [] },
  });
});

test("wire baseline: a malformed operation block drops without sinking submit", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({
      delivery: "stacked",
      operation: { kind: "sync", operation_id: null, no_op: "yes", affected: [], notes: [] },
    }),
  });
  assert.equal(r.text, "Opened draft PR #42 → u/pr/42 (no plan embed) (stacked layer)");
  assert.deepEqual(r.details, { ...BASE_DETAILS, delivery: "stacked" });
});

test("wire baseline: the failure arm", async () => {
  const r = await invokeSubmit({ stdout: pushRejectedJson(), code: 1 });
  assert.equal(r.text, `submit failed: ${PUSH_REJECTED_MESSAGE}`);
  assert.deepEqual(r.details, {
    ok: false,
    error: PUSH_REJECTED_MESSAGE,
    error_type: "push_rejected",
  });
  assert.equal(r.terminate, null);
});

// --- the moved decode-leniency matrix (through the registered tool) --------------------------

test("decode: mergeability fields absent keeps a clean decode", async () => {
  const r = await invokeSubmit({
    stdout: JSON.stringify({
      success: true,
      error_type: null,
      message: null,
      pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
    }),
  });
  assert.deepEqual(r.details, {
    ok: true,
    pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
    conflicts: [],
  });
});

test("decode: malformed advisory fields never sink the decode", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({ mergeable: "nope", conflicts: "oops", base: 5 }),
  });
  assert.equal(r.details.ok, true);
  assert.equal(r.details.mergeable, undefined);
  assert.deepEqual(r.details.conflicts, []);
  assert.equal(r.details.base, undefined);
});

test("decode: a stacked bottom layer without stack facts keeps the stacked suffix", async () => {
  const r = await invokeSubmit({ stdout: submitJson({ delivery: "stacked", stack: null }) });
  assert.equal(r.details.stack, undefined);
  assert.match(r.text, /\(stacked layer\)$/);
});

test("decode: malformed stacked fields never sink the decode", async () => {
  const r = await invokeSubmit({
    stdout: submitJson({ delivery: 7, stack: { number: "nine", size: 3 } }),
  });
  assert.equal(r.details.ok, true);
  assert.equal(r.details.delivery, undefined);
  assert.equal(r.details.stack, undefined);
});

test("decode: a definitive conflict with unparsed paths still reflects in the message", async () => {
  const r = await invokeSubmit({ stdout: submitJson({ mergeable: false, conflicts: [] }) });
  assert.match(r.text, /merge conflicts detected; resolving/);
});

// --- the run-id argv pin ----------------------------------------------------------------------

test("argv: a planted run id rides as an adjacent --run-id flag pair", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: submitJson(), argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("submit", {});
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), [
      "pr",
      "submit",
      "--json",
      "--run-id",
      "01RID",
    ]);
  } finally {
    h.dispose();
  }
});

test("argv: no branch run id ⇒ no --run-id flag", async () => {
  // A LOADED warm session always mints a run id (the identity-less arm), so the absent-run-id
  // wire is pinned through the production deps over a branch with no run_id entry.
  const argvs: string[][] = [];
  const { pi, ctx } = world({ stdout: submitJson() });
  (pi as unknown as { exec: unknown }).exec = async (_bin: string, args: string[]) => {
    argvs.push(args);
    return { code: 0, killed: false, stdout: submitJson(), stderr: "" };
  };
  const outcome = await submitChange(publishDepsFor(pi, ctx));
  assert.equal(outcome.kind, "published");
  assert.deepEqual(argvs, [["pr", "submit", "--json"]]);
});

// --- counter behaviors through the production deps --------------------------------------------

test("a clean submit resets the conflict counter", async () => {
  const { pi, ctx, entries } = world({ stdout: submitJson(), attempts: 1 });
  await submitChange(publishDepsFor(pi, ctx));
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 0);
});

test("a conflicted submit does not reset", async () => {
  const { pi, ctx, entries } = world({
    stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }),
    attempts: 1,
  });
  await submitChange(publishDepsFor(pi, ctx));
  // The conflicted publish never resets; the decide arm was at 1 < cap ⇒ incremented to 2.
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 2);
});

test("notes warnings surface on success through the publisher port", async () => {
  const { pi, ctx } = world({
    stdout: submitJson({
      delivery: "stacked",
      operation: {
        kind: "sync",
        operation_id: "op-1",
        no_op: false,
        affected: [{ node_id: "1.1" }],
        notes: ["concluded unresolved operation old-op"],
      },
    }),
  });
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => lines.push(args.map(String).join(" "));
  try {
    const outcome = await submitChange(publishDepsFor(pi, ctx));
    assert.equal(outcome.kind, "published");
  } finally {
    console.error = original;
  }
  assert.ok(lines.some((line) => line.includes("concluded unresolved operation old-op")));
});

// --- the implementation/main pointer-capture set ------------------------------------------------

test("a successful submit with a run id + session file captures implementation.main", async () => {
  // The address/warm case: a session the stage-gated session_start capture never sees still gets
  // its pointer captured at impl_run_ids-stamping time, so the run resolves `found`.
  const cwd = mkdtempSync(join(tmpdir(), "perk-submit-"));
  const { pi, ctx } = world({
    cwd,
    stdout: submitJson(),
    runId: "01RID",
    sessionFile: "/sessions/address.jsonl",
  });
  const outcome = await submitChange(publishDepsFor(pi, ctx));
  assert.equal(outcome.kind, "published");
  const record = readSessionPointers(cwd, "01RID");
  assert.equal(record?.implementation.main?.pi_session_id, "address.jsonl");
  assert.equal(record?.implementation.main?.session_file, "/sessions/address.jsonl");
});

test("no branch run_id ⇒ submit writes no session-pointer record", async () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-submit-"));
  const { pi, ctx } = world({ cwd, stdout: submitJson(), sessionFile: "/sessions/a.jsonl" });
  const outcome = await submitChange(publishDepsFor(pi, ctx));
  assert.equal(outcome.kind, "published");
  assert.equal(existsSync(scratchDir(cwd)), false, "no scratch record was written");
});

test("a failed submit captures nothing", async () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-submit-"));
  const { pi, ctx } = world({
    cwd,
    stdout: JSON.stringify({ success: false, error_type: "no_pr", message: "boom" }),
    runId: "01RID",
    sessionFile: "/sessions/address.jsonl",
  });
  const outcome = await submitChange(publishDepsFor(pi, ctx));
  assert.equal(outcome.kind, "publish_failed");
  assert.equal(readSessionPointers(cwd, "01RID"), null);
});

test("a pre-seeded foreign implementation.main survives submit (preserveForeign end-to-end)", async () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-submit-"));
  const implementPointer: SessionPointer = {
    pi_session_id: "implement.jsonl",
    session_file: "/sessions/implement.jsonl",
    parent_pi_session_id: null,
    at: "2026-06-01T00:00:00Z",
  };
  recordSessionPointer(cwd, "01RID", "implementation", "main", implementPointer);
  const { pi, ctx } = world({
    cwd,
    stdout: submitJson(),
    runId: "01RID",
    sessionFile: "/sessions/address.jsonl",
  });
  const outcome = await submitChange(publishDepsFor(pi, ctx));
  assert.equal(outcome.kind, "published", "the skipped capture never sinks a successful submit");
  assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, implementPointer);
});

// --- command-vs-tool report projections (the envelope-aware regression pair) --------------------

test("/submit: multiline push rejection is a headline plus one durable detail entry", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: pushRejectedJson(), code: 1 });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    mode: "print",
  });
  const stderr: string[] = [];
  t.mock.method(console, "error", (message: unknown) => stderr.push(String(message)));
  try {
    await h.invokeCommand("submit");
    const errors = h.notifyEvents.filter((event) => event.severity === "error");
    assert.deepEqual(errors, [
      {
        message: "perk: submit — Push rejected — the remote branch moved unexpectedly.",
        severity: "error",
      },
    ]);

    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: unknown;
    }[];
    const details = entries.filter((entry) => entry.customType === REPORT_DETAIL_TYPE);
    assert.deepEqual(
      details.map((entry) => entry.data),
      [{ text: `perk: submit — ${PUSH_REJECTED_MESSAGE}`, severity: "error" }],
    );
    assert.deepEqual(stderr, []);
  } finally {
    h.dispose();
  }
});

test("submit tool: multiline push rejection stays complete without a transcript detail", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: pushRejectedJson(), code: 1 });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    mode: "print",
  });
  const stderr: string[] = [];
  t.mock.method(console, "error", (message: unknown) => stderr.push(String(message)));
  try {
    const result = await h.invokeTool("submit", {});
    assert.equal(result.content[0]?.text, `submit failed: ${PUSH_REJECTED_MESSAGE}`);
    assert.deepEqual(result.details, {
      ok: false,
      error: PUSH_REJECTED_MESSAGE,
      error_type: "push_rejected",
    });

    const entries = h.session.sessionManager.getEntries() as unknown as { customType?: string }[];
    assert.equal(entries.filter((entry) => entry.customType === REPORT_DETAIL_TYPE).length, 0);
    assert.deepEqual(stderr, []);
  } finally {
    h.dispose();
  }
});

// --- planning refusal ----------------------------------------------------------------------------

test("planning-stage refusal: the submit tool refuses before any cold door", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: submitJson(), argvFile });
  const file = plantSession(
    cwd,
    [{ run_id: "01RID", mode: "read-write", stage: "plan", pi_session_id: "planning.jsonl" }],
    { fileName: "planning.jsonl" },
  );
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
    mode: "print",
  });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "planning_session");
    assert.ok(!existsSync(argvFile), "no cold door ran from the planning session");
  } finally {
    h.dispose();
  }
});

// --- conflictResolutionGuidance (pure) -----------------------------------------------------------

test("conflictResolutionGuidance spawns perk.conflict-resolver with a fresh context", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.match(text, /perk\.conflict-resolver/);
  assert.match(text, /context: "fresh"/);
});

test("conflictResolutionGuidance dispatches ONE foreground workflowScript one-child run", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.match(text, /workflowScript/);
  assert.match(text, /async: false/);
  assert.match(text, /runs\.run/);
});

test("conflictResolutionGuidance states the base branch and the clean+correct instruction", () => {
  const text = conflictResolutionGuidance("develop", 1, 2, "/wt/plan-42");
  assert.match(text, /`develop`/);
  assert.match(text, /\*\*clean\*\*/);
  assert.match(text, /\*\*correct\*\*/);
});

test("conflictResolutionGuidance notes the child reads its own plan/PR context", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.match(text, /perk pr review-context/);
  assert.match(text, /intent/);
});

test("conflictResolutionGuidance renders the attempt-of-cap text", () => {
  const text = conflictResolutionGuidance("main", 2, 3, "/wt/plan-42");
  assert.match(text, /attempt 2 of 3/);
});

test("conflictResolutionGuidance pins the plan worktree with a concrete cd command", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.match(text, /`cd \/wt\/plan-42`/);
});

test("conflictResolutionGuidance tells the model to re-/submit afterward", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.match(text, /`\/submit` again/);
});

test("conflictResolutionGuidance injects the configured model when set", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42", "anthropic/claude-opus-4");
  assert.match(text, /model: "anthropic\/claude-opus-4"/);
  assert.match(text, /\[models\.subagents\] conflict-resolver model/);
});

test("conflictResolutionGuidance omits the model override when unset", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "/wt/plan-42");
  assert.doesNotMatch(text, /model: "/);
  assert.match(text, /default model/);
});

// --- renderPublishedMessage (pure) ---------------------------------------------------------------

test("renderPublishedMessage: the existing-PR verb", () => {
  const text = renderPublishedMessage({
    pr: { number: 42, url: "u/pr/42", is_draft: true, existed: true },
    plan_embedded: true,
  });
  assert.equal(text, "Found existing PR #42 → u/pr/42 (plan embedded)");
});

// --- driveConflictFollowUp: translation + delivery mode -------------------------------------------

test("driveConflictFollowUp: none ⇒ nothing", () => {
  const { pi, ctx, messages } = world();
  driveConflictFollowUp(pi, ctx, { kind: "none" });
  assert.equal(messages.length, 0);
});

test("driveConflictFollowUp: drive ⇒ the guidance rides one injected message", () => {
  const { pi, ctx, messages } = world();
  driveConflictFollowUp(pi, ctx, { kind: "drive", base: "main", attempt: 1, cap: 2 });
  assert.equal(messages.length, 1);
  assert.match(messages[0]?.content ?? "", /perk\.conflict-resolver/);
});

test("driveConflictFollowUp: idle (/submit command) → immediate turn", () => {
  const { pi, ctx, messages } = world({ idle: true });
  driveConflictFollowUp(pi, ctx, { kind: "drive", base: "main", attempt: 1, cap: 2 });
  assert.equal(messages[0]?.options, undefined);
});

test("driveConflictFollowUp: streaming (submit tool) → followUp", () => {
  const { pi, ctx, messages } = world({ idle: false });
  driveConflictFollowUp(pi, ctx, { kind: "drive", base: "main", attempt: 1, cap: 2 });
  assert.equal(messages[0]?.options?.deliverAs, "followUp");
});

test("driveConflictFollowUp: exhausted ⇒ no drive, loud report", () => {
  const { pi, ctx, messages } = world();
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => lines.push(args.map(String).join(" "));
  try {
    driveConflictFollowUp(pi, ctx, {
      kind: "exhausted",
      base: "main",
      attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP,
    });
  } finally {
    console.error = original;
  }
  assert.equal(messages.length, 0, "no further drive past the cap");
  assert.deepEqual(lines, [
    "perk: submit — merge conflicts persist after 2 resolution attempt(s) — resolve manually " +
      "(rebase onto `main` and push), then re-run /submit.",
  ]);
});

test("scaffoldRepo cwd: drive reads config without throwing", () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const { pi, ctx, messages } = world({ cwd });
  driveConflictFollowUp(pi, ctx, { kind: "drive", base: "main", attempt: 1, cap: 2 });
  assert.equal(messages.length, 1);
});

// --- the composed conflicted drive through the REAL registered tool -------------------------------

test("submit tool e2e: a conflicted submit drives the resolver and increments the counter", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }) });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("submit", {});
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.equal(result.terminate, true, "the terminating tool stays terminating");
    assert.equal(injected.length, 1);
    assert.match(injected[0] ?? "", /perk\.conflict-resolver/);
    assert.equal(h.workflowState().conflict_resolution_attempts, 1);
  } finally {
    h.dispose();
  }
});

test("submit tool e2e: at the cap ⇒ loud report, no drive, counter unchanged", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }) });
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      mode: "read-write",
      conflict_resolution_attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP,
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  const injected = spyInjections(h);
  try {
    await h.invokeTool("submit", {});
    assert.equal(injected.length, 0, "no further drive past the cap");
    // invokeTool's ctx shares the message-only notify capture (not the severity-tagged array).
    assert.ok(h.notifies.some((message) => /merge conflicts persist after 2/.test(message)));
    assert.equal(h.workflowState().conflict_resolution_attempts, CONFLICT_RESOLUTION_ATTEMPT_CAP);
  } finally {
    h.dispose();
  }
});

// --- the command order pin: report-before-drive ---------------------------------------------------

test("/submit command: the success info line lands BEFORE the injected drive turn", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }) });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
    mode: "print",
  });
  // ONE shared recorder across both channels: headless report() writes console.error; the
  // injected drive turn rides sendUserMessage — the interleaving IS the order pin.
  const events: string[] = [];
  t.mock.method(console, "error", (message: unknown) => events.push(`report:${String(message)}`));
  (
    h.session as unknown as { sendUserMessage: (c: unknown, o?: unknown) => Promise<void> }
  ).sendUserMessage = async (c) => {
    events.push(`inject:${typeof c === "string" ? c.slice(0, 30) : "?"}`);
  };
  try {
    await h.invokeCommand("submit");
    const reportIndex = events.findIndex((e) =>
      e.startsWith("report:perk: submit — Opened draft PR #42"),
    );
    const injectIndex = events.findIndex((e) => e.startsWith("inject:"));
    assert.notEqual(reportIndex, -1, "the success line was reported");
    assert.notEqual(injectIndex, -1, "the drive turn was injected");
    assert.ok(reportIndex < injectIndex, "report-before-drive");
  } finally {
    h.dispose();
  }
});
