// P1.T3 — live warm-door tests (turn-3 §10). Drive a REAL bound AgentSession via the T1 harness
// and prove the cache.plan-ref delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in
// for the GitHub write, so no LLM / network / gh / Python is invoked. The pure extractPlanMarkdown
// twin is unit-tested separately below.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import { fakePerk, loadPerkSession, plantSession, scaffoldRepo } from "../testing/harness.ts";

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

test("tool: plan_save carries plan_ref.base into active_plan_ref (#633 parity)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const withBase = JSON.stringify({
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
      base: "develop",
    },
    cached: true,
    dry_run: false,
  });
  const bin = fakePerk(cwd, { stdout: withBase });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal(
      (h.workflowState().active_plan_ref as { base?: string | null } | null)?.base,
      "develop",
    );
  } finally {
    h.dispose();
  }
});

test("tool: plan_save tolerates a legacy plan_ref with no base (still links, base absent)", async () => {
  // #633 lenient decode: a pre-#633 cold-door payload whose plan_ref lacks `base` must still
  // decode + link (never bad_output); active_plan_ref simply carries no base.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: PLAN_JSON }); // PLAN_JSON's plan_ref has no `base`
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const ref = h.workflowState().active_plan_ref as { pr_id?: string; base?: unknown } | null;
    assert.equal(ref?.pr_id, "42", "linked despite no base");
    assert.equal(ref?.base, undefined, "absent base omitted, not a failure");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save drops a mistyped plan_ref.base (lenient parity, still links)", async () => {
  // #633 lenient decode: a non-string/non-null `base` is omitted (never a decode failure).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const mistyped = JSON.stringify({
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
      base: 7,
    },
    cached: true,
    dry_run: false,
  });
  const bin = fakePerk(cwd, { stdout: mistyped });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("plan_save", { plan: PLAN_MD });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const ref = h.workflowState().active_plan_ref as { pr_id?: string; base?: unknown } | null;
    assert.equal(ref?.pr_id, "42");
    assert.equal(ref?.base, undefined, "mistyped base dropped");
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
