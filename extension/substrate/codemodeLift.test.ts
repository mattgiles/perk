// The codemode lift (contracts.md §8.40), proven on REAL Pi sessions (fully offline): Pi's
// builtin codemode loaded as the CLI loads it (`builtin: true`, NO factory `mode` — the session's
// `codemode.mode` setting decides), enabled by the user's `defaultTools`, in every registry
// read-only stage × both codemode modes. Per cell: the model-facing census of the first request;
// one model-path codemode script whose every nested call is caught and recorded (the admitted
// reads, the hook refusals, and the bounded writers that are not members of the script's `tools`
// at all); and the stage's draft loop — writer (v1) → plan_review DENIED through the fake
// Plannotator → writer (v2). Shared rows (once, not per cell) pin the safety and control arms:
// a discovery nonparticipant keeps `only` suspended (its mode-over-stage actions stay direct),
// Pi's registry filter lifts it, a host-activated deferred member is never hidden, a `/reload`
// keeps a lifted codemode, and the read-write control's script write lands.
//
// Two refusal oracles, kept apart: a script reading a model-only name meets the sandbox's
// missing-member TypeError (`tools.<name> does not exist.`) before any nested call; a call that
// reaches the backstop carries the codemode call's id as its `parentToolCallId`.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { before, test } from "node:test";
import { createCodemodeExtension, type InlineExtension } from "@earendil-works/pi-coding-agent";
import { REFINEMENT_CONTEXT_ARTIFACT } from "../authoring/refinement/context.ts";
import {
  fakePerkRouter,
  gitInit,
  loadAt,
  type PerkSession,
  recordingRuntime,
  recordPerkInstalls,
  registerFakeTool,
  scaffoldRepo,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { runScratchDir } from "./cache.ts";
import { LOADOUT_HOST_NAME, READ_ONLY_STAGES } from "./toolPolicy.ts";

before(ensureToolCatalog);

type CodemodeMode = "on" | "only";
type Runtime = Awaited<ReturnType<typeof recordingRuntime>>;

/** The id of the one model-path codemode call per script turn. */
const SCRIPT_ID = "call-codemode";
/** The unknown-provenance tool a bare factory registers (`<inline:N>`). */
const UNKNOWN = "lift_unknown_probe";
/** The fixed `perk objective stack status --json` payload the fake cold door serves. */
const STATUS = { success: true, objective: { id: "7" }, no_train: "no stacked train" };
/** Pi's startup defaults are read/bash/edit/write: the census enables the other reads too. */
const READS = ["read", "bash", "grep", "find", "ls"];
const BASE_TOOLS = ["+codemode", "+grep", "+find", "+ls"];
/** The refinement fixture (Python-serialized context bytes + digest; the run it is bound to). */
const REFINE_FIXTURES = join(
  import.meta.dirname,
  "..",
  "..",
  "tests",
  "fixtures",
  "objective-refinement",
);
const REFINE_RUN = "01AUTHRUN";

/** Each read-only stage's bounded writer, its draft arguments, and the writers it declares. */
const STAGE_WRITERS: Record<
  string,
  { writer: string; args: (version: string) => Record<string, string>; declares: string[] }
> = {
  "gist-author": {
    writer: "gist_draft",
    args: (v) => ({ prose: `# Lift gist ${v}\n\nThe gist body, revision ${v}.\n` }),
    declares: ["gist_draft"],
  },
  "objective-author": {
    writer: "objective_draft",
    args: (v) => ({ prose: `# Lift objective ${v}\n\nThe objective prose, revision ${v}.\n` }),
    declares: ["objective_draft"],
  },
  "objective-plan": {
    writer: "plan_draft",
    args: (v) => ({ plan: `# Lift plan ${v}\n\nThe plan body, revision ${v}.\n` }),
    declares: ["plan_draft", "objective_node"],
  },
  plan: {
    writer: "plan_draft",
    args: (v) => ({ plan: `# Lift plan ${v}\n\nThe plan body, revision ${v}.\n` }),
    declares: ["plan_draft"],
  },
  audit: {
    writer: "plan_draft",
    args: (v) => ({ plan: `# Lift audit plan ${v}\n\nThe plan body, revision ${v}.\n` }),
    declares: ["plan_draft"],
  },
  "objective-refine": {
    writer: "objective_refinement_draft",
    args: (v) => ({ markdown: `## Refinement ${v}\n\nWhat the node delivers, revision ${v}.\n` }),
    declares: ["objective_refinement_draft"],
  },
};

/** Where `objective_stack_status` is gate-eligible (the planning/refinement read family). */
const QUERY_STAGES = ["plan", "objective-plan", "objective-refine"];

/** Pi's builtin codemode exactly as the CLI loads it: no factory `mode` (the setting decides). */
const cliCodemode = (): InlineExtension => ({
  name: "codemode",
  factory: createCodemodeExtension(),
  builtin: true,
});

/** A fake Plannotator on the event bus: every plan-review request is handled, then DENIED. */
function denyingPlannotator(): InlineExtension {
  let n = 0;
  return {
    name: "fake-plannotator",
    factory: (pi) => {
      pi.events.on("plannotator:request", (data) => {
        const req = data as { action?: string; respond?: (r: unknown) => void };
        if (req.action !== "plan-review") return;
        const reviewId = `rev-lift-${++n}`;
        req.respond?.({ status: "handled", result: { status: "pending", reviewId } });
        setTimeout(() => {
          pi.events.emit("plannotator:review-result", {
            reviewId,
            approved: false,
            feedback: "revise the lift draft",
          });
        }, 0);
      });
    },
  };
}

/** A gated (or read-write) session at `stage`, its cwd, and the recording runtime. */
type Lift = { h: PerkSession; cwd: string; rt: Runtime };

async function liftSession(opts: {
  stage: string;
  codemode: CodemodeMode;
  cohort?: boolean;
  mode?: "read-only" | "read-write";
  excludeTools?: string[];
}): Promise<Lift> {
  const { stage, codemode } = opts;
  const mode = opts.mode ?? "read-only";
  const refine = stage === "objective-refine";
  const runId = refine
    ? REFINE_RUN
    : `01LIFT${stage.replaceAll("-", "").toUpperCase()}${codemode.toUpperCase()}`;
  const cwd = scaffoldRepo({
    handoff: {
      runId,
      mode,
      stage,
      ...(refine
        ? {
            extra: {
              objective_refinement: {
                context_digest: readFileSync(
                  join(REFINE_FIXTURES, "context.sha256"),
                  "utf8",
                ).trim(),
              },
            },
          }
        : {}),
    },
  });
  gitInit(cwd, { dirty: false });
  if (refine) {
    mkdirSync(runScratchDir(cwd, REFINE_RUN), { recursive: true });
    writeFileSync(
      join(runScratchDir(cwd, REFINE_RUN), REFINEMENT_CONTEXT_ARTIFACT),
      readFileSync(join(REFINE_FIXTURES, "context.json"), "utf8"),
      "utf8",
    );
  }
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  writeFileSync(join(cwd, "notes.txt"), "lift notes\n");
  const bin = fakePerkRouter(cwd, { "objective stack": { json: STATUS } });
  const rt = await recordingRuntime();
  const h = await loadAt(cwd, {
    headful: true,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: runId, PERK_BIN: bin },
    extraExtensions: [
      cliCodemode(),
      toolSearch(),
      (pi) => registerFakeTool(pi, UNKNOWN),
      denyingPlannotator(),
    ],
    settings: {
      defaultTools: [...(opts.cohort === false ? [] : ["+tool_search"]), ...BASE_TOOLS],
      codemode: { mode: codemode },
    },
    ...(opts.excludeTools !== undefined ? { excludeTools: opts.excludeTools } : {}),
  });
  return { h, cwd, rt };
}

