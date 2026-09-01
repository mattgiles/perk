// Feature-tier tests for the ready operation (delivery/ready.ts): deterministic fake `ReadyDeps`
// — no Pi, no harness. Proves transition ordering (effect first), the three negative gate pins
// (the gate capability is never read off the stamped-with-cohort path), classification, the
// gate-before-evidence arm order, the strict evidence matrix, evidence minting, and the
// safe-retry policy. The compile-time negatives (`@ts-expect-error`) pin the type-level
// promises runtime tests cannot prove: evidence nominality and the arm↔facts correlation.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type MarkReadyAttempt,
  type ReadyDeps,
  type ReadyDriveEvidence,
  type ReadyHandoff,
  type ReadyOutcome,
  readyChange,
} from "./ready.ts";

const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);

function prFacts(): { number: number; url: string } {
  return { number: 42, url: "https://gh/o/r/pull/42" };
}

function cohort(over: Partial<ReadyHandoff> = {}): ReadyHandoff {
  return {
    objective: "500",
    node: "1.2",
    stamped_head: SHA_B,
    stamp_advanced: true,
    plan: "7",
    parent_checkpoint: SHA_A,
    ...over,
  };
}

/** Fake deps with a call log — the ordering and gate-read pins read the log. */
function depsFor(
  attempt: MarkReadyAttempt,
  opts?: { readOnly?: boolean; gate?: () => boolean },
): { deps: ReadyDeps; log: string[] } {
  const log: string[] = [];
  const deps: ReadyDeps = {
    markReady: async () => {
      log.push("markReady");
      return attempt;
    },
    sessionReadOnly:
      opts?.gate ??
      (() => {
        log.push("gate");
        return opts?.readOnly ?? false;
      }),
  };
  return { deps, log };
}

/** A throwing gate sentinel: any read on a non-cohort arm fails that arm's row. */
function throwingGate(label: string): () => boolean {
  return () => {
    throw new Error(`gate read on the ${label} arm`);
  };
}

// --- the three negative gate pins (no continuation activity off the cohort path) --------------

test("failed: the exterior failure returns as-is — no continuation activity, gate never read", async () => {
  const { deps } = depsFor(
    { ok: false, message: "boom", errorType: "exec_failed" },
    { gate: throwingGate("failed") },
  );
  const outcome = await readyChange(deps);
  assert.deepEqual(outcome, { kind: "failed", message: "boom", errorType: "exec_failed" });
});

test("completed: incremental facts (stacked false AND absent) — gate never read", async () => {
  for (const stacked of [false, undefined] as const) {
    const { deps } = depsFor(
      {
        ok: true,
        facts: { route: "incremental", pr: prFacts(), was_draft: true, stacked },
      },
      { gate: throwingGate("completed") },
    );
    const outcome = await readyChange(deps);
    assert.equal(outcome.kind, "completed");
    assert.ok(outcome.kind === "completed");
    // The facts pass through identically (the adapter renders the wire from them).
    assert.deepEqual(outcome.facts, {
      route: "incremental",
      pr: prFacts(),
      was_draft: true,
      stacked,
    });
  }
});

test("stamp_facts_unverified: a dropped cohort stands the effect — gate never read", async () => {
  const { deps } = depsFor(
    { ok: true, facts: { route: "stacked_unverified", pr: prFacts(), was_draft: true } },
    { gate: throwingGate("stamp_facts_unverified") },
  );
  const outcome = await readyChange(deps);
  assert.equal(outcome.kind, "stamp_facts_unverified");
  assert.ok(outcome.kind === "stamp_facts_unverified");
  assert.deepEqual(outcome.facts, { route: "stacked_unverified", pr: prFacts(), was_draft: true });
});

// --- transition ordering -----------------------------------------------------------------------

test("ordering: the exterior effect precedes the gate read on the stamped path", async () => {
  const { deps, log } = depsFor({
    ok: true,
    facts: { route: "stacked", pr: prFacts(), was_draft: true, handoff: cohort() },
  });
  const outcome = await readyChange(deps);
  assert.equal(outcome.kind, "stamped");
  assert.deepEqual(log, ["markReady", "gate"], "effect first; ONE gate read, after it");
});

// --- classification + the continuation arms ----------------------------------------------------

test("stamped + gate active: refused_read_only (the gate check precedes evidence validation)", async () => {
  // Corrupt evidence UNDER an active gate must still classify as the gate refusal — the
  // pinned arm order (gate before evidence, today's order).
  const { deps } = depsFor(
    {
      ok: true,
      facts: {
        route: "stacked",
        pr: prFacts(),
        was_draft: true,
        handoff: cohort({ stamped_head: "not-a-sha" }),
      },
    },
    { readOnly: true },
  );
  const outcome = await readyChange(deps);
  assert.equal(outcome.kind, "stamped");
  assert.ok(outcome.kind === "stamped");
  assert.deepEqual(outcome.continuation, { kind: "refused_read_only", retryPlan: "7" });
});

