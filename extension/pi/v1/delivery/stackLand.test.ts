// Live warm-surface tests for the stacked-delivery landing bindings (stackLand.ts): the frozen
// registration baselines (tool + driving command), the full-details WIRE baselines captured
// from the pre-migration door (the merged close's exact injected drive included), strict
// decodes, cold-door argv shapes, the lenient land render (readiness preview + mutation arms),
// and the reconcile drive call site through the REGISTERED tool. Fully offline (fakePerk via
// PERK_BIN; a REAL bound AgentSession via the T1 harness).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { writePlanRef } from "../../../substrate/cache.ts";
import {
  fakePerk,
  loadPerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { buildStackLandArgs, objectiveLandGuidance, renderLandOutcome } from "./stackLand.ts";

// --- frozen registration baselines (captured from the pre-migration door) --------------------------

const BASELINE_LAND_TOOL = {
  name: "objective_stack_land",
  label: "Objective stack land",
  description:
    "Land an objective's remaining delivery train atomically: preview readiness (dry_run), " +
    "or merge the whole train in one journaled operation (merge-async for a multi-layer " +
    "train; a SHA-pinned direct squash for the dynamic singleton), finalize every layer, " +
    "and close the objective once every node is terminal. Mutating: requires confirm: true " +
    "(preview first with dry_run: true). Delegates to the perk cold door.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      objective: {
        type: ["string", "number"],
        description: "The objective issue id (inferred from the session when omitted).",
      },
      dry_run: {
        type: "boolean",
        description: "Preview landing readiness and the land plan — read-only.",
      },
      confirm: {
        type: "boolean",
        description: "Explicit human approval (required for the mutating call).",
      },
    },
  },
  promptSnippet: "Land the objective's delivery train atomically (confirm-gated)",
  promptGuidelines: [
    "Call objective_stack_land only inside the /objective-land flow: preview with dry_run: true, present the land plan (or blockers) to the human, then pass confirm: true ONLY on explicit human approval.",
    "Never loop retries. A pending or unexpected_enqueued outcome means the LAND operation is UNRESOLVED — report it and stop (never re-submit); once the merge settles or expires, /objective-recover (objective_stack_recover) classifies it against fresh authority and concludes it.",
  ],
  executionMode: "sequential",
};

test("registration parity: land tool + /objective-land match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(h.registeredTool("objective_stack_land"), BASELINE_LAND_TOOL);
    assert.deepEqual(h.registeredCommand("objective-land"), {
      name: "objective-land",
      description:
        "Drive an atomic landing: preview readiness, present the land plan, merge the whole " +
        "train via the typed land tool on explicit approval. Pass an objective number (else " +
        "the active objective).",
    });
  } finally {
    h.dispose();
  }
});

// --- full-details wire baselines (captured from the pre-migration door) -----------------------------

async function invokeLand(opts: { params: unknown; stdout: string; code?: number }) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: opts.stdout, code: opts.code ?? 0 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("objective_stack_land", opts.params);
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

