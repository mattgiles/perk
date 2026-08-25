// The v1 gist installer + injected review arm, tested at the Pi boundary: registration parity
// (metadata pins carried from the deleted factory tests), the tool-boundary decode, harness
// paths under the read-only gate, the /gist-save artifact-first command, the gist-authoring
// hook pair (incl. the post-compaction re-injection the active-window escalation buys), and
// result-byte parity for every review-arm outcome (carried from planReviewGist.test.ts).

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { GIST_DRAFT_ARTIFACT, GIST_SCOPES } from "../../authoring/gist/draft.ts";
import {
  GIST_AUTHOR_CONTEXT_TYPE,
  GIST_DRAFT_TOOL_GUIDELINES,
  GIST_SAVE_TOOL_GUIDELINES,
} from "../../authoring/gist/prose.ts";
import { PLAN_CONTEXT_TYPE } from "../../authoring/plan/prose.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import {
  digestSessionData,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type EntrySink, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import type { ReportTarget } from "../../surfaces/report.ts";
import {
  fakePerk,
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../testing/harness.ts";
import {
  decodeGistSaveParams,
  gistSaveGuidance,
  installGistBindings,
  runGistReviewV1,
} from "./gist.ts";
import type { PlanReviewUI, ReviewOutcome } from "./review.ts";

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

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

// --- decode (shared between gist_draft and gist_save) ----------------------------------------

test("decodeGistSaveParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeGistSaveParams({ prose: "p", scope: "objective" }), {
    prose: "p",
    title: undefined,
    scope: "objective",
  });
  // prose absent decodes to "" (saveGist's invalid_input arm keeps owning that message).
  assert.equal(decodeGistSaveParams({})?.prose, "");
  assert.equal(decodeGistSaveParams(undefined), null);
  assert.equal(decodeGistSaveParams({ prose: 5 }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", title: 5 }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", scope: 5 }), null);
});

test("decodeGistSaveParams: a present scope outside the enum strict-fails", () => {
  assert.equal(decodeGistSaveParams({ prose: "p", scope: "banana" }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", scope: "plan" })?.scope, "plan");
  assert.equal(decodeGistSaveParams({ prose: "p" })?.scope, undefined);
});

// --- registration parity (the baseline-exact metadata pins) -----------------------------------

// The frozen registration baseline — BYTE-EXACT literals carried from the deleted factory
// registrations (extension/factories/gistDraft.ts / gistSave.ts at the pre-migration head).
// Deliberately literal in the test (never imported constants): metadata drift in the prose
// constants or the installer must fail here.
const BASELINE_PARAMETERS = {
  type: "object",
  additionalProperties: false,
  required: ["prose"],
  properties: {
    prose: {
      type: "string",
      description:
        "The gist prose (the problem-space intent: what we want, why it matters, what " +
        "bounds it, and any high-level solution leanings — no implementation steps).",
    },
    title: {
      type: "string",
      description: "Optional gist title (defaults to the prose's first heading).",
    },
    scope: {
      type: "string",
      enum: ["plan", "objective"],
      description:
        "Optional consumption tier: plan (plan-sized intent) or objective (objective-sized).",
    },
  },
};

const BASELINE_GIST_DRAFT = {
  name: "gist_draft",
  label: "Gist draft",
  description:
    "Write (or overwrite) the working gist draft — the statement-of-intent prose + an " +
    "optional scope hint — to the session data dir and record its provenance pointer. The " +
    "only sanctioned write surface while read-only. NOT a save — gist_save//gist-save still " +
    "persist the gist to the issue backend.",
  parameters: BASELINE_PARAMETERS,
  promptSnippet:
    "Persist the working gist draft (statement-of-intent prose) to the session data dir (full rewrite)",
  promptGuidelines: [
    "Call gist_draft to persist the current working gist as you author or revise it; pass the FULL prose each time (it rewrites the whole draft).",
    "gist_draft never saves to the issue backend and never ends the turn — gist_save//gist-save remain the canonical save surface.",
    "Pass gist_draft's `scope` only once the consumption tier is settled: `plan` for plan-sized intent, `objective` for objective-sized intent.",
  ],
  executionMode: "sequential",
};

const BASELINE_GIST_SAVE = {
  name: "gist_save",
  label: "Save gist",
  description:
    "Persist a drafted gist (a statement of intent) to the issue backend as a tracked " +
    "perk:gist. Terminating: ends the turn on save. Call only when the gist says what it " +
    "means.",
  parameters: BASELINE_PARAMETERS,
  promptSnippet: "Save the converged gist to the issue backend (terminates the turn)",
  promptGuidelines: [
    "Use gist_save only after the gist says what it means; it creates the tracked gist in the issue backend and ends the turn.",
    "Pass gist_save the statement-of-intent PROSE in `prose` — problem-focused, with at most high-level solution leanings; no implementation steps or roadmap.",
    "Pass gist_save's `scope` only once the consumption tier is settled (plan or objective); omit it to keep the pre-seeded/default scope.",
  ],
  executionMode: "sequential",
};

const BASELINE_GIST_SAVE_COMMAND = {
  name: "gist-save",
  description:
    "Save the working gist draft to the issue backend — the manual failsafe for the " +
    "approval→save flow (artifact-first; drives the save only when no draft exists).",
};

test("registration parity: gist_draft + gist_save + /gist-save metadata is byte-exact vs the frozen baseline", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.deepEqual(
      h.registeredTool("gist_draft"),
      BASELINE_GIST_DRAFT,
      "the COMPLETE gist_draft registration surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(
      h.registeredTool("gist_save"),
      BASELINE_GIST_SAVE,
      "the COMPLETE gist_save registration surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(
      h.registeredCommand("gist-save"),
      BASELINE_GIST_SAVE_COMMAND,
      "the /gist-save command surface must match the frozen baseline byte-exactly",
    );
    // The live constants still feed the registration (a second, independent equality: if the
    // installer stopped consuming the prose module, this catches the decoupling).
    assert.deepEqual(BASELINE_GIST_DRAFT.promptGuidelines, GIST_DRAFT_TOOL_GUIDELINES);
    assert.deepEqual(BASELINE_GIST_SAVE.promptGuidelines, GIST_SAVE_TOOL_GUIDELINES);
    assert.deepEqual(BASELINE_PARAMETERS.properties.scope.enum, [...GIST_SCOPES]);
  } finally {
    h.dispose();
  }
});