/** The script: every call caught and recorded by key; the record returned as one JSON line. */
function liftScript(writer: string): string {
  return `const out = {};
const attempt = async (key, call) => {
  try {
    out[key] = { ok: true, value: await call() };
  } catch (error) {
    out[key] = { ok: false, name: String(error.name), message: String(error.message) };
  }
};
await attempt("read", () => tools.read({ path: "notes.txt" }));
await attempt("ls", () => tools.bash({ command: "ls" }));
await attempt("query", () => tools.objective_stack_status({ objective: "7" }));
await attempt("write", () => tools.write({ path: "script-target.txt", content: "x\\n" }));
await attempt("touch", () => tools.bash({ command: "touch script-x" }));
await attempt("unknown", () => tools.${UNKNOWN}({}));
await attempt("writer", () => tools.${writer}({}));
await attempt("plan_review", () => tools.plan_review({}));
await attempt("run_scout_wave", () => tools.run_scout_wave({}));
return "LIFT-RESULTS " + JSON.stringify(out);`;
}

type Attempt = { ok: true; value: unknown } | { ok: false; name: string; message: string };

/** The persisted tool result answering `toolCallId`: its text, details and error flag. */
function toolResult(
  h: PerkSession,
  toolCallId: string,
): { text: string; details: unknown; isError: boolean } {
  const entries = h.session.sessionManager.getBranch() as unknown as {
    type: string;
    message?: {
      role?: string;
      toolCallId?: string;
      isError?: boolean;
      details?: unknown;
      content?: { type: string; text?: string }[];
    };
  }[];
  const found = entries.find(
    (e) =>
      e.type === "message" &&
      e.message?.role === "toolResult" &&
      e.message.toolCallId === toolCallId,
  );
  assert.ok(found?.message !== undefined, `a tool result answers ${toolCallId}`);
  return {
    text: (found.message.content ?? []).map((c) => c.text ?? "").join(""),
    details: found.message.details,
    isError: found.message.isError === true,
  };
}

