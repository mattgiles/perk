// Split from checkpoints.test.ts: the harness-heavy live session round-trip (seed from
// `## Steps`, advance on turn_end) and the generated-steps-for-prose-plans section.
// A sibling file so Node's --test cross-file parallelism runs it as its own child process.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxToolCall, registerFauxProvider } from "@earendil-works/pi-ai";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type PlanRef, planBodyPath, sessionDataDir } from "../substrate/cache.ts";
import { digestSessionData } from "../substrate/sessionData.ts";
import type { SessionArtifactPointer, WorkflowState } from "../substrate/workflowState.ts";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  CHECKPOINT_TYPE,
  isInert,
  isStaleCtxError,
  rebuildCheckpoint,
  STEPS_ARTIFACT_NAME,
  STEPS_CONTEXT_TYPE,
} from "./checkpoints.ts";

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

const PLAN_WITH_STEPS = `# Add retry

## Summary
Add retry to the gateway.

## Steps
1. Add the retry helper
2. Wire it into the client
3. Add a test

## Test plan
Run the suite.
`;

// --- live round-trip --------------------------------------------------------------------

test("session_start seeds checkpoints from the plan body's `## Steps`", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const state = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    assert.equal(state.steps.length, 3, "seeded 3 steps from `## Steps`");
    assert.equal(isInert(state), false);
  } finally {
    h.dispose();
  }
});

test("a plan WITHOUT `## Steps` yields an inert checkpoint (no crash)", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), "# T\n\n## Summary\nProse only.\n", "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.ok(isInert(rebuildCheckpoint(h.session.sessionManager.getBranch() as never)));
  } finally {
    h.dispose();
  }
});

test("rebuild restored on session_tree across a seeded checkpoint", async () => {
  const cwd = scaffoldRepo();
  // Seed entry, then an assistant [DONE:1], then a second checkpoint marker — navigation rebuilds.
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: CHECKPOINT_TYPE,
        data: {
          steps: [
            { step: 1, text: "one", completed: false },
            { step: 2, text: "two", completed: false },
          ],
        },
      },
    },
    { assistant: "completed [DONE:1]" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const ids = h.entryIds();
    await h.navigateTo(ids[0] as string); // navigate to the seed marker -> session_tree rebuild
    const atSeed = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    // At the seed marker (no assistant msgs after it on this branch) nothing is complete.
    assert.equal(
      atSeed.steps.every((s) => !s.completed),
      true,
    );
  } finally {
    h.dispose();
  }
});

test("session_compact re-renders the 📋 status over a seeded checkpoint branch", async () => {
  const cwd = scaffoldRepo();
  // Seed marker (two steps) + an assistant [DONE:1] after it -> rebuild yields 1/2 done, current 2.
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: CHECKPOINT_TYPE,
        data: {
          steps: [
            { step: 1, text: "one", completed: false },
            { step: 2, text: "two", completed: false },
          ],
        },
      },
    },
    { assistant: "completed [DONE:1]" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const before = h.statuses.filter((s) => s.slot === "perk").length;
    await h.emitLifecycle({ type: "session_compact" });
    const perkStatuses = h.statuses.filter((s) => s.slot === "perk");
    assert.ok(perkStatuses.length > before, "session_compact published a fresh status");
    assert.equal(perkStatuses.at(-1)?.value, "📋 1/2 · ▸2", "rebuilt progress re-rendered");
  } finally {
    h.dispose();
  }
});

test("isStaleCtxError matches the pi-core compaction race only", () => {
  assert.equal(isStaleCtxError(new Error("ctx is stale after session replacement")), true);
  assert.equal(isStaleCtxError("stale after session replacement"), true);
  assert.equal(isStaleCtxError(new Error("some unrelated rebuild bug")), false);
  assert.equal(isStaleCtxError(null), false);
});

test("coarse fallback: active prose plan sets `📋 <stage>` status; no plan clears", async () => {
  // Active plan-ref + a handoff carrying a stage, but NO `## Steps` body -> coarse status.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), "# T\n\n## Summary\nProse only.\n", "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const last = h.statuses.filter((s) => s.slot === "perk").at(-1);
    assert.ok(last?.value?.startsWith("📋 implement"), `coarse status set: ${last?.value}`);
    const widget = h.widgets.filter((w) => w.slot === "perk-checkpoints").at(-1);
    assert.ok(widget?.value?.[0]?.includes("prose plan"), "widget explains prose plan");
    assert.equal(widget?.placement, "belowEditor", "coarse widget placed belowEditor (D4)");
  } finally {
    h.dispose();
  }
});

