// P1.T3 — live warm-door tests (turn-3 §10). Drive a REAL bound AgentSession via the T1 harness
// and prove the cache.plan-ref delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in
// for the GitHub write, so no LLM / network / gh / Python is invoked. The pure extractPlanMarkdown
// twin is unit-tested separately below.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { sessionDataDir } from "./cache.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import {
  approvalSave,
  decodePlanSaveParams,
  extractPlanMarkdown,
  isPlanModeActive,
  resolvePlanSource,
} from "./planSave.ts";
import type { ReportTarget } from "./report.ts";
import { type SessionDataCtx, writeSessionArtifact } from "./sessionData.ts";
import { fakePerk, loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import type { ToolGating } from "./toolGating.ts";
import type { BranchEntry, EntrySink } from "./workflowState.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

const PLAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { id: "42", url: "https://gh/o/r/issues/42", existed: false },
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
  issue: { id: "42", url: "https://gh/o/r/issues/42", existed: true },
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
  issue: { id: "122", url: "https://gh/o/r/issues/122", existed: false },
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
  issue: { id: "122", url: "https://gh/o/r/issues/122", existed: false },
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

test("tool: plan_save forwards an explicit title into --title (#129 dropped-title fix)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, title: "Custom Title" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(
      argv.includes("--title") && argv[argv.indexOf("--title") + 1] === "Custom Title",
      `--title Custom Title was delegated (got ${JSON.stringify(argv)})`,
    );
  } finally {
    h.dispose();
  }
});

test("tool: plan_save with no title and the LLM gate on omits --title (#129)", async () => {
  // The harness sets PERK_NO_LLM=1 by default, so no model call fires and the cold door's
  // derive_title stays in control — proven by the absence of --title.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.ok(!argv.includes("--title"), "no explicit title + gate on omits --title");
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

test("tool: a success:false envelope at non-zero exit surfaces the structured error", async () => {
  // The envelope-aware regression (Node 2.2): the Python plane prints a structured failure
  // envelope to stdout before exiting non-zero — the door must surface it, not the stderr tail.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const envelope = JSON.stringify({
    success: false,
    error_type: "github_error",
    message: "gh exploded",
  });
  const bin = fakePerk(cwd, { stdout: envelope, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "github_error");
    assert.equal(details.error, "gh exploded");
    assert.equal(h.workflowState().active_plan_ref ?? null, null, "no linkage on failure");
  } finally {
    h.dispose();
  }
});

test("tool: success:true with a malformed plan_ref fails as bad_output, no linkage", async () => {
  // A half-formed ref appended to workflow-state would poison planRefsEqual + every downstream
  // consumer — the decode is fully strict on plan_ref.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    issue: { id: "42", url: "https://gh/o/r/issues/42", existed: false },
    plan_ref: {
      provider: "github",
      pr_id: 42, // number, not string → reject
      url: "https://gh/o/r/issues/42",
      labels: ["perk:plan"],
      objective_id: null,
    },
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
    assert.equal(h.workflowState().active_plan_ref ?? null, null, "no linkage appended");
  } finally {
    h.dispose();
  }
});

test("tool: a legacy pre-#387 issue shape (number, no id) still saves — derived from plan_ref", async () => {
  // The #390 incident regression (the #391 sibling): a version-skewed CLI emitting a different
  // `issue` sub-object shape must NOT fail a save that already succeeded — the rendered issue
  // id/url are derived from the strict plan_ref (byte-identical by construction in the cold door).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const legacy = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    issue: { number: 390, url: "https://gh/o/r/issues/390", existed: false }, // pre-#387 shape
    plan_ref: {
      provider: "github",
      pr_id: "390",
      url: "https://gh/o/r/issues/390",
      labels: ["perk:plan"],
      objective_id: null,
    },
  });
  const bin = fakePerk(cwd, { stdout: legacy });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as {
      ok: boolean;
      issue?: { id?: string; url?: string };
      existed?: boolean | null;
    };
    assert.equal(details.ok, true, "the save succeeded despite the skewed issue shape");
    assert.deepEqual(details.issue, { id: "390", url: "https://gh/o/r/issues/390" });
    assert.equal(details.existed, false, "existed is advisory — still decoded from the issue");
    assert.equal(result.terminate, true);
    assert.match(result.content[0]?.text ?? "", /Saved plan #390/);
    assert.equal(
      (h.workflowState().active_plan_ref as { pr_id?: string } | null)?.pr_id,
      "390",
      "the linkage was appended",
    );
  } finally {
    h.dispose();
  }
});

