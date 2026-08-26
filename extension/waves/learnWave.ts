// The `/learn` flow's per-flow wave entrypoint over the shared report-wave runner: the analyst
// fan-out as CODE. It owns the four learn angles, the analyst report schema, the tool-enforced
// angle policy (2–4 angles, `session-deviations` mandatory), and the assignment/task
// composition — delegating spawn/timeout/aggregate mechanics to `runReportWave` under the
// `best-effort` completeness policy (a failed analyst is an explicitly-reported skipped angle,
// never a failed pass). Analyst reports come back as engine-validated structured output (the
// workflow-level `outputSchema` → the injected `structured_output` tool), replacing fenced-JSON
// scraping.

import {
  type ReportAssignment,
  runReportWave,
  type WaveAdapter,
  type WaveResult,
} from "./reportWave.ts";

/** The four learn angles; `session-deviations` is the mandatory member of every selection. */
export const LEARN_ANGLES = [
  "session-deviations",
  "plan-vs-implementation",
  "existing-docs",
  "validation-risk",
] as const;

const MANDATORY_ANGLE = "session-deviations";

/**
 * The per-lane analyst report schema (the workflow-level `outputSchema`): closed shape,
 * all-required, enums, `target` required-nullable ({angle, verdict, candidates, fyi} — the same
 * field semantics as the agent def's report contract). DELIBERATE DIVERGENCE from
 * `PR_REVIEW_REPORT_SCHEMA`: no if/then verdict↔candidates conditional. Under `best-effort`
 * completeness, salvaging an internally inconsistent report beats failing its lane — the parent
 * derives the real verdict from `candidates[]` (`verdict` is derived data), so an inconsistent
 * verdict costs nothing while a failed lane loses the whole angle.
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
            enum: [
              "CAPTURE_LEARN",
              "SHOULD_BE_CODE",
              "UPDATE_EXISTING_DOC",
              "NEW_DOC",
              "STALE_DOC",
              "SKIP",
            ],
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
  angle: string;
  emphasis?: string;
}

/**
 * The angle policy as one pure function (tested implementation, not guidance): 2–4 angles, no
 * duplicates, only the four known slugs, and `session-deviations` always included. Returns the
 * human-readable rule violation, or null when the selection is valid.
 */
export function angleSelectionError(selections: LearnAngleSelection[]): string | null {
  if (selections.length < 2 || selections.length > 4) {
    return `choose 2–4 angles (got ${selections.length})`;
  }
  const seen = new Set<string>();
  for (const { angle } of selections) {
    if (!(LEARN_ANGLES as readonly string[]).includes(angle)) {
      return `unknown angle '${angle}' — the valid angles are ${LEARN_ANGLES.join(", ")}`;
    }
    if (seen.has(angle)) {
      return `duplicate angle '${angle}' — each angle at most once`;
    }
    seen.add(angle);
  }
  if (!seen.has(MANDATORY_ANGLE)) {
    return `the '${MANDATORY_ANGLE}' angle is mandatory — always include it`;
  }
  return null;
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

/**
 * Run the learn analyst wave: one `perk.learn-analyst` child per selected angle over the shared
 * evidence bundle, `best-effort` completeness (assignment failure = a skipped angle; only a
 * wave-level failure makes the result incomplete). Assumes a validated selection — the
 * `run_learn_wave` tool runs `angleSelectionError` first; the runner's programmer-error throws
 * (empty/duplicate keys) remain the backstop.
 */
export async function runLearnWave(
  adapter: WaveAdapter,
  opts: {
    selections: LearnAngleSelection[];
    manifestPath: string;
    bundleDir: string;
    model?: string;
  },
  signal?: AbortSignal,
): Promise<WaveResult> {
  const assignments: ReportAssignment[] = opts.selections.map((selection) => ({
    key: selection.angle,
    label: selection.angle,
    agent: "perk.learn-analyst",
    phase: "learn",
    task: assignmentTask(selection, opts.manifestPath, opts.bundleDir),
  }));
  return await runReportWave(
    adapter,
    {
      flow: "learn",
      assignments,
      outputSchema: LEARN_ANALYST_REPORT_SCHEMA,
      completeness: "best-effort",
      ...(opts.model !== undefined ? { model: opts.model } : {}),
    },
    signal,
  );
}
