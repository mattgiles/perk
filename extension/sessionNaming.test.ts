// Live composition tests for perk-owned session names (contracts.md §8.71(h)) over a REAL bound
// AgentSession (offline): the cold claim names from the handoff's `naming` hints + the linked
// plan-ref; an unnamed pre-feature session gains its name on reopen; a human `/name` is
// preserved; an adopted env-child and a minted hand-run session (even after a warm refinement
// append) stay unnamed; a failing `setSessionName` is one warning and startup still completes; a
// failed ownership append leaves the new name and freezes it as `preserved`; the kept arm's `fill`
// policy never reverts a later-learned title. The owning behavior matrix lives in
// `session/sessionName.test.ts`; this suite pins the real Pi wiring around it.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, writePlanRef } from "./substrate/cache.ts";
import { recordSessionPointer } from "./substrate/sessionPointers.ts";
import { WORKFLOW_STATE_TYPE } from "./substrate/workflowState.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

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
