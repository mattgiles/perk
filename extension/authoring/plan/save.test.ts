// Direct feature tests for savePlan + planApprovalSave — memory session, deterministic fake
// PlanBackend (the port-admission rule: one production adapter, one useful fake), fake gate; no
// Pi, no cold door. The linkage/claimClear arms are the session seam's own WorkflowChangeResult
// values passed through verbatim — every arm is pinned here (the adapter's rendering ignores
// them by design).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type MemoryWorkflowSession,
  openMemoryWorkflowSession,
} from "../../session/memoryWorkflowSession.ts";
import type { PlanRef } from "../../substrate/cache.ts";
import { revisePlanDraft } from "./draft.ts";
import {
  type ObjectiveNodeLink,
  type PlanBackend,
  type PlanBackendSaveResult,
  type PlanGate,
  type PlanSaveDeps,
  planApprovalSave,
  savePlan,
} from "./save.ts";

const PLAN = "# A plan\n\n## Steps\n\n1. Do the thing.\n";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
  base: null,
};

function savedResult(nodeLink: ObjectiveNodeLink | null = null): PlanBackendSaveResult {
  return { status: "saved", ref: REF, existed: false, updated: false, cached: true, nodeLink };
}

/** A deterministic backend fake recording requests and returning a canned result. */
function fakeBackend(result?: PlanBackendSaveResult): PlanBackend & {
  requests: Parameters<PlanBackend["save"]>[0][];
} {
  const backend = {
    requests: [] as Parameters<PlanBackend["save"]>[0][],
    async save(req: Parameters<PlanBackend["save"]>[0]) {
      backend.requests.push(req);
      return result ?? savedResult();
    },
  };
  return backend;
}

/** A gate fake recording exits; `active` is the isActive snapshot. */
function fakeGate(active: boolean): PlanGate & { exits: number } {
  const gate = {
    exits: 0,
    isActive: () => active,
    exit() {
      gate.exits += 1;
    },
  };
  return gate;
}

function depsFor(
  session: MemoryWorkflowSession,
  backend: PlanBackend,
  opts: { title?: string | null } = {},
): PlanSaveDeps & { captured: number; titled: string[] } {
  const deps = {
    session,
    backend,
    captured: 0,
    titled: [] as string[],
    async generateTitle(plan: string) {
      deps.titled.push(plan);
      return opts.title === undefined ? "A generated title" : opts.title;
    },
    capturePlanningPointer() {
      deps.captured += 1;
    },
  };
  return deps;
}

// ------------------------------------------------------------------------------------ savePlan

test("savePlan: a blank plan refuses invalid_input before the backend", async () => {
  const backend = fakeBackend();
  const deps = depsFor(openMemoryWorkflowSession({ runId: "RID" }), backend);
  const outcome = await savePlan({ plan: "  \n" }, deps);
  assert.deepEqual(outcome, {
    status: "failed",
    message: "no plan markdown to save (propose a plan first)",
    errorType: "invalid_input",
  });
  assert.equal(backend.requests.length, 0);
  assert.equal(deps.titled.length, 0, "no title generation for a refused save");
});

test("savePlan: an explicit title wins outright — generateTitle is never invoked", async () => {
  const backend = fakeBackend();
  const deps = depsFor(openMemoryWorkflowSession({ runId: "RID" }), backend);
  await savePlan({ plan: PLAN, title: "  Explicit title  " }, deps);
  assert.equal(backend.requests[0]?.title, "Explicit title");
  assert.equal(deps.titled.length, 0);
});

test("savePlan: no explicit title → generateTitle; null falls back to the cold door (omitted)", async () => {
  const generated = fakeBackend();
  const genDeps = depsFor(openMemoryWorkflowSession({ runId: "RID" }), generated);
  await savePlan({ plan: PLAN }, genDeps);
  assert.equal(generated.requests[0]?.title, "A generated title");
  assert.deepEqual(genDeps.titled, [PLAN.trim()], "the trimmed plan fed the title model");

  const fallback = fakeBackend();
  const nullDeps = depsFor(openMemoryWorkflowSession({ runId: "RID" }), fallback, { title: null });
  await savePlan({ plan: PLAN }, nullDeps);
  assert.equal(fallback.requests[0]?.title, undefined, "null ⇒ omit — the cold door derives");
});

