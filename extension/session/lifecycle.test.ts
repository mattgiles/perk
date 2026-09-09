// The pure OWNING suite for `session/lifecycle.ts`: the identity arms (claim / unclaimed / fork /
// adopt / mint / keep), the pre-gate tool-scope slice, the post-gate facts (the lazy linkage
// reconciliation with its capture/feedback inputs) and the navigation twin — every behavior
// pinned exactly once here, over ONE memory `SessionStateStore` fake and recording ports, with
// REAL identities driving the facts (one `startup()` runs identity → scope → facts as production
// does). `extension/sessionLifecycle.test.ts` proves only the composition through the real
// wiring; it re-proves no arm.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Handoff, PlanRef } from "../substrate/cache.ts";
import type { Registry } from "../substrate/registry.ts";
import { planRefsEqual, type WorkflowState } from "../substrate/workflowState.ts";
import {
  type EstablishIdentityOutcome,
  establishSessionIdentity,
  refinementHandoffContamination,
  reflectSessionReadOnlyFloor,
  resolveSessionStartFacts,
  type SessionIdentityPorts,
  type SessionStartFactReads,
  type SessionStateStore,
  sessionStartToolScope,
  sessionTreeFacts,
} from "./lifecycle.ts";

// --- fixtures ------------------------------------------------------------------------------------

/** A handoff blob (optionally carrying `stage`/`consumed`/claim fields). */
function handoffBlob(
  runId: string,
  stage?: string,
  opts: { consumed?: boolean; piSessionId?: string; mode?: string } = {},
): Handoff {
  return {
    run_id: runId,
    consumed: opts.consumed ?? false,
    stage,
    mode: opts.mode,
    pi_session_id: opts.piSessionId,
  };
}

function ref(prId: string, extra: Partial<PlanRef> = {}): PlanRef {
  return {
    provider: "github",
    pr_id: prId,
    url: `https://github.com/o/r/issues/${prId}`,
    labels: ["perk:plan"],
    objective_id: null,
    ...extra,
  };
}

/** The observable slice of one verified append (the generic opts, flattened for pins). */
interface RecordedAppend {
  data: WorkflowState;
  field: string;
  expected: unknown;
  scope: string;
  failure: string;
  equals: unknown;
}

type InducedStatus = "rejected" | "unverified";

/**
 * The ONE store fake: a per-field-LWW memory state (undefined never clobbers), every store touch
 * recorded in `calls` (`rebuild` / `append` / `appendVerified:<field>`), every appended payload in
 * `appends`, every verified append's opts in `verified`, and `induce(status)` arming the NEXT
 * verified append to classify as `rejected` (nothing merged) or `unverified` (nothing merged).
 */
function makeStore(initial: WorkflowState[] = []) {
  const state: WorkflowState = {};
  const merge = (data: WorkflowState) => {
    for (const [key, value] of Object.entries(data)) {
      if (value !== undefined) (state as Record<string, unknown>)[key] = value;
    }
  };
  for (const data of initial) merge(data);
  const appends: WorkflowState[] = [];
  const calls: string[] = [];
  const verified: RecordedAppend[] = [];
  let induced: InducedStatus | null = null;
  const store: SessionStateStore = {
    rebuild: () => {
      calls.push("rebuild");
      return { ...state };
    },
    append: (data) => {
      calls.push("append");
      appends.push(data);
      merge(data);
    },
    appendVerified: (opts) => {
      calls.push(`appendVerified:${String(opts.field)}`);
      appends.push(opts.data);
      verified.push({
        data: opts.data,
        field: String(opts.field),
        expected: opts.expected,
        scope: opts.scope,
        failure: opts.failure,
        equals: opts.equals,
      });
      const status = induced;
      induced = null;
      if (status === "rejected") return { status, problem: `${String(opts.field)} append threw` };
      if (status === "unverified") return { status, problem: opts.failure };
      merge(opts.data);
      return { status: "applied" };
    },
  };
  return {
    store,
    appends,
    calls,
    verified,
    induce: (status: InducedStatus) => {
      induced = status;
    },
  };
}

/**
 * Deterministic `SessionIdentityPorts`. The identity-phase ports record nothing into `calls`:
 * consumption and scratch isolation are observed through `consumed`/`scratched`, the mint and the
 * version stamp through the appended payloads.
 */
