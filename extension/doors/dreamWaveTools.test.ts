// The `run_dream_wave` tool's suite: registration pins (NO parameters — the audit no-param
// shape, both the read and the write derived from the claimed run), the census pins
// (PERK_TOOLS + READ_ONLY_TOOLS, deliberately NO stage list), the ordered pre-spawn refusal
// ladder (claimed run → manifest existence → parse → strict decode → resolved containment;
// nothing spawns on any arm), the execute core's arms over the memory adapter with injected
// write/remove/marker/bracket spies (the entry-time removal invariant, the
// marker-clear-before-removal invariant, the incomplete/over-budget skip arms — bracket never
// invoked, `bracket: null` — the io_error receipt retention, the two-wave happy path with the
// bracket-then-finalize-in-place rewrite + digest marker, the drifted-bracket arm (no finalize,
// no marker set), the finalize-write io_error arm), and the fake-RPC e2e sinking both waves'
// spawn params (per-key config-model threading, analyst-before-reducer sequencing, the
// production marker wiring, the REAL default revalidation bracket over a git fixture — happy
// and drifted).

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runScratchDir } from "../substrate/cache.ts";
import { digestSessionData } from "../substrate/sessionData.ts";
import { PERK_TOOLS, READ_ONLY_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { dreamRepoCommit, initDreamRepo } from "../testing/dreamFixtures.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  composeDreamBundle,
  DREAM_ANALYSES_FILENAME,
  DREAM_BUNDLE_BUDGET_BYTES,
  DREAM_REDUCER_ANGLES,
  finalizeDreamBundle,
} from "../waves/dreamReducerWave.ts";
import {
  DREAM_ANALYST_CAPS,
  DREAM_MANIFEST_FILENAME,
  type DreamManifest,
  decodeDreamManifest,
} from "../waves/dreamWave.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import { WAVE_RPC_REPLY_EVENT_PREFIX, WAVE_RPC_REQUEST_EVENT } from "../waves/rpcAdapter.ts";
import {
  type DreamBundleMarkers,
  type DreamWaveOk,
  executeDreamWave,
  registerDreamWave,
} from "./dreamWaveTools.ts";

const RUN_ID = "01DREAMRUN00";

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
  overrides: Record<string, unknown> = {},
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
    ...overrides,
  };
}

function manifestJson(
  lanes?: { id: string; rollup: string | null; docs: Record<string, unknown>[] }[],
  overrides: Record<string, unknown> = {},
): string {
  const value = rawManifest(
    lanes ?? [
      {
        id: "pi-1",
        rollup: "Pi craft",
        docs: [dreamDoc("docs/learned/pi/subagents.md")],
      },
    ],
    overrides,
  );
  return `${JSON.stringify(value, null, 2)}\n`;
}

const MANIFEST_PATH = "/abs/scratch/runs/RUN/dream-manifest.json";
const BUNDLE_PATH = `/abs/scratch/runs/RUN/${DREAM_ANALYSES_FILENAME}`;

