// Live warm-door tests for the `objective_save` tool + `/objective-save` command. Drive a
// REAL bound AgentSession via the harness and prove the `perk objective create` delegation +
// session linkage (active_objective + budget marker) end-to-end, OFFLINE: a fake `perk` (PERK_BIN)
// stands in for the GitHub write. The pure objectiveSaveGuidance twin is unit-tested below.
// The `objectiveApprovalSave` seam (pure fakes, the planSave.test.ts recipe) and
// the artifact-first `/objective-save` command (seam-first; legacy drive as the no-draft fallback).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type SessionDataCtx, writeSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import {
  type EntrySink,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./objectiveDraft.ts";
import { objectiveApprovalSave, objectiveSaveGuidance } from "./objectiveSave.ts";

const CREATE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  objective: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  dry_run: false,
});

const PROSE = "# Ship retries\n\n## Why\nThe gateway needs retries.\n";

interface BudgetEntry {
  type?: string;
  customType?: string;
  data?: { objective_id?: string };
}

test("tool: objective_save delegates, links active_objective + seeds budget marker, terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CREATE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", {
      prose: PROSE,
      roadmap: [{ id: "1.1", description: "first" }],
    });
    const details = result.details as { ok: boolean; objective?: { id: string } };
    assert.equal(details.ok, true);
    assert.equal(details.objective?.id, "7");
    assert.equal(result.terminate, true);
    // active_objective linked on the live session.
    assert.equal(h.workflowState().active_objective, "7");
    // a fresh budget activation marker was seeded.
    const entries = h.session.sessionManager.getEntries() as unknown as BudgetEntry[];
    const marker = entries.find((e) => e.customType === OBJECTIVE_BUDGET_TYPE);
    assert.ok(marker, "budget marker seeded");
    assert.equal(marker?.data?.objective_id, "7");
  } finally {
    h.dispose();
  }
});

test("tool: objective_save passes the structured roadmap as --roadmap <json>", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_save", {
      prose: PROSE,
      title: "Ship retries",
      roadmap: [{ id: "1.1", description: "first" }],
    });
    const argv = readFileSync(argvFile, "utf8");
    assert.match(argv, /objective\ncreate/);
    assert.match(argv, /--roadmap/);
    assert.match(argv, /"id":"1.1"/);
    assert.match(argv, /--run-id\n01RID/);
    assert.match(argv, /--title\nShip retries/);
  } finally {
    h.dispose();
  }
});

test("tool: objective_save passes --base when supplied, omits it otherwise", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_save", { prose: PROSE, base: "develop" });
    assert.match(readFileSync(argvFile, "utf8"), /--base\ndevelop/);
    await h.invokeTool("objective_save", { prose: PROSE });
    assert.doesNotMatch(readFileSync(argvFile, "utf8"), /--base/);
  } finally {
    h.dispose();
  }
});

test("tool: a success:false envelope at non-zero exit surfaces the structured error (no linkage)", async () => {
  // The envelope-aware regression: the Python plane prints a structured failure
  // envelope to stdout before exiting non-zero — the door surfaces it, not the stderr tail.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: false, error_type: "github_error", message: "boom" }),
    code: 1,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", { prose: PROSE });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "github_error");
    assert.equal(details.error, "boom");
    assert.equal(h.workflowState().active_objective ?? null, null, "no linkage on failure");
  } finally {
    h.dispose();
  }
});

test("tool: success:true with a malformed objective fails as bad_output (no linkage)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    objective: { id: 7, url: "https://gh/o/r/issues/7" }, // id a number → reject (string ids, §8.21)
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", { prose: PROSE });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
    assert.equal(h.workflowState().active_objective ?? null, null, "no linkage on bad output");
  } finally {
    h.dispose();
  }
});

