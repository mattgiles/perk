// Live warm-surface tests for the stacked-delivery door (objectiveStack.ts): registration
// census, the driving commands' gate-on soft refusal, the pure guidance, strict tool decodes,
// cold-door argv shapes, objective inference precedence, and the lenient renders. Fully offline
// (fakePerk via PERK_BIN; a REAL bound AgentSession via the T1 harness).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "../substrate/cache.ts";
import {
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../testing/harness.ts";
import {
  buildStackAdoptArgs,
  buildStackRecoverArgs,
  buildStackSyncArgs,
  objectiveRecoverGuidance,
  objectiveSyncGuidance,
  renderRecoverOutcome,
  renderStackStatus,
  renderSyncOutcome,
} from "./objectiveStack.ts";

const STACK_TOOLS = [
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
];

const STACK_COMMANDS = ["objective-stack", "objective-sync", "objective-recover"];

/** A minimal success envelope every stack worker fake can return (renders leniently). */
const OK_ENVELOPE = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
  no_op: false,
  declined: false,
  affected: [],
  operations: [],
});

// --- registration census -------------------------------------------------------------------------

test("registration: three commands + four tools, headless-safe load", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined }, headful: false });
  try {
    for (const name of STACK_COMMANDS) {
      assert.ok(h.registeredCommands().includes(name), `command registered: ${name}`);
    }
    for (const name of STACK_TOOLS) {
      assert.ok(h.registeredTool(name) !== null, `tool registered: ${name}`);
    }
  } finally {
    h.dispose();
  }
});

// --- the driving commands' gate-on soft refusal ---------------------------------------------------

test("gate-on: /objective-sync and /objective-recover soft-refuse (notify, inject nothing)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    for (const name of ["objective-sync", "objective-recover"]) {
      await h.invokeCommand(name, "7");
    }
    assert.deepEqual(injected, [], "a gated session gets NO guidance injection");
    assert.equal(
      h.notifyEvents.filter((e) => e.severity === "warning" && /read-only session/.test(e.message))
        .length,
      2,
      "both driving commands notified the soft refusal",
    );
  } finally {
    h.dispose();
  }
});

test("gate-on headless: the soft refusal mirrors to stderr", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  const injected = spyInjections(h);
  const errors: string[] = [];
  t.mock.method(console, "error", (message: string) => {
    errors.push(String(message));
  });
  try {
    await h.invokeCommand("objective-sync", "7");
    assert.deepEqual(injected, [], "headless gated session injects nothing");
    assert.ok(
      errors.some((m) => /objective-sync/.test(m) && /read-only session/.test(m)),
      "the refusal reached stderr (the headless mirror)",
    );
  } finally {
    h.dispose();
  }
});

test("gate-off: the driving commands inject the guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    await h.invokeCommand("objective-sync", "7");
    await h.invokeCommand("objective-recover", "#7");
    assert.equal(injected.length, 2);
    assert.ok(injected[0]?.includes("objective #7"), "sync guidance names the objective");
    assert.ok(injected[0]?.includes("objective_stack_sync"), "sync guidance names its tool");
    assert.ok(injected[1]?.includes("objective_stack_recover"), "recover guidance names its tool");
  } finally {
    h.dispose();
  }
});

// --- the pure guidance ----------------------------------------------------------------------------

