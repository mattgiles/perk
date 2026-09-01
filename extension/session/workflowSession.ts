// The minimal feature-facing WorkflowSession seam (module-contracts.md's `session/` home):
// run identity + verified session-artifact operations + the named workflow-state reads and the
// closed change union, sized strictly to the callers that exist. No `stage`/`mode`/pointer-map
// snapshot — no feature caller consumes them through the seam yet (stage routing and the gate
// stay adapter-side); the seam grows only from proven callers.
//
// Identity is OPTIONAL: `runId` is `string | null` and a session always opens — the plan-save
// surfaces prove the shape (workflow-state appends are branch-backed and identity-independent:
// an identity-less save still links `active_plan_ref`). The ARTIFACT ops classify no-identity as
// `rejected` (write) / `absent` (read); the state ops (`nodeClaim`, `apply`) work without
// identity.
//
// `apply(change)` is a CLOSED union admitted from proven callers (never a feature dispatcher);
// the first two variants come from the plan-save surfaces, the second two from the objective
// flows (`transitionObjectiveNode`'s planning arm records the claim; `saveObjective`'s
// post-save linkage sets `active_objective`). Deliberate deviation from the illustrative
// contracts sketch: no snapshot payloads on the applied/unchanged arms — nothing consumes them
// (narrow until proven).
//
// Two backings implement it: `branchWorkflowSession.ts` (the branch/file production backing,
// delegating to `substrate/sessionData.ts`'s classified cores and the strict-append seam) and
// `memoryWorkflowSession.ts` (the deterministic in-memory backing with failure knobs). Both are
// exercised by the shared interface suite in `workflowSession.test.ts`.
//
// Field classification — every workflow-state field the migrated slices touch, by access path:
//
// | Field | Access in this slice | Authority | Retention | Fork behavior | Model visibility | Verification | Artifact relationship |
// | --- | --- | --- | --- | --- | --- | --- | --- |
// | `run_id` | seam (`WorkflowSession.runId`) | three-way mint (contracts §8.3): Python exterior cold mint → interior claim; TS interior `mintRunId()` on the warm identity-less arm; fork/adopt derive `<parent>.<n>` interior-side | current value | recompute (derive `<parent>.<n>`) | permitted (appears in tool results) | strict read-back at claim (outside this seam); read-only here | keys artifact dirs + pointers |
// | `session_artifacts` | seam (artifact ops) | session interior | current map (per-name latest) | reset (cross-run pointers refuse) | permitted (pointer details in results) | strict read-back (append→rebuild→compare) + digest-validated reads | pointer + digest authority |
// | `active_plan_ref` | seam (`apply({kind:"link-plan-ref"})`) | the save surfaces — warm `savePlan` appends after a verified cold-door save; the Python cold door + the stage-gated session_start reconciliation (index.ts, substrate-direct) are the other writers | current value (LWW) | inherit (fork entries never touch it; the branch LWW carries the parent's) | permitted (save results render the ref; the footer/status probe reads it) | strict read-back (append → rebuild → `planRefsEqual`) | none (mirrors the exterior plan issue / `cache.plan-ref`; not a session artifact) |
// | `objective_node_claim` | seam (`nodeClaim()` read + `apply({kind:"record-node-claim"})` + `apply({kind:"clear-node-claim"})`) | the interior RECORDS it on a verified `planning` transition (`transitionObjectiveNode`) and CLEARS it on a verified non-planning transition / node-linked save — both through the seam; the cold-claim write lives in `session/lifecycle.ts`'s claim arm (the objective-plan handoff carrier) | current value until cleared (a null append clears) | inherit (fork entries omit it — a fork continues the same node's planning session); adopt never impersonates it | permitted (claim recovery + the implement-here refusal surface it) | strict read-back on record + clear (append → rebuild → `nodeClaimsEqual`) | none |
// | `active_objective` | seam (`activeObjective()` read + `apply({kind:"link-objective"})`) | the save surfaces (`saveObjective`'s post-save linkage) + the `/objective` command's set/clear (pi/v1/objective.ts) | current value (LWW; explicit null clears) | inherit (fork entries never touch it; the branch LWW carries the parent's) | permitted (save results render the id; the budget status reads it) | strict read-back on the seam path (append → rebuild → string equality); the `/objective` command path stays a raw LWW append — stated honestly | none |
// | `last_pr_review` | seam (`apply({kind:"record-pr-review"})`) | session interior — the automated post surface (`post_pr_review`) | current value (LWW) | inherit (via LWW) | permitted (tool results render it) | strict read-back on the seam path (seam-reported warning, never a tool failure) | none |
// | `last_review` | seam (`apply({kind:"record-review"})`) | session interior — the curated-submission post surface (`submit_pr_review`) | current value (LWW) | inherit (via LWW) | permitted (tool results render it) | strict read-back on the seam path (seam-reported warning, never a tool failure) | none |
// | `review_posts` | seam (`reviewPosts()` read + `apply({kind:"append-review-post"})`) | session interior — the curated-submission post surface (one row per REAL success; the stack flow's resume authority) | append-only list (read-rebuild-append — each write carries the whole ordered list) | inherit (via LWW) | permitted (the resume guard's refusal names the prior row) | strict read-back on the seam path (order-sensitive `reviewPostsEqual`; seam-reported warning, never a tool failure) | none |
// | `stage` | adapter-read (hook/dispatch routing; NOT seam-backed this slice) | exterior handoff, recorded at cold claim | current value | **inherit** (the fork entry omits `stage`; LWW retains the parent's — deliberate, contracts §8.40); only **adopt** never impersonates the launched stage | permitted (drives routing) | best effort | none |
// | `mode` | gate-owned (`ToolGating`; NOT seam-backed this slice) | session interior (gate transitions), seeded from handoff | current value | inherit (adopt carries parent mode) | permitted via injected mode context | best effort (`gating.exit` appends without read-back — honest tier) | none |

