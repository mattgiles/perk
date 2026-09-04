// The objective save feature over the MEMORY session + a deterministic fake `ObjectiveBackend`
// (the port-admission rule's test fake): saveObjective's ordering + refusal arms, the §8.63
// dream arms (scripted gate — the routing proof; the real resolver matrix lives in
// `dreamReportGate.test.ts`), the linkage matrix over the seam knobs, the trim-or-omit
// normalization, and the `objectiveApprovalSave` D1a gate matrix.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "./draft.ts";
import type { DreamReportGateOutcome, ObjectiveDreamReportBlock } from "./dreamReportGate.ts";
import {
  type ObjectiveBackend,
  type ObjectiveBackendSaveResult,
  type ObjectiveGate,
  objectiveApprovalSave,
  saveObjective,
} from "./save.ts";

const PROSE = "# Objective\n\nThe why.\n";
const ROADMAP = [{ id: "1.1", description: "first" }];

const DREAM_BLOCK: ObjectiveDreamReportBlock = {
  input: { rows: [] },
  generated_at: "2026-01-01T00:00:00Z",
  parts: ["# Dream report — RID\n\nbody\n"],
};

/** A deterministic backend that records its requests and returns a scripted result. */
function fakeBackend(result?: ObjectiveBackendSaveResult): {
  backend: ObjectiveBackend;
  requests: Parameters<ObjectiveBackend["create"]>[0][];
} {
  const requests: Parameters<ObjectiveBackend["create"]>[0][] = [];
  return {
    backend: {
      create: (req) => {
        requests.push(req);
        return Promise.resolve(
          result ?? { status: "saved", id: "7", url: "https://x/7", existed: false },
        );
      },
    },
    requests,
  };
}

/** A scripted §8.63 gate that records its calls (absent unless overridden). */
function scriptedGate(outcome: DreamReportGateOutcome = { kind: "absent" }): {
  resolveDreamGate: (input: unknown, generatedAt: string) => DreamReportGateOutcome;
  calls: { input: unknown; generatedAt: string }[];
} {
  const calls: { input: unknown; generatedAt: string }[] = [];
  return {
    resolveDreamGate: (input, generatedAt) => {
      calls.push({ input, generatedAt });
      return outcome;
    },
    calls,
  };
}

/** A gate slice with observation (starts read-only unless told otherwise). */
function fakeGate(active = true): ObjectiveGate & { exits: number } {
  const gate = {
    exits: 0,
    isActive: () => active,
    exit: () => {
      active = false;
      gate.exits += 1;
    },
  };
  return gate;
}

/** Capture console.error calls for the duration of `fn` (silences the seam's loud warnings). */
async function quietly<T>(fn: () => Promise<T> | T): Promise<T> {
  const original = console.error;
  console.error = () => {};
  try {
    return await fn();
  } finally {
    console.error = original;
  }
}

// --- saveObjective: refusal ordering + the backend request ---------------------------------------

test("save: blank prose refuses invalid_input BEFORE the gate and the backend", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const gate = scriptedGate();
  const outcome = await saveObjective(
    { prose: "   \n" },
    { session, backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "no objective prose to save (draft the objective first)",
    errorType: "invalid_input",
  });
  assert.equal(gate.calls.length, 0);
  assert.equal(requests.length, 0);
});

test("save: happy path — trimmed prose + full request shape reach the backend; linkage applied", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const outcome = await saveObjective(
    {
      prose: `\n${PROSE}\n`,
      title: " Ship retries ",
      base: "develop",
      delivery: "stacked",
      roadmap: ROADMAP,
    },
    { session, backend, resolveDreamGate: scriptedGate().resolveDreamGate },
  );
  assert.deepEqual(requests, [
    {
      prose: PROSE.trim(),
      title: "Ship retries",
      base: "develop",
      delivery: "stacked",
      roadmap: ROADMAP,
      runId: "RID",
    },
  ]);
  assert.deepEqual(outcome, {
    status: "saved",
    id: "7",
    url: "https://x/7",
    existed: false,
    linkage: { status: "applied" },
  });
  assert.equal(session.activeObjective(), "7");
});

test("save: whitespace-only title/base normalize to absent (trim-or-omit)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  await saveObjective(
    { prose: PROSE, title: "   ", base: " \t" },
    { session, backend, resolveDreamGate: scriptedGate().resolveDreamGate },
  );
  assert.equal(requests.length, 1);
  assert.ok(!("title" in (requests[0] ?? {})), "blank title never reaches the backend");
  assert.ok(!("base" in (requests[0] ?? {})), "blank base never reaches the backend");
});

test("save: identity-less session passes runId null; the linkage still runs", async () => {
  const session = openMemoryWorkflowSession({ runId: null });
  const { backend, requests } = fakeBackend();
  const outcome = await saveObjective(
    { prose: PROSE },
    { session, backend, resolveDreamGate: scriptedGate().resolveDreamGate },
  );
  assert.equal(requests[0]?.runId, null);
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.linkage?.status, "applied");
  assert.equal(session.activeObjective(), "7");
});

