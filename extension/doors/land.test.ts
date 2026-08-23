// Live warm-door tests for `/land`. Drive a REAL bound AgentSession via the
// T1 harness; the `perk pr land` merge is faked via PERK_BIN, so no LLM / network / gh / Python.
// The warm door's own effect (setting pending-learn for the in-session path) is verified on disk.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { markerPath, PENDING_LEARN } from "../substrate/cache.ts";
import { BORROWED_TOOLS, PERK_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { REPORT_DETAIL_TYPE } from "../surfaces/surfaces.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import { driveReconcileAfterLand, type LandDetails, landPr } from "./land.ts";

const LAND_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, state: "MERGED" },
  branch: "plan-7",
  issue: "7",
  pending_learn: true,
  dry_run: false,
});

test("tool: land delegates, sets pending-learn, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: LAND_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    assert.equal(result.terminate, true, "land terminates the turn");
    const details = result.details as { ok: boolean; pr?: { number?: number } };
    assert.equal(details.ok, true);
    assert.equal(details.pr?.number, 42);
    // the warm door set pending-learn for the in-session path
    assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn is set");
  } finally {
    h.dispose();
  }
});

test("tool: a failing land does not set pending-learn (soft fail)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true);
    assert.ok(
      !existsSync(join(cwd, ".perk", "workflow", "markers", PENDING_LEARN)),
      "no marker on failure",
    );
  } finally {
    h.dispose();
  }
});

const LAND_JSON_WITH_OBJECTIVE = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, state: "MERGED" },
  branch: "plan-7",
  issue: "7",
  pending_learn: true,
  dry_run: false,
  objective: { id: "5", nodes_marked: ["1.2"], skipped_reason: null },
});

const LAND_JSON_WITH_REPORT_DETAIL = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, state: "MERGED" },
  branch: "plan-7",
  issue: "7",
  pending_learn: true,
  dry_run: false,
  objective: { id: "5", nodes_marked: ["1.2"], skipped_reason: null },
  learn: { closed: ["45", "50"], skipped_reason: null },
});

// `landPr` is exercised directly here (not via the harness `invokeTool`) because the tool's
// `execute` now routes through `driveReconcileAfterLand`, which would inject a real model turn for
// an objective fixture the keyless harness can't service. The drive itself is unit-tested below
// with a spy `pi`. This test fixes `landPr`'s merge/marker/report behavior for the objective case.
test("landPr: objective node-done reports auto-reconciliation (no manual nudge)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const piStub = {
    exec: async () => ({
      code: 0,
      killed: false,
      stdout: LAND_JSON_WITH_OBJECTIVE,
      stderr: "",
    }),
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: false,
    isIdle: () => true,
    // A readable (empty) branch: the planning-stage guard fails closed on an unreadable one.
    sessionManager: { getBranch: () => [] },
  } as unknown as ExtensionContext;
  const result = await landPr(piStub, ctx);
  const text = result.content[0]?.text ?? "";
  assert.match(text, /Objective #5 node\(s\) 1\.2 marked done/);
  assert.match(text, /reconciling/i);
  assert.doesNotMatch(text, /\/objective-reconcile #/);
  assert.ok(result.details.ok);
  assert.deepEqual(result.details.objective?.nodes_marked, ["1.2"]);
});

// --- driveReconcileAfterLand: decision + delivery-mode unit tests (spy pi, no real turn) ---

function spyPi(): {
  pi: ExtensionAPI;
  calls: { content: string; options?: { deliverAs?: string } }[];
} {
  const calls: { content: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
      calls.push({ content, options });
    },
  } as unknown as ExtensionAPI;
  return { pi, calls };
}

const OBJECTIVE_DETAILS: LandDetails = {
  ok: true,
  pr: { number: 9, state: "MERGED" },
  pending_learn: true,
  objective: { id: "5", nodes_marked: ["1.2"], skipped_reason: null, closed: false },
};

test("driveReconcileAfterLand: no objective → not driven", () => {
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => true } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, {
    ok: true,
    pr: { number: 9, state: "MERGED" },
    pending_learn: true,
  });
  assert.equal(calls.length, 0);
});

test("driveReconcileAfterLand: failed land → not driven", () => {
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => true } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, { ok: false, error: "boom", error_type: "github_error" });
  assert.equal(calls.length, 0);
});

test("driveReconcileAfterLand: idle (/land command) → immediate turn", () => {
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => true } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, OBJECTIVE_DETAILS);
  assert.equal(calls.length, 1);
  assert.match(calls[0]?.content ?? "", /objective #5/i);
  assert.equal(calls[0]?.options, undefined);
});

test("driveReconcileAfterLand: streaming (land tool) → followUp", () => {
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => false } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, OBJECTIVE_DETAILS);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.options?.deliverAs, "followUp");
});

