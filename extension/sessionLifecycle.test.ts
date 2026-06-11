// P1.T1 — live session-lifecycle tests (turn-1 §7). These drive a REAL bound AgentSession through
// the harness and prove the Phase-0 T3 perk:workflow-state wiring end-to-end, OFFLINE (no LLM, no
// network). Each case has a pure-function twin in workflowState.test.ts; here we prove the wiring.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { runScratchDir, workflowDir } from "./cache.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

test("claim: fresh session with PERK_RUN_ID + handoff claims the run", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const s = h.sentinel();
    assert.equal(s?.source, "env");
    assert.equal(s?.run_id, "01RID");
    assert.equal(h.workflowState().run_id, "01RID");
    // node 3.1: the `v<version> loaded` toast is retired — identity is a standing footer segment
    assert.ok(!h.notifies.some((m) => m.includes("loaded")));
    assert.ok(h.footerFactory() !== null, "the perk footer factory was installed");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1);
    assert.ok((footer[0] as string).includes("perk v"), footer[0]);
    // D5 rescinded: perk never touches the working indicator
    assert.equal(h.workingIndicators.length, 0);
    // handoff was consumed (Q3 establish-before-consume)
    const handoff = JSON.parse(
      readFileSync(join(workflowDir(cwd), "handoff", "01RID.json"), "utf8"),
    );
    assert.equal(handoff.consumed, true);
  } finally {
    h.dispose();
  }
});

test("keep: reload() re-emits session_start and preserves the run", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.equal(h.sentinel()?.source, "env");
    // reload with PERK_RUN_ID unset: the run must come from session state, not the env
    await h.reload({ PERK_RUN_ID: undefined });
    const s = h.sentinel();
    assert.equal(s?.source, "session");
    assert.equal(s?.run_id, "01RID");
    assert.equal(s?.predecessor, null);
  } finally {
    h.dispose();
  }
});

test("fork: an inherited pi_session_id derives a child run_id", async () => {
  const cwd = scaffoldRepo();
  // Planted state carries a pi_session_id that won't match this file's basename -> fork.
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const s = h.sentinel();
    assert.equal(s?.source, "fork");
    assert.equal(s?.run_id, "01RID.1");
    assert.equal(s?.predecessor, "01RID");
    // the child's scratch dir was isolated
    assert.ok(existsSync(runScratchDir(cwd, "01RID.1")));
  } finally {
    h.dispose();
  }
});

test("session_tree: navigateTree fires the tree-rebuild handler", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const ids = h.entryIds();
    assert.ok(ids.length > 0, "expected at least one branch entry to navigate to");
    await h.navigateTo(ids[0] as string);
    assert.equal(h.sentinel()?.source, "tree");
  } finally {
    h.dispose();
  }
});

test("command: an extension command runs to completion offline", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  try {
    assert.ok(h.registeredCommands().includes("perk-selfcheck"));
    await h.invokeCommand("perk-selfcheck"); // must not throw, no model turn
  } finally {
    h.dispose();
  }
});

test("headless fail-safe: a missing handoff is reported, not thrown", async () => {
  const cwd = scaffoldRepo(); // no handoff planted
  // headless => ctx.hasUI === false; PERK_RUN_ID set but handoff absent -> linkage error path
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01MISS" }, headful: false });
  try {
    // loaded unclaimed, no crash, and no UI notifications in headless mode
    assert.equal(h.workflowState().run_id, undefined);
    assert.equal(h.notifies.length, 0);
    assert.equal(h.sentinel()?.source, "env"); // decision was a claim attempt that failed to verify
    // node 3.1: headless installs no footer and never touches the working indicator
    assert.equal(h.footerFactory(), null);
    assert.equal(h.workingIndicators.length, 0);
  } finally {
    h.dispose();
  }
});
