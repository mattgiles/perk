// The dream report module's suite (the dream/dreamReducer matrix shape), exercised entirely
// through the ONE exported entry (`buildDreamReport` — it returns both the typed report and
// the rendered parts, and its Refusal shape carries the validator's details): the schema↔caps
// lockstep + the single-line rule + code-point cap measurement, the context
// re-verification refusals (complete waves only), the fail-fast structural decode, the
// collected semantic rules (path-set equality, downgrade-only, the destructive evidence bar,
// merge-target survival/acyclicity, the exact unit partition + node cap, surviving follow-up
// destinations, no-quota predicted effects), the two-stage bounded error collection, and the
// deterministic renderer (byte equality, the pinned full-fixture snapshot, part splitting
// with table-header re-emission, sanitization, the oversize defensive arm). The module's
// caps/constants are private: this suite pins them through the local `CAPS`/threshold mirrors
// (the schema lockstep + the rendered refusal details keep the mirrors honest). Fully offline.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  codePointLength,
  DREAM_DISPOSITIONS,
  type DreamDisposition,
  type DreamDocAssessment,
  type DreamLaneAnalysis,
  type DreamManifest,
  decodeDreamManifest,
} from "./dream.ts";
import {
  DREAM_REDUCER_ANGLES,
  type DreamReducerAnalysis,
  type DreamReducerAngle,
  type DreamStance,
  type DreamStanceDisposition,
} from "./dreamReducer.ts";
import {
  buildDreamReport,
  DREAM_REPORT_INPUT_SCHEMA,
  type DreamReport,
  type DreamReportContext,
} from "./dreamReport.ts";

// ------------------------------------------- the local mirrors of the module-private pins

/** The pinned values of the module-private `DREAM_REPORT_CAPS` SSOT — the schema-lockstep
 * test compares the exported input schema against this mirror, so a silent cap retune in the
 * module still trips the suite. */
