// The objective planning feature ops over the memory session + deterministic fake backends:
// the completion-audit gate matrix (incl. the length boundary), the no-change refusal, the
// warm claim-carrier maintenance through the seam (record on planning / clear on other
// statuses / untouched on pr-or-description-only, with the claimChange arms via the memory
// knobs), the thin reconcile/add-node passthroughs, and the reconcile three-tier resolution.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import {
  addObjectiveNode,
  isNonTrivialAudit,
  MIN_AUDIT_LENGTH,
  type ObjectiveNodeBackend,
  type ObjectiveReconcileBackend,
  reconcileObjective,
  resolveReconcileObjective,
  transitionObjectiveNode,
} from "./planning.ts";

const AUDIT = "Requirement: retry on 5xx → evidence: PR #99 merged, test_retry passing.";

/** A deterministic node backend recording its requests. */
function fakeNodeBackend(result?: Awaited<ReturnType<ObjectiveNodeBackend["transition"]>>): {
  backend: ObjectiveNodeBackend;
  requests: unknown[];
} {
  const requests: unknown[] = [];
  return {
    backend: {
      transition: (req) => {
        requests.push(req);
        return Promise.resolve(result ?? { status: "ok", commentUpdated: true });
      },
    },
    requests,
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

// --- the completion-audit gate --------------------------------------------------------------

test("isNonTrivialAudit: the pinnable predicate (39/40-char boundary, trim, mistyped)", () => {
  assert.equal(isNonTrivialAudit("x".repeat(MIN_AUDIT_LENGTH)), true, "exactly 40 passes");
  assert.equal(isNonTrivialAudit("x".repeat(MIN_AUDIT_LENGTH - 1)), false, "39 refuses");
  assert.equal(isNonTrivialAudit(`  ${"x".repeat(MIN_AUDIT_LENGTH - 1)}  `), false, "trim first");
  assert.equal(isNonTrivialAudit(undefined), false);
  assert.equal(isNonTrivialAudit(7), false);
});

test("transition: done without a non-trivial audit refuses audit_required; backend untouched", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeNodeBackend();
  for (const audit of [undefined, "too short", "x".repeat(MIN_AUDIT_LENGTH - 1)]) {
    const outcome = await transitionObjectiveNode(
      { objective: "7", node: "1.2", status: "done", ...(audit !== undefined ? { audit } : {}) },
      { backend, session },
    );
    assert.deepEqual(outcome, {
      status: "failed",
      message:
        `setting a node to "done" requires a completion audit (a requirement→evidence mapping of ` +
        `at least ${MIN_AUDIT_LENGTH} characters) — confirm the work actually landed first.`,
      errorType: "audit_required",
    });
  }
  assert.equal(requests.length, 0);
});

test("transition: done WITH a non-trivial audit passes (the audit never reaches the backend)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeNodeBackend();
  const outcome = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "done", audit: AUDIT },
    { backend, session },
  );
  assert.equal(outcome.status, "ok");
  assert.deepEqual(requests, [{ objective: "7", node: "1.2", status: "done" }]);
});

test("transition: neither status nor pr nor description refuses bad_input", async () => {
  const { backend, requests } = fakeNodeBackend();
  const outcome = await transitionObjectiveNode(
    { objective: "7", node: "1.2" },
    { backend, session: openMemoryWorkflowSession({ runId: "RID" }) },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "objective_node needs a `status`, a `pr`, or a `description` to change",
    errorType: "bad_input",
  });
  assert.equal(requests.length, 0);
});

test("transition: a failed backend passes through; the claim carrier is untouched", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend } = fakeNodeBackend({
    status: "failed",
    message: "perk objective node failed",
    errorType: "door_failed",
  });
  const outcome = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "planning" },
    { backend, session },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "perk objective node failed",
    errorType: "door_failed",
  });
  assert.equal(session.nodeClaim(), null, "no claim recorded off a failed transition");
});

// --- the warm claim-carrier maintenance (through the seam) ----------------------------------

test("transition: planning records the claim; an idempotent re-claim is unchanged", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend } = fakeNodeBackend();
  const first = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "planning" },
    { backend, session },
  );
  assert.equal(first.status === "ok" && first.claimChange?.status, "applied");
  assert.deepEqual(session.nodeClaim(), { objective: "7", node: "1.2" });

  // The idempotent re-claim (delta 2): the re-append "refresh" carries no semantic payload.
  const again = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "planning" },
    { backend, session },
  );
  assert.equal(again.status === "ok" && again.claimChange?.status, "unchanged");
});

test("transition: a non-planning status clears the MATCHING claim only", async () => {
  const matching = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.2" },
  });
  const { backend } = fakeNodeBackend();
  const cleared = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "in_progress" },
    { backend, session: matching },
  );
  assert.equal(cleared.status === "ok" && cleared.claimChange?.status, "applied");
  assert.equal(matching.nodeClaim(), null);

  // An unrelated claim is never clobbered (the seam's both-field match ⇒ unchanged).
  const unrelated = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "9", node: "1.2" },
  });
  const kept = await transitionObjectiveNode(
    { objective: "7", node: "1.2", status: "blocked" },
    { backend, session: unrelated },
  );
  assert.equal(kept.status === "ok" && kept.claimChange?.status, "unchanged");
  assert.deepEqual(unrelated.nodeClaim(), { objective: "9", node: "1.2" });
});

