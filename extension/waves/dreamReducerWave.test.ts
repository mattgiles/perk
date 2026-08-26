// The dream reducer wave module's suite (the dreamWave.test.ts matrix shape): the bundle
// serialization (deterministic bytes, identity echoes, UTF-8 byte measurement, the ONE
// happy-path ordering pin), the finalized-bundle round-trip + the strict recovery decode (the
// closed-wrapper/whitelist-projected-row unknown-key policy, both sides), the ordered non-keep
// proposal universe, the schema↔caps lockstep,
// the composed defensive re-decode (the angle/disposition echo rules, proposal membership,
// code-point caps, whitelisted construction), the strict-completeness runner over the memory
// adapter (fixed angle lanes, requestedKeys, model/signal forwarding), and the agent-def ↔
// report-schema prose lockstep pin (+ the delivered `.pi/agents/perk/` mirror). Fully offline.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import {
  composeDreamBundle,
  DREAM_ANALYSES_FILENAME,
  DREAM_BUNDLE_BUDGET_BYTES,
  DREAM_REDUCER_ANGLES,
  DREAM_REDUCER_CAPS,
  DREAM_REDUCER_REPORT_SCHEMA,
  type DreamProposal,
  type DreamReducerAnalysis,
  type DreamReducerReport,
  type DreamStance,
  decodeDreamReducerReport,
  decodeFinalizedDreamBundle,
  finalizeDreamBundle,
  nonKeepProposals,
  runDreamReducerWave,
} from "./dreamReducerWave.ts";
import {
  type DreamDocAssessment,
  type DreamLaneAnalysis,
  type DreamManifest,
  decodeDreamManifest,
} from "./dreamWave.ts";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";
import { RUN_KEY_PATTERN } from "./reportWave.ts";

const MANIFEST_PATH = "/abs/scratch/runs/RUN/dream-manifest.json";
const BUNDLE_PATH = `/abs/scratch/runs/RUN/${DREAM_ANALYSES_FILENAME}`;

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

function fixtureManifest(): DreamManifest {
  const raw = {
    schema_version: "1",
    commit_sha: "abc123",
    registry_mode: "clusters",
    doc_count: 3,
    total_bytes: 350,
    findings: emptyFindings(),
    lanes: [
      {
        id: "pi-extension-1",
        rollup: "Pi SDK craft",
        docs: [
          {
            path: "docs/learned/pi/context-injection.md",
            title: "T",
            read_when: "cue",
            cluster: "pi-extension",
            bytes: 100,
          },
          {
            path: "docs/learned/pi/subagents.md",
            title: null,
            read_when: null,
            cluster: null,
            bytes: 200,
          },
        ],
      },
      {
        id: "workflow-1",
        rollup: null,
        docs: [
          {
            path: "docs/learned/workflow/report-waves.md",
            title: null,
            read_when: null,
            cluster: "workflow",
            bytes: 50,
          },
        ],
      },
    ],
  };
  const decoded = decodeDreamManifest(raw, MANIFEST_PATH);
  assert.equal(decoded.ok, true, JSON.stringify(decoded));
  return (decoded as { ok: true; manifest: DreamManifest }).manifest;
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

function analysisOf(lane: string, docs: DreamDocAssessment[]): DreamLaneAnalysis {
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
    },
  };
}

/** Manifest-lane-order analyses with a mixed disposition spread (2 non-keep, 1 keep, 1 retire). */
function fixtureAnalyses(): DreamLaneAnalysis[] {
  return [
    analysisOf("pi-extension-1", [
      assessment("docs/learned/pi/context-injection.md", { disposition: "revise" }),
      assessment("docs/learned/pi/subagents.md", {
        disposition: "merge-into",
        merge_target: "docs/learned/workflow/report-waves.md",
      }),
    ]),
    analysisOf("workflow-1", [
      assessment("docs/learned/workflow/report-waves.md", { disposition: "retire" }),
    ]),
  ];
}

const PROPOSALS: readonly DreamProposal[] = [
  { doc: "docs/learned/pi/context-injection.md", disposition: "revise" },
  { doc: "docs/learned/pi/subagents.md", disposition: "merge-into" },
  { doc: "docs/learned/workflow/report-waves.md", disposition: "retire" },
];

function stanceRow(doc: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const disposition = PROPOSALS.find((p) => p.doc === doc)?.disposition ?? "revise";
  return {
    doc,
    disposition,
    stance: "endorse",
    reason: "verified against the checkout",
    evidence_checked: ["re-read the cited pointer"],
    ...overrides,
  };
}

const ANGLE = DREAM_REDUCER_ANGLES[0];

function reducerReportOf(
  angle: string = ANGLE,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    angle,
    stances: [],
    angle_findings: [],
    uncertainties: [],
    stances_omitted: 0,
    angle_findings_omitted: 0,
    uncertainties_omitted: 0,
    ...overrides,
  };
}

/** Parse the lane items the module rendered into the spawned workflowScript. */
function spawnedLaneItems(
  script: string,
): { key: string; agent: string; task: string; label: string; phase?: string }[] {
  return waveScriptItems(script) as {
    key: string;
    agent: string;
    task: string;
    label: string;
    phase?: string;
  }[];
}

