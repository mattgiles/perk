// The subject snapshot store over real temp repos (docs/design/pi-durable-v2-foundations.md §5):
// S1 materialization is idempotent per tree (temp then rename, a collision inside the window,
// partial states), S3 a tampered snapshot fails verification (and reuse fails closed), S4 symlink
// and gitlink entries materialize and verify per §5, and exact names (BOM and CR) survive.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmdirSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, join } from "node:path";
import { type TestContext, test } from "node:test";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
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
  unlock,
  writeFiles,
} from "../testing/subject.ts";
import { observeGitSubject } from "./observe.ts";
import {
  discardTree,
  ensureSnapshot,
  SUBJECTS_DIR,
  snapshotDir,
  snapshotManifestPath,
  verifySnapshot,
} from "./snapshot.ts";

const options = { timeout: CASE_TIMEOUT_MS };

function sha256(bytes: Buffer | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

const README = "# readme\r\nwith a CRLF line\n";
const RUN = "#!/bin/sh\necho run\n";
const SPACED = "a spaced name\n";
const NESTED = "nested with a BOM\n";

type Fixture = { readonly repo: string; readonly first: string; readonly commit: string };

/**
 * The S4 repo: `README.md`, `bin/run` (`100755`), the real symlink `docs/link` → `../README.md`,
 * `dir/a b.txt`, and the index-only gitlink `vendor/sub` at the first commit. `nested` adds the
 * index-only `dir/\uFEFFnested.txt`.
 */
async function subjectRepo(t: TestContext, nested = false): Promise<Fixture> {
  const repo = await gitRepo(t);
  writeFiles(repo, { "README.md": README });
  const first = commitAll(repo, "first");
  writeFiles(repo, { "bin/run": RUN, "dir/a b.txt": SPACED });
  chmodSync(join(repo, "bin/run"), 0o755);
  mkdirSync(join(repo, "docs"));
  symlinkSync("../README.md", join(repo, "docs/link"));
  stageAll(repo);
  addIndexEntry(repo, "160000", first, "vendor/sub");
  if (nested) addIndexEntry(repo, "100644", hashObject(repo, NESTED), "dir/\uFEFFnested.txt");
  const commit = commitIndex(repo, "second");
  return { repo, first, commit };
}

async function observeOk(
  storeDir: string,
  repo: string,
  hooks?: { beforeRename?(tempDir: string): Promise<void> },
): Promise<{ readonly tree: string; readonly manifestDigest: string }> {
  const observation = await observeGitSubject({
    storeDir,
    repo,
    ref: "main",
    ...(hooks === undefined ? {} : { hooks }),
  });
  if (observation.kind !== "observed") assert.fail(`observed: ${observation.detail}`);
  return observation.facts;
}

function subjectsEntries(storeDir: string): string[] {
  return readdirSync(join(storeDir, SUBJECTS_DIR)).sort();
}

function ino(path: string): number {
  return lstatSync(path).ino;
}

test(
  "S1: materializing the same tree twice yields one snapshot and one manifest",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    const first = await observeOk(store, repo);
    const dir = snapshotDir(store, first.tree);
    const manifest = snapshotManifestPath(store, first.tree);
    const inodes = [ino(dir), ino(manifest)];
    const second = await observeOk(store, repo);
    assert.equal(second.manifestDigest, first.manifestDigest);
    assert.deepEqual(subjectsEntries(store), [first.tree, `${first.tree}.manifest`]);
    assert.deepEqual([ino(dir), ino(manifest)], inodes, "the second observation rewrote nothing");
  },
);

