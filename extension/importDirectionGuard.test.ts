// Import-direction + cycle guards over the extension's PRODUCTION import graph.
//
// Corpus: every `.ts` under extension/ except `*.test.ts` and `testing/` (the same selector as
// `bareImportGuard.test.ts` and package.json `files`); `vendor/` is included. Edges are the
// relative import specifiers each file carries — extracted with `ts.preProcessFile` (a real lexer:
// static imports, `import type`, `export … from`, string-literal dynamic `import()`, `require()`;
// comments and string text correctly ignored) and resolved by plain path join (every repo import
// carries an explicit `.ts` extension). TYPE-ONLY EDGES COUNT — a type-only import is still a
// dependency-direction fact (the config↔bindings cycle this guard was born after was type-only).
//
// The rules:
//   A. No production import cycles beyond the frozen `KNOWN_CYCLES` baseline (exact + shrink-only:
//      a stale entry fails, so the baseline can only burn down).
//   B. Stable mechanisms never import features: `substrate/`, `waves/`, `worker/` have no edge
//      into the feature-policy homes — current (`doors/`, `factories/`, `adapters/`) or future
//      (`authoring/`, `delivery/`, `codeReview/`, `learning/`) — beyond the one ratcheted
//      allowlist entry. Mechanisms take dependencies as parameters; feature policy calls
//      mechanisms, never the reverse. (`surfaces/` is the sanctioned rendering seam, not a
//      feature home — mechanism→surfaces edges stay allowed.)
//   C. The `extension/` top-level directory census is frozen set-exactly. ANY new directory fails
//      until the directory-creating slice registers it (see `KNOWN_TOP_LEVEL_DIRS`) — the
//      activation ratchet that forces every future home through this guard.
//
// DEFERRED RULES (no corpus yet; Rule C forces the activating slice to touch this file):
//   - "Features never import Pi" and "features never import RPC wire" (`waves/rpcAdapter.ts`) —
//     implemented by the slice that creates the first feature directory. Two facts that slice
//     must honor: (a) the rule is a DIRECT-SPECIFIER ban (`@earendil-works/*`; the RPC transport
//     module) — it cannot catch Pi vocabulary arriving through a local re-export (the existing
//     sanctioned pattern: `surfaces/surfaces.ts` re-exports `Key` from `@earendil-works/pi-tui`
//     and `factories/planMode.ts` consumes it), so the activating slice must pair the direct-edge
//     scan with a decision on re-export seams (census the sanctioned ones or add a taint-style
//     walk), with its own non-vacuity controls; (b) an empty first corpus needs the known-anchor
//     floor from `ANCHORED_DIRS`.
//   - "Pi registration only in approved adapter/composition files" — activates when `pi/` is
//     created; a frozen ~40-file allowlist today would churn in every node while proving nothing.
//
// Test-only `typescript` import: the guard lexes with the exact-pinned `typescript` devDependency;
// production sources gain no imports (`bareImportGuard.test.ts` scans production files only, and
// package.json runtime `dependencies` stay empty).

import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import ts from "typescript";

// Removed by Node 4.1 (the plan-review feature slice). Its closing edge is type-only
// (`import type { ReviewOutcome }`), so this entry's stale arm doubles as a live positive control
// that type-only extraction works: if type edges were dropped, the entry would match nothing.
const KNOWN_CYCLES: string[][] = [
  ["adapters/planAdapterPlannotator.ts", "factories/planReview.ts"],
];

/** The stable-mechanism homes (Rule B sources). */
const MECHANISM_HOMES = ["substrate/", "waves/", "worker/"];

/**
 * The feature-policy homes (Rule B banned targets) — current and future. The future homes are
 * cheap literals: the rule covers them from the day they appear.
 */
const FEATURE_HOMES = [
  "adapters/",
  "authoring/",
  "codeReview/",
  "delivery/",
  "doors/",
  "factories/",
  "learning/",
];

// Confined by Node 3.1 (stage-execution seam; the plan-read gate moves behind it). The stale arm
// doubles as a live positive control: the scanner MUST see this real cross-directory edge, so an
// extraction/resolution regression cannot pass silently.
const MECHANISM_EDGE_ALLOWLIST: Array<{ from: string; to: string }> = [
  { from: "worker/worker.ts", to: "doors/lifecycleGates.ts" },
];

