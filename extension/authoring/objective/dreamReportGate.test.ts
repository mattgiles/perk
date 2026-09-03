// The `dream_report` gate resolver's PURE matrix suite (contracts §8.63), over a FAKE
// `DreamGateRecovery` — no scratch files, no git, fully offline: the four matrix arms,
// unreadable-state precedence and the resolver's one rendering prefix (byte-exact),
// recovery-failure → `bad_state` mapping (details pass through UNPREFIXED), the §8.65 drift
// refusal bytes, `buildDreamReport` refusal details (newline-joined), render determinism under
// one stamp, the invariance-violation refusal, `decodeDreamReportBlock`, the parity fixtures,
// and the spy pin that non-dream/pre-recovery arms never invoke `recoverContext`/`bracket`.
// The BOUNDARY suite (real run-scratch fixtures, the production capability, the real
// revalidation bracket) lives with the capability: `pi/v1/objectiveDreamGate.test.ts`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  type DreamDocAssessment,
  type DreamLaneAnalysis,
  type DreamManifest,
  decodeDreamManifest,
} from "../../learning/dream.ts";
import { DREAM_REDUCER_ANGLES, type DreamReducerAnalysis } from "../../learning/dreamReducer.ts";
import {
  COMPANION_COMMENT_MAX_CHARS,
  type DreamGateRecovery,
  type DreamReportGateOutcome,
  decodeDreamReportBlock,
  reportPartInvarianceViolations,
  resolveDreamReportGate,
} from "./dreamReportGate.ts";

const RUN_ID = "01DREAMGATE";
const STAMP = "2026-02-03T04:05:06Z";
const MARKER = "sha256:fixture-marker";

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

