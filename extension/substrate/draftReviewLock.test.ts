import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { sessionDataDir } from "./cache.ts";
import {
  acquireDraftReviewLock,
  DRAFT_REVIEW_LOCK,
  type DraftReviewAcquisition,
} from "./draftReviewLock.ts";
import { acquireWorktreeResolverLock } from "./worktreeResolverLock.ts";

const parent = { sessionId: "parent", runId: "run", requestId: "request" };
function fixture(t: TestContext) {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "perk-draft-lock-")));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  return cwd;
}
function claim(result: DraftReviewAcquisition) {
  assert.equal(result.kind, "acquired");
  if (result.kind !== "acquired") throw new Error("no claim");
  return result.claim;
}

test("fixed canonical run-data filename, closed diagnostic owner, aliases contend, runs are independent", (t) => {
  const cwd = fixture(t);
  const alias = join(cwd, "alias");
  symlinkSync(cwd, alias);
  const a = claim(acquireDraftReviewLock(alias, parent));
  assert.equal(a.path, join(sessionDataDir(cwd, parent.runId), DRAFT_REVIEW_LOCK));
  const record = JSON.parse(readFileSync(a.path, "utf8"));
  assert.deepEqual(
    Object.keys(record).sort(),
    [
      "schema",
      "token",
      "pid",
      "parentSessionId",
      "ownerRunId",
      "requestId",
      "reviewNamespace",
      "createdAt",
    ].sort(),
  );
  assert.equal(record.schema, 1);
  assert.equal(record.reviewNamespace, sessionDataDir(cwd, "run"));
  const busy = acquireDraftReviewLock(cwd, { ...parent, sessionId: "other" });
  assert.equal(busy.kind, "busy");
  if (busy.kind !== "busy") return;
  assert.deepEqual(busy.owner, {
    pid: process.pid,
    parentSessionId: "parent",
    ownerRunId: "run",
    requestId: "request",
    reviewNamespace: sessionDataDir(cwd, "run"),
    createdAt: record.createdAt,
  });
  assert.equal(JSON.stringify(busy).includes(record.token), false);
  claim(acquireDraftReviewLock(cwd, { ...parent, runId: "run.1" })).finish("release");
  // The resolver has a different identity/filename and can coexist even in the same directory.
  const resolver = acquireWorktreeResolverLock(cwd, parent, {
    gitDir: () => record.reviewNamespace,
  });
  assert.equal(resolver.kind, "acquired");
  if (resolver.kind === "acquired") resolver.claim.finish("release");
  assert.equal(
    acquireDraftReviewLock(cwd, parent).kind,
    "busy",
    "non-reentrant even in one process",
  );
  assert.equal(a.check(), "owned");
  a.finish("retain");
  assert.equal(acquireDraftReviewLock(cwd, parent).kind, "busy");
});

for (const runId of [null, "", "..", "../other", "run/child", "run\0bad"]) {
  test(`unsafe or missing run ${JSON.stringify(runId)} creates no namespace`, (t) => {
    const cwd = fixture(t);
    assert.deepEqual(acquireDraftReviewLock(cwd, { ...parent, runId }), {
      kind: "unavailable",
      reason: "no-identity",
    });
    assert.equal(existsSync(join(cwd, ".perk")), false);
  });
}

for (const redirect of [".perk", "data", "writable-data", "file-data"]) {
  test(`unsafe ${redirect} namespace refuses without lock creation`, (t) => {
    const cwd = fixture(t);
    const outside = join(cwd, "outside");
    mkdirSync(outside);
    if (redirect === ".perk") symlinkSync(outside, join(cwd, ".perk"));
    else {
      const data = sessionDataDir(cwd, "run");
      mkdirSync(join(data, ".."), { recursive: true });
      if (redirect === "data") symlinkSync(outside, data);
      else if (redirect === "file-data") writeFileSync(data, "not a directory");
      else {
        mkdirSync(data);
        chmodSync(data, 0o777);
      }
    }
    assert.deepEqual(acquireDraftReviewLock(cwd, parent), {
      kind: "unavailable",
      reason: "unsafe-namespace",
    });
    assert.equal(existsSync(join(outside, DRAFT_REVIEW_LOCK)), false);
  });
}

test("draft malformed incumbent and successor-fenced release reuse primitive behavior", (t) => {
  const cwd = fixture(t);
  const a = claim(acquireDraftReviewLock(cwd, parent));
  renameSync(a.path, `${a.path}.old`);
  writeFileSync(a.path, "{");
  assert.equal(a.check(), "ownership-error");
  assert.equal(a.finish("release").kind, "ownership-error");
  assert.deepEqual(acquireDraftReviewLock(cwd, parent), { kind: "busy", path: a.path });
  assert.equal(readFileSync(a.path, "utf8"), "{");
});

test("draft fsync fault is typed and does not report acquisition", (t) => {
  const cwd = fixture(t);
  assert.deepEqual(
    acquireDraftReviewLock(cwd, parent, {
      fs: {
        sync() {
          throw new Error("induced");
        },
      },
    }),
    { kind: "io-error", path: join(sessionDataDir(cwd, "run"), DRAFT_REVIEW_LOCK), residue: false },
  );
});
