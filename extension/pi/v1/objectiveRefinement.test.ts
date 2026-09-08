// The v1 refinement installer at the Pi boundary: the command/tool decodes, the warm admission
// table, registration surface pins, the `objective_refinement_draft` tool (wrong_stage outside
// refinement; context-bound writes inside), the warm `/objective-refine` entry over a scripted
// worker, the human `/objective-refinement-save` failsafe (the manual-save state table, exact
// draft bytes staged, manual labelling), the `plan_review` refinement arm (first-party), and
// the plan-graph surface refusals inside a refinement session. Real draft-review activation;
// scripted exec / UI; no network.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  GOLDEN_CONTEXT,
  GOLDEN_DIGEST,
  GOLDEN_RUN,
} from "../../authoring/refinement/context.test.ts";
import { REFINEMENT_CONTEXT_ARTIFACT } from "../../authoring/refinement/context.ts";
import {
  decodeRefinementDraft,
  REFINEMENT_DRAFT_ARTIFACT,
  reviseRefinementDraft,
} from "../../authoring/refinement/draft.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { soundPointer } from "../../session/workflowSession.ts";
import { runScratchDir, sessionDataDir } from "../../substrate/cache.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { scriptedDraftReviewBridge } from "../../testing/draftReview.ts";
import { gitInit, loadPerkSession, scaffoldRepo, spyInjections } from "../../testing/harness.ts";
import type { ReportWave } from "../../waves/reportWave.ts";
import { createDraftReviewSlot } from "./draftReview.ts";
import { installGistBindings } from "./gist.ts";
import { installObjectiveAuthoringBindings } from "./objectiveAuthoring.ts";
import { installObjectivePlanningBindings } from "./objectivePlanning.ts";
import {
  decideWarmRefinementAdmission,
  decodeRefinementDraftParams,
  installObjectiveRefinementBindings,
  parseRefineCommandArgs,
  runRefinementReviewV1,
} from "./objectiveRefinement.ts";
import { installPlanBindings } from "./plan.ts";
import type { ReviewOutcome, ToolResult } from "./review.ts";

const MARKDOWN = "## Refinement\n\nWhat 2.3 must deliver — and the seams as observed now.\n";
/** The refinement approval verdict label: names the Linear node comment, never GitHub. */
const APPROVE = "Approve — auto-save to Linear (the node's refinement comment)";

const SAVE_JSON = {
  success: true,
  error_type: null,
  comment_id: "cmt-10",
  carrier_url: "https://linear.app/x/issue/ENG-23",
  carrier_identifier: "ENG-23",
  objective_id: "proj-1",
  objective_run_id: "01OBJRUN",
  node_id: "2.3",
  body_digest: "e".repeat(64),
  source_digest: "757bd82dce52e08ff6debbe74ff83486a9aeebb07dbc5ae5b3e795a1f347b077",
  saved_at: "2026-09-07T12:30:00Z",
  authored_at: "2026-09-07T12:00:00Z",
};
const SAVE_FAIL = {
  success: false,
  error_type: "stale_refinement",
  message: "the node's refinement comment changed since the grounding read",
  comment_ids: ["cmt-9", "cmt-11"],
  write_attempted: false,
};
const CONTEXT_JSON = {
  success: true,
  error_type: null,
  context_json: GOLDEN_CONTEXT,
  context_digest: GOLDEN_DIGEST,
};

// ------------------------------------------------------------------------- pure decodes

test("parseRefineCommandArgs: positional + --node forms; every extra/duplicate/missing shape refuses", () => {
  assert.deepEqual(parseRefineCommandArgs(""), { ok: true, objective: null, node: null });
  assert.deepEqual(parseRefineCommandArgs(" #7 "), { ok: true, objective: "7", node: null });
  assert.deepEqual(parseRefineCommandArgs("ENG-7 --node 2.3"), {
    ok: true,
    objective: "ENG-7",
    node: "2.3",
  });
  assert.deepEqual(parseRefineCommandArgs("--node=2.3 7"), {
    ok: true,
    objective: "7",
    node: "2.3",
  });
  assert.deepEqual(parseRefineCommandArgs("--node 2.3"), {
    ok: true,
    objective: null,
    node: "2.3",
  });
  for (const bad of [
    "7 8",
    "--node",
    "--node=",
    "--node --node 2",
    "7 --node 1 --node 2",
    "--bogus",
    "#",
  ]) {
    const parsed = parseRefineCommandArgs(bad);
    assert.equal(parsed.ok, false, bad);
  }
});

test("decodeRefinementDraftParams: exactly { markdown: string }", () => {
  assert.deepEqual(decodeRefinementDraftParams({ markdown: "m" }), { markdown: "m" });
  for (const bad of [null, [], {}, { markdown: 1 }, { markdown: null }, "m"]) {
    assert.equal(decodeRefinementDraftParams(bad), null);
  }
});

test("decideWarmRefinementAdmission: the strict admission table", () => {
  const absent = { status: "absent" as const };
  const ok = decideWarmRefinementAdmission({ run_id: "01RID", active_objective: "7" }, absent);
  assert.deepEqual(ok, { ok: true, runId: "01RID", activeObjective: "7", alreadyRefining: false });
  const reentry = decideWarmRefinementAdmission(
    { run_id: "01RID", stage: "objective-refine" },
    absent,
  );
  assert.ok(reentry.ok && reentry.alreadyRefining && reentry.activeObjective === null);
  // Unbound authoring sessions (objective-author / gist-author / no stage) are admitted.
  for (const stage of ["objective-author", "gist-author", undefined]) {
    assert.equal(
      decideWarmRefinementAdmission({ run_id: "01RID", stage }, absent).ok,
      true,
      String(stage),
    );
  }
  const bad = (
    state: Record<string, unknown>,
    handoff: Parameters<typeof decideWarmRefinementAdmission>[1] = absent,
  ) => {
    const result = decideWarmRefinementAdmission(state as never, handoff);
    assert.ok(!result.ok, JSON.stringify(state));
    return result.code;
  };
  assert.equal(bad({}), "bad_state");
  assert.equal(bad({ run_id: "../x" }), "bad_state");
  assert.equal(bad({ run_id: "01RID", objective_node_claim: { objective: "7" } }), "bad_state");
  assert.equal(bad({ run_id: "01RID", active_plan_ref: { provider: "github" } }), "bad_state");
  assert.equal(bad({ run_id: "01RID", stage: 4 }), "bad_state");
  assert.equal(bad({ run_id: "01RID" }, { status: "unreadable" }), "bad_state");
  assert.equal(
    bad({ run_id: "01RID" }, { status: "present", handoff: { run_id: "01OTHER", consumed: true } }),
    "bad_state",
  );
  assert.equal(
    bad({ run_id: "01RID", objective_node_claim: { objective: "7", node: "1.1" } }),
    "bound_session",
  );
  assert.equal(
    bad({
      run_id: "01RID",
      active_plan_ref: {
        provider: "github",
        pr_id: "42",
        url: "u",
        labels: [],
        objective_id: null,
      },
    }),
    "bound_session",
  );
  for (const stage of [
    "plan",
    "objective-plan",
    "save",
    "implement",
    "submit",
    "address",
    "land",
    "learn",
  ]) {
    assert.equal(bad({ run_id: "01RID", stage }), "bound_session", stage);
    assert.equal(
      bad(
        { run_id: "01RID" },
        { status: "present", handoff: { run_id: "01RID", consumed: true, stage } },
      ),
      "bound_session",
      `handoff ${stage}`,
    );
  }
  for (const extra of [
    { objective_id: "7", node_id: "1.1" },
    { objective_id: "7" },
    { adopt_from: "12" },
  ]) {
    assert.equal(
      bad(
        { run_id: "01RID" },
        { status: "present", handoff: { run_id: "01RID", consumed: true, ...extra } },
      ),
      "bound_session",
      JSON.stringify(extra),
    );
  }
  // A clean refinement handoff (the cold door's own) is not plan-bearing.
  const cold = decideWarmRefinementAdmission(
    { run_id: "01RID", stage: "objective-refine" },
    {
      status: "present",
      handoff: {
        run_id: "01RID",
        consumed: true,
        stage: "objective-refine",
        objective_refinement: { context_digest: "sha256:x" },
      },
    },
  );
  assert.ok(cold.ok && cold.alreadyRefining);
});

// ------------------------------------------------------------------------- the fixture

