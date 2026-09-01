// The minimal feature-facing WorkflowSession seam (module-contracts.md's `session/` home):
// run identity + verified session-artifact operations, sized strictly to the callers that exist.
// No `stage`/`mode`/pointer-map snapshot — no feature caller consumes them through the seam yet
// (stage routing and the gate stay adapter-side); the seam grows only from proven callers.
//
// Two backings implement it: `branchWorkflowSession.ts` (the branch/file production backing,
// delegating to `substrate/sessionData.ts`'s classified cores) and `memoryWorkflowSession.ts`
// (the deterministic in-memory backing with failure knobs). Both are exercised by the shared
// interface suite in `workflowSession.test.ts`.
//
// Field classification — every workflow-state field the gist slice touches, by access path:
//
// | Field | Access in this slice | Authority | Retention | Fork behavior | Model visibility | Verification | Artifact relationship |
// | --- | --- | --- | --- | --- | --- | --- | --- |
// | `run_id` | seam (`WorkflowSession.runId`) | three-way mint (contracts §8.3): Python exterior cold mint → interior claim; TS interior `mintRunId()` on the warm identity-less arm; fork/adopt derive `<parent>.<n>` interior-side | current value | recompute (derive `<parent>.<n>`) | permitted (appears in tool results) | strict read-back at claim (outside this seam); read-only here | keys artifact dirs + pointers |
// | `session_artifacts` | seam (artifact ops) | session interior | current map (per-name latest) | reset (cross-run pointers refuse) | permitted (pointer details in results) | strict read-back (append→rebuild→compare) + digest-validated reads | pointer + digest authority |
// | `stage` | adapter-read (hook/dispatch routing; NOT seam-backed this slice) | exterior handoff, recorded at cold claim | current value | **inherit** (the fork entry omits `stage`; LWW retains the parent's — deliberate, contracts §8.40); only **adopt** never impersonates the launched stage | permitted (drives routing) | best effort | none |
// | `mode` | gate-owned (`ToolGating`; NOT seam-backed this slice) | session interior (gate transitions), seeded from handoff | current value | inherit (adopt carries parent mode) | permitted via injected mode context | best effort (`gating.exit` appends without read-back — honest tier) | none |

import type { SessionArtifactPointer } from "../substrate/workflowState.ts";

/** A human-readable problem description (the backing has already warned where its tier is loud). */
export type SessionProblem = string;

/**
 * The classified artifact read. `absent` is the silent, branchable tier (no pointer, or a
 * cross-run fork pointer — designed isolation); `invalid` is the loud tier (a pointer whose file
 * is missing or digest-mismatched — rewind/tamper).
 */
export type ReadArtifactResult =
  | { status: "found"; content: string }
  | { status: "absent" }
  | { status: "invalid"; problem: SessionProblem };

/**
 * The classified artifact write — the verified state op: `applied` proves the file AND the
 * strict-appended `session_artifacts` pointer both landed and read back; `unchanged` is the
 * byte-identical short-circuit (the recorded pointer already proves these bytes); `rejected`
 * refused before any effect; `unverified` means an effect may have landed but the read-back
 * proof failed — never consumable.
 */
export type WriteArtifactResult =
  | { status: "applied"; pointer: SessionArtifactPointer }
  | { status: "unchanged"; pointer: SessionArtifactPointer }
  | { status: "unverified"; problem: SessionProblem }
  | { status: "rejected"; problem: SessionProblem };

/** The feature-facing session: identity + verified artifact ops. A session exists only WITH identity. */
export interface WorkflowSession {
  readonly runId: string;
  readArtifact(name: string): ReadArtifactResult;
  writeArtifact(name: string, content: string): WriteArtifactResult;
}

/** An open attempt: `absent` when the surrounding context carries no run identity. */
export type OpenWorkflowSession =
  | { status: "opened"; session: WorkflowSession }
  | { status: "absent" };
