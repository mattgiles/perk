// The snapshot environment (docs/design/pi-durable-v2-foundations.md §12 the native assignment):
// the read-only `ExecutionEnv` rooted at one subject snapshot, which every worker tool reads
// through, and the Harness env factory that hands it only to a worker conversation.
//
// Invariants:
// - One path gate. Every read member passes its path through `#contain` and hands the delegate
//   only the contained absolute path; `exec` is never delegated, and no write member reaches the
//   filesystem.
// - The root is trusted only as a real directory: only its parent (`subjects/`) is canonicalized,
//   and the root itself must `lstat` as a directory — never a symlink — when the environment opens
//   and again at every gate. A genuine snapshot holds no symlink (a git link materializes as a
//   regular file), so every symlink component below the root is refused, even one pointing inside.
// - Escapes and symlinks are `permission_denied`; malformed paths are `invalid`; a refused path is
//   never reported as absent (`exists` returns the refusal, so `read` surfaces it).
// - The factory resolves the snapshot from records, never from conversation config: a
//   conversation gets an environment only when its agent `cwd` is the symbolic workspace root AND
//   the durable map names it as some attempt's worker conversation. Everything else gets
//   `undefined`, so its tools fail closed.
//
// Residual (recorded in §12): each gate checks, then the delegate opens. A component swapped
// between the two is not refused at read time. Only an outside process with the user's privileges
// can swap one — the worker has no write capability — and such a process could equally write
// outside content into the snapshot, which the verification before acceptance refuses.

import { lstat, realpath } from "node:fs/promises";
import { basename, dirname, join, posix } from "node:path";
import type { Context } from "@earendil-works/chord";
import type { HarnessOptions } from "@earendil-works/pi-durable";
import {
  type BinaryReader,
  type DirReader,
  type ExecutionEnv,
  ExecutionError,
  err,
  FileError,
  type FileInfo,
  type FileWatcher,
  ok,
  type Result,
  type ShellExecResult,
  type TextLineReader,
} from "@earendil-works/pi-durable/env";
import { NodeExecutionEnv } from "@earendil-works/pi-durable/env/node";
import { indexRecords } from "../kernel/records.ts";
import { attemptOfConversation, readRecords } from "./records.ts";

/** The symbolic workspace root a worker conversation's agent `cwd` names. */
export const WORKSPACE_ROOT = "subject-snapshot";

const LABEL = "perk.v2 snapshot environment";

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

function isErrno(error: unknown): boolean {
  const code = errorCode(error);
  return error instanceof Error && typeof code === "string" && /^E[A-Z0-9]+$/.test(code);
}

function denied(message: string, path: string): Result<never, FileError> {
  return err(new FileError("permission_denied", `${LABEL}: ${message}`, path));
}

function readOnly<T>(member: string, path?: string): Result<T, FileError> {
  return err(
    new FileError("permission_denied", `${LABEL}: ${member} refused: read-only snapshot`, path),
  );
}

/** Strip trailing slashes from a normalized absolute POSIX path (keeping `/`). */
function trimTrailing(path: string): string {
  let trimmed = path;
  while (trimmed.length > 1 && trimmed.endsWith("/")) trimmed = trimmed.slice(0, -1);
  return trimmed;
}

export class SnapshotEnv implements ExecutionEnv {
  readonly id: string;
  readonly cwd: string;
  readonly #root: string;
  /** Used only for delegated reads, always with a contained absolute path. */
  readonly #inner: NodeExecutionEnv;

  private constructor(trusted: string) {
    this.#root = trusted;
    this.cwd = trusted;
    this.id = `perk.v2.snapshot:${trusted}`;
    this.#inner = new NodeExecutionEnv({ cwd: trusted });
  }

  /**
   * The environment over the snapshot root `root`, or `null` when the root is not a real directory
   * (absent, a file, or a symlink — even one pointing at a real directory).
   */
  static async open(root: string): Promise<SnapshotEnv | null> {
    let trusted: string;
    try {
      trusted = join(await realpath(dirname(root)), basename(root));
      const stats = await lstat(trusted);
      if (!stats.isDirectory()) return null;
    } catch (error) {
      if (isErrno(error)) return null;
      throw error;
    }
    return new SnapshotEnv(trusted);
  }