// --- the gist_draft tool under the read-only gate ---------------------------------------------

test("harness: gist_draft succeeds while read-only; artifact + pointer land", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().mode, "read-only", "the gate is active");
    const result = await h.invokeTool("gist_draft", { prose: PROSE, scope: "plan" });
    const details = result.details as {
      ok: boolean;
      name?: string;
      path?: string;
      digest?: string;
      bytes?: number;
      run_id?: string;
    };
    assert.equal(details.ok, true);
    assert.equal(details.run_id, "01RID");
    assert.equal(details.name, GIST_DRAFT_ARTIFACT);

    const path = join(sessionDataDir(cwd, "01RID"), GIST_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    const content = readFileSync(path, "utf8");
    assert.deepEqual(JSON.parse(content), { schema_version: 1, scope: "plan", prose: PROSE });
    assert.equal(details.digest, digestSessionData(content));
    assert.equal(details.bytes, Buffer.byteLength(content, "utf8"));
    assert.equal(
      details.path,
      join(".perk", "workflow", "scratch", "runs", "01RID", "data", GIST_DRAFT_ARTIFACT),
    );
    assert.match(String(result.content[0]?.text), /Gist draft written → /);
    assert.equal(result.terminate, undefined, "non-terminating by design");
    const pointer = h.workflowState().session_artifacts?.[GIST_DRAFT_ARTIFACT];
    assert.equal(pointer?.digest, digestSessionData(content));

    // A byte-identical rewrite renders the SAME success bytes (the interior short-circuit is
    // host-invisible).
    const again = await h.invokeTool("gist_draft", { prose: PROSE, scope: "plan" });
    assert.deepEqual(again.details, result.details, "identical rewrite → identical details");
    assert.deepEqual(again.content, result.content, "identical rewrite → identical text");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("harness: gist_draft mistyped params ⇒ bad_input; blank prose ⇒ invalid_input", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const bad = await h.invokeTool("gist_draft", { prose: PROSE, scope: "banana" });
    const badDetails = bad.details as { ok: boolean; error_type?: string };
    assert.equal(badDetails.ok, false);
    assert.equal(badDetails.error_type, "bad_input");

    const blank = await h.invokeTool("gist_draft", { prose: "  \n" });
    const blankDetails = blank.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(blankDetails.ok, false);
    assert.equal(blankDetails.error_type, "invalid_input");
    assert.equal(blankDetails.error, "no gist prose to write (pass the full working draft)");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the gist_save tool ------------------------------------------------------------------------

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

// --- the artifact-first /gist-save command ------------------------------------------------------

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

test("command: /gist-save with an explicit title overrides the draft title", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("gist_draft", { prose: PROSE, title: "Draft title" });
    await h.invokeCommand("gist-save", "Override title");
    const argv = readFileSync(argvFile, "utf8");
    assert.match(argv, /--title\nOverride title/, "the explicit /gist-save title wins");
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

// --- absent identity (the offline v1 bindings over an identity-less branch) --------------------
//
// The harness cannot reach this arm: a warm session with no identity MINTS a run_id at
// session_start, so `openSession` is always `opened` there. These cases install the REAL v1
// bindings on a capturing fake `pi` and invoke the captured execute/handler over a branch with
// no `run_id` — the production identity-less arms, exercised directly.

interface CapturedToolSpec {
  name: string;
  execute: (
    toolCallId: string,
    params: unknown,
    signal: undefined,
    onUpdate: undefined,
    ctx: unknown,
  ) => Promise<{ content: { text?: string }[]; details: Record<string, unknown> }>;
}

function installOffline(opts: { stdout: string; argvs: string[][]; sent: string[] }): {
  tools: Map<string, CapturedToolSpec>;
  commands: Map<string, (args: string, ctx: unknown) => Promise<void>>;
  gating: ReturnType<typeof fakeGating>;
} {
  const tools = new Map<string, CapturedToolSpec>();
  const commands = new Map<string, (args: string, ctx: unknown) => Promise<void>>();
  const gating = fakeGating(true);
  const pi = {
    on() {},
    registerTool(spec: CapturedToolSpec) {
      tools.set(spec.name, spec);
    },
    registerCommand(
      name: string,
      spec: { handler: (args: string, ctx: unknown) => Promise<void> },
    ) {
      commands.set(name, spec.handler);
    },
    sendUserMessage(text: string) {
      opts.sent.push(text);
    },
    appendEntry() {},
    async exec(_cmd: string, args: string[]) {
      opts.argvs.push(args);
      return { stdout: opts.stdout, stderr: "", code: 0, killed: false };
    },
  } as unknown as Parameters<typeof installGistBindings>[0];
  installGistBindings(pi, gating);
  return { tools, commands, gating };
}

test("absent identity: gist_draft refuses blank prose BEFORE missing identity (the adapter mapping)", async () => {
  const cwd = scaffoldRepo();
  const { tools } = installOffline({ stdout: CREATE_JSON, argvs: [], sent: [] });
  const draftTool = tools.get("gist_draft");
  assert.ok(draftTool, "gist_draft captured");
  const ctx = headfulCtx(cwd, []); // no workflow-state entry — no run_id

  const blank = await draftTool.execute("t1", { prose: "  \n" }, undefined, undefined, ctx);
  assert.equal(blank.details.ok, false);
  assert.equal(blank.details.error_type, "invalid_input", "blank prose wins the precedence");
  assert.equal(blank.details.error, "no gist prose to write (pass the full working draft)");

  const noIdentity = await draftTool.execute("t2", { prose: "# X" }, undefined, undefined, ctx);
  assert.equal(noIdentity.details.ok, false);
  assert.equal(noIdentity.details.error_type, "no_run_id", "the no_identity → no_run_id mapping");
  assert.equal(
    noIdentity.details.error,
    "session has no run_id — cannot write the gist-draft artifact",
  );
});

test("absent identity: gist_save still saves — the cold door argv simply omits --run-id", async () => {
  const cwd = scaffoldRepo();
  const argvs: string[][] = [];
  const { tools } = installOffline({ stdout: CREATE_JSON, argvs, sent: [] });
  const saveTool = tools.get("gist_save");
  assert.ok(saveTool, "gist_save captured");
  const result = await saveTool.execute(
    "t1",
    { prose: PROSE },
    undefined,
    undefined,
    headfulCtx(cwd, []),
  );
  assert.equal(result.details.ok, true, "an identity-less save keeps working");
  assert.equal(argvs.length, 1, "the cold door ran once");
  assert.equal(argvs[0]?.includes("--run-id"), false, "no --run-id without identity");
});

test("absent identity: /gist-save falls to the drive fallback (openSession absent)", async () => {
  const cwd = scaffoldRepo();
  const argvs: string[][] = [];
  const sent: string[] = [];
  const { commands, gating } = installOffline({ stdout: CREATE_JSON, argvs, sent });
  const handler = commands.get("gist-save");
  assert.ok(handler, "/gist-save captured");
  await handler("Driven title", headfulCtx(cwd, []));
  assert.equal(argvs.length, 0, "no cold-door save was attempted (no session to re-read)");
  assert.equal(gating.exits, 1, "the gate exits for the driven turn");
  assert.equal(sent.length, 1, "exactly one drive injection");
  assert.match(String(sent[0]), /gist_save/);
  assert.match(String(sent[0]), /title: "Driven title"/, "the title override rides the drive");
});

// --- pure helpers -------------------------------------------------------------------------------

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

// --- the gist-authoring hook pair ---------------------------------------------------------------

const ADDENDUM_TOML = '[workflow]\nplan_authoring = "House rule: cite a file path per change."\n';

function writeAddendumConfig(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), ADDENDUM_TOML, "utf8");
}

test("gist-author session injects gist-authoring context; planMode defers", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "gist-author" },
  });
  writeAddendumConfig(cwd);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal(h.workflowState().stage, "gist-author", "stage recorded at claim");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === GIST_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("[GIST AUTHORING]"),
      ),
      "gist-authoring context injected",
    );
    assert.ok(
      injected.some(
        (m) =>
          m.customType === GIST_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("House rule: cite a file path per change."),
      ),
      "the [workflow] plan_authoring addendum flows into the injected context per-event",
    );
    assert.equal(
      injected.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      false,
      "planMode defers — no plan-authoring context in a gist-author session",
    );
  } finally {
    h.dispose();
  }
});