test("save: a failed backend passes through verbatim; no linkage attempted", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend } = fakeBackend({
    status: "failed",
    message: "perk objective create failed",
    errorType: "door_failed",
  });
  const outcome = await saveObjective(
    { prose: PROSE },
    { session, backend, resolveDreamGate: scriptedGate().resolveDreamGate },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "perk objective create failed",
    errorType: "door_failed",
  });
  assert.equal(session.activeObjective(), null, "a failed save never touches the session");
});

// --- the linkage matrix (the seam's change result rides verbatim) --------------------------------

test("save: linkage matrix — unchanged / unverified / rejected via the memory knobs", async () => {
  const equal = openMemoryWorkflowSession({ runId: "RID", activeObjective: "7" });
  const first = await saveObjective(
    { prose: PROSE },
    {
      session: equal,
      backend: fakeBackend().backend,
      resolveDreamGate: scriptedGate().resolveDreamGate,
    },
  );
  assert.equal(first.status === "saved" && first.linkage?.status, "unchanged");

  const unverified = openMemoryWorkflowSession({ runId: "RID" });
  unverified.failNextApplyVerification();
  const second = await quietly(() =>
    saveObjective(
      { prose: PROSE },
      {
        session: unverified,
        backend: fakeBackend().backend,
        resolveDreamGate: scriptedGate().resolveDreamGate,
      },
    ),
  );
  assert.equal(second.status === "saved" && second.linkage?.status, "unverified");

  const rejected = openMemoryWorkflowSession({ runId: "RID" });
  rejected.failNextApply();
  const third = await quietly(() =>
    saveObjective(
      { prose: PROSE },
      {
        session: rejected,
        backend: fakeBackend().backend,
        resolveDreamGate: scriptedGate().resolveDreamGate,
      },
    ),
  );
  assert.equal(third.status === "saved" && third.linkage?.status, "rejected");
  assert.equal(rejected.activeObjective(), null, "a rejected linkage lands nothing");
});

// --- the §8.63 dream arms -------------------------------------------------------------------------

test("save: a gate refusal fails with the resolver's detail/errorType; backend never invoked", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const gate = scriptedGate({
    kind: "refuse",
    errorType: "invalid_input",
    detail: "dream_report is only valid inside a perk learn dream session",
  });
  const outcome = await saveObjective(
    { prose: PROSE, dream_report: { source: "direct", input: { rows: [] } } },
    { session, backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "dream_report is only valid inside a perk learn dream session",
    errorType: "invalid_input",
  });
  assert.equal(requests.length, 0);
  // The gate receives the CARRIER's input (never the whole carrier) + the stored/fresh stamp.
  assert.deepEqual(gate.calls[0]?.input, { rows: [] });
});

test("save: absent dream_report still consults the gate (fail-closed the other direction)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const gate = scriptedGate({
    kind: "refuse",
    errorType: "invalid_input",
    detail: "a dream session must carry dream_report",
  });
  const outcome = await saveObjective(
    { prose: PROSE },
    { session, backend: fakeBackend().backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.equal(
    outcome.status === "failed" && outcome.message,
    "a dream session must carry dream_report",
  );
  assert.equal(gate.calls[0]?.input, undefined, "absence is the undefined boundary");
});