const CAPS = {
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

/** The module-private thresholds, mirrored: each is pinned behaviorally below (the rendered
 * part sizes, the snapshot's schema_version, the refusal details' literal 12/25 caps). */
const SCHEMA_VERSION = "1";
const PART_MAX_CHARS = 60_000;
const MAX_ROADMAP_NODES = 12;
const MAX_VALIDATION_DETAILS = 25;

/** One final per-doc disposition row (the module-private input shape, mirrored). */
interface DreamReportInputRow {
  path: string;
  disposition: DreamDisposition;
  merge_target: string | null;
  rationale: string;
  fallback_reason: string | null;
}

/** The model-supplied input shape (module-private in the feature — `buildDreamReport` takes
 * `unknown`; mirrored here so the fixture builders stay typed). */
interface DreamReportInput {
  rows: DreamReportInputRow[];
  uncertainties: string[];
  selected_units: { title: string; roadmap_node: string; docs: string[]; rationale: string }[];
  overflow_units: { title: string; docs: string[]; rationale: string }[];
  harvest_followups: { title: string; destination: string; pointer: string; evidence: string }[];
  predicted_effects: { docs_after: number; bytes_after: number; note: string | null };
}

const MANIFEST_PATH = "/abs/scratch/runs/RUN/dream-manifest.json";
const RUN_ID = "01RUNDREAM";
const GENERATED_AT = "2026-02-03T04:05:06Z";

const DOC_CTX = "docs/learned/pi/context-injection.md";
const DOC_SUB = "docs/learned/pi/subagents.md";
const DOC_WAVES = "docs/learned/workflow/report-waves.md";

function emptyFindings(): Record<string, unknown> {
  return {
    structural: {
      stale_pointers: [],
      broken_doc_paths: [],
      duplicate_cues: [],
      missing_frontmatter: [],
    },
    advisory: {
      distillation_issues: [],
      source_code_blocks: [],
      overlong_cues: [],
      cue_hazards: [],
      empty_clusters: [],
    },
  };
}

function decodeManifest(raw: Record<string, unknown>): DreamManifest {
  const decoded = decodeDreamManifest(raw, MANIFEST_PATH);
  assert.equal(decoded.ok, true, JSON.stringify(decoded));
  return (decoded as { ok: true; manifest: DreamManifest }).manifest;
}

/** The 2-lane / 3-doc manifest (the reducer suite's shape) with one finding per family kind. */
function fixtureManifest(): DreamManifest {
  return decodeManifest({
    schema_version: "1",
    commit_sha: "abc123",
    registry_mode: "clusters",
    doc_count: 3,
    total_bytes: 350,
    findings: {
      structural: {
        stale_pointers: [
          { doc: DOC_CTX, pointer: "perk/run/launch.py::_gone", reason: "missing-symbol" },
        ],
        broken_doc_paths: [],
        duplicate_cues: [],
        missing_frontmatter: [],
      },
      advisory: {
        distillation_issues: [],
        source_code_blocks: [],
        overlong_cues: [],
        cue_hazards: [],
        empty_clusters: ["prose-governance"],
      },
    },
    lanes: [
      {
        id: "pi-extension-1",
        rollup: "Pi SDK craft",
        docs: [
          { path: DOC_CTX, title: "T", read_when: "cue", cluster: "pi-extension", bytes: 100 },
          { path: DOC_SUB, title: null, read_when: null, cluster: null, bytes: 200 },
        ],
      },
      {
        id: "workflow-1",
        rollup: null,
        docs: [{ path: DOC_WAVES, title: null, read_when: null, cluster: "workflow", bytes: 50 }],
      },
    ],
  });
}

/** A generated docCount-doc manifest: lanes of 8, cluster `gen-<lane>` per lane. */
function genManifest(docCount: number): DreamManifest {
  const lanes: Record<string, unknown>[] = [];
  for (let start = 0; start < docCount; start += 8) {
    const laneIndex = lanes.length;
    const docs: Record<string, unknown>[] = [];
    for (let i = start; i < Math.min(start + 8, docCount); i += 1) {
      docs.push({
        path: `docs/learned/gen/doc-${String(i).padStart(3, "0")}.md`,
        title: null,
        read_when: null,
        cluster: `gen-${laneIndex}`,
        bytes: 10,
      });
    }
    lanes.push({ id: `gen-${laneIndex}-1`, rollup: null, docs });
  }
  return decodeManifest({
    schema_version: "1",
    commit_sha: "abc123",
    registry_mode: "clusters",
    doc_count: docCount,
    total_bytes: 10 * docCount,
    findings: emptyFindings(),
    lanes,
  });
}

function manifestPaths(manifest: DreamManifest): string[] {
  return manifest.lanes.flatMap((lane) => lane.docs.map((doc) => doc.path));
}

function assessment(path: string, overrides: Partial<DreamDocAssessment> = {}): DreamDocAssessment {
  return {
    path,
    disposition: "keep",
    merge_target: null,
    rationale: "still true",
    preserve: [],
    evidence_checked: [],
    confidence: "high",
    ...overrides,
  };
}

function analysisOf(
  lane: string,
  docs: DreamDocAssessment[],
  extras: Partial<DreamLaneAnalysis["report"]> = {},
): DreamLaneAnalysis {
  return {
    lane,
    report: {
      docs,
      overlap_signals: [],
      harvest_followups: [],
      uncertainties: [],
      overlap_signals_omitted: 0,
      harvest_followups_omitted: 0,
      uncertainties_omitted: 0,
      ...extras,
    },
  };
}

function stanceOf(
  doc: string,
  disposition: DreamStanceDisposition,
  stance: "endorse" | "challenge" = "endorse",
  reason = "verified against the checkout",
  evidenceChecked: string[] = [],
): DreamStance {
  return { doc, disposition, stance, reason, evidence_checked: evidenceChecked };
}

function reducerOf(
  angle: DreamReducerAngle,
  stances: DreamStance[] = [],
  extras: Partial<DreamReducerAnalysis["report"]> = {},
): DreamReducerAnalysis {
  return {
    angle,
    report: {
      stances,
      angle_findings: [],
      uncertainties: [],
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
      ...extras,
    },
  };
}

/** One analyst proposal for `contextFor` (docs without an entry are proposed `keep`). */
interface Proposal {
  disposition: DreamDisposition;
  merge_target?: string;
  rationale?: string;
}

/**
 * Build a trusted context over a manifest: analyses echo `proposals` in manifest order; each
 * gate angle endorses every DESTRUCTIVE proposal by default (the evidence bar passes unless a
 * test overrides an angle's stances), knowledge-architecture is silent by default.
 */
function contextFor(
  manifest: DreamManifest,
  proposals: Record<string, Proposal> = {},
  stancesByAngle: Partial<Record<DreamReducerAngle, DreamStance[]>> = {},
): DreamReportContext {
  const analyses = manifest.lanes.map((lane) =>
    analysisOf(
      lane.id,
      lane.docs.map((doc) => {
        const proposal = proposals[doc.path] ?? { disposition: "keep" };
        return assessment(doc.path, {
          disposition: proposal.disposition,
          merge_target: proposal.merge_target ?? null,
          ...(proposal.rationale !== undefined ? { rationale: proposal.rationale } : {}),
        });
      }),
    ),
  );
  const gateDefault = Object.entries(proposals)
    .filter(([, p]) => p.disposition === "merge-into" || p.disposition === "retire")
    .map(([path, p]) => stanceOf(path, p.disposition as DreamStanceDisposition));
  const reducers = DREAM_REDUCER_ANGLES.map((angle) =>
    reducerOf(
      angle,
      stancesByAngle[angle] ?? (angle === "knowledge-architecture" ? [] : gateDefault),
    ),
  );
  return { manifest, analyses, reducers, run_id: RUN_ID, generated_at: GENERATED_AT };
}

/**
 * Build a valid input over a context: rows echo the analyst proposals (per-row overrides
 * applied), selected units auto-partition the FINAL non-keep docs (chunks of `unitDocs`, one
 * shared node), predicted effects echo the manifest. Top-level overrides win last.
 */
function inputFor(
  context: DreamReportContext,
  rowOverrides: Record<string, Partial<DreamReportInputRow>> = {},
  overrides: Partial<DreamReportInput> = {},
): DreamReportInput {
  const rows: DreamReportInputRow[] = context.analyses.flatMap((analysis) =>
    analysis.report.docs.map((doc) => ({
      path: doc.path,
      disposition: doc.disposition,
      merge_target: doc.merge_target,
      rationale: "the parent's reason",
      fallback_reason: null,
      ...rowOverrides[doc.path],
    })),
  );
  const nonKeep = rows.filter((row) => row.disposition !== "keep").map((row) => row.path);
  const selectedUnits: DreamReportInput["selected_units"] = [];
  for (let start = 0; start < nonKeep.length; start += CAPS.unitDocs) {
    selectedUnits.push({
      title: `Unit ${selectedUnits.length + 1}`,
      roadmap_node: "1.1",
      docs: nonKeep.slice(start, start + CAPS.unitDocs),
      rationale: "bundled",
    });
  }
  return {
    rows,
    uncertainties: [],
    selected_units: selectedUnits,
    overflow_units: [],
    harvest_followups: [],
    predicted_effects: {
      docs_after: context.manifest.doc_count,
      bytes_after: context.manifest.total_bytes,
      note: null,
    },
    ...overrides,
  };
}

/** The pinned full fixture: a merge kept destructive (both gates endorse), a retire downgraded
 * to revise on a currency challenge (the fallback), and a plain revise. */
function fixtureContext(): DreamReportContext {
  const manifest = fixtureManifest();
  return {
    manifest,
    analyses: [
      analysisOf(
        "pi-extension-1",
        [
          assessment(DOC_CTX, {
            disposition: "revise",
            rationale: "the cue drifted",
            preserve: ["the injection table"],
            evidence_checked: ["extension/context.ts"],
            confidence: "high",
          }),
          assessment(DOC_SUB, {
            disposition: "merge-into",
            merge_target: DOC_WAVES,
            rationale: "duplicates report-waves",
            evidence_checked: ["extension/waves/reportWave.ts"],
            confidence: "medium",
          }),
        ],
        { uncertainties: ["unsure the cue survives a merge"], overlap_signals_omitted: 2 },
      ),
      analysisOf("workflow-1", [
        assessment(DOC_WAVES, {
          disposition: "retire",
          rationale: "superseded by newer docs",
          confidence: "low",
        }),
      ]),
    ],
    reducers: [
      reducerOf(
        "consolidation-preservation",
        [
          stanceOf(DOC_SUB, "merge-into", "endorse", "the target covers it", [DOC_WAVES]),
          stanceOf(DOC_WAVES, "retire", "endorse", "content preserved elsewhere"),
        ],
        { angle_findings: ["the two pi docs overlap"] },
      ),
      reducerOf(
        "currency-accuracy",
        [
          stanceOf(DOC_SUB, "merge-into", "endorse", "claims verified current", [
            "extension/waves/reportWave.ts",
          ]),
          stanceOf(DOC_WAVES, "retire", "challenge", "still cited by the index", [
            "docs/learned/index.md",
          ]),
        ],
        {
          uncertainties: ["the retire may be premature"],
          stances_omitted: 1,
          uncertainties_omitted: 3,
        },
      ),
      reducerOf("knowledge-architecture", [], {
        angle_findings: ["cluster routing stays coherent"],
      }),
    ],
    run_id: RUN_ID,
    generated_at: GENERATED_AT,
  };
}

function fixtureInput(): DreamReportInput {
  return {
    rows: [
      {
        path: DOC_CTX,
        disposition: "revise",
        merge_target: null,
        rationale: "refresh the drifted cue",
        fallback_reason: null,
      },
      {
        path: DOC_SUB,
        disposition: "merge-into",
        merge_target: DOC_WAVES,
        rationale: "both gates endorse the merge",
        fallback_reason: null,
      },
      {
        path: DOC_WAVES,
        disposition: "revise",
        merge_target: null,
        rationale: "refresh instead of retire",
        fallback_reason: "currency-accuracy challenged the retire",
      },
    ],
    uncertainties: ["unsure the merged doc needs a new cue"],
    selected_units: [
      {
        title: "Merge subagents guidance into report-waves",
        roadmap_node: "2.1",
        docs: [DOC_SUB, DOC_CTX],
        rationale: "one focused PR",
      },
    ],
    overflow_units: [
      {
        title: "Refresh report-waves after the merge",
        docs: [DOC_WAVES],
        rationale: "lower-priority follow-on",
      },
    ],
    harvest_followups: [
      {
        title: "Extract the shared wave helper",
        destination: DOC_WAVES,
        pointer: "extension/waves/reportWave.ts",
        evidence: "both dream waves duplicate the retry shape",
      },
    ],
    predicted_effects: { docs_after: 2, bytes_after: 300, note: "one merge lands" },
  };
}

function refusalDetails(input: unknown, context: DreamReportContext): string[] {
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, false, `expected a refusal, got: ${JSON.stringify(result)}`);
  return (result as { ok: false; details: string[] }).details;
}

/** Assert ONE fail-fast detail (context re-verification / structural decode arms). */
function expectFailFast(input: unknown, context: DreamReportContext, detail: RegExp): void {
  const details = refusalDetails(input, context);
  assert.equal(details.length, 1, `fail-fast must return one detail, got: ${details.join(" | ")}`);
  assert.match(details[0] as string, detail);
}

function validReport(input: DreamReportInput, context: DreamReportContext): DreamReport {
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, true, JSON.stringify(result));
  return (result as { ok: true; report: DreamReport }).report;
}

// ------------------------------------------------------------- the schema↔caps lockstep