test("gist-author context dedups against a prior copy in the LIVE window (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "gist-author" },
      },
    },
    {
      custom: {
        type: GIST_AUTHOR_CONTEXT_TYPE,
        data: { content: "[GIST AUTHORING]\nprior copy" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "gist-author");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "prior [GIST AUTHORING] copy in the live window → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("gist-author context RE-INJECTS when compaction drops the prior copy", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "gist-author" },
      },
    },
    {
      custom: {
        type: GIST_AUTHOR_CONTEXT_TYPE,
        data: { content: "[GIST AUTHORING]\nprior copy" },
      },
    },
    { assistant: "recent work that survives compaction" },
  ]);
  const sessionManager = SessionManager.open(file);
  const keptId = sessionManager.getEntries().at(-1)?.id;
  assert.ok(keptId !== undefined);
  sessionManager.appendCompaction(
    "summary quoting [GIST AUTHORING] is not a live copy",
    keptId,
    100,
  );
  const h = await loadPerkSession({ cwd, sessionManager, env: { PERK_RUN_ID: undefined } });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === GIST_AUTHOR_CONTEXT_TYPE &&
          String(m.content).includes("[GIST AUTHORING]"),
      ),
      "a copy outside the active compaction window must not suppress re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("gist-author context keeps dedup when compaction retains the prior copy", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "gist-author" },
      },
    },
    {
      custom: {
        type: GIST_AUTHOR_CONTEXT_TYPE,
        data: { content: "[GIST AUTHORING]\nprior copy" },
      },
    },
  ]);
  const sessionManager = SessionManager.open(file);
  const keptId = sessionManager.getEntries().at(-2)?.id ?? sessionManager.getEntries().at(-1)?.id;
  assert.ok(keptId !== undefined);
  // Keep from the workflow-state entry onward — the prior copy stays in the live window.
  sessionManager.appendCompaction("summary", keptId, 100);
  const h = await loadPerkSession({ cwd, sessionManager, env: { PERK_RUN_ID: undefined } });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "a live retained copy still dedups",
    );
  } finally {
    h.dispose();
  }
});

