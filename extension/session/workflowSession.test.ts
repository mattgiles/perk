// The shared WorkflowSession interface suite, parameterized over BOTH bindings of the one
// session engine (branch/file production and the testing/ in-memory ports) — every
// classification arm is reached on each: identity (including the identity-less always-open arm:
// artifact writes reject, reads read absent, state ops work; and the unsafe-run-id degrade),
// applied (receipt + read-back roundtrip), the unchanged short-circuit (no fresh append),
// rejected (invalid name, io refusal), unverified (pointer-append failure), the read tiers
// (found / absent — no pointer, malformed pointer, cross-run fork pointer / invalid — missing
// file, digest mismatch), the strict ledger append pre-read, and the workflow-state ops
// (`nodeClaim()`/`activeObjective()`/`reviewPosts()` reads + `apply()` over the closed change
// union: applied / unchanged / unverified / rejected / non-matching claim /
// same-node-different-objective / no-identity). Branch-only seam-level cases prove the
// fork/reload reconstruction shapes (identity + claims + active_objective rebuild from the
// persisted branch; a fork-derived child reads the parent's artifacts as absent) and the
// persisted-pointer trust pins (junk never flows; hostile paths never dereferenced).

import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { test } from "node:test";
import { type PlanRef, sessionDataDir } from "../substrate/cache.ts";
import { digestSessionData, type SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type EntrySink,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "../substrate/workflowState.ts";
import { openMemoryWorkflowSession } from "../testing/memoryWorkflowSession.ts";
import { openBranchWorkflowSession } from "./branchWorkflowSession.ts";
import {
  type PrReviewRecord,
  type ReviewBatchRecord,
  type ReviewPostRow,
  type ReviewSubmissionRecord,
  reviewPostsOf,
  soundPointer,
  type WorkflowSession,
} from "./workflowSession.ts";

function planRef(prId: string): PlanRef {
  return {
    provider: "github",
    pr_id: prId,
    url: `https://github.com/o/r/issues/${prId}`,
    labels: ["perk:plan"],
    objective_id: null,
  };
}

const CLAIM = { objective: "7", node: "1.1" };

const REVIEW_RECORD: ReviewSubmissionRecord = {
  pr: 42,
  event: "comment",
  comment_count: 2,
  mode: "review",
  at: "2026-01-01T00:00:00Z",
};

const POST_ROW: ReviewPostRow = { pr: 42, event: "comment", at: "2026-01-01T00:00:00Z" };

const REVIEW_BATCH_RECORD: ReviewBatchRecord = {
  pr: 42,
  counts: { actionable: 2, informational: 0, praise: 0, question: 0 },
  resolved_thread_ids: ["PRRT_1", "PRRT_2"],
  at: "2026-01-01T00:00:00Z",
};

const PR_REVIEW_RECORD: PrReviewRecord = {
  pr: 42,
  verdict: "actionable",
  angles: ["plan-fidelity", "tests", "ponytail"],
  covered_angles: ["plan-fidelity", "tests", "ponytail"],
  comment_count: 2,
  mode: "review",
  at: "2026-01-01T00:00:00Z",
};

/** The per-backing harness: one session plus deterministic ways to reach every arm. */
interface SessionHarness {
  session: WorkflowSession;
  /** Make the NEXT writeArtifact refuse before any effect (the rejected io arm). */
  induceWriteRefusal(): void;
  /** Make the NEXT writeArtifact land its bytes but fail the pointer proof (unverified). */
  inducePointerAppendFailure(): void;
  /** Make the NEXT apply fail its read-back proof (unverified). */
  induceApplyVerificationFailure(): void;
  /** Make the NEXT apply refuse before any effect (rejected). */
  induceApplyRefusal(): void;
  /** After a successful write of `name`: make its stored bytes mismatch the pointer (invalid). */
  corrupt(name: string): void;
  /** After a successful write of `name`: drop its stored bytes, keep the pointer (invalid). */
  dropFile(name: string): void;
  /** After a successful write of `name`: make its pointer belong to a foreign run (absent). */
  disown(name: string): void;
  /** The rebuilt/live `active_plan_ref` (observation of the link effect). */
  linkedPlanRef(): PlanRef | null;
  /** The rebuilt/live `last_review` record (observation of the record-review effect). */
  lastReview(): ReviewSubmissionRecord | null;
  /** The rebuilt/live `last_pr_review` record (observation of the record-pr-review effect). */
  lastPrReview(): PrReviewRecord | null;
  /** The rebuilt/live `last_review_batch` record (observation of the record-review-batch effect). */
  lastReviewBatch(): ReviewBatchRecord | null;
  /** Attempted workflow-state appends (the no-append observation for the unchanged arm). */
  appendCount(): number;
  /** The backing's derived display path for `name` (what a receipt's `path` must equal). */
  expectedPath(name: string): string;
  dispose(): void;
}

interface HarnessOpts {
  nodeClaim?: { objective: string; node: string };
  activePlanRef?: PlanRef;
  activeObjective?: string;
  /** Deliberately wide: the strict-ledger pins seed malformed persisted shapes. */
  reviewPosts?: unknown;
}

interface Backing {
  label: string;
  open(runId: string | null): WorkflowSession;
  harness(runId: string | null, opts?: HarnessOpts): SessionHarness;
}

// --- the branch/file backing fixtures ----------------------------------------------------------

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

/** A `SessionArtifactCtx` over a live branch array (headless, notify is a no-op). */
function reportableCtx(cwd: string, branch: unknown[]): SessionArtifactCtx {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: false,
    ui: { notify() {} },
  };
}