test(
  "S1: the snapshot is written to a temp directory, complete, then renamed into place",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    let inWindow:
      | { entries: string[]; tree: ReturnType<typeof readTree>; mode: number }
      | undefined;
    const facts = await observeOk(store, repo, {
      beforeRename: async (temp) => {
        inWindow = {
          entries: subjectsEntries(store),
          tree: readTree(temp),
          mode: statSync(temp).mode & 0o7777,
        };
        assert.equal(join(store, SUBJECTS_DIR, basename(temp)), temp);
      },
    });
    assert.ok(inWindow !== undefined, "the hook ran");
    assert.equal(inWindow.entries.length, 1);
    assert.match(inWindow.entries[0] ?? "", /^\.tmp\./);
    assert.ok(!inWindow.entries.includes(facts.tree), "no snapshot directory before the rename");
    assert.equal(inWindow.mode, 0o555);
    assert.deepEqual(
      inWindow.tree,
      readTree(snapshotDir(store, facts.tree)),
      "complete in the window",
    );
    assert.deepEqual(subjectsEntries(store), [facts.tree, `${facts.tree}.manifest`]);
  },
);

test(
  "S1: a competing observation inside the window wins the rename; both observe",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    let competitor: { digest: string; inode: number } | undefined;
    const facts = await observeOk(store, repo, {
      beforeRename: async () => {
        const won = await observeOk(store, repo);
        competitor = { digest: won.manifestDigest, inode: ino(snapshotDir(store, won.tree)) };
      },
    });
    assert.ok(competitor !== undefined, "the competitor ran inside the window");
    assert.equal(facts.manifestDigest, competitor.digest);
    assert.equal(
      ino(snapshotDir(store, facts.tree)),
      competitor.inode,
      "the competitor's snapshot stands",
    );
    assert.deepEqual(subjectsEntries(store), [facts.tree, `${facts.tree}.manifest`]);
  },
);

test(
  "S1: partial states — a lost manifest is rewritten, a lost directory re-materialized, strays ignored",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    const facts = await observeOk(store, repo);
    const dir = snapshotDir(store, facts.tree);
    const manifest = snapshotManifestPath(store, facts.tree);
    const text = readFileSync(manifest);

    rmSync(manifest);
    const dirInode = ino(dir);
    assert.equal((await observeOk(store, repo)).manifestDigest, facts.manifestDigest);
    assert.deepEqual(readFileSync(manifest), text, "the manifest is rewritten from git");
    assert.equal(ino(dir), dirInode, "the directory is not re-materialized");
    assert.equal(statSync(manifest).mode & 0o7777, 0o444);

    await discardTree(dir);
    const manifestInode = ino(manifest);
    assert.equal((await observeOk(store, repo)).manifestDigest, facts.manifestDigest);
    assert.equal(ino(manifest), manifestInode, "the manifest is kept");
    assert.equal((await verifySnapshot(store, facts.tree, facts.manifestDigest)).ok, true);

    mkdirSync(join(store, SUBJECTS_DIR, ".tmp.leftover"));
    writeFileSync(join(store, SUBJECTS_DIR, ".tmp.leftover", "junk"), "junk");
    assert.equal((await observeOk(store, repo)).manifestDigest, facts.manifestDigest);
    assert.deepEqual(subjectsEntries(store), [
      ".tmp.leftover",
      facts.tree,
      `${facts.tree}.manifest`,
    ]);
  },
);

test(
  "exact names: BOM twins and a CR-ending name materialize, manifest and verify as named",
  options,
  async (t) => {
    const repo = await gitRepo(t);
    writeFiles(repo, { foo: "plain foo\n" });
    stageAll(repo);
    addIndexEntry(repo, "100644", hashObject(repo, "bom foo\n"), "\uFEFFfoo");
    addIndexEntry(repo, "100644", hashObject(repo, NESTED), "dir/\uFEFFnested.txt");
    addIndexEntry(repo, "100644", hashObject(repo, "carriage\n"), "cr\r");
    commitIndex(repo, "names");
    const store = await subjectStore(t);
    const facts = await observeOk(store, repo);
    const dir = snapshotDir(store, facts.tree);
    const raw = (path: string) =>
      readdirSync(path, { encoding: "buffer" })
        .sort(Buffer.compare)
        .map((name) => name.toString("hex"));
    const hex = (name: string) => Buffer.from(name, "utf8").toString("hex");
    assert.deepEqual(raw(dir), [hex("cr\r"), hex("dir"), hex("foo"), hex("\uFEFFfoo")]);
    assert.deepEqual(raw(join(dir, "dir")), [hex("\uFEFFnested.txt")]);
    assert.equal(readFileSync(join(dir, "foo"), "utf8"), "plain foo\n");
    assert.equal(readFileSync(join(dir, "\uFEFFfoo"), "utf8"), "bom foo\n");
    assert.equal(readFileSync(join(dir, "cr\r"), "utf8"), "carriage\n");
    const manifest = readFileSync(snapshotManifestPath(store, facts.tree), "utf8");
    const paths = manifest
      .slice(0, -1)
      .split("\n")
      .map((line) => line.split(" ").slice(4).join(" "));
    assert.deepEqual(paths, ["cr\r", "dir/\uFEFFnested.txt", "foo", "\uFEFFfoo"]);
    assert.deepEqual(await verifySnapshot(store, facts.tree, facts.manifestDigest), { ok: true });
  },
);