function fakePorts(opts: {
  handoff?: Handoff | null;
  runIds?: string[];
  scratchThrows?: boolean;
  mintedId?: string;
}) {
  const consumed: { runId: string; piSessionId?: string }[] = [];
  const scratched: string[] = [];
  const ports: SessionIdentityPorts = {
    readHandoff: () => opts.handoff ?? null,
    listRunIds: () => opts.runIds ?? [],
    markHandoffConsumed: (runId, o) => {
      consumed.push({ runId, ...o });
    },
    ensureRunScratch: (runId) => {
      if (opts.scratchThrows === true) throw new Error("scratch refused");
      scratched.push(runId);
    },
    mintRunId: () => opts.mintedId ?? "01MINT",
    versionStamp: "1.2.3",
  };
  return { ports, consumed, scratched };
}

/** A minimal registry: implement/submit consume `cache.plan-ref`; plan does not. */
function fakeRegistry(calls: string[]): Registry {
  const stage = (id: string, mode: string): Registry["stages"][number] => ({
    id,
    command: id,
    mode,
    doors: {},
    predecessors: [],
    successors: [],
  });
  const stages: Registry["stages"] = [
    stage("implement", "read-write"),
    stage("submit", "read-write"),
    stage("plan", "read-only"),
  ];
  (stages[0] as Registry["stages"][number]).requires = ["cache.plan-ref"];
  (stages[1] as Registry["stages"][number]).reads = ["cache.plan-ref"];
  return {
    schemaVersion: 1,
    // Admission is observed through the stages read (the only registry access the operation has).
    get stages() {
      calls.push("registry");
      return stages;
    },
  };
}

/** Recording post-gate fact reads: every touch lands in `calls`. */
function factReads(
  calls: string[],
  opts: { handoff?: Handoff | null; planRef?: PlanRef | null },
): SessionStartFactReads {
  return {
    readHandoff(runId) {
      calls.push(`handoff:${runId}`);
      return opts.handoff ?? null;
    },
    readPlanRef() {
      calls.push("plan-ref");
      return opts.planRef ?? null;
    },
  };
}

/** The receiver-shaped feedback object startup derives (defaults: not adopted, this session). */
function fb(
  stage: string | null,
  runId: string | null,
  activePlanRef: PlanRef | null,
  extra: { adopted?: boolean; piSessionId?: string } = {},
) {
  return { stage, adopted: false, runId, piSessionId: "me.jsonl", activePlanRef, ...extra };
}

interface StartupOpts {
  seed?: WorkflowState[];
  /** ONE handoff authority: serves the identity ports AND the post-gate fact reads. */
  handoff?: Handoff | null;
  /** Default null (no `PERK_RUN_ID`). */
  envRunId?: string | null;
  /** Default "me.jsonl"; null allowed. */
  sessionId?: string | null;
  runIds?: string[];
  scratchThrows?: boolean;
  mintedId?: string;
  planRef?: PlanRef | null;
  /** `null` runs the facts with a failed-to-load registry; otherwise the fake registry. */
  registry?: null;
  /** Arms the identity phase's verified append (claim/mint) to fail. */
  identityFailure?: InducedStatus;
  /** Arms the post-gate linkage append to fail. */
  linkFailure?: InducedStatus;
}

/**
 * One production-shaped startup over ONE store and ONE ports fake: identity → tool scope → the
 * post-gate facts. The store trace is split at the gate: `identityCalls` is what identity
 * establishment touched; `calls` is everything from `resolveSessionStartFacts` on (store touches,
 * the post-gate handoff/plan-ref reads, the registry read) — pinned exactly, so a forbidden read
 * fails the pin.
 */
function startup(opts: StartupOpts) {
  const s = makeStore(opts.seed);
  const p = fakePorts(opts);
  const currentSessionId = opts.sessionId === undefined ? "me.jsonl" : opts.sessionId;
  if (opts.identityFailure !== undefined) s.induce(opts.identityFailure);
  const identity = establishSessionIdentity(s.store, p.ports, {
    currentSessionId,
    envRunId: opts.envRunId ?? null,
  });
  const scope = sessionStartToolScope(identity);
  const identityCalls = [...s.calls];
  s.calls.length = 0;
  if (opts.linkFailure !== undefined) s.induce(opts.linkFailure);
  const registry = opts.registry === null ? null : fakeRegistry(s.calls);
  const facts = resolveSessionStartFacts(s.store, factReads(s.calls, opts), {
    identity,
    registry,
    currentSessionId,
  });
  return {
    identity,
    scope,
    facts,
    identityCalls,
    calls: s.calls,
    appends: s.appends,
    verified: s.verified,
    consumed: p.consumed,
    scratched: p.scratched,
  };
}

const IMPL = handoffBlob("01RID", "implement", { mode: "read-write" });
const KEPT: WorkflowState = {
  run_id: "01RID",
  pi_session_id: "me.jsonl",
  mode: "read-write",
  stage: "plan",
  active_plan_ref: ref("41"),
};
const KEPT_IMPL: WorkflowState = { ...KEPT, stage: "implement" };
const PARENT: WorkflowState = {
  run_id: "01RID",
  pi_session_id: "parent.jsonl",
  mode: "read-write",
  stage: "implement",
  active_plan_ref: ref("41"),
};

