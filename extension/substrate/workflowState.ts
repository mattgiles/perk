// The `perk:workflow-state` session tier (contracts.md §8.3) — rebuild, claim, fork-derive,
// and the strict-append seam (appendWorkflowState).
//
// Mostly pure, fs-light logic kept separate from the `pi`/`ctx` effects (in index.ts); the
// strict-append seam touches effects only through structural slices (`EntrySink`, `BranchSource`,
// `ReportTarget`), so the whole module stays unit-testable under `node --test` with fakes. The
// reconstruction discipline (scan getBranch on session_start AND session_tree, per-field LWW)
// and the verified-linkage claim live here.

import { type ReportTarget, report } from "../surfaces/report.ts";
import { listRunIds, type PlanRef, readHandoff } from "./cache.ts";

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
  predecessor?: string;
  active_plan_ref?: PlanRef | null;
  active_objective?: string | null;
  last_review_batch?: unknown;
  /**
   * The last `/pr-review` outcome posted via the `post_pr_review` warm tool (§8.3):
   * `{pr, verdict, angles, comment_count, mode, at}`. Best-effort tier (per-field LWW in
   * `rebuildWorkflowState`, no rebuild change). The PR comment stays canonical.
   */
  last_pr_review?: unknown;
  /**
   * The last review-door outcome posted via the `submit_pr_review` warm tool (§8.3):
   * `{pr, event, comment_count, mode, at}`. Best-effort tier (per-field LWW in
   * `rebuildWorkflowState`, no rebuild change). The submitted PR review stays canonical.
   */
  last_review?: unknown;
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
   * The bounded conflict-resolution re-drive counter (§8.3). Incremented each time
   * `/submit` drives the `perk.conflict-resolver` subagent on a definitively-unmergeable PR;
   * reset to 0 on a clean submit. Best-effort tier (cheaply reconstructable). Per-field LWW in
   * `rebuildWorkflowState` handles it with no rebuild change.
   */
  conflict_resolution_attempts?: number;
}

/** The structural slice of a session entry that the rebuild cares about. */
export interface BranchEntry {
  type: string;
  customType?: string;
  data?: Record<string, unknown>;
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
  opts: {
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
  },
): boolean {
  const equals =
    opts.equals ??
    ((a: WorkflowState[K] | undefined, b: WorkflowState[K]) => Object.is(a ?? null, b ?? null));
  try {
    sink.appendEntry(WORKFLOW_STATE_TYPE, opts.data);
    const rebuilt = rebuildWorkflowState(branchOf(source))[opts.field];
    if (equals(rebuilt, opts.expected)) return true;
    report(source, opts.scope, "error", opts.failure, { alsoLog: true });
    return false;
  } catch (error) {
    report(source, opts.scope, "error", `${String(opts.field)} append threw — ${String(error)}`, {
      alsoLog: true,
    });
    return false;
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

/**
 * Derive a fork-child run_id: `<parent>.<n>` where `n` is the max existing sibling + 1
 * (scanning `scratch/runs/`), else 1.
 */
export function deriveForkRunId(parentRunId: string, cwd: string): string {
  const prefix = `${parentRunId}.`;
  let max = 0;
  for (const id of listRunIds(cwd)) {
    if (!id.startsWith(prefix)) continue;
    const segment = id.slice(prefix.length).split(".")[0] ?? "";
    const n = Number.parseInt(segment, 10);
    if (Number.isInteger(n) && n > max) max = n;
  }
  return `${parentRunId}.${max + 1}`;
}

export type ClaimDecision =
  | { action: "keep"; source: "session"; state: WorkflowState }
  | {
      action: "fork";
      source: "fork";
      childRunId: string;
      parentRunId: string;
      state: WorkflowState;
    }
  | { action: "claim"; source: "env"; runId: string }
  | {
      action: "adopt";
      source: "env-child";
      childRunId: string;
      parentRunId: string;
      /** Inherited from the parent's handoff so read-only gating survives into the child. */
      mode?: string;
    }
  | { action: "none"; source: "none"; state: WorkflowState };

/**
 * Decide what `session_start` should do, from the rebuilt state + the current session handle
 * + the launch env. Reload vs fork is distinguished by the `run_id ↔ pi_session_id` mapping
 * (NOT `event.reason`, which is "startup" for a headless `pi --fork`): if the branch already
 * carries a `run_id` whose recorded `pi_session_id` differs from the current session, the id
 * was inherited across a fork → derive a child; if it matches (or is absent), it's a reload.
 * An env-inherited run id whose handoff was already CONSUMED by a different session is a
 * spawned child, not the launched session → `adopt` (derive a sibling id, inherit `mode`).
 */
/**
 * The registry stage id the launched run is acting on, read from its handoff blob, or null.
 * Only `claim` (cold) and `keep` (reload) sessions have a settled run whose handoff records a
 * `stage`; `fork`, `adopt`, and `none` carry no launched stage (an adopted env-child must never
 * impersonate the launched stage; LWW restores fork/none state instead). The stage gates whether
 * `session_start` reconciles `cache.plan-ref` into `active_plan_ref`.
 */
export function resolveRunStage(decision: ClaimDecision, cwd: string): string | null {
  const runId =
    decision.action === "claim"
      ? decision.runId
      : decision.action === "keep"
        ? decision.state.run_id
        : null;
  if (runId === undefined || runId === null) return null;
  const stage = readHandoff(cwd, runId)?.stage;
  return typeof stage === "string" && stage !== "" ? stage : null;
}

export function decideClaim(args: {
  state: WorkflowState;
  currentSessionId: string | null;
  envRunId: string | null;
  cwd: string;
}): ClaimDecision {
  const { state, currentSessionId, envRunId, cwd } = args;
  if (state.run_id !== undefined) {
    if (state.pi_session_id === undefined || state.pi_session_id === currentSessionId) {
      return { action: "keep", source: "session", state };
    }
    const childRunId = deriveForkRunId(state.run_id, cwd);
    return { action: "fork", source: "fork", childRunId, parentRunId: state.run_id, state };
  }
  if (envRunId !== null && envRunId !== "") {
    // Env-child detection (contracts §8.2): subagent children are spawned as separate `pi`
    // processes with the parent's env, so they arrive here carrying the parent's PERK_RUN_ID.
    // A handoff already consumed by a DIFFERENT (or unrecorded) session belongs to someone else:
    // adopt a derived `<run_id>.<n>` child identity instead of re-claiming — never re-consume the
    // handoff, never capture pointers, never impersonate the launched stage. The parent's `mode`
    // is inherited so read-only gating survives into exploration children. Everything else —
    // absent/corrupt/mismatched handoff (the loud unclaimed error), unconsumed (the normal cold
    // claim), or consumed by THIS session (idempotent re-claim after lost branch state) — stays
    // the claim arm.
    const handoff = readHandoff(cwd, envRunId);
    if (
      handoff !== null &&
      handoff.run_id === envRunId &&
      handoff.consumed === true &&
      handoff.pi_session_id !== currentSessionId
    ) {
      return {
        action: "adopt",
        source: "env-child",
        childRunId: deriveForkRunId(envRunId, cwd),
        parentRunId: envRunId,
        mode: handoff.mode,
      };
    }
    return { action: "claim", source: "env", runId: envRunId };
  }
  return { action: "none", source: "none", state };
}
