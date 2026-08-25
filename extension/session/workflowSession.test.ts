// The shared WorkflowSession interface suite, parameterized over BOTH backings (branch/file and
// in-memory) — every classification arm is reached on each: identity (including the
// identity-less always-open arm: artifact writes reject, reads read absent, state ops work),
// applied (pointer recorded + read-back roundtrip), the unchanged short-circuit, rejected
// (invalid name, io refusal), unverified (pointer-append failure), the read tiers (found /
// absent — no pointer, cross-run fork pointer / invalid — missing file, digest mismatch), and
// the workflow-state ops (`nodeClaim()` + `apply()`: applied / unchanged / unverified /
// rejected / non-matching claim / same-node-different-objective / no-identity).

import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { type PlanRef, sessionDataDir } from "../substrate/cache.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type EntrySink,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "../substrate/workflowState.ts";
import { openBranchWorkflowSession } from "./branchWorkflowSession.ts";
import { openMemoryWorkflowSession } from "./memoryWorkflowSession.ts";
import type { WorkflowSession } from "./workflowSession.ts";

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
  dispose(): void;
}

interface HarnessOpts {
  nodeClaim?: { objective: string; node: string };
  activePlanRef?: PlanRef;
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
      let dropAppends = false;
      let throwNextAppend = false;
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
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

  test(`${backing.label}: applied — pointer recorded, read-back roundtrips`, () => {
    const h = backing.harness("RID");
    try {
      const written = h.session.writeArtifact("draft.json", "v1");
      assert.equal(written.status, "applied");
      assert.ok(written.status === "applied");
      assert.equal(written.pointer.run_id, "RID");
      assert.equal(written.pointer.name, "draft.json");
      assert.match(written.pointer.digest, /^sha256:[0-9a-f]{64}$/);
      assert.ok(!Number.isNaN(Date.parse(written.pointer.at)));
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
      const second = h.session.writeArtifact("draft.json", "same bytes");
      assert.equal(second.status, "unchanged");
      assert.ok(first.status === "applied" && second.status === "unchanged");
      assert.equal(second.pointer.digest, first.pointer.digest);
      assert.equal(second.pointer.at, first.pointer.at, "no fresh pointer entry was appended");
      // Different bytes still apply.
      const third = h.session.writeArtifact("draft.json", "different bytes");
      assert.equal(third.status, "applied");
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
}
