// Direct feature tests for the draft + compaction policy (draftCompact.ts) — memory session only;
// no Pi, no filesystem. Owns the draft policy: the gate's no-read guarantee, the session routing
// refusals, the stage → subject routing, the three-state baseline, and the settle proof (same
// run, a valid draft, and a moved digest — or unusable → valid).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { WorkflowSession } from "../session/workflowSession.ts";
import {
  type MemoryWorkflowSession,
  openMemoryWorkflowSession,
} from "../testing/memoryWorkflowSession.ts";
import {
  type DraftCompactPending,
  settleDraftAndCompact,
  startDraftAndCompact,
} from "./draftCompact.ts";
import { DRAFT_SUBJECT_ARTIFACTS, type DraftSubject } from "./review/subjects.ts";

const RUN = "01DRAFTCOMPACTRUN";
const PLAN_ARTIFACT = DRAFT_SUBJECT_ARTIFACTS.plan;
const DRAFT = "# A plan\n\n## Unresolved\n\n- which seam owns the slot?\n";

/** Silence the session seam's loud stderr lines on induced failures. */
function quietly<T>(fn: () => T): T {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

function write(session: WorkflowSession, name: string, content: string): void {
  const result = session.writeArtifact(name, content);
  assert.ok(
    result.status === "applied" || result.status === "unchanged",
    `seed write landed (${result.status})`,
  );
}

/** Start against a live session and return the drive arm (asserting it drove). */
function drive(session: MemoryWorkflowSession): {
  pending: DraftCompactPending;
  current: string | null;
} {
  const outcome = startDraftAndCompact(true, () => session);
  assert.equal(outcome.kind, "drive");
  if (outcome.kind !== "drive") throw new Error("unreachable");
  return { pending: outcome.pending, current: outcome.current };
}

// --- start: the gate and the routing refusals -----------------------------------------------------

test("not-gated returns before the session factory is ever invoked", () => {
  const outcome = startDraftAndCompact(false, () => {
    throw new Error("the gate-OFF arm must not open the session");
  });
  assert.deepEqual(outcome, { kind: "skip", reason: "not-gated" });
});

test("an identity-less session skips no-identity", () => {
  const session = openMemoryWorkflowSession({ runId: null });
  assert.deepEqual(
    startDraftAndCompact(true, () => session),
    {
      kind: "skip",
      reason: "no-identity",
    },
  );
});

test("a malformed stage skips invalid-state", () => {
  const session = openMemoryWorkflowSession({ runId: RUN, stage: "" });
  assert.deepEqual(
    startDraftAndCompact(true, () => session),
    {
      kind: "skip",
      reason: "invalid-state",
    },
  );
});

test("subject routing follows the session seam's stage-derived read", () => {
  const cases: [string | undefined, DraftSubject][] = [
    [undefined, "plan"],
    ["plan", "plan"],
    ["objective-plan", "plan"],
    ["audit", "plan"],
    ["objective-author", "objective"],
    ["objective-save", "objective"],
    ["gist-author", "gist"],
    ["objective-refine", "refinement"],
  ];
  for (const [stage, subject] of cases) {
    const session = openMemoryWorkflowSession({ runId: RUN, ...(stage ? { stage } : {}) });
    const { pending } = drive(session);
    assert.equal(pending.subject, subject, `stage ${stage ?? "(none)"}`);
    assert.equal(pending.runId, RUN);
  }
});

// --- start: the three-state baseline --------------------------------------------------------------

test("baseline absent: no draft yet, current null", () => {
  const { pending, current } = drive(openMemoryWorkflowSession({ runId: RUN }));
  assert.deepEqual(pending.baseline, { kind: "absent" });
  assert.equal(current, null);
});

test("baseline digest: an existing draft carries its digest and its exact bytes", () => {
  const session = openMemoryWorkflowSession({ runId: RUN, stage: "objective-author" });
  write(session, DRAFT_SUBJECT_ARTIFACTS.objective, '{"prose":"x"}\n');
  const { pending, current } = drive(session);
  assert.equal(pending.baseline.kind, "digest");
  if (pending.baseline.kind === "digest") {
    assert.match(pending.baseline.digest, /^sha256:[0-9a-f]{64}$/);
  }
  assert.equal(current, '{"prose":"x"}\n');
});

test("baseline invalid: a corrupted draft is its own fact, current null", () => {
  const session = openMemoryWorkflowSession({ runId: RUN });
  write(session, PLAN_ARTIFACT, DRAFT);
  session.corruptContent(PLAN_ARTIFACT);
  const { pending, current } = quietly(() => drive(session));
  assert.deepEqual(pending.baseline, { kind: "invalid" });
  assert.equal(current, null);
});

// --- settle: the fresh-checkpoint proof ------------------------------------------------------------

test("settle: a different live run id skips run-changed before any artifact read", () => {
  const { pending } = drive(openMemoryWorkflowSession({ runId: RUN }));
  const forked = openMemoryWorkflowSession({ runId: `${RUN}X` });
  const guarded: WorkflowSession = {
    ...forked,
    readArtifact: () => {
      throw new Error("run-changed must decide before reading the artifact");
    },
  };
  assert.deepEqual(settleDraftAndCompact(pending, guarded), {
    kind: "skip",
    reason: "run-changed",
  });
  assert.deepEqual(settleDraftAndCompact(pending, openMemoryWorkflowSession({ runId: null })), {
    kind: "skip",
    reason: "run-changed",
  });
});

test("settle: no valid draft skips no-draft (absent, dropped bytes, disowned pointer)", () => {
  const absent = openMemoryWorkflowSession({ runId: RUN });
  const { pending } = drive(absent);
  assert.deepEqual(settleDraftAndCompact(pending, absent), { kind: "skip", reason: "no-draft" });

  const dropped = openMemoryWorkflowSession({ runId: RUN });
  const dropArm = drive(dropped);
  write(dropped, PLAN_ARTIFACT, DRAFT);
  dropped.dropContent(PLAN_ARTIFACT);
  assert.deepEqual(
    quietly(() => settleDraftAndCompact(dropArm.pending, dropped)),
    { kind: "skip", reason: "no-draft" },
  );

  const disowned = openMemoryWorkflowSession({ runId: RUN });
  const disownArm = drive(disowned);
  write(disowned, PLAN_ARTIFACT, DRAFT);
  disowned.disownPointer(PLAN_ARTIFACT);
  assert.deepEqual(settleDraftAndCompact(disownArm.pending, disowned), {
    kind: "skip",
    reason: "no-draft",
  });
});

test("settle: a byte-identical rewrite over a digest baseline skips unchanged-draft", () => {
  const session = openMemoryWorkflowSession({ runId: RUN });
  write(session, PLAN_ARTIFACT, DRAFT);
  const { pending } = drive(session);
  write(session, PLAN_ARTIFACT, DRAFT);
  assert.deepEqual(settleDraftAndCompact(pending, session), {
    kind: "skip",
    reason: "unchanged-draft",
  });
});

test("settle: changed bytes over a digest baseline compact with exactly the bytes read", () => {
  const session = openMemoryWorkflowSession({ runId: RUN });
  write(session, PLAN_ARTIFACT, DRAFT);
  const { pending } = drive(session);
  const next = `${DRAFT}- and one more question\n`;
  write(session, PLAN_ARTIFACT, next);
  assert.deepEqual(settleDraftAndCompact(pending, session), {
    kind: "compact-now",
    completion: { subject: "plan", content: next },
  });
});

test("settle: absent → found is a checkpoint", () => {
  const session = openMemoryWorkflowSession({ runId: RUN, stage: "gist-author" });
  const { pending } = drive(session);
  write(session, DRAFT_SUBJECT_ARTIFACTS.gist, '{"prose":"gist"}\n');
  assert.deepEqual(settleDraftAndCompact(pending, session), {
    kind: "compact-now",
    completion: { subject: "gist", content: '{"prose":"gist"}\n' },
  });
});

test("settle: invalid → found is a checkpoint", () => {
  const session = openMemoryWorkflowSession({ runId: RUN });
  write(session, PLAN_ARTIFACT, DRAFT);
  session.corruptContent(PLAN_ARTIFACT);
  const { pending } = quietly(() => drive(session));
  assert.deepEqual(pending.baseline, { kind: "invalid" });
  write(session, PLAN_ARTIFACT, DRAFT);
  assert.deepEqual(settleDraftAndCompact(pending, session), {
    kind: "compact-now",
    completion: { subject: "plan", content: DRAFT },
  });
});