test("savePlan: claim recovery fills BOTH link params when both are absent", async () => {
  const backend = fakeBackend(
    savedResult({ linked: true, node: "1.2", status: "in_progress", error: null }),
  );
  const session = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.2" },
  });
  const outcome = await savePlan({ plan: PLAN }, depsFor(session, backend));
  assert.equal(backend.requests[0]?.objectiveId, "7");
  assert.equal(backend.requests[0]?.nodeId, "1.2");
  // The full-identity match clears the claim.
  assert.equal(outcome.status === "saved" ? outcome.claimClear?.status : null, "applied");
  assert.equal(session.nodeClaim(), null, "the matching claim was cleared");
});

test("savePlan: ANY explicit link param wins outright — never mixed with the claim", async () => {
  const objOnly = fakeBackend();
  const objSession = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.2" },
  });
  await savePlan({ plan: PLAN, objectiveId: "9" }, depsFor(objSession, objOnly));
  assert.equal(objOnly.requests[0]?.objectiveId, "9");
  assert.equal(objOnly.requests[0]?.nodeId, undefined, "the claim's node never rides along");

  const nodeOnly = fakeBackend();
  const nodeSession = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.2" },
  });
  await savePlan({ plan: PLAN, nodeId: "2.1" }, depsFor(nodeSession, nodeOnly));
  assert.equal(nodeOnly.requests[0]?.objectiveId, undefined);
  assert.equal(nodeOnly.requests[0]?.nodeId, "2.1");
});

test("savePlan: a failed backend save passes through — no pointer capture, no linkage", async () => {
  const backend = fakeBackend({
    status: "failed",
    message: "gh exploded",
    errorType: "github_error",
  });
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const deps = depsFor(session, backend);
  const outcome = await savePlan({ plan: PLAN }, deps);
  assert.deepEqual(outcome, {
    status: "failed",
    message: "gh exploded",
    errorType: "github_error",
  });
  assert.equal(deps.captured, 0);
  assert.equal(session.linkedPlanRef(), null);
});

test("savePlan: a saved outcome captures the pointer and links the session (linkage applied)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const deps = depsFor(session, fakeBackend());
  const outcome = await savePlan({ plan: PLAN, source: "plan-draft", paramMismatch: true }, deps);
  assert.equal(outcome.status, "saved");
  if (outcome.status !== "saved") return;
  assert.equal(deps.captured, 1);
  assert.deepEqual(outcome.linkage, { status: "applied" });
  assert.deepEqual(session.linkedPlanRef(), REF);
  assert.equal(outcome.claimClear, null, "no node link ⇒ claim clear never attempted");
  assert.equal(outcome.source, "plan-draft");
  assert.equal(outcome.paramMismatch, true);
  assert.equal(outcome.cached, true);
});

test("savePlan: linkage arms — unchanged (same ref), rejected and unverified (seam knobs)", async () => {
  const unchanged = openMemoryWorkflowSession({ runId: "RID", activePlanRef: REF });
  const unchangedOutcome = await savePlan({ plan: PLAN }, depsFor(unchanged, fakeBackend()));
  assert.equal(
    unchangedOutcome.status === "saved" ? unchangedOutcome.linkage?.status : null,
    "unchanged",
  );

  const rejected = openMemoryWorkflowSession({ runId: "RID" });
  rejected.failNextApply();
  const rejectedOutcome = await savePlan({ plan: PLAN }, depsFor(rejected, fakeBackend()));
  assert.equal(
    rejectedOutcome.status === "saved" ? rejectedOutcome.linkage?.status : null,
    "rejected",
  );

  const unverified = openMemoryWorkflowSession({ runId: "RID" });
  unverified.failNextApplyVerification();
  const unverifiedOutcome = await savePlan({ plan: PLAN }, depsFor(unverified, fakeBackend()));
  assert.equal(
    unverifiedOutcome.status === "saved" ? unverifiedOutcome.linkage?.status : null,
    "unverified",
  );
  // A linkage failure never fails the save — the plan genuinely persisted.
  assert.equal(unverifiedOutcome.status, "saved");
});