// -------------------------------------------------------------------------- the bundle

test("composeDreamBundle: deterministic bytes, identity echoes, manifest lane order (the ONE ordering pin)", () => {
  const manifest = fixtureManifest();
  const analyses = fixtureAnalyses();
  const first = composeDreamBundle(manifest, analyses);
  const second = composeDreamBundle(manifest, analyses);
  assert.equal(first.content, second.content, "the serialization is deterministic");
  assert.equal(first.bytes, second.bytes);
  assert.ok(first.content.endsWith("\n"), "trailing newline");

  const bundle = JSON.parse(first.content) as {
    schema_version: string;
    commit_sha: string;
    registry_mode: string;
    doc_count: number;
    total_bytes: number;
    lanes: { lane: string; report: unknown }[];
  };
  assert.equal(bundle.schema_version, "1");
  assert.equal(bundle.commit_sha, "abc123");
  assert.equal(bundle.registry_mode, "clusters");
  assert.equal(bundle.doc_count, 3);
  assert.equal(bundle.total_bytes, 350);
  // The ordering pin: a complete wave's analyses are already in manifest lane order (the
  // runner's spec.lanes-order normalization + buildDreamLanes' manifest-order plan), so the
  // serialized lanes carry that order — no re-sort layer exists.
  assert.deepEqual(
    bundle.lanes.map((lane) => lane.lane),
    ["pi-extension-1", "workflow-1"],
  );
  assert.deepEqual(bundle.lanes[0]?.report, analyses[0]?.report);
});

test("composeDreamBundle: bytes are UTF-8 bytes, not UTF-16 units or code points", () => {
  const manifest = fixtureManifest();
  const analyses = fixtureAnalyses();
  const astral = analysisOf("workflow-1", [
    assessment("docs/learned/workflow/report-waves.md", {
      disposition: "retire",
      rationale: "😀".repeat(10),
    }),
  ]);
  const { content, bytes } = composeDreamBundle(manifest, [
    analyses[0] as DreamLaneAnalysis,
    astral,
  ]);
  assert.equal(bytes, Buffer.byteLength(content, "utf8"));
  assert.ok(bytes > content.length, "astral chars weigh 4 UTF-8 bytes but 2 UTF-16 units");
});

test("DREAM_BUNDLE_BUDGET_BYTES is 384 KiB", () => {
  assert.equal(DREAM_BUNDLE_BUDGET_BYTES, 393216);
  assert.equal(DREAM_BUNDLE_BUDGET_BYTES, 384 * 1024);
});

// ---------------------------------------------------------------- the finalized bundle

/** The arbitrary manifest-bytes digest the finalized fixtures bind (opaque to this module —
 * real digests are computed by the door and the recovery path over the on-disk bytes). */
const MANIFEST_DIGEST = "sha256:fixture-manifest-digest";

function typedStance(doc: string): DreamStance {
  const disposition = PROPOSALS.find((p) => p.doc === doc)?.disposition ?? "revise";
  return {
    doc,
    disposition,
    stance: "endorse",
    reason: "verified against the checkout",
    evidence_checked: ["re-read the cited pointer"],
  };
}

/** Typed reducer analyses over the fixture proposals, in the fixed angle order. */
function fixtureReducers(): DreamReducerAnalysis[] {
  return DREAM_REDUCER_ANGLES.map((angle, index) => ({
    angle,
    report: {
      stances: index === 0 ? [typedStance("docs/learned/pi/context-injection.md")] : [],
      angle_findings: index === 1 ? ["cross-lane redundancy between the two pi docs"] : [],
      uncertainties: [],
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
    },
  }));
}

/** The parsed finalized fixture (each test mutates its own copy). */
function finalizedRaw(): Record<string, unknown> {
  return JSON.parse(
    finalizeDreamBundle(fixtureManifest(), fixtureAnalyses(), fixtureReducers(), MANIFEST_DIGEST),
  ) as Record<string, unknown>;
}

test("finalizeDreamBundle ↔ decodeFinalizedDreamBundle: deterministic round-trip, raw echo shape", () => {
  const manifest = fixtureManifest();
  const analyses = fixtureAnalyses();
  const reducers = fixtureReducers();
  const first = finalizeDreamBundle(manifest, analyses, reducers, MANIFEST_DIGEST);
  assert.equal(
    first,
    finalizeDreamBundle(manifest, analyses, reducers, MANIFEST_DIGEST),
    "deterministic bytes",
  );
  assert.ok(first.endsWith("\n"), "trailing newline (the composeDreamBundle convention)");

  const parsed = JSON.parse(first) as Record<string, unknown>;
  // The wrapper is the composeDreamBundle shape plus manifest_digest + reducers — nothing else.
  assert.deepEqual(Object.keys(parsed), [
    "schema_version",
    "commit_sha",
    "registry_mode",
    "doc_count",
    "total_bytes",
    "manifest_digest",
    "lanes",
    "reducers",
  ]);
  assert.equal(parsed.schema_version, "1", "schema_version stays 1");
  assert.equal(parsed.manifest_digest, MANIFEST_DIGEST, "the manifest digest is bound in");
  // Each reducer entry is the RAW ECHO shape {angle, ...report} — what the row decoder accepts.
  const entries = parsed.reducers as Record<string, unknown>[];
  assert.deepEqual(
    entries.map((entry) => entry.angle),
    [...DREAM_REDUCER_ANGLES],
  );
  assert.deepEqual(Object.keys(entries[0] ?? {}), [
    "angle",
    "stances",
    "angle_findings",
    "uncertainties",
    "stances_omitted",
    "angle_findings_omitted",
    "uncertainties_omitted",
  ]);

  const decoded = decodeFinalizedDreamBundle(parsed, manifest, MANIFEST_DIGEST);
  assert.equal(decoded.ok, true, JSON.stringify(decoded));
  const value = decoded as { ok: true; analyses: DreamLaneAnalysis[]; reducers: unknown };
  assert.deepEqual(value.analyses, analyses, "the analyses round-trip byte-equivalently");
  assert.deepEqual(value.reducers, reducers, "the reducers round-trip byte-equivalently");
});

