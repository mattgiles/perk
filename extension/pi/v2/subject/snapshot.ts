// The subject snapshot store (docs/design/pi-durable-v2-foundations.md §5).
//
// Layout: `<store>/subjects/<tree>/` (the snapshot) and `<store>/subjects/<tree>.manifest` (its
// snapshot manifest). Temp names `subjects/.tmp.<nonce>` and `subjects/.tmp.<nonce>.manifest`, and
// every other stray name, are ignored.
//
// Invariants:
// - The manifest is derived from git entries and git object bytes, never from walking the
//   snapshot; the stored manifest file is never the source of the digest either.
// - A snapshot directory and a manifest file each appear only by renaming a complete temp, and are
//   written only when absent — never overwritten, never repaired. The directory is renamed before
//   the manifest, so a crash can leave a directory without its manifest (the next observation
//   writes the manifest from git and verifies the directory against it), never the reverse with a
//   half-written directory.
// - Reuse fails closed: a cached snapshot or manifest failing verification is a `problem`, and
//   nothing is rewritten. Recovery is manual (restore the write bits, remove, re-run).
// - No fsync: the protocol guards process death, not power loss; a torn write fails verification.
// - Modes are set explicitly with `chmod`, independent of the umask: files `0444`, directories
//   `0555`. Removing a snapshot therefore needs the write bits restored first (`discardTree`).
// - Directory-entry names are read as raw bytes and decoded strictly, a leading U+FEFF kept, so a
//   name differing only by a BOM is never collapsed into another.
// - The verifier never re-derives modes or gitlink oids from disk: the manifest digest
//   authenticates them.

import { createHash, randomUUID } from "node:crypto";
import { constants, type Stats } from "node:fs";
import { chmod, lstat, mkdir, open, readdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { isGitOid, isSha256Hex } from "../kernel/identity.ts";
import {
  isSnapshotPath,
  type ManifestEntry,
  parseSnapshotManifest,
  snapshotManifest,
} from "../kernel/subject.ts";
import { decodeStrictUtf8, readBlobs, type TreeEntry } from "./git.ts";

export const SUBJECTS_DIR = "subjects";
export const MANIFEST_SUFFIX = ".manifest";
export const SNAPSHOT_FILE_MODE = 0o444;
export const SNAPSHOT_DIR_MODE = 0o555;

const TEMP_PREFIX = ".tmp.";

function requireTree(tree: string): void {
  if (!isGitOid(tree)) throw new RangeError(`malformed tree oid: ${JSON.stringify(tree)}`);
}

/** `<store>/subjects/<tree>`; throws `RangeError` unless `tree` is a git oid. */
export function snapshotDir(storeDir: string, tree: string): string {
  requireTree(tree);
  return join(storeDir, SUBJECTS_DIR, tree);
}

/** `<store>/subjects/<tree>.manifest`; throws `RangeError` unless `tree` is a git oid. */
export function snapshotManifestPath(storeDir: string, tree: string): string {
  requireTree(tree);
  return join(storeDir, SUBJECTS_DIR, `${tree}${MANIFEST_SUFFIX}`);
}

/**
 * Test-only. `beforeRename(tempDir)` runs once the temp tree is complete (content written, every
 * mode set), immediately before the rename that would create the snapshot directory.
 */
export type SnapshotHooks = { beforeRename?(tempDir: string): Promise<void> };

export type EnsuredSnapshot =
  | { readonly ok: true; readonly manifestDigest: string }
  | { readonly ok: false; readonly problem: string };

export type SnapshotVerification =
  | { readonly ok: true }
  | { readonly ok: false; readonly problem: string };

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

function isErrno(error: unknown): error is Error & { code: string } {
  const code = errorCode(error);
  return error instanceof Error && typeof code === "string" && /^E[A-Z0-9]+$/.test(code);
}

/** Whether anything exists at `path` (`lstat`, no link following); other errors throw. */
async function exists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (errorCode(error) === "ENOENT") return false;
    throw error;
  }
}

type Kind = ManifestEntry["kind"];

type Planned = {
  readonly kind: Kind;
  readonly mode: string;
  readonly oid: string;
  readonly path: string;
};

function kindOf(entry: TreeEntry): Kind | null {
  if ((entry.mode === "100644" || entry.mode === "100755") && entry.type === "blob") return "blob";
  if (entry.mode === "120000" && entry.type === "blob") return "link";
  if (entry.mode === "160000" && entry.type === "commit") return "gitlink";
  return null;
}

