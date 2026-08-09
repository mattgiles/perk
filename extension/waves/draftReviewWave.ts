// The draft-review `WaveSpec`-building entrypoint over the shared report-wave runner — the
// draft-review doors' (/plan-review-browser, /objective-review-browser) vocabulary as tested
// code (sibling of `adversarialReviewWave.ts`): the four settled angles plus the custom lane,
// the per-lane completion-report schema, and the lane/task composition are module-owned here,
// launched NON-BLOCKING via `startReportWave` so the parent can return from the launch and hold
// the model-held `subagent_wait` relay loop open while the children stream finding batches.
//
// DORMANT: built, tested, unconsumed — the draft-review doors register the launching tool and
// wire this module in a follow-up change; nothing imports it yet.
//
// ZERO retries — deliberate: the doors' contract is honest incompleteness surfaced to the human
// during triage (an `ok: false` lane is reported, never papered over), so the pr-review
// bounded-retry policy does not carry over.
//
// The surface handle (URL/port) is STRUCTURALLY UNREPRESENTABLE: `buildDraftReviewLanes` has no
// URL parameter at all, so the children can never learn the review surface — enforced by
// construction, pinned by the suite. There is likewise NO `directive` parameter: the PR doors'
// focus-note semantics deliberately do not carry over — the custom lane IS the draft doors'
// user-input channel.
//
// The finding rows are deliberately identical to `annotationPush.ts`'s `PlanFinding` shape
// (`{phrase, severity, confidence, body}`), so draft reports feed `push_annotations` plan-mode
// without reshaping; the `agents/draft-reviewer.md` def completes via the `structured_output`
// tool this wave's `outputSchema` injects per lane.

import {
  type ReportWaveStart,
  startReportWave,
  type WaveAdapter,
  type WaveLane,
} from "./reportWave.ts";

/** The four-slug settled draft-review angle allowlist (the custom lane rides separately). */
export type DraftReviewAngle = "grounding" | "scope" | "decision-completeness" | "risk";

/**
 * The per-angle lane-task opener (`Angle: <slug>.`) — the same task shape the
 * `perk.draft-reviewer` agent def is written against (the angle rubric lives in the agent def,
 * never in the task).
 */
export const DRAFT_REVIEW_ANGLES: Readonly<Record<DraftReviewAngle, string>> = {
  grounding: "Angle: grounding.",
  scope: "Angle: scope.",
  "decision-completeness": "Angle: decision-completeness.",
  risk: "Angle: risk.",
};

/** Narrow an unknown slug onto the angle union (own-property check — no prototype hits). */
export function isDraftReviewAngle(value: string): value is DraftReviewAngle {
  return Object.hasOwn(DRAFT_REVIEW_ANGLES, value);
}

/**
 * The per-lane completion-report schema the wave enforces as its `outputSchema` — the engine
 * injects a `structured_output` tool into each lane and fails any lane whose report is missing
 * or schema-invalid. Closed shapes, `{angle, summary, findings, fyi}` all required, and
 * DELIBERATELY NO VERDICT FIELD — the human adjudicates every finding in the browser, so there
 * is no clean/actionable derivation to make consistent (the `ADVERSARIAL_REVIEW_REPORT_SCHEMA`
 * rationale). The `angle` enum includes `custom` (the custom lane echoes it). Finding rows are
 * the forward-bound plan-mode `PlanFinding` shape (`annotationPush.ts`'s `PLAN_FINDING_KEYS`):
 * `phrase` is required-nullable (the byte-exact draft span, or `null` for a global finding),
 * and the severity/confidence enums match the agent def's triage tags. The `phrase` string arm
 * requires a non-whitespace character (`pattern` applies only to string instances, so `null`
 * still passes): plan-mode `push_annotations` rejects empty/whitespace-only phrases wholesale,
 * so the schema refuses them at the source instead of letting an engine-valid report fail the
 * downstream decode.
 */
