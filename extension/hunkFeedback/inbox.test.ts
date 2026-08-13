// The §8.58 delivery guarantees, exercised through the inbox's open/transport/close interface
// with injected timers + clock and a scripted transport — no sleeps, no real fs.watch.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { hunkConsumerLockDir, hunkDeliveredPath, hunkOutboxPath } from "../substrate/cache.ts";
import {
  BATCH_MAX_RECORDS,
  type ConsumerIdentity,
  createHunkFeedbackInbox,
  DEBOUNCE_MS,
  type FeedbackInboxHandle,
  type FeedbackTransport,
  type InboxTimers,
  type PassiveClaim,
  POLL_MS,
  type WatchFactory,
} from "./inbox.ts";
import { acquireLease, appendAcks, type FeedbackRecord, readDeliveredIds } from "./store.ts";

/** Deterministic timers + clock: tasks run in due order as the clock advances. */
class FakeTimers {
  private clock = 0;
  private nextId = 1;
  private tasks = new Map<number, { at: number; fn: () => void; interval: number | null }>();
  readonly now = () => this.clock;
  readonly timers: InboxTimers = {
    setTimeout: (fn, ms) => this.schedule(fn, ms, null),
    clearTimeout: (handle) => void this.tasks.delete(handle as number),
    setInterval: (fn, ms) => this.schedule(fn, ms, ms),
    clearInterval: (handle) => void this.tasks.delete(handle as number),
  };
  private schedule(fn: () => void, ms: number, interval: number | null): number {
    const id = this.nextId++;
    this.tasks.set(id, { at: this.clock + ms, fn, interval });
    return id;
  }
  advance(ms: number): void {
    const target = this.clock + ms;
    for (;;) {
      let dueId: number | null = null;
      let dueAt = Number.POSITIVE_INFINITY;
      for (const [id, task] of this.tasks) {
        if (task.at <= target && task.at < dueAt) {
          dueAt = task.at;
          dueId = id;
        }
      }
      if (dueId === null) break;
      const task = this.tasks.get(dueId);
      if (task === undefined) break;
      this.clock = task.at;
      if (task.interval !== null) task.at += task.interval;
      else this.tasks.delete(dueId);
      task.fn();
    }
    this.clock = target;
  }
  pendingCount(): number {
    return this.tasks.size;
  }
}

/** A scripted transport: observation is keyed by the batch's first feedback_id (the marker). */
class FakeTransport implements FeedbackTransport {
  injections: { at: number; ids: string[] }[] = [];
  observed = new Set<string>();
  idle = true;
  throwOnInject: Error | null = null;
  throwOnIsInjected: Error | null = null;
  private clockNow: () => number;
  constructor(clockNow: () => number) {
    this.clockNow = clockNow;
  }
  inject(batch: readonly FeedbackRecord[]): void {
    if (this.throwOnInject) throw this.throwOnInject;
    this.injections.push({ at: this.clockNow(), ids: batch.map((r) => r.feedback_id) });
  }
  isInjected(batch: readonly FeedbackRecord[]): boolean {
    if (this.throwOnIsInjected) throw this.throwOnIsInjected;
    return this.observed.has(batch[0]?.feedback_id ?? "");
  }
  isIdle(): boolean {
    return this.idle;
  }
  observeLast(): void {
    const last = this.injections.at(-1);
    if (last) this.observed.add(last.ids[0] ?? "");
  }
}

function record(n: number, overrides: Partial<FeedbackRecord> = {}): FeedbackRecord {
  return {
    schema: 1,
    feedback_id: `01WATCH:note-${n}`,
    watch_instance_id: "01WATCH",
    plan_id: "42",
    created_at: "2026-01-01T00:00:00.000Z",
    changeset_id: null,
    anchor: { file_path: "src/a.ts", hunk_index: 0, side: "new", line: n + 1 },
    body: `note body ${n}`,
    ...overrides,
  };
}

function appendOutbox(cwd: string, records: FeedbackRecord[]): void {
  const path = hunkOutboxPath(cwd);
  mkdirSync(join(path, ".."), { recursive: true });
  for (const r of records) appendFileSync(path, `${JSON.stringify(r)}\n`, "utf8");
}

