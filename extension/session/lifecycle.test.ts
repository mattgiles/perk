// The session identity lifecycle's pure decision units (`decideClaim` / `deriveForkRunId` /
// `resolveRunStage`) — moved with the definitions from `substrate/workflowState.test.ts` — the
// two-store `establishSessionIdentity` suite, and (at the end) the two-phase startup facts:
// `sessionStartToolScope`'s pure scope table, `resolveSessionStartFacts`' authority + lazy-read
// matrix (recorded port sequence, registry admission, the exact verified-link append, the
// kept-versus-claimed posture on a failed append, establish-before-consume observed through
// linkage), and `sessionTreeFacts`' read-only navigation twin. Each arm has a live wiring twin
// in `extension/sessionLifecycle.test.ts` (the harness suite proving the composition preserved
// behavior end-to-end); here we prove the operations themselves over fakes.

import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { Handoff, PlanRef } from "../substrate/cache.ts";
import type { Registry } from "../substrate/registry.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type EntrySink,
  planRefsEqual,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "../substrate/workflowState.ts";
import {
  branchSessionStateStore,
  decideClaim,
  deriveForkRunId,
  type EstablishIdentityOutcome,
  establishSessionIdentity,
  refinementHandoffContamination,
  reflectSessionReadOnlyFloor,
  resolveRunStage,
  resolveSessionStartFacts,
  type SessionIdentityPorts,
  type SessionIdentityReads,
  type SessionStartFactReads,
  type SessionStateStore,
  sessionStartToolScope,
  sessionTreeFacts,
} from "./lifecycle.ts";

test("floor reflection is mode-only, honest across outcomes, and contains unexpected append failures", () => {
  const state: WorkflowState = {
    run_id: "RID",
    pi_session_id: "session.jsonl",
    stage: "implement",
    predecessor: "parent",
    perk_version: "1.2.3",
  };
  const base = { resolved: state, problems: ["original problem"], warnings: ["original warning"] };
  const outcomes: EstablishIdentityOutcome[] = [
    { ...base, arm: "claimed", decision: { action: "claim", source: "env", runId: "RID" } },
    { ...base, arm: "kept", decision: { action: "keep", source: "session", state } },
    {
      ...base,
      arm: "forked",
      decision: { action: "fork", source: "fork", state, childRunId: "RID", parentRunId: "parent" },
    },
    {
      ...base,
      arm: "adopted",
      decision: { action: "adopt", source: "env-child", childRunId: "RID", parentRunId: "parent" },
    },
    { ...base, arm: "minted", decision: { action: "none", source: "none", state } },
    { ...base, arm: "unclaimed", decision: { action: "claim", source: "env", runId: "RID" } },
    { ...base, arm: "unclaimed", decision: { action: "none", source: "none", state } },
  ];
  for (const outcome of outcomes) {
    for (const mode of [undefined, "read-write", "read-only"]) {
      const input = { ...outcome, resolved: { ...state, mode } };
      for (const status of ["applied", "rejected", "unverified", "throws"] as const) {
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
        const result = reflectSessionReadOnlyFloor(store, input);
        const skipped = outcome.arm === "unclaimed" || mode === "read-only";
        assert.equal(appends, skipped ? 0 : 1);
        assert.equal(result.unexpectedFailure, !skipped && status === "throws");
        if (!skipped && status === "applied") {
          assert.deepEqual(result.outcome, {
            ...input,
            resolved: { ...input.resolved, mode: "read-only" },
          });
          assert.equal(result.outcome.decision, input.decision);
          assert.equal(result.outcome.problems, input.problems);
          assert.equal(result.outcome.warnings, input.warnings);
        } else assert.equal(result.outcome, input);
        assert.equal(input.resolved.mode, mode, "input never mutated");
      }
    }
  }
});

/** A handoff blob (optionally carrying `stage`/`consumed`/claim fields) for the claim tests. */
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

/** Deterministic `SessionIdentityReads` — the decision tier never touches disk. */
function fakeReads(
  opts: { handoff?: Handoff | null; runIds?: string[] } = {},
): SessionIdentityReads {
  return {
    readHandoff: () => opts.handoff ?? null,
    listRunIds: () => opts.runIds ?? [],
  };
}

test("decideClaim: cold env claim when no prior state", () => {
  const d = decideClaim({
    state: {},
    currentSessionId: "s1",
    envRunId: "01RID",
    reads: fakeReads(),
  });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: none when no state and no env", () => {
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: null, reads: fakeReads() });
  assert.equal(d.action, "none");
});

test("decideClaim: keep (reload) when pi_session_id matches the current session", () => {
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    reads: fakeReads(),
  });
  assert.equal(d.action, "keep");
  assert.equal(d.source, "session");
});

test("decideClaim: fork when run_id was inherited from a different session", () => {
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "parent" },
    currentSessionId: "child",
    envRunId: null,
    reads: fakeReads(),
  });
  assert.equal(d.action, "fork");
  if (d.action === "fork") {
    assert.equal(d.parentRunId, "01RID");
    assert.equal(d.childRunId, "01RID.1");
  }
});

test("decideClaim: a consumed handoff claimed by a DIFFERENT session adopts a child identity", () => {
  const reads = fakeReads({
    handoff: handoffBlob("01RID", "implement", {
      consumed: true,
      piSessionId: "parent.jsonl",
      mode: "read-write",
    }),
  });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", reads });
  assert.deepEqual(d, {
    action: "adopt",
    source: "env-child",
    childRunId: "01RID.1",
    parentRunId: "01RID",
    mode: "read-write",
  });
});

test("decideClaim: a consumed handoff with NO recorded pi_session_id adopts (unrecorded claimer)", () => {
  const reads = fakeReads({
    handoff: handoffBlob("01RID", "implement", { consumed: true, mode: "read-only" }),
  });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", reads });
  assert.equal(d.action, "adopt");
  if (d.action === "adopt") {
    assert.equal(d.childRunId, "01RID.1");
    assert.equal(d.mode, "read-only");
  }
});

test("decideClaim: a consumed handoff claimed by the CURRENT session re-claims (idempotent)", () => {
  const reads = fakeReads({
    handoff: handoffBlob("01RID", "implement", { consumed: true, piSessionId: "me.jsonl" }),
  });
  const d = decideClaim({ state: {}, currentSessionId: "me.jsonl", envRunId: "01RID", reads });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: an unconsumed handoff stays the normal cold claim", () => {
  const reads = fakeReads({ handoff: handoffBlob("01RID", "implement", { consumed: false }) });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", reads });
  assert.deepEqual(d, { action: "claim", source: "env", runId: "01RID" });
});

test("decideClaim: adopt derives past existing siblings", () => {
  const reads = fakeReads({
    handoff: handoffBlob("01RID", "implement", { consumed: true, piSessionId: "parent.jsonl" }),
    runIds: ["01RID.1"],
  });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", reads });
  assert.equal(d.action, "adopt");
  if (d.action === "adopt") assert.equal(d.childRunId, "01RID.2");
});

