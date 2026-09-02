// The audit-judgment feature op's offline suite (memory adapter + a recording writer): the
// verdict-schema pin, the lenient manifest decode (+ the code-owned detail fallback), lane
// composition asserted through the recorded spawn (packetized-only, run-key-safe ordinal keys,
// the per-lane task/label/agent contract), the degrade/skip routing, the zero-lane
// short-circuits, the semantic verdicts-payload write matrix, the deterministic reduction
// order, the wave-level failure arm, the cancellation contract (mid-flight + pre-aborted), and
// the write-failed arm. The runner's own matrix lives in reportWave.test.ts — not re-tested
// here beyond the wave-level arms the flow surfaces.

import assert from "node:assert/strict";
import { test } from "node:test";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import { RUN_KEY_PATTERN, reportWaveOver } from "../waves/reportWave.ts";
import type { WaveAdapter } from "../waves/transport.ts";
import {
  AUDIT_VERDICT_SCHEMA,
  type AuditJudgmentOutcome,
  type AuditManifest,
  type AuditManifestPair,
  type AuditVerdictLane,
  decodeAuditManifest,
  judgeAuditBundle,
} from "./audit.ts";

const GRILL = "plan.grill-before-review";
const ROUTE = "objective-plan.route-explorer-report";
const DETAIL_FALLBACK = "(detail missing from manifest)";
const BUNDLE_DIR = "/abs/bundle";
const VERDICTS_PATH = "/abs/bundle/verdicts.json";

function pair(
  expectationId: string,
  basename: string,
  overrides: Partial<AuditManifestPair> = {},
): AuditManifestPair {
  return {
    expectation_id: expectationId,
    session_basename: basename,
    session_path: `/sessions/enc-main/${basename}`,
    status: "packetized",
    packet_path: `packets/${expectationId}/${basename.replace(/\.jsonl$/, "")}.md`,
    detail: "",
    ...overrides,
  };
}

function manifest(results: { id: string; pairs: AuditManifestPair[] }[]): AuditManifest {
  return {
    results: results.map((r) => ({
      id: r.id,
      evidence: `evidence prose for ${r.id}`,
      violation: `violation prose for ${r.id}`,
      pairs: r.pairs,
    })),
  };
}

/** The op's composed run-key-safe lane key: `<expectation id>.<1-based planned ordinal>`. */
function laneKey(ordinal: number): string {
  return `${GRILL}.${ordinal}`;
}

function report(basename: string, overrides: Record<string, unknown> = {}): unknown {
  return {
    expectation_id: GRILL,
    session_basename: basename,
    verdict: "satisfied",
    confidence: "high",
    citations: [2, 4],
    rationale: "clean",
    ...overrides,
  };
}

/** A recording in-memory `writeVerdicts` capability (the injected writer seam). */
function recordingWriter(): {
  files: Map<string, string>;
  write: (path: string, content: string) => void;
} {
  const files = new Map<string, string>();
  return { files, write: (path, content) => files.set(path, content) };
}

function writtenVerdicts(files: Map<string, string>): {
  bundle_dir: string;
  flow: string;
  lanes: AuditVerdictLane[];
} {
  const content = files.get(VERDICTS_PATH);
  assert.ok(content !== undefined, "verdicts.json was written to <bundle>/verdicts.json");
  assert.ok(content.endsWith("\n"), "the payload carries the trailing newline");
  return JSON.parse(content);
}

function assertWritten(
  outcome: AuditJudgmentOutcome,
): Extract<AuditJudgmentOutcome, { kind: "verdicts_written" }> {
  assert.equal(outcome.kind, "verdicts_written");
  assert.ok(outcome.kind === "verdicts_written");
  return outcome;
}

// ------------------------------------------------------------------------- the schema pin