/** The script's recorded attempts, parsed from the codemode result. */
function scriptAttempts(h: PerkSession): Record<string, Attempt> {
  const result = toolResult(h, SCRIPT_ID);
  assert.equal(result.isError, false, result.text);
  assert.match(result.text, /^Script completed/);
  const match = /LIFT-RESULTS (\{.*\})/s.exec(result.text);
  assert.ok(match?.[1] !== undefined, result.text);
  return JSON.parse(match[1]) as Record<string, Attempt>;
}

/** Every nested `tool_call` (one carrying `parentToolCallId`) and its verdict. */
function spyNested(h: PerkSession): { toolName: string; parent?: string; reason?: string }[] {
  const seen: { toolName: string; parent?: string; reason?: string }[] = [];
  const runner = h.session.extensionRunner;
  const emit = runner.emitToolCall.bind(runner);
  runner.emitToolCall = async (event) => {
    const result = await emit(event);
    const parent = (event as { parentToolCallId?: string }).parentToolCallId;
    if (parent !== undefined) {
      seen.push({
        toolName: event.toolName,
        parent,
        reason: (result as { reason?: string } | undefined)?.reason,
      });
    }
    return result;
  };
  return seen;
}

const blocked = (name: string, why: string) => `perk read-only mode: ${name} is blocked (${why}).`;

function assertRefused(attempt: Attempt | undefined, reason: string, label: string): void {
  assert.ok(attempt !== undefined && !attempt.ok, `${label}: refused (${JSON.stringify(attempt)})`);
  assert.ok(attempt.message.includes(reason), `${label}: ${attempt.message}`);
}

function assertMissingMember(attempt: Attempt | undefined, name: string): void {
  assert.ok(attempt !== undefined && !attempt.ok, `${name}: not a script member`);
  assert.equal(attempt.name, "TypeError", `${name}: ${attempt.message}`);
  assert.match(attempt.message, new RegExp(`^tools\\.${name} does not exist\\.`), name);
}

/** A declared tool's description in a recorded request. */
function description(declared: unknown[], name: string): string {
  const tool = declared.find((t) => (t as { name?: string }).name === name) as
    | { description?: string }
    | undefined;
  assert.ok(tool !== undefined, `${name} declared`);
  return tool.description ?? "";
}

// --- the per-cell proof: every registry read-only stage × both codemode modes -------------------

