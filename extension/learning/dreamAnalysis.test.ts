// The `analyzeDream` entry op's suite: the two-level ordering/recovery policy over the memory
// adapter with injected write/remove/marker/bracket capabilities — the entry-time removal
// invariant, the marker-clear-before-removal invariant, the incomplete/over-budget skip arms
// (bracket never invoked, `bracket: null`), the io_failed receipt retention (unverified clear,
// failed removal, bundle-write throw, finalize-write throw), the two-wave happy path with the
// bracket-then-finalize-in-place rewrite + digest marker, the drifted-bracket arm (no finalize,
// no marker set), the failed-marker-set honestly-incomplete arm, and the glue-boundary
// cancellation rule (an abort between the waves issues NO reducer spawn while retaining the
// analyst analyses + the exact cancelled attempt accounting). Fully offline.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { digestSessionData } from "../substrate/sessionData.ts";
import { createMemoryWaveAdapter } from "../testing/memoryAdapter.ts";
import { reportWaveOver } from "../waves/reportWave.ts";
import { type DreamManifest, decodeDreamManifest } from "./dream.ts";
import {
  analyzeDream,
  type DreamAnalysisAggregate,
  type DreamAnalysisOutcome,
} from "./dreamAnalysis.ts";
import {
  composeDreamBundle,
  DREAM_ANALYSES_FILENAME,
  DREAM_BUNDLE_BUDGET_BYTES,
  DREAM_REDUCER_ANGLES,
  finalizeDreamBundle,
} from "./dreamReducer.ts";

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

function dreamDoc(path: string): Record<string, unknown> {
  return { path, title: "T", read_when: "cue", cluster: "pi", bytes: 100 };
}

/** A strictly-valid raw dream manifest with derived doc_count/total_bytes. */
function rawManifest(
  lanes: { id: string; rollup: string | null; docs: Record<string, unknown>[] }[],
): Record<string, unknown> {
  const docCount = lanes.reduce((sum, lane) => sum + lane.docs.length, 0);
  const totalBytes = lanes.reduce(
    (sum, lane) => sum + lane.docs.reduce((s, d) => s + ((d.bytes as number) ?? 0), 0),
    0,
  );
  return {
    schema_version: "1",
    commit_sha: "abc123",
    registry_mode: "clusters",
    doc_count: docCount,
    total_bytes: totalBytes,
    findings: emptyFindings(),
    lanes,
  };
}

const MANIFEST_PATH = "/abs/scratch/runs/RUN/dream-manifest.json";
const BUNDLE_PATH = `/abs/scratch/runs/RUN/${DREAM_ANALYSES_FILENAME}`;

/** The analyst caps mirrored from the schema for the over-budget fixture (the exact values
 * are pinned by the analyst tier's own suite; this fixture only needs padded-at-caps rows). */
const LANE_DOCS_CAP = 8;

function decodedManifest(
  lanes: { id: string; rollup: string | null; docs: Record<string, unknown>[] }[],
): DreamManifest {
  const result = decodeDreamManifest(rawManifest(lanes), MANIFEST_PATH);
  assert.equal(result.ok, true, JSON.stringify(result));
  return (result as { ok: true; manifest: DreamManifest }).manifest;
}

const TWO_LANE_MANIFEST = () =>
  decodedManifest([
    {
      id: "pi-1",
      rollup: null,
      docs: [
        dreamDoc("docs/learned/pi/context-injection.md"),
        dreamDoc("docs/learned/pi/subagents.md"),
      ],
    },
    { id: "workflow-1", rollup: null, docs: [dreamDoc("docs/learned/workflow/report-waves.md")] },
  ]);

function docRow(path: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
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

function analystReportOf(
  docs: unknown[],
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    docs,
    overlap_signals: [],
    harvest_followups: [],
    uncertainties: [],
    overlap_signals_omitted: 0,
    harvest_followups_omitted: 0,
    uncertainties_omitted: 0,
    ...overrides,
  };
}

