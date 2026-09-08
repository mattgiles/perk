// The authoring-context eligibility policy WIRED through the real bound extension: which
// installer injects what (plan guidance, the dedicated objective/gist contexts, the plannotator
// adapter flavors), on which evidence (a plan-family cold stage, the warm `plan_authoring`
// intent, a dedicated authoring stage), and for whom (never a native runner child, never a bare
// read-only gate) — plus the retention side: owned copies follow selection across `/plan`
// on/off, tree navigation, compaction, reload and separate bound sessions, while user input and
// the gate's own `[READ-ONLY MODE]` guidance are never touched. The pure policy table is pinned
// in `authoring/context/eligibility.test.ts`; the helper mechanics in `contextInjection.test.ts`.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { GIST_AUTHOR_CONTEXT_TYPE } from "../../authoring/gist/prose.ts";
import { OBJECTIVE_AUTHOR_CONTEXT_TYPE } from "../../authoring/objective/prose.ts";
import { PLAN_CONTEXT_TYPE, PLAN_MARKER } from "../../authoring/plan/prose.ts";
import { loadPerkSession, plantRawSession, scaffoldRepo } from "../../testing/harness.ts";
import { PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE } from "./providers/plannotator.ts";
import { PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE } from "./providers/tombell.ts";

const MODE_CONTEXT_TYPE = "perk:mode-context";
// The adapter flavor markers, as literals (the provider suites pin the same bytes).
const PLAN_ADAPTER_PLANNOTATOR_MARKER = "[PLAN ADAPTER: PLANNOTATOR]";
const OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER = "[OBJECTIVE ADAPTER: PLANNOTATOR]";
const GIST_ADAPTER_PLANNOTATOR_MARKER = "[GIST ADAPTER: PLANNOTATOR]";
const AUTHORING_TYPES = [
  PLAN_CONTEXT_TYPE,
  OBJECTIVE_AUTHOR_CONTEXT_TYPE,
  GIST_AUTHOR_CONTEXT_TYPE,
  PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
  PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
];

const runnerPacket = {
  PI_SUBAGENT_CHILD: "1",
  PI_SUBAGENT_EXTENSION_BINDINGS: '{"perk.parent-restrictions/1":{"readOnly":true}}',
};

type Harness = Awaited<ReturnType<typeof loadPerkSession>>;

/** The customTypes the next turn would inject (order-free). */
async function injectedTypes(h: Harness): Promise<Set<string>> {
  return new Set(
    (await h.emitBeforeAgentStart())
      .map((m) => m.customType)
      .filter((t): t is string => typeof t === "string"),
  );
}

function selectPlannotator(cwd: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[providers]\nplan = "plannotator-plan"\n',
    "utf8",
  );
}

/** The mixed message list every retention pass must hand back minus ONLY the named owned copies. */
function preservedInput(): Record<string, unknown>[] {
  return [
    { role: "user", content: `${PLAN_MARKER} quoted by the human` },
    {
      role: "user",
      content: [
        {
          type: "text",
          text: `<untrusted_draft>\n${PLAN_MARKER}\n${PLAN_ADAPTER_PLANNOTATOR_MARKER}\n</untrusted_draft>`,
        },
      ],
    },
    { role: "user", content: `Explore the repo.\n\n${PLAN_MARKER}\nhistorical cold seed` },
    { role: "assistant", content: [{ type: "text", text: `I read ${PLAN_MARKER} above` }] },
    { customType: MODE_CONTEXT_TYPE, content: "[READ-ONLY MODE]\nthe gate's own guidance" },
    { role: "user", content: "a normal message" },
  ];
}

// --- warm intent: /plan --------------------------------------------------------------------------

