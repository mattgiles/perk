// Native discovery (contracts.md §8.40 "Native discovery"), driven through REAL
// bound AgentSessions (Mode A, fully offline) with Pi's real builtin `tool_search` loaded. A
// cohort session carries the converged `defaultTools: ["+tool_search"]`; a nonparticipant loads
// the SAME extension set without it, so the registries are identical and only activation differs.
// The nested-execution probe lives in its own file (`discoveryNested.test.ts`) so its fixture
// registration never enters this process's census.
//
// `PERK_PRINT_DISCOVERY_CENSUS=1` prints the census tables to stderr for transcription into the
// design record (`docs/design/native-discovery-pilot.md`).

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { before, test } from "node:test";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import { DRAFT_REVIEW_DOOR_PRIMES } from "../authoring/review/draftContext.ts";
import { REVIEW_BROWSER_PRIMES } from "../pi/v1/codeReview/browser.ts";
import { PLANNOTATOR_REVIEW_COMMAND } from "../pi/v1/providers/plannotatorHandoff.ts";
import { createFakeSubagents } from "../testing/fakeSubagents.ts";
import {
  COHORT_SETTINGS,
  fakePerk,
  gitInit,
  loadAt,
  type PerkSession,
  plantSession,
  type RecordedRequest,
  recordingRuntime,
  recordPerkInstalls,
  registerFakeTool,
  scaffoldRepo,
  spyInjections,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import type { PlanRef } from "./cache.ts";
import { sharedDir } from "./resources.ts";
import {
  discoveryFamily,
  isEligible,
  isPerkTool,
  perkToolNames,
  perkToolPolicy,
  perkToolsFor,
  REGISTRY_STAGE_IDS,
} from "./toolPolicy.ts";

before(ensureToolCatalog);

const PRINT = process.env.PERK_PRINT_DISCOVERY_CENSUS === "1";

/** A census-capable session: the real `tool_search` registered; `cohort` activates it. */
async function pilotSession(
  stage: string,
  mode: "read-only" | "read-write",
  cohort: boolean,
  opts: Omit<Parameters<typeof staged>[2] & object, "model" | "modelRuntime"> = {},
): Promise<{ h: PerkSession; rt: Awaited<ReturnType<typeof recordingRuntime>> }> {
  const rt = await recordingRuntime();
  const h = await staged(stage, mode, {
    headful: false,
    ...opts,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), ...(opts.extraExtensions ?? [])],
    ...(cohort ? { settings: { ...COHORT_SETTINGS, ...(opts.settings ?? {}) } } : {}),
  });
  return { h, rt };
}

/** The session's active perk names, sorted. */
function activePerk(h: PerkSession): string[] {
  return h.session.getActiveToolNames().filter(isPerkTool).sort();
}

/** The registered subset of a perk view, sorted — what perk's activation installs. */
function registeredSubset(h: PerkSession, view: readonly string[]): string[] {
  const registered = new Set(h.session.getAllTools().map((t) => t.name));
  return view.filter((name) => registered.has(name)).sort();
}

const isActive = (h: PerkSession, name: string): boolean =>
  h.session.getActiveToolNames().includes(name);

/** The backstop's verdict for a call to `name` (the block reason, or undefined when allowed). */
async function blocked(h: PerkSession, name: string): Promise<string | undefined> {
  const verdict = await h.emitToolCall(name, {});
  return verdict?.block === true ? verdict.reason : undefined;
}

/** A plan-ref linking the session to objective 7 (the stack-drive commands' fallback). */
const PLAN_REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://github.com/o/r/issues/42",
  labels: [],
  objective_id: "7",
  base: null,
};

/** The implement-eligible family members (read-write). */
const IMPLEMENT_MEMBERS = ["collect_review_wave", "objective_stack_status", "push_annotations"];

// --- 1. the cohort join ---------------------------------------------------------------------------