/** A complete analyst aggregate for TWO_LANE_MANIFEST (keys are the code-owned `<id>.<n>`). */
function completeAnalystAggregate(): { state: string; value: unknown } {
  return {
    state: "complete",
    value: [
      {
        key: "pi-1.1",
        ok: true,
        error: null,
        report: analystReportOf([
          docRow("docs/learned/pi/context-injection.md", { disposition: "revise" }),
          docRow("docs/learned/pi/subagents.md"),
        ]),
      },
      {
        key: "workflow-1.2",
        ok: true,
        error: null,
        report: analystReportOf([docRow("docs/learned/workflow/report-waves.md")]),
      },
    ],
  };
}

function reducerReportOf(angle: string, overrides: Record<string, unknown> = {}) {
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

/** A real stance on the fixture analysts' one non-keep proposal (context-injection, revise) —
 * decodable ONLY when the op threads `nonKeepProposals(analysis.analyses)` into the reducer
 * re-decode (an empty or wrong proposal set would malform the lane). */
const BRIDGE_STANCE = {
  doc: "docs/learned/pi/context-injection.md",
  disposition: "revise",
  stance: "endorse",
  reason: "verified against the checkout",
  evidence_checked: ["re-read the cited pointer"],
};

function completeReducerAggregate(): { state: string; value: unknown } {
  return {
    state: "complete",
    value: DREAM_REDUCER_ANGLES.map((angle, index) => ({
      key: angle,
      ok: true,
      error: null,
      report: reducerReportOf(angle, index === 0 ? { stances: [BRIDGE_STANCE] } : {}),
    })),
  };
}

/** The arbitrary manifest-bytes digest the op treats as an opaque token (only the adapter's
 * registered execute computes a real one). */
const MANIFEST_DIGEST = "sha256:test-manifest-digest";

/** Injected write/remove/marker/bracket capability spies: `events` records the shared
 * clear/remove/write/bracket/set ordering (the marker-before-removal, bracket-before-finalize,
 * and finalize-then-set invariants); `clearFails` makes the verified clear report failure;
 * `writeThrows` throws on every write, `finalizeThrows` only on the second (finalize) write;
 * `drift` makes the bracket report drift with that detail. */
function bundleSpies(
  opts: {
    clearFails?: boolean;
    setFails?: boolean;
    writeThrows?: string;
    finalizeThrows?: string;
    drift?: string;
  } = {},
): {
  writes: { path: string; content: string }[];
  removes: string[];
  events: string[];
  markBundleDigest: (digest: string) => boolean;
  bracket: () => { ok: boolean; detail: string | null };
  writeBundle: (path: string, content: string) => void;
  removeBundle: (path: string) => void;
} {
  const writes: { path: string; content: string }[] = [];
  const removes: string[] = [];
  const events: string[] = [];
  return {
    writes,
    removes,
    events,
    bracket: () => {
      events.push("bracket");
      return opts.drift !== undefined
        ? { ok: false, detail: opts.drift }
        : { ok: true, detail: null };
    },
    // The ONE function-shaped marker capability: "" is the invalidation clear.
    markBundleDigest: (digest) => {
      if (digest === "") {
        events.push("clear");
        return opts.clearFails !== true;
      }
      events.push(`set:${digest}`);
      return opts.setFails !== true;
    },
    writeBundle: (path, content) => {
      if (opts.writeThrows !== undefined) throw new Error(opts.writeThrows);
      if (opts.finalizeThrows !== undefined && writes.length === 1) {
        throw new Error(opts.finalizeThrows);
      }
      events.push("write");
      writes.push({ path, content });
    },
    removeBundle: (path) => {
      events.push("remove");
      removes.push(path);
    },
  };
}

/** Narrow to the aggregate arm (the post-launch matrices' common path). */
function aggregateOf(outcome: DreamAnalysisOutcome): DreamAnalysisAggregate {
  assert.equal(outcome.kind, "aggregate", JSON.stringify(outcome).slice(0, 400));
  return (outcome as { kind: "aggregate"; details: DreamAnalysisAggregate }).details;
}

test("analyzeDream: an incomplete first wave skips write + reducers (entry removal still runs)", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: "pi-1.1",
          ok: true,
          error: null,
          report: analystReportOf([
            docRow("docs/learned/pi/context-injection.md"),
            docRow("docs/learned/pi/subagents.md"),
          ]),
        },
        { key: "workflow-1.2", ok: false, error: "analyst crashed", report: null },
      ],
    },
  });
  const spies = bundleSpies();
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  assert.equal(details.complete, false);
  assert.equal(details.analysis.complete, false);
  assert.equal(details.analysis.analyses.length, 1, "surviving analyses retained");
  assert.deepEqual(details.analysis.failures, [
    { lane: "workflow-1", reason: "lane-failed", detail: "analyst crashed" },
  ]);
  assert.equal(details.bundle, null, "the bundle is never composed on an incomplete first wave");
  assert.equal(details.bracket, null, "the bracket is never evaluated on an earlier arm");
  assert.deepEqual(details.reducers, {
    launched: false,
    skip_reason: "incomplete-analysis",
    complete: false,
    reports: [],
    failures: [],
  });
  // The entry-time removal invariant: the stale-bundle removal runs on EVERY arm — and the
  // marker is cleared FIRST, never set again (nothing finalized).
  assert.deepEqual(spies.removes, [BUNDLE_PATH]);
  assert.deepEqual(spies.events, ["clear", "remove"], "marker cleared before removal, no set");
  assert.deepEqual(spies.writes, [], "zero write calls");
  assert.equal(adapter.calls.spawn.length, 1, "zero reducer lanes spawned");
  assert.equal(details.attempts.length, 1);
  assert.equal(details.attempts[0]?.flow, "dream-analyst");
  assert.deepEqual(details.attempts[0]?.requestedKeys, ["pi-1.1", "workflow-1.2"]);
});

