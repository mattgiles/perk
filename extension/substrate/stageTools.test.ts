// Stage-scoped active tools (contracts.md §8.40): the STAGE_TOOLS map hygiene + the live
// scoping behavior driven through a REAL bound AgentSession via the harness (fully offline).
// Sibling of toolGating.test.ts (which stays focused on the read-only gate itself).

import assert from "node:assert/strict";
import { test } from "node:test";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import { commitAndCompactContinuation, commitAndCompactGuidance } from "../doors/commitCompact.ts";
import {
  objectiveLandGuidance,
  objectiveRecoverGuidance,
  objectiveSyncGuidance,
} from "../doors/objectiveStack.ts";
import { prReviewGuidance } from "../doors/prReview.ts";
import { stackReviewGuidance } from "../doors/stackReviewBrowser.ts";
import { reconcileGuidance } from "../factories/objectivePlan.ts";
import {
  loadPerkSession,
  type PerkSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { render } from "./prompts.ts";
import { loadRegistry } from "./registry.ts";
import {
  BORROWED_TOOLS,
  FFF_SEARCH_TOOLS,
  LINEAR_READ_TOOLS,
  PERK_TOOLS,
  READ_ONLY_TOOLS,
  STAGE_TOOLS,
  WEB_RESEARCH_TOOLS,
} from "./toolGating.ts";

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

test("STAGE_TOOLS: the two objective stage lists are pinned exactly (least privilege)", () => {
  // The exact-set pin for the /objective-review-browser widening: the six authoring/reconcile
  // tools + the draft-review companions + plan_review (the door guidance names it; it routes to
  // the objective review arm in both stages) + the universal research bundle — and NOTHING
  // else. A presence check alone would let unrelated scoped tools ride these gate-OFF sessions
  // (e.g. the §8.66 ready-time reconcile guidance deliberately avoids naming `ready`, so the
  // zero-argument ready tool never rides an unbound main-root objective session where it could
  // act on the cached selector's plan instead of the continuation's).
  const expected = [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    "plan_review",
    ...WEB_RESEARCH_TOOLS,
    ...LINEAR_READ_TOOLS,
    ...FFF_SEARCH_TOOLS,
  ].sort();
  for (const stage of ["objective-author", "objective-save"]) {
    assert.deepEqual(
      [...(STAGE_TOOLS[stage] ?? [])].sort(),
      expected,
      `STAGE_TOOLS.${stage} must carry exactly the pinned objective-stage set`,
    );
  }
});

test("STAGE_TOOLS: keys set-equal the registry stage ids", () => {
  const registryIds = loadRegistry()
    .stages.map((s) => s.id)
    .sort();
  const mapKeys = Object.keys(STAGE_TOOLS).sort();
  assert.deepEqual(
    mapKeys,
    registryIds,
    "STAGE_TOOLS must carry exactly one entry per registry stage id",
  );
});

test("STAGE_TOOLS: every listed name is in the scoped universe, and ask_user_question is universal", () => {
  const scoped = new Set([...PERK_TOOLS, ...BORROWED_TOOLS]);
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    for (const name of tools) {
      assert.ok(
        scoped.has(name),
        `${stage} lists a name outside PERK_TOOLS ∪ BORROWED_TOOLS: ${name}`,
      );
    }
    assert.ok(tools.includes("ask_user_question"), `${stage} must carry ask_user_question`);
  }
});

test("STAGE_TOOLS: every stage list carries the FFF search tools (via the universal bundle)", () => {
  // FFF local search rides RESEARCH_TOOLS (the universal non-mutating bundle); this pins the
  // universality so a future stage-list refactor can't silently shed it.
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    for (const name of FFF_SEARCH_TOOLS) {
      assert.ok(tools.includes(name), `${stage} must carry the FFF search tool ${name}`);
    }
  }
});

test("BORROWED_TOOLS: no duplicates and zero overlap with PERK_TOOLS (single governance)", () => {
  assert.equal(
    new Set(BORROWED_TOOLS).size,
    BORROWED_TOOLS.length,
    "BORROWED_TOOLS carries a duplicate name",
  );
  assert.deepEqual(
    BORROWED_TOOLS.filter((name) => PERK_TOOLS.includes(name)),
    [],
    "a name is governed ONCE — it lives in exactly one census (perk-registered names in PERK_TOOLS, borrowed names like ask_user_question in BORROWED_TOOLS)",
  );
});