test("AUDIT_VERDICT_SCHEMA pins the tri-state verdict shape (closed, all required, no conditionals)", () => {
  const s = AUDIT_VERDICT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, unknown> & {
      verdict: { enum: string[] };
      confidence: { enum: string[] };
      citations: { items: { type: string } };
    };
    if?: unknown;
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, [
    "expectation_id",
    "session_basename",
    "verdict",
    "confidence",
    "citations",
    "rationale",
  ]);
  assert.deepEqual(Object.keys(s.properties), s.required);
  // The literal enum values (the Python fold's vocabulary), not the derivation.
  assert.deepEqual(s.properties.verdict.enum, ["satisfied", "violated", "unclear"]);
  assert.deepEqual(s.properties.confidence.enum, ["high", "medium", "low"]);
  assert.equal(s.properties.citations.items.type, "integer");
  // NO if/then conditional — the violated⇒citations invariant is enforced at fold time (a
  // cite-less violated degrades to unchecked/auditor-unclear), never by failing the lane.
  assert.equal(s.if, undefined);
});

// ---------------------------------------------------------------------- the lenient decode

test("decodeAuditManifest: never throws; ill-typed rows are skipped; detail falls back", () => {
  assert.deepEqual(decodeAuditManifest(null), { results: [] });
  assert.deepEqual(decodeAuditManifest("junk"), { results: [] });
  assert.deepEqual(decodeAuditManifest({ results: "nope" }), { results: [] });

  const decoded = decodeAuditManifest({
    results: [
      "not an object",
      { id: 42, pairs: [] }, // ill-typed id → the whole row is skipped
      {
        id: GRILL,
        evidence: "the evidence",
        violation: 7, // ill-typed → degrades to ""
        pairs: [
          "not an object",
          { expectation_id: GRILL, session_basename: "a.jsonl" }, // no path/status → skipped
          {
            expectation_id: GRILL,
            session_basename: "a.jsonl",
            session_path: "/s/a.jsonl",
            status: "unboundable",
            packet_path: null,
            // detail missing → the code-owned fallback diagnostic, never empty/invented
          },
          {
            expectation_id: GRILL,
            session_basename: "b.jsonl",
            session_path: "/s/b.jsonl",
            status: "packetized",
            packet_path: "packets/x/b.md",
            detail: "kept verbatim",
          },
          {
            expectation_id: GRILL,
            session_basename: "c.jsonl",
            session_path: "/s/c.jsonl",
            status: "not-sampled",
            packet_path: null,
            detail: "", // blank on a degradation → the fallback (never an empty diagnosis)
          },
          {
            expectation_id: GRILL,
            session_basename: "d.jsonl",
            session_path: "/s/d.jsonl",
            status: "packetized",
            packet_path: "packets/x/d.md",
            detail: "", // blank on a packetized pair is legitimate (unused) — kept as-is
          },
        ],
      },
    ],
  });
  assert.equal(decoded.results.length, 1);
  const result = decoded.results[0];
  assert.ok(result);
  assert.equal(result.id, GRILL);
  assert.equal(result.evidence, "the evidence");
  assert.equal(result.violation, "");
  assert.equal(result.pairs.length, 4);
  assert.equal(result.pairs[0]?.detail, DETAIL_FALLBACK);
  assert.equal(result.pairs[1]?.detail, "kept verbatim");
  assert.equal(result.pairs[2]?.detail, DETAIL_FALLBACK);
  assert.equal(result.pairs[3]?.detail, "");
});

// ------------------------------------------- lane composition (via the recorded spawn)

