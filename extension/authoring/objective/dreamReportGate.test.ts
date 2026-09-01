// The `dream_report` gate resolver's suite (contracts §8.63), over a temp cwd with REAL
// run-scratch fixtures (a raw manifest through `decodeDreamManifest`'s producer shape, the
// bundle via `composeDreamBundle`/`finalizeDreamBundle`, the digest marker via a
// workflow-state entry — the dreamReport.test.ts + objectiveDraft.test.ts fixture recipes):
// the four matrix arms, the recovery happy path feeding `buildDreamReport` to an ok block,
// render determinism under one stamp, every named recovery-failure arm (the digest-pointer
// doctrine's fail-closed ladder), the §8.65 revalidation-bracket re-check (injected stubs —
// the temp cwds here are not git repos; the REAL default bracket is exercised end-to-end by
// the boundary suites over the git-backed testing/dreamFixtures.ts fixture), and the
// `decodeDreamReportBlock` shape check. Fully offline.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { runScratchDir } from "../../substrate/cache.ts";
import { digestSessionData, type SessionDataCtx } from "../../substrate/sessionData.ts";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import {
  composeDreamBundle,
  DREAM_ANALYSES_FILENAME,
  DREAM_REDUCER_ANGLES,
  type DreamReducerAnalysis,
  finalizeDreamBundle,
} from "../../waves/dreamReducerWave.ts";
import {
  DREAM_MANIFEST_FILENAME,
  type DreamDocAssessment,
  type DreamLaneAnalysis,
  type DreamManifest,
  decodeDreamManifest,
} from "../../waves/dreamWave.ts";
import {
  COMPANION_COMMENT_MAX_CHARS,
  type DreamReportGateOutcome,
  decodeDreamReportBlock,
  reportPartInvarianceViolations,
  resolveDreamReportGate,
} from "./dreamReportGate.ts";

const RUN_ID = "01DREAMGATE";
const STAMP = "2026-02-03T04:05:06Z";

const DOC_CTX = "docs/learned/pi/context-injection.md";
const DOC_SUB = "docs/learned/pi/subagents.md";
const DOC_WAVES = "docs/learned/workflow/report-waves.md";

// --- fixtures -----------------------------------------------------------------------------

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

/** The 2-lane / 3-doc raw producer manifest (the reducer suite's shape). */
function rawManifest(): Record<string, unknown> {
  return {
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
  };
}

function decodedManifest(manifestPath: string): DreamManifest {
  const result = decodeDreamManifest(rawManifest(), manifestPath);
  assert.equal(result.ok, true, JSON.stringify(result));
  return (result as { ok: true; manifest: DreamManifest }).manifest;
}

/** The exact manifest bytes `plantDream` writes by default (what the bound digest covers). */
function defaultManifestBytes(): string {
  return `${JSON.stringify(rawManifest(), null, 2)}\n`;
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

/** One non-keep proposal (DOC_CTX revise); the other two docs keep. */
function fixtureAnalyses(): DreamLaneAnalysis[] {
  const report = (docs: DreamDocAssessment[]): DreamLaneAnalysis["report"] => ({
    docs,
    overlap_signals: [],
    harvest_followups: [],
    uncertainties: [],
    overlap_signals_omitted: 0,
    harvest_followups_omitted: 0,
    uncertainties_omitted: 0,
  });
  return [
    {
      lane: "pi-extension-1",
      report: report([assessment(DOC_CTX, { disposition: "revise" }), assessment(DOC_SUB)]),
    },
    { lane: "workflow-1", report: report([assessment(DOC_WAVES)]) },
  ];
}

function fixtureReducers(): DreamReducerAnalysis[] {
  return DREAM_REDUCER_ANGLES.map((angle, index) => ({
    angle,
    report: {
      stances:
        index === 0
          ? [
              {
                doc: DOC_CTX,
                disposition: "revise" as const,
                stance: "endorse" as const,
                reason: "verified against the checkout",
                evidence_checked: [],
              },
            ]
          : [],
      angle_findings: [],
      uncertainties: [],
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
    },
  }));
}

/** A valid model input over the fixture: rows echo the proposals, one unit covers DOC_CTX. */
function validInput(): Record<string, unknown> {
  return {
    rows: [
      {
        path: DOC_CTX,
        disposition: "revise",
        merge_target: null,
        rationale: "the parent's reason",
        fallback_reason: null,
      },
      {
        path: DOC_SUB,
        disposition: "keep",
        merge_target: null,
        rationale: "k",
        fallback_reason: null,
      },
      {
        path: DOC_WAVES,
        disposition: "keep",
        merge_target: null,
        rationale: "k",
        fallback_reason: null,
      },
    ],
    uncertainties: [],
    selected_units: [{ title: "Revise ctx", roadmap_node: "1.1", docs: [DOC_CTX], rationale: "r" }],
    overflow_units: [],
    harvest_followups: [],
    predicted_effects: { docs_after: 3, bytes_after: 350, note: null },
  };
}

/** A `SessionDataCtx` over a live branch array (the objectiveDraft.test.ts fixture). */
function ctxOf(cwd: string, branch: unknown[]): SessionDataCtx {
  return { cwd, sessionManager: { getBranch: () => branch } };
}

function runIdEntry(runId: string): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: runId } };
}