test("tool: an absent issue sub-object still saves — derived from plan_ref", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const noIssue = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    plan_ref: {
      provider: "github",
      pr_id: "77",
      url: "https://gh/o/r/issues/77",
      labels: ["perk:plan"],
      objective_id: null,
    },
  });
  const bin = fakePerk(cwd, { stdout: noIssue });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as {
      ok: boolean;
      issue?: { id?: string; url?: string };
      existed?: boolean | null;
    };
    assert.equal(details.ok, true);
    assert.deepEqual(details.issue, { id: "77", url: "https://gh/o/r/issues/77" });
    assert.equal(details.existed, null);
  } finally {
    h.dispose();
  }
});

test("tool: a malformed objective_node is dropped (advisory), save still succeeds", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const advisory = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    issue: { id: "42", url: "https://gh/o/r/issues/42", existed: false },
    plan_ref: {
      provider: "github",
      pr_id: "42",
      url: "https://gh/o/r/issues/42",
      labels: ["perk:plan"],
      objective_id: null,
    },
    objective_node: { linked: "yes", node: "1.2", status: null, error: null }, // malformed
  });
  const bin = fakePerk(cwd, { stdout: advisory });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; objective_node?: unknown };
    assert.equal(details.ok, true, "the save itself succeeded");
    assert.equal(details.objective_node, null, "the malformed sub-object was dropped");
    assert.doesNotMatch(result.content[0]?.text ?? "", /objective node/, "no link suffix");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save stages the plan markdown in run scratch (mkdtemp retirement)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    const planFile = argv[argv.indexOf("--plan-file") + 1] ?? "";
    assert.ok(
      planFile.includes(join(".pi", "workflow", "scratch", "runs", "01RID")),
      `plan staged under run scratch (got ${planFile})`,
    );
    // savePlan trims the plan before staging, hence the .trim() on the expectation.
    assert.equal(readFileSync(planFile, "utf8"), PLAN_MD.trim(), "the staged file holds the plan");
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

// --- Node 2.2: resolvePlanSource (pure, offline fakes — the planDraft.test.ts recipe) ------

/** A `SessionDataCtx & ReportTarget` over a live branch array (headless, notify is a no-op). */
function reportableCtx(cwd: string, branch: unknown[]): SessionDataCtx & ReportTarget {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: false,
    ui: { notify() {} },
  };
}

function fakeSink(branch: unknown[]): EntrySink {
  return {
    appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
  };
}

function runIdEntry(runId: string): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: runId } };
}

function assistantEntry(text: string): unknown {
  return { type: "message", message: { role: "assistant", content: text } };
}

/** A temp-cwd ctx with the draft artifact written; calls `fn`, then cleans up. */
function withSourceCtx(
  opts: { artifact?: string; assistant?: string },
  fn: (ctx: SessionDataCtx & ReportTarget) => void,
): void {
  const cwd = mkdtempSync(join(tmpdir(), "plan-save-source-test-"));
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    if (opts.assistant !== undefined) branch.push(assistantEntry(opts.assistant));
    const ctx = reportableCtx(cwd, branch);
    if (opts.artifact !== undefined) {
      const written = writeSessionArtifact(
        fakeSink(branch),
        ctx,
        PLAN_DRAFT_ARTIFACT,
        opts.artifact,
      );
      assert.ok(written, "the draft artifact landed");
    }
    fn(ctx);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
}

test("resolvePlanSource: the artifact wins over param + transcript", () => {
  withSourceCtx({ artifact: "# Draft\nplan\n", assistant: "# Scraped" }, (ctx) => {
    const src = resolvePlanSource(ctx, "# Draft\nplan\n");
    assert.deepEqual(src, { plan: "# Draft\nplan\n", source: "plan-draft", paramMismatch: false });
  });
});

test("resolvePlanSource: paramMismatch only for a differing non-blank param under an artifact win", () => {
  withSourceCtx({ artifact: "# Draft\n" }, (ctx) => {
    assert.equal(resolvePlanSource(ctx, "# Other")?.paramMismatch, true);
    // Trim-equal param is NOT a mismatch.
    assert.equal(resolvePlanSource(ctx, "# Draft")?.paramMismatch, false);
    // Blank / absent params are not mismatches either.
    assert.equal(resolvePlanSource(ctx, "   ")?.paramMismatch, false);
    assert.equal(resolvePlanSource(ctx)?.paramMismatch, false);
  });
});