/** Every proper ancestor directory of `path` (`a/b/c` → `a`, `a/b`). */
function ancestorsOf(path: string): string[] {
  const segments = path.split("/");
  const ancestors: string[] = [];
  for (let i = 1; i < segments.length; i++) ancestors.push(segments.slice(0, i).join("/"));
  return ancestors;
}

/** Map every entry to its manifest kind, or return the first problem; touches nothing. */
function planEntries(entries: readonly TreeEntry[]): readonly Planned[] | string {
  const planned: Planned[] = [];
  const paths = new Set<string>();
  const directories = new Set<string>();
  for (const entry of entries) {
    const shown = JSON.stringify(entry.path);
    const kind = kindOf(entry);
    if (kind === null) return `${shown}: unsupported tree entry ${entry.mode} ${entry.type}`;
    if (!isSnapshotPath(entry.path)) return `${shown}: not a snapshot path`;
    if (!isGitOid(entry.oid)) return `${shown}: oid is not a lowercase git oid`;
    if (paths.has(entry.path)) return `${shown}: duplicate path`;
    paths.add(entry.path);
    for (const ancestor of ancestorsOf(entry.path)) directories.add(ancestor);
    planned.push({ kind, mode: entry.mode, oid: entry.oid, path: entry.path });
  }
  for (const path of paths) {
    if (directories.has(path)) return `${JSON.stringify(path)}: both an entry and a directory`;
  }
  return planned;
}

function manifestEntry(planned: Planned, sha256: string | undefined): ManifestEntry | null {
  const { mode, oid, path } = planned;
  switch (planned.kind) {
    case "blob":
      if (sha256 === undefined || (mode !== "100644" && mode !== "100755")) return null;
      return { kind: "blob", mode, oid, sha256, path };
    case "link":
      if (sha256 === undefined || mode !== "120000") return null;
      return { kind: "link", mode, oid, sha256, path };
    case "gitlink":
      if (mode !== "160000") return null;
      return { kind: "gitlink", mode, oid, path };
  }
}

/** Best-effort removal: a cleanup failure never replaces the error being reported. */
async function discardQuietly(path: string): Promise<void> {
  await discardTree(path).catch(() => {});
}

/**
 * Materialize `tree` into `<store>/subjects/<tree>/` (or reuse the snapshot already there), write
 * its manifest when absent, and verify both against the manifest derived from git. An
 * unrepresentable entry or a failed verification is a `problem`; a `GitError` or a filesystem
 * error throws.
 */
export async function ensureSnapshot(options: {
  readonly storeDir: string;
  readonly repoRoot: string;
  readonly tree: string;
  readonly entries: readonly TreeEntry[];
  readonly hooks?: SnapshotHooks;
}): Promise<EnsuredSnapshot> {
  const { storeDir, repoRoot, tree, hooks } = options;
  const planned = planEntries(options.entries);
  if (typeof planned === "string") {
    return { ok: false, problem: `tree ${tree} cannot be represented: ${planned}` };
  }
  const subjects = join(storeDir, SUBJECTS_DIR);
  const target = snapshotDir(storeDir, tree);
  const manifestPath = snapshotManifestPath(storeDir, tree);
  await mkdir(subjects, { recursive: true });
  const temp = (await exists(target)) ? null : join(subjects, `${TEMP_PREFIX}${randomUUID()}`);

  let manifest: { readonly text: string; readonly digest: string };
  if (temp !== null) await mkdir(temp);
  try {
    const pathsByOid = new Map<string, string[]>();
    for (const entry of planned) {
      if (entry.kind === "gitlink") continue;
      const paths = pathsByOid.get(entry.oid);
      if (paths === undefined) pathsByOid.set(entry.oid, [entry.path]);
      else paths.push(entry.path);
    }
    const hashes = new Map<string, string>();
    await readBlobs(repoRoot, [...pathsByOid.keys()], async (oid, bytes) => {
      hashes.set(oid, createHash("sha256").update(bytes).digest("hex"));
      if (temp === null) return;
      for (const path of pathsByOid.get(oid) ?? []) {
        const file = join(temp, path);
        await mkdir(dirname(file), { recursive: true });
        await writeFile(file, bytes, { flag: "wx" });
        await chmod(file, SNAPSHOT_FILE_MODE);
      }
    });
    const entries: ManifestEntry[] = [];
    for (const entry of planned) {
      const built = manifestEntry(entry, hashes.get(entry.oid));
      if (built === null) throw new Error(`no content hash for ${JSON.stringify(entry.path)}`);
      entries.push(built);
    }
    const rendered = snapshotManifest(entries);
    if (!rendered.ok) {
      if (temp !== null) await discardQuietly(temp);
      return { ok: false, problem: rendered.problem };
    }
    manifest = rendered;
    if (temp !== null) {
      const directories = new Set<string>();
      for (const entry of planned) {
        for (const ancestor of ancestorsOf(entry.path)) directories.add(ancestor);
        if (entry.kind === "gitlink") {
          await mkdir(join(temp, entry.path), { recursive: true });
          directories.add(entry.path);
        }
      }
      // Deepest first, then the root; each chmod needs only search permission on the path.
      const ordered = [...directories].sort((a, b) => b.split("/").length - a.split("/").length);
      for (const directory of ordered) await chmod(join(temp, directory), SNAPSHOT_DIR_MODE);
      await chmod(temp, SNAPSHOT_DIR_MODE);
      await hooks?.beforeRename?.(temp);
    }
  } catch (error) {
    if (temp !== null) await discardQuietly(temp);
    throw error;
  }

  if (temp !== null) {
    // A sibling rename within `subjects/`: it never needs write permission on the `0555` temp.
    try {
      await rename(temp, target);
    } catch (error) {
      await discardQuietly(temp);
      const code = errorCode(error);
      if (code !== "ENOTEMPTY" && code !== "EEXIST") throw error;
      // Another observation materialized the tree first; verification decides below.
    }
  }

  if (!(await exists(manifestPath))) {
    const tempManifest = join(subjects, `${TEMP_PREFIX}${randomUUID()}${MANIFEST_SUFFIX}`);
    try {
      await writeFile(tempManifest, manifest.text, { flag: "wx" });
      await chmod(tempManifest, SNAPSHOT_FILE_MODE);
      await rename(tempManifest, manifestPath);
    } catch (error) {
      await rm(tempManifest, { force: true }).catch(() => {});
      throw error;
    }
  }

  const verified = await verifySnapshot(storeDir, tree, manifest.digest);
  if (!verified.ok) {
    return { ok: false, problem: `snapshot ${tree} failed verification: ${verified.problem}` };
  }
  return { ok: true, manifestDigest: manifest.digest };
}

