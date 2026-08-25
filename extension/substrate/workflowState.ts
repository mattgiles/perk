// The `perk:workflow-state` session tier (contracts.md §8.3) — rebuild and the strict-append
// seam (appendWorkflowState). The identity-lifecycle decisions (claim/fork-derive/stage
// resolution) live in `session/lifecycle.ts` — the named session operation.
//
// Mostly pure, fs-light logic kept separate from the `pi`/`ctx` effects (in index.ts); the
// strict-append seam touches effects only through structural slices (`EntrySink`, `BranchSource`,
// `ReportTarget`), so the whole module stays unit-testable under `node --test` with fakes. The
// reconstruction discipline (scan getBranch on session_start AND session_tree, per-field LWW)
// lives here.

import { type ReportTarget, report } from "../surfaces/report.ts";
import type { PlanRef } from "./cache.ts";

export const WORKFLOW_STATE_TYPE = "perk:workflow-state";

/**
 * A session-artifact provenance pointer (contracts §8.3): the session tier's proof
 * that a `scratch/runs/<run_id>/data/` file is current for THIS run. Reads validate the
 * on-disk file against the rebuilt pointer (run_id match + digest match) and refuse otherwise.
 */
export interface SessionArtifactPointer {
  run_id: string;
  name: string;
  /** Repo-relative, informational only — validation always re-derives via the seam. */
  path: string;
  /** `sha256:<hex>` of the file bytes as read back from disk. */
  digest: string;
  at: string; // ISO timestamp
}

export interface WorkflowState {
  run_id?: string;
  pi_session_id?: string;
  mode?: string;
  /** The registry stage id this run is acting on (recorded at cold claim from the handoff). */
  stage?: string;
  /**
   * The running @mgiles/perk version stamped when run identity is established (§8.3) —
   * claim/fork/adopt/mint in session_start. The session-audit vintage layer's exact basis;
   * omitted when only the perkVersion() failure sentinel is available. Best-effort tier.
   */
  perk_version?: string;
  predecessor?: string;
  active_plan_ref?: PlanRef | null;
  active_objective?: string | null;
  last_review_batch?: unknown;
  /**
   * The last `/pr-review` outcome posted via the `post_pr_review` warm tool (§8.3):
   * `{pr, verdict, angles, covered_angles, comment_count, mode, at}`. After a recorded wave,
   * `angles` is the authoritative attempted manifest and `covered_angles` is its schema-valid
   * subset; standalone posts use the caller's `angles` for both. Best-effort tier (per-field LWW
   * in `rebuildWorkflowState`, no rebuild change). The PR comment stays canonical.
   */
  last_pr_review?: unknown;
  /**
   * The last review-door outcome posted via the `submit_pr_review` warm tool (§8.3):
   * `{pr, event, comment_count, mode, at}`. Best-effort tier (per-field LWW in
   * `rebuildWorkflowState`, no rebuild change). The submitted PR review stays canonical.
   */
  last_review?: unknown;
  /**
   * The accumulating per-PR posting ledger of a stacked review (§8.3/§8.4): one
   * `{pr, event, at}` row per REAL `submit_pr_review` success, ordered by posting time
   * (read-rebuild-append — the whole list is re-appended each time). The resume authority for
   * a partially-posted stack sequence: confirmed successes are skipped, never replayed.
   * Best-effort tier (per-field LWW in `rebuildWorkflowState`, no rebuild change).
   */
  review_posts?: unknown;
  /** Session-artifact provenance pointers, keyed by artifact name (§8.3). */
  session_artifacts?: Record<string, SessionArtifactPointer> | null;
  /**
   * The objective node this session has claimed `planning` (§8.3) — the warm
   * node-link carrier an approval-triggered save recovers from. Written by the `objective_node`
   * tool on a successful `planning` transition; cleared on a non-planning transition for the same
   * node and after a successful node-linked plan save. Best-effort tier.
   */
  objective_node_claim?: { objective: string; node: string } | null;
  /**
   * The dream-wave finalized-bundle digest marker (§8.61) — the freshness/integrity authority
   * the dream-report recovery (§8.63) trusts over the bare run-scratch bundle file. `""` =
   * invalidated (cleared unconditionally at wave entry BEFORE the stale-bundle removal attempt,
   * so a failed cleanup leaves prior files behind but recovery refuses them); `sha256:<hex>` =
   * the digest of the current finalized bundle bytes, set only after a successful finalize
   * write. Per-field LWW; no rebuild change.
   */
  dream_bundle_digest?: string;
  /**
   * The bounded conflict-resolution re-drive counter (§8.3). Incremented on each
   * `perk.conflict-resolver` dispatch from EITHER warm surface — `/submit`'s PR-rebase drive on
   * a definitively-unmergeable PR, or `/objective-sync`'s retained-continuation drive; reset to
   * 0 on any clean completion (a clean submit; a clean non-declined mutating stack
   * sync/continue/abort/adopt). Best-effort tier (cheaply reconstructable). Per-field LWW in
   * `rebuildWorkflowState` handles it with no rebuild change.
   */
  conflict_resolution_attempts?: number;
}