type Tool = {
  name: string;
  execute(
    id: string,
    params: unknown,
    signal: undefined,
    update: undefined,
    ctx: ExtensionContext,
  ): Promise<ToolResult>;
};

/** A session fixture with a real draft-review slot over a scripted exec + UI. */
function fixture(
  opts: { stage?: string | null; runId?: string | null; grounded?: boolean; mode?: string } = {},
) {
  // `stage: null` = no stage at all (a bare warm session); undefined = the refinement default.
  const stage = opts.stage === undefined ? "objective-refine" : opts.stage;
  const runId = opts.runId === undefined ? GOLDEN_RUN : opts.runId;
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  const branch: BranchEntry[] = [
    {
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: {
        ...(runId === null ? {} : { run_id: runId }),
        ...(stage === null ? {} : { stage }),
        mode: opts.mode ?? "read-only",
      },
    },
  ];
  const tools = new Map<string, Tool>();
  const commands = new Map<string, (args: string, ctx: ExtensionContext) => Promise<void>>();
  const notices: { severity?: string; message: string }[] = [];
  const messages: string[] = [];
  const calls: string[][] = [];
  const routes: Record<string, { json: unknown; code?: number }> = {
    "objective refinement-save": { json: SAVE_JSON },
    "objective refine-context": { json: CONTEXT_JSON },
  };
  let verdict = "Skip — decide later (manual /objective-refinement-save)";
  let duringWait: (() => void | Promise<void>) | undefined;
  let idle = true;
  let exits = 0;
  let enters = 0;
  const synced: [string | undefined, string | undefined][] = [];
  const pi = {
    events: {
      emit() {
        assert.fail("first-party fixture must not emit transport requests");
      },
      on() {
        throw new Error("no transport");
      },
    },
    on() {},
    registerTool(tool: Tool) {
      tools.set(tool.name, tool);
    },
    registerCommand(
      name: string,
      spec: { handler: (args: string, ctx: ExtensionContext) => Promise<void> },
    ) {
      commands.set(name, spec.handler);
    },
    registerShortcut() {},
    registerFlag() {},
    appendEntry(customType: string, data: Record<string, unknown>) {
      branch.push({ type: "custom", customType, data });
    },
    sendUserMessage(text: string) {
      messages.push(text);
    },
    async exec(_cmd: string, args: string[]) {
      calls.push(args);
      const key = `${args[0]} ${args[1]}`;
      const route = routes[key];
      if (route === undefined)
        return { code: 2, stdout: "", stderr: `unexpected ${key}`, killed: false };
      return {
        code: route.code ?? 0,
        stdout: JSON.stringify(route.json),
        stderr: "",
        killed: false,
      };
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    isIdle: () => idle,
    sessionManager: { getBranch: () => branch, getSessionId: () => "refinement-session" },
    ui: {
      notify(message: string, severity?: string) {
        notices.push({ severity, message });
      },
      editor: async (_title: string, text: string) => text,
      select: async () => {
        // The verdict dialog IS the human wait: exclusion is released here, so a concurrent
        // writer scripted into `duringWait` acts exactly where a real one could.
        await duringWait?.();
        return verdict;
      },
    },
  } as unknown as ExtensionContext;
  const gating = {
    isActive: () =>
      (branch
        .map((e) => (e as { data?: { mode?: string } }).data?.mode)
        .filter(Boolean)
        .at(-1) ?? "read-only") === "read-only",
    exit() {
      exits++;
      branch.push({
        type: "custom",
        customType: WORKFLOW_STATE_TYPE,
        data: { mode: "read-write" },
      });
    },
    enter() {
      enters++;
      branch.push({ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { mode: "read-only" } });
    },
    syncFromState(mode: string | undefined, s: string | undefined) {
      synced.push([mode, s]);
    },
  } satisfies ToolGating;
  const reviews = createDraftReviewSlot(pi);
  const contextPolicy = { runnerChild: () => false };
  installPlanBindings(pi, gating, reviews, contextPolicy);
  installObjectiveAuthoringBindings(pi, gating, reviews, contextPolicy);
  installGistBindings(pi, gating, reviews, contextPolicy);
  installObjectivePlanningBindings(pi, gating, {} as ReportWave);
  installObjectiveRefinementBindings(pi, gating, reviews, contextPolicy);
  const session = openBranchWorkflowSession(pi, ctx);
  if (opts.grounded !== false && runId !== null) {
    const written = session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, GOLDEN_CONTEXT, {
      provenance: "strict",
    });
    assert.equal(written.status, "applied", "the golden context is grounded");
  }
  const invoke = async (name: string, params: unknown = {}) => {
    const tool = tools.get(name);
    assert.ok(tool, `registered ${name}`);
    return tool.execute("actual-tool-id", params, undefined, undefined, ctx);
  };
  const command = async (name: string, args = "") => {
    const handler = commands.get(name);
    assert.ok(handler, `registered /${name}`);
    await handler(args, ctx);
  };
  const draft = (markdown = MARKDOWN) => invoke("objective_refinement_draft", { markdown });
  return {
    cwd,
    pi,
    ctx,
    reviews,
    branch,
    session,
    gating,
    tools,
    commands,
    invoke,
    command,
    draft,
    calls,
    notices,
    messages,
    routes,
    synced,
    get exits() {
      return exits;
    },
    get enters() {
      return enters;
    },
    set verdict(value: string) {
      verdict = value;
    },
    set duringWait(value: (() => void | Promise<void>) | undefined) {
      duringWait = value;
    },
    set idle(value: boolean) {
      idle = value;
    },
    draftBytes: () =>
      readFileSync(join(sessionDataDir(cwd, GOLDEN_RUN), REFINEMENT_DRAFT_ARTIFACT), "utf8"),
    state: () => openBranchWorkflowSession(pi, ctx),
    dispose() {
      rmSync(cwd, { recursive: true, force: true });
    },
  };
}

const errorNotices = (f: ReturnType<typeof fixture>) =>
  f.notices.filter((n) => n.severity === "error").map((n) => n.message);
const warnNotices = (f: ReturnType<typeof fixture>) =>
  f.notices.filter((n) => n.severity === "warning").map((n) => n.message);

// ------------------------------------------------------------------------- registration

test("registration: exactly one model tool (objective_refinement_draft), two commands; NO objective_refinement_save", () => {
  const f = fixture();
  try {
    assert.ok(f.tools.has("objective_refinement_draft"));
    assert.equal(f.tools.has("objective_refinement_save"), false, "no model save twin");
    assert.ok(f.commands.has("objective-refine"));
    assert.ok(f.commands.has("objective-refinement-save"));
    const tool = f.tools.get("objective_refinement_draft") as Tool & {
      parameters: unknown;
      promptGuidelines: string[];
    };
    assert.deepEqual(tool.parameters, {
      type: "object",
      additionalProperties: false,
      required: ["markdown"],
      properties: {
        markdown: {
          type: "string",
          description:
            "The full refinement Markdown: what the node must deliver, the prerequisites that " +
            "do not exist yet, the code seams as observed at capture time, the risks, and the " +
            "assumptions a later real plan must re-verify.",
        },
      },
    });
    assert.equal(tool.promptGuidelines.length, 3);
  } finally {
    f.dispose();
  }
});

// ------------------------------------------------------------------------- the draft tool

test("objective_refinement_draft: writes the context-bound envelope; unchanged on identical bytes; classified refusals", async () => {
  const f = fixture();
  try {
    for (const params of [{}, { markdown: 1 }, null]) {
      const bad = await f.invoke("objective_refinement_draft", params);
      assert.equal((bad.details as { error_type?: string }).error_type, "bad_input");
    }
    const blank = await f.draft(" \n");
    assert.equal((blank.details as { error_type?: string }).error_type, "invalid_input");
    const written = await f.draft();
    const details = written.details as Record<string, unknown>;
    assert.equal(details.ok, true, JSON.stringify(details));
    assert.equal(details.name, REFINEMENT_DRAFT_ARTIFACT);
    assert.equal(details.run_id, GOLDEN_RUN);
    assert.equal(details.context_digest, GOLDEN_DIGEST);
    assert.equal(details.objective_id, "proj-1");
    assert.equal(details.node_id, "2.3");
    assert.equal(details.unchanged, false);
    const bytes = f.draftBytes();
    assert.equal(
      bytes,
      `${JSON.stringify({ schema_version: 1, run_id: GOLDEN_RUN, context_digest: GOLDEN_DIGEST, markdown: MARKDOWN })}\n`,
    );
    assert.equal(details.digest, digestSessionData(bytes));
    assert.match(String(written.content[0]?.text), /bound to objective proj-1 node 2\.3/);
    assert.equal(written.terminate, undefined);
    const again = await f.draft();
    assert.equal((again.details as { unchanged?: boolean }).unchanged, true);
    assert.equal(f.calls.length, 0, "the draft tool never invokes the cold door");
    assert.equal(f.exits, 0, "the draft tool never touches the gate");
  } finally {
    f.dispose();
  }
});

