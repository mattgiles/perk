// Stage-scoped active tools (contracts.md §8.40): the derived stage-diet hygiene, the
// catalog↔live-registration census, perk's own-names scoping driven through a REAL bound
// AgentSession via the harness (fully offline), and the both-planes prompt guard's TS half.
// Siblings: toolGating.test.ts (the read-only gate itself) and ownNamesActivation.test.ts (the
// provenance-posture table, foreign invariance and the loadout host's presentation).

import assert from "node:assert/strict";
import { before, test } from "node:test";
import { fauxAssistantMessage, fauxText, getCurrentTools } from "@earendil-works/pi-ai";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { GIST_AUTHORING_CONTEXT } from "../authoring/gist/prose.ts";
import {
  factoryGuidance,
  OBJECTIVE_AUTHORING_CONTEXT,
  objectiveReadInstruction,
  reconcileGuidance,
} from "../authoring/objective/prose.ts";
import { PLAN_AUTHORING_CONTEXT } from "../authoring/plan/prose.ts";
import { REFINEMENT_CONTEXT } from "../authoring/refinement/prose.ts";
import { learnFactoryGuidance } from "../learning/prose.ts";
import { CODE_FACTORY, DOCS_FACTORY } from "../learning/routing.ts";
import { prReviewGuidance } from "../pi/v1/codeReview/automated.ts";
import { stackReviewGuidance } from "../pi/v1/codeReview/stack.ts";
import { prReviewTerminalGuidance } from "../pi/v1/codeReview/terminal.ts";
import { isPlanGuidanceStage } from "../pi/v1/contextInjection.ts";
import {
  commitAndCompactContinuation,
  commitAndCompactGuidance,
} from "../pi/v1/delivery/commitCompact.ts";
import { objectiveLandGuidance } from "../pi/v1/delivery/stackLand.ts";
import { objectiveRecoverGuidance } from "../pi/v1/delivery/stackRecover.ts";
import {
  objectiveSyncGuidance,
  syncConflictResolutionGuidance,
} from "../pi/v1/delivery/stackSync.ts";
import { draftAndCompactContinuation, draftAndCompactGuidance } from "../pi/v1/draftCompact.ts";
import { gistSaveGuidance } from "../pi/v1/gist.ts";
import { simplifyGuidance } from "../pi/v1/simplify.ts";
import { retainedDispatch } from "../testing/fakeConflictResolver.ts";
import {
  fauxModelRuntime,
  loadPerkSession,
  type PerkSession,
  plantSession,
  registerFakeTool,
  scaffoldRepo,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { render } from "./prompts.ts";
import { renderReadOnlyContext } from "./toolGating.ts";
import {
  AUTHORING_STAGES,
  GIST_STAGES,
  gatedToolsFor,
  isEligible,
  isPerkTool,
  LOADOUT_HOST_NAME,
  type Mode,
  OBJECTIVE_STAGES,
  PLAN_FAMILY_STAGES,
  perkToolNames,
  REGISTRY_STAGE_IDS,
  stageToolsFor,
  toolMatrix,
  WORKTREE_STAGES,
} from "./toolPolicy.ts";

// The pure diet/guard tests read the catalog: fill it the way production does first.
before(ensureToolCatalog);

/**
 * loadPerkSession with process.cwd() pointed at the scaffold for the load: provider vacating
 * (e.g. perk's plan surface under a foreign `[providers] plan`) resolves `process.cwd()` at
 * factory time, so running the suite from a repo with its own selections would otherwise leak
 * into what registers (the planMode.test.ts chdir pattern). Restores cwd before returning.
 */
async function loadAt(
  cwd: string,
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> = {},
): Promise<PerkSession> {
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, ...opts });
  } finally {
    process.chdir(savedCwd);
  }
}

/** The 5 authoring tools every worktree-stage session must scope off. (The reconcile trio —
 * `reconcile_objective`/`add_objective_node`/`objective_node` — is NOT here: it rides the
 * worktree family for the post-land reconcile drive.) */
const AUTHORING_TOOLS = [
  "plan_draft",
  "plan_review",
  "plan_save",
  "objective_draft",
  "objective_save",
];

/** The session's active perk names, sorted. */
function activePerk(h: PerkSession): string[] {
  return h.session.getActiveToolNames().filter(isPerkTool).sort();
}

/** The registered subset of a perk view, sorted — what perk's activation installs. */
function registeredSubset(h: PerkSession, view: readonly string[]): string[] {
  const registered = new Set(h.session.getAllTools().map((t) => t.name));
  return view.filter((name) => registered.has(name)).sort();
}

