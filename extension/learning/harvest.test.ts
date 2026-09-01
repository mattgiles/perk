// The harvest feature op's suite: schema pins, the STRICT manifest decode's refusal arms, the
// shared resolved doc-containment layer (injected fs), and the `analyzeHarvest` entry op over
// the memory adapter — lane/task composition via the recorded spawn, the deterministic pointer
// post-pass (injected exists), the malformed-report lane degrades, and the wave-level failure
// arm. Lane planning and the pointer stamp are module-private, so those matrices are exercised
// through the one entry op. The agent-def ↔ report-schema prose lockstep pin (+ the delivered
// `.pi/agents/perk/` mirror) rides along. Fully offline.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, sep } from "node:path";
import { test } from "node:test";
import { waveScriptItems } from "../testing/fakeSubagents.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import { verifyDocContainment } from "./containment.ts";
import {
  analyzeHarvest,
  decodeHarvestManifest,
  HARVEST_ANALYST_REPORT_SCHEMA,
  HARVEST_KINDS,
  HARVEST_MANIFEST_FILENAME,
  HARVEST_MAX_OPPORTUNITIES,
  type HarvestAnalysisOutcome,
  type HarvestManifest,
} from "./harvest.ts";

function doc(
  path: string,
  overrides: Partial<{ title: string | null; read_when: string | null }> = {},
) {
  return { path, title: "A title", read_when: "a cue", ...overrides };
}

function manifestOf(lanes: { id: string; docs: unknown[] }[]): Record<string, unknown> {
  return { schema_version: "1", commit_sha: "abc123", lanes };
}

const TWO_LANE_RAW = manifestOf([
  { id: "pi-1", docs: [doc("docs/learned/pi/subagents.md", { title: null, read_when: null })] },
  { id: "workflow-1", docs: [doc("docs/learned/workflow/report-waves.md")] },
]);

function decoded(raw: unknown): HarvestManifest {
  const result = decodeHarvestManifest(raw);
  assert.equal(result.ok, true, `expected a valid manifest: ${JSON.stringify(result)}`);
  return (result as { ok: true; manifest: HarvestManifest }).manifest;
}

const MANIFEST_PATH = "/abs/scratch/runs/RUN/harvest-manifest.json";

/** Run `analyzeHarvest` and narrow to the `analyzed` arm (the matrices' common path). */
async function analyzed(
  adapter: Parameters<typeof analyzeHarvest>[0],
  opts: Omit<Parameters<typeof analyzeHarvest>[1], "manifestPath" | "checkoutRoot"> &
    Partial<Pick<Parameters<typeof analyzeHarvest>[1], "manifestPath" | "checkoutRoot">>,
): Promise<Extract<HarvestAnalysisOutcome, { kind: "analyzed" }>> {
  const outcome = await analyzeHarvest(adapter, {
    manifestPath: MANIFEST_PATH,
    checkoutRoot: "/checkout",
    ...opts,
  });
  assert.equal(outcome.kind, "analyzed", JSON.stringify(outcome));
  return outcome as Extract<HarvestAnalysisOutcome, { kind: "analyzed" }>;
}

// ---------------------------------------------------------------------------- schema pins

test("HARVEST_ANALYST_REPORT_SCHEMA: closed shape, required fields, enums, the 5-cap", () => {
  const schema = HARVEST_ANALYST_REPORT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: {
      opportunities: {
        maxItems: number;
        items: {
          additionalProperties: boolean;
          required: string[];
          properties: {
            kind: { enum: string[] };
            confidence: { enum: string[] };
          };
        };
      };
      omitted_count: { minimum: number };
    };
  };
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.required, ["opportunities", "omitted_count"]);
  // The cap is ONE named constant — the schema's maxItems and the sanitizer's over-cap arm
  // must never diverge (both derive from it).
  assert.equal(schema.properties.opportunities.maxItems, HARVEST_MAX_OPPORTUNITIES);
  assert.equal(HARVEST_MAX_OPPORTUNITIES, 5, "the node-pinned tunable");
  const items = schema.properties.opportunities.items;
  assert.equal(items.additionalProperties, false);
  assert.deepEqual(items.required, ["title", "kind", "pointer", "evidence", "confidence"]);
  assert.deepEqual(items.properties.kind.enum, [...HARVEST_KINDS]);
  assert.deepEqual(items.properties.confidence.enum, ["high", "medium", "low"]);
  assert.equal(schema.properties.omitted_count.minimum, 0);
});

