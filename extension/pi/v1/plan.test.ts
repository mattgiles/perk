// The v1 plan installer suite — ONE file for the whole registration surface (the
// pi/v1/gist.test.ts recipe): registration parity against the FROZEN pre-migration baselines,
// the plan-mode three-tier provider deferral, the `--plan` cold start, the plan-authoring
// context injection/strip (+ the active-window re-injection pin), the `plan_draft`/`plan_save`
// tool harness cases (read-only carve-out, decode strictness, cold-door delegation, node-link
// surfacing), the `/plan-save` severity mapping, the `approvalSave` seam, and the
// `/implement-here` command arms. Driven through a REAL bound AgentSession (offline): a fake
// `perk` (PERK_BIN) stands in for the GitHub write, so no LLM / network / gh / Python runs.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import {
  PLAN_AUTHORING_CONTEXT,
  PLAN_CONTEXT_TYPE,
  planAuthoringContextContent,
} from "../../authoring/plan/prose.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { soundPointer } from "../../session/workflowSession.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import type { SessionArtifactCtx, SessionDataCtx } from "../../substrate/sessionData.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import { readSessionPointers } from "../../substrate/sessionPointers.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import type { BranchEntry, EntrySink } from "../../substrate/workflowState.ts";
import { rebuildWorkflowState, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import type { ReportTarget } from "../../surfaces/report.ts";
import {
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../testing/harness.ts";
import { approvalSave, decodePlanDraftParams, decodePlanSaveParams } from "./plan.ts";
import { implementHereGuidance } from "./planReview.ts";

/** Plant a draft artifact (file + verified pointer) through the branch session seam. */
function writeSessionArtifact(
  sink: EntrySink,
  ctx: SessionArtifactCtx,
  name: string,
  content: string,
): string | null {
  const result = openBranchWorkflowSession(sink, ctx).writeArtifact(name, content);
  return result.status === "applied" || result.status === "unchanged"
    ? join(ctx.cwd, result.receipt.path)
    : null;
}

const PLAN_MD = "# Add retry\n\n## Summary\nAdd retry to the gateway.\n";
const DRAFT_MD = "# Draft plan\n\n## Summary\nThe validated working draft.\n";

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

// ------------------------------------------------------------- the plan-authoring prose units

test("planAuthoringContextContent: carries the gather-then-plan contract; appends the addendum", () => {
  const base = planAuthoringContextContent(undefined);
  assert.equal(base, PLAN_AUTHORING_CONTEXT);
  assert.match(base, /\[PLAN AUTHORING\]/);
  assert.match(base, /concrete discoveries/);
  assert.match(base, /never line numbers/);
  assert.match(base, /docs\/learned/);
  assert.match(base, /first stop/);
  assert.match(base, /house-style skill/);
  // The review-first ending — plan_review when decision-complete; /plan-save is the
  // manual failsafe when the review reports skipped/unavailable.
  assert.match(base, /plan_review/);
  assert.match(base, /plan_draft/);
  assert.match(base, /\/plan-save \(the manual failsafe\)/);
  // The implement-here outcome arm (the no-save exit, contracts.md §8.23).
  assert.match(base, /IMPLEMENT HERE → the human chose to implement without saving an issue/);
  assert.match(base, /edits only; leave git\s+gestures to the\s+user/);

  const withAddendum = planAuthoringContextContent("House rule: cite a file path per change.");
  assert.match(withAddendum, /House rule: cite a file path per change\./);
  assert.ok(withAddendum.startsWith(PLAN_AUTHORING_CONTEXT));
});

// ----------------------------------------------------------------------------------- plan mode

test("/plan round-trip: on -> read-only + write blocked + plan-context injected; off -> released", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  try {
    // Starts OFF: write allowed, no plan-context injected.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
    assert.equal(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
    );

    // /plan ON -> read-only mode, write blocked, plan-context injected.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "mode flips to read-only");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) => m.customType === PLAN_CONTEXT_TYPE && String(m.content).includes("[PLAN AUTHORING]"),
      ),
      "plan-authoring context injected while on",
    );

    // /plan OFF -> read-write, write allowed, plan-context stripped from context.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write", "mode flips back to read-write");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
    const stale = [
      { customType: PLAN_CONTEXT_TYPE, content: "[PLAN AUTHORING]\nstale" },
      { role: "user", content: "[PLAN AUTHORING] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "plan-context custom message stripped when off",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[PLAN AUTHORING]")),
      false,
      "plan-authoring marker stripped from user turns when off",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});