test("warm /plan records the intent beside the mode; guidance follows the intent, never the stage; off removes the owned copy and preserves input", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  try {
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal(h.workflowState().plan_authoring, true, "the explicit intent bit (§8.3)");
    assert.equal(h.workflowState().stage, undefined, "no stage is invented");
    let types = await injectedTypes(h);
    assert.ok(types.has(PLAN_CONTEXT_TYPE), "plan guidance selected on the warm intent");
    assert.ok(types.has(MODE_CONTEXT_TYPE), "the gate's own guidance rides alongside");
    assert.equal(types.has(OBJECTIVE_AUTHOR_CONTEXT_TYPE), false);
    assert.equal(types.has(GIST_AUTHOR_CONTEXT_TYPE), false);

    // While selected: the owned copy is retained, everything else untouched.
    const ownedCopy = { customType: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\nlive copy` };
    assert.deepEqual(await h.emitContext([ownedCopy, ...preservedInput()]), [
      ownedCopy,
      ...preservedInput(),
    ]);

    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    assert.equal(h.workflowState().plan_authoring, false, "exit records the intent off");
    types = await injectedTypes(h);
    assert.equal(types.has(PLAN_CONTEXT_TYPE), false, "no guidance once off");
    // Off: ONLY the owned plan copy goes; the human's quotes, the draft, the cold seed, the
    // assistant turn and the gate's own (independently retained) guidance are untouched.
    const surviving = await h.emitContext([ownedCopy, ...preservedInput()]);
    assert.deepEqual(
      surviving,
      preservedInput().filter((m) => m.customType !== MODE_CONTEXT_TYPE),
      "user input byte-for-byte; the gate strips its own copy off-gate by its own rule",
    );
  } finally {
    h.dispose();
  }
});

test("a legacy stage-less read-only session stays restricted with NO plan guidance until /plan is re-entered", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: { run_id: "01RID", mode: "read-only" } } },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, true);
    let types = await injectedTypes(h);
    assert.ok(types.has(MODE_CONTEXT_TYPE), "the restriction guidance still delivers");
    for (const t of AUTHORING_TYPES) assert.equal(types.has(t), false, `${t}: not inferred`);
    // A stale owned copy from the old inferring behavior is retired; input stays.
    assert.deepEqual(
      await h.emitContext([
        { customType: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\nstale` },
        ...preservedInput(),
      ]),
      preservedInput(),
    );
    // Re-entry: /plan off (exit) then /plan on establishes the intent explicitly.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().plan_authoring, true);
    types = await injectedTypes(h);
    assert.ok(types.has(PLAN_CONTEXT_TYPE), "guidance after explicit re-entry");
  } finally {
    h.dispose();
  }
});

// --- cold stages -----------------------------------------------------------------------------

test("cold stage shapes: the plan family selects plan guidance; the dedicated stages take precedence; unknown/worktree stages select nothing", async () => {
  const cases: {
    stage: string;
    mode: "read-only" | "read-write";
    expect: string[];
  }[] = [
    { stage: "plan", mode: "read-only", expect: [PLAN_CONTEXT_TYPE] },
    { stage: "save", mode: "read-only", expect: [PLAN_CONTEXT_TYPE] },
    { stage: "objective-plan", mode: "read-only", expect: [PLAN_CONTEXT_TYPE] },
    { stage: "objective-author", mode: "read-only", expect: [OBJECTIVE_AUTHOR_CONTEXT_TYPE] },
    { stage: "gist-author", mode: "read-only", expect: [GIST_AUTHOR_CONTEXT_TYPE] },
    { stage: "objective-save", mode: "read-only", expect: [] },
    { stage: "gist-save", mode: "read-only", expect: [] },
    { stage: "audit", mode: "read-only", expect: [] },
    { stage: "not-a-stage", mode: "read-only", expect: [] },
    { stage: "implement", mode: "read-write", expect: [] },
    { stage: "plan", mode: "read-write", expect: [] },
  ];
  for (const c of cases) {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: c.mode, stage: c.stage } });
    const h = await loadPerkSession({
      cwd,
      sessionManager: SessionManager.inMemory(cwd),
      env: { PERK_RUN_ID: "01RID" },
    });
    try {
      const types = await injectedTypes(h);
      const authoring = AUTHORING_TYPES.filter((t) => types.has(t));
      assert.deepEqual(authoring, c.expect, `${c.stage}/${c.mode}`);
      assert.equal(
        types.has(MODE_CONTEXT_TYPE),
        c.mode === "read-only",
        `${c.stage}: the gate's guidance follows the mode alone`,
      );
    } finally {
      h.dispose();
    }
  }
});

test("a stray warm intent never turns a dedicated authoring stage into a plan author", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: {
          run_id: "01RID",
          mode: "read-only",
          stage: "objective-author",
          plan_authoring: true,
        },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const types = await injectedTypes(h);
    assert.ok(types.has(OBJECTIVE_AUTHOR_CONTEXT_TYPE));
    assert.equal(types.has(PLAN_CONTEXT_TYPE), false);
  } finally {
    h.dispose();
  }
});

// --- runner children -------------------------------------------------------------------------

