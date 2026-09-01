// Live warm-surface tests for the stacked-delivery recovery bindings (stackRecover.ts): the
// frozen registration baselines (tool + driving command), the full-details WIRE baselines
// captured from the pre-migration door, strict decodes (the conclusion matrix), cold-door argv
// shapes, the lenient recover render, objective inference precedence, and the reconcile drive
// call site through the REGISTERED tool. Fully offline (fakePerk via PERK_BIN; a REAL bound
// AgentSession via the T1 harness).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { writePlanRef } from "../../../substrate/cache.ts";
import {
  fakePerk,
  loadPerkSession,
  type PerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { OK_ENVELOPE, PLAN_REF } from "../../../testing/objectiveStackFixtures.ts";
import {
  buildStackRecoverArgs,
  objectiveRecoverGuidance,
  renderRecoverOutcome,
} from "./stackRecover.ts";

// --- frozen registration baselines (captured from the pre-migration door) --------------------------

const BASELINE_RECOVER_TOOL = {
  name: "objective_stack_recover",
  label: "Objective stack recover",
  description:
    "Conclude an objective's unresolved stack operations (classify against fresh authority; " +
    "roll forward what verified complete — LAND included; abandon with proof under " +
    "abandon+confirm; accept an externally merged LAND prefix as a recorded breach under " +
    "accept_prefix+confirm) and sweep orphaned sync residue. dry_run reports without acting. " +
    "Delegates to the perk cold door.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      objective: {
        type: ["string", "number"],
        description: "The objective issue id (inferred from the session when omitted).",
      },
      operation: {
        type: "string",
        description: "The target operation ULID (required when several are unresolved).",
      },
      dry_run: {
        type: "boolean",
        description: "Classify and report only — no roll-forward, no abandon, no sweep.",
      },
      abandon: {
        type: "boolean",
        description: "Abandon the target operation (requires an all-before proof + confirm).",
      },
      accept_prefix: {
        type: "boolean",
        description:
          "Accept an externally merged LAND prefix as a recorded degraded-atomicity breach " +
          "(requires an external_prefix classification + confirm).",
      },
      confirm: {
        type: "boolean",
        description: "Explicit human approval (required with abandon or accept_prefix).",
      },
    },
  },
  promptSnippet: "Conclude unresolved stack operations + sweep orphaned residue",
  promptGuidelines: [
    "Call objective_stack_recover inside the /objective-recover flow: dry_run: true classifies and reports; the real call concludes deterministically (all-after rolls forward — LAND included) and sweeps orphaned residue.",
    "abandon: true requires confirm: true (explicit human approval) and an all-before classification — never abandon to make a report go away; mixed classifications need human investigation.",
    "accept_prefix: true requires confirm: true and an external_prefix LAND classification — it records the externally merged prefix as a degraded-atomicity breach; then cascade the remainder with objective_stack_sync { base: true } and land it with objective_stack_land.",
  ],
  executionMode: "sequential",
};

test("registration parity: recover tool + /objective-recover match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(h.registeredTool("objective_stack_recover"), BASELINE_RECOVER_TOOL);
    assert.deepEqual(h.registeredCommand("objective-recover"), {
      name: "objective-recover",
      description:
        "Drive stack recovery: classify unresolved operations, present the report, conclude " +
        "via the typed recover tool on explicit approval. Pass an objective number (else the " +
        "active objective).",
    });
  } finally {
    h.dispose();
  }
});

// --- full-details wire baselines (captured from the pre-migration door) -----------------------------

async function invokeRecover(opts: { params: unknown; stdout: string; code?: number }) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: opts.stdout, code: opts.code ?? 0 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_recover", opts.params);
    const wire = JSON.parse(
      JSON.stringify({
        text: result.content[0]?.text,
        details: result.details,
        terminate: result.terminate ?? null,
      }),
    ) as { text: string | undefined; details: Record<string, unknown>; terminate: boolean | null };
    return { ...wire, injected: [...injected] };
  } finally {
    h.dispose();
  }
}

const RECOVER_REPORT = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
  dry_run: true,
  selection_required: false,
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
  swept_worktrees: [],
  swept_refs: [],
  sweep_failures: [],
  sweep_skipped: null,
  landed_layers: [],
  objective_closed: false,
  reconcile_evidence: null,
  notes: [],
});