test("decodeFinalizedDreamBundle: each refusal arm carries its named detail", () => {
  const manifest = fixtureManifest();
  const swap = <T>(items: T[], a: number, b: number): T[] => {
    const out = [...items];
    const tmp = out[a] as T;
    out[a] = out[b] as T;
    out[b] = tmp;
    return out;
  };
  const arms: { label: string; raw: () => unknown; detail: RegExp }[] = [
    { label: "non-object", raw: () => "nope", detail: /not an object/ },
    {
      label: "the analyses-only mid-wave shape (no reducers key)",
      raw: () => JSON.parse(composeDreamBundle(manifest, fixtureAnalyses()).content),
      detail: /no reducers section — the dream wave did not finalize/,
    },
    {
      label: "an unknown wrapper key",
      raw: () => ({ ...finalizedRaw(), smuggled: 1 }),
      detail: /unknown wrapper key 'smuggled'/,
    },
    {
      label: "wrong schema_version",
      raw: () => ({ ...finalizedRaw(), schema_version: "2" }),
      detail: /schema_version must be the string "1"/,
    },
    {
      label: "a manifest cross-check mismatch",
      raw: () => ({ ...finalizedRaw(), commit_sha: "other" }),
      detail: /commit_sha \("other"\) does not match the manifest's \("abc123"\)/,
    },
    {
      label: "a manifest_digest mismatch (the manifest changed after the wave finalized)",
      raw: () => ({ ...finalizedRaw(), manifest_digest: "sha256:other" }),
      detail:
        /manifest_digest \("sha256:other"\) does not match the digest of the manifest just read/,
    },
    {
      label: "a missing lane",
      raw: () => {
        const raw = finalizedRaw();
        raw.lanes = (raw.lanes as unknown[]).slice(0, 1);
        return raw;
      },
      detail: /carries 1 lane\(s\), the manifest has 2 — the lanes must pair exactly/,
    },
    {
      label: "reordered lanes",
      raw: () => {
        const raw = finalizedRaw();
        raw.lanes = swap(raw.lanes as unknown[], 0, 1);
        return raw;
      },
      detail: /lane 1 is "workflow-1", the manifest's lane is 'pi-extension-1'/,
    },
    {
      label: "an unknown lane-entry key",
      raw: () => {
        const raw = finalizedRaw();
        const lane = (raw.lanes as Record<string, unknown>[])[0] as Record<string, unknown>;
        lane.smuggled = 1;
        return raw;
      },
      detail: /lane entry 1 carries an unknown key 'smuggled'/,
    },
    {
      label: "a lane report the analyst re-decode rejects",
      raw: () => {
        const raw = finalizedRaw();
        const lane = (raw.lanes as { report: { docs: { disposition: string }[] } }[])[0];
        (lane as { report: { docs: { disposition: string }[] } }).report.docs[0] = {
          ...(lane as { report: { docs: { disposition: string }[] } }).report.docs[0],
          disposition: "bogus",
        } as { disposition: string };
        return raw;
      },
      detail: /dream bundle lane 'pi-extension-1': .*outside the vocabulary/,
    },
    {
      label: "a missing reducer angle",
      raw: () => {
        const raw = finalizedRaw();
        raw.reducers = (raw.reducers as unknown[]).slice(0, 2);
        return raw;
      },
      detail: /carries 2 reducer entrie\(s\) — exactly the 3 fixed angles/,
    },
    {
      label: "an extra reducer entry",
      raw: () => {
        const raw = finalizedRaw();
        const entries = raw.reducers as unknown[];
        raw.reducers = [...entries, entries[0]];
        return raw;
      },
      detail: /carries 4 reducer entrie\(s\) — exactly the 3 fixed angles/,
    },
    {
      label: "reordered reducer angles (the byte-exact echo refuses)",
      raw: () => {
        const raw = finalizedRaw();
        raw.reducers = swap(raw.reducers as unknown[], 0, 1);
        return raw;
      },
      detail:
        /reducer 'consolidation-preservation': reducer report echoes angle "currency-accuracy"/,
    },
    {
      label: "a duplicated reducer angle",
      raw: () => {
        const raw = finalizedRaw();
        const entries = raw.reducers as unknown[];
        raw.reducers = [entries[0], entries[0], entries[2]];
        return raw;
      },
      detail:
        /reducer 'currency-accuracy': reducer report echoes angle "consolidation-preservation"/,
    },
    {
      label: "an unknown reducer-entry key",
      raw: () => {
        const raw = finalizedRaw();
        const entry = (raw.reducers as Record<string, unknown>[])[0] as Record<string, unknown>;
        entry.smuggled = 1;
        return raw;
      },
      detail: /reducer entry 'consolidation-preservation' carries an unknown key 'smuggled'/,
    },
    {
      label: "a stance doc outside the proposal universe",
      raw: () => {
        const raw = finalizedRaw();
        const entry = (raw.reducers as { stances: unknown[] }[])[0] as { stances: unknown[] };
        entry.stances = [stanceRow("docs/learned/gone.md", { disposition: "revise" })];
        return raw;
      },
      detail: /not one of the analysts' non-keep proposals/,
    },
  ];
  for (const arm of arms) {
    const result = decodeFinalizedDreamBundle(arm.raw(), manifest, MANIFEST_DIGEST);
    assert.equal(result.ok, false, `must refuse: ${arm.label}`);
    assert.match((result as { detail: string }).detail, arm.detail, arm.label);
  }
});