test("resolveRunStage: adopt carries no launched stage", () => {
  const reads = fakeReads({
    handoff: handoffBlob("01RID", "implement", { consumed: true, piSessionId: "parent.jsonl" }),
  });
  const d = decideClaim({ state: {}, currentSessionId: "child.jsonl", envRunId: "01RID", reads });
  assert.equal(d.action, "adopt");
  assert.equal(resolveRunStage(d, reads), null);
});

test("resolveRunStage: claim reads the stage from the run's handoff", () => {
  const reads = fakeReads({ handoff: handoffBlob("01RID", "implement") });
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: "01RID", reads });
  assert.equal(resolveRunStage(d, reads), "implement");
});

test("resolveRunStage: claim with a stage-less handoff is null", () => {
  const reads = fakeReads({ handoff: handoffBlob("01RID") });
  const d = decideClaim({ state: {}, currentSessionId: "s1", envRunId: "01RID", reads });
  assert.equal(d.action, "claim");
  assert.equal(resolveRunStage(d, reads), null);
});

test("resolveRunStage: keep reads the stage from the kept run's handoff", () => {
  const reads = fakeReads({ handoff: handoffBlob("01RID", "submit") });
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    reads,
  });
  assert.equal(d.action, "keep");
  assert.equal(resolveRunStage(d, reads), "submit");
});

test("resolveRunStage: keep with no handoff file is null", () => {
  const reads = fakeReads();
  const d = decideClaim({
    state: { run_id: "01RID", pi_session_id: "s1" },
    currentSessionId: "s1",
    envRunId: null,
    reads,
  });
  assert.equal(d.action, "keep");
  assert.equal(resolveRunStage(d, reads), null);
});

test("resolveRunStage: fork and none carry no launched stage", () => {
  const reads = fakeReads({ handoff: handoffBlob("01RID", "implement") });
  const fork = decideClaim({
    state: { run_id: "01RID", pi_session_id: "parent" },
    currentSessionId: "child",
    envRunId: null,
    reads,
  });
  assert.equal(fork.action, "fork");
  assert.equal(resolveRunStage(fork, reads), null);
  const none = decideClaim({ state: {}, currentSessionId: "s1", envRunId: null, reads });
  assert.equal(none.action, "none");
  assert.equal(resolveRunStage(none, reads), null);
});

test("deriveForkRunId: increments past existing siblings", () => {
  const runIds = ["01RID.1", "01RID.2", "unrelated"];
  assert.equal(deriveForkRunId("01RID", runIds), "01RID.3");
  assert.equal(deriveForkRunId("01OTHER", runIds), "01OTHER.1");
});

// --- establishSessionIdentity over BOTH stores ---------------------------------------------------
//
// The branch store is the production `branchSessionStateStore` (live branch array + a
// no-op-notify ctx); the memory store is a knobbed fake. Each proves the same arm matrix:
// claim (with/without the handoff node-claim carrier; blank/half ids persist no claim),
// unclaimed (missing/mismatched handoff; a failed read-back does NOT consume), fork (derived
// child + tolerated scratch warning), adopt (no stage impersonation, inherited mode, never
// re-consumes), mint (verified; a failed read-back leaves the session unidentified), and
// keep (NO append, no version backfill).

interface StoreHarness {
  store: SessionStateStore;
  /** Every appended entry payload, in order (the observation channel). */
  appends: WorkflowState[];
  /** Make the NEXT verified append miss its read-back (`unverified`). */
  induceReadBackMiss(): void;
  /** Make the NEXT verified append refuse before any effect (`rejected`). */
  induceAppendRefusal(): void;
}

interface StoreBacking {
  label: string;
  make(cwd: string, initial: WorkflowState[]): StoreHarness;
}

function branchStoreBacking(): StoreBacking {
  return {
    label: "branch store",
    make(cwd, initial) {
      const branch: unknown[] = initial.map((data) => ({
        type: "custom",
        customType: WORKFLOW_STATE_TYPE,
        data,
      }));
      const appends: WorkflowState[] = [];
      let dropNext = false;
      let throwNext = false;
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
          appends.push(data as WorkflowState);
          if (throwNext) {
            throwNext = false;
            throw new Error("append refused (induced)"); // the classified seam proves `rejected`
          }
          if (dropNext) {
            dropNext = false;
            return; // dropped on the floor — the read-back proof misses
          }
          branch.push({ type: "custom", customType, data });
        },
      };
      const ctx: SessionArtifactCtx = {
        cwd,
        sessionManager: { getBranch: () => branch },
        hasUI: false,
        ui: { notify() {} },
      };
      return {
        store: branchSessionStateStore(sink, ctx),
        appends,
        induceReadBackMiss: () => {
          dropNext = true;
        },
        induceAppendRefusal: () => {
          throwNext = true;
        },
      };
    },
  };
}

function memoryStoreBacking(): StoreBacking {
  return {
    label: "memory store",
    make(_cwd, initial) {
      const state: WorkflowState = {};
      const merge = (data: WorkflowState) => {
        for (const [key, value] of Object.entries(data)) {
          if (value !== undefined) (state as Record<string, unknown>)[key] = value;
        }
      };
      for (const data of initial) merge(data);
      const appends: WorkflowState[] = [];
      let failNext = false;
      let refuseNext = false;
      return {
        store: {
          rebuild: () => ({ ...state }),
          append: (data) => {
            appends.push(data);
            merge(data);
          },
          appendVerified: (opts) => {
            appends.push(opts.data);
            if (refuseNext) {
              refuseNext = false;
              return { status: "rejected", problem: `${String(opts.field)} append threw` };
            }
            if (failNext) {
              failNext = false;
              return { status: "unverified", problem: opts.failure };
            }
            merge(opts.data);
            return { status: "applied" };
          },
        },
        appends,
        induceReadBackMiss: () => {
          failNext = true;
        },
        induceAppendRefusal: () => {
          refuseNext = true;
        },
      };
    },
  };
}

/** Deterministic `SessionIdentityPorts` with observation channels. */
function fakePorts(opts: {
  handoff?: Handoff | null;
  runIds?: string[];
  scratchThrows?: boolean;
  mintedId?: string;
  stamp?: string | undefined;
}): {
  ports: SessionIdentityPorts;
  consumed: { runId: string; piSessionId?: string }[];
  scratched: string[];
} {
  const consumed: { runId: string; piSessionId?: string }[] = [];
  const scratched: string[] = [];
  return {
    ports: {
      readHandoff: () => opts.handoff ?? null,
      listRunIds: () => opts.runIds ?? [],
      markHandoffConsumed: (runId, o) => {
        consumed.push({ runId, ...o });
      },
      ensureRunScratch: (runId) => {
        if (opts.scratchThrows === true) throw new Error("scratch refused");
        scratched.push(runId);
      },
      mintRunId: () => opts.mintedId ?? "01MINTED",
      versionStamp: "stamp" in opts ? opts.stamp : "1.2.3",
    },
    consumed,
    scratched,
  };
}

