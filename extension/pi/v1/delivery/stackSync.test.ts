// Live warm-surface tests for the stacked-delivery sync bindings (stackSync.ts): the frozen
// registration baselines (both tools + the driving command), the full-details WIRE baselines
// captured from the pre-migration door (byte-exact on the JSON round-trip), strict decodes,
// cold-door argv shapes, the lenient sync render, the §8.51 conflict drive through the
// REGISTERED tool (auto-fire sequence, explicit resolve, adopt-never-dispatches, the
// containment fail-closed arm, withheld dispatch, model interpolation), and the counter reset
// arms. Fully offline (fakePerk via PERK_BIN; a REAL bound AgentSession via the T1 harness).

import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { CONFLICT_RESOLUTION_ATTEMPT_CAP } from "../../../delivery/submit.ts";
import { resolverLockDir } from "../../../substrate/resolverLease.ts";
import {
  fakePerk,
  loadPerkSession,
  type PerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { OK_ENVELOPE } from "../../../testing/objectiveStackFixtures.ts";
import { evaluateWriterScript } from "../../../testing/writerScript.ts";
import {
  buildStackAdoptArgs,
  buildStackSyncArgs,
  objectiveSyncGuidance,
  renderSyncOutcome,
  runSyncResolution,
  syncConflictResolutionGuidance,
} from "./stackSync.ts";

// --- frozen registration baselines (captured from the pre-migration door) -------------------------

const BASELINE_SYNC_TOOL = {
  name: "objective_stack_sync",
  label: "Objective stack sync",
  description:
    "Synchronize an objective's published stack after an amend or base advance: preview " +
    "(dry_run), cascade, resume a resolved conflict continuation (continue), discard it " +
    "(abort), or dispatch the conflict-resolver subagent into the retained worktree " +
    "(resolve, on explicit human request). Modes are mutually exclusive. Delegates to the " +
    "perk cold door; call mutating modes only on explicit human approval.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      objective: {
        type: ["string", "number"],
        description: "The objective issue id (inferred from the session when omitted).",
      },
      base: {
        type: "boolean",
        description: "Also advance the stack root onto the current base head.",
      },
      dry_run: {
        type: "boolean",
        description: "Preview the cascade — no journal, push, or retention.",
      },
      continue: {
        type: "boolean",
        description:
          "Resume the retained conflict continuation (after the rebase was finished — by " +
          "the human or by the dispatched resolver; publication stays the human's call).",
      },
      abort: {
        type: "boolean",
        description: "Discard the retained conflict continuation (worktree + temp refs).",
      },
      resolve: {
        type: "boolean",
        description:
          "Dispatch the conflict-resolver subagent into the retained continuation worktree " +
          "(explicit human request; composes with no other mode).",
      },
    },
  },
  promptSnippet:
    "Cascade-sync the objective's published stack (preview/continue/abort/resolve modes)",
  promptGuidelines: [
    "Call objective_stack_sync only inside the /objective-sync flow: preview with dry_run: true, present the cascade to the human, and act (no dry_run) ONLY on explicit human approval.",
    "The modes are mutually exclusive: continue resumes a resolved conflict continuation, abort discards it, resolve dispatches the perk.conflict-resolver subagent into the retained worktree on explicit human request; none composes with base/dry_run.",
    "A mutating sync/continue that stops on a rebase conflict auto-dispatches the resolver (bounded attempts); follow the injected dispatch instructions — they own the resume gate.",
  ],
  executionMode: "sequential",
};

