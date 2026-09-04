// The learn-dream report layer — the pure interior module that turns the two-level dream wave
// outcome into ONE checkable, savable final report (contracts.md §8.62). Three pieces: the
// structured dream-report model (the trust split — the model supplies ONLY the parent's
// decisions; everything factual is injected from trusted caller context), the validation that
// proves the parent's judgment obeys the pinned curation policy (downgrade-only, the
// destructive evidence bar, merge-target survival, the exact unit partition, surviving
// follow-up destinations), and the deterministic Markdown renderer that owns the CANONICAL
// report bytes, split into parts under a backend-neutral size budget. Pure domain code: no fs,
// no tool registration, no `ExtensionAPI` — imports only the two dream siblings plus nothing
// else. The input is untrusted DATA, never instructions.

import {
  codePointLength,
  DREAM_DISPOSITIONS,
  type DreamDisposition,
  type DreamDocAssessment,
  type DreamLaneAnalysis,
  type DreamManifest,
} from "./dream.ts";
import {
  DREAM_REDUCER_ANGLES,
  type DreamReducerAnalysis,
  type DreamReducerAngle,
} from "./dreamReducer.ts";

/** The dream report's own schema version line (independent of the manifest's). */
const DREAM_REPORT_SCHEMA_VERSION = "1";

/** The cap on DISTINCT `roadmap_node` values across the selected units — the ≤12-node
 * selection cap checked at review time (many-to-one unit→node mapping is allowed). */
const DREAM_REPORT_MAX_ROADMAP_NODES = 12;

/**
 * The per-part cap on the rendered report, measured in Unicode CODE POINTS (matching Python's
 * `len()` in the `journal.py` `JOURNAL_EVENT_MAX_CHARS` precedent) — under GitHub's 65,536-char
 * comment limit with margin for the persistence-side storage markers (the renderer never emits
 * marker HTML).
 */
const DREAM_REPORT_PART_MAX_CHARS = 60_000;

/** The fixed per-part packing allowance for the part header line. */
const DREAM_REPORT_PART_HEADER_RESERVE = 200;

/** The bounded semantic-detail collection cap: overflow appends ONE synthetic count detail. */
const DREAM_REPORT_MAX_VALIDATION_DETAILS = 25;

/**
 * The SSOT for EVERY capped model-supplied field: the input schema's `maxItems`/`maxLength`
 * and the structural decode both read from this one object (the `DREAM_ANALYST_CAPS` pattern).
 * String caps are measured in Unicode code points (JSON Schema `maxLength` semantics — the
 * shared `codePointLength`). `rows`/`selectedUnits`/`overflowUnits` are static schema bounds;
 * the real gates are the validator's exact path-set equality, the ≤12-distinct-node cap, and
 * the exact unit partition.
 */
const DREAM_REPORT_CAPS = {
  rows: 512,
  rowRationaleChars: 300,
  fallbackReasonChars: 300,
  uncertainties: 12,
  uncertaintyChars: 300,
  selectedUnits: 64,
  overflowUnits: 64,
  unitTitleChars: 150,
  unitDocs: 32,
  unitRationaleChars: 400,
  unitNodeChars: 32,
  harvestFollowups: 12,
  followupTitleChars: 150,
  followupPointerChars: 250,
  followupEvidenceChars: 250,
  followupDestinationChars: 400,
  predictedNoteChars: 300,
} as const;

// ------------------------------------------------------------------ the model-facing input

/** One final per-doc disposition row (model-supplied). */
interface DreamReportInputRow {
  path: string;
  disposition: DreamDisposition;
  merge_target: string | null;
  rationale: string;
  /** Required non-empty exactly when the final disposition differs from the analyst proposal. */
  fallback_reason: string | null;
}

/** One selected curation unit (rank = input position; several units MAY share a node). */
interface DreamReportSelectedUnit {
  title: string;
  roadmap_node: string;
  docs: string[];
  rationale: string;
}

/** One overflow curation unit (rank = input position; carries no roadmap node). */
interface DreamReportOverflowUnit {
  title: string;
  docs: string[];
  rationale: string;
}

/** One harvest follow-up citing a SURVIVING destination (a keep/revise doc or its cluster). */
interface DreamReportFollowup {
  title: string;
  destination: string;
  pointer: string;
  evidence: string;
}

/** The model-supplied prediction — TYPE sanity only, deliberately no directional/quota rule. */
interface DreamReportPredictedEffectsInput {
  docs_after: number;
  bytes_after: number;
  note: string | null;
}

/** The untrusted, model-supplied input: ONLY the decisions the design assigns to the parent. */
interface DreamReportInput {
  rows: DreamReportInputRow[];
  uncertainties: string[];
  selected_units: DreamReportSelectedUnit[];
  overflow_units: DreamReportOverflowUnit[];
  harvest_followups: DreamReportFollowup[];
  predicted_effects: DreamReportPredictedEffectsInput;
}

/** The trusted, caller-supplied context the report is composed FROM — everything factual
 * (snapshot identity, coverage, analyst evidence, reducer stances, uncertainties, counters)
 * is injected from here, never accepted from the model. */
export interface DreamReportContext {
  manifest: DreamManifest;
  analyses: DreamLaneAnalysis[];
  reducers: DreamReducerAnalysis[];
  run_id: string;
  generated_at: string;
}

/**
 * The model-facing input schema (exported for the review path's param embedding — the
 * `DREAM_ANALYST_REPORT_SCHEMA` discipline): closed shape at every level, all fields required
 * (optional semantics via `null`), enums, every `maxItems`/`maxLength` read from the ONE
 * `DREAM_REPORT_CAPS` SSOT, no if/then, no `pattern` — the composed defensive validation
 * enforces everything the schema cannot (the single-line rule included).
 */