function markerEntry(digest: string): unknown {
  return {
    type: "custom",
    customType: WORKFLOW_STATE_TYPE,
    data: { dream_bundle_digest: digest },
  };
}

/**
 * Plant the full dream fixture in a temp cwd: the run-scoped manifest, the (default finalized)
 * bundle, and the digest marker on the branch. `bundle: false` plants no bundle file;
 * `marker: false` appends no marker entry; `marker: ""` is the cleared/invalidated state.
 */
function plantDream(
  opts: { manifest?: string | false; bundle?: string | false; marker?: string | false } = {},
): { cwd: string; ctx: SessionDataCtx; branch: unknown[]; manifest: DreamManifest } {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-report-test-"));
  const scratch = runScratchDir(cwd, RUN_ID);
  mkdirSync(scratch, { recursive: true });
  const manifestPath = join(scratch, DREAM_MANIFEST_FILENAME);
  const manifest = decodedManifest(manifestPath);
  if (opts.manifest !== false) {
    writeFileSync(manifestPath, opts.manifest ?? defaultManifestBytes());
  }
  const bundle =
    opts.bundle === undefined
      ? finalizeDreamBundle(
          manifest,
          fixtureAnalyses(),
          fixtureReducers(),
          digestSessionData(defaultManifestBytes()),
        )
      : opts.bundle;
  if (bundle !== false) {
    writeFileSync(join(scratch, DREAM_ANALYSES_FILENAME), bundle);
  }
  const branch: unknown[] = [runIdEntry(RUN_ID)];
  if (opts.marker !== false) {
    branch.push(
      markerEntry(opts.marker ?? digestSessionData(bundle === false ? "" : (bundle as string))),
    );
  }
  return { cwd, ctx: ctxOf(cwd, branch), branch, manifest };
}

function refusal(outcome: DreamReportGateOutcome): { errorType: string; detail: string } {
  assert.equal(outcome.kind, "refuse", JSON.stringify(outcome));
  const refused = outcome as { kind: "refuse"; errorType: string; detail: string };
  return { errorType: refused.errorType, detail: refused.detail };
}

/** An always-ok injected bracket (the temp cwds here are not git repos, so the tests that
 * reach past recovery pin the bracket explicitly instead of the real default). */
function okBracket(): { ok: boolean; detail: string | null } {
  return { ok: true, detail: null };
}

// --- decodeDreamReportBlock -----------------------------------------------------------------

test("decodeDreamReportBlock: a valid block round-trips; every malformed shape refuses", () => {
  const block = { input: { rows: [] }, generated_at: STAMP, parts: ["# Dream report — R\n"] };
  assert.deepEqual(decodeDreamReportBlock(block), block);

  for (const [label, value] of [
    ["non-object", "nope"],
    ["null", null],
    ["array", []],
    ["non-object input", { ...block, input: "nope" }],
    ["array input", { ...block, input: [] }],
    ["missing input", { generated_at: STAMP, parts: ["p"] }],
    ["blank generated_at", { ...block, generated_at: "  " }],
    ["missing generated_at", { input: {}, parts: ["p"] }],
    ["mistyped generated_at", { ...block, generated_at: 7 }],
    ["missing parts", { input: {}, generated_at: STAMP }],
    ["empty parts", { ...block, parts: [] }],
    ["non-array parts", { ...block, parts: "p" }],
    ["a non-string part", { ...block, parts: ["ok", 7] }],
  ] as const) {
    assert.equal(decodeDreamReportBlock(value), null, `must refuse: ${label}`);
  }
});

// --- the gate matrix ------------------------------------------------------------------------

