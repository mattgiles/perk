// The subject proofs' shared fixture (dev-only): hermetic fixture repos, index-only entries,
// snapshot stores and a raw tree reader.
//
// Invariants the proofs rely on:
//   - Fixture git runs with every inherited `GIT_*` variable dropped, user and system config off
//     (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`) and a fixed author and committer, so
//     no hook, signing or user config runs.
//   - Entries a worktree cannot hold or should not hold (non-UTF-8, LF, CR or BOM names, gitlinks)
//     are built index-only: `addIndexEntry` after `stageAll` and before `commitIndex`, so `add -A`
//     never stages the absent path's deletion.
//   - Every store is removed through `discardTree`, which restores the `0555` directories' write
//     bits; it runs before the temp root's own plain removal (LIFO).

import { execFileSync } from "node:child_process";
import { chmodSync, lstatSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { TestContext } from "node:test";
import { decodeStrictUtf8 } from "../subject/git.ts";
import { discardTree } from "../subject/snapshot.ts";
import { defer, tempDir } from "./durable.ts";

const FIXTURE_GIT_TIMEOUT_MS = 30_000;

function fixtureEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith("GIT_")) env[key] = value;
  }
  return {
    ...env,
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_AUTHOR_NAME: "perk fixture",
    GIT_AUTHOR_EMAIL: "fixture@perk.invalid",
    GIT_COMMITTER_NAME: "perk fixture",
    GIT_COMMITTER_EMAIL: "fixture@perk.invalid",
  };
}

/** Run fixture git in `repo` (hermetic env); its stdout. Throws on a non-zero exit. */
export function fixtureGit(repo: string, args: readonly string[], input?: Buffer | string): Buffer {
  return execFileSync("git", args, {
    cwd: repo,
    env: fixtureEnv(),
    timeout: FIXTURE_GIT_TIMEOUT_MS,
    stdio: ["pipe", "pipe", "pipe"],
    ...(input === undefined ? {} : { input }),
  });
}

/** `fixtureGit`'s stdout as text, one trailing LF removed. */
function gitText(repo: string, args: readonly string[], input?: Buffer | string): string {
  return fixtureGit(repo, args, input).toString("utf8").replace(/\n$/, "");
}

/** A fresh repo (branch `main`) in a temp directory, removed after the test. */
export async function gitRepo(
  t: TestContext,
  options: { readonly objectFormat?: "sha1" | "sha256"; readonly bare?: boolean } = {},
): Promise<string> {
  const dir = await tempDir(t, "perk-v2-subject-repo-");
  fixtureGit(dir, [
    "init",
    "-q",
    "--initial-branch=main",
    ...(options.objectFormat === undefined ? [] : [`--object-format=${options.objectFormat}`]),
    ...(options.bare === true ? ["--bare"] : []),
    dir,
  ]);
  return dir;
}

/** Write `files` (repo-relative path → content) into the worktree, creating parent directories. */
export function writeFiles(repo: string, files: Readonly<Record<string, string | Buffer>>): void {
  for (const [path, content] of Object.entries(files)) {
    const file = join(repo, path);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, content);
  }
}

/** `git add -A`. */
export function stageAll(repo: string): void {
  fixtureGit(repo, ["add", "-A"]);
}

/** Commit the index as it stands (no add); the new commit's oid. */
export function commitIndex(repo: string, message: string): string {
  fixtureGit(repo, ["commit", "-q", "--allow-empty", "-m", message]);
  return gitText(repo, ["rev-parse", "HEAD"]);
}

/** `stageAll` then `commitIndex`. */
export function commitAll(repo: string, message: string): string {
  stageAll(repo);
  return commitIndex(repo, message);
}

/** The tree oid of `rev`. */
export function treeOf(repo: string, rev: string): string {
  return gitText(repo, ["rev-parse", `${rev}^{tree}`]);
}

/** Write `bytes` as a blob; its oid. */
export function hashObject(repo: string, bytes: Buffer | string): string {
  return gitText(repo, ["hash-object", "-w", "--stdin"], bytes);
}

/** Add one index entry `<mode> <oid>` at `path`; the path's bytes pass through raw. */
export function addIndexEntry(
  repo: string,
  mode: string,
  oid: string,
  path: string | Buffer,
): void {
  const record = Buffer.concat([
    Buffer.from(`${mode} ${oid}\t`, "utf8"),
    typeof path === "string" ? Buffer.from(path, "utf8") : path,
    Buffer.from([0]),
  ]);
  fixtureGit(repo, ["update-index", "--add", "-z", "--index-info"], record);
}

/**
 * A not-yet-existing `store` path inside a fresh temp directory. `discardTree` over the temp root
 * is registered after the root's own removal, so it runs first and restores the write bits.
 */
export async function subjectStore(t: TestContext): Promise<string> {
  const root = await tempDir(t, "perk-v2-subject-store-");
  defer(t, () => discardTree(root));
  return join(root, "store");
}

/** Add the owner write bit to `path`, so a tamper can edit or rename inside a snapshot. */
export function unlock(path: string): void {
  chmodSync(path, (lstatSync(path).mode & 0o7777) | 0o200);
}

export type TreeNode = {
  readonly path: string;
  readonly kind: "file" | "dir" | "symlink" | "other";
  readonly mode: number;
  readonly bytes?: Buffer;
};

/**
 * Every node under `dir` (lstat, no link following), sorted bytewise by path, with each regular
 * file's bytes. Names are read as raw bytes and decoded strictly, so a BOM-prefixed name is
 * reported exactly.
 */
export function readTree(dir: string): TreeNode[] {
  const nodes: { node: TreeNode; key: Buffer }[] = [];
  const walk = (absolute: string, relative: string): void => {
    for (const raw of readdirSync(absolute, { encoding: "buffer" })) {
      const name = decodeStrictUtf8(raw);
      if (name === null) throw new Error(`a name under ${absolute} is not valid UTF-8`);
      const path = relative === "" ? name : `${relative}/${name}`;
      const full = join(absolute, name);
      const stats = lstatSync(full);
      const mode = stats.mode & 0o7777;
      let node: TreeNode;
      if (stats.isDirectory()) node = { path, kind: "dir", mode };
      else if (stats.isFile()) node = { path, kind: "file", mode, bytes: readFileSync(full) };
      else if (stats.isSymbolicLink()) node = { path, kind: "symlink", mode };
      else node = { path, kind: "other", mode };
      nodes.push({ node, key: Buffer.from(path, "utf8") });
      if (stats.isDirectory()) walk(full, path);
    }
  };
  walk(dir, "");
  return nodes.sort((a, b) => Buffer.compare(a.key, b.key)).map(({ node }) => node);
}