test("judgeAuditBundle: packetized pairs only, ordinal-keyed, per-lane task composition", async () => {
  const m = manifest([
    {
      id: GRILL,
      pairs: [
        pair(GRILL, "s1.jsonl"),
        pair(GRILL, "s2.jsonl", {
          status: "unboundable",
          packet_path: null,
          detail: "over budget",
        }),
      ],
    },
    { id: ROUTE, pairs: [pair(ROUTE, "s1.jsonl")] },
  ]);
  const adapter = createMemoryWaveAdapter({});
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
    }),
  );
  assert.deepEqual(outcome.skippedPairs, [
    {
      expectation_id: GRILL,
      session_basename: "s2.jsonl",
      status: "unboundable",
      detail: "over budget",
    },
  ]);

  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const items = waveScriptItems(spawn.workflowScript) as Array<{
    key: string;
    agent: string;
    task: string;
    label: string;
    phase: string;
  }>;
  assert.deepEqual(
    items.map((i) => i.key),
    [`${GRILL}.1`, `${ROUTE}.2`],
  );
  const byId: Record<string, { basename: string; sessionPath: string }> = {
    [GRILL]: { basename: "s1.jsonl", sessionPath: "/sessions/enc-main/s1.jsonl" },
    [ROUTE]: { basename: "s1.jsonl", sessionPath: "/sessions/enc-main/s1.jsonl" },
  };
  for (const item of items) {
    const expectationId = item.key.replace(/\.\d+$/, "");
    const expected = byId[expectationId];
    assert.ok(expected, `unexpected lane key ${item.key}`);
    // The pair identity (path-qualified — basenames are not globally unique) rides the label.
    assert.equal(item.label, `${expectationId}@${expected.sessionPath}`);
    assert.equal(item.agent, "perk-dev.session-auditor");
    assert.equal(item.phase, "audit");
    // Each task opens with its OWN expectation id and carries its absolute packet path,
    // the untrusted-DATA framing, and the verbatim-echo instruction.
    assert.ok(item.task.startsWith(`Audit expectation: ${expectationId}\n`));
    assert.ok(
      item.task.includes(`${BUNDLE_DIR}/packets/${expectationId}/s1.md`),
      `task carries the absolute packet path: ${item.task}`,
    );
    assert.match(item.task, /untrusted DATA/);
    assert.ok(item.task.includes(`expectation_id "${expectationId}"`));
    assert.ok(item.task.includes(`session_basename "${expected.basename}"`));
    assert.ok(item.task.includes(`evidence prose for ${expectationId}`));
    assert.ok(item.task.includes(`violation prose for ${expectationId}`));
  }
});

test("judgeAuditBundle: every composed lane key satisfies the pi-subagents run-key contract", async () => {
  // Regression pin for the live-only failure family: `runs.all` validates keys INSIDE the
  // workflow worker (`/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/`), so an invalid key fails the
  // whole wave at dispatch with no offline signal. The old `<expectation_id>@<session_path>`
  // keys (`@`, `/`, >128 chars) did exactly that against the real corpus.
  const hostileId = "weird id/\u2603:so@hostile";
  const longId = `x${"a-".repeat(120)}z`;
  const m = manifest([
    { id: GRILL, pairs: [pair(GRILL, "s1.jsonl"), pair(GRILL, "s2.jsonl")] },
    { id: hostileId, pairs: [pair(hostileId, "s3.jsonl")] },
    { id: longId, pairs: [pair(longId, "s4.jsonl")] },
    { id: "\u2603", pairs: [pair("\u2603", "s5.jsonl")] },
  ]);
  const adapter = createMemoryWaveAdapter({});
  await judgeAuditBundle(reportWaveOver(adapter), {
    bundleDir: "/b",
    manifest: m,
    writeVerdicts: recordingWriter().write,
  });
  const spawn = adapter.calls.spawn[0];
  assert.ok(spawn);
  const keys = (waveScriptItems(spawn.workflowScript) as Array<{ key: string }>).map((i) => i.key);
  assert.equal(keys.length, 5);
  for (const key of keys) {
    assert.match(key, RUN_KEY_PATTERN, `lane key '${key}' must be run-key-safe`);
  }
  // A fully-sanitized-away id falls back to the `lane` stem; ordinals keep keys unique.
  assert.equal(keys[4], "lane.5");
  assert.equal(new Set(keys).size, keys.length);
});