import type { PlanRef } from "../substrate/cache.ts";
import type { SessionArtifactPointer } from "../substrate/workflowState.ts";

/** A human-readable problem description (the backing has already warned where its tier is loud). */
export type SessionProblem = string;

/**
 * The classified artifact read. `absent` is the silent, branchable tier (no identity, no
 * pointer, or a cross-run fork pointer — designed isolation); `invalid` is the loud tier (a
 * pointer whose file is missing or digest-mismatched — rewind/tamper).
 */
export type ReadArtifactResult =
  | { status: "found"; content: string }
  | { status: "absent" }
  | { status: "invalid"; problem: SessionProblem };

/**
 * The classified artifact write — the verified state op: `applied` proves the file AND the
 * strict-appended `session_artifacts` pointer both landed and read back; `unchanged` is the
 * byte-identical short-circuit (the recorded pointer already proves these bytes); `rejected`
 * refused before any effect (including the no-identity refusal — artifacts need a run_id);
 * `unverified` means an effect may have landed but the read-back proof failed — never
 * consumable.
 */
export type WriteArtifactResult =
  | { status: "applied"; pointer: SessionArtifactPointer }
  | { status: "unchanged"; pointer: SessionArtifactPointer }
  | { status: "unverified"; problem: SessionProblem }
  | { status: "rejected"; problem: SessionProblem };

/**
 * The last automated `/pr-review` outcome (`last_pr_review`, contracts §8.3): exactly the
 * record the `post_pr_review` post surface constructs on a real success. After a recorded wave,
 * `angles` is the authoritative attempted manifest and `covered_angles` its schema-valid
 * subset; standalone posts use the caller's angles for both.
 */
export interface PrReviewRecord {
  pr: number;
  verdict: "clean" | "actionable";
  angles: readonly string[];
  covered_angles: readonly string[];
  comment_count: number | null;
  mode: string | null;
  at: string;
}

/**
 * The last curated review-door outcome (`last_review`, contracts §8.3): exactly the record the
 * `submit_pr_review` post surface constructs on a real success. `event` stays `string` in the
 * record — the decode boundary already constrains it; the stored field is render-only.
 */
export interface ReviewSubmissionRecord {
  pr: number;
  event: string;
  comment_count: number | null;
  mode: string | null;
  at: string;
}

/** One `review_posts` ledger row: a REAL curated submission that reached GitHub (§8.3). */
export interface ReviewPostRow {
  pr: number;
  event: string;
  at: string;
}

/**
 * Tolerant re-narrow of a rebuilt `review_posts` list (best-effort tier: a malformed row is
 * dropped, never a refusal — the ledger only ever grows from the seam's own writes).
 */
