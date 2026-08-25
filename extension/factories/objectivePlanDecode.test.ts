// Split from objectivePlan.test.ts: the reconcile_objective tool + /objective-reconcile
// path, the tool-boundary decode, and the warm node-link carrier. A sibling file for
// cross-file parallelism. (The nodeClaimsEqual / readNodeClaim pure units live with their
// substrate home in workflowState.test.ts.)

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "../substrate/cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  decodeObjectiveNodeParams,
  decodeReconcileParams,
  isNonTrivialAudit,
  MIN_AUDIT_LENGTH,
  reconcileGuidance,
  resolveReconcileObjective,
} from "./objectivePlan.ts";

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

// --- reconcile_objective tool + /objective-reconcile -----------------------------

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

test("tool: reconcile_objective — a success:false envelope at non-zero exit surfaces the structured error", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const envelope = JSON.stringify({
    success: false,
    error_type: "github_error",
    message: "could not update the objective body",
  });
  const bin = fakePerk(cwd, { stdout: envelope, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("reconcile_objective", { objective: 5, prose: "x" });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "github_error");
    assert.equal(details.error, "could not update the objective body");
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

// --- tool-boundary decode (strict-fail on mistyped params) -----------------------

test("tool: objective_node with a mistyped objective → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", { objective: true, node: "1.2", pr: "#9" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("tool: objective_node with an unknown status → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "bogus",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("tool: reconcile_objective with a mistyped prose → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: RECONCILE_OK, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("reconcile_objective", { objective: 5, prose: 5 });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("decodeObjectiveNodeParams: tri-state strict-fail shapes", () => {
  // objective ids are opaque strings (§8.21); bare numbers coerce via String().
  assert.deepEqual(decodeObjectiveNodeParams({ objective: 7, node: "1.2", pr: "#9" }), {
    objective: "7",
    node: "1.2",
    status: undefined,
    pr: "#9",
    description: undefined,
    audit: undefined,
  });
  assert.equal(decodeObjectiveNodeParams(undefined), null);
  assert.equal(decodeObjectiveNodeParams("x"), null);
  assert.deepEqual(
    decodeObjectiveNodeParams({ objective: "ENG-7", node: "1.2", pr: "#9" })?.objective,
    "ENG-7",
  );
  assert.equal(decodeObjectiveNodeParams({ objective: true, node: "1.2" }), null);
  assert.equal(decodeObjectiveNodeParams({ objective: 7, node: "" }), null);
  assert.equal(decodeObjectiveNodeParams({ objective: 7, node: "1.2", status: "bogus" }), null);
  assert.equal(decodeObjectiveNodeParams({ objective: 7, node: "1.2", status: 5 }), null);
  assert.equal(decodeObjectiveNodeParams({ objective: 7, node: "1.2", pr: 9 }), null);
  assert.equal(decodeObjectiveNodeParams({ objective: 7, node: "1.2", audit: 1 }), null);
  assert.equal(
    decodeObjectiveNodeParams({ objective: 7, node: "1.2", status: "done", audit: "a" })?.status,
    "done",
  );
});

test("decodeReconcileParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeReconcileParams({ objective: 5, prose: "p" }), {
    objective: "5",
    prose: "p",
  });
  assert.deepEqual(decodeReconcileParams({ objective: "ENG-5", prose: "p" }), {
    objective: "ENG-5",
    prose: "p",
  });
  assert.equal(decodeReconcileParams(undefined), null);
  assert.equal(decodeReconcileParams({ objective: true, prose: "p" }), null);
  assert.equal(decodeReconcileParams({ objective: 5, prose: 5 }), null);
  assert.equal(decodeReconcileParams({ objective: 5 }), null);
});

// --- the warm node-link carrier (objective_node_claim) --------------------

const NODE_FAIL_JSON = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "boom",
});

test("tool: a successful planning transition writes objective_node_claim", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "planning",
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.deepEqual(h.workflowState().objective_node_claim, { objective: "7", node: "1.2" });
  } finally {
    h.dispose();
  }
});

test("tool: a non-planning transition for the claimed node clears the claim", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", status: "planning" });
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", status: "blocked" });
    assert.equal(h.workflowState().objective_node_claim, null, "the claim was cleared");
  } finally {
    h.dispose();
  }
});

test("tool: a non-planning transition for a DIFFERENT node preserves the claim", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", status: "planning" });
    await h.invokeTool("objective_node", { objective: 7, node: "9.9", status: "blocked" });
    assert.deepEqual(
      h.workflowState().objective_node_claim,
      { objective: "7", node: "1.2" },
      "an unrelated claim is never clobbered",
    );
  } finally {
    h.dispose();
  }
});

test("tool: a failed cold door writes no claim", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: NODE_FAIL_JSON, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", {
      objective: 7,
      node: "1.2",
      status: "planning",
    });
    assert.equal((result.details as { ok: boolean }).ok, false);
    assert.equal(h.workflowState().objective_node_claim ?? null, null, "no claim was written");
  } finally {
    h.dispose();
  }
});

test("tool: a pr-only backlink leaves the claim untouched", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", status: "planning" });
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", pr: "#9" });
    assert.deepEqual(
      h.workflowState().objective_node_claim,
      { objective: "7", node: "1.2" },
      "pr-only calls never touch the claim",
    );
  } finally {
    h.dispose();
  }
});

test("tool: pr-only with no prior claim writes none", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_node", { objective: 7, node: "1.2", pr: "#9" });
    assert.equal(h.workflowState().objective_node_claim ?? null, null);
  } finally {
    h.dispose();
  }
});