test("deferral: a foreign [providers] plan selection makes perk NOT register the plan surface", async () => {
  const cwd = scaffoldRepo();
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "tombell-plan"\n', "utf8");
  // Registration-time deferral resolves `process.cwd()` at install time (the production cwd IS
  // the repo Pi launches in). Point process.cwd() at the scaffold so the installer sees the
  // selection.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // Registration-time deferral: the `/plan` command is not registered at all.
    assert.equal(
      h.registeredCommands().includes("plan"),
      false,
      "perk does not register /plan under a foreign plan selection",
    );
    // The `--plan` flag is not registered either: setting it + reload does NOT flip read-only.
    h.setFlag("plan", true);
    await h.reload();
    assert.notEqual(
      h.workflowState().mode,
      "read-only",
      "--plan is inert (unregistered) under a foreign selection",
    );
    // ...and no plan-authoring context is injected (the before_agent_start handler is unregistered).
    assert.equal(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "no plan-context injected while deferred",
    );
  } finally {
    h.dispose();
    process.chdir(savedCwd);
  }
});

test("partial vacate: a plannotator-plan selection keeps /plan + injection but drops --plan", async () => {
  const cwd = scaffoldRepo();
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[providers]\nplan = "plannotator-plan"\n',
    "utf8",
  );
  // Registration-time branching resolves `process.cwd()` at install time — point it at the scaffold.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // Augment posture: perk's `/plan` command IS registered…
    assert.equal(
      h.registeredCommands().includes("plan"),
      true,
      "perk keeps /plan under the plannotator selection",
    );
    // …and the toggle + authoring injection still work end-to-end.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "/plan still flips read-only");
    assert.ok(
      (await h.emitBeforeAgentStart()).some((m) => m.customType === PLAN_CONTEXT_TYPE),
      "plan-authoring context still injected",
    );
    await h.invokeCommand("plan");
    // …but the `--plan` flag and the Ctrl+Alt+P shortcut are NOT registered (plannotator owns
    // them exclusively — duplicate flag/shortcut registration is the potentially-fatal collision).
    const runner = h.session.extensionRunner as unknown as {
      getFlags: () => Map<string, unknown>;
      getShortcuts: (kb: Record<string, unknown>) => Map<string, unknown>;
    };
    assert.equal(runner.getFlags().has("plan"), false, "--plan flag not registered");
    assert.equal(runner.getShortcuts({}).size, 0, "no perk shortcut registered");
    // Setting the (unregistered) flag + reload is inert.
    h.setFlag("plan", true);
    await h.reload();
    assert.notEqual(
      h.workflowState().mode,
      "read-only",
      "--plan is inert (unregistered) under the plannotator selection",
    );
  } finally {
    h.dispose();
    process.chdir(savedCwd);
  }
});

test("--plan cold start enters read-only on session_start", async () => {
  const cwd = scaffoldRepo();
  // Registration-time branching resolves `process.cwd()` at install time — point it at the
  // scaffold so the host repo's committed [providers] selection cannot vacate --plan.
  const savedCwd = process.cwd();
  process.chdir(cwd);
  // Unset PERK_RUN_ID so session_start takes the warm-mint "none" path (ad-hoc `pi --plan`).
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined },
    sessionManager: SessionManager.inMemory(cwd),
  });
  try {
    // No flag -> read-write by default (no mode entry, gate off).
    assert.notEqual(h.workflowState().mode, "read-only", "default is not read-only");

    // Simulate `pi --plan`: set the flag, then reload to re-fire session_start.
    h.setFlag("plan", true);
    await h.reload();
    assert.equal(h.workflowState().mode, "read-only", "--plan enters read-only on session_start");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
  } finally {
    h.dispose();
    process.chdir(savedCwd);
  }
});

// ---------------------------------------------- registration parity (frozen baseline pins)

