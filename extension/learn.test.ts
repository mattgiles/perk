// P1.T5b — live warm-door tests for `/learn` (turn-5 §10). TS-only: no delegation, no gh — `/learn`
// clears the pending-learn semaphore. Driven through a REAL bound AgentSession via the T1 harness.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
import { markerPath, PENDING_LEARN, setMarker, writePlanRef } from "./cache.ts";
import { learnGuidance } from "./learn.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

const PLAN_REF = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

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

test("/learn skip: clears the marker only", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd });
  try {
    await h.runCommandHandler("learn", "skip");
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "/learn skip cleared pending-learn");
  } finally {
    h.dispose();
  }
});

test("/learn (bare, headless): stays the safe marker-clear", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd, headful: false });
  try {
    await h.runCommandHandler("learn", "");
    assert.ok(
      !existsSync(markerPath(cwd, PENDING_LEARN)),
      "headless bare /learn cleared pending-learn (can't drive a turn)",
    );
  } finally {
    h.dispose();
  }
});

test("/learn (bare, interactive): injects guidance and keeps the marker", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  writePlanRef(cwd, PLAN_REF);
  const h = await loadPerkSession({ cwd });
  try {
    await h.runCommandHandler("learn", "");
    // The agent clears the marker by calling the `learn` tool — the command must NOT clear it.
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "bare /learn left pending-learn for the capture pass",
    );
    assert.ok(
      h.notifies.some((n) => n.includes("investigate the landed change")),
      "notified the capture workflow",
    );
  } finally {
    h.dispose();
  }
});

test("learnGuidance derives the head branch from the plan-ref (skill pointer is suffix-delivered)", () => {
  const withRef = learnGuidance(PLAN_REF);
  // Node 2.3: the perk-learn skill pointer is no longer hardcoded — it rides the binding suffix.
  assert.doesNotMatch(withRef, /Follow the perk-learn skill/);
  assert.match(withRef, /plan-42/);
  assert.match(withRef, /gh pr list --head plan-42/);
  assert.match(withRef, /`learn` tool/);
  assert.match(withRef, /\/learn skip/);
  // Without a plan-ref it still names the tool (no branch derivation).
  const noRef = learnGuidance(null);
  assert.doesNotMatch(noRef, /Follow the perk-learn skill/);
  assert.match(noRef, /`learn` tool/);
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