test("a normal plan read-only session injects plan context, not gist-authoring", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some((m) => m.customType === PLAN_CONTEXT_TYPE),
      "plan-authoring context injected for a plan session",
    );
    assert.equal(
      injected.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "no gist-authoring context outside a gist-author session",
    );
  } finally {
    h.dispose();
  }
});

test("gist-authoring marker is stripped from context when not authoring", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "gist-save" },
  });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const stale = [
      { customType: GIST_AUTHOR_CONTEXT_TYPE, content: "[GIST AUTHORING]\nstale" },
      { role: "user", content: "[GIST AUTHORING] leaked into a user turn" },
      { role: "user", content: "a normal message" },
    ];
    const surviving = await h.emitContext(stale);
    assert.equal(
      surviving.some((m) => m.customType === GIST_AUTHOR_CONTEXT_TYPE),
      false,
      "gist-author custom message stripped when not authoring",
    );
    assert.equal(
      surviving.some((m) => String(m.content).includes("[GIST AUTHORING]")),
      false,
      "marker stripped from user turns",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});

// --- the injected review arm (result-byte parity, carried from planReviewGist.test.ts) ---------

function selectPlanProvider(cwd: string, id: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[providers]\nplan = "${id}"\n`, "utf8");
}

/** A recording bridge: captures the reviewed bytes, returns the canned outcome. */
function cannedBridge(outcome: ReviewOutcome): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
  reviewed: string[];
} {
  const reviewed: string[] = [];
  return {
    reviewed,
    async review(plan: string) {
      reviewed.push(plan);
      return outcome;
    },
  };
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
function fakeColdDoorPi(
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

/** A recording first-party UI: scripted editor/select answers, captured prompts. */
function fakeUI(script: {
  editor?: (string | undefined)[];
  select?: (string | undefined)[];
}): PlanReviewUI & {
  editors: { title: string; prefill: string | undefined }[];
  selects: { title: string; options: string[] }[];
} {
  const editorAnswers = [...(script.editor ?? [])];
  const selectAnswers = [...(script.select ?? [])];
  const ui = {
    editors: [] as { title: string; prefill: string | undefined }[],
    selects: [] as { title: string; options: string[] }[],
    async editor(title: string, prefill?: string) {
      ui.editors.push({ title, prefill });
      return editorAnswers.shift();
    },
    async select(title: string, options: string[]) {
      ui.selects.push({ title, options });
      return selectAnswers.shift();
    },
  };
  return ui;
}

/** A headful `SessionDataCtx & ReportTarget` over a live branch array, with a scripted ui. */
function headfulCtx(
  cwd: string,
  branch: unknown[],
  ui: unknown = { notify() {} },
): SessionDataCtx & ReportTarget {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: true,
    ui: { notify() {}, ...(ui as object) },
  } as SessionDataCtx & ReportTarget;
}

function fakeSink(branch: unknown[]): EntrySink {
  return {
    appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
  };
}

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

const APPROVED: ReviewOutcome = { status: "completed", approved: true, reviewId: "rev-a" };
const DENIED: ReviewOutcome = {
  status: "completed",
  approved: false,
  reviewId: "rev-d",
  feedback: "needs work",
};

const GIST_APPROVE = "Approve — auto-save to GitHub";
const GIST_DENY = "Deny — send feedback for revision";
const GIST_SKIP = "Skip — decide later (manual /gist-save)";

const GIST_STATE = { run_id: "RID", mode: "read-only", stage: "gist-author" };

const GIST_PAYLOAD = `${JSON.stringify({
  schema_version: 1,
  title: "Faster reviews",
  scope: "plan",
  prose: "The intent and the why.\n",
})}\n`;

const GIST_JSON = CREATE_JSON;

/** Plant the gist-draft artifact (file + pointer) on a live branch. */
function plantGistDraft(
  ctx: SessionDataCtx & ReportTarget,
  branch: unknown[],
  content = GIST_PAYLOAD,
): string {
  const written = writeSessionArtifact(fakeSink(branch), ctx, GIST_DRAFT_ARTIFACT, content);
  assert.ok(written, "the gist draft artifact landed");
  return written;
}

test("gist arm: no draft -> skipped/no_gist_draft, no backend invoked", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  const bridge = cannedBridge(APPROVED);
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON });
  const result = await runGistReviewV1(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
  );
  const details = result.details as {
    ok?: boolean;
    status?: string;
    reason?: string;
    error_type?: string;
  };
  assert.equal(details.status, "skipped");
  assert.equal(details.reason, "no_gist_draft");
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "no_gist_draft");
  assert.equal(bridge.reviewed.length, 0, "the bridge was never invoked");
  assert.equal(ui.editors.length, 0, "no first-party dialog opened");
  assert.match(String(result.content[0]?.text), /write the working gist with gist_draft/);
});

test("gist arm: plannotator selected -> the bridge receives the RENDERED markdown", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const bridge = cannedBridge(DENIED);
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON });
  const result = await runGistReviewV1(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    bridge,
  );
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed once");
  const reviewed = String(bridge.reviewed[0]);
  assert.match(reviewed, /# Faster reviews/);
  assert.match(reviewed, /Scope: plan/);
  assert.match(reviewed, /The intent and the why\./);
  assert.doesNotMatch(reviewed, /schema_version/, "never raw JSON");
  assert.match(String(result.content[0]?.text), /gist DENIED/);
});

test("gist arm: ordinary plannotator approval (no Direct Edits) saves, exits the gate, terminates", async () => {
  // The control case for the Direct-Edits carve-out: an approval whose feedback does NOT open
  // with the Direct Edits heading must fall through to the gistApprovalSave seam — a broadened
  // carve-out condition would silently drop every browser-approved gist.
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const bridge = cannedBridge({
    status: "completed",
    approved: true,
    reviewId: "rev-ga",
    feedback: "Ship it — tighten the title later.",
  });
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const gating = fakeGating(true);
  const result = await runGistReviewV1(pi, ctx as unknown as ExtensionContext, gating, bridge);
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed the rendered draft");
  assert.equal(argvs.length, 1, "the gistApprovalSave seam was invoked once");
  assert.equal(argvs[0]?.[0], "gist");
  assert.equal(argvs[0]?.[1], "create");
  assert.equal(gating.exits, 1, "the gate was exited once (via the gistApprovalSave seam)");
  assert.equal(result.terminate, true, "a saved approval terminates the turn");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.saved, true);
  assert.equal(details.subject, "gist");
  assert.equal(details.approved, true);
  assert.match(String(result.content[0]?.text), /gist APPROVED by reviewer/);
});

test("gist arm: approved via the bridge + Direct Edits -> NO save, non-terminating revise round", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const directEditsFeedback = [
    "# Direct Edits",
    "",
    "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:",
    "",
    "```diff",
    "@@ -1,1 +1,1 @@",
    "-# Faster reviews",
    "+# Faster reviews (edited)",
    "```",
  ].join("\n");
  const bridge = cannedBridge({
    status: "completed",
    approved: true,
    reviewId: "rev-gde",
    feedback: directEditsFeedback,
  });
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const gating = fakeGating(true);
  const result = await runGistReviewV1(pi, ctx as unknown as ExtensionContext, gating, bridge);
  assert.equal(bridge.reviewed.length, 1, "the bridge reviewed the rendered draft");
  assert.equal(argvs.length, 0, "the gistApprovalSave seam was NEVER invoked");
  assert.equal(gating.exits, 0, "the gate stays read-only");
  assert.equal(result.terminate, undefined, "the revise round never terminates");
  assert.deepEqual(result.details, {
    ok: true,
    status: "revise",
    reason: "direct_edits",
    approved: true,
    feedback: directEditsFeedback,
    reviewId: "rev-gde",
    subject: "gist",
  });
  const text = String(result.content[0]?.text);
  assert.match(text, /gist APPROVED with direct browser edits/);
  assert.match(text, /nothing was saved/);
  assert.match(text, /`# <title>` heading hunk → title/, "the field-aware title mapping");
  assert.match(text, /`Scope:`\s+line hunk → scope/, "the field-aware scope mapping");
  assert.match(text, /prose hunks → prose/, "the field-aware prose mapping");
  assert.match(text, /call plan_review again to\s+confirm/);
  assert.match(text, /# Direct Edits/, "the FULL feedback (diff included) reaches the model");
});

