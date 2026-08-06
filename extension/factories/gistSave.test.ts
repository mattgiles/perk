// Live warm-door tests for the `gist_save` tool + `/gist-save` command (the gist mirror of
// objectiveSave.test.ts). Drive a REAL bound AgentSession via the harness and prove the
// `perk gist create` delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in for the
// backend write. Unlike the objective twin there is NO session linkage to assert — nothing
// consumes a gist in-session. The `gistApprovalSave` seam runs on pure fakes below.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type SessionDataCtx, writeSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { type EntrySink, WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import { GIST_DRAFT_ARTIFACT } from "./gistDraft.ts";
import { gistApprovalSave, gistSaveGuidance } from "./gistSave.ts";

const CREATE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  gist: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  scope: "plan",
  dry_run: false,
});

const FAIL_ENVELOPE = JSON.stringify({
  success: false,
  error_type: "github_error",
  message: "gh exploded",
});

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

test("tool: gist_save delegates to perk gist create, relays the consumption hint, terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("gist_save", {
      prose: PROSE,
      title: "Faster reviews",
      scope: "plan",
    });
    const details = result.details as { ok: boolean; gist?: { id: string }; scope?: string };
    assert.equal(details.ok, true);
    assert.equal(details.gist?.id, "7");
    assert.equal(details.scope, "plan");
    assert.equal(result.terminate, true);
    const text = String((result.content as { text?: string }[])[0]?.text);
    assert.match(text, /Saved gist 7/);
    assert.match(text, /Consume with: perk plan from 7/, "the consumption hint rides the relay");
    const argv = readFileSync(argvFile, "utf8");
    assert.match(argv, /gist\ncreate/);
    assert.match(argv, /--title\nFaster reviews/);
    assert.match(argv, /--scope\nplan/);
    assert.match(argv, /--run-id\n01RID/);
  } finally {
    h.dispose();
  }
});

test("tool: an objective-scope envelope relays the objective adoption door", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({
      success: true,
      error_type: null,
      gist: { id: "proj-9", url: "https://linear/p/9", existed: false },
      scope: "objective",
      dry_run: false,
    }),
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("gist_save", { prose: PROSE });
    assert.match(
      String((result.content as { text?: string }[])[0]?.text),
      /Consume with: perk objective author --from proj-9/,
    );
  } finally {
    h.dispose();
  }
});

test("tool: scope omitted from argv when not passed (the cold door owns the handoff default)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("gist_save", { prose: PROSE });
    assert.doesNotMatch(readFileSync(argvFile, "utf8"), /--scope/);
  } finally {
    h.dispose();
  }
});

test("tool: gist_save stages the prose in run scratch", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("gist_save", { prose: PROSE });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
    assert.ok(
      bodyFile.includes(join(".perk", "workflow", "scratch", "runs", "01RID")),
      `prose staged under run scratch (got ${bodyFile})`,
    );
    // saveGist trims the prose before staging, hence the .trim() on the expectation.
    assert.equal(readFileSync(bodyFile, "utf8"), PROSE.trim(), "the staged file holds the prose");
  } finally {
    h.dispose();
  }
});

test("tool: a success:false envelope at non-zero exit surfaces the structured error", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: FAIL_ENVELOPE, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("gist_save", { prose: PROSE });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "github_error");
    assert.equal(details.error, "gh exploded");
  } finally {
    h.dispose();
  }
});

test("tool: success:true with a malformed gist fails as bad_output", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    gist: { id: 7, url: "https://gh/o/r/issues/7" }, // id a number → reject (string ids, §8.21)
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("gist_save", { prose: PROSE });
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
  } finally {
    h.dispose();
  }
});

test("tool: gist_save with a mistyped scope → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("gist_save", { prose: PROSE, scope: "banana" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"), "no exec happened (argv file absent)");
  } finally {
    h.dispose();
  }
});

test("/gist-save registers and is headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("gist-save"), "the /gist-save command registered");
  } finally {
    h.dispose();
  }
});

// --- pure helpers (offline unit) ------------------------------------------------------------------