// The frozen extension/ top-level directory census. ANY new directory fails this guard until the
// directory-creating slice (a) adds it here, (b) registers ≥1 known-anchor file in ANCHORED_DIRS,
// and (c) wires the target rules that apply to it (see the header's deferral note). Removing a
// directory updates the census in the same change — the standing rule ("every directory-creating
// slice adds or refreshes a known-anchor assertion"), as structure.
const KNOWN_TOP_LEVEL_DIRS = [
  "adapters",
  "doors",
  "factories",
  "hunkFeedback",
  "substrate",
  "surfaces",
  "testing",
  "vendor",
  "waves",
  "worker",
];
const ANCHORED_DIRS: Record<string, string[]> = {}; // future homes register here as they appear

/** Every imported/re-exported module specifier `ts.preProcessFile` lexes from the source text. */
function extractSpecifiers(sourceText: string): string[] {
  return ts.preProcessFile(sourceText, true, true).importedFiles.map((f) => f.fileName);
}

/** Resolve a relative specifier to an extension-relative posix path (imports carry `.ts`). */
function resolveRelative(fromFile: string, spec: string): string {
  return path.posix.normalize(path.posix.join(path.posix.dirname(fromFile), spec));
}

/** Build the relative-import edge map: file → sorted unique extension-relative targets. */
function buildEdges(files: string[], read: (file: string) => string): Map<string, string[]> {
  const edges = new Map<string, string[]>();
  for (const file of files) {
    const targets = new Set<string>();
    for (const spec of extractSpecifiers(read(file))) {
      if (spec.startsWith(".")) targets.add(resolveRelative(file, spec));
    }
    edges.set(file, [...targets].sort());
  }
  return edges;
}

/**
 * Every cycle in the edge map: Tarjan SCCs, keeping each SCC with >1 member or a self-loop.
 * Members are sorted within each cycle; cycles are sorted for stable reporting.
 */
function findCycles(edges: Map<string, string[]>): string[][] {
  const nodes = new Set<string>(edges.keys());
  for (const targets of edges.values()) {
    for (const target of targets) nodes.add(target);
  }

  let counter = 0;
  const index = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const cycles: string[][] = [];

  function strongConnect(v: string): void {
    index.set(v, counter);
    lowlink.set(v, counter);
    counter++;
    stack.push(v);
    onStack.add(v);
    for (const w of edges.get(v) ?? []) {
      if (!index.has(w)) {
        strongConnect(w);
        lowlink.set(v, Math.min(lowlink.get(v) ?? 0, lowlink.get(w) ?? 0));
      } else if (onStack.has(w)) {
        lowlink.set(v, Math.min(lowlink.get(v) ?? 0, index.get(w) ?? 0));
      }
    }
    if (lowlink.get(v) === index.get(v)) {
      const scc: string[] = [];
      for (;;) {
        const w = stack.pop();
        if (w === undefined) break;
        onStack.delete(w);
        scc.push(w);
        if (w === v) break;
      }
      if (scc.length > 1 || (edges.get(v) ?? []).includes(v)) cycles.push(scc.sort());
    }
  }

  for (const v of [...nodes].sort()) {
    if (!index.has(v)) strongConnect(v);
  }
  return cycles.sort((a, b) => a.join(",").localeCompare(b.join(",")));
}

/** A cycle's identity is its member set. */
function cycleKey(cycle: string[]): string {
  return [...cycle].sort().join(" ⇄ ");
}

/**
 * Ratcheted-baseline comparison: `unexpected` = live cycles absent from the baseline (new cycles);
 * `stale` = baseline entries matching no live cycle (the shrink-only arm).
 */
function compareCycles(
  live: string[][],
  baseline: string[][],
): { unexpected: string[][]; stale: string[][] } {
  const liveKeys = new Set(live.map(cycleKey));
  const baselineKeys = new Set(baseline.map(cycleKey));
  return {
    unexpected: live.filter((cycle) => !baselineKeys.has(cycleKey(cycle))),
    stale: baseline.filter((entry) => !liveKeys.has(cycleKey(entry))),
  };
}

/**
 * Direction rule: `violations` = non-allowlisted edges from a banned-source home into a banned-
 * target home; `stale` = allowlist entries matching no live edge (the shrink-only arm).
 */