export function reviewPostsOf(raw: unknown): ReviewPostRow[] {
  if (!Array.isArray(raw)) return [];
  const rows: ReviewPostRow[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    if (typeof row.pr !== "number" || !Number.isInteger(row.pr)) continue;
    if (typeof row.event !== "string" || typeof row.at !== "string") continue;
    rows.push({ pr: row.pr, event: row.event, at: row.at });
  }
  return rows;
}

/** Ledger equality for the read-back verification (order-sensitive — posting order matters). */
export function reviewPostsEqual(rebuilt: unknown, expected: unknown): boolean {
  const a = reviewPostsOf(rebuilt);
  const b = reviewPostsOf(expected);
  if (a.length !== b.length) return false;
  return a.every(
    (row, i) => row.pr === b[i]?.pr && row.event === b[i]?.event && row.at === b[i]?.at,
  );
}

/**
 * The closed workflow-state change union — admitted variant-by-variant from proven callers
 * (this slice: the plan-save surfaces). Reads stay NAMED (`nodeClaim()`); only changes ride the
 * union.
 */
export type WorkflowChange =
  /** Link the live session to a saved plan: append `active_plan_ref` iff it differs. */
  | { kind: "link-plan-ref"; ref: PlanRef }
  /**
   * Clear `objective_node_claim` iff the live claim matches BOTH fields (never clobbers an
   * unrelated claim — a save linked to objective B node 1.1 must not clear objective A's 1.1).
   */
  | { kind: "clear-node-claim"; claim: { objective: string; node: string } }
  /**
   * Record `objective_node_claim` iff the live claim differs (`nodeClaimsEqual`) — an
   * idempotent re-claim short-circuits `unchanged` (the re-append "refresh" carries no
   * semantic payload: the claim has no timestamp and rebuilds identically).
   */
  | { kind: "record-node-claim"; claim: { objective: string; node: string } }
  /** Link the live session to a saved objective: append `active_objective` iff it differs. */
  | { kind: "link-objective"; objective: string }
  /**
   * Record the last automated `/pr-review` outcome: ONE `last_pr_review` append (LWW), strict
   * read-back. No pre-read, no dedupe (same runtime invariant as `record-review`:
   * `applied`/`unverified`/`rejected` only).
   */
  | { kind: "record-pr-review"; record: PrReviewRecord }
  /**
   * Record the last curated review-door outcome: ONE `last_review` append (LWW), strict
   * read-back. No pre-read, no dedupe — the `already_posted` resume guard is feature-op policy
   * upstream, so at runtime this yields `applied`/`unverified`/`rejected` only (a runtime
   * invariant, not a type claim).
   */
  | { kind: "record-review"; record: ReviewSubmissionRecord }
  /**
   * Append one `review_posts` ledger row: read-rebuild-append of the whole ordered list, with
   * the order-sensitive `reviewPostsEqual` read-back. No dedupe (same invariant as
   * `record-review`: `applied`/`unverified`/`rejected` only at runtime).
   */
  | { kind: "append-review-post"; row: ReviewPostRow };

/**
 * The classified change outcome: `applied` proves the append landed and read back; `unchanged`
 * is the idempotent short-circuit (link: the rebuilt ref already equals; clear: no matching
 * claim); `unverified` means the append may have landed but the read-back proof failed (the
 * branch backing has already warned loudly); `rejected` refused before any effect.
 */
export type WorkflowChangeResult =
  | { status: "applied" }
  | { status: "unchanged" }
  | { status: "unverified"; problem: SessionProblem }
  | { status: "rejected"; problem: SessionProblem };

/**
 * The feature-facing session: optional identity + verified artifact ops + the named
 * workflow-state reads and the closed change union. A session ALWAYS opens; `runId: null` is
 * the identity-less arm (artifact ops classify it; state ops still work).
 */
export interface WorkflowSession {
  readonly runId: string | null;
  readArtifact(name: string): ReadArtifactResult;
  writeArtifact(name: string, content: string): WriteArtifactResult;
  /** Snapshot read of the rebuilt `objective_node_claim` (malformed ⇒ null). */
  nodeClaim(): { objective: string; node: string } | null;
  /** Snapshot read of the rebuilt `active_objective` (malformed/throwing ⇒ null). */
  activeObjective(): string | null;
  /** Fail-open read of the rebuilt `review_posts` ledger (malformed rows dropped, never a refusal). */
  reviewPosts(): ReviewPostRow[];
  apply(change: WorkflowChange): WorkflowChangeResult;
}
