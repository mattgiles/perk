// Direct feature tests for the change-publication operation (delivery/submit.ts): ordering and
// atomicity via call-order recorders over fake ports — pre-effect failure (no session-side
// activity), verified success (pointer + reset-on-clean), the shared budget transition
// (inspect/commit), and the bounded conflict decision with the surface-uniform withhold
// posture. OFFLINE — no Pi, no cold door.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CONFLICT_RESOLUTION_ATTEMPT_CAP,
  type ConflictAttempts,
  decideConflictFollowUp,
  inspectConflictBudget,
  type PublishAttempt,
  type PublishDeps,
  type PublishedChange,
  publishVerified,
  submitChange,
} from "./submit.ts";

const CHANGE: PublishedChange = {
  pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
  branch: "plan-7",
  base: "main",
  mergeable: true,
  conflicts: [],
};

/** A recording ConflictAttempts fake: `reads`/`writes` pin the exact call sequence. */
function fakeAttempts(opts: { value?: number; writeResult?: boolean } = {}) {
  const writes: number[] = [];
  let reads = 0;
  const attempts: ConflictAttempts = {
    read() {
      reads += 1;
      return opts.value ?? 0;
    },
    write(next: number) {
      writes.push(next);
      return opts.writeResult ?? true;
    },
  };
  return { attempts, writes, readCount: () => reads };
}

function deps(opts: {
  attempt: PublishAttempt;
  runId?: string | null;
  attempts?: ConflictAttempts;
}) {
  const calls: string[] = [];
  const d: PublishDeps = {
    publish: async ({ runId }) => {
      calls.push(`publish(${runId === null ? "null" : runId})`);
      return opts.attempt;
    },
    readRunId: () => (opts.runId === undefined ? "01RID" : opts.runId),
    recordImplementationPointer: (runId) => {
      calls.push(`pointer(${runId})`);
    },
    attempts: opts.attempts ?? fakeAttempts().attempts,
  };
  return { d, calls };
}

// --- publishVerified ------------------------------------------------------------------------

test("publishVerified: a failed publish returns as-is with NO session-side activity", async () => {
  const rec = fakeAttempts({ value: 1 });
  const { d, calls } = deps({
    attempt: { ok: false, message: "boom", errorType: "push_rejected" },
    attempts: rec.attempts,
  });
  const attempt = await publishVerified(d);
  assert.deepEqual(attempt, { ok: false, message: "boom", errorType: "push_rejected" });
  assert.deepEqual(calls, ["publish(01RID)"], "the pointer capability is never invoked");
  assert.equal(rec.readCount(), 0, "the counter is never read");
  assert.deepEqual(rec.writes, [], "the counter is never written");
});

test("publishVerified: verified clean success records the pointer once and resets a dirty counter", async () => {
  const rec = fakeAttempts({ value: 1 });
  const { d, calls } = deps({ attempt: { ok: true, change: CHANGE }, attempts: rec.attempts });
  const attempt = await publishVerified(d);
  assert.equal(attempt.ok, true);
  assert.deepEqual(calls, ["publish(01RID)", "pointer(01RID)"], "the pointer receives the read id");
  assert.deepEqual(rec.writes, [0], "reset-on-clean");
});

test("publishVerified: a clean counter short-circuits the reset (no write)", async () => {
  const rec = fakeAttempts({ value: 0 });
  const { d } = deps({ attempt: { ok: true, change: CHANGE }, attempts: rec.attempts });
  await publishVerified(d);
  assert.deepEqual(rec.writes, [], "write(0) only when read() !== 0");
});

test("publishVerified: runId null ⇒ the port receives null and the pointer is not invoked", async () => {
  const { d, calls } = deps({ attempt: { ok: true, change: CHANGE }, runId: null });
  await publishVerified(d);
  assert.deepEqual(calls, ["publish(null)"]);
});

test("publishVerified: mergeable absent/null still resets (clean-or-undetermined)", async () => {
  for (const mergeable of [undefined, null]) {
    const rec = fakeAttempts({ value: 2 });
    const change = { ...CHANGE };
    if (mergeable === undefined) delete change.mergeable;
    else change.mergeable = mergeable;
    const { d } = deps({ attempt: { ok: true, change }, attempts: rec.attempts });
    await publishVerified(d);
    assert.deepEqual(rec.writes, [0], String(mergeable));
  }
});

test("publishVerified: a conflicted publish never resets", async () => {
  const rec = fakeAttempts({ value: 1 });
  const { d } = deps({
    attempt: { ok: true, change: { ...CHANGE, mergeable: false, conflicts: ["a.py"] } },
    attempts: rec.attempts,
  });
  await publishVerified(d);
  assert.deepEqual(rec.writes, []);
});

test("publishVerified: a throwing readRunId propagates BEFORE the external publish", async () => {
  // The load-bearing failure path (contracts §8.35 parity): an unreadable branch must abort the
  // publish — never silently drop the run-id stamp and publish anyway.
  const { d, calls } = deps({ attempt: { ok: true, change: CHANGE } });
  d.readRunId = () => {
    throw new Error("branch unreadable");
  };
  await assert.rejects(() => publishVerified(d), /branch unreadable/);
  assert.deepEqual(calls, [], "the publish port was never invoked");
});

// --- the shared budget transition (inspect → commit) -----------------------------------------

