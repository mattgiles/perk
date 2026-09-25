// The draft + compaction feature op (the `/draft-and-compact` policy tier), Pi-free. Owns the
// invocation decision (gate → session routing → baseline capture), the pending record, and the
// settle gate — which proves a FRESH CHECKPOINT: the working-draft artifact changed on the SAME
// run since invocation (the digest moved, or an absent/invalid artifact became a valid one). A
// fork mid-drive never compares unrelated artifacts, and a byte-identical rewrite skips. The
// feature carries no prose and no severity — every outcome is data; rendering and Pi delivery
// live in `pi/v1/draftCompact.ts`.

import { digestSessionData, type WorkflowSession } from "../session/workflowSession.ts";
import { DRAFT_SUBJECT_ARTIFACTS, type DraftSubject } from "./review/subjects.ts";

/** The invocation-time draft state — three DISTINCT facts, never collapsed: a valid draft's
 * digest, no draft at all, or a draft that failed validation. */
export type DraftBaseline =
  | { kind: "digest"; digest: string }
  | { kind: "absent" }
  | { kind: "invalid" };

/** The one-shot record the drive arm mints — the settle gate compares against it. */
export interface DraftCompactPending {
  subject: DraftSubject;
  runId: string;
  baseline: DraftBaseline;
}

/** The proven checkpoint: the subject and the exact bytes read at settle (the continuation
 * embeds them). */
export interface DraftCompactCompletion {
  subject: DraftSubject;
  content: string;
}

/** The invocation decision — skip loudly, or drive the checkpoint turn. `current` is the valid
 * draft's bytes at invocation (embedded in the guidance), null when there is none. */
export type DraftCompactStart =
  | { kind: "skip"; reason: "not-gated" | "no-identity" | "invalid-state" }
  | { kind: "drive"; pending: DraftCompactPending; current: string | null };

/** The settle decision — compact on a proven fresh checkpoint, or skip loudly. */
export type DraftCompactSettle =
  | { kind: "skip"; reason: "run-changed" | "no-draft" | "unchanged-draft" }
  | { kind: "compact-now"; completion: DraftCompactCompletion };

/** The invocation arms: gate (NO session reads — the factory is never called) → routing →
 * baseline. Always drives when gated: a planning session always has thinking to checkpoint. */
export function startDraftAndCompact(
  gateActive: boolean,
  openSession: () => WorkflowSession,
): DraftCompactStart {
  if (!gateActive) return { kind: "skip", reason: "not-gated" };
  const session = openSession();
  const context = session.draftReviewContext();
  if (!context.ok) return { kind: "skip", reason: context.reason };
  const { subject, runId } = context;
  const read = session.readArtifact(DRAFT_SUBJECT_ARTIFACTS[subject]);
  switch (read.status) {
    case "found":
      return {
        kind: "drive",
        pending: {
          subject,
          runId,
          baseline: { kind: "digest", digest: digestSessionData(read.content) },
        },
        current: read.content,
      };
    case "absent":
      return {
        kind: "drive",
        pending: { subject, runId, baseline: { kind: "absent" } },
        current: null,
      };
    case "invalid":
      return {
        kind: "drive",
        pending: { subject, runId, baseline: { kind: "invalid" } },
        current: null,
      };
  }
  const exhaustive: never = read; // no default arm: a new read status fails to compile here
  throw new Error(`unreachable artifact read: ${JSON.stringify(exhaustive)}`);
}

/** The settle gate: compact only on PROOF of a fresh checkpoint on the invocation run. The run
 * identity is checked before any artifact read; an absent/invalid baseline followed by a valid
 * draft counts (the artifact went from unusable to valid — the state change the door captures). */
export function settleDraftAndCompact(
  pending: DraftCompactPending,
  session: WorkflowSession,
): DraftCompactSettle {
  const identity = session.currentRunIdentity();
  if (!identity.ok || identity.runId !== pending.runId)
    return { kind: "skip", reason: "run-changed" };
  const read = session.readArtifact(DRAFT_SUBJECT_ARTIFACTS[pending.subject]);
  if (read.status !== "found") return { kind: "skip", reason: "no-draft" };
  const baseline = pending.baseline;
  if (baseline.kind === "digest" && digestSessionData(read.content) === baseline.digest) {
    return { kind: "skip", reason: "unchanged-draft" };
  }
  return { kind: "compact-now", completion: { subject: pending.subject, content: read.content } };
}