test("gist arm: default selection -> first-party VIEW-ONLY, 3 verdicts; approval auto-saves the artifact", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({ editor: ["# Edited by the human\n"], select: [GIST_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  const drafted = plantGistDraft(ctx, branch);
  const bridge = cannedBridge(APPROVED);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const gating = fakeGating(true);
  const result = await runGistReviewV1(pi, ctx as unknown as ExtensionContext, gating, bridge);
  assert.equal(bridge.reviewed.length, 0, "the plannotator bridge was never invoked");
  assert.equal(ui.editors.length, 1, "the editor dialog opened once");
  assert.match(String(ui.editors[0]?.title), /Gist review \(view only/);
  assert.match(String(ui.editors[0]?.prefill), /# Faster reviews/, "the rendered draft shown");
  assert.deepEqual(
    ui.selects[0]?.options,
    [GIST_APPROVE, GIST_DENY, GIST_SKIP],
    "3 verdicts — implement-here is never offered on the gist path",
  );
  assert.equal(
    readFileSync(drafted, "utf8"),
    GIST_PAYLOAD,
    "view-only: the edited editor return is NEVER written back to the artifact",
  );
  // Approved wires into the gistApprovalSave seam: the artifact is the save source (never the
  // editor's view-only return, never the rendered markdown).
  assert.equal(result.terminate, true, "a saved approval terminates the turn");
  const argv = argvs[0] ?? [];
  assert.equal(argv[0], "gist");
  assert.equal(argv[1], "create");
  assert.equal(argv[argv.indexOf("--title") + 1], "Faster reviews", "the draft's title");
  assert.equal(argv[argv.indexOf("--scope") + 1], "plan", "the draft's scope");
  const bodyFile = argv[argv.indexOf("--body") + 1] ?? "";
  assert.equal(
    readFileSync(bodyFile, "utf8"),
    "The intent and the why.",
    "the artifact's prose was staged (saveGist trims) — not the editor return",
  );
  assert.equal(gating.exits, 1, "the gate was exited once (via the gistApprovalSave seam)");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal(details.subject, "gist");
  assert.equal(details.approved, true);
  assert.equal(details.edited, undefined, "edited never set on the gist path");
  assert.match(String(result.content[0]?.text), /gist APPROVED by reviewer/);
  assert.match(String(result.content[0]?.text), /Saved gist 7/);
  assert.match(
    String(result.content[0]?.text),
    /Consume with: perk plan from 7/,
    "the consumption hint rides the relayed save text",
  );
});

test("gist arm: approved but the cold door fails -> non-terminating, gate stays on, failsafe", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({ editor: ["# whatever was shown"], select: [GIST_APPROVE] });
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
  const pi = fakeColdDoorPi(branch, { stdout: FAIL_ENVELOPE, code: 1 });
  const gating = fakeGating(true);
  const result = await runGistReviewV1(
    pi,
    ctx as unknown as ExtensionContext,
    gating,
    cannedBridge(DENIED),
  );
  assert.equal(result.terminate, undefined, "a failed auto-save never terminates");
  assert.equal(gating.exits, 0, "the gate stays on");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal(details.subject, "gist");
  const text = String(result.content[0]?.text);
  assert.match(text, /gist APPROVED by reviewer, but the auto-save FAILED/);
  assert.match(text, /gh exploded/);
  assert.match(text, /\/gist-save \(the manual failsafe\)/);
});

test("gist arm: approved but the draft vanished before the save re-read -> the no-source shape", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  const drafted = plantGistDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const bridge = {
    reviewed: [] as string[],
    async review(plan: string): Promise<ReviewOutcome> {
      // The draft vanishes between the review read and the save-time re-read.
      bridge.reviewed.push(plan);
      rmSync(drafted);
      return { status: "completed", approved: true, reviewId: "rev-gone" };
    },
  };
  const quiet = console.error;
  console.error = () => {};
  let result: Awaited<ReturnType<typeof runGistReviewV1>>;
  try {
    result = await runGistReviewV1(
      pi,
      ctx as unknown as ExtensionContext,
      fakeGating(true),
      bridge,
    );
  } finally {
    console.error = quiet;
  }
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no gist draft resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "no gist draft resolved");
  assert.equal(details.save, null);
  assert.equal(argvs.length, 0, "the cold door was never invoked");
});

test("gist arm: denied + feedback -> gist_draft redirect, no save", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({
    editor: ["# whatever was shown", "say what bounds it"],
    select: [GIST_DENY],
  });
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
  const argvs: string[][] = [];
  const pi = fakeColdDoorPi(branch, { stdout: GIST_JSON, argvs });
  const result = await runGistReviewV1(
    pi,
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
  );
  const text = String(result.content[0]?.text);
  assert.match(text, /gist DENIED/);
  assert.match(text, /rewrite the working draft with gist_draft/);
  assert.match(text, /call plan_review again/);
  assert.match(text, /say what bounds it/);
  assert.equal(argvs.length, 0, "no save on a deny");
  assert.equal((result.details as { subject?: string }).subject, "gist");
});

