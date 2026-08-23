// Lifecycle-gate tests. The pure gateDecision matrix as units; the dirty-repo
// gate + the guard-only `/implement` driven through a REAL bound offline session (T1 harness) over a
// REAL git repo (gitInit). No LLM / network.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, readPlanRef, writePlanRef } from "../substrate/cache.ts";
import type { WorkflowState } from "../substrate/workflowState.ts";
import {
  fakePerk,
  gitInit,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  gateDecision,
  implementHandoffPrompt,
  planningStageRefusal,
  planReadInstruction,
} from "./lifecycleGates.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};
const ACTIVE: Partial<WorkflowState> = {
  run_id: "01RID",
  mode: "read-write",
  active_plan_ref: REF,
};

/** Load a session over a planted branch + a real git repo (planted first so it commits clean). */
async function loadOverGit(
  cwd: string,
  states: Partial<WorkflowState>[],
  opts: { dirty: boolean; headful?: boolean },
) {
  const file = plantSession(cwd, states);
  gitInit(cwd, { dirty: opts.dirty });
  return loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    headful: opts.headful ?? true,
  });
}

// --- pure policy ------------------------------------------------------------------------

test("gateDecision: cancels only inside an active workflow with a dirty tree", () => {
  assert.equal(gateDecision({ active: true, dirty: true }).cancel, true);
  assert.equal(gateDecision({ active: true, dirty: false }).cancel, false);
  assert.equal(gateDecision({ active: false, dirty: true }).cancel, false);
  assert.equal(gateDecision({ active: false, dirty: false }).cancel, false);
});

// --- live gate matrix -------------------------------------------------------------------

test("gate: dirty + active workflow -> before_fork AND before_switch cancel", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: true });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    const sw = await h.emitLifecycle({ type: "session_before_switch", reason: "resume" });
    assert.equal(fork?.cancel, true, "dirty fork cancels");
    assert.equal(sw?.cancel, true, "dirty switch cancels");
    assert.ok(
      h.notifies.some((n) => /uncommitted changes/.test(n)),
      "loud notify",
    );
  } finally {
    h.dispose();
  }
});

test("gate: clean + active workflow -> allows", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: false });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.notEqual(fork?.cancel, true, "clean fork is allowed");
  } finally {
    h.dispose();
  }
});

test("gate: dirty but NO active workflow -> allows (perk does not interfere)", async () => {
  // mode set, but no active_plan_ref -> not a perk workflow
  const h = await loadOverGit(scaffoldRepo(), [{ run_id: "01RID", mode: "read-write" }], {
    dirty: true,
  });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.notEqual(fork?.cancel, true, "non-workflow fork is not gated");
  } finally {
    h.dispose();
  }
});

test("gate: headless + dirty + active -> cancels (fail-safe, no notify)", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: true, headful: false });
  try {
    const fork = await h.emitLifecycle({
      type: "session_before_fork",
      entryId: "x",
      position: "at",
    });
    assert.equal(fork?.cancel, true, "headless dirty fork still cancels");
    assert.equal(h.notifies.length, 0, "headless: no UI notify (stderr only)");
  } finally {
    h.dispose();
  }
});

// --- the guard-only /implement ----------------------------------------------------------

test("/implement: outside an impl worktree -> refuses, points to the cold door", async () => {
  const h = await loadPerkSession({ cwd: scaffoldRepo() });
  try {
    await h.invokeCommand("implement");
    assert.ok(
      h.notifies.some((n) => /cold-only/.test(n)),
      "warned cold-only",
    );
  } finally {
    h.dispose();
  }
});