/** A bare (unknown-provenance) extension registering load-time no-op tools. */
function fakeForeign(names: readonly string[]): (pi: ExtensionAPI) => void {
  return (pi) => {
    for (const name of names) registerFakeTool(pi, name);
  };
}

test("stage diets: run_scout_wave rides exactly the three authoring stages", () => {
  // The scout launcher's gate-OFF placement (contracts.md §8.70): plan / objective-plan /
  // objective-author and NO other stage.
  for (const stage of REGISTRY_STAGE_IDS) {
    assert.equal(
      stageToolsFor(stage)?.includes("run_scout_wave"),
      AUTHORING_STAGES.includes(stage),
      `run_scout_wave in the ${stage} diet`,
    );
  }
});

test("stage diets: run_librarian rides exactly the three authoring stages and the worktree family", () => {
  // The library writer launcher's gate-OFF placement (contracts.md §8.75(l)).
  const carriers = new Set([...AUTHORING_STAGES, ...WORKTREE_STAGES]);
  for (const stage of REGISTRY_STAGE_IDS) {
    assert.equal(
      stageToolsFor(stage)?.includes("run_librarian"),
      carriers.has(stage),
      `run_librarian in the ${stage} diet`,
    );
  }
});

test("stage diets: every perk view lies in the catalog, carries the loadout host, and names no foreign tool", () => {
  const catalog = new Set(perkToolNames());
  for (const stage of REGISTRY_STAGE_IDS) {
    for (const view of [stageToolsFor(stage) ?? [], gatedToolsFor(stage)]) {
      for (const name of view)
        assert.ok(catalog.has(name), `${stage}: ${name} outside the catalog`);
      assert.ok(view.includes(LOADOUT_HOST_NAME), `${stage}: the host rides every landing`);
    }
  }
});

test("the tool catalog set-equals the non-builtin tools a perk-only session registers", async () => {
  // The completeness drift guard: the harness binds ONLY perk with no [providers] config, so all
  // perk registrations are live and builtins are the only other source — and every one of them
  // went through the seam (no registration bypasses the catalog; the loadout host included).
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: undefined } });
  try {
    const registered = h.session
      .getAllTools()
      .filter((t) => t.sourceInfo.source !== "builtin")
      .map((t) => t.name)
      .sort();
    assert.deepEqual(registered, [...perkToolNames()].sort());
    assert.ok(registered.includes(LOADOUT_HOST_NAME));
  } finally {
    h.dispose();
  }
});

