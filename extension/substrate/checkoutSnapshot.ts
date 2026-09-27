// The checkout snapshot policy behind the writer-child bracket (contracts.md §8.75(l)): what a
// clean start is, and what an end state must equal. Pure — the git probes that produce an
// observation live in `git.ts`; this module only decides. Fail-closed throughout: an unprovable
// probe refuses the start and violates the end, never reads as "unchanged".
//
// The claim is END-STATE equality, never mid-window immutability: a transient modify-and-restore
// inside the window is invisible (§8.65's accepted residual). Ignored paths are invisible by
// design — that is where the writer is allowed to write.

/** One non-ignored untracked path: a file's sha256, a symlink's target, or `""` for anything else. */
export interface UntrackedEntry {
  path: string;
  kind: "file" | "symlink" | "other";
  digest: string;
}

/** The recorded clean start: HEAD plus the untracked inventory sorted by path. */
export interface CheckoutSnapshot {
  head: string;
  untracked: readonly UntrackedEntry[];
}

/** One observation of the checkout; `null` = that probe failed (unprovable). */
export interface SnapshotObservation {
  head: string | null;
  trackedChanges: string[] | null;
  flags: boolean | null;
  untracked: UntrackedEntry[] | null;
}

export type BracketOutcome =
  | { ok: true }
  | {
      ok: false;
      detail: string;
      moved: {
        head?: { from: string; to: string };
        tracked?: string[];
        flags?: true;
        untrackedAdded?: string[];
        untrackedRemoved?: string[];
        untrackedChanged?: string[];
        probeFailures?: string[];
      };
    };

const MAX_RENDERED_PATHS = 20;

/**
 * A path list as bounded DATA: each path JSON-quoted (control characters escaped, so a hostile
 * file name can never break the line), at most 20 shown then `(+N more)`.
 */
export function renderPaths(paths: readonly string[]): string {
  const shown = paths.slice(0, MAX_RENDERED_PATHS).map((p) => JSON.stringify(p));
  const rest = paths.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} (+${rest} more)` : shown.join(", ");
}

const PROBES = [
  ["head", "HEAD"],
  ["trackedChanges", "tracked-tree cleanliness"],
  ["flags", "index flag state"],
  ["untracked", "the untracked inventory"],
] as const;

function failedProbes(observation: SnapshotObservation): string[] {
  return PROBES.filter(([key]) => observation[key] === null).map(([, label]) => label);
}

function byPath(a: UntrackedEntry, b: UntrackedEntry): number {
  return a.path < b.path ? -1 : a.path > b.path ? 1 : 0;
}

const FLAGS_DETAIL =
  "the index carries assume-unchanged/skip-worktree flag(s) — tracked cleanliness cannot be proven";

/**
 * The clean-start policy: HEAD resolvable, tracked tree clean, no hiding index flags, and the
 * non-ignored untracked inventory readable (recorded — untracked paths are allowed at start,
 * never forbidden). Every problem is named in one detail.
 */
export function cleanStart(
  observation: SnapshotObservation,
): { ok: true; snapshot: CheckoutSnapshot } | { ok: false; detail: string } {
  const problems: string[] = [];
  const failures = failedProbes(observation);
  if (failures.length > 0) problems.push(`could not verify ${failures.join(", ")}`);
  if (observation.trackedChanges !== null && observation.trackedChanges.length > 0)
    problems.push(`uncommitted tracked changes: ${renderPaths(observation.trackedChanges)}`);
  if (observation.flags === true) problems.push(FLAGS_DETAIL);
  if (problems.length > 0 || observation.head === null || observation.untracked === null)
    return { ok: false, detail: problems.join("; ") };
  return {
    ok: true,
    snapshot: { head: observation.head, untracked: [...observation.untracked].sort(byPath) },
  };
}

/**
 * The end-state check: HEAD, tracked cleanliness, flags and the untracked inventory must EQUAL
 * the snapshot. Added, removed and changed (same path, different kind or digest) untracked
 * entries are each violations; any failed probe is a violation. Every observed difference is
 * accumulated into one detail, never just the first.
 */
export function compareEndState(
  snapshot: CheckoutSnapshot,
  observation: SnapshotObservation,
): BracketOutcome {
  const moved: Extract<BracketOutcome, { ok: false }>["moved"] = {};
  const parts: string[] = [];
  const failures = failedProbes(observation);
  if (failures.length > 0) {
    moved.probeFailures = failures;
    parts.push(`could not verify ${failures.join(", ")}`);
  }
  if (observation.head !== null && observation.head !== snapshot.head) {
    moved.head = { from: snapshot.head, to: observation.head };
    parts.push(`HEAD moved from ${snapshot.head} to ${observation.head}`);
  }
  if (observation.trackedChanges !== null && observation.trackedChanges.length > 0) {
    moved.tracked = [...observation.trackedChanges];
    parts.push(`tracked changes: ${renderPaths(moved.tracked)}`);
  }
  if (observation.flags === true) {
    moved.flags = true;
    parts.push(FLAGS_DETAIL);
  }
  if (observation.untracked !== null) {
    const before = new Map(snapshot.untracked.map((e) => [e.path, e]));
    const after = new Map(observation.untracked.map((e) => [e.path, e]));
    const added = [...after.keys()].filter((p) => !before.has(p)).sort();
    const removed = [...before.keys()].filter((p) => !after.has(p)).sort();
    const changed = [...after.values()]
      .filter((e) => {
        const prior = before.get(e.path);
        return prior !== undefined && (prior.kind !== e.kind || prior.digest !== e.digest);
      })
      .map((e) => e.path)
      .sort();
    if (added.length > 0) {
      moved.untrackedAdded = added;
      parts.push(`untracked added: ${renderPaths(added)}`);
    }
    if (removed.length > 0) {
      moved.untrackedRemoved = removed;
      parts.push(`untracked removed: ${renderPaths(removed)}`);
    }
    if (changed.length > 0) {
      moved.untrackedChanged = changed;
      parts.push(`untracked changed: ${renderPaths(changed)}`);
    }
  }
  return parts.length === 0 ? { ok: true } : { ok: false, detail: parts.join("; "), moved };
}
