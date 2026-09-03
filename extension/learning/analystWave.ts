// The `/learn` flow's analyst-wave policy over the shared report-wave module: the analyst
// fan-out as CODE. It owns the four learn angles, the analyst report schema, the tool-enforced
// angle policy (2–4 angles, `session-deviations` mandatory — parse-don't-validate), the
// assignment/task composition, the whitelist report decoder (`decodeLearnAnalystReport` — the
// trust boundary keyed by the validated assignment), and the typed outcome mapping — delegating
// spawn/timeout/aggregate mechanics to `wave.run` under the `best-effort` completeness policy
// (a failed analyst is an explicitly-reported skipped angle, never a failed pass). Analyst reports come
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
import { CAPTURED_DECISIONS, type CapturedDecision, isCapturedDecision } from "./capture.ts";

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

/** One decoded analyst candidate (the typed twin of the schema's `candidates` items). */
export interface LearnAnalystCandidate {
  decision: CapturedDecision | "SKIP";
  summary: string;
  target: string | null;
  evidence: string;
}

/** The decoded analyst report (the typed twin of `LEARN_ANALYST_REPORT_SCHEMA`). */
export interface LearnAnalystReport {
  angle: LearnAngle;
  verdict: "clean" | "actionable";
  candidates: LearnAnalystCandidate[];
  fyi: string[];
}

/**
 * Decode one lane's engine-validated structured report at the trust boundary (the
 * `stampHarvestReport` pattern): whitelist construction field-by-field — never a spread — with
 * `angle` set from the validated assignment KEY, so a report can never re-attribute itself.
 * The observable detail taxonomy is exactly two byte-shapes: the angle-contradiction arm (a
 * schema-valid report whose echoed angle names a DIFFERENT lane — unattributable content,
 * never salvaged) and ONE stable generic vocabulary detail for everything else (no per-field
 * diagnostics — schema enforcement is upstream, engine-validated; this decoder is a boundary,
 * not a linter). The defensive narrowings (a non-angle key, a non-record report) are
 * unreachable on the production path — `ReportWave.normalizeAssignments` filters non-object
 * reports and unknown aggregate keys first — so they fold into the generic detail.
 */
export function decodeLearnAnalystReport(
  key: string,
  report: unknown,
): { ok: true; report: LearnAnalystReport } | { ok: false; detail: string } {
  const generic = {
    ok: false as const,
    detail: `analyst report for lane '${key}' is outside the report schema vocabulary`,
  };
  if (!isLearnAngle(key)) return generic;
  if (typeof report !== "object" || report === null || Array.isArray(report)) return generic;
  const raw = report as Record<string, unknown>;
  const angle = raw.angle;
  if (typeof angle !== "string" || !isLearnAngle(angle)) return generic;
  if (angle !== key) {
    return {
      ok: false,
      detail: `analyst report angle '${angle}' contradicts the assigned lane '${key}'`,
    };
  }
  const verdict = raw.verdict;
  if (verdict !== "clean" && verdict !== "actionable") return generic;
  if (!Array.isArray(raw.candidates)) return generic;
  const candidates: LearnAnalystCandidate[] = [];
  for (const item of raw.candidates) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return generic;
    const c = item as Record<string, unknown>;
    const decision = c.decision;
    if (typeof decision !== "string") return generic;
    if (!isCapturedDecision(decision) && decision !== "SKIP") return generic;
    const summary = c.summary;
    const target = c.target;
    const evidence = c.evidence;
    if (typeof summary !== "string" || typeof evidence !== "string") return generic;
    if (target !== null && typeof target !== "string") return generic;
    candidates.push({ decision, summary, target, evidence });
  }
  const fyiRaw = raw.fyi;
  if (!Array.isArray(fyiRaw)) return generic;
  const fyi: string[] = [];
  for (const entry of fyiRaw) {
    if (typeof entry !== "string") return generic;
    fyi.push(entry);
  }
  return { ok: true, report: { angle: key, verdict, candidates, fyi } };
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
      reports: { angle: LearnAngle; report: LearnAnalystReport }[];
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

  // Decode every lane report at the trust boundary: an undecodable/contradictory report moves
  // its lane to `skipped` (`malformed-report`) with the decoder's detail. Skip ordering:
  // decoder skips first (report order), then the wave's own lane failures.
  const reports: { angle: LearnAngle; report: LearnAnalystReport }[] = [];
  const decoderSkips: { angle: string; reason: ReportWaveFailureReason; detail: string }[] = [];
  for (const r of result.reports) {
    const decoded = decodeLearnAnalystReport(r.key, r.report);
    if (decoded.ok) {
      reports.push({ angle: decoded.report.angle, report: decoded.report });
    } else {
      decoderSkips.push({ angle: r.key, reason: "malformed-report", detail: decoded.detail });
    }
  }
  const skipped = [
    ...decoderSkips,
    ...result.failures
      .filter((f) => f.key !== null)
      .map((f) => ({ angle: f.key as string, reason: f.reason, detail: f.detail })),
  ];
  return { kind: "complete", reports, skipped, attempts };
}
