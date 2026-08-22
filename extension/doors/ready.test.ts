// Live warm-door tests for `/ready` (the draft→ready review gate). Drive a REAL bound
// AgentSession via the T1 harness and prove the `perk pr ready` delegation end-to-end, OFFLINE: a
// fake `perk` (PERK_BIN) stands in for the GitHub mark-ready, so no LLM / network / gh is invoked.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ToolGating } from "../substrate/toolGating.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { driveReadyReconcile, markReady, type ReadyDetails } from "./ready.ts";

const READY_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://gh/o/r/pull/42" },
  was_draft: true,
});

const STACKED_READY_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://gh/o/r/pull/42" },
  was_draft: true,
  dry_run: false,
  stacked: true,
  objective: "500",
  node: "1.2",
  stamped_head: "b".repeat(40),
  stamp_advanced: true,
  reconcile_notice: "the ready-time reconcile pass was not launched",
  reconcile_retry: "perk ready 7",
  plan: "7",
  parent_checkpoint: "a".repeat(40),
});

test("tool: ready delegates, surfaces the PR, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: READY_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("ready", {});
    assert.equal(result.terminate, true, "ready terminates the turn");
    const details = result.details as {
      ok: boolean;
      pr?: { number?: number };
      was_draft?: boolean;
    };
    assert.equal(details.ok, true);
    assert.equal(details.pr?.number, 42);
    assert.equal(details.was_draft, true);
    assert.match(result.content[0]?.text ?? "", /#42/);
  } finally {
    h.dispose();
  }
});

test("tool: a missing/failing worker fails loud-but-soft (no terminate)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("ready", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true, "a failed ready does not terminate");
  } finally {
    h.dispose();
  }
});

test("tool: garbage worker output fails soft with bad_output", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "not json" });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("ready", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
  } finally {
    h.dispose();
  }
});

test("tool: success:true with a malformed pr fails as bad_output (unexpected payload)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, url: 12345 },
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("ready", {});
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
  } finally {
    h.dispose();
  }
});

// `markReady` is exercised directly here (not via the harness `invokeTool`) because the tool's
// `execute` now routes through `driveReadyReconcile`, which would inject a real model turn for
// a full stacked cohort the keyless harness can't service (the land precedent). The drive itself
// is unit-tested below with a spy `pi`.
test("markReady: a stacked payload surfaces the handoff facts (incl. the continuation cohort)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const piStub = {
    exec: async () => ({ code: 0, killed: false, stdout: STACKED_READY_JSON, stderr: "" }),
  } as unknown as ExtensionAPI;
  const ctx = { cwd, hasUI: false, isIdle: () => true } as unknown as ExtensionContext;
  const result = await markReady(piStub, ctx);
  assert.equal(result.terminate, true);
  const details = result.details as {
    ok: boolean;
    stacked?: boolean;
    handoff?: {
      objective?: string;
      node?: string;
      stamp_advanced?: boolean;
      plan?: string;
      parent_checkpoint?: string;
    };
  };
  assert.equal(details.ok, true);
  assert.equal(details.stacked, true, "the worker's routing fact passes through");
  assert.equal(details.handoff?.objective, "500");
  assert.equal(details.handoff?.node, "1.2");
  assert.equal(details.handoff?.stamp_advanced, true);
  assert.equal(details.handoff?.plan, "7");
  assert.equal(details.handoff?.parent_checkpoint, "a".repeat(40));
  const text = result.content[0]?.text ?? "";
  assert.match(text, /Handoff stamped/);
  assert.match(text, /objective #500 node 1\.2/);
  assert.match(text, /ready-time reconcile pass/);
  assert.match(text, /perk ready 7/);
});

test("tool: a partial stacked cohort is dropped whole (legacy success line)", async () => {
  // stacked:true without stamped_head (and without the two continuation fields) — the
  // augmentation must be validated-and-dropped whole, never half-rendered; the legacy success
  // line still renders (the worker already succeeded). Harness-safe: a dropped cohort drives
  // nothing (the malformed-cohort arm warns instead of injecting a turn).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const partial = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
    stacked: true,
    objective: "500",
    node: "1.2",
    stamp_advanced: true,
    reconcile_notice: "n",
    reconcile_retry: "perk ready 7",
    plan: "7",
    parent_checkpoint: "a".repeat(40),
  });
  const bin = fakePerk(cwd, { stdout: partial });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("ready", {});
    const details = result.details as { ok: boolean; stacked?: boolean; handoff?: object };
    assert.equal(details.ok, true);
    assert.equal(details.stacked, true, "the routing fact still passes through");
    assert.equal(details.handoff, undefined, "a partial cohort never attaches");
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Marked ready: PR #42 is open for review\./);
    assert.doesNotMatch(text, /Handoff/);
  } finally {
    h.dispose();
  }
});

