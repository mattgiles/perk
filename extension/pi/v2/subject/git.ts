// The observer's git reads (docs/design/pi-durable-v2-foundations.md §5 the observer).
//
// Invariants:
// - Every invocation is an argv array (never a shell) with an explicit timeout, and runs against
//   one named repo root: `git -C <root>`.
// - The environment is pinned: every inherited `GIT_*` variable is dropped, discovery is told not
//   to climb above the root (`GIT_CEILING_DIRECTORIES`), replace refs are ignored and no
//   credential prompt can block. The ceiling is a colon-separated list, so it cannot hold every
//   path; `checkRepoRoot` is the check that discovery settled on the named root.
// - The no-helper claim is scoped: neither the tree's content nor an inherited environment
//   variable can select a helper, because only `rev-parse`, `check-ref-format`, `ls-tree` and
//   `cat-file --batch` run, and none of them runs a filter, textconv, hook or checkout.
//   Repo-local, user and system config still apply (so `safe.directory` keeps working).
// - Raw committed bytes come only from `cat-file --batch`, never from `archive` or a checkout,
//   both of which apply `eol`, `export-*` and filter attributes.
// - Path bytes are decoded strictly (`decodeStrictUtf8`): invalid UTF-8 is a representability
//   problem, and a leading U+FEFF stays part of the name.

import { execFile, spawn } from "node:child_process";
import { dirname } from "node:path";
import type { Readable } from "node:stream";
import { isGitOid } from "../kernel/identity.ts";

/** The bound on every git invocation (a `cat-file --batch` stream included). */
export const GIT_TIMEOUT_MS = 60_000;
/** The cap on a captured git stdout (`ls-tree` listings, `rev-parse` output). */
export const GIT_LISTING_MAX_BUFFER = 64 * 1024 * 1024;

/** How much of a streamed git's stderr a `GitError` keeps. */
const STDERR_CAP = 64 * 1024;

// `ignoreBOM: true`: the default decoder consumes a leading U+FEFF as a byte-order mark, but in a
// filename those bytes belong to the name.
const STRICT_UTF8 = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

/** `bytes` as UTF-8 text, a leading U+FEFF kept; `null` when they are not valid UTF-8. */
export function decodeStrictUtf8(bytes: Uint8Array): string | null {
  try {
    return STRICT_UTF8.decode(bytes);
  } catch (error) {
    if (error instanceof TypeError) return null;
    throw error;
  }
}

/** A git invocation that failed: a non-zero exit, a spawn failure, a timeout, or bad output. */
export class GitError extends Error {
  constructor(args: readonly string[], reason: string, options?: { cause?: unknown }) {
    super(`git ${args.join(" ")} failed: ${reason}`, options);
    this.name = "GitError";
  }
}

/** `base` without any `GIT_*` variable, plus the observer's three pins. Pure. */
export function gitEnv(base: NodeJS.ProcessEnv, repoRoot: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(base)) {
    if (!key.startsWith("GIT_")) env[key] = value;
  }
  env.GIT_CEILING_DIRECTORIES = dirname(repoRoot);
  env.GIT_NO_REPLACE_OBJECTS = "1";
  env.GIT_TERMINAL_PROMPT = "0";
  return env;
}

type GitResult = { readonly exitCode: number; readonly stdout: Buffer; readonly stderr: string };

function exitReason(code: number, stderr: string): string {
  return stderr === "" ? `exit code ${code}` : `${stderr} (exit code ${code})`;
}

/**
 * Run `git -C <repoRoot> <args>` to completion. Resolves for any exit; throws `GitError` only for a
 * spawn failure, a timeout, a buffer overflow or a death by signal.
 */
