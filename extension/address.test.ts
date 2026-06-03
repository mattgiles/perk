// P2.T7 — live warm-door tests for the `/address` review loop. Drive a REAL bound AgentSession via
// the T1 harness and prove the `resolve_review_threads` delegation end-to-end, OFFLINE: a fake
// `perk` (PERK_BIN) stands in for the GitHub mutation, so no LLM / network / gh / Python is invoked.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

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
    const details = result.details as { ok: boolean; resolved_thread_ids?: string[] };
    assert.equal(details.ok, false);
    assert.deepEqual(details.resolved_thread_ids, ["PRRT_1"]);
    // a failed batch records NO last_review_batch.
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