test("resolvePlanSource: param when no artifact; blank param falls to transcript", () => {
  withSourceCtx({ assistant: "# Scraped" }, (ctx) => {
    assert.deepEqual(resolvePlanSource(ctx, "# Param"), {
      plan: "# Param",
      source: "param",
      paramMismatch: false,
    });
    assert.deepEqual(resolvePlanSource(ctx, "  \n"), {
      plan: "# Scraped",
      source: "transcript",
      paramMismatch: false,
    });
  });
});

test("resolvePlanSource: transcript when neither; null when everything misses", () => {
  withSourceCtx({ assistant: "# Scraped" }, (ctx) => {
    assert.deepEqual(resolvePlanSource(ctx), {
      plan: "# Scraped",
      source: "transcript",
      paramMismatch: false,
    });
  });
  withSourceCtx({}, (ctx) => {
    assert.equal(resolvePlanSource(ctx), null);
  });
});

// --- Node 2.2: file-first save surfaces (harness) ------------------------------------------

const DRAFT_MD = "# Draft plan\n\n## Summary\nThe validated working draft.\n";

function stagedPlan(argvFile: string): string {
  const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
  const planFile = argv[argv.indexOf("--plan-file") + 1] ?? "";
  return readFileSync(planFile, "utf8");
}

test("tool: the artifact wins over a differing param — staged bytes, suffix, plan_source", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    const result = await h.invokeTool("plan_save", { plan: "# A different param plan" });
    assert.equal(stagedPlan(argvFile), DRAFT_MD.trim(), "the artifact bytes were staged");
    const text = result.content[0]?.text ?? "";
    assert.match(text, /plan source: plan-draft artifact/);
    assert.match(text, /⚠ differing plan param ignored/);
    assert.equal((result.details as { plan_source?: string }).plan_source, "plan-draft");
  } finally {
    h.dispose();
  }
});

test("tool: no artifact + param — byte-stable legacy message, plan_source param", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal(stagedPlan(argvFile), PLAN_MD.trim(), "the param bytes were staged");
    const text = result.content[0]?.text ?? "";
    assert.doesNotMatch(text, /plan source:/, "param-path success messages stay byte-stable");
    assert.equal((result.details as { plan_source?: string }).plan_source, "param");
  } finally {
    h.dispose();
  }
});

test("tool: no artifact + no param falls back to the transcript scrape", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], {
    assistantText: "# Scraped plan\n\nFrom the transcript.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    const result = await h.invokeTool("plan_save", {});
    assert.equal(stagedPlan(argvFile), "# Scraped plan\n\nFrom the transcript.");
    assert.match(result.content[0]?.text ?? "", /plan source: transcript/);
    assert.equal((result.details as { plan_source?: string }).plan_source, "transcript");
  } finally {
    h.dispose();
  }
});

test("tool: nothing anywhere → invalid_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "invalid_input");
    assert.match(result.content[0]?.text ?? "", /no plan to save/);
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("command: /plan-save prefers the artifact over a trailing assistant message", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], {
    assistantText: "# Scraped plan\n\nNot the draft.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    await h.invokeCommand("plan-save");
    assert.equal(stagedPlan(argvFile), DRAFT_MD.trim(), "the artifact bytes were staged");
    assert.ok(
      h.notifies.some((n) => /plan source: plan-draft artifact/.test(n)),
      "the artifact source was announced",
    );
  } finally {
    h.dispose();
  }
});

test("command: a tampered artifact fails open to the transcript (digest mismatch)", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }], {
    assistantText: "# Scraped plan\n\nThe fallback.\n",
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    // Tamper with the on-disk bytes so the pointer's digest no longer matches (rewind/tamper).
    writeFileSync(join(sessionDataDir(cwd, "01RID"), PLAN_DRAFT_ARTIFACT), "# tampered\n", "utf8");
    await h.invokeCommand("plan-save");
    assert.equal(stagedPlan(argvFile), "# Scraped plan\n\nThe fallback.");
    assert.ok(
      h.notifies.some((n) => /plan source: transcript/.test(n)),
      "fell open to the transcript source",
    );
  } finally {
    h.dispose();
  }
});