test("PERK_TOOLS: set-equals the non-builtin tools a perk-only session registers", async () => {
  // The completeness drift guard: the harness binds ONLY perk with no [providers] config, so all
  // perk registrations are live and builtins are the only other source. A new perk tool must be
  // classified into PERK_TOOLS + STAGE_TOOLS before it can register.
  const cwd = scaffoldRepo();
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: undefined } });
  try {
    const registered = h.session
      .getAllTools()
      .filter((t) => t.sourceInfo.source !== "builtin")
      .map((t) => t.name)
      .sort();
    assert.deepEqual(
      registered,
      [...PERK_TOOLS].sort(),
      "a new perk tool must be classified into PERK_TOOLS and the STAGE_TOOLS map",
    );
  } finally {
    h.dispose();
  }
});

test("implement claim: PR-loop family active, the 5 authoring tools scoped off", async () => {
  const runId = "01STAGETOOLIMPL";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId } });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["submit", "ready", "run_ci", "land", "learn", "finalize_address"]) {
      assert.ok(active.includes(name), `PR-loop tool must stay active: ${name}`);
    }
    // The reconcile trio rides the worktree family (the post-land reconcile drive).
    for (const name of ["reconcile_objective", "add_objective_node", "objective_node"]) {
      assert.ok(active.includes(name), `reconcile-trio tool must stay active: ${name}`);
    }
    for (const name of ["read", "bash", "edit", "write"]) {
      assert.ok(active.includes(name), `builtin must pass through untouched: ${name}`);
    }
    for (const name of AUTHORING_TOOLS) {
      assert.ok(!active.includes(name), `authoring tool must be scoped off: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("gated stage: gate ON keeps exactly the READ_ONLY_TOOLS-available subset (no stage filter)", async () => {
  const runId = "01STAGETOOLOBJP";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-only", stage: "objective-plan" } });
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    // `subagent` registered so the gated delegation carve-in has a name to activate (the
    // objective-plan explorer spawn).
    extraExtensions: [fakeBorrowedPackage(["subagent"])],
  });
  try {
    const active = [...h.session.getActiveToolNames()].sort();
    // The gate-on set is byte-for-byte today's: the registered subset of READ_ONLY_TOOLS,
    // including the carve-outs a strict stage intersection would have broken.
    const expected = h.session
      .getAllTools()
      .map((t) => t.name)
      .filter((name) => READ_ONLY_TOOLS.includes(name))
      .sort();
    assert.deepEqual(active, expected);
    for (const name of ["objective_node", "plan_draft", "plan_review", "subagent"]) {
      assert.ok(active.includes(name), `gated carve-out must stay active: ${name}`);
    }
    for (const name of ["edit", "write"]) {
      assert.ok(!active.includes(name), `${name} must be inactive while gated`);
    }
  } finally {
    h.dispose();
  }
});

test("gated adopt-child: the engine's child-side tools survive the inherited gate", async () => {
  // The live regression (the objective-plan explorer failure): a spawned child inherits the
  // parent's read-only mode via the adopt arm (consumed handoff + env PERK_RUN_ID), and the
  // engine's child-side tools — registered at extension LOAD time, before perk's session_start
  // sync — must survive the gate's setActiveTools. Stripping structured_output made an
  // outputSchema child physically unable to make the engine-required completion call
  // (structuredOutputFailed after the whole exploration ran).
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
    // Load-time registration mirrors the real prompt runtime (registered BEFORE perk's
    // session_start sync — the order that reproduced the strip).
    extraExtensions: [
      fakeBorrowedPackage(["structured_output", "contact_supervisor", "subagent_wait"]),
    ],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["structured_output", "contact_supervisor", "subagent_wait"]) {
      assert.ok(active.includes(name), `child-side engine tool must survive the gate: ${name}`);
    }
    for (const name of ["read", "bash"]) {
      assert.ok(active.includes(name), `read-only tool must stay active: ${name}`);
    }
    for (const name of ["edit", "write"]) {
      assert.ok(!active.includes(name), `the gate itself still holds in the child: ${name}`);
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
    // Nothing filtered: every perk tool and the default-active builtins stay active.
    for (const name of [...PERK_TOOLS, "read", "bash", "edit", "write"]) {
      assert.ok(active.has(name), `must stay active in an unscoped session: ${name}`);
    }
    // Nothing widened: pi registers grep/find/ls but leaves them INACTIVE by default — an
    // accidental setActiveTools (e.g. a restore via the getAllTools fallback) would activate
    // them. Their staying inactive is the sharp zero-setActiveTools canary (this pins pi's
    // current default; update if pi ever activates these by default).
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

    // Navigate to the read-only entry → gate ON → exactly the READ_ONLY_TOOLS-available subset.
    await h.navigateTo(readOnlyId);
    const gated = [...h.session.getActiveToolNames()].sort();
    const expectedGated = h.session
      .getAllTools()
      .map((t) => t.name)
      .filter((name) => READ_ONLY_TOOLS.includes(name))
      .sort();
    assert.deepEqual(gated, expectedGated);

    // Navigate to the read-write entry → gate OFF + stage plan → the stage-filtered set.
    await h.navigateTo(readWriteId);
    const scoped = h.session.getActiveToolNames();
    assert.ok(scoped.includes("plan_save"), "plan-stage tool active once the gate is off");
    assert.ok(!scoped.includes("submit"), "PR-loop tool scoped off in a plan-stage session");
    assert.ok(scoped.includes("edit"), "builtins restored once the gate is off");
    assert.ok(scoped.includes("write"));
  } finally {
    h.dispose();
  }
});

// --- borrowed-package scoping (the fake-borrowed-package idiom, mirroring fakePlannotator) -------

/**
 * A fake borrowed-package extension registering LOAD-TIME tools with the given names (the
 * pi-subagents / rpiv-todo / pi-web-access / pi-mono-linear / plannotator registration shape).
 * Bound after perk via extraExtensions, so the tools exist before perk's session_start sync.
 */
function fakeBorrowedPackage(names: readonly string[]): (pi: ExtensionAPI) => void {
  return (pi) => {
    for (const name of names) {
      pi.registerTool({
        name,
        label: name,
        description: `fake borrowed tool ${name} (test)`,
        parameters: { type: "object", properties: {} },
        async execute() {
          return { content: [{ type: "text", text: "ok" }], details: {} };
        },
      });
    }
  };
}

/** The census cross-section the fake package registers (+ one un-enumerated foreign name). */
const FAKE_BORROWED_NAMES = [
  "subagent",
  "wait",
  "todo",
  "web_search",
  "linear_get_issue",
  "linear_create_issue",
  "plannotator_submit_plan",
  "some_foreign_tool",
];

test("implement claim: borrowed tools follow the matrix (research/delegation/todo stay; mutating/submit drop)", async () => {
  const runId = "01STAGETOOLBRWI";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const h = await loadAt(cwd, {
    env: { PERK_RUN_ID: runId },
    extraExtensions: [fakeBorrowedPackage(FAKE_BORROWED_NAMES)],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["subagent", "wait", "todo", "web_search", "linear_get_issue"]) {
      assert.ok(active.includes(name), `worktree-stage borrowed tool must stay active: ${name}`);
    }
    assert.ok(
      active.includes("some_foreign_tool"),
      "an un-enumerated foreign name passes through untouched (fail-open)",
    );
    for (const name of ["linear_create_issue", "plannotator_submit_plan"]) {
      assert.ok(!active.includes(name), `census tool in no stage list must be scoped off: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

test("plan stage (read-write): delegation + todo scoped off; research passes", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "plan", mode: "read-write" }]);
  const h = await loadAt(cwd, {
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
    extraExtensions: [fakeBorrowedPackage(FAKE_BORROWED_NAMES)],
  });
  try {
    const active = h.session.getActiveToolNames();
    for (const name of ["subagent", "wait", "todo"]) {
      assert.ok(!active.includes(name), `worktree-only borrowed tool must drop in plan: ${name}`);
    }
    for (const name of ["web_search", "linear_get_issue"]) {
      assert.ok(active.includes(name), `research tool must stay active in plan: ${name}`);
    }
    assert.ok(active.includes("some_foreign_tool"), "un-enumerated foreign name passes through");
  } finally {
    h.dispose();
  }
});