test("DREAM_REPORT_INPUT_SCHEMA: closed shape, required-completeness, enums, caps SSOT", () => {
  const caps = CAPS;
  const schema = DREAM_REPORT_INPUT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, Record<string, unknown>>;
  };
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(
    [...schema.required].sort(),
    Object.keys(schema.properties).sort(),
    "every top-level field is required",
  );

  type ObjectSchema = {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, Record<string, unknown>>;
  };
  const closedComplete = (node: ObjectSchema, what: string): void => {
    assert.equal(node.additionalProperties, false, `${what} is closed`);
    assert.deepEqual(
      [...node.required].sort(),
      Object.keys(node.properties).sort(),
      `every ${what} field is required`,
    );
  };

  const rows = schema.properties.rows as { maxItems: number; items: ObjectSchema };
  assert.equal(rows.maxItems, caps.rows);
  closedComplete(rows.items, "disposition row");
  assert.deepEqual(rows.items.properties.disposition, {
    type: "string",
    enum: [...DREAM_DISPOSITIONS],
  });
  assert.deepEqual(rows.items.properties.merge_target, { type: ["string", "null"] });
  assert.equal(rows.items.properties.rationale?.maxLength, caps.rowRationaleChars);
  assert.deepEqual(rows.items.properties.fallback_reason, {
    type: ["string", "null"],
    maxLength: caps.fallbackReasonChars,
  });

  assert.deepEqual(schema.properties.uncertainties, {
    type: "array",
    maxItems: caps.uncertainties,
    items: { type: "string", maxLength: caps.uncertaintyChars },
  });

  const selected = schema.properties.selected_units as { maxItems: number; items: ObjectSchema };
  assert.equal(selected.maxItems, caps.selectedUnits);
  closedComplete(selected.items, "selected unit");
  assert.equal(selected.items.properties.title?.maxLength, caps.unitTitleChars);
  assert.equal(selected.items.properties.roadmap_node?.maxLength, caps.unitNodeChars);
  assert.deepEqual(selected.items.properties.docs, {
    type: "array",
    maxItems: caps.unitDocs,
    items: { type: "string" },
  });
  assert.equal(selected.items.properties.rationale?.maxLength, caps.unitRationaleChars);

  const overflow = schema.properties.overflow_units as { maxItems: number; items: ObjectSchema };
  assert.equal(overflow.maxItems, caps.overflowUnits);
  closedComplete(overflow.items, "overflow unit");
  assert.deepEqual(
    Object.keys(overflow.items.properties).sort(),
    ["docs", "rationale", "title"],
    "overflow units carry no roadmap node",
  );
  assert.equal(overflow.items.properties.title?.maxLength, caps.unitTitleChars);
  assert.deepEqual(overflow.items.properties.docs, {
    type: "array",
    maxItems: caps.unitDocs,
    items: { type: "string" },
  });
  assert.equal(overflow.items.properties.rationale?.maxLength, caps.unitRationaleChars);

  const followups = schema.properties.harvest_followups as {
    maxItems: number;
    items: ObjectSchema;
  };
  assert.equal(followups.maxItems, caps.harvestFollowups);
  closedComplete(followups.items, "harvest follow-up");
  assert.equal(followups.items.properties.title?.maxLength, caps.followupTitleChars);
  assert.equal(followups.items.properties.destination?.maxLength, caps.followupDestinationChars);
  assert.equal(followups.items.properties.pointer?.maxLength, caps.followupPointerChars);
  assert.equal(followups.items.properties.evidence?.maxLength, caps.followupEvidenceChars);

  const effects = schema.properties.predicted_effects as ObjectSchema;
  closedComplete(effects, "predicted_effects");
  assert.deepEqual(effects.properties.docs_after, { type: "integer", minimum: 0 });
  assert.deepEqual(effects.properties.bytes_after, { type: "integer", minimum: 0 });
  assert.deepEqual(effects.properties.note, {
    type: ["string", "null"],
    maxLength: caps.predictedNoteChars,
  });
});

// ------------------------------------------------------- the context re-verification

test("context re-verification refuses fail-fast: run identity, lane coverage, reducer angles", () => {
  const context = fixtureContext();
  const input = fixtureInput();

  expectFailFast(input, { ...context, run_id: "" }, /context run_id must be a non-empty string/);
  expectFailFast(
    input,
    { ...context, generated_at: "a\nb" },
    /context generated_at must be a single-line string/,
  );

  // A missing lane analysis.
  expectFailFast(
    input,
    { ...context, analyses: [context.analyses[0] as DreamLaneAnalysis] },
    /context analyses must cover the manifest's lanes exactly in manifest order/,
  );
  // Lane order flipped.
  expectFailFast(
    input,
    { ...context, analyses: [...context.analyses].reverse() },
    /context analyses must cover the manifest's lanes exactly/,
  );
  // A lane analysis that does not cover its lane's docs.
  const partialLane = analysisOf("pi-extension-1", [assessment(DOC_CTX)]);
  expectFailFast(
    input,
    { ...context, analyses: [partialLane, context.analyses[1] as DreamLaneAnalysis] },
    /context analysis for lane 'pi-extension-1' does not cover the lane's docs exactly/,
  );

  // A missing reducer angle, a duplicate angle, and an extra fourth report.
  const [cp, ca, ka] = context.reducers as [
    DreamReducerAnalysis,
    DreamReducerAnalysis,
    DreamReducerAnalysis,
  ];
  const anglesDetail =
    /context reducers must carry exactly the three reducer angles in fixed order/;
  expectFailFast(input, { ...context, reducers: [cp, ca] }, anglesDetail);
  expectFailFast(input, { ...context, reducers: [cp, ca, cp] }, anglesDetail);
  expectFailFast(input, { ...context, reducers: [cp, ca, ka, cp] }, anglesDetail);
});

// --------------------------------------------------------- the structural decode (fail-fast)

test("structural decode: each arm fails fast with its named detail", () => {
  const caps = CAPS;
  const context = contextFor(fixtureManifest());
  const base = (): DreamReportInput => inputFor(context);
  const row = (): DreamReportInputRow => ({
    path: DOC_CTX,
    disposition: "keep",
    merge_target: null,
    rationale: "r",
    fallback_reason: null,
  });
  const arms: { input: unknown; detail: RegExp }[] = [
    { input: "nope", detail: /dream report input is not an object/ },
    { input: { ...base(), rows: "nope" }, detail: /input rows is not an array/ },
    {
      input: { ...base(), rows: Array.from({ length: caps.rows + 1 }, row) },
      detail: new RegExp(`input rows carries more than ${caps.rows} rows`),
    },
    { input: { ...base(), rows: [null] }, detail: /a disposition row is not an object/ },
    {
      input: { ...base(), rows: [{ ...row(), path: 5 }] },
      detail: /a disposition row path is not a string/,
    },
    {
      input: { ...base(), rows: [{ ...row(), disposition: "destroy" }] },
      detail: /disposition "destroy" is outside the vocabulary/,
    },
    {
      input: { ...base(), rows: [{ ...row(), merge_target: 5 }] },
      detail: /merge_target is not a string/,
    },
    {
      input: { ...base(), rows: [{ ...row(), rationale: "x".repeat(caps.rowRationaleChars + 1) }] },
      detail: new RegExp(`rationale exceeds ${caps.rowRationaleChars} code points`),
    },
    {
      input: {
        ...base(),
        rows: [{ ...row(), fallback_reason: "x".repeat(caps.fallbackReasonChars + 1) }],
      },
      detail: new RegExp(`fallback_reason exceeds ${caps.fallbackReasonChars} code points`),
    },
    {
      input: {
        ...base(),
        uncertainties: Array.from({ length: caps.uncertainties + 1 }, () => "u"),
      },
      detail: new RegExp(`input uncertainties carries more than ${caps.uncertainties} items`),
    },
    {
      input: { ...base(), uncertainties: ["x".repeat(caps.uncertaintyChars + 1)] },
      detail: new RegExp(`input uncertainties item exceeds ${caps.uncertaintyChars} code points`),
    },
    {
      input: { ...base(), selected_units: "nope" },
      detail: /input selected_units is not an array/,
    },
    {
      input: { ...base(), selected_units: [null] },
      detail: /selected unit 1 is not an object/,
    },
    {
      input: {
        ...base(),
        selected_units: [
          {
            title: "x".repeat(caps.unitTitleChars + 1),
            roadmap_node: "1.1",
            docs: [DOC_CTX],
            rationale: "r",
          },
        ],
      },
      detail: new RegExp(`selected unit 1 title exceeds ${caps.unitTitleChars} code points`),
    },
    {
      input: {
        ...base(),
        selected_units: [
          {
            title: "t",
            roadmap_node: "x".repeat(caps.unitNodeChars + 1),
            docs: [DOC_CTX],
            rationale: "r",
          },
        ],
      },
      detail: new RegExp(`selected unit 1 roadmap_node exceeds ${caps.unitNodeChars} code points`),
    },
    {
      input: {
        ...base(),
        selected_units: [
          {
            title: "t",
            roadmap_node: "1.1",
            docs: Array.from({ length: caps.unitDocs + 1 }, () => DOC_CTX),
            rationale: "r",
          },
        ],
      },
      detail: new RegExp(`selected unit 1 docs carries more than ${caps.unitDocs} items`),
    },
    {
      input: {
        ...base(),
        selected_units: [{ title: "t", roadmap_node: "1.1", docs: [5], rationale: "r" }],
      },
      detail: /a selected unit 1 docs item is not a string/,
    },
    {
      input: { ...base(), overflow_units: [{ title: "t", docs: [DOC_CTX], rationale: 5 }] },
      detail: /overflow unit 1 rationale is not a string/,
    },
    {
      input: { ...base(), harvest_followups: [null] },
      detail: /harvest follow-up 1 is not an object/,
    },
    {
      input: {
        ...base(),
        harvest_followups: [
          {
            title: "t",
            destination: "x".repeat(caps.followupDestinationChars + 1),
            pointer: "p",
            evidence: "e",
          },
        ],
      },
      detail: new RegExp(
        `harvest follow-up 1 destination exceeds ${caps.followupDestinationChars} code points`,
      ),
    },
    {
      input: {
        ...base(),
        harvest_followups: [
          {
            title: "t",
            destination: "d",
            pointer: "x".repeat(caps.followupPointerChars + 1),
            evidence: "e",
          },
        ],
      },
      detail: new RegExp(
        `harvest follow-up 1 pointer exceeds ${caps.followupPointerChars} code points`,
      ),
    },
    {
      input: { ...base(), predicted_effects: "nope" },
      detail: /input predicted_effects is not an object/,
    },
    {
      input: { ...base(), predicted_effects: { docs_after: -1, bytes_after: 0, note: null } },
      detail: /predicted_effects docs_after is not a non-negative integer/,
    },
    {
      input: { ...base(), predicted_effects: { docs_after: 0, bytes_after: 1.5, note: null } },
      detail: /predicted_effects bytes_after is not a non-negative integer/,
    },
    {
      input: {
        ...base(),
        predicted_effects: {
          docs_after: 0,
          bytes_after: 0,
          note: "x".repeat(caps.predictedNoteChars + 1),
        },
      },
      detail: new RegExp(`predicted_effects note exceeds ${caps.predictedNoteChars} code points`),
    },
  ];
  for (const arm of arms) {
    expectFailFast(arm.input, context, arm.detail);
  }
});