test("savePlan: claimClear arms — rejected/unverified via the seam knobs (linkage unchanged)", async () => {
  const nodeLink: ObjectiveNodeLink = {
    linked: true,
    node: "1.2",
    status: "in_progress",
    error: null,
  };
  // Seed the active ref equal so linkage short-circuits `unchanged` WITHOUT consuming the
  // one-shot failure knob — the knob then hits the claim clear.
  const rejected = openMemoryWorkflowSession({
    runId: "RID",
    activePlanRef: REF,
    nodeClaim: { objective: "7", node: "1.2" },
  });
  rejected.failNextApply();
  const rejectedOutcome = await savePlan(
    { plan: PLAN, objectiveId: "7", nodeId: "1.2" },
    depsFor(rejected, fakeBackend(savedResult(nodeLink))),
  );
  assert.equal(
    rejectedOutcome.status === "saved" ? rejectedOutcome.claimClear?.status : null,
    "rejected",
  );
  assert.deepEqual(rejected.nodeClaim(), { objective: "7", node: "1.2" }, "nothing landed");

  const unverified = openMemoryWorkflowSession({
    runId: "RID",
    activePlanRef: REF,
    nodeClaim: { objective: "7", node: "1.2" },
  });
  unverified.failNextApplyVerification();
  const unverifiedOutcome = await savePlan(
    { plan: PLAN, objectiveId: "7", nodeId: "1.2" },
    depsFor(unverified, fakeBackend(savedResult(nodeLink))),
  );
  assert.equal(
    unverifiedOutcome.status === "saved" ? unverifiedOutcome.claimClear?.status : null,
    "unverified",
  );
});

test("savePlan: the claim-identity matrix — full match clears; partial identity never clobbers", async () => {
  const nodeLink: ObjectiveNodeLink = {
    linked: true,
    node: "1.1",
    status: "in_progress",
    error: null,
  };
  // Same node, DIFFERENT objective: objective A's standing 1.1 claim must survive a save
  // linked to objective B's 1.1 (the delta-3 bug fix).
  const crossObjective = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "A", node: "1.1" },
  });
  const crossOutcome = await savePlan(
    { plan: PLAN, objectiveId: "B", nodeId: "1.1" },
    depsFor(crossObjective, fakeBackend(savedResult(nodeLink))),
  );
  assert.equal(crossOutcome.status === "saved" ? crossOutcome.claimClear : undefined, null);
  assert.deepEqual(crossObjective.nodeClaim(), { objective: "A", node: "1.1" });

  // No standing claim at all: nothing to clear.
  const noClaim = openMemoryWorkflowSession({ runId: "RID" });
  const noClaimOutcome = await savePlan(
    { plan: PLAN, objectiveId: "7", nodeId: "1.1" },
    depsFor(noClaim, fakeBackend(savedResult(nodeLink))),
  );
  assert.equal(noClaimOutcome.status === "saved" ? noClaimOutcome.claimClear : undefined, null);

  // A node link that did NOT commit (linked: false) never clears.
  const failedLink = openMemoryWorkflowSession({
    runId: "RID",
    nodeClaim: { objective: "7", node: "1.1" },
  });
  const failedLinkOutcome = await savePlan(
    { plan: PLAN, objectiveId: "7", nodeId: "1.1" },
    depsFor(
      failedLink,
      fakeBackend(
        savedResult({ linked: false, node: "1.1", status: null, error: "advance failed" }),
      ),
    ),
  );
  assert.equal(
    failedLinkOutcome.status === "saved" ? failedLinkOutcome.claimClear : undefined,
    null,
  );
  assert.deepEqual(failedLink.nodeClaim(), { objective: "7", node: "1.1" });
});