test("late registration leaks past rebuild-point filtering (the accepted supervisor-pair leak)", async () => {
  // Mirrors pi-subagents' parent intercom pair: registered inside its own session_start handler,
  // bound AFTER perk (the real load order — perk is the first `packages` entry), so registration
  // lands after perk's sync. Pi activation semantics: a tool registered after a setActiveTools
  // call becomes active — the pair leaks at launch (accepted + documented in BORROWED_TOOLS; a
  // later tree-navigation re-apply filters over the original snapshot and drops it).
  const runId = "01STAGETOOLLEAK";
  const cwd = scaffoldRepo({ handoff: { runId, mode: "read-write", stage: "implement" } });
  const lateRegistrar = (pi: ExtensionAPI): void => {
    pi.on("session_start", async () => {
      pi.registerTool({
        name: "subagent_supervisor",
        label: "subagent_supervisor",
        description: "fake late-registered parent intercom (test)",
        parameters: { type: "object", properties: {} },
        async execute() {
          return { content: [{ type: "text", text: "ok" }], details: {} };
        },
      });
    });
  };
  const h = await loadAt(cwd, { env: { PERK_RUN_ID: runId }, extraExtensions: [lateRegistrar] });
  try {
    assert.ok(
      h.session.getActiveToolNames().includes("subagent_supervisor"),
      "a tool registered after perk's sync stays active (the documented launch leak)",
    );
  } finally {
    h.dispose();
  }
});

