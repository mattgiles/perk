// The `/learn` flow's analyst-wave policy over the shared report-wave module: the analyst
// fan-out as CODE. It owns the four learn angles, the analyst report schema, the tool-enforced
// angle policy (2–4 angles, `session-deviations` mandatory — parse-don't-validate), the
// assignment/task composition, and the typed outcome mapping — delegating spawn/timeout/
// aggregate mechanics to `wave.run` under the `best-effort` completeness policy (a failed
// analyst is an explicitly-reported skipped angle, never a failed pass). Analyst reports come
// back as engine-validated structured output (the workflow-level `outputSchema` → the injected
// `structured_output` tool).
//
// Pi-free by construction: the `ReportWave` seam is the only mechanism edge; the adapter
// constructs the wave at the composition root and threads it.

import { join } from "node:path";
import {
  type ReportAssignment,
  type ReportWave,
  type ReportWaveAttemptReceipt,
  type ReportWaveFailureReason,
  toAttemptReceipt,
} from "../waves/reportWave.ts";
import { CAPTURED_DECISIONS } from "./capture.ts";

/** The four learn angles; `session-deviations` is the mandatory member of every selection. */
export const LEARN_ANGLES = [
  "session-deviations",
  "plan-vs-implementation",
  "existing-docs",
  "validation-risk",
] as const;

export type LearnAngle = (typeof LEARN_ANGLES)[number];

const MANDATORY_ANGLE: LearnAngle = "session-deviations";

function isLearnAngle(value: string): value is LearnAngle {
  return (LEARN_ANGLES as readonly string[]).includes(value);
}

/**
 * The per-lane analyst report schema (the workflow-level `outputSchema`): closed shape,
 * all-required, enums, `target` required-nullable ({angle, verdict, candidates, fyi} — the same
 * field semantics as the agent def's report contract). Enums are DERIVED from the vocabulary
 * constants (`LEARN_ANGLES`; `CAPTURED_DECISIONS` + schema-only `SKIP` — a skip creates no
 * issue), never hand-mirrored. DELIBERATE DIVERGENCE from `PR_REVIEW_REPORT_SCHEMA`: no if/then
 * verdict↔candidates conditional. Under `best-effort` completeness, salvaging an internally
 * inconsistent report beats failing its lane — the parent derives the real verdict from
 * `candidates[]` (`verdict` is derived data), so an inconsistent verdict costs nothing while a
 * failed lane loses the whole angle.
 */
export const LEARN_ANALYST_REPORT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["angle", "verdict", "candidates", "fyi"],
  properties: {
    angle: {
      type: "string",
      enum: [...LEARN_ANGLES],
    },
    verdict: {
      type: "string",
      enum: ["clean", "actionable"],
    },
    candidates: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["decision", "summary", "target", "evidence"],
        properties: {
          decision: {
            type: "string",
            enum: [...CAPTURED_DECISIONS, "SKIP"],
          },
          summary: { type: "string" },
          target: { type: ["string", "null"] },
          evidence: { type: "string" },
        },
      },
    },
    fyi: {
      type: "array",
      items: { type: "string" },
    },
  },
};

/** One chosen angle + the parent's optional plan-specific emphasis for its task text. */
export interface LearnAngleSelection {
  angle: LearnAngle;
  emphasis?: string;
}

/**
 * The angle policy as one parse-don't-validate entry (tested implementation, not guidance):
 * 2–4 angles, no duplicates, only the four known slugs, and `session-deviations` always
 * included. Narrows the shape-decoded rows into `LearnAngleSelection[]` (angle: `LearnAngle`,
 * never a bare string) or returns the human-readable rule violation.
 */
export function parseAngleSelections(
  raw: readonly { angle: string; emphasis?: string }[],
): { ok: true; selections: LearnAngleSelection[] } | { ok: false; message: string } {
  if (raw.length < 2 || raw.length > 4) {
    return { ok: false, message: `choose 2–4 angles (got ${raw.length})` };
  }
  const seen = new Set<LearnAngle>();
  const selections: LearnAngleSelection[] = [];
  for (const { angle, emphasis } of raw) {
    if (!isLearnAngle(angle)) {
      return {
        ok: false,
        message: `unknown angle '${angle}' — the valid angles are ${LEARN_ANGLES.join(", ")}`,
      };
    }
    if (seen.has(angle)) {
      return { ok: false, message: `duplicate angle '${angle}' — each angle at most once` };
    }
    seen.add(angle);
    selections.push({ angle, ...(emphasis !== undefined ? { emphasis } : {}) });
  }
  if (!seen.has(MANDATORY_ANGLE)) {
    return {
      ok: false,
      message: `the '${MANDATORY_ANGLE}' angle is mandatory — always include it`,
    };
  }
  return { ok: true, selections };
}