function checkDirection(
  edges: Map<string, string[]>,
  bannedSources: string[],
  bannedTargets: string[],
  allowlist: Array<{ from: string; to: string }>,
): { violations: Array<{ from: string; to: string }>; stale: Array<{ from: string; to: string }> } {
  const edgeKey = (edge: { from: string; to: string }): string => `${edge.from} → ${edge.to}`;
  const allowed = new Set(allowlist.map(edgeKey));
  const matched = new Set<string>();
  const violations: Array<{ from: string; to: string }> = [];
  for (const [from, targets] of edges) {
    if (!bannedSources.some((prefix) => from.startsWith(prefix))) continue;
    for (const to of targets) {
      if (!bannedTargets.some((prefix) => to.startsWith(prefix))) continue;
      const key = edgeKey({ from, to });
      if (allowed.has(key)) {
        matched.add(key);
        continue;
      }
      violations.push({ from, to });
    }
  }
  const stale = allowlist.filter((entry) => !matched.has(edgeKey(entry)));
  return { violations, stale };
}

/**
 * Census rule: live top-level dirs must equal `known ∪ keys(anchored)` set-exactly, and every
 * registered anchor file must exist.
 */
function checkDirCensus(
  liveDirs: string[],
  known: string[],
  anchored: Record<string, string[]>,
  anchorExists: (anchor: string) => boolean,
): { unknown: string[]; stale: string[]; missingAnchors: string[] } {
  const expected = new Set([...known, ...Object.keys(anchored)]);
  const live = new Set(liveDirs);
  const missingAnchors: string[] = [];
  for (const [dir, anchors] of Object.entries(anchored)) {
    for (const anchor of anchors) {
      if (!anchorExists(anchor)) missingAnchors.push(`${dir}: ${anchor}`);
    }
  }
  return {
    unknown: [...live].filter((dir) => !expected.has(dir)).sort(),
    stale: [...expected].filter((dir) => !live.has(dir)).sort(),
    missingAnchors,
  };
}

/**
 * Production sources: every `.ts` under extension/ except test files and the dev-only testing/
 * fakes (the `bareImportGuard.test.ts` selector; recursive readdir, OS separators normalized).
 */
function productionFiles(): string[] {
  const entries = readdirSync(import.meta.dirname, { recursive: true }) as string[];
  return entries
    .map((entry) => entry.split(path.sep).join("/"))
    .filter(
      (entry) =>
        entry.endsWith(".ts") && !entry.endsWith(".test.ts") && !entry.startsWith("testing/"),
    )
    .sort();
}

function readProductionFile(file: string): string {
  return readFileSync(path.join(import.meta.dirname, file), "utf8");
}

