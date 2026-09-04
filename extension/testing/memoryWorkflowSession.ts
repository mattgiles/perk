// The deterministic in-memory WorkflowSession binding — a FIRST-CLASS dev-only deliverable
// living under `extension/testing/` (the memoryAdapter precedent: outside the production
// corpus, the guard scans, and the npm tarball), so feature tests need no filesystem or branch
// fixtures. It supplies ONLY ports and knobs: the one session engine
// (`session/workflowSession.ts`) runs over an in-memory branch array (wrapped by the production
// `branchSessionStateStore`, so classification/policy/error text are the engine's own — never a
// second implementation) and a Map-backed `ArtifactContentStore`. The failure knobs instrument
// the SUBSTRATE (a throwing/dropping sink, map surgery), never the policy; note the strict
// append's report() path still writes its stderr line headlessly — suites silence with the
// existing `quietly()` idiom.

import { branchSessionStateStore } from "../session/lifecycle.ts";
import {
  type ArtifactContentStore,
  openWorkflowSession,
  type PlanRef,
  type PrReviewRecord,
  type ReviewBatchRecord,
  type ReviewPostRow,
  type ReviewSubmissionRecord,
  type WorkflowSession,
} from "../session/workflowSession.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type BranchEntry,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "../substrate/workflowState.ts";

/** The in-memory session plus its deterministic failure knobs (test-facing, side-effect free). */
export interface MemoryWorkflowSession extends WorkflowSession {
  /** Refuse the NEXT content store (the `rejected` io-refusal arm — nothing lands). */
  failNextWrite(): void;
  /** Land the NEXT content store but drop its pointer append (the `unverified` orphan arm). */
  failNextPointerAppend(): void;
  /** Corrupt the stored bytes under an intact pointer (a read now classifies `invalid`). */
  corruptContent(name: string): void;
  /** Drop the stored bytes under an intact pointer (the `invalid` missing-file arm). */
  dropContent(name: string): void;
  /** Re-key the pointer to a foreign run (the silent `absent` fork-isolation arm). */
  disownPointer(name: string): void;
  /** Throw on the NEXT append — the classified strict-append proves `rejected` (nothing lands). */
  failNextApply(): void;
  /** Drop the NEXT append on the floor — the read-back proof misses (`unverified`, not landed). */
  failNextApplyVerification(): void;
  /** The live linked plan-ref (test observation of the `link-plan-ref` effect). */
  linkedPlanRef(): PlanRef | null;
  /** The live `last_review` record (test observation of the `record-review` effect). */
  lastReviewRecord(): ReviewSubmissionRecord | null;
  /** The live `last_pr_review` record (test observation of the `record-pr-review` effect). */
  lastPrReviewRecord(): PrReviewRecord | null;
  /** The live `last_review_batch` record (test observation of the `record-review-batch` effect). */
  lastReviewBatchRecord(): ReviewBatchRecord | null;
  /** Attempted workflow-state appends (substrate observation for no-append pins). */
  appendCount(): number;
}

/**
 * Open an in-memory session — ALWAYS opens (`runId: null` seeds no identity entry: artifact
 * writes reject, reads read `absent`, the state ops keep working). Everything the session
 * observes rebuilds from the private branch array, exactly like the production binding.
 */
export function openMemoryWorkflowSession(opts: {
  runId: string | null;
  nodeClaim?: { objective: string; node: string } | null;
  activePlanRef?: PlanRef | null;
  activeObjective?: string | null;
  reviewPosts?: ReviewPostRow[];
}): MemoryWorkflowSession {
  const branch: BranchEntry[] = [];
  const seed = (data: Record<string, unknown>): void => {
    branch.push({ type: "custom", customType: WORKFLOW_STATE_TYPE, data });
  };
  if (opts.runId !== null) seed({ run_id: opts.runId });
  if (opts.nodeClaim !== undefined && opts.nodeClaim !== null) {
    seed({ objective_node_claim: opts.nodeClaim });
  }
  if (opts.activePlanRef !== undefined && opts.activePlanRef !== null) {
    seed({ active_plan_ref: opts.activePlanRef });
  }
  if (opts.activeObjective !== undefined && opts.activeObjective !== null) {
    seed({ active_objective: opts.activeObjective });
  }
  if (opts.reviewPosts !== undefined) seed({ review_posts: opts.reviewPosts });

  let throwNextAppend = false;
  let dropNextAppend = false;
  let appends = 0;
  const sink = {
    appendEntry(customType: string, data?: unknown): void {
      appends += 1;
      if (throwNextAppend) {
        throwNextAppend = false;
        throw new Error("append refused (induced)");
      }
      if (dropNextAppend) {
        dropNextAppend = false;
        return; // dropped on the floor — the read-back proof misses
      }
      branch.push({ type: "custom", customType, data: data as Record<string, unknown> });
    },
  };
  // Headless ctx: cwd is never dereferenced (the content port below owns all "paths"); report()
  // still writes its stderr line on strict-append failures.
  const source: SessionArtifactCtx = {
    cwd: "",
    sessionManager: { getBranch: () => branch },
    hasUI: false,
    ui: { notify() {} },
  };

  let failWrite = false;
  // One store per opened session, keyed by name: the run id the engine passes selects nothing
  // here (fork isolation is engine policy over the pointer's run_id, proven before any load).
  const contents = new Map<string, string>();
  const artifacts: ArtifactContentStore = {
    store(_runId: string, name: string, content: string): boolean {
      if (failWrite) {
        failWrite = false;
        return false;
      }
      contents.set(name, content);
      return true;
    },
    load(_runId: string, name: string): string | null {
      return contents.get(name) ?? null;
    },
    displayPath(_runId: string, name: string): string {
      return name;
    },
  };

  const session = openWorkflowSession({
    state: branchSessionStateStore(sink, source),
    artifacts,
  });

  return {
    ...session,
    failNextWrite() {
      failWrite = true;
    },
    failNextPointerAppend() {
      dropNextAppend = true;
    },
    corruptContent(name: string) {
      const current = contents.get(name);
      if (current !== undefined) contents.set(name, `${current} [corrupted]`);
    },
    dropContent(name: string) {
      contents.delete(name);
    },
    disownPointer(name: string) {
      // Substrate surgery, not policy: re-append the whole map with this pointer re-keyed to a
      // foreign run (the engine's fork-isolation arm then reads it `absent`).
      const map = { ...(rebuildWorkflowState(branch).session_artifacts ?? {}) };
      const current = map[name];
      if (typeof current !== "object" || current === null) return;
      map[name] = { ...current, run_id: `${opts.runId}.foreign` };
      seed({ session_artifacts: map });
    },
    failNextApply() {
      throwNextAppend = true;
    },
    failNextApplyVerification() {
      dropNextAppend = true;
    },
    linkedPlanRef() {
      return rebuildWorkflowState(branch).active_plan_ref ?? null;
    },
    lastReviewRecord() {
      return (rebuildWorkflowState(branch).last_review ?? null) as ReviewSubmissionRecord | null;
    },
    lastPrReviewRecord() {
      return (rebuildWorkflowState(branch).last_pr_review ?? null) as PrReviewRecord | null;
    },
    lastReviewBatchRecord() {
      return (rebuildWorkflowState(branch).last_review_batch ?? null) as ReviewBatchRecord | null;
    },
    appendCount() {
      return appends;
    },
  };
}
