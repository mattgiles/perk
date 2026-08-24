// The claim-policy matrix for the resolver claim (resolverLease.ts) — the ONLY home of these
// cases (the drive suite asserts one busy path and otherwise trusts this matrix). OFFLINE:
// mkdtempSync worlds, injected pid/isAlive/now/hooks/fs — no processes are actually probed.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  acquireResolverLease,
  RECLAIM_GRACE_MS,
  releaseResolverClaim,
  resolverLockDir,
} from "./resolverLease.ts";

const OP = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const OP2 = "01BX5ZZKBKACTAV9WEVGEMMVRZ";

function world(): { manifest: string; lock: string } {
  const dir = mkdtempSync(join(tmpdir(), "perk-resolver-lease-"));
  mkdirSync(join(dir, "sync-continuations"), { recursive: true });
  const manifest = join(dir, "sync-continuations", "01LIN.json");
  writeFileSync(manifest, "{}\n", "utf8");
  return { manifest, lock: resolverLockDir(manifest) };
}

function plantLease(lock: string, pid: number, operationId: string, token = `t-${pid}`): void {
  mkdirSync(lock, { recursive: true });
  writeFileSync(
    join(lock, "lease.json"),
    `${JSON.stringify({ schema: 1, pid, operation_id: operationId, token })}\n`,
    "utf8",
  );
}

function leaseOf(lock: string): {
  schema: number;
  pid: number;
  operation_id: string;
  token: string;
} {
  return JSON.parse(readFileSync(join(lock, "lease.json"), "utf8"));
}

/** Assert the on-disk lease carries the given identity plus a non-empty ownership token. */
function assertLease(lock: string, pid: number, operationId: string): void {
  const lease = leaseOf(lock);
  assert.equal(lease.schema, 1);
  assert.equal(lease.pid, pid);
  assert.equal(lease.operation_id, operationId);
  assert.ok(typeof lease.token === "string" && lease.token.length > 0);
}

test("fresh acquire creates the lock dir, the lease bytes, and returns the ownership token", () => {
  const { manifest, lock } = world();
  const r = acquireResolverLease(manifest, OP, { pid: 111 });
  assert.equal(r.acquired, true);
  if (!r.acquired) return;
  assert.ok(existsSync(lock));
  assertLease(lock, 111, OP);
  assert.equal(leaseOf(lock).token, r.token, "the returned token is the persisted fence");
});

test("same-pid reacquire rewrites lease.json with the CURRENT operation id + a fresh token", () => {
  // The continue-time NEW conflict reuses the SAME operation id in practice, but a same-pid
  // holder reacquires (never reclaims) even across operation ids — pin that.
  const { manifest, lock } = world();
  plantLease(lock, 222, OP, "old-token");
  const r = acquireResolverLease(manifest, OP2, { pid: 222 });
  assert.equal(r.acquired, true);
  if (!r.acquired) return;
  assertLease(lock, 222, OP2);
  assert.notEqual(leaseOf(lock).token, "old-token", "the token rotates on reacquire");
  assert.equal(leaseOf(lock).token, r.token);
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
  assert.equal(leaseOf(lock).pid, 333, "never stolen");
});

test("foreign dead pid → reclaim + acquire", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, { pid: 111, isAlive: (pid) => pid !== 333 });
  assert.equal(r.acquired, true);
  assertLease(lock, 111, OP);
});

test("foreign live DIFFERENT-op holder → reclaim + acquire (that operation was consumed)", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP2);
  const r = acquireResolverLease(manifest, OP, { pid: 111, isAlive: () => true });
  assert.equal(r.acquired, true);
  assertLease(lock, 111, OP);
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
  assert.equal(r.acquired, true);
  assertLease(lock, 111, OP);
});

test("post-rename re-judgment restores a raced-in fresh SAME-op claim → busy, dir intact", () => {
  // Between our reclaimability judgment (dead holder) and the rename, a competitor completes a
  // FULL reclaim + reacquire: the dir we then move holds a fresh live same-op claim. The
  // re-judgment renames it back and reports busy — a fresh claim is never stolen.
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
  assert.equal(leaseOf(lock).pid, 444, "the competitor's fresh claim is restored intact");
});