test("tool: objective_save stages the prose in run scratch (mkdtemp retirement)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_save", { prose: PROSE });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
    assert.ok(
      bodyFile.includes(join(".perk", "workflow", "scratch", "runs", "01RID")),
      `prose staged under run scratch (got ${bodyFile})`,
    );
    // saveObjective trims the prose before staging, hence the .trim() on the expectation.
    assert.equal(readFileSync(bodyFile, "utf8"), PROSE.trim(), "the staged file holds the prose");
  } finally {
    h.dispose();
  }
});

test("/objective-save registers and is headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(
      h.registeredCommands().includes("objective-save"),
      "the /objective-save command is registered",
    );
  } finally {
    h.dispose();
  }
});

// --- pure helpers (offline unit) --------------------------------------------------------

test("objectiveSaveGuidance: with no title, drives the objective_save tool with prose + roadmap", () => {
  const text = objectiveSaveGuidance();
  assert.match(text, /objective_save/);
  assert.match(text, /prose/);
  assert.match(text, /roadmap/);
  assert.match(text, /JSON array of nodes/);
  assert.match(text, /defaults to the prose's first heading/);
});

test("objectiveSaveGuidance: with a title argument, names that title", () => {
  const text = objectiveSaveGuidance("Ship retries");
  assert.match(text, /title: "Ship retries"/);
});

test("objectiveSaveGuidance: does not hardcode the perk-objective-author skill pointer", () => {
  // The skill pointer rides the binding suffix, never the guidance body.
  assert.doesNotMatch(objectiveSaveGuidance(), /perk-objective-author/);
});

// --- tool-boundary decode (strict-fail on mistyped params) -----------------------

test("tool: objective_save with a mistyped roadmap → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", {
      prose: "# Objective",
      roadmap: "not-an-array",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

// --- the objectiveApprovalSave seam (pure fakes, offline) --------------------

const DRAFT_ROADMAP = [{ id: "1.1", description: "first" }];
const DRAFT_PAYLOAD = `${JSON.stringify({
  schema_version: 1,
  title: "Ship retries",
  prose: PROSE,
  roadmap: DRAFT_ROADMAP,
})}\n`;

const FAIL_ENVELOPE = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
});

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

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

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

/** Plant the objective-draft artifact (file + pointer) on a live branch. */
function plantDraft(ctx: SessionDataCtx & ReportTarget, branch: unknown[]): void {
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, OBJECTIVE_DRAFT_ARTIFACT, DRAFT_PAYLOAD),
    "the objective draft artifact landed",
  );
}

test("objectiveApprovalSave: no draft → no-draft, no exec, gate untouched", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
  const gating = fakeGating(true);
  const outcome = await objectiveApprovalSave(pi, ctx, gating);
  assert.deepEqual(outcome, { status: "no-draft" });
  assert.equal(argvs.length, 0, "no cold-door exec");
  assert.equal(gating.exits, 0, "the gate was untouched");
});

test("objectiveApprovalSave: happy path — artifact saved, gate exited once, session linked", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  const gating = fakeGating(true);
  const outcome = await objectiveApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, true, "gateExited reported");
  assert.equal(gating.exits, 1, "the gate was exited exactly once");
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "objective");
  assert.equal(argv[1], "create");
  assert.equal(
    argv[argv.indexOf("--roadmap") + 1],
    JSON.stringify(DRAFT_ROADMAP),
    "the draft's structured roadmap rode --roadmap",
  );
  assert.equal(argv[argv.indexOf("--title") + 1], "Ship retries", "the draft's title rode --title");
  const result = outcome.status === "saved" ? outcome.result : null;
  assert.equal(result?.terminate, true, "the result keeps terminate for tool-path callers");
  assert.equal(
    rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0]).active_objective,
    "7",
    "active_objective linked",
  );
});