/** A big manifest + padded-at-caps analyst aggregate whose bundle exceeds the byte budget. */
function overBudgetFixture(): {
  manifest: DreamManifest;
  aggregate: { state: string; value: unknown };
} {
  const laneCount = 16;
  const lanes = Array.from({ length: laneCount }, (_, i) => ({
    id: `big-${i + 1}`,
    rollup: null,
    docs: Array.from({ length: LANE_DOCS_CAP }, (_, j) =>
      dreamDoc(`docs/learned/big/d${i + 1}-${j + 1}.md`),
    ),
  }));
  const manifest = decodedManifest(lanes);
  const value = lanes.map((lane, i) => ({
    key: `big-${i + 1}.${i + 1}`,
    ok: true,
    error: null,
    report: analystReportOf(
      lane.docs.map((doc) =>
        docRow(doc.path as string, {
          disposition: "revise",
          rationale: "r".repeat(500),
          preserve: Array.from({ length: 4 }, () => "p".repeat(300)),
          evidence_checked: Array.from({ length: 6 }, () => "e".repeat(250)),
        }),
      ),
      { uncertainties: Array.from({ length: 6 }, () => "u".repeat(300)) },
    ),
  }));
  return { manifest, aggregate: { state: "complete", value } };
}

test("analyzeDream: an over-budget bundle refuses with accounting — nothing written, no reducers", async () => {
  const { manifest, aggregate } = overBudgetFixture();
  const adapter = createMemoryWaveAdapter({ aggregate });
  const spies = bundleSpies();
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  assert.equal(details.complete, false);
  assert.equal(details.analysis.complete, true, "the first wave WAS complete");
  assert.ok(details.bundle, "the budget arm carries explicit accounting");
  assert.equal(details.bundle?.written, false);
  assert.ok((details.bundle?.bytes ?? 0) > DREAM_BUNDLE_BUDGET_BYTES, "sanity: over budget");
  assert.equal(details.bundle?.budget_bytes, DREAM_BUNDLE_BUDGET_BYTES);
  assert.equal(
    details.bundle?.overflow_bytes,
    (details.bundle?.bytes ?? 0) - DREAM_BUNDLE_BUDGET_BYTES,
    "overflow_bytes = bytes - budget_bytes",
  );
  assert.equal(details.reducers.launched, false);
  assert.equal(details.reducers.skip_reason, "budget-exceeded");
  assert.equal(details.bracket, null, "the bracket is never evaluated on the budget arm");
  assert.deepEqual(spies.writes, [], "zero write calls — never truncation");
  assert.equal(adapter.calls.spawn.length, 1, "zero reducer spawns");
  assert.deepEqual(spies.removes, [join(dirname(MANIFEST_PATH), DREAM_ANALYSES_FILENAME)]);
  assert.deepEqual(spies.events, ["clear", "remove"], "marker cleared, never set, no finalize");
  assert.equal(details.attempts.length, 1);
});

