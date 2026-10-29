// The observer's git reads over real temp repos: strict BOM-keeping decoding, the pinned
// environment, the ref-name rule, single resolution (branches, HEAD, annotated tags, sha256 and
// bare repos, the ceiling), raw `ls-tree` listings with exact path bytes, and `cat-file --batch`
// streaming of raw blob bytes.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, realpathSync, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  addIndexEntry,
  commitAll,
  commitIndex,
  fixtureGit,
  gitRepo,
  hashObject,
  stageAll,
  treeOf,
  writeFiles,
} from "../testing/subject.ts";
import {
  checkRefFormat,
  decodeStrictUtf8,
  GitError,
  gitEnv,
  listTree,
  readBlobs,
  resolveCommitTree,
} from "./git.ts";

const options = { timeout: CASE_TIMEOUT_MS };

test("decodeStrictUtf8 keeps a leading BOM, passes CR through and rejects invalid UTF-8", () => {
  assert.equal(decodeStrictUtf8(Buffer.from([0xef, 0xbb, 0xbf, 0x66, 0x6f, 0x6f])), "\uFEFFfoo");
  // The control: the default decoder drops it.
  assert.equal(new TextDecoder().decode(Buffer.from([0xef, 0xbb, 0xbf, 0x66])), "f");
  assert.equal(decodeStrictUtf8(Buffer.from([0xff])), null);
  assert.equal(decodeStrictUtf8(Buffer.from([0xed, 0xa0, 0x80])), null, "an encoded surrogate");
  assert.equal(decodeStrictUtf8(Buffer.from("a\rb", "utf8")), "a\rb");
});

test("gitEnv drops every inherited GIT_* variable and sets the three pins; pure", () => {
  const base: NodeJS.ProcessEnv = {
    GIT_DIR: "/elsewhere/.git",
    GIT_WORK_TREE: "/elsewhere",
    GIT_INDEX_FILE: "/elsewhere/index",
    GIT_CONFIG_COUNT: "1",
    GIT_CONFIG_KEY_0: "core.fsmonitor",
    GIT_CEILING_DIRECTORIES: "/nowhere",
    PATH: "/usr/bin",
    HOME: "/home/someone",
  };
  const frozen = structuredClone(base);
  assert.deepEqual(gitEnv(base, "/work/repo"), {
    PATH: "/usr/bin",
    HOME: "/home/someone",
    GIT_CEILING_DIRECTORIES: "/work",
    GIT_NO_REPLACE_OBJECTS: "1",
    GIT_TERMINAL_PROMPT: "0",
  });
  assert.deepEqual(base, frozen, "the base is not mutated");
});

test("checkRefFormat accepts ref names and rejects revision expressions", options, async (t) => {
  const repo = await gitRepo(t);
  for (const ref of ["HEAD", "main", "refs/heads/main", "v1.0"]) {
    assert.equal(await checkRefFormat(repo, ref), true, ref);
  }
  for (const ref of ["HEAD~1", "main^", "@{u}", "a..b", "@", "refs/heads/x.lock"]) {
    assert.equal(await checkRefFormat(repo, ref), false, ref);
  }
});

test("resolveCommitTree resolves a branch, HEAD and a peeled annotated tag", options, async (t) => {
  const repo = await gitRepo(t);
  writeFiles(repo, { "a.txt": "one\n" });
  const first = commitAll(repo, "first");
  fixtureGit(repo, ["tag", "-a", "v1", "-m", "annotated"]);
  writeFiles(repo, { "a.txt": "two\n" });
  const second = commitAll(repo, "second");
  assert.deepEqual(await resolveCommitTree(repo, "main"), {
    commit: second,
    tree: treeOf(repo, second),
  });
  assert.deepEqual(await resolveCommitTree(repo, "HEAD"), {
    commit: second,
    tree: treeOf(repo, second),
  });
  assert.deepEqual(await resolveCommitTree(repo, "refs/tags/v1"), {
    commit: first,
    tree: treeOf(repo, first),
  });
  assert.notEqual(
    fixtureGit(repo, ["rev-parse", "v1"]).toString().trim(),
    first,
    "the tag object is not the commit (the peel is real)",
  );
});

