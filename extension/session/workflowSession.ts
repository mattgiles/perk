// The feature-facing WorkflowSession seam AND its one deep engine (module-contracts.md's
// `session/` home): run identity + verified session-artifact operations + the named
// workflow-state reads and the closed change union, sized strictly to the callers that exist.
// No `stage`/`mode`/pointer-map snapshot — no feature caller consumes them through the seam yet
// (stage routing and the gate stay adapter-side); the seam grows only from proven callers.
//
// ONE ENGINE, TWO NARROW PORTS. `openWorkflowSession(deps)` implements every WorkflowChange
// invariant, the full artifact discipline (name policy → identity refusal → unchanged
// short-circuit → store → read-back digest → pointer construction → merged-map strict append;
// the classified read tiers), and all error/problem text exactly once. Backings supply only
// mechanics: a `SessionStateStore` (session/lifecycle.ts — the same workflow-state store port
// the identity lifecycle uses) and an `ArtifactContentStore` (content I/O only, zero error
// prose). The production binding is `branchWorkflowSession.ts` (branch/file); the deterministic
// in-memory binding lives in `testing/memoryWorkflowSession.ts` (dev-only, outside the
// production corpus). Both are exercised by the shared interface suite in
// `workflowSession.test.ts`.
//
// Identity is OPTIONAL: `runId` is `string | null` and a session always opens — the plan-save
// surfaces prove the shape (workflow-state appends are branch-backed and identity-independent:
// an identity-less save still links `active_plan_ref`). The ARTIFACT ops classify no-identity as
// `rejected` (write) / `absent` (read); the state ops (`nodeClaim`, `apply`) work without
// identity. Identity is TRUST-NARROWED: a rebuilt `run_id` that is unsafe as a path component
// (`isSafeRunId`) degrades to no-identity before any path derivation — a hostile persisted id
// can never steer artifact reads outside the run root or reach a receipt.
//
// Results carry the session-owned `SessionArtifactReceipt` — validated or re-derived values
// ONLY (never the persisted pointer, whose rebuilt fields are unvalidated branch data). The
// full `SessionArtifactPointer` wire shape is still constructed here for the
// `session_artifacts` strict append (contracts §8.3's persistence format) — derived at the
// storage boundary, internal to the engine, never exposed through results.
//
// `apply(change)` is a CLOSED union admitted from proven callers (never a feature dispatcher);
// the first two variants come from the plan-save surfaces, the second two from the objective
// flows (`transitionObjectiveNode`'s planning arm records the claim; `saveObjective`'s
// post-save linkage sets `active_objective`). Deliberate deviation from the illustrative
// contracts sketch: no snapshot payloads on the applied/unchanged arms — nothing consumes them
// (narrow until proven).
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
// | `last_review_batch` | seam (`apply({kind:"record-review-batch"})`) | session interior — the address finalizer, only after publication AND corroborated full thread resolution | current value (LWW) | inherit (via LWW) | permitted (nothing renders the record itself today — the finalize details carry the same facts independently) | strict read-back on the seam path (seam-reported warning, never a tool failure) | none |
// | `last_pr_review` | seam (`apply({kind:"record-pr-review"})`) | session interior — the automated post surface (`post_pr_review`) | current value (LWW) | inherit (via LWW) | permitted (tool results render it) | strict read-back on the seam path (seam-reported warning, never a tool failure) | none |
// | `last_review` | seam (`apply({kind:"record-review"})`) | session interior — the curated-submission post surface (`submit_pr_review`) | current value (LWW) | inherit (via LWW) | permitted (tool results render it) | strict read-back on the seam path (seam-reported warning, never a tool failure) | none |
// | `review_posts` | seam (`reviewPosts()` read + `apply({kind:"append-review-post"})`) | session interior — the curated-submission post surface (one row per REAL success; the stack flow's resume authority) | append-only list (read-rebuild-append — each write carries the whole ordered list) | inherit (via LWW) | permitted (the resume guard's refusal names the prior row) | strict read-back on the seam path (order-sensitive `reviewPostsEqual`; seam-reported warning, never a tool failure) | none |
// | `stage` | adapter-read (hook/dispatch routing; NOT seam-backed this slice) | exterior handoff, recorded at cold claim | current value | **inherit** (the fork entry omits `stage`; LWW retains the parent's — deliberate, contracts §8.40); only **adopt** never impersonates the launched stage | permitted (drives routing) | best effort | none |
// | `mode` | gate-owned (`ToolGating`; NOT seam-backed this slice) | session interior (gate transitions), seeded from handoff | current value | inherit (adopt carries parent mode) | permitted via injected mode context | best effort (`gating.exit` appends without read-back — honest tier) | none |

