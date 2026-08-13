// The §8.58 file contract: lenient NDJSON reads, the ack appender, and the consumer lease
// (atomic acquisition, token fencing, injected-clock staleness, quarantine recovery). All
// clocks are injected — no sleeps anywhere.

import assert from "node:assert/strict";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { hunkDeliveredPath } from "../substrate/cache.ts";
import {
  acquireLease,
  appendAcks,
  type DeliveryAck,
  type FeedbackRecord,
  type LeaseAcquisition,
  readDeliveredIds,
  readOutbox,
  releaseLease,
  renewHeartbeat,
  STALE_LEASE_MS,
  sweepQuarantine,
  verifyLease,
} from "./store.ts";

function tmp(): string {
  // realpath'd: the ack appender canonicalizes the family path against the cwd (macOS /tmp is
  // itself a symlink and must stay legal — only symlinks INSIDE the family are refused).
  return realpathSync(mkdtempSync(join(tmpdir(), "perk-hunk-store-")));
}

function record(overrides: Partial<FeedbackRecord> = {}): FeedbackRecord {
  return {
    schema: 1,
    feedback_id: "01WATCH:note-1",
    watch_instance_id: "01WATCH",
    plan_id: "42",
    created_at: "2026-01-01T00:00:00.000Z",
    changeset_id: "cs-1",
    anchor: { file_path: "src/a.ts", hunk_index: 0, side: "new", line: 12 },
    body: "rename this helper",
    ...overrides,
  };
}

function writeLines(path: string, lines: string[], opts: { trailingLf?: boolean } = {}): void {
  const content = lines.join("\n") + (opts.trailingLf === false ? "" : "\n");
  writeFileSync(path, content, "utf8");
}

// --- readOutbox -----------------------------------------------------------------------------

test("readOutbox: missing file is the normal no-feedback state", () => {
  const read = readOutbox(join(tmp(), "outbox.ndjson"));
  assert.deepEqual(read, { records: [], held: 0, warnings: [] });
});

test("readOutbox: valid records round-trip in append order", () => {
  const path = join(tmp(), "outbox.ndjson");
  const a = record({ feedback_id: "w:1" });
  const b = record({ feedback_id: "w:2", body: "second", changeset_id: null });
  writeLines(path, [JSON.stringify(a), JSON.stringify(b)]);
  const read = readOutbox(path);
  assert.deepEqual(read.records, [a, b]);
  assert.equal(read.held, 0);
  assert.deepEqual(read.warnings, []);
});

test("readOutbox: a trailing partial line is held, prior complete records read fine", () => {
  const path = join(tmp(), "outbox.ndjson");
  const a = record({ feedback_id: "w:1" });
  writeFileSync(path, `${JSON.stringify(a)}\n{"schema":1,"feedback_id":"w:2","bo`, "utf8");
  const read = readOutbox(path);
  assert.deepEqual(read.records, [a]);
  assert.equal(read.held, 1);
  assert.deepEqual(read.warnings, []); // held, never warned — a concurrent append in flight
});

test("readOutbox: a malformed complete line is skipped with a warning, isolation intact", () => {
  const path = join(tmp(), "outbox.ndjson");
  const a = record({ feedback_id: "w:1" });
  const b = record({ feedback_id: "w:2" });
  writeLines(path, [JSON.stringify(a), "{not json at all", JSON.stringify(b)]);
  const read = readOutbox(path);
  assert.deepEqual(
    read.records.map((r) => r.feedback_id),
    ["w:1", "w:2"],
  );
  assert.equal(read.warnings.length, 1);
  assert.match(read.warnings[0] as string, /malformed outbox line/);
});

