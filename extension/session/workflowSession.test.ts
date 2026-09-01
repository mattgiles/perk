// The shared WorkflowSession interface suite, parameterized over BOTH backings (branch/file and
// in-memory) — every classification arm is reached on each: identity, applied (pointer recorded +
// read-back roundtrip), the unchanged short-circuit, rejected (invalid name, io refusal), open →
// absent without identity, unverified (pointer-append failure), and the read tiers (found /
// absent — no pointer, cross-run fork pointer / invalid — missing file, digest mismatch).

import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { sessionDataDir } from "../substrate/cache.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import { type EntrySink, WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import { openBranchWorkflowSession } from "./branchWorkflowSession.ts";
import { openMemoryWorkflowSession } from "./memoryWorkflowSession.ts";
import type { OpenWorkflowSession, WorkflowSession } from "./workflowSession.ts";

/** The per-backing harness: one session plus deterministic ways to reach every arm. */
interface SessionHarness {
  session: WorkflowSession;
  /** Make the NEXT writeArtifact refuse before any effect (the rejected io arm). */
  induceWriteRefusal(): void;
  /** Make the NEXT writeArtifact land its bytes but fail the pointer proof (unverified). */
  inducePointerAppendFailure(): void;
  /** After a successful write of `name`: make its stored bytes mismatch the pointer (invalid). */
  corrupt(name: string): void;
  /** After a successful write of `name`: drop its stored bytes, keep the pointer (invalid). */
  dropFile(name: string): void;
  /** After a successful write of `name`: make its pointer belong to a foreign run (absent). */
  disown(name: string): void;
  dispose(): void;
}

interface Backing {
  label: string;
  open(runId: string | null): OpenWorkflowSession;
  harness(runId: string): SessionHarness;
}

// --- the branch/file backing fixtures ---------------------------------------------------------

function runIdEntry(runId: string): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: runId } };
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
      const branch: unknown[] = runId === null ? [] : [runIdEntry(runId)];
      const sink: EntrySink = {
        appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
      };
      return openBranchWorkflowSession(sink, reportableCtx(cwd, branch));
    },
    harness(runId) {
      const cwd = mkdtempSync(join(tmpdir(), "workflow-session-test-"));
      const branch: unknown[] = [runIdEntry(runId)];
      let dropAppends = false;
      const sink: EntrySink = {
        appendEntry: (customType, data) => {
          if (dropAppends) {
            dropAppends = false;
            return;
          }
          branch.push({ type: "custom", customType, data });
        },
      };
      const ctx = reportableCtx(cwd, branch);
      const opened = openBranchWorkflowSession(sink, ctx);
      assert.equal(opened.status, "opened");
      const session = opened.status === "opened" ? opened.session : null;
      assert.ok(session);
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
        corrupt(name) {
          writeFileSync(join(sessionDataDir(cwd, runId), name), "rewound bytes", "utf8");
        },
        dropFile(name) {
          rmSync(join(sessionDataDir(cwd, runId), name));
        },
        disown(name) {
          void name;
          // A fork child inherits the parent's pointer entries under a derived run_id: every
          // pointer on the branch now belongs to a foreign run.
          branch.push(runIdEntry(`${runId}.1`));
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
    harness(runId) {
      const opened = openMemoryWorkflowSession({ runId });
      assert.equal(opened.status, "opened");
      const session = opened.status === "opened" ? opened.session : null;
      assert.ok(session);
      return {
        session,
        induceWriteRefusal: () => session.failNextWrite(),
        inducePointerAppendFailure: () => session.failNextPointerAppend(),
        corrupt: (name) => session.corruptContent(name),
        dropFile: (name) => session.dropContent(name),
        disown: (name) => session.disownPointer(name),
        dispose() {},
      };
    },
  };
}

// --- the shared suite --------------------------------------------------------------------------

for (const backing of [branchBacking(), memoryBacking()]) {
  test(`${backing.label}: open without identity → absent; with identity → runId`, () => {
    assert.deepEqual(backing.open(null), { status: "absent" });
    const opened = backing.open("RID");
    assert.equal(opened.status, "opened");
    assert.equal(opened.status === "opened" && opened.session.runId, "RID");
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
}
