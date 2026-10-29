// The subject and the snapshot-manifest grammar (docs/design/pi-durable-v2-foundations.md §5):
// the git-tree subject, the manifest golden (UTF-8 byte order, which disagrees with the UTF-16
// sort for astral vs BMP paths), the empty manifest, and every representability rejection. Every
// expected digest is an independent hash of a literal text.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import {
  gitTreeSubject,
  isSnapshotPath,
  type ManifestEntry,
  parseSnapshotManifest,
  snapshotManifest,
  subjectDigest,
} from "./subject.ts";

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

const TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const TREE64 = "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321";

test("gitTreeSubject accepts lowercase sha1 and sha256 oids; the digest is the oid", () => {
  assert.deepEqual(gitTreeSubject(TREE), { kind: "git-tree", digest: TREE });
  assert.equal(subjectDigest(gitTreeSubject(TREE)), TREE);
  assert.equal(subjectDigest(gitTreeSubject(TREE64)), TREE64);
  assert.throws(() => gitTreeSubject(TREE.toUpperCase()), RangeError);
  assert.throws(() => gitTreeSubject(TREE.slice(1)), RangeError);
});

const ENTRIES: readonly ManifestEntry[] = [
  {
    kind: "blob",
    mode: "100644",
    oid: "1111111111111111111111111111111111111111",
    sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    path: "README.md",
  },
  {
    kind: "blob",
    mode: "100755",
    oid: "2222222222222222222222222222222222222222",
    sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    path: "bin/run",
  },
  {
    kind: "link",
    mode: "120000",
    oid: "3333333333333333333333333333333333333333",
    sha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    path: "docs/link",
  },
  {
    kind: "gitlink",
    mode: "160000",
    oid: "4444444444444444444444444444444444444444",
    path: "vendor/sub",
  },
  {
    kind: "blob",
    mode: "100644",
    oid: "5555555555555555555555555555555555555555",
    sha256: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    path: "dir/\u{1F600}.txt",
  },
  {
    kind: "blob",
    mode: "100644",
    oid: "6666666666666666666666666666666666666666",
    sha256: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    path: "dir/\uFF5E.txt",
  },
];

const GOLDEN =
  "blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 100644 1111111111111111111111111111111111111111 README.md\n" +
  "blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 100755 2222222222222222222222222222222222222222 bin/run\n" +
  "blob eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee 100644 6666666666666666666666666666666666666666 dir/\uFF5E.txt\n" +
  "blob dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd 100644 5555555555555555555555555555555555555555 dir/\u{1F600}.txt\n" +
  "link cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc 120000 3333333333333333333333333333333333333333 docs/link\n" +
  "gitlink - 160000 4444444444444444444444444444444444444444 vendor/sub\n";

test("the manifest golden: UTF-8 byte order, LF-terminated, gitlink carries `-`", () => {
  const manifest = snapshotManifest(ENTRIES.toReversed());
  assert.deepEqual(manifest, { ok: true, text: GOLDEN, digest: sha256(GOLDEN) });
  // The UTF-16 sort would put the astral path first; the byte order puts U+FF5E first.
  assert.ok(["dir/\uFF5E.txt", "dir/\u{1F600}.txt"].sort()[0] === "dir/\u{1F600}.txt");
  assert.deepEqual(snapshotManifest(ENTRIES), manifest, "input order does not matter");
});

test("the empty manifest is the empty text and the empty-string digest", () => {
  assert.deepEqual(snapshotManifest([]), {
    ok: true,
    text: "",
    digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  });
});

/** A valid blob entry at `path`, with optional field overrides (to build malformed entries). */
function blob(path: string, overrides: Record<string, string> = {}): ManifestEntry {
  const entry: Record<string, string> = {
    kind: "blob",
    mode: "100644",
    oid: "7777777777777777777777777777777777777777",
    sha256: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    path,
    ...overrides,
  };
  return entry as unknown as ManifestEntry;
}