test("refused_read_only: a marker-unsafe plan yields retryPlan null (placeholder policy)", async () => {
  const { deps } = depsFor(
    {
      ok: true,
      facts: { route: "stacked", pr: prFacts(), handoff: cohort({ plan: "7 !" }) },
    },
    { readOnly: true },
  );
  const outcome = await readyChange(deps);
  assert.ok(outcome.kind === "stamped");
  assert.deepEqual(outcome.continuation, { kind: "refused_read_only", retryPlan: null });
});

// Every prompt-interpolated evidence field is independently untrusted — each corruption must
// force `evidence_invalid` on its own (removing any one check fails exactly its row here).
const INVALID_EVIDENCE: readonly {
  label: string;
  over?: Partial<ReadyHandoff>;
  prNumber?: number;
  retryPlan: string | null;
}[] = [
  { label: "objective with whitespace", over: { objective: "50 0" }, retryPlan: "7" },
  { label: "marker-unsafe node", over: { node: "1.2!" }, retryPlan: "7" },
  { label: "empty plan", over: { plan: "" }, retryPlan: null },
  { label: "abbreviated parent checkpoint", over: { parent_checkpoint: "abc123" }, retryPlan: "7" },
  {
    label: "overlong parent checkpoint",
    over: { parent_checkpoint: "a".repeat(41) },
    retryPlan: "7",
  },
  { label: "uppercase stamped head", over: { stamped_head: "B".repeat(40) }, retryPlan: "7" },
  {
    label: "stamped head with trailing newline",
    over: { stamped_head: `${"b".repeat(39)}\n` },
    retryPlan: "7",
  },
  { label: "non-integer PR number", prNumber: 42.5, retryPlan: "7" },
];

test("each invalid evidence field independently forces evidence_invalid", async () => {
  for (const { label, over, prNumber, retryPlan } of INVALID_EVIDENCE) {
    const pr = prFacts();
    if (prNumber !== undefined) pr.number = prNumber;
    const { deps } = depsFor({
      ok: true,
      facts: { route: "stacked", pr, was_draft: true, handoff: cohort(over) },
    });
    const outcome = await readyChange(deps);
    assert.equal(outcome.kind, "stamped", label);
    assert.ok(outcome.kind === "stamped");
    assert.deepEqual(outcome.continuation, { kind: "evidence_invalid", retryPlan }, label);
  }
});

// --- the drive arm ------------------------------------------------------------------------------

test("drive: the evidence is minted with the exact six fields + the PR number", async () => {
  const { deps } = depsFor({
    ok: true,
    facts: { route: "stacked", pr: prFacts(), was_draft: false, handoff: cohort() },
  });
  const outcome = await readyChange(deps);
  assert.ok(outcome.kind === "stamped");
  assert.equal(outcome.continuation.kind, "drive");
  assert.ok(outcome.continuation.kind === "drive");
  const evidence = outcome.continuation.evidence;
  assert.equal(evidence.objective, "500");
  assert.equal(evidence.node, "1.2");
  assert.equal(evidence.plan, "7");
  assert.equal(evidence.stamped_head, SHA_B);
  assert.equal(evidence.parent_checkpoint, SHA_A);
  assert.equal(evidence.pr, 42);
  // The stamped facts ride the SAME arm — the message render reads them; the drive template
  // reads the evidence; both derive from the one decode.
  assert.deepEqual(outcome.facts.handoff, cohort());
});

test("drive: the evidence snapshots validated primitives — post-mint mutation cannot reach it", async () => {
  // The caller still holds the handoff object the facts arm carries; mutating it after the
  // validation passed must NOT change what the drive interpolates (no aliasing).
  const handoff = cohort();
  const { deps } = depsFor({
    ok: true,
    facts: { route: "stacked", pr: prFacts(), was_draft: true, handoff },
  });
  const outcome = await readyChange(deps);
  assert.ok(outcome.kind === "stamped" && outcome.continuation.kind === "drive");
  handoff.objective = "666";
  handoff.stamped_head = "not-a-sha";
  const evidence = outcome.continuation.evidence;
  assert.equal(evidence.objective, "500");
  assert.equal(evidence.stamped_head, SHA_B);
});

// --- compile-time negatives (type-level pins; runtime bodies are trivially green) ---------------

test("compile-time: a structural ReadyDriveEvidence literal is rejected (mint-only nominality)", () => {
  const raw = {
    pr: 42,
    objective: "500",
    node: "1.2",
    plan: "7",
    stamped_head: SHA_B,
    parent_checkpoint: SHA_A,
  };
  // @ts-expect-error — the #private brand makes structural forgery a compile error.
  const forged: ReadyDriveEvidence = raw;
  void forged;
});

test("compile-time: outcome arms are constrained to their matching facts variants", () => {
  const stacked = { route: "stacked", pr: prFacts(), handoff: cohort() } as const;
  // @ts-expect-error — a completed outcome cannot carry stacked facts.
  const completedWithCohort: ReadyOutcome = { kind: "completed", facts: stacked };
  void completedWithCohort;
  const incremental = { route: "incremental", pr: prFacts() } as const;
  const refusal = { kind: "refused_read_only", retryPlan: null } as const;
  const stampedIncremental: ReadyOutcome = {
    kind: "stamped",
    // @ts-expect-error — a stamped outcome cannot carry the incremental variant.
    facts: incremental,
    continuation: refusal,
  };
  void stampedIncremental;
});