test("steps widget: themed window at belowEditor — ≤4 step lines + elision (D1/D3/D4)", async () => {
  const cwd = scaffoldRepo();
  const planBody = `# Big\n\n## Steps\n1. one\n2. two\n3. three\n4. four\n5. five\n6. six\n`;
  writeFileSync(planBodyPath(cwd), planBody, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const widget = h.widgets.filter((w) => w.slot === "perk-checkpoints").at(-1);
    assert.ok(widget?.value, "steps widget rendered");
    assert.equal(widget?.placement, "belowEditor", "steps widget placed belowEditor (D4)");
    const lines = widget?.value as string[];
    const stepLines = lines.filter((l) => /^[✓▸○] /.test(l));
    assert.equal(stepLines.length, 4, `≤4 step lines: ${JSON.stringify(lines)}`);
    assert.ok(
      lines.some((l) => l.includes("… +2 later")),
      `elision marker rendered: ${JSON.stringify(lines)}`,
    );
    assert.ok(stepLines[0]?.startsWith("▸ 1."), "current step renders the ▸ glyph");
    // The status chip carries the full summary with the ▸ glyph (no retired ▶).
    const status = h.statuses.filter((s) => s.slot === "perk").at(-1);
    assert.equal(status?.value, "📋 0/6 · ▸1");
  } finally {
    h.dispose();
  }
});

test("/checkpoints notifies a single line (D8): done/total · ▸n <current step text>", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    await h.invokeCommand("checkpoints");
    // Skip the uniform `perk: checkpoints — running…` entry toast; assert the status line.
    const msg = h.notifies.find((m) => m.includes("checkpoints") && m.includes("·"));
    assert.ok(msg, `notified: ${JSON.stringify(h.notifies)}`);
    assert.ok(!msg.includes("\n"), `one line, no newlines: ${JSON.stringify(msg)}`);
    assert.ok(
      msg.includes("0/3 · ▸1 Add the retry helper"),
      `one-line format: ${JSON.stringify(msg)}`,
    );
  } finally {
    h.dispose();
  }
});

test("coarse fallback: no active plan clears status + widget", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), "# T\n\n## Summary\nProse only.\n", "utf8");
  // No workflow-state entries -> no active plan.
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const last = h.statuses.filter((s) => s.slot === "perk").at(-1);
    assert.equal(last?.value, undefined, "status cleared with no active plan");
  } finally {
    h.dispose();
  }
});

test("/checkpoints headless: uses console (no rich-UI throw)", async () => {
  const cwd = scaffoldRepo();
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    headful: false,
  });
  try {
    // Must not throw on the headless path (setStatus/setWidget are guarded by hasUI).
    await h.invokeCommand("checkpoints");
    assert.ok(true, "headless /checkpoints did not throw");
  } finally {
    h.dispose();
  }
});

// --- generated steps for prose plans ----------------------------------------------

const PROSE_PLAN = "# T\n\n## Summary\nProse only.\n";

/** Faux `set_plan_steps` happy response (markers echoed to exercise the sanitizer). */
const fauxStepsResponse = () =>
  fauxAssistantMessage(
    [fauxToolCall("set_plan_steps", { steps: ["1. Add the module", "Wire it in", "Test it"] })],
    { stopReason: "toolUse" },
  );

/** Write a pointer-valid generated-steps artifact for run `01RID`; returns the pointer. */
function plantStepsArtifact(
  cwd: string,
  artifact: { plan_id: string; plan_body_digest: string; steps: string[] },
): SessionArtifactPointer {
  const dir = sessionDataDir(cwd, "01RID");
  mkdirSync(dir, { recursive: true });
  const content = `${JSON.stringify(artifact, null, 2)}\n`;
  writeFileSync(join(dir, STEPS_ARTIFACT_NAME), content, "utf8");
  return {
    run_id: "01RID",
    name: STEPS_ARTIFACT_NAME,
    path: join(".perk", "workflow", "scratch", "runs", "01RID", "data", STEPS_ARTIFACT_NAME),
    digest: digestSessionData(content),
    at: new Date().toISOString(),
  };
}

test("prose plan under PERK_NO_LLM: coarse fallback unchanged, zero model calls", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  // Harness default env keeps PERK_NO_LLM=1 — the offline gate stays on.
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 0, "the gate prevents any model call");
    const branch = h.session.sessionManager.getBranch() as never as { customType?: string }[];
    assert.equal(
      branch.some((e) => e.customType === CHECKPOINT_TYPE),
      false,
      "no checkpoint entry seeded",
    );
    const widget = h.widgets.filter((w) => w.slot === "perk-checkpoints").at(-1);
    assert.ok(
      widget?.value?.[0]?.includes("prose plan — no `## Steps` checklist"),
      `coarse widget byte-identical to today: ${JSON.stringify(widget?.value)}`,
    );
  } finally {
    reg.unregister();
    h.dispose();
  }
});

