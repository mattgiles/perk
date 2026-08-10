// The `run_harvest_wave` tool's suite: registration pins (the ONE `manifest_path` param — a
// relay handshake, never an authority), the census pins (PERK_TOOLS + READ_ONLY_TOOLS, and
// deliberately NO stage list — cold-only, gate-on), the ordered pre-spawn refusal ladder
// (params → binding → strict decode → single-lane → resolved containment; nothing spawns on
// any arm), the execute core's stamp/degrade mapping over the memory adapter, and the fake-RPC
// e2e sinking spawn params (config-model threading; the no-responder unavailable arm).

import assert from "node:assert/strict";
import { mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runScratchDir } from "../substrate/cache.ts";
import { PERK_TOOLS, READ_ONLY_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { HARVEST_MANIFEST_FILENAME, type HarvestManifest } from "../waves/harvestWave.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import { WAVE_RPC_REPLY_EVENT_PREFIX, WAVE_RPC_REQUEST_EVENT } from "../waves/rpcAdapter.ts";
import {
  executeHarvestWave,
  type HarvestLaneReport,
  registerHarvestWave,
} from "./harvestWaveTools.ts";

const RUN_ID = "01HARVESTRUN";

function manifestJson(lanes?: { id: string; docs: unknown[] }[]): string {
  const value = {
    schema_version: "1",
    commit_sha: "abc123",
    lanes: lanes ?? [
      {
        id: "pi-1",
        docs: [{ path: "docs/learned/pi/subagents.md", title: "Subagents", read_when: "spawning" }],
      },
      {
        id: "workflow-1",
        docs: [{ path: "docs/learned/workflow/report-waves.md", title: null, read_when: null }],
      },
    ],
  };
  return `${JSON.stringify(value, null, 2)}\n`;
}

const TWO_LANE_MANIFEST: HarvestManifest = JSON.parse(manifestJson());

/** Scaffold a claimed learn-harvest session repo with the manifest planted at the run-scoped
 * scratch path (the door's binding). Returns the cwd + the bound manifest path. */
function scaffoldHarvestRepo(opts: { manifest?: string | false } = {}): {
  cwd: string;
  manifestPath: string;
} {
  const cwd = scaffoldRepo({
    handoff: { runId: RUN_ID, mode: "read-only", stage: "objective-author" },
  });
  const manifestPath = join(runScratchDir(cwd, RUN_ID), HARVEST_MANIFEST_FILENAME);
  if (opts.manifest !== false) {
    mkdirSync(dirname(manifestPath), { recursive: true });
    writeFileSync(manifestPath, opts.manifest ?? manifestJson(), "utf8");
  }
  return { cwd, manifestPath };
}

function opportunity(pointer: string, overrides: Record<string, unknown> = {}): unknown {
  return {
    title: "An opportunity",
    kind: "bug-risk",
    pointer,
    evidence: "the doc + the code",
    confidence: "high",
    ...overrides,
  };
}

/** The ReportTarget fake (mirrors learn.test.ts's executeLearnWave target). */
function target(): { hasUI: boolean; ui: { notify: (m: string) => void } } {
  return { hasUI: true, ui: { notify: () => {} } };
}

// ------------------------------------------------------------------- registration pins

test("registerHarvestWave: manifest_path is the ONLY parameter (the relay handshake)", () => {
  const tools = new Map<
    string,
    { parameters?: unknown; executionMode?: string; promptSnippet?: string }
  >();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
  } as unknown as ExtensionAPI;
  registerHarvestWave(pi);
  const def = tools.get("run_harvest_wave");
  assert.ok(def, "run_harvest_wave must register");
  const parameters = def.parameters as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, unknown>;
  };
  assert.equal(parameters.additionalProperties, false);
  assert.deepEqual(parameters.required, ["manifest_path"]);
  assert.deepEqual(Object.keys(parameters.properties), ["manifest_path"]);
  assert.equal(def.executionMode, "sequential", "sequential is load-bearing");
  assert.ok(
    typeof def.promptSnippet === "string" && def.promptSnippet !== "",
    "the model-facing contract is description + guidelines + snippet",
  );
});