test("an unrepresentable entry is a problem naming its path, never a throw", () => {
  const cases: [string, ManifestEntry[], string][] = [
    ["LF", [blob("a\nb")], "a\nb"],
    ["NUL", [blob("a\0b")], "a\0b"],
    ["lone surrogate", [blob("a\uD800b")], "a\uD800b"],
    ["leading /", [blob("/a")], "/a"],
    ["trailing /", [blob("a/")], "a/"],
    ["empty segment", [blob("a//b")], "a//b"],
    ["dot segment", [blob("a/./b")], "a/./b"],
    ["dot", [blob(".")], "."],
    ["dot-dot", [blob("a/../b")], "a/../b"],
    ["duplicate path", [blob("same"), blob("x"), blob("same")], "same"],
    ["blob with mode 120000", [blob("m", { mode: "120000" })], "m"],
    ["uppercase oid", [blob("o", { oid: "7777777777777777777777777777777777777ABC" })], "o"],
    ["short sha256", [blob("s", { sha256: "ffff" })], "s"],
  ];
  for (const [label, entries, path] of cases) {
    const manifest = snapshotManifest(entries);
    assert.equal(manifest.ok, false, label);
    if (!manifest.ok) assert.ok(manifest.problem.includes(JSON.stringify(path)), label);
  }
});

test("isSnapshotPath accepts POSIX relative paths and rejects the rest", () => {
  for (const path of ["a", "a/b", "a.b/c", ".hidden", "a/..b", "\u{1F600}"]) {
    assert.equal(isSnapshotPath(path), true, JSON.stringify(path));
  }
  for (const path of [
    "",
    "/",
    "/a",
    "a/",
    "a//b",
    ".",
    "..",
    "a/.",
    "../a",
    "a\nb",
    "a\0",
    "\uDC00",
  ]) {
    assert.equal(isSnapshotPath(path), false, JSON.stringify(path));
  }
});

test("parseSnapshotManifest inverts the renderer: the golden and the empty text round-trip", () => {
  const parsed = parseSnapshotManifest(GOLDEN);
  assert.ok(parsed.ok, parsed.ok ? "" : parsed.problem);
  const rendered = snapshotManifest(parsed.entries);
  assert.ok(rendered.ok);
  assert.equal(rendered.text, GOLDEN);
  assert.deepEqual(
    new Set(parsed.entries.map((entry) => JSON.stringify(entry))),
    new Set(ENTRIES.map((entry) => JSON.stringify(entry))),
  );
  assert.deepEqual(parseSnapshotManifest(""), { ok: true, entries: [] });
});

test("parsed paths keep every character the grammar allows: CR and a leading BOM", () => {
  const paths = ["cr\r", "a\rb", "\uFEFFroot", "dir/\uFEFFnested"];
  const manifest = snapshotManifest(paths.map((path) => blob(path)));
  assert.ok(manifest.ok);
  assert.ok(manifest.text.includes("cr\r\n"), "a CR-ending path renders as a CRLF line ending");
  const parsed = parseSnapshotManifest(manifest.text);
  assert.ok(parsed.ok, parsed.ok ? "" : parsed.problem);
  assert.deepEqual(parsed.entries.map((entry) => entry.path).sort(), [...paths].sort());
  const again = snapshotManifest(parsed.entries);
  assert.ok(again.ok);
  assert.equal(again.text, manifest.text);
});

test("parseSnapshotManifest rejects every non-canonical text with a problem, never a throw", () => {
  const SHA = "f".repeat(64);
  const OID = "7".repeat(40);
  const line = (path: string, kind = "blob", sha = SHA, mode = "100644", oid = OID) =>
    `${kind} ${sha} ${mode} ${oid} ${path}\n`;
  const cases: [string, string][] = [
    ["no trailing LF", line("a").slice(0, -1)],
    ["too few fields", `blob ${SHA} 100644 ${OID}\n`],
    ["an empty path", `blob ${SHA} 100644 ${OID} \n`],
    ["unknown kind", line("a", "tree")],
    ["a blob with -", line("a", "blob", "-")],
    ["a gitlink with a sha", line("a", "gitlink", SHA, "160000")],
    ["lines out of order", line("b") + line("a")],
    ["a duplicate path", line("a") + line("a")],
    ["a .. segment", line("a/../b")],
    ["a mode/kind mismatch", line("a", "blob", SHA, "120000")],
    ["uppercase hex", line("a", "blob", SHA.toUpperCase())],
  ];
  for (const [label, text] of cases) {
    const parsed = parseSnapshotManifest(text);
    assert.equal(parsed.ok, false, label);
  }
  assert.ok(parseSnapshotManifest(line("a") + line("b")).ok, "the control is canonical");
});