test("prose implement plan: faux model generates the seed + once-only injection", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_NO_LLM: undefined, PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 1, "exactly one generation call");
    const state = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    assert.deepEqual(
      state.steps.map((s) => [s.step, s.text, s.completed]),
      [
        [1, "Add the module", false],
        [2, "Wire it in", false],
        [3, "Test it", false],
      ],
      "seeded from the sanitized generated steps",
    );
    // The artifact + provenance pointer landed (the reuse cache).
    const pointer = h.workflowState().session_artifacts?.[STEPS_ARTIFACT_NAME];
    assert.equal(pointer?.run_id, "01RID", "provenance pointer recorded");
    // The injection teaches the exact numbering...
    const injected = await h.emitBeforeAgentStart();
    const msg = injected.find((m) => m.customType === STEPS_CONTEXT_TYPE);
    assert.ok(msg, "steps-context injected for a generated checklist");
    assert.ok(String(msg?.content).includes("1. Add the module"), "numbered list in the content");
    assert.ok(String(msg?.content).includes("EXACTLY these numbers"), "numbering instruction");
    // /checkpoints flags the LLM-derived checklist.
    await h.invokeCommand("checkpoints");
    assert.ok(
      h.notifies.some((m) => m.includes("(generated)")),
      `/checkpoints appends (generated): ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    reg.unregister();
    h.dispose();
  }
});

test("once-only: a branch already carrying perk:steps-context is not re-injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: ACTIVE } },
    {
      custom: {
        type: CHECKPOINT_TYPE,
        data: { steps: [{ step: 1, text: "one", completed: false }] },
      },
    },
    { custom: { type: STEPS_CONTEXT_TYPE, data: {} } },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === STEPS_CONTEXT_TYPE),
      false,
      "branch already carries the steps context → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("artifact reuse: a digest-valid plan-steps artifact seeds without a model call", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  const pointer = plantStepsArtifact(cwd, {
    plan_id: "42",
    plan_body_digest: digestSessionData(PROSE_PLAN),
    steps: ["From the artifact", "Second cached step"],
  });
  const file = plantSession(cwd, [
    { ...ACTIVE, session_artifacts: { [STEPS_ARTIFACT_NAME]: pointer } },
  ]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_NO_LLM: undefined, PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 0, "artifact reuse skips the model");
    const state = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    assert.deepEqual(
      state.steps.map((s) => s.text),
      ["From the artifact", "Second cached step"],
    );
  } finally {
    reg.unregister();
    h.dispose();
  }
});

test("digest-mismatched artifact is ignored → regeneration", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  // The artifact was generated against a DIFFERENT (stale) plan body — must be ignored.
  const pointer = plantStepsArtifact(cwd, {
    plan_id: "42",
    plan_body_digest: digestSessionData("# stale plan body\n"),
    steps: ["Stale cached step", "Another stale step"],
  });
  const file = plantSession(cwd, [
    { ...ACTIVE, session_artifacts: { [STEPS_ARTIFACT_NAME]: pointer } },
  ]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_NO_LLM: undefined, PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 1, "stale artifact → regeneration");
    const state = rebuildCheckpoint(h.session.sessionManager.getBranch() as never);
    assert.deepEqual(
      state.steps.map((s) => s.text),
      ["Add the module", "Wire it in", "Test it"],
      "seeded from the fresh generation, not the stale artifact",
    );
  } finally {
    reg.unregister();
    h.dispose();
  }
});

test("non-implement stage never generates (coarse fallback)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  writeFileSync(planBodyPath(cwd), PROSE_PLAN, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_NO_LLM: undefined, PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 0, "plan stage → no generation call");
    assert.ok(isInert(rebuildCheckpoint(h.session.sessionManager.getBranch() as never)));
  } finally {
    reg.unregister();
    h.dispose();
  }
});

test("explicit `## Steps` plans: no generation, no injection, no (generated) suffix", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  writeFileSync(planBodyPath(cwd), PLAN_WITH_STEPS, "utf8");
  const file = plantSession(cwd, [ACTIVE]);
  const reg = registerFauxProvider();
  reg.setResponses([fauxStepsResponse()]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    model: reg.getModel(),
    env: { PERK_NO_LLM: undefined, PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(reg.state.callCount, 0, "explicit steps → never a model call");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === STEPS_CONTEXT_TYPE),
      false,
      "explicit steps → no steps-context injection",
    );
    await h.invokeCommand("checkpoints");
    // Skip the uniform `perk: checkpoints — running…` entry toast; assert the status line.
    const msg = h.notifies.find((m) => m.includes("checkpoints") && m.includes("·"));
    assert.ok(msg && !msg.includes("(generated)"), `no (generated) suffix: ${JSON.stringify(msg)}`);
  } finally {
    reg.unregister();
    h.dispose();
  }
});