// The frozen registration baselines — BYTE-EXACT literals carried from the deleted factory
// registrations (extension/factories/planDraft.ts / planSave.ts / planReview.ts / planMode.ts /
// implementHere.ts at the pre-migration head). Deliberately literal in the test (never imported
// constants): metadata drift in the prose constants or the installer must fail here.
const BASELINE_PLAN_DRAFT = {
  name: "plan_draft",
  label: "Plan draft",
  description:
    "Write (or overwrite) the working plan draft to the session data dir and record its " +
    "provenance pointer. The only sanctioned write surface while read-only. NOT a save — " +
    "plan_save//plan-save still persist the plan to GitHub.",
  parameters: {
    type: "object",
    additionalProperties: false,
    required: ["plan"],
    properties: {
      plan: {
        type: "string",
        description: "The full working-plan markdown (rewrites the whole draft).",
      },
    },
  },
  promptSnippet: "Persist the working plan draft to the session data dir (full rewrite)",
  promptGuidelines: [
    "Call plan_draft to persist the current working draft as you author or revise the plan; pass the FULL plan markdown each time (it rewrites the whole draft).",
    "plan_draft never saves to GitHub and never ends the turn — plan_save//plan-save remain the canonical save surface.",
  ],
  executionMode: "sequential",
};

const BASELINE_PLAN_SAVE = {
  name: "plan_save",
  label: "Save plan",
  description:
    "Persist the current plan to GitHub as the canonical perk plan and link this session to it. " +
    "Terminating: ends the turn on save. Call only when the plan is decision-complete.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      plan: {
        type: "string",
        description:
          "Optional — the validated plan-draft.md artifact is preferred when present; this " +
          "param is the fallback for sessions that never wrote a draft (no line-number " +
          "references).",
      },
      title: {
        type: "string",
        description: "Optional issue title (defaults to the plan's first heading).",
      },
      objective_id: {
        type: "string",
        description:
          "Optional objective issue number to link this plan to (the objective plan factory " +
          "passes the active objective; omit for a standalone plan).",
      },
      node_id: {
        type: "string",
        description:
          "Objective node id to commit on save — the objective plan factory passes it with " +
          "`objective_id` (links the node and advances it to `in_progress`); omit for a " +
          "standalone plan.",
      },
      consumed_learn: {
        type: "array",
        items: { type: ["string", "number"] },
        description:
          "Optional perk:learn issue ids this docs plan consumes (the learned-docs factory " +
          "passes the gathered ids; omit for a standalone plan). /land closes + labels them.",
      },
    },
  },
  promptSnippet: "Save the decision-complete plan to GitHub (terminates the turn)",
  promptGuidelines: [
    "Use plan_save only after the plan is decision-complete and the user has agreed; it creates the canonical GitHub plan and ends the turn.",
    "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_save saves; the `plan` parameter is only a fallback when no draft exists. Never reference line numbers — use durable anchors (function names, behavioral descriptions, structural locations).",
    "Pass plan_save's consumed_learn (the gathered perk:learn issue ids) only from the learned-docs factory — it links the issues the docs plan consolidates so /land closes + labels them.",
    "When saving an objective-factory plan, pass plan_save BOTH objective_id and node_id — this links the node to the plan and advances it planning → in_progress (no separate backlink call).",
  ],
  executionMode: "sequential",
};

