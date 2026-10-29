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
// - The worker policy is pure text and names: the capability set binds the model, the worker
//   extension and every tool it enables (the report tool included, P7), plus the digest of the
//   one instructions text, so a changed instruction is a different assignment.

import { sha256Hex } from "./canonical.ts";
import { type CapabilitySet, capabilitySetDigest, normalizeCapabilitySet } from "./capability.ts";
import { deriveAssignmentId, isGitOid, isSlug } from "./identity.ts";
import { indexRecords, type KernelRecord, type RecordIndex } from "./records.ts";

export const FIXTURE_EXECUTION_KIND = "fixture-review";
export const FIXTURE_ASSIGNMENT_KIND = "fixture-report";
export const FIXTURE_ROLES = ["a", "b"] as const;
export const FIXTURE_DECISION_KIND = "fixture-approval";
export const FIXTURE_ACTIONS = ["approve", "reject"] as const;
export const FIXTURE_ACTOR = "human:cli";

/** The host-resolved, code-owned policy the fixture rules read (versioned by `policyVersion`). */
export type FixturePolicy = { readonly capabilitySet: CapabilitySet };

/** The extension that carries the worker's tools and the native assignment task. */
export const FIXTURE_WORKER_EXTENSION = "perk.v2.report";
/** The tool a worker finishes through. */
export const FIXTURE_REPORT_TOOL = "report";
/** Every tool a worker conversation enables, sorted: three read tools, `read`, and the report. */
export const FIXTURE_WORKER_TOOLS = ["find", "grep", "ls", "read", FIXTURE_REPORT_TOOL] as const;
/** The worker's model. */
export const FIXTURE_MODEL = { provider: "faux", modelId: "faux-1" } as const;
/** The policy version of `fixturePolicy()`; a change to the policy bumps it. */
export const FIXTURE_POLICY_VERSION = 1;

const FIXTURE_INSTRUCTIONS = [
  "You review one git tree. The workspace root is a read-only snapshot of that tree.",
  "Read it only with these tools: `read` (one file), `ls` (one directory), `grep` (literal,",
  "case-sensitive text, never a regular expression) and `find` (a glob matched against paths",
  "relative to the search root).",
  "Nothing can be written or executed, and every path outside the snapshot is refused.",
  "Finish by calling `report` exactly once, alone in its turn, as your last action, with",
  '{"subjectDigest": <the tree named in the request>, "summary": <non-empty text>,',
  '"findings": [{"path": <snapshot-relative path>, "note": <non-empty text>}]}.',
  'A finding path has no leading "/" and no empty, "." or ".." segment. Use an empty',
  "findings list when there is nothing to note.",
].join("\n");

/** The worker's fixed instructions; their sha256 is the capability set's `instructionsDigest`. */
export function renderFixtureInstructions(): string {
  return FIXTURE_INSTRUCTIONS;
}

/**
 * The per-attempt submission content naming the role and the subject tree; deterministic, so a
 * rerun submits the same text. Throws `RangeError` for a malformed role or tree.
 */
export function fixtureWorkerPrompt(role: string, subjectDigest: string): string {
  if (!isSlug(role)) throw new RangeError(`malformed role: ${JSON.stringify(role)}`);
  if (!isGitOid(subjectDigest)) {
    throw new RangeError(`malformed subject digest: ${JSON.stringify(subjectDigest)}`);
  }
  return `Review subject ${subjectDigest} as reviewer ${role}.`;
}

/** The fixture policy: the normalized worker capability set over the constants above. */
export function fixturePolicy(): FixturePolicy {
  return {
    capabilitySet: normalizeCapabilitySet({
      model: { provider: FIXTURE_MODEL.provider, modelId: FIXTURE_MODEL.modelId },
      extensions: [FIXTURE_WORKER_EXTENSION],
      tools: [...FIXTURE_WORKER_TOOLS],
      instructionsDigest: sha256Hex(renderFixtureInstructions()),
      posture: "read-only",
      workspaceRoot: "subject-snapshot",
    }),
  };
}

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