test("the single-line rule: \\r/\\n and other C0 controls refuse with a named detail", () => {
  const context = contextFor(fixtureManifest());
  expectFailFast(
    { ...inputFor(context), uncertainties: ["a\nb"] },
    context,
    /contains a newline — model-supplied strings must be single-line/,
  );
  expectFailFast(
    inputFor(context, { [DOC_CTX]: { rationale: "a\rb" } }),
    context,
    /rationale contains a carriage return — model-supplied strings must be single-line/,
  );
  expectFailFast(
    inputFor(context, { [DOC_CTX]: { rationale: "a\u0007b" } }),
    context,
    /rationale contains a C0 control character \(U\+0007\) — model-supplied strings must be single-line/,
  );
});

test("string caps are measured in Unicode code points (astral)", () => {
  const caps = CAPS;
  const context = contextFor(fixtureManifest());
  const astral = "😀".repeat(caps.rowRationaleChars);
  assert.ok(astral.length > caps.rowRationaleChars, "sanity: UTF-16 exceeds the cap");
  const pass = buildDreamReport(inputFor(context, { [DOC_CTX]: { rationale: astral } }), context);
  assert.equal(pass.ok, true, "exactly N astral code points passes");
  expectFailFast(
    inputFor(context, { [DOC_CTX]: { rationale: `${astral}😀` } }),
    context,
    new RegExp(`rationale exceeds ${caps.rowRationaleChars} code points`),
  );
});

test("a structural miss fails fast even when semantic violations are also present", () => {
  const context = contextFor(fixtureManifest());
  const input = inputFor(context);
  // Drop one row (semantic: missing) AND corrupt another's disposition (structural).
  input.rows = input.rows.slice(0, 2);
  const details = refusalDetails(
    { ...input, rows: [{ ...(input.rows[0] as DreamReportInputRow), disposition: "destroy" }] },
    context,
  );
  assert.equal(details.length, 1, "structural decode fails fast");
  assert.match(details[0] as string, /outside the vocabulary/);
});

// ---------------------------------------------------------------- path-set equality (D4)

test("rows must equal the authored-doc path set exactly: missing, extra, duplicate", () => {
  const context = contextFor(fixtureManifest());
  const base = inputFor(context);

  const missing = { ...base, rows: base.rows.filter((row) => row.path !== DOC_WAVES) };
  assert.deepEqual(refusalDetails(missing, context), [
    `missing disposition row for authored doc '${DOC_WAVES}'`,
  ]);

  const extraRow: DreamReportInputRow = {
    path: "docs/learned/gone.md",
    disposition: "keep",
    merge_target: null,
    rationale: "r",
    fallback_reason: null,
  };
  const extra = { ...base, rows: [...base.rows, extraRow] };
  assert.deepEqual(refusalDetails(extra, context), [
    "disposition row path 'docs/learned/gone.md' is not an authored doc in the manifest",
  ]);

  const duplicate = { ...base, rows: [...base.rows, { ...(base.rows[0] as DreamReportInputRow) }] };
  assert.deepEqual(refusalDetails(duplicate, context), [
    `duplicate disposition row for '${DOC_CTX}'`,
  ]);
});

test("the merge-target shape rules: non-null iff merge-into; rationale non-empty", () => {
  const manifest = fixtureManifest();
  const merging = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
  });
  const details = refusalDetails(inputFor(merging, { [DOC_SUB]: { merge_target: null } }), merging);
  assert.deepEqual(details, [
    `row '${DOC_SUB}' has disposition 'merge-into' but a null merge_target`,
  ]);

  const keeping = contextFor(manifest);
  assert.deepEqual(
    refusalDetails(inputFor(keeping, { [DOC_CTX]: { merge_target: DOC_SUB } }), keeping),
    [`row '${DOC_CTX}' carries a merge_target on a 'keep' disposition (must be null)`],
  );
  assert.deepEqual(refusalDetails(inputFor(keeping, { [DOC_CTX]: { rationale: "" } }), keeping), [
    `row '${DOC_CTX}' rationale must be non-empty`,
  ]);
});

// ------------------------------------------------------------------- downgrade-only (D4)

test("downgrade-only: escalations refuse; destructive finals must match the proposal exactly", () => {
  const manifest = fixtureManifest();

  // keep → revise is an escalation.
  const allKeep = contextFor(manifest);
  assert.deepEqual(
    refusalDetails(
      inputFor(allKeep, {
        [DOC_CTX]: { disposition: "revise", fallback_reason: "why" },
      }),
      allKeep,
    ),
    [
      `row '${DOC_CTX}' escalates the analyst proposal 'keep' to 'revise' — the parent never resolves upward`,
    ],
  );

  // revise → retire is an escalation.
  const revising = contextFor(manifest, { [DOC_CTX]: { disposition: "revise" } });
  const escalated = refusalDetails(
    inputFor(revising, { [DOC_CTX]: { disposition: "retire", fallback_reason: "why" } }),
    revising,
  );
  assert.match(escalated[0] as string, /escalates the analyst proposal 'revise' to 'retire'/);

  // merge-into → retire is an unendorsed swap (the destructive dispositions are incomparable).
  const merging = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
  });
  const swapped = refusalDetails(
    inputFor(merging, {
      [DOC_SUB]: { disposition: "retire", merge_target: null, fallback_reason: "why" },
    }),
    merging,
  );
  assert.deepEqual(swapped, [
    `row '${DOC_SUB}' final 'retire' does not match the analyst proposal ` +
      `'merge-into → ${DOC_WAVES}' exactly — an unendorsed destructive action is refused ` +
      "(downgrade to 'revise' or 'keep' with a fallback_reason instead)",
  ]);

  // A changed merge target is an unendorsed new action.
  const retargeted = refusalDetails(
    inputFor(merging, { [DOC_SUB]: { merge_target: DOC_CTX } }),
    merging,
  );
  assert.match(
    retargeted[0] as string,
    new RegExp(`final 'merge-into → ${DOC_CTX}' does not match the analyst proposal`),
  );
});

