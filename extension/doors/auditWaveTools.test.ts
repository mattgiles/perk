// The `run_audit_wave` tool's suite: registration pins (NO parameters — the structural write
// binding), the workflow-state `audit_bundle_dir` binding (refusal outside an audit-judge
// session; the bound path as the sole write target), the missing-artifact `bad_state` arms,
// the verdicts.json write matrix through the atomic seam (replace/no-residue pinned), the
// `io_error` write-failure arm with lanes attached, config-model threading, a fake-RPC e2e
// sinking spawn params, and the agent-def ↔ verdict-schema lockstep pin.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { workflowDir } from "../substrate/cache.ts";
import { createFakeSubagents, type FakeSubagents } from "../testing/fakeSubagents.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  AUDIT_VERDICT_SCHEMA,
  type AuditManifest,
  type AuditManifestPair,
} from "../waves/auditWave.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import { type AuditVerdictLane, executeAuditWave, registerAuditWave } from "./auditWaveTools.ts";

const GRILL = "plan.grill-before-review";
const RUN_ID = "01AUDITRUN";

function pair(basename: string, overrides: Partial<AuditManifestPair> = {}): AuditManifestPair {
  return {
    expectation_id: GRILL,
    session_basename: basename,
    session_path: `/sessions/enc-main/${basename}`,
    status: "packetized",
    packet_path: `packets/${GRILL}/${basename.replace(/\.jsonl$/, "")}.md`,
    detail: "",
    ...overrides,
  };
}

function manifestOf(pairs: AuditManifestPair[]): AuditManifest {
  return {
    results: [{ id: GRILL, evidence: "the evidence", violation: "the violation", pairs }],
  };
}

/** The wave's composed run-key-safe lane key: `<expectation id>.<1-based planned ordinal>`. */
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

/** The ReportTarget fake (mirrors learn.test.ts's executeLearnWave target). */
function target(): { hasUI: boolean; ui: { notify: (m: string) => void } } {
  return { hasUI: true, ui: { notify: () => {} } };
}

function readVerdicts(bundleDir: string): {
  bundle_dir: string;
  flow: string;
  lanes: AuditVerdictLane[];
} {
  return JSON.parse(readFileSync(join(bundleDir, "verdicts.json"), "utf8"));
}

// ------------------------------------------------------------------- registration pins

test("registerAuditWave: run_audit_wave takes NO parameters (the structural write binding)", () => {
  const tools = new Map<string, { parameters?: unknown; executionMode?: string }>();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
  } as unknown as ExtensionAPI;
  registerAuditWave(pi);
  const def = tools.get("run_audit_wave");
  assert.ok(def, "run_audit_wave must register");
  assert.deepEqual(def.parameters, {
    type: "object",
    additionalProperties: false,
    properties: {},
  });
  assert.equal(def.executionMode, "sequential");
});

// -------------------------------------------------- the workflow-state bundle binding

/** Scaffold a claimed audit-judge session repo: handoff carries `audit_bundle_dir` (the cold
 * door's `handoff_extra` binding) and the bundle dir holds the two judge-built artifacts. */
function scaffoldAuditRepo(opts: { bundle?: boolean; artifacts?: string[] } = {}): {
  cwd: string;
  bundleDir: string;
} {
  const cwd = scaffoldRepo({ handoff: { runId: RUN_ID, mode: "read-only", stage: "audit" } });
  const bundleDir = join(cwd, ".perk", "workflow", "scratch", "audit-evidence");
  if (opts.bundle !== false) {
    mkdirSync(bundleDir, { recursive: true });
    for (const artifact of opts.artifacts ?? ["manifest.json", "deterministic.json"]) {
      const content =
        artifact === "manifest.json"
          ? JSON.stringify({ success: true, results: manifestOf([pair("s1.jsonl")]).results })
          : JSON.stringify({ success: true });
      writeFileSync(join(bundleDir, artifact), content, "utf8");
    }
  }
  // Rebind the handoff with the audit_bundle_dir extra (scaffoldRepo writes the base keys).
  writeFileSync(
    join(workflowDir(cwd), "handoff", `${RUN_ID}.json`),
    `${JSON.stringify({
      run_id: RUN_ID,
      consumed: false,
      mode: "read-only",
      stage: "audit",
      audit_bundle_dir: bundleDir,
    })}\n`,
    "utf8",
  );
  return { cwd, bundleDir };
}