// ------------------------------------------------------------------------- census pins

test("census: run_harvest_wave rides PERK_TOOLS + READ_ONLY_TOOLS and NO stage list", () => {
  assert.ok(PERK_TOOLS.includes("run_harvest_wave"));
  // The read-only carve-in: the seeded learn-harvest session runs GATED, and the manifest read
  // is structurally bound to the claimed run-scoped scratch path (any other path refused), so
  // the tool is safe in every gated session (the run_audit_wave posture, read-side).
  assert.ok(READ_ONLY_TOOLS.includes("run_harvest_wave"));
  // The deliberate non-behavior pin: harvest is cold-only and gate-on — the gate-ON set ignores
  // stage lists, so NO stage list carries the tool (we do NOT touch drive coverage).
  for (const [stage, tools] of Object.entries(STAGE_TOOLS)) {
    assert.ok(
      !tools.includes("run_harvest_wave"),
      `stage '${stage}' must not carry run_harvest_wave`,
    );
  }
});

// ----------------------------------------------------------- the pre-spawn refusal ladder

/** The fake pi-subagents RPC responder (the doors/learn.test.ts pattern). */
function fakeSubagentsRpc(
  aggregate: unknown[],
  spawns: Record<string, unknown>[] = [],
): (pi: ExtensionAPI) => void {
  return (pi) => {
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
        const asyncDir = scaffoldRepo();
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({ state: "complete", workflow: { value: aggregate } }),
        );
        reply({ success: true, data: { text: "ok", details: { asyncId: "wave-1", asyncDir } } });
        pi.events.emit("subagent:async-complete", { id: "wave-1", asyncDir });
      }
    });
  };
}

async function refusalArm(
  cwd: string,
  params: unknown,
  opts: { env?: Record<string, string | undefined> } = {},
): Promise<{ text: string; error_type?: string; spawns: Record<string, unknown>[] }> {
  const spawns: Record<string, unknown>[] = [];
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID, ...(opts.env ?? {}) },
    extraExtensions: [fakeSubagentsRpc([], spawns)],
  });
  try {
    const result = await h.invokeTool("run_harvest_wave", params);
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

test("tool: absent/mistyped/empty/relative manifest_path are bad_input (nothing spawns)", async () => {
  const { cwd } = scaffoldHarvestRepo();
  const cases: { params: unknown; detail: RegExp }[] = [
    { params: {}, detail: /must be a non-empty string/ },
    { params: { manifest_path: 7 }, detail: /must be a non-empty string/ },
    { params: { manifest_path: "" }, detail: /must be a non-empty string/ },
    {
      params: { manifest_path: "relative/harvest-manifest.json" },
      detail: /must be the absolute path the seed rendered/,
    },
  ];
  for (const arm of cases) {
    const { text, error_type, spawns } = await refusalArm(cwd, arm.params);
    assert.equal(error_type, "bad_input");
    assert.match(text, arm.detail);
    assert.equal(spawns.length, 0, "nothing spawns on a pre-spawn refusal");
  }
});

test("tool: a non-harvest session is structurally refused (bad_state)", async () => {
  // A warm session with no handoff MINTS its own run_id (index.ts's `none` arm), so the
  // structural refusal for a gated non-harvest session is the derived run-scoped path holding
  // no manifest — the binding leaves nothing for a caller-supplied path to aim at. (The
  // no-run_id `bad_state` arm stays defensive-only in code — unreachable through a live
  // session.)
  const cwd = scaffoldRepo(); // no handoff — an ordinary minted-run session
  const { text, error_type, spawns } = await refusalArm(
    cwd,
    { manifest_path: join(cwd, "harvest-manifest.json") },
    { env: { PERK_RUN_ID: undefined } },
  );
  assert.equal(error_type, "bad_state");
  assert.match(text, /no harvest manifest for this run/);
  assert.equal(spawns.length, 0);
});

test("tool: a claimed run with no run-scoped manifest is bad_state", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo({ manifest: false });
  const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: manifestPath });
  assert.equal(error_type, "bad_state");
  assert.match(text, /no harvest manifest for this run/);
  assert.equal(spawns.length, 0);
});