// --- the drive-coverage guard (the structural "this must not happen again") ---------------------

const WORKTREE_STAGES: readonly string[] = ["implement", "submit", "address", "land", "learn"];
const GLOBAL_COMMAND_STAGES: readonly string[] = [
  ...WORKTREE_STAGES,
  "objective-author",
  "objective-save",
  "objective-plan",
  "plan",
  "save",
];

/**
 * Every scoped-universe tool name a rendered guidance references (word-boundary scan against
 * PERK_TOOLS ∪ BORROWED_TOOLS). Conservative on purpose: a negative mention ("do NOT call X")
 * still counts — acceptable, since an inactive X would confuse the model either way. Names are
 * `[a-z_]+` so no regex escaping is needed, and `_` is a word char so `\bsubagent\b` does not
 * match inside `subagent_supervisor`.
 */
function referencedScopedTools(text: string): string[] {
  return [...new Set([...PERK_TOOLS, ...BORROWED_TOOLS])].filter((name) =>
    new RegExp(`\\b${name}\\b`).test(text),
  );
}

/**
 * The static drive→stages table: every gate-OFF warm-door drive (a `sendUserMessage` guidance
 * injection) paired with EVERY stage its session can be in when the guidance lands. Each render
 * uses dummy params with all optional params SET (the richer conditional arm — the tool names
 * appear in both arms today). Gated-landing drives (the objective-plan seed/guidance, the
 * plan-family factory seeds) are deliberately excluded: gate-ON ignores stage lists, and the
 * gated-stage test above covers that surface (READ_ONLY_TOOLS carve-outs incl. delegation).
 */