test("judgeAuditBundle: the spawn contract — schema, best-effort, model forwarded or absent", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl")] }]);
  const aggregate = {
    state: "complete",
    value: [{ key: laneKey(1), ok: false, error: "x", report: null }],
  };

  const withModel = createMemoryWaveAdapter({ aggregate });
  await judgeAuditBundle(reportWaveOver(withModel), {
    bundleDir: "/b",
    manifest: m,
    writeVerdicts: recordingWriter().write,
    model: "faux/auditor",
  });
  const spawn = withModel.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.equal(spawn.outputSchema, AUDIT_VERDICT_SCHEMA);
  assert.equal(spawn.model, "faux/auditor");
  assert.match(spawn.workflowScript, /perk-dev\.session-auditor/);
  assert.equal(withModel.calls.spawn.length, 1, "ONE attempt, no retry");

  const withoutModel = createMemoryWaveAdapter({ aggregate });
  await judgeAuditBundle(reportWaveOver(withoutModel), {
    bundleDir: "/b",
    manifest: m,
    writeVerdicts: recordingWriter().write,
  });
  assert.equal(withoutModel.calls.spawn[0]?.model, undefined);
});

// --------------------------------------------------------------- the zero-lane short-circuits

test("judgeAuditBundle: a zero-exercising manifest short-circuits — no launch, verdicts written", async () => {
  const adapter = createMemoryWaveAdapter({});
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: manifest([{ id: GRILL, pairs: [] }]),
      writeVerdicts: writer.write,
    }),
  );
  assert.equal(adapter.calls.spawn.length, 0, "the wave must NOT be launched");
  assert.deepEqual(outcome.wave, { complete: true });
  assert.deepEqual(outcome.lanes, []);
  assert.equal(outcome.verdictsPath, VERDICTS_PATH);
  assert.deepEqual(writtenVerdicts(writer.files), {
    bundle_dir: BUNDLE_DIR,
    flow: "audit",
    lanes: [],
  });
});

test("judgeAuditBundle: an all-degraded manifest short-circuits with the degrade bucket written", async () => {
  const twinA = pair(GRILL, "twin.jsonl", { session_path: "/s/a/twin.jsonl" });
  const twinB = pair(GRILL, "twin.jsonl", { session_path: "/s/b/twin.jsonl" });
  const adapter = createMemoryWaveAdapter({});
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: manifest([{ id: GRILL, pairs: [twinA, twinB] }]),
      writeVerdicts: writer.write,
    }),
  );
  assert.equal(adapter.calls.spawn.length, 0, "the wave must NOT be launched");
  assert.deepEqual(outcome.wave, { complete: true });
  const written = writtenVerdicts(writer.files);
  assert.equal(written.lanes.length, 2);
  for (const lane of written.lanes) {
    assert.equal(lane.status, "lane-failed");
    assert.equal(lane.detail, "duplicate session basename in bundle — ambiguous packet identity");
  }
  // session_path stays code-owned — the twins remain distinguishable in the written file.
  assert.deepEqual(
    written.lanes.map((l) => l.session_path),
    ["/s/a/twin.jsonl", "/s/b/twin.jsonl"],
  );
});

test("judgeAuditBundle: a packetized pair without packet_path degrades (defensive arm)", async () => {
  const broken = pair(GRILL, "s1.jsonl", { packet_path: null });
  const adapter = createMemoryWaveAdapter({});
  const writer = recordingWriter();
  await judgeAuditBundle(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    manifest: manifest([{ id: GRILL, pairs: [broken] }]),
    writeVerdicts: writer.write,
  });
  assert.equal(adapter.calls.spawn.length, 0);
  const written = writtenVerdicts(writer.files);
  assert.equal(written.lanes.length, 1);
  assert.equal(written.lanes[0]?.status, "lane-failed");
  assert.match(written.lanes[0]?.detail ?? "", /no packet_path/);
});

// ------------------------------------------------------------ the verdicts write matrix