test("a native runner child receives no authoring or adapter guidance over inherited authoring history — floor true/false/invalid, stage present or absent — while its restrictions and child tools stay intact", async () => {
  const bindings = [
    { label: "floor true", value: runnerPacket.PI_SUBAGENT_EXTENSION_BINDINGS },
    { label: "floor false", value: '{"perk.parent-restrictions/1":{"readOnly":false}}' },
    { label: "invalid envelope", value: "not json" },
    { label: "absent envelope", value: undefined },
  ];
  const histories: Record<string, unknown>[] = [
    { run_id: "01RID", mode: "read-only", stage: "plan", plan_authoring: true },
    { run_id: "01RID", mode: "read-only", plan_authoring: true },
    { run_id: "01RID", mode: "read-only", stage: "objective-author" },
    { run_id: "01RID", mode: "read-only", stage: "gist-author" },
  ];
  for (const binding of bindings) {
    for (const history of histories) {
      const cwd = scaffoldRepo();
      selectPlannotator(cwd);
      const file = plantRawSession(cwd, [
        { custom: { type: "perk:workflow-state", data: history } },
        { customMessage: { type: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\ninherited copy` } },
      ]);
      const h = await loadPerkSession({
        cwd,
        sessionManager: SessionManager.open(file),
        systemPrompt: '<active_agent name="perk.draft-reviewer"/>\n\nReport rubric',
        env: {
          PERK_RUN_ID: undefined,
          PI_SUBAGENT_CHILD: "1",
          PI_SUBAGENT_EXTENSION_BINDINGS: binding.value,
        },
      });
      const label = `${binding.label} / ${JSON.stringify(history)}`;
      try {
        assert.equal(h.workflowState().mode, "read-only", label);
        const types = await injectedTypes(h);
        for (const t of AUTHORING_TYPES) assert.equal(types.has(t), false, `${label}: ${t}`);
        assert.ok(types.has(MODE_CONTEXT_TYPE), `${label}: reviewer mode guidance intact`);
        // The inherited owned copy is retired from the outgoing context; input is preserved.
        assert.deepEqual(
          await h.emitContext([
            { customType: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\ninherited copy` },
            ...preservedInput(),
          ]),
          preservedInput(),
          label,
        );
        // Restrictions and the engine's child tools are untouched by the suppression.
        for (const tool of ["write", "edit"])
          assert.equal(
            (await h.emitToolCall(tool, { path: "x" }))?.block,
            true,
            `${label}: ${tool}`,
          );
        assert.equal(
          (await h.emitToolCall("bash", { command: "rm -rf build" }))?.block,
          true,
          `${label}: unsafe bash`,
        );
        assert.equal(
          (await h.emitToolCall("bash", { command: "git status" }))?.block,
          undefined,
          `${label}: inspection bash`,
        );
        for (const tool of ["structured_output", "contact_supervisor"])
          assert.equal(
            (await h.emitToolCall(tool, { value: {} }))?.block,
            undefined,
            `${label}: ${tool}`,
          );
      } finally {
        h.dispose();
      }
    }
  }
});

test("the runner bit is activation-local: a reload without it in the SAME process restores eligibility over the same branch", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-only", stage: "plan" },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined, ...runnerPacket },
  });
  try {
    assert.equal((await injectedTypes(h)).has(PLAN_CONTEXT_TYPE), false, "suppressed as a runner");
    await h.reload({ PI_SUBAGENT_CHILD: undefined, PI_SUBAGENT_EXTENSION_BINDINGS: undefined });
    assert.equal(
      (await injectedTypes(h)).has(PLAN_CONTEXT_TYPE),
      true,
      "the same branch is eligible once the activation is not a runner",
    );
  } finally {
    h.dispose();
  }
});

// --- lifecycle: navigation, compaction, reload, separate sessions -----------------------------