test("downgrade-only: legal downgrades pass WITH a fallback_reason; the fallback rule is exact", () => {
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
    [DOC_WAVES]: { disposition: "retire" },
  });

  // retire → revise and merge-into → keep both downgrade legally with a reason.
  const downgraded = inputFor(context, {
    [DOC_SUB]: { disposition: "keep", merge_target: null, fallback_reason: "kept after all" },
    [DOC_WAVES]: { disposition: "revise", fallback_reason: "challenged" },
  });
  const report = validReport(downgraded, context);
  assert.deepEqual(
    report.rows
      .filter((row) => row.fallback_reason !== null)
      .map((row) => [row.path, row.analyst_disposition, row.final_disposition]),
    [
      [DOC_SUB, "merge-into", "keep"],
      [DOC_WAVES, "retire", "revise"],
    ],
  );

  // A fallback_reason on an unchanged row refuses (WAVES downgraded so survival stays clean).
  assert.deepEqual(
    refusalDetails(
      inputFor(context, {
        [DOC_CTX]: { fallback_reason: "noise" },
        [DOC_WAVES]: { disposition: "revise", fallback_reason: "challenged" },
      }),
      context,
    ),
    [`row '${DOC_CTX}' matches the analyst proposal and must carry fallback_reason: null`],
  );

  // A changed row without a fallback_reason refuses (empty string included). SUB is also
  // downgraded here so the missing reason is the ONLY violation.
  const missingReason = refusalDetails(
    inputFor(context, {
      [DOC_SUB]: { disposition: "keep", merge_target: null, fallback_reason: "kept after all" },
      [DOC_WAVES]: { disposition: "revise" },
    }),
    context,
  );
  assert.deepEqual(missingReason, [
    `row '${DOC_WAVES}' departs from the analyst proposal ('retire' → 'revise') and requires ` +
      "a non-empty fallback_reason",
  ]);
  const emptyReason = refusalDetails(
    inputFor(context, {
      [DOC_SUB]: { disposition: "keep", merge_target: null, fallback_reason: "kept after all" },
      [DOC_WAVES]: { disposition: "revise", fallback_reason: "" },
    }),
    context,
  );
  assert.match(emptyReason[0] as string, /requires a non-empty fallback_reason/);
});

// --------------------------------------------------------------- the evidence bar (D5)

test("the destructive evidence bar: both gates must endorse; ANY challenge blocks", () => {
  const manifest = fixtureManifest();
  const proposals: Record<string, Proposal> = {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
  };

  // Both gate angles endorse, no challenge — the destructive final passes.
  const endorsed = contextFor(manifest, proposals);
  assert.equal(buildDreamReport(inputFor(endorsed), endorsed).ok, true);

  // One gate silent — silence is non-endorsement.
  const silentGate = contextFor(manifest, proposals, { "currency-accuracy": [] });
  assert.deepEqual(refusalDetails(inputFor(silentGate), silentGate), [
    `destructive row '${DOC_SUB}' ('merge-into') fails the evidence bar: ` +
      "no 'currency-accuracy' endorsement (silence is non-endorsement) — the only legal moves " +
      "are downgrading to 'revise' or 'keep' with a fallback_reason",
  ]);

  // A challenge from ANY angle blocks — knowledge-architecture included.
  const challenged = contextFor(manifest, proposals, {
    "knowledge-architecture": [stanceOf(DOC_SUB, "merge-into", "challenge", "risky")],
  });
  assert.deepEqual(refusalDetails(inputFor(challenged), challenged), [
    `destructive row '${DOC_SUB}' ('merge-into') fails the evidence bar: ` +
      "a 'knowledge-architecture' challenge — the only legal moves are downgrading to " +
      "'revise' or 'keep' with a fallback_reason",
  ]);

  // The blocked proposal downgraded (with the recorded fallback) passes.
  const downgraded = inputFor(challenged, {
    [DOC_SUB]: {
      disposition: "revise",
      merge_target: null,
      fallback_reason: "the architecture challenge blocks the merge",
    },
  });
  assert.equal(buildDreamReport(downgraded, challenged).ok, true);
});

// ------------------------------------------------------- merge-target survival (D6)

test("merge-target survival: retired/merged-away targets, 2-cycles, and chains all refuse", () => {
  const manifest = fixtureManifest();

  // A retired target does not survive.
  const retiredTarget = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
    [DOC_WAVES]: { disposition: "retire" },
  });
  assert.deepEqual(refusalDetails(inputFor(retiredTarget), retiredTarget), [
    `row '${DOC_SUB}' merge_target '${DOC_WAVES}' does not survive (final disposition ` +
      "'retire') — a merge target must end keep or revise",
  ]);

  // A merged-away target (the 3-chain) refuses via the same survival detail.
  const chain = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
    [DOC_WAVES]: { disposition: "merge-into", merge_target: DOC_CTX },
  });
  assert.deepEqual(refusalDetails(inputFor(chain), chain), [
    `row '${DOC_SUB}' merge_target '${DOC_WAVES}' does not survive (final disposition ` +
      "'merge-into') — a merge target must end keep or revise",
  ]);

  // A 2-cycle refuses from both sides.
  const cycle = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
    [DOC_WAVES]: { disposition: "merge-into", merge_target: DOC_SUB },
  });
  const details = refusalDetails(inputFor(cycle), cycle);
  assert.equal(details.length, 2);
  for (const detail of details) {
    assert.match(detail, /does not survive \(final disposition 'merge-into'\)/);
  }

  // Existence is revalidated even against a (drifted) context proposal.
  const ghostTarget = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: "docs/learned/gone.md" },
  });
  assert.deepEqual(refusalDetails(inputFor(ghostTarget), ghostTarget), [
    `row '${DOC_SUB}' merge_target 'docs/learned/gone.md' is not a member of the manifest corpus`,
  ]);
});

// ------------------------------------------------------------- the unit partition (D7)

test("units must partition the final non-keep docs exactly", () => {
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_CTX]: { disposition: "revise" },
    [DOC_SUB]: { disposition: "revise" },
  });
  const unit = (docs: string[], title = "U"): DreamReportInput["selected_units"][number] => ({
    title,
    roadmap_node: "2.1",
    docs,
    rationale: "r",
  });

  // An uncovered non-keep doc.
  assert.deepEqual(
    refusalDetails(inputFor(context, {}, { selected_units: [unit([DOC_CTX])] }), context),
    [
      `non-keep doc '${DOC_SUB}' is not covered by any curation unit — selected + overflow ` +
        "units must partition the non-keep docs exactly",
    ],
  );

  // A doc in two units (selected + overflow both claim it).
  assert.deepEqual(
    refusalDetails(
      inputFor(
        context,
        {},
        {
          selected_units: [unit([DOC_CTX, DOC_SUB])],
          overflow_units: [{ title: "O", docs: [DOC_SUB], rationale: "r" }],
        },
      ),
      context,
    ),
    [`doc '${DOC_SUB}' appears in more than one curation unit`],
  );

  // A final-keep doc in a unit.
  assert.deepEqual(
    refusalDetails(
      inputFor(context, {}, { selected_units: [unit([DOC_CTX, DOC_SUB, DOC_WAVES])] }),
      context,
    ),
    [
      `selected unit 1 ('U') doc '${DOC_WAVES}' has final disposition 'keep' — final-keep ` +
        "docs appear in no unit",
    ],
  );

  // An empty unit.
  assert.deepEqual(
    refusalDetails(
      inputFor(context, {}, { selected_units: [unit([], "E"), unit([DOC_CTX, DOC_SUB])] }),
      context,
    ),
    ["selected unit 1 ('E') has no docs — empty units are refused"],
  );

  // An unknown path.
  assert.deepEqual(
    refusalDetails(
      inputFor(context, {}, { selected_units: [unit([DOC_CTX, DOC_SUB, "docs/learned/gone.md"])] }),
      context,
    ),
    ["selected unit 1 ('U') doc 'docs/learned/gone.md' is not a member of the manifest corpus"],
  );

  // An empty roadmap node.
  const nodeless = inputFor(context, {}, { selected_units: [unit([DOC_CTX, DOC_SUB])] });
  (nodeless.selected_units[0] as { roadmap_node: string }).roadmap_node = "";
  assert.deepEqual(refusalDetails(nodeless, context), [
    "selected unit 1 ('U') roadmap_node must be non-empty",
  ]);
});