test("decodeFinalizedDreamBundle: the pinned row-level policy — an extra key INSIDE a stance row is ignored", () => {
  // The other half of the closed-wrapper/whitelist-projected-row policy: closure is enforced
  // only at the levels this decoder authors; INSIDE a row the reused row decoders are the
  // single authority — whitelisted construction, so the extra key never survives into the
  // typed value (and never refuses).
  const raw = finalizedRaw();
  const stances = (raw.reducers as { stances: Record<string, unknown>[] }[])[0]?.stances ?? [];
  (stances[0] as Record<string, unknown>).smuggled = "an extra row-level key";
  const result = decodeFinalizedDreamBundle(raw, fixtureManifest(), MANIFEST_DIGEST);
  assert.equal(result.ok, true, JSON.stringify(result));
  const decoded = result as { ok: true; reducers: DreamReducerAnalysis[] };
  const stance = decoded.reducers[0]?.report.stances[0];
  assert.deepEqual(stance, typedStance("docs/learned/pi/context-injection.md"));
  assert.deepEqual(Object.keys(stance ?? {}).sort(), [
    "disposition",
    "doc",
    "evidence_checked",
    "reason",
    "stance",
  ]);
});

// ---------------------------------------------------------------- the proposal universe

test("nonKeepProposals: flat-map ordering and keep filtering", () => {
  assert.deepEqual(nonKeepProposalsView(fixtureAnalyses()), [
    ["docs/learned/pi/context-injection.md", "revise"],
    ["docs/learned/pi/subagents.md", "merge-into"],
    ["docs/learned/workflow/report-waves.md", "retire"],
  ]);
  // keep rows drop out; ordering inherits the analyses' (manifest) order.
  const keepHeavy = [
    analysisOf("pi-extension-1", [
      assessment("docs/learned/pi/context-injection.md"),
      assessment("docs/learned/pi/subagents.md", { disposition: "revise" }),
    ]),
    analysisOf("workflow-1", [assessment("docs/learned/workflow/report-waves.md")]),
  ];
  assert.deepEqual(nonKeepProposalsView(keepHeavy), [["docs/learned/pi/subagents.md", "revise"]]);
  assert.deepEqual(
    nonKeepProposalsView([
      analysisOf("workflow-1", [assessment("docs/learned/workflow/report-waves.md")]),
    ]),
    [],
    "an all-keep corpus yields an empty proposal universe (reducers still launch)",
  );
});

function nonKeepProposalsView(analyses: DreamLaneAnalysis[]): [string, string][] {
  return nonKeepProposals(analyses).map((p) => [p.doc, p.disposition]);
}

// ------------------------------------------------------------- the schema↔caps lockstep