/** The structural slice of a session entry that the rebuild cares about. */
export interface BranchEntry {
  type: string;
  customType?: string;
  data?: Record<string, unknown>;
  /** Present on Pi custom_message entries (hidden model-context messages). */
  content?: unknown;
}

/** The minimal read-only session surface the branch accessor needs. */
export interface BranchSource {
  sessionManager: { getBranch(): unknown[] };
}

/**
 * The one typed seam over `sessionManager.getBranch()`. Centralizes the single unavoidable
 * assertion from the SDK's `SessionEntry[]` (surfaced here as `unknown[]`) to perk's structural
 * `BranchEntry[]`. The SDK union (whose `CustomEntry.data` is `unknown`) is not assignable to the
 * structural slice, so the assertion is irreducible — do not "fix" it into a type error.
 * `ExtensionContext` and the test harness `session` both satisfy `BranchSource`.
 */
export function branchOf(source: BranchSource): BranchEntry[] {
  return source.sessionManager.getBranch() as BranchEntry[];
}

/**
 * Whether any entry on the branch already carries `needle` — the once-only injection dedup guard
 * (the bindingDelivery `branchHasHeader` form). Serializing each entry is the robust,
 * shape-agnostic scan; safe while the needle is a distinctive literal that other entries' data
 * can't casually contain (known accepted false positive: a tool result quoting perk's own source;
 * the typed customType scan is the escalation if that bites — docs/learned/pi/context-injection.md).
 */
export function branchCarries(branch: readonly BranchEntry[], needle: string): boolean {
  return branch.some((entry) => JSON.stringify(entry).includes(needle));
}

/**
 * The branch entries still represented directly in model context. Before compaction that is the
 * full branch. After compaction, Pi keeps entries from `firstKeptEntryId` onward plus anything
 * appended later; historical entries before that cutoff survive only through the summary.
 * Compaction entries are excluded because text quoted by a summary is not a live custom block.
 */
export function activeContextWindow(branch: readonly BranchEntry[]): BranchEntry[] {
  let latestCompaction = -1;
  for (let i = branch.length - 1; i >= 0; i--) {
    if (branch[i]?.type === "compaction") {
      latestCompaction = i;
      break;
    }
  }
  if (latestCompaction === -1) return [...branch];

  const firstKeptEntryId = (branch[latestCompaction] as { firstKeptEntryId?: unknown })
    .firstKeptEntryId;
  const firstKept =
    typeof firstKeptEntryId === "string"
      ? branch.findIndex(
          (entry, index) =>
            index < latestCompaction && (entry as { id?: unknown }).id === firstKeptEntryId,
        )
      : -1;
  const start = firstKept === -1 ? latestCompaction + 1 : firstKept;
  return branch.slice(start).filter((entry) => entry.type !== "compaction");
}

/**
 * Per-field last-write-wins over the `perk:workflow-state` custom entries on a branch.
 * Non-perk entries are ignored; `undefined` fields never clobber (but explicit `null` does).
 */
export function rebuildWorkflowState(entries: readonly BranchEntry[]): WorkflowState {
  const state: Record<string, unknown> = {};
  for (const entry of entries) {
    if (entry.type !== "custom" || entry.customType !== WORKFLOW_STATE_TYPE) continue;
    for (const [key, value] of Object.entries(entry.data ?? {})) {
      if (value !== undefined) state[key] = value;
    }
  }
  return state as WorkflowState;
}

/** The structural append surface the strict-append seam needs; ExtensionAPI satisfies it. */
export interface EntrySink {
  appendEntry(customType: string, data?: unknown): void;
}

/**
 * The one strict-append seam over `perk:workflow-state` (contracts §8.3 verified-linkage tier):
 * append → rebuild → compare → report. Loud-but-non-fatal and NEVER throws: a mismatch or a
 * throwing append/rebuild is reported via the report() seam ({ alsoLog: true }) and returns
 * false. Idempotence pre-checks ("append iff the rebuilt value differs") stay at call sites.
 */
export function appendWorkflowState<K extends keyof WorkflowState>(
  sink: EntrySink,
  source: BranchSource & ReportTarget,
  opts: AppendWorkflowStateOpts<K>,
): boolean {
  return appendWorkflowStateClassified(sink, source, opts).status === "applied";
}