/**
 * The one derivation point for the bundle's manifest path (shared by the launch routing and the
 * adapter's existence trust check) — `manifestPath` is derived, never passed.
 */
export function learnManifestPath(bundleDir: string): string {
  return join(bundleDir, "manifest.json");
}

/**
 * Compose one assignment's task text IN CODE (the prompt-drift-proof half of the migration):
 * the assigned angle, the absolute manifest path (read first), the bundle dir, and the parent's
 * optional emphasis appended verbatim. Deliberately short — the angle rubric lives in the agent
 * def, not the task.
 */
function assignmentTask(
  selection: LearnAngleSelection,
  manifestPath: string,
  bundleDir: string,
): string {
  const base =
    `angle: ${selection.angle} — analyze ONLY this angle. ` +
    `Read the evidence-bundle manifest FIRST: ${manifestPath} (bundle dir: ${bundleDir}). ` +
    "Do not re-gather the bundle.";
  const emphasis = selection.emphasis?.trim();
  return emphasis !== undefined && emphasis !== "" ? `${base} Emphasis: ${emphasis}` : base;
}

/** The typed analyst-wave outcome: a wave-level failure, or the per-angle reports + skips. */
export type LearnWaveOutcome =
  | {
      kind: "wave_failed";
      reason: ReportWaveFailureReason;
      detail: string;
      attempts: ReportWaveAttemptReceipt[];
    }
  | {
      kind: "complete";
      reports: { angle: string; report: unknown }[];
      skipped: { angle: string; reason: ReportWaveFailureReason; detail: string }[];
      attempts: ReportWaveAttemptReceipt[];
    };

/**
 * Run the learn analyst wave and map its result into the typed outcome: one
 * `perk.learn-analyst` child per selected angle over the shared evidence bundle, `best-effort`
 * completeness (assignment failure = a skipped angle; only a wave-level failure — found via
 * `key === null` — makes the outcome `wave_failed`). ONE attempt, no retry — the receipt rides
 * the outcome for observability only. Assumes a validated selection (`parseAngleSelections`
 * runs at the tool boundary); the wave's programmer-error throws (empty/duplicate keys)
 * remain the backstop. Cancellation: the caller's `AbortSignal` threads into `wave.run`;
 * an abort settles the wave as `cancelled` with a best-effort stop of an already-launched run,
 * normalized into the outcome — never a throw; the wave does not outlive the abort.
 */
export async function runLearnAnalystWave(
  wave: ReportWave,
  opts: {
    bundleDir: string;
    selections: LearnAngleSelection[];
    model?: string;
    signal?: AbortSignal;
  },
): Promise<LearnWaveOutcome> {
  const manifestPath = learnManifestPath(opts.bundleDir);
  const assignments: ReportAssignment[] = opts.selections.map((selection) => ({
    key: selection.angle,
    label: selection.angle,
    agent: "perk.learn-analyst",
    phase: "learn",
    task: assignmentTask(selection, manifestPath, opts.bundleDir),
  }));
  const result = await wave.run(
    {
      flow: "learn",
      assignments,
      outputSchema: LEARN_ANALYST_REPORT_SCHEMA,
      completeness: "best-effort",
      ...(opts.model !== undefined ? { model: opts.model } : {}),
    },
    { signal: opts.signal },
  );
  // The learn flow has no retry — ONE attempt over the validated selection.
  const attempts = [
    toAttemptReceipt(
      "learn",
      1,
      opts.selections.map((s) => s.angle),
      result.receipt,
    ),
  ];

  if (!result.complete) {
    const waveFailure = result.failures.find((f) => f.key === null);
    return {
      kind: "wave_failed",
      reason: waveFailure?.reason ?? "run-failed",
      detail: waveFailure?.detail ?? "the analyst wave failed without detail",
      attempts,
    };
  }

  const reports = result.reports.map((r) => ({ angle: r.key, report: r.report }));
  const skipped = result.failures
    .filter((f) => f.key !== null)
    .map((f) => ({ angle: f.key as string, reason: f.reason, detail: f.detail }));
  return { kind: "complete", reports, skipped, attempts };
}