function runGit(repoRoot: string, args: readonly string[]): Promise<GitResult> {
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      ["-C", repoRoot, ...args],
      {
        env: gitEnv(process.env, repoRoot),
        timeout: GIT_TIMEOUT_MS,
        maxBuffer: GIT_LISTING_MAX_BUFFER,
        encoding: "buffer",
      },
      (error, stdout, stderr) => {
        const stderrText = stderr.toString("utf8").trim();
        if (error === null) {
          resolve({ exitCode: 0, stdout, stderr: stderrText });
          return;
        }
        if (typeof error.code === "number") {
          resolve({ exitCode: error.code, stdout, stderr: stderrText });
          return;
        }
        if (error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") {
          reject(new GitError(args, `its output exceeded ${GIT_LISTING_MAX_BUFFER} bytes`));
        } else if (error.killed === true) {
          reject(new GitError(args, `timed out after ${GIT_TIMEOUT_MS} ms`));
        } else if (error.signal !== undefined && error.signal !== null) {
          reject(new GitError(args, `killed by ${error.signal}`));
        } else {
          reject(new GitError(args, `spawn failed: ${error.message}`, { cause: error }));
        }
      },
    );
  });
}

/**
 * Whether git's discovered repository is rooted exactly at `repoRoot`: it is the git dir itself
 * (a bare repo, or a named git dir), or `repoRoot` is the top of its work tree (a worktree or a
 * linked worktree). `GIT_CEILING_DIRECTORIES` is a colon-separated list, so a parent path holding
 * `:` silently weakens the ceiling; this check is what keeps discovery from settling on an
 * enclosing repo. Throws `GitError` when no repository is found at all.
 */
export async function checkRepoRoot(repoRoot: string): Promise<boolean> {
  const args = ["rev-parse", "--absolute-git-dir", "--is-inside-work-tree", "--show-prefix"];
  const result = await runGit(repoRoot, args);
  if (result.exitCode !== 0) throw new GitError(args, exitReason(result.exitCode, result.stderr));
  const text = result.stdout.toString("utf8");
  const lines = text.endsWith("\n") ? text.slice(0, -1).split("\n") : [];
  const [gitDir, insideWorkTree, prefix] = lines;
  if (
    lines.length !== 3 ||
    gitDir === undefined ||
    prefix === undefined ||
    (insideWorkTree !== "true" && insideWorkTree !== "false")
  ) {
    throw new GitError(args, `unexpected output ${JSON.stringify(text)}`);
  }
  return gitDir === repoRoot || (insideWorkTree === "true" && prefix === "");
}

/** Whether `ref` is a ref name (`check-ref-format --allow-onelevel`); not a revision expression. */
export async function checkRefFormat(repoRoot: string, ref: string): Promise<boolean> {
  const args = ["check-ref-format", "--allow-onelevel", ref];
  const result = await runGit(repoRoot, args);
  if (result.exitCode === 0) return true;
  if (result.exitCode === 1) return false;
  throw new GitError(args, exitReason(result.exitCode, result.stderr));
}

/** The one oid `rev-parse --verify` prints for `rev`; throws `GitError` otherwise. */
async function revParse(repoRoot: string, rev: string): Promise<string> {
  const args = ["rev-parse", "--verify", "--end-of-options", rev];
  const result = await runGit(repoRoot, args);
  if (result.exitCode !== 0) throw new GitError(args, exitReason(result.exitCode, result.stderr));
  const text = result.stdout.toString("latin1");
  const oid = text.endsWith("\n") ? text.slice(0, -1) : null;
  if (oid === null || !isGitOid(oid)) {
    throw new GitError(args, `unexpected output ${JSON.stringify(text)}`);
  }
  return oid;
}

/**
 * Resolve `ref` once, to a commit, and that commit to its tree. The tree is read from the commit
 * oid, never by resolving the ref again, so a ref moving meanwhile cannot pair one commit with
 * another's tree.
 */
export async function resolveCommitTree(
  repoRoot: string,
  ref: string,
): Promise<{ readonly commit: string; readonly tree: string }> {
  const commit = await revParse(repoRoot, `${ref}^{commit}`);
  const tree = await revParse(repoRoot, `${commit}^{tree}`);
  return { commit, tree };
}

/** One `ls-tree -r` entry: git's mode, type and oid, and the decoded path. */
export type TreeEntry = {
  readonly mode: string;
  readonly type: string;
  readonly oid: string;
  readonly path: string;
};

