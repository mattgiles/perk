// Live warm-door tests for the objective plan factory's `objective_node` tool. Drive a
// REAL bound AgentSession via the T1 harness and prove the delegation + the two arg shapes + the
// structural completion-audit refusal, OFFLINE: a fake `perk` (PERK_BIN) stands in for the GitHub
// mutation (and captures its argv), so no LLM / network / gh / Python is invoked. Pure helpers are
// unit-tested separately below.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import {
  explorerLaneTask,
  OBJECTIVE_EXPLORER_REPORT_SCHEMA,
} from "../waves/objectiveExplorerWave.ts";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";
import {
  buildAddObjectiveNodeArgs,
  buildObjectiveNodeArgs,
  decodeAddObjectiveNodeParams,
  decodeExploreParams,
  factoryGuidance,
  objectiveReadInstruction,
  reconcileGuidance,
} from "./objectivePlan.ts";

// Local fragments of the shared linear arm — used by the per-plane selection + guidance
// composition tests below (no longer a cross-plane lockstep; the `objective-read-*` live-parity
// cases own cross-plane byte-parity).
const OBJECTIVE_LINEAR_SUBSTRINGS = [
  "Linear Project",
  "linear_get_issue",
  "linear_list_comments",
  "inspect a node-issue",
  "if the linear tools are unavailable, open ",
];
const LINEAR_URL = "https://linear.app/acme/project/objective-7";

test("objectiveReadInstruction: linear arm carries the shared substrings + the url", () => {
  const clause = objectiveReadInstruction("linear", "7", LINEAR_URL);
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(clause.includes(needle), `linear objective-read instruction missing: ${needle}`);
  }
  assert.ok(clause.includes(LINEAR_URL));
});

test("objectiveReadInstruction: linear without a url uses the indirect form, drops the open fallback", () => {
  const clause = objectiveReadInstruction("linear", "7", "");
  assert.ok(clause.includes("run `perk objective show 7` for its URL"));
  assert.ok(!clause.includes("if the linear tools are unavailable, open "));
  assert.ok(clause.includes("linear_get_issue") && clause.includes("linear_list_comments"));
});

test("objectiveReadInstruction: github (and any non-linear) arm is empty", () => {
  assert.equal(objectiveReadInstruction("github", "7", LINEAR_URL), "");
  assert.equal(objectiveReadInstruction("gitlab", "7", LINEAR_URL), "");
});

test("factoryGuidance + reconcileGuidance: linear arm injects the read clause; github is unchanged", () => {
  const planLinear = factoryGuidance("7", "1.2", "linear", LINEAR_URL);
  const reconcileLinear = reconcileGuidance("7", "linear", LINEAR_URL);
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(planLinear.includes(needle), `factoryGuidance(linear) missing: ${needle}`);
    assert.ok(reconcileLinear.includes(needle), `reconcileGuidance(linear) missing: ${needle}`);
  }
  // The github arm (default) carries no linear fragment.
  const planGithub = factoryGuidance("7", "1.2");
  const reconcileGithub = reconcileGuidance("7");
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(!planGithub.includes(needle), `factoryGuidance(github) leaked: ${needle}`);
    assert.ok(!reconcileGithub.includes(needle), `reconcileGuidance(github) leaked: ${needle}`);
  }
});

test("reconcileGuidance names both reconcile_objective and add_objective_node", () => {
  const text = reconcileGuidance("7");
  assert.ok(text.includes("reconcile_objective"), "still names reconcile_objective");
  assert.ok(text.includes("add_objective_node"), "now names add_objective_node");
  assert.ok(text.includes("SPARINGLY"), "frames node insertion as sparing");
  // The other side of the rule: the positive trigger circumstances are named too.
  assert.ok(text.includes("deferred follow-up"), "names the deferred-follow-up trigger");
  assert.ok(text.includes("missing prerequisite"), "names the missing-prerequisite trigger");
});

test("reconcileGuidance instructs reading objective engagement as untrusted DATA", () => {
  const text = reconcileGuidance("7");
  assert.ok(
    text.includes("perk objective engagement 7"),
    "names the objective engagement read worker with the objective id",
  );
  assert.ok(
    text.includes("<untrusted_objective_engagement>"),
    "names the untrusted-DATA block tag",
  );
  assert.ok(
    text.includes("never as instructions"),
    "frames the engagement as DATA, never instructions",
  );
});