/** Capture console.error calls for the duration of `fn` (silences the seam's loud warnings). */
function quietly<T>(fn: () => T): T {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

function branchBacking(): Backing {
  return {
    label: "branch",
    open(runId) {
      const cwd = mkdtempSync(join(tmpdir(), "workflow-session-open-"));
      const branch: unknown[] = runId === null ? [] : [stateEntry({ run_id: runId })];
      const sink: EntrySink = {
        appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
      };
      return openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    },
    harness(runId, opts = {}) {
      const cwd = mkdtempSync(join(tmpdir(), "workflow-session-test-"));
      const branch: unknown[] = runId === null ? [] : [stateEntry({ run_id: runId })];
      if (opts.nodeClaim !== undefined) {
        branch.push(stateEntry({ objective_node_claim: opts.nodeClaim }));
      }
      if (opts.activePlanRef !== undefined) {
        branch.push(stateEntry({ active_plan_ref: opts.activePlanRef }));
      }
      if (opts.activeObjective !== undefined) {
        branch.push(stateEntry({ active_objective: opts.activeObjective }));
      }
      if (opts.reviewPosts !== undefined) {
        branch.push(stateEntry({ review_posts: opts.reviewPosts }));
      }
      let dropAppends = false;
      let throwNextAppend = false;
      let appends = 0;
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
          appends += 1;
          if (throwNextAppend) {
            throwNextAppend = false;
            throw new Error("append refused (induced)");
          }
          if (dropAppends) {
            dropAppends = false;
            return;
          }
          branch.push({ type: "custom", customType, data });
        },
      };
      const ctx = reportableCtx(cwd, branch);
      const session = openBranchWorkflowSession(sink, ctx);
      const perkDir = join(cwd, ".perk");
      let lockedPerkDir = false;
      return {
        session,
        induceWriteRefusal() {
          // A read-only cache parent refuses the atomic write before any effect lands.
          mkdirSync(perkDir, { recursive: true });
          chmodSync(perkDir, 0o444);
          lockedPerkDir = true;
        },
        inducePointerAppendFailure() {
          dropAppends = true;
        },
        induceApplyVerificationFailure() {
          dropAppends = true;
        },
        // A throwing append whose rebuilt field never changed is the PROVEN
        // refusal-before-effect — the classified strict-append maps it to `rejected`.
        induceApplyRefusal() {
          throwNextAppend = true;
        },
        corrupt(name) {
          writeFileSync(join(sessionDataDir(cwd, runId ?? ""), name), "rewound bytes", "utf8");
        },
        dropFile(name) {
          rmSync(join(sessionDataDir(cwd, runId ?? ""), name));
        },
        disown(name) {
          void name;
          // A fork child inherits the parent's pointer entries under a derived run_id: every
          // pointer on the branch now belongs to a foreign run.
          branch.push(stateEntry({ run_id: `${runId}.1` }));
        },
        linkedPlanRef() {
          return (
            rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0])
              .active_plan_ref ?? null
          );
        },
        lastReview() {
          const value = rebuildWorkflowState(
            branch as Parameters<typeof rebuildWorkflowState>[0],
          ).last_review;
          return (value ?? null) as ReviewSubmissionRecord | null;
        },
        lastPrReview() {
          const value = rebuildWorkflowState(
            branch as Parameters<typeof rebuildWorkflowState>[0],
          ).last_pr_review;
          return (value ?? null) as PrReviewRecord | null;
        },
        lastReviewBatch() {
          const value = rebuildWorkflowState(
            branch as Parameters<typeof rebuildWorkflowState>[0],
          ).last_review_batch;
          return (value ?? null) as ReviewBatchRecord | null;
        },
        appendCount() {
          return appends;
        },
        expectedPath(name) {
          return relative(cwd, join(sessionDataDir(cwd, runId ?? ""), name));
        },
        dispose() {
          if (lockedPerkDir) chmodSync(perkDir, 0o755);
          rmSync(cwd, { recursive: true, force: true });
        },
      };
    },
  };
}

function memoryBacking(): Backing {
  return {
    label: "memory",
    open(runId) {
      return openMemoryWorkflowSession({ runId });
    },
    harness(runId, opts = {}) {
      const session = openMemoryWorkflowSession({
        runId,
        ...(opts.nodeClaim !== undefined ? { nodeClaim: opts.nodeClaim } : {}),
        ...(opts.activePlanRef !== undefined ? { activePlanRef: opts.activePlanRef } : {}),
        ...(opts.activeObjective !== undefined ? { activeObjective: opts.activeObjective } : {}),
        ...(opts.reviewPosts !== undefined
          ? { reviewPosts: opts.reviewPosts as ReviewPostRow[] }
          : {}),
      });
      return {
        session,
        induceWriteRefusal: () => session.failNextWrite(),
        inducePointerAppendFailure: () => session.failNextPointerAppend(),
        induceApplyVerificationFailure: () => session.failNextApplyVerification(),
        induceApplyRefusal: () => session.failNextApply(),
        corrupt: (name) => session.corruptContent(name),
        dropFile: (name) => session.dropContent(name),
        disown: (name) => session.disownPointer(name),
        linkedPlanRef: () => session.linkedPlanRef(),
        lastReview: () => session.lastReviewRecord(),
        lastPrReview: () => session.lastPrReviewRecord(),
        lastReviewBatch: () => session.lastReviewBatchRecord(),
        appendCount: () => session.appendCount(),
        expectedPath: (name) => name,
        dispose() {},
      };
    },
  };
}

// --- the shared suite --------------------------------------------------------------------------

