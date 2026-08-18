// The per-row diff state machine behind the drawer's "Git changes" section (the
// sourceLoad.ts extraction idiom: a small factory node:test drives directly). One
// cache per App; a diff is fetched at most once per status snapshot — every new
// status outcome invalidates the whole cache, and a response tagged with a stale
// generation is dropped (latest-wins), so a pre-invalidation response can never
// repopulate a cleared row.

import { GIT_DIFF_FAILED_COPY, GIT_DIFF_UNAVAILABLE_COPY, type GitDiffOutcome } from "./git.ts";

// A path absent from the state map is `idle`; the cache never stores idle rows.
// Unavailable diffs fold into `failed` with their reason-specific fixed copy —
// the row presentation vocabulary is exactly these four states.
export type GitDiffRowState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; diff: string; truncated: boolean }
  | { status: "failed"; copy: string };

export const GIT_DIFF_IDLE_ROW: GitDiffRowState = { status: "idle" };

export type GitDiffCache = {
  open: (path: string) => void;
  invalidate: () => void;
  subscribe: (listener: () => void) => () => void;
  state: () => ReadonlyMap<string, GitDiffRowState>;
  dispose: () => void;
};

export type GitDiffCacheDeps = {
  fetchDiff: (path: string) => Promise<GitDiffOutcome>;
};

function rowFromOutcome(outcome: GitDiffOutcome): GitDiffRowState {
  if (outcome.status === "failed") {
    return { status: "failed", copy: GIT_DIFF_FAILED_COPY };
  }
  if (outcome.result.status === "unavailable") {
    return { status: "failed", copy: GIT_DIFF_UNAVAILABLE_COPY[outcome.result.reason] };
  }
  return { status: "loaded", diff: outcome.result.diff, truncated: outcome.result.truncated };
}

export function createGitDiffCache(deps: GitDiffCacheDeps): GitDiffCache {
  let generation = 0;
  let rows = new Map<string, GitDiffRowState>();
  // The stable published snapshot (useSyncExternalStore-compatible): a NEW map per
  // mutation, the same reference between mutations.
  let snapshot: ReadonlyMap<string, GitDiffRowState> = new Map();
  const listeners = new Set<() => void>();

  function commit(): void {
    snapshot = new Map(rows);
    for (const listener of [...listeners]) {
      listener();
    }
  }

  return {
    open(path: string): void {
      // Re-opening a loading/loaded/failed row never refetches: results are
      // retained across close/reopen within one status snapshot.
      if (rows.has(path)) {
        return;
      }
      const requestGeneration = generation;
      rows.set(path, { status: "loading" });
      commit();
      void deps.fetchDiff(path).then(
        (outcome) => {
          if (requestGeneration !== generation) {
            return;
          }
          rows.set(path, rowFromOutcome(outcome));
          commit();
        },
        () => {
          // The classified fetcher never rejects by contract; a defensive arm keeps
          // an unexpected rejection presentable rather than unhandled.
          if (requestGeneration !== generation) {
            return;
          }
          rows.set(path, { status: "failed", copy: GIT_DIFF_FAILED_COPY });
          commit();
        },
      );
    },
    invalidate(): void {
      generation += 1;
      rows = new Map();
      commit();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    state(): ReadonlyMap<string, GitDiffRowState> {
      return snapshot;
    },
    dispose(): void {
      generation += 1;
      listeners.clear();
    },
  };
}