function decodedManifest(): DreamManifest {
  const result = decodeDreamManifest(rawManifest(), "/scratch/dream-manifest.json");
  assert.equal(result.ok, true, JSON.stringify(result));
  return (result as { ok: true; manifest: DreamManifest }).manifest;
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

type SessionRead = ReturnType<DreamGateRecovery["readSession"]>;
type RecoverResult = ReturnType<DreamGateRecovery["recoverContext"]>;

/** A recording fake capability: every seam scriptable, every call spied. */
function fakeRecovery(
  opts: {
    session?: SessionRead;
    recover?: RecoverResult;
    bracket?: { ok: boolean; detail: string | null };
  } = {},
): DreamGateRecovery & {
  calls: { recover: { runId: string; marker: string | undefined }[]; bracket: string[] };
} {
  const calls: { recover: { runId: string; marker: string | undefined }[]; bracket: string[] } = {
    recover: [],
    bracket: [],
  };
  const session: SessionRead = opts.session ?? {
    kind: "read",
    runId: RUN_ID,
    dream: true,
    marker: MARKER,
  };
  const recover: RecoverResult = opts.recover ?? {
    ok: true,
    manifest: decodedManifest(),
    analyses: fixtureAnalyses(),
    reducers: fixtureReducers(),
  };
  return {
    calls,
    readSession: () => session,
    recoverContext(runId, marker) {
      calls.recover.push({ runId, marker });
      return recover;
    },
    bracket(sha) {
      calls.bracket.push(sha);
      return opts.bracket ?? { ok: true, detail: null };
    },
  };
}

function refusal(outcome: DreamReportGateOutcome): { errorType: string; detail: string } {
  assert.equal(outcome.kind, "refuse", JSON.stringify(outcome));
  const refused = outcome as { kind: "refuse"; errorType: string; detail: string };
  return { errorType: refused.errorType, detail: refused.detail };
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

test("gate: an UNREADABLE session refuses bad_state with the ONE rendering prefix (byte-exact)", () => {
  // Both the absent-input and present-input shapes fail closed BEFORE the matrix: a transient
  // read failure must never surface as `absent` (the silent-drop hazard). The capability's
  // detail is the RAW CAUSE — the resolver owns the rendering prefix.
  for (const input of [undefined, validInput()]) {
    const recovery = fakeRecovery({ session: { kind: "unreadable", detail: "boom" } });
    const { errorType, detail } = refusal(resolveDreamReportGate(recovery, input, STAMP));
    assert.equal(errorType, "bad_state");
    assert.equal(
      detail,
      "session workflow state is unreadable — cannot resolve the dream_report gate: boom",
    );
    assert.deepEqual(recovery.calls.recover, [], "no recovery on the unreadable arm");
    assert.deepEqual(recovery.calls.bracket, [], "no bracket on the unreadable arm");
  }
});

test("gate: non-dream + absent → absent (no claimed run, and claimed-run-without-manifest)", () => {
  // No claimed run counts as non-dream.
  const noRun = fakeRecovery({
    session: { kind: "read", runId: null, dream: false, marker: undefined },
  });
  assert.deepEqual(resolveDreamReportGate(noRun, undefined, STAMP), { kind: "absent" });
  // A claimed run with no run-scoped dream manifest is non-dream too.
  const noManifest = fakeRecovery({
    session: { kind: "read", runId: RUN_ID, dream: false, marker: undefined },
  });
  assert.deepEqual(resolveDreamReportGate(noManifest, undefined, STAMP), { kind: "absent" });
});

test("gate: non-dream + present → invalid_input (never silently dropped)", () => {
  const recovery = fakeRecovery({
    session: { kind: "read", runId: RUN_ID, dream: false, marker: undefined },
  });
  const { errorType, detail } = refusal(resolveDreamReportGate(recovery, validInput(), STAMP));
  assert.equal(errorType, "invalid_input");
  assert.match(detail, /only valid inside a perk learn dream session/);
  assert.match(detail, /refusing rather than silently dropping it/);
});

test("gate: dream + absent → invalid_input (the one-approval-bundle rule)", () => {
  const { errorType, detail } = refusal(resolveDreamReportGate(fakeRecovery(), undefined, STAMP));
  assert.equal(errorType, "invalid_input");
  assert.match(detail, /must carry dream_report/);
  assert.match(detail, /review as one bundle/);
});

test("gate: dream + valid → block carrying the input, the stamp, and the rendered parts", () => {
  const recovery = fakeRecovery();
  const input = validInput();
  const outcome = resolveDreamReportGate(recovery, input, STAMP);
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
  // The one-snapshot rule stays feature-visible: the marker handed to recovery is the SAME
  // snapshot's, and the bracket ran against the recovered manifest's stamped commit.
  assert.deepEqual(recovery.calls.recover, [{ runId: RUN_ID, marker: MARKER }]);
  assert.deepEqual(recovery.calls.bracket, ["abc123"]);
});

test("gate: determinism — two calls with the same input + stamp render byte-identical parts", () => {
  const first = resolveDreamReportGate(fakeRecovery(), validInput(), STAMP);
  const second = resolveDreamReportGate(fakeRecovery(), validInput(), STAMP);
  assert.equal(first.kind, "block");
  assert.equal(second.kind, "block");
  assert.deepEqual(
    (first as { kind: "block"; block: { parts: string[] } }).block.parts,
    (second as { kind: "block"; block: { parts: string[] } }).block.parts,
    "re-rendering under one stamp is deterministic (what the save byte-compare relies on)",
  );
});

test("gate: a buildDreamReport refusal → invalid_input with the named details newline-joined", () => {
  const input = validInput();
  (input.rows as unknown[]).pop(); // drop DOC_WAVES → a missing-row semantic detail
  (input.selected_units as { docs: string[] }[])[0]?.docs.push(DOC_SUB); // a final-keep doc in a unit
  const { errorType, detail } = refusal(resolveDreamReportGate(fakeRecovery(), input, STAMP));
  assert.equal(errorType, "invalid_input");
  const lines = detail.split("\n");
  assert.ok(lines.length >= 2, "the collected details ride the message newline-joined");
  assert.match(detail, /missing disposition row for authored doc/);
  assert.match(detail, /final-keep docs appear\s+in no unit/);
});

// --- the recovery-failure mapping ------------------------------------------------------------

test("gate: a recovery failure refuses bad_state with the detail passed through UNPREFIXED", () => {
  const recovery = fakeRecovery({
    recover: {
      ok: false,
      detail: "no finalized dream wave for this session — re-run the dream wave",
    },
  });
  const { errorType, detail } = refusal(resolveDreamReportGate(recovery, validInput(), STAMP));
  assert.equal(errorType, "bad_state");
  assert.equal(
    detail,
    "no finalized dream wave for this session — re-run the dream wave",
    "the recovery detail IS the refusal detail — no resolver prefix",
  );
  assert.deepEqual(recovery.calls.bracket, [], "recovery failure refuses BEFORE the bracket");
});

// --- the revalidation-bracket re-check (contracts §8.65) --------------------------------------

test("gate: a drifted bracket refuses bad_state with the stale message (after recovery)", () => {
  const recovery = fakeRecovery({
    bracket: { ok: false, detail: "HEAD moved from abc123 to def456" },
  });
  const { errorType, detail } = refusal(resolveDreamReportGate(recovery, validInput(), STAMP));
  assert.equal(errorType, "bad_state");
  assert.match(detail, /repository moved since the dream snapshot/);
  assert.match(detail, /HEAD moved from abc123 to def456/);
  assert.match(detail, /the analysis is stale; re-run perk learn dream/);
  // The bracket runs against the manifest's stamped commit — after the manifest was decoded
  // and authenticated (recovery succeeded first).
  assert.deepEqual(recovery.calls.bracket, ["abc123"]);
});

test("gate: non-dream and pre-recovery arms never invoke recoverContext or the bracket (spy)", () => {
  // Non-dream arms: absent → absent; present → invalid_input — no recovery either way.
  const absent = fakeRecovery({
    session: { kind: "read", runId: null, dream: false, marker: undefined },
  });
  assert.deepEqual(resolveDreamReportGate(absent, undefined, STAMP), { kind: "absent" });
  assert.deepEqual(absent.calls.recover, []);
  assert.deepEqual(absent.calls.bracket, []);

  const present = fakeRecovery({
    session: { kind: "read", runId: RUN_ID, dream: false, marker: undefined },
  });
  const { errorType } = refusal(resolveDreamReportGate(present, validInput(), STAMP));
  assert.equal(errorType, "invalid_input");
  assert.deepEqual(present.calls.recover, []);
  assert.deepEqual(present.calls.bracket, []);

  // The dream + absent arm refuses BEFORE recovery.
  const dreamAbsent = fakeRecovery();
  refusal(resolveDreamReportGate(dreamAbsent, undefined, STAMP));
  assert.deepEqual(dreamAbsent.calls.recover, []);
  assert.deepEqual(dreamAbsent.calls.bracket, []);
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
  const input = validInput();
  const rows = input.rows as Record<string, unknown>[];
  rows[0] = { ...rows[0], rationale: "keep <!-- perk:metadata-block:plan-body --> visible" };
  const { errorType, detail } = refusal(resolveDreamReportGate(fakeRecovery(), input, STAMP));
  assert.equal(errorType, "invalid_input");
  assert.match(detail, /invariance rule/);
  assert.match(detail, /perk HTML-comment marker/);
});