test("units: many-to-one node mapping passes; 13 DISTINCT nodes refuse", () => {
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_CTX]: { disposition: "revise" },
    [DOC_SUB]: { disposition: "revise" },
  });
  // Two units sharing one roadmap node — a node may bundle small independent units.
  const shared = inputFor(
    context,
    {},
    {
      selected_units: [
        { title: "A", roadmap_node: "2.1", docs: [DOC_CTX], rationale: "r" },
        { title: "B", roadmap_node: "2.1", docs: [DOC_SUB], rationale: "r" },
      ],
    },
  );
  assert.equal(buildDreamReport(shared, context).ok, true);

  // Thirteen DISTINCT nodes exceed the review-time selection cap.
  const bigManifest = genManifest(13);
  const bigContext = contextFor(
    bigManifest,
    Object.fromEntries(manifestPaths(bigManifest).map((p) => [p, { disposition: "revise" }])),
  );
  const thirteenNodes = inputFor(
    bigContext,
    {},
    {
      selected_units: manifestPaths(bigManifest).map((path, i) => ({
        title: `U${i + 1}`,
        roadmap_node: `${i + 1}.1`,
        docs: [path],
        rationale: "r",
      })),
    },
  );
  assert.deepEqual(refusalDetails(thirteenNodes, bigContext), [
    `selected units name 13 distinct roadmap nodes — the cap is ${MAX_ROADMAP_NODES}`,
  ]);
});

test("units: overflow-only reports pass; the zero-unit all-keep report passes (no action)", () => {
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_CTX]: { disposition: "revise" },
    [DOC_SUB]: { disposition: "revise" },
  });
  const overflowOnly = inputFor(
    context,
    {},
    {
      selected_units: [],
      overflow_units: [{ title: "Later", docs: [DOC_CTX, DOC_SUB], rationale: "deferred" }],
    },
  );
  assert.equal(buildDreamReport(overflowOnly, context).ok, true);

  const allKeep = contextFor(manifest);
  const noAction = validReport(inputFor(allKeep), allKeep);
  assert.deepEqual(noAction.selected_units, []);
  assert.deepEqual(noAction.overflow_units, []);
  assert.ok(
    noAction.rows.every((row) => row.fallback_reason === null),
    "every all-keep row carries fallback_reason: null",
  );
});

// ------------------------------------------------------- harvest follow-ups (D8)

test("harvest follow-ups must cite surviving destinations (doc or cluster)", () => {
  const manifest = fixtureManifest();
  const followup = (destination: string): DreamReportInput["harvest_followups"][number] => ({
    title: "F",
    destination,
    pointer: "extension/waves/reportWave.ts",
    evidence: "cited",
  });

  // Surviving doc + surviving cluster destinations pass.
  const surviving = contextFor(manifest, { [DOC_CTX]: { disposition: "revise" } });
  const pass = inputFor(
    surviving,
    {},
    { harvest_followups: [followup(DOC_CTX), followup(DOC_SUB), followup("pi-extension")] },
  );
  assert.equal(buildDreamReport(pass, surviving).ok, true);

  // A retired doc destination refuses; its dead cluster refuses too (its only member died).
  const retiring = contextFor(manifest, { [DOC_WAVES]: { disposition: "retire" } });
  assert.deepEqual(
    refusalDetails(inputFor(retiring, {}, { harvest_followups: [followup(DOC_WAVES)] }), retiring),
    [
      `harvest follow-up 1 ('F') destination '${DOC_WAVES}' is a corpus doc that does not ` +
        "survive (final disposition 'retire') — repoint the follow-up at a survivor",
    ],
  );
  assert.deepEqual(
    refusalDetails(inputFor(retiring, {}, { harvest_followups: [followup("workflow")] }), retiring),
    [
      "harvest follow-up 1 ('F') destination 'workflow' is a cluster with no surviving keep/revise member",
    ],
  );

  // A merged-away doc destination refuses.
  const merging = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
  });
  const merged = refusalDetails(
    inputFor(merging, {}, { harvest_followups: [followup(DOC_SUB)] }),
    merging,
  );
  assert.match(merged[0] as string, /does not survive \(final disposition 'merge-into'\)/);

  // An unknown destination and an empty pointer refuse.
  const keep = contextFor(manifest);
  assert.deepEqual(
    refusalDetails(inputFor(keep, {}, { harvest_followups: [followup("nowhere")] }), keep),
    [
      "harvest follow-up 1 ('F') destination 'nowhere' is neither a surviving corpus doc nor " +
        "a cluster named by a surviving doc",
    ],
  );
  assert.deepEqual(
    refusalDetails(
      inputFor(keep, {}, { harvest_followups: [{ ...followup(DOC_CTX), pointer: "" }] }),
      keep,
    ),
    ["harvest follow-up 1 ('F') pointer must be non-empty"],
  );
});

// ------------------------------------------------------- predicted effects (D9)

test("predicted effects carry NO quota rule: a growth prediction is valid (vacuity proof)", () => {
  const context = contextFor(fixtureManifest());
  const grown = inputFor(
    context,
    {},
    {
      predicted_effects: {
        docs_after: context.manifest.doc_count + 40,
        bytes_after: context.manifest.total_bytes * 10,
        note: "the corpus is predicted to GROW",
      },
    },
  );
  const report = validReport(grown, context);
  // The vacuity proof: the accepted prediction really is growth in both dimensions.
  assert.ok(report.predicted_effects.docs_after > report.predicted_effects.docs_before);
  assert.ok(report.predicted_effects.bytes_after > report.predicted_effects.bytes_before);
});

// ----------------------------------------------------- bounded error collection (D11)

test("semantic violations collect across phases in deterministic order", () => {
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_CTX]: { disposition: "revise" },
    [DOC_SUB]: { disposition: "revise" },
  });
  const input = inputFor(
    context,
    { [DOC_CTX]: { rationale: "" } },
    {
      selected_units: [{ title: "U", roadmap_node: "2.1", docs: [DOC_CTX], rationale: "r" }],
      harvest_followups: [
        { title: "F", destination: "nowhere", pointer: "src/x.ts", evidence: "e" },
      ],
    },
  );
  assert.deepEqual(refusalDetails(input, context), [
    `row '${DOC_CTX}' rationale must be non-empty`,
    `non-keep doc '${DOC_SUB}' is not covered by any curation unit — selected + overflow ` +
      "units must partition the non-keep docs exactly",
    "harvest follow-up 1 ('F') destination 'nowhere' is neither a surviving corpus doc nor " +
      "a cluster named by a surviving doc",
  ]);
});

test("collection is bounded: >25 violations truncate with the synthetic count detail", () => {
  const manifest = genManifest(30);
  const paths = manifestPaths(manifest);
  const context = contextFor(
    manifest,
    Object.fromEntries(paths.map((p) => [p, { disposition: "revise" }])),
  );
  const input = inputFor(context, Object.fromEntries(paths.map((p) => [p, { rationale: "" }])));
  const details = refusalDetails(input, context);
  assert.equal(details.length, MAX_VALIDATION_DETAILS + 1);
  assert.equal(details[0], "row 'docs/learned/gen/doc-000.md' rationale must be non-empty");
  for (const detail of details.slice(0, MAX_VALIDATION_DETAILS)) {
    assert.match(detail, /rationale must be non-empty/);
  }
  assert.equal(
    details[MAX_VALIDATION_DETAILS],
    `…and 5 more validation detail(s) omitted (cap ${MAX_VALIDATION_DETAILS})`,
  );
});

// ------------------------------------------------------------- the composed report