export const DREAM_REPORT_INPUT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "rows",
    "uncertainties",
    "selected_units",
    "overflow_units",
    "harvest_followups",
    "predicted_effects",
  ],
  properties: {
    rows: {
      type: "array",
      maxItems: DREAM_REPORT_CAPS.rows,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "disposition", "merge_target", "rationale", "fallback_reason"],
        properties: {
          path: { type: "string" },
          disposition: { type: "string", enum: [...DREAM_DISPOSITIONS] },
          merge_target: { type: ["string", "null"] },
          rationale: { type: "string", maxLength: DREAM_REPORT_CAPS.rowRationaleChars },
          fallback_reason: {
            type: ["string", "null"],
            maxLength: DREAM_REPORT_CAPS.fallbackReasonChars,
          },
        },
      },
    },
    uncertainties: {
      type: "array",
      maxItems: DREAM_REPORT_CAPS.uncertainties,
      items: { type: "string", maxLength: DREAM_REPORT_CAPS.uncertaintyChars },
    },
    selected_units: {
      type: "array",
      maxItems: DREAM_REPORT_CAPS.selectedUnits,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "roadmap_node", "docs", "rationale"],
        properties: {
          title: { type: "string", maxLength: DREAM_REPORT_CAPS.unitTitleChars },
          roadmap_node: { type: "string", maxLength: DREAM_REPORT_CAPS.unitNodeChars },
          docs: {
            type: "array",
            maxItems: DREAM_REPORT_CAPS.unitDocs,
            items: { type: "string" },
          },
          rationale: { type: "string", maxLength: DREAM_REPORT_CAPS.unitRationaleChars },
        },
      },
    },
    overflow_units: {
      type: "array",
      maxItems: DREAM_REPORT_CAPS.overflowUnits,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "docs", "rationale"],
        properties: {
          title: { type: "string", maxLength: DREAM_REPORT_CAPS.unitTitleChars },
          docs: {
            type: "array",
            maxItems: DREAM_REPORT_CAPS.unitDocs,
            items: { type: "string" },
          },
          rationale: { type: "string", maxLength: DREAM_REPORT_CAPS.unitRationaleChars },
        },
      },
    },
    harvest_followups: {
      type: "array",
      maxItems: DREAM_REPORT_CAPS.harvestFollowups,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "destination", "pointer", "evidence"],
        properties: {
          title: { type: "string", maxLength: DREAM_REPORT_CAPS.followupTitleChars },
          destination: {
            type: "string",
            maxLength: DREAM_REPORT_CAPS.followupDestinationChars,
          },
          pointer: { type: "string", maxLength: DREAM_REPORT_CAPS.followupPointerChars },
          evidence: { type: "string", maxLength: DREAM_REPORT_CAPS.followupEvidenceChars },
        },
      },
    },
    predicted_effects: {
      type: "object",
      additionalProperties: false,
      required: ["docs_after", "bytes_after", "note"],
      properties: {
        docs_after: { type: "integer", minimum: 0 },
        bytes_after: { type: "integer", minimum: 0 },
        note: { type: ["string", "null"], maxLength: DREAM_REPORT_CAPS.predictedNoteChars },
      },
    },
  },
};

// ------------------------------------------------------------------- the composed report

/** One injected reducer stance record, joined onto its doc's row (angle order). */
interface DreamReportStanceRecord {
  angle: DreamReducerAngle;
  stance: "endorse" | "challenge";
  reason: string;
  evidence_checked: string[];
}

/** One composed per-doc row: the model's final decision joined with the injected analyst
 * evidence and reducer stances (manifest lane/doc order). */
interface DreamReportRow {
  path: string;
  lane: string;
  cluster: string | null;
  analyst_disposition: DreamDisposition;
  analyst_merge_target: string | null;
  analyst_rationale: string;
  analyst_preserve: string[];
  analyst_evidence_checked: string[];
  analyst_confidence: "high" | "medium" | "low";
  final_disposition: DreamDisposition;
  final_merge_target: string | null;
  rationale: string;
  fallback_reason: string | null;
  stances: DreamReportStanceRecord[];
}

/** One analyst lane's coverage line (complete by construction — rendered for verification). */
interface DreamReportAnalystCoverage {
  lane: string;
  docs: number;
  overlap_signals_omitted: number;
  harvest_followups_omitted: number;
  uncertainties_omitted: number;
}

/** One reducer angle's coverage line. */
interface DreamReportReducerCoverage {
  angle: DreamReducerAngle;
  stances: number;
  stances_omitted: number;
  angle_findings_omitted: number;
  uncertainties_omitted: number;
}

/** The composed dream report — a plain JSON-serializable join of validated input with
 * injected trusted context. The renderer is a pure function of this value. */
export interface DreamReport {
  snapshot: {
    schema_version: string;
    run_id: string;
    generated_at: string;
    commit_sha: string;
    registry_mode: "clusters" | "categories";
    doc_count: number;
    total_bytes: number;
  };
  findings: {
    structural: { family: string; count: number }[];
    advisory: { family: string; count: number }[];
  };
  coverage: {
    analysts: DreamReportAnalystCoverage[];
    reducers: DreamReportReducerCoverage[];
  };
  rows: DreamReportRow[];
  uncertainties: {
    parent: string[];
    analysts: { lane: string; items: string[] }[];
    reducers: { angle: DreamReducerAngle; items: string[] }[];
  };
  reducer_findings: { angle: DreamReducerAngle; items: string[] }[];
  selected_units: DreamReportSelectedUnit[];
  overflow_units: DreamReportOverflowUnit[];
  harvest_followups: DreamReportFollowup[];
  predicted_effects: {
    docs_before: number;
    bytes_before: number;
    docs_after: number;
    bytes_after: number;
    note: string | null;
  };
}

// --------------------------------------------------------------------------- shared bits

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isDisposition(value: unknown): value is DreamDisposition {
  return typeof value === "string" && (DREAM_DISPOSITIONS as readonly string[]).includes(value);
}

/** Destructiveness levels for the downgrade-only rule — the two destructive dispositions
 * share a level and are INCOMPARABLE (a merge↔retire swap is never a downgrade). */
const DISPOSITION_LEVEL: Record<DreamDisposition, number> = {
  keep: 0,
  revise: 1,
  "merge-into": 2,
  retire: 2,
};

function isDestructive(disposition: DreamDisposition): boolean {
  return DISPOSITION_LEVEL[disposition] === 2;
}

/** Name the first line-structure violation in a model-supplied string, or null. The renderer
 * places these strings in table cells and bullets — line structure stays renderer-owned, so
 * `\r`/`\n` and every other C0 control character refuse with a named detail. */
function singleLineViolation(s: string): string | null {
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (cp < 0x20) {
      if (cp === 0x0a) return "a newline";
      if (cp === 0x0d) return "a carriage return";
      return `a C0 control character (U+${cp.toString(16).toUpperCase().padStart(4, "0")})`;
    }
  }
  return null;
}

/** `merge-into → docs/x.md` / `retire` — the proposal spelling used in named details. */
function describeProposal(disposition: DreamDisposition, target: string | null): string {
  return target === null ? disposition : `${disposition} → ${target}`;
}

type Refusal = { ok: false; details: string[] };

function refuse(detail: string): Refusal {
  return { ok: false, details: [detail] };
}

// ------------------------------------------------------------- the structural input decode

type StringField = { ok: true; value: string } | { ok: false; detail: string };

/** Decode one capped single-line model string (code-point cap + the single-line rule). */
function decodeReportString(value: unknown, maxChars: number | null, what: string): StringField {
  if (typeof value !== "string") {
    return { ok: false, detail: `${what} is not a string` };
  }
  if (maxChars !== null && codePointLength(value) > maxChars) {
    return { ok: false, detail: `${what} exceeds ${maxChars} code points` };
  }
  const violation = singleLineViolation(value);
  if (violation !== null) {
    return {
      ok: false,
      detail: `${what} contains ${violation} — model-supplied strings must be single-line`,
    };
  }
  return { ok: true, value };
}