test("analyzeDream: a throwing entry-time removal is a typed io_failed refusal — zero spawns", async () => {
  // The removal failure arm: never an uncaught throw, never a launch over an irremovable
  // stale bundle — the typed refusal carries the (empty) retention shape.
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter();
  const spies = bundleSpies();
  const outcome = await analyzeDream(reportWaveOver(adapter), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markBundleDigest: spies.markBundleDigest,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: () => {
      spies.events.push("remove-attempt");
      throw new Error("EACCES: permission denied");
    },
  });
  assert.equal(outcome.kind, "io_failed");
  const failed = outcome as Extract<DreamAnalysisOutcome, { kind: "io_failed" }>;
  assert.match(failed.detail, /stale dream bundle removal failed/);
  assert.match(failed.detail, /EACCES/);
  assert.deepEqual(failed.analyses, [], "nothing analyzed yet — the retention shape is empty");
  assert.deepEqual(failed.attempts, [], "nothing launched yet — no attempt receipt");
  assert.equal(adapter.calls.spawn.length, 0, "nothing spawns on a failed entry removal");
  assert.deepEqual(spies.writes, [], "nothing written");
  // The invalidation record: the marker was cleared BEFORE the removal attempt, so the files
  // the failed cleanup left behind are refused by recovery (fail-closed).
  assert.deepEqual(spies.events, ["clear", "remove-attempt"], "clear precedes the removal");
});

test("analyzeDream: an UNVERIFIED marker clear refuses io_failed before ANY filesystem work or spawn", async () => {
  // The fail-closed hazard this refusal prevents: with the old digest possibly still live, a
  // subsequent removal failure would leave the prior bundle + prior digest PAIR intact and
  // recoverable as fresh. The refusal fires before the removal even runs, so no mutation (and
  // no such mixed state) can happen — asserted here with a remove spy that would also fail.
  const adapter = createMemoryWaveAdapter();
  const spies = bundleSpies({ clearFails: true });
  const outcome = await analyzeDream(reportWaveOver(adapter), {
    manifest: TWO_LANE_MANIFEST(),
    manifestDigest: MANIFEST_DIGEST,
    markBundleDigest: spies.markBundleDigest,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: (path) => {
      spies.events.push("remove-attempt");
      throw new Error(`EACCES: permission denied '${path}'`);
    },
  });
  assert.equal(outcome.kind, "io_failed");
  const failed = outcome as Extract<DreamAnalysisOutcome, { kind: "io_failed" }>;
  assert.match(failed.detail, /dream_bundle_digest invalidation could not be verified/);
  assert.match(failed.detail, /possibly-recoverable prior finalized state/);
  assert.deepEqual(failed.analyses, [], "the retention shape is empty — nothing ran");
  assert.deepEqual(failed.attempts, []);
  assert.equal(adapter.calls.spawn.length, 0, "nothing spawns");
  assert.deepEqual(spies.writes, [], "nothing written");
  assert.deepEqual(
    spies.events,
    ["clear"],
    "the refusal fires BEFORE the removal attempt — no filesystem mutation is possible, so a " +
      "failed clear can never combine with a failed removal into a stale recoverable pair",
  );
});