test("resolveCommitTree reads a sha256 repo and a bare repo", options, async (t) => {
  const sha256 = await gitRepo(t, { objectFormat: "sha256" });
  writeFiles(sha256, { "a.txt": "x\n" });
  const commit = commitAll(sha256, "first");
  const resolved = await resolveCommitTree(sha256, "main");
  assert.equal(resolved.commit, commit);
  assert.match(resolved.commit, /^[0-9a-f]{64}$/);
  assert.match(resolved.tree, /^[0-9a-f]{64}$/);

  const source = await gitRepo(t);
  writeFiles(source, { "b.txt": "y\n" });
  const pushed = commitAll(source, "first");
  const bare = await gitRepo(t, { bare: true });
  fixtureGit(source, ["push", "-q", bare, "main"]);
  assert.deepEqual(await resolveCommitTree(bare, "main"), {
    commit: pushed,
    tree: treeOf(source, pushed),
  });
});

test(
  "resolveCommitTree throws GitError for what is not a commit at a repo root",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { "sub/a.txt": "a\n" });
    commitAll(repo, "first");
    const blob = hashObject(repo, "blob\n");
    fixtureGit(repo, ["tag", "blobtag", blob]);
    const empty = await gitRepo(t);
    const sub = join(repo, "sub");
    // The control: unpinned discovery from the subdirectory finds the enclosing repo.
    assert.equal(
      fixtureGit(sub, ["rev-parse", "--show-toplevel"]).toString().trim(),
      realpathSync(repo),
    );
    const cases: [string, string, string, RegExp][] = [
      ["an unknown ref", repo, "refs/heads/nope", /Needed a single revision/],
      ["a lightweight tag on a blob", repo, "blobtag", /blob/],
      ["an empty repo (unborn HEAD)", empty, "HEAD", /Needed a single revision/],
      ["a repo subdirectory as the root", sub, "HEAD", /not a git repository/],
    ];
    for (const [label, root, ref, message] of cases) {
      await assert.rejects(resolveCommitTree(root, ref), (error: unknown) => {
        assert.ok(error instanceof GitError, label);
        assert.match(error.message, message, label);
        return true;
      });
    }
  },
);

test("listTree lists modes, types, oids and exact path text", options, async (t) => {
  const repo = await gitRepo(t);
  writeFiles(repo, {
    "README.md": "readme\n",
    "bin/run": "#!/bin/sh\n",
    "dir/a b.txt": "spaced\n",
    "dir/tab\there.txt": "tabbed\n",
    "astral/\u{1F600}.txt": "astral\n",
  });
  chmodSync(join(repo, "bin/run"), 0o755);
  mkdirSync(join(repo, "docs"));
  symlinkSync("../README.md", join(repo, "docs/link"));
  const first = commitAll(repo, "first");
  stageAll(repo);
  const blob = hashObject(repo, "index-only\n");
  addIndexEntry(repo, "160000", first, "vendor/sub");
  addIndexEntry(repo, "100644", blob, "\uFEFFroot.txt");
  addIndexEntry(repo, "100644", blob, "dir/\uFEFFnested.txt");
  addIndexEntry(repo, "100644", blob, "cr\r");
  addIndexEntry(repo, "100644", blob, "line\nfeed");
  const commit = commitIndex(repo, "second");
  const listed = await listTree(repo, treeOf(repo, commit));
  assert.ok(listed.ok);
  const byPath = new Map(listed.entries.map((entry) => [entry.path, entry]));
  const oid = (path: string) =>
    fixtureGit(repo, ["rev-parse", `${commit}:${path}`])
      .toString()
      .trim();
  assert.deepEqual(byPath.get("README.md"), {
    mode: "100644",
    type: "blob",
    oid: oid("README.md"),
    path: "README.md",
  });
  assert.equal(byPath.get("bin/run")?.mode, "100755");
  assert.deepEqual(byPath.get("docs/link"), {
    mode: "120000",
    type: "blob",
    oid: oid("docs/link"),
    path: "docs/link",
  });
  assert.deepEqual(byPath.get("vendor/sub"), {
    mode: "160000",
    type: "commit",
    oid: first,
    path: "vendor/sub",
  });
  for (const path of [
    "dir/a b.txt",
    "dir/tab\there.txt",
    "astral/\u{1F600}.txt",
    "\uFEFFroot.txt",
    "dir/\uFEFFnested.txt",
    "cr\r",
    "line\nfeed",
  ]) {
    assert.ok(byPath.has(path), JSON.stringify(path));
  }
  assert.ok(!byPath.has("root.txt") && !byPath.has("dir/nested.txt"), "no BOM was dropped");
  assert.ok(!byPath.has("cr"), "no CR was dropped");
  assert.equal(listed.entries.length, 11);
});