interface Rig {
  cwd: string;
  fake: FakeTimers;
  transport: FakeTransport;
  reports: { severity: string; message: string }[];
  watches: { dir: string; onChange: () => void; onError: (error: unknown) => void }[];
  watcherCloses: number;
  identity: ConsumerIdentity;
  open(): FeedbackInboxHandle | PassiveClaim;
}

function rig(opts: { watchThrows?: boolean } = {}): Rig {
  const cwd = mkdtempSync(join(tmpdir(), "perk-hunk-inbox-"));
  const fake = new FakeTimers();
  const transport = new FakeTransport(fake.now);
  const reports: { severity: string; message: string }[] = [];
  const watches: Rig["watches"] = [];
  const state: Rig = {
    cwd,
    fake,
    transport,
    reports,
    watches,
    watcherCloses: 0,
    identity: { cwd, runId: "RID", piSessionId: "sess-1", planId: "42" },
    open: () => {
      const watch: WatchFactory = (dir, onChange, onError) => {
        if (opts.watchThrows) throw new Error("watch unavailable");
        watches.push({ dir, onChange, onError });
        return {
          close: () => {
            state.watcherCloses += 1;
          },
        };
      };
      const inbox = createHunkFeedbackInbox({
        now: fake.now,
        timers: fake.timers,
        watch,
        report: (severity, message) => reports.push({ severity, message }),
      });
      return inbox.open(state.identity, transport);
    },
  };
  return state;
}

function assertOwned(result: FeedbackInboxHandle | PassiveClaim): FeedbackInboxHandle {
  assert.ok(!("passive" in result), "expected an owned inbox handle");
  return result;
}

// --- drain + observation-based acknowledgement -----------------------------------------------

test("open drains immediately and acks only after the entry is OBSERVED on the branch", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  const handle = assertOwned(r.open());

  // Drain-now: injected without any timer advance; NOT yet acknowledged (no observation).
  assert.equal(r.transport.injections.length, 1);
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set());

  // A poll tick without observation (busy session) acks nothing.
  r.transport.idle = false;
  r.fake.advance(POLL_MS);
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set());

  // Observation → acknowledgement on the next poll tick.
  r.transport.observeLast();
  r.fake.advance(POLL_MS);
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set(["01WATCH:note-1"]));
  handle.close();
});

test("exactly one unacknowledged batch: new records during awaiting only mark dirty", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  const handle = assertOwned(r.open());
  assert.equal(r.transport.injections.length, 1);

  // New feedback arrives while the first batch awaits observation.
  appendOutbox(r.cwd, [record(2)]);
  r.watches[0]?.onChange();
  r.fake.advance(DEBOUNCE_MS);
  assert.equal(r.transport.injections.length, 1); // pinned: no second injection

  // Busy poll ticks do not inject either.
  r.transport.idle = false;
  r.fake.advance(POLL_MS * 2);
  assert.equal(r.transport.injections.length, 1);

  // Observation acks batch 1 and the dirty flag dispatches batch 2 immediately.
  r.transport.observeLast();
  r.fake.advance(POLL_MS);
  assert.equal(r.transport.injections.length, 2);
  assert.deepEqual(r.transport.injections[1]?.ids, ["01WATCH:note-2"]);
  handle.close();
});

test("batches are bounded and append-ordered; the remainder re-marks dirty", () => {
  const r = rig();
  appendOutbox(
    r.cwd,
    Array.from({ length: 12 }, (_, i) => record(i)),
  );
  const handle = assertOwned(r.open());

  assert.equal(r.transport.injections.length, 1);
  assert.equal(r.transport.injections[0]?.ids.length, BATCH_MAX_RECORDS);
  assert.deepEqual(
    r.transport.injections[0]?.ids,
    Array.from({ length: 10 }, (_, i) => `01WATCH:note-${i}`),
  );

  r.transport.observeLast();
  r.fake.advance(POLL_MS);
  assert.equal(r.transport.injections.length, 2);
  assert.deepEqual(r.transport.injections[1]?.ids, ["01WATCH:note-10", "01WATCH:note-11"]);
  handle.close();
});