test("tool: refuses outside an audit-judge session (no audit_bundle_dir in the launch state)", async () => {
  // An ordinary claimed session: the handoff has no audit_bundle_dir, so the binding is
  // absent — and with no parameter, no path substitution is even representable.
  const cwd = scaffoldRepo({ handoff: { runId: RUN_ID, mode: "read-write", stage: "implement" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: RUN_ID } });
  try {
    const result = await h.invokeTool("run_audit_wave", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_state");
    assert.match(result.content[0]?.text ?? "", /runs only inside a perk-dev audit judge session/);
  } finally {
    h.dispose();
  }
});

test("tool: missing bundle artifacts are bad_state naming the artifact (nothing written)", async () => {
  const cases: string[][] = [["deterministic.json"], ["manifest.json"]];
  for (const artifacts of cases) {
    const { cwd, bundleDir } = scaffoldAuditRepo({ artifacts });
    const missing = artifacts.includes("manifest.json") ? "deterministic.json" : "manifest.json";
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: RUN_ID } });
    try {
      const result = await h.invokeTool("run_audit_wave", {});
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false);
      assert.equal(details.error_type, "bad_state");
      assert.match(result.content[0]?.text ?? "", new RegExp(`${missing}.*audit judge first`));
      assert.ok(!existsSync(join(bundleDir, "verdicts.json")), "pre-launch arms write nothing");
    } finally {
      h.dispose();
    }
  }
});

// ------------------------------------------------------------ the verdicts write matrix

test("executeAuditWave: the write matrix — report / lane-failed / malformed / echo-mismatch / out-of-vocab / collision", async () => {
  const twinA = pair("twin.jsonl", { session_path: "/sessions/enc-a/twin.jsonl" });
  const twinB = pair("twin.jsonl", { session_path: "/sessions/enc-b/twin.jsonl" });
  const manifest = manifestOf([
    pair("ok.jsonl"),
    pair("failed.jsonl"),
    pair("malformed.jsonl"),
    pair("mismatch.jsonl"),
    pair("vocab.jsonl"),
    pair("skipped.jsonl", { status: "unboundable", packet_path: null, detail: "over budget" }),
    twinA,
    twinB,
  ]);
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: laneKey(1), ok: true, error: null, report: report("ok.jsonl") },
        { key: laneKey(2), ok: false, error: "auditor crashed", report: null },
        { key: laneKey(3), report: [] }, // no boolean ok → malformed-report
        {
          key: laneKey(4),
          ok: true,
          error: null,
          report: report("mismatch.jsonl", { session_basename: "other.jsonl" }),
        },
        {
          key: laneKey(5),
          ok: true,
          error: null,
          report: report("vocab.jsonl", { verdict: "guilty" }),
        },
      ],
    },
  });
  const bundleDir = scaffoldRepo();
  const result = await executeAuditWave(adapter, target(), { bundleDir, manifest });
  const details = result.details as {
    ok: boolean;
    complete?: boolean;
    lanes?: AuditVerdictLane[];
    skipped_pairs?: { expectation_id: string; status: string; detail: string }[];
    verdicts_path?: string;
  };
  assert.equal(details.ok, true);
  assert.equal(details.complete, true, "best-effort: lane failures never fail the wave");
  assert.equal(details.verdicts_path, join(bundleDir, "verdicts.json"));

  const written = readVerdicts(bundleDir);
  assert.equal(written.bundle_dir, bundleDir);
  assert.equal(written.flow, "audit");
  assert.deepEqual(written.lanes, details.lanes, "the tool result relays the written records");
  const byBasename = new Map(written.lanes.map((l) => [l.session_basename, l]));

  const okLane = written.lanes.find((l) => l.session_basename === "ok.jsonl");
  assert.deepEqual(okLane, {
    expectation_id: GRILL,
    session_basename: "ok.jsonl",
    session_path: "/sessions/enc-main/ok.jsonl",
    status: "report",
    verdict: "satisfied",
    confidence: "high",
    citations: [2, 4],
    rationale: "clean",
    detail: "",
  });

  const failed = byBasename.get("failed.jsonl");
  assert.equal(failed?.status, "lane-failed");
  assert.equal(failed?.verdict, null);
  assert.deepEqual(failed?.citations, []);
  assert.equal(failed?.detail, "auditor crashed");

  assert.equal(byBasename.get("malformed.jsonl")?.status, "malformed-report");

  const mismatch = byBasename.get("mismatch.jsonl");
  assert.equal(mismatch?.status, "lane-failed");
  assert.match(mismatch?.detail ?? "", /echoed identity mismatch/);
  assert.match(mismatch?.detail ?? "", /other\.jsonl/);

  // An out-of-vocabulary verdict is sanitized to malformed-report — the Python fold's
  // validate() rejects unknown vocabulary wholesale, so it must never reach verdicts.json.
  const vocab = byBasename.get("vocab.jsonl");
  assert.equal(vocab?.status, "malformed-report");
  assert.equal(vocab?.verdict, null);

  // The collision degrades ride verdicts.json as lane-failed; session_path stays code-owned.
  const twins = written.lanes.filter((l) => l.session_basename === "twin.jsonl");
  assert.equal(twins.length, 2);
  for (const twin of twins) {
    assert.equal(twin.status, "lane-failed");
    assert.equal(twin.detail, "duplicate session basename in bundle — ambiguous packet identity");
  }
  assert.deepEqual(twins.map((t) => t.session_path).sort(), [
    "/sessions/enc-a/twin.jsonl",
    "/sessions/enc-b/twin.jsonl",
  ]);

  // The non-packetized pair is NOT a lane — it comes back in skipped_pairs with its detail.
  assert.equal(
    written.lanes.some((l) => l.session_basename === "skipped.jsonl"),
    false,
  );
  assert.deepEqual(details.skipped_pairs, [
    {
      expectation_id: GRILL,
      session_basename: "skipped.jsonl",
      status: "unboundable",
      detail: "over budget",
    },
  ]);
});