test("DREAM_REDUCER_REPORT_SCHEMA: closed shape, required-completeness, enums, caps SSOT", () => {
  const schema = DREAM_REDUCER_REPORT_SCHEMA as {
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
  assert.deepEqual(schema.properties.angle, {
    type: "string",
    enum: [...DREAM_REDUCER_ANGLES],
  });
  assert.deepEqual(DREAM_REDUCER_ANGLES, [
    "consolidation-preservation",
    "currency-accuracy",
    "knowledge-architecture",
  ]);

  const stances = schema.properties.stances as {
    maxItems: number;
    items: {
      additionalProperties: boolean;
      required: string[];
      properties: Record<string, Record<string, unknown>>;
    };
  };
  assert.equal(stances.maxItems, DREAM_REDUCER_CAPS.stances);
  assert.equal(stances.items.additionalProperties, false);
  assert.deepEqual(
    [...stances.items.required].sort(),
    Object.keys(stances.items.properties).sort(),
    "every stance-row field is required",
  );
  assert.deepEqual(stances.items.properties.disposition?.enum, ["revise", "merge-into", "retire"]);
  assert.deepEqual(stances.items.properties.stance?.enum, ["endorse", "challenge"]);
  assert.equal(stances.items.properties.reason?.maxLength, DREAM_REDUCER_CAPS.stanceReasonChars);
  assert.deepEqual(stances.items.properties.evidence_checked, {
    type: "array",
    maxItems: DREAM_REDUCER_CAPS.stanceEvidenceItems,
    items: { type: "string", maxLength: DREAM_REDUCER_CAPS.stanceEvidenceItemChars },
  });

  assert.deepEqual(schema.properties.angle_findings, {
    type: "array",
    maxItems: DREAM_REDUCER_CAPS.angleFindings,
    items: { type: "string", maxLength: DREAM_REDUCER_CAPS.angleFindingChars },
  });
  assert.deepEqual(schema.properties.uncertainties, {
    type: "array",
    maxItems: DREAM_REDUCER_CAPS.uncertainties,
    items: { type: "string", maxLength: DREAM_REDUCER_CAPS.uncertaintyChars },
  });
  for (const counter of ["stances_omitted", "angle_findings_omitted", "uncertainties_omitted"]) {
    assert.deepEqual(schema.properties[counter], { type: "integer", minimum: 0 });
  }
});

test("DREAM_REDUCER_ANGLES are run-key-safe by construction (code-owned lane keys)", () => {
  for (const angle of DREAM_REDUCER_ANGLES) {
    assert.ok(RUN_KEY_PATTERN.test(angle), `angle '${angle}' must satisfy the run-key contract`);
  }
});

// ----------------------------------------------------------------- the defensive re-decode

test("decodeDreamReducerReport: a fully-populated report round-trips WITHOUT the echoed angle", () => {
  const raw = reducerReportOf(ANGLE, {
    // Rows deliberately in REVERSED proposal order, one with a smuggled extra key.
    stances: [
      stanceRow("docs/learned/workflow/report-waves.md", { stance: "challenge" }),
      stanceRow("docs/learned/pi/context-injection.md", { smuggled: "an extra input key" }),
    ],
    angle_findings: ["cross-lane redundancy between the two pi docs"],
    uncertainties: ["unsure whether the retire is safe"],
    stances_omitted: 1,
    angle_findings_omitted: 2,
    uncertainties_omitted: 3,
  });
  const result = decodeDreamReducerReport(raw, ANGLE, PROPOSALS);
  assert.equal(result.ok, true, JSON.stringify(result));
  const report = (result as { ok: true; report: DreamReducerReport }).report;
  assert.deepEqual(
    Object.keys(report).sort(),
    [
      "angle_findings",
      "angle_findings_omitted",
      "stances",
      "stances_omitted",
      "uncertainties",
      "uncertainties_omitted",
    ],
    "the typed report omits the echoed angle (named once, on the analysis)",
  );
  assert.deepEqual(
    report.stances.map((s) => s.doc),
    ["docs/learned/pi/context-injection.md", "docs/learned/workflow/report-waves.md"],
    "stances are normalized to the proposal order",
  );
  assert.deepEqual(Object.keys(report.stances[0] ?? {}).sort(), [
    "disposition",
    "doc",
    "evidence_checked",
    "reason",
    "stance",
  ]);
  assert.equal(report.stances[1]?.stance, "challenge");
  assert.equal(report.stances_omitted, 1);
  assert.equal(report.angle_findings_omitted, 2);
  assert.equal(report.uncertainties_omitted, 3);
});

test("decodeDreamReducerReport: empty stances is VALID (silence = non-endorsement downstream)", () => {
  const result = decodeDreamReducerReport(reducerReportOf(), ANGLE, PROPOSALS);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.deepEqual((result as { ok: true; report: DreamReducerReport }).report.stances, []);
});

test("decodeDreamReducerReport: string caps are measured in Unicode code points", () => {
  const astral = "😀".repeat(DREAM_REDUCER_CAPS.stanceReasonChars);
  assert.ok(astral.length > DREAM_REDUCER_CAPS.stanceReasonChars, "sanity: UTF-16 exceeds the cap");
  const pass = decodeDreamReducerReport(
    reducerReportOf(ANGLE, {
      stances: [stanceRow("docs/learned/pi/context-injection.md", { reason: astral })],
    }),
    ANGLE,
    PROPOSALS,
  );
  assert.equal(pass.ok, true, "exactly N astral code points passes");
  const fail = decodeDreamReducerReport(
    reducerReportOf(ANGLE, {
      stances: [stanceRow("docs/learned/pi/context-injection.md", { reason: `${astral}😀` })],
    }),
    ANGLE,
    PROPOSALS,
  );
  assert.equal(fail.ok, false, "N+1 code points fails");
  assert.match(
    (fail as { detail: string }).detail,
    new RegExp(`exceeds ${DREAM_REDUCER_CAPS.stanceReasonChars} code points`),
  );
});

test("decodeDreamReducerReport: each refusal arm carries its named detail", () => {
  const over = (n: number, s = "x") => Array.from({ length: n }, () => s);
  const arms: { report: unknown; detail: RegExp }[] = [
    { report: "nope", detail: /not an object/ },
    {
      report: reducerReportOf("currency-accuracy"),
      detail: /echoes angle "currency-accuracy", lane assigned 'consolidation-preservation'/,
    },
    {
      report: reducerReportOf(ANGLE, { stances: "nope" }),
      detail: /stances is not an array/,
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: Array.from({ length: DREAM_REDUCER_CAPS.stances + 1 }, () =>
          stanceRow("docs/learned/pi/context-injection.md"),
        ),
      }),
      detail: new RegExp(`more than ${DREAM_REDUCER_CAPS.stances} stances`),
    },
    {
      report: reducerReportOf(ANGLE, { stances: [null] }),
      detail: /a stance row is not an object/,
    },
    {
      // An unknown doc (not in the corpus at all).
      report: reducerReportOf(ANGLE, { stances: [stanceRow("docs/learned/gone.md")] }),
      detail: /"docs\/learned\/gone\.md" is not one of the analysts' non-keep proposals/,
    },
    {
      // A keep-disposed doc — in the corpus but NOT in the proposal universe.
      report: reducerReportOf(ANGLE, {
        stances: [stanceRow("docs/learned/pi/keep-me.md", { disposition: "revise" })],
      }),
      detail: /"docs\/learned\/pi\/keep-me\.md" is not one of the analysts' non-keep proposals/,
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [
          stanceRow("docs/learned/pi/context-injection.md"),
          stanceRow("docs/learned/pi/context-injection.md"),
        ],
      }),
      detail: /duplicate stance row for 'docs\/learned\/pi\/context-injection\.md'/,
    },
    {
      // The disposition-echo rule: the analyst proposed revise, the stance echoes retire.
      report: reducerReportOf(ANGLE, {
        stances: [stanceRow("docs/learned/pi/context-injection.md", { disposition: "retire" })],
      }),
      detail: /echoes disposition "retire", the analyst proposed 'revise'/,
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [stanceRow("docs/learned/pi/context-injection.md", { stance: "abstain" })],
      }),
      detail: /value "abstain" is outside the vocabulary/,
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [stanceRow("docs/learned/pi/context-injection.md", { reason: "" })],
      }),
      detail: /reason is not a non-empty string/,
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [
          stanceRow("docs/learned/pi/context-injection.md", {
            reason: "x".repeat(DREAM_REDUCER_CAPS.stanceReasonChars + 1),
          }),
        ],
      }),
      detail: new RegExp(`reason exceeds ${DREAM_REDUCER_CAPS.stanceReasonChars} code points`),
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [
          stanceRow("docs/learned/pi/context-injection.md", {
            evidence_checked: over(DREAM_REDUCER_CAPS.stanceEvidenceItems + 1),
          }),
        ],
      }),
      detail: new RegExp(
        `evidence_checked carries more than ${DREAM_REDUCER_CAPS.stanceEvidenceItems} items`,
      ),
    },
    {
      report: reducerReportOf(ANGLE, {
        stances: [
          stanceRow("docs/learned/pi/context-injection.md", {
            evidence_checked: ["y".repeat(DREAM_REDUCER_CAPS.stanceEvidenceItemChars + 1)],
          }),
        ],
      }),
      detail: new RegExp(
        `evidence_checked item exceeds ${DREAM_REDUCER_CAPS.stanceEvidenceItemChars} code points`,
      ),
    },
    {
      report: reducerReportOf(ANGLE, {
        angle_findings: over(DREAM_REDUCER_CAPS.angleFindings + 1),
      }),
      detail: new RegExp(
        `angle_findings carries more than ${DREAM_REDUCER_CAPS.angleFindings} items`,
      ),
    },
    {
      report: reducerReportOf(ANGLE, {
        angle_findings: ["z".repeat(DREAM_REDUCER_CAPS.angleFindingChars + 1)],
      }),
      detail: new RegExp(
        `angle_findings item exceeds ${DREAM_REDUCER_CAPS.angleFindingChars} code points`,
      ),
    },
    {
      report: reducerReportOf(ANGLE, {
        uncertainties: over(DREAM_REDUCER_CAPS.uncertainties + 1),
      }),
      detail: new RegExp(
        `uncertainties carries more than ${DREAM_REDUCER_CAPS.uncertainties} items`,
      ),
    },
    {
      report: reducerReportOf(ANGLE, { stances_omitted: -1 }),
      detail: /stances_omitted is not a non-negative integer/,
    },
    {
      report: reducerReportOf(ANGLE, { angle_findings_omitted: 1.5 }),
      detail: /angle_findings_omitted is not a non-negative integer/,
    },
    {
      report: reducerReportOf(ANGLE, { uncertainties_omitted: "0" }),
      detail: /uncertainties_omitted is not a non-negative integer/,
    },
  ];
  for (const arm of arms) {
    const result = decodeDreamReducerReport(arm.report, ANGLE, PROPOSALS);
    assert.equal(result.ok, false, `must refuse: ${JSON.stringify(arm.report)}`);
    assert.match((result as { detail: string }).detail, arm.detail);
  }
});