test("tool: a valid manifest at a DIFFERENT path is refused — the accepts-ONLY-that-path binding", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo();
  // A byte-valid manifest elsewhere: the binding refuses it BEFORE any read of its content.
  const otherPath = join(cwd, "elsewhere-manifest.json");
  writeFileSync(otherPath, manifestJson(), "utf8");
  const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: otherPath });
  assert.equal(error_type, "bad_input");
  assert.match(text, /is not this session's run-scoped manifest/);
  assert.ok(text.includes(manifestPath), "the refusal names the ONE acceptable path");
  assert.equal(spawns.length, 0);
});

test("tool: a nonexistent param path is bad_input (the wrapped realpath arm)", async () => {
  const { cwd } = scaffoldHarvestRepo();
  const { text, error_type, spawns } = await refusalArm(cwd, {
    manifest_path: join(cwd, "no-such-manifest.json"),
  });
  assert.equal(error_type, "bad_input");
  assert.match(text, /did not resolve/);
  assert.equal(spawns.length, 0);
});

test("tool: unparseable JSON at the bound path is bad_input naming the parse detail", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo({ manifest: "{not json" });
  const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: manifestPath });
  assert.equal(error_type, "bad_input");
  assert.match(text, /harvest manifest unreadable/);
  assert.equal(spawns.length, 0);
});

test("tool: manifest-validation failures surface the validator's named detail", async () => {
  const cases: { manifest: string; detail: RegExp }[] = [
    {
      manifest: JSON.stringify({ schema_version: "2", commit_sha: "x", lanes: [] }),
      detail: /schema_version must be the string "1"/,
    },
    {
      manifest: JSON.stringify({ schema_version: "1", commit_sha: "x", lanes: [] }),
      detail: /lanes must be a non-empty array/,
    },
    {
      manifest: manifestJson([
        { id: "a-1", docs: [{ path: "../secrets", title: null, read_when: null }] },
        { id: "a-2", docs: [{ path: "docs/learned/b.md", title: null, read_when: null }] },
      ]),
      detail: /doc path '\.\.\/secrets' escapes the checkout/,
    },
  ];
  for (const arm of cases) {
    const { cwd, manifestPath } = scaffoldHarvestRepo({ manifest: arm.manifest });
    const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: manifestPath });
    assert.equal(error_type, "bad_input");
    assert.match(text, arm.detail);
    assert.equal(spawns.length, 0);
  }
});

test("tool: a single-lane manifest is refused toward the seed's direct path", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo({
    manifest: manifestJson([
      { id: "pi-1", docs: [{ path: "docs/learned/pi/a.md", title: null, read_when: null }] },
    ]),
  });
  const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: manifestPath });
  assert.equal(error_type, "bad_input");
  assert.match(text, /analyze it directly in-session per the seed/);
  assert.equal(spawns.length, 0);
});

test("tool: an escaping-symlink doc refuses the wave (the resolved containment arm)", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo({
    manifest: manifestJson([
      { id: "pi-1", docs: [{ path: "docs/learned/evil.md", title: null, read_when: null }] },
      { id: "workflow-1", docs: [{ path: "docs/learned/ok.md", title: null, read_when: null }] },
    ]),
  });
  // A REAL symlink under docs/learned/ pointing outside the corpus.
  mkdirSync(join(cwd, "docs", "learned"), { recursive: true });
  writeFileSync(join(cwd, "outside.md"), "outside-tree content", "utf8");
  symlinkSync(join(cwd, "outside.md"), join(cwd, "docs", "learned", "evil.md"));
  const { text, error_type, spawns } = await refusalArm(cwd, { manifest_path: manifestPath });
  assert.equal(error_type, "bad_input");
  assert.match(text, /lane 'pi-1'/);
  assert.match(text, /resolves outside docs\/learned\//);
  assert.equal(spawns.length, 0);
});

