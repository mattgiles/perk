// P1.T3 — live warm-door tests (turn-3 §10). Drive a REAL bound AgentSession via the T1 harness
// and prove the cache.plan-ref delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in
// for the GitHub write, so no LLM / network / gh / Python is invoked. The pure extractPlanMarkdown
// twin is unit-tested separately below.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { extractPlanMarkdown, isPlanModeActive } from "./planSave.ts";
import { fakePerk, loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import type { BranchEntry } from "./workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

const PLAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { number: 42, url: "https://gh/o/r/issues/42", existed: false },
  plan_ref: {
    provider: "github",
    pr_id: "42",
    url: "https://gh/o/r/issues/42",
    labels: ["perk:plan"],
    objective_id: null,
  },
  cached: true,
  dry_run: false,
});

const PLAN_RESAVE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { number: 42, url: "https://gh/o/r/issues/42", existed: true },
  plan_ref: {
    provider: "github",
    pr_id: "42",
    url: "https://gh/o/r/issues/42",
    labels: ["perk:plan"],
    objective_id: null,
  },
  cached: true,
  updated: true,
  dry_run: false,
});

const PLAN_NODE_FAIL_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { number: 122, url: "https://gh/o/r/issues/122", existed: false },
  plan_ref: {
    provider: "github",
    pr_id: "122",
    url: "https://gh/o/r/issues/122",
    labels: ["perk:plan"],
    objective_id: "115",
  },
  cached: true,
  objective_node: { linked: false, node: "1.2", status: null, error: "boom" },
  dry_run: false,
});

const PLAN_NODE_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { number: 122, url: "https://gh/o/r/issues/122", existed: false },
  plan_ref: {
    provider: "github",
    pr_id: "122",
    url: "https://gh/o/r/issues/122",
    labels: ["perk:plan"],
    objective_id: "115",
  },
  cached: true,
  objective_node: { linked: true, node: "1.2", status: "in_progress", error: null },
  dry_run: false,
});

const PLAN_MD = "# Add retry\n\n## Summary\nAdd retry to the gateway.\n";

test("tool: plan_save re-save surfaces Updated + details.updated", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_RESAVE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; updated?: boolean; existed?: boolean | null };
    assert.equal(details.ok, true);
    assert.equal(details.updated, true);
    assert.equal(details.existed, true);
    assert.match(result.content[0]?.text ?? "", /Updated plan #42/);
  } finally {
    h.dispose();
  }
});

function countLinks(branch: readonly unknown[]): number {
  return branch.filter((entry) => {
    const e = entry as { type?: string; customType?: string; data?: Record<string, unknown> };
    return (
      e.type === "custom" &&
      e.customType === WORKFLOW_STATE_TYPE &&
      e.data?.active_plan_ref !== undefined
    );
  }).length;
}

test("tool: plan_save delegates, links the session, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal(result.terminate, true, "save terminates the turn");
    const details = result.details as {
      ok: boolean;
      plan_ref?: { pr_id?: string };
      cached?: boolean;
    };
    assert.equal(details.ok, true);
    assert.equal(details.plan_ref?.pr_id, "42");
    assert.equal(details.cached, true);
    assert.match(result.content[0]?.text ?? "", /#42/);
    // the live session is linked (the warm append lands on the branch; the sentinel is a
    // session_start/session_tree artifact and is intentionally not rewritten by the tool).
    assert.equal((h.workflowState().active_plan_ref as { pr_id?: string } | null)?.pr_id, "42");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save threads objective_id into the perk plan-save args (P2.T10)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, objective_id: "7" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(
      argv.includes("--objective-id") && argv[argv.indexOf("--objective-id") + 1] === "7",
      `--objective-id 7 was delegated (got ${JSON.stringify(argv)})`,
    );
  } finally {
    h.dispose();
  }
});

test("tool: plan_save threads node_id into --node-id next to --objective-id (P2.T10)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, objective_id: "7", node_id: "1.1" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(
      argv.includes("--node-id") && argv[argv.indexOf("--node-id") + 1] === "1.1",
      `--node-id 1.1 was delegated (got ${JSON.stringify(argv)})`,
    );
    assert.ok(argv.includes("--objective-id"), "--objective-id still delegated alongside");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save without node_id omits --node-id", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, objective_id: "7" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(!argv.includes("--node-id"), "plan without node_id omits --node-id");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save threads consumed_learn into --consumed-learn (hop-2)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, consumed_learn: [45, 50] });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(
      argv.includes("--consumed-learn") && argv[argv.indexOf("--consumed-learn") + 1] === "45,50",
      `--consumed-learn 45,50 was delegated (got ${JSON.stringify(argv)})`,
    );
  } finally {
    h.dispose();
  }
});

test("tool: plan_save without consumed_learn omits --consumed-learn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(!argv.includes("--consumed-learn"), "standalone plan omits --consumed-learn");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save without objective_id omits --objective-id", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(!argv.includes("--objective-id"), "standalone plan omits --objective-id");
  } finally {
    h.dispose();
  }
});

test("tool: a second save with the same ref does not duplicate the linkage", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal(countLinks(h.session.sessionManager.getBranch()), 1, "idempotent: one link entry");
  } finally {
    h.dispose();
  }
});