const DRIVE_COVERAGE: readonly {
  drive: string;
  stages: readonly string[];
  text: () => string;
  /** The drive deliberately names NO scoped tool — skip the scan-broken tripwire for this row. */
  namesNoTools?: boolean;
}[] = [
  {
    // The reported regression: `/land` auto-drives the reconcile pass in the CURRENT worktree
    // session, and the manual `/objective-reconcile` gesture is registered globally.
    drive: "reconcileGuidance (post-land drive + /objective-reconcile)",
    stages: [...WORKTREE_STAGES, "objective-author", "objective-save", "objective-plan"],
    text: () => reconcileGuidance("5", "github", "https://example.test/issues/5"),
  },
  {
    // The ready→reconcile continuation drive (contracts.md §8.66): fires wherever a stacked
    // `/ready` can succeed — the same stage set as the reconcile drive above (the pass uses
    // the same reconcile trio). Gate-active sessions are covered by the drive's own
    // gating.isActive() refusal, not by this list. The template deliberately names NO
    // ready/land re-entry gesture (re-entry guidance lives on the human-facing surfaces), so
    // this row passes without widening the objective-stage lists.
    drive: "driveReadyReconcile (stages/objective-reconcile-ready.md)",
    stages: [...WORKTREE_STAGES, "objective-author", "objective-save", "objective-plan"],
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
    // recovery and the atomic landing from anywhere in the PR loop) — WORKTREE_STAGE_TOOLS
    // carries the quintet.
    drive: "stages/objective-sync.md (/objective-sync)",
    stages: WORKTREE_STAGES,
    text: () => objectiveSyncGuidance("5"),
  },
  {
    drive: "stages/objective-recover.md (/objective-recover)",
    stages: WORKTREE_STAGES,
    text: () => objectiveRecoverGuidance("5"),
  },
  {
    drive: "stages/objective-land.md (/objective-land)",
    stages: WORKTREE_STAGES,
    text: () => objectiveLandGuidance("5"),
  },
  {
    drive: "stages/learn.md",
    stages: WORKTREE_STAGES,
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
    stages: WORKTREE_STAGES,
    text: () =>
      render("stages/learn-orchestrate.md", {
        manifest_path: "/tmp/bundle/manifest.json",
        bundle_dir: "/tmp/bundle",
      }),
  },
  {
    drive: "stages/conflict-resolution.md",
    stages: WORKTREE_STAGES,
    text: () =>
      render("stages/conflict-resolution.md", {
        base: "main",
        attempt: "1",
        cap: "2",
        worktree: "/tmp/wt",
        model: "test-model",
      }),
  },
  {
    drive: "stages/conflict-resolution-continuation.md (sync conflict drive + resolve mode)",
    stages: WORKTREE_STAGES,
    text: () =>
      render("stages/conflict-resolution-continuation.md", {
        objective: "5",
        node: "2.1",
        branch: "plan-42",
        pr: "42",
        worktree: "/tmp/wt",
        attempt: "1",
        cap: "2",
        model: "test-model",
      }),
  },
  {
    drive: "stages/address/preview.md",
    stages: WORKTREE_STAGES,
    text: () =>
      render("stages/address/preview.md", {
        provider: "github",
        pr_id: "42",
        url: "https://example.test/pull/42",
      }),
  },
  {
    drive: "stages/address/action.md",
    stages: WORKTREE_STAGES,
    text: () =>
      render("stages/address/action.md", {
        provider: "github",
        pr_id: "42",
        url: "https://example.test/pull/42",
      }),
  },
  {
    drive: "stages/pr-review.md",
    stages: WORKTREE_STAGES,
    text: () => prReviewGuidance("focus"),
  },
  {
    drive: "stages/pr-review-terminal/active.md",
    stages: WORKTREE_STAGES,
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
    stages: WORKTREE_STAGES,
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
    stages: WORKTREE_STAGES,
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
    stages: WORKTREE_STAGES,
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
    stages: [...WORKTREE_STAGES, "stack-review"],
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
      }),
  },
  {
    // The stack-review cold seed: the launched session's initial prompt names the ONE
    // open_stack_review call, so the tool must be active in the stack-review stage.
    drive: "stages/stack-review/cold.md (perk objective stack review seed)",
    stages: ["stack-review"],
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
    stages: ["plan", "save", "objective-plan"],
    text: () =>
      render("stages/plan-review-browser.md", {
        custom: "check every migration step against the rollback story",
      }),
  },
  {
    // The objective draft-review door: registered globally but stage-gated at entry to the two
    // objective-draft-authoring stages — the guidance can only ever land in those sessions.
    drive: "stages/objective-review-browser.md (/objective-review-browser)",
    stages: ["objective-author", "objective-save"],
    text: () =>
      render("stages/objective-review-browser.md", {
        custom: "check the roadmap ordering against the dependency story",
      }),
  },
  {
    drive: "stages/objective-save.md",
    stages: ["objective-author", "objective-save"],
    text: () => render("stages/objective-save.md", { title: "Test objective" }),
  },
  {
    // Registered globally, so the drive can land in any of the 10 registry stages. The guidance
    // names no scoped tool by design (plain git work) — the entry keeps future edits honest.
    drive: "commit-and-compact.md (/commit-and-compact)",
    stages: GLOBAL_COMMAND_STAGES,
    text: () => commitAndCompactGuidance(),
    namesNoTools: true,
  },
  {
    // Completion can dispatch from the same globally registered command in every stage. The
    // generic arm names no scoped tool; provider-aware plan rereads are selected at runtime.
    drive: "commit-and-compact-continuation.md (/commit-and-compact completion)",
    stages: GLOBAL_COMMAND_STAGES,
    text: () => commitAndCompactContinuation(null, { outcome: "clean" }),
    namesNoTools: true,
  },
  {
    // The Linear arm names its canonical read tools, so the global-stage census must prove both
    // remain reachable wherever a provider-aware continuation can land.
    drive: "commit-and-compact-continuation.md (Linear active plan)",
    stages: GLOBAL_COMMAND_STAGES,
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
];

test("drive coverage: every gate-off drive's named tools are active in every stage it can land in", () => {
  for (const { drive, stages, text, namesNoTools } of DRIVE_COVERAGE) {
    const named = referencedScopedTools(text());
    if (namesNoTools !== true) {
      assert.ok(named.length > 0, `${drive}: names no scoped tool at all — is the scan broken?`);
    }
    for (const stage of stages) {
      const stageList = STAGE_TOOLS[stage];
      assert.ok(stageList !== undefined, `${drive}: unknown stage id in the table: ${stage}`);
      for (const name of named) {
        assert.ok(
          stageList.includes(name),
          `${drive} names \`${name}\` but STAGE_TOOLS.${stage} scopes it off — the drive ` +
            "would dead-end in that session (add the tool to the stage list or fix the drive)",
        );
      }
    }
  }
});
