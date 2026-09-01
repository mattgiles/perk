// The commit + compaction feature op (the `/commit-and-compact` policy tier), Pi-free. Owns the
// invocation arm ORDER (read-only gate → indeterminate-worktree → clean → dirty/drive), the
// fail-safe posture (never compact without PROOF of a new commit), the observation ordering
// (worktree probed only past the gate; HEAD captured ONLY on the drive arm), the pending record,
// and the settle gate — which proves a NEW COMMIT (HEAD movement as range evidence, NOT
// end-state cleanliness: the guidance stages selectively, so a still-dirty tree after a real
// commit compacts BY DESIGN; no ancestry check). The feature carries no prose and no severity —
// every outcome is data; rendering and Pi delivery live in `pi/v1/delivery/commitCompact.ts`.

/** The discriminated pre-commit HEAD baseline. `unborn` (a resolvable branch pointer, no
 * commits yet) and `unprovable` (the probe failed outright) are DIFFERENT facts: an unborn
 * baseline lets a readable settle sha prove the first commit; an unprovable baseline can prove
 * nothing, so the settle arm skips it outright (fail-safe closure). */
export type HeadBaseline =
  | { kind: "sha"; sha: string }
  | { kind: "unborn" }
  | { kind: "unprovable" };

/** The one-shot record the dirty/drive arm mints — the settle gate compares against it. */
export interface PendingCompact {
  cwd: string;
  baseline: HeadBaseline;
}

/** The typed compaction completion the continuation render keys on. */
export type CommitCompactCompletion =
  | { outcome: "committed"; commits: string | null }
  | { outcome: "clean" }
  | { outcome: "read-only" };

/** The git observations the operation consumes — observations ONLY (the read-only gate rides a
 * plain parameter); ONE production composition, module-private in the installer, over
 * `substrate/git.ts`. `commitsSince(cwd, null)` lists everything — the unborn arm. */
export interface CommitCompactDeps {
  worktreeDirty(cwd: string): boolean | null;
  headState(cwd: string): HeadBaseline;
  commitsSince(cwd: string, from: string | null): string | null;
}

/** The invocation decision — compact now, skip loudly, or drive the commit turn. */
export type CommitCompactStart =
  | { kind: "compact-now"; completion: { outcome: "clean" } | { outcome: "read-only" } }
  | { kind: "skip"; reason: "indeterminate-worktree" }
  | { kind: "drive"; pending: PendingCompact };

/** The settle decision — compact on proven commit evidence, or skip loudly. */
export type CommitCompactSettle =
  | { kind: "skip"; reason: "no-commit" | "unprovable-baseline" }
  | { kind: "compact-now"; completion: { outcome: "committed"; commits: string | null } };

/** The invocation arms, in the pinned order: gate (NO git reads) → indeterminate worktree →
 * clean → dirty. Only the dirty arm probes HEAD and mints the pending record. An `unprovable`
 * baseline still DRIVES (committing is always safe); the settle gate is where it refuses. */
export function startCommitAndCompact(
  cwd: string,
  gateActive: boolean,
  deps: CommitCompactDeps,
): CommitCompactStart {
  if (gateActive) return { kind: "compact-now", completion: { outcome: "read-only" } };
  const dirty = deps.worktreeDirty(cwd);
  // Fail-safe: never compact when uncommitted work might exist.
  if (dirty === null) return { kind: "skip", reason: "indeterminate-worktree" };
  if (!dirty) return { kind: "compact-now", completion: { outcome: "clean" } };
  return { kind: "drive", pending: { cwd, baseline: deps.headState(cwd) } };
}

/** The settle gate: compact only on PROOF of a new commit against the minted baseline.
 * `sha` — an unreadable/unchanged settle HEAD skips; a moved HEAD compacts with the range
 * listing. `unborn` — a readable settle sha IS the first-commit proof (full listing);
 * unreadable skips. `unprovable` — skip OUTRIGHT: even a readable settle HEAD proves nothing
 * against a baseline that was never captured. */
export function settleCommitAndCompact(
  pending: PendingCompact,
  deps: CommitCompactDeps,
): CommitCompactSettle {
  const baseline = pending.baseline;
  switch (baseline.kind) {
    case "unprovable":
      return { kind: "skip", reason: "unprovable-baseline" };
    case "sha":
    case "unborn": {
      const settled = deps.headState(pending.cwd);
      if (settled.kind !== "sha" || (baseline.kind === "sha" && settled.sha === baseline.sha)) {
        return { kind: "skip", reason: "no-commit" };
      }
      const commits = deps.commitsSince(pending.cwd, baseline.kind === "sha" ? baseline.sha : null);
      return { kind: "compact-now", completion: { outcome: "committed", commits } };
    }
  }
  // Exhaustive over the baseline (no default arm): a new kind fails to compile here.
  const exhaustive: never = baseline;
  throw new Error(`unreachable head baseline: ${JSON.stringify(exhaustive)}`);
}
