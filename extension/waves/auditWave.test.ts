// The audit-wave entrypoint's suite: the verdict-schema pin, the lenient manifest decode (+ the
// code-owned detail fallback), lane construction (packetized-only, session_path-keyed, the
// basename-collision degrade), the zero-lane short-circuit, and memory-adapter runs (reports
// mapped, best-effort lane failure retained, model forwarded/absent).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AUDIT_VERDICT_SCHEMA,
  type AuditManifest,
  type AuditManifestPair,
  buildAuditLanes,
  DETAIL_FALLBACK,
  decodeAuditManifest,
  runAuditWave,
} from "./auditWave.ts";
import { createMemoryWaveAdapter } from "./memoryAdapter.ts";

const GRILL = "plan.grill-before-review";
const ROUTE = "objective-plan.route-explorer-report";

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

// -------------------------------------------------------------------------- lane building

test("buildAuditLanes: packetized pairs only, session_path-keyed, per-key task composition", () => {
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
  const plan = buildAuditLanes(m, "/abs/bundle");
  assert.deepEqual(
    plan.planned.map((p) => p.key),
    [`${GRILL}@/sessions/enc-main/s1.jsonl`, `${ROUTE}@/sessions/enc-main/s1.jsonl`],
  );
  assert.deepEqual(plan.degraded, []);
  assert.equal(plan.skipped.length, 1);
  assert.equal(plan.skipped[0]?.status, "unboundable");

  for (const planned of plan.planned) {
    assert.equal(planned.lane.key, planned.key);
    assert.equal(planned.lane.label, planned.key);
    assert.equal(planned.lane.agent, "perk-dev.session-auditor");
    assert.equal(planned.lane.phase, "audit");
    // Each task opens with its OWN expectation id and carries its absolute packet path,
    // the untrusted-DATA framing, and the verbatim-echo instruction.
    assert.ok(planned.lane.task.startsWith(`Audit expectation: ${planned.pair.expectation_id}\n`));
    assert.ok(
      planned.lane.task.includes(`/abs/bundle/packets/${planned.pair.expectation_id}/s1.md`),
      `task carries the absolute packet path: ${planned.lane.task}`,
    );
    assert.match(planned.lane.task, /untrusted DATA/);
    assert.ok(planned.lane.task.includes(`expectation_id "${planned.pair.expectation_id}"`));
    assert.ok(planned.lane.task.includes(`session_basename "${planned.pair.session_basename}"`));
    assert.ok(planned.lane.task.includes(`evidence prose for ${planned.pair.expectation_id}`));
    assert.ok(planned.lane.task.includes(`violation prose for ${planned.pair.expectation_id}`));
  }
});

test("buildAuditLanes: duplicate-basename packetized pairs degrade; unaffected lanes still dispatch", () => {
  const twinA = pair(GRILL, "twin.jsonl", { session_path: "/sessions/enc-a/twin.jsonl" });
  const twinB = pair(GRILL, "twin.jsonl", { session_path: "/sessions/enc-b/twin.jsonl" });
  const solo = pair(GRILL, "solo.jsonl");
  const plan = buildAuditLanes(manifest([{ id: GRILL, pairs: [twinA, twinB, solo] }]), "/b");
  assert.deepEqual(
    plan.planned.map((p) => p.pair.session_basename),
    ["solo.jsonl"],
  );
  assert.equal(plan.degraded.length, 2);
  for (const { pair: degraded, detail } of plan.degraded) {
    assert.equal(degraded.session_basename, "twin.jsonl");
    assert.equal(detail, "duplicate session basename in bundle — ambiguous packet identity");
  }
  assert.deepEqual(plan.skipped, []);
});

test("buildAuditLanes: a packetized pair without packet_path degrades (defensive arm)", () => {
  const broken = pair(GRILL, "s1.jsonl", { packet_path: null });
  const plan = buildAuditLanes(manifest([{ id: GRILL, pairs: [broken] }]), "/b");
  assert.deepEqual(plan.planned, []);
  assert.equal(plan.degraded.length, 1);
  assert.match(plan.degraded[0]?.detail ?? "", /no packet_path/);
});

// --------------------------------------------------------------- the zero-lane short-circuit