// --- the floor reflection --------------------------------------------------------------------------

test("floor reflection: skipped for an unclaimed or already read-only outcome; otherwise a mode-only verified append — reflected on applied, unchanged on rejected/unverified, contained on a throw", () => {
  const eligible: Extract<EstablishIdentityOutcome, { arm: "claimed" }> = {
    arm: "claimed",
    decision: { action: "claim", source: "env", runId: "RID" },
    resolved: {
      run_id: "RID",
      pi_session_id: "session.jsonl",
      stage: "implement",
      mode: "read-write",
    },
    problems: ["p"],
    warnings: ["w"],
  };
  /** A store whose only legal touch is the ONE exact mode append, classified as `status`. */
  const floorStore = (status: "applied" | InducedStatus | "throws") => {
    let appends = 0;
    const store: SessionStateStore = {
      rebuild: () => {
        throw new Error("must not rebuild");
      },
      append: () => {
        throw new Error("must not plain append");
      },
      appendVerified: (opts) => {
        appends++;
        assert.deepEqual(opts.data, { mode: "read-only" });
        assert.equal(opts.field, "mode");
        assert.equal(opts.expected, "read-only");
        assert.equal(opts.scope, "child restriction");
        if (status === "throws") throw Object.create(null);
        return status === "applied" ? { status } : { status, problem: "already reported" };
      },
    };
    return { store, appends: () => appends };
  };
  // The eligible outcome across the four append results.
  for (const status of ["applied", "rejected", "unverified", "throws"] as const) {
    const { store, appends } = floorStore(status);
    const result = reflectSessionReadOnlyFloor(store, eligible);
    assert.equal(appends(), 1, status);
    assert.equal(result.unexpectedFailure, status === "throws", status);
    if (status === "applied") {
      assert.deepEqual(result.outcome, {
        ...eligible,
        resolved: { ...eligible.resolved, mode: "read-only" },
      });
      assert.equal(result.outcome.decision, eligible.decision);
      assert.equal(result.outcome.problems, eligible.problems);
      assert.equal(result.outcome.warnings, eligible.warnings);
    } else assert.equal(result.outcome, eligible, status);
    assert.equal(eligible.resolved.mode, "read-write", "input never mutated");
  }
  // The two skips: no append at all, the outcome handed back by identity.
  const skipped: EstablishIdentityOutcome[] = [
    { ...eligible, arm: "unclaimed", resolved: {} },
    { ...eligible, resolved: { ...eligible.resolved, mode: "read-only" } },
  ];
  for (const input of skipped) {
    const { store, appends } = floorStore("applied");
    const result = reflectSessionReadOnlyFloor(store, input);
    assert.equal(appends(), 0, input.arm);
    assert.equal(result.unexpectedFailure, false, input.arm);
    assert.equal(result.outcome, input, input.arm);
  }
});

// --- the identity arms -----------------------------------------------------------------------------