const BASELINE_ADOPT_TOOL = {
  name: "objective_stack_adopt",
  label: "Objective stack adopt",
  description:
    "Adopt one node's manually-pushed remote head as the intended stack state, then cascade " +
    "the layers above it. Mutating: requires confirm: true (preview first with dry_run: " +
    "true). Delegates to the perk cold door.",
  parameters: {
    type: "object",
    additionalProperties: false,
    required: ["node"],
    properties: {
      objective: {
        type: ["string", "number"],
        description: "The objective issue id (inferred from the session when omitted).",
      },
      node: { type: "string", description: "The roadmap node id whose remote head to adopt." },
      dry_run: {
        type: "boolean",
        description: "Preview the adoption cascade — no journal, push, or retention.",
      },
      confirm: {
        type: "boolean",
        description: "Explicit human approval (required for the mutating call).",
      },
    },
  },
  promptSnippet: "Adopt a node's manually-pushed head into the stack (confirm-gated)",
  promptGuidelines: [
    "Call objective_stack_adopt only when the human wants a node's manually-pushed remote head adopted as intended: preview with dry_run: true, then pass confirm: true on explicit human approval (refused otherwise).",
  ],
  executionMode: "sequential",
};

test("registration parity: sync + adopt tools + /objective-sync match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(h.registeredTool("objective_stack_sync"), BASELINE_SYNC_TOOL);
    assert.deepEqual(h.registeredTool("objective_stack_adopt"), BASELINE_ADOPT_TOOL);
    assert.deepEqual(h.registeredCommand("objective-sync"), {
      name: "objective-sync",
      description:
        "Drive a stack sync: preview the cascade, present it, act via the typed stack tools " +
        "on explicit approval. Pass an objective number (else the active objective).",
    });
  } finally {
    h.dispose();
  }
});

// --- full-details wire baselines (captured from the pre-migration door) ----------------------------

interface Wire {
  text: string | undefined;
  details: Record<string, unknown>;
  terminate: boolean | null;
}

async function invokeStack(opts: {
  tool: string;
  params: unknown;
  stdout: string;
  code?: number;
}): Promise<Wire & { injected: string[] }> {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: opts.stdout, code: opts.code ?? 0 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool(opts.tool, opts.params);
    const wire = JSON.parse(
      JSON.stringify({
        text: result.content[0]?.text,
        details: result.details,
        terminate: result.terminate ?? null,
      }),
    ) as Wire;
    return { ...wire, injected: [...injected] };
  } finally {
    h.dispose();
  }
}

const SYNC_OK_ENVELOPE = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
  no_op: false,
  declined: false,
  affected: [
    {
      node_id: "1.2",
      plan_id: "1457",
      branch: "plan-1457",
      pr_number: 12,
      before_sha: "a".repeat(40),
      after_sha: "b".repeat(40),
    },
  ],
  operation_id: "01OP",
});

test("wire baseline: sync mutating success", async () => {
  const r = await invokeStack({
    tool: "objective_stack_sync",
    params: { objective: "7" },
    stdout: SYNC_OK_ENVELOPE,
  });
  assert.equal(
    r.text,
    "synchronized 1 layer(s)\n" +
      `  1.2 plan-1457 (pr #12): ${"a".repeat(40)} → ${"b".repeat(40)}\n` +
      "operation 01OP complete",
  );
  assert.deepEqual(r.details, { ok: true, objective: "7" });
  assert.equal(r.terminate, null);
  assert.deepEqual(r.injected, []);
});

test("wire baseline: sync rebase_conflict refusal (uncorroborated re-read stays report-only)", async () => {
  // The single-route fake returns the SAME refusal envelope to the corroborating status
  // re-read, so the auto-fire finds no continuation and only warns — the tool result stays
  // the rebase_conflict refusal, with NO injection.
  const r = await invokeStack({
    tool: "objective_stack_sync",
    params: { objective: "7" },
    stdout: JSON.stringify({
      success: false,
      error_type: "rebase_conflict",
      message: "the candidate rebase for layer 2.1 ('plan-91' onto abc) hit a conflict",
    }),
    code: 1,
  });
  assert.equal(
    r.text,
    "objective_stack_sync failed: the candidate rebase for layer 2.1 ('plan-91' onto abc) " +
      "hit a conflict",
  );
  assert.deepEqual(r.details, {
    ok: false,
    error: "the candidate rebase for layer 2.1 ('plan-91' onto abc) hit a conflict",
    error_type: "rebase_conflict",
  });
  assert.equal(r.terminate, null);
  assert.deepEqual(r.injected, []);
});

