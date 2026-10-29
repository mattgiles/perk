// Perk identities and their deterministic derivation (docs/design/pi-durable-v2-foundations.md §4).
//
// Invariants:
// - The execution id (a ULID) is the only random identity; every other id derives from it and
//   from record content, so a retry re-derives the same id and finds its receipt.
// - Each derivation validates its parts and throws `RangeError` on a malformed one; callers
//   validate untrusted input before deriving anything.
// - The op-id helpers over a caller-held id are pure concatenation, so a lookup with a garbage id
//   simply misses.
// - `decision` and the execution-scope op kinds never name an assignment kind: the segment after
//   `v2/<execution-id>/` tells an assignment apart from execution-scope ids.

import { isLowerHex } from "./canonical.ts";

export const OP_KINDS = [
  "observe",
  "admit",
  "submit",
  "launch",
  "accept-report",
  "aggregate",
  "open-decision",
  "reply",
  "continuation",
  "cancel",
] as const;

export type OpKind = (typeof OP_KINDS)[number];

/** Segments that never name an assignment `<kind>`. */
export const RESERVED_ASSIGNMENT_KINDS = ["decision", "observe", "aggregate", "cancel"] as const;

/** `[a-z][a-z0-9-]*`: the grammar of a kind, role, decision kind and op kind. */
export function isSlug(value: string): boolean {
  return typeof value === "string" && /^[a-z][a-z0-9-]*$/.test(value);
}

/** A ULID: 26 uppercase Crockford base32 characters. */
export function isExecutionId(value: string): boolean {
  return typeof value === "string" && /^[0-9A-HJKMNP-TV-Z]{26}$/.test(value);
}

/** A git object id: lowercase hex, sha1 (40) or sha256 (64). */
export function isGitOid(value: string): boolean {
  return isLowerHex(value, 40) || isLowerHex(value, 64);
}

/** A sha256 digest: 64 lowercase hex. */
export function isSha256Hex(value: string): boolean {
  return isLowerHex(value, 64);
}

function isReservedKind(kind: string): boolean {
  return (RESERVED_ASSIGNMENT_KINDS as readonly string[]).includes(kind);
}

function isOrdinal(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 1;
}

function malformed(what: string, value: unknown): RangeError {
  const shown = typeof value === "string" ? JSON.stringify(value) : String(value);
  return new RangeError(`malformed ${what}: ${shown}`);
}

/** `v2/<execution-id>`. */
export function executionScopeId(executionId: string): string {
  if (!isExecutionId(executionId)) throw malformed("execution id", executionId);
  return `v2/${executionId}`;
}

/** True iff `value` has the assignment-id grammar. */
export function isAssignmentId(value: string): boolean {
  if (typeof value !== "string") return false;
  const [prefix, executionId, kind, role, subject, capset, ...rest] = value.split("/");
  return (
    rest.length === 0 &&
    prefix === "v2" &&
    executionId !== undefined &&
    isExecutionId(executionId) &&
    kind !== undefined &&
    isSlug(kind) &&
    !isReservedKind(kind) &&
    role !== undefined &&
    isSlug(role) &&
    subject !== undefined &&
    isGitOid(subject) &&
    capset !== undefined &&
    isSha256Hex(capset)
  );
}

/** `v2/<execution-id>/<kind>/<role>/<subject-digest>/<capset-digest>`. */
export function deriveAssignmentId(parts: {
  readonly executionId: string;
  readonly kind: string;
  readonly role: string;
  readonly subjectDigest: string;
  readonly capabilitySetDigest: string;
}): string {
  const scope = executionScopeId(parts.executionId);
  if (!isSlug(parts.kind)) throw malformed("assignment kind", parts.kind);
  if (isReservedKind(parts.kind)) throw malformed("assignment kind (reserved)", parts.kind);
  if (!isSlug(parts.role)) throw malformed("role", parts.role);
  if (!isGitOid(parts.subjectDigest)) throw malformed("subject digest", parts.subjectDigest);
  if (!isSha256Hex(parts.capabilitySetDigest)) {
    throw malformed("capability-set digest", parts.capabilitySetDigest);
  }
  return `${scope}/${parts.kind}/${parts.role}/${parts.subjectDigest}/${parts.capabilitySetDigest}`;
}

/** `<assignment-id>/<ordinal>`, the ordinal 1-based decimal with no leading zeros. */
export function deriveAttemptId(assignmentId: string, ordinal: number): string {
  if (!isAssignmentId(assignmentId)) throw malformed("assignment id", assignmentId);
  if (!isOrdinal(ordinal)) throw malformed("attempt ordinal", ordinal);
  return `${assignmentId}/${ordinal}`;
}

/** `v2/<execution-id>/decision/<subject-digest>/<decision-kind>`. */
export function deriveDecisionId(parts: {
  readonly executionId: string;
  readonly subjectDigest: string;
  readonly decisionKind: string;
}): string {
  const scope = executionScopeId(parts.executionId);
  if (!isGitOid(parts.subjectDigest)) throw malformed("subject digest", parts.subjectDigest);
  if (!isSlug(parts.decisionKind)) throw malformed("decision kind", parts.decisionKind);
  return `${scope}/decision/${parts.subjectDigest}/${parts.decisionKind}`;
}

/** `v2/<execution-id>/observe/<seq>`. */
export function observeOpId(executionId: string, seq: number): string {
  const scope = executionScopeId(executionId);
  if (!isOrdinal(seq)) throw malformed("observation seq", seq);
  return `${scope}/observe/${seq}`;
}

/** `<assignment-id>/admit`. */
export function admitOpId(assignmentId: string): string {
  return `${assignmentId}/admit`;
}

/** `<attempt-id>/submit`: the Durable `requestId` of the attempt's submission. */
export function submitOpId(attemptId: string): string {
  return `${attemptId}/submit`;
}

/**
 * `<attempt-id>/launch`: the durable-map key of the attempt's launched Durable task; the kernel
 * records nothing under it.
 */
export function launchOpId(attemptId: string): string {
  return `${attemptId}/launch`;
}

/** `<attempt-id>/accept-report`. */
export function acceptReportOpId(attemptId: string): string {
  return `${attemptId}/accept-report`;
}

/** `v2/<execution-id>/aggregate/<subject-digest>`. */
export function aggregateOpId(executionId: string, subjectDigest: string): string {
  const scope = executionScopeId(executionId);
  if (!isGitOid(subjectDigest)) throw malformed("subject digest", subjectDigest);
  return `${scope}/aggregate/${subjectDigest}`;
}

/** `<decision-id>/open-decision`. */
export function openDecisionOpId(decisionId: string): string {
  return `${decisionId}/open-decision`;
}

/** `<decision-id>/reply`. */
export function replyOpId(decisionId: string): string {
  return `${decisionId}/reply`;
}

/** `<decision-id>/continuation`. */
export function continuationOpId(decisionId: string): string {
  return `${decisionId}/continuation`;
}

/** `v2/<execution-id>/cancel`. */
export function cancelOpId(executionId: string): string {
  return `${executionScopeId(executionId)}/cancel`;
}