test("save: the approval path's stored stamp keeps the comparison deterministic; parts→backend", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const gate = scriptedGate({ kind: "block", block: DREAM_BLOCK });
  const outcome = await saveObjective(
    {
      prose: PROSE,
      dream_report: {
        source: "reviewed",
        block: {
          input: DREAM_BLOCK.input,
          generated_at: DREAM_BLOCK.generated_at,
          parts: [...DREAM_BLOCK.parts],
        },
      },
    },
    { session, backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.equal(outcome.status, "saved");
  assert.equal(gate.calls[0]?.generatedAt, DREAM_BLOCK.generated_at, "the stored stamp rides");
  assert.deepEqual(requests[0]?.dreamParts, DREAM_BLOCK.parts, "gate-proven parts → the backend");
});

test("save: stored-parts mismatch refuses bad_state; nothing saved", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const gate = scriptedGate({ kind: "block", block: DREAM_BLOCK });
  const outcome = await saveObjective(
    {
      prose: PROSE,
      dream_report: {
        source: "reviewed",
        block: {
          input: DREAM_BLOCK.input,
          generated_at: DREAM_BLOCK.generated_at,
          parts: ["# Dream report — RID\n\nTAMPERED\n"],
        },
      },
    },
    { session, backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.deepEqual(outcome, {
    status: "failed",
    message: "the reviewed report no longer matches the wave state — re-draft and re-review",
    errorType: "bad_state",
  });
  assert.equal(requests.length, 0);
  assert.equal(session.activeObjective(), null);
});

test("save: the direct tool path (no stored parts) skips the byte-compare; parts still cross", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const { backend, requests } = fakeBackend();
  const gate = scriptedGate({ kind: "block", block: DREAM_BLOCK });
  const outcome = await saveObjective(
    { prose: PROSE, dream_report: { source: "direct", input: DREAM_BLOCK.input } },
    { session, backend, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.equal(outcome.status, "saved");
  assert.deepEqual(requests[0]?.dreamParts, DREAM_BLOCK.parts);
  // The fresh stamp: a valid ISO timestamp (the save stamps generated_at on this path).
  assert.ok(Number.isFinite(Date.parse(gate.calls[0]?.generatedAt ?? "")));
});

// --- objectiveApprovalSave: the D1a matrix --------------------------------------------------------

const DRAFT_CONTENT = `${JSON.stringify(
  {
    schema_version: 1,
    title: "Draft title",
    base: "develop",
    delivery: "stacked",
    prose: PROSE,
    roadmap: ROADMAP,
  },
  null,
  2,
)}\n`;

function sessionWithDraft(): ReturnType<typeof openMemoryWorkflowSession> {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(session.writeArtifact(OBJECTIVE_DRAFT_ARTIFACT, DRAFT_CONTENT).status, "applied");
  return session;
}

test("approvalSave: no draft ⇒ no-draft — nothing saved, the gate untouched", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const gate = fakeGate(true);
  const { backend, requests } = fakeBackend();
  const outcome = await objectiveApprovalSave({
    session,
    backend,
    resolveDreamGate: scriptedGate().resolveDreamGate,
    gate,
  });
  assert.deepEqual(outcome, { status: "no-draft" });
  assert.equal(requests.length, 0);
  assert.equal(gate.exits, 0);
  assert.equal(gate.isActive(), true);
});

test("approvalSave: saved while read-only ⇒ gate exits; draft fields feed the save", async () => {
  const session = sessionWithDraft();
  const gate = fakeGate(true);
  const { backend, requests } = fakeBackend();
  const outcome = await objectiveApprovalSave({
    session,
    backend,
    resolveDreamGate: scriptedGate().resolveDreamGate,
    gate,
  });
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, true);
  assert.equal(gate.exits, 1);
  // The artifact is the source: title/base/delivery/roadmap recovered from the draft.
  assert.deepEqual(requests[0], {
    prose: PROSE.trim(),
    title: "Draft title",
    base: "develop",
    delivery: "stacked",
    roadmap: ROADMAP,
    runId: "RID",
  });
});

test("approvalSave: an explicit title wins over the draft's", async () => {
  const session = sessionWithDraft();
  const { backend, requests } = fakeBackend();
  await objectiveApprovalSave(
    {
      session,
      backend,
      resolveDreamGate: scriptedGate().resolveDreamGate,
      gate: fakeGate(false),
    },
    { title: "Explicit title" },
  );
  assert.equal(requests[0]?.title, "Explicit title");
});

test("approvalSave: already-writable save succeeds without a gate exit", async () => {
  const session = sessionWithDraft();
  const gate = fakeGate(false);
  const outcome = await objectiveApprovalSave({
    session,
    backend: fakeBackend().backend,
    resolveDreamGate: scriptedGate().resolveDreamGate,
    gate,
  });
  assert.equal(outcome.status, "saved");
  assert.equal(outcome.status === "saved" && outcome.gateExited, false);
  assert.equal(gate.exits, 0);
});

test("approvalSave: a failed save leaves the gate ON (save-failed, gateExited false)", async () => {
  const session = sessionWithDraft();
  const gate = fakeGate(true);
  const outcome = await objectiveApprovalSave({
    session,
    backend: fakeBackend({ status: "failed", message: "boom", errorType: "door_failed" }).backend,
    resolveDreamGate: scriptedGate().resolveDreamGate,
    gate,
  });
  assert.deepEqual(outcome, {
    status: "save-failed",
    result: { status: "failed", message: "boom", errorType: "door_failed" },
    gateExited: false,
  });
  assert.equal(gate.exits, 0);
  assert.equal(gate.isActive(), true);
});

test("approvalSave: the artifact's dream block passes through whole (stored stamp + parts)", async () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const withDream = `${JSON.stringify(
    { schema_version: 1, dream_report: DREAM_BLOCK, prose: PROSE, roadmap: [] },
    null,
    2,
  )}\n`;
  assert.equal(session.writeArtifact(OBJECTIVE_DRAFT_ARTIFACT, withDream).status, "applied");
  const gateCalls = scriptedGate({ kind: "block", block: DREAM_BLOCK });
  const { backend, requests } = fakeBackend();
  const outcome = await objectiveApprovalSave({
    session,
    backend,
    resolveDreamGate: gateCalls.resolveDreamGate,
    gate: fakeGate(true),
  });
  assert.equal(outcome.status, "saved");
  assert.equal(gateCalls.calls[0]?.generatedAt, DREAM_BLOCK.generated_at, "stored stamp rides");
  assert.deepEqual(requests[0]?.dreamParts, DREAM_BLOCK.parts);
});