test("inspectConflictBudget: under the cap ⇒ available with the next attempt number", () => {
  for (const n of [0, CONFLICT_RESOLUTION_ATTEMPT_CAP - 1]) {
    const rec = fakeAttempts({ value: n });
    assert.deepEqual(inspectConflictBudget(rec.attempts), {
      kind: "available",
      next: n + 1,
      cap: CONFLICT_RESOLUTION_ATTEMPT_CAP,
    });
    assert.deepEqual(rec.writes, [], "inspect never writes");
  }
});

test("inspectConflictBudget: at (and past) the cap ⇒ exhausted with the observed count", () => {
  for (const n of [CONFLICT_RESOLUTION_ATTEMPT_CAP, CONFLICT_RESOLUTION_ATTEMPT_CAP + 3]) {
    const rec = fakeAttempts({ value: n });
    assert.deepEqual(inspectConflictBudget(rec.attempts), { kind: "exhausted", attempts: n });
  }
});

// --- decideConflictFollowUp -----------------------------------------------------------------

test("decideConflictFollowUp: mergeable true/null/absent ⇒ none (no counter activity)", () => {
  for (const change of [CHANGE, { ...CHANGE, mergeable: null }, { pr: CHANGE.pr }]) {
    const rec = fakeAttempts({ value: 1 });
    assert.deepEqual(decideConflictFollowUp(change, rec.attempts), { kind: "none" });
    assert.equal(rec.readCount(), 0);
    assert.deepEqual(rec.writes, []);
  }
});

test("decideConflictFollowUp: under the cap ⇒ drive with the written increment (0→1, 1→2)", () => {
  for (const n of [0, 1]) {
    const rec = fakeAttempts({ value: n });
    const followUp = decideConflictFollowUp({ ...CHANGE, mergeable: false }, rec.attempts);
    assert.deepEqual(followUp, {
      kind: "drive",
      base: "main",
      attempt: n + 1,
      cap: CONFLICT_RESOLUTION_ATTEMPT_CAP,
    });
    assert.deepEqual(rec.writes, [n + 1]);
  }
});

test("decideConflictFollowUp: at the cap ⇒ exhausted, no write", () => {
  const rec = fakeAttempts({ value: CONFLICT_RESOLUTION_ATTEMPT_CAP });
  const followUp = decideConflictFollowUp({ ...CHANGE, mergeable: false }, rec.attempts);
  assert.deepEqual(followUp, {
    kind: "exhausted",
    base: "main",
    attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP,
  });
  assert.deepEqual(rec.writes, []);
});

test('decideConflictFollowUp: base absent ⇒ ""', () => {
  const rec = fakeAttempts({ value: 0 });
  const followUp = decideConflictFollowUp({ pr: CHANGE.pr, mergeable: false }, rec.attempts);
  assert.equal(followUp.kind, "drive");
  assert.ok(followUp.kind === "drive" && followUp.base === "");
});

test("decideConflictFollowUp: an unpersisted increment withholds the dispatch (no drive)", () => {
  // The surface-uniform withhold posture: a `false` read-back means the counter is
  // unverifiable, and an unverifiable counter must never bypass the cap — the decision is
  // `withheld` (the adapter reports loudly, injects nothing). A THROWING read/write still
  // propagates — the 7.2-pinned load-bearing failure arm (recorded as unchanged).
  const rec = fakeAttempts({ value: 0, writeResult: false });
  const followUp = decideConflictFollowUp({ ...CHANGE, mergeable: false }, rec.attempts);
  assert.deepEqual(followUp, { kind: "withheld", base: "main" });
  assert.deepEqual(rec.writes, [1], "the write was attempted; its false result gates the drive");
});

// --- submitChange ---------------------------------------------------------------------------

test("submitChange: publish failure ⇒ publish_failed (no decide)", async () => {
  const rec = fakeAttempts({ value: 1 });
  const { d } = deps({
    attempt: { ok: false, message: "drift", errorType: "remote_drift" },
    attempts: rec.attempts,
  });
  assert.deepEqual(await submitChange(d), {
    kind: "publish_failed",
    message: "drift",
    errorType: "remote_drift",
  });
  assert.equal(rec.readCount(), 0);
});

test("submitChange: clean success ⇒ published with conflict none", async () => {
  const { d } = deps({ attempt: { ok: true, change: CHANGE } });
  assert.deepEqual(await submitChange(d), {
    kind: "published",
    change: CHANGE,
    conflict: { kind: "none" },
  });
});

test("submitChange: conflicted under cap ⇒ published with the drive decision (immediate timing)", async () => {
  const rec = fakeAttempts({ value: 0 });
  const change = { ...CHANGE, mergeable: false, conflicts: ["a.py"] };
  const { d } = deps({ attempt: { ok: true, change }, attempts: rec.attempts });
  assert.deepEqual(await submitChange(d), {
    kind: "published",
    change,
    conflict: { kind: "drive", base: "main", attempt: 1, cap: CONFLICT_RESOLUTION_ATTEMPT_CAP },
  });
  assert.deepEqual(rec.writes, [1], "no reset (conflicted), one increment");
});

test("submitChange: conflicted at cap ⇒ exhausted", async () => {
  const rec = fakeAttempts({ value: CONFLICT_RESOLUTION_ATTEMPT_CAP });
  const change = { ...CHANGE, mergeable: false };
  const { d } = deps({ attempt: { ok: true, change }, attempts: rec.attempts });
  const outcome = await submitChange(d);
  assert.ok(outcome.kind === "published");
  assert.deepEqual(outcome.conflict, {
    kind: "exhausted",
    base: "main",
    attempts: CONFLICT_RESOLUTION_ATTEMPT_CAP,
  });
  assert.deepEqual(rec.writes, []);
});
