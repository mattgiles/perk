// The branch/file WorkflowSession backing: identity from the rebuilt `perk:workflow-state`
// (`activeSessionRunId`), artifact ops delegating to `substrate/sessionData.ts`'s classified
// cores — one artifact-discipline implementation, two consumers (this seam + the legacy
// null-collapsing wrappers) — and the workflow-state ops delegating to the strict-append seam
// (`appendWorkflowStateClassified`) with the exact scope/failure strings the plan-save surfaces
// always used (the append helper's loud `report()` warning path is unchanged and remains the
// loudness channel; its classification IS the seam's change vocabulary — `rejected` only on a
// proven refusal-before-effect). The reporting slice arrives through `SessionArtifactCtx`, so this module never
// imports `surfaces/`.

import {
  activeSessionRunId,
  readSessionArtifactClassified,
  type SessionArtifactCtx,
  writeSessionArtifactClassified,
} from "../substrate/sessionData.ts";
import {
  appendWorkflowStateClassified,
  branchOf,
  type EntrySink,
  nodeClaimsEqual,
  planRefsEqual,
  readNodeClaim,
  rebuildWorkflowState,
} from "../substrate/workflowState.ts";
import {
  type ReadArtifactResult,
  type ReviewPostRow,
  reviewPostsEqual,
  reviewPostsOf,
  type WorkflowChange,
  type WorkflowChangeResult,
  type WorkflowSession,
} from "./workflowSession.ts";

/** The rebuilt `review_posts` ledger, read fail-open (malformed rows drop; a throwing branch ⇒ []). */
function readReviewPosts(source: SessionArtifactCtx): ReviewPostRow[] {
  try {
    return reviewPostsOf(rebuildWorkflowState(branchOf(source)).review_posts);
  } catch {
    return [];
  }
}

/** The rebuilt `active_objective`, read fail-open (malformed/throwing branch ⇒ null). */
function readActiveObjective(source: SessionArtifactCtx): string | null {
  try {
    const value = rebuildWorkflowState(branchOf(source)).active_objective ?? null;
    return typeof value === "string" && value !== "" ? value : null;
  } catch {
    return null;
  }
}

/**
 * Open the branch-backed session for the current context — ALWAYS opens; `runId: null` is the
 * identity-less arm (the classified artifact cores refuse writes and read `absent` without a
 * run_id; the workflow-state ops are branch-backed and identity-independent). Artifact ops
 * re-derive validation state from the live branch per call — the classified cores own the
 * digest/pointer discipline.
 */