test("the composed report joins validated input with injected context (manifest order)", () => {
  const context = fixtureContext();
  // Reverse the row order and the unit's doc order so the manifest-order assertion below
  // actually exercises normalization (input order must never leak into the composed rows).
  const shuffledInput = (): DreamReportInput => {
    const input = fixtureInput();
    input.rows.reverse();
    (input.selected_units[0] as { docs: string[] }).docs.reverse();
    return input;
  };
  const result = buildDreamReport(shuffledInput(), context);
  assert.equal(result.ok, true, JSON.stringify(result));
  const { report, parts } = result as { ok: true; report: DreamReport; parts: string[] };

  assert.deepEqual(report.snapshot, {
    schema_version: SCHEMA_VERSION,
    run_id: RUN_ID,
    generated_at: GENERATED_AT,
    commit_sha: "abc123",
    registry_mode: "clusters",
    doc_count: 3,
    total_bytes: 350,
  });
  assert.deepEqual(
    report.rows.map((row) => [row.path, row.analyst_disposition, row.final_disposition]),
    [
      [DOC_CTX, "revise", "revise"],
      [DOC_SUB, "merge-into", "merge-into"],
      [DOC_WAVES, "retire", "revise"],
    ],
    "rows are normalized to manifest lane/doc order",
  );
  assert.deepEqual(
    report.rows[1]?.stances.map((s) => [s.angle, s.stance]),
    [
      ["consolidation-preservation", "endorse"],
      ["currency-accuracy", "endorse"],
    ],
    "injected stances join in fixed angle order",
  );
  assert.deepEqual(
    report.rows[2]?.stances.map((s) => [s.angle, s.stance]),
    [
      ["consolidation-preservation", "endorse"],
      ["currency-accuracy", "challenge"],
    ],
  );
  assert.deepEqual(
    report.rows
      .filter((row) => row.fallback_reason !== null)
      .map((row) => [
        row.path,
        row.analyst_disposition,
        row.analyst_merge_target,
        row.final_disposition,
        row.fallback_reason,
      ]),
    [[DOC_WAVES, "retire", null, "revise", "currency-accuracy challenged the retire"]],
  );
  assert.deepEqual(report.coverage.analysts, [
    {
      lane: "pi-extension-1",
      docs: 2,
      overlap_signals_omitted: 2,
      harvest_followups_omitted: 0,
      uncertainties_omitted: 0,
    },
    {
      lane: "workflow-1",
      docs: 1,
      overlap_signals_omitted: 0,
      harvest_followups_omitted: 0,
      uncertainties_omitted: 0,
    },
  ]);
  assert.deepEqual(report.coverage.reducers, [
    {
      angle: "consolidation-preservation",
      stances: 2,
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
    },
    {
      angle: "currency-accuracy",
      stances: 2,
      stances_omitted: 1,
      angle_findings_omitted: 0,
      uncertainties_omitted: 3,
    },
    {
      angle: "knowledge-architecture",
      stances: 0,
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
    },
  ]);
  assert.deepEqual(report.uncertainties.parent, ["unsure the merged doc needs a new cue"]);
  assert.deepEqual(report.uncertainties.analysts, [
    { lane: "pi-extension-1", items: ["unsure the cue survives a merge"] },
    { lane: "workflow-1", items: [] },
  ]);
  assert.deepEqual(report.uncertainties.reducers[1], {
    angle: "currency-accuracy",
    items: ["the retire may be premature"],
  });
  assert.deepEqual(report.predicted_effects, {
    docs_before: 3,
    bytes_before: 350,
    docs_after: 2,
    bytes_after: 300,
    note: "one merge lands",
  });
  assert.deepEqual(
    JSON.parse(JSON.stringify(report)),
    report,
    "the composed report is JSON-serializable",
  );

  // The composed report is deterministic: a second build over the same input agrees.
  const rebuilt = buildDreamReport(shuffledInput(), context);
  assert.deepEqual((rebuilt as { ok: true; report: DreamReport }).report, report);
  assert.equal(parts.length, 1);
});

// ------------------------------------------------------------------- the renderer

test("the renderer: repeated builds yield byte-identical parts", () => {
  const first = buildDreamReport(fixtureInput(), fixtureContext());
  const second = buildDreamReport(fixtureInput(), fixtureContext());
  assert.equal(first.ok, true);
  assert.deepEqual(first, second);
});

/** The canonical bytes of the happy fixture's single part — a full-render pin. */
const PINNED_PART = `# Dream report — 01RUNDREAM

## Snapshot

- Run: 01RUNDREAM
- Report schema version: 1
- Commit: abc123
- Generated at: 2026-02-03T04:05:06Z
- Registry mode: clusters
- Docs: 3
- Total bytes: 350

## Findings summary

| Family | Count |
| --- | --- |
| structural.stale_pointers | 1 |
| structural.broken_doc_paths | 0 |
| structural.duplicate_cues | 0 |
| structural.missing_frontmatter | 0 |
| advisory.distillation_issues | 0 |
| advisory.source_code_blocks | 0 |
| advisory.overlong_cues | 0 |
| advisory.cue_hazards | 0 |
| advisory.empty_clusters | 1 |

## Wave coverage

### Analyst lanes

| Lane | Docs | Overlap signals omitted | Harvest follow-ups omitted | Uncertainties omitted |
| --- | --- | --- | --- | --- |
| pi-extension-1 | 2 | 2 | 0 | 0 |
| workflow-1 | 1 | 0 | 0 | 0 |

### Reducer angles

| Angle | Stances | Stances omitted | Angle findings omitted | Uncertainties omitted |
| --- | --- | --- | --- | --- |
| consolidation-preservation | 2 | 0 | 0 | 0 |
| currency-accuracy | 2 | 1 | 0 | 3 |
| knowledge-architecture | 0 | 0 | 0 | 0 |

## Dispositions

| Doc | Cluster | Analyst | Final | Merge target | Confidence | Rationale |
| --- | --- | --- | --- | --- | --- | --- |
| docs/learned/pi/context-injection.md | pi-extension | revise | revise | — | high | refresh the drifted cue |
| docs/learned/pi/subagents.md | — | merge-into → docs/learned/workflow/report-waves.md | merge-into | docs/learned/workflow/report-waves.md | medium | both gates endorse the merge |
| docs/learned/workflow/report-waves.md | workflow | retire | revise | — | low | refresh instead of retire |

## Non-keep evidence

### docs/learned/pi/context-injection.md

- Analyst rationale: the cue drifted
- Preserve: the injection table
- Evidence checked: extension/context.ts

- No reducer stances recorded (silence is non-endorsement).

### docs/learned/pi/subagents.md

- Analyst rationale: duplicates report-waves
- Preserve: —
- Evidence checked: extension/waves/reportWave.ts

- consolidation-preservation: endorse — the target covers it (checked: docs/learned/workflow/report-waves.md)
- currency-accuracy: endorse — claims verified current (checked: extension/waves/reportWave.ts)

### docs/learned/workflow/report-waves.md

- Analyst rationale: superseded by newer docs
- Preserve: —
- Evidence checked: —

- consolidation-preservation: endorse — content preserved elsewhere (checked: —)
- currency-accuracy: challenge — still cited by the index (checked: docs/learned/index.md)

## Fallbacks

### docs/learned/workflow/report-waves.md

- Analyst proposal: retire
- Final: revise
- Reason: currency-accuracy challenged the retire

## Uncertainties

- Parent: unsure the merged doc needs a new cue
- Analyst pi-extension-1: unsure the cue survives a merge
- Reducer currency-accuracy: the retire may be premature

## Reducer findings

- consolidation-preservation: the two pi docs overlap
- knowledge-architecture: cluster routing stays coherent

## Selected curation units

**1. Merge subagents guidance into report-waves** — node \`2.1\`
- Docs: docs/learned/pi/subagents.md; docs/learned/pi/context-injection.md
- Rationale: one focused PR

## Overflow

**1. Refresh report-waves after the merge**
- Docs: docs/learned/workflow/report-waves.md
- Rationale: lower-priority follow-on

## Harvest follow-ups

| Title | Destination | Pointer | Evidence |
| --- | --- | --- | --- |
| Extract the shared wave helper | docs/learned/workflow/report-waves.md | extension/waves/reportWave.ts | both dream waves duplicate the retry shape |

## Predicted effects

- Docs: 3 → 2
- Bytes: 350 → 300
- Note: one merge lands

_Predictions are not quotas._
`;

