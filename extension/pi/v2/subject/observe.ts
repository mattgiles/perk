// The git observation (docs/design/pi-durable-v2-foundations.md §5 the observer, §8): resolve the
// tracked ref once, materialize the subject snapshot (or reuse and verify it), and return the
// observation facts.
//
// It runs outside any commit; in the host it runs inside the owner lock, after the gate, because
// it writes under `<store>/subjects/`. It records nothing: the caller's reconcile commit records
// the facts and assigns `seq`, and `observedAt` is display data only.
//
// Invariants:
// - Single resolution: the ref resolves to one commit, and the tree is read from that commit oid.
// - `repo` is the realpath of the named repo root, and git's discovery stops there, so a
//   subdirectory of a repo fails to observe and switching worktrees changes the recorded repo.
// - Every operational failure — invalid input, a `GitError`, an unrepresentable tree, a failed
//   verification, a filesystem error, malformed facts — is `observation_failed` naming its step;
//   anything else is a programming error and is rethrown.

import { realpath } from "node:fs/promises";
import type { Observation, Observe } from "../host.ts";
import { isWellFormedText } from "../kernel/canonical.ts";
import { type ObservationFacts, observationProblem } from "../kernel/records.ts";
import { checkRefFormat, GitError, listTree, resolveCommitTree } from "./git.ts";
import { ensureSnapshot, type SnapshotHooks } from "./snapshot.ts";

export type GitObserverOptions = {
  readonly storeDir: string;
  /** The repo root: a worktree top, a linked worktree's top, or a bare git dir. */
  readonly repo: string;
  /** A ref name (`HEAD`, `main`, `refs/heads/main`, a tag), recorded verbatim. */
  readonly ref: string;
  /** The wall clock for `observedAt` only; default `Date.now`. */
  readonly now?: () => number;
  /** Test-only, forwarded to `ensureSnapshot`. */
  readonly hooks?: SnapshotHooks;
};

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

function isSystemError(error: unknown): error is Error {
  const code = errorCode(error);
  return error instanceof Error && typeof code === "string" && /^E[A-Z0-9]+$/.test(code);
}

function failed(detail: string): Observation {
  return { kind: "observation_failed", detail };
}

/** Observe `ref` in `repo` into the snapshot store at `storeDir`. Never records anything. */
export async function observeGitSubject(options: GitObserverOptions): Promise<Observation> {
  const { storeDir, repo, ref } = options;
  const shownRef = JSON.stringify(ref);
  // argv cannot carry NUL, and a leading `-` would read as an option.
  if (typeof repo !== "string" || repo === "" || repo.includes("\0")) {
    return failed(`repo ${JSON.stringify(repo)} is not a path`);
  }
  if (
    typeof ref !== "string" ||
    ref === "" ||
    !isWellFormedText(ref) ||
    ref.includes("\0") ||
    ref.startsWith("-")
  ) {
    return failed(`ref ${shownRef} is not a ref name`);
  }
  let step = `resolving repo ${repo}`;
  try {
    let repoRoot: string;
    try {
      repoRoot = await realpath(repo);
    } catch (error) {
      if (errorCode(error) === "ENOENT") return failed(`repo ${repo} is missing`);
      throw error;
    }
    step = `checking ref ${shownRef}`;
    if (!(await checkRefFormat(repoRoot, ref))) return failed(`ref ${shownRef} is not a ref name`);
    step = `resolving ref ${shownRef}`;
    let resolved: { readonly commit: string; readonly tree: string };
    try {
      resolved = await resolveCommitTree(repoRoot, ref);
    } catch (error) {
      if (!(error instanceof GitError)) throw error;
      return failed(
        `ref ${shownRef} does not resolve to a commit in ${repoRoot}: ${error.message}`,
      );
    }
    const { commit, tree } = resolved;
    const observedAt = (options.now ?? Date.now)();
    step = `listing tree ${tree}`;
    const listed = await listTree(repoRoot, tree);
    if (!listed.ok) return failed(`tree ${tree} cannot be represented: ${listed.problem}`);
    step = `materializing snapshot ${tree}`;
    const snapshot = await ensureSnapshot({
      storeDir,
      repoRoot,
      tree,
      entries: listed.entries,
      ...(options.hooks === undefined ? {} : { hooks: options.hooks }),
    });
    if (!snapshot.ok) return failed(snapshot.problem);
    const facts: ObservationFacts = {
      repo: repoRoot,
      ref,
      commit,
      tree,
      manifestDigest: snapshot.manifestDigest,
      observedAt,
    };
    const problem = observationProblem(facts);
    if (problem !== null) return failed(`observation is malformed: ${problem}`);
    return { kind: "observed", facts };
  } catch (error) {
    if (error instanceof GitError || isSystemError(error)) {
      return failed(`${step}: ${error.message}`);
    }
    throw error;
  }
}

/** The host's `Observe` seam over `observeGitSubject(options)`. */
export function gitObserver(options: GitObserverOptions): Observe {
  return () => observeGitSubject(options);
}