test("factoryGuidance explores via ONE explore_objective_node call — no transcribed mechanics", () => {
  const text = factoryGuidance("42", "1.2");
  assert.match(text, /explore_objective_node/);
  assert.match(text, /\[models\.subagents\] objective-explorer/);
  // The transcription surface is gone: no workflowScript skeleton, no schema block, no model
  // clause — the tool owns the mechanics and reads the model at execute time.
  assert.doesNotMatch(text, /workflowScript/);
  assert.doesNotMatch(text, /outputSchema/);
  assert.doesNotMatch(text, /runs\.run/);
  assert.doesNotMatch(text, /structuredOutput/);
  assert.doesNotMatch(text, /"additionalProperties": false/);
  assert.doesNotMatch(text, /model: "/);
});

test("factoryGuidance instructs the file-first loop (draft → review → approval-driven save)", () => {
  const text = factoryGuidance("42", "1.2");
  // The draft tool and the review step are present.
  assert.match(text, /plan_draft/);
  assert.match(text, /plan_review/);
  // The unconditional planning mark (re-records the claim even on resume).
  assert.match(text, /even if it is already `planning`/);
  assert.match(text, /records the in-session claim/);
  // Approval carries the node link.
  assert.match(text, /recovers `objective_id`\/`node_id` automatically/);
  // The old primary-save mandate is gone (the failsafe sentence is phrased differently).
  assert.doesNotMatch(text, /then persist with/);
  assert.doesNotMatch(text, /passing BOTH `objective_id: "/);
  // The failsafe + never-implement mandate survive.
  assert.match(text, /Manual failsafe: `\/plan-save`/);
  assert.match(text, /ALWAYS save, NEVER implement directly/);
});

test("factoryGuidance instructs the node-engagement fetch (backend-neutral, both backends)", () => {
  // The warm seed instructs the model to fetch the node-issue's pre-planning engagement
  // once it knows the node. The instruction is backend-neutral (harmless on github) so it appears
  // for both linear and github seeds.
  const linear = factoryGuidance("7", "1.2", "linear", LINEAR_URL);
  const github = factoryGuidance("7", "1.2");
  for (const text of [linear, github]) {
    assert.match(text, /perk objective node-engagement 7 --node <id>/);
    assert.match(text, /untrusted\s+DATA/);
  }
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

test("tool: add_objective_node delegates the node-add argv (with optionals)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("add_objective_node", {
      objective: 7,
      phase: 2,
      description: "Newly emerged work",
      depends_on: ["1.1", "2.1"],
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.deepEqual(readArgv(argvFile), [
      "objective",
      "node-add",
      "7",
      "--phase",
      "2",
      "--description",
      "Newly emerged work",
      "--depends-on",
      "1.1",
      "--depends-on",
      "2.1",
      "--json",
    ]);
  } finally {
    h.dispose();
  }
});

test("tool: add_objective_node — a failing worker fails loud-but-soft (no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("add_objective_node", {
      objective: 7,
      phase: 2,
      description: "x",
    });
    assert.equal((result.details as { ok: boolean }).ok, false);
  } finally {
    h.dispose();
  }
});

test("tool: add_objective_node — a success:false envelope surfaces the structured error", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const envelope = JSON.stringify({
    success: false,
    error_type: "invalid_input",
    message: "could not add node to phase 9 on #7 (id collision)",
  });
  const bin = fakePerk(cwd, { stdout: envelope, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("add_objective_node", {
      objective: 7,
      phase: 9,
      description: "x",
    });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "invalid_input");
    assert.equal(details.error, "could not add node to phase 9 on #7 (id collision)");
  } finally {
    h.dispose();
  }
});

test("tool: add_objective_node with a non-integer phase → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("add_objective_node", {
      objective: 7,
      phase: 1.5,
      description: "x",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("tool: objective_node — a success:false envelope at non-zero exit surfaces the structured error", async () => {
  // The envelope-aware regression: the Python plane prints a structured failure
  // envelope to stdout before exiting non-zero — the door must surface it, not the stderr tail.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const envelope = JSON.stringify({
    success: false,
    error_type: "node_not_found",
    message: "no node 9.9 in the roadmap",
  });
  const bin = fakePerk(cwd, { stdout: envelope, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_node", { objective: 7, node: "9.9", pr: "#9" });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "node_not_found");
    assert.equal(details.error, "no node 9.9 in the roadmap");
  } finally {
    h.dispose();
  }
});

// --- the warm handlers fetch the url only for linear, fail-open to the indirect form ---

/** Write a committed `.perk/config.toml` selecting the issue backend (resolveIssueBackendId reads it). */
function writeBackend(cwd: string, backend: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[issues]\nbackend = "${backend}"\n`, "utf8");
}

test("/objective-plan (linear) fetches the Project URL and seeds the backend-aware clause", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "linear");
  const url = "https://linear.app/acme/project/objective-7";
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: true, error_type: null, objective: { id: "7", url } }),
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const seen = spyInjections(h);
  try {
    await h.invokeCommand("objective-plan", "7");
    const msg = seen.join("\n");
    assert.ok(msg.includes("This objective is a Linear Project"), "linear clause injected");
    assert.ok(msg.includes(url), "the fetched Project URL is referenced");
  } finally {
    h.dispose();
  }
});