test("objective_refinement_draft: refuses outside a refinement session (wrong_stage) regardless of the gate; no context → refinement_context_missing", async () => {
  for (const [stage, mode] of [
    ["plan", "read-only"],
    ["objective-author", "read-only"],
    [null, "read-write"],
  ] as const) {
    const f = fixture({ stage, mode, grounded: false });
    try {
      const result = await f.draft();
      assert.equal(
        (result.details as { error_type?: string }).error_type,
        "wrong_stage",
        String(stage),
      );
      assert.equal(
        existsSync(join(sessionDataDir(f.cwd, GOLDEN_RUN), REFINEMENT_DRAFT_ARTIFACT)),
        false,
      );
    } finally {
      f.dispose();
    }
  }
  const ungrounded = fixture({ grounded: false });
  try {
    const result = await ungrounded.draft();
    assert.equal(
      (result.details as { error_type?: string }).error_type,
      "refinement_context_missing",
    );
  } finally {
    ungrounded.dispose();
  }
  const corrupt = fixture();
  try {
    writeFileSync(
      join(sessionDataDir(corrupt.cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT),
      "junk",
    );
    const result = await corrupt.draft();
    // The mutation boundary observes the corrupt subject artifact? No — the CONTEXT is not the
    // draft artifact; the feature's strict context resume refuses it.
    assert.equal(
      (result.details as { error_type?: string }).error_type,
      "refinement_context_invalid",
    );
  } finally {
    corrupt.dispose();
  }
  const noIdentity = fixture({ runId: null, grounded: false });
  try {
    const result = await noIdentity.draft();
    assert.equal((result.details as { error_type?: string }).error_type, "no_run_id");
  } finally {
    noIdentity.dispose();
  }
});

// ------------------------------------------------------------------------- refusals

test("plan-graph surfaces refuse inside a refinement session: tools → wrong_stage, commands → warning; nothing executed", async () => {
  const f = fixture();
  try {
    await f.draft();
    for (const [name, params] of [
      ["objective_node", { objective: "7", node: "1.1", status: "planning" }],
      ["plan_save", { plan: "# P\n", title: "T" }],
      ["objective_save", { prose: "P" }],
      ["gist_save", { prose: "G" }],
    ] as const) {
      const result = await f.invoke(name, params);
      const details = result.details as { ok?: boolean; error_type?: string; error?: string };
      assert.equal(details.ok, false, name);
      assert.equal(details.error_type, "wrong_stage", name);
      assert.match(String(details.error), /not available in an objective-refine session/);
    }
    for (const name of [
      "plan-save",
      "objective-save",
      "gist-save",
      "objective-plan",
      "implement-here",
    ]) {
      await f.command(name, name === "objective-plan" ? "7" : "");
      assert.ok(
        warnNotices(f).some((m) =>
          m.includes(`/${name} is not available in an objective-refine session`),
        ),
        `${name}: ${JSON.stringify(f.notices)}`,
      );
    }
    assert.equal(f.calls.length, 0, "no cold door was invoked by any refused surface");
    assert.equal(f.exits, 0, "the gate never exited");
    assert.equal(f.messages.length, 0, "nothing was driven");
    assert.equal(f.state().nodeClaim(), null);
  } finally {
    f.dispose();
  }
});

// ------------------------------------------------------------------------- the human failsafe

test("/objective-refinement-save: saves the EXACT draft bytes through the worker; labelled a manual human save; gate exits", async () => {
  const f = fixture();
  try {
    await f.draft();
    const bytes = f.draftBytes();
    await f.command("objective-refinement-save");
    assert.equal(f.calls.length, 1, JSON.stringify(f.calls));
    const argv = f.calls[0] as string[];
    assert.deepEqual(argv.slice(0, 5), [
      "objective",
      "refinement-save",
      "--run-id",
      GOLDEN_RUN,
      "--json",
    ]);
    assert.equal(argv[5], "--draft-file");
    const staged = readFileSync(argv[6] as string, "utf8");
    assert.equal(staged, bytes, "the staged file carries the exact draft artifact bytes");
    assert.equal(
      join(runScratchDir(f.cwd, GOLDEN_RUN), REFINEMENT_DRAFT_ARTIFACT),
      argv[6],
      "staged in run scratch",
    );
    const info = f.notices.find((n) => n.message.includes("manual human save"));
    assert.ok(info, JSON.stringify(f.notices));
    assert.match(info.message, /not a reviewer approval/);
    assert.match(
      info.message,
      /Saved refinement for objective proj-1 node 2\.3 → comment cmt-10 on ENG-23/,
    );
    assert.match(info.message, /ADVISORY content — not an executable plan — was saved/);
    assert.equal(info.message.includes("approved"), false, "never labelled as approval");
    assert.equal(f.exits, 1, "the gate exits only after the verified save");
    assert.equal(f.messages.length, 0, "the human save drives nothing");
    assert.equal(f.state().nodeClaim(), null);
    assert.equal(f.state().activeObjective(), null, "no objective activation");
  } finally {
    f.dispose();
  }
});

test("/objective-refinement-save: no args only; wrong_stage; busy; no draft / no context / refused draft stop without a worker call", async () => {
  const withArgs = fixture();
  try {
    await withArgs.draft();
    await withArgs.command("objective-refinement-save", "extra");
    assert.ok(warnNotices(withArgs).some((m) => m.includes("takes no arguments (invalid_input)")));
    withArgs.idle = false;
    await withArgs.command("objective-refinement-save");
    assert.ok(warnNotices(withArgs).some((m) => m.includes("(session_busy)")));
    assert.equal(withArgs.calls.length, 0);
    assert.equal(withArgs.exits, 0);
  } finally {
    withArgs.dispose();
  }
  const wrongStage = fixture({ stage: "plan" });
  try {
    await wrongStage.command("objective-refinement-save");
    assert.ok(warnNotices(wrongStage).some((m) => m.includes("(wrong_stage)")));
    assert.equal(wrongStage.calls.length, 0);
  } finally {
    wrongStage.dispose();
  }
  const noDraft = fixture();
  try {
    await noDraft.command("objective-refinement-save");
    assert.ok(errorNotices(noDraft).some((m) => m.includes("no working refinement draft")));
    assert.equal(noDraft.calls.length, 0);
    assert.equal(noDraft.exits, 0);
  } finally {
    noDraft.dispose();
  }
  const noContext = fixture({ grounded: false });
  try {
    noContext.session.writeArtifact(
      REFINEMENT_DRAFT_ARTIFACT,
      `${JSON.stringify({ schema_version: 1, run_id: GOLDEN_RUN, context_digest: GOLDEN_DIGEST, markdown: MARKDOWN })}\n`,
      { provenance: "strict" },
    );
    await noContext.command("objective-refinement-save");
    assert.ok(errorNotices(noContext).some((m) => m.includes("no refinement context")));
    assert.equal(noContext.calls.length, 0);
  } finally {
    noContext.dispose();
  }
  const mismatch = fixture();
  try {
    await mismatch.draft();
    // A re-prepared context (any byte change) turns the draft into rewrite evidence.
    mismatch.session.writeArtifact(
      REFINEMENT_CONTEXT_ARTIFACT,
      GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["w",'),
      {
        provenance: "strict",
      },
    );
    await mismatch.command("objective-refinement-save");
    assert.ok(
      errorNotices(mismatch).some((m) => m.includes("re-prepared") && m.includes("nothing saved")),
    );
    assert.equal(mismatch.calls.length, 0);
    assert.equal(mismatch.exits, 0);
  } finally {
    mismatch.dispose();
  }
});

test("/objective-refinement-save: a failed worker keeps the gate ON and relays the typed diagnostics", async () => {
  const f = fixture();
  try {
    f.routes["objective refinement-save"] = { json: SAVE_FAIL, code: 1 };
    await f.draft();
    await f.command("objective-refinement-save");
    assert.equal(f.calls.length, 1);
    const error = errorNotices(f).find((m) => m.includes("manual save FAILED"));
    assert.ok(error, JSON.stringify(f.notices));
    assert.match(error, /\(stale_refinement\)/);
    assert.match(error, /write_attempted=false; comment_ids=cmt-9,cmt-11/);
    assert.match(error, /read the node's comments back and reconcile/);
    assert.equal(error.includes("nothing saved"), false, "never claims nothing saved");
    assert.equal(f.exits, 0, "the gate stays on");
  } finally {
    f.dispose();
  }
});

test("/objective-refinement-save: the deliberate retry — a failed save latches automatic saves off, the manual command still runs the worker", async () => {
  const f = fixture();
  try {
    f.routes["objective refinement-save"] = { json: SAVE_FAIL, code: 1 };
    await f.draft();
    await f.command("objective-refinement-save");
    assert.equal(f.calls.length, 1, "the worker ran once");
    assert.deepEqual(f.reviews.unconfirmed()?.subject, "refinement", "the failed save latched");
    assert.match(String(f.reviews.unconfirmed()?.detail), /refinement comment changed/);
    // Automatic (approval-driven) saves are paused: a first-party approval refuses before the
    // worker, naming the run id and the manual command.
    f.verdict = APPROVE;
    const approved = await f.invoke("plan_review", {});
    assert.equal(approved.details.status, "refused", JSON.stringify(approved.details));
    assert.equal(approved.details.error_type, "save_unconfirmed");
    assert.match(String(approved.content[0]?.text), new RegExp(`run id ${GOLDEN_RUN}`));
    assert.match(
      String(approved.content[0]?.text),
      /\/objective-refinement-save \(the deliberate retry\)/,
    );
    assert.equal(f.calls.length, 1, "no worker call from the paused approval");
    // The manual command never consults the latch — it IS the retry.
    f.routes["objective refinement-save"] = { json: SAVE_JSON };
    await f.command("objective-refinement-save");
    assert.equal(f.calls.length, 2, "the manual retry ran the worker");
    assert.equal(f.exits, 1, "the gate exits on the verified manual save");
  } finally {
    f.dispose();
  }
});

// ------------------------------------------------------------------------- the plan_review arm

test("plan_review in a refinement session: no draft → no_refinement_draft; a well-typed plan param is ignored", async () => {
  const f = fixture();
  try {
    const result = await f.invoke("plan_review", { plan: "# An unrelated plan\n" });
    const details = result.details as Record<string, unknown>;
    assert.equal(details.reason, "no_refinement_draft");
    assert.equal(details.subject, "refinement");
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});

test("plan_review first-party approval saves the artifact bytes through the worker and terminates; deny/skip never save", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.verdict = APPROVE;
    const approved = await f.invoke("plan_review", {});
    const details = approved.details as Record<string, unknown>;
    assert.equal(details.ok, true, JSON.stringify(details));
    assert.equal(details.saved, true);
    assert.equal(details.subject, "refinement");
    assert.equal(approved.terminate, true);
    assert.match(String(approved.content[0]?.text), /refinement APPROVED by reviewer/);
    assert.match(
      String(approved.content[0]?.text),
      /ADVISORY content — not an executable plan — was saved/,
    );
    assert.equal(f.calls.length, 1);
    const argv = f.calls[0] as string[];
    assert.equal(
      readFileSync(argv[argv.indexOf("--draft-file") + 1] as string, "utf8"),
      f.draftBytes(),
    );
    assert.equal(f.exits, 1);
  } finally {
    f.dispose();
  }
  const denied = fixture();
  try {
    await denied.draft();
    denied.verdict = "Deny — send feedback for revision";
    const result = await denied.invoke("plan_review", {});
    const details = result.details as Record<string, unknown>;
    assert.equal(details.approved, false);
    assert.match(
      String(result.content[0]?.text),
      /rewrite the working draft with objective_refinement_draft/,
    );
    denied.verdict = "Skip — decide later (manual /objective-refinement-save)";
    const skipped = await denied.invoke("plan_review", {});
    assert.equal((skipped.details as { reason?: string }).reason, "dismissed");
    assert.match(
      String(skipped.content[0]?.text),
      /\/objective-refinement-save \(the manual failsafe\)/,
    );
    assert.equal(denied.calls.length, 0, "deny/skip never invoke the worker");
    assert.equal(denied.exits, 0);
  } finally {
    denied.dispose();
  }
});

test("plan_review first-party: an approval never saves a replacement — draft rewritten, context re-prepared, or binding changed during the human wait", async () => {
  // The draft rewritten through the sanctioned seam while the editor is open: the approval
  // was for the shown draft, so nothing is saved, the worker is never invoked, the gate stays ON.
  const rewritten = fixture();
  try {
    await rewritten.draft();
    const shown = rewritten.draftBytes();
    rewritten.verdict = APPROVE;
    rewritten.duringWait = async () => {
      const revised = reviseRefinementDraft(
        { markdown: "## Replacement written during the wait\n" },
        rewritten.state(),
      );
      assert.equal(revised.status, "revised");
    };
    const result = await rewritten.invoke("plan_review", {});
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, false, JSON.stringify(details));
    assert.equal(details.status, "stale");
    assert.equal(details.reason, "source_changed");
    assert.equal(details.changed, "draft");
    assert.equal(details.approved, true, "the human's verdict is reported, not rewritten");
    assert.match(String(result.content[0]?.text), /working draft was rewritten/);
    assert.match(String(result.content[0]?.text), /never transfers to a replacement/);
    assert.equal(result.terminate, undefined);
    assert.equal(rewritten.calls.length, 0, "the worker is never invoked");
    assert.equal(rewritten.exits, 0, "the gate stays ON");
    assert.notEqual(rewritten.draftBytes(), shown, "the replacement is the current draft");
    // The replacement reviewed on its own merits saves normally (a NEW approval).
    rewritten.duringWait = undefined;
    const fresh = await rewritten.invoke("plan_review", {});
    assert.equal((fresh.details as { saved?: boolean }).saved, true);
    assert.equal(rewritten.calls.length, 1);
    const argv = rewritten.calls[0] as string[];
    assert.equal(
      readFileSync(argv[argv.indexOf("--draft-file") + 1] as string, "utf8"),
      rewritten.draftBytes(),
    );
  } finally {
    rewritten.dispose();
  }

  // The grounding context re-prepared (a new pass) with the draft re-bound to it: the
  // first-party source is `editor` (no artifact compare), so the seam's own `reviewed` pair
  // check catches the moved context (pinned Pi-free in authoring/refinement/save.test.ts).
  const regrounded = fixture();
  try {
    await regrounded.draft();
    regrounded.verdict = APPROVE;
    regrounded.duringWait = () => {
      const session = regrounded.state();
      const written = session.writeArtifact(
        REFINEMENT_CONTEXT_ARTIFACT,
        GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["late",'),
        { provenance: "strict" },
      );
      assert.equal(written.status, "applied");
      assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, session).status, "revised");
    };
    const result = await regrounded.invoke("plan_review", {});
    const details = result.details as Record<string, unknown>;
    assert.equal(details.status, "stale", JSON.stringify(details));
    assert.equal(details.reason, "source_changed");
    assert.equal(details.changed, "context");
    assert.equal(regrounded.calls.length, 0);
    assert.equal(regrounded.exits, 0);
  } finally {
    regrounded.dispose();
  }

  // The save destination changed (the committed `[issues]` table rewritten during the wait)
  // while the pair is byte-identical: the destination fence refuses before the seam, naming
  // the moved components (never their values), with nothing saved.
  const rerouted = fixture();
  try {
    await rerouted.draft();
    rerouted.verdict = APPROVE;
    rerouted.duringWait = () => {
      mkdirSync(join(rerouted.cwd, ".perk"), { recursive: true });
      writeFileSync(join(rerouted.cwd, ".perk", "config.toml"), '[issues]\nbackend = "linear"\n');
    };
    const result = await rerouted.invoke("plan_review", {});
    const details = result.details as Record<string, unknown>;
    assert.equal(details.status, "destination-changed", JSON.stringify(details));
    assert.equal(details.subject, "refinement");
    // The backend flipped to Linear: `issues` moved and the GitHub-only `remotes` component vanished.
    assert.deepEqual(details.changed, ["issues", "remotes"]);
    assert.match(
      String(result.content[0]?.text),
      /save destination changed while the review was open \(changed: issues, remotes\)/,
    );
    assert.doesNotMatch(String(result.content[0]?.text), /linear/);
    assert.equal(rerouted.calls.length, 0);
    assert.equal(rerouted.exits, 0);
  } finally {
    rerouted.dispose();
  }

  // An unrelated config change during the wait (compaction/provider/comment edits, plus a
  // [workflow] base the refinement save never consumes) is not routing drift: the approval saves.
  const unrelated = fixture();
  try {
    await unrelated.draft();
    unrelated.verdict = APPROVE;
    unrelated.duringWait = () => {
      mkdirSync(join(unrelated.cwd, ".perk"), { recursive: true });
      writeFileSync(
        join(unrelated.cwd, ".perk", "config.toml"),
        '# edited during the wait\n[compaction]\nreserve_tokens = 65536\n[providers]\nplan = "perk-plan"\n[workflow]\nbase = "release"\n',
      );
    };
    const result = await unrelated.invoke("plan_review", {});
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, true, JSON.stringify(details));
    assert.equal(details.saved, true);
    assert.equal(unrelated.calls.length, 1);
    assert.equal(unrelated.exits, 1);
  } finally {
    unrelated.dispose();
  }

  // A denial during which the draft is rewritten is still just a denial (no save was at stake).
  const deniedLate = fixture();
  try {
    await deniedLate.draft();
    deniedLate.verdict = "Deny — send feedback for revision";
    deniedLate.duringWait = () => {
      assert.equal(
        reviseRefinementDraft({ markdown: "## Rewritten\n" }, deniedLate.state()).status,
        "revised",
      );
    };
    const result = await deniedLate.invoke("plan_review", {});
    assert.equal((result.details as { approved?: boolean }).approved, false);
    assert.equal(deniedLate.calls.length, 0);
  } finally {
    deniedLate.dispose();
  }
});

