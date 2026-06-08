// P2.T10 — live warm-door tests for the objective plan factory's `objective_node` tool. Drive a
// REAL bound AgentSession via the T1 harness and prove the delegation + the two arg shapes + the
// structural completion-audit refusal, OFFLINE: a fake `perk` (PERK_BIN) stands in for the GitHub
// mutation (and captures its argv), so no LLM / network / gh / Python is invoked. Pure helpers are
// unit-tested separately below.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "./cache.ts";
import {
  buildObjectiveNodeArgs,
  factoryGuidance,
  isNonTrivialAudit,
  MIN_AUDIT_LENGTH,
  reconcileGuidance,
  resolveReconcileObjective,
} from "./objectivePlan.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("factoryGuidance injects the configured objective-explorer model when set", () => {
  const text = factoryGuidance("42", "1.2", "x/y");
  assert.match(text, /model: "x\/y"/);
  assert.match(text, /\[subagents\] objective-explorer model/);
});

test("factoryGuidance omits the model override when unset", () => {
  assert.doesNotMatch(factoryGuidance("42", "1.2"), /model: "/);
});

const OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  objective: 7,
  node: "1.2",
  comment_updated: true,
});

const AUDIT = "Requirement: retry on 5xx → evidence: PR #99 merged, test_retry passing.";

function readArgv(path: string): string[] {
  return readFileSync(path, "utf8").trimEnd().split("\n");
}

test("tool: objective_node pr-only backlink delegates --pr with NO --status", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      pr: "#9",
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const argv = readArgv(argvFile);
    assert.deepEqual(argv, ["objective", "node", "7", "--node", "1.2", "--pr", "#9", "--json"]);
    assert.ok(!argv.includes("--status"), "pr-only backlink omits --status");
  } finally {
    h.dispose();
  }
});

test("tool: objective_node status change includes --status", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "planning",
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const argv = readArgv(argvFile);
    assert.deepEqual(argv, [
      "objective",
      "node",
      "7",
      "--node",
      "1.2",
      "--status",
      "planning",
      "--json",
    ]);
  } finally {
    h.dispose();
  }
});

test("tool: status=done WITHOUT audit refuses (audit_required, no exec)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "done",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "audit_required");
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("tool: status=done with a too-short audit refuses (no exec)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "done",
      audit: "did it", // < 40 chars trimmed
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "audit_required");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("tool: status=done WITH a sufficient audit execs", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "done",
      audit: AUDIT,
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const argv = readArgv(argvFile);
    assert.deepEqual(argv, [
      "objective",
      "node",
      "7",
      "--node",
      "1.2",
      "--status",
      "done",
      "--json",
    ]);
  } finally {
    h.dispose();
  }
});

test("tool: a non-done status change needs no audit", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "in_progress",
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
  } finally {
    h.dispose();
  }
});

test("tool: neither status nor pr → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", { objective: 7, node: "1.2" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("tool: a failing worker fails loud-but-soft (no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", { objective: 7, node: "1.2", pr: "#9" });
    assert.equal((result.details as { ok: boolean }).ok, false);
  } finally {
    h.dispose();
  }
});

test("/objective-plan registers and is headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(
      h.registeredCommands().includes("objective-plan"),
      "the /objective-plan command is registered",
    );
  } finally {
    h.dispose();
  }
});

// --- pure helpers (offline unit) --------------------------------------------------------

test("buildObjectiveNodeArgs: shapes", () => {
  assert.deepEqual(buildObjectiveNodeArgs({ objective: 7, node: "1.2", pr: "#9" }), [
    "objective",
    "node",
    "7",
    "--node",
    "1.2",
    "--pr",
    "#9",
    "--json",
  ]);
  assert.deepEqual(buildObjectiveNodeArgs({ objective: 7, node: "1.2", status: "planning" }), [
    "objective",
    "node",
    "7",
    "--node",
    "1.2",
    "--status",
    "planning",
    "--json",
  ]);
  assert.deepEqual(
    buildObjectiveNodeArgs({ objective: 7, node: "1.2", status: "in_progress", pr: "#9" }),
    ["objective", "node", "7", "--node", "1.2", "--status", "in_progress", "--pr", "#9", "--json"],
  );
  // neither status nor pr nor description -> structurally invalid.
  assert.equal(buildObjectiveNodeArgs({ objective: 7, node: "1.2" }), null);
});

