// Live session-lifecycle tests. These drive a REAL bound AgentSession through
// the harness and prove the perk:workflow-state wiring end-to-end, OFFLINE (no LLM, no
// network). Each case has a pure-function twin in workflowState.test.ts; here we prove the wiring.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { runScratchDir, workflowDir } from "./substrate/cache.ts";
import { readSessionPointers } from "./substrate/sessionPointers.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

test("claim: fresh session with PERK_RUN_ID + handoff claims the run", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const s = h.sentinel();
    assert.equal(s?.source, "env");
    assert.equal(s?.run_id, "01RID");
    assert.equal(h.workflowState().run_id, "01RID");
    // The `v<version> loaded` toast is retired — identity is a standing footer segment
    assert.ok(!h.notifies.some((m) => m.includes("loaded")));
    assert.ok(h.footerFactory() !== null, "the perk footer factory was installed");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1);
    assert.ok((footer[0] as string).includes("perk v"), footer[0]);
    // D5 rescinded: perk never touches the working indicator
    assert.equal(h.workingIndicators.length, 0);
    // handoff was consumed (establish-before-consume)
    const handoff = JSON.parse(
      readFileSync(join(workflowDir(cwd), "handoff", "01RID.json"), "utf8"),
    );
    assert.equal(handoff.consumed, true);
  } finally {
    h.dispose();
  }
});

for (const footerId of ["pi-bar-footer", "pi-status-footer", "pi-default"]) {
  test(`footer seam: a foreign [providers] footer = "${footerId}" selection vacates installPerkFooter`, async () => {
    // Install-site (runtime) vacating: under a non-`perk-footer` selection perk does NOT install
    // its own footer (no factory captured), leaving the foreign footer (or pi's stock footer, for
    // `pi-default`) as the sole surface. The default-repo case (factory installed) is proven by
    // the `claim` test above.
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
    mkdirSync(join(cwd, ".perk"), { recursive: true });
    writeFileSync(
      join(cwd, ".perk", "config.toml"),
      `[providers]\nfooter = "${footerId}"\n`,
      "utf8",
    );
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
    try {
      assert.equal(
        h.footerFactory(),
        null,
        "perk installed no footer under a foreign footer selection",
      );
    } finally {
      h.dispose();
    }
  });
}

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

test("implement session_start records the implementation/main session pointer", async () => {
  // A cold-claimed implement run self-keys its current session file into implementation.main.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  const file = plantSession(cwd, []); // file-backed so getSessionFile() yields a real path
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    const record = readSessionPointers(cwd, "01RID");
    assert.ok(record !== null, "a session-pointers record was written");
    assert.equal(record.implementation.main?.pi_session_id, "planted-parent.jsonl");
    assert.ok((record.implementation.main?.session_file ?? "").length > 0);
    assert.equal(record.implementation.main?.parent_pi_session_id, null);
    // Self-keyed: an implement run fills only the implementation slots.
    assert.equal(record.planning.main, null);
  } finally {
    h.dispose();
  }
});

test("a non-implement stage does NOT record an implementation pointer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    // The implementation/main capture is gated on stage === "implement"; a plan run writes none
    // here (planning.main is savePlan's job, not session_start's).
    assert.equal(readSessionPointers(cwd, "01RID"), null);
  } finally {
    h.dispose();
  }
});

test("fork: a forked implement session threads the parent session as fork provenance", async () => {
  const cwd = scaffoldRepo();
  // Planted state: an implement run forked (pi_session_id won't match this file's basename).
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "OTHER-SESSION", mode: "read-write", stage: "implement" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // The child run id is 01RID.1; the capture inherits the parent's launched stage + threads the
    // inherited parent session id as parent_pi_session_id.
    const record = readSessionPointers(cwd, "01RID.1");
    assert.ok(record !== null);
    assert.equal(record.implementation.main?.parent_pi_session_id, "OTHER-SESSION");
  } finally {
    h.dispose();
  }
});

test("mint: a plain warm session mints its own run_id", async () => {
  const cwd = scaffoldRepo(); // no handoff, no PERK_RUN_ID -> decideClaim's `none` arm
  // File-backed session (no planted state) so pi_session_id is recorded with the mint.
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.open(file),
  });
  try {
    const ULID_RE = /^[0-9A-HJKMNP-TV-Z]{26}$/;
    const minted = h.workflowState().run_id;
    assert.ok(minted !== undefined, "a run_id was minted");
    assert.match(minted, ULID_RE);
    assert.equal(h.workflowState().pi_session_id, "planted-parent.jsonl");
    const s = h.sentinel();
    assert.equal(s?.source, "mint");
    assert.equal(s?.run_id, minted);
    assert.equal(s?.predecessor, null);
    // Reload: the recorded pi_session_id matches the session file -> keep arm, no re-mint.
    await h.reload({ PERK_RUN_ID: undefined });
    assert.equal(h.sentinel()?.source, "session");
    assert.equal(h.workflowState().run_id, minted);
  } finally {
    h.dispose();
  }
});

test("version parity: a divergent PERK_CLI_VERSION emits the soft drift warning", async () => {
  // The harness loads the extension from source, so perkVersion() is the real repo
  // package.json version; a fake PERK_CLI_VERSION guarantees a mismatch -> the warning fires.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_CLI_VERSION: "9.9.9-not-real" },
  });
  try {
    assert.ok(
      h.notifies.some((m) => /version parity/.test(m)),
      `expected a version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

test("version parity: no PERK_CLI_VERSION emits no drift warning", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(
      !h.notifies.some((m) => /version parity/.test(m)),
      `expected no version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
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
    // Headless installs no footer and never touches the working indicator
    assert.equal(h.footerFactory(), null);
    assert.equal(h.workingIndicators.length, 0);
  } finally {
    h.dispose();
  }
});