test("cohort join (A): the family re-registers deferred and leaves the request; tool_search is declared; one perk install; a re-emitted session_start changes nothing", async (t) => {
  const installs = recordPerkInstalls(t);
  const family = discoveryFamily();
  assert.deepEqual(
    family.filter((name) => isEligible(name, undefined, "implement", "read-write")).sort(),
    IMPLEMENT_MEMBERS,
  );
  const { h, rt } = await pilotSession("implement", "read-write", true);
  try {
    assert.equal(installs.length, 1, "a cohort startup is ONE perk install");
    for (const name of family) {
      assert.equal(h.toolInfo(name)?.exposure, "deferred", `${name} re-registered deferred`);
      assert.ok(!isActive(h, name), `${name} inactive`);
    }
    assert.deepEqual(
      activePerk(h),
      registeredSubset(h, perkToolsFor("implement", "read-write", true)),
    );
    rt.census();
    await h.session.prompt("census");
    const request = rt.last();
    assert.ok(request.tools.includes("tool_search"), "tool_search is declared");
    for (const name of family) {
      assert.ok(!request.tools.includes(name), `${name} undeclared`);
      assert.ok(!request.prompt.includes(`- ${name}: `), `${name}'s snippet left the prompt`);
      for (const line of h.registeredTool(name)?.promptGuidelines ?? [])
        assert.ok(!request.prompt.includes(line), `${name}'s guideline left the prompt`);
    }
    assert.equal(installs.length, 1, "the prompt turn installed nothing");

    // Prime one member, then re-emit session_start: nothing installs, the family stays deferred
    // (an already-deferred member is never re-registered — the seam test pins the skip), and the
    // primed member is kept.
    spyInjections(h);
    await h.invokeCommand("objective-sync", "7");
    assert.ok(isActive(h, "objective_stack_status"), "primed by the door");
    const installed = installs.length;
    await h.emitSessionStart();
    assert.equal(installs.length, installed, "nothing installed");
    for (const name of family) assert.equal(h.toolInfo(name)?.exposure, "deferred", name);
    assert.ok(isActive(h, "objective_stack_status"), "the primed member is kept");
  } finally {
    h.dispose();
  }
});

test("reload (A): a real /reload re-runs the factory — the family is deferred and inactive again, tool_search stays declared, a primed member is gone", async () => {
  const family = discoveryFamily();
  const { h, rt } = await pilotSession("implement", "read-write", true);
  try {
    spyInjections(h);
    await h.invokeCommand("objective-sync", "7");
    assert.ok(isActive(h, "objective_stack_status"), "primed before the reload");
    await h.reload();
    for (const name of family) {
      assert.equal(
        h.toolInfo(name)?.exposure,
        "deferred",
        `${name} re-deferred by the new activation`,
      );
      assert.ok(!isActive(h, name), `${name} inactive after the reload`);
    }
    rt.census();
    await h.session.prompt("census");
    assert.ok(rt.last().tools.includes("tool_search"), "tool_search stays declared");
    for (const name of family) assert.ok(!rt.last().tools.includes(name), `${name} undeclared`);
  } finally {
    h.dispose();
  }
});

// --- 2. nonparticipant preservation ---------------------------------------------------------------

test("nonparticipant preservation (A): tool_search inactive, absent, or a foreign namesake — the family stays direct, active and declared; a bare session still installs nothing", async (t) => {
  const installs = recordPerkInstalls(t);
  const family = discoveryFamily();
  const namesake = (pi: ExtensionAPI) => registerFakeTool(pi, "tool_search");
  const arms: [string, Parameters<typeof staged>[2], boolean][] = [
    ["tool_search registered but inactive", { extraExtensions: [toolSearch()] }, false],
    ["no tool_search at all", {}, false],
    [
      "a foreign tool_search namesake, active and opted in",
      { extraExtensions: [namesake], settings: COHORT_SETTINGS },
      true,
    ],
  ];
  for (const [arm, opts, namesakeActive] of arms) {
    const rt = await recordingRuntime();
    const h = await staged("implement", "read-write", {
      headful: false,
      ...opts,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
    });
    try {
      assert.equal(isActive(h, "tool_search"), namesakeActive, `${arm}: the precondition`);
      for (const name of family)
        assert.equal(h.toolInfo(name)?.exposure, "direct", `${arm}: ${name} stays direct`);
      assert.deepEqual(
        activePerk(h),
        registeredSubset(h, perkToolsFor("implement", "read-write")),
        `${arm}: today's always-declared loadout`,
      );
      rt.census();
      await h.session.prompt("census");
      for (const name of IMPLEMENT_MEMBERS) {
        assert.ok(isActive(h, name), `${arm}: ${name} active`);
        assert.ok(rt.last().tools.includes(name), `${arm}: ${name} declared`);
      }
    } finally {
      h.dispose();
    }
  }

  // The bare-session zero-call guarantee holds with the family flagged.
  installs.length = 0;
  const rt = await recordingRuntime();
  const bare = await loadAt(scaffoldRepo(), {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: undefined },
    extraExtensions: [toolSearch()],
  });
  try {
    await bare.session.extensionRunner.emitResourcesDiscover(
      bare.session.sessionManager.getCwd(),
      "reload",
    );
    rt.census();
    await bare.session.prompt("census");
    assert.deepEqual(installs, [], "zero perk installs");
    for (const name of family) assert.ok(rt.last().tools.includes(name), `${name} declared`);
  } finally {
    bare.dispose();
  }
});