const BASELINE_PLAN_REVIEW = {
  name: "plan_review",
  label: "Plan review",
  description:
    "Present the plan to the configured review surface — the Plannotator browser UI when " +
    "selected, otherwise perk's in-TUI editor review — and wait for the human decision. " +
    "Reviews the validated plan-draft artifact (keep it current with plan_draft); on approval " +
    "the plan is auto-saved and the turn terminates. On deny, revise per the returned " +
    "feedback, rewrite the draft with plan_draft, and call again. On the Plannotator surface " +
    "the human may first opt into a streamed reviewer wave — the call then returns immediately " +
    'with wave guidance (status "wave_launched") to follow in the same turn, and the browser ' +
    "decision routes back automatically. No-op skip when the session is headless or the " +
    "review is dismissed.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      plan: {
        type: "string",
        description:
          "Optional — the validated plan-draft.md artifact is preferred when present; this " +
          "param is the fallback for sessions that never wrote a draft.",
      },
    },
  },
  promptSnippet: "Request a human review of the working plan draft",
  promptGuidelines: [
    "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_review reviews AND auto-saves; the plan param is only a fallback when no draft exists.",
    "Call plan_review only when the plan is decision-complete.",
    "On a DENIED review, revise per the feedback, rewrite the draft with plan_draft, then call plan_review again.",
    "On an APPROVED plan_review, the plan is auto-saved and the turn ends — never re-dump the plan as a final message and never tell the user to run /plan-save; relay the save outcome instead.",
    "On a wave_launched result (the human opted into the reviewer wave), follow the returned guidance in the same turn — launch the wave and relay its findings; the human's browser decision routes back automatically, so never re-call plan_review while that browser review is open.",
    "If plan_review reports it was skipped or unavailable (headless, dismissed), fall back to presenting the complete plan; the human runs /plan-save (the manual failsafe).",
  ],
  executionMode: "sequential",
};

const BASELINE_PLAN_COMMAND = {
  name: "plan",
  description: "Toggle perk plan mode (read-only exploration + plan authoring).",
};

const BASELINE_PLAN_SAVE_COMMAND = {
  name: "plan-save",
  description:
    "Save the latest proposed plan to GitHub — the manual failsafe for the approval→save flow " +
    "(the read-only → read-write boundary).",
};

const BASELINE_IMPLEMENT_HERE_COMMAND = {
  name: "implement-here",
  description:
    "Exit plan mode WITHOUT saving an issue and implement the current plan draft in this " +
    "session (the human-owned lightweight path).",
};

test("registration parity: the plan surface metadata is byte-exact vs the frozen baseline", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.deepEqual(
      h.registeredTool("plan_draft"),
      BASELINE_PLAN_DRAFT,
      "the COMPLETE plan_draft registration surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(
      h.registeredTool("plan_save"),
      BASELINE_PLAN_SAVE,
      "the COMPLETE plan_save registration surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(
      h.registeredTool("plan_review"),
      BASELINE_PLAN_REVIEW,
      "the COMPLETE plan_review registration surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(h.registeredCommand("plan"), BASELINE_PLAN_COMMAND);
    assert.deepEqual(h.registeredCommand("plan-save"), BASELINE_PLAN_SAVE_COMMAND);
    assert.deepEqual(h.registeredCommand("implement-here"), BASELINE_IMPLEMENT_HERE_COMMAND);
  } finally {
    h.dispose();
  }
});

// -------------------------------------------------------------------------- plan_draft decode

test("decodePlanDraftParams: tri-state strict-fail shapes", () => {
  // absent plan decodes to empty string (the core owns invalid_input).
  assert.deepEqual(decodePlanDraftParams({}), { plan: "" });
  assert.equal(decodePlanDraftParams({ plan: 42 }), null);
  assert.equal(decodePlanDraftParams("plan"), null);
  assert.equal(decodePlanDraftParams(null), null);
  assert.equal(decodePlanDraftParams([PLAN_MD]), null);
  // extra keys are ignored (the schema owns additionalProperties).
  assert.deepEqual(decodePlanDraftParams({ plan: PLAN_MD, extra: 1 }), { plan: PLAN_MD });
});

// ---------------------------------------------------------- plan_draft (the harness surface)