test("HARVEST_MANIFEST_FILENAME mirrors harvest.py::MANIFEST_FILENAME", () => {
  assert.equal(HARVEST_MANIFEST_FILENAME, "harvest-manifest.json");
});

// ------------------------------------------------------------------- the strict decode

test("decodeHarvestManifest: a valid two-lane manifest round-trips (null cues carried)", () => {
  const manifest = decoded(TWO_LANE_RAW);
  assert.equal(manifest.schema_version, "1");
  assert.equal(manifest.commit_sha, "abc123");
  assert.equal(manifest.lanes.length, 2);
  assert.deepEqual(manifest.lanes[0], {
    id: "pi-1",
    docs: [{ path: "docs/learned/pi/subagents.md", title: null, read_when: null }],
  });
  assert.deepEqual(manifest.lanes[1]?.docs, [
    { path: "docs/learned/workflow/report-waves.md", title: "A title", read_when: "a cue" },
  ]);
});

test("decodeHarvestManifest: unknown extra keys are ignored (forward-compat rides schema_version)", () => {
  const raw = {
    ...manifestOf([
      { id: "pi-1", docs: [{ ...doc("docs/learned/pi/x.md"), extra: "ignored" }] },
      { id: "pi-2", docs: [doc("docs/learned/pi/y.md")], stray: true } as never,
    ]),
    trailer: 42,
  };
  const manifest = decoded(raw);
  assert.equal(manifest.lanes.length, 2);
  assert.ok(!("extra" in (manifest.lanes[0]?.docs[0] ?? {})), "extra doc keys never survive");
});