test("wire baseline: sync bad_input and no_objective refusals", async () => {
  const badInput = await invokeStack({
    tool: "objective_stack_sync",
    params: { continue: true, abort: true },
    stdout: SYNC_OK_ENVELOPE,
  });
  assert.deepEqual(badInput.details, {
    ok: false,
    error:
      "objective_stack_sync takes { objective?, base?, dry_run?, continue?, abort?, resolve? " +
      "} — continue/abort are mutually exclusive and take no other mode flag; resolve " +
      "composes with nothing",
    error_type: "bad_input",
  });
  const noObjective = await invokeStack({
    tool: "objective_stack_sync",
    params: {},
    stdout: SYNC_OK_ENVELOPE,
  });
  assert.deepEqual(noObjective.details, {
    ok: false,
    error: "no objective given and none active or linked — pass the objective explicitly.",
    error_type: "no_objective",
  });
  assert.deepEqual(noObjective.injected, []);
});

test("wire baseline: adopt confirm-refusal and confirmed success", async () => {
  const refusal = await invokeStack({
    tool: "objective_stack_adopt",
    params: { objective: "7", node: "1.2" },
    stdout: SYNC_OK_ENVELOPE,
  });
  assert.deepEqual(refusal.details, {
    ok: false,
    error:
      "adoption accepts a published branch head, may cascade successor branch heads, and " +
      "updates checkpoints — preview with dry_run: true, then pass confirm: true on explicit " +
      "human approval.",
    error_type: "confirmation_required",
  });
  const success = await invokeStack({
    tool: "objective_stack_adopt",
    params: { objective: "7", node: "1.2", confirm: true },
    stdout: JSON.stringify({
      success: true,
      objective: { id: "7", url: "https://x/7", redirected_from: null },
      no_op: false,
      declined: false,
      affected: [],
      adopted_node: "1.2",
    }),
  });
  assert.equal(success.text, "synchronized 0 layer(s) (adopted node 1.2)");
  assert.deepEqual(success.details, { ok: true, objective: "7" });
  assert.equal(success.terminate, null);
});

// --- strict tool decodes ----------------------------------------------------------------------------

async function invokeExpectingFail(
  h: PerkSession,
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
    for (const params of [
      { continue: true, abort: true },
      { continue: true, base: true },
      { abort: true, dry_run: true },
      { dry_run: "yes" },
      // resolve composes with NOTHING — refused at the decode, before any cold-door exec.
      { resolve: true, continue: true },
      { resolve: true, base: true },
      { resolve: true, dry_run: true },
    ]) {
      await invokeExpectingFail(h, "objective_stack_sync", params, "bad_input");
    }
  } finally {
    h.dispose();
  }
});

test("decode: adopt requires node; the mutating adopt requires confirm", async () => {
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
  } finally {
    h.dispose();
  }
});

// --- argv shapes (pure builders + one live delegation) ---------------------------------------------

