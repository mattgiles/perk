// Feature-tier tests for the commit + compaction operation (delivery/commitCompact.ts):
// deterministic recording fakes over `CommitCompactDeps` — no Pi, no harness. Proves the pinned
// invocation arm order (the gate performs ZERO git reads; the worktree probed before HEAD; HEAD
// probed ONLY on the drive arm), the fail-safe skip reasons, the minted baseline for all three
// D1 kinds, and the full settle matrix — including the D1 regression (an unprovable baseline
// skips even when the settle HEAD reads fine). The compile-time negatives (`@ts-expect-error`)
// pin the arm↔completion correlations runtime tests cannot prove.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type CommitCompactDeps,
  type CommitCompactSettle,
  type CommitCompactStart,
  type HeadBaseline,
  type PendingCompact,
  settleCommitAndCompact,
  startCommitAndCompact,
} from "./commitCompact.ts";

const CWD = "/scratch/repo";
const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);

interface Recorded {
  deps: CommitCompactDeps;
  /** Every probe, in call order: `dirty:<cwd>`, `head:<cwd>`, `commits:<cwd>:<from>`. */
  reads: string[];
}

/** A recording `CommitCompactDeps`: scripted observations, every read captured in order. */
function recorderDeps(script: {
  dirty?: boolean | null;
  head?: HeadBaseline;
  commits?: string | null;
}): Recorded {
  const reads: string[] = [];
  return {
    reads,
    deps: {
      worktreeDirty: (cwd) => {
        reads.push(`dirty:${cwd}`);
        return script.dirty ?? null;
      },
      headState: (cwd) => {
        reads.push(`head:${cwd}`);
        return script.head ?? { kind: "unprovable" };
      },
      commitsSince: (cwd, from) => {
        reads.push(`commits:${cwd}:${from}`);
        return script.commits ?? null;
      },
    },
  };
}

/** Deps whose every observation throws — the zero-git-reads sentinel. */
function throwingDeps(): CommitCompactDeps {
  const boom = (): never => {
    throw new Error("no git read may happen on this arm");
  };
  return { worktreeDirty: boom, headState: boom, commitsSince: boom };
}

// --- startCommitAndCompact: arm order + observation ordering ------------------------------------

test("start: the read-only gate compacts immediately and performs ZERO git reads", () => {
  const outcome = startCommitAndCompact(CWD, true, throwingDeps());
  assert.deepEqual(outcome, { kind: "compact-now", completion: { outcome: "read-only" } });
});

test("start: an indeterminate worktree skips (fail-safe) without probing HEAD", () => {
  const r = recorderDeps({ dirty: null });
  const outcome = startCommitAndCompact(CWD, false, r.deps);
  assert.deepEqual(outcome, { kind: "skip", reason: "indeterminate-worktree" });
  assert.deepEqual(r.reads, [`dirty:${CWD}`], "only the dirty probe ran — HEAD stays unread");
});

test("start: a clean worktree compacts immediately without probing HEAD", () => {
  const r = recorderDeps({ dirty: false });
  const outcome = startCommitAndCompact(CWD, false, r.deps);
  assert.deepEqual(outcome, { kind: "compact-now", completion: { outcome: "clean" } });
  assert.deepEqual(r.reads, [`dirty:${CWD}`], "only the dirty probe ran — HEAD stays unread");
});

test("start: the dirty arm probes dirty BEFORE head and mints the sha baseline", () => {
  const r = recorderDeps({ dirty: true, head: { kind: "sha", sha: SHA_A } });
  const outcome = startCommitAndCompact(CWD, false, r.deps);
  assert.deepEqual(outcome, {
    kind: "drive",
    pending: { cwd: CWD, baseline: { kind: "sha", sha: SHA_A } },
  });
  assert.deepEqual(r.reads, [`dirty:${CWD}`, `head:${CWD}`], "dirty first, head second");
});

test("start: the drive arm mints whatever baseline the probe reports (all three D1 kinds)", () => {
  const baselines: HeadBaseline[] = [
    { kind: "sha", sha: SHA_A },
    { kind: "unborn" },
    { kind: "unprovable" },
  ];
  for (const baseline of baselines) {
    const r = recorderDeps({ dirty: true, head: baseline });
    const outcome = startCommitAndCompact(CWD, false, r.deps);
    assert.deepEqual(
      outcome,
      { kind: "drive", pending: { cwd: CWD, baseline } },
      `an ${baseline.kind} baseline still drives — committing is always safe`,
    );
  }
});

// --- settleCommitAndCompact: the D1 settle matrix ------------------------------------------------

function pending(baseline: HeadBaseline): PendingCompact {
  return { cwd: CWD, baseline };
}