test("readOutbox: structurally invalid records are refused (never delivered half-shaped)", () => {
  const path = join(tmp(), "outbox.ndjson");
  const bad = [
    { ...record(), body: "" }, // empty body
    { ...record(), feedback_id: "" }, // empty id
    { ...record(), anchor: { file_path: "a", hunk_index: -1, side: "new", line: 1 } },
    { ...record(), anchor: { file_path: "a", hunk_index: 0, side: "both", line: 1 } },
    { ...record(), anchor: { file_path: "a", hunk_index: 0, side: "new", line: 0 } },
    { ...record(), anchor: { file_path: "a", hunk_index: 0.5, side: "new", line: 1 } },
    { ...record(), changeset_id: 7 },
    "just a string",
  ];
  writeLines(
    path,
    bad.map((entry) => JSON.stringify(entry)),
  );
  const read = readOutbox(path);
  assert.deepEqual(read.records, []);
  assert.equal(read.warnings.length, bad.length);
});

test("readOutbox: an unknown schema is HELD with a loud version warning, never skipped", () => {
  const path = join(tmp(), "outbox.ndjson");
  writeLines(path, [JSON.stringify({ ...record({ feedback_id: "w:9" }), schema: 2 })]);
  const read = readOutbox(path);
  assert.deepEqual(read.records, []);
  assert.equal(read.held, 1);
  assert.equal(read.warnings.length, 1);
  assert.match(read.warnings[0] as string, /unknown schema 2/);
});

test("readOutbox: a non-missing read failure warns (never a silent empty stream)", () => {
  const dir = tmp();
  const path = join(dir, "outbox.ndjson");
  mkdirSync(path); // a directory at the outbox path → EISDIR on read
  const read = readOutbox(path);
  assert.deepEqual(read.records, []);
  assert.equal(read.warnings.length, 1);
  assert.match(read.warnings[0] as string, /could not read the feedback outbox/);
});

test("readOutbox: duplicate ids collapse silently; conflicting bytes report corruption", () => {
  const path = join(tmp(), "outbox.ndjson");
  const a = record({ feedback_id: "w:1" });
  const conflicting = record({ feedback_id: "w:1", body: "DIFFERENT body" });
  writeLines(path, [JSON.stringify(a), JSON.stringify(a), JSON.stringify(conflicting)]);
  const read = readOutbox(path);
  assert.deepEqual(read.records, [a]); // first valid record wins
  assert.equal(read.warnings.length, 1); // the identical duplicate was silent
  assert.match(read.warnings[0] as string, /conflicting bytes for feedback_id w:1/);
});

// --- readDeliveredIds / appendAcks ------------------------------------------------------------

const ACK: DeliveryAck = {
  schema: 1,
  feedback_id: "w:1",
  delivered_at: "2026-01-01T00:00:00.000Z",
  run_id: "RID",
  pi_session_id: "sess",
};

test("delivered ids: missing file is empty; duplicates collapse; malformed lines warn", () => {
  const dir = tmp();
  const path = join(dir, "delivered.ndjson");
  assert.deepEqual(readDeliveredIds(path), { ids: new Set(), warnings: [] });
  writeLines(path, [
    JSON.stringify(ACK),
    JSON.stringify(ACK),
    "{torn",
    JSON.stringify({ ...ACK, feedback_id: "w:2" }),
  ]);
  const read = readDeliveredIds(path);
  assert.deepEqual(read.ids, new Set(["w:1", "w:2"]));
  assert.equal(read.warnings.length, 1);
  assert.match(read.warnings[0] as string, /malformed acknowledgement/);
});

test("delivered ids: only structurally valid schema-1 acks count (v1 validation)", () => {
  // An unknown ack schema or a half-shaped line must NEVER suppress delivery — the safe
  // direction is a duplicate redelivery, never silent suppression.
  const dir = tmp();
  const path = join(dir, "delivered.ndjson");
  writeLines(path, [
    JSON.stringify({ ...ACK, schema: 2 }), // unknown version → ignored + version warning
    JSON.stringify({ schema: 1, feedback_id: "w:3" }), // missing v1 fields → invalid
    JSON.stringify({ ...ACK, feedback_id: "" }), // empty id → invalid
    JSON.stringify({ ...ACK, feedback_id: "w:4" }), // valid v1
  ]);
  const read = readDeliveredIds(path);
  assert.deepEqual(read.ids, new Set(["w:4"]));
  assert.equal(read.warnings.length, 3);
  assert.match(read.warnings[0] as string, /unknown schema 2/);
  assert.match(read.warnings[1] as string, /structurally invalid acknowledgement/);
});