const SYNC_DEFAULTS = {
  objective: undefined,
  base: false,
  dryRun: false,
  continue_: false,
  abort: false,
  resolve: false,
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

// --- the lenient sync render + the pure guidance ----------------------------------------------------

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

test("guidance: preview-first, consent-gated, no hardcoded skill pointer", () => {
  const text = objectiveSyncGuidance("7");
  for (const needle of [
    "objective_stack_status",
    "objective_stack_sync",
    "objective_stack_adopt",
    "dry_run: true",
    "confirm: true",
    "continue: true",
    "abort: true",
    "resolve: true",
    "explicit human approval",
  ]) {
    assert.ok(text.includes(needle), `sync guidance must include: ${needle}`);
  }
  assert.ok(!/skills\//.test(text), "no hardcoded skill pointer (bindings own delivery)");
  assert.ok(!/perk-objective-sync\b/.test(text), "no hardcoded skill name");
});

// --- the sync conflict drive through the REGISTERED tool (the execute composition point) -----------

const DRIVE_OP = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

function dispatchAt(cwd: string) {
  return {
    operationId: DRIVE_OP,
    manifestPath: join(cwd, "sync-continuations", "01LIN.json"),
    objective: "7",
    node: "2.1",
    branch: "plan-91",
    pr: 91,
    worktree: `/tmp/worktrees/sync-${DRIVE_OP}`,
  };
}

for (const model of [undefined, "test-org/resolver-model"]) {
  test(`retained writer renderer pins child foreground/cwd and compact return: ${model}`, async () => {
    const dispatch = dispatchAt("/caller");
    const text = syncConflictResolutionGuidance(dispatch, 1, 2, model);
    const { calls, result } = await evaluateWriterScript(text);
    assert.deepEqual(calls, [
      {
        key: "resolve",
        params: {
          agent: "perk.conflict-resolver",
          async: false,
          cwd: dispatch.worktree,
          task: "<the instruction of step 2>",
        },
      },
    ]);
    assert.deepEqual(result, { key: "resolve", ok: false, error: "stopped", output: "resolution" });
    assert.match(text, /top-level `async: false` and `context: "fresh"`/);
    assert.doesNotMatch(text, /extensionBindings|acceptance:|mission:/);
    assert.equal(text.includes('model: "test-org/resolver-model"'), model !== undefined);
    assert.ok(
      text.includes(
        `\nRETAINED-CONTINUATION SENTINEL: resume the in-progress rebase in ${dispatch.worktree}\n`,
      ),
    );
    assert.match(text, /ONLY a \*\*completed\*\* rebase \(verification passed\)/);
    assert.match(text, /Do not install wiring or copy\/mint a parent handoff/);
    assert.match(text, /Never change execution mode, extension composition, or launch protocol/);
  });
}

/** A stack-routing fake perk: routes on the third argv token (sync vs status) and appends each
 * call's full argv as one line — the smoke tests assert the exact cold-door sequence. */
function fakeStackPerk(
  cwd: string,
  opts: { sync?: { json: string; code: number }; status: string; argvFile: string },
): string {
  const path = join(cwd, "fake-stack-perk.sh");
  const q = (value: string) => value.replace(/'/g, "'\\''");
  const syncArm = opts.sync
    ? `  sync) printf '%s' '${q(opts.sync.json)}'; exit ${opts.sync.code} ;;\n`
    : "";
  writeFileSync(
    path,
    `#!/usr/bin/env bash\nprintf '%s\\n' "$*" >> '${q(opts.argvFile)}'\ncase "$3" in\n${syncArm}` +
      `  status) printf '%s' '${q(opts.status)}'; exit 0 ;;\n` +
      `  *) >&2 echo "unexpected subcommand: $*"; exit 2 ;;\nesac\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

/** A corroborating status projection whose manifest path lives under `cwd`. The continuation
 * carries `targets_contained: true` — the D2 containment verdict the corroboration requires. */
function driveStatusJson(cwd: string, over: Record<string, unknown> = {}): string {
  mkdirSync(join(cwd, "sync-continuations"), { recursive: true });
  return JSON.stringify({
    success: true,
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    train: {
      base: "main",
      delivery_lineage: "01LIN",
      published_prefix_len: 1,
      layers: [{ node_id: "2.1", branch: "plan-91", pr_number: 91, publication: "published" }],
    },
    continuation: {
      operation_id: DRIVE_OP,
      conflict_node_id: "2.1",
      adopted_node: null,
      created: "2026-01-01",
      worktree_path: `/tmp/worktrees/sync-${DRIVE_OP}`,
      manifest_path: join(cwd, "sync-continuations", "01LIN.json"),
      parseable: true,
      targets_contained: true,
      ...over,
    },
    orphaned_residue: { observed: true, reason: null, worktrees: [], refs: [] },
  });
}

const CONFLICT_JSON = JSON.stringify({
  success: false,
  error_type: "rebase_conflict",
  message: "the candidate rebase for layer 2.1 ('plan-91' onto abc) hit a conflict",
});

test("registered tool: a mutating sync refusing rebase_conflict auto-drives ONE dispatch", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakeStackPerk(cwd, {
    sync: { json: CONFLICT_JSON, code: 1 },
    status: driveStatusJson(cwd),
    argvFile,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: "7" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false, "the tool result still carries the refusal");
    assert.equal(details.error_type, "rebase_conflict");
    assert.deepEqual(
      readFileSync(argvFile, "utf8").trim().split("\n"),
      ["objective stack sync 7 --yes --json", "objective stack status 7 --json"],
      "the mutating sync is followed by exactly the corroborating status re-read",
    );
    assert.equal(injected.length, 1, "exactly one dispatch injection");
    assert.ok(injected[0]?.startsWith(syncConflictResolutionGuidance(dispatchAt(cwd), 1, 2)));
    assert.match(injected[0] ?? "", /RETAINED-CONTINUATION SENTINEL/);
    assert.match(injected[0] ?? "", /perk\.conflict-resolver/);
    assert.match(injected[0] ?? "", /attempt 1 of 2/);
    assert.ok(
      (injected[0] ?? "").includes(`cd /tmp/worktrees/sync-${DRIVE_OP}`),
      "the unquoted cd names the retained worktree",
    );
    assert.equal(h.workflowState().conflict_resolution_attempts, 1);
  } finally {
    h.dispose();
  }
});

test("registered tool: an uncontained continuation fails closed — warning, no dispatch", async () => {
  // The D2 cross-plane arm end-to-end: a projection whose continuation is NOT
  // containment-validated (targets_contained false — or absent under version skew) never
  // mints a dispatch; the loud reason names the update/abort remediation.
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakeStackPerk(cwd, {
    sync: { json: CONFLICT_JSON, code: 1 },
    status: driveStatusJson(cwd, { targets_contained: false }),
    argvFile,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.invokeTool("objective_stack_sync", { objective: "7" });
    assert.deepEqual(injected, [], "an uncontained continuation never dispatches");
    // invokeTool's ctx shares the message-only notify capture (not the severity-tagged array).
    assert.ok(
      h.notifies.some((m) => /not containment-validated/.test(m)),
      "the containment miss is reported as a warning",
    );
    assert.equal(h.workflowState().conflict_resolution_attempts, undefined, "no increment");
  } finally {
    h.dispose();
  }
});

test("registered tool: resolve dispatches without ever reaching the cold sync mutation", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  // No sync route at all: reaching the mutation worker would exit 2 and fail the corroboration.
  const bin = fakeStackPerk(cwd, { status: driveStatusJson(cwd), argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.match(result.content[0]?.text ?? "", /dispatch injected \(attempt 1 of 2\)/);
    assert.deepEqual(
      readFileSync(argvFile, "utf8").trim().split("\n"),
      ["objective stack status 7 --json"],
      "the status re-read is the ONLY cold call",
    );
    assert.equal(injected.length, 1, "exactly one dispatch injection");
    assert.match(injected[0] ?? "", /RETAINED-CONTINUATION SENTINEL/);
  } finally {
    h.dispose();
  }
});

test("registered tool: a rebase_conflict-refusing ADOPT makes no status call and injects nothing", async () => {
  // Adopt never enters the dispatch pipeline — pinned at the adapter, not via a widened
  // predicate: the adopt argv is the ONLY cold call, whatever the refusal says.
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakeStackPerk(cwd, {
    sync: { json: CONFLICT_JSON, code: 1 },
    status: driveStatusJson(cwd),
    argvFile,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_adopt", {
      objective: "7",
      node: "2.1",
      confirm: true,
    });
    assert.equal((result.details as { ok: boolean }).ok, false);
    assert.deepEqual(
      readFileSync(argvFile, "utf8").trim().split("\n"),
      ["objective stack sync 7 --adopt 2.1 --yes --json"],
      "no corroborating status re-read for adopt",
    );
    assert.deepEqual(injected, []);
  } finally {
    h.dispose();
  }
});

test("registered tool: at the cap → loud error, no dispatch, counter unchanged", async () => {
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakeStackPerk(cwd, { status: driveStatusJson(cwd), argvFile });
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      mode: "read-write",
      conflict_resolution_attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP,
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "attempt_cap");
    assert.match(details.error ?? "", /resolve manually/);
    assert.deepEqual(injected, []);
    assert.equal(h.workflowState().conflict_resolution_attempts, CONFLICT_RESOLUTION_ATTEMPT_CAP);
  } finally {
    h.dispose();
  }
});

test("registered tool: a dropped increment withholds the dispatch and releases this call's claim", async () => {
  // The verified-increment precondition end-to-end: session appends are silently dropped
  // (the strict read-back seam observes the miss), so the pipeline withholds + releases.
  const cwd = scaffoldRepo();
  const argvFile = join(cwd, "argv.txt");
  const bin = fakeStackPerk(cwd, { status: driveStatusJson(cwd), argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  const sm = h.session.sessionManager as unknown as {
    appendCustomEntry: (customType: string, data?: unknown) => string;
  };
  const realAppend = sm.appendCustomEntry.bind(sm);
  sm.appendCustomEntry = (customType: string, data?: unknown) =>
    customType === "perk:workflow-state" ? "dropped" : realAppend(customType, data);
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "state_error");
    assert.match(details.error ?? "", /dispatch withheld/);
    assert.deepEqual(injected, [], "an unverifiable counter never bypasses the cap");
    const lock = resolverLockDir(join(cwd, "sync-continuations", "01LIN.json"));
    assert.equal(existsSync(lock), false, "this call's claim dir was removed");
  } finally {
    h.dispose();
  }
});

test("registered tool: a dropped reset write warns loudly (the counter may be stale)", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", conflict_resolution_attempts: 2 },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  const sm = h.session.sessionManager as unknown as {
    appendCustomEntry: (customType: string, data?: unknown) => string;
  };
  const realAppend = sm.appendCustomEntry.bind(sm);
  sm.appendCustomEntry = (customType: string, data?: unknown) =>
    customType === "perk:workflow-state" ? "dropped" : realAppend(customType, data);
  try {
    const result = await h.invokeTool("objective_stack_sync", { objective: "7" });
    assert.equal((result.details as { ok: boolean }).ok, true, "the completion stands");
    assert.ok(
      h.notifies.some((m) =>
        m.includes(
          "conflict budget reset failed — the persisted counter may be stale (the seam's " +
            "warning names the details).",
        ),
      ),
      `expected the exact reset-failure warning; got: ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

// --- the counter reset arms through the REGISTERED tools --------------------------------------------

async function invokeWithAttempts(opts: {
  tool: string;
  params: unknown;
  stdout: string;
  attempts: number;
}): Promise<number | undefined> {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: opts.stdout });
  const file = plantSession(cwd, [
    { run_id: "01RID", mode: "read-write", conflict_resolution_attempts: opts.attempts },
  ]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    const result = await h.invokeTool(opts.tool, opts.params);
    assert.equal((result.details as { ok: boolean }).ok, true);
    return h.workflowState().conflict_resolution_attempts;
  } finally {
    h.dispose();
  }
}

test("reset: a clean mutating sync resets the shared counter to 0", async () => {
  assert.equal(
    await invokeWithAttempts({
      tool: "objective_stack_sync",
      params: { objective: "7" },
      stdout: OK_ENVELOPE,
      attempts: 2,
    }),
    0,
  );
});

test("reset: a dry-run ok leaves the counter unchanged", async () => {
  assert.equal(
    await invokeWithAttempts({
      tool: "objective_stack_sync",
      params: { objective: "7", dry_run: true },
      stdout: JSON.stringify({ success: true, dry_run: true, no_op: true }),
      attempts: 2,
    }),
    2,
  );
});

test("reset: a declined mutating sync never resets", async () => {
  assert.equal(
    await invokeWithAttempts({
      tool: "objective_stack_sync",
      params: { objective: "7" },
      stdout: JSON.stringify({ success: true, declined: true }),
      attempts: 2,
    }),
    2,
  );
});

test("reset: a clean abort resets (the episode concluded)", async () => {
  assert.equal(
    await invokeWithAttempts({
      tool: "objective_stack_sync",
      params: { objective: "7", abort: true },
      stdout: JSON.stringify({ success: true, aborted: true }),
      attempts: 1,
    }),
    0,
  );
});

test("reset: a clean confirmed adopt resets", async () => {
  assert.equal(
    await invokeWithAttempts({
      tool: "objective_stack_adopt",
      params: { objective: "7", node: "2.1", confirm: true },
      stdout: OK_ENVELOPE,
      attempts: 1,
    }),
    0,
  );
});

// --- model interpolation through the registered resolve mode ----------------------------------------

test("dispatch: the configured [models.subagents] conflict-resolver model renders; unset omits", async () => {
  {
    const cwd = scaffoldRepo();
    mkdirSync(join(cwd, ".perk"), { recursive: true });
    writeFileSync(
      join(cwd, ".perk", "config.toml"),
      '[models.subagents]\nconflict-resolver = "test-org/resolver-model"\n',
      "utf8",
    );
    const bin = fakeStackPerk(cwd, {
      status: driveStatusJson(cwd),
      argvFile: join(cwd, "argv.txt"),
    });
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
    const injected = spyInjections(h);
    try {
      await h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.match(injected[0] ?? "", /model: "test-org\/resolver-model"/);
    } finally {
      h.dispose();
    }
  }
  {
    // An isolated cwd: the dev checkout's own [models.subagents] must not leak in.
    const cwd = scaffoldRepo();
    const bin = fakeStackPerk(cwd, {
      status: driveStatusJson(cwd),
      argvFile: join(cwd, "argv.txt"),
    });
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
    const injected = spyInjections(h);
    try {
      await h.invokeTool("objective_stack_sync", { objective: "7", resolve: true });
      assert.doesNotMatch(injected[0] ?? "", /model: "/);
      assert.match(injected[0] ?? "", /default model/);
    } finally {
      h.dispose();
    }
  }
});

// --- the dispatch delivery-mode matrix over the exported adapter core --------------------------------
// (the idle harness cannot produce the streaming `followUp` arm — the exported-core precedent)

test("runSyncResolution: idle → immediate turn; streaming → followUp", async () => {
  const cwd = scaffoldRepo();
  const status = driveStatusJson(cwd);
  for (const [idle, expected] of [
    [true, undefined],
    [false, "followUp"],
  ] as const) {
    const calls: { content: string; options?: { deliverAs?: string } }[] = [];
    const entries: { type: string; customType?: string; data?: unknown }[] = [];
    const pi = {
      exec: async () => ({ code: 0, killed: false, stdout: status, stderr: "" }),
      appendEntry: (customType: string, data?: unknown) => {
        entries.push({ type: "custom", customType, data });
      },
      sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
        calls.push({ content, options });
      },
    } as unknown as ExtensionAPI;
    const ctx = {
      cwd,
      hasUI: true,
      isIdle: () => idle,
      sessionManager: { getBranch: () => entries },
      ui: { notify: () => {} },
    } as unknown as ExtensionContext;
    const outcome = await runSyncResolution(pi, ctx, "7", null);
    assert.equal(outcome.kind, "dispatched");
    assert.equal(calls.length, 1);
    assert.equal(calls[0]?.options?.deliverAs, expected);
    assert.match(calls[0]?.content ?? "", /RETAINED-CONTINUATION SENTINEL/);
  }
});