// ------------------------------------------------------------------------- the plannotator arm

/**
 * The plannotator refinement arm over the REAL draft-review activation (state, claims,
 * registration, capability fencing) with only the upstream browser verdict scripted: the bridge
 * opens + attaches a real registration, may act as a concurrent writer while the review is
 * pending (`duringReview`), then returns the scripted outcome — so `review.complete` runs the
 * genuine capability-fenced `completeRefinementReviewV1` → `boundRefinementSaveDeps` path.
 */
function plannotatorArm(
  outcome: ReviewOutcome,
  opts: { save?: { json: unknown; code?: number }; duringReview?: () => void } = {},
) {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const branch: BranchEntry[] = [
    {
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { run_id: GOLDEN_RUN, stage: "objective-refine", mode: "read-only" },
    },
  ];
  const calls: string[][] = [];
  const save = opts.save ?? { json: SAVE_JSON };
  const pi = {
    on() {},
    appendEntry(customType: string, data: Record<string, unknown>) {
      branch.push({ type: "custom", customType, data });
    },
    async exec(_cmd: string, args: string[]) {
      calls.push(args);
      return { code: save.code ?? 0, stdout: JSON.stringify(save.json), stderr: "", killed: false };
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    isIdle: () => true,
    sessionManager: {
      getBranch: () => branch,
      getSessionId: () => "plannotator-refinement",
      appendCustomEntry(customType: string, data: Record<string, unknown>) {
        branch.push({ type: "custom", customType, data });
      },
    },
    ui: {
      notify() {},
      editor: async () => assert.fail("the plannotator arm never opens the first-party editor"),
      select: async () => assert.fail("the plannotator arm never opens the first-party menu"),
    },
  } as unknown as ExtensionContext;
  let exits = 0;
  const gating = {
    isActive: () => exits === 0,
    exit() {
      exits++;
    },
    enter() {},
    syncFromState() {},
  } satisfies ToolGating;
  const session = openBranchWorkflowSession(pi, ctx);
  assert.equal(
    session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, GOLDEN_CONTEXT, { provenance: "strict" })
      .status,
    "applied",
  );
  assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, session).status, "revised");
  const scripted = scriptedDraftReviewBridge(outcome);
  const bridge = {
    ...scripted,
    async review(...args: Parameters<typeof scripted.review>): Promise<ReviewOutcome> {
      const result = await scripted.review(...args);
      // Attached and pending: the exact window in which a browser decision is outstanding.
      opts.duringReview?.();
      return result;
    },
  };
  const draftBytes = () =>
    readFileSync(join(sessionDataDir(cwd, GOLDEN_RUN), REFINEMENT_DRAFT_ARTIFACT), "utf8");
  const slot = createDraftReviewSlot(pi);
  return {
    cwd,
    session,
    calls,
    bridge,
    draftBytes,
    get exits() {
      return exits;
    },
    slot,
    run: () => runRefinementReviewV1(pi, ctx, gating, bridge, slot, undefined),
    dispose: () => rmSync(cwd, { recursive: true, force: true }),
  };
}