import { isSafeRunId, type PlanRef } from "../substrate/cache.ts";
import { digestSessionData } from "../substrate/sessionData.ts";
import {
  nodeClaimsEqual,
  planRefsEqual,
  type SessionArtifactPointer,
} from "../substrate/workflowState.ts";
import type { SessionStateStore } from "./lifecycle.ts";

/** Session-owned vocabulary: features import the plan-ref shape through the session seam. */
export type { PlanRef };

/** A human-readable problem description (the backing has already warned where its tier is loud). */
export type SessionProblem = string;

/**
 * Session-owned artifact receipt: validated or re-derived values ONLY. `runId` is the
 * safe-narrowed active run id (matches the persisted pointer's `run_id` by construction);
 * `path` is re-derived from the content store (fs: repo-relative; memory: the name) — NEVER a
 * persisted pointer field; `digest` is proven — computed from the bytes read back (applied) or
 * from the stored bytes during the unchanged probe.
 */
export interface SessionArtifactReceipt {
  runId: string;
  path: string;
  digest: string;
}

/**
 * The artifact content port: content I/O only, mechanical results, zero error prose —
 * classification, policy, and all problem text are engine-owned.
 */
export interface ArtifactContentStore {
  /** Persist bytes; false = refusal (the port has already warned where its tier is loud). */
  store(name: string, content: string): boolean;
  /** Current bytes; null = missing/unreadable. */
  load(name: string): string | null;
  /** The receipt/warning display path, re-derived — NEVER a persisted pointer field. */
  displayPath(name: string): string;
}

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
  | { status: "applied"; receipt: SessionArtifactReceipt }
  | { status: "unchanged"; receipt: SessionArtifactReceipt }
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

/** The four known review-classification count keys the finalizer records (§8.3). */
export interface ReviewBatchCounts {
  actionable?: number;
  informational?: number;
  praise?: number;
  question?: number;
}

/**
 * The last finalized review batch (`last_review_batch`, contracts §8.3): exactly the record the
 * address finalizer constructs after publication and corroborated full thread resolution.
 */