test("the byte bound splits a batch before 48 KiB of raw body bytes (pre-render)", () => {
  const r = rig();
  const big = "x".repeat(20 * 1024);
  appendOutbox(r.cwd, [
    record(0, { body: big }),
    record(1, { body: big }),
    record(2, { body: big }),
  ]);
  const handle = assertOwned(r.open());
  assert.deepEqual(r.transport.injections[0]?.ids, ["01WATCH:note-0", "01WATCH:note-1"]);
  r.transport.observeLast();
  r.fake.advance(POLL_MS);
  assert.deepEqual(r.transport.injections[1]?.ids, ["01WATCH:note-2"]);
  handle.close();
});

test("watcher events debounce-coalesce into one dispatch", () => {
  const r = rig();
  const handle = assertOwned(r.open());
  assert.equal(r.transport.injections.length, 0);

  appendOutbox(r.cwd, [record(1)]);
  r.watches[0]?.onChange();
  r.fake.advance(DEBOUNCE_MS - 200);
  assert.equal(r.transport.injections.length, 0); // still inside the debounce window
  r.watches[0]?.onChange(); // resets the window
  r.fake.advance(DEBOUNCE_MS - 200);
  assert.equal(r.transport.injections.length, 0);
  r.fake.advance(200);
  assert.equal(r.transport.injections.length, 1);
  handle.close();
});

// --- backoff ----------------------------------------------------------------------------------

test("demotion re-dispatches the same ids and backoff doubles until observation resets it", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  const handle = assertOwned(r.open());
  r.transport.idle = true; // idle with no observed entry = the abort/failed-turn arm

  // t=0 inject#1; t=10s demote→backoff 1s; t=11s inject#2; t=30s demote→backoff 2s;
  // t=32s inject#3; t=50s demote→backoff 4s; t=54s inject#4.
  r.fake.advance(60_000);
  assert.deepEqual(
    r.transport.injections.map((i) => i.at),
    [0, 11_000, 32_000, 54_000],
  );
  // The demoted batch re-dispatches the SAME ids — duplicates possible, loss not.
  for (const injection of r.transport.injections) {
    assert.deepEqual(injection.ids, ["01WATCH:note-1"]);
  }

  // Observation acks and RESETS backoff (the only reset site).
  r.transport.observeLast();
  r.fake.advance(10_000); // t=70s poll: observed → acknowledged
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set(["01WATCH:note-1"]));

  // A fresh record failing again starts back at the 1 s base — proof the reset happened.
  appendOutbox(r.cwd, [record(2)]);
  const before = r.transport.injections.length;
  r.fake.advance(10_000); // poll dispatches inject at t=80s
  assert.equal(r.transport.injections[before]?.at, 80_000);
  r.fake.advance(10_000); // t=90s: demote (age 10s) → backoff 1s
  r.fake.advance(1_000); // t=91s: re-dispatch
  assert.equal(r.transport.injections.at(-1)?.at, 91_000);
  handle.close();
});

test("a synchronous inject throw routes through backoff (and doubles while it persists)", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  r.transport.throwOnInject = new Error("queue refused");
  const handle = assertOwned(r.open());

  assert.equal(r.transport.injections.length, 0);
  assert.ok(r.reports.some((rep) => rep.message.includes("injection refused synchronously")));

  // Backoff-owned retries at 1s, then +2s, then +4s — all still throwing.
  const throwCount = () =>
    r.reports.filter((rep) => rep.message.includes("injection refused")).length;
  assert.equal(throwCount(), 1);
  r.fake.advance(1_000);
  assert.equal(throwCount(), 2);
  r.fake.advance(2_000);
  assert.equal(throwCount(), 3);
  r.fake.advance(4_000);
  assert.equal(throwCount(), 4);

  // Recovery: the throw clears, the next backoff dispatch injects.
  r.transport.throwOnInject = null;
  r.fake.advance(8_000);
  assert.equal(r.transport.injections.length, 1);
  handle.close();
});

test("a batch already observed on the branch is acked WITHOUT re-injection", () => {
  const r = rig();
  const rec = record(1);
  appendOutbox(r.cwd, [rec]);
  r.transport.observed.add(rec.feedback_id); // a prior injection survives on this branch
  const handle = assertOwned(r.open());
  assert.equal(r.transport.injections.length, 0);
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set([rec.feedback_id]));
  handle.close();
});