// ---------------------------------------------------------------------------- the runner

function validAggregate(): { state: string; value: unknown } {
  return {
    state: "complete",
    value: DREAM_REDUCER_ANGLES.map((angle) => ({
      key: angle,
      ok: true,
      error: null,
      report: reducerReportOf(angle, {
        stances: [stanceRow("docs/learned/pi/context-injection.md")],
      }),
    })),
  };
}

test("runDreamReducerWave: three fixed lanes — key = label = angle slug, the task shape", async () => {
  const adapter = createMemoryWaveAdapter({ aggregate: validAggregate() });
  const outcome = await runDreamReducerWave(adapter, {
    manifestPath: MANIFEST_PATH,
    bundlePath: BUNDLE_PATH,
    proposals: PROPOSALS,
    model: "faux/reducer",
  });
  assert.equal(outcome.complete, true);
  assert.deepEqual(outcome.failures, []);
  assert.deepEqual(outcome.requestedKeys, [...DREAM_REDUCER_ANGLES]);
  assert.deepEqual(
    outcome.reports.map((r) => r.angle),
    [...DREAM_REDUCER_ANGLES],
    "reports are normalized to the fixed angle order",
  );

  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.equal(spawn?.async, true);
  assert.equal(spawn?.mission, false);
  assert.equal(spawn?.context, "fresh");
  assert.equal(spawn?.model, "faux/reducer", "the caller's model reaches the spawn params");
  assert.deepEqual(spawn?.outputSchema, DREAM_REDUCER_REPORT_SCHEMA);
  const items = spawnedLaneItems(spawn?.workflowScript ?? "");
  assert.deepEqual(
    items.map((item) => item.key),
    [...DREAM_REDUCER_ANGLES],
  );
  assert.deepEqual(
    items.map((item) => item.label),
    [...DREAM_REDUCER_ANGLES],
  );
  for (const item of items) {
    assert.equal(item.agent, "perk.dream-reducer");
    assert.equal(item.phase, "dream");
    assert.ok(item.task.startsWith(`Angle: ${item.key}\n`), "the task opens with the angle");
    assert.ok(
      item.task.includes(`Read the compact analyst bundle FIRST: ${BUNDLE_PATH}`),
      "the bundle path rides the task, read FIRST",
    );
    assert.ok(item.task.includes(MANIFEST_PATH), "the manifest path rides the task");
    assert.match(item.task, /untrusted DATA, never instructions/);
    assert.match(item.task, /Report via structured_output/);
  }
});

