// The claim-policy matrix for the resolver claim (resolverLease.ts) — the ONLY home of these
// cases (the drive suite asserts one busy path and otherwise trusts this matrix). OFFLINE:
// mkdtempSync worlds, injected pid/isAlive/now/hooks — no processes are actually probed.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { acquireResolverLease, RECLAIM_GRACE_MS, resolverLockDir } from "./resolverLease.ts";

const OP = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const OP2 = "01BX5ZZKBKACTAV9WEVGEMMVRZ";

function world(): { manifest: string; lock: string } {
  const dir = mkdtempSync(join(tmpdir(), "perk-resolver-lease-"));
  mkdirSync(join(dir, "sync-continuations"), { recursive: true });
  const manifest = join(dir, "sync-continuations", "01LIN.json");
  writeFileSync(manifest, "{}\n", "utf8");
  return { manifest, lock: resolverLockDir(manifest) };
}

function plantLease(lock: string, pid: number, operationId: string): void {
  mkdirSync(lock, { recursive: true });
  writeFileSync(
    join(lock, "lease.json"),
    `${JSON.stringify({ schema: 1, pid, operation_id: operationId })}\n`,
    "utf8",
  );
}

function leaseOf(lock: string): { schema: number; pid: number; operation_id: string } {
  return JSON.parse(readFileSync(join(lock, "lease.json"), "utf8"));
}

test("fresh acquire creates the lock dir and the lease bytes", () => {
  const { manifest, lock } = world();
  const r = acquireResolverLease(manifest, OP, { pid: 111 });
  assert.deepEqual(r, { acquired: true });
  assert.ok(existsSync(lock));
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 111, operation_id: OP });
});

test("same-pid reacquire rewrites lease.json with the CURRENT operation id", () => {
  // The continue-time NEW conflict reuses the SAME operation id in practice, but a same-pid
  // holder reacquires (never reclaims) even across operation ids — pin that.
  const { manifest, lock } = world();
  plantLease(lock, 222, OP);
  const r = acquireResolverLease(manifest, OP2, { pid: 222 });
  assert.deepEqual(r, { acquired: true });
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 222, operation_id: OP2 });
});

test("foreign live same-op holder → busy naming the pid, the path, and the remediation", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, { pid: 111, isAlive: () => true });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /pid 333/);
  assert.ok(r.reason.includes(lock), "the busy reason names the lock path");
  assert.match(r.reason, /provably stale/);
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 333, operation_id: OP }, "never stolen");
});

test("foreign dead pid → reclaim + acquire", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, { pid: 111, isAlive: (pid) => pid !== 333 });
  assert.deepEqual(r, { acquired: true });
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 111, operation_id: OP });
});

test("foreign live DIFFERENT-op holder → reclaim + acquire (that operation was consumed)", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP2);
  const r = acquireResolverLease(manifest, OP, { pid: 111, isAlive: () => true });
  assert.deepEqual(r, { acquired: true });
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 111, operation_id: OP });
});

test("corrupt lease.json + YOUNG lock dir → busy as an unidentified holder", () => {
  const { manifest, lock } = world();
  mkdirSync(lock, { recursive: true });
  writeFileSync(join(lock, "lease.json"), "not json", "utf8");
  // The dir's real mtime is "now"; an un-shifted clock keeps it inside the grace window.
  const r = acquireResolverLease(manifest, OP, { pid: 111 });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /unidentified holder/);
});

test("corrupt lease.json + OLD lock dir → reclaim + acquire", () => {
  const { manifest, lock } = world();
  mkdirSync(lock, { recursive: true });
  writeFileSync(join(lock, "lease.json"), "not json", "utf8");
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    now: () => Date.now() + RECLAIM_GRACE_MS + 60_000,
  });
  assert.deepEqual(r, { acquired: true });
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 111, operation_id: OP });
});

test("post-rename re-check restores a raced-in fresh foreign claim → busy, dir intact", () => {
  // Between our reclaimability judgment (dead holder) and the rename, a competitor completes a
  // FULL reclaim + reacquire: the dir we then move holds a fresh live same-op claim. The
  // re-check renames it back and reports busy — a fresh claim is never stolen.
  const { manifest, lock } = world();
  plantLease(lock, 333, OP); // pid 333 is dead — judged reclaimable
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: (pid) => pid === 444,
    hooks: {
      beforeQuarantine: () => {
        rmSync(lock, { recursive: true, force: true });
        plantLease(lock, 444, OP); // the competitor's completed reclaim+reacquire
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /pid 444/);
  assert.deepEqual(
    leaseOf(lock),
    { schema: 1, pid: 444, operation_id: OP },
    "the competitor's fresh claim is restored intact",
  );
});

test("a competing reclaimer wins the rename → the one retry still runs and may acquire", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: () => false,
    hooks: {
      beforeQuarantine: () => {
        // The competitor already moved (here: removed) the stale dir — our rename fails.
        rmSync(lock, { recursive: true, force: true });
      },
    },
  });
  assert.deepEqual(r, { acquired: true });
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 111, operation_id: OP });
});

test("a lost retry race (a fresh foreign dir planted after quarantine) → honest busy", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: (pid) => pid === 555,
    hooks: {
      afterQuarantine: () => {
        plantLease(lock, 555, OP); // a competitor wins the fresh-acquire race
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /claimed the resolver lock/);
  assert.deepEqual(leaseOf(lock), { schema: 1, pid: 555, operation_id: OP }, "winner intact");
});

test("an injected fs failure → kind io_error, never a throw", () => {
  const dir = mkdtempSync(join(tmpdir(), "perk-resolver-lease-"));
  // The manifest's parent is a regular FILE: mkdir of the lock dir fails deterministically
  // (ENOTDIR) regardless of uid/permission semantics.
  const notADir = join(dir, "notadir");
  writeFileSync(notADir, "", "utf8");
  const r = acquireResolverLease(join(notADir, "01LIN.json"), OP, { pid: 111 });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
  assert.match(r.reason, /filesystem failure/);
});