// --- suppression + holds ------------------------------------------------------------------------

test("an ack-append failure warns but still suppresses same-session redelivery", () => {
  const r = rig();
  const rec = record(1);
  appendOutbox(r.cwd, [rec]);
  // A directory at the delivered path makes the append fail (EISDIR).
  mkdirSync(hunkDeliveredPath(r.cwd), { recursive: true });
  r.transport.observed.add(rec.feedback_id);
  const handle = assertOwned(r.open());

  assert.equal(r.transport.injections.length, 0); // acked via observation, no re-injection
  const warnings = r.reports.filter((rep) => rep.message.includes("could not append feedback"));
  assert.equal(warnings.length, 1);
  // Same-session redelivery stays suppressed in memory across later polls.
  r.fake.advance(POLL_MS * 3);
  assert.equal(r.transport.injections.length, 0);
  handle.close();
});

test("delivered ids never re-batch", () => {
  const r = rig();
  const rec = record(1);
  appendOutbox(r.cwd, [rec]);
  appendAcks(r.cwd, [
    {
      schema: 1,
      feedback_id: rec.feedback_id,
      delivered_at: "2026-01-01T00:00:00.000Z",
      run_id: "RID-prior",
      pi_session_id: "sess-prior",
    },
  ]);
  const handle = assertOwned(r.open());
  r.fake.advance(POLL_MS * 2);
  assert.equal(r.transport.injections.length, 0);
  handle.close();
});

test("a plan_id mismatch is held with a once-per-id warning — never delivered, never acked", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1, { plan_id: "99" })]);
  const handle = assertOwned(r.open());
  r.fake.advance(POLL_MS * 3);
  assert.equal(r.transport.injections.length, 0);
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set());
  const holds = r.reports.filter((rep) => rep.message.includes("holding feedback"));
  assert.equal(holds.length, 1); // warned once per id, not once per poll
  assert.match(holds[0]?.message ?? "", /plan 99.*plan 42/);
  handle.close();
});

// --- provenance + read-failure arms --------------------------------------------------------------

test("a git-TRACKED file under hunk-watch/ refuses to open (checkout-supplied feedback)", () => {
  const r = rig();
  const g = (...args: string[]) => execFileSync("git", args, { cwd: r.cwd, stdio: "ignore" });
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  appendOutbox(r.cwd, [record(1)]);
  g("add", "-f", ".perk/workflow/hunk-watch/outbox.ndjson"); // the force-tracked attack shape
  const result = r.open();
  assert.ok("passive" in result);
  assert.match(result.reason, /tracked file\(s\) under \.perk\/workflow\/hunk-watch/);
  assert.ok(r.reports.some((rep) => rep.severity === "error" && rep.message.includes("tracked")));
  assert.equal(r.transport.injections.length, 0); // nothing under the family was read
});

test("an unreadable outbox (non-missing) is reported once — never a silent stall", () => {
  const r = rig();
  mkdirSync(hunkOutboxPath(r.cwd), { recursive: true }); // a DIRECTORY at the outbox → EISDIR
  const handle = assertOwned(r.open());
  r.fake.advance(POLL_MS * 3);
  const warnings = r.reports.filter((rep) =>
    rep.message.includes("could not read the feedback outbox"),
  );
  assert.equal(warnings.length, 1); // reported once, polling continues
  handle.close();
});

// --- lease arms ---------------------------------------------------------------------------------

test("a fresh foreign lease yields a passive claim (never stolen)", () => {
  const r = rig();
  const foreign = acquireLease(
    hunkConsumerLockDir(r.cwd),
    { runId: "OTHER", piSessionId: "sess-other" },
    r.fake.now,
  );
  assert.ok(foreign.owned);
  const result = r.open();
  assert.ok("passive" in result);
  assert.match(result.reason, /another live implement session/);
});