test("implement claim: PR-loop family active, the 5 authoring tools scoped off", async () => {
  const runId = "01STAGETOOLIMPL";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    assert.deepEqual(activePerk(h), registeredSubset(h, stageToolsFor("implement") ?? []));
    const active = h.session.getActiveToolNames();
    for (const name of [
      "submit",
      "resolve_submit_conflicts",
      "ready",
      "run_ci",
      "land",
      "learn",
      "finalize_address",
    ]) {
      assert.ok(active.includes(name), `PR-loop tool must stay active: ${name}`);
    }
    // The reconcile trio rides the worktree family (the post-land reconcile drive).
    for (const name of ["reconcile_objective", "add_objective_node", "objective_node"]) {
      assert.ok(active.includes(name), `reconcile-trio tool must stay active: ${name}`);
    }
    for (const name of ["read", "bash", "edit", "write"]) {
      assert.ok(active.includes(name), `builtin must pass through untouched: ${name}`);
    }
    for (const name of [...AUTHORING_TOOLS, "run_scout_wave"]) {
      assert.ok(!active.includes(name), `authoring tool must be scoped off: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("gated stage: gate ON keeps exactly the registered subset of the stage's gated view; foreign activation untouched", async () => {
  const runId = "01STAGETOOLOBJP";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-only", stage: "objective-plan" } });
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    // An unknown-provenance foreign tool: perk never deactivates it — the gate hides it from the
    // model and the backstop blocks it.
    extraExtensions: [fakeForeign(["subagent"])],
  });
  try {
    assert.deepEqual(activePerk(h), registeredSubset(h, gatedToolsFor("objective-plan")));
    const active = h.session.getActiveToolNames();
    for (const name of [
      "objective_node",
      "explore_objective_node",
      "plan_draft",
      "plan_review",
      "run_scout_wave",
    ]) {
      assert.ok(active.includes(name), `gated carve-out must stay active: ${name}`);
    }
    assert.ok(!active.includes("plan_save"), "a gate-blocked perk tool is deactivated");
    for (const name of ["edit", "write", "subagent"]) {
      assert.ok(active.includes(name), `perk never deactivates a non-perk tool: ${name}`);
      assert.equal((await h.emitToolCall(name, {}))?.block, true, `${name} is blocked`);
    }
  } finally {
    h.dispose();
  }
});

test("gated adopt-child: the engine's child-side tools survive the inherited gate", async () => {
  // The live regression (the objective-plan explorer failure): a spawned child inherits the
  // parent's read-only mode via the adopt arm (consumed handoff + env PERK_RUN_ID), and the
  // engine's child-side tools — registered at extension LOAD time by pi-subagents' named
  // prompt-runtime factory — must stay active and callable under the gate. A blocked
  // structured_output makes an outputSchema child physically unable to make the engine-required
  // completion call.
  const runId = "01STAGETOOLCHLD";
  const cwd = scaffoldRepo({
    handoff: {
      runId,
      mode: "read-only",
      stage: "objective-plan",
      consumed: true,
      piSessionId: "parent.jsonl",
    },
  });
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    sessionManager: SessionManager.open(file),
    extraExtensions: [
      {
        name: "pi-subagents:prompt-runtime",
        factory: fakeForeign(["structured_output", "contact_supervisor"]),
      },
      fakeForeign(["bg_wait"]),
    ],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["structured_output", "contact_supervisor", "read"]) {
      assert.ok(active.includes(name), `must stay active under the inherited gate: ${name}`);
      assert.equal((await h.emitToolCall(name, {}))?.block, undefined, `${name} is callable`);
    }
    // The gate itself still holds in the child — by the backstop, not by deactivation.
    for (const name of ["edit", "write", "bg_wait"]) {
      assert.equal((await h.emitToolCall(name, {}))?.block, true, `${name} is blocked`);
    }
  } finally {
    h.dispose();
  }
});

test("unknown stage id: fail-open (no filtering — version-skew safety)", async () => {
  const runId = "01STAGETOOLFUTR";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "future-stage" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    const active = h.session.getActiveToolNames();
    assert.ok(active.includes("plan_draft"), "an unknown stage id must not filter anything");
    assert.ok(active.includes("submit"));
    assert.ok(active.includes("edit"));
  } finally {
    h.dispose();
  }
});

test("bare session: no stage → zero perk intervention (pi's default active set survives)", async () => {
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: undefined } });
  try {
    const active = new Set(h.session.getActiveToolNames());
    // Nothing filtered: every perk tool (the host included) and the default-active builtins stay
    // active.
    for (const name of [...perkToolNames(), "read", "bash", "edit", "write"]) {
      assert.ok(active.has(name), `must stay active in an unscoped session: ${name}`);
    }
    // Nothing widened: pi registers grep/find/ls but leaves them INACTIVE by default — an
    // accidental setActiveTools over the registry would activate them. Their staying inactive
    // is the sharp zero-setActiveTools canary (this pins pi's current default; update if pi ever
    // activates these by default).
    for (const name of ["grep", "find", "ls"]) {
      assert.ok(!active.has(name), `pi default-inactive builtin must stay untouched: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("tree navigation: gate/stage recompute across mode entries", async () => {
  const cwd = scaffoldRepo();
  // stage=plan rides the branch (per-field LWW); the two mode entries flip the gate across it.
  const file = plantSession(cwd, [{ stage: "plan", mode: "read-only" }, { mode: "read-write" }]);
  const h = await loadAt(cwd, {
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const ids = h.entryIds();
    const [readOnlyId, readWriteId] = ids as [string, string];

    // Navigate to the read-only entry → gate ON → perk's subset is the plan stage's gated view.
    await h.navigateTo(readOnlyId);
    assert.deepEqual(activePerk(h), registeredSubset(h, gatedToolsFor("plan")));
    assert.equal((await h.emitToolCall("edit", {}))?.block, true);

    // Navigate to the read-write entry → gate OFF + stage plan → the stage-filtered set.
    await h.navigateTo(readWriteId);
    assert.deepEqual(activePerk(h), registeredSubset(h, stageToolsFor("plan") ?? []));
    const scoped = h.session.getActiveToolNames();
    assert.ok(scoped.includes("plan_save"), "plan-stage tool active once the gate is off");
    assert.ok(scoped.includes("run_scout_wave"), "the scout launcher rides the plan stage");
    assert.ok(!scoped.includes("submit"), "PR-loop tool scoped off in a plan-stage session");
    assert.ok(scoped.includes("edit"), "builtins active once the gate is off");
    assert.ok(scoped.includes("write"));
    assert.equal((await h.emitToolCall("edit", {}))?.block, undefined);
  } finally {
    h.dispose();
  }
});

/**
 * A stand-in for `@juicesharp/rpiv-ask-user-question`'s `hasUI` reconcile: registers
 * `ask_user_question` at load and strips it in its own `before_agent_start` when `!ctx.hasUI`.
 */
function fakeQuestionnaire(pi: ExtensionAPI): void {
  registerFakeTool(pi, "ask_user_question");
  pi.on("before_agent_start", async (_event: unknown, ctx: ExtensionContext) => {
    if (ctx.hasUI) return;
    pi.setActiveTools(pi.getActiveTools().filter((n) => n !== "ask_user_question"));
  });
}

/** A late registrant: registers its tool inside its own `session_start` (after perk's sync). */
function fakeLate(name: string): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.on("session_start", async () => registerFakeTool(pi, name));
  };
}

test("headless prompt turn: the model-visible census after startup", async () => {
  // One real (faux-runtime) prompt turn: the provider sees a TranscriptContext (pi-ai ≥ 0.87
  // declares the tool loadout through the system messages' `toolsAdded`/`toolsRemoved`, not a
  // `context.tools` field), so `getCurrentTools(context.messages)` IS the model-visible census.
  // This pins what the model actually sees after the startup re-apply and perk's own
  // `before_agent_start` re-apply: the late foreign tool declared (it passes the read-write
  // diet), the scoped-off authoring tool absent, the host never declared, and the
  // questionnaire's own strip honored — perk's re-apply runs first and changes no foreign name.
  const runId = "01STAGETOOLTURN";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const reg = await fauxModelRuntime();
  const seen: string[][] = [];
  reg.setResponses([
    (context: { messages: { role: string }[] }) => {
      seen.push(getCurrentTools(context.messages).map((t) => t.name));
      return fauxAssistantMessage([fauxText("census read")], { stopReason: "stop" });
    },
  ]);
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    headful: false,
    model: reg.getModel(),
    modelRuntime: reg.modelRuntime,
    extraExtensions: [fakeLate("subagent_supervisor"), fakeQuestionnaire],
  });
  try {
    const foreignBefore = h.session.getActiveToolNames().filter((n) => !isPerkTool(n));
    assert.ok(foreignBefore.includes("ask_user_question"), "active until its owner strips it");
    await h.session.prompt("census");
    assert.equal(seen.length, 1, "exactly one model request");
    const tools = new Set(seen[0]);
    for (const name of ["subagent_supervisor", "submit", "read", "bash", "edit", "write"]) {
      assert.ok(tools.has(name), `model-visible after startup: ${name}`);
    }
    for (const name of ["plan_draft", "ask_user_question", LOADOUT_HOST_NAME]) {
      assert.ok(!tools.has(name), `not model-visible after startup: ${name}`);
    }
    // The only foreign change across the turn is the owner's own strip.
    assert.deepEqual(
      h.session.getActiveToolNames().filter((n) => !isPerkTool(n)),
      foreignBefore.filter((n) => n !== "ask_user_question"),
    );
  } finally {
    h.dispose();
  }
});

// --- the prompt guard (both planes; tests/test_tool_matrix_prompts.py is the Python half) ------

const GLOBAL_COMMAND_STAGES: readonly string[] = [
  ...WORKTREE_STAGES,
  "objective-author",
  "objective-save",
  "objective-plan",
  "plan",
  "save",
];

/** One (stage, mode) landing a carrier can have; `stage: null` = an unscoped session. */
type Landing = { stage: string | null; mode: Mode };
const rw = (stages: readonly string[]): Landing[] =>
  stages.map((stage) => ({ stage, mode: "read-write" }));
const ro = (stages: readonly (string | null)[]): Landing[] =>
  stages.map((stage) => ({ stage, mode: "read-only" }));
/** Every gated landing: each registry stage plus the unscoped session. */
const EVERY_GATED: readonly Landing[] = ro([null, ...REGISTRY_STAGE_IDS]);

/**
 * The scan universe: the matrix's perk-owned names. Builtins are excluded — never stage-scoped,
 * the gate's own prose names `edit`/`write`, and `read`/`write`/`find` are ordinary English.
 * Foreign names are not enumerable (they are governed by provenance, not by name), so a carrier
 * naming one is outside the guard — the eligible-everywhere foreign tools the guidance names
 * (`ask_user_question`, the implement checklist's `todo`) are what that leaves unpinned.
 */
function scanUniverse(): string[] {
  return Object.entries(toolMatrix().tools)
    .filter(([, entry]) => entry.owner === "perk")
    .map(([name]) => name);
}

/**
 * The match rule (shared with the Python half): a name containing `_` matches as a bare word —
 * an underscore identifier in prose is always a tool mention (`_` is a word char, so
 * `\bplan_save\b` never matches inside a longer identifier); a single-word name (`submit`,
 * `ready`, `todo`, …) matches only backtick-quoted. Model-facing guidance code-quotes tool names
 * by convention; an unquoted single-word mention is an accepted, recorded miss. Conservative on
 * purpose: a negative mention ("do NOT call X") still counts.
 */
function toolMention(name: string): RegExp {
  return name.includes("_") ? new RegExp(`\\b${name}\\b`) : new RegExp(`\`${name}\``);
}

/** Every scan-universe tool name a carrier references. */
function referencedScopedTools(text: string): string[] {
  return scanUniverse().filter((name) => toolMention(name).test(text));
}

/** The draft-and-compact subjects and the gated landings the session seam routes to each. */
const DRAFT_SUBJECT_LANDINGS: readonly ["plan" | "objective" | "gist" | "refinement", Landing[]][] =
  [
    ["objective", ro(["objective-author", "objective-save"])],
    ["gist", ro(["gist-author"])],
    ["refinement", ro(["objective-refine"])],
    [
      "plan",
      ro([
        null,
        ...REGISTRY_STAGE_IDS.filter(
          (id) =>
            !["objective-author", "objective-save", "gist-author", "objective-refine"].includes(id),
        ),
      ]),
    ],
  ];

/**
 * The carrier → landings table: every model-facing guidance (a gate-OFF drive, a gated context, a
 * mode-over-stage flow) paired with EVERY (stage, mode) landing its session can have when it
 * lands. The rule: a carrier may name only tools eligible in every landing it has. Each render
 * uses dummy params with all optional params SET (the richer conditional arm).
 */
const DRIVE_COVERAGE: readonly {
  drive: string;
  landings: readonly Landing[];
  text: () => string;
  /** The drive deliberately names NO scoped tool — skip the scan-broken tripwire for this row. */
  namesNoTools?: boolean;
}[] = [
  {
    // The reported regression: `/land` auto-drives the reconcile pass in the CURRENT worktree
    // session, and the manual `/objective-reconcile` gesture is registered globally.
    drive: "reconcileGuidance (post-land drive + /objective-reconcile)",
    landings: rw([...WORKTREE_STAGES, "objective-author", "objective-save", "objective-plan"]),
    text: () => reconcileGuidance("5", "github", "https://example.test/issues/5"),
  },
  {
    // The ready→reconcile continuation drive (contracts.md §8.66): fires wherever a stacked
    // `/ready` can succeed — the same stage set as the reconcile drive above (the pass uses
    // the same reconcile trio). Gate-active sessions are covered by the feature op's own
    // gate refusal (the injected sessionReadOnly capability), not by this list. The template deliberately names NO
    // ready/land re-entry gesture (re-entry guidance lives on the human-facing surfaces), so
    // this row passes without widening the objective-stage lists.
    drive: "driveReadyContinuation (stages/objective-reconcile-ready.md)",
    landings: rw([...WORKTREE_STAGES, "objective-author", "objective-save", "objective-plan"]),
    text: () =>
      render("stages/objective-reconcile-ready.md", {
        objective: "5",
        node: "2.1",
        plan: "42",
        pr: "77",
        parent_checkpoint: "a".repeat(40),
        stamped_head: "b".repeat(40),
        read_clause: "Read the linked Project too.",
      }),
  },
  {
    // The stacked-delivery drives: registered globally, gate-on soft-refuses, and the
    // worktree family is where they land in practice (post-amend sync from implement/address;
    // recovery and the atomic landing from anywhere in the PR loop) — the worktree family
    // carries the quintet.
    drive: "stages/objective-sync.md (/objective-sync)",
    landings: rw(WORKTREE_STAGES),
    text: () => objectiveSyncGuidance("5"),
  },
  {
    drive: "stages/objective-recover.md (/objective-recover)",
    landings: rw(WORKTREE_STAGES),
    text: () => objectiveRecoverGuidance("5"),
  },
  {
    drive: "stages/objective-land.md (/objective-land)",
    landings: rw(WORKTREE_STAGES),
    text: () => objectiveLandGuidance("5"),
  },
  {
    drive: "stages/learn.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/learn.md", {
        provider: "github",
        pr_id: "42",
        url: "https://example.test/pull/42",
        read_cmd: "gh issue view 42",
      }),
  },
  {
    drive: "stages/learn-orchestrate.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/learn-orchestrate.md", {
        manifest_path: "/tmp/bundle/manifest.json",
        bundle_dir: "/tmp/bundle",
      }),
  },
  {
    drive: "stages/conflict-resolution.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/conflict-resolution.md", {
        base: "main",
        attempt: "1",
        cap: "2",
      }),
  },
  {
    drive: "stages/conflict-resolution-continuation.md (sync conflict drive + resolve mode)",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      syncConflictResolutionGuidance(retainedDispatch("/tmp/wt"), 1, 2, {
        kind: "continuation-ready",
        report: {
          mode: "retained-continuation",
          outcome: "completed",
          verification: "passed",
          summary: "Checks passed.",
        },
        receipt: {
          nodeId: "retained-conflict",
          cwd: "/tmp/wt",
          termination: "confirmed",
          lock: { disposition: "released" },
        },
      }),
  },
  {
    drive: "stages/address/preview.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/address/preview.md", {
        provider: "github",
        pr_id: "42",
        url: "https://example.test/pull/42",
      }),
  },
  {
    drive: "stages/address/action.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/address/action.md", {
        provider: "github",
        pr_id: "42",
        url: "https://example.test/pull/42",
      }),
  },
  {
    drive: "stages/pr-review.md",
    landings: rw(WORKTREE_STAGES),
    text: () => prReviewGuidance("focus"),
  },
  {
    drive: "stages/pr-review-terminal/active.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/pr-review-terminal/active.md", {
        pr: "42",
        worktree: "/tmp/wt",
        base_sha: "abc123",
        directive: "focus",
      }),
  },
  {
    drive: "stages/pr-review-terminal/foreign.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/pr-review-terminal/foreign.md", {
        pr: "42",
        worktree: "/tmp/wt",
        base_sha: "abc123",
        directive: "focus",
      }),
  },
  {
    drive: "stages/pr-review-browser/active.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/pr-review-browser/active.md", {
        pr: "42",
        pr_url: "https://example.test/pull/42",
        worktree: "/tmp/wt",
        directive: "focus",
      }),
  },
  {
    drive: "stages/pr-review-browser/foreign.md",
    landings: rw(WORKTREE_STAGES),
    text: () =>
      render("stages/pr-review-browser/foreign.md", {
        pr: "42",
        pr_url: "https://example.test/pull/42",
        worktree: "/tmp/wt",
        directive: "focus",
      }),
  },
  {
    // The stacked-review door: registered globally but realistically lands in the worktree
    // family (a warm mid-loop gesture) or the dedicated `perk objective stack review` launch
    // session (where `open_stack_review` returns the same guidance).
    drive: "stages/stack-review-browser/stack.md (/stack-review-browser + open_stack_review)",
    landings: rw([...WORKTREE_STAGES, "stack-review"]),
    text: () =>
      stackReviewGuidance({
        topPr: 42,
        checkout: "/tmp/review-42",
        stackBase: "main",
        members: [
          {
            pr: 41,
            url: "https://example.test/pull/41",
            branch: "plan-301",
            head_sha: "a".repeat(40),
            base_ref: "main",
            node_id: "1.1",
            plan_id: "301",
          },
          {
            pr: 42,
            url: "https://example.test/pull/42",
            branch: "plan-302",
            head_sha: "b".repeat(40),
            base_ref: "plan-301",
            node_id: null,
            plan_id: null,
          },
        ],
        notes: ["drift: PR #41 head moved"],
        directive: "focus",
        pinned: {
          topPr: 42,
          checkout: "/tmp/review-42",
          baseSha: "0".repeat(40),
          heads: [
            { pr: 41, headSha: "a".repeat(40) },
            { pr: 42, headSha: "b".repeat(40) },
          ],
        },
      }),
  },
  {
    // The stack-review cold seed: the launched session's initial prompt names the ONE
    // open_stack_review call, so the tool must be active in the stack-review stage.
    drive: "stages/stack-review/cold.md (perk objective stack review seed)",
    landings: rw(["stack-review"]),
    text: () =>
      render("stages/stack-review/cold.md", {
        stack_phrase: "objective #77's delivery train",
        member_count: "3",
        top_pr: "42",
      }),
  },
  {
    // The draft-review door: registered globally but stage-gated at entry to the three
    // plan-draft-authoring stages — the guidance can only ever land in those sessions.
    drive: "stages/plan-review-browser.md (/plan-review-browser)",
    // It is ALSO plan_review's wave-launched guidance: the reviewer wave is offered in any gated
    // session holding a plan draft (the /plan toggle lands everywhere), so every gated landing.
    landings: [...rw(PLAN_FAMILY_STAGES), ...EVERY_GATED],
    text: () =>
      render("stages/plan-review-browser.md", {
        custom: "check every migration step against the rollback story",
      }),
  },
  {
    // The objective draft-review door: registered globally but stage-gated at entry to the two
    // objective-draft-authoring stages — the guidance can only ever land in those sessions.
    drive: "stages/objective-review-browser.md (/objective-review-browser)",
    // The objective chooser's wave arm lands it gated too.
    landings: [...rw(OBJECTIVE_STAGES), ...ro(OBJECTIVE_STAGES)],
    text: () =>
      render("stages/objective-review-browser.md", {
        custom: "check the roadmap ordering against the dependency story",
      }),
  },
  {
    // The simplify doors: registered globally but stage-gated at entry to the stages whose
    // diets carry the subject's draft tool (the browser doors' draft stages).
    drive: "stages/simplify.md (/simplify-plan)",
    landings: rw(["plan", "save", "objective-plan"]),
    text: () => simplifyGuidance({ subject: "plan", intensity: "lite", nodeScoped: true }),
  },
  {
    drive: "stages/simplify.md (/simplify-objective)",
    landings: rw(["objective-author", "objective-save"]),
    text: () => simplifyGuidance({ subject: "objective", intensity: "ultra", nodeScoped: false }),
  },
  {
    // The draftless /gist-save fallback exits the gate first; the save tool is the gist pair's.
    drive: "stages/gist-save.md (/gist-save)",
    landings: rw(GIST_STAGES),
    text: () => gistSaveGuidance("Test gist"),
  },
  {
    drive: "stages/pr-review-terminal/local.md",
    landings: rw(WORKTREE_STAGES),
    text: () => prReviewTerminalGuidance({ mode: "local", worktree: "/tmp/wt", baseSha: "abc123" }),
    namesNoTools: true,
  },
  {
    drive: "stages/objective-save.md",
    landings: rw(["objective-author", "objective-save"]),
    text: () => render("stages/objective-save.md", { title: "Test objective" }),
  },
  {
    // Registered globally, so the drive can land in any of the 10 registry stages. The guidance
    // names no scoped tool by design (plain git work) — the entry keeps future edits honest.
    drive: "commit-and-compact.md (/commit-and-compact)",
    landings: rw(GLOBAL_COMMAND_STAGES),
    text: () => commitAndCompactGuidance(),
    namesNoTools: true,
  },
  {
    // Completion can dispatch from the same globally registered command in every stage. The
    // generic arm names no scoped tool; provider-aware plan rereads are selected at runtime.
    drive: "commit-and-compact-continuation.md (/commit-and-compact completion)",
    landings: rw(GLOBAL_COMMAND_STAGES),
    text: () => commitAndCompactContinuation(null, { outcome: "clean" }),
    namesNoTools: true,
  },
  {
    // The Linear arm names only its canonical read tools — foreign names, governed by the
    // `npm:pi-mono-linear` posture row (research: eligible in every landing), so the perk-only
    // scan finds nothing here.
    drive: "commit-and-compact-continuation.md (Linear active plan)",
    landings: rw(GLOBAL_COMMAND_STAGES),
    namesNoTools: true,
    text: () =>
      commitAndCompactContinuation(
        {
          provider: "linear",
          pr_id: "uuid-1",
          url: "https://linear.app/x/ENG-1",
          labels: [],
          objective_id: null,
        },
        { outcome: "read-only" },
      ),
  },
  // The warm learn factories run only where the plan_save tool is active (the interactive host
  // guard): read-write, in a plan-family stage or unscoped.
  ...[DOCS_FACTORY, CODE_FACTORY].map((kind) => ({
    drive: `${kind.seedTemplate} (warm /${kind.name})`,
    landings: [...rw(PLAN_FAMILY_STAGES), { stage: null, mode: "read-write" as const }],
    text: () => learnFactoryGuidance(kind, "inbox.md", ["45", "50"]),
  })),
  {
    // The /plan toggle's gated guidance: injected in every gated stage plan guidance rides.
    drive: "contexts/plan-authoring.md (/plan toggle)",
    landings: ro([null, ...REGISTRY_STAGE_IDS.filter((id) => isPlanGuidanceStage(id))]),
    text: () => PLAN_AUTHORING_CONTEXT,
  },
  {
    drive: "contexts/objective-authoring.md",
    landings: ro(["objective-author"]),
    text: () => OBJECTIVE_AUTHORING_CONTEXT,
  },
  {
    drive: "contexts/gist-authoring.md",
    landings: ro(["gist-author"]),
    text: () => GIST_AUTHORING_CONTEXT,
  },
  {
    drive: "contexts/objective-refinement.md",
    landings: ro(["objective-refine"]),
    text: () => REFINEMENT_CONTEXT,
  },
  {
    // The warm /objective-plan seed — the session claims stage objective-plan, gated.
    drive: "factoryGuidance (warm /objective-plan, github)",
    landings: ro(["objective-plan"]),
    text: () => factoryGuidance("5", "2.1", "github", "https://example.test/issues/5"),
  },
  {
    drive: "factoryGuidance (warm /objective-plan, linear)",
    landings: ro(["objective-plan"]),
    text: () => factoryGuidance("5", "2.1", "linear", "https://linear.app/x/ENG-5"),
  },
  {
    // The warm /objective-refine seed (refinementGuidance renders this template).
    drive: "stages/objective-refine/seed.md (warm /objective-refine)",
    landings: ro(["objective-refine"]),
    text: () =>
      render("stages/objective-refine/seed.md", {
        number: "5",
        title: "Test objective",
        node_id: "2.1",
        node_description: "Refine the node",
        read_clause: objectiveReadInstruction("linear", "5", "https://linear.app/x/ENG-5"),
        context_path: "/tmp/context.json",
        prior_note: "A prior refinement exists.",
      }),
  },
  ...[null, ...REGISTRY_STAGE_IDS].map((stage) => ({
    drive: `renderReadOnlyContext(${String(stage)})`,
    landings: ro([stage]),
    text: () => renderReadOnlyContext(stage),
  })),
  ...DRAFT_SUBJECT_LANDINGS.flatMap(([subject, landings]) => [
    {
      drive: `draftAndCompactGuidance(${subject})`,
      landings,
      text: () => draftAndCompactGuidance(subject, "current draft"),
    },
    {
      drive: `draftAndCompactContinuation(${subject})`,
      landings,
      text: () => draftAndCompactContinuation(subject, "the draft content"),
    },
  ]),
];

