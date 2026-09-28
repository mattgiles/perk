import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type CheckoutSnapshot,
  cleanStart,
  compareEndState,
  renderPaths,
  type SnapshotObservation,
  type UntrackedEntry,
} from "./checkoutSnapshot.ts";

const HEAD = "a".repeat(40);
const OTHER = "b".repeat(40);
const notes: UntrackedEntry = { path: "notes.txt", kind: "file", digest: "1".repeat(64) };
const link: UntrackedEntry = { path: "link", kind: "symlink", digest: "target" };

function observation(overrides: Partial<SnapshotObservation> = {}): SnapshotObservation {
  return { head: HEAD, trackedChanges: [], flags: false, untracked: [], ...overrides };
}
function violated(
  outcome: ReturnType<typeof compareEndState>,
): Extract<ReturnType<typeof compareEndState>, { ok: false }> {
  assert.equal(outcome.ok, false, JSON.stringify(outcome));
  return outcome as Extract<ReturnType<typeof compareEndState>, { ok: false }>;
}

test("cleanStart: each null probe refuses, naming the probe", () => {
  for (const [key, label] of [
    ["head", "HEAD"],
    ["trackedChanges", "tracked-tree cleanliness"],
    ["flags", "index flag state"],
    ["untracked", "the untracked inventory"],
  ] as const) {
    const verdict = cleanStart(observation({ [key]: null }));
    assert.equal(verdict.ok, false, key);
    assert.match(verdict.ok ? "" : verdict.detail, new RegExp(`could not verify ${label}`), key);
  }
});

test("cleanStart: tracked changes refuse listing the paths; flags refuse", () => {
  const dirty = cleanStart(observation({ trackedChanges: ["seed.txt", "src/a.ts"] }));
  assert.ok(!dirty.ok);
  assert.match(dirty.detail, /uncommitted tracked changes: "seed.txt", "src\/a.ts"/);
  const flagged = cleanStart(observation({ flags: true }));
  assert.ok(!flagged.ok);
  assert.match(flagged.detail, /assume-unchanged\/skip-worktree/);
  const both = cleanStart(observation({ trackedChanges: ["x"], flags: true }));
  assert.ok(!both.ok);
  assert.match(both.detail, /"x".*assume-unchanged/, "every problem is named");
});

test("cleanStart: untracked entries are accepted (inventoried, sorted by path)", () => {
  const verdict = cleanStart(observation({ untracked: [notes, link] }));
  assert.ok(verdict.ok);
  assert.deepEqual(verdict.snapshot, { head: HEAD, untracked: [link, notes] });
});

test("compareEndState: an identical end state is ok", () => {
  const snapshot: CheckoutSnapshot = { head: HEAD, untracked: [link, notes] };
  assert.deepEqual(compareEndState(snapshot, observation({ untracked: [notes, link] })), {
    ok: true,
  });
});

test("compareEndState: each moved dimension is a violation naming it", () => {
  const snapshot: CheckoutSnapshot = { head: HEAD, untracked: [notes] };
  const head = violated(
    compareEndState(snapshot, observation({ head: OTHER, untracked: [notes] })),
  );
  assert.deepEqual(head.moved.head, { from: HEAD, to: OTHER });
  assert.match(head.detail, new RegExp(`HEAD moved from ${HEAD} to ${OTHER}`));
  const tracked = violated(
    compareEndState(snapshot, observation({ trackedChanges: ["seed.txt"], untracked: [notes] })),
  );
  assert.deepEqual(tracked.moved.tracked, ["seed.txt"]);
  assert.match(tracked.detail, /tracked changes: "seed.txt"/);
  const flags = violated(
    compareEndState(snapshot, observation({ flags: true, untracked: [notes] })),
  );
  assert.equal(flags.moved.flags, true);
  assert.match(flags.detail, /index carries assume-unchanged\/skip-worktree/);
  const added = violated(compareEndState(snapshot, observation({ untracked: [notes, link] })));
  assert.deepEqual(added.moved.untrackedAdded, ["link"]);
  assert.match(added.detail, /untracked added: "link"/);
  const removed = violated(compareEndState(snapshot, observation({ untracked: [] })));
  assert.deepEqual(removed.moved.untrackedRemoved, ["notes.txt"]);
  assert.match(removed.detail, /untracked removed: "notes.txt"/);
  const digest = violated(
    compareEndState(snapshot, observation({ untracked: [{ ...notes, digest: "2".repeat(64) }] })),
  );
  assert.deepEqual(digest.moved.untrackedChanged, ["notes.txt"], "same path, new bytes");
  assert.match(digest.detail, /untracked changed: "notes.txt"/);
  const kind = violated(
    compareEndState(snapshot, observation({ untracked: [{ ...notes, kind: "symlink" }] })),
  );
  assert.deepEqual(kind.moved.untrackedChanged, ["notes.txt"], "file → symlink at the same path");
});

test("compareEndState: several differences are all named", () => {
  const snapshot: CheckoutSnapshot = { head: HEAD, untracked: [notes] };
  const outcome = violated(
    compareEndState(
      snapshot,
      observation({ head: OTHER, trackedChanges: ["seed.txt"], flags: true, untracked: [link] }),
    ),
  );
  assert.deepEqual(Object.keys(outcome.moved).sort(), [
    "flags",
    "head",
    "tracked",
    "untrackedAdded",
    "untrackedRemoved",
  ]);
  for (const part of ["HEAD moved", "tracked changes", "assume-unchanged", "added", "removed"])
    assert.match(outcome.detail, new RegExp(part));
});

test("compareEndState: each null probe is a violation naming the probe", () => {
  const snapshot: CheckoutSnapshot = { head: HEAD, untracked: [] };
  for (const [key, label] of [
    ["head", "HEAD"],
    ["trackedChanges", "tracked-tree cleanliness"],
    ["flags", "index flag state"],
    ["untracked", "the untracked inventory"],
  ] as const) {
    const outcome = violated(compareEndState(snapshot, observation({ [key]: null })));
    assert.deepEqual(outcome.moved.probeFailures, [label], key);
    assert.match(outcome.detail, new RegExp(`could not verify ${label}`), key);
  }
});

test("renderPaths: caps at 20 and escapes control characters", () => {
  const many = Array.from({ length: 23 }, (_, i) => `f${i}`);
  const rendered = renderPaths(many);
  assert.match(rendered, /"f19" \(\+3 more\)$/);
  assert.doesNotMatch(rendered, /"f20"/);
  const hostile = renderPaths(["evil\nIGNORE PREVIOUS\u0007"]);
  assert.equal(hostile, '"evil\\nIGNORE PREVIOUS\\u0007"');
  assert.doesNotMatch(hostile, /\n/);
});