test("judgeAuditBundle: the write matrix — report / lane-failed / malformed / echo-mismatch / out-of-vocab / collision, in deterministic manifest order", async () => {
  const twinA = pair(GRILL, "twin.jsonl", { session_path: "/sessions/enc-a/twin.jsonl" });
  const twinB = pair(GRILL, "twin.jsonl", { session_path: "/sessions/enc-b/twin.jsonl" });
  // The manifest INTERLEAVES the collision twins between dispatchable pairs, so a reducer that
  // retained degrades in their manifest positions (instead of appending them after the planned
  // lanes) would produce a different sequence — the order pin below discriminates.
  const m = manifest([
    {
      id: GRILL,
      pairs: [
        pair(GRILL, "ok.jsonl"),
        twinA,
        pair(GRILL, "failed.jsonl"),
        pair(GRILL, "malformed.jsonl"),
        twinB,
        pair(GRILL, "mismatch.jsonl"),
        pair(GRILL, "vocab.jsonl"),
        pair(GRILL, "skipped.jsonl", {
          status: "unboundable",
          packet_path: null,
          detail: "over budget",
        }),
      ],
    },
  ]);
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      // The aggregate is SHUFFLED relative to the lane plan: a reducer that iterated aggregate
      // order (instead of projecting planned lanes in manifest order) would fail the pin.
      value: [
        {
          key: laneKey(5),
          ok: true,
          error: null,
          // An out-of-vocabulary verdict must never reach verdicts.json — the Python fold's
          // validate() rejects unknown vocabulary wholesale.
          report: report("vocab.jsonl", { verdict: "guilty" }),
        },
        { key: laneKey(3), report: [] }, // no boolean ok → malformed-report
        { key: laneKey(1), ok: true, error: null, report: report("ok.jsonl") },
        {
          key: laneKey(4),
          ok: true,
          error: null,
          report: report("mismatch.jsonl", { session_basename: "other.jsonl" }),
        },
        { key: laneKey(2), ok: false, error: "auditor crashed", report: null },
      ],
    },
  });
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
    }),
  );
  assert.deepEqual(
    outcome.wave,
    { complete: true },
    "best-effort: lane failures never fail the wave",
  );
  assert.equal(outcome.verdictsPath, VERDICTS_PATH);

  const laneOf = (basename: string, sessionPath: string, rest: Record<string, unknown>) => ({
    expectation_id: GRILL,
    session_basename: basename,
    session_path: sessionPath,
    ...rest,
  });
  const failedShape = (status: string, detail: string) => ({
    status,
    verdict: null,
    confidence: null,
    citations: [],
    rationale: null,
    detail,
  });
  // The FULL ordered projection as one sequence: planned lanes in manifest order, the
  // pre-dispatch degrades appended — never per-lane lookups.
  const expectedLanes = [
    laneOf("ok.jsonl", "/sessions/enc-main/ok.jsonl", {
      status: "report",
      verdict: "satisfied",
      confidence: "high",
      citations: [2, 4],
      rationale: "clean",
      detail: "",
    }),
    laneOf("failed.jsonl", "/sessions/enc-main/failed.jsonl", {
      ...failedShape("lane-failed", "auditor crashed"),
    }),
    laneOf("malformed.jsonl", "/sessions/enc-main/malformed.jsonl", {
      ...failedShape(
        "malformed-report",
        `lane '${laneKey(3)}' aggregate entry has no boolean 'ok'`,
      ),
    }),
    laneOf("mismatch.jsonl", "/sessions/enc-main/mismatch.jsonl", {
      ...failedShape(
        "lane-failed",
        `echoed identity mismatch: report claims ${GRILL} × other.jsonl, lane graded ` +
          `${GRILL} × mismatch.jsonl`,
      ),
    }),
    laneOf("vocab.jsonl", "/sessions/enc-main/vocab.jsonl", {
      ...failedShape(
        "malformed-report",
        "auditor report fields are outside the verdict schema vocabulary",
      ),
    }),
    laneOf("twin.jsonl", "/sessions/enc-a/twin.jsonl", {
      ...failedShape(
        "lane-failed",
        "duplicate session basename in bundle — ambiguous packet identity",
      ),
    }),
    laneOf("twin.jsonl", "/sessions/enc-b/twin.jsonl", {
      ...failedShape(
        "lane-failed",
        "duplicate session basename in bundle — ambiguous packet identity",
      ),
    }),
  ];

  // Semantic deepEqual on the parsed writer payload: the exact key set + the exact lane objects.
  const written = writtenVerdicts(writer.files);
  assert.deepEqual(Object.keys(written), ["bundle_dir", "flow", "lanes"]);
  assert.equal(written.bundle_dir, BUNDLE_DIR);
  assert.equal(written.flow, "audit");
  assert.deepEqual(written.lanes, expectedLanes);
  assert.deepEqual(outcome.lanes, expectedLanes, "the outcome relays the written records");

  // The non-packetized pair is NOT a lane — it rides skippedPairs with its detail.
  assert.deepEqual(outcome.skippedPairs, [
    {
      expectation_id: GRILL,
      session_basename: "skipped.jsonl",
      status: "unboundable",
      detail: "over budget",
    },
  ]);
});