test("two-session isolation (A): a cohort session's join never reaches a nonparticipant bound in the same process", async () => {
  const family = discoveryFamily();
  const a = await pilotSession("implement", "read-write", true);
  const b = await pilotSession("implement", "read-write", false);
  try {
    await a.h.emitSessionStart();
    for (const name of family) {
      assert.equal(a.h.toolInfo(name)?.exposure, "deferred", `A: ${name}`);
      assert.equal(b.h.toolInfo(name)?.exposure, "direct", `B: ${name}`);
    }
    for (const name of IMPLEMENT_MEMBERS) {
      assert.ok(!isActive(a.h, name), `A defers ${name}`);
      assert.ok(isActive(b.h, name), `B keeps ${name}`);
    }
  } finally {
    a.h.dispose();
    b.h.dispose();
  }
});

// --- 3. primed activation -------------------------------------------------------------------------

test("primed activation (A): /objective-sync primes objective_stack_status, declared on the next request; /objective-recover primes nothing; a successful start_review_wave primes collect_review_wave, a failed launch nothing", async () => {
  {
    const fake = createFakeSubagents();
    const { h, rt } = await pilotSession("implement", "read-write", true, {
      planRef: PLAN_REF,
      extraExtensions: [fake.extension],
    });
    try {
      spyInjections(h);
      await h.invokeCommand("objective-recover");
      assert.ok(!isActive(h, "objective_stack_status"), "recover primes nothing");
      await h.invokeCommand("objective-sync");
      assert.ok(isActive(h, "objective_stack_status"), "sync primed it (the plan-ref's objective)");
      rt.census();
      await h.session.prompt("census");
      assert.ok(rt.last().tools.includes("objective_stack_status"), "declared on the next request");

      assert.ok(!isActive(h, "collect_review_wave"));
      const started = await h.invokeTool("start_review_wave", {
        angles: ["claimed-intent", "correctness"],
        pr: 42,
        worktree: "/abs/wt",
      });
      assert.equal((started.details as { ok: boolean }).ok, true, started.content[0]?.text);
      assert.ok(isActive(h, "collect_review_wave"), "the launch primed its collector");
      rt.census();
      await h.session.prompt("census");
      assert.ok(rt.last().tools.includes("collect_review_wave"), "declared on the next request");
    } finally {
      h.dispose();
    }
  }
  {
    // No subagent responder + a tiny ping timeout: the deterministic `unavailable` launch.
    const { h } = await pilotSession("implement", "read-write", true, {
      env: { PERK_WAVE_RPC_PING_MS: "20" },
    });
    try {
      const failed = await h.invokeTool("start_review_wave", {
        angles: ["claimed-intent", "correctness"],
        pr: 42,
        worktree: "/abs/wt",
      });
      assert.equal((failed.details as { ok: boolean }).ok, false);
      assert.ok(!isActive(h, "collect_review_wave"), "a failed launch primes nothing");
    } finally {
      h.dispose();
    }
  }
});

test("primed activation (A): an ineligible prime and a nonparticipant prime install nothing", async (t) => {
  const installs = recordPerkInstalls(t);
  {
    // objective_stack_status rides only the worktree stages: a cohort plan session skips it.
    const { h } = await pilotSession("plan", "read-write", true);
    try {
      spyInjections(h);
      const before = installs.length;
      await h.invokeCommand("objective-sync", "7");
      assert.ok(!isActive(h, "objective_stack_status"), "ineligible: never activated");
      assert.equal(installs.length, before, "no install");
    } finally {
      h.dispose();
    }
  }
  {
    const { h } = await pilotSession("implement", "read-write", false);
    try {
      spyInjections(h);
      const before = installs.length;
      await h.invokeCommand("objective-sync", "7");
      assert.ok(isActive(h, "objective_stack_status"), "always declared outside the cohort");
      assert.equal(installs.length, before, "priming is a no-op outside the cohort");
    } finally {
      h.dispose();
    }
  }
});