test("gist arm: dismissed (Esc) -> the /gist-save manual-failsafe skip shape", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({ editor: [undefined] });
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
  const result = await runGistReviewV1(
    fakeColdDoorPi(branch, { stdout: GIST_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
  );
  assert.match(String(result.content[0]?.text), /\/gist-save \(the manual failsafe\)/);
  assert.deepEqual(result.details, {
    ok: true,
    status: "skipped",
    reason: "dismissed",
    subject: "gist",
  });
});

test("gist arm: unavailable bridge -> the WARNING shape with subject gist", async () => {
  const cwd = scaffoldRepo();
  selectPlanProvider(cwd, "plannotator-plan");
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ctx = headfulCtx(cwd, branch);
  plantGistDraft(ctx, branch);
  const quiet = console.error;
  console.error = () => {};
  let result: Awaited<ReturnType<typeof runGistReviewV1>>;
  try {
    result = await runGistReviewV1(
      fakeColdDoorPi(branch, { stdout: GIST_JSON }),
      ctx as unknown as ExtensionContext,
      fakeGating(true),
      cannedBridge({ status: "unavailable", warning: "no bus" }),
    );
  } finally {
    console.error = quiet;
  }
  assert.match(String(result.content[0]?.text), /WARNING: no bus/);
  assert.match(String(result.content[0]?.text), /Present the complete gist/);
  assert.deepEqual(result.details, {
    ok: false,
    error: "no bus",
    error_type: "unavailable",
    status: "unavailable",
    subject: "gist",
  });
});

test("gist arm: aborted turn -> the aborted shape", async () => {
  const cwd = scaffoldRepo();
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const ui = fakeUI({});
  const ctx = headfulCtx(cwd, branch, ui);
  plantGistDraft(ctx, branch);
  const controller = new AbortController();
  controller.abort();
  const result = await runGistReviewV1(
    fakeColdDoorPi(branch, { stdout: GIST_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
    controller.signal,
  );
  assert.match(String(result.content[0]?.text), /gist review aborted \(turn interrupted\)\./);
  assert.deepEqual(result.details, { ok: true, status: "aborted", subject: "gist" });
});

test("gist arm: headless -> the standard skipResult", async () => {
  const branch: unknown[] = [stateEntry(GIST_STATE)];
  const cwd = scaffoldRepo();
  const ctx = { ...headfulCtx(cwd, branch), hasUI: false };
  const result = await runGistReviewV1(
    fakeColdDoorPi(branch, { stdout: GIST_JSON }),
    ctx as unknown as ExtensionContext,
    fakeGating(true),
    cannedBridge(APPROVED),
  );
  const skipDetails = result.details as { ok?: boolean; status?: string };
  assert.equal(skipDetails.status, "skipped");
  assert.equal(skipDetails.ok, true, "the sanctioned fail-open skip is ok:true");
  assert.match(String(result.content[0]?.text), /no interactive review surface available/);
});