test("settle: sha baseline + unchanged HEAD skips (no-commit)", () => {
  const r = recorderDeps({ head: { kind: "sha", sha: SHA_A } });
  const outcome = settleCommitAndCompact(pending({ kind: "sha", sha: SHA_A }), r.deps);
  assert.deepEqual(outcome, { kind: "skip", reason: "no-commit" });
  assert.deepEqual(r.reads, [`head:${CWD}`], "no range listing on a skip");
});

test("settle: sha baseline + unreadable HEAD skips (no-commit, fail-safe)", () => {
  const r = recorderDeps({ head: { kind: "unprovable" } });
  const outcome = settleCommitAndCompact(pending({ kind: "sha", sha: SHA_A }), r.deps);
  assert.deepEqual(outcome, { kind: "skip", reason: "no-commit" });
});

test("settle: sha baseline + an unborn settle pointer skips (no readable sha is no proof)", () => {
  const r = recorderDeps({ head: { kind: "unborn" } });
  const outcome = settleCommitAndCompact(pending({ kind: "sha", sha: SHA_A }), r.deps);
  assert.deepEqual(outcome, { kind: "skip", reason: "no-commit" });
});

test("settle: sha baseline + moved HEAD compacts with the exact commitsSince payload", () => {
  const r = recorderDeps({
    head: { kind: "sha", sha: SHA_B },
    commits: "abc1234 the driven commit",
  });
  const outcome = settleCommitAndCompact(pending({ kind: "sha", sha: SHA_A }), r.deps);
  assert.deepEqual(outcome, {
    kind: "compact-now",
    completion: { outcome: "committed", commits: "abc1234 the driven commit" },
  });
  assert.deepEqual(
    r.reads,
    [`head:${CWD}`, `commits:${CWD}:${SHA_A}`],
    "the range listing starts at the sha baseline",
  );
});

test("settle: a null commitsSince listing rides the committed completion unmasked", () => {
  const r = recorderDeps({ head: { kind: "sha", sha: SHA_B }, commits: null });
  const outcome = settleCommitAndCompact(pending({ kind: "sha", sha: SHA_A }), r.deps);
  assert.deepEqual(outcome, {
    kind: "compact-now",
    completion: { outcome: "committed", commits: null },
  });
});

test("settle: unborn baseline + a readable settle sha proves the first commit (full listing)", () => {
  const r = recorderDeps({ head: { kind: "sha", sha: SHA_B }, commits: "abc1234 first commit" });
  const outcome = settleCommitAndCompact(pending({ kind: "unborn" }), r.deps);
  assert.deepEqual(outcome, {
    kind: "compact-now",
    completion: { outcome: "committed", commits: "abc1234 first commit" },
  });
  assert.deepEqual(
    r.reads,
    [`head:${CWD}`, `commits:${CWD}:null`],
    "the unborn arm lists everything (null from-sha)",
  );
});

test("settle: unborn baseline + an unreadable settle HEAD skips (no-commit)", () => {
  for (const settled of [{ kind: "unborn" }, { kind: "unprovable" }] as HeadBaseline[]) {
    const r = recorderDeps({ head: settled });
    const outcome = settleCommitAndCompact(pending({ kind: "unborn" }), r.deps);
    assert.deepEqual(outcome, { kind: "skip", reason: "no-commit" });
  }
});

test("settle: an unprovable baseline skips even when the settle HEAD reads fine (the D1 regression)", () => {
  // The regression D1 closes: a transient invocation-time read failure followed by a readable
  // settle-time HEAD must NOT compact — there is no proven baseline to compare against.
  const r = recorderDeps({
    head: { kind: "sha", sha: SHA_B },
    commits: "abc1234 someone's commit",
  });
  const outcome = settleCommitAndCompact(pending({ kind: "unprovable" }), r.deps);
  assert.deepEqual(outcome, { kind: "skip", reason: "unprovable-baseline" });
  assert.deepEqual(r.reads, [], "the unprovable arm decides on the baseline alone — no reads");
});

// --- compile-time negatives (the ready.test.ts pattern) ------------------------------------------

test("compile-time: an invocation compact-now cannot carry a committed completion", () => {
  const invalid: CommitCompactStart = {
    kind: "compact-now",
    // @ts-expect-error — the invocation arms never produce a committed completion.
    completion: { outcome: "committed", commits: null },
  };
  void invalid;
});

test("compile-time: settle arms are constrained to their matching payloads", () => {
  const settleClean: CommitCompactSettle = {
    kind: "compact-now",
    // @ts-expect-error — a settle compact-now is always the committed completion.
    completion: { outcome: "clean" },
  };
  void settleClean;
  const settleIndeterminate: CommitCompactSettle = {
    kind: "skip",
    // @ts-expect-error — the invocation skip reason never appears on the settle union.
    reason: "indeterminate-worktree",
  };
  void settleIndeterminate;
  // @ts-expect-error — the settle skip reasons never appear on the invocation union.
  const startNoCommit: CommitCompactStart = { kind: "skip", reason: "no-commit" };
  void startNoCommit;
});