type Tamper = {
  readonly label: string;
  readonly apply: (dir: string, manifest: string) => void | Promise<void>;
  readonly problem: string;
  readonly digest?: string;
};

const TAMPERS: readonly Tamper[] = [
  {
    label: "a file's content edited",
    apply: (dir) => {
      unlock(join(dir, "README.md"));
      writeFileSync(join(dir, "README.md"), "edited\n");
    },
    problem: 'content of "README.md" differs',
  },
  {
    label: "an extra file",
    apply: (dir) => {
      unlock(dir);
      writeFileSync(join(dir, "extra.txt"), "extra\n");
    },
    problem: 'unexpected file "extra.txt"',
  },
  {
    label: "an extra empty directory",
    apply: (dir) => {
      unlock(join(dir, "dir"));
      mkdirSync(join(dir, "dir", "empty"));
    },
    problem: 'unexpected directory "dir/empty"',
  },
  {
    label: "a file removed",
    apply: (dir) => {
      unlock(join(dir, "dir"));
      rmSync(join(dir, "dir", "a b.txt"));
    },
    problem: 'missing "dir/a b.txt"',
  },
  {
    label: "a file replaced by a symlink with the same target text",
    apply: (dir) => {
      unlock(join(dir, "docs"));
      rmSync(join(dir, "docs", "link"));
      symlinkSync("../README.md", join(dir, "docs", "link"));
    },
    problem: 'unexpected symlink at "docs/link"',
  },
  {
    label: "a file added inside a gitlink directory",
    apply: (dir) => {
      unlock(join(dir, "vendor", "sub"));
      writeFileSync(join(dir, "vendor", "sub", "x"), "x\n");
    },
    problem: 'gitlink "vendor/sub" is not an empty directory',
  },
  {
    label: "a gitlink directory replaced by an empty file",
    apply: (dir) => {
      unlock(join(dir, "vendor"));
      rmdirSync(join(dir, "vendor", "sub"));
      writeFileSync(join(dir, "vendor", "sub"), "");
    },
    problem: 'gitlink "vendor/sub" is not an empty directory',
  },
  {
    label: "the manifest file edited",
    apply: (_dir, manifest) => {
      unlock(manifest);
      writeFileSync(manifest, `${readFileSync(manifest, "utf8")}\n`);
    },
    problem: "manifest digest mismatch",
  },
  {
    label: "the manifest removed",
    apply: (_dir, manifest) => rmSync(manifest),
    problem: "missing manifest",
  },
  {
    label: "the snapshot directory removed",
    apply: (dir) => discardTree(dir),
    problem: "missing snapshot directory",
  },
  {
    label: "a wrong manifestDigest argument",
    apply: () => {},
    problem: "manifest digest mismatch",
    digest: "0".repeat(64),
  },
  {
    label: "a file chmodded 000",
    apply: (dir) => chmodSync(join(dir, "bin", "run"), 0o000),
    problem: 'cannot read "bin/run": EACCES',
  },
  {
    label: "a nested BOM dropped by a rename",
    apply: (dir) => {
      unlock(join(dir, "dir"));
      renameSync(join(dir, "dir", "\uFEFFnested.txt"), join(dir, "dir", "nested.txt"));
    },
    problem: 'unexpected file "dir/nested.txt"',
  },
  {
    label: "a root-level BOM added by a rename",
    apply: (dir) => {
      unlock(dir);
      renameSync(join(dir, "README.md"), join(dir, "\uFEFFREADME.md"));
    },
    problem: 'unexpected file "\uFEFFREADME.md"',
  },
];