test("driveReconcileAfterLand: every scoped tool the injected guidance names is stage-active", () => {
  // The reported failure, pinned at its source: the drive lands in the CURRENT worktree session
  // (stage `implement` when `/land` runs there), so every scoped-universe tool the injected
  // reconcile guidance names must survive that stage's filter — or the drive dead-ends.
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => true } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, OBJECTIVE_DETAILS);
  const content = calls[0]?.content ?? "";
  const named = [...new Set([...PERK_TOOLS, ...BORROWED_TOOLS])].filter((name) =>
    new RegExp(`\\b${name}\\b`).test(content),
  );
  assert.ok(named.includes("reconcile_objective"), "sanity: the guidance names the reconcile tool");
  const implementTools = STAGE_TOOLS.implement ?? [];
  for (const name of named) {
    assert.ok(
      implementTools.includes(name),
      `the reconcile drive names \`${name}\` but STAGE_TOOLS.implement scopes it off`,
    );
  }
});

test("driveReconcileAfterLand: still fires when the land closed the objective", () => {
  // The reconcile pass auto-drives after a closing land — the final prose reconciliation against
  // the last merged diff is still wanted (a closed issue's body/comments remain editable).
  const { pi, calls } = spyPi();
  const ctx = { cwd: ".", isIdle: () => true } as unknown as ExtensionContext;
  driveReconcileAfterLand(pi, ctx, {
    ok: true,
    pr: { number: 9, state: "MERGED" },
    pending_learn: true,
    objective: { id: "5", nodes_marked: ["1.3"], skipped_reason: null, closed: true },
  });
  assert.equal(calls.length, 1);
  assert.match(calls[0]?.content ?? "", /objective #5/i);
});

function stubLandCtx(cwd: string, stdout: string): [ExtensionAPI, ExtensionContext] {
  const piStub = {
    exec: async () => ({ code: 0, killed: false, stdout, stderr: "" }),
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: false,
    isIdle: () => true,
    // A readable (empty) branch: the planning-stage guard fails closed on an unreadable one.
    sessionManager: { getBranch: () => [] },
  } as unknown as ExtensionContext;
  return [piStub, ctx];
}

test("landPr: a closing land reports the objective close", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const payload = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    pending_learn: true,
    objective: { id: "5", nodes_marked: ["1.3"], skipped_reason: null, closed: true },
  });
  const result = await landPr(...stubLandCtx(cwd, payload));
  assert.ok(result.details.ok);
  assert.equal(result.details.objective?.closed, true);
  assert.match(result.content[0]?.text ?? "", /Objective #5 complete — closed\./);
});

test("landPr: `closed` decodes leniently — absent/malformed → false, sub-object kept", async () => {
  // Advisory display detail: a missing or non-boolean `closed` must default to false rather than
  // dropping the whole objective sub-object (the existing advisory-tier posture).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  for (const closed of [undefined, "yes"]) {
    const payload = JSON.stringify({
      success: true,
      error_type: null,
      message: null,
      pr: { number: 42, state: "MERGED" },
      pending_learn: true,
      objective: { id: "5", nodes_marked: ["1.2"], skipped_reason: null, closed },
    });
    const result = await landPr(...stubLandCtx(cwd, payload));
    assert.ok(result.details.ok);
    assert.equal(result.details.objective?.closed, false, `closed=${closed} → false`);
    assert.deepEqual(result.details.objective?.nodes_marked, ["1.2"], "sub-object kept");
    assert.doesNotMatch(result.content[0]?.text ?? "", /complete — closed/);
  }
});

test("tool: land with a skipped objective adds no nudge", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const skipped = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: "7",
    pending_learn: true,
    dry_run: false,
    objective: { id: null, nodes_marked: [], skipped_reason: "no_objective_link" },
  });
  const bin = fakePerk(cwd, { stdout: skipped });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.doesNotMatch(text, /objective-reconcile/);
    assert.equal((result.details as { ok: boolean }).ok, true);
  } finally {
    h.dispose();
  }
});

test("tool: land surfaces a non-benign learn-consume skip", async () => {
  // A partial `failed: …` close is a real failure — surface it, do not stay silent.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const partial = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: "7",
    pending_learn: true,
    dry_run: false,
    learn: { closed: ["45"], skipped_reason: "failed: #50" },
  });
  const bin = fakePerk(cwd, { stdout: partial });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Closed 1 learn issue\(s\)/);
    assert.match(text, /learn consume incomplete — failed: #50/);
  } finally {
    h.dispose();
  }
});