export interface ReviewBatchRecord {
  pr: number | null;
  counts: ReviewBatchCounts | null;
  resolved_thread_ids: string[];
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
   * the order-sensitive `reviewPostsEqual` read-back. The pre-read is FAIL-CLOSED and
   * STRICT-DECODED (an unrebuildable or malformed persisted ledger refuses the append — see the
   * engine's arm); no dedupe (same invariant as `record-review`:
   * `applied`/`unverified`/`rejected` only at runtime).
   */
  | { kind: "append-review-post"; row: ReviewPostRow }
  /**
   * Record the last finalized review batch: ONE `last_review_batch` append (LWW), strict
   * read-back. No pre-read, no dedupe — the corroborated-success-first ordering is feature-op
   * policy upstream (`applied`/`unverified`/`rejected` only at runtime).
   */
  | { kind: "record-review-batch"; record: ReviewBatchRecord };

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

// ------------------------------------------------------------------------------- the engine

/**
 * Validate a session-artifact name at the seam: non-empty, no path separators (the artifact
 * name keys the pointer map and joins under the run's data dir — a separator would escape it).
 * Returns the problem string, or `null` when the name is safe. Name policy is refusal policy —
 * it lives with the engine, not the backings.
 */
export function sessionArtifactNameProblem(name: string): string | null {
  if (name.trim() === "") return "session artifact name is empty";
  if (name.includes("/") || name.includes("\\")) {
    return `session artifact name ${JSON.stringify(name)} carries a path separator`;
  }
  return null;
}

/**
 * The ONE persisted-pointer decode: accept a rebuilt `session_artifacts` value only when it is
 * SHAPE-SOUND, and narrow the return to exactly the two fields the engine dereferences —
 * branch data is unvalidated (`rebuildWorkflowState` trusts entry data), so a malformed session
 * entry can put `null` — or anything else — where a pointer belongs, and the OTHER persisted
 * fields (`path`, `name`, `at`) stay untrusted `unknown` even on a sound value (`path` is always
 * re-derived, `name` is the map key, `at` has no consumer). Anything unsound reads as "no
 * pointer" and never throws. Tests asserting persisted-pointer facts narrow through this —
 * never a cast.
 */
export function soundPointer(candidate: unknown): { run_id: string; digest: string } | null {
  if (typeof candidate !== "object" || candidate === null) return null;
  const pointer = candidate as Record<string, unknown>;
  if (typeof pointer.run_id !== "string" || typeof pointer.digest !== "string") return null;
  return { run_id: pointer.run_id, digest: pointer.digest };
}

/** Per-name pointer identity: same run_id + same digest (each side narrowed via the decode). */
function artifactMapsEqual(
  rebuilt: Record<string, unknown> | null | undefined,
  expected: Record<string, unknown> | null | undefined,
): boolean {
  const a = rebuilt ?? {};
  const b = expected ?? {};
  const names = Object.keys(b);
  if (Object.keys(a).length !== names.length) return false;
  return names.every((name) => {
    const ra = soundPointer(a[name]);
    const rb = soundPointer(b[name]);
    // Unsound on both sides (junk siblings carried forward by the merged-map spread) compares
    // equal — the append is verified on the pointers it can vouch for, never on junk shape.
    if (ra === null || rb === null) return ra === rb;
    return ra.run_id === rb.run_id && ra.digest === rb.digest;
  });
}

/**
 * Strict `review_posts` decode for the append pre-read (CONTRAST with the tolerant
 * `reviewPostsOf`): a present-but-malformed persisted ledger — non-array, or any row that is
 * not `{pr: integer, event: string, at: string}` — refuses with a problem naming the malformed
 * variant instead of silently narrowing (a tolerant pre-read would let the whole-list LWW
 * re-append ERASE malformed-but-possibly-real rows, violating the ledger invariant that a
 * confirmed post is never erased by a write). Extra row fields are narrowed out.
 */
function strictReviewPosts(raw: unknown): { rows: ReviewPostRow[] } | { malformed: string } {
  if (!Array.isArray(raw)) return { malformed: `not a list (${JSON.stringify(raw)})` };
  const rows: ReviewPostRow[] = [];
  for (const item of raw) {
    const row = soundReviewPostRow(item);
    if (row === null) return { malformed: `malformed row ${JSON.stringify(item)}` };
    rows.push(row);
  }
  return { rows };
}

function soundReviewPostRow(item: unknown): ReviewPostRow | null {
  if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
  const row = item as Record<string, unknown>;
  if (typeof row.pr !== "number" || !Number.isInteger(row.pr)) return null;
  if (typeof row.event !== "string" || typeof row.at !== "string") return null;
  return { pr: row.pr, event: row.event, at: row.at };
}

/** The two ports the engine runs over — the backings supply ONLY these. */
export interface WorkflowSessionDeps {
  state: SessionStateStore;
  artifacts: ArtifactContentStore;
}

/**
 * The safe-narrowed active run id: the rebuilt `run_id`, non-empty AND safe as a path component
 * (`isSafeRunId` — an unsafe persisted id degrades to no-identity BEFORE any path derivation);
 * a throwing rebuild degrades to null (no resolvable identity, never a stamp).
 */
function activeRunId(state: SessionStateStore): string | null {
  try {
    const runId = state.rebuild().run_id;
    if (typeof runId === "string" && isSafeRunId(runId)) return runId;
  } catch {
    // a throwing rebuild means no resolvable identity — degrade to null
  }
  return null;
}

/** The rebuilt `objective_node_claim`, read fail-open (malformed/throwing rebuild → null). */
function readClaim(state: SessionStateStore): { objective: string; node: string } | null {
  try {
    const claim = state.rebuild().objective_node_claim ?? null;
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

/** The rebuilt `active_objective`, read fail-open (malformed/throwing rebuild ⇒ null). */
function readActiveObjective(state: SessionStateStore): string | null {
  try {
    const value = state.rebuild().active_objective ?? null;
    return typeof value === "string" && value !== "" ? value : null;
  } catch {
    return null;
  }
}

/** The rebuilt `review_posts` ledger, read fail-open (malformed rows drop; a throwing rebuild ⇒ []). */
function readReviewPosts(state: SessionStateStore): ReviewPostRow[] {
  try {
    return reviewPostsOf(state.rebuild().review_posts);
  } catch {
    return [];
  }
}

/**
 * Open a session over the two ports — the ONE deep implementation of the seam. ALWAYS opens;
 * `runId: null` is the identity-less arm (artifact writes reject, reads read absent; the state
 * ops are store-backed and identity-independent). `runId` is captured at open and re-derived
 * per artifact call (a fork entry appended mid-session re-keys the artifact ops — today's
 * behavior). Loudness: the strict-append port reports its own read-back failures (the
 * classified-append seam's report() channel inside the production binding); the engine warns on
 * stderr for the loud read tier (rewind/tamper) and the unreadable-after-write arm.
 */
export function openWorkflowSession(deps: WorkflowSessionDeps): WorkflowSession {
  const { state, artifacts } = deps;

  return {
    runId: activeRunId(state),
    readArtifact(name: string): ReadArtifactResult {
      const runId = activeRunId(state);
      if (runId === null) return { status: "absent" }; // no identity — silent, branchable
      let pointer: { run_id: string; digest: string } | null;
      try {
        pointer = soundPointer(state.rebuild().session_artifacts?.[name]);
      } catch {
        return { status: "absent" };
      }
      if (pointer === null) return { status: "absent" }; // no pointer — or a malformed one (no provenance)
      if (pointer.run_id !== runId) return { status: "absent" }; // fork isolation — by design, silent

      const content = artifacts.load(name);
      if (content === null) {
        console.error(
          `perk: warning: session artifact ${name} has a pointer but no file at ` +
            artifacts.displayPath(name),
        );
        return { status: "invalid", problem: `session artifact ${name} has a pointer but no file` };
      }
      if (digestSessionData(content) !== pointer.digest) {
        console.error(
          `perk: warning: session artifact ${artifacts.displayPath(name)} digest mismatch ` +
            "(rewound or modified) — refusing",
        );
        return {
          status: "invalid",
          problem: `session artifact ${name} digest mismatch (rewound or modified)`,
        };
      }
      return { status: "found", content };
    },
    writeArtifact(name: string, content: string): WriteArtifactResult {
      const nameProblem = sessionArtifactNameProblem(name);
      if (nameProblem !== null) return { status: "rejected", problem: nameProblem };

      const runId = activeRunId(state);
      if (runId === null) {
        return {
          status: "rejected",
          problem: "session has no run_id — session artifacts need identity",
        };
      }

      // The unchanged short-circuit: a byte-identical rewrite is a no-op (no store, no fresh
      // pointer entry) — the recorded pointer already proves exactly these bytes. QUIET by
      // design: a stale/broken/malformed pointer simply fails the probe and the write proceeds
      // (the probe must never emit the read tier's rewind warnings). The receipt is fully
      // re-derived — junk persisted fields are unobservable.
      let current: { run_id: string; digest: string } | null;
      try {
        current = soundPointer(state.rebuild().session_artifacts?.[name]);
      } catch {
        current = null;
      }
      if (current !== null && current.run_id === runId) {
        const stored = artifacts.load(name);
        if (
          stored !== null &&
          digestSessionData(stored) === current.digest &&
          current.digest === digestSessionData(content)
        ) {
          return {
            status: "unchanged",
            receipt: {
              runId,
              path: artifacts.displayPath(name),
              digest: digestSessionData(stored),
            },
          };
        }
      }

      if (!artifacts.store(name, content)) {
        // the port already warned; never point at an unwritten file
        return {
          status: "rejected",
          problem: `could not write session data ${name} (see warnings)`,
        };
      }

      // Digest the bytes as read back from the store — catches encoding/disk surprises.
      const readBack = artifacts.load(name);
      if (readBack === null) {
        const problem = `session artifact ${artifacts.displayPath(name)} unreadable after write`;
        console.error(`perk: warning: ${problem}`);
        return { status: "unverified", problem };
      }

      // The persisted wire shape (contracts §8.3) — constructed at the storage boundary,
      // internal to the engine, never exposed through results.
      const pointer: SessionArtifactPointer = {
        run_id: runId,
        name,
        path: artifacts.displayPath(name),
        digest: digestSessionData(readBack),
        at: new Date().toISOString(),
      };

      // Per-field LWW: each append must carry the WHOLE merged map so sibling artifacts survive
      // (junk siblings carry forward unchanged — existing LWW behavior).
      const merged: Record<string, unknown> = {
        ...(state.rebuild().session_artifacts ?? {}),
        [name]: pointer,
      };
      const appended = state.appendVerified({
        data: { session_artifacts: merged },
        field: "session_artifacts",
        expected: merged,
        scope: "session-data",
        failure: `session_artifacts pointer read-back failed for ${name}`,
        equals: artifactMapsEqual,
      });
      if (appended.status !== "applied") {
        // already reported through the strict-append port
        return {
          status: "unverified",
          problem: `session_artifacts pointer read-back failed for ${name}`,
        };
      }
      return {
        status: "applied",
        receipt: { runId, path: pointer.path, digest: pointer.digest },
      };
    },
    nodeClaim() {
      return readClaim(state);
    },
    activeObjective() {
      return readActiveObjective(state);
    },
    reviewPosts() {
      return readReviewPosts(state);
    },
    apply(change: WorkflowChange): WorkflowChangeResult {
      switch (change.kind) {
        case "link-plan-ref": {
          const ref = change.ref;
          // The pre-read dedupe is deliberately NOT try/caught — a throwing rebuild propagates.
          if (planRefsEqual(state.rebuild().active_plan_ref ?? null, ref)) {
            return { status: "unchanged" };
          }
          // The classified strict-append distinguishes a PROVEN refusal-before-effect (the
          // append threw and the rebuilt field never changed — `rejected`) from a read-back
          // miss (`unverified`: an append may have landed unproven); its report() path stays
          // the loudness channel. `ClassifiedAppend` IS the seam's change vocabulary.
          return state.appendVerified({
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
          if (!nodeClaimsEqual(readClaim(state), claim)) return { status: "unchanged" };
          return state.appendVerified({
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
          if (nodeClaimsEqual(readClaim(state), claim)) return { status: "unchanged" };
          return state.appendVerified({
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
          if (readActiveObjective(state) === objective) return { status: "unchanged" };
          return state.appendVerified({
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
          return state.appendVerified({
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
          return state.appendVerified({
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
          return state.appendVerified({
            data: { last_review_batch: change.record },
            field: "last_review_batch",
            expected: change.record,
            scope: "address",
            failure: "last_review_batch read-back failed",
          });
        }
        case "append-review-post": {
          // Read-rebuild-append: each write carries the whole ordered list (the resume reader
          // sees every confirmed post); order-sensitive read-back. The pre-read is FAIL-CLOSED
          // and STRICT — deliberately NOT the fail-open `reviewPosts()` read: appending over an
          // unrebuildable OR malformed ledger would LWW-overwrite possibly-real earlier rows,
          // and the resume guard would then permit duplicate GitHub reviews. Refusing before
          // any effect keeps the asymmetric trust rule intact (a row may be MISSING spuriously,
          // never PRESENT spuriously — and never erased by a write). An ABSENT field is the
          // normal first append (the empty prior ledger).
          let prior: ReviewPostRow[];
          try {
            const raw = state.rebuild().review_posts;
            if (raw === undefined || raw === null) {
              prior = [];
            } else {
              const decoded = strictReviewPosts(raw);
              if ("malformed" in decoded) {
                return {
                  status: "rejected",
                  problem:
                    "review_posts ledger is malformed — refusing to append over an unknown " +
                    `ledger: ${decoded.malformed}`,
                };
              }
              prior = decoded.rows;
            }
          } catch (error) {
            return {
              status: "rejected",
              problem:
                "review_posts ledger rebuild failed — refusing to append over an unknown " +
                `ledger: ${String(error)}`,
            };
          }
          const posts: ReviewPostRow[] = [...prior, change.row];
          return state.appendVerified({
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
