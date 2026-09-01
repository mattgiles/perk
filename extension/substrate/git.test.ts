// Tests for the fail-open TS git seam. `sinceBaseSha` runs against scratch repos whose
// `refs/remotes/origin/*` refs are planted locally (no real remote), so the best-effort fetch
// step fails offline and the stale-ref arm is what every case exercises — by design.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  commitsSince,
  headSha,
  revalidationBracket,
  sinceBaseSha,
  unbornHead,
  worktreeDirty,
} from "./git.ts";

/** `git init` a scratch repo: two commits, `origin/main` planted at the FIRST (the base). */
function scratchRepo(opts: { originHead?: boolean } = {}): { cwd: string; baseSha: string } {
  const cwd = mkdtempSync(join(tmpdir(), "perk-git-test-"));
  const g = (...args: string[]): string =>
    execFileSync("git", args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  writeFileSync(join(cwd, "seed.txt"), "seed\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "base");
  const baseSha = g("rev-parse", "HEAD");
  g("update-ref", "refs/remotes/origin/main", baseSha);
  if (opts.originHead) g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main");
  writeFileSync(join(cwd, "work.txt"), "work\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "work");
  return { cwd, baseSha };
}

test("sinceBaseSha: an explicit base resolves merge-base(HEAD, origin/<base>)", () => {
  const { cwd, baseSha } = scratchRepo();
  assert.equal(sinceBaseSha(cwd, "main"), baseSha);
});

test("sinceBaseSha: a null base falls back to origin/HEAD (origin/main → main)", () => {
  const { cwd, baseSha } = scratchRepo({ originHead: true });
  assert.equal(sinceBaseSha(cwd, null), baseSha);
  assert.equal(sinceBaseSha(cwd, undefined), baseSha);
});

test("sinceBaseSha: null when origin/HEAD is unset and no base is given", () => {
  const { cwd } = scratchRepo();
  assert.equal(sinceBaseSha(cwd, null), null);
});

test("sinceBaseSha: null when the base ref is missing", () => {
  const { cwd } = scratchRepo();
  assert.equal(sinceBaseSha(cwd, "nope"), null);
});

test("sinceBaseSha: null outside a repo (fail-open, never throws)", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(sinceBaseSha(cwd, "main"), null);
  assert.equal(sinceBaseSha(cwd, null), null);
});

test("headSha: the current sha in a repo, null outside one (fail-open)", () => {
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null && /^[0-9a-f]{40}$/.test(sha), `expected a full sha, got ${sha}`);
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(headSha(norepo), null);
});

test("unbornHead: positive absence proof only — born false, unborn true, detached/non-repo null", () => {
  const { cwd, baseSha } = scratchRepo();
  // A born branch: the pointer resolves AND the ref exists — NOT unborn (so a transient
  // `headSha` failure on a born branch can never read as unborn; the D1 discrimination).
  assert.equal(unbornHead(cwd), false);
  const g = (...args: string[]) =>
    execFileSync("git", args, { cwd, stdio: ["ignore", "ignore", "ignore"] });
  // HEAD switched to a never-born branch in a repo WITH other refs: positively proven absent.
  g("symbolic-ref", "HEAD", "refs/heads/ghost");
  assert.equal(headSha(cwd), null, "sanity: the unborn pointer has no sha");
  assert.equal(unbornHead(cwd), true, "absence of the pointed-to ref is the unborn proof");
  g("symbolic-ref", "HEAD", "refs/heads/main");
  g("checkout", "-q", "--detach", baseSha);
  assert.equal(unbornHead(cwd), null, "a detached HEAD is not a branch pointer");
  const unborn = mkdtempSync(join(tmpdir(), "perk-git-unborn-"));
  execFileSync("git", ["init", "-q"], { cwd: unborn, stdio: "ignore" });
  assert.equal(unbornHead(unborn), true, "a fresh init is unborn (no refs at all)");
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(unbornHead(norepo), null);
});

test("worktreeDirty: false on a clean tree, true when dirty, null outside a repo", () => {
  const { cwd } = scratchRepo();
  assert.equal(worktreeDirty(cwd), false);
  writeFileSync(join(cwd, "untracked.txt"), "dirty\n", "utf8");
  assert.equal(worktreeDirty(cwd), true, "untracked files count as dirty");
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(worktreeDirty(norepo), null);
});

test("commitsSince: lists the commits after fromSha; null when the range is empty or outside a repo", () => {
  const { cwd, baseSha } = scratchRepo();
  const listing = commitsSince(cwd, baseSha);
  assert.ok(listing !== null, "expected a commit listing");
  assert.ok(listing.includes("work"), `expected the work commit in ${listing}`);
  assert.ok(!listing.includes("base"), "the base commit is outside the range");
  const head = headSha(cwd);
  assert.equal(commitsSince(cwd, head), null, "an empty range is null (fail-open style)");
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(commitsSince(norepo, null), null);
});

test("commitsSince: a null fromSha lists every commit (the unborn-HEAD-at-capture arm)", () => {
  const { cwd } = scratchRepo();
  const listing = commitsSince(cwd, null);
  assert.ok(listing !== null, "expected a commit listing");
  assert.ok(listing.includes("work") && listing.includes("base"));
});

test("revalidationBracket: matching HEAD + clean tree is ok", () => {
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  assert.deepEqual(revalidationBracket(cwd, sha), { ok: true, detail: null });
});

test("revalidationBracket: a moved HEAD drifts, naming both SHAs", () => {
  const { cwd, baseSha } = scratchRepo();
  const head = headSha(cwd);
  const result = revalidationBracket(cwd, baseSha);
  assert.equal(result.ok, false);
  assert.ok(result.detail?.includes(baseSha), `expected ${baseSha} in ${result.detail}`);
  assert.ok(result.detail?.includes(head ?? ""), `expected ${head} in ${result.detail}`);
});

test("revalidationBracket: a dirty tree drifts (untracked files included)", () => {
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  writeFileSync(join(cwd, "untracked.txt"), "dirty\n", "utf8");
  const result = revalidationBracket(cwd, sha);
  assert.equal(result.ok, false);
  assert.match(result.detail ?? "", /no longer clean/);
});

test("revalidationBracket: a non-repo cwd drifts fail-CLOSED (the head-null arm)", () => {
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  const result = revalidationBracket(norepo, "a".repeat(40));
  assert.equal(result.ok, false);
  assert.match(result.detail ?? "", /HEAD could not be resolved/);
});

test("revalidationBracket: an unprovable dirty probe drifts (the second fail-closed arm)", () => {
  // Reachable only through the probe seam: a resolvable HEAD but a null cleanliness probe —
  // an unprovable end state must read as drift, never as "unchanged".
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  const result = revalidationBracket(cwd, sha, { dirty: () => null });
  assert.equal(result.ok, false);
  assert.match(result.detail ?? "", /cleanliness could not be verified/);
});

test("revalidationBracket: an assume-unchanged flag drifts (the flags arm, through the bracket)", () => {
  // The privatized index probe is reached through its ONE consumer: a plain repo passes the
  // bracket, an assume-unchanged flag fails it, and clearing the flag restores the pass.
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  const g = (...args: string[]) =>
    execFileSync("git", args, { cwd, stdio: ["ignore", "ignore", "ignore"] });
  assert.deepEqual(revalidationBracket(cwd, sha), { ok: true, detail: null });
  g("update-index", "--assume-unchanged", "seed.txt");
  const flagged = revalidationBracket(cwd, sha);
  assert.equal(flagged.ok, false, "assume-unchanged is detected");
  assert.match(flagged.detail ?? "", /assume-unchanged\/skip-worktree/);
  g("update-index", "--no-assume-unchanged", "seed.txt");
  assert.deepEqual(revalidationBracket(cwd, sha), { ok: true, detail: null });
});

test("revalidationBracket: a flagged index drifts — status can no longer prove cleanliness", () => {
  // The hidden-edit hazard: mark a file skip-worktree and EDIT it — `git status` stays clean
  // and HEAD still matches, so only the flags arm catches the drift.
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  execFileSync("git", ["update-index", "--skip-worktree", "seed.txt"], {
    cwd,
    stdio: ["ignore", "ignore", "ignore"],
  });
  writeFileSync(join(cwd, "seed.txt"), "silently changed\n", "utf8");
  assert.equal(worktreeDirty(cwd), false, "sanity: the status probe alone would have passed");
  const result = revalidationBracket(cwd, sha);
  assert.equal(result.ok, false);
  assert.match(result.detail ?? "", /assume-unchanged\/skip-worktree/);
  assert.match(result.detail ?? "", /cannot be proven/);
});

test("revalidationBracket: an unprovable flags probe drifts (the third fail-closed arm)", () => {
  const { cwd } = scratchRepo();
  const sha = headSha(cwd);
  assert.ok(sha !== null);
  const result = revalidationBracket(cwd, sha, { flags: () => null });
  assert.equal(result.ok, false);
  assert.match(result.detail ?? "", /index flag state could not be verified/);
});