test("harness: plan_draft succeeds while read-only; artifact + pointer land", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().mode, "read-only", "the gate is active");
    const result = await h.invokeTool("plan_draft", { plan: PLAN_MD });
    const details = result.details as {
      ok: boolean;
      name?: string;
      path?: string;
      digest?: string;
      bytes?: number;
      run_id?: string;
    };
    // The receipt→Pi mapping is pinned exactly: derived repo-relative path, proven digest,
    // byte count, run id, and the complete rendered line.
    const relPath = join(
      ".perk",
      "workflow",
      "scratch",
      "runs",
      "01RID",
      "data",
      PLAN_DRAFT_ARTIFACT,
    );
    assert.equal(details.ok, true);
    assert.equal(details.name, PLAN_DRAFT_ARTIFACT);
    assert.equal(details.path, relPath);
    assert.equal(details.digest, digestSessionData(PLAN_MD));
    assert.equal(details.bytes, Buffer.byteLength(PLAN_MD, "utf8"));
    assert.equal(details.run_id, "01RID");
    assert.equal(
      result.content[0]?.text,
      `Plan draft written → ${relPath} (${digestSessionData(PLAN_MD)})`,
    );

    const path = join(sessionDataDir(cwd, "01RID"), PLAN_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    assert.equal(readFileSync(path, "utf8"), PLAN_MD);
    const pointer = soundPointer(h.workflowState().session_artifacts?.[PLAN_DRAFT_ARTIFACT]);
    assert.equal(pointer?.digest, digestSessionData(PLAN_MD));
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("harness: plan_draft failure taxonomy — bad_input / invalid_input", async () => {
  // The no_identity → no_run_id arm is unreachable through the harness (session_start
  // warm-mints an identity); it is pinned by authoring/plan/draft.test.ts + the shared
  // session suite instead.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const mistyped = await h.invokeTool("plan_draft", { plan: 42 });
    assert.equal((mistyped.details as { error_type?: string }).error_type, "bad_input");
    const blank = await h.invokeTool("plan_draft", { plan: "   \n" });
    assert.equal((blank.details as { error_type?: string }).error_type, "invalid_input");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

// ------------------------------------------------------------ plan_save (the harness surface)

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
    assert.equal((h.workflowState().active_plan_ref as { pr_id?: string } | null)?.pr_id, "42");
  } finally {
    h.dispose();
  }
});

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

test("tool: plan_save records the planning/main session pointer (file-backed session)", async () => {
  // A file-backed keep session has a real session file → the save captures planning.main under
  // the run id, into the shared main checkout (cwd here, since scaffoldRepo is not a git repo).
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    { run_id: "01RID", pi_session_id: "planted-parent.jsonl", mode: "read-write" },
  ]);
  const bin = fakePerk(cwd, { stdout: PLAN_JSON });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const record = readSessionPointers(cwd, "01RID");
    assert.ok(record !== null, "a session-pointers record was written");
    assert.ok((record.planning.main?.session_file ?? "").length > 0);
    assert.equal(record.planning.main?.pi_session_id, "planted-parent.jsonl");
    // Self-keyed: a planning run fills only the planning slots.
    assert.equal(record.implementation.main, null);
    assert.equal(record.implementation.worker, null);
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

test("tool: plan_save carries plan_ref.base into active_plan_ref (parity)", async () => {
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
  // Lenient decode: a legacy cold-door payload whose plan_ref lacks `base` must still
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
  // Lenient decode: a non-string/non-null `base` is omitted (never a decode failure).
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

test("tool: plan_save threads the link/learn/title params into the perk argv", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", {
      plan: PLAN_MD,
      title: "Custom Title",
      objective_id: "7",
      node_id: "1.1",
      consumed_learn: [45, 50],
    });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    assert.equal(argv[argv.indexOf("--title") + 1], "Custom Title");
    assert.equal(argv[argv.indexOf("--objective-id") + 1], "7");
    assert.equal(argv[argv.indexOf("--node-id") + 1], "1.1");
    assert.equal(argv[argv.indexOf("--consumed-learn") + 1], "45,50");
  } finally {
    h.dispose();
  }
});