test("objectiveApprovalSave: a draft base rides --base; absent draft base omits it", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  const payloadWithBase = `${JSON.stringify({
    schema_version: 1,
    title: "Ship retries",
    prose: PROSE,
    roadmap: DRAFT_ROADMAP,
    base: "develop",
  })}\n`;
  assert.ok(writeSessionArtifact(fakeSink(branch), ctx, OBJECTIVE_DRAFT_ARTIFACT, payloadWithBase));
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  await objectiveApprovalSave(pi, ctx as unknown as ExtensionContext, fakeGating(true));
  const argv = argvs[0] ?? [];
  assert.equal(argv[argv.indexOf("--base") + 1], "develop", "the draft's base rode --base");

  // A base-less draft omits --base entirely.
  const branch2: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx2 = reportableCtx(cwd, branch2);
  plantDraft(ctx2, branch2);
  const argvs2: string[][] = [];
  const pi2 = fakeApprovalPi(branch2, { stdout: CREATE_JSON, argvs: argvs2 });
  await objectiveApprovalSave(pi2, ctx2 as unknown as ExtensionContext, fakeGating(true));
  assert.ok(!(argvs2[0] ?? []).includes("--base"), "no --base for a base-less draft");
});

test("objectiveApprovalSave: an explicit title overrides the draft title", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  await objectiveApprovalSave(pi, ctx as unknown as ExtensionContext, fakeGating(true), {
    title: "Override title",
  });
  const argv = argvs[0] ?? [];
  assert.equal(argv[argv.indexOf("--title") + 1], "Override title");
});

test("objectiveApprovalSave: a failed save leaves the gate on, no linkage", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const pi = fakeApprovalPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
  const gating = fakeGating(true);
  const outcome = await objectiveApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "save-failed");
  assert.equal(outcome.status === "save-failed" && outcome.gateExited, false);
  assert.equal(gating.exits, 0, "the gate stays on");
  assert.equal(
    rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0]).active_objective ??
      null,
    null,
    "no active_objective append on failure",
  );
});

test("objectiveApprovalSave: a successful save while already read-write never exits the gate", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-write" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON });
  const gating = fakeGating(false);
  const outcome = await objectiveApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, false);
  assert.equal(gating.exits, 0, "no gating.exit call");
});

// --- the artifact-first /objective-save command --------------------------------

test("command: /objective-save with a draft → the seam saves; no drive injection", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, { stdout: CREATE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    const drafted = await h.invokeTool("objective_draft", {
      prose: PROSE,
      title: "Ship retries",
      roadmap: DRAFT_ROADMAP,
    });
    assert.equal((drafted.details as { ok?: boolean }).ok, true, "the draft landed");
    await h.invokeCommand("objective-save");
    assert.ok(
      h.notifies.some((n) => /Saved objective #7/.test(n)),
      `the save message was reported (got ${JSON.stringify(h.notifies)})`,
    );
    assert.equal(sent.length, 0, "no drive injection when a draft exists");
    assert.equal(h.workflowState().active_objective, "7", "the session was linked");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited on the saved arm");
  } finally {
    h.dispose();
  }
});

test("command: /objective-save without a draft → the legacy drive fallback", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: "/nonexistent" } });
  const sent = spyInjections(h);
  try {
    await h.invokeCommand("objective-save", "Ship retries");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited for the driven turn");
    assert.ok(
      h.notifies.some((n) => /handing the structured save to the session/.test(n)),
      "the drive report",
    );
    assert.equal(sent.length, 1, "exactly one drive injection");
    assert.match(String(sent[0]), /objective_save/);
    assert.match(String(sent[0]), /title: "Ship retries"/);
  } finally {
    h.dispose();
  }
});

test("command: /objective-save with a draft but a failing cold door → error report, gate stays on", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, { stdout: FAIL_ENVELOPE, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    await h.invokeTool("objective_draft", { prose: PROSE, roadmap: DRAFT_ROADMAP });
    await h.invokeCommand("objective-save");
    assert.ok(
      h.notifyEvents.some((e) => e.severity === "error" && /gh exploded/.test(e.message)),
      `an error-severity report (got ${JSON.stringify(h.notifyEvents)})`,
    );
    assert.equal(sent.length, 0, "no drive injection on a failed save");
    assert.equal(h.workflowState().mode, "read-only", "the gate stays on");
  } finally {
    h.dispose();
  }
});