test("wire baseline: the dry-run classification report", async () => {
  const r = await invokeRecover({
    params: { objective: "7", dry_run: true },
    stdout: RECOVER_REPORT,
  });
  assert.equal(
    r.text,
    "dry run: nothing was concluded, journaled, or swept\n" +
      "01OP (sync, prepared 2026-01-01): all_after → reported\n" +
      "  verified at the prepared after state",
  );
  assert.deepEqual(r.details, { ok: true, objective: "7" });
  assert.equal(r.terminate, null);
  assert.deepEqual(r.injected, [], "a dry-run report never drives");
});

test("wire baseline: the abandon confirm-refusal", async () => {
  const r = await invokeRecover({
    params: { objective: "7", abandon: true },
    stdout: RECOVER_REPORT,
  });
  assert.equal(
    r.text,
    "objective_stack_recover failed: abandoning an unresolved operation journals its " +
      "permanent conclusion — preview with dry_run: true, then pass confirm: true on explicit " +
      "human approval.",
  );
  assert.deepEqual(r.details, {
    ok: false,
    error:
      "abandoning an unresolved operation journals its permanent conclusion — preview with " +
      "dry_run: true, then pass confirm: true on explicit human approval.",
    error_type: "confirmation_required",
  });
  assert.equal(r.terminate, null);
});

// --- strict tool decodes -----------------------------------------------------------------------------

async function invokeExpectingFail(
  h: PerkSession,
  params: unknown,
  errorType: string,
): Promise<void> {
  const result = await h.invokeTool("objective_stack_recover", params);
  const details = result.details as { ok: boolean; error_type?: string };
  assert.equal(details.ok, false, `${JSON.stringify(params)} must refuse`);
  assert.equal(details.error_type, errorType);
}

test("decode: the recover conclusion matrix (confirm gates; dry_run × conclusions refuse)", async () => {
  const cwd = scaffoldRepo();
  // A throwing PERK_BIN proves the refusals happen before any cold-door exec.
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await invokeExpectingFail(h, { objective: "7", abandon: true }, "confirmation_required");
    await invokeExpectingFail(h, { abandon: true, confirm: true, dry_run: true }, "bad_input");
    await invokeExpectingFail(h, { objective: "7", accept_prefix: true }, "confirmation_required");
    await invokeExpectingFail(
      h,
      { accept_prefix: true, confirm: true, dry_run: true },
      "bad_input",
    );
    await invokeExpectingFail(
      h,
      { accept_prefix: true, abandon: true, confirm: true },
      "bad_input",
    );
    await invokeExpectingFail(h, { accept_prefix: "yes" }, "bad_input");
  } finally {
    h.dispose();
  }
});

// --- argv shapes --------------------------------------------------------------------------------------

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

// --- objective inference precedence --------------------------------------------------------------------

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
  try {
    const result = await h2.invokeTool("objective_stack_recover", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_objective");
  } finally {
    h2.dispose();
  }
});

// --- the lenient recover render + the pure guidance ------------------------------------------------------

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

test("guidance: classify-first, consent-gated, no hardcoded skill pointer", () => {
  const text = objectiveRecoverGuidance("7");
  for (const needle of [
    "objective_stack_recover",
    "dry_run: true",
    "abandon: true, confirm: true",
    'operation: "<ULID>"',
    "explicit human approval",
  ]) {
    assert.ok(text.includes(needle), `recover guidance must include: ${needle}`);
  }
  assert.ok(!/skills\//.test(text), "no hardcoded skill pointer (bindings own delivery)");
  assert.ok(!/perk-objective-recover\b/.test(text), "no hardcoded skill name");
});

// --- the reconcile drive call site (harness-level: the tool itself injects) ---------------------------

test("delegation: the recover tool's convergence close injects the reconcile drive exactly once", async () => {
  const cwd = scaffoldRepo();
  const envelope = JSON.stringify({
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
      ],
      final_base_sha: "d".repeat(40),
      partial: false,
      notes: [],
    },
    operations: [],
    landed_layers: [],
    swept_worktrees: [],
    swept_refs: [],
    sweep_skipped: null,
    notes: [],
  });
  const bin = fakePerk(cwd, { stdout: envelope });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_recover", { objective: "7" });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.equal(injected.length, 1, "exactly one drive injection");
    assert.match(injected[0] ?? "", /reconcile objective #7/i);
    assert.match(injected[0] ?? "", /BEGIN UNTRUSTED DATA/);
  } finally {
    h.dispose();
  }
});