for (const stage of READ_ONLY_STAGES) {
  for (const codemode of ["on", "only"] as const) {
    test(`codemode lift (${stage} × ${codemode}): declared and scriptable under the gate; the nested policy bounds the script; the draft loop completes`, async () => {
      const cell = STAGE_WRITERS[stage];
      assert.ok(cell !== undefined, stage);
      const { writer, declares } = cell;
      const { h, cwd, rt } = await liftSession({ stage, codemode });
      const seen = spyNested(h);
      try {
        assert.equal(h.workflowState().stage, stage);
        assert.equal(h.workflowState().mode, "read-only");
        rt.callsThenStop([
          { tool: "codemode", args: { code: liftScript(writer) }, id: SCRIPT_ID },
          { tool: writer, args: cell.args("v1"), id: "call-writer-v1" },
          { tool: "plan_review", args: {}, id: "call-review" },
          { tool: writer, args: cell.args("v2"), id: "call-writer-v2" },
        ]);
        await h.session.prompt("draft under the gate");
        assert.ok(h.session.getActiveToolNames().includes("codemode"), "codemode active");

        // The census: the first request.
        const first = rt.requests[0];
        assert.ok(first !== undefined, "a request was made");
        for (const name of ["codemode", "tool_search", "plan_review", ...declares])
          assert.ok(first.tools.includes(name), `${name} declared (${first.tools.join(", ")})`);
        for (const name of READS) {
          assert.equal(
            first.tools.includes(name),
            codemode === "on",
            `${name}: declared iff mode on (Pi's only hides direct tools)`,
          );
        }
        for (const name of ["edit", "write", LOADOUT_HOST_NAME, UNKNOWN])
          assert.ok(!first.tools.includes(name), `${name} not declared`);
        for (const name of declares)
          assert.ok(
            !description(first.declared, name).includes("Codemode:"),
            `${name}: no rewrite`,
          );
        if (codemode === "on") {
          assert.ok(
            description(first.declared, "read").includes("Codemode:"),
            "the rewrite is live for a callable direct tool (the negative is not vacuous)",
          );
        }

        // The script: admitted reads; hook refusals; model-only names absent from the sandbox.
        const attempts = scriptAttempts(h);
        const read = attempts.read;
        assert.ok(read?.ok === true, JSON.stringify(read));
        assert.match(String(read.value), /lift notes/);
        const ls = attempts.ls;
        assert.ok(ls?.ok === true, JSON.stringify(ls));
        assert.match(JSON.stringify(ls.value), /notes\.txt/);
        if (QUERY_STAGES.includes(stage)) {
          const query = attempts.query;
          assert.ok(query?.ok === true, JSON.stringify(query));
          assert.deepEqual(query.value, { ok: true, objective: "7", status: STATUS });
        } else {
          assertRefused(
            attempts.query,
            blocked("objective_stack_status", "tool not allowlisted"),
            "query",
          );
        }
        assertRefused(attempts.write, blocked("write", "file modifications disabled"), "write");
        assertRefused(
          attempts.touch,
          "perk read-only mode: command blocked (not allowlisted).\nCommand: touch script-x",
          "touch",
        );
        assertRefused(attempts.unknown, blocked(UNKNOWN, "tool not allowlisted"), "unknown");
        assertMissingMember(attempts.writer, writer);
        assertMissingMember(attempts.plan_review, "plan_review");
        assertMissingMember(attempts.run_scout_wave, "run_scout_wave");
        assert.equal(existsSync(join(cwd, "script-target.txt")), false, "the write never landed");
        assert.equal(existsSync(join(cwd, "script-x")), false, "the touch never ran");
        assert.ok(seen.length > 0, "nested calls reached the backstop");
        for (const call of seen) assert.equal(call.parent, SCRIPT_ID, call.toolName);
        assert.deepEqual(
          seen.map((call) => call.toolName),
          ["read", "bash", "objective_stack_status", "write", "bash", UNKNOWN],
        );

        // The draft loop: v1 lands, the review is DENIED naming the writer, v2 lands distinct.
        const v1 = toolResult(h, "call-writer-v1");
        assert.equal((v1.details as { ok?: unknown }).ok, true, v1.text);
        const review = toolResult(h, "call-review");
        assert.match(review.text, /DENIED/, review.text);
        assert.ok(review.text.includes(writer), `the denial names ${writer}: ${review.text}`);
        const v2 = toolResult(h, "call-writer-v2");
        assert.equal((v2.details as { ok?: unknown }).ok, true, v2.text);
        const digest = (d: unknown) => (d as { digest?: string }).digest;
        assert.ok(digest(v1.details) !== undefined && digest(v2.details) !== undefined);
        assert.notEqual(digest(v2.details), digest(v1.details), "distinct revision bytes");
        const revising = rt.requests[3];
        assert.ok(revising?.tools.includes(writer), `${writer} still declared for the revision`);
      } finally {
        h.dispose();
      }
    });
  }
}

// --- the shared safety and control rows ----------------------------------------------------------

/** One plain census turn; returns the declared names. */
async function census(lift: Lift): Promise<string[]> {
  lift.rt.census();
  await lift.h.session.prompt("census");
  return lift.rt.last().tools;
}

