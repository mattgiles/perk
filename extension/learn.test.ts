// P1.T5b — live warm-door tests for `/learn` (turn-5 §10). TS-only: no delegation, no gh — `/learn`
// clears the pending-learn semaphore. Driven through a REAL bound AgentSession via the T1 harness.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
import { markerPath, PENDING_LEARN, setMarker } from "./cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

const CAPTURE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  learn_issue: { number: 99, url: "https://gh/o/r/issues/99", existed: false },
  plan_issue: 7,
  commented: true,
  pending_cleared: true,
  dry_run: false,
});

test("tool: learn clears pending-learn and terminates", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN); // land left it set
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", {});
    assert.equal(result.terminate, true);
    const details = result.details as { ok: boolean; was_pending: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.was_pending, true);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn cleared");
  } finally {
    h.dispose();
  }
});

test("tool: learn is idempotent when nothing is pending", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", {});
    const details = result.details as { ok: boolean; was_pending: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.was_pending, false, "nothing was pending");
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)));
  } finally {
    h.dispose();
  }
});

test("/learn command: clears the marker", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("learn");
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "command cleared pending-learn");
  } finally {
    h.dispose();
  }
});

test("tool: learn with a summary delegates capture, surfaces the issue, and clears", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: CAPTURE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "## Learnings\n\nWe deviated on X." });
    assert.equal(result.terminate, true);
    const details = result.details as {
      ok: boolean;
      captured?: boolean;
      learn_issue?: { number?: number };
    };
    assert.equal(details.ok, true);
    assert.equal(details.captured, true);
    assert.equal(details.learn_issue?.number, 99);
    assert.match(result.content[0]?.text ?? "", /#99/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn cleared after capture");
  } finally {
    h.dispose();
  }
});

test("tool: learn with a summary but a failing worker fails soft (no terminate, marker kept)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "something" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true);
    // A failed capture leaves the marker so the cycle is not silently closed.
    assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "marker kept on capture failure");
  } finally {
    h.dispose();
  }
});