test("drive coverage: the simplify guidance names exactly its draft tool + plan_review in every arm", () => {
  for (const subject of ["plan", "objective"] as const) {
    for (const intensity of ["lite", "full", "ultra"] as const) {
      for (const nodeScoped of subject === "plan" ? [true, false] : [false]) {
        const named = referencedScopedTools(simplifyGuidance({ subject, intensity, nodeScoped }));
        assert.deepEqual(
          named.sort(),
          [`${subject}_draft`, "plan_review"].sort(),
          `${subject}/${intensity}/nodeScoped=${nodeScoped}`,
        );
      }
    }
  }
});

test("prompt guard: every carrier names only tools eligible in every (stage, mode) landing it has", () => {
  const violations: string[] = [];
  for (const { drive, landings, text, namesNoTools } of DRIVE_COVERAGE) {
    const named = referencedScopedTools(text());
    if (namesNoTools !== true && named.length === 0) {
      violations.push(`${drive}: names no scoped tool at all — is the scan broken?`);
    }
    for (const { stage, mode } of landings) {
      if (stage !== null && !REGISTRY_STAGE_IDS.includes(stage)) {
        violations.push(`${drive}: unknown stage id in the table: ${stage}`);
      }
      for (const name of named) {
        if (!isEligible(name, undefined, stage, mode)) {
          violations.push(`${drive} names \`${name}\` — ineligible in (${String(stage)}, ${mode})`);
        }
      }
    }
  }
  // A violation means the carrier would dead-end in that session: reword the carrier — never
  // widen a policy to fit.
  assert.deepEqual(violations, []);
});