test("delivered ids: a non-missing read failure warns and suppresses nothing", () => {
  const dir = tmp();
  const path = join(dir, "delivered.ndjson");
  mkdirSync(path); // EISDIR
  const read = readDeliveredIds(path);
  assert.deepEqual(read.ids, new Set());
  assert.equal(read.warnings.length, 1);
  assert.match(read.warnings[0] as string, /could not read the feedback acknowledgements/);
});

test("appendAcks: creates the dir, appends one complete LF-terminated line per ack", () => {
  const cwd = tmp();
  const path = hunkDeliveredPath(cwd);
  appendAcks(cwd, [ACK, { ...ACK, feedback_id: "w:2" }]);
  const content = readFileSync(path, "utf8");
  assert.equal(content.split("\n").length, 3); // two lines + trailing empty
  assert.ok(content.endsWith("\n"));
  assert.deepEqual(readDeliveredIds(path).ids, new Set(["w:1", "w:2"]));
  // Appending is additive — a second call never truncates.
  appendAcks(cwd, [{ ...ACK, feedback_id: "w:3" }]);
  assert.deepEqual(readDeliveredIds(path).ids, new Set(["w:1", "w:2", "w:3"]));
});

test("appendAcks: a symlinked delivered file is refused (nothing written through it)", () => {
  const cwd = tmp();
  const path = hunkDeliveredPath(cwd);
  mkdirSync(join(path, ".."), { recursive: true });
  const elsewhere = join(cwd, "exfil.ndjson");
  writeFileSync(elsewhere, "", "utf8");
  symlinkSync(elsewhere, path);
  assert.throws(() => appendAcks(cwd, [ACK]), /symlinked append target/);
  assert.equal(readFileSync(elsewhere, "utf8"), ""); // nothing escaped the family dir
});

test("appendAcks: a symlinked hunk-watch dir is refused", () => {
  const cwd = tmp();
  const real = join(cwd, "elsewhere");
  mkdirSync(real, { recursive: true });
  mkdirSync(join(cwd, ".perk", "workflow"), { recursive: true });
  symlinkSync(real, join(cwd, ".perk", "workflow", "hunk-watch"));
  assert.throws(() => appendAcks(cwd, [ACK]), /symlinked hunk-watch dir/);
});

// --- the consumer lease -----------------------------------------------------------------------

const IDENTITY = { runId: "RID", piSessionId: "sess-1" };
const OTHER = { runId: "RID-2", piSessionId: "sess-2" };

function lockDirIn(dir: string): string {
  return join(dir, "hunk-watch", "consumer.lock");
}

test("lease: fresh acquisition owns; a fresh foreign lease is passive (never stolen)", () => {
  const lockDir = lockDirIn(tmp());
  let clock = 1_000_000;
  const now = () => clock;
  const first = acquireLease(lockDir, IDENTITY, now);
  assert.ok(first.owned);
  assert.ok(verifyLease(lockDir, first.token));

  clock += 1_000; // well within the stale threshold
  const second = acquireLease(lockDir, OTHER, now);
  assert.ok(!second.owned);
  assert.match(second.reason, /another live implement session/);
  // The original holder's token is untouched.
  assert.ok(verifyLease(lockDir, first.token));
});

test("lease: same-identity reacquire is idempotent and fences with a FRESH token", () => {
  const lockDir = lockDirIn(tmp());
  const now = () => 1_000_000;
  const first = acquireLease(lockDir, IDENTITY, now);
  assert.ok(first.owned);
  const again = acquireLease(lockDir, IDENTITY, now);
  assert.ok(again.owned);
  assert.notEqual(again.token, first.token); // the predecessor instance is retired
  assert.ok(verifyLease(lockDir, again.token));
  assert.ok(!verifyLease(lockDir, first.token));
});