test("guidance: preview-first, consent-gated, no hardcoded skill pointer", () => {
  const syncText = objectiveSyncGuidance("7");
  for (const needle of [
    "objective_stack_status",
    "objective_stack_sync",
    "objective_stack_adopt",
    "dry_run: true",
    "confirm: true",
    "continue: true",
    "abort: true",
    "explicit human approval",
  ]) {
    assert.ok(syncText.includes(needle), `sync guidance must include: ${needle}`);
  }
  const recoverText = objectiveRecoverGuidance("7");
  for (const needle of [
    "objective_stack_recover",
    "dry_run: true",
    "abandon: true, confirm: true",
    'operation: "<ULID>"',
    "explicit human approval",
  ]) {
    assert.ok(recoverText.includes(needle), `recover guidance must include: ${needle}`);
  }
  for (const text of [syncText, recoverText]) {
    assert.ok(!/skills\//.test(text), "no hardcoded skill pointer (bindings own delivery)");
    assert.ok(!/perk-objective-(sync|recover)\b/.test(text), "no hardcoded skill name");
  }
});

// --- strict tool decodes ---------------------------------------------------------------------------

async function invokeExpectingFail(
  h: Awaited<ReturnType<typeof loadPerkSession>>,
  tool: string,
  params: unknown,
  errorType: string,
): Promise<void> {
  const result = await h.invokeTool(tool, params);
  const details = result.details as { ok: boolean; error_type?: string };
  assert.equal(details.ok, false, `${tool} ${JSON.stringify(params)} must refuse`);
  assert.equal(details.error_type, errorType);
}

test("decode: the sync mode matrix and mistyped fields refuse the whole call", async () => {
  const cwd = scaffoldRepo();
  // A throwing PERK_BIN proves the refusals happen before any cold-door exec.
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await invokeExpectingFail(
      h,
      "objective_stack_sync",
      { continue: true, abort: true },
      "bad_input",
    );
    await invokeExpectingFail(
      h,
      "objective_stack_sync",
      { continue: true, base: true },
      "bad_input",
    );
    await invokeExpectingFail(
      h,
      "objective_stack_sync",
      { abort: true, dry_run: true },
      "bad_input",
    );
    await invokeExpectingFail(h, "objective_stack_sync", { dry_run: "yes" }, "bad_input");
    await invokeExpectingFail(h, "objective_stack_status", { objective: [] }, "bad_input");
  } finally {
    h.dispose();
  }
});

test("decode: adopt requires node; mutating adopt/abandon require confirm", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await invokeExpectingFail(h, "objective_stack_adopt", { objective: "7" }, "bad_input");
    await invokeExpectingFail(h, "objective_stack_adopt", { node: "" }, "bad_input");
    const adoptRefusal = await h.invokeTool("objective_stack_adopt", {
      objective: "7",
      node: "1.2",
    });
    assert.equal(
      (adoptRefusal.details as { ok: boolean; error_type?: string }).error_type,
      "confirmation_required",
    );
    assert.match(adoptRefusal.content[0]?.text ?? "", /accepts a published branch head/);
    assert.doesNotMatch(adoptRefusal.content[0]?.text ?? "", /stack membership/);
    await invokeExpectingFail(
      h,
      "objective_stack_recover",
      { objective: "7", abandon: true },
      "confirmation_required",
    );
    // dry_run × abandon is the CLI matrix refusal, enforced at the decode.
    await invokeExpectingFail(
      h,
      "objective_stack_recover",
      { abandon: true, confirm: true, dry_run: true },
      "bad_input",
    );
  } finally {
    h.dispose();
  }
});

// --- argv shapes (pure builders + one live delegation) --------------------------------------------

const SYNC_DEFAULTS = {
  objective: undefined,
  base: false,
  dryRun: false,
  continue_: false,
  abort: false,
};

test("argv: sync modes — --yes on mutating paths, absent on dry-run", () => {
  assert.deepEqual(buildStackSyncArgs("7", { ...SYNC_DEFAULTS }), [
    "objective",
    "stack",
    "sync",
    "7",
    "--yes",
    "--json",
  ]);
  assert.deepEqual(buildStackSyncArgs("7", { ...SYNC_DEFAULTS, base: true, dryRun: true }), [
    "objective",
    "stack",
    "sync",
    "7",
    "--base",
    "--dry-run",
    "--json",
  ]);
  assert.deepEqual(buildStackSyncArgs("7", { ...SYNC_DEFAULTS, continue_: true }), [
    "objective",
    "stack",
    "sync",
    "7",
    "--continue",
    "--yes",
    "--json",
  ]);
  assert.deepEqual(buildStackSyncArgs("7", { ...SYNC_DEFAULTS, abort: true }), [
    "objective",
    "stack",
    "sync",
    "7",
    "--abort",
    "--yes",
    "--json",
  ]);
});

test("argv: adopt — dry-run previews without --yes; the confirmed call passes --yes", () => {
  assert.deepEqual(
    buildStackAdoptArgs("7", { objective: undefined, node: "1.2", dryRun: true, confirm: false }),
    ["objective", "stack", "sync", "7", "--adopt", "1.2", "--dry-run", "--json"],
  );
  assert.deepEqual(
    buildStackAdoptArgs("7", { objective: undefined, node: "1.2", dryRun: false, confirm: true }),
    ["objective", "stack", "sync", "7", "--adopt", "1.2", "--yes", "--json"],
  );
});