test("the renderer: the pinned full-fixture snapshot", () => {
  const rendered = buildDreamReport(fixtureInput(), fixtureContext());
  assert.equal(rendered.ok, true, JSON.stringify(rendered).slice(0, 400));
  const parts = (rendered as { ok: true; parts: string[] }).parts;
  assert.equal(parts.length, 1);
  assert.equal(parts[0], PINNED_PART);
});

test("the renderer: part splitting under the code-point cap with header re-emission", () => {
  const docCount = 200;
  const manifest = genManifest(docCount);
  const paths = manifestPaths(manifest);
  const context = contextFor(
    manifest,
    Object.fromEntries(paths.map((p) => [p, { disposition: "revise" }])),
  );
  // Astral rationale: each 𝛼 is ONE code point but TWO UTF-16 units — 290 code points stays
  // under the rowRationaleChars cap while doubling the string's UTF-16 length.
  const longRationale = "𝛼".repeat(290);
  const input = inputFor(
    context,
    Object.fromEntries(paths.map((p) => [p, { rationale: longRationale }])),
  );
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, true, JSON.stringify(result).slice(0, 400));
  const parts = (result as { ok: true; parts: string[] }).parts;
  assert.ok(parts.length >= 2, `expected a split, got ${parts.length} part(s)`);
  for (const part of parts) {
    assert.ok(codePointLength(part) <= PART_MAX_CHARS, "every part stays under the code-point cap");
  }
  // The discriminating pin: packing measured in UTF-16 units would split earlier and never
  // produce a part whose UTF-16 length exceeds the cap while its code-point length fits.
  assert.ok(
    parts.some((part) => part.length > PART_MAX_CHARS && codePointLength(part) <= PART_MAX_CHARS),
    "the part cap is measured in code points, not UTF-16 units",
  );
  assert.ok(parts[0]?.startsWith(`# Dream report — ${RUN_ID}\n\n`), "the first part's header");
  for (const [index, part] of parts.entries()) {
    if (index === 0) continue;
    assert.ok(
      part.startsWith(
        `# Dream report — ${RUN_ID} (continued, part ${index + 1} of ${parts.length})\n\n`,
      ),
      `part ${index + 1}'s continuation header`,
    );
  }
  // The dispositions table (200 rows × ~350 chars) spans the first part boundary — the next
  // part re-emits the table header row before the continuing rows.
  const continuation = (parts[1] as string).split("\n");
  assert.equal(
    continuation[2],
    "| Doc | Cluster | Analyst | Final | Merge target | Confidence | Rationale |",
    "the table header row is re-emitted after a mid-table split",
  );
  assert.equal(continuation[3], "| --- | --- | --- | --- | --- | --- | --- |");
  assert.match(continuation[4] ?? "", /^\| docs\/learned\/gen\/doc-\d{3}\.md \|/);
});

test("the renderer: injected pipes/newlines sanitize in cells and bullets", () => {
  const manifest = fixtureManifest();
  const context = contextFor(
    manifest,
    { [DOC_CTX]: { disposition: "revise", rationale: "first\nsecond | third" } },
    { "currency-accuracy": [stanceOf(DOC_CTX, "revise", "endorse", "line1\nline2")] },
  );
  const input = inputFor(context, { [DOC_CTX]: { rationale: "cell | pipe" } });
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, true, JSON.stringify(result));
  const text = (result as { ok: true; parts: string[] }).parts.join("\n");
  assert.ok(
    text.includes(`| ${DOC_CTX} | pi-extension | revise | revise | — | high | cell \\| pipe |`),
    "a model-supplied pipe is escaped in the dispositions cell",
  );
  assert.ok(
    text.includes("- Analyst rationale: first second \\| third"),
    "injected newlines collapse and pipes escape in bullets",
  );
  assert.ok(
    text.includes("- currency-accuracy: endorse — line1 line2 (checked: —)"),
    "injected stance reasons sanitize in bullets",
  );
});

test("the renderer: an oversized bullet-list section splits at line boundaries", () => {
  // A cap-conformant report whose §7 uncertainty bullets alone (35 lanes × 6 × ~310 code
  // points ≈ 65K) exceed the packing budget — rendered as ONE joined block this exact input
  // hits the oversize refusal; per-line grouping splits it at bullet boundaries instead.
  const manifest = genManifest(280);
  const base = contextFor(manifest);
  const uncertainty = "u".repeat(290);
  const context: DreamReportContext = {
    ...base,
    analyses: base.analyses.map((analysis) => ({
      ...analysis,
      report: {
        ...analysis.report,
        uncertainties: Array.from({ length: 6 }, () => uncertainty),
      },
    })),
  };
  const input = inputFor(context);
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, true, JSON.stringify(result).slice(0, 400));
  const parts = (result as { ok: true; parts: string[] }).parts;
  assert.ok(parts.length >= 2, `expected a split inside §7, got ${parts.length} part(s)`);
  for (const part of parts) {
    assert.ok(codePointLength(part) <= PART_MAX_CHARS, "every part stays under the code-point cap");
  }
  const text = parts.join("\n");
  assert.equal(
    text.split("## Uncertainties").length - 1,
    1,
    "the section heading renders exactly once across all parts",
  );
  assert.equal(
    text.split("- Analyst gen-").length - 1,
    context.analyses.length * 6,
    "every uncertainty bullet renders exactly once",
  );
});

test("the renderer: a final-keep fallback renders its stances in §6 exactly once", () => {
  // A destructive proposal (both gates endorsing) downgraded to final keep with a fallback
  // reason: the doc never reaches §5, and its injected stances render under §6 — the
  // exactly-once §5-or-§6 rule.
  const manifest = fixtureManifest();
  const context = contextFor(manifest, {
    [DOC_SUB]: { disposition: "merge-into", merge_target: DOC_WAVES },
  });
  const input = inputFor(context, {
    [DOC_SUB]: { disposition: "keep", merge_target: null, fallback_reason: "kept after all" },
  });
  const result = buildDreamReport(input, context);
  assert.equal(result.ok, true, JSON.stringify(result));
  const { report, parts } = result as { ok: true; report: DreamReport; parts: string[] };
  const text = parts.join("\n");
  const nonKeepSection = text.slice(
    text.indexOf("## Non-keep evidence"),
    text.indexOf("## Fallbacks"),
  );
  assert.ok(
    !nonKeepSection.includes(`### ${DOC_SUB}`),
    "the final-keep doc's heading never appears under §5",
  );
  const fallbacksSection = text.slice(
    text.indexOf("## Fallbacks"),
    text.indexOf("## Uncertainties"),
  );
  assert.ok(fallbacksSection.includes(`### ${DOC_SUB}`), "the fallback doc renders under §6");
  const subRow = report.rows.find((row) => row.path === DOC_SUB);
  const stances = subRow?.stances ?? [];
  assert.equal(stances.length, 2, "both gate endorsements joined onto the row");
  for (const stance of stances) {
    const line = `- ${stance.angle}: ${stance.stance} — ${stance.reason} (checked: —)`;
    assert.ok(fallbacksSection.includes(line), `the stance bullet renders under §6: ${line}`);
    assert.equal(text.split(line).length - 1, 1, `the stance line renders exactly once: ${line}`);
  }
});

test("the renderer: a single oversize block refuses (never truncates)", () => {
  // INJECTED (trusted-context) prose is not cap-bounded, so an oversized analyst rationale
  // reaches the renderer's defensive arm through the one entry: the §5 evidence bullet block
  // for the non-keep doc exceeds the packing budget in a single block.
  const context = fixtureContext();
  const analysis = context.analyses[0] as DreamLaneAnalysis;
  (analysis.report.docs[0] as { rationale: string }).rationale = "x".repeat(PART_MAX_CHARS);
  const result = buildDreamReport(fixtureInput(), context);
  assert.equal(result.ok, false);
  const details = (result as { ok: false; details: string[] }).details;
  assert.equal(details.length, 1, "the renderer's single-detail arm wraps into one detail");
  assert.match(details[0] as string, /exceeds the part packing budget .* refusing to truncate/);
});