test("post-rename re-judgment restores a raced-in live claim for a DIFFERENT operation", () => {
  // The judgment→rename window again, but the raced-in successor works a NEWER operation:
  // our own operation id is the stale one, so the moved lease must be restored on the
  // changed-since-judgment rule — never judged reclaimable just because its id differs.
  const { manifest, lock } = world();
  plantLease(lock, 333, OP); // dead — judged reclaimable
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: (pid) => pid === 444,
    hooks: {
      beforeQuarantine: () => {
        rmSync(lock, { recursive: true, force: true });
        plantLease(lock, 444, OP2); // a live successor claim on a NEWER operation
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /pid 444/);
  const restored = leaseOf(lock);
  assert.equal(restored.pid, 444);
  assert.equal(restored.operation_id, OP2, "the successor's claim is restored intact");
});

test("post-rename re-judgment restores a raced-in YOUNG lease-less dir (the mkdir window)", () => {
  // A competitor's fresh mkdir sits between its mkdir and first lease write when we rename:
  // the moved dir has no lease but is YOUNG — the grace rule applies post-rename too, so it
  // is restored as an unidentified holder instead of being stolen.
  const { manifest, lock } = world();
  plantLease(lock, 333, OP); // dead — judged reclaimable
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: () => false,
    hooks: {
      beforeQuarantine: () => {
        rmSync(lock, { recursive: true, force: true });
        mkdirSync(lock); // the competitor's mkdir; its lease.json is not written yet
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "busy");
  assert.match(r.reason, /unidentified holder/);
  assert.ok(existsSync(lock), "the young dir is restored");
  assert.equal(existsSync(join(lock, "lease.json")), false, "still lease-less — untouched");
});

test("a competing reclaimer wins the rename → the one retry still runs and may acquire", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: () => false,
    hooks: {
      beforeQuarantine: () => {
        // The competitor already moved (here: removed) the stale dir — our rename fails ENOENT.
        rmSync(lock, { recursive: true, force: true });
      },
    },
  });
  assert.equal(r.acquired, true);
  assertLease(lock, 111, OP);
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
  assert.equal(leaseOf(lock).pid, 555, "winner intact");
});

// --- genuine I/O failures: the typed io_error arm, never a fabricated busy/reclaim ---------------

function eacces(): NodeJS.ErrnoException {
  const error: NodeJS.ErrnoException = new Error("EACCES: permission denied");
  error.code = "EACCES";
  return error;
}

test("an unwritable lock parent (real fs) → kind io_error, never a throw", () => {
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

test("a lease.json that is a DIRECTORY (real fs) → io_error, not corrupt-data reclaim", () => {
  const { manifest, lock } = world();
  mkdirSync(join(lock, "lease.json"), { recursive: true }); // read fails EISDIR
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    now: () => Date.now() + RECLAIM_GRACE_MS + 60_000, // an aged dir must still NOT reclaim
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
});

test("a contended lease READ failure → io_error, never busy", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP);
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    fs: {
      readFile: () => {
        throw eacces();
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
  assert.match(r.reason, /EACCES/);
});

test("a lock-dir STAT failure on the corrupt-lease path → io_error, never busy/reclaim", () => {
  const { manifest, lock } = world();
  mkdirSync(lock, { recursive: true });
  writeFileSync(join(lock, "lease.json"), "not json", "utf8");
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    fs: {
      statMtimeMs: () => {
        throw eacces();
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
});

test("a same-pid lease REWRITE failure → io_error", () => {
  const { manifest, lock } = world();
  plantLease(lock, 222, OP);
  const r = acquireResolverLease(manifest, OP2, {
    pid: 222,
    fs: {
      writeLease: () => {
        throw eacces();
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
});

test("a FRESH lease write failure → io_error and this call's own dir is removed", () => {
  const { manifest, lock } = world();
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    fs: {
      writeLease: () => {
        throw eacces();
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
  assert.equal(existsSync(lock), false, "the partially created dir was cleaned");
});

test("a quarantine RENAME failure (non-ENOENT) → io_error, never a contention retry", () => {
  const { manifest, lock } = world();
  plantLease(lock, 333, OP); // dead — judged reclaimable, so the rename is attempted
  const r = acquireResolverLease(manifest, OP, {
    pid: 111,
    isAlive: () => false,
    fs: {
      rename: () => {
        throw eacces();
      },
    },
  });
  assert.equal(r.acquired, false);
  if (r.acquired) return;
  assert.equal(r.kind, "io_error");
  assert.equal(leaseOf(lock).pid, 333, "the observed claim is untouched");
});

// --- the token-fenced release (the withheld-dispatch cleanup) -------------------------------------

test("releaseResolverClaim removes the claim when the token proves ours", () => {
  const { manifest, lock } = world();
  const r = acquireResolverLease(manifest, OP, { pid: 111 });
  assert.equal(r.acquired, true);
  if (!r.acquired) return;
  releaseResolverClaim(manifest, r.token);
  assert.equal(existsSync(lock), false);
});

test("releaseResolverClaim restores a successor's claim on a token mismatch", () => {
  // A reclaimer replaced our claim between acquisition and the withheld-dispatch release:
  // the fenced release must put the successor back untouched, never delete it.
  const { manifest, lock } = world();
  const r = acquireResolverLease(manifest, OP, { pid: 111 });
  assert.equal(r.acquired, true);
  if (!r.acquired) return;
  rmSync(lock, { recursive: true, force: true });
  plantLease(lock, 444, OP2, "successor-token");
  releaseResolverClaim(manifest, r.token);
  assert.ok(existsSync(lock), "the successor's claim survives");
  assert.deepEqual(leaseOf(lock), {
    schema: 1,
    pid: 444,
    operation_id: OP2,
    token: "successor-token",
  });
});

test("releaseResolverClaim is a silent no-op when no claim exists and never throws on I/O", () => {
  const { manifest, lock } = world();
  releaseResolverClaim(manifest, "whatever"); // nothing to release
  assert.equal(existsSync(lock), false);
  plantLease(lock, 111, OP, "mine");
  releaseResolverClaim(manifest, "mine", {
    fs: {
      rename: () => {
        throw eacces();
      },
    },
  }); // best-effort: the failure is swallowed, the claim stays for the reclaim rules
  assert.ok(existsSync(lock));
});