test("argv: recover — report/dry-run pass neither --abandon nor --yes; --operation threads", () => {
  const base = {
    objective: undefined,
    operation: undefined,
    dryRun: false,
    abandon: false,
    confirm: false,
  };
  assert.deepEqual(buildStackRecoverArgs("7", { ...base }), [
    "objective",
    "stack",
    "recover",
    "7",
    "--json",
  ]);
  assert.deepEqual(buildStackRecoverArgs("7", { ...base, operation: "01OP", dryRun: true }), [
    "objective",
    "stack",
    "recover",
    "7",
    "--operation",
    "01OP",
    "--dry-run",
    "--json",
  ]);
  assert.deepEqual(
    buildStackRecoverArgs("7", { ...base, operation: "01OP", abandon: true, confirm: true }),
    ["objective", "stack", "recover", "7", "--operation", "01OP", "--abandon", "--yes", "--json"],
  );
});

test("delegation: the sync tool execs the built argv through the cold door", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: 7, dry_run: true });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), [
      "objective",
      "stack",
      "sync",
      "7",
      "--dry-run",
      "--json",
    ]);
  } finally {
    h.dispose();
  }
});

// --- objective inference precedence ----------------------------------------------------------------

const PLAN_REF = {
  provider: "github",
  pr_id: "1457",
  url: "https://github.com/o/r/issues/1457",
  labels: [],
  objective_id: "137",
};

test("inference: explicit param wins over active_objective and plan-ref", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("objective_stack_status", { objective: "42" });
    assert.ok(readFileSync(argvFile, "utf8").includes("42"), "the explicit objective is passed");
  } finally {
    h.dispose();
  }
});

test("inference: active_objective wins over the plan-ref; plan-ref is the last tier", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("objective_stack_status", {});
    const argv = readFileSync(argvFile, "utf8").trim().split("\n");
    assert.ok(argv.includes("9"), "active_objective resolved");
    assert.ok(!argv.includes("137"), "the plan-ref tier is not consulted when active is set");
  } finally {
    h.dispose();
  }
});

test("inference: plan-ref tier resolves when nothing else does; else a soft no_objective fail", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_stack_recover", {});
    assert.ok(readFileSync(argvFile, "utf8").includes("137"), "the plan-ref objective resolved");
  } finally {
    h.dispose();
  }

  const bare = scaffoldRepo();
  const bareBin = fakePerk(bare, { stdout: OK_ENVELOPE });
  const h2 = await loadPerkSession({
    cwd: bare,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bareBin },
  });
  const injected = spyInjections(h2);
  try {
    const result = await h2.invokeTool("objective_stack_status", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_objective");
    // The command twin soft-fails with a warning and injects nothing.
    await h2.invokeCommand("objective-sync");
    assert.deepEqual(injected, []);
    assert.ok(
      h2.notifyEvents.some((e) => e.severity === "warning" && /no objective/.test(e.message)),
    );
  } finally {
    h2.dispose();
  }
});

// --- the lenient renders ----------------------------------------------------------------------------