test("analyzeDream: a bundle-write throw is the io_failed arm retaining analyses + attempts", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({ aggregate: completeAnalystAggregate() });
  const spies = bundleSpies({ writeThrows: "disk full" });
  const outcome = await analyzeDream(reportWaveOver(adapter), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markBundleDigest: spies.markBundleDigest,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  assert.equal(outcome.kind, "io_failed");
  const failed = outcome as Extract<DreamAnalysisOutcome, { kind: "io_failed" }>;
  assert.match(failed.detail, /dream bundle write failed: disk full/);
  assert.equal(failed.analyses.length, 2, "the analyst analyses ride the retention shape");
  assert.equal(failed.attempts.length, 1, "the analyst attempt receipt is retained");
  assert.equal(failed.attempts[0]?.flow, "dream-analyst");
  assert.equal(adapter.calls.spawn.length, 1, "no reducer spawn after a failed write");
  assert.deepEqual(spies.removes, [BUNDLE_PATH], "entry removal ran — the target stays absent");
  assert.deepEqual(spies.events, ["clear", "remove"], "the marker stays cleared");
});

test("analyzeDream: the happy path — analyst write, reducers read it, finalize rewrite + marker", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies();
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      analystModel: "faux/analyst",
      reducerModel: "faux/reducer",
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  assert.equal(details.complete, true);
  assert.equal(details.analysis.complete, true);
  assert.deepEqual(
    details.analysis.analyses.map((a) => a.lane),
    ["pi-1", "workflow-1"],
  );
  // TWO atomic writes of the ONE fixed name beside the manifest: the composed analyst bundle
  // the reducers read, then the finalize-in-place rewrite with the reducers section.
  assert.equal(spies.writes.length, 2);
  assert.equal(spies.writes[0]?.path, BUNDLE_PATH);
  const expected = composeDreamBundle(manifest, details.analysis.analyses);
  assert.equal(spies.writes[0]?.content, expected.content);
  assert.equal(spies.writes[1]?.path, BUNDLE_PATH, "the finalize rewrites the SAME fixed name");
  const finalized = finalizeDreamBundle(
    manifest,
    details.analysis.analyses,
    details.reducers.reports,
    MANIFEST_DIGEST,
  );
  assert.equal(spies.writes[1]?.content, finalized);
  assert.equal(
    (JSON.parse(finalized) as { manifest_digest: string }).manifest_digest,
    MANIFEST_DIGEST,
    "the caller's manifest digest is bound into the finalized bundle",
  );
  // The marker is set to the digest of the finalized bytes, after the finalize write — and
  // the bracket runs BETWEEN the reducer wave and the finalize write.
  assert.deepEqual(spies.events, [
    "clear",
    "remove",
    "write",
    "bracket",
    "write",
    `set:${digestSessionData(finalized)}`,
  ]);
  assert.deepEqual(details.bracket, { ok: true, detail: null });
  assert.deepEqual(details.bundle, {
    path: BUNDLE_PATH,
    written: true,
    bytes: expected.bytes,
    budget_bytes: DREAM_BUNDLE_BUDGET_BYTES,
    overflow_bytes: 0,
  });
  assert.deepEqual(spies.removes, [BUNDLE_PATH], "entry removal precedes the write");
  // The reducer wave launched over the written path, with its own model.
  assert.equal(adapter.calls.spawn.length, 2);
  assert.equal(adapter.calls.spawn[0]?.model, "faux/analyst");
  assert.equal(adapter.calls.spawn[1]?.model, "faux/reducer");
  assert.ok(
    adapter.calls.spawn[1]?.workflowScript.includes(BUNDLE_PATH),
    "the reducer lanes read the written bundle path",
  );
  assert.ok(adapter.calls.spawn[1]?.workflowScript.includes(MANIFEST_PATH));
  assert.equal(details.reducers.launched, true);
  assert.equal(details.reducers.skip_reason, null);
  assert.equal(details.reducers.complete, true);
  assert.deepEqual(
    details.reducers.reports.map((r) => r.angle),
    [...DREAM_REDUCER_ANGLES],
  );
  // The nonKeepProposals bridge is LIVE: the stance echoing the analyst's actual non-keep
  // proposal survives the reducer re-decode into the aggregate — an empty or wrong proposal
  // set passed to the reducer wave would have malformed this lane instead.
  assert.deepEqual(details.reducers.reports[0]?.report.stances, [BRIDGE_STANCE]);
  // Two attempt receipts whose requestedKeys are each wave's code-owned orchestration keys.
  assert.deepEqual(
    details.attempts.map((a) => [a.flow, a.attempt]),
    [
      ["dream-analyst", 1],
      ["dream-reducer", 1],
    ],
  );
  assert.deepEqual(details.attempts[0]?.requestedKeys, ["pi-1.1", "workflow-1.2"]);
  assert.deepEqual(details.attempts[1]?.requestedKeys, [...DREAM_REDUCER_ANGLES]);
});