test("a lease verification failure closes the inbox fail-closed", () => {
  const r = rig();
  const handle = assertOwned(r.open());
  // The lease vanishes from under us (a reclaimer raced) — the next dispatch must refuse.
  rmSync(hunkConsumerLockDir(r.cwd), { recursive: true, force: true });
  appendOutbox(r.cwd, [record(1)]);
  r.fake.advance(POLL_MS);
  assert.equal(r.transport.injections.length, 0);
  assert.ok(r.reports.some((rep) => rep.message.includes("lease verification failed")));
  // Closed: every timer disposed, later polls impossible.
  assert.equal(r.fake.pendingCount(), 0);
  assert.equal(r.watcherCloses, 1);
  handle.close(); // idempotent
});

// --- failure containment -----------------------------------------------------------------------

test("a watcher error degrades permanently to poll-only (which still delivers)", () => {
  const r = rig();
  const handle = assertOwned(r.open());
  r.watches[0]?.onError(new Error("inotify budget"));
  assert.ok(r.reports.some((rep) => rep.message.includes("watcher failed")));
  assert.equal(r.watcherCloses, 1);

  appendOutbox(r.cwd, [record(1)]);
  r.fake.advance(POLL_MS); // no watch event — the poll is the correctness path
  assert.equal(r.transport.injections.length, 1);
  handle.close();
});

test("a watcher construction failure reports once and continues poll-only", () => {
  const r = rig({ watchThrows: true });
  const handle = assertOwned(r.open());
  assert.ok(r.reports.some((rep) => rep.message.includes("could not watch")));
  appendOutbox(r.cwd, [record(1)]);
  r.fake.advance(POLL_MS);
  assert.equal(r.transport.injections.length, 1);
  handle.close();
});

test("a poll-tick exception is reported once per distinct message and polling continues", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  const handle = assertOwned(r.open());
  r.transport.throwOnIsInjected = new Error("branch scan exploded");
  r.fake.advance(POLL_MS * 3);
  const errors = r.reports.filter((rep) => rep.message.includes("branch scan exploded"));
  assert.equal(errors.length, 1); // once per distinct message, never a spin of reports

  r.transport.throwOnIsInjected = null;
  r.transport.observeLast();
  r.fake.advance(POLL_MS); // polling survived — observation still acknowledges
  assert.deepEqual(readDeliveredIds(hunkDeliveredPath(r.cwd)).ids, new Set(["01WATCH:note-1"]));
  handle.close();
});

test("read warnings (malformed outbox lines) are reported once, not once per poll", () => {
  const r = rig();
  const path = hunkOutboxPath(r.cwd);
  mkdirSync(join(path, ".."), { recursive: true });
  appendFileSync(path, "{not json\n", "utf8");
  const handle = assertOwned(r.open());
  r.fake.advance(POLL_MS * 3);
  const warnings = r.reports.filter((rep) => rep.message.includes("malformed outbox line"));
  assert.equal(warnings.length, 1);
  handle.close();
});

// --- disposal -----------------------------------------------------------------------------------

test("close disposes watcher, timers, and the owned lease — idempotently", () => {
  const r = rig();
  appendOutbox(r.cwd, [record(1)]);
  const handle = assertOwned(r.open());
  assert.ok(existsSync(hunkConsumerLockDir(r.cwd)));

  handle.close();
  assert.equal(r.fake.pendingCount(), 0);
  assert.equal(r.watcherCloses, 1);
  assert.ok(!existsSync(hunkConsumerLockDir(r.cwd))); // token matched → released

  handle.close(); // idempotent
  assert.equal(r.watcherCloses, 1);

  // A closed inbox never dispatches again.
  appendOutbox(r.cwd, [record(2)]);
  r.fake.advance(POLL_MS * 2);
  assert.equal(r.transport.injections.length, 1);
});

test("heartbeat renewal keeps the lease fresh; a heartbeat failure reports without closing", () => {
  const r = rig();
  const handle = assertOwned(r.open());
  // Break the lease file's token by re-acquiring under the same identity elsewhere: the
  // idempotent reacquire rewrites a FRESH token, so OUR heartbeat now fails (lease lost).
  const stolen = acquireLease(
    hunkConsumerLockDir(r.cwd),
    { runId: "RID", piSessionId: "sess-1" },
    r.fake.now,
  );
  assert.ok(stolen.owned);
  r.fake.advance(5_000); // one heartbeat tick
  assert.ok(r.reports.some((rep) => rep.message.includes("heartbeat failed")));
  handle.close();
});