/** Decode one capped array of single-line model strings. */
function decodeReportStringArray(
  raw: unknown,
  maxItems: number,
  maxChars: number | null,
  what: string,
): { ok: true; items: string[] } | { ok: false; detail: string } {
  if (!Array.isArray(raw)) {
    return { ok: false, detail: `${what} is not an array` };
  }
  if (raw.length > maxItems) {
    return { ok: false, detail: `${what} carries more than ${maxItems} items (${raw.length})` };
  }
  const items: string[] = [];
  for (const item of raw) {
    const decoded = decodeReportString(item, maxChars, `a ${what} item`);
    if (!decoded.ok) return decoded;
    items.push(decoded.value);
  }
  return { ok: true, items };
}

/**
 * The fail-fast structural decode (whitelisted construction — an extra input key never
 * survives; the first named detail wins): the schema-equivalent shape plus the code-enforced
 * caps and the single-line rule. Relational/semantic rules (path sets, downgrade-only, the
 * evidence bar, survival, partition, destinations) are collected afterwards — construction
 * cannot proceed over malformed input, so those misses fail fast here.
 */
function decodeDreamReportInput(
  raw: unknown,
): { ok: true; input: DreamReportInput } | { ok: false; detail: string } {
  if (!isRecord(raw)) {
    return { ok: false, detail: "dream report input is not an object" };
  }
  const caps = DREAM_REPORT_CAPS;

  if (!Array.isArray(raw.rows)) {
    return { ok: false, detail: "input rows is not an array" };
  }
  if (raw.rows.length > caps.rows) {
    return {
      ok: false,
      detail: `input rows carries more than ${caps.rows} rows (${raw.rows.length})`,
    };
  }
  const rows: DreamReportInputRow[] = [];
  for (const rawRow of raw.rows) {
    if (!isRecord(rawRow)) {
      return { ok: false, detail: "a disposition row is not an object" };
    }
    const path = decodeReportString(rawRow.path, null, "a disposition row path");
    if (!path.ok) return path;
    const what = `row '${path.value}'`;
    if (!isDisposition(rawRow.disposition)) {
      return {
        ok: false,
        detail: `${what} disposition ${JSON.stringify(rawRow.disposition)} is outside the vocabulary`,
      };
    }
    let mergeTarget: string | null = null;
    if (rawRow.merge_target !== null) {
      const decoded = decodeReportString(rawRow.merge_target, null, `${what} merge_target`);
      if (!decoded.ok) return decoded;
      mergeTarget = decoded.value;
    }
    const rationale = decodeReportString(
      rawRow.rationale,
      caps.rowRationaleChars,
      `${what} rationale`,
    );
    if (!rationale.ok) return rationale;
    let fallbackReason: string | null = null;
    if (rawRow.fallback_reason !== null) {
      const decoded = decodeReportString(
        rawRow.fallback_reason,
        caps.fallbackReasonChars,
        `${what} fallback_reason`,
      );
      if (!decoded.ok) return decoded;
      fallbackReason = decoded.value;
    }
    rows.push({
      path: path.value,
      disposition: rawRow.disposition,
      merge_target: mergeTarget,
      rationale: rationale.value,
      fallback_reason: fallbackReason,
    });
  }

  const uncertainties = decodeReportStringArray(
    raw.uncertainties,
    caps.uncertainties,
    caps.uncertaintyChars,
    "input uncertainties",
  );
  if (!uncertainties.ok) return uncertainties;

  if (!Array.isArray(raw.selected_units)) {
    return { ok: false, detail: "input selected_units is not an array" };
  }
  if (raw.selected_units.length > caps.selectedUnits) {
    return {
      ok: false,
      detail:
        `input selected_units carries more than ${caps.selectedUnits} units ` +
        `(${raw.selected_units.length})`,
    };
  }
  const selectedUnits: DreamReportSelectedUnit[] = [];
  for (const [index, rawUnit] of raw.selected_units.entries()) {
    const what = `selected unit ${index + 1}`;
    if (!isRecord(rawUnit)) {
      return { ok: false, detail: `${what} is not an object` };
    }
    const title = decodeReportString(rawUnit.title, caps.unitTitleChars, `${what} title`);
    if (!title.ok) return title;
    const node = decodeReportString(
      rawUnit.roadmap_node,
      caps.unitNodeChars,
      `${what} roadmap_node`,
    );
    if (!node.ok) return node;
    const docs = decodeReportStringArray(rawUnit.docs, caps.unitDocs, null, `${what} docs`);
    if (!docs.ok) return docs;
    const rationale = decodeReportString(
      rawUnit.rationale,
      caps.unitRationaleChars,
      `${what} rationale`,
    );
    if (!rationale.ok) return rationale;
    selectedUnits.push({
      title: title.value,
      roadmap_node: node.value,
      docs: docs.items,
      rationale: rationale.value,
    });
  }

  if (!Array.isArray(raw.overflow_units)) {
    return { ok: false, detail: "input overflow_units is not an array" };
  }
  if (raw.overflow_units.length > caps.overflowUnits) {
    return {
      ok: false,
      detail:
        `input overflow_units carries more than ${caps.overflowUnits} units ` +
        `(${raw.overflow_units.length})`,
    };
  }
  const overflowUnits: DreamReportOverflowUnit[] = [];
  for (const [index, rawUnit] of raw.overflow_units.entries()) {
    const what = `overflow unit ${index + 1}`;
    if (!isRecord(rawUnit)) {
      return { ok: false, detail: `${what} is not an object` };
    }
    const title = decodeReportString(rawUnit.title, caps.unitTitleChars, `${what} title`);
    if (!title.ok) return title;
    const docs = decodeReportStringArray(rawUnit.docs, caps.unitDocs, null, `${what} docs`);
    if (!docs.ok) return docs;
    const rationale = decodeReportString(
      rawUnit.rationale,
      caps.unitRationaleChars,
      `${what} rationale`,
    );
    if (!rationale.ok) return rationale;
    overflowUnits.push({ title: title.value, docs: docs.items, rationale: rationale.value });
  }

  if (!Array.isArray(raw.harvest_followups)) {
    return { ok: false, detail: "input harvest_followups is not an array" };
  }
  if (raw.harvest_followups.length > caps.harvestFollowups) {
    return {
      ok: false,
      detail:
        `input harvest_followups carries more than ${caps.harvestFollowups} follow-ups ` +
        `(${raw.harvest_followups.length})`,
    };
  }
  const harvestFollowups: DreamReportFollowup[] = [];
  for (const [index, rawFollowup] of raw.harvest_followups.entries()) {
    const what = `harvest follow-up ${index + 1}`;
    if (!isRecord(rawFollowup)) {
      return { ok: false, detail: `${what} is not an object` };
    }
    const title = decodeReportString(rawFollowup.title, caps.followupTitleChars, `${what} title`);
    if (!title.ok) return title;
    const destination = decodeReportString(
      rawFollowup.destination,
      caps.followupDestinationChars,
      `${what} destination`,
    );
    if (!destination.ok) return destination;
    const pointer = decodeReportString(
      rawFollowup.pointer,
      caps.followupPointerChars,
      `${what} pointer`,
    );
    if (!pointer.ok) return pointer;
    const evidence = decodeReportString(
      rawFollowup.evidence,
      caps.followupEvidenceChars,
      `${what} evidence`,
    );
    if (!evidence.ok) return evidence;
    harvestFollowups.push({
      title: title.value,
      destination: destination.value,
      pointer: pointer.value,
      evidence: evidence.value,
    });
  }

  if (!isRecord(raw.predicted_effects)) {
    return { ok: false, detail: "input predicted_effects is not an object" };
  }
  const effects = raw.predicted_effects;
  if (!nonNegativeInteger(effects.docs_after)) {
    return { ok: false, detail: "predicted_effects docs_after is not a non-negative integer" };
  }
  if (!nonNegativeInteger(effects.bytes_after)) {
    return { ok: false, detail: "predicted_effects bytes_after is not a non-negative integer" };
  }
  let note: string | null = null;
  if (effects.note !== null) {
    const decoded = decodeReportString(
      effects.note,
      caps.predictedNoteChars,
      "predicted_effects note",
    );
    if (!decoded.ok) return decoded;
    note = decoded.value;
  }

  return {
    ok: true,
    input: {
      rows,
      uncertainties: uncertainties.items,
      selected_units: selectedUnits,
      overflow_units: overflowUnits,
      harvest_followups: harvestFollowups,
      predicted_effects: {
        docs_after: effects.docs_after,
        bytes_after: effects.bytes_after,
        note,
      },
    },
  };
}