const NUL = 0x00;
const TAB = 0x09;
const LF = 0x0a;

/** True iff every byte is printable ASCII or a space. */
function isPrintableAscii(bytes: Uint8Array): boolean {
  return bytes.every((byte) => byte >= 0x20 && byte < 0x7f);
}

/**
 * Every entry of `tree`, recursively, from the repo root (`--full-tree`). A path that is not valid
 * UTF-8 is a representability `problem`, not a git failure; malformed output throws `GitError`.
 * Modes and types are reported as git prints them.
 */
export async function listTree(
  repoRoot: string,
  tree: string,
): Promise<
  | { readonly ok: true; readonly entries: readonly TreeEntry[] }
  | { readonly ok: false; readonly problem: string }
> {
  const args = ["ls-tree", "-r", "-z", "--full-tree", tree];
  const result = await runGit(repoRoot, args);
  if (result.exitCode !== 0) throw new GitError(args, exitReason(result.exitCode, result.stderr));
  const { stdout } = result;
  const entries: TreeEntry[] = [];
  let start = 0;
  while (start < stdout.length) {
    let end = stdout.indexOf(NUL, start);
    if (end < 0) end = stdout.length;
    const record = stdout.subarray(start, end);
    start = end + 1;
    const tab = record.indexOf(TAB);
    const header = tab < 0 ? record : record.subarray(0, tab);
    const fields = isPrintableAscii(header) ? header.toString("latin1").split(" ") : [];
    const [mode, type, oid] = fields;
    if (
      tab < 0 ||
      fields.length !== 3 ||
      mode === undefined ||
      type === undefined ||
      oid === undefined ||
      fields.some((field) => field === "")
    ) {
      throw new GitError(args, `unexpected output record ${JSON.stringify(record.toString())}`);
    }
    const path = decodeStrictUtf8(record.subarray(tab + 1));
    if (path === null) return { ok: false, problem: "a tree path is not valid UTF-8" };
    entries.push({ mode, type, oid, path });
  }
  return { ok: true, entries };
}

/** A pull reader over a byte stream: LF-terminated lines and exact byte counts. */
class ByteReader {
  readonly #stream: Readable;
  readonly #iterator: AsyncIterator<Buffer>;
  #pending: Buffer = Buffer.alloc(0);

  constructor(stream: Readable) {
    this.#stream = stream;
    this.#iterator = stream[Symbol.asyncIterator]();
  }