test("tool: land stays quiet on a benign learn-consume skip", async () => {
  // `no_consumed_learn` is the ordinary non-factory case — no warning.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const benign = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: "7",
    pending_learn: true,
    dry_run: false,
    learn: { closed: [], skipped_reason: "no_consumed_learn" },
  });
  const bin = fakePerk(cwd, { stdout: benign });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.doesNotMatch(text, /learn consume incomplete/);
  } finally {
    h.dispose();
  }
});

test("tool: a learn-docs land sets no marker and drops the /learn nudge", async () => {
  // The learn-docs exemption: the cold door reports `pending_learn: false` (no marker on its
  // side either) — the warm door mirrors it: no marker, no /learn nudge, releasable worktree.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const docsLand = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: "7",
    pending_learn: false,
    dry_run: false,
    learn: { closed: ["45"], skipped_reason: null },
  });
  const bin = fakePerk(cwd, { stdout: docsLand });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "no marker on the exempt arm");
    assert.doesNotMatch(text, /run \/learn/);
    assert.match(text, /learn-docs plan — no learn pass needed; the worktree is releasable/);
    assert.match(text, /Closed 1 learn issue\(s\) \(#45\)/, "still reports the consumed issues");
    assert.equal((result.details as { pending_learn?: boolean }).pending_learn, false);
  } finally {
    h.dispose();
  }
});

test("landPr: a missing pending_learn decodes to true (skew-safe legacy default)", async () => {
  // Version skew: an older cold CLI omits `pending_learn` — the warm door must degrade to the
  // legacy behavior (marker + /learn nudge), never a silently-unreleased marker with no nudge.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const legacy = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: "7",
    dry_run: false,
  });
  const result = await landPr(...stubLandCtx(cwd, legacy));
  assert.ok(result.details.ok);
  assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "marker set on the legacy default");
  assert.match(result.content[0]?.text ?? "", /run \/learn/);
});

test("tool: success:true with a malformed pr fails as bad_output (unexpected payload)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42 }, // missing `state`
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
    assert.ok(
      !existsSync(join(cwd, ".perk", "workflow", "markers", PENDING_LEARN)),
      "no marker on a bad payload",
    );
  } finally {
    h.dispose();
  }
});

test("landPr: a malformed objective is dropped, land still succeeds", async () => {
  // The merge already succeeded — a malformed advisory `objective` must not fail the door.
  // (The old unchecked cast would instead crash the composer on a non-array nodes_marked.)
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformedObjective = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    pending_learn: true,
    objective: { id: "5", nodes_marked: "1.2", skipped_reason: null }, // non-array
  });
  const piStub = {
    exec: async () => ({ code: 0, killed: false, stdout: malformedObjective, stderr: "" }),
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: false,
    isIdle: () => true,
    // A readable (empty) branch: the planning-stage guard fails closed on an unreadable one.
    sessionManager: { getBranch: () => [] },
  } as unknown as ExtensionContext;
  const result = await landPr(piStub, ctx);
  assert.ok(result.details.ok, "land still succeeds");
  assert.equal(result.details.objective, undefined, "the malformed objective is dropped");
  const text = result.content[0]?.text ?? "";
  assert.match(text, /Landed PR #42/);
  assert.doesNotMatch(text, /Objective/, "no objective line in the text");
  // ...and the drive short-circuits: no reconcile turn for a dropped objective.
  const { pi, calls } = spyPi();
  driveReconcileAfterLand(pi, ctx, result.details);
  assert.equal(calls.length, 0, "driveReconcileAfterLand not driven");
});

test("/land command: multiline success is a headline plus one durable detail entry", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: LAND_JSON_WITH_REPORT_DETAIL });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    mode: "print",
  });
  const injected = spyInjections(h);
  const stderr: string[] = [];
  t.mock.method(console, "error", (message: unknown) => stderr.push(String(message)));
  const complete =
    "Landed PR #42; run /learn to release the worktree.\n" +
    "Objective #5 node(s) 1.2 marked done — reconciling the roadmap against the merged diff.\n" +
    "Closed 2 learn issue(s) (#45, #50) into docs/learned.";
  try {
    await h.invokeCommand("land");
    assert.deepEqual(
      h.notifyEvents.filter((event) => event.message.startsWith("perk: land — Landed PR")),
      [
        {
          message: "perk: land — Landed PR #42; run /learn to release the worktree.",
          severity: "info",
        },
      ],
    );

    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: unknown;
    }[];
    const details = entries.filter((entry) => entry.customType === REPORT_DETAIL_TYPE);
    assert.deepEqual(
      details.map((entry) => entry.data),
      [{ text: `perk: land — ${complete}`, severity: "info" }],
    );
    assert.equal(injected.length, 1, "the objective reconcile drive was captured");
    assert.deepEqual(
      stderr.filter((line) => line.startsWith("perk: land —")),
      [],
      "report() emitted no raw stderr (unrelated binding warnings remain outside this fix)",
    );
  } finally {
    h.dispose();
  }
});