test("decodeHarvestManifest: each refusal arm carries its named detail", () => {
  const arms: { raw: unknown; detail: RegExp }[] = [
    { raw: "nope", detail: /not an object/ },
    {
      raw: { ...manifestOf([{ id: "a-1", docs: [doc("docs/learned/a.md")] }]), schema_version: 1 },
      detail: /schema_version must be the string "1" \(got 1\)/,
    },
    {
      raw: {
        ...manifestOf([{ id: "a-1", docs: [doc("docs/learned/a.md")] }]),
        schema_version: "2",
      },
      detail: /schema_version must be the string "1" \(got "2"\)/,
    },
    {
      raw: { schema_version: "1", lanes: [{ id: "a-1", docs: [doc("docs/learned/a.md")] }] },
      detail: /commit_sha must be a string/,
    },
    {
      raw: {
        ...manifestOf([{ id: "a-1", docs: [doc("docs/learned/a.md")] }]),
        commit_sha: 7,
      },
      detail: /commit_sha must be a string/,
    },
    { raw: { schema_version: "1", commit_sha: "x" }, detail: /lanes must be a non-empty array/ },
    { raw: manifestOf([]), detail: /lanes must be a non-empty array/ },
    {
      raw: manifestOf([{ docs: [doc("docs/learned/a.md")] } as never]),
      detail: /missing a non-empty string id/,
    },
    {
      raw: manifestOf([{ id: "", docs: [doc("docs/learned/a.md")] }]),
      detail: /missing a non-empty string id/,
    },
    {
      raw: manifestOf([
        { id: "a-1", docs: [doc("docs/learned/a.md")] },
        { id: "a-1", docs: [doc("docs/learned/b.md")] },
      ]),
      detail: /duplicate lane id 'a-1'/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [] }]),
      detail: /lane 'a-1' docs must be a non-empty array/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc("/etc/passwd")] }]),
      detail: /lane 'a-1' doc path '\/etc\/passwd' is absolute/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc("../secrets")] }]),
      detail: /doc path '\.\.\/secrets' escapes the checkout/,
    },
    {
      // Normalizes to `x` — inside the checkout but outside the corpus.
      raw: manifestOf([{ id: "a-1", docs: [doc("docs/learned/../../x")] }]),
      detail: /doc path 'docs\/learned\/\.\.\/\.\.\/x' is outside docs\/learned\//,
    },
    {
      // Normalizes to `../x` — escapes the checkout itself.
      raw: manifestOf([{ id: "a-1", docs: [doc("docs/../../x")] }]),
      detail: /doc path 'docs\/\.\.\/\.\.\/x' escapes the checkout/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc("src/perk/cli.py")] }]),
      detail: /doc path 'src\/perk\/cli\.py' is outside docs\/learned\//,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc("docs/learned/a.md", { title: 4 as never })] }]),
      detail: /title\/read_when must each be string or null/,
    },
    // Malformed NESTED shapes — corrupt untrusted JSON must land on the named refusal path,
    // never a throw (every arm below returns { ok: false }).
    { raw: manifestOf([null as never]), detail: /a manifest lane is not an object/ },
    { raw: manifestOf(["lane" as never]), detail: /a manifest lane is not an object/ },
    { raw: manifestOf([[] as never]), detail: /a manifest lane is not an object/ },
    {
      raw: manifestOf([{ id: "a-1", docs: "nope" as never }]),
      detail: /lane 'a-1' docs must be a non-empty array/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [null] }]),
      detail: /lane 'a-1' carries a doc that is not an object/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: ["doc"] }]),
      detail: /lane 'a-1' carries a doc that is not an object/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [{ title: null, read_when: null }] }]),
      detail: /doc without a non-empty string path/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc(7 as never)] }]),
      detail: /doc without a non-empty string path/,
    },
    {
      raw: manifestOf([{ id: "a-1", docs: [doc("")] }]),
      detail: /doc without a non-empty string path/,
    },
  ];
  for (const arm of arms) {
    const result = decodeHarvestManifest(arm.raw);
    assert.equal(result.ok, false, `must refuse: ${JSON.stringify(arm.raw)}`);
    assert.match((result as { detail: string }).detail, arm.detail);
  }
});

// ------------------------------------------------------------- the resolved containment

test("verifyDocContainment: contained paths pass; nonexistent paths skip", () => {
  const manifest = decoded(TWO_LANE_RAW);
  const root = `${sep}repo`;
  const corpus = join(root, "docs", "learned");
  const fs = {
    exists: (p: string) => p === join(root, "docs/learned/pi/subagents.md"),
    realpath: (p: string) => p, // no symlinks — resolved paths are the literal paths
  };
  // One existing contained doc + one nonexistent doc (skipped): the wave is dispatchable.
  assert.deepEqual(verifyDocContainment(manifest, root, fs), { ok: true });
  assert.ok(corpus.startsWith(root), "sanity: the corpus root is under the checkout");
});