test("/objective-plan (linear) fails open to the indirect form when the fetch fails", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "linear");
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const seen = spyInjections(h);
  try {
    await h.invokeCommand("objective-plan", "7");
    const msg = seen.join("\n");
    assert.ok(msg.includes("This objective is a Linear Project"), "linear clause still injected");
    assert.ok(msg.includes("run `perk objective show 7` for its URL"), "indirect form used");
    assert.ok(!msg.includes("if the linear tools are unavailable, open "), "no open fallback");
  } finally {
    h.dispose();
  }
});

test("/objective-plan (github) injects no linear clause and runs no fetch", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "github");
  // A throwing PERK_BIN proves no fetch happens for the github arm (no objective show call).
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const seen = spyInjections(h);
  try {
    await h.invokeCommand("objective-plan", "7");
    const msg = seen.join("\n");
    assert.ok(!msg.includes("Linear Project"), "no linear clause on the github arm");
  } finally {
    h.dispose();
  }
});

test("/objective-reconcile (linear) fetches the Project URL and seeds the backend-aware clause", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "linear");
  const url = "https://linear.app/acme/project/objective-7";
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: true, error_type: null, objective: { id: "7", url } }),
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const seen = spyInjections(h);
  try {
    await h.invokeCommand("objective-reconcile", "7");
    const msg = seen.join("\n");
    assert.ok(msg.includes("This objective is a Linear Project"), "linear clause injected");
    assert.ok(msg.includes(url), "the fetched Project URL is referenced");
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

// --- /objective-plan enters the read-only gate -------------------

test("/objective-plan enters the read-only gate: mode flips, write blocked, announce reported", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  spyInjections(h);
  try {
    // Starts read-write: write allowed.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);

    await h.invokeCommand("objective-plan", "7");

    assert.equal(h.workflowState().mode, "read-only", "mode flips to read-only");
    assert.equal(
      (await h.emitToolCall("write", { path: "x", content: "y" }))?.block,
      true,
      "write is structurally blocked",
    );
    assert.ok(
      h.notifies.some((m) => /read-only ON/.test(m)),
      "the read-only announce line was reported",
    );
  } finally {
    h.dispose();
  }
});

test("/objective-plan skip-if-active: an already read-only session gets no duplicate enter/announce", async () => {
  // The cold-door shape: the handoff's `mode: read-only` claim syncs the gate on at session_start.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  spyInjections(h);
  try {
    await h.invokeCommand("objective-plan", "7");

    assert.equal(h.workflowState().mode, "read-only", "mode stays read-only");
    assert.equal(
      h.notifies.filter((m) => /read-only ON/.test(m)).length,
      0,
      "no duplicate announce when the gate is already active",
    );
    assert.ok(
      h.notifies.some((m) => /#7/.test(m)),
      "the objective info line still reports",
    );
  } finally {
    h.dispose();
  }
});

test("/objective-plan with no objective leaves the gate off (warning only)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    await h.invokeCommand("objective-plan");

    assert.ok(
      h.notifyEvents.some((e) => e.severity === "warning" && /no objective given/.test(e.message)),
      "the no-objective warning fires",
    );
    assert.notEqual(h.workflowState().mode, "read-only", "the gate stays off");
    assert.equal(
      (await h.emitToolCall("write", { path: "x", content: "y" }))?.block,
      undefined,
      "writes stay unblocked",
    );
  } finally {
    h.dispose();
  }
});