test("analyzeDream: a finalize-write throw is the second io_failed arm — marker stays cleared", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies({ finalizeThrows: "disk full at finalize" });
  const outcome = await analyzeDream(reportWaveOver(adapter), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markBundleDigest: spies.markBundleDigest,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  assert.equal(outcome.kind, "io_failed");
  const failed = outcome as Extract<DreamAnalysisOutcome, { kind: "io_failed" }>;
  assert.match(failed.detail, /dream bundle finalize write failed: disk full at finalize/);
  assert.equal(failed.analyses.length, 2, "the analyst analyses ride the retention shape");
  assert.deepEqual(
    failed.attempts.map((a) => a.flow),
    ["dream-analyst", "dream-reducer"],
    "BOTH attempt receipts are retained (the finalize failed after the reducer wave)",
  );
  assert.equal(spies.writes.length, 1, "only the analyst bundle landed");
  assert.deepEqual(
    spies.events,
    ["clear", "remove", "write", "bracket"],
    "the marker is never set (the bracket passed; the finalize write threw)",
  );
});

test("analyzeDream: a failed marker set is an honestly-incomplete aggregate, never io_failed", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies({ setFails: true });
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  // The wave RAN (both waves + the finalize write landed) — the outcome is honest
  // incompleteness with a named digest-marker failure entry, not the io_failed arm.
  assert.equal(details.complete, false);
  assert.equal(details.analysis.complete, true);
  assert.equal(details.reducers.complete, true);
  const markerFailure = details.reducers.failures.find((f) => f.angle === "digest-marker");
  assert.ok(markerFailure, "the digest-marker failure entry is present");
  assert.match(markerFailure.detail, /marker append failed its read-back/);
  assert.equal(spies.writes.length, 2, "the finalize write landed before the marker set");
  assert.equal(details.bracket?.ok, true, "the bracket passed — only the marker set failed");
});

test("analyzeDream: a drifted bracket skips the finalize AND the marker set", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies({ drift: "HEAD moved from aaa to bbb" });
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  assert.equal(details.complete, false, "a drifted wave is never complete");
  assert.equal(details.analysis.complete, true, "both waves DID complete");
  assert.equal(details.reducers.complete, true);
  assert.deepEqual(details.bracket, { ok: false, detail: "HEAD moved from aaa to bbb" });
  assert.equal(
    details.analysis.analyses.length,
    2,
    "analyses retained for honest coverage reporting",
  );
  assert.equal(details.reducers.reports.length, DREAM_REDUCER_ANGLES.length);
  // NO finalize write, NO marker set: the write spy saw exactly the one analyst-bundle write,
  // and the entry clear stands — recovery refuses the analyses-only bundle, so a drifted wave
  // is structurally undraftable.
  assert.equal(spies.writes.length, 1, "exactly one bundle write — the finalize never ran");
  assert.deepEqual(spies.events, ["clear", "remove", "write", "bracket"], "no marker set");
});