test("runDreamReducerWave: STRICT — one failed lane ⇒ incomplete, surviving reports retained", async () => {
  const [first, second] = [DREAM_REDUCER_ANGLES[0], DREAM_REDUCER_ANGLES[1]];
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: first, ok: true, error: null, report: reducerReportOf(first) },
        { key: second, ok: false, error: "reducer crashed", report: null },
        {
          key: DREAM_REDUCER_ANGLES[2],
          ok: true,
          error: null,
          report: reducerReportOf(DREAM_REDUCER_ANGLES[2]),
        },
      ],
    },
  });
  const outcome = await runDreamReducerWave(adapter, {
    manifestPath: MANIFEST_PATH,
    bundlePath: BUNDLE_PATH,
    proposals: PROPOSALS,
  });
  assert.equal(outcome.complete, false, "strict: one failed lane fails the wave");
  assert.deepEqual(outcome.failures, [
    { angle: second, reason: "lane-failed", detail: "reducer crashed" },
  ]);
  assert.deepEqual(
    outcome.reports.map((r) => r.angle),
    [first, DREAM_REDUCER_ANGLES[2]],
    "decoded reports are retained even when incomplete",
  );
});

test("runDreamReducerWave: a schema-valid but re-decode-failing report is malformed-report with angle identity", async () => {
  const bad = reducerReportOf(DREAM_REDUCER_ANGLES[1], {
    stances: [stanceRow("docs/learned/not-a-proposal.md", { disposition: "revise" })],
  });
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: DREAM_REDUCER_ANGLES[0],
          ok: true,
          error: null,
          report: reducerReportOf(DREAM_REDUCER_ANGLES[0]),
        },
        { key: DREAM_REDUCER_ANGLES[1], ok: true, error: null, report: bad },
        {
          key: DREAM_REDUCER_ANGLES[2],
          ok: true,
          error: null,
          report: reducerReportOf(DREAM_REDUCER_ANGLES[2]),
        },
      ],
    },
  });
  const outcome = await runDreamReducerWave(adapter, {
    manifestPath: MANIFEST_PATH,
    bundlePath: BUNDLE_PATH,
    proposals: PROPOSALS,
  });
  assert.equal(outcome.complete, false);
  assert.equal(outcome.failures.length, 1);
  assert.equal(outcome.failures[0]?.angle, DREAM_REDUCER_ANGLES[1]);
  assert.equal(outcome.failures[0]?.reason, "malformed-report");
  assert.match(outcome.failures[0]?.detail ?? "", /not one of the analysts' non-keep proposals/);
  assert.deepEqual(
    outcome.reports.map((r) => r.angle),
    [DREAM_REDUCER_ANGLES[0], DREAM_REDUCER_ANGLES[2]],
  );
});

