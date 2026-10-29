// The fixture-review execution kind's constants, policy and coverage
// (docs/design/pi-durable-v2-foundations.md §12 — a fixture; real execution kinds replace it).
//
// Invariants:
// - Coverage reads the CURRENT subject: the latest observation's tree. Each role is looked up by
//   its derived assignment id under the host-resolved policy, so records over earlier subjects or
//   under another capability set never count.
// - Roles are reported in `FIXTURE_ROLES` order, never in record order, so coverage is a pure
//   function of the record set.
// - Incomplete coverage stays visible: a role without an accepted outcome is listed with
//   `acceptedOutcomeId: null` and `complete` is false (P6).

import { type CapabilitySet, capabilitySetDigest } from "./capability.ts";
import { deriveAssignmentId } from "./identity.ts";
import { indexRecords, type KernelRecord, type RecordIndex } from "./records.ts";

export const FIXTURE_EXECUTION_KIND = "fixture-review";
export const FIXTURE_ASSIGNMENT_KIND = "fixture-report";
export const FIXTURE_ROLES = ["a", "b"] as const;
export const FIXTURE_DECISION_KIND = "fixture-approval";
export const FIXTURE_ACTIONS = ["approve", "reject"] as const;
export const FIXTURE_ACTOR = "human:cli";

/** The host-resolved, code-owned policy the fixture rules read (versioned by `policyVersion`). */
export type FixturePolicy = { readonly capabilitySet: CapabilitySet };

/** The assignment id for `role` over `subjectDigest` under the policy's capability set. */
export function roleAssignmentId(
  executionId: string,
  role: string,
  subjectDigest: string,
  policy: FixturePolicy,
): string {
  return deriveAssignmentId({
    executionId,
    kind: FIXTURE_ASSIGNMENT_KIND,
    role,
    subjectDigest,
    capabilitySetDigest: capabilitySetDigest(policy.capabilitySet),
  });
}

export type RoleCoverage = {
  readonly role: string;
  readonly assignmentId: string;
  readonly admitted: boolean;
  readonly attempts: number;
  readonly acceptedOutcomeId: string | null;
};

export type Coverage = {
  readonly subjectDigest: string | null;
  readonly roles: readonly RoleCoverage[];
  readonly complete: boolean;
};

/** Coverage of the current subject, one entry per fixture role in role order. */
export function coverageOf(index: RecordIndex, policy: FixturePolicy): Coverage {
  if (index.manifest === null || index.latest === null) {
    return { subjectDigest: null, roles: [], complete: false };
  }
  const executionId = index.manifest.workspace.executionId;
  const current = index.latest.tree;
  const roles = FIXTURE_ROLES.map((role): RoleCoverage => {
    const assignmentId = roleAssignmentId(executionId, role, current, policy);
    const attempts = index.attemptsByAssignment.get(assignmentId) ?? [];
    const accepted = attempts
      .map((attempt) => index.outcomesByAttempt.get(attempt.attemptId))
      .find((outcome) => outcome !== undefined);
    return {
      role,
      assignmentId,
      admitted: index.assignments.has(assignmentId),
      attempts: attempts.length,
      acceptedOutcomeId: accepted?.opId ?? null,
    };
  });
  return {
    subjectDigest: current,
    roles,
    complete: roles.every((role) => role.acceptedOutcomeId !== null),
  };
}

/** `coverageOf` over a record set (validated first). */
export function coverage(records: readonly KernelRecord[], policy: FixturePolicy): Coverage {
  return coverageOf(indexRecords(records), policy);
}