test("prompt guard: the match rule's representative cases", () => {
  // The gate's own prose and the generated writer lines are never findings.
  for (const stage of [null, ...REGISTRY_STAGE_IDS]) {
    const context = renderReadOnlyContext(stage);
    assert.ok(context.includes("edit/write are blocked"));
    assert.ok(!referencedScopedTools(context).includes("edit"));
    assert.ok(!referencedScopedTools(context).includes("write"));
  }
  assert.deepEqual(referencedScopedTools("the bounded write is fine; the plan is ready"), []);
  // A backticked single-word tool IS a finding (ineligible in a gated authoring landing)…
  assert.deepEqual(referencedScopedTools("then call `submit`"), ["submit"]);
  assert.equal(isEligible("submit", undefined, "plan", "read-only"), false);
  // …while the bare word is not; an underscore name matches bare.
  assert.deepEqual(referencedScopedTools("when ready, submit the work"), []);
  assert.deepEqual(referencedScopedTools("fall back to plan_save"), ["plan_save"]);
  assert.equal(isEligible("plan_save", undefined, "objective-plan", "read-only"), false);
  // `_` is a word char: no partial-identifier match.
  assert.deepEqual(referencedScopedTools("explore_objective_node"), ["explore_objective_node"]);
  assert.deepEqual(referencedScopedTools("`land` and explore_objective_node").sort(), [
    "explore_objective_node",
    "land",
  ]);
  // A foreign name is outside the universe whatever its quoting.
  assert.deepEqual(referencedScopedTools("`subagent` and subagent_supervisor"), []);
});

test("prompt guard: the scan universe is exactly the catalog (no foreign name, no builtin)", () => {
  assert.deepEqual([...scanUniverse()].sort(), [...perkToolNames()].sort());
  for (const name of Object.keys(toolMatrix().tools).filter((n) => !isPerkTool(n))) {
    assert.equal(toolMatrix().tools[name]?.owner, "builtin", name);
  }
});