test("claim: one combined verified entry, consumed only after success; the handoff node link rides as objective_node_claim; a clean objective-refine handoff claims stage-only", () => {
  // (a) the cold claim
  const claim = startup({
    handoff: { run_id: "01RID", consumed: false, mode: "read-only", stage: "objective-author" },
    envRunId: "01RID",
  });
  assert.equal(claim.identity.arm, "claimed");
  assert.deepEqual(claim.identityCalls, ["rebuild", "appendVerified:run_id"]);
  assert.deepEqual(claim.appends, [
    {
      run_id: "01RID",
      pi_session_id: "me.jsonl",
      mode: "read-only",
      perk_version: "1.2.3",
      stage: "objective-author",
    },
  ]);
  assert.deepEqual(claim.identity.resolved, claim.appends[0]);
  assert.deepEqual(claim.consumed, [{ runId: "01RID", piSessionId: "me.jsonl" }]);
  assert.deepEqual(claim.identity.problems, []);
  assert.deepEqual(claim.identity.warnings, []);

  // (b) idempotent re-claim by the session that already consumed it (lost branch state)
  const again = startup({
    handoff: {
      run_id: "01RID",
      consumed: true,
      pi_session_id: "me.jsonl",
      mode: "read-only",
      stage: "objective-author",
    },
    envRunId: "01RID",
  });
  assert.equal(again.identity.arm, "claimed");
  assert.equal(again.consumed.length, 1, "consumed re-marked once");

  // (c) the objective-plan door's node link persists as the objective_node_claim carrier
  const linked = startup({
    handoff: {
      run_id: "01RID",
      consumed: false,
      mode: "read-only",
      stage: "objective-plan",
      objective_id: "7",
      node_id: "1.1",
    },
    envRunId: "01RID",
  });
  assert.equal(linked.identity.arm, "claimed");
  assert.deepEqual(linked.appends[0]?.objective_node_claim, { objective: "7", node: "1.1" });

  // (d) blank / half-specified / non-string ids persist NO claim
  for (const extra of [
    { objective_id: "  ", node_id: "1.1" },
    { objective_id: "7" },
    { node_id: "1.1" },
    { objective_id: "7", node_id: "" },
    { objective_id: 7, node_id: 1.1 },
  ]) {
    const label = JSON.stringify(extra);
    const r = startup({
      handoff: { run_id: "01RID", consumed: false, ...extra },
      envRunId: "01RID",
    });
    assert.equal(r.identity.arm, "claimed", label);
    assert.equal(
      r.appends[0] !== undefined && "objective_node_claim" in r.appends[0],
      false,
      label,
    );
  }

  // (e) a clean objective-refine handoff (namespaced block, empty/null link keys) claims stage-only
  const refine = startup({
    handoff: {
      run_id: "01RID",
      consumed: false,
      mode: "read-only",
      stage: "objective-refine",
      objective_refinement: { context_digest: "sha256:abc" },
      consumed_learn: [],
      adopt_from: null,
    },
    envRunId: "01RID",
  });
  assert.equal(refine.identity.arm, "claimed");
  assert.deepEqual(refine.appends[0], {
    run_id: "01RID",
    pi_session_id: "me.jsonl",
    mode: "read-only",
    perk_version: "1.2.3",
    stage: "objective-refine",
  });
  assert.deepEqual(refine.consumed, [{ runId: "01RID", piSessionId: "me.jsonl" }]);
});

test("unclaimed: a missing, mismatched, or contaminated handoff and a failed read-back all leave the run unclaimed and NEVER consume", () => {
  // (a) missing; (b) mismatched — consumed AND foreign, so the adopt probe is proven to check
  // `run_id` first (a mismatched blob is never adopted).
  for (const handoff of [
    null,
    { run_id: "01OTHER", consumed: true, pi_session_id: "parent.jsonl" },
  ]) {
    const label = JSON.stringify(handoff);
    const r = startup({ handoff, envRunId: "01RID" });
    assert.equal(r.identity.arm, "unclaimed", label);
    assert.deepEqual(r.identity.problems, ["handoff missing or mismatched for run 01RID"], label);
    assert.deepEqual(r.identity.resolved, {}, label);
    assert.deepEqual(r.appends, [], label);
    assert.deepEqual(r.consumed, [], label);
  }

  // (c) a contaminated objective-refine handoff is refused before any claim and not consumed
  for (const [extra, named] of [
    [{ objective_id: "7", node_id: "1.1" }, "objective_id, node_id"],
    [{ objective_id: "7" }, "objective_id"],
    [{ adopt_from: "12" }, "adopt_from"],
    [{ supersedes: "9" }, "supersedes"],
    [{ gist_scope: "plan" }, "gist_scope"],
    [{ consumed_learn: ["L1"] }, "consumed_learn"],
  ] as const) {
    const r = startup({
      handoff: {
        run_id: "01RID",
        consumed: false,
        mode: "read-only",
        stage: "objective-refine",
        ...extra,
      },
      envRunId: "01RID",
    });
    assert.equal(r.identity.arm, "unclaimed", named);
    assert.equal(r.identity.problems.length, 1, named);
    const problem = r.identity.problems[0] ?? "";
    assert.ok(problem.includes(`it carries ${named}`), problem);
    assert.ok(problem.includes("refusing the objective-refine handoff for run 01RID"), problem);
    assert.deepEqual(r.appends, [], named);
    assert.deepEqual(r.consumed, [], named);
  }
  // The same keys on an ordinary objective-plan handoff are a legitimate node link.
  assert.equal(
    refinementHandoffContamination({
      run_id: "01RID",
      consumed: false,
      stage: "objective-plan",
      objective_id: "7",
      node_id: "1.1",
    }),
    null,
  );

  // (d) a failed read-back: the attempt landed, the seam reported, nothing consumed
  const failed = startup({ handoff: IMPL, envRunId: "01RID", identityFailure: "unverified" });
  assert.equal(failed.identity.arm, "unclaimed");
  assert.deepEqual(failed.consumed, [], "establish-before-consume");
  assert.deepEqual(failed.identity.problems, [], "the strict-append seam reports, not the arm");
  assert.equal(failed.appends.length, 1, "the one attempt");
  assert.deepEqual(failed.identity.resolved, {});
});