// ------------------------------------------------------------------- the execute core

test("executeHarvestWave: the ok-arm mapping — stamped reports, skipped lanes, the attempt receipt", async () => {
  const goodReport = {
    opportunities: [opportunity("src/x.py"), opportunity("src/gone.py::f", { kind: "elegance" })],
    omitted_count: 1,
  };
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: "pi-1", ok: true, error: null, report: goodReport },
        { key: "workflow-1", ok: false, error: "analyst crashed", report: null },
      ],
    },
  });
  const exists = (p: string) => p === join("/checkout", "src/x.py");
  const result = await executeHarvestWave(adapter, target(), {
    manifest: TWO_LANE_MANIFEST,
    manifestPath: "/abs/harvest-manifest.json",
    checkoutRoot: "/checkout",
    exists,
  });
  const details = result.details as {
    ok: boolean;
    reports?: HarvestLaneReport[];
    skipped?: { lane: string; reason: string; detail: string }[];
    attempts?: { flow: string; attempt: number; requestedKeys: string[]; state: string }[];
  };
  assert.equal(details.ok, true);
  assert.notEqual(result.terminate, true, "non-terminating: the parent continues to curate");
  assert.equal(details.reports?.length, 1);
  const laneReport = details.reports?.[0];
  assert.equal(laneReport?.lane, "pi-1");
  assert.equal(laneReport?.omitted_count, 1);
  // Every stamped opportunity carries the code-owned pointer_status.
  assert.deepEqual(
    laneReport?.opportunities.map((o) => o.pointer_status),
    ["resolved", "unresolved"],
  );
  assert.deepEqual(details.skipped, [
    { lane: "workflow-1", reason: "lane-failed", detail: "analyst crashed" },
  ]);
  assert.equal(details.attempts?.length, 1);
  const attempt = details.attempts?.[0];
  assert.equal(attempt?.flow, "harvest");
  assert.equal(attempt?.attempt, 1);
  assert.deepEqual(attempt?.requestedKeys, ["pi-1", "workflow-1"]);
  assert.equal(attempt?.state, "complete");
  const text = result.content[0]?.text ?? "";
  assert.match(text, /untrusted DATA/);
  assert.match(text, /Lane `pi-1`/);
  assert.match(text, /pointer_status/);
  assert.match(text, /Skipped lanes:/);
  assert.match(text, /workflow-1 \(lane-failed\): analyst crashed/);
});

test("executeHarvestWave: malformed reports degrade the LANE, never the wave", async () => {
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        {
          key: "pi-1",
          ok: true,
          error: null,
          // Out-of-vocabulary kind — the defensive re-decode refuses it.
          report: {
            opportunities: [opportunity("src/x.py", { kind: "feature" })],
            omitted_count: 0,
          },
        },
        {
          key: "workflow-1",
          ok: true,
          error: null,
          // Six otherwise-valid opportunities — the over-cap arm.
          report: {
            opportunities: Array.from({ length: 6 }, () => opportunity("src/x.py")),
            omitted_count: 0,
          },
        },
      ],
    },
  });
  const result = await executeHarvestWave(adapter, target(), {
    manifest: TWO_LANE_MANIFEST,
    manifestPath: "/abs/harvest-manifest.json",
    checkoutRoot: "/checkout",
    exists: () => true,
  });
  const details = result.details as {
    ok: boolean;
    reports?: HarvestLaneReport[];
    skipped?: { lane: string; reason: string; detail: string }[];
  };
  assert.equal(details.ok, true);
  assert.deepEqual(details.reports, [], "neither lane's report survives the re-decode");
  assert.equal(details.skipped?.length, 2);
  assert.deepEqual(
    details.skipped?.map((s) => [s.lane, s.reason]),
    [
      ["pi-1", "malformed-report"],
      ["workflow-1", "malformed-report"],
    ],
  );
  assert.match(details.skipped?.[1]?.detail ?? "", /more than 5 opportunities/);
  assert.match(
    result.content[0]?.text ?? "",
    /No lane produced a report — analyze the manifest lanes yourself\./,
  );
});