const DIRECT_EDITS = [
  "# Direct Edits",
  "",
  "The user edited the document directly. Apply these exact changes — a unified diff against the version you submitted:",
  "",
  "```diff",
  "@@ -1,1 +1,1 @@",
  "-## Refinement",
  "+## Refinement (edited)",
  "```",
].join("\n");

test("plannotator arm: a plain approval saves the EXACT reviewed draft bytes once through the worker, exits the gate, terminates", async () => {
  const arm = plannotatorArm({ status: "completed", approved: true, reviewId: "rev-ok" });
  try {
    const result = await arm.run();
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, true, JSON.stringify(details));
    assert.equal(details.saved, true);
    assert.equal(details.subject, "refinement");
    assert.equal(result.terminate, true);
    assert.equal(arm.bridge.reviewed.length, 1, "one review over the RENDERED pair");
    assert.match(String(arm.bridge.reviewed[0]), /^# Refinement — objective proj-1 · node 2\.3/);
    assert.doesNotMatch(String(arm.bridge.reviewed[0]), /schema_version/, "never raw JSON");
    assert.equal(arm.calls.length, 1, "exactly one worker invocation");
    const argv = arm.calls[0] as string[];
    assert.deepEqual(argv.slice(0, 2), ["objective", "refinement-save"]);
    assert.equal(
      readFileSync(argv[argv.indexOf("--draft-file") + 1] as string, "utf8"),
      arm.draftBytes(),
      "the staged bytes are the reviewed draft artifact, byte for byte",
    );
    assert.equal(argv[argv.indexOf("--run-id") + 1], GOLDEN_RUN);
    assert.equal(arm.exits, 1);
    assert.equal(arm.slot.unconfirmed(), null, "a confirmed save never latches");
  } finally {
    arm.dispose();
  }
});

test("plannotator arm: approval carrying Direct Edits is one revise round — no worker call, no gate exit, not terminating", async () => {
  const arm = plannotatorArm({
    status: "completed",
    approved: true,
    reviewId: "rev-de",
    feedback: DIRECT_EDITS,
  });
  try {
    const result = await arm.run();
    const details = result.details as Record<string, unknown>;
    assert.equal(details.status, "revise", JSON.stringify(details));
    assert.equal(details.reason, "direct_edits");
    assert.equal(details.approved, true);
    assert.equal(result.terminate, undefined);
    assert.match(String(result.content[0]?.text), /nothing was saved/);
    assert.match(String(result.content[0]?.text), /objective_refinement_draft rewrite/);
    assert.equal(arm.calls.length, 0);
    assert.equal(arm.exits, 0);
  } finally {
    arm.dispose();
  }
});

test("plannotator arm: a denial saves nothing and redirects to the draft tool", async () => {
  const arm = plannotatorArm({
    status: "completed",
    approved: false,
    reviewId: "rev-no",
    feedback: "too vague",
  });
  try {
    const result = await arm.run();
    assert.equal((result.details as { approved?: boolean }).approved, false);
    assert.match(String(result.content[0]?.text), /refinement DENIED/);
    assert.match(String(result.content[0]?.text), /objective_refinement_draft/);
    assert.equal(arm.calls.length, 0);
    assert.equal(arm.exits, 0);
  } finally {
    arm.dispose();
  }
});

