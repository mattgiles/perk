import assert from "node:assert/strict";
import { execFileSync, fork } from "node:child_process";
import { once } from "node:events";
import {
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { worktreeGitDir } from "./git.ts";
import {
  acquireWorktreeResolverLock,
  WORKTREE_RESOLVER_LOCK,
  type WorktreeResolverAcquisition,
} from "./worktreeResolverLock.ts";

const parent = { sessionId: "parent", runId: "run", requestId: "request" };
function fixture(t: TestContext) {
  const cwd = mkdtempSync(join(tmpdir(), "perk-worktree-lock-"));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  execFileSync("git", ["init", "-q", cwd], { timeout: 5000 });
  return realpathSync(cwd);
}
function claim(result: WorktreeResolverAcquisition) {
  assert.equal(result.kind, "acquired");
  if (result.kind !== "acquired") throw new Error("no claim");
  return result.claim;
}
function lockPath(cwd: string) {
  return join(cwd, ".git", WORKTREE_RESOLVER_LOCK);
}
function fault(): never {
  throw Object.assign(new Error("test fault"), { code: "EIO" });
}

test("exclusive private record, same-PID contention, release then reacquisition, double finish", (t) => {
  const cwd = fixture(t);
  const a = claim(acquireWorktreeResolverLock(cwd, parent));
  assert.equal(lstatSync(a.path).mode & 0o777, 0o600);
  const record = JSON.parse(readFileSync(a.path, "utf8"));
  assert.equal(record.schema, 1);
  assert.equal(record.worktreeIdentity, worktreeGitDir(cwd));
  assert.deepEqual(
    Object.keys(record).sort(),
    [
      "schema",
      "token",
      "pid",
      "parentSessionId",
      "ownerRunId",
      "requestId",
      "worktreeIdentity",
      "createdAt",
    ].sort(),
  );
  const b = acquireWorktreeResolverLock(cwd, { ...parent, sessionId: "another" });
  assert.equal(b.kind, "busy");
  assert.equal(JSON.stringify(b).includes(record.token), false);
  assert.equal(a.check(), "owned");
  assert.equal(a.finish("release").kind, "released");
  const c = claim(acquireWorktreeResolverLock(cwd, parent));
  assert.equal(a.finish("release").kind, "released");
  assert.equal(c.check(), "owned", "double finish cannot unlink a successor");
  c.finish("release");
});

test("retention closes resources and never reclaims on a later acquisition", (t) => {
  const cwd = fixture(t);
  let closes = 0;
  const a = claim(
    acquireWorktreeResolverLock(cwd, parent, {
      fs: {
        close(fd) {
          closes++;
          closeSync(fd);
        },
      },
    }),
  );
  assert.equal(a.finish("retain").kind, "retained");
  assert.equal(a.finish("release").kind, "retained");
  assert.equal(closes, 1);
  assert.equal(acquireWorktreeResolverLock(cwd, parent).kind, "busy");
});

for (const incumbent of ["empty", "malformed", "old-dead", "symlink", "directory", "oversized"]) {
  test(`incumbent ${incumbent} stays busy without takeover`, (t) => {
    const cwd = fixture(t);
    const path = lockPath(cwd);
    if (incumbent === "directory") mkdirSync(path);
    else if (incumbent === "symlink") symlinkSync("/nonexistent/test-target", path);
    else if (incumbent === "old-dead") {
      const a = claim(acquireWorktreeResolverLock(cwd, parent));
      a.finish("retain");
      writeFileSync(
        path,
        JSON.stringify({
          ...JSON.parse(readFileSync(path, "utf8")),
          pid: 2147483647,
          createdAt: "1900-01-01T00:00:00Z",
        }),
      );
    } else
      writeFileSync(
        path,
        incumbent === "oversized" ? "x".repeat(16385) : incumbent === "empty" ? "" : "{",
      );
    let reads = 0;
    const result = acquireWorktreeResolverLock(cwd, parent, {
      fs: {
        read() {
          reads++;
          return 0;
        },
      },
    });
    assert.equal(result.kind, "busy");
    if (["symlink", "directory", "oversized", "empty"].includes(incumbent)) assert.equal(reads, 0);
    assert.ok(lstatSync(path));
  });
}

for (const replacement of ["missing", "inode", "token"]) {
  test(`release fences ${replacement} mismatch and leaves successors untouched`, (t) => {
    const cwd = fixture(t);
    const a = claim(acquireWorktreeResolverLock(cwd, parent));
    if (replacement === "token")
      writeFileSync(
        a.path,
        JSON.stringify({ ...JSON.parse(readFileSync(a.path, "utf8")), token: "successor" }),
      );
    else {
      renameSync(a.path, `${a.path}.old`);
      if (replacement === "inode") writeFileSync(a.path, readFileSync(`${a.path}.old`));
    }
    assert.equal(a.finish("release").kind, "ownership-error");
    assert.equal(existsSync(a.path), replacement !== "missing");
  });
}

test("initialization failure cleans only identity-matched fresh file, reports residue, closes", (t) => {
  const cwd = fixture(t);
  let closes = 0;
  const a = acquireWorktreeResolverLock(cwd, parent, {
    fs: {
      write: fault,
      close(fd) {
        closes++;
        closeSync(fd);
      },
    },
  });
  assert.deepEqual(a, { kind: "io-error", path: lockPath(cwd), residue: false });
  assert.equal(closes, 1);
  const b = acquireWorktreeResolverLock(cwd, parent, {
    fs: {
      write(fd, _data) {
        renameSync(lockPath(cwd), `${lockPath(cwd)}.old`);
        writeFileSync(lockPath(cwd), "successor");
        assert.ok(fd >= 0);
        fault();
      },
    },
  });
  assert.deepEqual(b, { kind: "io-error", path: lockPath(cwd), residue: true });
  assert.equal(readFileSync(lockPath(cwd), "utf8"), "successor");
});

test("non-contention and release IO failures are typed, never success", (t) => {
  const cwd = fixture(t);
  assert.equal(acquireWorktreeResolverLock(cwd, parent, { fs: { open: fault } }).kind, "io-error");
  const a = claim(acquireWorktreeResolverLock(cwd, parent, { fs: { unlink: fault } }));
  assert.equal(a.finish("release").kind, "io-error");
  assert.ok(existsSync(a.path));
  assert.equal(acquireWorktreeResolverLock(cwd, parent, { fs: { lstat: fault } }).kind, "io-error");
});

test("Git discovery fails closed; aliases share identity but linked worktrees don't serialize", (t) => {
  const cwd = fixture(t);
  assert.equal(
    acquireWorktreeResolverLock(cwd, parent, { gitDir: () => null }).kind,
    "unavailable",
  );
  assert.equal(worktreeGitDir(join(cwd, "missing")), null);
  const outside = mkdtempSync(join(tmpdir(), "perk-nongit-"));
  t.after(() => rmSync(outside, { recursive: true, force: true }));
  assert.equal(worktreeGitDir(outside), null);
  execFileSync(
    "git",
    [
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.test",
      "commit",
      "--allow-empty",
      "-qm",
      "initial",
    ],
    { cwd, timeout: 5000 },
  );
  const linked = join(cwd, "linked");
  execFileSync("git", ["worktree", "add", "-qb", "linked", linked], { cwd, timeout: 5000 });
  const alias = join(cwd, "alias");
  symlinkSync(cwd, alias);
  mkdirSync(join(cwd, "subdir"));
  assert.equal(worktreeGitDir(alias), worktreeGitDir(join(cwd, "subdir")));
  assert.notEqual(worktreeGitDir(linked), worktreeGitDir(cwd));
  const a = claim(acquireWorktreeResolverLock(alias, parent));
  assert.equal(acquireWorktreeResolverLock(join(cwd, "subdir"), parent).kind, "busy");
  claim(acquireWorktreeResolverLock(linked, parent)).finish("release");
  a.finish("release");
});

async function child(t: TestContext, cwd: string) {
  const p = fork(new URL("../testing/worktreeLockChild.ts", import.meta.url), [cwd], {
    stdio: ["ignore", "ignore", "ignore", "ipc"],
  });
  t.after(async () => {
    if (p.exitCode === null && p.signalCode === null) {
      const exit = once(p, "exit");
      p.kill();
      await exit;
    }
  });
  const [result] = await once(p, "message");
  return { p, result };
}
async function send(p: ReturnType<typeof fork>, message: string) {
  const result = once(p, "message");
  p.send(message);
  return (await result)[0];
}

test("actual processes: incumbent excludes competitors; release permits later acquisition", async (t) => {
  const cwd = fixture(t);
  const a = await child(t, cwd);
  const b = await child(t, cwd);
  assert.equal(a.result.kind, "acquired");
  assert.equal(b.result.kind, "busy");
  assert.equal((await send(a.p, "release")).kind, "released");
  const c = await child(t, cwd);
  assert.equal(c.result.kind, "acquired");
  await send(c.p, "release");
});

for (const mode of ["exit", "kill"]) {
  test(`actual processes: ${mode} without release leaves existing and new contenders blocked`, async (t) => {
    const cwd = fixture(t);
    const a = await child(t, cwd);
    assert.equal(a.result.kind, "acquired");
    const b = await child(t, cwd);
    assert.equal(b.result.kind, "busy");
    const exit = once(a.p, "exit");
    if (mode === "exit") a.p.send("exit");
    else a.p.kill("SIGKILL");
    await exit;
    assert.equal(
      (await send(b.p, "try")).kind,
      "busy",
      "already-running contender still cannot reclaim",
    );
    assert.equal(acquireWorktreeResolverLock(cwd, parent).kind, "busy");
    assert.equal((await child(t, cwd)).result.kind, "busy");
    // Human-only recovery is deliberately NOT exposed by the production module.
    unlinkSync(lockPath(cwd));
  });
}