test("implementHandoffPrompt: carries the plan forward (read it; never summarize)", () => {
  const prompt = implementHandoffPrompt(REF);
  assert.match(prompt, /implementing perk plan github #42/);
  assert.match(prompt, /gh issue view 42 --comments/);
  assert.match(prompt, /\/submit/);
  // The warm handoff is now unified with the cold/worker primer — it carries the progress tail.
  assert.match(prompt, /Progress tracking:/);
  // …and the validation discipline (run_ci while iterating; a green run-all is terminal).
  assert.match(prompt, /Validation:/);
  // A non-github provider falls back to opening the url.
  const other = implementHandoffPrompt({ ...REF, provider: "gitlab" });
  assert.match(other, /open https:\/\/gh\/o\/r\/issues\/42/);
  // A linear ref renders the pi-mono-linear read recipe.
  const linear = implementHandoffPrompt({ ...REF, provider: "linear" });
  assert.match(linear, /linear_get_issue/);
  assert.match(linear, /linear_list_comments/);
});

test("planReadInstruction: three arms (github / linear / fallback)", () => {
  assert.equal(planReadInstruction("github", "42", "https://x/42"), "gh issue view 42 --comments");
  const linear = planReadInstruction("linear", "uuid-1", "https://linear.app/x/ENG-1");
  assert.ok(linear.includes("use the `linear_get_issue` tool (id `uuid-1`)"));
  assert.ok(linear.includes("then `linear_list_comments`"));
  assert.ok(linear.includes("the plan body is the first comment"));
  assert.ok(
    linear.includes("if the linear tools are unavailable, open https://linear.app/x/ENG-1"),
  );
  assert.equal(planReadInstruction("gitlab", "9", "https://gl/x"), "open https://gl/x");
});

test("/implement: inside a clean impl worktree -> seeded ctx.newSession handoff (output capped)", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: false });
  try {
    const { newSessionCalls, seeded } = await h.runCommandHandler("implement");
    assert.equal(newSessionCalls.length, 1, "newSession invoked once");
    assert.equal(seeded.length, 1, "exactly one priming message seeded");
    assert.match(seeded[0] ?? "", /implementing perk plan github #42/, "plan-read priming seeded");
    // Model-visible output is capped: a single short confirmation notify, not the plan body.
    assert.ok(
      h.notifies.some((n) => /fresh implement session started for plan #42/.test(n)),
      "capped confirmation surfaced",
    );
    assert.ok(
      !h.notifies.some((n) => /gh issue view/.test(n)),
      "the plan body is not echoed into model-visible output",
    );
  } finally {
    h.dispose();
  }
});

test("/implement: dirty impl worktree -> refuses the handoff (no newSession)", async () => {
  const h = await loadOverGit(scaffoldRepo(), [ACTIVE], { dirty: true });
  try {
    const { newSessionCalls } = await h.runCommandHandler("implement");
    assert.equal(newSessionCalls.length, 0, "no handoff on a dirty tree");
    assert.ok(
      h.notifies.some((n) => /uncommitted changes/.test(n)),
      "refused with a dirty-tree message",
    );
  } finally {
    h.dispose();
  }
});

test("/implement: outside an impl worktree via handler -> no newSession, points cold", async () => {
  const h = await loadOverGit(scaffoldRepo(), [{ run_id: "01RID", mode: "read-write" }], {
    dirty: false,
  });
  try {
    const { newSessionCalls } = await h.runCommandHandler("implement");
    assert.equal(newSessionCalls.length, 0, "no handoff outside an impl context");
    assert.ok(
      h.notifies.some((n) => /cold-only/.test(n)),
      "pointed at the cold door",
    );
  } finally {
    h.dispose();
  }
});

// --- the planning-stage lifecycle-door refusal --------------------------------------------

test("planningStageRefusal: planning stages refuse; other/absent stages pass", () => {
  const ctxFor = (stage?: string) => ({
    sessionManager: {
      getBranch: () => [
        {
          type: "custom",
          customType: "perk:workflow-state",
          data: { run_id: "01RID", ...(stage !== undefined ? { stage } : {}) },
        },
      ],
    },
  });
  for (const stage of ["plan", "objective-plan"]) {
    const message = planningStageRefusal(ctxFor(stage), "submit");
    assert.ok(message !== null, `${stage} refuses`);
    assert.match(message, /planning session/);
    assert.match(message, /perk impl <N>/);
    assert.match(message, new RegExp(stage));
  }
  for (const stage of ["implement", "address", "learn", undefined]) {
    assert.equal(planningStageRefusal(ctxFor(stage), "submit"), null, `${stage} passes`);
  }
});

