// Live composition tests for perk-owned session names (contracts.md §8.71(h)) over a REAL bound
// AgentSession (offline): the cold claim names from the handoff's `naming` hints + the linked
// plan-ref; an unnamed pre-feature session gains its name on reopen; a human `/name` is
// preserved; a fork child inherits its parent's origin through the real fork arm; an adopted
// env-child and a minted hand-run session (even after a warm refinement append) stay unnamed; a failing `setSessionName` is one warning and startup still completes; a
// failed ownership append leaves the new name and freezes it as `preserved`; the kept arm's `fill`
// policy never reverts a later-learned title. The later refresh moments ride the same wiring:
// the draft tools (`plan_draft`/`objective_draft`/`gist_draft`) refresh with the draft's title
// and the linking saves (`/plan-save`, `/objective-save`) add the `plan #N` / `objective #O`
// segment. The owning behavior matrix lives in `session/sessionName.test.ts`; this suite pins the
// real Pi wiring around it.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, writePlanRef } from "./substrate/cache.ts";
import { recordSessionPointer } from "./substrate/sessionPointers.ts";
import { WORKFLOW_STATE_TYPE } from "./substrate/workflowState.ts";
import { fakePerk, loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

function planRef(prId: string, extra: Partial<PlanRef> = {}): PlanRef {
  return {
    provider: "github",
    pr_id: prId,
    url: `https://github.com/o/r/issues/${prId}`,
    labels: ["perk:plan"],
    objective_id: null,
    ...extra,
  };
}

const CLAIMED_NAME = "implement | plan #42 | objective #7 / 1.1 | Add retry";

function namingWarnings(h: Awaited<ReturnType<typeof loadPerkSession>>) {
  return h.notifyEvents.filter(
    (event) => event.severity === "warning" && event.message.includes("session name"),
  );
}

/** The cold-claimed implement session with launch-era naming hints and an objective-linked ref. */
async function claimedImplementSession() {
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-write",
      stage: "implement",
      extra: { naming: { title: "Add retry", node: "1.1" } },
    },
  });
  writePlanRef(cwd, planRef("42", { objective_id: "7" }));
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  return { cwd, h };
}

test("naming: a cold claim names the session from the handoff hints and the linked plan-ref", async () => {
  const { h } = await claimedImplementSession();
  try {
    assert.equal(h.session.sessionManager.getSessionName(), CLAIMED_NAME);
    const state = h.workflowState();
    assert.equal(state.session_name, CLAIMED_NAME);
    assert.deepEqual(state.session_naming, { title: "Add retry", node: "1.1" });
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: an unnamed pre-feature session gains its name on reopen (kept arm, no handoff)", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      pi_session_id: "planted-parent.jsonl",
      mode: "read-write",
      stage: "implement",
      active_plan_ref: planRef("42"),
    },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.session.sessionManager.getSessionName(), "implement | plan #42");
    assert.equal(h.workflowState().session_name, "implement | plan #42");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a differing /name is preserved on the next start", async () => {
  const { h } = await claimedImplementSession();
  try {
    h.session.setSessionName("mine");
    await h.emitSessionStart();
    assert.equal(h.session.sessionManager.getSessionName(), "mine");
    assert.equal(h.workflowState().session_name, CLAIMED_NAME); // perk's record is untouched
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a fork child inherits its parent's origin through the real forked arm", async () => {
  // The child's branch begins with the parent's cold-claim entry, recorded under a DIFFERENT
  // session id than this file's basename — the shape a `/fork` or `pi --fork` child arrives in.
  const cwd = scaffoldRepo();
  const file = plantSession(
    cwd,
    [
      {
        run_id: "01RID",
        pi_session_id: "parent.jsonl",
        mode: "read-write",
        perk_version: "3.4.0",
        stage: "implement",
      },
      { active_plan_ref: planRef("42", { objective_id: "7" }) },
      { session_naming: { title: "Add retry", node: "1.1" } },
    ],
    { fileName: "planted-child.jsonl" },
  );
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const state = h.workflowState();
    assert.equal(h.sentinel()?.source, "fork");
    assert.equal(state.run_id, "01RID.1");
    assert.equal(state.predecessor, "01RID");
    // The fork entry carries no `stage`; the origin is the parent's claim entry heading the branch.
    assert.equal(h.session.sessionManager.getSessionName(), CLAIMED_NAME);
    assert.equal(state.session_name, CLAIMED_NAME);
    assert.deepEqual(state.session_naming, { title: "Add retry", node: "1.1" });
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: an adopted env-child has no origin and stays unnamed", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "plan",
      consumed: true,
      piSessionId: "parent.jsonl",
      extra: { naming: { title: "Parent title" } },
    },
  });
  recordSessionPointer(cwd, "01RID", "implementation", "main", {
    pi_session_id: "parent.jsonl",
    session_file: "/sessions/parent.jsonl",
    parent_pi_session_id: null,
    at: "2026-06-01T00:00:00Z",
  });
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.sentinel()?.source, "env-child");
    assert.equal(h.session.sessionManager.getSessionName(), undefined);
    const state = h.workflowState();
    assert.equal(state.session_name, undefined);
    assert.equal(state.session_naming, undefined);
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a minted hand-run session stays unnamed even after a warm refinement stage append", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    { run_id: "01MINT", pi_session_id: "planted-parent.jsonl" },
    { stage: "objective-refine" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.session.sessionManager.getSessionName(), undefined);
    assert.equal(h.workflowState().session_name, undefined);
    const appended = h.session.sessionManager
      .getBranch()
      .filter(
        (entry) =>
          entry.type === "custom" &&
          entry.customType === WORKFLOW_STATE_TYPE &&
          typeof entry.data === "object" &&
          entry.data !== null &&
          "session_name" in entry.data,
      );
    assert.deepEqual(appended, []);
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a failing setSessionName is one warning; startup still completes and the old name stands", async () => {
  const { cwd, h } = await claimedImplementSession();
  try {
    h.session.setSessionName = () => {
      throw new Error("boom");
    };
    // Move the CHECKOUT binding: the kept arm re-reads and re-links it, so the composed name
    // really changes (a raw branch append would be reconciled back to the binding).
    writePlanRef(cwd, planRef("43", { objective_id: "7" }));
    await h.emitSessionStart();
    const warnings = namingWarnings(h);
    assert.equal(warnings.length, 1, JSON.stringify(h.notifyEvents));
    assert.match(warnings[0]?.message ?? "", /boom/);
    assert.equal(h.sentinel()?.source, "session"); // startup reached its final step
    assert.equal(h.session.sessionManager.getSessionName(), CLAIMED_NAME);
  } finally {
    h.dispose();
  }
});