// --- pure helpers (offline unit) --------------------------------------------------------

test("buildObjectiveNodeArgs: shapes", () => {
  assert.deepEqual(buildObjectiveNodeArgs({ objective: "7", node: "1.2", pr: "#9" }), [
    "objective",
    "node",
    "7",
    "--node",
    "1.2",
    "--pr",
    "#9",
    "--json",
  ]);
  assert.deepEqual(buildObjectiveNodeArgs({ objective: "7", node: "1.2", status: "planning" }), [
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
    buildObjectiveNodeArgs({ objective: "7", node: "1.2", status: "in_progress", pr: "#9" }),
    ["objective", "node", "7", "--node", "1.2", "--status", "in_progress", "--pr", "#9", "--json"],
  );
  // neither status nor pr nor description -> structurally invalid.
  assert.equal(buildObjectiveNodeArgs({ objective: "7", node: "1.2" }), null);
});

test("buildObjectiveNodeArgs: description alone is valid", () => {
  assert.deepEqual(
    buildObjectiveNodeArgs({ objective: "7", node: "1.2", description: "reconciled scope" }),
    ["objective", "node", "7", "--node", "1.2", "--description", "reconciled scope", "--json"],
  );
  // description with status + pr -> all three pushed in order.
  assert.deepEqual(
    buildObjectiveNodeArgs({
      objective: "7",
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

test("buildAddObjectiveNodeArgs: required-only shape", () => {
  assert.deepEqual(
    buildAddObjectiveNodeArgs({ objective: "7", phase: 2, description: "New work" }),
    ["objective", "node-add", "7", "--phase", "2", "--description", "New work", "--json"],
  );
});

test("buildAddObjectiveNodeArgs: all optionals, one --depends-on per dep, --phase stringified", () => {
  assert.deepEqual(
    buildAddObjectiveNodeArgs({
      objective: "7",
      phase: 3,
      description: "New work",
      status: "planning",
      slug: "new-work",
      depends_on: ["1.1", "2.1"],
      comment: "emerged during reconcile",
    }),
    [
      "objective",
      "node-add",
      "7",
      "--phase",
      "3",
      "--description",
      "New work",
      "--status",
      "planning",
      "--slug",
      "new-work",
      "--depends-on",
      "1.1",
      "--depends-on",
      "2.1",
      "--comment",
      "emerged during reconcile",
      "--json",
    ],
  );
});

test("decodeAddObjectiveNodeParams: happy decode (bare-number objective coerces)", () => {
  assert.deepEqual(
    decodeAddObjectiveNodeParams({ objective: 7, phase: 2, description: "New work" }),
    {
      objective: "7",
      phase: 2,
      description: "New work",
      status: undefined,
      slug: undefined,
      depends_on: undefined,
      comment: undefined,
    },
  );
});

test("decodeAddObjectiveNodeParams: strict-fail cases", () => {
  // absent phase
  assert.equal(decodeAddObjectiveNodeParams({ objective: "7", description: "x" }), null);
  // non-integer phase
  assert.equal(
    decodeAddObjectiveNodeParams({ objective: "7", phase: 1.5, description: "x" }),
    null,
  );
  // zero / negative phase
  assert.equal(decodeAddObjectiveNodeParams({ objective: "7", phase: 0, description: "x" }), null);
  // missing description
  assert.equal(decodeAddObjectiveNodeParams({ objective: "7", phase: 2 }), null);
  // empty description
  assert.equal(decodeAddObjectiveNodeParams({ objective: "7", phase: 2, description: "" }), null);
  // unknown status
  assert.equal(
    decodeAddObjectiveNodeParams({ objective: "7", phase: 2, description: "x", status: "nope" }),
    null,
  );
  // non-string depends_on item
  assert.equal(
    decodeAddObjectiveNodeParams({
      objective: "7",
      phase: 2,
      description: "x",
      depends_on: ["1.1", 2],
    }),
    null,
  );
  // empty-string depends_on item
  assert.equal(
    decodeAddObjectiveNodeParams({
      objective: "7",
      phase: 2,
      description: "x",
      depends_on: [""],
    }),
    null,
  );
});

// --- explore_objective_node: decode matrix + the flow tool over a fake RPC responder ------------

test("decodeExploreParams: trim-then-refuse matrix (whitespace-only arms refuse whole)", () => {
  // The happy trims: the TRIMMED values are what enter the lane task.
  assert.deepEqual(decodeExploreParams({ node: " 2.3 ", description: " Do the thing " }), {
    node: "2.3",
    description: "Do the thing",
  });
  assert.deepEqual(
    decodeExploreParams({ node: "2.3", description: "Do it", focus: " map consumers " }),
    { node: "2.3", description: "Do it", focus: "map consumers" },
  );
  // Absent/mistyped/blank required fields ⇒ whole refusal.
  assert.equal(decodeExploreParams(undefined), null);
  assert.equal(decodeExploreParams({}), null);
  assert.equal(decodeExploreParams({ node: "2.3" }), null);
  assert.equal(decodeExploreParams({ description: "x" }), null);
  assert.equal(decodeExploreParams({ node: 2.3, description: "x" }), null);
  assert.equal(decodeExploreParams({ node: "2.3", description: 5 }), null);
  assert.equal(decodeExploreParams({ node: "   ", description: "x" }), null);
  assert.equal(decodeExploreParams({ node: "2.3", description: "   " }), null);
  // focus: absent is fine; present-but-mistyped or blank-after-trim refuses.
  assert.equal(decodeExploreParams({ node: "2.3", description: "x", focus: 5 }), null);
  assert.equal(decodeExploreParams({ node: "2.3", description: "x", focus: "   " }), null);
});

/** The spawn params the fake responder observes (the tool-boundary threading assertions). */
interface SpawnSink {
  spawns: { workflowScript?: string; model?: string; outputSchema?: unknown }[];
}

/** A schema-valid explorer report the fake responder answers with. */
const EXPLORER_REPORT = {
  node: "2.3",
  relevant_files: [{ path: "src/a.py", why: "the seam" }],
  symbols: [{ name: "run", path: "src/a.py", why: "entry" }],
  anchors: ["the adapter seam"],
  patterns: ["mirror the learn wave"],
  open_questions: ["retry policy?"],
};

/**
 * A fake pi-subagents responder bound as a bus peer (the prReview.test.ts pattern): answers
 * ping/spawn on `pi.events` with the v1 envelope, writes a terminal `status.json` carrying one
 * schema-valid explorer report per lane into a real temp `asyncDir`, and emits the advertised
 * completion event. Each spawn's params land in `sink` ("pin the glue").
 */
function fakeSubagentsResponder(sink: SpawnSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.events.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const request = raw as {
        requestId: string;
        method: string;
        params?: { workflowScript?: string; model?: string; outputSchema?: unknown };
      };
      const reply = (payload: Record<string, unknown>): void => {
        pi.events.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, {
          version: WAVE_RPC_PROTOCOL_VERSION,
          requestId: request.requestId,
          method: request.method,
          ...payload,
        });
      };
      if (request.method === "ping") {
        reply({
          success: true,
          data: {
            version: WAVE_RPC_PROTOCOL_VERSION,
            methods: ["ping", "status", "spawn", "steer", "interrupt", "stop", "resume"],
            capabilities: { asyncSpawn: true },
            events: { asyncComplete: "subagent:async-complete" },
            session: {},
          },
        });
        return;
      }
      if (request.method === "spawn") {
        if (request.params !== undefined) sink.spawns.push(request.params);
        const script = request.params?.workflowScript ?? "";
        const start = script.indexOf("runs.all(") + "runs.all(".length;
        const end = script.indexOf(");\nreturn");
        const lanes = JSON.parse(script.slice(start, end)) as Array<{ key: string }>;
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-explore-e2e-"));
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({
            runId: basename(asyncDir),
            mode: "workflow",
            state: "complete",
            startedAt: 0,
            workflow: {
              value: lanes.map(({ key }) => ({
                key,
                ok: true,
                error: null,
                report: EXPLORER_REPORT,
              })),
            },
          }),
        );
        reply({
          success: true,
          data: { text: "Started async run.", details: { asyncId: basename(asyncDir), asyncDir } },
        });
        pi.events.emit("subagent:async-complete", {
          id: basename(asyncDir),
          asyncDir,
          state: "complete",
        });
        return;
      }
      reply({
        success: false,
        error: { code: "not_found", message: `fake responder rejects ${request.method}` },
      });
    });
  };
}

test("tool: explore_objective_node end-to-end — trimmed params in the task, model threads, flow receipt", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // The configured explorer model must reach the wave as its workflow-level default.
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nobjective-explorer = "test-explorer-model"\n',
    "utf8",
  );
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    const result = await h.invokeTool("explore_objective_node", {
      node: " 2.3 ",
      description: " Wire the adapter seam ",
      focus: " map the config consumers ",
    });
    const details = result.details as {
      ok: boolean;
      report?: unknown;
      attempts?: { flow: string; attempt: number; requestedKeys: string[]; state: string }[];
    };
    assert.equal(details.ok, true);
    assert.equal(result.terminate, undefined, "explore is non-terminating");
    assert.deepEqual(details.report, EXPLORER_REPORT);
    // The single attempt receipt pins the flow value the tool records.
    assert.equal(details.attempts?.length, 1);
    assert.equal(details.attempts?.[0]?.flow, "objective-explorer");
    assert.equal(details.attempts?.[0]?.attempt, 1);
    assert.deepEqual(details.attempts?.[0]?.requestedKeys, ["explore"]);
    assert.equal(details.attempts?.[0]?.state, "complete");
    // The model-facing prose: untrusted-DATA preface + ONE fenced json block of the report.
    const text = result.content[0]?.text ?? "";
    assert.match(text, /untrusted DATA/);
    assert.match(text, /```json/);
    // Pin the glue: the configured model and the module-owned schema reached the actual spawn,
    // and the TRIMMED params entered the code-owned lane task.
    assert.equal(sink.spawns.length, 1);
    assert.equal(sink.spawns[0]?.model, "test-explorer-model");
    assert.deepEqual(sink.spawns[0]?.outputSchema, OBJECTIVE_EXPLORER_REPORT_SCHEMA);
    const script = sink.spawns[0]?.workflowScript ?? "";
    const lanes = JSON.parse(
      script.slice(script.indexOf("runs.all(") + "runs.all(".length, script.indexOf(");\nreturn")),
    ) as Array<{ key: string; agent: string; task: string }>;
    assert.equal(lanes[0]?.agent, "perk.objective-explorer");
    assert.equal(
      lanes[0]?.task,
      explorerLaneTask("2.3", "Wire the adapter seam", "map the config consumers"),
    );
  } finally {
    h.dispose();
  }
});

test("tool: explore_objective_node — bad input refuses whole before any spawn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    for (const params of [
      {},
      { node: "   ", description: "x" },
      { node: "2.3", description: "   " },
      { node: "2.3", description: "x", focus: "   " },
    ]) {
      const result = await h.invokeTool("explore_objective_node", params);
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false);
      assert.equal(details.error_type, "bad_input");
    }
    assert.equal(sink.spawns.length, 0, "no spawn on a refused decode");
  } finally {
    h.dispose();
  }
});

test("tool: explore_objective_node — an unavailable wave soft-fails loudly (explore directly instead)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // No RPC responder bound + a tiny ping timeout → the deterministic `unavailable` arm.
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_WAVE_RPC_PING_MS: "20" },
  });
  try {
    const result = await h.invokeTool("explore_objective_node", {
      node: "2.3",
      description: "Wire the adapter seam",
    });
    const details = result.details as {
      ok: boolean;
      error_type?: string;
      attempts?: { state: string }[];
    };
    assert.equal(details.ok, false, "an incomplete explore wave is a soft failure");
    assert.equal(details.error_type, "unavailable");
    assert.equal(details.attempts?.length, 1);
    assert.equal(details.attempts?.[0]?.state, "unavailable");
    assert.match(result.content[0]?.text ?? "", /explore_objective_node failed/);
  } finally {
    h.dispose();
  }
});