test("retention follows selection across tree navigation, compaction and reload; dedup re-delivers once compaction drops the live copy", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  try {
    const manager = h.session.sessionManager;
    const beforeEnter = manager.getLeafId();
    assert.ok(beforeEnter !== null);
    await h.invokeCommand("plan");
    const ownedCopy = { customType: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\nlive copy` };

    // On the eligible leaf: retained.
    assert.deepEqual(await h.emitContext([ownedCopy, ...preservedInput()]), [
      ownedCopy,
      ...preservedInput(),
    ]);
    // Navigate before the enter: the branch carries no intent → the owned copy is retired.
    await h.navigateTo(beforeEnter);
    assert.equal(h.workflowState().plan_authoring, undefined);
    assert.deepEqual(
      await h.emitContext([ownedCopy, ...preservedInput()]),
      preservedInput().filter((m) => m.customType !== MODE_CONTEXT_TYPE),
    );
    // Back onto the eligible leaf: retained again, and delivery resumes.
    const enterLeaf = manager.getLeafId();
    const ids = h.entryIds();
    const eligibleLeaf = ids[ids.length - 1];
    assert.ok(eligibleLeaf !== undefined && enterLeaf !== eligibleLeaf);
    await h.navigateTo(eligibleLeaf);
    assert.equal(h.workflowState().plan_authoring, true);
    assert.deepEqual(await h.emitContext([ownedCopy, ...preservedInput()]), [
      ownedCopy,
      ...preservedInput(),
    ]);

    // Deliver, persist the copy the way Pi would, then compact it out of the live projection:
    // the once-only dedup re-delivers on the next turn (the historical entry stays on the branch).
    assert.ok((await injectedTypes(h)).has(PLAN_CONTEXT_TYPE));
    manager.appendCustomMessageEntry(PLAN_CONTEXT_TYPE, ownedCopy.content, false);
    assert.equal((await injectedTypes(h)).has(PLAN_CONTEXT_TYPE), false, "the live copy dedups");
    const kept = manager.appendMessage({
      role: "assistant",
      content: [{ type: "text", text: "recent planning work" }],
      api: "t",
      provider: "t",
      model: "t",
      usage: {},
      stopReason: "stop",
      timestamp: 1,
    } as never);
    manager.appendCompaction(`a summary quoting ${PLAN_MARKER} is not a live copy`, kept, 100);
    assert.ok((await injectedTypes(h)).has(PLAN_CONTEXT_TYPE), "re-delivered after compaction");

    // Reload on the same leaf: eligibility and retention are rebuilt from the branch.
    await h.reload();
    assert.equal(h.workflowState().plan_authoring, true);
    assert.deepEqual(await h.emitContext([ownedCopy, ...preservedInput()]), [
      ownedCopy,
      ...preservedInput(),
    ]);
  } finally {
    h.dispose();
  }
});

test("separate bound sessions never share eligibility: /plan in one leaves the other unselected", async () => {
  const cwdA = scaffoldRepo();
  const cwdB = scaffoldRepo();
  const a = await loadPerkSession({ cwd: cwdA, sessionManager: SessionManager.inMemory(cwdA) });
  try {
    await a.invokeCommand("plan");
    assert.ok((await injectedTypes(a)).has(PLAN_CONTEXT_TYPE));
    const b = await loadPerkSession({ cwd: cwdB, sessionManager: SessionManager.inMemory(cwdB) });
    try {
      assert.equal(b.workflowState().plan_authoring, undefined);
      assert.equal((await injectedTypes(b)).has(PLAN_CONTEXT_TYPE), false);
      assert.deepEqual(
        await b.emitContext([
          { customType: PLAN_CONTEXT_TYPE, content: `${PLAN_MARKER}\nnot this session's` },
          { role: "user", content: "keep me" },
        ]),
        [{ role: "user", content: "keep me" }],
      );
    } finally {
      b.dispose();
    }
  } finally {
    a.dispose();
  }
});

// --- plannotator flavors -------------------------------------------------------------------

test("plannotator: a plan→objective transition retires the obsolete plan-adapter flavor while the selected objective flavor survives; a bare gate selects nothing", async () => {
  const flavorCopy = (marker: string) => ({
    customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
    content: `${marker}\nadapter copy`,
  });
  const cases: { stage: string | undefined; keep: string | null }[] = [
    { stage: "plan", keep: PLAN_ADAPTER_PLANNOTATOR_MARKER },
    { stage: "objective-author", keep: OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER },
    { stage: "objective-save", keep: OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER },
    { stage: "gist-author", keep: GIST_ADAPTER_PLANNOTATOR_MARKER },
    { stage: "gist-save", keep: null },
    { stage: undefined, keep: null },
  ];
  for (const c of cases) {
    const cwd = scaffoldRepo();
    selectPlannotator(cwd);
    const file = plantRawSession(cwd, [
      {
        custom: {
          type: "perk:workflow-state",
          data: { run_id: "01RID", mode: "read-only", stage: c.stage },
        },
      },
    ]);
    const h = await loadPerkSession({
      cwd,
      sessionManager: SessionManager.open(file),
      env: { PERK_RUN_ID: undefined },
    });
    try {
      const all = [
        flavorCopy(PLAN_ADAPTER_PLANNOTATOR_MARKER),
        flavorCopy(OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER),
        flavorCopy(GIST_ADAPTER_PLANNOTATOR_MARKER),
      ];
      const surviving = await h.emitContext([...all, ...preservedInput()]);
      const expectedOwned = c.keep === null ? [] : [flavorCopy(c.keep)];
      assert.deepEqual(surviving, [...expectedOwned, ...preservedInput()], `stage ${c.stage}`);
      const injected = (await injectedTypes(h)).has(PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE);
      assert.equal(injected, c.keep !== null, `stage ${c.stage}: injection follows selection`);
    } finally {
      h.dispose();
    }
  }
});