test("codemode lift: a discovery nonparticipant keeps `only` suspended in plan — its mode-over-stage actions stay direct — while `on` lifts", async () => {
  const outside = await liftSession({ stage: "plan", codemode: "only", cohort: false });
  try {
    const declared = await census(outside);
    assert.ok(!outside.h.session.getActiveToolNames().includes("codemode"), "suspended");
    assert.ok(!declared.includes("codemode"), "not declared");
    assert.equal(
      (await outside.h.emitToolCall("codemode", { code: "return 1" }))?.reason,
      blocked("codemode", "tool not allowlisted"),
    );
    for (const name of ["plan_draft", "read", "bash", "push_annotations"])
      assert.ok(declared.includes(name), `${name} still declared`);
  } finally {
    outside.h.dispose();
  }

  const on = await liftSession({ stage: "plan", codemode: "on", cohort: false });
  try {
    const declared = await census(on);
    assert.ok(on.h.session.getActiveToolNames().includes("codemode"), "lifted");
    assert.ok(declared.includes("codemode"));
    assert.equal(await on.h.emitToolCall("codemode", { code: "return 1" }), undefined);
  } finally {
    on.h.dispose();
  }
});

test("codemode lift: Pi's registry filter leaving out both mode-over-stage actions lifts `only` for a nonparticipant", async () => {
  const filtered = await liftSession({
    stage: "plan",
    codemode: "only",
    cohort: false,
    excludeTools: ["push_annotations", "collect_draft_review_wave"],
  });
  try {
    const declared = await census(filtered);
    assert.equal(filtered.h.toolInfo("push_annotations"), null, "filtered out");
    assert.ok(filtered.h.session.getActiveToolNames().includes("codemode"), "lifted");
    assert.ok(declared.includes("codemode"));
  } finally {
    filtered.h.dispose();
  }
});

test("codemode lift: in a cohort `only` session a host-activated deferred member stays declared (deferred, never hidden by Pi)", async () => {
  const lift = await liftSession({ stage: "plan", codemode: "only" });
  try {
    await census(lift);
    assert.ok(lift.h.session.getActiveToolNames().includes("codemode"), "lifted");
    assert.equal(lift.h.toolInfo("push_annotations")?.exposure, "deferred");
    lift.h.session.setActiveToolsByName([
      ...lift.h.session.getActiveToolNames(),
      "push_annotations",
    ]);
    const declared = await census(lift);
    assert.ok(declared.includes("push_annotations"), "declared on the next request");
    assert.ok(lift.h.session.getActiveToolNames().includes("codemode"), "still lifted");
  } finally {
    lift.h.dispose();
  }
});

test("codemode lift: a cohort `on` session keeps codemode across /reload — perk only adds inside the window, and the close removes nothing of it", async (t) => {
  const lift = await liftSession({ stage: "plan", codemode: "on" });
  const installs = recordPerkInstalls(t);
  try {
    await census(lift);
    assert.ok(lift.h.session.getActiveToolNames().includes("codemode"));
    await lift.h.reload();
    assert.ok(lift.h.session.getActiveToolNames().includes("codemode"), "kept by the reload");
    const declared = await census(lift);
    assert.ok(lift.h.session.getActiveToolNames().includes("codemode"), "kept past agent_start");
    assert.ok(declared.includes("codemode"));
    for (const [i, install] of installs.entries())
      assert.ok(install.names.includes("codemode"), `perk install #${i} kept codemode`);
  } finally {
    lift.h.dispose();
  }
});

test("codemode lift: the read-write control — the same script's write lands", async () => {
  const lift = await liftSession({ stage: "plan", codemode: "on", mode: "read-write" });
  try {
    assert.equal(lift.h.workflowState().mode, "read-write");
    lift.rt.callsThenStop([
      { tool: "codemode", args: { code: liftScript("plan_draft") }, id: SCRIPT_ID },
    ]);
    await lift.h.session.prompt("script read-write");
    const attempts = scriptAttempts(lift.h);
    assert.ok(attempts.write?.ok === true, JSON.stringify(attempts.write));
    assert.equal(readFileSync(join(lift.cwd, "script-target.txt"), "utf8"), "x\n");
    // Model-only everywhere: the writer is no script member read-write either.
    assertMissingMember(attempts.writer, "plan_draft");
  } finally {
    lift.h.dispose();
  }
});