const LAND_DRY_RUN = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
  dry_run: true,
  disposition: "ready",
  plan: {
    mode: "singleton_squash",
    merge_method: "squash",
    top_pr_number: 501,
    top_head_sha: "1".repeat(40),
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

const LAND_MERGED = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
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

test("wire baseline: the dry-run readiness preview (no drive)", async () => {
  const r = await invokeLand({ params: { objective: "7", dry_run: true }, stdout: LAND_DRY_RUN });
  assert.equal(
    r.text,
    "Objective #7: landing readiness (dry run) — READY\n" +
      "plan: singleton_squash via squash — top pr #501 (1 layer(s))\n" +
      `  1.1 plan #101 (pr #501): ${"0".repeat(40)} → ${"1".repeat(40)}\n` +
      "information:\n" +
      "  - [unresolved_threads] 2 unresolved",
  );
  assert.deepEqual(r.details, { ok: true, objective: "7" });
  assert.equal(r.terminate, null);
  assert.deepEqual(r.injected, [], "a readiness preview never drives");
});

test("wire baseline: the mutating confirm-refusal", async () => {
  const r = await invokeLand({ params: { objective: "7" }, stdout: LAND_DRY_RUN });
  assert.deepEqual(r.details, {
    ok: false,
    error:
      "landing merges the ENTIRE remaining train atomically — preview with dry_run: true, " +
      "then pass confirm: true on explicit human approval.",
    error_type: "confirmation_required",
  });
  assert.equal(r.terminate, null);
  assert.deepEqual(r.injected, []);
});

test("wire baseline: the merged close — evidence summary + exactly ONE injected drive", async () => {
  const r = await invokeLand({ params: { objective: "7", confirm: true }, stdout: LAND_MERGED });
  assert.equal(
    r.text,
    "landed 1 layer(s) atomically (operation 01OP)\n" +
      "  1.1 plan #101 (pr #501): merged as cccccccccccc\n" +
      "objective #7 complete — closed\n" +
      "reconcile evidence: 1 layer(s), final base cccccccccccc",
  );
  assert.deepEqual(r.details, { ok: true, objective: "7" });
  assert.equal(r.terminate, null);
  assert.equal(r.injected.length, 1, "exactly one drive injection");
  const content = r.injected[0] ?? "";
  assert.match(content, /reconcile objective #7/i);
  assert.match(
    content,
    /Landed-train evidence \(journal-ordered, bottom→top\) — BEGIN UNTRUSTED DATA/,
  );
  assert.match(content, /- 1\.1 plan #101 pr #501: base 0{40} → head 1{40}, merged as c{40}/);
  assert.match(content, /final objective-base sha: c{40}/);
  assert.match(content, /END UNTRUSTED DATA/);
  assert.match(content, /gh pr diff <pr>/);
  assert.match(content, /perk-objective-reconcile/);
});

// --- strict tool decodes -----------------------------------------------------------------------------

test("decode: land — mistyped fields refuse; the mutating call requires confirm", async () => {
  const cwd = scaffoldRepo();
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    for (const params of [{ dry_run: "yes" }, { objective: [] }]) {
      const result = await h.invokeTool("objective_stack_land", params);
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false);
      assert.equal(details.error_type, "bad_input");
    }
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

// --- argv shapes + delegation --------------------------------------------------------------------------

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

test("delegation: the confirmed land infers the objective (plan-ref tier) and passes --yes", async () => {
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

// --- the lenient land render + the pure guidance ---------------------------------------------------------

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
    renderLandOutcome({
      objective: { id: "7" },
      outcome: "completed_without_merge",
      objective_closed: true,
    }),
    /nothing to merge — objective #7 closed as complete/,
  );
  // Honest close reporting: no close transition ⇒ never announce one.
  assert.match(
    renderLandOutcome({ objective: { id: "7" }, outcome: "completed_without_merge" }),
    /nothing to merge — objective #7 was NOT closed \(see notes\)/,
  );
  // Tolerant of a missing outcome entirely (an unknown arm renders honestly).
  assert.match(renderLandOutcome({ objective: { id: "7" } }), /landing outcome: \?/);
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

test("guidance: preview-first, consent-gated, no hardcoded skill pointer", () => {
  const text = objectiveLandGuidance("7");
  for (const needle of [
    "objective_stack_status",
    "objective_stack_land",
    "dry_run: true",
    "confirm: true",
    "explicit human approval",
    "UNRESOLVED",
    "Never loop retries",
  ]) {
    assert.ok(text.includes(needle), `land guidance must include: ${needle}`);
  }
  assert.ok(!/skills\//.test(text), "no hardcoded skill pointer (bindings own delivery)");
  assert.ok(!/perk-objective-land\b/.test(text), "no hardcoded skill name");
});