/** The strict-append options (shared by the boolean and classified entry points). */
export interface AppendWorkflowStateOpts<K extends keyof WorkflowState> {
  /** The entry payload — may carry extra fields beyond the verified one (the claim record). */
  data: WorkflowState;
  /** The field verified on read-back. */
  field: K;
  /** The value the rebuilt field must equal. */
  expected: WorkflowState[K];
  /** report() scope, e.g. "plan-save", "workflow-state linkage error". */
  scope: string;
  /** The mismatch message (byte-preserved per site). */
  failure: string;
  /** Comparator; default: (a, b) => Object.is(a ?? null, b ?? null). */
  equals?: (rebuilt: WorkflowState[K] | undefined, expected: WorkflowState[K]) => boolean;
}

/**
 * The classified strict-append outcome. `rejected` is PROVEN refusal-before-effect: the append
 * threw AND the rebuilt field is still not the expected value, so no entry landed. `unverified`
 * means an effect may have landed unproven — the append returned but the read-back missed, or
 * the post-throw rebuild itself failed.
 */
export type ClassifiedAppend =
  | { status: "applied" }
  | { status: "rejected"; problem: string }
  | { status: "unverified"; problem: string };

/**
 * The classified sibling of `appendWorkflowState` (same report discipline — every failure arm
 * reports loudly before returning). The extra classification work happens only on failure
 * paths: a throwing `appendEntry` is re-checked against the rebuilt branch — a field still not
 * equal to `expected` proves the entry never landed (`rejected`, the refusal-before-effect arm
 * the session seam surfaces); a field that DOES equal `expected` landed despite the throw (the
 * read-back is the proof authority — `applied`); a rebuild failure stays honest (`unverified`).
 */
export function appendWorkflowStateClassified<K extends keyof WorkflowState>(
  sink: EntrySink,
  source: BranchSource & ReportTarget,
  opts: AppendWorkflowStateOpts<K>,
): ClassifiedAppend {
  const equals =
    opts.equals ??
    ((a: WorkflowState[K] | undefined, b: WorkflowState[K]) => Object.is(a ?? null, b ?? null));
  try {
    sink.appendEntry(WORKFLOW_STATE_TYPE, opts.data);
    const rebuilt = rebuildWorkflowState(branchOf(source))[opts.field];
    if (equals(rebuilt, opts.expected)) return { status: "applied" };
    report(source, opts.scope, "error", opts.failure, { alsoLog: true });
    return { status: "unverified", problem: opts.failure };
  } catch (error) {
    const problem = `${String(opts.field)} append threw — ${String(error)}`;
    report(source, opts.scope, "error", problem, { alsoLog: true });
    try {
      const rebuilt = rebuildWorkflowState(branchOf(source))[opts.field];
      if (equals(rebuilt, opts.expected)) return { status: "applied" };
      return { status: "rejected", problem };
    } catch {
      return { status: "unverified", problem };
    }
  }
}

/** The warm node-link carrier's non-null shape (the `objective_node_claim` field). */
export type ObjectiveNodeClaim = NonNullable<WorkflowState["objective_node_claim"]>;

/** Structural claim equality (objective + node match); absent compares equal only to absent. */
export function nodeClaimsEqual(
  a: WorkflowState["objective_node_claim"] | undefined,
  b: WorkflowState["objective_node_claim"] | undefined,
): boolean {
  const an = a ?? null;
  const bn = b ?? null;
  if (an === null || bn === null) return an === bn;
  return an.objective === bn.objective && an.node === bn.node;
}

/** The rebuilt `objective_node_claim`, read fail-open (malformed/throwing branch → null). */
export function readNodeClaim(ctx: BranchSource): ObjectiveNodeClaim | null {
  try {
    const claim = rebuildWorkflowState(branchOf(ctx)).objective_node_claim ?? null;
    if (
      claim !== null &&
      typeof claim.objective === "string" &&
      claim.objective !== "" &&
      typeof claim.node === "string" &&
      claim.node !== ""
    ) {
      return claim;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Equality by identity (provider + pr_id) — the plan-ref dedup key. Two refs to
 * the same plan are equal even if other fields drift; absent compares equal only to absent.
 */
export function planRefsEqual(
  a: PlanRef | null | undefined,
  b: PlanRef | null | undefined,
): boolean {
  if (a === null || a === undefined || b === null || b === undefined) {
    return (a === null || a === undefined) && (b === null || b === undefined);
  }
  return a.provider === b.provider && a.pr_id === b.pr_id;
}