test("fork: a derived <parent>.<n> identity past existing siblings, inherited mode and NO stage, a plain append, isolated scratch; a scratch failure is a warning", () => {
  const seed: WorkflowState = {
    run_id: "01RID",
    pi_session_id: "parent.jsonl",
    mode: "read-only",
    stage: "plan",
  };
  const fork = startup({
    seed: [seed],
    sessionId: "child.jsonl",
    runIds: ["01RID.1", "01RID.2", "unrelated", "01RID.x"],
  });
  assert.equal(fork.identity.arm, "forked");
  assert.deepEqual(fork.identityCalls, ["rebuild", "append"]);
  assert.deepEqual(fork.appends, [
    {
      run_id: "01RID.3",
      pi_session_id: "child.jsonl",
      predecessor: "01RID",
      mode: "read-only",
      perk_version: "1.2.3",
    },
  ]);
  assert.deepEqual(fork.scratched, ["01RID.3"]);
  assert.deepEqual(fork.consumed, []);
  assert.deepEqual(fork.identity.warnings, []);
  assert.equal(fork.identity.resolved.run_id, "01RID.3");

  const refused = startup({
    seed: [seed],
    sessionId: "child.jsonl",
    runIds: [],
    scratchThrows: true,
  });
  assert.equal(refused.identity.arm, "forked");
  assert.deepEqual(refused.identity.warnings, [
    "could not create fork run root for 01RID.1: Error: scratch refused",
  ]);
  assert.equal(refused.appends.length, 1, "the derived-identity append still lands");
});

test("adopt: an env-inherited run whose handoff another (or an unrecorded) session consumed derives a child identity — inherited handoff mode, no stage or claim impersonation, never re-consumed", () => {
  // No `pi_session_id` on the consumed handoff: the unrecorded claimer counts as foreign.
  const adopt = startup({
    handoff: {
      run_id: "01RID",
      consumed: true,
      mode: "read-write",
      stage: "implement",
      objective_id: "7",
      node_id: "1.1",
    },
    envRunId: "01RID",
    sessionId: "child.jsonl",
  });
  assert.equal(adopt.identity.arm, "adopted");
  assert.deepEqual(adopt.identityCalls, ["rebuild", "append"]);
  assert.deepEqual(adopt.appends, [
    {
      run_id: "01RID.1",
      pi_session_id: "child.jsonl",
      predecessor: "01RID",
      mode: "read-write",
      perk_version: "1.2.3",
    },
  ]);
  assert.deepEqual(adopt.consumed, [], "adopt never re-consumes the handoff");
  assert.deepEqual(adopt.scratched, ["01RID.1"]);

  const sibling = startup({
    handoff: handoffBlob("01RID", "implement", {
      consumed: true,
      piSessionId: "parent.jsonl",
      mode: "read-only",
    }),
    envRunId: "01RID",
    sessionId: "child.jsonl",
    runIds: ["01RID.1"],
    scratchThrows: true,
  });
  assert.equal(sibling.identity.arm, "adopted");
  assert.equal(sibling.appends[0]?.run_id, "01RID.2");
  assert.equal(sibling.appends[0]?.mode, "read-only");
  assert.deepEqual(sibling.identity.warnings, [
    "could not create adopted run root for 01RID.2: Error: scratch refused",
  ]);
});

test("mint: a warm session with no identity and no (or a blank) env run id mints a verified run_id; a failed read-back leaves it unidentified", () => {
  const mint = startup({ envRunId: "" });
  assert.equal(mint.identity.arm, "minted");
  assert.deepEqual(mint.identityCalls, ["rebuild", "appendVerified:run_id"]);
  assert.deepEqual(mint.appends, [
    { run_id: "01MINT", pi_session_id: "me.jsonl", perk_version: "1.2.3" },
  ]);
  assert.equal(mint.identity.resolved.run_id, "01MINT");

  const failed = startup({ identityFailure: "unverified" });
  assert.equal(failed.identity.arm, "unclaimed");
  assert.equal(failed.identity.resolved.run_id, undefined, "re-mints next session_start");
});

test("keep: a run whose recorded pi_session_id matches (or is absent) appends nothing — no version backfill", () => {
  const seed: WorkflowState = { run_id: "01RID", pi_session_id: "me.jsonl", mode: "read-only" };
  const keep = startup({ seed: [seed] });
  assert.equal(keep.identity.arm, "kept");
  assert.deepEqual(keep.identityCalls, ["rebuild"]);
  assert.deepEqual(keep.appends, [], "reload-generation reconstruction IS the LWW rebuild");
  assert.deepEqual(keep.identity.resolved, seed);
  assert.equal(keep.identity.resolved.perk_version, undefined, "no version backfill (§8.3)");
  assert.deepEqual(keep.consumed, []);
  assert.deepEqual(keep.scratched, []);

  const legacy = startup({ seed: [{ run_id: "01RID", mode: "read-only" }] });
  assert.equal(legacy.identity.arm, "kept");
});