for (const backing of [branchBacking(), memoryBacking()]) {
  test(`${backing.label}: always opens — identity-less runId is null; with identity → runId`, () => {
    assert.equal(backing.open(null).runId, null);
    assert.equal(backing.open("RID").runId, "RID");
  });

  test(`${backing.label}: no identity — artifact writes reject, reads read absent, state ops work`, () => {
    const h = backing.harness(null, { nodeClaim: CLAIM });
    try {
      const written = quietly(() => h.session.writeArtifact("draft.json", "v1"));
      assert.equal(written.status, "rejected");
      assert.ok(written.status === "rejected" && /no run_id/.test(written.problem));
      assert.deepEqual(h.session.readArtifact("draft.json"), { status: "absent" });
      // State ops are branch-backed and identity-independent (the identity-less save arm).
      assert.deepEqual(h.session.nodeClaim(), CLAIM);
      const linked = h.session.apply({ kind: "link-plan-ref", ref: planRef("42") });
      assert.deepEqual(linked, { status: "applied" });
      assert.deepEqual(h.linkedPlanRef(), planRef("42"));
      const cleared = h.session.apply({ kind: "clear-node-claim", claim: CLAIM });
      assert.deepEqual(cleared, { status: "applied" });
      assert.equal(h.session.nodeClaim(), null);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: applied — receipt carries validated identity + derived path, read-back roundtrips`, () => {
    const h = backing.harness("RID");
    try {
      const written = h.session.writeArtifact("draft.json", "v1");
      assert.equal(written.status, "applied");
      assert.ok(written.status === "applied");
      assert.equal(written.receipt.runId, "RID");
      assert.equal(written.receipt.path, h.expectedPath("draft.json"));
      assert.match(written.receipt.digest, /^sha256:[0-9a-f]{64}$/);
      assert.deepEqual(h.session.readArtifact("draft.json"), {
        status: "found",
        content: "v1",
      });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: a byte-identical rewrite short-circuits to unchanged`, () => {
    const h = backing.harness("RID");
    try {
      const first = h.session.writeArtifact("draft.json", "same bytes");
      assert.equal(first.status, "applied");
      const afterFirst = h.appendCount();
      const second = h.session.writeArtifact("draft.json", "same bytes");
      assert.equal(second.status, "unchanged");
      assert.ok(first.status === "applied" && second.status === "unchanged");
      assert.deepEqual(second.receipt, first.receipt, "the receipt re-derives identically");
      assert.equal(h.appendCount(), afterFirst, "no fresh pointer entry was appended");
      // Different bytes still apply (and append a fresh pointer).
      const third = h.session.writeArtifact("draft.json", "different bytes");
      assert.equal(third.status, "applied");
      assert.equal(h.appendCount(), afterFirst + 1);
      assert.deepEqual(h.session.readArtifact("draft.json"), {
        status: "found",
        content: "different bytes",
      });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: rejected — invalid names refuse before any effect`, () => {
    const h = backing.harness("RID");
    try {
      for (const name of ["", "  ", "a/b.json", "a\\b.json"]) {
        const result = h.session.writeArtifact(name, "x");
        assert.equal(result.status, "rejected", `name ${JSON.stringify(name)} must be rejected`);
        assert.ok(result.status === "rejected" && result.problem.length > 0);
      }
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: rejected — an io refusal lands nothing`, () => {
    const h = backing.harness("RID");
    try {
      h.induceWriteRefusal();
      const result = quietly(() => h.session.writeArtifact("draft.json", "x"));
      assert.equal(result.status, "rejected");
      assert.deepEqual(h.session.readArtifact("draft.json"), { status: "absent" });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: unverified — a pointer-append failure is never consumable`, () => {
    const h = backing.harness("RID");
    try {
      h.inducePointerAppendFailure();
      const result = quietly(() => h.session.writeArtifact("draft.json", "x"));
      assert.equal(result.status, "unverified");
      assert.ok(result.status === "unverified" && /pointer read-back failed/.test(result.problem));
      // The orphan bytes may exist, but without a pointer the artifact reads absent.
      assert.deepEqual(h.session.readArtifact("draft.json"), { status: "absent" });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: read — absent without a pointer; absent on a cross-run fork pointer`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.readArtifact("never-written.json"), { status: "absent" });
      assert.equal(h.session.writeArtifact("draft.json", "v1").status, "applied");
      h.disown("draft.json");
      assert.deepEqual(
        quietly(() => h.session.readArtifact("draft.json")),
        { status: "absent" },
        "a pointer keyed to a foreign run reads absent (fork isolation — silent)",
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: read — invalid on a missing file and on a digest mismatch (rewind)`, () => {
    const h = backing.harness("RID");
    try {
      assert.equal(h.session.writeArtifact("gone.json", "v1").status, "applied");
      h.dropFile("gone.json");
      const missing = quietly(() => h.session.readArtifact("gone.json"));
      assert.equal(missing.status, "invalid");
      assert.ok(missing.status === "invalid" && /pointer but no file/.test(missing.problem));

      assert.equal(h.session.writeArtifact("rewound.json", "v1").status, "applied");
      h.corrupt("rewound.json");
      const rewound = quietly(() => h.session.readArtifact("rewound.json"));
      assert.equal(rewound.status, "invalid");
      assert.ok(rewound.status === "invalid" && /digest mismatch/.test(rewound.problem));
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: nodeClaim — snapshot read (present, absent)`, () => {
    const withClaim = backing.harness("RID", { nodeClaim: CLAIM });
    const without = backing.harness("RID");
    try {
      assert.deepEqual(withClaim.session.nodeClaim(), CLAIM);
      assert.equal(without.session.nodeClaim(), null);
    } finally {
      withClaim.dispose();
      without.dispose();
    }
  });

  test(`${backing.label}: apply link-plan-ref — applied, then unchanged on the same identity`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "link-plan-ref", ref: planRef("42") }), {
        status: "applied",
      });
      assert.deepEqual(h.linkedPlanRef(), planRef("42"));
      // Same (provider, pr_id) identity → unchanged, even when other fields drift.
      assert.deepEqual(
        h.session.apply({
          kind: "link-plan-ref",
          ref: { ...planRef("42"), labels: ["perk:plan", "drifted"] },
        }),
        { status: "unchanged" },
      );
      // A different plan applies again.
      assert.deepEqual(h.session.apply({ kind: "link-plan-ref", ref: planRef("43") }), {
        status: "applied",
      });
      assert.deepEqual(h.linkedPlanRef(), planRef("43"));
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply link-plan-ref — a read-back miss classifies unverified`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const result = quietly(() => h.session.apply({ kind: "link-plan-ref", ref: planRef("42") }));
      assert.equal(result.status, "unverified");
      assert.ok(result.status === "unverified" && /plan-ref read-back failed/.test(result.problem));
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply clear-node-claim — applied on a both-field match, verified`, () => {
    const h = backing.harness("RID", { nodeClaim: CLAIM });
    try {
      assert.deepEqual(h.session.apply({ kind: "clear-node-claim", claim: CLAIM }), {
        status: "applied",
      });
      assert.equal(h.session.nodeClaim(), null);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply clear-node-claim — no live claim / non-matching claim ⇒ unchanged`, () => {
    const none = backing.harness("RID");
    const other = backing.harness("RID", { nodeClaim: { objective: "7", node: "2.9" } });
    try {
      assert.deepEqual(none.session.apply({ kind: "clear-node-claim", claim: CLAIM }), {
        status: "unchanged",
      });
      assert.deepEqual(other.session.apply({ kind: "clear-node-claim", claim: CLAIM }), {
        status: "unchanged",
      });
      assert.deepEqual(other.session.nodeClaim(), { objective: "7", node: "2.9" });
    } finally {
      none.dispose();
      other.dispose();
    }
  });

  test(`${backing.label}: apply clear-node-claim — same node, DIFFERENT objective is preserved`, () => {
    // A save linked to objective B node 1.1 must never clear objective A's standing 1.1 claim.
    const h = backing.harness("RID", { nodeClaim: { objective: "7", node: "1.1" } });
    try {
      const result = h.session.apply({
        kind: "clear-node-claim",
        claim: { objective: "9", node: "1.1" },
      });
      assert.deepEqual(result, { status: "unchanged" });
      assert.deepEqual(h.session.nodeClaim(), { objective: "7", node: "1.1" });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply clear-node-claim — a read-back miss classifies unverified`, () => {
    const h = backing.harness("RID", { nodeClaim: CLAIM });
    try {
      h.induceApplyVerificationFailure();
      const result = quietly(() => h.session.apply({ kind: "clear-node-claim", claim: CLAIM }));
      assert.equal(result.status, "unverified");
      assert.ok(
        result.status === "unverified" &&
          /objective_node_claim clear read-back failed/.test(result.problem),
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: activeObjective — snapshot read (present, absent)`, () => {
    const withObjective = backing.harness("RID", { activeObjective: "7" });
    const without = backing.harness("RID");
    try {
      assert.equal(withObjective.session.activeObjective(), "7");
      assert.equal(without.session.activeObjective(), null);
    } finally {
      withObjective.dispose();
      without.dispose();
    }
  });

  test(`${backing.label}: apply record-node-claim — applied, verified via the named read`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "record-node-claim", claim: CLAIM }), {
        status: "applied",
      });
      assert.deepEqual(h.session.nodeClaim(), CLAIM);
      // A DIFFERENT claim applies again (replaces the live one).
      const other = { objective: "9", node: "3.2" };
      assert.deepEqual(h.session.apply({ kind: "record-node-claim", claim: other }), {
        status: "applied",
      });
      assert.deepEqual(h.session.nodeClaim(), other);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-node-claim — an equal live claim short-circuits unchanged`, () => {
    // The idempotent re-claim (a re-append "refresh" carries no semantic payload: the claim
    // has no timestamp and rebuilds identically).
    const h = backing.harness("RID", { nodeClaim: CLAIM });
    try {
      assert.deepEqual(h.session.apply({ kind: "record-node-claim", claim: { ...CLAIM } }), {
        status: "unchanged",
      });
      assert.deepEqual(h.session.nodeClaim(), CLAIM);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-node-claim — a read-back miss classifies unverified`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const result = quietly(() => h.session.apply({ kind: "record-node-claim", claim: CLAIM }));
      assert.equal(result.status, "unverified");
      assert.ok(
        result.status === "unverified" &&
          /objective_node_claim read-back failed/.test(result.problem),
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-node-claim — a refusal before any effect is rejected`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyRefusal();
      const result = quietly(() => h.session.apply({ kind: "record-node-claim", claim: CLAIM }));
      assert.equal(result.status, "rejected");
      assert.equal(h.session.nodeClaim(), null, "a rejected record lands nothing");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply link-objective — applied, then unchanged on the same id`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "link-objective", objective: "7" }), {
        status: "applied",
      });
      assert.equal(h.session.activeObjective(), "7");
      assert.deepEqual(h.session.apply({ kind: "link-objective", objective: "7" }), {
        status: "unchanged",
      });
      // A different objective applies again (LWW).
      assert.deepEqual(h.session.apply({ kind: "link-objective", objective: "9" }), {
        status: "applied",
      });
      assert.equal(h.session.activeObjective(), "9");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply link-objective — a read-back miss classifies unverified`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const result = quietly(() => h.session.apply({ kind: "link-objective", objective: "7" }));
      assert.equal(result.status, "unverified");
      assert.ok(
        result.status === "unverified" &&
          /active_objective read-back failed for #7/.test(result.problem),
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply link-objective — a refusal before any effect is rejected`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyRefusal();
      const result = quietly(() => h.session.apply({ kind: "link-objective", objective: "7" }));
      assert.equal(result.status, "rejected");
      assert.equal(h.session.activeObjective(), null, "a rejected link lands nothing");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-pr-review — applied; a repeat identical record applies AGAIN (no unchanged)`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "record-pr-review", record: PR_REVIEW_RECORD }), {
        status: "applied",
      });
      assert.deepEqual(h.lastPrReview(), PR_REVIEW_RECORD);
      assert.deepEqual(
        h.session.apply({ kind: "record-pr-review", record: { ...PR_REVIEW_RECORD } }),
        { status: "applied" },
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-pr-review — unverified on a read-back miss; rejected lands nothing`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const miss = quietly(() =>
        h.session.apply({ kind: "record-pr-review", record: PR_REVIEW_RECORD }),
      );
      assert.equal(miss.status, "unverified");
      assert.ok(
        miss.status === "unverified" && /last_pr_review read-back failed/.test(miss.problem),
      );
      h.induceApplyRefusal();
      const refused = quietly(() =>
        h.session.apply({ kind: "record-pr-review", record: PR_REVIEW_RECORD }),
      );
      assert.equal(refused.status, "rejected");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-review — applied; a repeat identical record applies AGAIN (no unchanged)`, () => {
    // No pre-read/deep-equal short-circuit by design: the resume guard is feature-op policy
    // upstream, so the seam never emits `unchanged` for this variant (runtime invariant).
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "record-review", record: REVIEW_RECORD }), {
        status: "applied",
      });
      assert.deepEqual(h.lastReview(), REVIEW_RECORD);
      assert.deepEqual(h.session.apply({ kind: "record-review", record: { ...REVIEW_RECORD } }), {
        status: "applied",
      });
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-review — unverified on a read-back miss; rejected lands nothing`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const miss = quietly(() => h.session.apply({ kind: "record-review", record: REVIEW_RECORD }));
      assert.equal(miss.status, "unverified");
      assert.ok(miss.status === "unverified" && /last_review read-back failed/.test(miss.problem));
      h.induceApplyRefusal();
      const refused = quietly(() =>
        h.session.apply({ kind: "record-review", record: REVIEW_RECORD }),
      );
      assert.equal(refused.status, "rejected");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply append-review-post — ordered rows; an identical row appends AGAIN (no dedupe)`, () => {
    const h = backing.harness("RID", { reviewPosts: [{ pr: 41, event: "comment", at: "t0" }] });
    try {
      assert.deepEqual(h.session.apply({ kind: "append-review-post", row: POST_ROW }), {
        status: "applied",
      });
      assert.deepEqual(h.session.reviewPosts(), [{ pr: 41, event: "comment", at: "t0" }, POST_ROW]);
      // No dedupe: the same row appends again (the resume guard lives upstream).
      assert.deepEqual(h.session.apply({ kind: "append-review-post", row: { ...POST_ROW } }), {
        status: "applied",
      });
      assert.equal(h.session.reviewPosts().length, 3);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-review-batch — applied; a repeat identical record applies AGAIN (no unchanged)`, () => {
    // No pre-read/deep-equal short-circuit by design: the corroborated-success ordering is
    // feature-op policy upstream, so the seam never emits `unchanged` for this variant.
    const h = backing.harness("RID");
    try {
      assert.deepEqual(
        h.session.apply({ kind: "record-review-batch", record: REVIEW_BATCH_RECORD }),
        {
          status: "applied",
        },
      );
      // The persisted shape is pinned byte-exactly (the wire twin of the recorded batch).
      assert.deepEqual(h.lastReviewBatch(), {
        pr: 42,
        counts: { actionable: 2, informational: 0, praise: 0, question: 0 },
        resolved_thread_ids: ["PRRT_1", "PRRT_2"],
        at: "2026-01-01T00:00:00Z",
      });
      assert.deepEqual(
        h.session.apply({ kind: "record-review-batch", record: { ...REVIEW_BATCH_RECORD } }),
        { status: "applied" },
      );
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply record-review-batch — unverified on a read-back miss; rejected lands nothing`, () => {
    const h = backing.harness("RID");
    try {
      h.induceApplyVerificationFailure();
      const miss = quietly(() =>
        h.session.apply({ kind: "record-review-batch", record: REVIEW_BATCH_RECORD }),
      );
      assert.equal(miss.status, "unverified");
      assert.ok(
        miss.status === "unverified" && /last_review_batch read-back failed/.test(miss.problem),
      );
      h.induceApplyRefusal();
      const refused = quietly(() =>
        h.session.apply({ kind: "record-review-batch", record: REVIEW_BATCH_RECORD }),
      );
      assert.equal(refused.status, "rejected");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: apply append-review-post — unverified on a read-back miss; rejected preserves the ledger`, () => {
    const h = backing.harness("RID", { reviewPosts: [{ pr: 41, event: "comment", at: "t0" }] });
    try {
      h.induceApplyVerificationFailure();
      const miss = quietly(() => h.session.apply({ kind: "append-review-post", row: POST_ROW }));
      assert.equal(miss.status, "unverified");
      assert.ok(miss.status === "unverified" && /review_posts read-back failed/.test(miss.problem));
      h.induceApplyRefusal();
      const refused = quietly(() => h.session.apply({ kind: "append-review-post", row: POST_ROW }));
      assert.equal(refused.status, "rejected");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: reviewPosts — snapshot read (seeded, empty)`, () => {
    const seeded = backing.harness("RID", { reviewPosts: [POST_ROW] });
    const empty = backing.harness("RID");
    try {
      assert.deepEqual(seeded.session.reviewPosts(), [POST_ROW]);
      assert.deepEqual(empty.session.reviewPosts(), []);
    } finally {
      seeded.dispose();
      empty.dispose();
    }
  });

  test(`${backing.label}: apply — a refusal before any effect classifies rejected`, () => {
    const h = backing.harness("RID", { nodeClaim: CLAIM });
    try {
      h.induceApplyRefusal();
      const linked = quietly(() => h.session.apply({ kind: "link-plan-ref", ref: planRef("42") }));
      assert.equal(linked.status, "rejected");
      assert.equal(h.linkedPlanRef(), null, "a rejected apply lands nothing");
      h.induceApplyRefusal();
      const cleared = quietly(() => h.session.apply({ kind: "clear-node-claim", claim: CLAIM }));
      assert.equal(cleared.status, "rejected");
      assert.deepEqual(h.session.nodeClaim(), CLAIM, "a rejected clear preserves the claim");
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: an unsafe rebuilt run_id degrades to no identity (the read-path trust boundary)`, () => {
    // A hostile persisted run_id (path traversal, separators) must never key a path derivation
    // or reach a receipt: identity degrades to null — reads absent, writes rejected, no append.
    for (const hostile of ["../evil", "a/b"]) {
      const h = backing.harness(hostile);
      try {
        assert.equal(h.session.runId, null, JSON.stringify(hostile));
        assert.deepEqual(h.session.readArtifact("draft.json"), { status: "absent" });
        const written = h.session.writeArtifact("draft.json", "x");
        assert.equal(written.status, "rejected");
        assert.ok(written.status === "rejected" && /no run_id/.test(written.problem));
        assert.equal(h.appendCount(), 0, "the refusal lands before any effect");
      } finally {
        h.dispose();
      }
    }
    // Legitimate ids — ULID mints and `<parent>.<n>` fork derivations — pass unaffected.
    assert.equal(backing.open("RID").runId, "RID");
    assert.equal(backing.open("RID.1").runId, "RID.1");
  });

  test(`${backing.label}: append-review-post refuses over a MALFORMED persisted ledger (strict decode)`, () => {
    // Deliberately stricter than the tolerant reviewPosts() read: silently narrowing a
    // malformed persisted ledger would let the whole-list LWW re-append ERASE
    // malformed-but-possibly-real rows — a confirmed post must never be erased by a write.
    const malformedLedgers: unknown[] = [
      "junk", // not a list
      { pr: 41 }, // not a list
      [{ pr: "41", event: "comment", at: "t0" }], // malformed row: pr not an integer
      [{ pr: 41, event: "comment", at: "t0" }, 7], // malformed row amid sound ones
    ];
    for (const seeded of malformedLedgers) {
      const h = backing.harness("RID", { reviewPosts: seeded });
      try {
        const before = h.appendCount();
        const result = h.session.apply({ kind: "append-review-post", row: POST_ROW });
        assert.equal(result.status, "rejected", JSON.stringify(seeded));
        assert.ok(
          result.status === "rejected" &&
            /refusing to append over an unknown ledger/.test(result.problem),
        );
        assert.equal(h.appendCount(), before, "the refusal lands before any append effect");
      } finally {
        h.dispose();
      }
    }
  });

  test(`${backing.label}: append-review-post over an ABSENT ledger applies (the normal first append)`, () => {
    const h = backing.harness("RID");
    try {
      assert.deepEqual(h.session.apply({ kind: "append-review-post", row: POST_ROW }), {
        status: "applied",
      });
      assert.deepEqual(h.session.reviewPosts(), [POST_ROW]);
    } finally {
      h.dispose();
    }
  });

  test(`${backing.label}: extra fields on sound ledger rows are narrowed out by the append pre-read`, () => {
    const h = backing.harness("RID", {
      reviewPosts: [{ pr: 41, event: "comment", at: "t0", extra: "junk" }],
    });
    try {
      assert.deepEqual(h.session.apply({ kind: "append-review-post", row: POST_ROW }), {
        status: "applied",
      });
      assert.deepEqual(h.session.reviewPosts(), [{ pr: 41, event: "comment", at: "t0" }, POST_ROW]);
    } finally {
      h.dispose();
    }
  });
}

// --- seam-level fork/reload reconstruction (branch backing only: the persisted branch IS the
// --- reconstruction source; the memory backing has no branch to reopen) --------------------------

test("branch: a reopen over a fork-appended branch derives the child identity and isolates artifacts", () => {
  // The reload/fork shape: the seam re-derives everything from the persisted branch content,
  // never from in-memory state. A fork entry re-keys run identity; the parent's artifact
  // pointers now belong to a foreign run and read `absent` (designed isolation, silent).
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-fork-"));
  try {
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const parent = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(parent.runId, "RID");
    assert.equal(parent.writeArtifact("draft.json", "parent bytes").status, "applied");

    // The fork arm appends the derived identity (predecessor + child run_id) to the SAME branch.
    branch.push(stateEntry({ run_id: "RID.1", predecessor: "RID" }));

    // A fresh open over the same persisted branch reconstructs the CHILD identity.
    const child = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(child.runId, "RID.1");
    assert.deepEqual(child.readArtifact("draft.json"), { status: "absent" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: a reload-shaped reopen reconstructs runId, claims, and activeObjective", () => {
  // The reload shape: a fresh session object over the same persisted branch (no in-memory
  // carry-over) rebuilds every named read from branch content alone.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-reload-"));
  try {
    const branch: unknown[] = [
      stateEntry({ run_id: "RID", mode: "read-only" }),
      stateEntry({ objective_node_claim: CLAIM }),
      stateEntry({ active_objective: "7" }),
    ];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const first = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(first.writeArtifact("draft.json", "v1").status, "applied");

    const reopened = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(reopened.runId, "RID");
    assert.deepEqual(reopened.nodeClaim(), CLAIM);
    assert.equal(reopened.activeObjective(), "7");
    assert.deepEqual(reopened.readArtifact("draft.json"), { status: "found", content: "v1" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: activeObjective() is fail-open — malformed state and a throwing branch read null", () => {
  // The read's contract includes the boundary error paths: a non-string/blank rebuilt value
  // and a THROWING `getBranch()` must both read null (never a throw to the caller).
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-fail-open-"));
  try {
    const sink: EntrySink = { appendEntry: () => {} };
    for (const malformed of [7, "", { id: "7" }, ["7"], null]) {
      const branch: unknown[] = [
        stateEntry({ run_id: "RID" }),
        stateEntry({ active_objective: malformed }),
      ];
      const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
      assert.equal(session.activeObjective(), null, JSON.stringify(malformed));
    }
    const throwing = openBranchWorkflowSession(sink, {
      cwd,
      sessionManager: {
        getBranch(): unknown[] {
          throw new Error("adversarial branch read");
        },
      },
      hasUI: false,
      ui: { notify() {} },
    });
    assert.equal(throwing.activeObjective(), null, "a throwing branch read is fail-open");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("reviewPostsOf: tolerant re-narrow — malformed rows drop, order preserved", () => {
  assert.deepEqual(reviewPostsOf(undefined), []);
  assert.deepEqual(reviewPostsOf("junk"), []);
  const rows = reviewPostsOf([
    { pr: 41, event: "comment", at: "t1" },
    { pr: "42", event: "comment", at: "t2" }, // malformed: dropped
    { pr: 43, event: "request-changes", at: "t3" },
  ]);
  assert.deepEqual(rows, [
    { pr: 41, event: "comment", at: "t1" },
    { pr: 43, event: "request-changes", at: "t3" },
  ]);
});

test("branch: reviewPosts() is fail-open — malformed rows drop; a throwing branch reads []", () => {
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-review-posts-"));
  try {
    const sink: EntrySink = { appendEntry: () => {} };
    const branch: unknown[] = [
      stateEntry({ run_id: "RID" }),
      stateEntry({ review_posts: [{ pr: 41, event: "comment", at: "t1" }, "junk", { pr: 1.5 }] }),
    ];
    const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.deepEqual(session.reviewPosts(), [{ pr: 41, event: "comment", at: "t1" }]);
    const throwing = openBranchWorkflowSession(sink, {
      cwd,
      sessionManager: {
        getBranch(): unknown[] {
          throw new Error("adversarial branch read");
        },
      },
      hasUI: false,
      ui: { notify() {} },
    });
    assert.deepEqual(throwing.reviewPosts(), [], "a throwing branch read is fail-open");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: append-review-post FAILS CLOSED when the prior ledger cannot be rebuilt", () => {
  // The read-modify-write asymmetry: the public reviewPosts() read stays fail-open (above),
  // but the append path must never treat a throwing branch as an empty prior ledger — a
  // successful append over that would LWW-erase every earlier confirmed post and let the
  // resume guard permit duplicate GitHub reviews.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-review-posts-closed-"));
  try {
    const appends: unknown[] = [];
    const sink: EntrySink = {
      appendEntry: (customType, data) => appends.push({ customType, data }),
    };
    const throwing = openBranchWorkflowSession(sink, {
      cwd,
      sessionManager: {
        getBranch(): unknown[] {
          throw new Error("adversarial branch read");
        },
      },
      hasUI: false,
      ui: { notify() {} },
    });
    const result = throwing.apply({ kind: "append-review-post", row: POST_ROW });
    assert.equal(result.status, "rejected");
    assert.ok(
      result.status === "rejected" &&
        /refusing to append over an unknown ledger/.test(result.problem),
    );
    assert.equal(appends.length, 0, "the refusal lands before any append effect");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: the link-plan-ref pre-read is deliberately un-caught — a throwing rebuild propagates", () => {
  // Unlike the fail-open named reads, the link dedupe must never treat an unreadable branch as
  // "no current ref": a rebuild failure propagates to the caller and nothing is appended.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-link-throws-"));
  try {
    const appends: unknown[] = [];
    const sink: EntrySink = {
      appendEntry: (customType, data) => appends.push({ customType, data }),
    };
    const throwing = openBranchWorkflowSession(sink, {
      cwd,
      sessionManager: {
        getBranch(): unknown[] {
          throw new Error("adversarial branch read");
        },
      },
      hasUI: false,
      ui: { notify() {} },
    });
    assert.throws(
      () => throwing.apply({ kind: "link-plan-ref", ref: planRef("42") }),
      /adversarial branch read/,
    );
    assert.equal(appends.length, 0, "the exception propagates before any append effect");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: the persisted pointer keeps the full five-field wire shape (contracts §8.3)", () => {
  // The receipt deliberately narrows what RESULTS carry — but the PERSISTED `session_artifacts`
  // entry stays the cross-plane five-field pointer. Pin the raw rebuilt map value so the engine
  // can never silently drop or rename a wire field.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-wire-shape-"));
  try {
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(session.writeArtifact("draft.json", "v1").status, "applied");
    const raw = rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0])
      .session_artifacts?.["draft.json"];
    assert.ok(typeof raw === "object" && raw !== null, "a pointer object persisted");
    const pointer = raw as Record<string, unknown>;
    assert.deepEqual(Object.keys(pointer).sort(), ["at", "digest", "name", "path", "run_id"]);
    assert.equal(pointer.run_id, "RID");
    assert.equal(pointer.name, "draft.json");
    assert.equal(pointer.path, relative(cwd, join(sessionDataDir(cwd, "RID"), "draft.json")));
    assert.equal(pointer.digest, digestSessionData("v1"));
    assert.ok(
      typeof pointer.at === "string" && !Number.isNaN(Date.parse(pointer.at)),
      "at is a parseable timestamp",
    );
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: nodeClaim() is fail-open — malformed persisted claims and a throwing branch read null", () => {
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-claim-fail-open-"));
  try {
    const sink: EntrySink = { appendEntry: () => {} };
    for (const malformed of [null, { objective: 7, node: "1.2" }, { objective: "7", node: "" }]) {
      const branch: unknown[] = [
        stateEntry({ run_id: "RID" }),
        stateEntry({ objective_node_claim: malformed }),
      ];
      const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
      assert.equal(session.nodeClaim(), null, JSON.stringify(malformed));
    }
    const throwing = openBranchWorkflowSession(sink, {
      cwd,
      sessionManager: {
        getBranch(): unknown[] {
          throw new Error("adversarial branch read");
        },
      },
      hasUI: false,
      ui: { notify() {} },
    });
    assert.equal(throwing.nodeClaim(), null, "a throwing branch read is fail-open");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: a malformed persisted pointer reads absent; a write proceeds and replaces it", () => {
  // Branch data is cast, not validated: a malformed session entry can put null (or any
  // non-pointer value) where a pointer belongs. The engine's decode treats it as "no pointer":
  // the read classifies `absent`, and the write's unchanged probe fails so the write proceeds
  // and REPLACES the junk with a sound pointer.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-malformed-"));
  try {
    for (const malformed of [null, "junk", 7, { run_id: 42 }, { run_id: "RID" }]) {
      const branch: unknown[] = [
        stateEntry({ run_id: "RID" }),
        stateEntry({ session_artifacts: { "draft.json": malformed } }),
      ];
      const sink: EntrySink = {
        appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
      };
      const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
      assert.deepEqual(
        session.readArtifact("draft.json"),
        { status: "absent" },
        `read classifies (${JSON.stringify(malformed)})`,
      );
      const written = session.writeArtifact("draft.json", "fresh");
      assert.equal(written.status, "applied", `write proceeds (${JSON.stringify(malformed)})`);
      const repaired = soundPointer(
        rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0])
          .session_artifacts?.["draft.json"],
      );
      assert.equal(repaired?.run_id, "RID", "the malformed pointer was replaced by a sound one");
      rmSync(join(cwd, ".perk"), { recursive: true, force: true });
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: a shape-sound pointer with junk path/name/at yields a fully RE-DERIVED receipt", () => {
  // The unchanged arm must never leak persisted junk through the receipt: only run_id + digest
  // are validated, so path/name/at can carry any JSON value — the receipt re-derives all three
  // of its fields and the junk stays unobservable.
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-junk-pointer-"));
  try {
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(session.writeArtifact("draft.json", "same bytes").status, "applied");
    // Doctor the persisted pointer: digest still matches the stored bytes; everything else junk.
    branch.push(
      stateEntry({
        session_artifacts: {
          "draft.json": {
            run_id: "RID",
            digest: digestSessionData("same bytes"),
            path: 123,
            name: 99,
            at: {},
          },
        },
      }),
    );
    const rewrite = session.writeArtifact("draft.json", "same bytes");
    assert.equal(rewrite.status, "unchanged");
    assert.ok(rewrite.status === "unchanged");
    assert.equal(typeof rewrite.receipt.path, "string");
    assert.deepEqual(rewrite.receipt, {
      runId: "RID",
      path: relative(cwd, join(sessionDataDir(cwd, "RID"), "draft.json")),
      digest: digestSessionData("same bytes"),
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: untrusted pointer.path is never dereferenced — validation uses the derived path only", () => {
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-hostile-path-"));
  try {
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(session.writeArtifact("draft.md", "real").status, "applied");
    // …and a foreign file elsewhere that a malicious pointer.path points at.
    const foreign = join(cwd, "foreign.md");
    writeFileSync(foreign, "foreign", "utf8");
    branch.push(
      stateEntry({
        session_artifacts: {
          "draft.md": {
            run_id: "RID",
            name: "draft.md",
            path: foreign, // absolute, hostile — must be ignored
            digest: digestSessionData("real"),
            at: new Date().toISOString(),
          },
        },
      }),
    );
    // The derived file is read (and digest-validated), never the foreign one.
    assert.deepEqual(session.readArtifact("draft.md"), { status: "found", content: "real" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: sibling pointers survive — each append carries the whole merged map", () => {
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-siblings-"));
  try {
    const branch: unknown[] = [stateEntry({ run_id: "RID" })];
    const sink: EntrySink = {
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    };
    const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    assert.equal(session.writeArtifact("a.md", "alpha").status, "applied");
    assert.equal(session.writeArtifact("b.md", "beta").status, "applied");
    const map =
      rebuildWorkflowState(branch as Parameters<typeof rebuildWorkflowState>[0])
        .session_artifacts ?? {};
    assert.deepEqual(Object.keys(map).sort(), ["a.md", "b.md"]);
    assert.deepEqual(session.readArtifact("a.md"), { status: "found", content: "alpha" });
    assert.deepEqual(session.readArtifact("b.md"), { status: "found", content: "beta" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: concurrent sessions — run_id keying isolates pointers and dirs", () => {
  const cwd = mkdtempSync(join(tmpdir(), "workflow-session-concurrent-"));
  try {
    const branchA: unknown[] = [stateEntry({ run_id: "A" })];
    const branchB: unknown[] = [stateEntry({ run_id: "B" })];
    const sinkFor = (branch: unknown[]): EntrySink => ({
      appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
    });
    const a = openBranchWorkflowSession(sinkFor(branchA), reportableCtx(cwd, branchA));
    const b = openBranchWorkflowSession(sinkFor(branchB), reportableCtx(cwd, branchB));
    assert.equal(a.writeArtifact("a.md", "from A").status, "applied");
    assert.equal(b.writeArtifact("b.md", "from B").status, "applied");
    assert.deepEqual(a.readArtifact("a.md"), { status: "found", content: "from A" });
    assert.deepEqual(b.readArtifact("b.md"), { status: "found", content: "from B" });
    assert.deepEqual(a.readArtifact("b.md"), { status: "absent" }); // silent: no pointer on A's branch
    assert.deepEqual(b.readArtifact("a.md"), { status: "absent" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("branch: a read-back miss reports LOUDLY under each change's seam-owned scope", () => {
  // The seam owns each append's report scope (the caller passes none): a headless read-back
  // miss must surface as `perk: <scope> — <failure>` on stderr — not stay quiet, and not
  // drift to another scope. Captured (not silenced) so the exact line per change is pinned:
  // record-node-claim → objective-plan, clear-node-claim → plan-save (the existing seam
  // warning the clearing path emits), link-objective → objective-save.
  const cases: {
    seed: Record<string, unknown> | null;
    change: Parameters<WorkflowSession["apply"]>[0];
    expected: string;
  }[] = [
    {
      seed: null,
      change: { kind: "record-node-claim", claim: CLAIM },
      expected: "perk: objective-plan — objective_node_claim read-back failed for #7 node 1.1",
    },
    {
      seed: { objective_node_claim: CLAIM },
      change: { kind: "clear-node-claim", claim: CLAIM },
      expected: "perk: plan-save — objective_node_claim clear read-back failed for node 1.1",
    },
    {
      seed: null,
      change: { kind: "link-objective", objective: "7" },
      expected: "perk: objective-save — active_objective read-back failed for #7",
    },
    {
      seed: null,
      change: { kind: "record-pr-review", record: PR_REVIEW_RECORD },
      expected: "perk: pr-review — last_pr_review read-back failed",
    },
    {
      seed: null,
      change: { kind: "record-review", record: REVIEW_RECORD },
      expected: "perk: review — last_review read-back failed",
    },
    {
      seed: null,
      change: { kind: "append-review-post", row: POST_ROW },
      expected: "perk: review — review_posts read-back failed",
    },
    {
      seed: null,
      change: { kind: "record-review-batch", record: REVIEW_BATCH_RECORD },
      expected: "perk: address — last_review_batch read-back failed",
    },
  ];
  for (const { seed, change, expected } of cases) {
    const cwd = mkdtempSync(join(tmpdir(), "workflow-session-scope-"));
    try {
      const branch: unknown[] = [stateEntry({ run_id: "RID" })];
      if (seed !== null) branch.push(stateEntry(seed));
      let dropAppends = false;
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
          if (dropAppends) return; // dropped on the floor — the read-back proof misses
          branch.push({ type: "custom", customType, data });
        },
      };
      const session = openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
      const lines: string[] = [];
      const original = console.error;
      console.error = (...args: unknown[]) => {
        lines.push(args.map(String).join(" "));
      };
      let result: ReturnType<typeof session.apply>;
      try {
        dropAppends = true;
        result = session.apply(change);
      } finally {
        console.error = original;
      }
      assert.equal(result.status, "unverified", expected);
      assert.deepEqual(lines, [expected]);
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  }
});
