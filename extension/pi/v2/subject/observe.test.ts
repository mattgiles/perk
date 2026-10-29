// The git observation over real temp repos (docs/design/pi-durable-v2-foundations.md §5, §8): the
// facts it returns, S2 uncommitted edits never reach the snapshot (which holds raw committed
// bytes), S5 every observer failure is `observation_failed` and writes no subject, and S6 a new
// tree is a new subject while a same-tree commit is a new observation of the same subject.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { Observation } from "../host.ts";
import type { ObservationFacts } from "../kernel/records.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import {
  addIndexEntry,
  commitAll,
  commitIndex,
  fixtureGit,
  gitRepo,
  hashObject,
  readTree,
  stageAll,
  subjectStore,
  treeOf,
  writeFiles,
} from "../testing/subject.ts";
import { gitObserver, observeGitSubject } from "./observe.ts";
import { SUBJECTS_DIR, snapshotDir, snapshotManifestPath } from "./snapshot.ts";

const options = { timeout: CASE_TIMEOUT_MS };

function expectObserved(observation: Observation): ObservationFacts {
  if (observation.kind !== "observed") assert.fail(`observed: ${observation.detail}`);
  return observation.facts;
}

function sha256(bytes: Buffer | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

test(
  "the facts: the realpath repo, the verbatim ref, git's commit and tree, the injected clock",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { "a.txt": "a\n" });
    const commit = commitAll(repo, "first");
    const links = await tempDir(t, "perk-v2-subject-link-");
    const link = join(links, "repo-link");
    symlinkSync(repo, link);
    const store = await subjectStore(t);
    const facts = expectObserved(
      await gitObserver({ storeDir: store, repo: link, ref: "refs/heads/main", now: () => 4242 })(),
    );
    assert.deepEqual(facts, {
      repo: realpathSync(repo),
      ref: "refs/heads/main",
      commit,
      tree: treeOf(repo, commit),
      manifestDigest: sha256(readFileSync(snapshotManifestPath(store, facts.tree))),
      observedAt: 4242,
    });
  },
);

test(
  "S2: uncommitted edits in the live checkout never appear in the snapshot",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    const committed = {
      "a.txt": "a committed\n",
      "b.txt": "b committed\n",
      "c.txt": "c committed\n",
    };
    writeFiles(repo, committed);
    commitAll(repo, "first");
    const before = expectObserved(
      await observeGitSubject({ storeDir: await subjectStore(t), repo, ref: "main" }),
    );

    writeFiles(repo, { "a.txt": "a edited, unstaged\n" });
    writeFiles(repo, { "b.txt": "b edited, staged\n" });
    fixtureGit(repo, ["add", "b.txt"]);
    writeFiles(repo, { "u.txt": "untracked\n" });
    rmSync(join(repo, "c.txt"));
    const store = await subjectStore(t);
    const after = expectObserved(await observeGitSubject({ storeDir: store, repo, ref: "main" }));
    assert.equal(after.manifestDigest, before.manifestDigest);
    assert.equal(after.tree, before.tree);
    assert.deepEqual(
      readTree(snapshotDir(store, after.tree)).map((node) => [node.path, node.bytes?.toString()]),
      Object.entries(committed),
    );
  },
);

test(
  "S2: the snapshot holds raw committed bytes, never the checkout's eol conversion",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { ".gitattributes": "*.txt text eol=crlf\n", "file.txt": "one\ntwo\n" });
    const commit = commitAll(repo, "first");
    const blob = fixtureGit(repo, ["cat-file", "blob", `${commit}:file.txt`]);
    assert.equal(blob.toString(), "one\ntwo\n");
    // The control: a checkout of the same blob converts it.
    rmSync(join(repo, "file.txt"));
    fixtureGit(repo, ["checkout", "--", "file.txt"]);
    assert.equal(readFileSync(join(repo, "file.txt"), "utf8"), "one\r\ntwo\r\n");

    const store = await subjectStore(t);
    const facts = expectObserved(await observeGitSubject({ storeDir: store, repo, ref: "main" }));
    assert.deepEqual(readFileSync(join(snapshotDir(store, facts.tree), "file.txt")), blob);
  },
);