test("judgeAuditBundle: the sanitizer rejects each out-of-vocabulary field independently", async () => {
  // Every report below is otherwise valid and corrupts exactly ONE field, so deleting any one
  // of the sanitizer's independent checks (confidence, rationale, citations shape, citation
  // integrality, the expectation_id echo) turns exactly one expected lane green — no fixture
  // is rejected earlier by aggregate normalization.
  const m = manifest([
    {
      id: GRILL,
      pairs: [
        pair(GRILL, "conf.jsonl"),
        pair(GRILL, "rat.jsonl"),
        pair(GRILL, "cit-shape.jsonl"),
        pair(GRILL, "cit-frac.jsonl"),
        pair(GRILL, "echo.jsonl"),
      ],
    },
  ]);
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: laneKey(1),
          ok: true,
          error: null,
          report: report("conf.jsonl", { confidence: "certain" }),
        },
        { key: laneKey(2), ok: true, error: null, report: report("rat.jsonl", { rationale: 42 }) },
        {
          key: laneKey(3),
          ok: true,
          error: null,
          report: report("cit-shape.jsonl", { citations: "2, 4" }),
        },
        {
          key: laneKey(4),
          ok: true,
          error: null,
          report: report("cit-frac.jsonl", { citations: [2, 4.5] }),
        },
        {
          key: laneKey(5),
          ok: true,
          error: null,
          // The basename echoes correctly — only the expectation id mismatches (the write-matrix
          // mismatch case corrupts only the basename, so this arm pins the OTHER identity check).
          report: report("echo.jsonl", { expectation_id: "other.expectation" }),
        },
      ],
    },
  });
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
    }),
  );
  assert.deepEqual(outcome.wave, { complete: true });
  const vocabDetail = "auditor report fields are outside the verdict schema vocabulary";
  assert.deepEqual(
    writtenVerdicts(writer.files).lanes.map((l) => [l.session_basename, l.status, l.detail]),
    [
      ["conf.jsonl", "malformed-report", vocabDetail],
      ["rat.jsonl", "malformed-report", vocabDetail],
      ["cit-shape.jsonl", "malformed-report", vocabDetail],
      ["cit-frac.jsonl", "malformed-report", vocabDetail],
      [
        "echo.jsonl",
        "lane-failed",
        `echoed identity mismatch: report claims other.expectation × echo.jsonl, lane graded ` +
          `${GRILL} × echo.jsonl`,
      ],
    ],
  );
  // No corrupted field leaks into a written record — the verdict fields stay null-and-empty.
  for (const lane of writtenVerdicts(writer.files).lanes) {
    assert.equal(lane.verdict, null);
    assert.equal(lane.confidence, null);
    assert.deepEqual(lane.citations, []);
    assert.equal(lane.rationale, null);
  }
});