test("lease: a stale heartbeat is reclaimed (quarantine + fresh acquire, quarantine removed)", () => {
  const dir = tmp();
  const lockDir = lockDirIn(dir);
  let clock = 1_000_000;
  const now = () => clock;
  const dead = acquireLease(lockDir, OTHER, now);
  assert.ok(dead.owned);

  clock += STALE_LEASE_MS + 1;
  const reclaimed = acquireLease(lockDir, IDENTITY, now);
  assert.ok(reclaimed.owned);
  assert.ok(verifyLease(lockDir, reclaimed.token));
  // The winner best-effort-removed its quarantine dir.
  const leftovers = readdirSync(join(dir, "hunk-watch")).filter((e) => e.includes(".stale-"));
  assert.deepEqual(leftovers, []);
});

test("lease: a heartbeat renewal keeps a live lease fresh past the threshold", () => {
  const lockDir = lockDirIn(tmp());
  let clock = 1_000_000;
  const now = () => clock;
  const holder = acquireLease(lockDir, OTHER, now);
  assert.ok(holder.owned);

  clock += STALE_LEASE_MS - 1;
  renewHeartbeat(lockDir, holder.token, now);
  clock += STALE_LEASE_MS - 1; // stale relative to claim, fresh relative to the renewal
  const contender = acquireLease(lockDir, IDENTITY, now);
  assert.ok(!contender.owned);
});

test("lease: a corrupt lease.json falls back to the lock-dir mtime for staleness", () => {
  const lockDir = lockDirIn(tmp());
  mkdirSync(lockDir, { recursive: true });
  writeFileSync(join(lockDir, "lease.json"), "{torn", "utf8");
  // A freshly created dir has a fresh mtime — passive under an injected far-future-free clock.
  const passive = acquireLease(lockDir, IDENTITY, () => Date.now());
  assert.ok(!passive.owned);
  // With the clock pushed past the stale threshold the corrupt lease is reclaimed.
  const reclaimed = acquireLease(lockDir, IDENTITY, () => Date.now() + STALE_LEASE_MS + 1_000);
  assert.ok(reclaimed.owned);
});

test("lease: renewHeartbeat throws on a lost/foreign token (the caller reports)", () => {
  const lockDir = lockDirIn(tmp());
  const now = () => 1_000_000;
  const holder = acquireLease(lockDir, IDENTITY, now);
  assert.ok(holder.owned);
  assert.throws(() => renewHeartbeat(lockDir, "not-the-token", now), /lease lost/);
});

test("lease: release removes only on token match; verify fails closed afterwards", () => {
  const lockDir = lockDirIn(tmp());
  const now = () => 1_000_000;
  const holder = acquireLease(lockDir, IDENTITY, now);
  assert.ok(holder.owned);

  releaseLease(lockDir, "wrong-token"); // no-op
  assert.ok(existsSync(lockDir));
  assert.ok(verifyLease(lockDir, holder.token));

  releaseLease(lockDir, holder.token);
  assert.ok(!existsSync(lockDir));
  assert.ok(!verifyLease(lockDir, holder.token)); // fail-closed on the missing dir
  releaseLease(lockDir, holder.token); // idempotent
});