test("naming: a failed ownership append leaves the new name in place and freezes it as preserved", async () => {
  const { cwd, h } = await claimedImplementSession();
  try {
    const manager = h.session.sessionManager;
    const realAppend = manager.appendCustomEntry.bind(manager);
    manager.appendCustomEntry = (type, data) => {
      if (
        type === WORKFLOW_STATE_TYPE &&
        typeof data === "object" &&
        data !== null &&
        "session_name" in data
      ) {
        throw new Error("append refused");
      }
      return realAppend(type, data);
    };
    writePlanRef(cwd, planRef("43", { objective_id: "7" }));
    await h.emitSessionStart();
    const renamed = "implement | plan #43 | objective #7 / 1.1 | Add retry";
    assert.equal(manager.getSessionName(), renamed); // Pi's name moved…
    assert.equal(h.workflowState().session_name, CLAIMED_NAME); // …but the record did not
    assert.equal(namingWarnings(h).length, 1);

    // The next start sees a current name without an ownership record → preserved: no write,
    // no new warning.
    manager.appendCustomEntry = realAppend;
    const setCalls: string[] = [];
    h.session.setSessionName = (name: string) => {
      setCalls.push(name);
    };
    await h.emitSessionStart();
    assert.deepEqual(setCalls, []);
    assert.equal(namingWarnings(h).length, 1);
    assert.equal(manager.getSessionName(), renamed);
  } finally {
    h.dispose();
  }
});

// ------------------------------------------------- the draft-tool and linking-save refreshes

/** The `perk plan save --json` payload shape (`pi/v1/plan.test.ts::PLAN_JSON`). */
const PLAN_SAVE_JSON = JSON.stringify({
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

/** The objective-linked variant: the cold door wrote `objective_id` and committed the node. */
const OBJECTIVE_PLAN_SAVE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  issue: { id: "42", url: "https://gh/o/r/issues/42", existed: false },
  plan_ref: {
    provider: "github",
    pr_id: "42",
    url: "https://gh/o/r/issues/42",
    labels: ["perk:plan"],
    objective_id: "7",
  },
  objective_node: { linked: true, node: "2.2", status: "in_progress", error: null },
  cached: true,
  dry_run: false,
});

/** The `perk objective create --json` payload shape (`pi/v1/objectiveAuthoring.test.ts`). */
const OBJECTIVE_CREATE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  objective: { id: "7", url: "https://gh/o/r/issues/7", existed: false },
  dry_run: false,
});

const DRAFT_PLAN = "# Add retry\n\nSteps.\n";

/** A cold `plan` session whose cold door answers every save with `stdout`. */
async function planSession(stdout: string) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const bin = fakePerk(cwd, { stdout });
  return loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
}

function name(h: Awaited<ReturnType<typeof loadPerkSession>>): string | undefined {
  return h.session.sessionManager.getSessionName();
}