// --- driveReadyReconcile: decision + delivery-mode unit tests (spy pi, no real turn) ---

function spyPi(): {
  pi: ExtensionAPI;
  calls: { content: string; options?: { deliverAs?: string } }[];
} {
  const calls: { content: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
      calls.push({ content, options });
    },
  } as unknown as ExtensionAPI;
  return { pi, calls };
}

function spyCtx(opts?: { idle?: boolean }): { ctx: ExtensionContext; warnings: string[] } {
  const warnings: string[] = [];
  const ctx = {
    cwd: ".",
    hasUI: true,
    isIdle: () => opts?.idle !== false,
    ui: {
      notify: (message: string, type?: string) => {
        if (type === "warning") warnings.push(message);
      },
    },
  } as unknown as ExtensionContext;
  return { ctx, warnings };
}

const GATE_OFF: ToolGating = { isActive: () => false } as ToolGating;
const GATE_ON: ToolGating = { isActive: () => true } as ToolGating;

function stackedDetails(): ReadyDetails {
  return {
    ok: true,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
    stacked: true,
    handoff: {
      objective: "500",
      node: "1.2",
      stamped_head: "b".repeat(40),
      stamp_advanced: true,
      reconcile_notice: "n",
      reconcile_retry: "perk ready 7",
      plan: "7",
      parent_checkpoint: "a".repeat(40),
    },
  };
}

test("driveReadyReconcile: failure → not driven, no warning", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  await driveReadyReconcile(pi, ctx, GATE_OFF, {
    ok: false,
    error: "boom",
    error_type: "github_error",
  });
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 0);
});

test("driveReadyReconcile: incremental (no handoff, stacked false/absent) → not driven, quiet", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  await driveReadyReconcile(pi, ctx, GATE_OFF, {
    ok: true,
    pr: { number: 42, url: "u" },
    was_draft: true,
    stacked: false,
  });
  await driveReadyReconcile(pi, ctx, GATE_OFF, {
    ok: true,
    pr: { number: 42, url: "u" },
    was_draft: true,
  });
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 0);
});

test("driveReadyReconcile: gate-active → no drive + loud warning", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  await driveReadyReconcile(pi, ctx, GATE_ON, stackedDetails());
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] ?? "", /read-only/);
  assert.match(warnings[0] ?? "", /stamp stands/);
});

test("driveReadyReconcile: stacked with a malformed cohort → no drive + loud warning", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  await driveReadyReconcile(pi, ctx, GATE_OFF, {
    ok: true,
    pr: { number: 42, url: "u" },
    was_draft: true,
    stacked: true,
  });
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] ?? "", /malformed/);
});

test("driveReadyReconcile: invalid evidence (abbreviated SHA) → no drive + loud warning", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  const details = stackedDetails();
  if (details.ok && details.handoff) details.handoff.parent_checkpoint = "abc123";
  await driveReadyReconcile(pi, ctx, GATE_OFF, details);
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] ?? "", /strict validation/);
});

test("driveReadyReconcile: idle (/ready command) → one immediate turn with the pinned range", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx({ idle: true });
  await driveReadyReconcile(pi, ctx, GATE_OFF, stackedDetails());
  assert.equal(warnings.length, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.options, undefined);
  const content = calls[0]?.content ?? "";
  assert.match(content, new RegExp(`${"a".repeat(40)}\\.\\.${"b".repeat(40)}`));
  assert.match(content, /objective #500/);
  assert.match(content, /gh pr view 42/);
  assert.match(content, /perk ready 7/);
  // The command:objective-reconcile binding suffix rides the same message (Mechanism B).
  assert.match(content, /perk-objective-reconcile/);
});

test("driveReadyReconcile: streaming (ready tool) → followUp", async () => {
  const { pi, calls } = spyPi();
  const { ctx } = spyCtx({ idle: false });
  await driveReadyReconcile(pi, ctx, GATE_OFF, stackedDetails());
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.options?.deliverAs, "followUp");
});

test("/ready command: notifies success", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: READY_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("ready");
    assert.ok(
      h.notifies.some((n) => /#42/.test(n)),
      "command notifies the ready PR",
    );
  } finally {
    h.dispose();
  }
});