test("lease: competing reclaimers — the rename WINNER can lose the acquisition (one owner)", () => {
  // The true interleaving, driven deterministically via the race hooks: both contenders see
  // the stale lease; A wins the quarantine rename, but B runs its whole acquisition inside
  // A's rename→retry window (the dir is gone, so B fresh-acquires immediately). A's one retry
  // then hits EEXIST — exactly one owner, and it is the rename LOSER.
  const dir = tmp();
  const lockDir = lockDirIn(dir);
  let clock = 1_000_000;
  const now = () => clock;
  assert.ok(acquireLease(lockDir, OTHER, now).owned);
  clock += STALE_LEASE_MS + 1;

  let b: LeaseAcquisition | null = null;
  const a = acquireLease(lockDir, IDENTITY, now, {
    afterQuarantine: () => {
      b = acquireLease(lockDir, { runId: "RID-3", piSessionId: "sess-3" }, now);
    },
  });
  const winner = b as LeaseAcquisition | null;
  assert.ok(winner?.owned, "B (in the window) must own");
  assert.ok(!a.owned, "A (the rename winner) must converge to passive");
  assert.match(a.reason, /reclaimed the stale feedback lease first/);
  assert.ok(verifyLease(lockDir, winner.token));
  // A (the loser) still cleaned up ITS quarantine dir on the way out.
  const leftovers = readdirSync(join(dir, "hunk-watch")).filter((e) => e.includes(".stale-"));
  assert.deepEqual(leftovers, []);
});

test("lease: competing reclaimers — the rename LOSER retries into passivity (one owner)", () => {
  // The mirror interleaving: B completes the WHOLE reclaim (rename + fresh acquire) inside
  // A's stale-observation→rename window. A's rename then fails (the dead dir is gone) and
  // A's one fresh-acquire retry hits B's new lease → passive.
  const dir = tmp();
  const lockDir = lockDirIn(dir);
  let clock = 1_000_000;
  const now = () => clock;
  assert.ok(acquireLease(lockDir, OTHER, now).owned);
  clock += STALE_LEASE_MS + 1;

  let b: LeaseAcquisition | null = null;
  const a = acquireLease(lockDir, IDENTITY, now, {
    beforeQuarantine: () => {
      b = acquireLease(lockDir, { runId: "RID-3", piSessionId: "sess-3" }, now);
    },
  });
  const winner = b as LeaseAcquisition | null;
  assert.ok(winner?.owned, "B (the completed reclaim) must own");
  assert.ok(!a.owned, "A must stay passive after losing both the rename and the retry");
  assert.ok(verifyLease(lockDir, winner.token));
  const leftovers = readdirSync(join(dir, "hunk-watch")).filter((e) => e.includes(".stale-"));
  assert.deepEqual(leftovers, []);
});

test("lease: renewHeartbeat detects a lock-dir replacement (inode fence)", () => {
  const lockDir = lockDirIn(tmp());
  let clock = 1_000_000;
  const now = () => clock;
  const holder = acquireLease(lockDir, IDENTITY, now);
  assert.ok(holder.owned);
  // A reclaimer replaces the directory wholesale (rename away + fresh mkdir): the directory
  // identity changed, so the holder's renew must throw — whether via the token check or the
  // inode fence — and never resurrect its claim.
  clock += STALE_LEASE_MS + 1;
  const successor = acquireLease(lockDir, { runId: "RID-9", piSessionId: "sess-9" }, now);
  assert.ok(successor.owned);
  assert.throws(() => renewHeartbeat(lockDir, holder.token, now), /lease lost|fencing lost/);
  assert.ok(verifyLease(lockDir, successor.token)); // the successor's lease is intact
});

test("sweepQuarantine: removes leftover consumer.lock.stale-* dirs, leaves everything else", () => {
  const dir = tmp();
  const lockDir = lockDirIn(dir);
  const watchDir = join(dir, "hunk-watch");
  mkdirSync(join(watchDir, "consumer.lock.stale-abc"), { recursive: true });
  writeFileSync(join(watchDir, "consumer.lock.stale-abc", "lease.json"), "{}", "utf8");
  mkdirSync(join(watchDir, "consumer.lock.stale-def"), { recursive: true });
  appendFileSync(join(watchDir, "outbox.ndjson"), "", "utf8");
  const warnings = sweepQuarantine(lockDir);
  assert.deepEqual(warnings, []);
  assert.deepEqual(readdirSync(watchDir).sort(), ["outbox.ndjson"]);
});

test("sweepQuarantine: a missing parent dir sweeps nothing, warns nothing", () => {
  assert.deepEqual(sweepQuarantine(lockDirIn(tmp())), []);
});
