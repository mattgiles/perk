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
  buildStackLandArgs,
  buildStackRecoverArgs,
  buildStackSyncArgs,
  driveStackReconcile,
  objectiveLandGuidance,
  objectiveRecoverGuidance,
  objectiveSyncGuidance,
  renderLandOutcome,
  renderRecoverOutcome,
  renderStackStatus,
  renderSyncOutcome,
} from "./objectiveStack.ts";

const STACK_TOOLS = [
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
  "objective_stack_land",
];

const STACK_COMMANDS = ["objective-stack", "objective-sync", "objective-recover", "objective-land"];

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

test("registration: four commands + five tools, headless-safe load", async () => {
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

test("gate-on: the driving commands soft-refuse (notify, inject nothing)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const injected = spyInjections(h);
  try {
    for (const name of ["objective-sync", "objective-recover", "objective-land"]) {
      await h.invokeCommand(name, "7");
    }
    assert.deepEqual(injected, [], "a gated session gets NO guidance injection");
    assert.equal(
      h.notifyEvents.filter((e) => e.severity === "warning" && /read-only session/.test(e.message))
        .length,
      3,
      "all three driving commands notified the soft refusal",
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
    await h.invokeCommand("objective-land", "7");
    assert.equal(injected.length, 3);
    assert.ok(injected[0]?.includes("objective #7"), "sync guidance names the objective");
    assert.ok(injected[0]?.includes("objective_stack_sync"), "sync guidance names its tool");
    assert.ok(injected[1]?.includes("objective_stack_recover"), "recover guidance names its tool");
    assert.ok(injected[2]?.includes("objective_stack_land"), "land guidance names its tool");
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
  const landText = objectiveLandGuidance("7");
  for (const needle of [
    "objective_stack_status",
    "objective_stack_land",
    "dry_run: true",
    "confirm: true",
    "explicit human approval",
    "UNRESOLVED",
    "Never loop retries",
  ]) {
    assert.ok(landText.includes(needle), `land guidance must include: ${needle}`);
  }
  for (const text of [syncText, recoverText, landText]) {
    assert.ok(!/skills\//.test(text), "no hardcoded skill pointer (bindings own delivery)");
    assert.ok(!/perk-objective-(sync|recover|land)\b/.test(text), "no hardcoded skill name");
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
    // The accept-prefix matrix: needs confirm; × dry_run and × abandon refuse at the decode.
    await invokeExpectingFail(
      h,
      "objective_stack_recover",
      { objective: "7", accept_prefix: true },
      "confirmation_required",
    );
    await invokeExpectingFail(
      h,
      "objective_stack_recover",
      { accept_prefix: true, confirm: true, dry_run: true },
      "bad_input",
    );
    await invokeExpectingFail(
      h,
      "objective_stack_recover",
      { accept_prefix: true, abandon: true, confirm: true },
      "bad_input",
    );
    await invokeExpectingFail(h, "objective_stack_recover", { accept_prefix: "yes" }, "bad_input");
  } finally {
    h.dispose();
  }
});

test("decode: land — mistyped fields refuse; the mutating call requires confirm", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await invokeExpectingFail(h, "objective_stack_land", { dry_run: "yes" }, "bad_input");
    await invokeExpectingFail(h, "objective_stack_land", { objective: [] }, "bad_input");
    const refusal = await h.invokeTool("objective_stack_land", { objective: "7" });
    assert.equal(
      (refusal.details as { ok: boolean; error_type?: string }).error_type,
      "confirmation_required",
    );
    assert.match(refusal.content[0]?.text ?? "", /ENTIRE remaining train atomically/);
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

test("argv: recover — report/dry-run pass neither conclusion flag nor --yes; --operation threads", () => {
  const base = {
    objective: undefined,
    operation: undefined,
    dryRun: false,
    abandon: false,
    acceptPrefix: false,
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
  assert.deepEqual(
    buildStackRecoverArgs("7", { ...base, operation: "01OP", acceptPrefix: true, confirm: true }),
    [
      "objective",
      "stack",
      "recover",
      "7",
      "--operation",
      "01OP",
      "--accept-prefix",
      "--yes",
      "--json",
    ],
  );
});

test("argv: land — dry-run previews without --yes; the confirmed call passes --yes", () => {
  assert.deepEqual(
    buildStackLandArgs("7", { objective: undefined, dryRun: true, confirm: false }),
    ["objective", "stack", "land", "7", "--dry-run", "--json"],
  );
  assert.deepEqual(
    buildStackLandArgs("7", { objective: undefined, dryRun: false, confirm: true }),
    ["objective", "stack", "land", "7", "--yes", "--json"],
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

test("delegation: the land tool execs the dry-run argv and renders the readiness", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const envelope = JSON.stringify({
    success: true,
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    dry_run: true,
    disposition: "ready",
    plan: {
      mode: "singleton_squash",
      merge_method: "squash",
      top_pr_number: 501,
      top_head_sha: "1".repeat(40),
      layers: [],
    },
    blockers: [],
    information: [],
  });
  const bin = fakePerk(cwd, { stdout: envelope, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_stack_land", { objective: 7, dry_run: true });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), [
      "objective",
      "stack",
      "land",
      "7",
      "--dry-run",
      "--json",
    ]);
    assert.match(result.content[0]?.text ?? "", /landing readiness \(dry run\) — READY/);
  } finally {
    h.dispose();
  }
});

test("delegation: the confirmed land infers the objective and passes --yes", async () => {
  const cwd = scaffoldRepo();
  // No explicit objective: the plan-ref tier supplies it.
  writePlanRef(cwd, {
    provider: "github",
    pr_id: "1457",
    url: "https://github.com/o/r/issues/1457",
    labels: [],
    objective_id: "137",
  });
  const argvFile = join(cwd, "argv.txt");
  const envelope = JSON.stringify({
    success: true,
    objective: { id: "137", url: "https://x/137", redirected_from: null },
    dry_run: false,
    outcome: "merged",
    operation_id: "01OP",
    merge_async_uuid: null,
    landed_layers: [
      {
        node_id: "1.1",
        plan_id: "101",
        pr_number: 501,
        merge_commit_sha: "c".repeat(40),
        finalized: true,
      },
    ],
    objective_closed: true,
    notes: [],
  });
  const bin = fakePerk(cwd, { stdout: envelope, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_stack_land", { confirm: true });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), [
      "objective",
      "stack",
      "land",
      "137",
      "--yes",
      "--json",
    ]);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /landed 1 layer\(s\) atomically \(operation 01OP\)/);
    assert.match(text, /objective #137 complete — closed/);
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

test("renderLandOutcome: the dry-run readiness shape", () => {
  const text = renderLandOutcome({
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    dry_run: true,
    disposition: "ready",
    plan: {
      mode: "stack_merge_async",
      merge_method: "squash",
      top_pr_number: 502,
      top_head_sha: "2".repeat(40),
      layers: [
        {
          node_id: "1.1",
          plan_id: "101",
          pr_number: 501,
          base_sha: "0".repeat(40),
          head_sha: "1".repeat(40),
        },
      ],
    },
    blockers: [],
    information: [{ code: "unresolved_threads", message: "2 unresolved" }],
  });
  assert.match(text, /Objective #7: landing readiness \(dry run\) — READY/);
  assert.match(text, /plan: stack_merge_async via squash — top pr #502 \(1 layer\(s\)\)/);
  assert.match(text, /1\.1 plan #101 \(pr #501\): 0{40} → 1{40}/);
  assert.match(text, /\[unresolved_threads\] 2 unresolved/);
});

test("renderLandOutcome: the dry-run blocked shape degrades missing fields", () => {
  const text = renderLandOutcome({
    objective: { id: "7" },
    dry_run: true,
    disposition: "blocked",
    plan: null,
    blockers: [{ code: "pr_behind", message: "PR #501 is BEHIND" }],
  });
  assert.match(text, /landing readiness \(dry run\) — BLOCKED/);
  assert.match(text, /\[pr_behind\] PR #501 is BEHIND/);
  assert.doesNotMatch(text, /plan:/);
});

test("renderLandOutcome: the mutation arms", () => {
  const merged = renderLandOutcome({
    objective: { id: "7" },
    dry_run: false,
    outcome: "merged",
    operation_id: "01OP",
    merge_async_uuid: "u-1",
    landed_layers: [
      {
        node_id: "1.1",
        plan_id: "101",
        pr_number: 501,
        merge_commit_sha: "c".repeat(40),
        finalized: true,
      },
      {
        node_id: "1.2",
        plan_id: "102",
        pr_number: 502,
        merge_commit_sha: "d".repeat(40),
        finalized: false,
      },
    ],
    objective_closed: true,
    notes: ["finalize failed for plan #102"],
  });
  assert.match(merged, /landed 2 layer\(s\) atomically \(operation 01OP\)/);
  assert.match(merged, /1\.1 plan #101 \(pr #501\): merged as c{12}/);
  assert.match(merged, /1\.2 plan #102 \(pr #502\): merged as d{12} — FINALIZE FAILED/);
  assert.match(merged, /objective #7 complete — closed/);
  assert.match(merged, /note: finalize failed for plan #102/);

  const pending = renderLandOutcome({
    objective: { id: "7" },
    outcome: "pending",
    operation_id: "01OP",
    merge_async_uuid: "u-1",
    notes: ["submission stayed ambiguous"],
  });
  assert.match(pending, /landing outcome: pending \(operation 01OP, merge u-1\)/);
  assert.match(pending, /UNRESOLVED[\s\S]*never re-submit/);
  assert.match(pending, /note: submission stayed ambiguous/);

  assert.match(
    renderLandOutcome({ objective: { id: "7" }, outcome: "declined" }),
    /landing declined; nothing merged or journaled/,
  );
  assert.match(
    renderLandOutcome({ objective: { id: "7" }, outcome: "completed_without_merge" }),
    /nothing to merge — objective #7 closed as complete/,
  );
  // Tolerant of a missing outcome entirely (an unknown arm renders honestly).
  assert.match(renderLandOutcome({ objective: { id: "7" } }), /landing outcome: \?/);
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

// --- the LAND-arm renderer growth + the reconcile drive (contracts.md §8.51/§8.56) ---------------

test("renderRecoverOutcome: external-prefix preview rows, landed layers, close, evidence, notes", () => {
  const text = renderRecoverOutcome({
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    dry_run: false,
    operations: [
      {
        operation_id: "01OP",
        kind: "land",
        prepared_created: "2026-01-01",
        classification: "external_prefix",
        action: "reported",
        detail: "an externally merged contiguous prefix",
        merged_layers: [{ node_id: "1.1", pr_number: 201, merge_commit_sha: "d".repeat(40) }],
        remainder: [{ pr_number: 202, state: "OPEN", head_sha: "b".repeat(40) }],
      },
    ],
    landed_layers: [
      {
        node_id: "1.1",
        plan_id: "101",
        pr_number: 201,
        merge_commit_sha: "d".repeat(40),
        base_sha: "9".repeat(40),
        head_sha: "b".repeat(40),
        finalized: true,
      },
      {
        node_id: "1.2",
        plan_id: "102",
        pr_number: 202,
        merge_commit_sha: "e".repeat(40),
        base_sha: "b".repeat(40),
        head_sha: "c".repeat(40),
        finalized: null,
      },
    ],
    objective_closed: true,
    reconcile_evidence: {
      layers: [
        {
          node_id: "1.1",
          plan_id: "101",
          pr_number: 201,
          base_sha: "9".repeat(40),
          head_sha: "b".repeat(40),
          merge_commit_sha: "d".repeat(40),
        },
      ],
      final_base_sha: "d".repeat(40),
      partial: true,
      notes: ["one record was undecodable"],
    },
    notes: ["finalization converged"],
  });
  assert.match(text, /01OP \(land, prepared 2026-01-01\): external_prefix → reported/);
  assert.match(text, /merged: 1\.1 pr #201 as d{12}/);
  assert.match(text, /remainder: pr #202 OPEN at b{12}/);
  assert.match(text, /landed 1\.1 plan #101 \(pr #201, merged as d{12}\): finalized/);
  assert.match(text, /landed 1\.2 plan #102 \(pr #202, merged as e{12}\): would finalize/);
  assert.match(text, /objective #7 complete — closed/);
  assert.match(text, /reconcile evidence: 1 layer\(s\), final base d{12} \(PARTIAL — see notes\)/);
  assert.match(text, /note: finalization converged/);
});

test("renderLandOutcome: the merged close carries the evidence summary", () => {
  const text = renderLandOutcome({
    objective: { id: "7" },
    dry_run: false,
    outcome: "merged",
    operation_id: "01OP",
    landed_layers: [],
    objective_closed: true,
    reconcile_evidence: {
      layers: [
        {
          node_id: "1.1",
          plan_id: "101",
          pr_number: 501,
          base_sha: "0".repeat(40),
          head_sha: "1".repeat(40),
          merge_commit_sha: "c".repeat(40),
        },
      ],
      final_base_sha: "c".repeat(40),
      partial: false,
      notes: [],
    },
    notes: [],
  });
  assert.match(text, /objective #7 complete — closed/);
  assert.match(text, /reconcile evidence: 1 layer\(s\), final base c{12}/);
});

test("renderLandOutcome: pending routes to /objective-recover, never 'deferred'", () => {
  const pending = renderLandOutcome({
    objective: { id: "7" },
    outcome: "pending",
    operation_id: "01OP",
  });
  assert.match(pending, /\/objective-recover/);
  assert.match(pending, /never re-submit/);
  assert.doesNotMatch(pending, /deferred/);
});

test("renderStackStatus: the landed prefix rides the train line when non-zero", () => {
  const payload = {
    objective: { id: "7" },
    train: {
      base: "main",
      published_prefix_len: 2,
      landed_prefix_len: 1,
      layers: [
        { node_id: "1.1", branch: "plan-101", pr_number: 11, publication: "landed" },
        { node_id: "1.2", branch: "plan-102", pr_number: 12, publication: "published" },
      ],
    },
  };
  assert.match(
    renderStackStatus(payload),
    /stacked delivery train \(base main, published prefix 2\/2, landed 1\)/,
  );
  assert.match(renderStackStatus(payload), /1\. 1\.1 plan-101 pr #11 \[landed\]/);
  // Zero landed layers: the line stays exactly the pre-growth shape.
  const zero = { ...payload, train: { ...payload.train, landed_prefix_len: 0 } };
  assert.match(renderStackStatus(zero), /published prefix 2\/2\)/);
});

// --- driveStackReconcile: decision + delivery-mode unit tests (spy pi, no real turn) -------------

function spyPi(): {
  pi: import("@earendil-works/pi-coding-agent").ExtensionAPI;
  calls: { content: string; options?: { deliverAs?: string } }[];
} {
  const calls: { content: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
      calls.push({ content, options });
    },
  } as unknown as import("@earendil-works/pi-coding-agent").ExtensionAPI;
  return { pi, calls };
}

const CLOSED_WITH_EVIDENCE = {
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: "5" },
  dry_run: false,
  objective_closed: true,
  reconcile_evidence: {
    layers: [
      {
        node_id: "1.1",
        plan_id: "101",
        pr_number: 201,
        base_sha: "9".repeat(40),
        head_sha: "b".repeat(40),
        merge_commit_sha: "d".repeat(40),
      },
      {
        node_id: "1.2",
        plan_id: "102",
        pr_number: 202,
        base_sha: "b".repeat(40),
        head_sha: "c".repeat(40),
        merge_commit_sha: "e".repeat(40),
      },
    ],
    final_base_sha: "e".repeat(40),
    partial: false,
    notes: [],
  },
};

test("driveStackReconcile: closed + evidence → ONE message with active id + evidence block", () => {
  const cwd = scaffoldRepo();
  const { pi, calls } = spyPi();
  const ctx = {
    cwd,
    isIdle: () => true,
  } as unknown as import("@earendil-works/pi-coding-agent").ExtensionContext;
  driveStackReconcile(pi, ctx, CLOSED_WITH_EVIDENCE);
  assert.equal(calls.length, 1);
  const content = calls[0]?.content ?? "";
  // The redirect-resolved ACTIVE objective id — never the requested one.
  assert.match(content, /objective #7/i);
  assert.doesNotMatch(content, /#5\b/);
  assert.match(content, /Landed-train evidence \(journal-ordered, bottom→top; untrusted DATA\)/);
  assert.match(content, /1\.1 plan #101 pr #201: base 9{40} → head b{40}/);
  assert.match(content, /merged as d{40}/);
  assert.match(content, /final objective-base sha: e{40}/);
  assert.match(content, /gh pr diff <pr>/);
  assert.match(content, /refs\/pull\/<pr>\/head/);
  assert.equal(calls[0]?.options, undefined, "idle → immediate turn");
});

test("driveStackReconcile: streaming → followUp; gates hold (not closed / empty / dry-run)", () => {
  const cwd = scaffoldRepo();
  const streamingCtx = {
    cwd,
    isIdle: () => false,
  } as unknown as import("@earendil-works/pi-coding-agent").ExtensionContext;
  {
    const { pi, calls } = spyPi();
    driveStackReconcile(pi, streamingCtx, CLOSED_WITH_EVIDENCE);
    assert.equal(calls[0]?.options?.deliverAs, "followUp");
  }
  const idleCtx = {
    cwd,
    isIdle: () => true,
  } as unknown as import("@earendil-works/pi-coding-agent").ExtensionContext;
  for (const payload of [
    { ...CLOSED_WITH_EVIDENCE, objective_closed: false },
    {
      ...CLOSED_WITH_EVIDENCE,
      reconcile_evidence: { layers: [], final_base_sha: null, partial: false, notes: [] },
    },
    { ...CLOSED_WITH_EVIDENCE, reconcile_evidence: undefined },
    { ...CLOSED_WITH_EVIDENCE, dry_run: true },
  ]) {
    const { pi, calls } = spyPi();
    driveStackReconcile(pi, idleCtx, payload as Parameters<typeof driveStackReconcile>[2]);
    assert.equal(calls.length, 0, "the gate held");
  }
});