// --------------------------------------------------------------- the context re-verification

/**
 * Re-verify the trusted context BEFORE any input judgment: a report can only be built from
 * COMPLETE waves — `analyses` must cover the manifest's lanes exactly (one per lane, manifest
 * order, each covering its lane's docs exactly) and `reducers` must carry exactly the three
 * `DREAM_REDUCER_ANGLES` in fixed order. Incomplete coverage is never described as complete.
 */
function contextViolation(context: DreamReportContext): string | null {
  if (typeof context.run_id !== "string" || context.run_id === "") {
    return "context run_id must be a non-empty string";
  }
  if (singleLineViolation(context.run_id) !== null) {
    return "context run_id must be a single-line string";
  }
  if (typeof context.generated_at !== "string" || context.generated_at === "") {
    return "context generated_at must be a non-empty string";
  }
  if (singleLineViolation(context.generated_at) !== null) {
    return "context generated_at must be a single-line string";
  }
  const expectedLanes = context.manifest.lanes.map((lane) => lane.id);
  const gotLanes = context.analyses.map((analysis) => analysis.lane);
  if (
    expectedLanes.length !== gotLanes.length ||
    expectedLanes.some((id, i) => id !== gotLanes[i])
  ) {
    return (
      "context analyses must cover the manifest's lanes exactly in manifest order " +
      `(expected: ${expectedLanes.join(", ")}; got: ${gotLanes.join(", ") || "none"})`
    );
  }
  for (const [index, lane] of context.manifest.lanes.entries()) {
    const analysis = context.analyses[index] as DreamLaneAnalysis;
    const expectedDocs = lane.docs.map((doc) => doc.path);
    const gotDocs = analysis.report.docs.map((doc) => doc.path);
    if (expectedDocs.length !== gotDocs.length || expectedDocs.some((p, i) => p !== gotDocs[i])) {
      return `context analysis for lane '${lane.id}' does not cover the lane's docs exactly`;
    }
  }
  const gotAngles = context.reducers.map((reducer) => reducer.angle);
  if (
    gotAngles.length !== DREAM_REDUCER_ANGLES.length ||
    DREAM_REDUCER_ANGLES.some((angle, i) => angle !== gotAngles[i])
  ) {
    return (
      "context reducers must carry exactly the three reducer angles in fixed order " +
      `(expected: ${DREAM_REDUCER_ANGLES.join(", ")}; got: ${gotAngles.join(", ") || "none"})`
    );
  }
  return null;
}

// ------------------------------------------------------------------------- the validation

/** The gate angles whose explicit endorsement a destructive final row requires. */
const EVIDENCE_BAR_GATE_ANGLES: readonly DreamReducerAngle[] = [
  "consolidation-preservation",
  "currency-accuracy",
];

interface JoinedRow {
  input: DreamReportInputRow;
  analyst: DreamDocAssessment;
  /** The downgrade rule passed — later phases (evidence bar, survival) only run then. */
  downgradeOk: boolean;
}

/**
 * Validate the model-supplied input against the pinned curation policy and compose the full
 * typed `DreamReport` by joining it with the injected trusted context. Two-stage error
 * reporting (the interactive-redraft deviation from the fail-fast decoder posture): context
 * re-verification and structural decode fail FAST (first named detail, one-element `details`);
 * the semantic rules collect up to `DREAM_REPORT_MAX_VALIDATION_DETAILS` named details in
 * deterministic order (validation phase order, then manifest doc order within a phase),
 * overflow appending one final synthetic detail counting the omitted violations.
 * Module-private: `buildDreamReport` is the one entry — the whole matrix is exercised
 * through it.
 */