// --- 4. priming survives the points ---------------------------------------------------------------

/** The code-review handshake the fake plannotator records (responded to at teardown). */
type Envelope = { respond: (response: unknown) => void };

/** A fake plannotator: the presence-probe command plus a bus listener recording each request. */
function fakePlannotator(sink: Envelope[]): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      sink.push(data as Envelope);
    });
  };
}

/** Settle every recorded bridge and wait for the readiness poll's env restore (bounded). */
async function settleBridges(sink: Envelope[]): Promise<void> {
  for (const envelope of sink) envelope.respond({ status: "handled", result: { approved: true } });
  const start = Date.now();
  while ("PLANNOTATOR_PORT" in process.env && Date.now() - start < 5000) {
    await new Promise((r) => setTimeout(r, 25));
  }
}

const CHECKOUT_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  path: "/wt/review-77",
  pr: 77,
  url: "https://github.com/o/r/pull/77",
  head_sha: "a".repeat(40),
  base_sha: "b".repeat(40),
  base_ref: "main",
});

test("priming survives the points (A): door-primed members stay active and declared through before_agent_start, resources_discover and session_start; under the gate only the gate-allowed one stays", async () => {
  const sink: Envelope[] = [];
  const bin = fakePerk(scaffoldRepo(), { stdout: CHECKOUT_OK_JSON });
  const { h, rt } = await pilotSession("implement", "read-write", true, {
    headful: true,
    env: { PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    spyInjections(h);
    await h.runCommandHandler("pr-review-browser", "77");
    for (const name of REVIEW_BROWSER_PRIMES) assert.ok(isActive(h, name), `${name} primed`);
    await h.emitBeforeAgentStart();
    await h.session.extensionRunner.emitResourcesDiscover(
      h.session.sessionManager.getCwd(),
      "reload",
    );
    await h.emitSessionStart();
    rt.census();
    await h.session.prompt("census");
    for (const name of REVIEW_BROWSER_PRIMES)
      assert.ok(rt.last().tools.includes(name), `${name} declared after every point`);

    // Gate entry: push_annotations is gate-allowed (mode over stage) and kept; the gate-blocked
    // collector is dropped.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only");
    assert.ok(isActive(h, "push_annotations"), "kept under the gate");
    assert.ok(!isActive(h, "collect_review_wave"), "ineligible under the gate: dropped");
    rt.census();
    await h.session.prompt("census");
    assert.ok(rt.last().tools.includes("push_annotations"));
    assert.ok(!rt.last().tools.includes("collect_review_wave"));
    // Gate exit: the kept member survives; reconciliation never re-activates the dropped one.
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-write");
    assert.ok(isActive(h, "push_annotations"), "kept across the exit");
    assert.ok(!isActive(h, "collect_review_wave"), "only a primer or the host re-activates");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("draft-review door from a gated worktree (A): /plan → plan_draft → plan_review's wave arm primes collect_draft_review_wave and push_annotations, declared on the next request", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01DRAFTWAVE", mode: "read-write", stage: "implement" },
  });
  gitInit(cwd, { dirty: false });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const rt = await recordingRuntime();
  let bus: ExtensionAPI["events"] | undefined;
  const h = await loadAt(cwd, {
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    env: { PERK_RUN_ID: "01DRAFTWAVE" },
    settings: COHORT_SETTINGS,
    extraExtensions: [
      toolSearch(),
      (pi) => {
        // A fake plannotator: presence plus a pending handshake; denied at teardown.
        bus = pi.events;
        pi.registerCommand(PLANNOTATOR_REVIEW_COMMAND, {
          description: "fake plannotator (presence probe target)",
          handler: async () => {},
        });
        pi.events.on("plannotator:request", (data) => {
          const req = data as { respond?: (r: unknown) => void };
          req.respond?.({ status: "handled", result: { status: "pending", reviewId: "rev-c" } });
        });
      },
    ],
  });
  try {
    spyInjections(h);
    for (const name of DRAFT_REVIEW_DOOR_PRIMES) assert.ok(!isActive(h, name), `${name} inactive`);
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "the real gate is on");
    for (const name of DRAFT_REVIEW_DOOR_PRIMES)
      assert.ok(!isActive(h, name), `${name} still deferred under the gate`);
    const written = await h.invokeTool("plan_draft", { plan: "# A plan in a cohort worktree\n" });
    assert.equal((written.details as { ok?: boolean }).ok, true, "the draft landed");
    const reviewed = await h.invokeTool(
      "plan_review",
      {},
      {
        ui: {
          select: async (_title: string, options: string[]) =>
            options.find((o) => /reviewer wave/.test(o)),
          input: async () => undefined,
        },
      },
    );
    assert.equal((reviewed.details as { status?: string }).status, "wave_launched");
    for (const name of DRAFT_REVIEW_DOOR_PRIMES)
      assert.ok(isActive(h, name), `${name} primed by the wave arm`);
    rt.census();
    await h.session.prompt("census");
    for (const name of DRAFT_REVIEW_DOOR_PRIMES)
      assert.ok(rt.last().tools.includes(name), `${name} declared on the next request`);
  } finally {
    // Settle the open review (a deny) so the door's background tasks end before disposal.
    bus?.emit("plannotator:review-result", { reviewId: "rev-c", approved: false, feedback: "x" });
    for (let i = 0; i < 80 && !h.notifies.some((n) => /DENIED/.test(n)); i++) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    h.dispose();
  }
});

test("priming resets (A): resume and fork from the primed leaf start without it and perk never installs it; /tree restores it and perk keeps it, or drops it in an ineligible stage", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);
  const rt = await recordingRuntime();
  const opts = {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch()],
    settings: COHORT_SETTINGS,
    env: { PERK_RUN_ID: undefined },
  };
  const primed = await loadAt(cwd, { ...opts, sessionManager: SessionManager.open(file) });
  let leaf: string;
  try {
    spyInjections(primed);
    await primed.invokeCommand("objective-sync", "7");
    assert.ok(isActive(primed, "objective_stack_status"));
    rt.census();
    await primed.session.prompt("census");
    const id = primed.session.sessionManager.getLeafId();
    assert.ok(id !== null);
    leaf = id;
  } finally {
    primed.dispose();
  }
  assert.ok(existsSync(file) && readFileSync(file, "utf8").includes("objective_stack_status"));

  for (const manager of [SessionManager.open(file), SessionManager.forkFrom(file, cwd)]) {
    installs.length = 0;
    const resumed = await loadAt(cwd, { ...opts, sessionManager: manager });
    try {
      assert.equal(resumed.workflowState().stage, "implement");
      assert.ok(!isActive(resumed, "objective_stack_status"), "starts without it");
      rt.census();
      await resumed.session.prompt("census");
      assert.ok(!isActive(resumed, "objective_stack_status"));
      assert.ok(installs.length > 0, "the recorder sees perk's startup install (non-vacuous)");
      assert.deepEqual(
        installs.filter((names) => names.includes("objective_stack_status")),
        [],
        "perk never installs it",
      );
    } finally {
      resumed.dispose();
    }
  }

  const h = await loadAt(cwd, { ...opts, sessionManager: SessionManager.open(file) });
  try {
    const [planted] = h.entryIds() as [string];
    await h.navigateTo(planted);
    await h.navigateTo(leaf);
    assert.ok(isActive(h, "objective_stack_status"), "/tree restored it and perk kept it");
    const toPlan = h.session.sessionManager.appendCustomEntry("perk:workflow-state", {
      stage: "plan",
    });
    await h.navigateTo(planted);
    await h.navigateTo(toPlan);
    assert.equal(h.workflowState().stage, "plan");
    assert.ok(!isActive(h, "objective_stack_status"), "dropped where it is ineligible");
  } finally {
    h.dispose();
  }
});

