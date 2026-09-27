// Tests for the fail-open TS git seam. `sinceBaseSha` runs against scratch repos whose
// `refs/remotes/origin/*` refs are planted locally (no real remote), so the best-effort fetch
// step fails offline and the stale-ref arm is what every case exercises — by design.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { CheckoutSnapshot } from "./checkoutSnapshot.ts";
import {
  checkoutBracket,
  checkoutCleanStart,
  commitsSince,
  headSha,
  revalidationBracket,
  sinceBaseSha,
  trackedChanges,
  unbornHead,
  untrackedInventory,
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

// ------------------------------------------------------------------ the checkout-bracket probes

function run(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim();
}
const sha256 = (text: string) => createHash("sha256").update(text).digest("hex");
const isRoot = typeof process.getuid === "function" && process.getuid() === 0;

test("trackedChanges: [] when clean; modified and staged-rename paths listed; null outside a repo", () => {
  const { cwd } = scratchRepo();
  assert.deepEqual(trackedChanges(cwd), []);
  writeFileSync(join(cwd, "untracked.txt"), "u\n", "utf8");
  assert.deepEqual(trackedChanges(cwd), [], "untracked paths never appear");
  writeFileSync(join(cwd, "seed.txt"), "changed\n", "utf8");
  assert.deepEqual(trackedChanges(cwd), ["seed.txt"]);
  run(cwd, "checkout", "--", "seed.txt");
  run(cwd, "mv", "work.txt", "moved.txt");
  assert.deepEqual(trackedChanges(cwd), ["moved.txt"], "a staged rename lists the new path");
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(trackedChanges(norepo), null);
});

test("untrackedInventory: files with sha256, symlinks with targets; ignored excluded; README negation listed", () => {
  const { cwd } = scratchRepo();
  assert.deepEqual(untrackedInventory(cwd), []);
  writeFileSync(
    join(cwd, ".gitignore"),
    "/.perk/\n/docs/library/**\n!/docs/library/README.md\nignored.txt\n",
    "utf8",
  );
  run(cwd, "add", ".gitignore");
  run(cwd, "commit", "-qm", "ignore");
  writeFileSync(join(cwd, "notes.txt"), "notes\n", "utf8");
  writeFileSync(join(cwd, "ignored.txt"), "ignored\n", "utf8");
  symlinkSync("notes.txt", join(cwd, "link"));
  mkdirSync(join(cwd, "docs/library/documentation/pi"), { recursive: true });
  writeFileSync(join(cwd, "docs/library/documentation/pi/index.md"), "# pi\n", "utf8");
  writeFileSync(join(cwd, "docs/library/catalog.json"), "{}\n", "utf8");
  writeFileSync(join(cwd, "docs/library/README.md"), "readme\n", "utf8");
  assert.deepEqual(untrackedInventory(cwd), [
    { path: "docs/library/README.md", kind: "file", digest: sha256("readme\n") },
    { path: "link", kind: "symlink", digest: "notes.txt" },
    { path: "notes.txt", kind: "file", digest: sha256("notes\n") },
  ]);
  const norepo = mkdtempSync(join(tmpdir(), "perk-git-norepo-"));
  assert.equal(untrackedInventory(norepo), null);
});

test("untrackedInventory: an unreadable untracked file fails closed", {
  skip: isRoot || process.platform === "win32",
}, () => {
  const { cwd } = scratchRepo();
  const path = join(cwd, "secret.txt");
  writeFileSync(path, "s\n", "utf8");
  chmodSync(path, 0o000);
  try {
    assert.equal(untrackedInventory(cwd), null);
  } finally {
    chmodSync(path, 0o644);
  }
});

test("checkoutCleanStart: clean → ok (untracked inventoried); tracked edit / assume-unchanged / skip-worktree refuse", () => {
  const { cwd } = scratchRepo();
  writeFileSync(join(cwd, "notes.txt"), "notes\n", "utf8");
  const clean = checkoutCleanStart(cwd);
  assert.ok(clean.ok);
  assert.equal(clean.snapshot.head, headSha(cwd));
  assert.deepEqual(
    clean.snapshot.untracked.map((e) => e.path),
    ["notes.txt"],
  );
  writeFileSync(join(cwd, "seed.txt"), "dirty\n", "utf8");
  const dirty = checkoutCleanStart(cwd);
  assert.ok(!dirty.ok);
  assert.match(dirty.detail, /"seed.txt"/);
  run(cwd, "checkout", "--", "seed.txt");
  for (const flag of ["--assume-unchanged", "--skip-worktree"]) {
    run(cwd, "update-index", flag, "seed.txt");
    const flagged = checkoutCleanStart(cwd);
    assert.ok(!flagged.ok, flag);
    assert.match(flagged.detail, /assume-unchanged\/skip-worktree/);
    run(cwd, "update-index", flag.replace("--", "--no-"), "seed.txt");
  }
  assert.ok(checkoutCleanStart(cwd).ok);
});

test("checkoutBracket: every end-state movement is a violation naming it; ignored writes are invisible", () => {
  function started(): { cwd: string; snapshot: CheckoutSnapshot } {
    const { cwd } = scratchRepo();
    writeFileSync(join(cwd, ".gitignore"), "/docs/library/**\n!/docs/library/README.md\n", "utf8");
    run(cwd, "add", ".gitignore");
    run(cwd, "commit", "-qm", "ignore");
    writeFileSync(join(cwd, "notes.txt"), "notes\n", "utf8");
    const start = checkoutCleanStart(cwd);
    assert.ok(start.ok);
    return { cwd, snapshot: start.snapshot };
  }
  const moves: [string, (cwd: string) => void, RegExp][] = [
    [
      "commit",
      (cwd) => {
        writeFileSync(join(cwd, "seed.txt"), "committed\n", "utf8");
        run(cwd, "commit", "-qam", "child");
      },
      /HEAD moved from/,
    ],
    [
      "tracked edit",
      (cwd) => writeFileSync(join(cwd, "seed.txt"), "x\n", "utf8"),
      /tracked changes: "seed.txt"/,
    ],
    [
      "new untracked",
      (cwd) => writeFileSync(join(cwd, "new.txt"), "n\n", "utf8"),
      /untracked added: "new.txt"/,
    ],
    [
      "removed untracked",
      (cwd) => rmSync(join(cwd, "notes.txt")),
      /untracked removed: "notes.txt"/,
    ],
    [
      "overwritten untracked",
      (cwd) => writeFileSync(join(cwd, "notes.txt"), "rewritten\n", "utf8"),
      /untracked changed: "notes.txt"/,
    ],
    [
      "flag",
      (cwd) => run(cwd, "update-index", "--assume-unchanged", "seed.txt"),
      /assume-unchanged/,
    ],
  ];
  for (const [label, move, detail] of moves) {
    const { cwd, snapshot } = started();
    assert.deepEqual(checkoutBracket(cwd, snapshot), { ok: true }, `${label}: untouched is ok`);
    move(cwd);
    const outcome = checkoutBracket(cwd, snapshot);
    assert.ok(!outcome.ok, label);
    assert.match(outcome.detail, detail, label);
  }
  const { cwd, snapshot } = started();
  mkdirSync(join(cwd, "docs/library/documentation/pi"), { recursive: true });
  writeFileSync(join(cwd, "docs/library/documentation/pi/index.md"), "# pi\n", "utf8");
  assert.deepEqual(checkoutBracket(cwd, snapshot), { ok: true }, "ignored writes are invisible");
  writeFileSync(join(cwd, "docs/library/README.md"), "readme\n", "utf8");
  const readme = checkoutBracket(cwd, snapshot);
  assert.ok(!readme.ok);
  assert.deepEqual(readme.moved.untrackedAdded, ["docs/library/README.md"]);
});

test("checkoutBracket / checkoutCleanStart: the probes seam's null arms fail closed", () => {
  const { cwd } = scratchRepo();
  const start = checkoutCleanStart(cwd);
  assert.ok(start.ok);
  for (const probes of [
    { head: () => null },
    { trackedChanges: () => null },
    { flags: () => null },
    { untracked: () => null },
  ]) {
    const label = Object.keys(probes)[0];
    assert.equal(checkoutCleanStart(cwd, probes).ok, false, `start ${label}`);
    const outcome = checkoutBracket(cwd, start.snapshot, probes);
    assert.ok(!outcome.ok, `end ${label}`);
    assert.equal(outcome.moved.probeFailures?.length, 1, `end ${label}`);
  }
});