// -------------------------------------------------------------------- the wave-level failure

test("judgeAuditBundle: a wave-level failure fails ALL planned lanes with the wave-level detail", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl"), pair(GRILL, "s2.jsonl")] }]);
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(createMemoryWaveAdapter({ ping: null })), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
    }),
  );
  assert.deepEqual(outcome.wave, {
    complete: false,
    failure: {
      reason: "unavailable",
      detail:
        "pi-subagents did not advertise the report-wave capabilities (ping failed or incomplete)",
    },
  });
  const written = writtenVerdicts(writer.files);
  assert.equal(written.lanes.length, 2);
  for (const lane of written.lanes) {
    assert.equal(lane.status, "lane-failed");
    assert.match(lane.detail, /report-wave capabilities/);
  }
});

// ------------------------------------------------------------------------------ cancellation

test("judgeAuditBundle: a mid-flight abort stops the run, fails the lanes, and still writes", async () => {
  // Deterministic synchronization via the adapter seam (no timing sleeps): the abort fires
  // inside the spawn call — strictly AFTER the spawn is observed, strictly BEFORE any
  // completion could ever arrive (the run never completes).
  const inner = createMemoryWaveAdapter({ completion: false });
  const controller = new AbortController();
  const adapter: WaveAdapter = {
    ...inner,
    async spawn(params) {
      const handle = await inner.spawn(params);
      controller.abort();
      return handle;
    },
  };
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl"), pair(GRILL, "s2.jsonl")] }]);
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
      signal: controller.signal,
    }),
  );
  assert.equal(inner.calls.spawn.length, 1, "the wave was launched before the abort");
  assert.equal(inner.calls.stop.length, 1, "the aborted run is stopped (best-effort)");
  assert.equal(outcome.wave.complete, false);
  assert.ok(!outcome.wave.complete);
  assert.equal(outcome.wave.failure.reason, "cancelled");
  const written = writtenVerdicts(writer.files);
  assert.equal(written.lanes.length, 2);
  for (const lane of written.lanes) {
    assert.equal(lane.status, "lane-failed");
    assert.equal(lane.detail, outcome.wave.failure.detail);
  }
});

test("judgeAuditBundle: a pre-aborted signal settles as cancelled — no spawn, verdicts written", async () => {
  const adapter = createMemoryWaveAdapter({});
  const controller = new AbortController();
  controller.abort();
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl")] }]);
  const writer = recordingWriter();
  const outcome = assertWritten(
    await judgeAuditBundle(reportWaveOver(adapter), {
      bundleDir: BUNDLE_DIR,
      manifest: m,
      writeVerdicts: writer.write,
      signal: controller.signal,
    }),
  );
  assert.equal(adapter.calls.spawn.length, 0, "a pre-aborted wave never spawns");
  assert.equal(outcome.wave.complete, false);
  assert.ok(!outcome.wave.complete);
  assert.equal(outcome.wave.failure.reason, "cancelled");
  const written = writtenVerdicts(writer.files);
  assert.equal(written.lanes.length, 1);
  assert.equal(written.lanes[0]?.status, "lane-failed");
});

// ------------------------------------------------------------------------- the write failure

test("judgeAuditBundle: a throwing writer returns write_failed with the in-memory lanes", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl")] }]);
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: laneKey(1), ok: true, error: null, report: report("s1.jsonl") }],
    },
  });
  const outcome = await judgeAuditBundle(reportWaveOver(adapter), {
    bundleDir: BUNDLE_DIR,
    manifest: m,
    writeVerdicts: () => {
      throw new Error("disk full");
    },
  });
  assert.equal(outcome.kind, "write_failed");
  assert.ok(outcome.kind === "write_failed");
  assert.match(outcome.detail, /disk full/);
  // The in-memory lane records ride the outcome so a caller can still present the leads.
  assert.equal(outcome.lanes.length, 1);
  assert.equal(outcome.lanes[0]?.status, "report");
});