test("executeAuditWave: zero-lane arm still writes verdicts.json (lanes []) + skipped_pairs", async () => {
  const manifest = manifestOf([
    pair("skipped.jsonl", { status: "not-sampled", packet_path: null, detail: "cap reached" }),
  ]);
  const adapter = createMemoryWaveAdapter({});
  const bundleDir = scaffoldRepo();
  const result = await executeAuditWave(adapter, target(), { bundleDir, manifest });
  const details = result.details as {
    ok: boolean;
    complete?: boolean;
    skipped_pairs?: unknown[];
  };
  assert.equal(details.ok, true);
  assert.equal(details.complete, true);
  assert.equal(adapter.calls.spawn.length, 0, "zero lanes ⇒ the wave is never launched");
  const written = readVerdicts(bundleDir);
  assert.deepEqual(written.lanes, []);
  assert.equal((details.skipped_pairs ?? []).length, 1);
});

test("executeAuditWave: a wave-level failure writes ALL planned lanes lane-failed (complete: false)", async () => {
  const manifest = manifestOf([pair("s1.jsonl"), pair("s2.jsonl")]);
  const adapter = createMemoryWaveAdapter({ ping: null }); // unavailable — nothing launched
  const bundleDir = scaffoldRepo();
  const result = await executeAuditWave(adapter, target(), { bundleDir, manifest });
  const details = result.details as { ok: boolean; complete?: boolean };
  assert.equal(details.ok, true, "verdicts exist, so the orchestrator gets an ok result");
  assert.equal(details.complete, false);
  const written = readVerdicts(bundleDir);
  assert.equal(written.lanes.length, 2);
  for (const lane of written.lanes) {
    assert.equal(lane.status, "lane-failed");
    assert.match(lane.detail, /report-wave capabilities/);
  }
  assert.match(result.content[0]?.text ?? "", /Wave-level failure \(unavailable\)/);
});

test("executeAuditWave: the atomic seam replaces a stale verdicts.json and leaves no residue", async () => {
  const manifest = manifestOf([pair("s1.jsonl")]);
  const bundleDir = scaffoldRepo();
  writeFileSync(join(bundleDir, "verdicts.json"), '{"stale": true}', "utf8");
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: laneKey(1), ok: true, error: null, report: report("s1.jsonl") }],
    },
  });
  const result = await executeAuditWave(adapter, target(), { bundleDir, manifest });
  assert.equal((result.details as { ok: boolean }).ok, true);
  const written = readVerdicts(bundleDir);
  assert.equal(written.lanes[0]?.status, "report");
  assert.ok(!("stale" in written), "the stale file is REPLACED, never merged");
  const residue = readdirSync(bundleDir).filter((name) => name.endsWith(".tmp"));
  assert.deepEqual(residue, [], "the atomic seam leaves no temp residue");
});