export function openBranchWorkflowSession(
  sink: EntrySink,
  source: SessionArtifactCtx,
): WorkflowSession {
  return {
    runId: activeSessionRunId(source),
    readArtifact(name: string): ReadArtifactResult {
      const result = readSessionArtifactClassified(source, name);
      switch (result.status) {
        case "found":
          return { status: "found", content: result.content };
        case "absent":
          return { status: "absent" };
        case "invalid":
          return { status: "invalid", problem: result.problem };
      }
    },
    writeArtifact(name: string, content: string) {
      const result = writeSessionArtifactClassified(sink, source, name, content);
      switch (result.status) {
        case "applied":
          return { status: "applied", pointer: result.pointer };
        case "unchanged":
          return { status: "unchanged", pointer: result.pointer };
        case "unverified":
          return { status: "unverified", problem: result.problem };
        case "rejected":
          return { status: "rejected", problem: result.problem };
      }
    },
    nodeClaim() {
      return readNodeClaim(source);
    },
    activeObjective() {
      return readActiveObjective(source);
    },
    reviewPosts() {
      return readReviewPosts(source);
    },
    apply(change: WorkflowChange): WorkflowChangeResult {
      switch (change.kind) {
        case "link-plan-ref": {
          const ref = change.ref;
          if (planRefsEqual(rebuildWorkflowState(branchOf(source)).active_plan_ref ?? null, ref)) {
            return { status: "unchanged" };
          }
          // The classified strict-append distinguishes a PROVEN refusal-before-effect (the
          // append threw and the rebuilt field never changed — `rejected`) from a read-back
          // miss (`unverified`: an append may have landed unproven); its report() path stays
          // the loudness channel. `ClassifiedAppend` IS the seam's change vocabulary.
          return appendWorkflowStateClassified(sink, source, {
            data: { active_plan_ref: ref },
            field: "active_plan_ref",
            expected: ref,
            scope: "plan-save",
            failure: `plan-ref read-back failed for ${ref.provider}:${ref.pr_id}`,
            equals: planRefsEqual,
          });
        }
        case "clear-node-claim": {
          const claim = change.claim;
          // Never clobber an unrelated claim: clear only when the LIVE claim matches BOTH
          // fields (same-node/different-objective stays untouched).
          if (!nodeClaimsEqual(readNodeClaim(source), claim)) return { status: "unchanged" };
          return appendWorkflowStateClassified(sink, source, {
            data: { objective_node_claim: null },
            field: "objective_node_claim",
            expected: null,
            scope: "plan-save",
            failure: `objective_node_claim clear read-back failed for node ${claim.node}`,
            equals: nodeClaimsEqual,
          });
        }
        case "record-node-claim": {
          const claim = change.claim;
          // The idempotent re-claim short-circuit: an equal live claim rebuilds identically, so
          // a re-append would carry no semantic payload (the claim has no timestamp).
          if (nodeClaimsEqual(readNodeClaim(source), claim)) return { status: "unchanged" };
          return appendWorkflowStateClassified(sink, source, {
            data: { objective_node_claim: claim },
            field: "objective_node_claim",
            expected: claim,
            scope: "objective-plan",
            failure: `objective_node_claim read-back failed for #${claim.objective} node ${claim.node}`,
            equals: nodeClaimsEqual,
          });
        }
        case "link-objective": {
          const objective = change.objective;
          if (readActiveObjective(source) === objective) return { status: "unchanged" };
          return appendWorkflowStateClassified(sink, source, {
            data: { active_objective: objective },
            field: "active_objective",
            expected: objective,
            scope: "objective-save",
            failure: `active_objective read-back failed for #${objective}`,
          });
        }
        case "record-pr-review": {
          // No pre-read/dedupe by design (the single-use wave state is feature-op policy
          // upstream): at runtime this yields applied/unverified/rejected only.
          return appendWorkflowStateClassified(sink, source, {
            data: { last_pr_review: change.record },
            field: "last_pr_review",
            expected: change.record,
            scope: "pr-review",
            failure: "last_pr_review read-back failed",
          });
        }
        case "record-review": {
          // No pre-read/dedupe by design (the resume guard is feature-op policy upstream): at
          // runtime this yields applied/unverified/rejected only.
          return appendWorkflowStateClassified(sink, source, {
            data: { last_review: change.record },
            field: "last_review",
            expected: change.record,
            scope: "review",
            failure: "last_review read-back failed",
          });
        }
        case "record-review-batch": {
          // No pre-read/dedupe by design (the corroborated-success ordering is feature-op
          // policy upstream): at runtime this yields applied/unverified/rejected only.
          return appendWorkflowStateClassified(sink, source, {
            data: { last_review_batch: change.record },
            field: "last_review_batch",
            expected: change.record,
            scope: "address",
            failure: "last_review_batch read-back failed",
          });
        }
        case "append-review-post": {
          // Read-rebuild-append: each write carries the whole ordered list (the resume reader
          // sees every confirmed post); order-sensitive read-back. The rebuild here is
          // FAIL-CLOSED — deliberately NOT the fail-open `reviewPosts()` read: appending over
          // an unrebuildable ledger would LWW-overwrite every earlier confirmed post with a
          // one-row list, and the resume guard would then permit duplicate GitHub reviews.
          // Refusing before any effect keeps the asymmetric trust rule intact (a row may be
          // MISSING spuriously, never PRESENT spuriously — and never erased by a write).
          let prior: ReviewPostRow[];
          try {
            prior = reviewPostsOf(rebuildWorkflowState(branchOf(source)).review_posts);
          } catch (error) {
            return {
              status: "rejected",
              problem:
                "review_posts ledger rebuild failed — refusing to append over an unknown " +
                `ledger: ${String(error)}`,
            };
          }
          const posts: ReviewPostRow[] = [...prior, change.row];
          return appendWorkflowStateClassified(sink, source, {
            data: { review_posts: posts },
            field: "review_posts",
            expected: posts,
            scope: "review",
            failure: "review_posts read-back failed",
            equals: reviewPostsEqual,
          });
        }
      }
    },
  };
}