test("buildObjectiveNodeArgs: description alone is valid (P2.T11)", () => {
  assert.deepEqual(
    buildObjectiveNodeArgs({ objective: 7, node: "1.2", description: "reconciled scope" }),
    ["objective", "node", "7", "--node", "1.2", "--description", "reconciled scope", "--json"],
  );
  // description with status + pr -> all three pushed in order.
  assert.deepEqual(
    buildObjectiveNodeArgs({
      objective: 7,
      node: "1.2",
      status: "done",
      pr: "#9",
      description: "d",
    }),
    [
      "objective",
      "node",
      "7",
      "--node",
      "1.2",
      "--status",
      "done",
      "--pr",
      "#9",
      "--description",
      "d",
      "--json",
    ],
  );
});

// --- P2.T11b: reconcile_objective tool + /objective-reconcile -----------------------------

const RECONCILE_OK = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  objective: 5,
  updated: true,
});

test("tool: reconcile_objective writes scratch + builds --body argv, never throws", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: RECONCILE_OK, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("reconcile_objective", {
      objective: 5,
      prose: "New reconciled prose.",
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    const argv = readArgv(argvFile);
    assert.equal(argv[0], "objective");
    assert.equal(argv[1], "reconcile");
    assert.equal(argv[2], "5");
    assert.ok(argv.includes("--json"));
    const bodyIdx = argv.indexOf("--body");
    assert.ok(bodyIdx > 0, "--body present");
    const bodyPath = argv[bodyIdx + 1] ?? "";
    assert.equal(readFileSync(bodyPath, "utf8"), "New reconciled prose.");
  } finally {
    h.dispose();
  }
});

test("tool: reconcile_objective failing worker fails loud-but-soft (no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("reconcile_objective", { objective: 5, prose: "x" });
    assert.equal((result.details as { ok: boolean }).ok, false);
  } finally {
    h.dispose();
  }
});

test("/objective-reconcile registers", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(h.registeredCommands().includes("objective-reconcile"));
  } finally {
    h.dispose();
  }
});

// resolveReconcileObjective three-tier resolution (pure; minimal ctx, no model turn).
function reconcileCtx(cwd: string): ExtensionContext {
  return {
    cwd,
    sessionManager: { getBranch: () => [] },
  } as unknown as ExtensionContext;
}

test("resolveReconcileObjective: arg wins (first tier)", () => {
  const cwd = scaffoldRepo();
  assert.equal(resolveReconcileObjective("5", reconcileCtx(cwd)), "5");
  assert.equal(resolveReconcileObjective("#5", reconcileCtx(cwd)), "5");
});

test("resolveReconcileObjective: plan_ref.objective_id (third tier)", () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, {
    provider: "github",
    pr_id: "7",
    url: "u/7",
    labels: ["perk:plan"],
    objective_id: "42",
  });
  // no arg, no active objective -> falls through to the plan-ref.
  assert.equal(resolveReconcileObjective("", reconcileCtx(cwd)), "42");
});

test("resolveReconcileObjective: null when nothing resolves", () => {
  const cwd = scaffoldRepo();
  assert.equal(resolveReconcileObjective("", reconcileCtx(cwd)), null);
});

test("resolveReconcileObjective: null when plan-ref has no objective_id", () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, {
    provider: "github",
    pr_id: "7",
    url: "u/7",
    labels: ["perk:plan"],
    objective_id: null,
  });
  assert.equal(resolveReconcileObjective("", reconcileCtx(cwd)), null);
});

test("isNonTrivialAudit: the trim().length >= MIN_AUDIT_LENGTH predicate", () => {
  assert.equal(isNonTrivialAudit(undefined), false);
  assert.equal(isNonTrivialAudit(123), false);
  assert.equal(isNonTrivialAudit("short"), false);
  assert.equal(isNonTrivialAudit(`   ${"x".repeat(MIN_AUDIT_LENGTH - 1)}   `), false);
  assert.equal(isNonTrivialAudit("x".repeat(MIN_AUDIT_LENGTH)), true);
  assert.equal(isNonTrivialAudit(AUDIT), true);
});

test("reconcileGuidance: names the objective and carries the reconcile cues (no skill pointer)", () => {
  const g = reconcileGuidance("5");
  assert.match(g, /#5/);
  assert.match(g, /gh pr diff/);
  assert.match(g, /perk objective show 5/);
  assert.match(g, /reconcile_objective/);
  // The skill pointer rides the bindingSuffix, never the guidance body.
  assert.doesNotMatch(g, /Follow the/);
});