  async #next(): Promise<Buffer | null> {
    const next = await this.#iterator.next();
    return next.done === true ? null : next.value;
  }

  /** The bytes before the next LF (consumed), or `null` if the stream ends first. */
  async line(): Promise<Buffer | null> {
    for (;;) {
      const at = this.#pending.indexOf(LF);
      if (at >= 0) {
        const line = this.#pending.subarray(0, at);
        this.#pending = this.#pending.subarray(at + 1);
        return line;
      }
      const chunk = await this.#next();
      if (chunk === null) return null;
      this.#pending = Buffer.concat([this.#pending, chunk]);
    }
  }

  /** Exactly the next `count` bytes (consumed), or `null` if the stream ends first. */
  async exact(count: number): Promise<Buffer | null> {
    const parts = [this.#pending];
    let have = this.#pending.length;
    while (have < count) {
      const chunk = await this.#next();
      if (chunk === null) return null;
      parts.push(chunk);
      have += chunk.length;
    }
    const all = parts.length === 1 ? this.#pending : Buffer.concat(parts, have);
    this.#pending = all.subarray(count);
    return all.subarray(0, count);
  }

  /** Whether the stream ends with nothing more unread. */
  async atEnd(): Promise<boolean> {
    if (this.#pending.length > 0) return false;
    const chunk = await this.#next();
    if (chunk === null) return true;
    this.#pending = chunk;
    return false;
  }

  /** Stop reading: destroy the stream, so its close never waits on unread data. */
  cancel(): void {
    this.#stream.destroy();
  }
}

const BLOB_HEADER = /^([0-9a-f]+) ([a-z]+) ([0-9]+)$/;

/**
 * Stream the raw bytes of every object in `oids` through one `cat-file --batch`, in request order.
 * Each `onBlob` call finishes before the next object is parsed (backpressure). Every object must
 * echo the requested oid and be a blob; anything else — a missing object, another type,
 * truncation, trailing output or a failed exit — throws `GitError`. If `onBlob` throws, git is
 * killed and the callback's error is rethrown.
 */
export async function readBlobs(
  repoRoot: string,
  oids: readonly string[],
  onBlob: (oid: string, bytes: Buffer) => Promise<void>,
): Promise<void> {
  if (oids.length === 0) return;
  const args = ["cat-file", "--batch"];
  const child = spawn("git", ["-C", repoRoot, ...args], {
    env: gitEnv(process.env, repoRoot),
    stdio: ["pipe", "pipe", "pipe"],
    timeout: GIT_TIMEOUT_MS,
  });
  let spawnError: Error | undefined;
  let stdinError: Error | undefined;
  let stopped = false;
  let stderr = "";
  const closed = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve) => {
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
  child.on("error", (error) => {
    spawnError ??= error;
  });
  child.stdin.on("error", (error) => {
    stdinError ??= error;
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk: string) => {
    if (stderr.length < STDERR_CAP) stderr += chunk;
  });
  child.stdin.end(oids.map((oid) => `${oid}\n`).join(""));
  const reader = new ByteReader(child.stdout);

  /** Why the finished process failed, or `null` when it exited 0 cleanly. */
  const failure = async (): Promise<GitError | null> => {
    const { code, signal } = await closed;
    if (spawnError !== undefined) {
      return new GitError(args, `spawn failed: ${spawnError.message}`, { cause: spawnError });
    }
    if (signal !== null) {
      return new GitError(
        args,
        child.killed ? `timed out after ${GIT_TIMEOUT_MS} ms` : `killed by ${signal}`,
      );
    }
    if (code !== 0) return new GitError(args, exitReason(code ?? -1, stderr.trim()));
    if (stdinError !== undefined) {
      return new GitError(args, `writing its input failed: ${stdinError.message}`, {
        cause: stdinError,
      });
    }
    return null;
  };
  const stop = async (): Promise<void> => {
    stopped = true;
    child.kill("SIGKILL");
    reader.cancel();
    await closed;
  };
  /** The output ended early: git's own failure, if it had one, is the better report. */
  const endedEarly = async (detail: string): Promise<GitError> =>
    (await failure()) ?? new GitError(args, `unexpected output: ${detail}`);
  /** Output git never prints for a well-formed request: stop it and report the output. */
  const unexpected = async (detail: string): Promise<GitError> => {
    await stop();
    return new GitError(args, `unexpected output: ${detail}`);
  };

  try {
    for (let read = 0; read < oids.length; read++) {
      const requested = oids[read] ?? "";
      const headerBytes = await reader.line();
      if (headerBytes === null) {
        throw await endedEarly(`it ended after ${read} of ${oids.length} objects`);
      }
      const header = headerBytes.toString("latin1");
      const match = BLOB_HEADER.exec(header);
      if (match === null || match[1] !== requested || match[2] !== "blob") {
        throw await unexpected(`object ${requested} answered ${JSON.stringify(header)}`);
      }
      const size = Number(match[3]);
      if (!Number.isSafeInteger(size))
        throw await unexpected(`object ${requested} has size ${match[3]}`);
      const body = await reader.exact(size + 1);
      if (body === null) throw await endedEarly(`object ${requested} is truncated`);
      if (body[size] !== LF) throw await unexpected(`object ${requested} is not LF-terminated`);
      try {
        await onBlob(requested, body.subarray(0, size));
      } catch (error) {
        await stop();
        throw error;
      }
    }
    if (!(await reader.atEnd())) throw await unexpected("trailing bytes after the last object");
  } catch (error) {
    if (stopped || error instanceof GitError) throw error;
    // The pipe itself failed to read.
    await stop();
    throw new GitError(args, `reading its output failed: ${String(error)}`, { cause: error });
  }
  const failed = await failure();
  if (failed !== null) throw failed;
}