test("executeHarvestWave: a wave-level failure soft-fails with its reason and keeps the attempts", async () => {
  const adapter = createMemoryWaveAdapter({ ping: null });
  const result = await executeHarvestWave(adapter, target(), {
    manifest: TWO_LANE_MANIFEST,
    manifestPath: "/abs/harvest-manifest.json",
    checkoutRoot: "/checkout",
  });
  const details = result.details as {
    ok: boolean;
    error_type?: string;
    attempts?: { flow: string; state: string; requestedKeys: string[] }[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "unavailable");
  assert.deepEqual(details.attempts, [
    {
      flow: "harvest",
      attempt: 1,
      requestedKeys: ["pi-1", "workflow-1"],
      state: "unavailable",
      children: [],
    },
  ]);
  assert.match(result.content[0]?.text ?? "", /run_harvest_wave failed:/);
});

// ----------------------------------------------------------------- the fake-RPC e2e

test("tool e2e: typed reports flow through, and the configured model rides the spawn", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo();
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nharvest-analyst = "faux/harvester-model"\n',
    "utf8",
  );
  // A checkout file the stamp can resolve.
  mkdirSync(join(cwd, "src"), { recursive: true });
  writeFileSync(join(cwd, "src", "x.py"), "print()\n", "utf8");
  const aggregate = [
    {
      key: "pi-1",
      ok: true,
      error: null,
      report: { opportunities: [opportunity("src/x.py")], omitted_count: 0 },
    },
    { key: "workflow-1", ok: false, error: "analyst crashed", report: null },
  ];
  const spawns: Record<string, unknown>[] = [];
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakeSubagentsRpc(aggregate, spawns)],
  });
  try {
    const result = await h.invokeTool("run_harvest_wave", { manifest_path: manifestPath });
    const details = result.details as {
      ok: boolean;
      reports?: HarvestLaneReport[];
      skipped?: { lane: string; reason: string }[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.reports?.length, 1);
    assert.equal(details.reports?.[0]?.lane, "pi-1");
    assert.equal(details.reports?.[0]?.opportunities[0]?.pointer_status, "resolved");
    assert.deepEqual(
      details.skipped?.map((s) => [s.lane, s.reason]),
      [["workflow-1", "lane-failed"]],
    );
    // The "pin the glue" rule: the configured model reaches the real spawn params.
    assert.equal(spawns.length, 1);
    const spawn = spawns[0] as { workflowScript?: string; model?: string };
    assert.equal(spawn.model, "faux/harvester-model");
    assert.match(spawn.workflowScript ?? "", /perk\.harvest-analyst/);
    assert.ok(spawn.workflowScript?.includes(manifestPath), "the task carries the BOUND path");
  } finally {
    h.dispose();
  }
});

test("tool e2e: no RPC responder soft-fails loudly as unavailable (never a throw)", async () => {
  const { cwd, manifestPath } = scaffoldHarvestRepo();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID, PERK_WAVE_RPC_PING_MS: "20" },
  });
  try {
    const result = await h.invokeTool("run_harvest_wave", { manifest_path: manifestPath });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "unavailable");
    assert.match(result.content[0]?.text ?? "", /run_harvest_wave failed:/);
    assert.match(result.content[0]?.text ?? "", /report-wave capabilities/);
  } finally {
    h.dispose();
  }
});