test("runAuditWave: a zero-exercising manifest short-circuits — no launch, synthetic complete", async () => {
  const adapter = createMemoryWaveAdapter({});
  const outcome = await runAuditWave(adapter, {
    bundleDir: "/b",
    manifest: manifest([{ id: GRILL, pairs: [] }]),
  });
  assert.equal(outcome.result.complete, true);
  assert.deepEqual(outcome.result.reports, []);
  assert.deepEqual(outcome.result.failures, []);
  assert.deepEqual(outcome.plan.planned, []);
  assert.equal(adapter.calls.spawn.length, 0, "the wave must NOT be launched");
});

test("runAuditWave: an all-degraded manifest short-circuits with the degrade bucket intact", async () => {
  const twinA = pair(GRILL, "twin.jsonl", { session_path: "/s/a/twin.jsonl" });
  const twinB = pair(GRILL, "twin.jsonl", { session_path: "/s/b/twin.jsonl" });
  const adapter = createMemoryWaveAdapter({});
  const outcome = await runAuditWave(adapter, {
    bundleDir: "/b",
    manifest: manifest([{ id: GRILL, pairs: [twinA, twinB] }]),
  });
  assert.equal(outcome.result.complete, true);
  assert.equal(adapter.calls.spawn.length, 0, "the wave must NOT be launched");
  assert.equal(outcome.plan.degraded.length, 2);
});

// ------------------------------------------------------------------- memory-adapter runs

function okEntry(key: string, report: Record<string, unknown>): unknown {
  return { key, ok: true, error: null, report };
}

test("runAuditWave: reports mapped by lane key; a failed lane is retained best-effort", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl"), pair(GRILL, "s2.jsonl")] }]);
  const keyS1 = `${GRILL}@/sessions/enc-main/s1.jsonl`;
  const keyS2 = `${GRILL}@/sessions/enc-main/s2.jsonl`;
  const report = {
    expectation_id: GRILL,
    session_basename: "s1.jsonl",
    verdict: "satisfied",
    confidence: "high",
    citations: [2],
    rationale: "clean",
  };
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [okEntry(keyS1, report), { key: keyS2, ok: false, error: "auditor crashed" }],
    },
  });
  const outcome = await runAuditWave(adapter, { bundleDir: "/b", manifest: m });
  // best-effort: a lane failure never fails the wave.
  assert.equal(outcome.result.complete, true);
  assert.deepEqual(outcome.result.reports, [{ key: keyS1, report }]);
  assert.deepEqual(outcome.result.failures, [
    { key: keyS2, reason: "lane-failed", detail: "auditor crashed" },
  ]);
  assert.equal(adapter.calls.spawn.length, 1, "ONE attempt, no retry");
});

test("runAuditWave: the spawn contract — schema, best-effort, model forwarded or absent", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl")] }]);
  const key = `${GRILL}@/sessions/enc-main/s1.jsonl`;
  const aggregate = {
    state: "complete",
    value: [{ key, ok: false, error: "x", report: null }],
  };

  const withModel = createMemoryWaveAdapter({ aggregate });
  await runAuditWave(withModel, { bundleDir: "/b", manifest: m, model: "faux/auditor" });
  const spawn = withModel.calls.spawn[0];
  assert.ok(spawn);
  assert.equal(spawn.async, true);
  assert.equal(spawn.mission, false);
  assert.equal(spawn.context, "fresh");
  assert.equal(spawn.outputSchema, AUDIT_VERDICT_SCHEMA);
  assert.equal(spawn.model, "faux/auditor");
  assert.match(spawn.workflowScript, /perk-dev\.session-auditor/);

  const withoutModel = createMemoryWaveAdapter({ aggregate });
  await runAuditWave(withoutModel, { bundleDir: "/b", manifest: m });
  assert.equal(withoutModel.calls.spawn[0]?.model, undefined);
});

test("runAuditWave: a wave-level failure comes back incomplete with the null-key failure", async () => {
  const m = manifest([{ id: GRILL, pairs: [pair(GRILL, "s1.jsonl")] }]);
  const outcome = await runAuditWave(createMemoryWaveAdapter({ ping: null }), {
    bundleDir: "/b",
    manifest: m,
  });
  assert.equal(outcome.result.complete, false);
  assert.deepEqual(
    outcome.result.failures.map((f) => [f.key, f.reason]),
    [[null, "unavailable"]],
  );
});