// --- 5. ineligible search, end to end -------------------------------------------------------------

test("ineligible search (A): in plan a searched collect_review_wave is hidden at once, deactivated at the next prompt and blocked under the gate; an eligible search in implement survives every point", async () => {
  {
    const { h, rt } = await pilotSession("plan", "read-write", true);
    try {
      rt.callThenStop("tool_search", { query: "collect the adversarial review wave reports" });
      await h.session.prompt("find the collector");
      assert.ok(isActive(h, "collect_review_wave"), "the search activated it for this prompt");
      assert.ok(
        !rt.last().tools.includes("collect_review_wave"),
        "hidden on the very next request",
      );
      rt.census();
      await h.session.prompt("census");
      assert.ok(!isActive(h, "collect_review_wave"), "deactivated when the next prompt started");
      assert.ok(!rt.last().tools.includes("collect_review_wave"));
      await h.invokeCommand("plan");
      assert.equal(
        await blocked(h, "collect_review_wave"),
        "perk read-only mode: collect_review_wave is blocked (tool not allowlisted).",
      );
    } finally {
      h.dispose();
    }
  }
  {
    const { h, rt } = await pilotSession("implement", "read-write", true);
    try {
      rt.callThenStop("tool_search", { query: "push findings to the browser as annotations" });
      await h.session.prompt("find the annotation tool");
      assert.ok(rt.last().tools.includes("push_annotations"), "declared on the next request");
      await h.session.extensionRunner.emitResourcesDiscover(
        h.session.sessionManager.getCwd(),
        "reload",
      );
      await h.emitSessionStart();
      await h.invokeCommand("plan");
      assert.ok(isActive(h, "push_annotations"), "kept under the gate");
      await h.invokeCommand("plan");
      rt.census();
      await h.session.prompt("census");
      assert.ok(rt.last().tools.includes("push_annotations"), "declared after every point");
    } finally {
      h.dispose();
    }
  }
});

