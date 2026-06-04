// The `perk:workflow-state` session tier (contracts.md §8.3) — rebuild, claim, fork-derive.
//
// Pure, fs-light logic kept separate from the `pi`/`ctx` effects (in index.ts) so it is
// unit-testable under `node --test`. The reconstruction discipline (scan getBranch on
// session_start AND session_tree, per-field LWW) and the verified-linkage claim (Q3) live here.

import { listRunIds, type PlanRef, readHandoff } from "./cache.ts";

export const WORKFLOW_STATE_TYPE = "perk:workflow-state";

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
}

/** The structural slice of a session entry that the rebuild cares about. */
export interface BranchEntry {
  type: string;
  customType?: string;
  data?: Record<string, unknown>;
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

/**
 * Equality by identity (provider + pr_id) — the plan-ref dedup key (turn-2b D4). Two refs to
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
  | { action: "none"; source: "none"; state: WorkflowState };

/**
 * Decide what `session_start` should do, from the rebuilt state + the current session handle
 * + the launch env. Reload vs fork is distinguished by the `run_id ↔ pi_session_id` mapping
 * (NOT `event.reason`, which is "startup" for a headless `pi --fork`): if the branch already
 * carries a `run_id` whose recorded `pi_session_id` differs from the current session, the id
 * was inherited across a fork → derive a child; if it matches (or is absent), it's a reload.
 */
/**
 * The registry stage id the launched run is acting on, read from its handoff blob, or null.
 * Only `claim` (cold) and `keep` (reload) sessions have a settled run whose handoff records a
 * `stage`; `fork` and `none` carry no launched stage (LWW restores their state instead). The
 * stage gates whether `session_start` reconciles `cache.plan-ref` into `active_plan_ref`.
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
    return { action: "claim", source: "env", runId: envRunId };
  }
  return { action: "none", source: "none", state };
}
