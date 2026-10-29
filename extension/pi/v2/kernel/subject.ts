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
// - The parser is the renderer's inverse and accepts only canonical text: a parse must re-render
//   to exactly the input, so a parsed manifest is ordered, unique and valid by construction.
//   Every character `isSnapshotPath` allows is path data, a CR included — a line whose path ends
//   in CR ends in CRLF and is still canonical.

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

export type ParsedSnapshotManifest =
  | { readonly ok: true; readonly entries: readonly ManifestEntry[] }
  | { readonly ok: false; readonly problem: string };

/** The line's first four space-separated fields and the rest (the path), or `null` if fewer. */
function manifestFields(line: string): readonly [string, string, string, string, string] | null {
  const fields: string[] = [];
  let rest = line;
  for (let n = 0; n < 4; n++) {
    const at = rest.indexOf(" ");
    if (at < 0) return null;
    fields.push(rest.slice(0, at));
    rest = rest.slice(at + 1);
  }
  const [kind, sha, mode, oid] = fields;
  if (kind === undefined || sha === undefined || mode === undefined || oid === undefined) {
    return null;
  }
  if (rest === "") return null;
  return [kind, sha, mode, oid, rest];
}

function parsedEntry(
  kind: string,
  sha: string,
  mode: string,
  oid: string,
  path: string,
): ManifestEntry | string {
  switch (kind) {
    case "blob":
      if (sha === "-") return "a blob carries no sha256";
      if (mode !== "100644" && mode !== "100755")
        return `mode ${JSON.stringify(mode)} is not a blob mode`;
      return { kind, mode, oid, sha256: sha, path };
    case "link":
      if (sha === "-") return "a link carries no sha256";
      if (mode !== "120000") return `mode ${JSON.stringify(mode)} is not a link mode`;
      return { kind, mode, oid, sha256: sha, path };
    case "gitlink":
      if (sha !== "-") return "a gitlink carries a sha256";
      if (mode !== "160000") return `mode ${JSON.stringify(mode)} is not a gitlink mode`;
      return { kind, mode, oid, path };
    default:
      return `unknown entry kind ${JSON.stringify(kind)}`;
  }
}

/**
 * The entries of a canonical snapshot manifest, or the first problem. Never throws. A path keeps
 * everything after the fourth space, spaces and CR included; the result must re-render to exactly
 * `text`, which rejects order, duplicates and every other non-canonical form.
 */
export function parseSnapshotManifest(text: string): ParsedSnapshotManifest {
  if (typeof text !== "string") return { ok: false, problem: "manifest is not text" };
  if (text === "") return { ok: true, entries: [] };
  if (!text.endsWith("\n")) return { ok: false, problem: "manifest does not end with LF" };
  const entries: ManifestEntry[] = [];
  const lines = text.slice(0, -1).split("\n");
  for (let i = 0; i < lines.length; i++) {
    const fields = manifestFields(lines[i] ?? "");
    if (fields === null) return { ok: false, problem: `line ${i + 1}: fewer than five fields` };
    const entry = parsedEntry(...fields);
    if (typeof entry === "string") return { ok: false, problem: `line ${i + 1}: ${entry}` };
    entries.push(entry);
  }
  const rendered = snapshotManifest(entries);
  if (!rendered.ok) return { ok: false, problem: rendered.problem };
  if (rendered.text !== text) return { ok: false, problem: "manifest is not canonical" };
  return { ok: true, entries };
}
