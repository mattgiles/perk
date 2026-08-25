// The deterministic in-memory WorkflowSession backing (the waves-memory-adapter precedent: a
// production file so feature tests need no filesystem or branch fixtures). It mirrors the
// classified cores' arms exactly — same name validation, same unchanged short-circuit, same
// rejected/unverified split, same no-identity classification (`runId: null` ⇒ artifact writes
// reject, reads read `absent`; the state ops still work) — with deterministic failure knobs so
// the shared interface suite reaches every arm without permission tricks or fake sinks.

import type { PlanRef } from "../substrate/cache.ts";
import { digestSessionData, sessionArtifactNameProblem } from "../substrate/sessionData.ts";
import {
  nodeClaimsEqual,
  planRefsEqual,
  type SessionArtifactPointer,
} from "../substrate/workflowState.ts";
import type {
  ReadArtifactResult,
  WorkflowChange,
  WorkflowChangeResult,
  WorkflowSession,
  WriteArtifactResult,
} from "./workflowSession.ts";

/** The in-memory session plus its deterministic failure knobs (test-facing, side-effect free). */
export interface MemoryWorkflowSession extends WorkflowSession {
  /** Refuse the NEXT content store (the `rejected` io-refusal arm — nothing lands). */
  failNextWrite(): void;
  /** Land the NEXT content store but drop its pointer (the `unverified` orphan arm). */
  failNextPointerAppend(): void;
  /** Corrupt the stored bytes under an intact pointer (a read now classifies `invalid`). */
  corruptContent(name: string): void;
  /** Drop the stored bytes under an intact pointer (the `invalid` missing-file arm). */
  dropContent(name: string): void;
  /** Re-key the pointer to a foreign run (the silent `absent` fork-isolation arm). */
  disownPointer(name: string): void;
  /** Refuse the NEXT `apply` before any effect (the `rejected` arm — nothing lands). */
  failNextApply(): void;
  /** Land the NEXT `apply` but fail its read-back proof (the `unverified` arm). */
  failNextApplyVerification(): void;
  /** Seed/replace the live node claim (the lifecycle write stays outside the seam). */
  setNodeClaim(claim: { objective: string; node: string } | null): void;
  /** Seed/replace the live active objective (the `/objective` raw-append path's twin). */
  setActiveObjective(objective: string | null): void;
  /** The live linked plan-ref (test observation of the `link-plan-ref` effect). */
  linkedPlanRef(): PlanRef | null;
}

/**
 * Open an in-memory session over a private content + pointer map and workflow-state twin —
 * ALWAYS opens (`runId: null` mirrors an identity-less branch: artifact writes reject, reads
 * read `absent`, the state ops keep working).
 */