/** A verification failure, raised inside the verifier and returned as its `problem`. */
class Unverified extends Error {}

/** `op()`, with an errno failure turned into a problem naming `what` and the code. */
async function step<T>(what: string, op: () => Promise<T>): Promise<T> {
  try {
    return await op();
  } catch (error) {
    if (isErrno(error)) throw new Unverified(`${what}: ${error.code}`);
    throw error;
  }
}

const READ_CHUNK = 64 * 1024;

/** The sha256 of a regular file's bytes, opened without following a link. */
async function fileSha256(path: string): Promise<string> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const hash = createHash("sha256");
    const buffer = Buffer.alloc(READ_CHUNK);
    for (;;) {
      const { bytesRead } = await handle.read(buffer, 0, READ_CHUNK, null);
      if (bytesRead === 0) break;
      hash.update(buffer.subarray(0, bytesRead));
    }
    return hash.digest("hex");
  } finally {
    await handle.close();
  }
}

function compareBuffers(a: Buffer, b: Buffer): number {
  return Buffer.compare(a, b);
}

function kindName(stats: Stats): string {
  if (stats.isSymbolicLink()) return "symlink";
  if (stats.isFIFO()) return "fifo";
  if (stats.isSocket()) return "socket";
  return "device";
}

async function verifyOrThrow(
  storeDir: string,
  tree: string,
  manifestDigest: string,
): Promise<void> {
  const manifestPath = snapshotManifestPath(storeDir, tree);
  const manifestName = `${tree}${MANIFEST_SUFFIX}`;
  const manifestStats = await lstat(manifestPath).catch((error: unknown) => {
    if (errorCode(error) === "ENOENT") throw new Unverified(`missing manifest ${manifestName}`);
    if (isErrno(error)) throw new Unverified(`manifest ${manifestName}: ${error.code}`);
    throw error;
  });
  if (!manifestStats.isFile()) throw new Unverified(`manifest ${manifestName} is not a file`);
  const handle = await step(`manifest ${manifestName}`, () =>
    open(manifestPath, constants.O_RDONLY | constants.O_NOFOLLOW),
  );
  const bytes = await step(`manifest ${manifestName}`, async () => {
    try {
      return await handle.readFile();
    } finally {
      await handle.close();
    }
  });
  if (createHash("sha256").update(bytes).digest("hex") !== manifestDigest) {
    throw new Unverified("manifest digest mismatch");
  }
  const text = decodeStrictUtf8(bytes);
  if (text === null) throw new Unverified("manifest is not valid UTF-8");
  const parsed = parseSnapshotManifest(text);
  if (!parsed.ok) throw new Unverified(`manifest: ${parsed.problem}`);
  const leaves = new Map<string, ManifestEntry>();
  const ancestors = new Set<string>();
  for (const entry of parsed.entries) {
    leaves.set(entry.path, entry);
    for (const ancestor of ancestorsOf(entry.path)) ancestors.add(ancestor);
  }

  const root = snapshotDir(storeDir, tree);
  const rootStats = await lstat(root).catch((error: unknown) => {
    if (errorCode(error) === "ENOENT") throw new Unverified(`missing snapshot directory ${tree}`);
    if (isErrno(error)) throw new Unverified(`snapshot directory ${tree}: ${error.code}`);
    throw error;
  });
  if (!rootStats.isDirectory()) throw new Unverified(`snapshot ${tree} is not a directory`);

  const seen = new Set<string>();
  const walk = async (directory: string, relative: string): Promise<void> => {
    const where = relative === "" ? "the snapshot root" : JSON.stringify(relative);
    const names = await step(`cannot list ${where}`, () =>
      readdir(directory, { encoding: "buffer" }),
    );
    for (const raw of names.sort(compareBuffers)) {
      const name = decodeStrictUtf8(raw);
      if (name === null) throw new Unverified(`a name in ${where} is not valid UTF-8`);
      const path = relative === "" ? name : `${relative}/${name}`;
      const shown = JSON.stringify(path);
      const absolute = join(directory, name);
      const stats = await step(`cannot stat ${shown}`, () => lstat(absolute));
      const leaf = leaves.get(path);
      if (stats.isDirectory()) {
        if (leaf?.kind === "gitlink") {
          const inside = await step(`cannot list ${shown}`, () => readdir(absolute));
          if (inside.length > 0) throw new Unverified(`gitlink ${shown} is not an empty directory`);
          seen.add(path);
        } else if (leaf === undefined && ancestors.has(path)) {
          await walk(absolute, path);
        } else {
          throw new Unverified(`unexpected directory ${shown}`);
        }
      } else if (stats.isFile()) {
        if (leaf === undefined) throw new Unverified(`unexpected file ${shown}`);
        if (leaf.kind === "gitlink") {
          throw new Unverified(`gitlink ${shown} is not an empty directory`);
        }
        const sha256 = await step(`cannot read ${shown}`, () => fileSha256(absolute));
        if (sha256 !== leaf.sha256) throw new Unverified(`content of ${shown} differs`);
        seen.add(path);
      } else {
        throw new Unverified(`unexpected ${kindName(stats)} at ${shown}`);
      }
    }
  };
  await walk(root, "");
  for (const entry of parsed.entries) {
    if (!seen.has(entry.path)) throw new Unverified(`missing ${JSON.stringify(entry.path)}`);
  }
}