function decodedManifest(
  lanes: { id: string; rollup: string | null; docs: Record<string, unknown>[] }[],
  manifestPath: string = MANIFEST_PATH,
): DreamManifest {
  const result = decodeDreamManifest(rawManifest(lanes), manifestPath);
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
 * decodable ONLY when the door threads `nonKeepProposals(analysis.analyses)` into the reducer
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

/** The ReportTarget fake (mirrors harvestWaveTools.test.ts's target). */
function target(): { hasUI: boolean; ui: { notify: (m: string) => void } } {
  return { hasUI: true, ui: { notify: () => {} } };
}

/** The arbitrary manifest-bytes digest the execute-core tests thread through (the core treats
 * it as an opaque token; only the registered execute computes a real one). */
const MANIFEST_DIGEST = "sha256:test-manifest-digest";

/** Injected write/remove/marker/bracket spies for the execute core: `events` records the
 * shared clear/remove/write/bracket/set ordering (the marker-before-removal,
 * bracket-before-finalize, and finalize-then-set invariants); `clearFails` makes the verified
 * clear report failure; `writeThrows` throws on every write, `finalizeThrows` only on the
 * second (finalize) write; `drift` makes the bracket report drift with that detail. */
function bundleSpies(
  opts: {
    clearFails?: boolean;
    writeThrows?: string;
    finalizeThrows?: string;
    drift?: string;
  } = {},
): {
  writes: { path: string; content: string }[];
  removes: string[];
  events: string[];
  markers: DreamBundleMarkers;
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
    markers: {
      clear: () => {
        events.push("clear");
        return opts.clearFails !== true;
      },
      set: (digest) => {
        events.push(`set:${digest}`);
      },
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

// ------------------------------------------------------------------- registration pins

test("registerDreamWave: NO parameters (the audit no-param shape), the model-facing contract", () => {
  const tools = new Map<
    string,
    {
      label?: string;
      description?: string;
      parameters?: unknown;
      executionMode?: string;
      promptSnippet?: string;
      promptGuidelines?: string[];
    }
  >();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
  } as unknown as ExtensionAPI;
  registerDreamWave(pi);
  const def = tools.get("run_dream_wave");
  assert.ok(def, "run_dream_wave must register");
  assert.equal(def.label, "Run dream wave");
  assert.deepEqual(def.parameters, {
    type: "object",
    additionalProperties: false,
    properties: {},
  });
  assert.equal(def.executionMode, "sequential", "sequential is load-bearing");
  assert.match(def.description ?? "", /untrusted DATA/);
  assert.match(def.description ?? "", /No parameters/);
  assert.ok(
    typeof def.promptSnippet === "string" && def.promptSnippet !== "",
    "the model-facing contract is description + guidelines + snippet",
  );
  const guidelines = def.promptGuidelines ?? [];
  assert.ok(Array.isArray(guidelines) && guidelines.length > 0, "promptGuidelines must exist");
  const joined = guidelines.join("\n");
  assert.match(joined, /Call run_dream_wave ONCE, with no arguments/);
  assert.match(joined, /bound to this session's claimed run/);
  assert.match(joined, /untrusted DATA/);
  assert.match(joined, /present the coverage honestly/);
  assert.match(joined, /never retry the wave/);
});

// ------------------------------------------------------------------------- census pins

test("census: run_dream_wave rides PERK_TOOLS + READ_ONLY_TOOLS and NO stage list", () => {
  assert.ok(PERK_TOOLS.includes("run_dream_wave"));
  // The read-only carve-in: the seeded dream session runs GATED (the read-only
  // objective-author borrow); the tool takes NO parameters, its manifest read AND its one
  // write (the fixed-name run-scratch bundle) are both derived from the claimed run's
  // manifest path (the run_audit_wave no-aimable-writer posture, BOTH sides), and it spawns
  // only the read-only dream analysts/reducers over the carved-in delegation family.
  assert.ok(READ_ONLY_TOOLS.includes("run_dream_wave"));
  // The deliberate non-behavior pin: dream is cold-only and gate-on — the gate-ON set ignores
  // stage lists, so NO stage list carries the tool (we do NOT touch drive coverage).
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    assert.ok(!tools.includes("run_dream_wave"), `stage '${stage}' must not carry run_dream_wave`);
  }
});

// ----------------------------------------------------------- the pre-spawn refusal ladder

/** Scaffold a claimed dream session repo with the manifest planted at the run-scoped scratch
 * path (the door's binding). */
function scaffoldDreamRepo(opts: { manifest?: string | false } = {}): {
  cwd: string;
  manifestPath: string;
} {
  const cwd = scaffoldRepo({
    handoff: { runId: RUN_ID, mode: "read-only", stage: "objective-author" },
  });
  const manifestPath = join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME);
  if (opts.manifest !== false) {
    mkdirSync(dirname(manifestPath), { recursive: true });
    writeFileSync(manifestPath, opts.manifest ?? manifestJson(), "utf8");
  }
  return { cwd, manifestPath };
}

/** The fake pi-subagents RPC responder with a PER-SPAWN aggregate FIFO (the two-wave door). */
function fakeSubagentsRpc(
  aggregates: unknown[][],
  spawns: Record<string, unknown>[] = [],
): (pi: ExtensionAPI) => void {
  return (pi) => {
    let spawnCount = 0;
    pi.events.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const req = raw as { requestId?: unknown; method?: unknown };
      const reply = (payload: Record<string, unknown>): void => {
        pi.events.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${String(req.requestId)}`, {
          version: 1,
          requestId: req.requestId,
          method: req.method,
          ...payload,
        });
      };
      if (req.method === "ping") {
        reply({
          success: true,
          data: {
            capabilities: { asyncSpawn: true },
            methods: ["ping", "spawn", "stop"],
            events: { asyncComplete: "subagent:async-complete" },
          },
        });
        return;
      }
      if (req.method === "spawn") {
        spawns.push((raw as { params?: unknown }).params as Record<string, unknown>);
        const aggregate = aggregates[spawnCount] ?? [];
        spawnCount += 1;
        const asyncId = `wave-${spawnCount}`;
        const asyncDir = scaffoldRepo();
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({ state: "complete", workflow: { value: aggregate } }),
        );
        reply({ success: true, data: { text: "ok", details: { asyncId, asyncDir } } });
        pi.events.emit("subagent:async-complete", { id: asyncId, asyncDir });
      }
    });
  };
}

async function refusalArm(
  cwd: string,
  opts: { env?: Record<string, string | undefined> } = {},
): Promise<{ text: string; error_type?: string; spawns: Record<string, unknown>[] }> {
  const spawns: Record<string, unknown>[] = [];
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID, ...(opts.env ?? {}) },
    extraExtensions: [fakeSubagentsRpc([], spawns)],
  });
  try {
    const result = await h.invokeTool("run_dream_wave", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    return {
      text: result.content[0]?.text ?? "",
      ...(details.error_type !== undefined ? { error_type: details.error_type } : {}),
      spawns,
    };
  } finally {
    h.dispose();
  }
}

test("tool: a branch with no claimed run is bad_state (zero RPC traffic)", async () => {
  // A live warm session always mints a run_id, so this arm is driven through the captured tool
  // definition directly over a ctx whose branch carries NO run_id (the defensive first rung).
  const { cwd } = scaffoldDreamRepo();
  const emitted: string[] = [];
  const tools = new Map<
    string,
    {
      execute: (
        id: string,
        params: unknown,
        signal: undefined,
        onUpdate: undefined,
        ctx: unknown,
      ) => Promise<{ content: { text?: string }[]; details: unknown }>;
    }
  >();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
    events: {
      emit: (channel: string) => {
        emitted.push(channel);
      },
      on: () => () => {},
    },
  } as unknown as ExtensionAPI;
  registerDreamWave(pi);
  const ctx = {
    cwd,
    hasUI: true,
    ui: { notify: () => {} },
    sessionManager: {
      getBranch: () => [{ type: "custom", customType: "perk:workflow-state", data: {} }],
    },
  };
  const def = tools.get("run_dream_wave");
  assert.ok(def, "run_dream_wave must register");
  const result = await def.execute("tc-norun", {}, undefined, undefined, ctx);
  const details = result.details as { ok: boolean; error?: string; error_type?: string };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "bad_state");
  assert.match(details.error ?? "", /no claimed run in this session/);
  assert.deepEqual(emitted, [], "zero RPC traffic — nothing pinged, nothing spawned");
});

test("tool: a non-dream session is structurally refused (bad_state, nothing spawns)", async () => {
  // A warm session with no handoff MINTS its own run_id, so the structural refusal for a
  // non-dream session is the derived run-scoped path holding no dream manifest — the tool is
  // registered globally but unreachable outside a dream launch.
  const cwd = scaffoldRepo(); // no handoff — an ordinary minted-run session
  const { text, error_type, spawns } = await refusalArm(cwd, {
    env: { PERK_RUN_ID: undefined },
  });
  assert.equal(error_type, "bad_state");
  assert.match(text, /no dream manifest for this run/);
  assert.match(text, /run `perk learn dream` first/);
  assert.equal(spawns.length, 0);
});

test("tool: a claimed run with no run-scoped manifest is bad_state", async () => {
  const { cwd } = scaffoldDreamRepo({ manifest: false });
  const { text, error_type, spawns } = await refusalArm(cwd);
  assert.equal(error_type, "bad_state");
  assert.match(text, /no dream manifest for this run/);
  assert.equal(spawns.length, 0);
});

test("tool: unparseable JSON at the bound path is bad_input naming the parse detail", async () => {
  const { cwd } = scaffoldDreamRepo({ manifest: "{not json" });
  const { text, error_type, spawns } = await refusalArm(cwd);
  assert.equal(error_type, "bad_input");
  assert.match(text, /dream manifest unreadable/);
  assert.equal(spawns.length, 0);
});

test("tool: manifest-validation failures surface the strict decoder's named detail", async () => {
  const cases: { manifest: string; detail: RegExp }[] = [
    {
      manifest: manifestJson(undefined, { schema_version: "2" }),
      detail: /schema_version must be the string "1"/,
    },
    {
      manifest: manifestJson([{ id: "pi-1", rollup: null, docs: [dreamDoc("../secrets")] }]),
      detail: /doc path '\.\.\/secrets' escapes the checkout/,
    },
    {
      manifest: manifestJson(undefined, { doc_count: 99 }),
      detail: /doc_count \(99\) does not match/,
    },
  ];
  for (const arm of cases) {
    const { cwd } = scaffoldDreamRepo({ manifest: arm.manifest });
    const { text, error_type, spawns } = await refusalArm(cwd);
    assert.equal(error_type, "bad_input");
    assert.match(text, arm.detail);
    assert.equal(spawns.length, 0);
  }
});

test("tool: an escaping-symlink doc refuses the wave (the resolved containment arm)", async () => {
  const { cwd } = scaffoldDreamRepo({
    manifest: manifestJson([
      { id: "pi-1", rollup: null, docs: [dreamDoc("docs/learned/evil.md")] },
      { id: "workflow-1", rollup: null, docs: [dreamDoc("docs/learned/ok.md")] },
    ]),
  });
  mkdirSync(join(cwd, "docs", "learned"), { recursive: true });
  writeFileSync(join(cwd, "outside.md"), "outside-tree content", "utf8");
  symlinkSync(join(cwd, "outside.md"), join(cwd, "docs", "learned", "evil.md"));
  const { text, error_type, spawns } = await refusalArm(cwd);
  assert.equal(error_type, "bad_input");
  assert.match(text, /lane 'pi-1'/);
  assert.match(text, /resolves outside docs\/learned\//);
  assert.equal(spawns.length, 0);
});

// ------------------------------------------------------------------- the execute core

test("executeDreamWave: an incomplete first wave skips write + reducers (entry removal still runs)", async () => {
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
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true, "post-launch outcomes are ok + complete: false");
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
  const text = result.content[0]?.text ?? "";
  assert.match(text, /untrusted DATA/);
  assert.match(text, /INCOMPLETE/);
  assert.match(text, /present the coverage honestly/);
  assert.match(text, /stop before drafting/);
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
    docs: Array.from({ length: DREAM_ANALYST_CAPS.laneDocs }, (_, j) =>
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
          rationale: "r".repeat(DREAM_ANALYST_CAPS.rationaleChars),
          preserve: Array.from({ length: DREAM_ANALYST_CAPS.preserveItems }, () =>
            "p".repeat(DREAM_ANALYST_CAPS.preserveItemChars),
          ),
          evidence_checked: Array.from({ length: DREAM_ANALYST_CAPS.evidenceItems }, () =>
            "e".repeat(DREAM_ANALYST_CAPS.evidenceItemChars),
          ),
        }),
      ),
      {
        uncertainties: Array.from({ length: DREAM_ANALYST_CAPS.uncertainties }, () =>
          "u".repeat(DREAM_ANALYST_CAPS.uncertaintyChars),
        ),
      },
    ),
  }));
  return { manifest, aggregate: { state: "complete", value } };
}

test("executeDreamWave: an over-budget bundle refuses with accounting — nothing written, no reducers", async () => {
  const { manifest, aggregate } = overBudgetFixture();
  const adapter = createMemoryWaveAdapter({ aggregate });
  const spies = bundleSpies();
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true);
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

test("executeDreamWave: a throwing entry-time removal is a typed io_error refusal — zero spawns", async () => {
  // The removal failure arm: never an uncaught throw, never a launch over an irremovable
  // stale bundle — the typed refusal carries the (empty) extras shape.
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter();
  const spies = bundleSpies();
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: () => {
      spies.events.push("remove-attempt");
      throw new Error("EACCES: permission denied");
    },
  });
  const details = result.details as {
    ok: boolean;
    error?: string;
    error_type?: string;
    analyses?: unknown[];
    attempts?: unknown[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "io_error");
  assert.match(details.error ?? "", /stale dream bundle removal failed/);
  assert.match(details.error ?? "", /EACCES/);
  assert.deepEqual(details.analyses, [], "nothing analyzed yet — the extras shape is empty");
  assert.deepEqual(details.attempts, [], "nothing launched yet — no attempt receipt");
  assert.equal(adapter.calls.spawn.length, 0, "nothing spawns on a failed entry removal");
  assert.deepEqual(spies.writes, [], "nothing written");
  // The invalidation record: the marker was cleared BEFORE the removal attempt, so the files
  // the failed cleanup left behind are refused by recovery (fail-closed).
  assert.deepEqual(spies.events, ["clear", "remove-attempt"], "clear precedes the removal");
});

test("executeDreamWave: an UNVERIFIED marker clear refuses io_error before ANY filesystem work or spawn", async () => {
  // The fail-closed hazard this refusal prevents: with the old digest possibly still live, a
  // subsequent removal failure would leave the prior bundle + prior digest PAIR intact and
  // recoverable as fresh. The refusal fires before the removal even runs, so no mutation (and
  // no such mixed state) can happen — asserted here with a remove spy that would also fail.
  const cwd = scaffoldRepo();
  const manifestPath = join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME);
  mkdirSync(dirname(manifestPath), { recursive: true });
  writeFileSync(manifestPath, manifestJson(), "utf8");
  // A REAL prior finalized state: the old bundle on disk whose digest the (unclearable) old
  // marker would still name.
  const priorManifest = decodedManifest(
    [{ id: "pi-1", rollup: null, docs: [dreamDoc("docs/learned/pi/subagents.md")] }],
    manifestPath,
  );
  const priorBundle = finalizeDreamBundle(
    priorManifest,
    [
      {
        lane: "pi-1",
        report: {
          docs: [
            {
              path: "docs/learned/pi/subagents.md",
              disposition: "keep",
              merge_target: null,
              rationale: "still true",
              preserve: [],
              evidence_checked: [],
              confidence: "high",
            },
          ],
          overlap_signals: [],
          harvest_followups: [],
          uncertainties: [],
          overlap_signals_omitted: 0,
          harvest_followups_omitted: 0,
          uncertainties_omitted: 0,
        },
      },
    ],
    [],
    digestSessionData(manifestJson()),
  );
  const priorBundlePath = join(dirname(manifestPath), DREAM_ANALYSES_FILENAME);
  writeFileSync(priorBundlePath, priorBundle, "utf8");

  const adapter = createMemoryWaveAdapter();
  const spies = bundleSpies({ clearFails: true });
  const result = await executeDreamWave(adapter, target(), {
    manifest: priorManifest,
    manifestDigest: digestSessionData(manifestJson()),
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: (path) => {
      spies.events.push("remove-attempt");
      throw new Error(`EACCES: permission denied '${path}'`);
    },
  });
  const details = result.details as {
    ok: boolean;
    error?: string;
    error_type?: string;
    analyses?: unknown[];
    attempts?: unknown[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "io_error");
  assert.match(details.error ?? "", /dream_bundle_digest invalidation could not be verified/);
  assert.match(details.error ?? "", /possibly-recoverable prior finalized state/);
  assert.deepEqual(details.analyses, [], "the extras shape is empty — nothing ran");
  assert.deepEqual(details.attempts, []);
  assert.equal(adapter.calls.spawn.length, 0, "nothing spawns");
  assert.deepEqual(spies.writes, [], "nothing written");
  assert.deepEqual(
    spies.events,
    ["clear"],
    "the refusal fires BEFORE the removal attempt — no filesystem mutation is possible, so a " +
      "failed clear can never combine with a failed removal into a stale recoverable pair",
  );
  assert.equal(
    readFileSync(priorBundlePath, "utf8"),
    priorBundle,
    "the prior finalized state is untouched (the wave refused before mutating anything)",
  );
});

test("executeDreamWave: a bundle-write throw is the io_error fail arm retaining analyses + attempts", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({ aggregate: completeAnalystAggregate() });
  const spies = bundleSpies({ writeThrows: "disk full" });
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as {
    ok: boolean;
    error?: string;
    error_type?: string;
    analyses?: unknown[];
    attempts?: { flow: string; requestedKeys: string[] }[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "io_error");
  assert.match(details.error ?? "", /dream bundle write failed: disk full/);
  assert.equal(details.analyses?.length, 2, "the analyst analyses ride the fail extras");
  assert.equal(details.attempts?.length, 1, "the analyst attempt receipt is retained");
  assert.equal(details.attempts?.[0]?.flow, "dream-analyst");
  assert.equal(adapter.calls.spawn.length, 1, "no reducer spawn after a failed write");
  assert.deepEqual(spies.removes, [BUNDLE_PATH], "entry removal ran — the target stays absent");
  assert.deepEqual(spies.events, ["clear", "remove"], "the marker stays cleared");
});

test("executeDreamWave: the happy path — analyst write, reducers read it, finalize rewrite + marker", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies();
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    analystModel: "faux/analyst",
    reducerModel: "faux/reducer",
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true);
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
  // proposal survives the reducer re-decode into the tool result — an empty or wrong proposal
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
  assert.doesNotMatch(result.content[0]?.text ?? "", /INCOMPLETE/);
});

test("executeDreamWave: a finalize-write throw is the second io_error arm — marker stays cleared", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies({ finalizeThrows: "disk full at finalize" });
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as {
    ok: boolean;
    error?: string;
    error_type?: string;
    analyses?: unknown[];
    attempts?: { flow: string }[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "io_error");
  assert.match(details.error ?? "", /dream bundle finalize write failed: disk full at finalize/);
  assert.equal(details.analyses?.length, 2, "the analyst analyses ride the fail extras");
  assert.deepEqual(
    details.attempts?.map((a) => a.flow),
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

test("executeDreamWave: a drifted bracket skips the finalize AND the marker set", async () => {
  const manifest = TWO_LANE_MANIFEST();
  const adapter = createMemoryWaveAdapter({
    aggregates: [completeAnalystAggregate(), completeReducerAggregate()],
  });
  const spies = bundleSpies({ drift: "HEAD moved from aaa to bbb" });
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true, "drift is a post-launch outcome — ok + complete: false");
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
  // The drift line ACCOMPANIES the generic incomplete instruction, never replaces it.
  const text = result.content[0]?.text ?? "";
  assert.match(text, /INCOMPLETE/);
  assert.match(text, /present the coverage honestly/);
  assert.match(text, /repository DRIFTED during the wave \(HEAD moved from aaa to bbb\)/);
  assert.match(text, /the dream snapshot is STALE/);
});

test("executeDreamWave: a reducer lane failure ⇒ complete: false with analyses retained", async () => {
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
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: spies.markers,
    bracket: spies.bracket,
    writeBundle: spies.writeBundle,
    removeBundle: spies.removeBundle,
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true);
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
  assert.match(result.content[0]?.text ?? "", /INCOMPLETE/);
  assert.doesNotMatch(result.content[0]?.text ?? "", /DRIFTED/, "no drift line off the drift arm");
});

test("executeDreamWave: a pre-existing stale bundle is removed before the wave (real fs default)", async () => {
  // The default removeBundle (rmSync force) against a REAL stale file: the incomplete arm
  // writes nothing, so the fixed name must be gone afterward (exists iff the CURRENT call
  // wrote it).
  const cwd = scaffoldRepo();
  const manifestPath = join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME);
  mkdirSync(dirname(manifestPath), { recursive: true });
  const stalePath = join(dirname(manifestPath), DREAM_ANALYSES_FILENAME);
  writeFileSync(stalePath, "{stale prior bundle}", "utf8");
  const manifest = decodedManifest(
    [{ id: "pi-1", rollup: null, docs: [dreamDoc("docs/learned/pi/subagents.md")] }],
    manifestPath,
  );
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: "pi-1.1", ok: false, error: "analyst crashed", report: null }],
    },
  });
  const result = await executeDreamWave(adapter, target(), {
    manifest,
    manifestDigest: MANIFEST_DIGEST,
    markers: { clear: () => true, set: () => {} },
    bracket: () => ({ ok: true, detail: null }),
  });
  const details = result.details as { ok: boolean } & DreamWaveOk;
  assert.equal(details.ok, true);
  assert.equal(details.complete, false);
  assert.equal(
    existsSync(stalePath),
    false,
    "the stale prior bundle can never contradict the returned aggregate",
  );
});

// ----------------------------------------------------------------- the fake-RPC e2e

/** Scaffold a claimed dream session over a REAL clean git repo whose HEAD stamps the planted
 * manifest — the registered-tool e2e exercises the production revalidation bracket end-to-end
 * (`dreamRepoCommit` after planting drifts it). `config` is committed as `.perk/config.toml`
 * before the snapshot commit so the tree stays clean through the wave. */
function scaffoldDreamGitRepo(opts: { config?: string } = {}): {
  cwd: string;
  sha: string;
  manifestPath: string;
} {
  const cwd = scaffoldRepo({
    handoff: { runId: RUN_ID, mode: "read-only", stage: "objective-author" },
  });
  if (opts.config !== undefined) {
    mkdirSync(join(cwd, ".perk"), { recursive: true });
    writeFileSync(join(cwd, ".perk", "config.toml"), opts.config, "utf8");
  }
  const sha = initDreamRepo(cwd);
  const manifestPath = join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME);
  mkdirSync(dirname(manifestPath), { recursive: true });
  writeFileSync(manifestPath, manifestJson(undefined, { commit_sha: sha }), "utf8");
  return { cwd, sha, manifestPath };
}

test("tool e2e: both configured models ride their wave's spawn; analyst completes before reducers", async () => {
  const { cwd } = scaffoldDreamGitRepo({
    config:
      '[models.subagents]\ndream-analyst = "faux/dream-analyst-model"\ndream-reducer = "faux/dream-reducer-model"\n',
  });
  const analystAggregate = [
    {
      key: "pi-1.1",
      ok: true,
      error: null,
      report: analystReportOf([docRow("docs/learned/pi/subagents.md")]),
    },
  ];
  const reducerAggregate = DREAM_REDUCER_ANGLES.map((angle) => ({
    key: angle,
    ok: true,
    error: null,
    report: reducerReportOf(angle),
  }));
  const spawns: Record<string, unknown>[] = [];
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakeSubagentsRpc([analystAggregate, reducerAggregate], spawns)],
  });
  try {
    const result = await h.invokeTool("run_dream_wave", {});
    const details = result.details as { ok: boolean } & DreamWaveOk;
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.deepEqual(
      details.analysis.analyses.map((a) => a.lane),
      ["pi-1"],
      "a single-lane manifest launches (no direct-analysis refusal) — an all-keep corpus " +
        "still gets its reducer pass",
    );
    assert.deepEqual(
      details.reducers.reports.map((r) => r.angle),
      [...DREAM_REDUCER_ANGLES],
    );
    // The "pin the glue" rule: each configured key reaches ITS wave's real spawn params, and
    // the analyst wave completed before any reducer spawn (the spawn order is the proof — the
    // door awaits the first wave and composes the bundle before the second spawn exists).
    assert.equal(spawns.length, 2);
    const analystSpawn = spawns[0] as { workflowScript?: string; model?: string };
    const reducerSpawn = spawns[1] as { workflowScript?: string; model?: string };
    assert.equal(analystSpawn.model, "faux/dream-analyst-model");
    assert.match(analystSpawn.workflowScript ?? "", /perk\.dream-analyst/);
    assert.equal(reducerSpawn.model, "faux/dream-reducer-model");
    assert.match(reducerSpawn.workflowScript ?? "", /perk\.dream-reducer/);
    // The written bundle is REAL on this path (the default atomicWriteFileSync): the reducer
    // task names it, and — both waves complete — it holds the FINALIZED shape (the analyst
    // reports plus the reducers section).
    const bundlePath = join(runScratchDir(cwd, RUN_ID), DREAM_ANALYSES_FILENAME);
    assert.ok(reducerSpawn.workflowScript?.includes(bundlePath));
    const finalizedBytes = readFileSync(bundlePath, "utf8");
    const bundle = JSON.parse(finalizedBytes) as {
      lanes: { lane: string }[];
      reducers: { angle: string }[];
    };
    assert.deepEqual(
      bundle.lanes.map((lane) => lane.lane),
      ["pi-1"],
    );
    assert.deepEqual(
      bundle.reducers.map((entry) => entry.angle),
      [...DREAM_REDUCER_ANGLES],
      "the on-disk bundle finalized in place",
    );
    // The production manifest binding: manifest_digest = the digest of the on-disk manifest
    // bytes the registered execute read and decoded.
    assert.equal(
      (bundle as unknown as { manifest_digest: string }).manifest_digest,
      digestSessionData(
        readFileSync(join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME), "utf8"),
      ),
    );
    // The production marker wiring: dream_bundle_digest holds the finalized bytes' digest.
    assert.equal(h.workflowState().dream_bundle_digest, digestSessionData(finalizedBytes));
    // The REAL default bracket ran and passed: the repo never moved and the run scratch is
    // gitignored, so the end state matches the stamped snapshot.
    assert.deepEqual(details.bracket, { ok: true, detail: null });
  } finally {
    h.dispose();
  }
});

test("tool e2e: repository drift during the wave is caught by the REAL default bracket", async () => {
  // HEAD moves off the stamped snapshot before the wave completes — the registered execute's
  // production bracket (revalidationBracket over ctx.cwd + the manifest's commit_sha) reports
  // drift: complete: false, no finalize (the on-disk bundle stays analyses-only), marker
  // cleared — structurally undraftable.
  const { cwd } = scaffoldDreamGitRepo();
  dreamRepoCommit(cwd, "drift: a commit after the manifest was stamped");
  const analystAggregate = [
    {
      key: "pi-1.1",
      ok: true,
      error: null,
      report: analystReportOf([docRow("docs/learned/pi/subagents.md")]),
    },
  ];
  const reducerAggregate = DREAM_REDUCER_ANGLES.map((angle) => ({
    key: angle,
    ok: true,
    error: null,
    report: reducerReportOf(angle),
  }));
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakeSubagentsRpc([analystAggregate, reducerAggregate])],
  });
  try {
    const result = await h.invokeTool("run_dream_wave", {});
    const details = result.details as { ok: boolean } & DreamWaveOk;
    assert.equal(details.ok, true, "drift is a post-launch outcome — ok + complete: false");
    assert.equal(details.complete, false);
    assert.equal(
      details.analysis.complete,
      true,
      "both waves completed — only the bracket drifted",
    );
    assert.equal(details.reducers.complete, true);
    assert.equal(details.bracket?.ok, false);
    assert.match(details.bracket?.detail ?? "", /HEAD moved/);
    // The marker stays at the entry clear — recovery refuses.
    assert.equal(h.workflowState().dream_bundle_digest, "");
    // The on-disk bundle never finalized (no reducers key) — the analyses-only mid-wave shape.
    const bundle = JSON.parse(
      readFileSync(join(runScratchDir(cwd, RUN_ID), DREAM_ANALYSES_FILENAME), "utf8"),
    ) as Record<string, unknown>;
    assert.ok(!("reducers" in bundle), "the finalize write was skipped");
    const text = result.content[0]?.text ?? "";
    assert.match(text, /INCOMPLETE/);
    assert.match(text, /DRIFTED/);
  } finally {
    h.dispose();
  }
});

test("tool e2e: no RPC responder soft-fails loudly as unavailable (never a throw)", async () => {
  const { cwd } = scaffoldDreamRepo();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID, PERK_WAVE_RPC_PING_MS: "20" },
  });
  try {
    const result = await h.invokeTool("run_dream_wave", {});
    const details = result.details as {
      ok: boolean;
      complete?: boolean;
      analysis?: { failures: { reason: string }[] };
      reducers?: { launched: boolean; skip_reason: string | null };
    };
    // An unavailable analyst wave is an INCOMPLETE first wave — the ok + complete: false
    // posture, with the wave-level reason in the analysis failures.
    assert.equal(details.ok, true);
    assert.equal(details.complete, false);
    assert.equal(details.analysis?.failures[0]?.reason, "unavailable");
    assert.equal(details.reducers?.launched, false);
    assert.equal(details.reducers?.skip_reason, "incomplete-analysis");
  } finally {
    h.dispose();
  }
});