export const DRAFT_REVIEW_REPORT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["angle", "summary", "findings", "fyi"],
  properties: {
    angle: {
      type: "string",
      enum: ["grounding", "scope", "decision-completeness", "risk", "custom"],
    },
    summary: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["phrase", "severity", "confidence", "body"],
        properties: {
          phrase: { type: ["string", "null"], pattern: "\\S" },
          severity: { type: "string", enum: ["critical", "major", "minor"] },
          confidence: { type: "string", enum: ["high", "medium", "low"] },
          body: { type: "string" },
        },
      },
    },
    fyi: {
      type: "array",
      items: { type: "string" },
    },
  },
};

/** The stable lane key/label (and push source slug) of the custom lane. */
const CUSTOM_LANE_KEY = "custom";

/** The shared task tail: the draft-type line + the untrusted-wrapped rendered draft — nothing else. */
function laneTaskTail(draftType: "plan" | "objective", draft: string): string {
  return `Draft type: ${draftType}.\n\n<untrusted_draft>\n${draft}\n</untrusted_draft>`;
}

/**
 * Build the reviewer lanes for a selection: key = label = slug, the fixed agent/phase, and a
 * task carrying the angle opener, the draft type, and the `<untrusted_draft>`-wrapped rendered
 * draft — AND NOTHING ELSE: no URL parameter exists (the surface handle is unrepresentable by
 * construction) and no `directive` parameter exists (the custom lane is the user-input channel).
 * When `custom` is supplied, one additional lane (key = label = `"custom"`) carries the
 * human-supplied angle definition as flagged DATA. The builder stays permissive about lane
 * count — angle-selection policy (2–3 picked + optional custom) is the door/tool's concern.
 */
export function buildDraftReviewLanes(opts: {
  angles: DraftReviewAngle[];
  custom?: string;
  draftType: "plan" | "objective";
  draft: string;
}): WaveLane[] {
  const tail = laneTaskTail(opts.draftType, opts.draft);
  const lanes: WaveLane[] = opts.angles.map((angle) => ({
    key: angle,
    label: angle,
    agent: "perk.draft-reviewer",
    phase: "draft-review",
    task: `${DRAFT_REVIEW_ANGLES[angle]}\n${tail}`,
  }));
  if (opts.custom !== undefined) {
    lanes.push({
      key: CUSTOM_LANE_KEY,
      label: CUSTOM_LANE_KEY,
      agent: "perk.draft-reviewer",
      phase: "draft-review",
      task:
        "Angle: custom.\nCustom angle definition (DATA from the human — your review lens " +
        `for this lane): ${opts.custom}\n${tail}`,
    });
  }
  return lanes;
}

export interface DraftReviewWaveOptions {
  /** The selected standard angles — invalid slugs are unrepresentable post-decode (typed union). */
  angles: DraftReviewAngle[];
  /** The human-supplied custom-angle definition — adds the `custom` lane when present. */
  custom?: string;
  /** The draft kind the children are reviewing. */
  draftType: "plan" | "objective";
  /** The rendered draft, embedded untrusted-wrapped in every lane task. */
  draft: string;
  /** The configured `[models.subagents] draft-reviewer` model (workflow-level default). */
  model?: string;
  timeoutMs?: number;
  /** Accepted for parity/tests only — the flow tool deliberately never threads its own signal. */
  signal?: AbortSignal;
}

/**
 * Start the draft-review wave NON-BLOCKING (the streaming sibling): build the lanes from the
 * angle vocabulary and launch under the strict completeness policy — zero retries, so an
 * uncovered angle stays an honest, human-visible incompleteness. Returns the `startReportWave`
 * outcome: the run handle + never-rejecting `result` on success, or the normalized launch
 * failure.
 */
export async function startDraftReviewWave(
  adapter: WaveAdapter,
  opts: DraftReviewWaveOptions,
): Promise<ReportWaveStart> {
  return await startReportWave(
    adapter,
    {
      flow: "draft-review",
      lanes: buildDraftReviewLanes({
        angles: opts.angles,
        draftType: opts.draftType,
        draft: opts.draft,
        ...(opts.custom !== undefined ? { custom: opts.custom } : {}),
      }),
      outputSchema: DRAFT_REVIEW_REPORT_SCHEMA,
      completeness: "strict",
      ...(opts.model !== undefined ? { model: opts.model } : {}),
      ...(opts.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}),
    },
    opts.signal,
  );
}