function validateDreamReport(
  input: unknown,
  context: DreamReportContext,
): { ok: true; report: DreamReport } | Refusal {
  const contextDetail = contextViolation(context);
  if (contextDetail !== null) return refuse(contextDetail);
  const decoded = decodeDreamReportInput(input);
  if (!decoded.ok) return refuse(decoded.detail);
  const typed = decoded.input;

  const manifest = context.manifest;
  const manifestPaths: string[] = manifest.lanes.flatMap((lane) =>
    lane.docs.map((doc) => doc.path),
  );
  const corpusSet = new Set(manifestPaths);
  const assessmentByPath = new Map<string, DreamDocAssessment>();
  for (const analysis of context.analyses) {
    for (const doc of analysis.report.docs) assessmentByPath.set(doc.path, doc);
  }

  const details: string[] = [];

  // Phase 1 — exact path-set equality: no duplicate, no extra, no missing rows.
  const rowByPath = new Map<string, DreamReportInputRow>();
  for (const row of typed.rows) {
    if (rowByPath.has(row.path)) {
      details.push(`duplicate disposition row for '${row.path}'`);
      continue;
    }
    if (!corpusSet.has(row.path)) {
      details.push(`disposition row path '${row.path}' is not an authored doc in the manifest`);
      continue;
    }
    rowByPath.set(row.path, row);
  }
  for (const path of manifestPaths) {
    if (!rowByPath.has(path)) {
      details.push(`missing disposition row for authored doc '${path}'`);
    }
  }

  // Phase 2 — per-row rules in manifest doc order: rationale non-empty, the
  // merge-target shape, downgrade-only against the analyst proposal, the fallback rule.
  const joined = new Map<string, JoinedRow>();
  for (const path of manifestPaths) {
    const row = rowByPath.get(path);
    if (row === undefined) continue;
    const analyst = assessmentByPath.get(path) as DreamDocAssessment;
    const state: JoinedRow = { input: row, analyst, downgradeOk: true };
    joined.set(path, state);
    if (row.rationale === "") {
      details.push(`row '${path}' rationale must be non-empty`);
    }
    if (row.disposition === "merge-into") {
      if (row.merge_target === null) {
        details.push(`row '${path}' has disposition 'merge-into' but a null merge_target`);
        state.downgradeOk = false;
        continue;
      }
    } else if (row.merge_target !== null) {
      details.push(
        `row '${path}' carries a merge_target on a '${row.disposition}' disposition (must be null)`,
      );
      state.downgradeOk = false;
      continue;
    }
    // Downgrade-only: final level ≤ analyst level; a destructive final must match the analyst
    // proposal EXACTLY (same disposition AND byte-identical merge_target — the reducers
    // stanced that specific proposal; anything else is an unendorsed new action).
    if (isDestructive(row.disposition)) {
      if (!isDestructive(analyst.disposition)) {
        details.push(
          `row '${path}' escalates the analyst proposal '${analyst.disposition}' to ` +
            `'${row.disposition}' — the parent never resolves upward`,
        );
        state.downgradeOk = false;
      } else if (
        row.disposition !== analyst.disposition ||
        row.merge_target !== analyst.merge_target
      ) {
        details.push(
          `row '${path}' final '${describeProposal(row.disposition, row.merge_target)}' does ` +
            `not match the analyst proposal ` +
            `'${describeProposal(analyst.disposition, analyst.merge_target)}' exactly — an ` +
            "unendorsed destructive action is refused (downgrade to 'revise' or 'keep' with a " +
            "fallback_reason instead)",
        );
        state.downgradeOk = false;
      }
    } else if (row.disposition === "revise" && analyst.disposition === "keep") {
      details.push(
        `row '${path}' escalates the analyst proposal 'keep' to 'revise' — the parent never ` +
          "resolves upward",
      );
      state.downgradeOk = false;
    }
    if (!state.downgradeOk) continue;
    const changed = row.disposition !== analyst.disposition;
    if (changed && (row.fallback_reason === null || row.fallback_reason === "")) {
      details.push(
        `row '${path}' departs from the analyst proposal ('${analyst.disposition}' → ` +
          `'${row.disposition}') and requires a non-empty fallback_reason`,
      );
    } else if (!changed && row.fallback_reason !== null) {
      details.push(
        `row '${path}' matches the analyst proposal and must carry fallback_reason: null`,
      );
    }
  }

  // Phase 3 — the destructive evidence bar, computed ONLY from context stances: an
  // explicit endorse from BOTH gate angles and no challenge from ANY angle; silence counts as
  // non-endorsement. The bar is necessary, not sufficient — an eligible proposal MAY still be
  // downgraded by parent judgment.
  const stancesByDoc = new Map<string, DreamReportStanceRecord[]>();
  for (const reducer of context.reducers) {
    for (const stance of reducer.report.stances) {
      const records = stancesByDoc.get(stance.doc) ?? [];
      records.push({
        angle: reducer.angle,
        stance: stance.stance,
        reason: stance.reason,
        evidence_checked: stance.evidence_checked,
      });
      stancesByDoc.set(stance.doc, records);
    }
  }
  for (const path of manifestPaths) {
    const state = joined.get(path);
    if (state === undefined || !state.downgradeOk) continue;
    if (!isDestructive(state.input.disposition)) continue;
    const records = stancesByDoc.get(path) ?? [];
    const blockers: string[] = [];
    for (const gate of EVIDENCE_BAR_GATE_ANGLES) {
      const endorsed = records.some((r) => r.angle === gate && r.stance === "endorse");
      if (!endorsed) blockers.push(`no '${gate}' endorsement (silence is non-endorsement)`);
    }
    for (const record of records) {
      if (record.stance === "challenge") blockers.push(`a '${record.angle}' challenge`);
    }
    if (blockers.length > 0) {
      details.push(
        `destructive row '${path}' ('${state.input.disposition}') fails the evidence bar: ` +
          `${blockers.join("; ")} — the only legal moves are downgrading to 'revise' or ` +
          "'keep' with a fallback_reason",
      );
    }
  }

  // Phase 4 — merge-target existence + survival over FINAL dispositions. Survival
  // structurally forbids merge chains and cycles (a merge-into doc can never be a target).
  for (const path of manifestPaths) {
    const state = joined.get(path);
    if (state === undefined || !state.downgradeOk) continue;
    if (state.input.disposition !== "merge-into") continue;
    const target = state.input.merge_target as string;
    if (!corpusSet.has(target)) {
      details.push(`row '${path}' merge_target '${target}' is not a member of the manifest corpus`);
      continue;
    }
    const targetRow = rowByPath.get(target);
    if (targetRow === undefined) continue; // the missing-row detail already covers the target
    if (targetRow.disposition !== "keep" && targetRow.disposition !== "revise") {
      details.push(
        `row '${path}' merge_target '${target}' does not survive (final disposition ` +
          `'${targetRow.disposition}') — a merge target must end keep or revise`,
      );
    }
  }

  // Phase 5 — curation units: corpus membership, no doc in two units, no empty unit, no
  // final-keep doc in a unit, the exact partition over the final non-keep set, non-empty
  // roadmap nodes, and the ≤12-distinct-node cap (many-to-one node mapping is allowed).
  const claimedBy = new Set<string>();
  const allUnits: { what: string; docs: string[] }[] = [
    ...typed.selected_units.map((unit, i) => ({
      what: `selected unit ${i + 1} ('${unit.title}')`,
      docs: unit.docs,
    })),
    ...typed.overflow_units.map((unit, i) => ({
      what: `overflow unit ${i + 1} ('${unit.title}')`,
      docs: unit.docs,
    })),
  ];
  for (const unit of allUnits) {
    if (unit.docs.length === 0) {
      details.push(`${unit.what} has no docs — empty units are refused`);
    }
    for (const doc of unit.docs) {
      if (!corpusSet.has(doc)) {
        details.push(`${unit.what} doc '${doc}' is not a member of the manifest corpus`);
        continue;
      }
      if (claimedBy.has(doc)) {
        details.push(`doc '${doc}' appears in more than one curation unit`);
        continue;
      }
      claimedBy.add(doc);
      const row = rowByPath.get(doc);
      if (row !== undefined && row.disposition === "keep") {
        details.push(
          `${unit.what} doc '${doc}' has final disposition 'keep' — final-keep docs appear ` +
            "in no unit",
        );
      }
    }
  }
  for (const path of manifestPaths) {
    const row = rowByPath.get(path);
    if (row === undefined || row.disposition === "keep") continue;
    if (!claimedBy.has(path)) {
      details.push(
        `non-keep doc '${path}' is not covered by any curation unit — selected + overflow ` +
          "units must partition the non-keep docs exactly",
      );
    }
  }
  const distinctNodes = new Set<string>();
  for (const [index, unit] of typed.selected_units.entries()) {
    if (unit.roadmap_node === "") {
      details.push(`selected unit ${index + 1} ('${unit.title}') roadmap_node must be non-empty`);
      continue;
    }
    distinctNodes.add(unit.roadmap_node);
  }
  if (distinctNodes.size > DREAM_REPORT_MAX_ROADMAP_NODES) {
    details.push(
      `selected units name ${distinctNodes.size} distinct roadmap nodes — the cap is ` +
        `${DREAM_REPORT_MAX_ROADMAP_NODES}`,
    );
  }

  // Phase 6 — harvest follow-ups cite SURVIVING destinations: a keep/revise corpus doc,
  // or a cluster named by at least one keep/revise doc.
  const survivingDocs = new Set<string>();
  for (const path of manifestPaths) {
    const row = rowByPath.get(path);
    if (row !== undefined && (row.disposition === "keep" || row.disposition === "revise")) {
      survivingDocs.add(path);
    }
  }
  const allClusters = new Set<string>();
  const survivingClusters = new Set<string>();
  for (const lane of manifest.lanes) {
    for (const doc of lane.docs) {
      if (doc.cluster === null) continue;
      allClusters.add(doc.cluster);
      if (survivingDocs.has(doc.path)) survivingClusters.add(doc.cluster);
    }
  }
  for (const [index, followup] of typed.harvest_followups.entries()) {
    const what = `harvest follow-up ${index + 1} ('${followup.title}')`;
    if (followup.pointer === "") {
      details.push(`${what} pointer must be non-empty`);
    }
    if (corpusSet.has(followup.destination)) {
      if (!survivingDocs.has(followup.destination)) {
        const row = rowByPath.get(followup.destination);
        details.push(
          `${what} destination '${followup.destination}' is a corpus doc that does not ` +
            `survive (final disposition '${row?.disposition ?? "missing"}') — repoint the ` +
            "follow-up at a survivor",
        );
      }
    } else if (allClusters.has(followup.destination)) {
      if (!survivingClusters.has(followup.destination)) {
        details.push(
          `${what} destination '${followup.destination}' is a cluster with no surviving ` +
            "keep/revise member",
        );
      }
    } else {
      details.push(
        `${what} destination '${followup.destination}' is neither a surviving corpus doc ` +
          "nor a cluster named by a surviving doc",
      );
    }
  }

  // Phase 7 — predicted effects carry deliberately NO directional/quota rule: a growth
  // prediction is valid (type sanity was structural).

  if (details.length > 0) {
    if (details.length > DREAM_REPORT_MAX_VALIDATION_DETAILS) {
      const omitted = details.length - DREAM_REPORT_MAX_VALIDATION_DETAILS;
      return {
        ok: false,
        details: [
          ...details.slice(0, DREAM_REPORT_MAX_VALIDATION_DETAILS),
          `…and ${omitted} more validation detail(s) omitted ` +
            `(cap ${DREAM_REPORT_MAX_VALIDATION_DETAILS})`,
        ],
      };
    }
    return { ok: false, details };
  }

  // Compose — whitelisted construction, manifest lane/doc order throughout.
  const rows: DreamReportRow[] = [];
  for (const lane of manifest.lanes) {
    for (const doc of lane.docs) {
      const state = joined.get(doc.path) as JoinedRow;
      rows.push({
        path: doc.path,
        lane: lane.id,
        cluster: doc.cluster,
        analyst_disposition: state.analyst.disposition,
        analyst_merge_target: state.analyst.merge_target,
        analyst_rationale: state.analyst.rationale,
        analyst_preserve: state.analyst.preserve,
        analyst_evidence_checked: state.analyst.evidence_checked,
        analyst_confidence: state.analyst.confidence,
        final_disposition: state.input.disposition,
        final_merge_target: state.input.merge_target,
        rationale: state.input.rationale,
        fallback_reason: state.input.fallback_reason,
        stances: stancesByDoc.get(doc.path) ?? [],
      });
    }
  }
  const report: DreamReport = {
    snapshot: {
      schema_version: DREAM_REPORT_SCHEMA_VERSION,
      run_id: context.run_id,
      generated_at: context.generated_at,
      commit_sha: manifest.commit_sha,
      registry_mode: manifest.registry_mode,
      doc_count: manifest.doc_count,
      total_bytes: manifest.total_bytes,
    },
    findings: {
      structural: [
        { family: "stale_pointers", count: manifest.findings.structural.stale_pointers.length },
        {
          family: "broken_doc_paths",
          count: manifest.findings.structural.broken_doc_paths.length,
        },
        { family: "duplicate_cues", count: manifest.findings.structural.duplicate_cues.length },
        {
          family: "missing_frontmatter",
          count: manifest.findings.structural.missing_frontmatter.length,
        },
      ],
      advisory: [
        {
          family: "distillation_issues",
          count: manifest.findings.advisory.distillation_issues.length,
        },
        {
          family: "source_code_blocks",
          count: manifest.findings.advisory.source_code_blocks.length,
        },
        { family: "overlong_cues", count: manifest.findings.advisory.overlong_cues.length },
        { family: "cue_hazards", count: manifest.findings.advisory.cue_hazards.length },
        { family: "empty_clusters", count: manifest.findings.advisory.empty_clusters.length },
      ],
    },
    coverage: {
      analysts: manifest.lanes.map((lane, index) => {
        const analysis = context.analyses[index] as DreamLaneAnalysis;
        return {
          lane: lane.id,
          docs: lane.docs.length,
          overlap_signals_omitted: analysis.report.overlap_signals_omitted,
          harvest_followups_omitted: analysis.report.harvest_followups_omitted,
          uncertainties_omitted: analysis.report.uncertainties_omitted,
        };
      }),
      reducers: context.reducers.map((reducer) => ({
        angle: reducer.angle,
        stances: reducer.report.stances.length,
        stances_omitted: reducer.report.stances_omitted,
        angle_findings_omitted: reducer.report.angle_findings_omitted,
        uncertainties_omitted: reducer.report.uncertainties_omitted,
      })),
    },
    rows,
    uncertainties: {
      parent: typed.uncertainties,
      analysts: context.analyses.map((analysis) => ({
        lane: analysis.lane,
        items: analysis.report.uncertainties,
      })),
      reducers: context.reducers.map((reducer) => ({
        angle: reducer.angle,
        items: reducer.report.uncertainties,
      })),
    },
    reducer_findings: context.reducers.map((reducer) => ({
      angle: reducer.angle,
      items: reducer.report.angle_findings,
    })),
    selected_units: typed.selected_units,
    overflow_units: typed.overflow_units,
    harvest_followups: typed.harvest_followups,
    predicted_effects: {
      docs_before: manifest.doc_count,
      bytes_before: manifest.total_bytes,
      docs_after: typed.predicted_effects.docs_after,
      bytes_after: typed.predicted_effects.bytes_after,
      note: typed.predicted_effects.note,
    },
  };
  return { ok: true, report };
}