  /** The one path gate: the contained absolute path, or the refusal. */
  async #contain(path: unknown): Promise<Result<string, FileError>> {
    if (typeof path !== "string" || path === "" || path.includes("\0")) {
      return err(
        new FileError(
          "invalid",
          `${LABEL}: malformed path`,
          typeof path === "string" ? path : undefined,
        ),
      );
    }
    const root = this.#root;
    const normalized = trimTrailing(
      posix.isAbsolute(path) ? posix.normalize(path) : posix.join(root, path),
    );
    if (normalized !== root && !normalized.startsWith(`${root}/`)) {
      return denied("escapes the snapshot root", path);
    }
    try {
      const stats = await lstat(root);
      if (stats.isSymbolicLink() || !stats.isDirectory()) {
        return denied("symlink: the snapshot root is not a real directory", path);
      }
    } catch (error) {
      if (isErrno(error)) return denied("the snapshot root is unavailable", path);
      throw error;
    }
    const relative = normalized === root ? "" : normalized.slice(root.length + 1);
    let current = root;
    for (const segment of relative === "" ? [] : relative.split("/")) {
      current = `${current}/${segment}`;
      try {
        if ((await lstat(current)).isSymbolicLink()) return denied("symlink", path);
      } catch (error) {
        const code = errorCode(error);
        // Nothing exists below here to follow; the delegate reports `not_found`.
        if (code === "ENOENT" || code === "ENOTDIR") break;
        if (isErrno(error)) return denied(`cannot inspect a component (${String(code)})`, path);
        throw error;
      }
    }
    return ok(normalized);
  }

  async absolutePath(path: string, _context: Context): Promise<Result<string, FileError>> {
    return this.#contain(path);
  }

  async joinPath(parts: string[], _context: Context): Promise<Result<string, FileError>> {
    // A pure join; the result is gated wherever it is used.
    return ok(posix.join(...parts));
  }

  async readTextFile(path: string, context: Context): Promise<Result<string, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.readTextFile(contained.value, context) : contained;
  }

  async openTextLineReader(
    path: string,
    context: Context,
  ): Promise<Result<TextLineReader, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.openTextLineReader(contained.value, context) : contained;
  }

  async readTextLines(
    path: string,
    options: { maxLines?: number } | undefined,
    context: Context,
  ): Promise<Result<string[], FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.readTextLines(contained.value, options, context) : contained;
  }

  async readBinaryFile(path: string, context: Context): Promise<Result<Uint8Array, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.readBinaryFile(contained.value, context) : contained;
  }

  async openBinaryReader(
    path: string,
    _options: { noFollow?: boolean } | undefined,
    context: Context,
  ): Promise<Result<BinaryReader, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok
      ? this.#inner.openBinaryReader(contained.value, { noFollow: true }, context)
      : contained;
  }

  async fileInfo(path: string, context: Context): Promise<Result<FileInfo, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.fileInfo(contained.value, context) : contained;
  }

  async listDir(path: string, context: Context): Promise<Result<FileInfo[], FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.listDir(contained.value, context) : contained;
  }

  async openDirReader(path: string, context: Context): Promise<Result<DirReader, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.openDirReader(contained.value, context) : contained;
  }

  async canonicalPath(path: string, context: Context): Promise<Result<string, FileError>> {
    const contained = await this.#contain(path);
    if (!contained.ok) return contained;
    const canonical = await this.#inner.canonicalPath(contained.value, context);
    if (canonical.ok && canonical.value !== contained.value) {
      return denied("canonical path differs from the contained path", path);
    }
    return canonical;
  }

  async exists(path: string, context: Context): Promise<Result<boolean, FileError>> {
    const contained = await this.#contain(path);
    return contained.ok ? this.#inner.exists(contained.value, context) : contained;
  }

  async writeFile(path: string): Promise<Result<void, FileError>> {
    return readOnly("writeFile", path);
  }

  async appendFile(path: string): Promise<Result<void, FileError>> {
    return readOnly("appendFile", path);
  }

  async truncateFile(path: string): Promise<Result<void, FileError>> {
    return readOnly("truncateFile", path);
  }

  async flushFile(path: string): Promise<Result<void, FileError>> {
    return readOnly("flushFile", path);
  }

  async renameFile(sourcePath: string): Promise<Result<void, FileError>> {
    return readOnly("renameFile", sourcePath);
  }

  async createDir(path: string): Promise<Result<void, FileError>> {
    return readOnly("createDir", path);
  }

  async remove(path: string): Promise<Result<void, FileError>> {
    return readOnly("remove", path);
  }

  async createTempDir(): Promise<Result<string, FileError>> {
    return readOnly("createTempDir");
  }

  async createTempFile(): Promise<Result<string, FileError>> {
    return readOnly("createTempFile");
  }

  async watch(): Promise<Result<FileWatcher, FileError>> {
    return err(new FileError("not_supported", `${LABEL}: watch is not supported`));
  }

  async exec(): Promise<Result<ShellExecResult, ExecutionError>> {
    return err(new ExecutionError("shell_unavailable", `${LABEL}: exec refused`));
  }

  async cleanup(_context: Context): Promise<void> {}
}

export type SnapshotEnvFactoryOptions = {
  /** The snapshot directory of a subject tree (`<store>/subjects/<tree>`). */
  readonly snapshotRoot: (tree: string) => string;
};

/**
 * The Harness env factory: a `SnapshotEnv` over the subject snapshot of the attempt whose worker
 * conversation the target is, resolved from records; `undefined` for every other conversation and
 * for a snapshot root that is not a real directory.
 */
export function snapshotEnvFactory(
  options: SnapshotEnvFactoryOptions,
): NonNullable<HarnessOptions["env"]> {
  return async (target) => {
    if (target.cwd !== WORKSPACE_ROOT) return undefined;
    const read = await readRecords(target.read);
    const index = indexRecords(read.records);
    const attempt = attemptOfConversation(index, read.durableMap, target.conversationId);
    if (attempt === null) return undefined;
    const assignment = index.assignments.get(attempt.assignmentId);
    if (assignment === undefined || assignment.capabilitySet.workspaceRoot !== target.cwd) {
      return undefined;
    }
    return (await SnapshotEnv.open(options.snapshotRoot(assignment.subject.digest))) ?? undefined;
  };
}