/** Capture console.error for the duration of `fn` (the strict seam's loud failure channel). */
function quietly<T>(fn: () => T): T {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

for (const backing of [branchStoreBacking(), memoryStoreBacking()]) {
  test(`${backing.label}: claim — one combined verified entry, consumed only after success`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, []);
    const { ports, consumed } = fakePorts({
      handoff: { run_id: "01RID", consumed: false, mode: "read-only", stage: "objective-author" },
    });
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "me.jsonl",
      envRunId: "01RID",
    });
    assert.equal(outcome.arm, "claimed");
    assert.equal(h.appends.length, 1);
    assert.deepEqual(h.appends[0], {
      run_id: "01RID",
      pi_session_id: "me.jsonl",
      mode: "read-only",
      perk_version: "1.2.3",
      stage: "objective-author",
    });
    assert.deepEqual(outcome.resolved, h.appends[0]);
    assert.deepEqual(consumed, [{ runId: "01RID", piSessionId: "me.jsonl" }]);
    assert.deepEqual(outcome.problems, []);
    assert.deepEqual(outcome.warnings, []);
  });

  test(`${backing.label}: claim — the handoff node link rides as the objective_node_claim carrier`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, []);
    const { ports } = fakePorts({
      handoff: {
        run_id: "01RID",
        consumed: false,
        mode: "read-only",
        stage: "plan",
        objective_id: "7",
        node_id: "1.1",
      },
    });
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "me.jsonl",
      envRunId: "01RID",
    });
    assert.equal(outcome.arm, "claimed");
    assert.deepEqual(h.appends[0]?.objective_node_claim, { objective: "7", node: "1.1" });
  });

  test(`${backing.label}: claim — blank or half-specified handoff ids persist NO claim`, () => {
    for (const extra of [
      { objective_id: "  ", node_id: "1.1" },
      { objective_id: "7" },
      { node_id: "1.1" },
      { objective_id: "7", node_id: "" },
    ]) {
      const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
      const h = backing.make(cwd, []);
      const { ports } = fakePorts({
        handoff: { run_id: "01RID", consumed: false, ...extra },
      });
      const outcome = establishSessionIdentity(h.store, ports, {
        currentSessionId: "me.jsonl",
        envRunId: "01RID",
      });
      assert.equal(outcome.arm, "claimed");
      assert.equal(h.appends[0] !== undefined && "objective_node_claim" in h.appends[0], false);
    }
  });

  test(`${backing.label}: claim — a clean objective-refine handoff claims stage-only (namespaced block, no node claim)`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, []);
    const { ports, consumed } = fakePorts({
      handoff: {
        run_id: "01RID",
        consumed: false,
        mode: "read-only",
        stage: "objective-refine",
        objective_refinement: { context_digest: "sha256:abc" },
        consumed_learn: [],
        adopt_from: null,
      },
    });
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "me.jsonl",
      envRunId: "01RID",
    });
    assert.equal(outcome.arm, "claimed");
    assert.deepEqual(h.appends[0], {
      run_id: "01RID",
      pi_session_id: "me.jsonl",
      mode: "read-only",
      perk_version: "1.2.3",
      stage: "objective-refine",
    });
    assert.deepEqual(consumed, [{ runId: "01RID", piSessionId: "me.jsonl" }]);
  });

  test(`${backing.label}: claim — a contaminated objective-refine handoff refuses before claiming and is NOT consumed`, () => {
    for (const [extra, named] of [
      [{ objective_id: "7", node_id: "1.1" }, "objective_id, node_id"],
      [{ objective_id: "7" }, "objective_id"],
      [{ adopt_from: "12" }, "adopt_from"],
      [{ supersedes: "9" }, "supersedes"],
      [{ gist_scope: "plan" }, "gist_scope"],
      [{ consumed_learn: ["L1"] }, "consumed_learn"],
    ] as const) {
      const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
      const h = backing.make(cwd, []);
      const { ports, consumed } = fakePorts({
        handoff: {
          run_id: "01RID",
          consumed: false,
          mode: "read-only",
          stage: "objective-refine",
          ...extra,
        },
      });
      const outcome = establishSessionIdentity(h.store, ports, {
        currentSessionId: "me.jsonl",
        envRunId: "01RID",
      });
      assert.equal(outcome.arm, "unclaimed", named);
      assert.equal(outcome.problems.length, 1);
      assert.ok(outcome.problems[0]?.includes(`it carries ${named}`), outcome.problems[0]);
      assert.deepEqual(outcome.resolved, {});
      assert.equal(h.appends.length, 0, "nothing recorded — no claim, no stage");
      assert.equal(consumed.length, 0, "the contaminated handoff is not consumed");
    }
    // The same keys on an ordinary objective-plan handoff still claim normally.
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
  });

  test(`${backing.label}: claim — a missing or mismatched handoff is unclaimed (never mints)`, () => {
    for (const handoff of [null, { run_id: "01OTHER", consumed: false }]) {
      const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
      const h = backing.make(cwd, []);
      const { ports, consumed } = fakePorts({ handoff });
      const outcome = establishSessionIdentity(h.store, ports, {
        currentSessionId: "me.jsonl",
        envRunId: "01RID",
      });
      assert.equal(outcome.arm, "unclaimed");
      assert.deepEqual(outcome.problems, ["handoff missing or mismatched for run 01RID"]);
      assert.deepEqual(outcome.resolved, {});
      assert.equal(h.appends.length, 0);
      assert.equal(consumed.length, 0);
    }
  });

  test(`${backing.label}: claim — a failed read-back is unclaimed and does NOT consume`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, []);
    const { ports, consumed } = fakePorts({
      handoff: { run_id: "01RID", consumed: false, mode: "read-only" },
    });
    h.induceReadBackMiss();
    const outcome = quietly(() =>
      establishSessionIdentity(h.store, ports, {
        currentSessionId: "me.jsonl",
        envRunId: "01RID",
      }),
    );
    assert.equal(outcome.arm, "unclaimed");
    assert.equal(consumed.length, 0, "establish-before-consume: unverified claim never consumes");
    assert.deepEqual(outcome.resolved, {});
    // no problems of its own — the strict-append seam already reported through its channel
    assert.deepEqual(outcome.problems, []);
  });

  test(`${backing.label}: fork — derived child identity, inherited mode, honest-tier append`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, [
      { run_id: "01RID", pi_session_id: "parent.jsonl", mode: "read-only" },
    ]);
    const { ports, consumed, scratched } = fakePorts({});
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "child.jsonl",
      envRunId: null,
    });
    assert.equal(outcome.arm, "forked");
    assert.equal(h.appends.length, 1);
    assert.deepEqual(h.appends[0], {
      run_id: "01RID.1",
      pi_session_id: "child.jsonl",
      predecessor: "01RID",
      mode: "read-only",
      perk_version: "1.2.3",
    });
    assert.deepEqual(scratched, ["01RID.1"]);
    assert.equal(consumed.length, 0);
    assert.deepEqual(outcome.warnings, []);
    assert.equal(outcome.resolved.run_id, "01RID.1");
  });

  test(`${backing.label}: fork — a scratch failure is a warning; identity still settles`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, [{ run_id: "01RID", pi_session_id: "parent.jsonl" }]);
    const { ports } = fakePorts({ scratchThrows: true });
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "child.jsonl",
      envRunId: null,
    });
    assert.equal(outcome.arm, "forked");
    assert.deepEqual(outcome.warnings, [
      "could not create fork run root for 01RID.1: Error: scratch refused",
    ]);
    assert.equal(h.appends.length, 1, "the derived-identity append still lands");
  });

  test(`${backing.label}: adopt — inherited mode, no stage impersonation, never re-consumes`, () => {
    // decideClaim's env-child probe reads the SAME injected port as the claim arm — a consumed
    // handoff claimed by a different session routes to adopt.
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, []);
    const { ports, consumed, scratched } = fakePorts({
      handoff: handoffBlob("01RID", "implement", {
        consumed: true,
        piSessionId: "parent.jsonl",
        mode: "read-write",
      }),
      scratchThrows: true,
    });
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "child.jsonl",
      envRunId: "01RID",
    });
    assert.equal(outcome.arm, "adopted");
    assert.deepEqual(h.appends[0], {
      run_id: "01RID.1",
      pi_session_id: "child.jsonl",
      predecessor: "01RID",
      mode: "read-write",
      perk_version: "1.2.3",
    });
    assert.equal(
      h.appends[0] !== undefined && "stage" in h.appends[0] && h.appends[0].stage !== undefined,
      false,
      "adopt never impersonates the launched stage",
    );
    assert.equal(consumed.length, 0, "adopt never re-consumes the handoff");
    assert.deepEqual(scratched, []);
    assert.deepEqual(outcome.warnings, [
      "could not create adopted run root for 01RID.1: Error: scratch refused",
    ]);
  });

  test(`${backing.label}: mint — verified append; a failed read-back leaves the session unidentified`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const minted = backing.make(cwd, []);
    const { ports } = fakePorts({ mintedId: "01MINT" });
    const outcome = establishSessionIdentity(minted.store, ports, {
      currentSessionId: "me.jsonl",
      envRunId: null,
    });
    assert.equal(outcome.arm, "minted");
    assert.deepEqual(minted.appends[0], {
      run_id: "01MINT",
      pi_session_id: "me.jsonl",
      perk_version: "1.2.3",
    });
    assert.equal(outcome.resolved.run_id, "01MINT");

    const failed = backing.make(cwd, []);
    failed.induceReadBackMiss();
    const failedOutcome = quietly(() =>
      establishSessionIdentity(failed.store, fakePorts({ mintedId: "01MINT" }).ports, {
        currentSessionId: "me.jsonl",
        envRunId: null,
      }),
    );
    assert.equal(failedOutcome.arm, "unclaimed");
    assert.equal(failedOutcome.resolved.run_id, undefined, "re-mints next session_start");
  });

  test(`${backing.label}: keep (reload) — NO append, no version backfill`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const h = backing.make(cwd, [
      { run_id: "01RID", pi_session_id: "me.jsonl", mode: "read-only" },
    ]);
    const { ports, consumed, scratched } = fakePorts({});
    const outcome = establishSessionIdentity(h.store, ports, {
      currentSessionId: "me.jsonl",
      envRunId: null,
    });
    assert.equal(outcome.arm, "kept");
    assert.equal(h.appends.length, 0, "reload-generation reconstruction IS the LWW rebuild");
    assert.equal(outcome.resolved.run_id, "01RID");
    assert.equal(outcome.resolved.perk_version, undefined, "no version backfill (§8.3)");
    assert.equal(consumed.length, 0);
    assert.deepEqual(scratched, []);
  });
}

