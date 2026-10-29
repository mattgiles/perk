// The subject and the snapshot-manifest grammar (docs/design/pi-durable-v2-foundations.md §5).
//
// Invariants:
// - The fixture's subject is a git tree; its digest is the tree oid itself, git's own content
//   address, so a same-tree commit is the same subject.
// - The snapshot manifest is one LF-terminated line per entry,
//   `<kind> <sha256|-> <git-mode> <oid> <path>`, sorted bytewise by the UTF-8 encoding of the path
//   (not the UTF-16 sort); its digest is the sha256 of the manifest text.
// - A path that cannot be represented (LF, NUL, a lone surrogate, a non-relative or
//   non-normalized path) makes the manifest a `problem` result, never a throw, so the observer
//   can map it to `observation_failed`.

import { isWellFormedText, sha256Hex } from "./canonical.ts";
import { isGitOid, isSha256Hex } from "./identity.ts";

export type Subject = { readonly kind: "git-tree"; readonly digest: string };

/** The git-tree subject over `treeOid`; throws `RangeError` unless it is a git oid. */
export function gitTreeSubject(treeOid: string): Subject {
  if (!isGitOid(treeOid)) throw new RangeError(`malformed tree oid: ${JSON.stringify(treeOid)}`);
  return { kind: "git-tree", digest: treeOid };
}

/** The canonical digest of `subject`: for a git tree, the tree oid. */
export function subjectDigest(subject: Subject): string {
  return subject.digest;
}

/** A non-empty POSIX relative path with no empty, `.` or `..` segment, no LF or NUL, well-formed. */
export function isSnapshotPath(path: string): boolean {
  if (typeof path !== "string" || path === "") return false;
  if (path.includes("\n") || path.includes("\0") || !isWellFormedText(path)) return false;
  return path.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

export type ManifestEntry =
  | {
      readonly kind: "blob";
      readonly mode: "100644" | "100755";
      readonly oid: string;
      readonly sha256: string;
      readonly path: string;
    }
  | {
      readonly kind: "link";
      readonly mode: "120000";
      readonly oid: string;
      readonly sha256: string;
      readonly path: string;
    }
  | {
      readonly kind: "gitlink";
      readonly mode: "160000";
      readonly oid: string;
      readonly path: string;
    };

export type SnapshotManifest =
  | { readonly ok: true; readonly text: string; readonly digest: string }
  | { readonly ok: false; readonly problem: string };

const MODES_BY_KIND: Readonly<Record<string, readonly string[]>> = {
  blob: ["100644", "100755"],
  link: ["120000"],
  gitlink: ["160000"],
};

function entryProblem(entry: ManifestEntry): string | null {
  if (!isSnapshotPath(entry.path)) return "not a snapshot path";
  const modes = MODES_BY_KIND[entry.kind];
  if (modes === undefined) return `unknown entry kind ${JSON.stringify(entry.kind)}`;
  if (!modes.includes(entry.mode)) {
    return `mode ${JSON.stringify(entry.mode)} does not match kind ${entry.kind}`;
  }
  if (!isGitOid(entry.oid)) return "oid is not a lowercase git oid";
  if (entry.kind !== "gitlink" && !isSha256Hex(entry.sha256)) {
    return "sha256 is not 64 lowercase hex";
  }
  return null;
}

function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i++) {
    const delta = (a[i] ?? 0) - (b[i] ?? 0);
    if (delta !== 0) return delta;
  }
  return a.length - b.length;
}

function manifestLine(entry: ManifestEntry): string {
  const sha256 = entry.kind === "gitlink" ? "-" : entry.sha256;
  return `${entry.kind} ${sha256} ${entry.mode} ${entry.oid} ${entry.path}\n`;
}

/** The snapshot manifest over `entries`, or the first problem (naming its path and rule). */
export function snapshotManifest(entries: readonly ManifestEntry[]): SnapshotManifest {
  const seen = new Set<string>();
  for (const entry of entries) {
    const problem = entryProblem(entry);
    if (problem !== null) {
      return { ok: false, problem: `${JSON.stringify(entry.path)}: ${problem}` };
    }
    if (seen.has(entry.path)) {
      return { ok: false, problem: `${JSON.stringify(entry.path)}: duplicate path` };
    }
    seen.add(entry.path);
  }
  const encoder = new TextEncoder();
  const keyed = entries.map((entry) => ({ entry, bytes: encoder.encode(entry.path) }));
  const text = keyed
    .toSorted((a, b) => compareBytes(a.bytes, b.bytes))
    .map(({ entry }) => manifestLine(entry))
    .join("");
  return { ok: true, text, digest: sha256Hex(text) };
}