// --- Node 3.2: tool-boundary decode (strict-fail on mistyped params) -----------------------

test("tool: plan_save with a mistyped consumed_learn → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: "# Plan", consumed_learn: "x" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.match(result.content[0]?.text ?? "", /^plan_save failed: /);
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("decodePlanSaveParams: tri-state strict-fail shapes", () => {
  // consumed_learn: string ids are canonical (§8.21); bare numbers coerce via String().
  assert.deepEqual(decodePlanSaveParams({ plan: "# P", consumed_learn: [1, 2] }), {
    plan: "# P",
    title: undefined,
    objective_id: undefined,
    node_id: undefined,
    consumed_learn: ["1", "2"],
  });
  // plan absent decodes to undefined (Node 2.2: resolvePlanSource owns the fallback chain).
  assert.equal(decodePlanSaveParams({})?.plan, undefined);
  assert.equal(decodePlanSaveParams(undefined), null);
  assert.equal(decodePlanSaveParams({ plan: 5 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", title: 5 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", objective_id: 7 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", node_id: 1.2 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", consumed_learn: "x" }), null);
  // mixed string/number ids are fine now (coerced); a non-id element still strict-fails.
  assert.deepEqual(
    decodePlanSaveParams({ plan: "p", consumed_learn: [1, "ENG-2"] })?.consumed_learn,
    ["1", "ENG-2"],
  );
  assert.equal(decodePlanSaveParams({ plan: "p", consumed_learn: [true] }), null);
});

// --- Node 2.3 (#339): warm node-link recovery (the objective_node_claim carrier) -----------

const CLAIM = { objective: "115", node: "1.2" };

test("tool: both link params absent + a claim present → recovered into the argv", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_NODE_OK_JSON, argvFile });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", objective_node_claim: CLAIM },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.equal(argv[argv.indexOf("--objective-id") + 1], "115", "objective recovered");
    assert.equal(argv[argv.indexOf("--node-id") + 1], "1.2", "node recovered");
  } finally {
    h.dispose();
  }
});

test("tool: explicit link params win outright over a claim", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", objective_node_claim: CLAIM },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, objective_id: "9", node_id: "2.2" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.equal(argv[argv.indexOf("--objective-id") + 1], "9");
    assert.equal(argv[argv.indexOf("--node-id") + 1], "2.2");
  } finally {
    h.dispose();
  }
});

test("tool: a half-specified explicit link is never mixed with the claim", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", objective_node_claim: CLAIM },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD, objective_id: "9" });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.equal(argv[argv.indexOf("--objective-id") + 1], "9", "the explicit half is kept");
    assert.ok(!argv.includes("--node-id"), "the claim's node is NOT mixed in");
  } finally {
    h.dispose();
  }
});

test("tool: a successful node-linked save clears the matching claim", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: PLAN_NODE_OK_JSON });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", objective_node_claim: CLAIM },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal(h.workflowState().objective_node_claim, null, "the claim was cleared");
  } finally {
    h.dispose();
  }
});

test("tool: a failed save keeps the claim", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: "not json", code: 1 });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", objective_node_claim: CLAIM },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.deepEqual(h.workflowState().objective_node_claim, CLAIM, "the claim survives");
  } finally {
    h.dispose();
  }
});

// --- Node 2.3 (#339): the approvalSave orchestration seam (pure fakes, offline) -------------

const FAIL_ENVELOPE = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
});

/** A ToolGating fake recording exits; `active` is the isActive snapshot. */
function fakeGating(active: boolean): ToolGating & { exits: number } {
  const g = {
    exits: 0,
    syncFromState() {},
    enter() {},
    exit() {
      g.exits += 1;
    },
    isActive: () => active,
  };
  return g;
}

/** An ExtensionAPI fake: appendEntry lands on the branch; exec returns the canned payload. */
function fakeApprovalPi(
  branch: unknown[],
  opts: { stdout: string; code?: number; argvs?: string[][] },
): ExtensionAPI {
  return {
    appendEntry(customType: string, data?: unknown) {
      branch.push({ type: "custom", customType, data });
    },
    async exec(_cmd: string, args: string[]) {
      opts.argvs?.push(args);
      return { stdout: opts.stdout, stderr: "", code: opts.code ?? 0, killed: false };
    },
  } as unknown as ExtensionAPI;
}