test("plannotator arm: a draft rewritten while the review is pending blocks the late approval — stale-approval, worker never invoked", async () => {
  let arm: ReturnType<typeof plannotatorArm> | undefined;
  let shown = "";
  arm = plannotatorArm(
    { status: "completed", approved: true, reviewId: "rev-late" },
    {
      duringReview: () => {
        shown = (arm as NonNullable<typeof arm>).draftBytes();
        const revised = reviseRefinementDraft(
          { markdown: "## Replacement while pending\n" },
          arm?.session as NonNullable<typeof arm>["session"],
        );
        // The write lands; the reviewed-bytes guard refuses the approval at decision time.
        assert.equal(revised.status, "revised");
      },
    },
  );
  try {
    const result = await arm.run();
    const details = result.details as Record<string, unknown>;
    // The live draft no longer equals the reviewed bytes: the late approval saves nothing and
    // names the REVIEWED digest — never an approval of the current draft.
    assert.equal(details.status, "stale-approval", JSON.stringify(details));
    assert.equal(details.subject, "refinement");
    assert.equal(details.reviewed_digest, digestSessionData(shown));
    assert.notEqual(arm.draftBytes(), shown, "the replacement is current");
    assert.match(String(result.content[0]?.text), /working draft changed after the review opened/);
    assert.match(String(result.content[0]?.text), /Nothing was saved/);
    assert.equal(arm.calls.length, 0, "the worker is never invoked on a late approval");
    assert.equal(arm.exits, 0);
  } finally {
    arm.dispose();
  }
});

test("plannotator arm: a context re-prepared while the review is pending blocks the late approval — the context digest, worker never invoked", async () => {
  let arm: ReturnType<typeof plannotatorArm> | undefined;
  arm = plannotatorArm(
    { status: "completed", approved: true, reviewId: "rev-moved" },
    {
      duringReview: () => {
        const session = arm?.session as NonNullable<typeof arm>["session"];
        assert.equal(
          session.writeArtifact(
            REFINEMENT_CONTEXT_ARTIFACT,
            GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["late",'),
            { provenance: "strict" },
          ).status,
          "applied",
        );
        assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, session).status, "revised");
      },
    },
  );
  try {
    const result = await arm.run();
    const details = result.details as Record<string, unknown>;
    // The re-prepared context leaves the draft bytes identical; the reviewed-bytes guard also
    // compares the grounding context's digest for refinement, so the approval is stale.
    assert.equal(details.status, "stale-approval", JSON.stringify(details));
    assert.equal(details.subject, "refinement");
    assert.match(String(result.content[0]?.text), /Nothing was saved/);
    assert.equal(arm.calls.length, 0);
    assert.equal(arm.exits, 0);
  } finally {
    arm.dispose();
  }
});

test("plannotator arm: an unrelated TOML edit during the review leaves the approval saving once; a routing edit refuses naming its component", async () => {
  let arm: ReturnType<typeof plannotatorArm> | undefined;
  arm = plannotatorArm(
    { status: "completed", approved: true, reviewId: "rev-unrelated" },
    {
      duringReview: () => {
        const cwd = arm?.cwd as string;
        writeFileSync(
          join(cwd, ".perk", "config.toml"),
          '# rewritten during the review\n[compaction]\nreserve_tokens = 65536\n[providers]\nplan = "plannotator-plan"\n[workflow]\nbase = "release"\n',
        );
        // A refinement save does not consume [workflow] base: even that edit is invisible here.
      },
    },
  );
  try {
    const result = await arm.run();
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, true, JSON.stringify(details));
    assert.equal(details.saved, true);
    assert.equal(arm.calls.length, 1, "exactly one worker invocation");
    assert.equal(arm.exits, 1);
  } finally {
    arm.dispose();
  }
  let rerouted: ReturnType<typeof plannotatorArm> | undefined;
  rerouted = plannotatorArm(
    { status: "completed", approved: true, reviewId: "rev-rerouted" },
    {
      duringReview: () => {
        const cwd = rerouted?.cwd as string;
        writeFileSync(
          join(cwd, ".perk", "config.toml"),
          '[providers]\nplan = "plannotator-plan"\n[issues]\nbackend = "linear"\n',
        );
      },
    },
  );
  try {
    const result = await rerouted.run();
    const details = result.details as Record<string, unknown>;
    assert.equal(details.status, "destination-changed", JSON.stringify(details));
    assert.deepEqual(details.changed, ["issues", "remotes"]);
    assert.match(
      String(result.content[0]?.text),
      /save destination changed while the review was open \(changed: issues, remotes\)/,
    );
    assert.doesNotMatch(String(result.content[0]?.text), /linear/);
    assert.equal(rerouted.calls.length, 0);
    assert.equal(rerouted.exits, 0);
  } finally {
    rerouted.dispose();
  }
});

test("plannotator arm: a failed worker surfaces the feature's typed save failure, latches automatic saves off, gate stays ON", async () => {
  const arm = plannotatorArm(
    { status: "completed", approved: true, reviewId: "rev-fail" },
    { save: { json: SAVE_FAIL, code: 1 } },
  );
  try {
    const quiet = console.error;
    console.error = () => {};
    let result: ToolResult;
    try {
      result = await arm.run();
    } finally {
      console.error = quiet;
    }
    const details = result.details as Record<string, unknown>;
    assert.equal(details.ok, false, JSON.stringify(details));
    assert.equal(details.error_type, "save_failed");
    assert.equal(details.saved, false);
    assert.equal(result.terminate, undefined);
    // The worker's typed diagnostics ride the rendered save message.
    const save = details.save as Record<string, unknown>;
    assert.equal(save.write_attempted, false);
    assert.deepEqual(save.comment_ids, ["cmt-9", "cmt-11"]);
    const text = result.content.map((c) => c.text).join("\n");
    assert.match(text, /auto-save FAILED/);
    assert.match(text, /automatic saves are paused/);
    assert.match(text, /\/objective-refinement-save \(the deliberate retry\)/);
    assert.equal(arm.calls.length, 1, "one worker invocation, never replayed");
    assert.equal(arm.exits, 0, "the gate stays ON");
    assert.equal(arm.slot.unconfirmed()?.subject, "refinement", "the latch is set");
    // A second approval in the same activation is paused before the worker.
    const again = await arm.run();
    assert.equal(again.details.status, "refused", JSON.stringify(again.details));
    assert.equal(again.details.error_type, "save_unconfirmed");
    assert.equal(arm.calls.length, 1, "no further worker call");
  } finally {
    arm.dispose();
  }
});

// ------------------------------------------------------------------------- the warm entry