const IS_ROOT = process.getuid?.() === 0;

for (const tamper of TAMPERS) {
  const skip = tamper.label === "a file chmodded 000" && IS_ROOT ? "uid 0 reads any file" : false;
  test(`S3: a tampered snapshot fails verification — ${tamper.label}`, {
    ...options,
    skip,
  }, async (t) => {
    const { repo } = await subjectRepo(t, true);
    const store = await subjectStore(t);
    const facts = await observeOk(store, repo);
    const dir = snapshotDir(store, facts.tree);
    const manifest = snapshotManifestPath(store, facts.tree);
    assert.deepEqual(
      await verifySnapshot(store, facts.tree, facts.manifestDigest),
      { ok: true },
      "the untampered control verifies",
    );
    await tamper.apply(dir, manifest);
    const verified = await verifySnapshot(store, facts.tree, tamper.digest ?? facts.manifestDigest);
    assert.equal(verified.ok, false);
    if (!verified.ok) assert.ok(verified.problem.includes(tamper.problem), verified.problem);
  });
}

test("S3: reuse of a tampered snapshot fails closed and rewrites nothing", options, async (t) => {
  const { repo } = await subjectRepo(t);
  const store = await subjectStore(t);
  const facts = await observeOk(store, repo);
  const readme = join(snapshotDir(store, facts.tree), "README.md");
  unlock(readme);
  writeFileSync(readme, "tampered\n");
  const again = await observeGitSubject({ storeDir: store, repo, ref: "main" });
  assert.equal(again.kind, "observation_failed");
  if (again.kind === "observation_failed") {
    assert.match(again.detail, /failed verification: content of "README\.md" differs/);
  }
  assert.equal(readFileSync(readme, "utf8"), "tampered\n", "the tampered bytes are still there");
});

test(
  "S3: a self-consistent forgery of a file and its manifest still fails re-observation",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    const facts = await observeOk(store, repo);
    const readme = join(snapshotDir(store, facts.tree), "README.md");
    const manifest = snapshotManifestPath(store, facts.tree);
    unlock(readme);
    writeFileSync(readme, "forged\n");
    const original = readFileSync(manifest, "utf8");
    const forged = original.replace(sha256(README), sha256("forged\n"));
    assert.notEqual(forged, original);
    unlock(manifest);
    writeFileSync(manifest, forged);
    // The control: the forged cache is self-consistent, so only a digest derived from git catches it.
    assert.deepEqual(await verifySnapshot(store, facts.tree, sha256(forged)), { ok: true });

    const again = await observeGitSubject({ storeDir: store, repo, ref: "main" });
    assert.equal(again.kind, "observation_failed");
    if (again.kind === "observation_failed") {
      assert.match(again.detail, /failed verification: manifest digest mismatch/);
    }
    assert.equal(readFileSync(readme, "utf8"), "forged\n", "the forged file is still there");
    assert.equal(readFileSync(manifest, "utf8"), forged, "the forged manifest is still there");
  },
);