// --- 6. offline discoverability pins (criterion D1) -----------------------------------------------

/**
 * D1's scored queries, exactly as pinned before measurement — a change needs an owner-approved
 * amendment recorded in docs/design/native-discovery-pilot.md BEFORE the amended run is scored.
 */
const D1_QUERIES: readonly { stage: string; member: string; query: string }[] = [
  {
    stage: "implement",
    member: "collect_review_wave",
    query: "collect the adversarial review wave reports",
  },
  {
    stage: "implement",
    member: "push_annotations",
    query: "push findings to the browser as annotations",
  },
  { stage: "implement", member: "objective_stack_status", query: "stacked delivery train status" },
  {
    stage: "plan",
    member: "collect_draft_review_wave",
    query: "collect the draft review wave reports",
  },
];

test("discoverability (A, D1): each family member is tool_search's top hit for its pinned query where eligible", async () => {
  assert.deepEqual(
    D1_QUERIES.map((q) => q.member).sort(),
    [...discoveryFamily()].sort(),
    "one scored query per family member",
  );
  for (const { stage, member, query } of D1_QUERIES) {
    assert.ok(isEligible(member, undefined, stage, "read-write"), `${member} eligible in ${stage}`);
    const { h } = await pilotSession(stage, "read-write", true);
    try {
      const result = await h.invokeTool("tool_search", { query });
      const loaded = (result.details as { loaded: string[] }).loaded;
      if (PRINT) process.stderr.write(`D1 ${stage} "${query}" → ${JSON.stringify(loaded)}\n`);
      assert.equal(loaded[0], member, `D1: "${query}" in ${stage}`);
    } finally {
      h.dispose();
    }
  }
});

/** The bytes one census request costs: its declared tools plus its system prompt. */
function requestBytes(request: RecordedRequest): number {
  return Buffer.byteLength(JSON.stringify(request.declared)) + Buffer.byteLength(request.prompt);
}

// --- 8. census and savings (criteria S1/S2) -------------------------------------------------------

/** The production `query`/`action` tools — the population a deferral can ever reach. */
const MEASURED_POPULATION = [
  "add_objective_node",
  "collect_draft_review_wave",
  "collect_review_wave",
  "gist_draft",
  "objective_draft",
  "objective_node",
  "objective_refinement_draft",
  "objective_stack_adopt",
  "objective_stack_land",
  "objective_stack_recover",
  "objective_stack_status",
  "plan_draft",
  "post_pr_review",
  "push_annotations",
  "reconcile_objective",
  "run_ci",
  "submit_pr_review",
];

/** The stage where no family member is eligible read-write: the fixed cost's measuring point. */
const FIXED_COST_STAGE = "gist-author";