test("/objective-refine (warm): unbound session → worker context imported byte-exact, stage entered, gate scoped, guidance driven", async () => {
  const f = fixture({ stage: null, mode: "read-write", grounded: false });
  try {
    f.branch.push({
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { active_objective: "proj-1" },
    });
    await f.command("objective-refine", "--node 2.3");
    assert.equal(f.calls.length, 1, JSON.stringify(f.notices));
    assert.deepEqual(f.calls[0], [
      "objective",
      "refine-context",
      "proj-1",
      "--node",
      "2.3",
      "--run-id",
      GOLDEN_RUN,
      "--json",
    ]);
    const stored = readFileSync(
      join(sessionDataDir(f.cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT),
      "utf8",
    );
    assert.equal(stored, GOLDEN_CONTEXT, "the worker's context string landed unchanged");
    const context = f.state().draftReviewContext();
    assert.ok(context.ok && context.subject === "refinement", "the stage entered");
    assert.equal(f.state().activeObjective(), "proj-1", "active_objective preserved");
    assert.equal(f.state().nodeClaim(), null, "no claim");
    assert.equal(f.enters, 1, "the gate entered");
    assert.deepEqual(
      f.synced.at(-1),
      ["read-only", "objective-refine"],
      "the gate re-scoped to the stage",
    );
    assert.equal(f.messages.length, 1, "one driven turn");
    assert.match(String(f.messages[0]), /perk objective refine flow/);
    assert.match(String(f.messages[0]), /Objective #proj-1: Objective “Ship it” 🚢/);
    assert.match(String(f.messages[0]), /re-refining/, "the prior note rides the seed");
    assert.match(String(f.messages[0]), /objective-refinement-context\.json/);
    assert.ok(
      f.notices.some((n) =>
        n.message.includes("context prepared for objective proj-1 node 2.3 (blocked; re-refining"),
      ),
    );
    // Re-entry with identical bytes: unchanged, no second stage append, still driven.
    await f.command("objective-refine", "proj-1 --node 2.3");
    assert.equal(f.calls.length, 2);
    assert.ok(f.notices.some((n) => n.message.includes("context unchanged")));
    assert.equal(f.messages.length, 2);
  } finally {
    f.dispose();
  }
});

test("/objective-refine (warm): refusals leave state untouched — bad args, objective_required, bound_session, busy, worker failure, digest mismatch", async () => {
  const badArgs = fixture({ stage: null, mode: "read-write", grounded: false });
  try {
    await badArgs.command("objective-refine", "7 8");
    assert.ok(warnNotices(badArgs).some((m) => m.includes("Usage: /objective-refine")));
    await badArgs.command("objective-refine", "");
    assert.ok(warnNotices(badArgs).some((m) => m.includes("(objective_required)")));
    badArgs.idle = false;
    await badArgs.command("objective-refine", "7");
    assert.ok(warnNotices(badArgs).some((m) => m.includes("the model is running")));
    assert.equal(badArgs.calls.length, 0);
    assert.equal(badArgs.messages.length, 0);
    assert.equal(badArgs.enters, 0);
  } finally {
    badArgs.dispose();
  }
  const bound = fixture({ stage: "objective-plan", grounded: false });
  try {
    bound.branch.push({
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { objective_node_claim: { objective: "7", node: "1.1" } },
    });
    await bound.command("objective-refine", "7");
    const refusal = warnNotices(bound).find((m) => m.includes("(bound_session)"));
    assert.ok(refusal, JSON.stringify(bound.notices));
    assert.match(refusal, /perk objective refine 7/, "the cold equivalent is offered");
    assert.equal(bound.calls.length, 0, "no worker call");
    assert.deepEqual(
      bound.state().nodeClaim(),
      { objective: "7", node: "1.1" },
      "the claim is never cleared",
    );
    assert.equal(bound.messages.length, 0);
  } finally {
    bound.dispose();
  }
  const failing = fixture({ stage: null, mode: "read-write", grounded: false });
  try {
    failing.routes["objective refine-context"] = {
      json: {
        success: false,
        error_type: "unsupported_backend",
        message: "GitHub objectives are not refinable yet",
      },
      code: 1,
    };
    await failing.command("objective-refine", "7");
    assert.ok(errorNotices(failing).some((m) => m.includes("(unsupported_backend)")));
    assert.equal(
      existsSync(join(sessionDataDir(failing.cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT)),
      false,
    );
    assert.equal(failing.messages.length, 0);
    assert.equal(failing.enters, 0);
  } finally {
    failing.dispose();
  }
  const skewed = fixture({ stage: null, mode: "read-write", grounded: false });
  try {
    skewed.routes["objective refine-context"] = {
      json: { ...CONTEXT_JSON, context_digest: `sha256:${"0".repeat(64)}` },
    };
    await skewed.command("objective-refine", "proj-1");
    assert.ok(errorNotices(skewed).some((m) => m.includes("(refinement_context_invalid)")));
    assert.equal(
      existsSync(join(sessionDataDir(skewed.cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT)),
      false,
    );
    assert.equal(skewed.messages.length, 0);
  } finally {
    skewed.dispose();
  }
});

// ------------------------------------------------------------------------- the cold claim (harness)

/** Materialize the cold door's fixed run-scratch transfer file. */
function writeTransfer(cwd: string, raw: string): void {
  mkdirSync(runScratchDir(cwd, GOLDEN_RUN), { recursive: true });
  writeFileSync(join(runScratchDir(cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT), raw, "utf8");
}

test("cold claim: an objective-refine handoff imports the run-scratch transfer once, byte-exact; the gate + flavor follow the stage", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: GOLDEN_RUN,
      mode: "read-only",
      stage: "objective-refine",
      extra: { objective_refinement: { context_digest: GOLDEN_DIGEST } },
    },
  });
  writeTransfer(cwd, GOLDEN_CONTEXT);
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: GOLDEN_RUN } });
  try {
    assert.equal(h.workflowState().stage, "objective-refine");
    assert.equal(
      h.workflowState().objective_node_claim,
      undefined,
      "no claim from the refinement handoff",
    );
    const stored = readFileSync(
      join(sessionDataDir(cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT),
      "utf8",
    );
    assert.equal(stored, GOLDEN_CONTEXT);
    assert.equal(
      soundPointer(h.workflowState().session_artifacts?.[REFINEMENT_CONTEXT_ARTIFACT])?.digest,
      GOLDEN_DIGEST,
    );
    // The refinement gate-ON census + backstop.
    assert.equal(await h.emitToolCall("objective_refinement_draft", { markdown: "m" }), undefined);
    assert.equal(
      (await h.emitToolCall("objective_node", { objective: "7", node: "1.1" }))?.block,
      true,
    );
    assert.equal((await h.emitToolCall("plan_draft", { plan: "p" }))?.block, true);
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    const injected = await h.emitBeforeAgentStart();
    const mode = injected.find((m) => m.customType === "perk:mode-context");
    assert.ok(
      String(mode?.content).includes("[READ-ONLY REFINEMENT MODE]"),
      "the refinement flavor",
    );
    assert.ok(
      String(mode?.content).includes("objective_refinement_draft is the sole sanctioned write"),
    );
    assert.ok(
      injected.some((m) => m.customType === "perk:objective-refinement-context"),
      "the refinement context",
    );
    assert.equal(
      injected.some((m) => m.customType === "perk:plan-context"),
      false,
      "plan mode defers",
    );
    // The draft tool works end-to-end against the imported context.
    const drafted = await h.invokeTool("objective_refinement_draft", { markdown: MARKDOWN });
    assert.equal((drafted.details as { ok?: boolean }).ok, true, JSON.stringify(drafted.details));
    const draft = decodeRefinementDraft(
      readFileSync(join(sessionDataDir(cwd, GOLDEN_RUN), REFINEMENT_DRAFT_ARTIFACT), "utf8"),
    );
    assert.ok(draft.ok && draft.draft.context_digest === GOLDEN_DIGEST);
  } finally {
    h.dispose();
  }
});