test("command: /plan-save extracts the proposed plan and saves it", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: PLAN_JSON });
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], {
    assistantText: "# Add retry\n\n## Summary\nRetry it.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeCommand("plan-save");
    assert.equal((h.workflowState().active_plan_ref as { pr_id?: string } | null)?.pr_id, "42");
    assert.ok(
      h.notifies.some((n) => /#42/.test(n)),
      "a confirmation was notified",
    );
  } finally {
    h.dispose();
  }
});

test("command: /plan-save with no proposed plan is loud but non-fatal", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: "/nonexistent" } });
  try {
    await h.invokeCommand("plan-save"); // no assistant message planted -> no plan
    assert.equal(h.workflowState().active_plan_ref ?? null, null, "nothing linked");
    assert.ok(
      h.notifies.some((n) => /no plan to save/i.test(n)),
      "warned about the missing plan",
    );
  } finally {
    h.dispose();
  }
});

test("tool: a missing perk binary fails loud, appends no linkage", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: "/nonexistent/perk-xyz" },
  });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.notEqual(result.terminate, true);
    assert.equal(h.workflowState().active_plan_ref ?? null, null);
  } finally {
    h.dispose();
  }
});

test("tool: a non-zero exit / garbage stdout fails loud, no linkage", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "not json", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal((result.details as { ok: boolean }).ok, false);
    assert.equal(h.workflowState().active_plan_ref ?? null, null);
  } finally {
    h.dispose();
  }
});

test("command: /plan-save saves while read-only, then auto-exits the gate (D1a)", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: PLAN_JSON });
  // Read-only mode active -> the command crosses the boundary: save, then exit to read-write.
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }], {
    assistantText: "# Add retry\n\n## Summary\nRetry it.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().mode, "read-only", "starts read-only");
    await h.invokeCommand("plan-save");
    // Saved (linked) AND auto-exited the read-only gate in one gesture.
    assert.equal(
      (h.workflowState().active_plan_ref as { pr_id?: string } | null)?.pr_id,
      "42",
      "plan saved + linked",
    );
    assert.equal(h.workflowState().mode, "read-write", "auto-exited to read-write on success");
  } finally {
    h.dispose();
  }
});

// --- objective node-link outcome surfacing (#124 silent-partial-failure fix) -----------

test("command: /plan-save surfaces a failed objective-node advance as a warning", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: PLAN_NODE_FAIL_JSON });
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], {
    assistantText: "# Add retry\n\n## Summary\nRetry it.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeCommand("plan-save");
    const warned = h.notifyEvents.find(
      (n) =>
        /objective node 1\.2 NOT advanced/.test(n.message) && /re-run \/plan-save/.test(n.message),
    );
    assert.ok(
      warned,
      `a failed-advance warning was notified (got ${JSON.stringify(h.notifyEvents)})`,
    );
    assert.equal(warned?.severity, "warning", "raised at warning severity");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save content text reflects a failed node link (save still succeeds)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_NODE_FAIL_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.match(result.content[0]?.text ?? "", /NOT advanced/);
    const details = result.details as {
      ok: boolean;
      objective_node?: { linked: boolean } | null;
    };
    assert.equal(details.ok, true, "the save itself succeeded");
    assert.equal(details.objective_node?.linked, false);
    assert.equal(result.terminate, true, "a failed link does not block termination");
  } finally {
    h.dispose();
  }
});

test("command/tool: a successful node link still shows → in_progress", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_NODE_OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.match(result.content[0]?.text ?? "", /linked objective node 1\.2 → in_progress/);
    assert.equal(
      (result.details as { objective_node?: { linked: boolean } }).objective_node?.linked,
      true,
    );
  } finally {
    h.dispose();
  }
});

// --- isPlanModeActive (pure unit) -------------------------------------------------------

test("isPlanModeActive: reads perk's own read-only mode (not the retired plan-mode-state)", () => {
  const mode = (m: string): BranchEntry => ({
    type: "custom",
    customType: "perk:workflow-state",
    data: { mode: m },
  });
  assert.equal(isPlanModeActive([]), false);
  assert.equal(isPlanModeActive([mode("read-only")]), true);
  assert.equal(isPlanModeActive([mode("read-only"), mode("read-write")]), false); // latest wins
  // The retired pi-plan signal is now ignored entirely.
  assert.equal(
    isPlanModeActive([{ type: "custom", customType: "plan-mode-state", data: { enabled: true } }]),
    false,
  );
});

// --- extractPlanMarkdown (pure unit) ----------------------------------------------------

test("extractPlanMarkdown: returns the whole text of the latest assistant message (no marker)", () => {
  const entries = [
    { type: "message", message: { role: "user", content: "do it" } },
    {
      type: "message",
      message: { role: "assistant", content: [{ type: "text", text: "# T\nbody" }] },
    },
  ];
  // No `<proposed_plan>` convention exists (pi-plan emits none) — the command takes the whole text.
  assert.equal(extractPlanMarkdown(entries), "# T\nbody");
});

test("extractPlanMarkdown: the whole latest assistant text; null when absent", () => {
  assert.equal(
    extractPlanMarkdown([
      { type: "message", message: { role: "assistant", content: "# Plain plan" } },
    ]),
    "# Plain plan",
  );
  assert.equal(
    extractPlanMarkdown([{ type: "message", message: { role: "user", content: "hi" } }]),
    null,
  );
  assert.equal(extractPlanMarkdown([]), null);
});