// --- the two-phase startup facts -------------------------------------------------------------------
//
// PHASE 1 (`sessionStartToolScope`) is pure over the established identity. PHASE 2
// (`resolveSessionStartFacts`) is pinned by its exact post-gate trace (rebuild → the allowed
// handoff read → registry admission → the checkout read on the consuming arm only → the one
// verified link). The three authorities — the branch-LWW stage (tool scope), the launched handoff
// stage (capture / feedback), and the checkout ref (linkage) — are made to DISAGREE so the rows
// prove they are never interchangeable.

test("startup matrix: per-arm tool scope (pure), the post-gate port sequence, linkage, capture and feedback", () => {
  const CONSUMING = [
    "rebuild",
    "handoff:01RID",
    "registry",
    "plan-ref",
    "appendVerified:active_plan_ref",
  ];
  const rows: {
    label: string;
    opts: StartupOpts;
    scope: Pick<WorkflowState, "mode" | "stage">;
    calls: string[];
    ref: PlanRef | null;
    capture: { runId: string; parentSessionId: string | null } | null;
    feedback: ReturnType<typeof fb>;
  }[] = [
    {
      label: "claim, consuming stage → one verified link, capture",
      opts: { handoff: IMPL, envRunId: "01RID", planRef: ref("42") },
      scope: { mode: "read-write", stage: "implement" },
      calls: CONSUMING,
      ref: ref("42"),
      capture: { runId: "01RID", parentSessionId: null },
      feedback: fb("implement", "01RID", ref("42")),
    },
    ...["plan", "weird-stage"].map((stage) => ({
      label: `claim, non-consuming or unknown stage (${stage}) never reads the checkout — the root selector never leaks in`,
      opts: {
        seed: [{ active_plan_ref: ref("41") }],
        handoff: handoffBlob("01RID", stage, { mode: "read-write" }),
        envRunId: "01RID",
        planRef: ref("42"),
      },
      scope: { mode: "read-write", stage },
      calls: ["rebuild", "handoff:01RID", "registry"],
      ref: ref("41"),
      capture: null,
      feedback: fb(stage, "01RID", ref("41")),
    })),
    {
      label: "claim, null registry is permissive with a launched stage",
      opts: {
        handoff: handoffBlob("01RID", "plan", { mode: "read-write" }),
        envRunId: "01RID",
        planRef: ref("42"),
        registry: null,
      },
      scope: { mode: "read-write", stage: "plan" },
      calls: ["rebuild", "handoff:01RID", "plan-ref", "appendVerified:active_plan_ref"],
      ref: ref("42"),
      capture: null,
      feedback: fb("plan", "01RID", ref("42")),
    },
    {
      label: "claim, null registry + stage-less handoff is inert",
      opts: {
        seed: [{ active_plan_ref: ref("41") }],
        handoff: handoffBlob("01RID", undefined, { mode: "read-write" }),
        envRunId: "01RID",
        planRef: ref("42"),
        registry: null,
      },
      scope: { mode: "read-write", stage: undefined },
      calls: ["rebuild", "handoff:01RID"],
      ref: ref("41"),
      capture: null,
      feedback: fb(null, "01RID", ref("41")),
    },
    {
      label:
        "keep, branch stage and handoff stage disagree — scope follows the branch, capture/feedback the handoff, linkage re-reads the checkout",
      opts: { seed: [KEPT], handoff: IMPL, planRef: ref("42") },
      scope: { mode: "read-write", stage: "plan" },
      calls: CONSUMING,
      ref: ref("42"),
      capture: { runId: "01RID", parentSessionId: null },
      feedback: fb("implement", "01RID", ref("42")),
    },
    {
      label: "keep, no handoff → no launched stage, no checkout read, LWW ref stays",
      opts: { seed: [KEPT], handoff: null, planRef: ref("42") },
      scope: { mode: "read-write", stage: "plan" },
      calls: ["rebuild", "handoff:01RID"],
      ref: ref("41"),
      capture: null,
      feedback: fb(null, "01RID", ref("41")),
    },
    {
      label:
        "fork of an implement parent inherits scope + capture with fork provenance; never reads",
      opts: { seed: [PARENT], sessionId: "child.jsonl", handoff: IMPL, planRef: ref("42") },
      scope: { mode: "read-write", stage: "implement" },
      calls: ["rebuild"],
      ref: ref("41"),
      capture: { runId: "01RID.1", parentSessionId: "parent.jsonl" },
      feedback: fb("implement", "01RID.1", ref("41"), { piSessionId: "child.jsonl" }),
    },
    {
      label: "adopt is unscoped, flagged, uncaptured; never reads",
      opts: {
        handoff: handoffBlob("01RID", "implement", {
          consumed: true,
          piSessionId: "parent.jsonl",
          mode: "read-only",
        }),
        envRunId: "01RID",
        sessionId: "child.jsonl",
        planRef: ref("42"),
      },
      scope: { mode: "read-only", stage: undefined },
      calls: ["rebuild"],
      ref: null,
      capture: null,
      feedback: fb(null, "01RID.1", null, { adopted: true, piSessionId: "child.jsonl" }),
    },
    {
      label: "mint carries the branch's LWW scope and ref; no launched stage, no reads",
      opts: {
        seed: [{ mode: "read-only", stage: "implement", active_plan_ref: ref("41") }],
        planRef: ref("42"),
      },
      scope: { mode: "read-only", stage: "implement" },
      calls: ["rebuild"],
      ref: ref("41"),
      capture: null,
      feedback: fb(null, "01MINT", ref("41")),
    },
    {
      label: "unclaimed (missing handoff) keeps the downstream path — unscoped, gate off",
      opts: { handoff: null, envRunId: "01RID", planRef: ref("42") },
      scope: { mode: undefined, stage: undefined },
      calls: ["rebuild", "handoff:01RID"],
      ref: null,
      capture: null,
      feedback: fb(null, null, null),
    },
    {
      label: "unclaimed (mint read-back miss) passes the warm branch state through",
      opts: {
        seed: [{ mode: "read-only", stage: "plan" }],
        identityFailure: "unverified",
        planRef: ref("42"),
      },
      scope: { mode: "read-only", stage: "plan" },
      calls: ["rebuild"],
      ref: null,
      capture: null,
      feedback: fb(null, null, null),
    },
  ];
  for (const row of rows) {
    const r = startup(row.opts);
    assert.deepEqual(r.scope, row.scope, row.label);
    assert.deepEqual(r.calls, row.calls, row.label);
    assert.deepEqual(r.facts.resolved.active_plan_ref ?? null, row.ref, row.label);
    assert.deepEqual(r.facts.implementationCapture, row.capture, row.label);
    assert.deepEqual(r.facts.feedback, row.feedback, row.label);
  }
});