test("planningStageRefusal: an unreadable branch refuses (fail-closed)", () => {
  // Without the state the guard cannot prove the session is not a positioned planning session
  // (whose cwd binding is the PREDECESSOR), so an unreadable branch refuses, never allows.
  const throwing = {
    sessionManager: {
      getBranch: () => {
        throw new Error("branch unavailable");
      },
    },
  };
  const message = planningStageRefusal(throwing, "land");
  assert.ok(message !== null, "unreadable state refuses");
  assert.match(message, /could not be read/);
  assert.match(message, /branch unavailable/);
});

test("lifecycle doors refuse in a planning session — the two-ref regression", async () => {
  // The dangerous shape after an approved save in a positioned stacked planning session: the
  // cwd binding is the PREDECESSOR (readPlanRef(ctx.cwd)) while active_plan_ref is the
  // just-saved child. Every lifecycle door refuses BEFORE any cold-door delegation — the fake
  // perk records zero invocations, so no door action can touch the predecessor.
  const cwd = scaffoldRepo();
  const predecessor: PlanRef = { ...REF, pr_id: "101", url: "u/101" };
  const child: PlanRef = { ...REF, pr_id: "102", url: "u/102" };
  writePlanRef(cwd, predecessor); // the positioned checkout's own durable binding
  const argvFile = join(cwd, "cold-door-argv.txt");
  const bin = fakePerk(cwd, { stdout: "{}", argvFile });
  const file = plantSession(
    cwd,
    [
      {
        run_id: "01RID",
        // Post-approval-save: the gate exited (read-write) but the stage stays objective-plan.
        mode: "read-write",
        stage: "objective-plan",
        pi_session_id: "two-ref.jsonl",
        active_plan_ref: child,
      },
    ],
    { fileName: "two-ref.jsonl" },
  );
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
    mode: "print",
  });
  try {
    for (const [tool, params] of [
      ["submit", {}],
      ["land", {}],
      ["learn", {}],
      ["finalize_address", { threads: [{ thread_id: "T1" }] }],
    ] as const) {
      const result = await h.invokeTool(tool, params);
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false, `${tool} refused`);
      assert.equal(details.error_type, "planning_session", `${tool} refusal is typed`);
    }
    await h.runCommandHandler("address", "");
    await h.runCommandHandler("learn", "skip");
    assert.ok(
      h.notifyEvents.some(
        (event) => event.severity === "warning" && /planning session/.test(event.message),
      ),
      "the command surfaces warned with the planning refusal",
    );
    assert.ok(!existsSync(argvFile), "no cold door was ever invoked");
    // The predecessor's binding is byte-untouched.
    assert.deepEqual(readPlanRef(cwd), predecessor);
  } finally {
    h.dispose();
  }
});

test("lifecycle doors proceed in a non-planning session (stage implement)", async () => {
  // The guard keys ONLY off the planning stages: an implement-stage session reaches the cold
  // door as before (the fake perk is invoked; the failure surfaced is the fake's, not the
  // planning refusal).
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "cold-door-argv.txt");
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: false, error_type: "boom", message: "fake door" }),
    code: 1,
    argvFile,
  });
  const file = plantSession(
    cwd,
    [{ run_id: "01RID", mode: "read-write", stage: "implement", pi_session_id: "impl.jsonl" }],
    { fileName: "impl.jsonl" },
  );
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
    mode: "print",
  });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.notEqual(details.error_type, "planning_session");
    assert.ok(existsSync(argvFile), "the cold door was reached");
    assert.match(readFileSync(argvFile, "utf8"), /submit/);
  } finally {
    h.dispose();
  }
});
