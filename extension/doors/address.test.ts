// P2.T7 — live warm-door tests for the `/address` review loop. Drive a REAL bound AgentSession via
// the T1 harness and prove the `resolve_review_threads` delegation end-to-end, OFFLINE: a fake
// `perk` (PERK_BIN) stands in for the GitHub mutation, so no LLM / network / gh / Python is invoked.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { addressGuidance, decodeResolveParams } from "./address.ts";

test("addressGuidance injects the configured review-classifier model when set", () => {
  const text = addressGuidance(false, "x/y");
  assert.match(text, /model: "x\/y"/);
  assert.match(text, /\[subagents\] review-classifier model/);
});

test("addressGuidance omits the model override when unset", () => {
  assert.doesNotMatch(addressGuidance(false), /model: "/);
});

const RESOLVE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  results: [
    { thread_id: "PRRT_1", success: true, comment_added: true, error: null },
    { thread_id: "PRRT_2", success: true, comment_added: false, error: null },
  ],
});

const PARTIAL_JSON = JSON.stringify({
  success: false,
  error_type: null,
  message: null,
  dry_run: false,
  results: [
    { thread_id: "PRRT_1", success: true, comment_added: false, error: null },
    { thread_id: "PRRT_2", success: false, comment_added: false, error: "bad thread" },
  ],
});

test("tool: resolve_review_threads delegates, surfaces results, records last_review_batch", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: RESOLVE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1", comment: "Fixed" }, { thread_id: "PRRT_2" }],
      pr: 42,
      counts: { actionable: 2, informational: 0, praise: 0, question: 0 },
    });
    const details = result.details as { ok: boolean; resolved_thread_ids?: string[] };
    assert.equal(details.ok, true);
    assert.deepEqual(details.resolved_thread_ids, ["PRRT_1", "PRRT_2"]);
    // last_review_batch landed in workflow-state (strict read-back via rebuild).
    const batch = h.workflowState().last_review_batch as {
      pr?: number;
      resolved_thread_ids?: string[];
    };
    assert.equal(batch?.pr, 42);
    assert.deepEqual(batch?.resolved_thread_ids, ["PRRT_1", "PRRT_2"]);
  } finally {
    h.dispose();
  }
});

test("tool: a partial batch is loud-but-soft (ok=false, no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PARTIAL_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1" }, { thread_id: "PRRT_2" }],
    });
    const details = result.details as {
      ok: boolean;
      error_type?: string;
      resolved_thread_ids?: string[];
    };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "partial_failure");
    assert.deepEqual(details.resolved_thread_ids, ["PRRT_1"]);
    assert.match(result.content[0]?.text ?? "", /Resolved 1\/2 thread\(s\); 1 failed\./);
    // a failed batch records NO last_review_batch.
    assert.equal(h.workflowState().last_review_batch, undefined);
  } finally {
    h.dispose();
  }
});

test("tool: a success envelope with malformed results rows fails as bad_output", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    results: [{ thread_id: "PRRT_1", success: "yes", comment_added: false }],
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1" }],
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    // No half-rendered partial table and no recorded batch.
    assert.equal(h.workflowState().last_review_batch, undefined);
  } finally {
    h.dispose();
  }
});

test("tool: a failing worker fails loud-but-soft", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1" }],
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
  } finally {
    h.dispose();
  }
});

test("tool: empty threads fails with bad_input (no worker call)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: RESOLVE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", { threads: [] });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});

test("/address and /address --preview register and are headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("address"), "the /address command is registered");
  } finally {
    h.dispose();
  }
});

// --- Node 3.2: tool-boundary decode (strict-fail on mistyped params) -----------------------

test("tool: a row missing thread_id → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: RESOLVE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1" }, { comment: "no id" }],
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("tool: mistyped counts → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: RESOLVE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("resolve_review_threads", {
      threads: [{ thread_id: "PRRT_1" }],
      counts: "x",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("decodeResolveParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeResolveParams({ threads: [{ thread_id: "t1", comment: "c" }] }), {
    threads: [{ thread_id: "t1", comment: "c" }],
    pr: undefined,
    counts: undefined,
  });
  // threads absent/non-array decodes to [] (the existing empty-batch bad_input arm fires).
  assert.deepEqual(decodeResolveParams({})?.threads, []);
  assert.deepEqual(decodeResolveParams({ threads: "x" })?.threads, []);
  assert.equal(decodeResolveParams(undefined), null);
  assert.equal(decodeResolveParams({ threads: [{ comment: "no id" }] }), null);
  assert.equal(decodeResolveParams({ threads: [{ thread_id: 5 }] }), null);
  assert.equal(decodeResolveParams({ threads: [{ thread_id: "t1", comment: 5 }] }), null);
  assert.equal(decodeResolveParams({ threads: [], pr: "42" }), null);
  assert.equal(decodeResolveParams({ threads: [], counts: "x" }), null);
  assert.equal(decodeResolveParams({ threads: [], counts: { actionable: "2" } }), null);
  assert.deepEqual(decodeResolveParams({ threads: [], counts: { actionable: 2 } })?.counts, {
    actionable: 2,
  });
});