/**
 * Verify the snapshot of `tree` against `manifestDigest`: the stored manifest's digest first
 * (before any parse), then the snapshot's paths and content against the manifest. Fails closed:
 * every missing, unreadable or altered path is a returned `problem` — the first in a walk sorted
 * bytewise by name, else the first missing path in manifest order. Throws `RangeError` only for a
 * malformed `tree` or `manifestDigest` (a caller bug).
 */
export async function verifySnapshot(
  storeDir: string,
  tree: string,
  manifestDigest: string,
): Promise<SnapshotVerification> {
  requireTree(tree);
  if (!isSha256Hex(manifestDigest)) {
    throw new RangeError(`malformed manifest digest: ${JSON.stringify(manifestDigest)}`);
  }
  try {
    await verifyOrThrow(storeDir, tree, manifestDigest);
    return { ok: true };
  } catch (error) {
    if (error instanceof Unverified) return { ok: false, problem: error.message };
    throw error;
  }
}

/** Give the owner rwx on every directory under `path` (lstat, never following a link). */
async function restoreDirectoryBits(path: Buffer): Promise<void> {
  let stats: Stats;
  try {
    stats = await lstat(path);
  } catch (error) {
    if (errorCode(error) === "ENOENT") return;
    throw error;
  }
  if (!stats.isDirectory()) return;
  await chmod(path, (stats.mode & 0o7777) | 0o700);
  for (const name of await readdir(path, { encoding: "buffer" })) {
    await restoreDirectoryBits(Buffer.concat([path, Buffer.from("/"), name]));
  }
}

/**
 * Remove the tree at `path` — a snapshot, a temp directory, a store — after restoring the owner's
 * write bits on every directory (snapshot directories are `0555`). An absent path is a no-op.
 */
export async function discardTree(path: string): Promise<void> {
  await restoreDirectoryBits(Buffer.from(path));
  await rm(path, { recursive: true, force: true });
}
