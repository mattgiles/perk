// Tests for the warm `/submit` mergeability gate. The pure `conflictResolutionGuidance` is
// pinned directly; `submitPr`'s advisory decode leniency is exercised against a faked cold door;
// `driveConflictResolution` (decision + cap + increment + reset) runs against in-memory fakes (the
// spy-pi + fake-branch recipe). OFFLINE — no LLM / network / gh / Python.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { scratchDir } from "../substrate/cache.ts";
import {
  readSessionPointers,
  recordSessionPointer,
  type SessionPointer,
} from "../substrate/sessionPointers.ts";
import { rebuildWorkflowState } from "../substrate/workflowState.ts";
import { scaffoldRepo } from "../testing/harness.ts";
import {
  CONFLICT_RESOLUTION_ATTEMPT_CAP,
  conflictResolutionGuidance,
  driveConflictResolution,
  type SubmitDetails,
  submitPr,
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

function submitJson(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
    branch: "plan-7",
    issue: 7,
    plan_embedded: false,
    base: "main",
    mergeable: true,
    conflicts: [],
    ...over,
  });
}

// --- conflictResolutionGuidance (pure) -----------------------------------------------------------

test("conflictResolutionGuidance spawns perk.conflict-resolver with a fresh context", () => {
  const text = conflictResolutionGuidance("main", 1, 2);
  assert.match(text, /perk\.conflict-resolver/);
  assert.match(text, /context: "fresh"/);
});

test("conflictResolutionGuidance dispatches ONE foreground workflowScript one-child run", () => {
  const text = conflictResolutionGuidance("main", 1, 2);
  assert.match(text, /workflowScript/);
  assert.match(text, /async: false/);
  assert.match(text, /runs\.run/);
});

test("conflictResolutionGuidance states the base branch and the clean+correct instruction", () => {
  const text = conflictResolutionGuidance("develop", 1, 2);
  assert.match(text, /`develop`/);
  assert.match(text, /\*\*clean\*\*/);
  assert.match(text, /\*\*correct\*\*/);
});

test("conflictResolutionGuidance notes the child reads its own plan/PR context", () => {
  const text = conflictResolutionGuidance("main", 1, 2);
  assert.match(text, /perk pr review-context/);
  assert.match(text, /intent/);
});

test("conflictResolutionGuidance renders the attempt-of-cap text", () => {
  const text = conflictResolutionGuidance("main", 2, 3);
  assert.match(text, /attempt 2 of 3/);
});

test("conflictResolutionGuidance tells the model to re-/submit afterward", () => {
  const text = conflictResolutionGuidance("main", 1, 2);
  assert.match(text, /`\/submit` again/);
});

test("conflictResolutionGuidance injects the configured model when set", () => {
  const text = conflictResolutionGuidance("main", 1, 2, "anthropic/claude-opus-4");
  assert.match(text, /model: "anthropic\/claude-opus-4"/);
  assert.match(text, /\[models\.subagents\] conflict-resolver model/);
});

test("conflictResolutionGuidance omits the model override when unset", () => {
  const text = conflictResolutionGuidance("main", 1, 2);
  assert.doesNotMatch(text, /model: "/);
  assert.match(text, /default model/);
});

// --- submitPr advisory decode leniency -----------------------------------------------------------

test("submitPr keeps a clean decode when mergeability fields are present", async () => {
  const { pi, ctx } = world({ stdout: submitJson() });
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true);
  assert.equal(result.details.base, "main");
  assert.equal(result.details.mergeable, true);
  assert.deepEqual(result.details.conflicts, []);
  assert.equal(result.terminate, true);
});

test("submitPr keeps a clean decode when mergeability fields are absent", async () => {
  const { pi, ctx } = world({
    stdout: JSON.stringify({
      success: true,
      error_type: null,
      message: null,
      pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
    }),
  });
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true);
  assert.equal(result.details.mergeable, undefined);
  assert.deepEqual(result.details.conflicts, []);
});

test("submitPr keeps a clean decode when mergeability fields are malformed", async () => {
  const { pi, ctx } = world({
    stdout: submitJson({ mergeable: "nope", conflicts: "oops", base: 5 }),
  });
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true, "malformed advisory fields never sink the decode");
  assert.equal(result.details.mergeable, undefined);
  assert.deepEqual(result.details.conflicts, []);
  assert.equal(result.details.base, undefined);
});