test("linkage outcomes: equal (provider, pr_id) keeps the linked object without appending — on a claim and on a kept session's reload alike; a different ref is ONE exact verified append folded in only on applied; a failed append leaves resolved as it arrived — a claim's none, a kept session's LWW ref; no cached ref preserves the link", () => {
  const NO_APPEND = ["rebuild", "handoff:01RID", "registry", "plan-ref"];
  const ONE_APPEND = [...NO_APPEND, "appendVerified:active_plan_ref"];

  // (a) equal identity keeps the LINKED object's metadata (not the checkout's), no append
  const linked = ref("42", { labels: ["perk:plan", "linked-metadata"], objective_id: "7" });
  const equal = startup({
    seed: [{ active_plan_ref: linked }],
    handoff: IMPL,
    envRunId: "01RID",
    planRef: ref("42", { labels: ["checkout-metadata"] }),
  });
  assert.deepEqual(equal.calls, NO_APPEND);
  assert.deepEqual(equal.facts.resolved.active_plan_ref, linked);
  // …and a kept session's reload with the same ref appends nothing (no duplicate link entry).
  const reload = startup({
    seed: [{ ...KEPT_IMPL, active_plan_ref: linked }],
    handoff: IMPL,
    planRef: ref("42"),
  });
  assert.deepEqual(reload.calls, NO_APPEND);
  assert.deepEqual(reload.appends, []);
  assert.deepEqual(reload.facts.resolved.active_plan_ref, linked);

  // (b) a different ref: the exact append — field / comparator / scope / failure text
  const applied = startup({
    seed: [{ active_plan_ref: ref("41") }],
    handoff: handoffBlob("01RID", "submit", { mode: "read-write" }),
    envRunId: "01RID",
    planRef: ref("42"),
  });
  assert.deepEqual(applied.verified.at(-1), {
    data: { active_plan_ref: ref("42") },
    field: "active_plan_ref",
    expected: ref("42"),
    scope: "workflow-state linkage error",
    failure: "plan-ref read-back failed for github:42",
    equals: planRefsEqual,
  });
  assert.deepEqual(applied.appends.at(-1), { active_plan_ref: ref("42") });
  assert.deepEqual(applied.facts.resolved.active_plan_ref, ref("42"));
  assert.equal(applied.facts.implementationCapture, null, "submit is not implement");
  assert.equal(applied.facts.feedback.stage, "submit");

  // (c) a failed append on a claim: exactly one attempt, resolved EXACTLY as it arrived (no ref —
  // never flattened onto the branch's #41, never rebuilt again to manufacture a fallback)
  for (const linkFailure of ["rejected", "unverified"] as const) {
    const failed = startup({
      seed: [{ active_plan_ref: ref("41") }],
      handoff: IMPL,
      envRunId: "01RID",
      planRef: ref("42"),
      linkFailure,
    });
    assert.deepEqual(failed.calls, ONE_APPEND, linkFailure);
    assert.deepEqual(failed.facts.resolved, failed.identity.resolved, linkFailure);
    assert.equal(failed.facts.feedback.activePlanRef, null, `${linkFailure}: no guessed ref`);
    assert.deepEqual(
      failed.facts.implementationCapture,
      { runId: "01RID", parentSessionId: null },
      `${linkFailure}: capture follows the launched stage, not the link`,
    );
  }
  // (d) …and on a kept session the LWW ref survives (never flattened to a claim's none)
  for (const linkFailure of ["rejected", "unverified"] as const) {
    const kept = startup({ seed: [KEPT_IMPL], handoff: IMPL, planRef: ref("42"), linkFailure });
    assert.deepEqual(kept.facts.resolved, KEPT_IMPL, linkFailure);
    assert.deepEqual(kept.facts.feedback.activePlanRef, ref("41"), linkFailure);
  }

  // (e) no cached ref preserves a non-null linked ref; nothing links when both are absent
  const preserved = startup({
    seed: [{ active_plan_ref: ref("41") }],
    handoff: IMPL,
    envRunId: "01RID",
    planRef: null,
  });
  assert.deepEqual(preserved.calls, NO_APPEND);
  assert.equal(preserved.appends.length, 1, "the claim entry only");
  assert.deepEqual(preserved.facts.resolved.active_plan_ref, ref("41"));
  const none = startup({ handoff: IMPL, envRunId: "01RID", planRef: null });
  assert.equal(none.facts.feedback.activePlanRef, null);
});