test("executeAuditWave: a throwing write is the io_error arm with the lanes attached", async () => {
  const manifest = manifestOf([pair("s1.jsonl")]);
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [{ key: laneKey(1), ok: true, error: null, report: report("s1.jsonl") }],
    },
  });
  const result = await executeAuditWave(adapter, target(), {
    bundleDir: "/abs/bundle",
    manifest,
    writeVerdicts: () => {
      throw new Error("disk full");
    },
  });
  const details = result.details as {
    ok: boolean;
    error?: string;
    error_type?: string;
    lanes?: AuditVerdictLane[];
  };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "io_error");
  assert.match(details.error ?? "", /disk full/);
  // The in-memory lane records ride the fail payload so the orchestrator can still present
  // the leads (the failFor typed-extra pattern).
  assert.equal(details.lanes?.length, 1);
  assert.equal(details.lanes?.[0]?.status, "report");
});

// ----------------------------------------------------------------- the fake-RPC e2e

/** The shared fake pi-subagents responder over one staged complete aggregate. */
function fakeSubagentsRpc(aggregate: unknown[]): FakeSubagents {
  return createFakeSubagents([{ value: aggregate }]);
}

test("tool e2e: the bound bundle dir is the write target; spawn params sink the auditor contract", async () => {
  const { cwd, bundleDir } = scaffoldAuditRepo();
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nsession-auditor = "faux/auditor-model"\n',
    "utf8",
  );
  const aggregate = [{ key: laneKey(1), ok: true, error: null, report: report("s1.jsonl") }];
  const fake = fakeSubagentsRpc(aggregate);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fake.extension],
  });
  try {
    const result = await h.invokeTool("run_audit_wave", {});
    const details = result.details as {
      ok: boolean;
      complete?: boolean;
      lanes?: AuditVerdictLane[];
      verdicts_path?: string;
      bundle_dir?: string;
    };
    assert.equal(details.ok, true);
    assert.equal(details.complete, true);
    assert.equal(details.bundle_dir, bundleDir, "the write target IS the launch-bound dir");
    assert.equal(details.verdicts_path, join(bundleDir, "verdicts.json"));
    assert.equal(readVerdicts(bundleDir).lanes[0]?.status, "report");

    // Spawn contract: the auditor agent + the configured model + the packet-path task.
    assert.equal(fake.spawns.length, 1);
    const spawn = fake.spawns[0] as { workflowScript?: string; model?: string };
    assert.equal(spawn.model, "faux/auditor-model");
    assert.match(spawn.workflowScript ?? "", /perk-dev\.session-auditor/);
    assert.match(
      spawn.workflowScript ?? "",
      new RegExp(`packets/${GRILL.replace(".", "\\.")}/s1\\.md`),
    );
    assert.match(result.content[0]?.text ?? "", /untrusted DATA/);
  } finally {
    h.dispose();
  }
});

// ------------------------------------------------------- the agent-def lockstep pin

test("the session-auditor def completes via structured_output with the schema's fields — no fenced-JSON completion", () => {
  // The wave fails any lane without a schema-valid structured_output call, so the repo-local
  // def and AUDIT_VERDICT_SCHEMA must agree (the adversarialReviewWave.test.ts pattern).
  const defPath = join(
    import.meta.dirname,
    "..",
    "..",
    ".pi",
    "agents",
    "perk-dev",
    "session-auditor.md",
  );
  const def = readFileSync(defPath, "utf8");
  // Frontmatter: the runtime name perk-dev.session-auditor + the read-only tool surface.
  assert.match(def, /^name: session-auditor$/m);
  assert.match(def, /^package: perk-dev$/m);
  assert.match(def, /^model: openai\/gpt-5\.6-luna$/m);
  assert.match(def, /^ {2}- openai\/gpt-5\.6-terra$/m);
  assert.match(def, /^tools: read, grep, find, ls, bash$/m);
  assert.match(def, /^systemPromptMode: replace$/m);
  assert.match(def, /^inheritProjectContext: false$/m);
  assert.match(def, /^inheritSkills: false$/m);
  // The completion contract.
  assert.match(
    def,
    /calling the\s+engine-injected \*\*`structured_output`\*\* tool exactly once/,
    "the completion step must instruct ONE structured_output call",
  );
  const schema = AUDIT_VERDICT_SCHEMA as { required: string[] };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  assert.match(
    def,
    /Do NOT emit a fenced-JSON completion block — the\s+`structured_output` call IS the report\./,
  );
  assert.doesNotMatch(def, /```json/, "no fenced-JSON completion form anywhere in the def");
  // The judgment framing the fold relies on.
  assert.match(def, /lead, not a proof/);
  assert.match(def, /\*\*REQUIRES citations\*\*/);
  assert.match(def, /earned, not defaulted/);
});
