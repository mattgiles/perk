// The deterministic in-memory WorkflowSession backing (the waves-memory-adapter precedent: a
// production file so feature tests need no filesystem or branch fixtures). It mirrors the
// classified cores' arms exactly — same name validation, same unchanged short-circuit, same
// rejected/unverified split — with deterministic failure knobs so the shared interface suite
// reaches every arm without permission tricks or fake sinks.

import { digestSessionData, sessionArtifactNameProblem } from "../substrate/sessionData.ts";
import type { SessionArtifactPointer } from "../substrate/workflowState.ts";
import type { ReadArtifactResult, WorkflowSession, WriteArtifactResult } from "./workflowSession.ts";

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
}

/** The memory open union — assignable to `OpenWorkflowSession`, with the knob-bearing session. */
export type OpenMemoryWorkflowSession =
  | { status: "opened"; session: MemoryWorkflowSession }
  | { status: "absent" };

/**
 * Open an in-memory session: `absent` when `runId` is null (mirroring an identity-less branch),
 * else an opened session over a private content + pointer map.
 */
export function openMemoryWorkflowSession(opts: {
  runId: string | null;
}): OpenMemoryWorkflowSession {
  const runId = opts.runId;
  if (runId === null) return { status: "absent" };

  const contents = new Map<string, string>();
  const pointers = new Map<string, SessionArtifactPointer>();
  let failWrite = false;
  let failPointerAppend = false;

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
    readArtifact(name: string): ReadArtifactResult {
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
  };
  return { status: "opened", session };
}