test("census and savings (A): per-stage request bytes with and without the cohort; the fixed cost is tool_search's own declaration", async () => {
  const members = discoveryFamily();
  const rows: { stage: string; baseline: number; cohort: number; net: number }[] = [];
  let censusTools: string[] = [];
  let toolSearchOwn = -1;
  const toolRows: string[] = [];

  for (const stage of REGISTRY_STAGE_IDS) {
    const measured: Record<"baseline" | "cohort", RecordedRequest> = {} as never;
    for (const cohort of [false, true]) {
      const { h, rt } = await pilotSession(stage, "read-write", cohort);
      try {
        rt.census();
        await h.session.prompt("census");
        measured[cohort ? "cohort" : "baseline"] = rt.last();
        if (stage === FIXED_COST_STAGE && cohort) {
          // tool_search's exact delta: its declaration (plus the array separator) and its
          // snippet line (plus the line separator); it carries no guidelines.
          const declared = (rt.last().declared as { name: string }[]).find(
            (t) => t.name === "tool_search",
          );
          const snippet = h.registeredTool("tool_search")?.promptSnippet ?? "";
          assert.ok(declared !== undefined, "tool_search is declared in a cohort session");
          assert.deepEqual(h.registeredTool("tool_search")?.promptGuidelines ?? [], []);
          toolSearchOwn =
            Buffer.byteLength(JSON.stringify(declared)) +
            1 +
            Buffer.byteLength(`- tool_search: ${snippet}\n`);
        }
        if (stage === "implement" && !cohort) {
          censusTools = perkToolNames().filter((name) => {
            const policy = perkToolPolicy(name);
            return (
              (policy?.kind === "query" || policy?.kind === "action") &&
              h.registeredTool(name) !== null
            );
          });
          for (const name of censusTools) {
            const def = h.registeredTool(name);
            const policy = perkToolPolicy(name);
            assert.ok(def !== null && policy !== undefined);
            const request = Buffer.byteLength(
              JSON.stringify({ description: def.description, parameters: def.parameters }),
            );
            const prompt =
              Buffer.byteLength(def.promptSnippet ?? "") +
              Buffer.byteLength((def.promptGuidelines ?? []).join("\n"));
            const gated = typeof policy.gated === "object" ? "carve-out" : policy.gated;
            toolRows.push(
              `| \`${name}\` | ${policy.kind} | ${gated} | ${policy.stages.join(", ")} | ${request} | ${prompt} |`,
            );
          }
        }
      } finally {
        h.dispose();
      }
    }
    const { baseline, cohort } = measured;
    assert.ok(cohort.tools.includes("tool_search"), `${stage}: the cohort declares tool_search`);
    assert.ok(!baseline.tools.includes("tool_search"), `${stage}: a nonparticipant does not`);
    const eligibleMembers = members.filter((name) =>
      isEligible(name, undefined, stage, "read-write"),
    );
    for (const name of eligibleMembers) {
      assert.ok(baseline.tools.includes(name), `${stage}: a nonparticipant declares ${name}`);
      assert.ok(!cohort.tools.includes(name), `${stage}: the cohort defers ${name}`);
    }
    assert.deepEqual(
      cohort.tools.filter(isPerkTool).sort(),
      baseline.tools.filter((name) => isPerkTool(name) && !eligibleMembers.includes(name)).sort(),
      `${stage}: the cohort's perk declarations are the nonparticipant's minus the deferred family`,
    );
    const b = requestBytes(baseline);
    const c = requestBytes(cohort);
    rows.push({ stage, baseline: b, cohort: c, net: b - c });
  }

  assert.deepEqual([...censusTools].sort(), MEASURED_POPULATION, "the measured population");
  const fixedCost = -(rows.find((r) => r.stage === FIXED_COST_STAGE)?.net ?? Number.NaN);
  assert.equal(fixedCost, toolSearchOwn, "the fixed cost is tool_search's own bytes");

  if (PRINT) {
    const out = [
      "",
      "Per-tool census (implement session; request = JSON {description, parameters}; prompt = snippet + guidelines):",
      "",
      "| tool | kind | gated | stages | request bytes | prompt bytes |",
      "|---|---|---|---|---|---|",
      ...toolRows,
      "",
      `Per-stage census request bytes (declared + system prompt), read-write; fixed cost = ${fixedCost}:`,
      "",
      "| stage | nonparticipant | cohort | net |",
      "|---|---|---|---|",
      ...rows.map((r) => `| ${r.stage} | ${r.baseline} | ${r.cohort} | ${r.net} |`),
      "",
    ];
    process.stderr.write(`${out.join("\n")}\n`);
  }

  if (members.length === 0) {
    // The baseline: identical perk declarations; the cohort costs exactly tool_search everywhere.
    for (const r of rows) assert.equal(r.net, -fixedCost, `${r.stage}: net is -fixedCost`);
    return;
  }
  assert.ok(fixedCost <= 1024, `S2: the fixed cost ${fixedCost} ≤ 1024`);
  for (const r of rows) {
    const eligible = members.some((name) => isEligible(name, undefined, r.stage, "read-write"));
    if (eligible) assert.ok(r.net >= 4096, `S1: ${r.stage} net ${r.net} ≥ 4096`);
    else assert.equal(r.net, -fixedCost, `${r.stage}: no member eligible, net is -fixedCost`);
  }
});

