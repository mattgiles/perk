// The Git wire boundary: the one frontend vocabulary owner for the read-only Git
// observation endpoints. Closed literal arrays mirror perk_dev.prose_review.git;
// reject-unknown structural parsers return null on any ill-shaped payload AND on any
// envelope contradiction (the DTO construction invariants are re-checked here, so a
// contradictory payload can never reach a render). The complete fixed copy tables
// live here — components render these strings verbatim, never server text.

import type { FetchLike } from "./sourceLoad.ts";

export const GIT_FILE_STATES = ["modified", "added", "deleted", "untracked", "conflicted"] as const;
export type GitFileState = (typeof GIT_FILE_STATES)[number];

// `too-large` cannot occur on status (no per-file bound applies there); an unknown
// reason on either envelope folds to the parse-failure arm.
export const GIT_STATUS_UNAVAILABLE_REASONS = ["git-missing", "timeout", "git-error"] as const;
export type GitStatusUnavailableReason = (typeof GIT_STATUS_UNAVAILABLE_REASONS)[number];

export const GIT_DIFF_UNAVAILABLE_REASONS = [
  "git-missing",
  "timeout",
  "too-large",
  "git-error",
] as const;
export type GitDiffUnavailableReason = (typeof GIT_DIFF_UNAVAILABLE_REASONS)[number];

export type GitFileEntry = {
  path: string;
  state: GitFileState;
};

export type GitStatus =
  | { status: "available"; entries: GitFileEntry[]; otherChangeCount: number }
  | { status: "unavailable"; reason: GitStatusUnavailableReason };

export type GitDiff =
  | { status: "available"; diff: string; truncated: boolean }
  | { status: "unavailable"; reason: GitDiffUnavailableReason };

// State labels shared by tree badges, drawer rows, and the inspector row —
// always a text word, never color-only.
export const GIT_STATE_LABELS: Record<GitFileState, string> = {
  modified: "modified",
  added: "added",
  deleted: "deleted",
  untracked: "untracked",
  conflicted: "conflicted",
};

export const GIT_STATUS_UNAVAILABLE_COPY: Record<GitStatusUnavailableReason, string> = {
  "git-missing": "Git is not available on this machine.",
  timeout: "Git timed out.",
  "git-error": "Git could not report working-tree status.",
};

export const GIT_STATUS_FAILED_COPY = "Git status could not be loaded.";
export const GIT_STATUS_LOADING_COPY = "Loading Git status…";
export const GIT_STATUS_CLEAN_COPY = "No changes to catalog files.";

export function gitOtherChangesNote(count: number): string {
  return `${count} changed file(s) outside the catalog.`;
}

export const GIT_DIFF_LOADING_COPY = "Loading diff…";
export const GIT_DIFF_FAILED_COPY = "Git diff could not be loaded.";
export const GIT_DIFF_UNAVAILABLE_COPY: Record<GitDiffUnavailableReason, string> = {
  "git-missing": "Git is not available on this machine.",
  timeout: "Git timed out.",
  "too-large": "File too large to diff safely.",
  "git-error": "Git could not produce a diff for this file.",
};
export const GIT_DIFF_EMPTY_COPY = "No changes on disk for this file.";
export const GIT_DIFF_TRUNCATED_COPY = "Diff truncated — showing raw text.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function included<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

function parseGitFileEntry(value: unknown): GitFileEntry | null {
  if (
    !isRecord(value) ||
    typeof value.path !== "string" ||
    !included(GIT_FILE_STATES, value.state)
  ) {
    return null;
  }
  return { path: value.path, state: value.state };
}

/** Structurally validate a /api/git/status payload (null on defect or contradiction). */
export function parseGitStatus(value: unknown): GitStatus | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.status === "available") {
    if (
      value.reason !== null ||
      !Array.isArray(value.entries) ||
      !Number.isInteger(value.other_change_count) ||
      (value.other_change_count as number) < 0
    ) {
      return null;
    }
    const entries: GitFileEntry[] = [];
    for (const entry of value.entries) {
      const parsed = parseGitFileEntry(entry);
      if (parsed === null) {
        return null;
      }
      entries.push(parsed);
    }
    return {
      status: "available",
      entries,
      otherChangeCount: value.other_change_count as number,
    };
  }
  if (value.status === "unavailable") {
    // Contradiction rejection: an unavailable envelope must carry no entries and a
    // zero count (the DTO construction invariant, re-pinned at the parse boundary).
    if (
      !included(GIT_STATUS_UNAVAILABLE_REASONS, value.reason) ||
      !Array.isArray(value.entries) ||
      value.entries.length !== 0 ||
      value.other_change_count !== 0
    ) {
      return null;
    }
    return { status: "unavailable", reason: value.reason };
  }
  return null;
}

/** Structurally validate a /api/git/diff payload (null on defect or contradiction). */
export function parseGitDiff(value: unknown): GitDiff | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.status === "available") {
    if (
      value.reason !== null ||
      typeof value.diff !== "string" ||
      typeof value.truncated !== "boolean"
    ) {
      return null;
    }
    return { status: "available", diff: value.diff, truncated: value.truncated };
  }
  if (value.status === "unavailable") {
    // Contradiction rejection: unavailable ⇒ diff null AND truncated false.
    if (
      !included(GIT_DIFF_UNAVAILABLE_REASONS, value.reason) ||
      value.diff !== null ||
      value.truncated !== false
    ) {
      return null;
    }
    return { status: "unavailable", reason: value.reason };
  }
  return null;
}

export type GitStatusOutcome = { status: "loaded"; result: GitStatus } | { status: "failed" };
export type GitDiffOutcome = { status: "loaded"; result: GitDiff } | { status: "failed" };

/** GET and classify one working-tree status snapshot. Never rejects. */
export async function fetchGitStatus(fetchFn: FetchLike = fetch): Promise<GitStatusOutcome> {
  try {
    const response = await fetchFn("/api/git/status");
    if (!response.ok) {
      return { status: "failed" };
    }
    const result = parseGitStatus(await response.json());
    return result === null ? { status: "failed" } : { status: "loaded", result };
  } catch {
    return { status: "failed" };
  }
}

/** GET and classify one per-file diff (non-200 — the 404 included — is failed). Never rejects. */
export async function fetchGitDiff(
  path: string,
  fetchFn: FetchLike = fetch,
): Promise<GitDiffOutcome> {
  try {
    const response = await fetchFn(`/api/git/diff?path=${encodeURIComponent(path)}`);
    if (!response.ok) {
      return { status: "failed" };
    }
    const result = parseGitDiff(await response.json());
    return result === null ? { status: "failed" } : { status: "loaded", result };
  } catch {
    return { status: "failed" };
  }
}