test("gate: an UNREADABLE workflow state refuses bad_state — never conflated with non-dream", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-report-test-"));
  try {
    const throwing: SessionDataCtx = {
      cwd,
      sessionManager: {
        getBranch: () => {
          throw new Error("branch storage exploded");
        },
      },
    };
    // Both the absent-input and present-input shapes fail closed BEFORE the matrix: a
    // transient branch-read failure must never surface as `absent` (the silent-drop hazard).
    for (const input of [undefined, validInput()]) {
      const { errorType, detail } = refusal(resolveDreamReportGate(throwing, input, STAMP));
      assert.equal(errorType, "bad_state");
      assert.match(detail, /session workflow state is unreadable/);
      assert.match(detail, /branch storage exploded/);
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: non-dream + absent → absent (no claimed run, and claimed-run-without-manifest)", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-report-test-"));
  try {
    // No claimed run counts as non-dream.
    assert.deepEqual(resolveDreamReportGate(ctxOf(cwd, []), undefined, STAMP), {
      kind: "absent",
    });
    // A claimed run with no run-scoped dream manifest is non-dream too.
    assert.deepEqual(resolveDreamReportGate(ctxOf(cwd, [runIdEntry(RUN_ID)]), undefined, STAMP), {
      kind: "absent",
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: non-dream + present → invalid_input (never silently dropped)", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-report-test-"));
  try {
    // The missing-manifest arm IS the non-dream detection: a present dream_report refuses.
    const outcome = resolveDreamReportGate(ctxOf(cwd, [runIdEntry(RUN_ID)]), validInput(), STAMP);
    const { errorType, detail } = refusal(outcome);
    assert.equal(errorType, "invalid_input");
    assert.match(detail, /only valid inside a perk learn dream session/);
    assert.match(detail, /refusing rather than silently dropping it/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: dream + absent → invalid_input (the one-approval-bundle rule)", () => {
  const { cwd, ctx } = plantDream();
  try {
    const { errorType, detail } = refusal(resolveDreamReportGate(ctx, undefined, STAMP));
    assert.equal(errorType, "invalid_input");
    assert.match(detail, /must carry dream_report/);
    assert.match(detail, /review as one bundle/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: dream + valid → block carrying the input, the stamp, and the rendered parts", () => {
  const { cwd, ctx } = plantDream();
  try {
    const input = validInput();
    const outcome = resolveDreamReportGate(ctx, input, STAMP, okBracket);
    assert.equal(outcome.kind, "block", JSON.stringify(outcome));
    const block = (
      outcome as { kind: "block"; block: { input: unknown; generated_at: string; parts: string[] } }
    ).block;
    assert.equal(block.input, input, "the input rides the block verbatim");
    assert.equal(block.generated_at, STAMP, "the caller's ONE stamp is stored");
    assert.ok(block.parts.length >= 1);
    assert.ok(
      block.parts[0]?.startsWith(`# Dream report — ${RUN_ID}`),
      "the parts carry their own dream-report header",
    );
    assert.match(block.parts[0] ?? "", /## Dispositions/);
    assert.ok(decodeDreamReportBlock(block), "the block round-trips the artifact shape check");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: determinism — two calls with the same input + stamp render byte-identical parts", () => {
  const { cwd, ctx } = plantDream();
  try {
    const first = resolveDreamReportGate(ctx, validInput(), STAMP, okBracket);
    const second = resolveDreamReportGate(ctx, validInput(), STAMP, okBracket);
    assert.equal(first.kind, "block");
    assert.equal(second.kind, "block");
    assert.deepEqual(
      (first as { kind: "block"; block: { parts: string[] } }).block.parts,
      (second as { kind: "block"; block: { parts: string[] } }).block.parts,
      "re-rendering under one stamp is deterministic (what the save byte-compare relies on)",
    );
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: a buildDreamReport refusal → invalid_input with the named details newline-joined", () => {
  const { cwd, ctx } = plantDream();
  try {
    const input = validInput();
    (input.rows as unknown[]).pop(); // drop DOC_WAVES → a missing-row semantic detail
    (input.selected_units as { docs: string[] }[])[0]?.docs.push(DOC_SUB); // a final-keep doc in a unit
    const { errorType, detail } = refusal(resolveDreamReportGate(ctx, input, STAMP, okBracket));
    assert.equal(errorType, "invalid_input");
    const lines = detail.split("\n");
    assert.ok(lines.length >= 2, "the collected details ride the message newline-joined");
    assert.match(detail, /missing disposition row for authored doc/);
    assert.match(detail, /final-keep docs appear\s+in no unit/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the recovery failure ladder (every arm bad_state, named) --------------------------------

test("gate: recovery failure arms are bad_state with named details", () => {
  const arms: {
    label: string;
    plant: () => ReturnType<typeof plantDream>;
    detail: RegExp;
  }[] = [
    {
      label: "unparsable manifest",
      plant: () => plantDream({ manifest: "{not json" }),
      detail: /dream manifest unreadable/,
    },
    {
      label: "undecodable manifest",
      plant: () =>
        plantDream({
          manifest: `${JSON.stringify({ ...rawManifest(), doc_count: 99 }, null, 2)}\n`,
        }),
      detail: /dream manifest invalid: .*doc_count \(99\) does not match/,
    },
    {
      label: "bundle absent",
      plant: () => plantDream({ bundle: false, marker: "sha256:deadbeef" }),
      detail: /no dream bundle at .* — re-run the dream wave/,
    },
    {
      label: "marker missing",
      plant: () => plantDream({ marker: false }),
      detail: /no finalized dream wave for this session — re-run the dream wave/,
    },
    {
      // The cleanup-failure→draft path: files intact, marker cleared → refuse.
      label: "marker empty (invalidated)",
      plant: () => plantDream({ marker: "" }),
      detail: /no finalized dream wave for this session — re-run the dream wave/,
    },
    {
      label: "digest mismatch (one flipped byte)",
      plant: () => {
        const planted = plantDream();
        const finalized = finalizeDreamBundle(
          planted.manifest,
          fixtureAnalyses(),
          fixtureReducers(),
          digestSessionData(defaultManifestBytes()),
        );
        // Rewrite the on-disk bundle with one flipped byte; the marker still names the
        // original finalized digest.
        writeFileSync(
          join(runScratchDir(planted.cwd, RUN_ID), DREAM_ANALYSES_FILENAME),
          finalized.replace("abc123", "abc124"),
        );
        return planted;
      },
      detail: /does not match the session's finalized digest — re-run the dream wave/,
    },
    {
      // The at-rest manifest tamper the bound manifest_digest catches: the echoed identity
      // fields, paths, counts, and bytes all survive the edit, so only the digest binding
      // refuses — the marker still matches the untouched bundle bytes.
      label: "manifest tampered at rest (identity fields preserved)",
      plant: () => {
        const planted = plantDream();
        const tampered = rawManifest();
        (tampered.findings as { advisory: { empty_clusters: unknown[] } }).advisory.empty_clusters =
          ["prose-governance"];
        writeFileSync(
          join(runScratchDir(planted.cwd, RUN_ID), DREAM_MANIFEST_FILENAME),
          `${JSON.stringify(tampered, null, 2)}\n`,
        );
        return planted;
      },
      detail:
        /manifest_digest .* does not match the digest of the manifest just read — the manifest changed after the wave finalized/,
    },
    {
      // A cleanly-digested analyses-only bundle (mid-wave shape): freshness passes, the
      // finalized decode refuses.
      label: "analyses-only bundle",
      plant: () => {
        const analysesOnly = composeDreamBundle(
          decodedManifest("/unused"),
          fixtureAnalyses(),
        ).content;
        return plantDream({ bundle: analysesOnly });
      },
      detail: /no reducers section — the dream wave did not finalize .*— re-run the dream wave/,
    },
    {
      // A digest-matching but structurally-invalid finalized bundle: the strict decode refuses.
      label: "finalized-decode refusal",
      plant: () => {
        const finalized = finalizeDreamBundle(
          decodedManifest("/unused"),
          fixtureAnalyses(),
          fixtureReducers(),
          digestSessionData(defaultManifestBytes()),
        );
        const mutated = `${JSON.stringify(
          { ...(JSON.parse(finalized) as Record<string, unknown>), smuggled: 1 },
          null,
          2,
        )}\n`;
        return plantDream({ bundle: mutated });
      },
      detail: /unknown wrapper key 'smuggled' — re-run the dream wave/,
    },
  ];
  for (const arm of arms) {
    const planted = arm.plant();
    try {
      const { errorType, detail } = refusal(
        resolveDreamReportGate(planted.ctx, validInput(), STAMP),
      );
      assert.equal(errorType, "bad_state", arm.label);
      assert.match(detail, arm.detail, arm.label);
    } finally {
      rmSync(planted.cwd, { recursive: true, force: true });
    }
  }
});

// --- the revalidation-bracket re-check (contracts §8.65) --------------------------------------

test("gate: a drifted bracket refuses bad_state with the stale message (after recovery)", () => {
  const { cwd, ctx, manifest } = plantDream();
  try {
    const seen: { cwd: string; sha: string }[] = [];
    const outcome = resolveDreamReportGate(ctx, validInput(), STAMP, (bracketCwd, sha) => {
      seen.push({ cwd: bracketCwd, sha });
      return { ok: false, detail: "HEAD moved from abc123 to def456" };
    });
    const { errorType, detail } = refusal(outcome);
    assert.equal(errorType, "bad_state");
    assert.match(detail, /repository moved since the dream snapshot/);
    assert.match(detail, /HEAD moved from abc123 to def456/);
    assert.match(detail, /the analysis is stale; re-run perk learn dream/);
    // The bracket runs against the session cwd and the manifest's stamped commit — after the
    // manifest was decoded and authenticated (recovery succeeded first).
    assert.deepEqual(seen, [{ cwd, sha: manifest.commit_sha }]);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("gate: non-dream and pre-recovery arms never invoke the bracket (spy)", () => {
  const boom = (): { ok: boolean; detail: string | null } => {
    throw new Error("the bracket must not run on this arm");
  };
  // Non-dream arms: absent → absent; present → invalid_input — no bracket either way.
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-report-test-"));
  try {
    assert.deepEqual(resolveDreamReportGate(ctxOf(cwd, []), undefined, STAMP, boom), {
      kind: "absent",
    });
    const { errorType } = refusal(
      resolveDreamReportGate(ctxOf(cwd, [runIdEntry(RUN_ID)]), validInput(), STAMP, boom),
    );
    assert.equal(errorType, "invalid_input");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
  // A dream session whose recovery fails refuses BEFORE the bracket.
  const planted = plantDream({ marker: "" });
  try {
    const { errorType, detail } = refusal(
      resolveDreamReportGate(planted.ctx, validInput(), STAMP, boom),
    );
    assert.equal(errorType, "bad_state");
    assert.match(detail, /no finalized dream wave/);
  } finally {
    rmSync(planted.cwd, { recursive: true, force: true });
  }
});

// --- the part-invariance mirror (contracts §8.64; parity-pinned with the Python twin) ----------

const PARITY_FIXTURE_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "tests",
  "parity",
  "dream_report_invariance.json",
);

interface ParityFixture {
  run_id: string;
  valid: string[];
  invalid: ({ reason: string } & ({ part: string } | { repeat: string; count: number }))[];
}

test("invariance parity: the shared fixture set is accepted/rejected exactly like the Python twin", () => {
  const fixture = JSON.parse(readFileSync(PARITY_FIXTURE_PATH, "utf8")) as ParityFixture;
  assert.deepEqual(reportPartInvarianceViolations(fixture.valid, fixture.run_id), []);
  for (const entry of fixture.invalid) {
    const part = "part" in entry ? entry.part : entry.repeat.repeat(entry.count);
    const violations = reportPartInvarianceViolations([part], fixture.run_id);
    assert.ok(violations.length > 0, `expected a violation for: ${entry.reason}`);
  }
});

test("invariance parity: the comment-body cap pins the Python constant", () => {
  // perk.learn.dream_companion.COMPANION_COMMENT_MAX_CHARS is the same literal.
  assert.equal(COMPANION_COMMENT_MAX_CHARS, 65_000);
});

test("invariance parity: an empty parts list is a violation", () => {
  assert.notDeepEqual(reportPartInvarianceViolations([], "R"), []);
});

test("gate: invariance-violating rendered parts refuse invalid_input (both consumers share this resolver)", () => {
  // A single-line rationale carrying a perk HTML marker passes §8.62's single-line rule but
  // renders into the dispositions table — the §8.64 mirror refuses the rendered parts, at
  // draft-write AND save (writeObjectiveDraft and saveObjective both run this gate).
  const planted = plantDream();
  try {
    const input = validInput();
    const rows = input.rows as Record<string, unknown>[];
    rows[0] = { ...rows[0], rationale: "keep <!-- perk:metadata-block:plan-body --> visible" };
    const { errorType, detail } = refusal(
      resolveDreamReportGate(planted.ctx, input, STAMP, okBracket),
    );
    assert.equal(errorType, "invalid_input");
    assert.match(detail, /invariance rule/);
    assert.match(detail, /perk HTML-comment marker/);
  } finally {
    rmSync(planted.cwd, { recursive: true, force: true });
  }
});