test("savePlan: the identity-less arm — backend runId null, linkage still applied", async () => {
  const backend = fakeBackend();
  const session = openMemoryWorkflowSession({ runId: null });
  const deps = depsFor(session, backend);
  const outcome = await savePlan({ plan: PLAN }, deps);
  assert.equal(backend.requests[0]?.runId, null, "the adapter omits --run-id downstream");
  assert.equal(deps.captured, 1, "the capture thunk still runs (the carrier no-ops inside)");
  assert.equal(outcome.status === "saved" ? outcome.linkage?.status : null, "applied");
  assert.deepEqual(session.linkedPlanRef(), REF, "workflow-state ops are identity-independent");
});

// ---------------------------------------------------------------------------- planApprovalSave

function approvalDeps(
  session: MemoryWorkflowSession,
  backend: PlanBackend,
  gate: PlanGate,
  transcript?: () => string | null,
) {
  return {
    ...depsFor(session, backend),
    gate,
    ...(transcript !== undefined ? { transcript } : {}),
  };
}

test("planApprovalSave: nothing resolvable → no-plan; gate untouched", async () => {
  const gate = fakeGate(true);
  const outcome = await planApprovalSave(
    approvalDeps(openMemoryWorkflowSession({ runId: "RID" }), fakeBackend(), gate),
  );
  assert.deepEqual(outcome, { status: "no-plan" });
  assert.equal(gate.exits, 0);
});

test("planApprovalSave: the artifact wins; a successful save while read-only exits the gate (D1a)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(revisePlanDraft({ plan: PLAN }, session).status, "revised");
  const gate = fakeGate(true);
  const outcome = await planApprovalSave(
    approvalDeps(session, fakeBackend(), gate, () => "# Scraped — must not win"),
    { reviewedPlan: "# Reviewed fallback — must not win" },
  );
  assert.equal(outcome.status, "saved");
  if (outcome.status !== "saved") return;
  assert.equal(outcome.gateExited, true);
  assert.equal(gate.exits, 1);
  assert.equal(outcome.result.source, "plan-draft");
  assert.equal(outcome.result.paramMismatch, true, "the differing reviewedPlan is flagged");
});

test("planApprovalSave: reviewedPlan is the explicit fallback; transcript is the last resort", async () => {
  const reviewed = await planApprovalSave(
    approvalDeps(openMemoryWorkflowSession({ runId: "RID" }), fakeBackend(), fakeGate(false)),
    { reviewedPlan: "# Reviewed plan" },
  );
  assert.equal(reviewed.status === "saved" ? reviewed.result.source : null, "param");

  const scraped = await planApprovalSave(
    approvalDeps(
      openMemoryWorkflowSession({ runId: "RID" }),
      fakeBackend(),
      fakeGate(false),
      () => "# Scraped plan",
    ),
  );
  assert.equal(scraped.status === "saved" ? scraped.result.source : null, "transcript");
});

test("planApprovalSave: already read-write → saved with gateExited false, no exit", async () => {
  const gate = fakeGate(false);
  const outcome = await planApprovalSave(
    approvalDeps(openMemoryWorkflowSession({ runId: "RID" }), fakeBackend(), gate),
    { reviewedPlan: PLAN },
  );
  assert.equal(outcome.status === "saved" ? outcome.gateExited : null, false);
  assert.equal(gate.exits, 0);
});

test("planApprovalSave: a failed save leaves the gate ON (save-failed, gateExited false)", async () => {
  const gate = fakeGate(true);
  const outcome = await planApprovalSave(
    approvalDeps(
      openMemoryWorkflowSession({ runId: "RID" }),
      fakeBackend({ status: "failed", message: "gh exploded", errorType: "github_error" }),
      gate,
    ),
    { reviewedPlan: PLAN },
  );
  assert.equal(outcome.status, "save-failed");
  if (outcome.status !== "save-failed") return;
  assert.equal(outcome.gateExited, false);
  assert.equal(gate.exits, 0);
  assert.equal(outcome.result.message, "gh exploded");
});

test("planApprovalSave: an explicit title rides through to the backend", async () => {
  const backend = fakeBackend();
  await planApprovalSave(
    approvalDeps(openMemoryWorkflowSession({ runId: "RID" }), backend, fakeGate(false)),
    { reviewedPlan: PLAN, title: "Chosen title" },
  );
  assert.equal(backend.requests[0]?.title, "Chosen title");
});