test("analyzeDream: a reducer lane failure ⇒ complete: false with analyses retained", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const reducerAggregate = {
    state: "complete",
    value: [
      {
        key: DREAM_REDUCER_ANGLES[0],
        ok: true,
        error: null,
        report: reducerReportOf(DREAM_REDUCER_ANGLES[0]),
      },
      { key: DREAM_REDUCER_ANGLES[1], ok: false, error: "reducer crashed", report: null },
      {
        key: DREAM_REDUCER_ANGLES[2],
        ok: true,
        error: null,
        report: reducerReportOf(DREAM_REDUCER_ANGLES[2]),
      },
    ],
  };
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), reducerAggregate],
  });
  const spies = bundleSpies();
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: spies.writeBundle,
      removeBundle: spies.removeBundle,
    }),
  );
  assert.equal(details.complete, false, "an incomplete reducer wave fails the aggregate");
  assert.equal(details.analysis.complete, true, "analyst analyses retained");
  assert.equal(details.reducers.launched, true);
  assert.equal(details.reducers.complete, false);
  assert.deepEqual(details.reducers.failures, [
    { angle: DREAM_REDUCER_ANGLES[1], reason: "lane-failed", detail: "reducer crashed" },
  ]);
  assert.deepEqual(
    details.reducers.reports.map((r) => r.angle),
    [DREAM_REDUCER_ANGLES[0], DREAM_REDUCER_ANGLES[2]],
  );
  // No finalize on an incomplete reducer wave: the analyses-only bundle stays behind (the
  // finalized decode refuses it), the marker stays cleared, and the bracket is never invoked.
  assert.equal(spies.writes.length, 1, "the analyses-only bundle is left as-is");
  assert.deepEqual(spies.events, ["clear", "remove", "write"], "no marker set, no bracket");
  assert.equal(details.bracket, null, "the bracket is never evaluated on an earlier arm");
});

test("analyzeDream: cancellation at the glue boundary — no reducer spawn after an abort between the waves", async () => {
  // The report-waves glue-boundary rule: the analyst wave completes, the signal aborts before
  // the reducer launch — the op must not issue the reducer spawn, and the aggregate retains
  // the analyst analyses plus the exact cancelled reducer attempt accounting.
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({ aggregate: completeAnalystAggregate() });
  const controller = new AbortController();
  const spies = bundleSpies();
  const details = aggregateOf(
    await analyzeDream(reportWaveOver(adapter), {
      manifest,
      manifestDigest: MANIFEST_DIGEST,
      markBundleDigest: spies.markBundleDigest,
      bracket: spies.bracket,
      writeBundle: (path, content) => {
        // The abort lands between the waves: after the analyst wave completed (the bundle
        // write is the first post-wave step), before the reducer launch.
        controller.abort();
        spies.writeBundle(path, content);
      },
      removeBundle: spies.removeBundle,
      signal: controller.signal,
    }),
  );
  assert.equal(adapter.calls.spawn.length, 1, "NO reducer spawn is issued after the abort");
  assert.equal(details.complete, false);
  assert.equal(details.analysis.complete, true, "the completed analyst analyses are retained");
  assert.equal(details.analysis.analyses.length, 2);
  assert.equal(details.reducers.launched, true, "the reducer wave was entered, then cancelled");
  assert.equal(details.reducers.complete, false);
  assert.equal(details.reducers.failures[0]?.angle, null);
  assert.equal(details.reducers.failures[0]?.reason, "cancelled");
  assert.match(details.reducers.failures[0]?.detail ?? "", /dream-reducer/);
  // The exact cancelled attempt accounting: both receipts present, the reducer's cancelled
  // with zero children (nothing launched).
  assert.deepEqual(
    details.attempts.map((a) => [a.flow, a.state]),
    [
      ["dream-analyst", "complete"],
      ["dream-reducer", "cancelled"],
    ],
  );
  assert.deepEqual(details.attempts[1]?.children, []);
  assert.deepEqual(details.attempts[1]?.requestedKeys, [...DREAM_REDUCER_ANGLES]);
  // No bracket, no finalize, no marker set — the analyses-only bundle stays behind with a
  // cleared marker (recovery refuses it).
  assert.deepEqual(spies.events, ["clear", "remove", "write"]);
  assert.equal(spies.writes.length, 1);
});