test("gistSaveGuidance: drives the gist_save tool with prose + scope; optional title named", () => {
  const text = gistSaveGuidance();
  assert.match(text, /gist_save/);
  assert.match(text, /prose/);
  assert.match(text, /scope/);
  assert.match(text, /defaults to the prose's first heading/);
  assert.match(gistSaveGuidance("Faster reviews"), /title: "Faster reviews"/);
});

test("gistSaveGuidance: does not hardcode the perk-gist-author skill pointer", () => {
  // The skill pointer rides the binding suffix, never the guidance body.
  assert.doesNotMatch(gistSaveGuidance(), /perk-gist-author/);
});

// --- the gistApprovalSave seam (pure fakes, offline) -----------------------------------------------

const DRAFT_PAYLOAD = `${JSON.stringify({
  schema_version: 1,
  title: "Faster reviews",
  scope: "objective",
  prose: PROSE,
})}\n`;

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

/** Plant the gist-draft artifact (file + pointer) on a live branch. */
function plantDraft(ctx: SessionDataCtx & ReportTarget, branch: unknown[]): void {
  assert.ok(
    writeSessionArtifact(fakeSink(branch), ctx, GIST_DRAFT_ARTIFACT, DRAFT_PAYLOAD),
    "the gist draft artifact landed",
  );
}

test("gistApprovalSave: no draft → no-draft, no exec, gate untouched", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
  const gating = fakeGating(true);
  const outcome = await gistApprovalSave(pi, ctx, gating);
  assert.deepEqual(outcome, { status: "no-draft" });
  assert.equal(argvs.length, 0, "no cold-door exec");
  assert.equal(gating.exits, 0, "the gate was untouched");
});

test("gistApprovalSave: happy path — the draft's title/scope ride argv, gate exited once", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  const gating = fakeGating(true);
  const outcome = await gistApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, true, "gateExited reported");
  assert.equal(gating.exits, 1, "the gate was exited exactly once");
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "gist");
  assert.equal(argv[1], "create");
  assert.equal(argv[argv.indexOf("--title") + 1], "Faster reviews", "the draft's title");
  assert.equal(argv[argv.indexOf("--scope") + 1], "objective", "the draft's scope");
  const result = outcome.status === "saved" ? outcome.result : null;
  assert.equal(result?.terminate, true, "the result keeps terminate for tool-path callers");
});

test("gistApprovalSave: an explicit title overrides the draft title", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON, argvs });
  await gistApprovalSave(pi, ctx as unknown as ExtensionContext, fakeGating(true), {
    title: "Override title",
  });
  const argv = argvs[0] ?? [];
  assert.equal(argv[argv.indexOf("--title") + 1], "Override title");
});

test("gistApprovalSave: a failed save leaves the gate on", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-only" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const pi = fakeApprovalPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
  const gating = fakeGating(true);
  const outcome = await gistApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "save-failed");
  assert.equal(outcome.status === "save-failed" && outcome.gateExited, false);
  assert.equal(gating.exits, 0, "the gate stays on");
});

test("gistApprovalSave: a successful save while already read-write never exits the gate", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry({ run_id: "RID", mode: "read-write" })];
  const ctx = reportableCtx(cwd, branch);
  plantDraft(ctx, branch);
  const pi = fakeApprovalPi(branch, { stdout: CREATE_JSON });
  const gating = fakeGating(false);
  const outcome = await gistApprovalSave(pi, ctx as unknown as ExtensionContext, gating);
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, false);
  assert.equal(gating.exits, 0, "no gating.exit call");
});

// --- the artifact-first /gist-save command ---------------------------------------------------------

test("command: /gist-save with a draft → the seam saves; no drive injection; gate exits", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, { stdout: CREATE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    const drafted = await h.invokeTool("gist_draft", { prose: PROSE, title: "Faster reviews" });
    assert.equal((drafted.details as { ok?: boolean }).ok, true, "the draft landed");
    await h.invokeCommand("gist-save");
    assert.ok(
      h.notifies.some((n) => /Saved gist 7/.test(n)),
      `the save message was reported (got ${JSON.stringify(h.notifies)})`,
    );
    assert.equal(sent.length, 0, "no drive injection when a draft exists");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited on the saved arm");
  } finally {
    h.dispose();
  }
});

test("command: /gist-save without a draft → the legacy drive fallback", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: "/nonexistent" } });
  const sent = spyInjections(h);
  try {
    await h.invokeCommand("gist-save", "Faster reviews");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited for the driven turn");
    assert.ok(
      h.notifies.some((n) => /handing the save to the session/.test(n)),
      "the drive report",
    );
    assert.equal(sent.length, 1, "exactly one drive injection");
    assert.match(String(sent[0]), /gist_save/);
    assert.match(String(sent[0]), /title: "Faster reviews"/);
  } finally {
    h.dispose();
  }
});

test("command: /gist-save with a draft but a failing cold door → error report, gate stays on", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, { stdout: FAIL_ENVELOPE, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    await h.invokeTool("gist_draft", { prose: PROSE });
    await h.invokeCommand("gist-save");
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