// --- the two-phase startup facts -----------------------------------------------------------------
//
// PHASE 1 (`sessionStartToolScope`) is pure over the established identity. PHASE 2
// (`resolveSessionStartFacts`) runs over BOTH stores with recording ports: the operation
// sequence is pinned per arm (rebuild → allowed handoff read → registry admission → checkout
// read on the consuming arm only → the one verified link), every forbidden port throws, and the
// three authorities — the branch-LWW stage (tool scope), the launched handoff stage
// (implementation capture / feedback), and the checkout ref (linkage) — are deliberately made to
// DISAGREE so the tests prove they are never interchangeable.

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

/** A minimal registry: implement/submit consume `cache.plan-ref`; plan does not. */
function fakeRegistry(calls: string[]): Registry {
  const stages: Registry["stages"] = [
    { id: "implement", command: "implement", doors: {}, predecessors: [], successors: [] },
    { id: "submit", command: "submit", doors: {}, predecessors: [], successors: [] },
    { id: "plan", command: "plan", doors: {}, predecessors: [], successors: [] },
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

/** Recording fact reads: every touch lands in `calls`; a forbidden touch throws. */
function factReads(
  calls: string[],
  opts: { handoff?: Handoff | null; planRef?: PlanRef | null; forbid?: ("handoff" | "plan-ref")[] },
): SessionStartFactReads {
  return {
    readHandoff(runId) {
      if (opts.forbid?.includes("handoff")) throw new Error(`forbidden handoff read (${runId})`);
      calls.push(`handoff:${runId}`);
      return opts.handoff ?? null;
    },
    readPlanRef() {
      if (opts.forbid?.includes("plan-ref")) throw new Error("forbidden checkout plan-ref read");
      calls.push("plan-ref");
      return opts.planRef ?? null;
    },
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

/** Wrap a store harness so every store touch lands in `calls` (and the verified opts are kept). */
function recordingStore(
  h: StoreHarness,
  calls: string[],
): { store: SessionStateStore; verified: RecordedAppend[] } {
  const verified: RecordedAppend[] = [];
  return {
    verified,
    store: {
      rebuild: () => {
        calls.push("rebuild");
        return h.store.rebuild();
      },
      append: () => {
        throw new Error("the post-gate facts never plain-append");
      },
      appendVerified: (opts) => {
        calls.push(`appendVerified:${String(opts.field)}`);
        verified.push({
          data: opts.data,
          field: String(opts.field),
          expected: opts.expected,
          scope: opts.scope,
          failure: opts.failure,
          equals: opts.equals,
        });
        return h.store.appendVerified(opts);
      },
    },
  };
}

const CLAIM_RESOLVED: WorkflowState = {
  run_id: "01RID",
  pi_session_id: "me.jsonl",
  mode: "read-write",
  perk_version: "1.2.3",
  stage: "implement",
};
const claimed = (resolved: WorkflowState = CLAIM_RESOLVED): EstablishIdentityOutcome => ({
  arm: "claimed",
  resolved,
  decision: { action: "claim", source: "env", runId: "01RID" },
  problems: [],
  warnings: [],
});
const kept = (state: WorkflowState): EstablishIdentityOutcome => ({
  arm: "kept",
  resolved: state,
  decision: { action: "keep", source: "session", state },
  problems: [],
  warnings: [],
});
const forked = (parent: WorkflowState): EstablishIdentityOutcome => {
  const resolved: WorkflowState = {
    run_id: "01RID.1",
    pi_session_id: "child.jsonl",
    predecessor: "01RID",
    mode: parent.mode,
    perk_version: "1.2.3",
  };
  return {
    arm: "forked",
    resolved,
    decision: {
      action: "fork",
      source: "fork",
      childRunId: "01RID.1",
      parentRunId: "01RID",
      state: parent,
    },
    problems: [],
    warnings: [],
  };
};
const adopted = (resolved: WorkflowState): EstablishIdentityOutcome => ({
  arm: "adopted",
  resolved,
  decision: {
    action: "adopt",
    source: "env-child",
    childRunId: "01RID.1",
    parentRunId: "01RID",
    mode: resolved.mode,
  },
  problems: [],
  warnings: [],
});
const minted = (state: WorkflowState): EstablishIdentityOutcome => ({
  arm: "minted",
  resolved: { ...state, run_id: "01MINT", pi_session_id: "me.jsonl", perk_version: "1.2.3" },
  decision: { action: "none", source: "none", state },
  problems: [],
  warnings: [],
});
const unclaimedClaim = (): EstablishIdentityOutcome => ({
  arm: "unclaimed",
  resolved: {},
  decision: { action: "claim", source: "env", runId: "01RID" },
  problems: ["handoff missing or mismatched for run 01RID"],
  warnings: [],
});
const unclaimedMint = (state: WorkflowState): EstablishIdentityOutcome => ({
  arm: "unclaimed",
  resolved: state,
  decision: { action: "none", source: "none", state },
  problems: [],
  warnings: [],
});

test("sessionStartToolScope: pure per-arm mode/stage slice — branch stage is the key, adopt is unscoped, only fork inherits", () => {
  const parent: WorkflowState = {
    run_id: "01RID",
    pi_session_id: "parent.jsonl",
    mode: "read-only",
    stage: "plan",
  };
  const cases: { label: string; identity: EstablishIdentityOutcome; expected: unknown }[] = [
    {
      label: "claim → the handoff-recorded stage just appended",
      identity: claimed(),
      expected: { mode: "read-write", stage: "implement" },
    },
    {
      label: "claim with a stage-less handoff → unscoped",
      identity: claimed({ ...CLAIM_RESOLVED, stage: undefined }),
      expected: { mode: "read-write", stage: undefined },
    },
    {
      label: "claim passes an unknown stage id through unvalidated",
      identity: claimed({ ...CLAIM_RESOLVED, stage: "weird-stage" }),
      expected: { mode: "read-write", stage: "weird-stage" },
    },
    {
      label: "keep → the branch-LWW stage (never a handoff read)",
      identity: kept({ ...parent, pi_session_id: "me.jsonl", stage: "implement" }),
      expected: { mode: "read-only", stage: "implement" },
    },
    {
      label: "fork INHERITS the parent's stage when its own entry has none",
      identity: forked(parent),
      expected: { mode: "read-only", stage: "plan" },
    },
    {
      label: "fork: a null-coalesced resolved stage also falls back to the parent's",
      identity: {
        ...forked(parent),
        resolved: { ...forked(parent).resolved, stage: null as unknown as string },
      },
      expected: { mode: "read-only", stage: "plan" },
    },
    {
      label: "fork of a stage-less parent stays unscoped",
      identity: forked({ ...parent, stage: undefined }),
      expected: { mode: "read-only", stage: undefined },
    },
    {
      label: "adopt NEVER impersonates a stage — even one smuggled onto the resolved entry",
      identity: adopted({ run_id: "01RID.1", mode: "read-only", stage: "implement" }),
      expected: { mode: "read-only", stage: undefined },
    },
    {
      label: "mint → the branch-LWW stage/mode the warm session already carried",
      identity: minted({ mode: "read-only", stage: "objective-author" }),
      expected: { mode: "read-only", stage: "objective-author" },
    },
    {
      label: "unclaimed (failed claim) → empty resolved → unscoped, gate off",
      identity: unclaimedClaim(),
      expected: { mode: undefined, stage: undefined },
    },
    {
      label: "unclaimed (failed mint) → the warm branch state passes through",
      identity: unclaimedMint({ mode: "read-only", stage: "plan" }),
      expected: { mode: "read-only", stage: "plan" },
    },
    {
      label: "the reflected floor's mode is exactly what the gate sees",
      identity: { ...claimed(), resolved: { ...CLAIM_RESOLVED, mode: "read-only" } },
      expected: { mode: "read-only", stage: "implement" },
    },
  ];
  for (const { label, identity, expected } of cases) {
    const before = JSON.stringify(identity);
    assert.deepEqual(sessionStartToolScope(identity), expected, label);
    assert.equal(JSON.stringify(identity), before, `input never mutated: ${label}`);
  }
});

for (const backing of [branchStoreBacking(), memoryStoreBacking()]) {
  /** One post-gate run over a seeded store with recording ports; returns everything observable. */
  function run(opts: {
    identity: EstablishIdentityOutcome;
    seed?: WorkflowState[];
    handoff?: Handoff | null;
    planRef?: PlanRef | null;
    registry?: "fake" | null;
    forbid?: ("handoff" | "plan-ref")[];
    before?: (h: StoreHarness) => void;
    currentSessionId?: string | null;
  }) {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-facts-"));
    const h = backing.make(cwd, opts.seed ?? []);
    opts.before?.(h);
    const calls: string[] = [];
    const registry = opts.registry === null ? null : fakeRegistry(calls);
    const { store, verified } = recordingStore(h, calls);
    const reads = factReads(calls, {
      handoff: opts.handoff,
      planRef: opts.planRef,
      forbid: opts.forbid,
    });
    const facts = quietly(() =>
      resolveSessionStartFacts(store, reads, {
        identity: opts.identity,
        registry,
        currentSessionId: opts.currentSessionId === undefined ? "me.jsonl" : opts.currentSessionId,
      }),
    );
    return { facts, calls, verified, appends: h.appends, harness: h };
  }

  test(`${backing.label}: post-gate facts — a consuming cold claim runs rebuild → handoff → registry → checkout → ONE verified link, in that order`, () => {
    const r = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED],
      handoff: handoffBlob("01RID", "implement"),
      planRef: ref("42"),
    });
    assert.deepEqual(r.calls, [
      "rebuild",
      "handoff:01RID",
      "registry",
      "plan-ref",
      "appendVerified:active_plan_ref",
    ]);
    // The exact append: field / comparator / scope / failure text — the same classified
    // mechanism that sat beneath the old boolean wrapper.
    assert.equal(r.verified.length, 1);
    const opts = r.verified[0];
    assert.ok(opts);
    assert.deepEqual(opts.data, { active_plan_ref: ref("42") });
    assert.equal(opts.field, "active_plan_ref");
    assert.deepEqual(opts.expected, ref("42"));
    assert.equal(opts.scope, "workflow-state linkage error");
    assert.equal(opts.failure, "plan-ref read-back failed for github:42");
    assert.equal(opts.equals, planRefsEqual);
    assert.deepEqual(r.appends, [{ active_plan_ref: ref("42") }]);
    assert.deepEqual(r.facts.resolved, { ...CLAIM_RESOLVED, active_plan_ref: ref("42") });
    assert.deepEqual(r.facts.implementationCapture, { runId: "01RID", parentSessionId: null });
    assert.deepEqual(r.facts.feedback, {
      stage: "implement",
      adopted: false,
      runId: "01RID",
      piSessionId: "me.jsonl",
      activePlanRef: ref("42"),
    });
  });

  test(`${backing.label}: post-gate facts — equal (provider, pr_id) keeps the LINKED object's metadata with no append`, () => {
    const linked = ref("42", { labels: ["perk:plan", "linked-metadata"], objective_id: "7" });
    const r = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED, { active_plan_ref: linked }],
      handoff: handoffBlob("01RID", "implement"),
      planRef: ref("42", { labels: ["checkout-metadata"] }),
    });
    assert.deepEqual(r.calls, ["rebuild", "handoff:01RID", "registry", "plan-ref"]);
    assert.deepEqual(r.appends, [], "no duplicate append on equal identity");
    assert.deepEqual(
      r.facts.resolved.active_plan_ref,
      linked,
      "the linked object, not the cache's",
    );
    assert.deepEqual(r.facts.feedback.activePlanRef, linked);
  });

  test(`${backing.label}: post-gate facts — a DIFFERENT checkout ref performs one strict append and folds in only on applied`, () => {
    const applied = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED, { active_plan_ref: ref("41") }],
      handoff: handoffBlob("01RID", "submit"),
      planRef: ref("42"),
    });
    assert.deepEqual(applied.calls, [
      "rebuild",
      "handoff:01RID",
      "registry",
      "plan-ref",
      "appendVerified:active_plan_ref",
    ]);
    assert.deepEqual(applied.facts.resolved.active_plan_ref, ref("42"));
    assert.equal(applied.facts.implementationCapture, null, "submit is not implement");
    assert.equal(applied.facts.feedback.stage, "submit");

    // Rejected / unverified: the incoming resolved result is left EXACTLY as it arrived — a
    // fresh claim carries no ref (never flattened onto the branch's #41), and nothing is rebuilt
    // again to manufacture success or a fallback.
    for (const failure of ["rejected", "unverified"] as const) {
      const failed = run({
        identity: claimed(),
        seed: [CLAIM_RESOLVED, { active_plan_ref: ref("41") }],
        handoff: handoffBlob("01RID", "implement"),
        planRef: ref("42"),
        before: (h) => (failure === "rejected" ? h.induceAppendRefusal() : h.induceReadBackMiss()),
      });
      assert.deepEqual(
        failed.calls,
        ["rebuild", "handoff:01RID", "registry", "plan-ref", "appendVerified:active_plan_ref"],
        `${failure}: exactly one attempt, no retry rebuild`,
      );
      assert.deepEqual(failed.facts.resolved, CLAIM_RESOLVED, `${failure}: resolved as it arrived`);
      assert.equal(failed.facts.feedback.activePlanRef, null, `${failure}: no guessed ref`);
      assert.deepEqual(
        failed.facts.implementationCapture,
        { runId: "01RID", parentSessionId: null },
        `${failure}: capture follows the launched stage, not the link`,
      );
    }
  });

  test(`${backing.label}: post-gate facts — a KEPT session keeps its LWW ref on a failed append (never flattened to a claim's none)`, () => {
    const state: WorkflowState = {
      run_id: "01RID",
      pi_session_id: "me.jsonl",
      mode: "read-write",
      stage: "implement",
      active_plan_ref: ref("41"),
    };
    for (const failure of ["rejected", "unverified"] as const) {
      const r = run({
        identity: kept(state),
        seed: [state],
        handoff: handoffBlob("01RID", "implement"),
        planRef: ref("42"),
        before: (h) => (failure === "rejected" ? h.induceAppendRefusal() : h.induceReadBackMiss()),
      });
      assert.deepEqual(r.facts.resolved, state, `${failure}: the kept resolved ref survives`);
      assert.deepEqual(r.facts.feedback.activePlanRef, ref("41"));
    }
    // …and applies normally when the append lands.
    const ok = run({
      identity: kept(state),
      seed: [state],
      handoff: handoffBlob("01RID", "implement"),
      planRef: ref("42"),
    });
    assert.deepEqual(ok.facts.resolved, { ...state, active_plan_ref: ref("42") });
  });

  test(`${backing.label}: post-gate facts — no cached ref preserves a non-null linked ref; nothing links when both are absent`, () => {
    const preserved = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED, { active_plan_ref: ref("41") }],
      handoff: handoffBlob("01RID", "implement"),
      planRef: null,
    });
    assert.deepEqual(preserved.calls, ["rebuild", "handoff:01RID", "registry", "plan-ref"]);
    assert.deepEqual(preserved.appends, []);
    assert.deepEqual(preserved.facts.resolved.active_plan_ref, ref("41"));

    const none = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED],
      handoff: handoffBlob("01RID", "implement"),
      planRef: null,
    });
    assert.deepEqual(none.calls, ["rebuild", "handoff:01RID", "registry", "plan-ref"]);
    assert.deepEqual(none.facts.resolved, CLAIM_RESOLVED);
    assert.equal(none.facts.feedback.activePlanRef, null);
  });

  test(`${backing.label}: post-gate facts — a non-consuming or unknown launched stage never reads the checkout, preserving linkage via LWW`, () => {
    for (const stage of ["plan", "weird-stage"]) {
      const r = run({
        identity: claimed({ ...CLAIM_RESOLVED, stage }),
        seed: [{ ...CLAIM_RESOLVED, stage }, { active_plan_ref: ref("41") }],
        handoff: handoffBlob("01RID", stage),
        planRef: ref("42"),
        forbid: ["plan-ref"],
      });
      assert.deepEqual(r.calls, ["rebuild", "handoff:01RID", "registry"], stage);
      assert.deepEqual(r.appends, []);
      assert.deepEqual(
        r.facts.resolved.active_plan_ref,
        ref("41"),
        "the root selector never leaks in",
      );
      assert.equal(r.facts.implementationCapture, null);
      assert.equal(r.facts.feedback.stage, stage, "the launched stage still rides to the receiver");
    }
  });

  test(`${backing.label}: post-gate facts — registry-null is permissive WITH a launched stage and inert without one`, () => {
    const permissive = run({
      identity: claimed(),
      seed: [CLAIM_RESOLVED],
      handoff: handoffBlob("01RID", "plan"),
      planRef: ref("42"),
      registry: null,
    });
    assert.deepEqual(permissive.calls, [
      "rebuild",
      "handoff:01RID",
      "plan-ref",
      "appendVerified:active_plan_ref",
    ]);
    assert.deepEqual(permissive.facts.resolved.active_plan_ref, ref("42"));

    const stageless = run({
      identity: claimed({ ...CLAIM_RESOLVED, stage: undefined }),
      seed: [{ ...CLAIM_RESOLVED, stage: undefined }, { active_plan_ref: ref("41") }],
      handoff: handoffBlob("01RID"),
      planRef: ref("42"),
      registry: null,
      forbid: ["plan-ref"],
    });
    assert.deepEqual(stageless.calls, ["rebuild", "handoff:01RID"]);
    assert.deepEqual(stageless.facts.resolved.active_plan_ref, ref("41"));
    assert.equal(stageless.facts.implementationCapture, null);
    assert.equal(stageless.facts.feedback.stage, null);
  });

  test(`${backing.label}: post-gate facts — keep reads its run's handoff; branch stage and handoff stage are NOT interchangeable`, () => {
    // Branch says implement, handoff says submit: tool scope (phase 1) follows the branch;
    // capture/feedback (phase 2) follow the launched handoff stage.
    const state: WorkflowState = {
      run_id: "01RID",
      pi_session_id: "me.jsonl",
      mode: "read-write",
      stage: "implement",
      active_plan_ref: ref("41"),
    };
    const disagree = run({
      identity: kept(state),
      seed: [state],
      handoff: handoffBlob("01RID", "submit"),
      planRef: ref("42"),
    });
    assert.deepEqual(sessionStartToolScope(kept(state)), {
      mode: "read-write",
      stage: "implement",
    });
    assert.deepEqual(disagree.calls, [
      "rebuild",
      "handoff:01RID",
      "registry",
      "plan-ref",
      "appendVerified:active_plan_ref",
    ]);
    assert.equal(disagree.facts.implementationCapture, null, "submit ≠ implement");
    assert.equal(disagree.facts.feedback.stage, "submit");
    assert.deepEqual(
      disagree.facts.resolved.active_plan_ref,
      ref("42"),
      "reload re-reads the binding",
    );

    // …and the converse: branch says plan, handoff says implement → capture fires.
    const planBranch: WorkflowState = { ...state, stage: "plan" };
    const converse = run({
      identity: kept(planBranch),
      seed: [planBranch],
      handoff: handoffBlob("01RID", "implement"),
      planRef: ref("41"),
    });
    assert.deepEqual(sessionStartToolScope(kept(planBranch)), {
      mode: "read-write",
      stage: "plan",
    });
    assert.deepEqual(converse.facts.implementationCapture, {
      runId: "01RID",
      parentSessionId: null,
    });
    assert.equal(converse.facts.feedback.stage, "implement");

    // Keep WITHOUT a handoff: no launched stage → no checkout read, no capture, the LWW ref stays.
    const noHandoff = run({
      identity: kept(state),
      seed: [state],
      handoff: null,
      planRef: ref("42"),
      forbid: ["plan-ref"],
    });
    assert.deepEqual(noHandoff.calls, ["rebuild", "handoff:01RID"]);
    assert.deepEqual(noHandoff.facts.resolved, state);
    assert.equal(noHandoff.facts.implementationCapture, null);
    assert.deepEqual(noHandoff.facts.feedback, {
      stage: null,
      adopted: false,
      runId: "01RID",
      piSessionId: "me.jsonl",
      activePlanRef: ref("41"),
    });
  });

  test(`${backing.label}: post-gate facts — fork never reads a handoff or the checkout; capture inherits the parent's stage + session provenance`, () => {
    const parent: WorkflowState = {
      run_id: "01RID",
      pi_session_id: "parent.jsonl",
      mode: "read-write",
      stage: "implement",
      active_plan_ref: ref("41"),
    };
    const identity = forked(parent);
    const r = run({
      identity,
      seed: [parent, identity.resolved],
      handoff: handoffBlob("01RID", "submit"), // present but MUST NOT be read
      planRef: ref("42"), // present but MUST NOT be read
      forbid: ["handoff", "plan-ref"],
      currentSessionId: "child.jsonl",
    });
    assert.deepEqual(r.calls, ["rebuild"], "the linked-state rebuild only");
    assert.deepEqual(r.appends, []);
    assert.deepEqual(r.facts.resolved, { ...identity.resolved, active_plan_ref: ref("41") });
    assert.deepEqual(r.facts.implementationCapture, {
      runId: "01RID.1",
      parentSessionId: "parent.jsonl",
    });
    assert.deepEqual(r.facts.feedback, {
      stage: "implement",
      adopted: false,
      runId: "01RID.1",
      piSessionId: "child.jsonl", // startup's CURRENT handle, never the inherited parent's
      activePlanRef: ref("41"),
    });
    // A fork of a non-implement parent captures nothing.
    const planFork = forked({ ...parent, stage: "plan" });
    const none = run({
      identity: planFork,
      seed: [{ ...parent, stage: "plan" }, planFork.resolved],
      forbid: ["handoff", "plan-ref"],
      currentSessionId: "child.jsonl",
    });
    assert.equal(none.facts.implementationCapture, null);
    assert.equal(none.facts.feedback.stage, "plan");
  });

  test(`${backing.label}: post-gate facts — adopt and mint never read a handoff or the checkout and never capture`, () => {
    const adoptedIdentity = adopted({
      run_id: "01RID.1",
      pi_session_id: "child.jsonl",
      predecessor: "01RID",
      mode: "read-write",
      perk_version: "1.2.3",
    });
    const adopt = run({
      identity: adoptedIdentity,
      seed: [adoptedIdentity.resolved],
      handoff: handoffBlob("01RID", "implement", { consumed: true, piSessionId: "parent.jsonl" }),
      planRef: ref("42"),
      forbid: ["handoff", "plan-ref"],
      currentSessionId: "child.jsonl",
    });
    assert.deepEqual(adopt.calls, ["rebuild"]);
    assert.deepEqual(adopt.facts.resolved, adoptedIdentity.resolved);
    assert.equal(adopt.facts.implementationCapture, null, "no parent-stage impersonation");
    assert.deepEqual(adopt.facts.feedback, {
      stage: null,
      adopted: true,
      runId: "01RID.1",
      piSessionId: "child.jsonl",
      activePlanRef: null,
    });

    const mintedIdentity = minted({
      mode: "read-only",
      stage: "implement",
      active_plan_ref: ref("41"),
    });
    const mint = run({
      identity: mintedIdentity,
      seed: [mintedIdentity.resolved],
      planRef: ref("42"),
      forbid: ["handoff", "plan-ref"],
    });
    assert.deepEqual(mint.calls, ["rebuild"]);
    assert.equal(mint.facts.implementationCapture, null, "a warm mint has no launched stage");
    assert.deepEqual(mint.facts.feedback, {
      stage: null,
      adopted: false,
      runId: "01MINT",
      piSessionId: "me.jsonl",
      activePlanRef: ref("41"),
    });
  });

  test(`${backing.label}: post-gate facts — both unclaimed shapes keep the existing downstream path (no early return, no capture)`, () => {
    // A failed cold claim still resolves the launched stage from the (mismatched-or-missing)
    // handoff exactly as before; with no run id nothing is captured and the receiver sees no run.
    const missing = run({ identity: unclaimedClaim(), handoff: null, planRef: ref("42") });
    assert.deepEqual(missing.calls, ["rebuild", "handoff:01RID"]);
    assert.deepEqual(missing.facts.resolved, {});
    assert.equal(missing.facts.implementationCapture, null);
    assert.deepEqual(missing.facts.feedback, {
      stage: null,
      adopted: false,
      runId: null,
      piSessionId: "me.jsonl",
      activePlanRef: null,
    });

    const failedMint = run({
      identity: unclaimedMint({ mode: "read-only", stage: "implement" }),
      seed: [{ mode: "read-only", stage: "implement" }],
      planRef: ref("42"),
      forbid: ["handoff", "plan-ref"],
    });
    assert.deepEqual(failedMint.calls, ["rebuild"]);
    assert.equal(failedMint.facts.implementationCapture, null, "no run id → no capture");
    assert.deepEqual(failedMint.facts.feedback, {
      stage: null,
      adopted: false,
      runId: null,
      piSessionId: "me.jsonl",
      activePlanRef: null,
    });
  });

  test(`${backing.label}: post-gate facts — a throwing linked-state rebuild propagates before any handoff/checkout read`, () => {
    const cwd = mkdtempSync(join(tmpdir(), "perk-lifecycle-facts-"));
    const h = backing.make(cwd, [CLAIM_RESOLVED]);
    const calls: string[] = [];
    const reads = factReads(calls, {
      handoff: handoffBlob("01RID", "implement"),
      planRef: ref("42"),
      forbid: ["handoff", "plan-ref"],
    });
    const store: SessionStateStore = {
      rebuild: () => {
        throw new Error("unreadable branch");
      },
      append: h.store.append,
      appendVerified: h.store.appendVerified,
    };
    assert.throws(
      () =>
        resolveSessionStartFacts(store, reads, {
          identity: claimed(),
          registry: fakeRegistry(calls),
          currentSessionId: "me.jsonl",
        }),
      /unreadable branch/,
    );
    assert.deepEqual(calls, [], "no guessed facts — nothing else was touched");
    assert.deepEqual(h.appends, []);
  });

  test(`${backing.label}: establish-before-consume observed through linkage — a failed claim retains its handoff; a link failure never consumes or un-consumes`, () => {
    // (a) A missing handoff: unclaimed, not consumed; the post-gate facts read the handoff again
    // (null), link nothing, and consumption stays untouched.
    const cwdA = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const a = backing.make(cwdA, []);
    const portsA = fakePorts({ handoff: null });
    const identityA = establishSessionIdentity(a.store, portsA.ports, {
      currentSessionId: "me.jsonl",
      envRunId: "01RID",
    });
    assert.equal(identityA.arm, "unclaimed");
    const callsA: string[] = [];
    const factsA = quietly(() =>
      resolveSessionStartFacts(
        recordingStore(a, callsA).store,
        { readHandoff: portsA.ports.readHandoff, readPlanRef: () => ref("42") },
        { identity: identityA, registry: fakeRegistry(callsA), currentSessionId: "me.jsonl" },
      ),
    );
    assert.deepEqual(callsA, ["rebuild"]);
    assert.deepEqual(portsA.consumed, [], "a failed claim is never consumed by linkage");
    assert.deepEqual(factsA.resolved, {});
    assert.deepEqual(a.appends, []);

    // (b) A claim whose read-back missed: unclaimed and NOT consumed; a later link failure on
    // the same session neither consumes it nor changes the empty resolved facts.
    const cwdB = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const b = backing.make(cwdB, []);
    const portsB = fakePorts({ handoff: handoffBlob("01RID", "implement") });
    b.induceReadBackMiss();
    const identityB = quietly(() =>
      establishSessionIdentity(b.store, portsB.ports, {
        currentSessionId: "me.jsonl",
        envRunId: "01RID",
      }),
    );
    assert.equal(identityB.arm, "unclaimed");
    assert.deepEqual(portsB.consumed, []);
    b.induceReadBackMiss();
    const factsB = quietly(() =>
      resolveSessionStartFacts(
        b.store,
        { readHandoff: portsB.ports.readHandoff, readPlanRef: () => ref("42") },
        { identity: identityB, registry: null, currentSessionId: "me.jsonl" },
      ),
    );
    assert.deepEqual(portsB.consumed, [], "a later link failure never consumes a failed claim");
    assert.deepEqual(factsB.resolved, {}, "unchanged: no run id, no guessed ref");
    assert.equal(factsB.implementationCapture, null);
    assert.equal(factsB.feedback.runId, null);

    // (c) A VERIFIED claim consumed its handoff; a subsequent link failure does not undo that
    // consumption and leaves the claim's resolved facts (no ref) exactly as they arrived.
    const cwdC = mkdtempSync(join(tmpdir(), "perk-lifecycle-"));
    const c = backing.make(cwdC, []);
    const portsC = fakePorts({ handoff: handoffBlob("01RID", "implement") });
    const identityC = establishSessionIdentity(c.store, portsC.ports, {
      currentSessionId: "me.jsonl",
      envRunId: "01RID",
    });
    assert.equal(identityC.arm, "claimed");
    assert.deepEqual(portsC.consumed, [{ runId: "01RID", piSessionId: "me.jsonl" }]);
    c.induceAppendRefusal();
    const factsC = quietly(() =>
      resolveSessionStartFacts(
        c.store,
        { readHandoff: portsC.ports.readHandoff, readPlanRef: () => ref("42") },
        { identity: identityC, registry: null, currentSessionId: "me.jsonl" },
      ),
    );
    assert.deepEqual(
      portsC.consumed,
      [{ runId: "01RID", piSessionId: "me.jsonl" }],
      "consumption history is untouched by the link failure",
    );
    assert.deepEqual(factsC.resolved, identityC.resolved, "the claim's facts, no repaired linkage");
    assert.equal(factsC.feedback.activePlanRef, null);
    assert.deepEqual(factsC.implementationCapture, { runId: "01RID", parentSessionId: null });
    assert.equal(c.appends.length, 2, "the claim entry + the ONE refused link attempt — no retry");
  });
}

test("sessionTreeFacts: pure over the supplied selected-branch state — its own session id, adopted false, no capture, no reads", () => {
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
  assert.deepEqual(sessionTreeFacts({}), {
    toolScope: { mode: undefined, stage: undefined },
    feedback: { stage: null, adopted: false, runId: null, piSessionId: null, activePlanRef: null },
  });
});