test("naming: a planning session becomes plan | <title> after plan_draft and plan | plan #N | <title> after the save", async () => {
  const h = await planSession(PLAN_SAVE_JSON);
  try {
    assert.equal(name(h), "plan");
    const drafted = await h.invokeTool("plan_draft", { plan: DRAFT_PLAN });
    assert.equal((drafted.details as { ok?: boolean }).ok, true);
    assert.equal(name(h), "plan | Add retry");
    assert.deepEqual(h.workflowState().session_naming, { title: "Add retry" });
    // The approval-path surface (the lower-fidelity one): the thunk sits on the shared
    // `savePlan` path, so every save surface names alike.
    await h.invokeCommand("plan-save");
    assert.equal(name(h), "plan | plan #42 | Add retry");
    assert.equal(h.workflowState().session_name, "plan | plan #42 | Add retry");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: an objective-plan factory session keeps its node through draft, save and reopen", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: "01RID",
      mode: "read-only",
      stage: "objective-plan",
      extra: {
        objective_id: "7",
        node_id: "2.2",
        naming: { title: "Node description", node: "2.2" },
      },
    },
  });
  const bin = fakePerk(cwd, { stdout: OBJECTIVE_PLAN_SAVE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    assert.equal(name(h), "objective-plan | objective #7 / 2.2 | Node description");
    await h.invokeTool("plan_draft", { plan: "# Real title\n\nSteps.\n" });
    // override: the draft's title replaced the door's node description.
    assert.equal(name(h), "objective-plan | objective #7 / 2.2 | Real title");
    await h.invokeCommand("plan-save");
    assert.equal(name(h), "objective-plan | plan #42 | objective #7 / 2.2 | Real title");
    assert.equal(h.workflowState().objective_node_claim, null, "the claim was cleared");
    // The kept arm's `fill` replay of the launch-era hints: the door's `node` hint keeps `/ 2.2`
    // once the claim is gone, and the replayed `Node description` never reverts `Real title`.
    await h.emitSessionStart();
    assert.equal(name(h), "objective-plan | plan #42 | objective #7 / 2.2 | Real title");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: an objective-author session gains objective #O after the save", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  const bin = fakePerk(cwd, { stdout: OBJECTIVE_CREATE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    assert.equal(name(h), "objective-author");
    const roadmap = [{ id: "1.1", description: "first" }];
    await h.invokeTool("objective_draft", {
      prose: "# Objective\n\nThe why.\n",
      title: "Ship retries",
      roadmap,
    });
    assert.equal(name(h), "objective-author | Ship retries");
    await h.invokeCommand("objective-save");
    assert.equal(name(h), "objective-author | objective #7 | Ship retries");
    assert.deepEqual(namingWarnings(h), []);
    // Declared-else-derived under override: a title-less redraft names from its heading.
    await h.invokeTool("objective_draft", { prose: "# Derived\n\nThe why.\n", roadmap });
    assert.equal(name(h), "objective-author | objective #7 | Derived");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a gist session is <stage> | <title> after gist_draft", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "gist-author" },
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.equal(name(h), "gist-author");
    await h.invokeTool("gist_draft", { prose: "# Faster reviews\n\nWhy.\n" });
    assert.equal(name(h), "gist-author | Faster reviews");
    await h.invokeTool("gist_draft", { prose: "# Faster reviews\n\nWhy.\n", title: "Declared" });
    assert.equal(name(h), "gist-author | Declared");
    // Heading-less + title-less: `{}` under override leaves the stored title alone.
    await h.invokeTool("gist_draft", { prose: "Just prose, no heading.\n" });
    assert.equal(name(h), "gist-author | Declared");
    assert.doesNotMatch(name(h) ?? "", /objective|plan/, "no gist/plan/objective segment");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a foreign /name before the draft is preserved through every refresh — hints still persist", async () => {
  const h = await planSession(PLAN_SAVE_JSON);
  try {
    h.session.setSessionName("mine");
    await h.invokeTool("plan_draft", { plan: DRAFT_PLAN });
    assert.equal(name(h), "mine");
    await h.invokeCommand("plan-save");
    assert.equal(name(h), "mine");
    const state = h.workflowState();
    assert.equal(state.session_name, "plan", "perk's record is the startup name");
    assert.deepEqual(state.session_naming, { title: "Add retry" }, "learned facts persist");
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});

test("naming: a plan_draft failure never refreshes", async () => {
  const h = await planSession(PLAN_SAVE_JSON);
  try {
    const result = await h.invokeTool("plan_draft", { plan: "   \n" });
    assert.equal((result.details as { error_type?: string }).error_type, "invalid_input");
    assert.equal(name(h), "plan");
    assert.equal(h.workflowState().session_naming, undefined);
  } finally {
    h.dispose();
  }
});

test("naming: the kept arm fills only missing hint fields — a later-learned title survives reopen", async () => {
  const { h } = await claimedImplementSession();
  try {
    h.session.sessionManager.appendCustomEntry(WORKFLOW_STATE_TYPE, {
      session_naming: { title: "Learned", node: "1.1" },
    });
    await h.emitSessionStart();
    assert.equal(
      h.session.sessionManager.getSessionName(),
      "implement | plan #42 | objective #7 / 1.1 | Learned",
    );
    assert.deepEqual(h.workflowState().session_naming, { title: "Learned", node: "1.1" });
    assert.deepEqual(namingWarnings(h), []);
  } finally {
    h.dispose();
  }
});