test("submitPr reflects conflicts in the success message", async () => {
  const { pi, ctx } = world({ stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }) });
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true);
  assert.match(result.content[0]?.text ?? "", /merge conflicts detected; resolving/);
});

test("submitPr resets the conflict counter on a clean submit", async () => {
  const { pi, ctx, entries } = world({ stdout: submitJson(), attempts: 1 });
  await submitPr(pi, ctx);
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 0);
});

test("submitPr does not reset on a conflicted submit", async () => {
  const { pi, ctx, entries } = world({
    stdout: submitJson({ mergeable: false, conflicts: ["a.py"] }),
    attempts: 1,
  });
  await submitPr(pi, ctx);
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 1);
});

// --- the submit-door implementation/main capture --------------------------------------------------

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
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true);
  const record = readSessionPointers(cwd, "01RID");
  assert.equal(record?.implementation.main?.pi_session_id, "address.jsonl");
  assert.equal(record?.implementation.main?.session_file, "/sessions/address.jsonl");
});

test("no branch run_id ⇒ submit writes no session-pointer record", async () => {
  // The existing fixture default (no run_id entry) — also proves the older cases stay inert.
  const cwd = mkdtempSync(join(tmpdir(), "perk-submit-"));
  const { pi, ctx } = world({ cwd, stdout: submitJson(), sessionFile: "/sessions/a.jsonl" });
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true);
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
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, false);
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
  const result = await submitPr(pi, ctx);
  assert.equal(result.details.ok, true, "the skipped capture never sinks a successful submit");
  assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, implementPointer);
});

// --- driveConflictResolution: decision + cap + increment + delivery mode --------------------------

const CONFLICT_DETAILS: SubmitDetails = {
  ok: true,
  pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
  base: "main",
  mergeable: false,
  conflicts: ["a.py"],
};

test("driveConflictResolution: clean submit → not driven", () => {
  const { pi, ctx, messages } = world();
  driveConflictResolution(pi, ctx, {
    ok: true,
    pr: { number: 42, url: "u", is_draft: true, existed: false },
    mergeable: true,
    conflicts: [],
  });
  assert.equal(messages.length, 0);
});

test("driveConflictResolution: undetermined (null) submit → not driven", () => {
  const { pi, ctx, messages } = world();
  driveConflictResolution(pi, ctx, {
    ok: true,
    pr: { number: 42, url: "u", is_draft: true, existed: false },
    mergeable: null,
    conflicts: [],
  });
  assert.equal(messages.length, 0);
});

test("driveConflictResolution: failed submit → not driven", () => {
  const { pi, ctx, messages } = world();
  driveConflictResolution(pi, ctx, { ok: false, error: "boom", error_type: "exec_failed" });
  assert.equal(messages.length, 0);
});

test("driveConflictResolution: conflicts → drives + increments the counter", () => {
  const { pi, ctx, messages, entries } = world();
  driveConflictResolution(pi, ctx, CONFLICT_DETAILS);
  assert.equal(messages.length, 1);
  assert.match(messages[0]?.content ?? "", /perk\.conflict-resolver/);
  assert.equal(rebuildWorkflowState(entries).conflict_resolution_attempts, 1);
});

test("driveConflictResolution: idle (/submit command) → immediate turn", () => {
  const { pi, ctx, messages } = world({ idle: true });
  driveConflictResolution(pi, ctx, CONFLICT_DETAILS);
  assert.equal(messages[0]?.options, undefined);
});

test("driveConflictResolution: streaming (submit tool) → followUp", () => {
  const { pi, ctx, messages } = world({ idle: false });
  driveConflictResolution(pi, ctx, CONFLICT_DETAILS);
  assert.equal(messages[0]?.options?.deliverAs, "followUp");
});

test("driveConflictResolution: at the cap → no drive, loud report", () => {
  const { pi, ctx, messages, entries } = world({ attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP });
  driveConflictResolution(pi, ctx, CONFLICT_DETAILS);
  assert.equal(messages.length, 0, "no further drive past the cap");
  // The counter is not incremented past the cap.
  assert.equal(
    rebuildWorkflowState(entries).conflict_resolution_attempts,
    CONFLICT_RESOLUTION_ATTEMPT_CAP,
  );
});

test("scaffoldRepo cwd: drive reads config without throwing", () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const { pi, ctx, messages } = world({ cwd });
  driveConflictResolution(pi, ctx, CONFLICT_DETAILS);
  assert.equal(messages.length, 1);
});