test("a throwing linked-state rebuild propagates before any handoff or checkout read", () => {
  const s = makeStore();
  const identity = establishSessionIdentity(s.store, fakePorts({ handoff: IMPL }).ports, {
    currentSessionId: "me.jsonl",
    envRunId: "01RID",
  });
  const calls: string[] = [];
  assert.throws(
    () =>
      resolveSessionStartFacts(
        {
          ...s.store,
          rebuild: () => {
            throw new Error("unreadable branch");
          },
        },
        factReads(calls, { handoff: IMPL, planRef: ref("42") }),
        { identity, registry: fakeRegistry(calls), currentSessionId: "me.jsonl" },
      ),
    /unreadable branch/,
  );
  assert.deepEqual(calls, [], "no guessed facts — nothing else was touched");
  assert.equal(s.appends.length, 1, "the claim entry only");
});

test("sessionTreeFacts: pure over the selected-branch state — its own session id, adopted false, no capture, only the five facts read", () => {
  const state: WorkflowState = {
    run_id: "01RID.1",
    pi_session_id: "branch.jsonl",
    mode: "read-only",
    stage: "implement",
    active_plan_ref: ref("42"),
    predecessor: "01RID",
  };
  const touched = new Set<string>();
  const observed = new Proxy(state, {
    get(target, key) {
      touched.add(String(key));
      return Reflect.get(target, key);
    },
  });
  const facts = sessionTreeFacts(observed);
  assert.deepEqual(facts, {
    toolScope: { mode: "read-only", stage: "implement" },
    feedback: {
      stage: "implement",
      adopted: false,
      runId: "01RID.1",
      piSessionId: "branch.jsonl", // the BRANCH's recorded id — never a current-handle override
      activePlanRef: ref("42"),
    },
  });
  assert.ok(!("implementationCapture" in facts), "navigation never captures");
  assert.deepEqual(
    [...touched].sort(),
    ["active_plan_ref", "mode", "pi_session_id", "run_id", "stage"],
    "only the five facts are read — no handoff, checkout, registry, or claim",
  );
  // An env-adopted child's fresh branch: no stage → receiver-ineligible by the stage gate alone.
  assert.deepEqual(sessionTreeFacts({ run_id: "01RID.1", pi_session_id: "child.jsonl" }), {
    toolScope: { mode: undefined, stage: undefined },
    feedback: {
      stage: null,
      adopted: false,
      runId: "01RID.1",
      piSessionId: "child.jsonl",
      activePlanRef: null,
    },
  });
});