test("runDreamReducerWave: the unavailable arm is a wave-level failure (angle: null)", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const outcome = await runDreamReducerWave(adapter, {
    manifestPath: MANIFEST_PATH,
    bundlePath: BUNDLE_PATH,
    proposals: PROPOSALS,
  });
  assert.equal(outcome.complete, false);
  assert.deepEqual(outcome.reports, []);
  assert.equal(outcome.failures[0]?.angle, null, "a wave-level failure carries angle: null");
  assert.equal(outcome.failures[0]?.reason, "unavailable");
  assert.deepEqual(outcome.requestedKeys, [...DREAM_REDUCER_ANGLES]);
});

test("runDreamReducerWave: a pre-aborted signal cancels before launch, naming the flow", async () => {
  const adapter = createMemoryWaveAdapter();
  const controller = new AbortController();
  controller.abort();
  const outcome = await runDreamReducerWave(
    adapter,
    { manifestPath: MANIFEST_PATH, bundlePath: BUNDLE_PATH, proposals: PROPOSALS },
    controller.signal,
  );
  assert.equal(adapter.calls.spawn.length, 0, "no spawn is issued");
  assert.equal(outcome.complete, false);
  assert.equal(outcome.failures[0]?.reason, "cancelled");
  assert.match(outcome.failures[0]?.detail ?? "", /dream-reducer/);
});

// ------------------------------------------------------- the agent-def lockstep pin

test("the dream-reducer def agrees with the report schema — fields, stances, caps, completion", () => {
  const defPath = join(import.meta.dirname, "..", "..", "agents", "dream-reducer.md");
  const def = readFileSync(defPath, "utf8");
  const flat = def.replace(/\s+/g, " ");
  // Frontmatter: the runtime name perk.dream-reducer, the stronger-tier default model, and
  // the read-only isolation posture (the auditWaveTools.test.ts precedent) — these fields
  // define the reducer's identity and execution behavior, so they are pinned exactly.
  assert.match(def, /^name: dream-reducer$/m);
  assert.match(def, /^package: perk$/m);
  assert.match(def, /^model: anthropic\/claude-fable-5$/m);
  assert.match(def, /^ {2}- anthropic\/claude-sonnet-4-5$/m);
  assert.match(def, /^tools: read, grep, find, ls, bash$/m);
  assert.match(def, /^systemPromptMode: replace$/m);
  assert.match(def, /^inheritProjectContext: false$/m);
  assert.match(def, /^inheritSkills: false$/m);
  const schema = DREAM_REDUCER_REPORT_SCHEMA as {
    required: string[];
    properties: { stances: { items: { required: string[] } } };
  };
  // Derived from schema.required at BOTH levels — drift in either direction trips this test.
  const namesField = (field: string): boolean =>
    new RegExp(`\`[^\`]*\\b${field}\\b[^\`]*\``).test(def);
  for (const field of schema.required) {
    assert.ok(namesField(field), `the def must name the report field ${field}`);
  }
  for (const field of schema.properties.stances.items.required) {
    assert.ok(namesField(field), `the def must name the stance-row field ${field}`);
  }
  for (const stance of ["endorse", "challenge"]) {
    assert.ok(def.includes(stance), `the def must name the stance value ${stance}`);
  }
  for (const angle of DREAM_REDUCER_ANGLES) {
    assert.ok(def.includes(angle), `the def must name the angle ${angle}`);
  }
  // The cap prose agrees with the DREAM_REDUCER_CAPS SSOT (whitespace-normalized).
  const caps = DREAM_REDUCER_CAPS;
  for (const prose of [
    `\`stances\` ≤ ${caps.stances} (reasons ≤ ${caps.stanceReasonChars} chars, \`evidence_checked\` ≤ ${caps.stanceEvidenceItems} items ≤ ${caps.stanceEvidenceItemChars} chars each)`,
    `\`angle_findings\` ≤ ${caps.angleFindings} (≤ ${caps.angleFindingChars} chars each)`,
    `\`uncertainties\` ≤ ${caps.uncertainties} (≤ ${caps.uncertaintyChars} chars each)`,
  ]) {
    assert.ok(flat.includes(prose), `the def's cap prose must state: ${prose}`);
  }
  // The completion form: the engine-injected structured_output phrasing, never fenced JSON.
  assert.match(def, /engine-injected \*\*`structured_output`\*\* tool/);
  assert.match(def, /never print a fenced JSON block/);
  assert.doesNotMatch(def, /```json/, "no fenced-JSON completion form anywhere in the def");
  // The selective-evidence boundary: verify cited evidence, never re-audit the corpus.
  assert.match(flat, /\*\*Never broadly rescan the corpus\*\*/);
  assert.match(flat, /read the \*specific named\* docs and code sites/);
  assert.match(flat, /never read docs beyond the cited or named ones/);
  // The stance semantics: silence = non-endorsement; destructive proposals stanced FIRST.
  assert.match(flat, /\*\*silence counts as non-endorsement\*\*/);
  assert.match(flat, /stance \*\*every `merge-into`\/`retire` proposal FIRST\*\*/);
  assert.match(flat, /count the overflow in `stances_omitted`/);
  // The delivered `.pi/agents/perk/` mirror stays byte-identical (the same-commit convergence).
  const mirror = join(import.meta.dirname, "..", "..", ".pi", "agents", "perk", "dream-reducer.md");
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});