test("renderStackStatus: train + operations + continuation + residue", () => {
  const text = renderStackStatus({
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    delivery: "stacked",
    train: {
      base: "main",
      published_prefix_len: 1,
      layers: [
        { node_id: "1.1", branch: "plan-101", pr_number: 11, publication: "published" },
        { node_id: "1.2", branch: "plan-102", pr_number: 12, publication: "unpublished" },
      ],
      next_build_ready: { node_id: "1.3", ready: true, reason: null },
      blockers: [{ code: "stack_drift", message: "drifted", node_id: null, plan_id: null }],
      information: [],
    },
    operations: [{ operation_id: "01OP", kind: "sync", prepared_created: "2026-01-01" }],
    continuation: {
      operation_id: "01OP",
      conflict_node_id: "1.2",
      worktree_path: "/wt/sync-01OP",
      manifest_path: "/m/01L.json",
      parseable: true,
    },
    orphaned_residue: { observed: true, reason: null, worktrees: ["/wt/sync-01X"], refs: [] },
  });
  assert.match(text, /stacked delivery train \(base main, published prefix 1\/2\)/);
  assert.match(text, /1\. 1\.1 plan-101 pr #11 \[published\]/);
  assert.match(text, /next build-ready: 1\.3/);
  assert.match(text, /\[stack_drift\] drifted/);
  assert.match(text, /unresolved operation: 01OP \(sync, prepared 2026-01-01\)/);
  assert.match(text, /pending continuation: operation 01OP stopped on node 1\.2/);
  assert.match(text, /orphaned residue: 1 worktree\(s\), 0 ref\(s\)/);
});

test("renderStackStatus: honors observed:false, the unparseable manifest, and no_train", () => {
  const text = renderStackStatus({
    objective: { id: "7" },
    no_train: "objective #7 is incremental",
    continuation: { manifest_path: "/m/01L.json", parseable: false },
    orphaned_residue: { observed: false, reason: "config unavailable", worktrees: [], refs: [] },
  });
  assert.match(text, /Objective #7: objective #7 is incremental/);
  assert.match(text, /UNPARSEABLE manifest at \/m\/01L\.json/);
  assert.match(text, /orphaned residue: not observed — config unavailable/);
});

test("renderSyncOutcome: the arms are mode-aware", () => {
  const affected = [
    {
      node_id: "1.2",
      plan_id: "1457",
      branch: "plan-1457",
      pr_number: 12,
      before_sha: "a".repeat(8),
      after_sha: "b".repeat(8),
    },
  ];
  assert.match(
    renderSyncOutcome({ dry_run: true, affected, adopted_node: "1.2" }, "sync"),
    /dry run: a real sync would adopt \+ cascade 1 layer\(s\)/,
  );
  assert.match(
    renderSyncOutcome({ affected, operation_id: "01OP", continued: true }, "continue"),
    /continued 1 layer\(s\)[\s\S]*operation 01OP complete/,
  );
  assert.equal(renderSyncOutcome({ aborted: true }, "abort"), "retained continuation discarded");
  assert.equal(
    renderSyncOutcome({ aborted: true, notes: ["cleanup left residue"] }, "abort"),
    "retained continuation discarded\nnote: cleanup left residue",
  );
  assert.match(renderSyncOutcome({ declined: true }, "abort"), /abort declined/);
  assert.match(renderSyncOutcome({ declined: true }, "continue"), /continuation declined/);
  assert.match(renderSyncOutcome({ declined: true }, "sync"), /cascade declined/);
  assert.match(
    renderSyncOutcome({ no_op: true, base_advanced: true }, "sync"),
    /nothing to synchronize \(the base advanced/,
  );
});

test("renderRecoverOutcome: rows, selection, sweep, and failures", () => {
  const text = renderRecoverOutcome({
    dry_run: true,
    selection_required: true,
    operations: [
      {
        operation_id: "01OP",
        kind: "sync",
        prepared_created: "2026-01-01",
        classification: "all_after",
        action: "reported",
        detail: "verified at the prepared after state",
      },
    ],
    swept_worktrees: ["/wt/sync-01X"],
    swept_refs: [],
    sweep_failures: [{ target: "refs/perk/sync/01Y/x", error: "boom" }],
    sweep_skipped: null,
  });
  assert.match(text, /dry run: nothing was concluded/);
  assert.match(text, /01OP \(sync, prepared 2026-01-01\): all_after → reported/);
  assert.match(text, /several operations are unresolved/);
  assert.match(text, /would sweep 1 orphaned worktree\(s\) and 0 orphaned ref\(s\)/);
  assert.match(text, /sweep failure: refs\/perk\/sync\/01Y\/x \(boom\)/);
  assert.match(
    renderRecoverOutcome({ operations: [], sweep_skipped: "unparseable manifest(s) present" }),
    /no unresolved operations[\s\S]*sweep skipped: unparseable manifest\(s\) present/,
  );
});

// --- the /objective-stack read door -----------------------------------------------------------------

test("/objective-stack renders the status through the cold door (works gated too)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({
      success: true,
      objective: { id: "7" },
      no_train: "objective #7 is incremental",
      orphaned_residue: { observed: true, reason: null, worktrees: [], refs: [] },
    }),
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("objective-stack", "7");
    assert.ok(
      h.notifies.some((m) => /objective #7 is incremental/.test(m)),
      "the read door rendered the status (gate-on included)",
    );
  } finally {
    h.dispose();
  }
});

test("/objective-stack reports a cold-door failure loudly", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: false, error_type: "not_stacked", message: "no train" }),
    code: 1,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await h.invokeCommand("objective-stack", "7");
    assert.ok(
      h.notifyEvents.some((e) => e.severity === "error" && /no train/.test(e.message)),
      "the typed failure surfaced",
    );
  } finally {
    h.dispose();
  }
});