// --- 9. the converged seed resolves additively on the real host -----------------------------------

/** One `shared/fixtures/default-tools-seed.json` case (`live` omitted = the key is absent). */
interface SeedCase {
  case: string;
  live?: unknown;
  converged: unknown;
  seeded: boolean;
  host_check: boolean;
}

const SEED_CASES = (
  JSON.parse(readFileSync(join(sharedDir(), "fixtures", "default-tools-seed.json"), "utf8")) as {
    cases: SeedCase[];
  }
).cases;

/** A host-checkable `defaultTools` value: absent (`undefined`) or a raw JSON array. */
function hostList(value: unknown, label: string): readonly unknown[] | undefined {
  if (value === undefined) return undefined;
  assert.ok(Array.isArray(value), `${label}: a host_check value is an array`);
  return value;
}

/** Whether a raw `defaultTools` array carries no string entry (`[]`, or only non-strings). */
const noStringEntries = (value: unknown): boolean =>
  Array.isArray(value) && !value.some((entry) => typeof entry === "string");

/** Pi's own startup selection under `defaultTools` (absent = no key): the non-perk active set. */
async function resolvedSelection(defaultTools: readonly unknown[] | undefined): Promise<string[]> {
  const h = await loadAt(scaffoldRepo(), {
    headful: false,
    env: { PERK_RUN_ID: undefined },
    extraExtensions: [toolSearch()],
    // Pi's `Settings` type says `string[]`, but a project file is raw JSON: feed it unchanged so
    // Pi's own `getDefaultTools` filtering (non-strings dropped) is what gets measured.
    ...(defaultTools !== undefined ? { settings: { defaultTools: defaultTools as string[] } } : {}),
  });
  try {
    return h.session
      .getActiveToolNames()
      .filter((name) => !isPerkTool(name))
      .sort();
  } finally {
    h.dispose();
  }
}

// The Python plane proves the seed's JSON delta; this lane proves the resolved selection, because
// Pi's modifier semantics make the two differ for a list with no string entries (no builtins,
// while a nonempty modifier-only list starts from the four defaults).
test("converged seed (A): for every host-checkable fixture case the seed adds tool_search and nothing else to Pi's resolved selection; an untouched list with no string entries still resolves to no builtins, which a naive append would widen", async () => {
  const rows = SEED_CASES.filter((c) => c.host_check);
  assert.ok(rows.some((c) => c.seeded) && rows.some((c) => !c.seeded), "both arms are exercised");
  assert.ok(
    rows.some((c) => Array.isArray(c.live) && c.live.length === 0) &&
      rows.some((c) => noStringEntries(c.live) && Array.isArray(c.live) && c.live.length > 0),
    "the empty and the all-non-string cases are exercised",
  );
  for (const row of rows) {
    const live = hostList(row.live, `${row.case} live`);
    const before = await resolvedSelection(live);
    const after = await resolvedSelection(hostList(row.converged, `${row.case} converged`));
    if (row.seeded) {
      assert.ok(!before.includes("tool_search"), `${row.case}: tool_search was not selected`);
      assert.deepEqual(after, [...before, "tool_search"].sort(), `${row.case}: additive`);
    } else {
      assert.deepEqual(after, before, `${row.case}: untouched`);
    }
    if (live !== undefined && noStringEntries(live)) {
      assert.equal(row.seeded, false, `${row.case}: never seeded`);
      assert.deepEqual(before, [], `${row.case}: resolves to no builtin tools`);
      // Why it is left alone: appending the modifier would switch on Pi's four defaults too.
      const naive = await resolvedSelection([...live, "+tool_search"]);
      assert.deepEqual(naive, ["bash", "edit", "read", "tool_search", "write"], row.case);
    }
  }
});