export function openMemoryWorkflowSession(opts: {
  runId: string | null;
  nodeClaim?: { objective: string; node: string } | null;
  activePlanRef?: PlanRef | null;
  activeObjective?: string | null;
}): MemoryWorkflowSession {
  const runId = opts.runId;
  const contents = new Map<string, string>();
  const pointers = new Map<string, SessionArtifactPointer>();
  let claim = opts.nodeClaim ?? null;
  let activePlanRef = opts.activePlanRef ?? null;
  let activeObjective = opts.activeObjective ?? null;
  let failWrite = false;
  let failPointerAppend = false;
  let failApply = false;
  let failApplyVerification = false;

  const session: MemoryWorkflowSession = {
    runId,
    failNextWrite() {
      failWrite = true;
    },
    failNextPointerAppend() {
      failPointerAppend = true;
    },
    corruptContent(name: string) {
      const current = contents.get(name);
      if (current !== undefined) contents.set(name, `${current} [corrupted]`);
    },
    dropContent(name: string) {
      contents.delete(name);
    },
    disownPointer(name: string) {
      const pointer = pointers.get(name);
      if (pointer !== undefined) pointers.set(name, { ...pointer, run_id: `${runId}.foreign` });
    },
    failNextApply() {
      failApply = true;
    },
    failNextApplyVerification() {
      failApplyVerification = true;
    },
    setNodeClaim(next: { objective: string; node: string } | null) {
      claim = next;
    },
    setActiveObjective(next: string | null) {
      activeObjective = next;
    },
    linkedPlanRef() {
      return activePlanRef;
    },
    nodeClaim() {
      return claim;
    },
    activeObjective() {
      return activeObjective;
    },
    readArtifact(name: string): ReadArtifactResult {
      if (runId === null) return { status: "absent" }; // no identity — silent, branchable
      const pointer = pointers.get(name);
      if (pointer === undefined) return { status: "absent" };
      if (pointer.run_id !== runId) return { status: "absent" }; // fork isolation — silent
      const content = contents.get(name);
      if (content === undefined) {
        return { status: "invalid", problem: `session artifact ${name} has a pointer but no file` };
      }
      if (digestSessionData(content) !== pointer.digest) {
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
      if (runId === null) {
        // The no-identity classification (mirrors the classified write core's refusal).
        return {
          status: "rejected",
          problem: "session has no run_id — session artifacts need identity",
        };
      }

      // The unchanged short-circuit (same probe as the branch backing: a valid current pointer
      // whose stored digest equals the new content's — quiet, no fresh pointer).
      const current = pointers.get(name);
      const stored = contents.get(name);
      if (
        current !== undefined &&
        current.run_id === runId &&
        stored !== undefined &&
        digestSessionData(stored) === current.digest &&
        current.digest === digestSessionData(content)
      ) {
        return { status: "unchanged", pointer: current };
      }

      if (failWrite) {
        failWrite = false;
        return { status: "rejected", problem: `could not write session data ${name} (induced)` };
      }
      contents.set(name, content);
      if (failPointerAppend) {
        failPointerAppend = false;
        // The orphan arm: the bytes landed, the pointer did not — never consumable.
        return {
          status: "unverified",
          problem: `session_artifacts pointer read-back failed for ${name}`,
        };
      }
      const pointer: SessionArtifactPointer = {
        run_id: runId,
        name,
        path: name,
        digest: digestSessionData(content),
        at: new Date().toISOString(),
      };
      pointers.set(name, pointer);
      return { status: "applied", pointer };
    },
    apply(change: WorkflowChange): WorkflowChangeResult {
      switch (change.kind) {
        case "link-plan-ref": {
          if (planRefsEqual(activePlanRef, change.ref)) return { status: "unchanged" };
          if (failApply) {
            failApply = false;
            return { status: "rejected", problem: "workflow-state append refused (induced)" };
          }
          activePlanRef = change.ref;
          if (failApplyVerification) {
            failApplyVerification = false;
            return {
              status: "unverified",
              problem: `plan-ref read-back failed for ${change.ref.provider}:${change.ref.pr_id}`,
            };
          }
          return { status: "applied" };
        }
        case "clear-node-claim": {
          // Never clobber an unrelated claim: both fields must match the live claim.
          if (!nodeClaimsEqual(claim, change.claim)) return { status: "unchanged" };
          if (failApply) {
            failApply = false;
            return { status: "rejected", problem: "workflow-state append refused (induced)" };
          }
          claim = null;
          if (failApplyVerification) {
            failApplyVerification = false;
            return {
              status: "unverified",
              problem: `objective_node_claim clear read-back failed for node ${change.claim.node}`,
            };
          }
          return { status: "applied" };
        }
        case "record-node-claim": {
          // The idempotent re-claim short-circuit (an equal claim rebuilds identically).
          if (nodeClaimsEqual(claim, change.claim)) return { status: "unchanged" };
          if (failApply) {
            failApply = false;
            return { status: "rejected", problem: "workflow-state append refused (induced)" };
          }
          claim = change.claim;
          if (failApplyVerification) {
            failApplyVerification = false;
            return {
              status: "unverified",
              problem:
                `objective_node_claim read-back failed for #${change.claim.objective} node ` +
                change.claim.node,
            };
          }
          return { status: "applied" };
        }
        case "link-objective": {
          if (activeObjective === change.objective) return { status: "unchanged" };
          if (failApply) {
            failApply = false;
            return { status: "rejected", problem: "workflow-state append refused (induced)" };
          }
          activeObjective = change.objective;
          if (failApplyVerification) {
            failApplyVerification = false;
            return {
              status: "unverified",
              problem: `active_objective read-back failed for #${change.objective}`,
            };
          }
          return { status: "applied" };
        }
      }
    },
  };
  return session;
}