/** Run `fn` with PERK_NO_LLM pinned on (deterministic: no title generation path). */
async function withNoLlm(fn: () => Promise<void>): Promise<void> {
  const prev = process.env.PERK_NO_LLM;
  process.env.PERK_NO_LLM = "1";
  try {
    await fn();
  } finally {
    if (prev === undefined) delete process.env.PERK_NO_LLM;
    else process.env.PERK_NO_LLM = prev;
  }
}

test("approvalSave: no artifact/param/transcript → no-plan, no exec, gate untouched", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      const argvs: string[][] = [];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_JSON, argvs });
      const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
      const gating = fakeGating(true);
      const outcome = await approvalSave(pi, ctx, gating);
      assert.deepEqual(outcome, { status: "no-plan" });
      assert.equal(argvs.length, 0, "no cold-door exec");
      assert.equal(gating.exits, 0, "the gate was untouched");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

test("approvalSave: reviewedPlan fallback saves while read-only → gate exited", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      const argvs: string[][] = [];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_JSON, argvs });
      const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
      const gating = fakeGating(true);
      const outcome = await approvalSave(pi, ctx, gating, { reviewedPlan: "# Reviewed plan" });
      assert.equal(outcome.status, "saved");
      assert.equal(outcome.status === "saved" && outcome.gateExited, true, "gateExited reported");
      assert.equal(gating.exits, 1, "the gate was exited once");
      const argv = argvs[0] ?? [];
      const planFile = argv[argv.indexOf("--plan-file") + 1] ?? "";
      assert.equal(readFileSync(planFile, "utf8"), "# Reviewed plan", "the reviewed plan staged");
      const result = outcome.status === "saved" ? outcome.result : null;
      assert.equal(result?.terminate, true, "the SaveResult keeps terminate for tool callers");
      // The param-path success message stays byte-stable (no source suffix); details carry it.
      const details = result?.details as { plan_source?: string } | undefined;
      assert.equal(details?.plan_source, "param");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

test("approvalSave: a successful save while already read-write never exits the gate", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_JSON });
      const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
      const gating = fakeGating(false);
      const outcome = await approvalSave(pi, ctx, gating, { reviewedPlan: "# Reviewed plan" });
      assert.equal(outcome.status, "saved");
      assert.equal(outcome.status === "saved" && outcome.gateExited, false);
      assert.equal(gating.exits, 0, "no gating.exit call");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

test("approvalSave: a failed save leaves the gate on", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      const pi = fakeApprovalPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
      const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
      const gating = fakeGating(true);
      const outcome = await approvalSave(pi, ctx, gating, { reviewedPlan: "# Reviewed plan" });
      assert.equal(outcome.status, "save-failed");
      assert.equal(outcome.status === "save-failed" && outcome.gateExited, false);
      assert.equal(gating.exits, 0, "the gate stays on");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

test("approvalSave: the artifact wins over a differing reviewedPlan (paramMismatch)", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      const argvs: string[][] = [];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_JSON, argvs });
      const ctx = reportableCtx(cwd, branch);
      assert.ok(
        writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
        "the draft artifact landed",
      );
      const gating = fakeGating(false);
      const outcome = await approvalSave(pi, ctx as unknown as ExtensionContext, gating, {
        reviewedPlan: "# A different reviewed plan",
      });
      assert.equal(outcome.status, "saved");
      const text = outcome.status === "saved" ? (outcome.result.content[0]?.text ?? "") : "";
      assert.match(text, /plan source: plan-draft artifact/);
      assert.match(text, /⚠ differing plan param ignored/);
      const argv = argvs[0] ?? [];
      const planFile = argv[argv.indexOf("--plan-file") + 1] ?? "";
      assert.equal(readFileSync(planFile, "utf8"), "# The draft", "the artifact bytes staged");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

test("command: /plan-save with no plan leaves a read-only gate untouched", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: "/nonexistent" },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeCommand("plan-save");
    assert.equal(h.workflowState().mode, "read-only", "the gate stays on (nothing saved)");
    assert.ok(
      h.notifies.some((n) => /no plan to save/i.test(n)),
      "the byte-stable no-plan warning",
    );
  } finally {
    h.dispose();
  }
});