// --------------------------------------------------------------------------- the renderer

/** One packable Markdown block: same-group consecutive blocks join with `\n` (consecutive
 * table or bullet lines); a table-row block carries its table's header for re-emission after
 * a mid-table split (`null` for non-table groups — bullet lines split without re-emission). */
interface RenderBlock {
  text: string;
  groupId: number | null;
  tableHeader: string | null;
}

/** Deterministic table-cell/bullet sanitization: `|` escaped, internal newline runs collapsed
 * to a single space — injected (analyst/reducer) prose may carry newlines/pipes; model strings
 * are single-line by validation, so the collapse is idempotent for them. Line structure stays
 * renderer-owned; the typed report retains the exact strings. */
function sanitize(s: string): string {
  return s.replace(/\|/g, "\\|").replace(/[\r\n]+/g, " ");
}

/** `a; b; c` or an em-dash for an empty list (inside a table cell or bullet). */
function joinOrDash(items: string[]): string {
  return items.length === 0 ? "—" : items.map(sanitize).join("; ");
}

/**
 * Render the composed report to CANONICAL Markdown bytes in parts — a pure function of the
 * report (no clock, no locale, no environment): an ordered stream of blocks greedily packed
 * under `DREAM_REPORT_PART_MAX_CHARS − DREAM_REPORT_PART_HEADER_RESERVE` code points, splits
 * only at block boundaries (bullet-list sections pack per bullet line, so a block group
 * splits at line boundaries), a table split re-emitting the table header row in the next part,
 * every part prefixed with its header after packing. A single block exceeding the budget is a
 * defensive refusal (structurally unreachable under the caps arithmetic — named, never
 * truncated).
 * Module-private: `buildDreamReport` is the one entry (it returns both the typed report and
 * the rendered parts).
 */