function liveTopLevelDirs(): string[] {
  return readdirSync(import.meta.dirname, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** One scan shared by the production assertions (the controls build their own inputs). */
let scanned: { files: string[]; edges: Map<string, string[]> } | undefined;
function scan(): { files: string[]; edges: Map<string, string[]> } {
  if (scanned === undefined) {
    const files = productionFiles();
    scanned = { files, edges: buildEdges(files, readProductionFile) };
  }
  return scanned;
}

function formatCycles(cycles: string[][]): string {
  return cycles.map((cycle) => `  ${cycle.join(" ⇄ ")}`).join("\n");
}

// ---------------------------------------------------------------------------------------------
// Production assertions
// ---------------------------------------------------------------------------------------------

test("Rule A: no production import cycles beyond the frozen baseline", () => {
  const { unexpected, stale } = compareCycles(findCycles(scan().edges), KNOWN_CYCLES);
  assert.deepEqual(
    unexpected,
    [],
    `production import cycle(s) beyond the frozen baseline:\n${formatCycles(unexpected)}\n` +
      "Break the cycle (invert or delete the closing edge) — do NOT silently baseline it; " +
      "a baseline entry requires operator confirmation and names the node that owns its removal.",
  );
  assert.deepEqual(
    stale,
    [],
    `stale KNOWN_CYCLES entr(y/ies) matching no live cycle:\n${formatCycles(stale)}\n` +
      "The baseline is shrink-only: delete the entry in the same change that broke the cycle.",
  );
});

test("Rule B: stable mechanisms never import features (one ratcheted allowlist entry)", () => {
  const { violations, stale } = checkDirection(
    scan().edges,
    MECHANISM_HOMES,
    FEATURE_HOMES,
    MECHANISM_EDGE_ALLOWLIST,
  );
  assert.deepEqual(
    violations.map((edge) => `${edge.from} → ${edge.to}`),
    [],
    "mechanism→feature import(s): mechanisms take dependencies as parameters; " +
      "feature policy calls mechanisms, never the reverse. Invert the edge (pass the dependency " +
      "in from the feature side) instead of allowlisting.",
  );
  assert.deepEqual(
    stale.map((edge) => `${edge.from} → ${edge.to}`),
    [],
    "stale MECHANISM_EDGE_ALLOWLIST entr(y/ies) matching no live edge — the allowlist is " +
      "shrink-only: delete the entry in the same change that confined the edge.",
  );
});

test("Rule C: the extension/ top-level directory census is set-exact", () => {
  const { unknown, stale, missingAnchors } = checkDirCensus(
    liveTopLevelDirs(),
    KNOWN_TOP_LEVEL_DIRS,
    ANCHORED_DIRS,
    (anchor) => existsSync(path.join(import.meta.dirname, anchor)),
  );
  assert.deepEqual(
    unknown,
    [],
    `unregistered extension/ top-level director(y/ies): ${unknown.join(", ")}\n` +
      "The directory-creating slice must (a) add it to KNOWN_TOP_LEVEL_DIRS, (b) register a " +
      "known-anchor file in ANCHORED_DIRS, and (c) wire the target rules that apply to it " +
      "(see this guard's header deferral note).",
  );
  assert.deepEqual(
    stale,
    [],
    `census entr(y/ies) with no live directory: ${stale.join(", ")} — ` +
      "update the census in the same change that removed the directory.",
  );
  assert.deepEqual(missingAnchors, [], "ANCHORED_DIRS anchor file(s) missing");
});

// ---------------------------------------------------------------------------------------------
// Non-vacuity controls (synthetic inputs through the SAME pure functions; no production edits)
// ---------------------------------------------------------------------------------------------

test("control 1: corpus + edge-map floors and known anchors", () => {
  const { files, edges } = scan();
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  for (const anchor of [
    "index.ts",
    "substrate/config.ts",
    "waves/reportWave.ts",
    "worker/worker.ts",
  ]) {
    assert.ok(files.includes(anchor), `scan missed ${anchor} — guard is misaimed`);
  }
  assert.ok(edges.size > 0, "edge map came up empty — guard is vacuous");
  assert.ok(
    (edges.get("substrate/config.ts") ?? []).includes("substrate/bindings.ts"),
    "edge map missed the live runtime edge substrate/config.ts → substrate/bindings.ts",
  );
  // Explicit type-extraction floor, independent of the Rule A stale arm: this live edge is a
  // type-only import (`import type { ReviewOutcome }`).
  assert.ok(
    (edges.get("adapters/planAdapterPlannotator.ts") ?? []).includes("factories/planReview.ts"),
    "edge map missed the live type-only edge adapters/planAdapterPlannotator.ts → factories/planReview.ts",
  );
});

test("control 2: extractor sees all five specifier forms and ignores comments", () => {
  const fixture = [
    'import a from "./static.ts";',
    'import type { B } from "./typeOnly.ts";',
    'export { c } from "./reExport.ts";',
    'const d = await import("./dynamic.ts");',
    'const e = require("./required.ts");',
    '// import x from "./commented.ts";',
    '/* import y from "./blockCommented.ts"; */',
  ].join("\n");
  const specs = extractSpecifiers(fixture);
  assert.deepEqual([...specs].sort(), [
    "./dynamic.ts",
    "./reExport.ts",
    "./required.ts",
    "./static.ts",
    "./typeOnly.ts",
  ]);
});

test("control 3: cycle-detector fixtures (2-cycle, 3-cycle, self-loop, acyclic)", () => {
  const twoCycle = new Map([
    ["a.ts", ["b.ts"]],
    ["b.ts", ["a.ts"]],
  ]);
  assert.deepEqual(findCycles(twoCycle), [["a.ts", "b.ts"]]);

  const threeCycle = new Map([
    ["a.ts", ["b.ts"]],
    ["b.ts", ["c.ts"]],
    ["c.ts", ["a.ts"]],
  ]);
  assert.deepEqual(findCycles(threeCycle), [["a.ts", "b.ts", "c.ts"]]);

  const selfLoop = new Map([["a.ts", ["a.ts"]]]);
  assert.deepEqual(findCycles(selfLoop), [["a.ts"]]);

  const acyclic = new Map([
    ["a.ts", ["b.ts", "c.ts"]],
    ["b.ts", ["c.ts"]],
    ["c.ts", []],
  ]);
  assert.deepEqual(findCycles(acyclic), []);
});

test("control 4: the resurrection mutation — re-adding bindings→config is caught", () => {
  // The exact regression this guard exists to prevent: take the REAL scanned edge map, re-add the
  // single deleted edge, and prove Rule A would fire.
  const mutated = new Map([...scan().edges].map(([file, targets]) => [file, [...targets]]));
  mutated.set("substrate/bindings.ts", [
    ...(mutated.get("substrate/bindings.ts") ?? []),
    "substrate/config.ts",
  ]);
  const { unexpected } = compareCycles(findCycles(mutated), KNOWN_CYCLES);
  assert.ok(
    unexpected.some(
      (cycle) => cycle.includes("substrate/bindings.ts") && cycle.includes("substrate/config.ts"),
    ),
    "the resurrected config↔bindings cycle was NOT reported outside the baseline",
  );
});

test("control 5: baseline ratchet fixtures (new cycle fails; stale entry fails)", () => {
  const fabricated = [["x.ts", "y.ts"]];
  const missed = compareCycles(fabricated, KNOWN_CYCLES);
  assert.deepEqual(
    missed.unexpected,
    fabricated,
    "a live cycle absent from the baseline must fail",
  );

  const stale = compareCycles([], [["gone-a.ts", "gone-b.ts"]]);
  assert.deepEqual(
    stale.stale,
    [["gone-a.ts", "gone-b.ts"]],
    "a baseline entry matching no live cycle must fail",
  );
});

test("control 6: direction-rule fixtures (violation, allowlisted, stale, future home)", () => {
  const flagged = checkDirection(
    new Map([["substrate/x.ts", ["doors/y.ts"]]]),
    MECHANISM_HOMES,
    FEATURE_HOMES,
    [],
  );
  assert.deepEqual(flagged.violations, [{ from: "substrate/x.ts", to: "doors/y.ts" }]);

  const allowlisted = checkDirection(
    new Map([["worker/worker.ts", ["doors/lifecycleGates.ts"]]]),
    MECHANISM_HOMES,
    FEATURE_HOMES,
    MECHANISM_EDGE_ALLOWLIST,
  );
  assert.deepEqual(allowlisted.violations, [], "the allowlisted edge shape must not be flagged");
  assert.deepEqual(allowlisted.stale, [], "a matched allowlist entry must not read as stale");

  const staleEntry = checkDirection(new Map(), MECHANISM_HOMES, FEATURE_HOMES, [
    { from: "substrate/gone.ts", to: "doors/gone.ts" },
  ]);
  assert.deepEqual(staleEntry.stale, [{ from: "substrate/gone.ts", to: "doors/gone.ts" }]);

  const futureHome = checkDirection(
    new Map([["substrate/x.ts", ["authoring/y.ts"]]]),
    MECHANISM_HOMES,
    FEATURE_HOMES,
    [],
  );
  assert.deepEqual(
    futureHome.violations,
    [{ from: "substrate/x.ts", to: "authoring/y.ts" }],
    "future feature homes must be banned targets already",
  );
});

test("control 7: census fixtures (unknown dir, stale entry, missing anchor, present anchor)", () => {
  const known = ["alpha", "beta"];

  const unknown = checkDirCensus(["alpha", "beta", "gamma"], known, {}, () => true);
  assert.deepEqual(unknown.unknown, ["gamma"], "an unknown extra top-level dir must fail");

  const stale = checkDirCensus(["alpha"], known, {}, () => true);
  assert.deepEqual(stale.stale, ["beta"], "a census entry with no live dir must fail");

  const missingAnchor = checkDirCensus(
    ["alpha", "beta", "gamma"],
    known,
    { gamma: ["gamma/anchor.ts"] },
    () => false,
  );
  assert.deepEqual(missingAnchor.missingAnchors, ["gamma: gamma/anchor.ts"]);
  assert.deepEqual(missingAnchor.unknown, [], "an anchored dir is a registered dir");

  const anchored = checkDirCensus(
    ["alpha", "beta", "gamma"],
    known,
    { gamma: ["gamma/anchor.ts"] },
    (anchor) => anchor === "gamma/anchor.ts",
  );
  assert.deepEqual(anchored.unknown, []);
  assert.deepEqual(anchored.stale, []);
  assert.deepEqual(
    anchored.missingAnchors,
    [],
    "an anchored entry with the anchor present must pass",
  );
});
