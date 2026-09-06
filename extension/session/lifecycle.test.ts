// The session identity lifecycle's pure decision units (`decideClaim` / `deriveForkRunId` /
// `resolveRunStage`) — moved with the definitions from `substrate/workflowState.test.ts` — and
// (below) the two-store `establishSessionIdentity` suite. Each establishment arm has a live
// wiring twin in `extension/sessionLifecycle.test.ts` (the harness suite proving the
// extraction preserved behavior end-to-end); here we prove the operation itself over fakes.

import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { Handoff } from "../substrate/cache.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type EntrySink,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "../substrate/workflowState.ts";
import {
  branchSessionStateStore,
  decideClaim,
  deriveForkRunId,
  type EstablishIdentityOutcome,
  establishSessionIdentity,
  reflectSessionReadOnlyFloor,
  resolveRunStage,
  type SessionIdentityPorts,
  type SessionIdentityReads,
  type SessionStateStore,
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
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
          appends.push(data as WorkflowState);
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
      return {
        store: {
          rebuild: () => ({ ...state }),
          append: (data) => {
            appends.push(data);
            merge(data);
          },
          appendVerified: (opts) => {
            appends.push(opts.data);
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