test("cold claim: a contaminated objective-refine handoff is refused before claiming; a digest mismatch imports nothing", async () => {
  const contaminated = scaffoldRepo({
    handoff: {
      runId: GOLDEN_RUN,
      mode: "read-only",
      stage: "objective-refine",
      extra: {
        objective_id: "7",
        node_id: "1.1",
        objective_refinement: { context_digest: GOLDEN_DIGEST },
      },
    },
  });
  writeTransfer(contaminated, GOLDEN_CONTEXT);
  const h1 = await loadPerkSession({ cwd: contaminated, env: { PERK_RUN_ID: GOLDEN_RUN } });
  try {
    assert.equal(h1.workflowState().run_id, undefined, "unclaimed");
    assert.equal(h1.workflowState().objective_node_claim, undefined, "no planning claim recorded");
    assert.equal(
      existsSync(join(sessionDataDir(contaminated, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT)),
      false,
    );
    const handoff = JSON.parse(
      readFileSync(
        join(contaminated, ".perk", "workflow", "handoff", `${GOLDEN_RUN}.json`),
        "utf8",
      ),
    );
    assert.equal(handoff.consumed, false, "not consumed");
  } finally {
    h1.dispose();
  }
  // Ordinary objective planning still claims from the same keys.
  const planning = scaffoldRepo({
    handoff: {
      runId: "01PLAN",
      mode: "read-only",
      stage: "objective-plan",
      extra: { objective_id: "7", node_id: "1.1" },
    },
  });
  const h2 = await loadPerkSession({ cwd: planning, env: { PERK_RUN_ID: "01PLAN" } });
  try {
    assert.deepEqual(h2.workflowState().objective_node_claim, { objective: "7", node: "1.1" });
  } finally {
    h2.dispose();
  }
  const mismatched = scaffoldRepo({
    handoff: {
      runId: GOLDEN_RUN,
      mode: "read-only",
      stage: "objective-refine",
      extra: { objective_refinement: { context_digest: `sha256:${"0".repeat(64)}` } },
    },
  });
  writeTransfer(mismatched, GOLDEN_CONTEXT);
  const h3 = await loadPerkSession({ cwd: mismatched, env: { PERK_RUN_ID: GOLDEN_RUN } });
  try {
    assert.equal(h3.workflowState().stage, "objective-refine", "the claim itself lands");
    assert.equal(
      existsSync(join(sessionDataDir(mismatched, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT)),
      false,
      "nothing imported",
    );
    assert.ok(
      h3.notifies.some(
        (n) => n.includes("context import refused") && n.includes("do not match their digest"),
      ),
    );
    const drafted = await h3.invokeTool("objective_refinement_draft", { markdown: MARKDOWN });
    assert.equal(
      (drafted.details as { error_type?: string }).error_type,
      "refinement_context_missing",
      "no drafting without a context",
    );
    // A reload never re-imports (no orphan repair).
    await h3.reload();
    assert.equal(
      existsSync(join(sessionDataDir(mismatched, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT)),
      false,
    );
  } finally {
    h3.dispose();
  }
});

test("warm /objective-refine (harness): an idle unbound session with an active objective enters refinement and injects the flavored contexts", async () => {
  // The session's identity is the golden run under a bare (stage-less, plan-less) launch
  // handoff — an UNBOUND session that already knows its run — so the worker's golden envelope
  // is this run's.
  const cwd = scaffoldRepo({ handoff: { runId: GOLDEN_RUN, mode: "read-write" } });
  const { fakePerkRouter } = await import("../../testing/harness.ts");
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[providers]\nplan = "plannotator-plan"\n',
    "utf8",
  );
  const bin = fakePerkRouter(cwd, { "objective refine-context": { json: CONTEXT_JSON } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: GOLDEN_RUN, PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    assert.equal(h.workflowState().stage, undefined, "unbound: no stage");
    assert.equal(h.workflowState().mode, "read-write");
    // No argument and no active objective → objective_required, nothing entered.
    await h.invokeCommand("objective-refine", "");
    assert.ok(
      h.notifies.some((n) => n.includes("(objective_required)")),
      JSON.stringify(h.notifies),
    );
    assert.equal(h.workflowState().stage, undefined);
    // An explicit objective enters: the worker's bytes land unchanged, the stage is set, the
    // gate is on with the refinement census, and one flow turn is driven.
    await h.invokeCommand("objective-refine", "proj-1 --node 2.3");
    assert.equal(h.workflowState().stage, "objective-refine", h.notifies.join("\n"));
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal(h.workflowState().objective_node_claim, undefined, "no claim");
    assert.equal(
      readFileSync(join(sessionDataDir(cwd, GOLDEN_RUN), REFINEMENT_CONTEXT_ARTIFACT), "utf8"),
      GOLDEN_CONTEXT,
    );
    assert.equal(sent.length, 1, "one driven flow turn");
    assert.match(sent[0] ?? "", /perk objective refine flow/);
    assert.equal(await h.emitToolCall("objective_refinement_draft", { markdown: "m" }), undefined);
    assert.equal((await h.emitToolCall("plan_draft", { plan: "p" }))?.block, true);
    assert.equal((await h.emitToolCall("edit", { path: "x" }))?.block, true);
    // The flavored contexts: the refinement mode flavor, the refinement grounding context, the
    // plannotator REFINEMENT adapter flavor; plan mode and the plan/objective/gist flavors defer.
    const injected = await h.emitBeforeAgentStart();
    const types = injected.map((m) => m.customType);
    assert.ok(types.includes("perk:objective-refinement-context"), types.join(","));
    assert.equal(types.includes("perk:plan-context"), false, "plan mode defers");
    const mode = injected.find((m) => m.customType === "perk:mode-context");
    assert.ok(String(mode?.content).includes("[READ-ONLY REFINEMENT MODE]"));
    const bridge = injected.filter((m) => m.customType === "perk:plan-adapter-plannotator");
    assert.equal(bridge.length, 1, "exactly one plannotator bridge flavor");
    assert.ok(String(bridge[0]?.content).includes("[REFINEMENT ADAPTER: PLANNOTATOR]"));
    assert.ok(String(bridge[0]?.content).includes("objective_refinement_draft"));
    for (const other of ["[PLAN ADAPTER", "[OBJECTIVE ADAPTER", "[GIST ADAPTER"]) {
      assert.equal(String(bridge[0]?.content).includes(other), false, other);
    }
  } finally {
    h.dispose();
  }
});

test("warm /objective-refine (harness): plan-mode contexts ALREADY injected before the transition are stripped — only the refinement flavors direct the model afterwards", async () => {
  // An unbound session that ran a plan-mode turn first: the plan-authoring context and the
  // plannotator PLAN adapter flavor are live in context when /objective-refine enters. The
  // transition must not leave those instructions (the now-refused plan draft/save flow) beside
  // the refinement ones — the plan context's liveness is stage-aware, and the adapter's shared
  // customType strips the non-selected flavor.
  const cwd = scaffoldRepo({ handoff: { runId: GOLDEN_RUN, mode: "read-write" } });
  const { fakePerkRouter } = await import("../../testing/harness.ts");
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const bin = fakePerkRouter(cwd, { "objective refine-context": { json: CONTEXT_JSON } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: GOLDEN_RUN, PERK_BIN: bin } });
  try {
    // Plan mode ON (the gate), then the turn that injects both plan-flavored contexts.
    await h.invokeCommand("plan", "");
    assert.equal(h.workflowState().mode, "read-only", "plan mode entered the gate");
    const before = await h.emitBeforeAgentStart();
    const planCopy = before.find((m) => m.customType === "perk:plan-context");
    const adapterCopy = before.find((m) => m.customType === "perk:plan-adapter-plannotator");
    assert.ok(planCopy && String(planCopy.content).includes("[PLAN AUTHORING]"));
    assert.ok(adapterCopy && String(adapterCopy.content).includes("[PLAN ADAPTER: PLANNOTATOR]"));
    // The context window as Pi would carry it into the next turn: both copies live.
    const carried = [
      { customType: "perk:plan-context", content: String(planCopy.content) },
      { customType: "perk:plan-adapter-plannotator", content: String(adapterCopy.content) },
      { role: "user", content: "author me a plan" },
    ];
    assert.equal((await h.emitContext(carried)).length, 3, "everything live before the transition");

    // The warm transition into refinement.
    await h.invokeCommand("objective-refine", "proj-1 --node 2.3");
    assert.equal(h.workflowState().stage, "objective-refine", h.notifies.join("\n"));

    // The stale copies are stripped from the carried window; the user turn survives.
    const after = await h.emitContext(carried);
    assert.deepEqual(
      after.map((m) => m.customType ?? m.role),
      ["user"],
      "the plan context and the PLAN adapter flavor are stale in a refinement session",
    );
    // The next turn injects only the refinement-flavored contexts.
    const injected = await h.emitBeforeAgentStart();
    const types = injected.map((m) => m.customType);
    assert.equal(types.includes("perk:plan-context"), false);
    assert.ok(types.includes("perk:objective-refinement-context"), types.join(","));
    const bridge = injected.filter((m) => m.customType === "perk:plan-adapter-plannotator");
    assert.equal(bridge.length, 1);
    assert.ok(String(bridge[0]?.content).includes("[REFINEMENT ADAPTER: PLANNOTATOR]"));
    // And a window that already carries the refinement flavor keeps it (the selected flavor is
    // never stripped) while still dropping the stale plan flavor.
    const mixed = await h.emitContext([
      { customType: "perk:plan-adapter-plannotator", content: String(bridge[0]?.content) },
      { customType: "perk:plan-adapter-plannotator", content: String(adapterCopy.content) },
    ]);
    assert.equal(mixed.length, 1);
    assert.ok(String(mixed[0]?.content).includes("[REFINEMENT ADAPTER: PLANNOTATOR]"));
  } finally {
    h.dispose();
  }
});

test("warm /objective-refine (harness): a worker envelope bound to ANOTHER run is refused fail-closed — nothing imported, nothing driven", async () => {
  const cwd = scaffoldRepo();
  const { fakePerkRouter } = await import("../../testing/harness.ts");
  const bin = fakePerkRouter(cwd, { "objective refine-context": { json: CONTEXT_JSON } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const sent = spyInjections(h);
  try {
    const minted = h.workflowState().run_id;
    assert.ok(minted && minted !== GOLDEN_RUN, "a warm session mints its own identity");
    await h.invokeCommand("objective-refine", "proj-1");
    assert.ok(
      h.notifies.some(
        (n) => n.includes("(refinement_context_invalid)") && n.includes("not this run"),
      ),
    );
    assert.equal(sent.length, 0);
    assert.equal(h.workflowState().stage, undefined);
    assert.equal(existsSync(join(sessionDataDir(cwd, minted), REFINEMENT_CONTEXT_ARTIFACT)), false);
  } finally {
    h.dispose();
  }
});