test("verifyDocContainment: an escaping symlink refuses with the lane + path named", () => {
  const manifest = decoded(TWO_LANE_RAW);
  const root = `${sep}repo`;
  const fs = {
    exists: () => true,
    realpath: (p: string) =>
      p.endsWith(join("pi", "subagents.md")) ? join(`${sep}outside`, "evil.md") : p,
  };
  const result = verifyDocContainment(manifest, root, fs);
  assert.equal(result.ok, false);
  const detail = (result as { detail: string }).detail;
  assert.match(detail, /lane 'pi-1'/);
  assert.match(detail, /docs\/learned\/pi\/subagents\.md/);
  assert.match(detail, /resolves outside docs\/learned\//);
});

test("verifyDocContainment: a throwing realpath on an existing path refuses, never throws", () => {
  const manifest = decoded(TWO_LANE_RAW);
  const fs = {
    exists: () => true,
    realpath: (p: string): string => {
      if (p.endsWith(join("docs", "learned"))) return p;
      throw new Error("EACCES: permission denied");
    },
  };
  const result = verifyDocContainment(manifest, `${sep}repo`, fs);
  assert.equal(result.ok, false);
  assert.match((result as { detail: string }).detail, /could not be resolved: EACCES/);
});

test("verifyDocContainment: a corpus root escaping the checkout refuses (the symlinked-root guard)", () => {
  // The gather core's posture: a docs/learned that is itself a symlink out of the checkout
  // would launder every doc beneath the outside target through the per-doc check — refuse
  // before dispatching anything.
  const manifest = decoded(TWO_LANE_RAW);
  const root = `${sep}repo`;
  const realCorpus = join(`${sep}volumes`, "corpus");
  const fs = {
    exists: (p: string) => p === join(root, "docs/learned/pi/subagents.md"),
    realpath: (p: string) => {
      if (p === join(root, "docs", "learned")) return realCorpus;
      if (p === join(root, "docs/learned/pi/subagents.md")) {
        return join(realCorpus, "pi", "subagents.md");
      }
      return p;
    },
  };
  const result = verifyDocContainment(manifest, root, fs);
  assert.equal(result.ok, false);
  assert.match(
    (result as { detail: string }).detail,
    /docs\/learned resolves outside the checkout \(a symlinked corpus root\)/,
  );
});

test("verifyDocContainment: containment is judged on RESOLVED paths (a relocated checkout)", () => {
  // The whole checkout resolves elsewhere CONSISTENTLY (e.g. macOS /var → /private/var): the
  // resolved corpus root stays inside the resolved checkout and docs under it are contained.
  const manifest = decoded(TWO_LANE_RAW);
  const root = `${sep}repo`;
  const realRoot = join(`${sep}private`, "repo");
  const fs = {
    exists: (p: string) => p === join(root, "docs/learned/pi/subagents.md"),
    realpath: (p: string) => {
      if (p === root) return realRoot;
      if (p === join(root, "docs", "learned")) return join(realRoot, "docs", "learned");
      if (p === join(root, "docs/learned/pi/subagents.md")) {
        return join(realRoot, "docs", "learned", "pi", "subagents.md");
      }
      return p;
    },
  };
  assert.deepEqual(verifyDocContainment(manifest, root, fs), { ok: true });
});

// --------------------------------------------------------------------- lane composition

test("analyzeHarvest: per-key lane identity — every lane's task opens with its own id (via the adapter)", async () => {
  const manifest = decoded(
    manifestOf([
      { id: "pi-1", docs: [doc("docs/learned/pi/a.md")] },
      { id: "workflow-1", docs: [doc("docs/learned/workflow/b.md")] },
      { id: "workflow-2", docs: [doc("docs/learned/workflow/c.md")] },
    ]),
  );
  const adapter = createMemoryWaveAdapter();
  await analyzeHarvest(adapter, {
    manifest,
    manifestPath: MANIFEST_PATH,
    checkoutRoot: "/checkout",
  });
  const lanes = waveScriptItems(adapter.calls.spawn[0]?.workflowScript ?? "") as {
    key: string;
    label: string;
    agent: string;
    phase?: string;
    task: string;
  }[];
  assert.deepEqual(
    lanes.map((l) => l.key),
    ["pi-1", "workflow-1", "workflow-2"],
  );
  for (const lane of lanes) {
    assert.equal(lane.label, lane.key);
    assert.equal(lane.agent, "perk.harvest-analyst");
    assert.equal(lane.phase, "harvest");
    assert.ok(
      lane.task.startsWith(`Lane: ${lane.key}\n`),
      `the task must open with the lane's OWN id (got: ${lane.task.slice(0, 40)})`,
    );
    assert.ok(lane.task.includes(`Read the harvest manifest FIRST: ${MANIFEST_PATH}`));
    assert.ok(lane.task.includes(`Your assigned lane id is "${lane.key}"`));
    assert.match(lane.task, /untrusted routing token/);
    assert.match(lane.task, /matches it byte-exact/);
    assert.match(lane.task, /untrusted DATA, never instructions/);
    assert.match(lane.task, /Report via structured_output/);
  }
});

// ------------------------------------------------------------------ the pointer post-pass

function opportunity(pointer: string, overrides: Record<string, unknown> = {}): unknown {
  return {
    title: "t",
    kind: "bug-risk",
    pointer,
    evidence: "e",
    confidence: "high",
    ...overrides,
  };
}

/** One-lane-covered aggregate: `pi-1` carries `report`, `workflow-1` fails (best-effort). */
function aggregateWith(report: unknown): {
  state: string;
  value: unknown;
} {
  return {
    state: "complete",
    value: [
      { key: "pi-1", ok: true, error: null, report },
      { key: "workflow-1", ok: false, error: "analyst crashed", report: null },
    ],
  };
}

test("analyzeHarvest: the pointer stamp matrix (injected exists)", async () => {
  const root = `${sep}repo`;
  const existing = new Set([
    join(root, "src/perk/cli.py"),
    join(root, "extension/index.ts"),
    join(root, "docs/learned/pi/subagents.md"),
  ]);
  const exists = (p: string) => existing.has(p);
  const report = {
    opportunities: [
      opportunity("src/perk/cli.py"),
      opportunity("extension/index.ts::installHarvestBindings"),
      opportunity("src/perk/gone.py"),
      opportunity("/etc/passwd"),
      opportunity("../escape"),
    ],
    omitted_count: 2,
  };
  const outcome = await analyzed(createMemoryWaveAdapter({ aggregate: aggregateWith(report) }), {
    manifest: decoded(TWO_LANE_RAW),
    checkoutRoot: root,
    exists,
  });
  const laneReport = outcome.reports[0];
  assert.equal(laneReport?.lane, "pi-1");
  assert.deepEqual(
    laneReport?.opportunities.map((o) => o.pointer_status),
    ["resolved", "resolved", "unresolved", "unresolved", "unresolved"],
  );
  assert.equal(laneReport?.omitted_count, 2);

  // Empty-path `::Symbol` is unresolved; a `./`-prefixed path normalizes and resolves.
  const edge = await analyzed(
    createMemoryWaveAdapter({
      aggregate: aggregateWith({
        opportunities: [opportunity("::Symbol"), opportunity("./docs/learned/pi/subagents.md")],
        omitted_count: 0,
      }),
    }),
    { manifest: decoded(TWO_LANE_RAW), checkoutRoot: root, exists },
  );
  assert.deepEqual(
    edge.reports[0]?.opportunities.map((o) => o.pointer_status),
    ["unresolved", "resolved"],
  );
});

test("analyzeHarvest: existence is checked on the path segment before the FIRST ::", async () => {
  const root = `${sep}repo`;
  const seen: string[] = [];
  const exists = (p: string) => {
    seen.push(p);
    return true;
  };
  const outcome = await analyzed(
    createMemoryWaveAdapter({
      aggregate: aggregateWith({
        opportunities: [
          {
            title: "t",
            kind: "elegance",
            pointer: "a/b.py::C::method",
            evidence: "e",
            confidence: "low",
          },
        ],
        omitted_count: 0,
      }),
    }),
    { manifest: decoded(TWO_LANE_RAW), checkoutRoot: root, exists },
  );
  assert.equal(outcome.reports[0]?.opportunities[0]?.pointer_status, "resolved");
  assert.deepEqual(seen, [join(root, "a/b.py")], "the segment before the FIRST :: only");
});

test("analyzeHarvest: malformed-report arms each degrade the lane with a named detail", async () => {
  const good = {
    title: "t",
    kind: "bug-risk",
    pointer: "src/x.py",
    evidence: "e",
    confidence: "high",
  };
  const arms: { report: unknown; detail: RegExp }[] = [
    // A non-object report is caught by the runner's own aggregate normalization — the lane
    // still degrades to malformed-report before the stamp ever runs.
    { report: "nope", detail: /carries a non-object report \(string\)/ },
    { report: { opportunities: [good] }, detail: /omitted_count is not a non-negative integer/ },
    {
      report: { opportunities: [good], omitted_count: -1 },
      detail: /omitted_count is not a non-negative integer/,
    },
    {
      report: { opportunities: [good], omitted_count: 1.5 },
      detail: /omitted_count is not a non-negative integer/,
    },
    { report: { omitted_count: 0 }, detail: /opportunities is not an array/ },
    {
      report: { opportunities: [{ ...good, kind: "feature" }], omitted_count: 0 },
      detail: /outside the report schema vocabulary/,
    },
    {
      report: { opportunities: [{ ...good, confidence: "certain" }], omitted_count: 0 },
      detail: /outside the report schema vocabulary/,
    },
    {
      report: { opportunities: [{ ...good, title: 7 }], omitted_count: 0 },
      detail: /outside the report schema vocabulary/,
    },
    {
      report: { opportunities: [null], omitted_count: 0 },
      detail: /an analyst opportunity is not an object/,
    },
    {
      // Cap+1 otherwise-valid opportunities — the over-cap arm (derived from the constant).
      report: {
        opportunities: Array.from({ length: HARVEST_MAX_OPPORTUNITIES + 1 }, () => ({ ...good })),
        omitted_count: 0,
      },
      detail: new RegExp(
        `more than ${HARVEST_MAX_OPPORTUNITIES} opportunities \\(${HARVEST_MAX_OPPORTUNITIES + 1}\\)`,
      ),
    },
  ];
  for (const arm of arms) {
    const outcome = await analyzed(
      createMemoryWaveAdapter({ aggregate: aggregateWith(arm.report) }),
      { manifest: decoded(TWO_LANE_RAW), exists: () => true },
    );
    assert.deepEqual(outcome.reports, [], `must degrade: ${JSON.stringify(arm.report)}`);
    assert.equal(outcome.skipped[0]?.lane, "pi-1");
    assert.equal(outcome.skipped[0]?.reason, "malformed-report");
    assert.match(outcome.skipped[0]?.detail ?? "", arm.detail);
  }
});

test("analyzeHarvest: stamped records carry exactly the six whitelisted keys", async () => {
  const outcome = await analyzed(
    createMemoryWaveAdapter({
      aggregate: aggregateWith({
        opportunities: [
          {
            title: "t",
            kind: "simplification",
            pointer: "src/x.py",
            evidence: "e",
            confidence: "medium",
            smuggled: "an extra input key",
          },
        ],
        omitted_count: 0,
      }),
    }),
    { manifest: decoded(TWO_LANE_RAW), exists: () => true },
  );
  const record = outcome.reports[0]?.opportunities[0] as unknown as Record<string, unknown>;
  assert.deepEqual(Object.keys(record ?? {}).sort(), [
    "confidence",
    "evidence",
    "kind",
    "pointer",
    "pointer_status",
    "title",
  ]);
});

// ---------------------------------------------------------------------------- the entry op

test("analyzeHarvest: the spawn contract over the memory adapter (schema, best-effort, model)", async () => {
  const manifest = decoded(TWO_LANE_RAW);
  const report = { opportunities: [], omitted_count: 0 };
  const adapter = createMemoryWaveAdapter({
    aggregate: {
      state: "complete",
      value: [
        { key: "pi-1", ok: true, error: null, report },
        { key: "workflow-1", ok: false, error: "analyst crashed", report: null },
      ],
    },
  });
  const outcome = await analyzed(adapter, { manifest, model: "faux/analyst" });
  assert.deepEqual(
    outcome.reports,
    [{ lane: "pi-1", opportunities: [], omitted_count: 0 }],
    "best-effort: a lane failure never fails the analysis",
  );
  assert.deepEqual(outcome.skipped, [
    { lane: "workflow-1", reason: "lane-failed", detail: "analyst crashed" },
  ]);
  // ONE attempt receipt, flow-attributed, with the pre-launch assignment manifest.
  assert.equal(outcome.attempts.length, 1);
  assert.equal(outcome.attempts[0]?.flow, "harvest");
  assert.equal(outcome.attempts[0]?.attempt, 1);
  assert.deepEqual(outcome.attempts[0]?.requestedKeys, ["pi-1", "workflow-1"]);

  assert.equal(adapter.calls.spawn.length, 1);
  const spawn = adapter.calls.spawn[0];
  assert.equal(spawn?.async, true);
  assert.equal(spawn?.mission, false);
  assert.equal(spawn?.context, "fresh");
  assert.equal(spawn?.model, "faux/analyst");
  assert.deepEqual(spawn?.outputSchema, HARVEST_ANALYST_REPORT_SCHEMA);
  assert.match(spawn?.workflowScript ?? "", /perk\.harvest-analyst/);
  assert.match(spawn?.workflowScript ?? "", /"pi-1"/);
  assert.match(spawn?.workflowScript ?? "", /"workflow-1"/);
});

test("analyzeHarvest: the unavailable arm is wave_failed carrying the attempt receipt", async () => {
  const manifest = decoded(TWO_LANE_RAW);
  const adapter = createMemoryWaveAdapter({ ping: null });
  const outcome = await analyzeHarvest(adapter, {
    manifest,
    manifestPath: MANIFEST_PATH,
    checkoutRoot: "/checkout",
  });
  assert.equal(outcome.kind, "wave_failed");
  const failed = outcome as Extract<HarvestAnalysisOutcome, { kind: "wave_failed" }>;
  assert.equal(failed.reason, "unavailable");
  assert.match(failed.detail, /report-wave capabilities/);
  assert.equal(failed.attempts.length, 1);
  assert.equal(failed.attempts[0]?.flow, "harvest");
  assert.equal(failed.attempts[0]?.state, "unavailable");
  assert.deepEqual(failed.attempts[0]?.requestedKeys, ["pi-1", "workflow-1"]);
});

// ------------------------------------------------------- the agent-def lockstep pin

test("the harvest-analyst def agrees with the report schema — structured_output completion, no fenced JSON", () => {
  // The wave fails any lane without a schema-valid structured_output call, so the def and
  // HARVEST_ANALYST_REPORT_SCHEMA must agree (the adversarialReviewWave.test.ts pattern).
  const defPath = join(import.meta.dirname, "..", "..", "agents", "harvest-analyst.md");
  const def = readFileSync(defPath, "utf8");
  const schema = HARVEST_ANALYST_REPORT_SCHEMA as {
    required: string[];
    properties: { opportunities: { maxItems: number; items: { required: string[] } } };
  };
  for (const field of schema.required) {
    assert.match(def, new RegExp(`\`${field}\``), `the def must name the report field ${field}`);
  }
  for (const field of schema.properties.opportunities.items.required) {
    assert.match(
      def,
      new RegExp(`\`${field}\``),
      `the def must name the opportunity field ${field}`,
    );
  }
  for (const kind of HARVEST_KINDS) {
    assert.ok(def.includes(kind), `the def must name the kind ${kind}`);
  }
  // The completion form: the engine-injected structured_output phrasing, never fenced JSON.
  assert.match(def, /engine-injected \*\*`structured_output`\*\* tool/);
  assert.match(def, /never print a fenced JSON block/);
  assert.doesNotMatch(def, /```json/, "no fenced-JSON completion form anywhere in the def");
  // The cap prose agrees with the one named constant.
  assert.ok(def.includes(`top **≤ ${HARVEST_MAX_OPPORTUNITIES}**`));
  assert.equal(schema.properties.opportunities.maxItems, HARVEST_MAX_OPPORTUNITIES);
  // The delivered `.pi/agents/perk/` mirror stays byte-identical (the same-commit convergence).
  const mirror = join(
    import.meta.dirname,
    "..",
    "..",
    ".pi",
    "agents",
    "perk",
    "harvest-analyst.md",
  );
  assert.equal(readFileSync(mirror, "utf8"), def, "the .pi/agents/perk mirror must not drift");
});