test(
  "S5: every observer failure is observation_failed and writes no subject",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { "sub/a.txt": "a\n" });
    commitAll(repo, "first");
    writeFiles(repo, { "b.txt": "b\n" });
    commitAll(repo, "second");
    // The control: HEAD~1 resolves in git, so only the ref-name rule refuses it.
    fixtureGit(repo, ["rev-parse", "--verify", "HEAD~1"]);
    fixtureGit(repo, ["tag", "blobtag", hashObject(repo, "blob\n")]);
    const plain = await tempDir(t, "perk-v2-subject-plain-");
    const empty = await gitRepo(t);

    const lf = await gitRepo(t);
    writeFiles(lf, { "ok.txt": "ok\n" });
    stageAll(lf);
    addIndexEntry(lf, "100644", hashObject(lf, "x\n"), "line\nfeed");
    commitIndex(lf, "lf");
    const nonUtf8 = await gitRepo(t);
    addIndexEntry(nonUtf8, "100644", hashObject(nonUtf8, "x\n"), Buffer.from([0x62, 0xff]));
    commitIndex(nonUtf8, "bytes");

    const cases: [string, string, string, RegExp][] = [
      ["a missing repo path", join(plain, "absent"), "main", /is missing/],
      ["an existing non-repo directory", plain, "main", /not a git repository/],
      ["a repo subdirectory", join(repo, "sub"), "main", /not a git repository/],
      ["an unknown ref", repo, "refs/heads/nope", /does not resolve to a commit/],
      ["a resolvable revision expression", repo, "HEAD~1", /is not a ref name/],
      ["a ref starting with -", repo, "-main", /is not a ref name/],
      ["an empty ref", repo, "", /is not a ref name/],
      ["a ref containing NUL", repo, "ma\0in", /is not a ref name/],
      ["a lightweight tag on a blob", repo, "blobtag", /does not resolve to a commit/],
      ["an empty repo", empty, "HEAD", /does not resolve to a commit/],
      ["an index-only LF path", lf, "main", /not a snapshot path/],
      ["an index-only non-UTF-8 path", nonUtf8, "main", /cannot be represented/],
    ];
    for (const [label, root, ref, detail] of cases) {
      const store = await subjectStore(t);
      const observation = await observeGitSubject({ storeDir: store, repo: root, ref });
      assert.equal(observation.kind, "observation_failed", label);
      if (observation.kind === "observation_failed")
        assert.match(observation.detail, detail, label);
      assert.equal(
        existsSync(join(store, SUBJECTS_DIR)),
        false,
        `${label}: no subject was written`,
      );
    }

    // The positive control: a bare repo observes.
    const bare = await gitRepo(t, { bare: true });
    fixtureGit(repo, ["push", "-q", bare, "main"]);
    const facts = expectObserved(
      await observeGitSubject({ storeDir: await subjectStore(t), repo: bare, ref: "main" }),
    );
    assert.equal(facts.repo, realpathSync(bare));
  },
);

test(
  "S6: a same-tree commit reuses the subject; a new tree is a new subject",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { "a.txt": "one\n" });
    const c1 = commitAll(repo, "c1");
    const store = await subjectStore(t);
    const first = expectObserved(await observeGitSubject({ storeDir: store, repo, ref: "main" }));
    assert.equal(first.commit, c1);
    const inode = lstatSync(snapshotDir(store, first.tree)).ino;

    const c2 = commitIndex(repo, "c2, same tree");
    const second = expectObserved(await observeGitSubject({ storeDir: store, repo, ref: "main" }));
    assert.equal(second.commit, c2);
    assert.notEqual(second.commit, first.commit);
    assert.equal(second.tree, first.tree);
    assert.equal(second.manifestDigest, first.manifestDigest);
    assert.equal(lstatSync(snapshotDir(store, second.tree)).ino, inode, "the snapshot is reused");
    assert.deepEqual(readdirSync(join(store, SUBJECTS_DIR)).sort(), [
      first.tree,
      `${first.tree}.manifest`,
    ]);

    writeFiles(repo, { "a.txt": "two\n" });
    const c3 = commitAll(repo, "c3");
    const third = expectObserved(await observeGitSubject({ storeDir: store, repo, ref: "main" }));
    assert.equal(third.commit, c3);
    assert.notEqual(third.tree, first.tree);
    assert.notEqual(third.manifestDigest, first.manifestDigest);
    assert.deepEqual(
      readdirSync(join(store, SUBJECTS_DIR)).sort(),
      [first.tree, `${first.tree}.manifest`, third.tree, `${third.tree}.manifest`].sort(),
    );
  },
);

test("a repo given as a file is observation_failed, never a throw", options, async (t) => {
  const dir = await tempDir(t, "perk-v2-subject-file-");
  const file = join(dir, "file");
  writeFileSync(file, "not a repo\n");
  mkdirSync(join(dir, "store"));
  const observation = await observeGitSubject({
    storeDir: join(dir, "store"),
    repo: file,
    ref: "main",
  });
  assert.equal(observation.kind, "observation_failed");
});