test("listTree: an empty tree is []; a non-UTF-8 path is a problem", options, async (t) => {
  const repo = await gitRepo(t);
  const empty = commitIndex(repo, "empty");
  assert.deepEqual(await listTree(repo, treeOf(repo, empty)), { ok: true, entries: [] });

  const blob = hashObject(repo, "x\n");
  addIndexEntry(repo, "100644", blob, Buffer.from([0x62, 0x61, 0x64, 0xff]));
  const bad = commitIndex(repo, "bad");
  assert.deepEqual(await listTree(repo, treeOf(repo, bad)), {
    ok: false,
    problem: "a tree path is not valid UTF-8",
  });
});

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

test("readBlobs streams raw bytes in request order", options, async (t) => {
  const repo = await gitRepo(t);
  const large = Buffer.alloc(1024 * 1024 + 7);
  for (let i = 0; i < large.length; i++) large[i] = (i * 31 + 7) & 0xff;
  const contents = [
    Buffer.from("nul\0inside", "latin1"),
    Buffer.from("crlf\r\nline\r\n", "latin1"),
    large,
    Buffer.from([0x00, 0xff, 0x0a, 0x0a, 0x80]),
    Buffer.alloc(0),
  ];
  const oids = contents.map((bytes) => hashObject(repo, bytes));
  const requested = [oids[3], oids[2], oids[0], oids[4], oids[1]].map((oid) => oid ?? "");
  const seen: [string, string][] = [];
  await readBlobs(repo, requested, async (oid, bytes) => {
    seen.push([oid, sha256(bytes)]);
  });
  assert.deepEqual(
    seen,
    requested.map((oid) => [oid, sha256(contents[oids.indexOf(oid)] ?? Buffer.alloc(1))]),
  );
  // No objects: no spawn, no calls.
  await readBlobs(dirname(repo), [], async () => assert.fail("no object was requested"));
});

test(
  "readBlobs throws GitError for a missing object or a tree; a callback error propagates",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { "a.txt": "a\n" });
    const commit = commitAll(repo, "first");
    const blob = hashObject(repo, "a\n");
    const missing = "0123456789abcdef0123456789abcdef01234567";
    for (const [label, oids] of [
      ["a missing object", [blob, missing]],
      ["a tree", [treeOf(repo, commit)]],
    ] as const) {
      await assert.rejects(
        readBlobs(repo, oids, async () => {}),
        (error: unknown) => error instanceof GitError,
        label,
      );
    }
    const boom = new Error("callback failed");
    await assert.rejects(
      readBlobs(repo, [blob, blob], async () => {
        throw boom;
      }),
      (error: unknown) => error === boom,
    );
    await assert.rejects(
      readBlobs(join(repo, "a.txt"), [blob], async () => {}),
      (error: unknown) => error instanceof GitError,
      "git cannot start in a file",
    );
  },
);