function renderDreamReport(
  report: DreamReport,
): { ok: true; parts: string[] } | { ok: false; detail: string } {
  const blocks: RenderBlock[] = [];
  let nextGroupId = 0;
  const push = (text: string): void => {
    blocks.push({ text, groupId: null, tableHeader: null });
  };
  /** Push each line as its own block sharing ONE fresh group: unsplit output joins with `\n`
   * (byte-identical to a single joined block); an oversized section splits at line
   * boundaries with no header re-emission. */
  const pushLines = (lines: string[]): void => {
    const groupId = nextGroupId;
    nextGroupId += 1;
    for (const line of lines) {
      blocks.push({ text: line, groupId, tableHeader: null });
    }
  };
  const pushTable = (headerCells: string[], rows: string[][]): void => {
    const groupId = nextGroupId;
    nextGroupId += 1;
    const header =
      `| ${headerCells.join(" | ")} |\n` + `| ${headerCells.map(() => "---").join(" | ")} |`;
    blocks.push({ text: header, groupId, tableHeader: null });
    for (const row of rows) {
      blocks.push({
        text: `| ${row.map(sanitize).join(" | ")} |`,
        groupId,
        tableHeader: header,
      });
    }
  };
  const stanceBullets = (stances: DreamReportStanceRecord[]): string =>
    stances.length === 0
      ? "- No reducer stances recorded (silence is non-endorsement)."
      : stances
          .map(
            (s) =>
              `- ${s.angle}: ${s.stance} — ${sanitize(s.reason)} ` +
              `(checked: ${joinOrDash(s.evidence_checked)})`,
          )
          .join("\n");

  // 1 — Snapshot.
  push("## Snapshot");
  push(
    [
      `- Run: ${sanitize(report.snapshot.run_id)}`,
      `- Report schema version: ${sanitize(report.snapshot.schema_version)}`,
      `- Commit: ${sanitize(report.snapshot.commit_sha)}`,
      `- Generated at: ${sanitize(report.snapshot.generated_at)}`,
      `- Registry mode: ${report.snapshot.registry_mode}`,
      `- Docs: ${report.snapshot.doc_count}`,
      `- Total bytes: ${report.snapshot.total_bytes}`,
    ].join("\n"),
  );

  // 2 — Findings summary.
  push("## Findings summary");
  pushTable(
    ["Family", "Count"],
    [
      ...report.findings.structural.map((f) => [`structural.${f.family}`, String(f.count)]),
      ...report.findings.advisory.map((f) => [`advisory.${f.family}`, String(f.count)]),
    ],
  );

  // 3 — Wave coverage (complete by construction; rendered so a reviewer can verify it).
  push("## Wave coverage");
  push("### Analyst lanes");
  pushTable(
    [
      "Lane",
      "Docs",
      "Overlap signals omitted",
      "Harvest follow-ups omitted",
      "Uncertainties omitted",
    ],
    report.coverage.analysts.map((c) => [
      c.lane,
      String(c.docs),
      String(c.overlap_signals_omitted),
      String(c.harvest_followups_omitted),
      String(c.uncertainties_omitted),
    ]),
  );
  push("### Reducer angles");
  pushTable(
    ["Angle", "Stances", "Stances omitted", "Angle findings omitted", "Uncertainties omitted"],
    report.coverage.reducers.map((c) => [
      c.angle,
      String(c.stances),
      String(c.stances_omitted),
      String(c.angle_findings_omitted),
      String(c.uncertainties_omitted),
    ]),
  );

  // 4 — Dispositions: ONE table, one row per authored doc in manifest order.
  push("## Dispositions");
  pushTable(
    ["Doc", "Cluster", "Analyst", "Final", "Merge target", "Confidence", "Rationale"],
    report.rows.map((row) => [
      row.path,
      row.cluster ?? "—",
      describeProposal(row.analyst_disposition, row.analyst_merge_target),
      row.final_disposition,
      row.final_merge_target ?? "—",
      row.analyst_confidence,
      row.rationale,
    ]),
  );

  // 5 — Non-keep evidence: one subsection per FINAL non-keep doc (manifest order) — the
  // injected analyst evidence plus every injected reducer stance for that doc's proposal.
  push("## Non-keep evidence");
  const nonKeepRows = report.rows.filter((row) => row.final_disposition !== "keep");
  if (nonKeepRows.length === 0) {
    push("_None._");
  }
  for (const row of nonKeepRows) {
    push(`### ${row.path}`);
    push(
      [
        `- Analyst rationale: ${sanitize(row.analyst_rationale)}`,
        `- Preserve: ${joinOrDash(row.analyst_preserve)}`,
        `- Evidence checked: ${joinOrDash(row.analyst_evidence_checked)}`,
      ].join("\n"),
    );
    push(stanceBullets(row.stances));
  }

  // 6 — Fallbacks: the recorded non-destructive departures, rendered directly from the rows
  // carrying a non-null fallback_reason (manifest order). A fallback doc whose final is keep
  // renders its injected stances HERE (its proposal never reaches §5), so every reducer
  // stance renders exactly once — §5 (final non-keep) or §6 (final keep).
  push("## Fallbacks");
  const fallbackRows = report.rows.filter((row) => row.fallback_reason !== null);
  if (fallbackRows.length === 0) {
    push("_None._");
  }
  for (const row of fallbackRows) {
    push(`### ${row.path}`);
    push(
      [
        `- Analyst proposal: ${sanitize(
          describeProposal(row.analyst_disposition, row.analyst_merge_target),
        )}`,
        `- Final: ${row.final_disposition}`,
        `- Reason: ${sanitize(row.fallback_reason as string)}`,
      ].join("\n"),
    );
    if (row.final_disposition === "keep") {
      push(stanceBullets(row.stances));
    }
  }

  // 7 — Uncertainties, labeled by source: the parent's input first, then the injected
  // analyst (by lane) and reducer (by angle) uncertainties.
  push("## Uncertainties");
  const uncertaintyLines: string[] = [
    ...report.uncertainties.parent.map((item) => `- Parent: ${sanitize(item)}`),
    ...report.uncertainties.analysts.flatMap((entry) =>
      entry.items.map((item) => `- Analyst ${sanitize(entry.lane)}: ${sanitize(item)}`),
    ),
    ...report.uncertainties.reducers.flatMap((entry) =>
      entry.items.map((item) => `- Reducer ${entry.angle}: ${sanitize(item)}`),
    ),
  ];
  if (uncertaintyLines.length === 0) {
    push("_None._");
  } else {
    pushLines(uncertaintyLines);
  }

  // 8 — Reducer findings: the injected per-angle `angle_findings` (bounded cross-corpus
  // value — a deliberate minor addition beyond the node's section list).
  push("## Reducer findings");
  const findingLines: string[] = report.reducer_findings.flatMap((entry) =>
    entry.items.map((item) => `- ${entry.angle}: ${sanitize(item)}`),
  );
  if (findingLines.length === 0) {
    push("_None._");
  } else {
    pushLines(findingLines);
  }

  // 9 — Selected curation units (rank = position).
  push("## Selected curation units");
  if (report.selected_units.length === 0) {
    push("_None._");
  }
  for (const [index, unit] of report.selected_units.entries()) {
    push(
      [
        `**${index + 1}. ${sanitize(unit.title)}** — node \`${sanitize(unit.roadmap_node)}\``,
        `- Docs: ${joinOrDash(unit.docs)}`,
        `- Rationale: ${sanitize(unit.rationale)}`,
      ].join("\n"),
    );
  }

  // 10 — Overflow (rank = position, no node).
  push("## Overflow");
  if (report.overflow_units.length === 0) {
    push("_None._");
  }
  for (const [index, unit] of report.overflow_units.entries()) {
    push(
      [
        `**${index + 1}. ${sanitize(unit.title)}**`,
        `- Docs: ${joinOrDash(unit.docs)}`,
        `- Rationale: ${sanitize(unit.rationale)}`,
      ].join("\n"),
    );
  }

  // 11 — Harvest follow-ups.
  push("## Harvest follow-ups");
  if (report.harvest_followups.length === 0) {
    push("_None._");
  } else {
    pushTable(
      ["Title", "Destination", "Pointer", "Evidence"],
      report.harvest_followups.map((f) => [f.title, f.destination, f.pointer, f.evidence]),
    );
  }

  // 12 — Predicted effects (with the explicit not-quotas line).
  push("## Predicted effects");
  push(
    [
      `- Docs: ${report.predicted_effects.docs_before} → ${report.predicted_effects.docs_after}`,
      `- Bytes: ${report.predicted_effects.bytes_before} → ` +
        `${report.predicted_effects.bytes_after}`,
      `- Note: ${report.predicted_effects.note === null ? "—" : sanitize(report.predicted_effects.note)}`,
    ].join("\n"),
  );
  push("_Predictions are not quotas._");

  // Greedy block packing under the reserve-adjusted budget.
  const budget = DREAM_REPORT_PART_MAX_CHARS - DREAM_REPORT_PART_HEADER_RESERVE;
  const oversize = (length: number): { ok: false; detail: string } => ({
    ok: false,
    detail:
      `a single rendered block of ${length} code points exceeds the part packing budget ` +
      `(${budget}) — refusing to truncate`,
  });
  const bodies: string[] = [];
  let current = "";
  let prevGroupId: number | null = null;
  for (const block of blocks) {
    if (current === "") {
      const length = codePointLength(block.text);
      if (length > budget) return oversize(length);
      current = block.text;
    } else {
      const separator = block.groupId !== null && block.groupId === prevGroupId ? "\n" : "\n\n";
      const candidate = current + separator + block.text;
      if (codePointLength(candidate) <= budget) {
        current = candidate;
      } else {
        bodies.push(current);
        const opener =
          block.tableHeader === null ? block.text : `${block.tableHeader}\n${block.text}`;
        const length = codePointLength(opener);
        if (length > budget) return oversize(length);
        current = opener;
      }
    }
    prevGroupId = block.groupId;
  }
  if (current !== "") bodies.push(current);

  const total = bodies.length;
  const parts = bodies.map((body, index) => {
    const header =
      index === 0
        ? `# Dream report — ${report.snapshot.run_id}`
        : `# Dream report — ${report.snapshot.run_id} (continued, part ${index + 1} of ${total})`;
    return `${header}\n\n${body}\n`;
  });
  for (const part of parts) {
    const length = codePointLength(part);
    if (length > DREAM_REPORT_PART_MAX_CHARS) {
      // Defensive: reachable only when the run id outgrows the fixed header reserve.
      return {
        ok: false,
        detail:
          `a rendered part of ${length} code points exceeds the part cap ` +
          `(${DREAM_REPORT_PART_MAX_CHARS}) — refusing to truncate`,
      };
    }
  }
  return { ok: true, parts };
}

// ------------------------------------------------------------------------ the entry point

/**
 * Validate, compose, render, and enforce the part budget in ONE call — the draft path
 * validates BEFORE review, so an approved report is always savable. `validateDreamReport`'s
 * two-stage `details` shape passes through; the renderer's single-detail defensive arm is
 * wrapped into a one-element `details`.
 */
export function buildDreamReport(
  input: unknown,
  context: DreamReportContext,
): { ok: true; report: DreamReport; parts: string[] } | Refusal {
  const validated = validateDreamReport(input, context);
  if (!validated.ok) return validated;
  const rendered = renderDreamReport(validated.report);
  if (!rendered.ok) return refuse(rendered.detail);
  return { ok: true, report: validated.report, parts: rendered.parts };
}