test("tool: plan_save omits every absent optional flag (incl. --title under the LLM gate)", async () => {
  // The harness sets PERK_NO_LLM=1 by default, so no model call fires and the cold door's
  // derive_title stays in control — proven by the absence of --title.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: PLAN_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("plan_save", { plan: PLAN_MD });
    const argv = readFileSync(argvFile, "utf8").trimEnd().split("\n");
    for (const flag of ["--title", "--objective-id", "--node-id", "--consumed-learn"]) {
      assert.ok(!argv.includes(flag), `a standalone plan omits ${flag}`);
    }
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
      planFile.includes(join(".perk", "workflow", "scratch", "runs", "01RID")),
      `plan staged under run scratch (got ${planFile})`,
    );
    // savePlan trims the plan before staging, hence the .trim() on the expectation.
    assert.equal(readFileSync(planFile, "utf8"), PLAN_MD.trim(), "the staged file holds the plan");
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
  // The envelope-aware regression: the Python plane prints a structured failure
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

test("tool: a legacy issue shape (number, no id) still saves — derived from plan_ref", async () => {
  // A version-skew incident regression: a version-skewed CLI emitting a different
  // `issue` sub-object shape must NOT fail a save that already succeeded — the rendered issue
  // id/url are derived from the strict plan_ref (byte-identical by construction in the cold door).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const legacy = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    issue: { number: 390, url: "https://gh/o/r/issues/390", existed: false }, // legacy shape
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

// --------------------------------------------------- file-first resolution (harness surface)

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

// --------------------------------------------------------------------- plan_save decode pins

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
  // plan absent decodes to undefined (resolvePlanSource owns the fallback chain).
  assert.equal(decodePlanSaveParams({})?.plan, undefined);
  assert.equal(decodePlanSaveParams(undefined), null);
  assert.equal(decodePlanSaveParams({ plan: 5 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", title: 5 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", objective_id: 7 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", node_id: 1.2 }), null);
  assert.equal(decodePlanSaveParams({ plan: "p", consumed_learn: "x" }), null);
  // mixed string/number ids are fine (coerced); a non-id element still strict-fails.
  assert.deepEqual(
    decodePlanSaveParams({ plan: "p", consumed_learn: [1, "ENG-2"] })?.consumed_learn,
    ["1", "ENG-2"],
  );
  assert.equal(decodePlanSaveParams({ plan: "p", consumed_learn: [true] }), null);
});

// ------------------------------------------------- warm node-link recovery (the claim carrier)

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

// --------------------------------------------------------------- /plan-save (severity + D1a)

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

// -------------------------------------------- the approvalSave orchestration seam (pure fakes)

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

function runIdEntry(runId: string): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: runId } };
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

test("approvalSave: an identity-less save omits --run-id; the save and linkage still land", async () => {
  // The real composition (planSaveDepsFor → coldDoorPlanBackend → the actual argv assembly)
  // over a branch with NO run_id: the identity-less arm must stay legal end to end — the argv
  // omits `--run-id` entirely (never `--run-id null`), the save succeeds, and the branch-backed
  // `active_plan_ref` linkage still appends (workflow-state ops are identity-independent).
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [];
      const argvs: string[][] = [];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_JSON, argvs });
      const ctx = reportableCtx(cwd, branch) as unknown as ExtensionContext;
      const gating = fakeGating(true);
      const outcome = await approvalSave(pi, ctx, gating, { reviewedPlan: "# Reviewed plan" });
      assert.equal(outcome.status, "saved");
      const argv = argvs[0] ?? [];
      assert.deepEqual(argv.slice(0, 3), ["plan", "save", "--json"]);
      assert.equal(argv.includes("--run-id"), false, "the identity-less argv omits --run-id");
      assert.equal(argv.includes("null"), false, "no stringified null rides the argv");
      const linked = rebuildWorkflowState(
        branch as Parameters<typeof rebuildWorkflowState>[0],
      ).active_plan_ref;
      assert.deepEqual(
        linked,
        {
          provider: "github",
          pr_id: "42",
          url: "https://gh/o/r/issues/42",
          labels: ["perk:plan"],
          objective_id: null,
          base: undefined,
        },
        "the identity-less save still links active_plan_ref on the branch",
      );
      assert.equal(gating.exits, 1, "the D1a gate exit still fires on the verified save");
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

test("approvalSave: a planted claim is recovered into the argv and cleared on success", async () => {
  await withNoLlm(async () => {
    const cwd = mkdtempSync(join(tmpdir(), "approval-save-test-"));
    try {
      const branch: unknown[] = [
        {
          type: "custom",
          customType: WORKFLOW_STATE_TYPE,
          data: { run_id: "RID", objective_node_claim: CLAIM },
        },
      ];
      const argvs: string[][] = [];
      const pi = fakeApprovalPi(branch, { stdout: PLAN_NODE_OK_JSON, argvs });
      const ctx = reportableCtx(cwd, branch);
      assert.ok(
        writeSessionArtifact(fakeSink(branch), ctx, PLAN_DRAFT_ARTIFACT, "# The draft\n"),
        "the draft artifact landed",
      );
      const gating = fakeGating(true);
      const outcome = await approvalSave(pi, ctx as unknown as ExtensionContext, gating);
      assert.equal(outcome.status, "saved");
      const argv = argvs[0] ?? [];
      assert.equal(argv[argv.indexOf("--objective-id") + 1], "115", "objective recovered");
      assert.equal(argv[argv.indexOf("--node-id") + 1], "1.2", "node recovered");
      const rebuilt = rebuildWorkflowState(branch as BranchEntry[]);
      assert.equal(rebuilt.objective_node_claim, null, "the claim was cleared");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});

// ------------------------------------------------------------------------------ /implement-here

test("implementHereGuidance: content pins (no-issue / no-commit / doors / draft-intact)", () => {
  const cwd = scaffoldRepo();
  const text = implementHereGuidance(cwd, {});
  assert.match(text, /IMPLEMENT HERE/);
  assert.match(text, /no plan issue was created and none will be/);
  assert.match(text, /Do NOT commit, branch, or push unless the user explicitly asks/);
  assert.match(text, /\/submit, \/land, \/learn\) do not apply/);
  assert.match(text, /\/plan-save can still create the canonical issue later/);
  assert.doesNotMatch(text, /implement THESE final bytes/, "no inlined plan by default");
});

test("implementHereGuidance: the edited variant inlines the final reviewed bytes", () => {
  const cwd = scaffoldRepo();
  const text = implementHereGuidance(cwd, { editedPlan: "# Final plan bytes\n" });
  assert.match(text, /The human edited the plan during review; implement THESE final bytes:/);
  assert.match(text, /# Final plan bytes/);
});

test("/implement-here: gate on -> gate exited (no save) + the guidance injected", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  const injected = spyInjections(h);
  try {
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "plan mode on");
    await h.runCommandHandler("implement-here", "");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited");
    assert.ok(
      h.notifies.some((n) => n.includes("plan mode off — implementing here; no issue saved")),
      "the exit was reported",
    );
    assert.ok(
      injected.some(
        (m) => m.includes("IMPLEMENT HERE") && m.includes("Do NOT commit, branch, or push"),
      ),
      "the implement-now guidance was injected",
    );
  } finally {
    h.dispose();
  }
});

test("/implement-here: gate off -> warning, gate untouched, nothing injected", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("implement-here", "");
    assert.ok(
      h.notifies.some((n) => n.includes("not in plan mode — nothing to exit")),
      "warned that there is nothing to exit",
    );
    assert.notEqual(h.workflowState().mode, "read-only", "no gate transition");
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/implement-here: a COLD objective-plan claim refuses (handoff-persisted node link)", async () => {
  // The cold-claim channel: the objective-plan cold door's handoff_extra (objective_id/node_id)
  // persists the objective_node_claim at session_start, so the no-save exit refuses in cold
  // factory sessions too — with a positioned predecessor-checkout cwd it would otherwise edit
  // the published predecessor checkout.
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "objective-plan",
      extra: { objective_id: "7", node_id: "2.3" },
    },
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    assert.deepEqual(h.workflowState().objective_node_claim, { objective: "7", node: "2.3" });
    await h.runCommandHandler("implement-here", "");
    assert.ok(
      h.notifies.some((n) => n.includes("objective-node planning session")),
      "refused with the objective carve-out",
    );
    assert.equal(h.workflowState().mode, "read-only", "the gate stays on");
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/implement-here: a seeded node claim refuses; gate stays on, nothing injected", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      mode: "read-only",
      objective_node_claim: { objective: "115", node: "1.2" },
    },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  const injected = spyInjections(h);
  try {
    assert.equal(h.workflowState().mode, "read-only", "the planted gate is on");
    await h.runCommandHandler("implement-here", "");
    assert.ok(
      h.notifies.some((n) => n.includes("objective-node planning session")),
      "refused with the objective carve-out",
    );
    assert.equal(h.workflowState().mode, "read-only", "the gate stays on");
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});