test("S4: symlink and gitlink entries materialize and verify per §5", options, async (t) => {
  const { repo, first, commit } = await subjectRepo(t);
  const store = await subjectStore(t);
  const facts = await observeOk(store, repo);
  assert.equal(facts.tree, treeOf(repo, commit));
  const dir = snapshotDir(store, facts.tree);
  const nodes = new Map(readTree(dir).map((node) => [node.path, node]));
  const fileAt = (path: string) => {
    const node = nodes.get(path);
    assert.ok(node !== undefined && node.kind === "file", path);
    assert.equal(node.mode, 0o444, path);
    return node.bytes?.toString("utf8");
  };
  assert.equal(fileAt("README.md"), README);
  assert.equal(fileAt("bin/run"), RUN, "an executable is a 0444 file");
  assert.equal(fileAt("docs/link"), "../README.md", "a symlink is a file holding its target");
  assert.equal(fileAt("dir/a b.txt"), SPACED);
  assert.deepEqual(nodes.get("vendor/sub"), { path: "vendor/sub", kind: "dir", mode: 0o555 });
  assert.deepEqual(readdirSync(join(dir, "vendor/sub")), []);
  for (const directory of ["bin", "docs", "dir", "vendor"]) {
    assert.equal(nodes.get(directory)?.mode, 0o555, directory);
  }
  assert.equal(statSync(dir).mode & 0o7777, 0o555, "the snapshot root");
  assert.equal(nodes.size, 9);

  const oid = (path: string) =>
    fixtureGit(repo, ["rev-parse", `${commit}:${path}`])
      .toString()
      .trim();
  const expected =
    `blob ${sha256(README)} 100644 ${oid("README.md")} README.md\n` +
    `blob ${sha256(RUN)} 100755 ${oid("bin/run")} bin/run\n` +
    `blob ${sha256(SPACED)} 100644 ${oid("dir/a b.txt")} dir/a b.txt\n` +
    `link ${sha256("../README.md")} 120000 ${oid("docs/link")} docs/link\n` +
    `gitlink - 160000 ${first} vendor/sub\n`;
  assert.equal(readFileSync(snapshotManifestPath(store, facts.tree), "utf8"), expected);
  assert.equal(facts.manifestDigest, sha256(expected));
  assert.deepEqual(await verifySnapshot(store, facts.tree, facts.manifestDigest), { ok: true });
});

test("ensureSnapshot plans every entry before touching the store", options, async (t) => {
  const store = await subjectStore(t);
  const tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
  const oid = "1".repeat(40);
  const cases: [string, { mode: string; type: string; oid: string; path: string }[], string][] = [
    [
      "a tree entry",
      [{ mode: "040000", type: "tree", oid, path: "d" }],
      "unsupported tree entry 040000 tree",
    ],
    [
      "a blob typed commit",
      [{ mode: "100644", type: "commit", oid, path: "f" }],
      "unsupported tree entry",
    ],
    ["an LF path", [{ mode: "100644", type: "blob", oid, path: "a\nb" }], "not a snapshot path"],
    ["a bad oid", [{ mode: "100644", type: "blob", oid: "XYZ", path: "f" }], "oid"],
    [
      "a duplicate path",
      [
        { mode: "100644", type: "blob", oid, path: "f" },
        { mode: "100755", type: "blob", oid, path: "f" },
      ],
      "duplicate path",
    ],
    [
      "an entry that is also a directory",
      [
        { mode: "100644", type: "blob", oid, path: "f" },
        { mode: "100644", type: "blob", oid, path: "f/g" },
      ],
      "both an entry and a directory",
    ],
  ];
  for (const [label, entries, problem] of cases) {
    const ensured = await ensureSnapshot({ storeDir: store, repoRoot: store, tree, entries });
    assert.equal(ensured.ok, false, label);
    if (!ensured.ok) assert.ok(ensured.problem.includes(problem), `${label}: ${ensured.problem}`);
  }
  assert.equal(existsSync(store), false, "nothing was written");
});

test("verifySnapshot throws RangeError only for a malformed tree or digest", options, async (t) => {
  const store = await subjectStore(t);
  const tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
  await assert.rejects(verifySnapshot(store, "../escape", "0".repeat(64)), RangeError);
  await assert.rejects(verifySnapshot(store, tree, "ABC"), RangeError);
  assert.deepEqual(await verifySnapshot(store, tree, "0".repeat(64)), {
    ok: false,
    problem: `missing manifest ${tree}.manifest`,
  });
});

test(
  "discardTree removes a snapshot with 0555 directories; an absent path is a no-op",
  options,
  async (t) => {
    const { repo } = await subjectRepo(t);
    const store = await subjectStore(t);
    const facts = await observeOk(store, repo);
    const dir = snapshotDir(store, facts.tree);
    await discardTree(dir);
    assert.equal(existsSync(dir), false);
    await discardTree(dir);
    await discardTree(store);
    assert.equal(existsSync(store), false);
  },
);