test("transition: pr-only / description-only leave the carrier untouched (claimChange null)", async () => {
  const session = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.2" },
  });
  const { backend, requests } = fakeNodeBackend();
  const prOnly = await transitionObjectiveNode(
    { objective: "7", node: "1.2", pr: "#42" },
    { backend, session },
  );
  assert.equal(prOnly.status === "ok" && prOnly.claimChange, null);
  const descOnly = await transitionObjectiveNode(
    { objective: "7", node: "1.2", description: "sharper scope" },
    { backend, session },
  );
  assert.equal(descOnly.status === "ok" && descOnly.claimChange, null);
  assert.deepEqual(session.nodeClaim(), { objective: "7", node: "1.2" }, "carrier untouched");
  assert.deepEqual(requests, [
    { objective: "7", node: "1.2", pr: "#42" },
    { objective: "7", node: "1.2", description: "sharper scope" },
  ]);
});

test("transition: claimChange rides the seam's unverified/rejected arms verbatim", async () => {
  const unverified = openMemoryWorkflowSession({ runId: "RID" });
  unverified.failNextApplyVerification();
  const { backend } = fakeNodeBackend();
  const first = await quietly(() =>
    transitionObjectiveNode(
      { objective: "7", node: "1.2", status: "planning" },
      { backend, session: unverified },
    ),
  );
  assert.equal(first.status, "ok", "a failed claim append never fails the tool result");
  assert.equal(first.status === "ok" && first.claimChange?.status, "unverified");

  const rejected = openMemoryWorkflowSession({ runId: "RID" });
  rejected.failNextApply();
  const second = await quietly(() =>
    transitionObjectiveNode(
      { objective: "7", node: "1.2", status: "planning" },
      { backend, session: rejected },
    ),
  );
  assert.equal(second.status === "ok" && second.claimChange?.status, "rejected");
  assert.equal(rejected.nodeClaim(), null);
});

// --- reconcile / add-node (thin typed passthroughs) ------------------------------------------

function fakeReconcileBackend(): {
  backend: ObjectiveReconcileBackend;
  reconciles: unknown[];
  added: unknown[];
} {
  const reconciles: unknown[] = [];
  const added: unknown[] = [];
  return {
    backend: {
      reconcile: (req) => {
        reconciles.push(req);
        return Promise.resolve({ status: "ok", updated: true });
      },
      addNode: (req) => {
        added.push(req);
        return Promise.resolve({ status: "ok", node: "2.4", commentUpdated: false });
      },
    },
    reconciles,
    added,
  };
}

test("reconcileObjective / addObjectiveNode: typed passthrough — requests verbatim, results verbatim", async () => {
  const { backend, reconciles, added } = fakeReconcileBackend();
  assert.deepEqual(await reconcileObjective({ objective: "7", prose: "New prose." }, { backend }), {
    status: "ok",
    updated: true,
  });
  assert.deepEqual(reconciles, [{ objective: "7", prose: "New prose." }]);

  const input = {
    objective: "7",
    phase: 2,
    description: "harden retries",
    status: "pending" as const,
    slug: "retries",
    depends_on: ["2.1"],
    comment: "flagged by the PR",
  };
  assert.deepEqual(await addObjectiveNode(input, { backend }), {
    status: "ok",
    node: "2.4",
    commentUpdated: false,
  });
  assert.deepEqual(added, [input]);
});

test("reconcileObjective / addObjectiveNode: failed backends pass through verbatim", async () => {
  const failing: ObjectiveReconcileBackend = {
    reconcile: () =>
      Promise.resolve({ status: "failed", message: "no such objective", errorType: "not_found" }),
    addNode: () =>
      Promise.resolve({ status: "failed", message: "stacked tail only", errorType: "bad_state" }),
  };
  assert.deepEqual(await reconcileObjective({ objective: "7", prose: "p" }, { backend: failing }), {
    status: "failed",
    message: "no such objective",
    errorType: "not_found",
  });
  assert.deepEqual(
    await addObjectiveNode({ objective: "7", phase: 1, description: "d" }, { backend: failing }),
    { status: "failed", message: "stacked tail only", errorType: "bad_state" },
  );
});

// --- resolveReconcileObjective (the three tiers) ----------------------------------------------

test("resolveReconcileObjective: explicit → active → plan-ref → null", () => {
  assert.equal(
    resolveReconcileObjective({ explicit: "9", active: "7", planRefObjective: "5" }),
    "9",
  );
  assert.equal(
    resolveReconcileObjective({ explicit: null, active: "7", planRefObjective: "5" }),
    "7",
  );
  assert.equal(
    resolveReconcileObjective({ explicit: null, active: null, planRefObjective: "5" }),
    "5",
  );
  assert.equal(
    resolveReconcileObjective({ explicit: null, active: null, planRefObjective: null }),
    null,
  );
});
