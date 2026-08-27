// Import-direction + cycle guards over the extension's PRODUCTION import graph.
//
// Corpus: every `.ts` under extension/ except `*.test.ts` and `testing/` (the same selector as
// `bareImportGuard.test.ts` and package.json `files`); `vendor/` is included. Edges are the
// relative import specifiers each file carries — extracted with `ts.preProcessFile` (a real lexer:
// static imports, `import type`, `export … from`, string-literal dynamic `import()`, `require()`;
// comments and string text correctly ignored) and resolved by plain path join. Every resolved
// relative target MUST be a scanned production file (repo imports carry explicit `.ts`
// extensions) — an unresolvable specifier (e.g. extensionless `./b`) is a guard failure, never a
// silent phantom node. TYPE-ONLY EDGES COUNT — a type-only import is still a
// dependency-direction fact (the config↔bindings cycle this guard was born after was type-only).
//
// The rules:
//   A. No production import cycles beyond the frozen `KNOWN_CYCLES` baseline (exact + shrink-only:
//      a stale entry fails, so the baseline can only burn down).
//   B. Stable mechanisms never import features: the mechanism homes — current (`substrate/`,
//      `waves/`, `worker/`) or future (`config/`, `execution/`, `session/` — the
//      module-contracts ownership map's stable layer) — have no edge into the feature-policy
//      homes — current (`doors/`, `factories/`, `adapters/`) or future (`authoring/`,
//      `delivery/`, `codeReview/`, `learning/`) — beyond the ratcheted allowlist (EMPTY today:
//      the last entry died when the plan-read gate moved behind the stage-execution seam).
//      Mechanisms take dependencies as parameters; feature policy calls mechanisms, never the
//      reverse. (`surfaces/` is the sanctioned rendering seam, not a feature home —
//      mechanism→surfaces edges stay allowed.)
//   C. The `extension/` top-level directory census is set-exact. `KNOWN_TOP_LEVEL_DIRS` is
//      FROZEN (this guard's birth census — never append); ANY new directory fails until the
//      directory-creating slice registers it in `ANCHORED_DIRS` with ≥1 in-directory production
//      `.ts` anchor in the scanned corpus — the activation ratchet that forces every future
//      home through this guard.
//   D. Features never import Pi or the RPC wire: `PI_FREE_HOMES` (`authoring/`, `codeReview/`,
//      `learning/`, `session/`) carry no `@earendil-works/*` specifier, no edge to `waves/rpcAdapter.ts`, no edge
//      into `surfaces/` (the report shape these homes need is re-exported through
//      `substrate/sessionData.ts`, so a surfaces edge is never necessary), and no edge into
//      `pi/` (the module-contracts law: the adapter imports the feature, never the reverse).
//      This is a DIRECT-SPECIFIER ban (type-only edges count): it cannot catch Pi vocabulary
//      arriving through a local re-export, and NO re-export seam is sanctioned for these
//      homes — the sanctioned `surfaces/surfaces.ts` re-export pattern serves the
//      feature-policy homes (e.g. `pi/v1/plan.ts`), never the pure ones; adding a seam is a
//      reviewed edit to this rule, not a loophole. The known-anchor floor: the rule must
//      visit ≥1 file per home.
//   E. Pi registration only in approved adapter/composition files: every production file whose
//      source carries a registration token (`pi.registerTool(` / `pi.registerCommand(` /
//      `pi.registerFlag(` / `pi.registerShortcut(` / `pi.registerEntryRenderer(` / `pi.on(` /
//      `registerPerkCommand(` — whitespace-tolerant, word-bounded; `substrate/command.ts`'s
//      definition site is a legacy entry like any other) must be under the `pi/` home, be
//      `index.ts`/`workerMain.ts`, or sit in `LEGACY_REGISTRANTS` — frozen from the
//      activation-day census, shrink-only via the stale arm (the census only burns down as
//      registrations migrate into `pi/`). A LOCATION ratchet, not a runtime
//      single-registration proof — the dogfood gate carries the runtime observation.
//   F. Worker-plane confinement: the only production edge into `worker/` from outside is
//      `workerMain.ts → worker/stageExecution.ts` (exact-set — doubling as the live-edge
//      non-vacuity floor); the only production edge into the private `worker/sdkAdapter.ts` is
//      `worker/stageExecution.ts → worker/sdkAdapter.ts`; and across `workerMain.ts` + every
//      file under `worker/`, ONLY the adapter may carry an `@earendil-works/*` specifier
//      (type edges count) — and it must carry ≥ 1 (the positive floor: the SDK vocabulary
//      provably lives in the adapter and the extractor still sees package specifiers).
//   G. Report-wave transport confinement: the production files outside `waves/` with an edge
//      to `waves/rpcAdapter.ts` are EXACTLY the nine wave registration sites (set-exact both
//      directions; shrink-only intent — the census only burns down as registrations migrate);
//      no production file outside `waves/` has an edge into the interior transport modules
//      (`waves/transport.ts`, `waves/memoryAdapter.ts` — callers reach the wave mechanism
//      through `waves/reportWave.ts`'s logical tier and its one sanctioned `WaveAdapter`
//      re-export); and outside `waves/` + `testing/`, NO file — tests included — carries a
//      raw RPC token (`WAVE_RPC_*` word-bounded, so the public `PERK_WAVE_RPC_PING_MS` env
//      knob never matches) or a `subagents:rpc:v1` channel literal. Positive floor:
//      `waves/rpcAdapter.ts` itself carries ≥ 1 of each. This guard file is the one documented
//      census self-exemption (it necessarily names the tokens it polices).
//
// Test-only `typescript` import: the guard lexes with the exact-pinned `typescript` devDependency;
// production sources gain no imports (`bareImportGuard.test.ts` scans production files only, and
// package.json runtime `dependencies` stay empty).

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import ts from "typescript";

// EMPTY — and ratcheted (shrink-only): the last entry (`adapters/planAdapterPlannotator.ts ⇄
// factories/planReview.ts`) died when the plan flow migrated to `authoring/plan/` + `pi/v1/`
// (the review-outcome vocabulary now lives in the leaf `pi/v1/review.ts`). Any future entry
// requires operator confirmation and names the node that owns its removal. Type-only edge
// extraction keeps its own live positive control in control 1.
const KNOWN_CYCLES: string[][] = [];

/**
 * The stable-mechanism homes (Rule B sources) — current (`substrate/`, `waves/`, `worker/`) and
 * future (`config/`, `execution/`, `session/`, the stable layer of the module-contracts
 * ownership map). The future homes are cheap literals: the rule covers them from the day they
 * appear.
 */
const MECHANISM_HOMES = ["config/", "execution/", "session/", "substrate/", "waves/", "worker/"];

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

// EMPTY — and ratcheted (shrink-only): the last entry (`worker/worker.ts →
// doors/lifecycleGates.ts`) died when `planReadInstruction` moved behind the stage-execution
// seam into `substrate/prompts.ts`. Any future entry requires operator confirmation and names
// the node that owns its removal.
const MECHANISM_EDGE_ALLOWLIST: Array<{ from: string; to: string }> = [];

// The FROZEN extension/ top-level directory census — the directories that existed when this
// guard was born. NEVER append here: ANY new directory fails this guard until the
// directory-creating slice (a) registers it in ANCHORED_DIRS with ≥1 known-anchor file INSIDE
// the new directory (a production `.ts` in the scanned corpus), and (b) wires the target rules
// that apply to it (Rules B/D/E as they fit) — so a future home can never become
// expected anchor-free. Removing a directory updates the census in the same change — the
// standing rule ("every directory-creating slice adds or refreshes a known-anchor assertion"),
// as structure.
const KNOWN_TOP_LEVEL_DIRS = [
  "doors",
  "hunkFeedback",
  "substrate",
  "surfaces",
  "testing",
  "vendor",
  "waves",
  "worker",
];
// Future homes register here as they appear: dir → ≥1 in-directory production `.ts` anchor
// (checkDirCensus rejects an empty list, an out-of-directory anchor, and an anchor missing from
// the scanned corpus).
const ANCHORED_DIRS: Record<string, string[]> = {
  authoring: ["authoring/gist/draft.ts"],
  codeReview: ["codeReview/submission.ts"],
  learning: ["learning/capture.ts"],
  pi: ["pi/v1/gist.ts"],
  session: ["session/workflowSession.ts"],
};

/**
 * The Pi-free homes (Rule D sources): typed features and the session seam. Direct-specifier
 * bans — `@earendil-works/*`, the RPC transport module, and the `surfaces/` rendering seam —
 * with NO sanctioned re-export seams for these homes (see the header).
 */
const PI_FREE_HOMES = ["authoring/", "codeReview/", "learning/", "session/"];

/**
 * Rule E's registration tokens: whitespace-tolerant (a registration split across lines still
 * matches), word-bounded (`api.on(`, `pi.online(`, `registerPerkCommandFoo(` never match).
 * `pi.on(` rides the repo-wide `pi` parameter convention for `ExtensionAPI` — an alias would
 * surface at review as a missed registration against the frozen census.
 */
const REGISTRATION_TOKEN =
  /\bpi\s*\.\s*(?:registerTool|registerCommand|registerFlag|registerShortcut|registerEntryRenderer|on)\s*\(|\bregisterPerkCommand\s*\(/;

/** Rule E's approved registrars: the Pi adapter home + the two composition roots. */
const APPROVED_REGISTRAR_PREFIXES = ["pi/"];
const APPROVED_REGISTRAR_FILES = ["index.ts", "workerMain.ts"];

// Rule G's adapter-construction census: the exact production files outside `waves/` allowed an
// edge to `waves/rpcAdapter.ts` — the wave registration sites (each constructs its adapter
// at its execute site; construction threading was considered and dropped at review). SHRINK-ONLY
// intent: entries leave as flows migrate behind typed operations; no new file may join without
// operator confirmation — the `pi/v1/codeReview/` and `pi/v1/learning/` successors joined under
// their approved migration plans (the operator confirmation: the flows' registration sites moved
// wholesale into the adapter home, swapping their door entries).
const RPC_ADAPTER_IMPORTERS = [
  "doors/address.ts",
  "doors/auditWaveTools.ts",
  "doors/draftReviewWaveTools.ts",
  "doors/dreamWaveTools.ts",
  "doors/harvestWaveTools.ts",
  "pi/v1/codeReview/automated.ts",
  "pi/v1/codeReview/reviewWave.ts",
  "pi/v1/learning/learn.ts",
  "pi/v1/objectivePlanning.ts",
];

/** Rule G's interior transport modules: importable only from inside `waves/`. */
const TRANSPORT_INTERIOR = ["waves/memoryAdapter.ts", "waves/transport.ts"];

/**
 * Rule G's raw-transport tokens: the RPC constant prefix — WORD-BOUNDED, so the public
 * `PERK_WAVE_RPC_PING_MS` env knob (its `WAVE` is preceded by a word character) never
 * matches — and the raw v1 channel literal.
 */
const TRANSPORT_TOKEN = /\bWAVE_RPC_|subagents:rpc:v1/;

// The activation-day registration census (Rule E) — every production file that carried a
// registration token when the rule activated, frozen as literals and SHRINK-ONLY via the stale
// arm: a file that stops registering leaves the census in the same change, and no new file may
// join it (new registrations go under `pi/`). The three deleted gist factories left the census
// in the activating change itself — the first burn-down.
const LEGACY_REGISTRANTS = [
  "doors/address.ts",
  "doors/auditWaveTools.ts",
  "doors/ciExecutor.ts",
  "doors/commitCompact.ts",
  "doors/draftReviewWaveTools.ts",
  "doors/dreamWaveTools.ts",
  "doors/harvestWaveTools.ts",
  "doors/land.ts",
  "doors/lifecycleGates.ts",
  "doors/objectiveReviewBrowser.ts",
  "doors/objectiveStack.ts",
  "doors/planReviewBrowser.ts",
  "doors/ready.ts",
  "doors/selfcheck.ts",
  "doors/submit.ts",
  "substrate/agentScratch.ts",
  "substrate/bindingDelivery.ts",
  "substrate/command.ts",
  "substrate/toolGating.ts",
  "surfaces/surfaces.ts",
  "vendor/btw/btw.ts",
  "vendor/whimsical/whimsical.ts",
];

/** Every imported/re-exported module specifier `ts.preProcessFile` lexes from the source text. */
function extractSpecifiers(sourceText: string): string[] {
  return ts.preProcessFile(sourceText, true, true).importedFiles.map((f) => f.fileName);
}

/** Resolve a relative specifier to an extension-relative posix path (imports carry `.ts`). */
function resolveRelative(fromFile: string, spec: string): string {
  return path.posix.normalize(path.posix.join(path.posix.dirname(fromFile), spec));
}

/**
 * Build the relative-import edge map: file → sorted unique extension-relative targets. Every
 * relative specifier must resolve to a file in the scanned corpus: an extensionless specifier
 * (`./b`) would otherwise mint a phantom node (`b` ≠ `b.ts`) invisible to cycle detection, so
 * unresolvable specifiers are reported in `unresolved`, never silently edged or dropped.
 */
function buildEdges(
  files: string[],
  read: (file: string) => string,
): { edges: Map<string, string[]>; unresolved: string[] } {
  const corpus = new Set(files);
  const edges = new Map<string, string[]>();
  const unresolved: string[] = [];
  for (const file of files) {
    const targets = new Set<string>();
    for (const spec of extractSpecifiers(read(file))) {
      if (!spec.startsWith(".")) continue;
      const resolved = resolveRelative(file, spec);
      if (corpus.has(resolved)) {
        targets.add(resolved);
      } else {
        unresolved.push(`${file}: "${spec}" → ${resolved}`);
      }
    }
    edges.set(file, [...targets].sort());
  }
  return { edges, unresolved };
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
 * Feature-purity rule (Rule D): for every file under a Pi-free home, flag any direct
 * `@earendil-works/*` specifier, any relative edge resolving to `waves/rpcAdapter.ts`, and any
 * relative edge resolving into `surfaces/`. Direct-specifier semantics on the SAME lexer as the
 * edge map — type-only imports count. `visited` carries the per-home file count for the
 * known-anchor floor (an empty home would otherwise pass vacuously).
 */
function checkFeaturePurity(
  files: string[],
  read: (file: string) => string,
  homes: string[],
): { violations: string[]; visited: Map<string, number> } {
  const visited = new Map<string, number>(homes.map((home) => [home, 0]));
  const violations: string[] = [];
  for (const file of files) {
    const home = homes.find((prefix) => file.startsWith(prefix));
    if (home === undefined) continue;
    visited.set(home, (visited.get(home) ?? 0) + 1);
    for (const spec of extractSpecifiers(read(file))) {
      if (spec.startsWith("@earendil-works/")) {
        violations.push(`${file}: "${spec}" (direct Pi import)`);
        continue;
      }
      if (!spec.startsWith(".")) continue;
      const resolved = resolveRelative(file, spec);
      if (resolved === "waves/rpcAdapter.ts") {
        violations.push(`${file}: "${spec}" → ${resolved} (RPC wire)`);
      } else if (resolved.startsWith("surfaces/")) {
        violations.push(`${file}: "${spec}" → ${resolved} (surfaces seam)`);
      } else if (resolved.startsWith("pi/")) {
        // The module-contracts law: features never import Pi adapters — the adapter imports
        // the feature, injecting Pi-shaped dependencies through ports.
        violations.push(`${file}: "${spec}" → ${resolved} (Pi adapter home)`);
      }
    }
  }
  return { violations, visited };
}

/**
 * Registration-confinement rule (Rule E): `matched` = every file whose source carries a
 * registration token; `violations` = matched files outside `approvedPrefixes ∪ approvedFiles ∪
 * legacy`; `stale` = legacy entries that no longer register (the shrink-only arm).
 */
function checkRegistrationConfinement(
  files: string[],
  read: (file: string) => string,
  approvedPrefixes: string[],
  approvedFiles: string[],
  legacy: string[],
): { matched: string[]; violations: string[]; stale: string[] } {
  const matched = files.filter((file) => REGISTRATION_TOKEN.test(read(file)));
  const matchedSet = new Set(matched);
  const violations = matched.filter(
    (file) =>
      !approvedPrefixes.some((prefix) => file.startsWith(prefix)) &&
      !approvedFiles.includes(file) &&
      !legacy.includes(file),
  );
  const stale = legacy.filter((file) => !matchedSet.has(file));
  return { matched, violations, stale };
}

/**
 * Worker-plane confinement (Rule F) computations — deliberately Rule-F-specific (no new generic
 * rule helper: the underlying edge-map/extractor machinery is already control-proven by
 * controls 1/2), shared by the production assertion and its mutation control so the control
 * exercises the SAME comparison logic. `inbound` = every production edge into `worker/` from
 * outside; `adapterEdges` = every production edge into the private `worker/sdkAdapter.ts`;
 * `sdkCarriers` = the census files (`workerMain.ts` + every `worker/` file) carrying a direct
 * `@earendil-works/*` specifier (type edges count — same lexer as the edge map).
 */
function workerConfinement(
  files: string[],
  edges: Map<string, string[]>,
  read: (file: string) => string,
): { inbound: string[]; adapterEdges: string[]; sdkCarriers: string[] } {
  const inbound: string[] = [];
  const adapterEdges: string[] = [];
  for (const [from, targets] of edges) {
    for (const to of targets) {
      if (to.startsWith("worker/") && !from.startsWith("worker/")) {
        inbound.push(`${from} → ${to}`);
      }
      if (to === "worker/sdkAdapter.ts") adapterEdges.push(`${from} → ${to}`);
    }
  }
  const census = files.filter((file) => file === "workerMain.ts" || file.startsWith("worker/"));
  const sdkCarriers = census.filter((file) =>
    extractSpecifiers(read(file)).some((spec) => spec.startsWith("@earendil-works/")),
  );
  return { inbound: inbound.sort(), adapterEdges: adapterEdges.sort(), sdkCarriers };
}

/**
 * Report-wave transport confinement (Rule G) computations — deliberately Rule-G-specific,
 * shared by the production assertions and their mutation controls so the controls exercise the
 * SAME comparison logic. `rpcImporters` = every production file outside `waves/` with an edge
 * to `waves/rpcAdapter.ts` (compared set-exactly against `RPC_ADAPTER_IMPORTERS`, both
 * directions); `interiorEdges` = every production edge from outside `waves/` into the interior
 * transport modules.
 */
function transportConfinement(edges: Map<string, string[]>): {
  rpcImporters: string[];
  interiorEdges: string[];
} {
  const rpcImporters: string[] = [];
  const interiorEdges: string[] = [];
  for (const [from, targets] of edges) {
    if (from.startsWith("waves/")) continue;
    for (const to of targets) {
      if (to === "waves/rpcAdapter.ts") rpcImporters.push(from);
      if (TRANSPORT_INTERIOR.includes(to)) interiorEdges.push(`${from} → ${to}`);
    }
  }
  return { rpcImporters: rpcImporters.sort(), interiorEdges: interiorEdges.sort() };
}

/**
 * Rule G's token census: every `file:line: match` where a census file carries a raw transport
 * token. Raw text matching (no comment stripping): a comment naming a raw channel outside
 * `waves/` is itself leakage the census exists to catch.
 */
function checkTransportTokens(files: string[], read: (file: string) => string): string[] {
  const violations: string[] = [];
  for (const file of files) {
    const lines = read(file).split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line === undefined) continue;
      const match = TRANSPORT_TOKEN.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

/**
 * Census rule: live top-level dirs must equal `frozen ∪ keys(anchored)` set-exactly; the frozen
 * census and the anchored registrations never overlap (a new directory registers ONLY in
 * `ANCHORED_DIRS` — the frozen list never grows); and every anchored dir carries ≥1 anchor,
 * each an in-directory `.ts` file present in the scanned corpus — so a future home can neither
 * become expected anchor-free nor satisfy its floor with a file outside itself.
 */
function checkDirCensus(
  liveDirs: string[],
  frozen: string[],
  anchored: Record<string, string[]>,
  anchorInCorpus: (anchor: string) => boolean,
): { unknown: string[]; stale: string[]; overlap: string[]; anchorIssues: string[] } {
  const expected = new Set([...frozen, ...Object.keys(anchored)]);
  const live = new Set(liveDirs);
  const anchorIssues: string[] = [];
  for (const [dir, anchors] of Object.entries(anchored)) {
    if (anchors.length === 0) {
      anchorIssues.push(`${dir}: no anchor files registered (≥1 required)`);
    }
    for (const anchor of anchors) {
      if (!anchor.startsWith(`${dir}/`)) {
        anchorIssues.push(`${dir}: anchor ${anchor} is not inside the directory`);
      } else if (!anchor.endsWith(".ts") || !anchorInCorpus(anchor)) {
        anchorIssues.push(`${dir}: anchor ${anchor} is not a scanned production .ts file`);
      }
    }
  }
  return {
    unknown: [...live].filter((dir) => !expected.has(dir)).sort(),
    stale: [...expected].filter((dir) => !live.has(dir)).sort(),
    overlap: frozen.filter((dir) => Object.hasOwn(anchored, dir)).sort(),
    anchorIssues,
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

/**
 * Rule G's token-census corpus: every `.ts` under extension/ — TESTS INCLUDED — except
 * `waves/` (where transport vocabulary lives), `testing/` (the shared fake responder implements
 * the envelope), and this guard file itself (the one documented self-exemption: it necessarily
 * names the tokens it polices).
 */
function tokenCensusFiles(): string[] {
  const guardFile = path.basename(import.meta.filename);
  const entries = readdirSync(import.meta.dirname, { recursive: true }) as string[];
  return entries
    .map((entry) => entry.split(path.sep).join("/"))
    .filter(
      (entry) =>
        entry.endsWith(".ts") &&
        !entry.startsWith("waves/") &&
        !entry.startsWith("testing/") &&
        entry !== guardFile,
    )
    .sort();
}

function liveTopLevelDirs(): string[] {
  return readdirSync(import.meta.dirname, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** One scan shared by the production assertions (the controls build their own inputs). */
let scanned: { files: string[]; edges: Map<string, string[]>; unresolved: string[] } | undefined;
function scan(): { files: string[]; edges: Map<string, string[]>; unresolved: string[] } {
  if (scanned === undefined) {
    const files = productionFiles();
    scanned = { files, ...buildEdges(files, readProductionFile) };
  }
  return scanned;
}

function formatCycles(cycles: string[][]): string {
  return cycles.map((cycle) => `  ${cycle.join(" ⇄ ")}`).join("\n");
}

// ---------------------------------------------------------------------------------------------
// Production assertions
// ---------------------------------------------------------------------------------------------

test("every relative import resolves to a scanned production file (explicit .ts targets)", () => {
  assert.deepEqual(
    scan().unresolved,
    [],
    "relative import specifier(s) that do not resolve to a scanned production file — an " +
      "unresolved (e.g. extensionless) specifier would mint a phantom graph node invisible to " +
      "cycle detection. Use an explicit ./path.ts specifier to a production file.",
  );
});

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
  const { unknown, stale, overlap, anchorIssues } = checkDirCensus(
    liveTopLevelDirs(),
    KNOWN_TOP_LEVEL_DIRS,
    ANCHORED_DIRS,
    (anchor) => scan().files.includes(anchor),
  );
  assert.deepEqual(
    unknown,
    [],
    `unregistered extension/ top-level director(y/ies): ${unknown.join(", ")}\n` +
      "The directory-creating slice must (a) register it in ANCHORED_DIRS with ≥1 in-directory " +
      "known-anchor production file, and (b) wire the target rules that apply to it (Rules " +
      "B/D/E as they fit). KNOWN_TOP_LEVEL_DIRS is frozen — never append to it.",
  );
  assert.deepEqual(
    stale,
    [],
    `census entr(y/ies) with no live directory: ${stale.join(", ")} — ` +
      "update the census in the same change that removed the directory.",
  );
  assert.deepEqual(
    overlap,
    [],
    "director(y/ies) in BOTH the frozen census and ANCHORED_DIRS — a new directory registers " +
      "only in ANCHORED_DIRS; the frozen census never grows.",
  );
  assert.deepEqual(anchorIssues, [], "ANCHORED_DIRS anchor issue(s)");
});

test("Rule D: Pi-free homes never import Pi, the RPC wire, or surfaces", () => {
  const { violations, visited } = checkFeaturePurity(
    scan().files,
    readProductionFile,
    PI_FREE_HOMES,
  );
  assert.deepEqual(
    violations,
    [],
    "Pi/RPC/surfaces import(s) from a Pi-free home: typed features and the session seam take " +
      "Pi-shaped dependencies as parameters (ports), never as imports. Invert the edge — do NOT " +
      "add a re-export seam (none is sanctioned for these homes; see this guard's header).",
  );
  for (const home of PI_FREE_HOMES) {
    assert.ok(
      (visited.get(home) ?? 0) >= 1,
      `Rule D visited no files under ${home} — the rule is vacuous for that home`,
    );
  }
});

test("Rule E: Pi registration only in approved adapter/composition files (frozen census)", () => {
  const { matched, violations, stale } = checkRegistrationConfinement(
    scan().files,
    readProductionFile,
    APPROVED_REGISTRAR_PREFIXES,
    APPROVED_REGISTRAR_FILES,
    LEGACY_REGISTRANTS,
  );
  // Positive extraction proof: the scan must SEE the v1 installers' registrations — a token
  // regex that stopped matching real registrations would otherwise pass vacuously.
  for (const installer of [
    "pi/v1/codeReview/submit.ts",
    "pi/v1/gist.ts",
    "pi/v1/plan.ts",
    "pi/v1/objectivePlanning.ts",
  ]) {
    assert.ok(
      matched.includes(installer),
      `the registration scan missed ${installer} — the token extraction is broken`,
    );
  }
  assert.deepEqual(
    violations,
    [],
    "registration token(s) outside the approved registrars: new registrations live under pi/ " +
      "(the adapter home) or the composition roots — LEGACY_REGISTRANTS is frozen and never grows.",
  );
  assert.deepEqual(
    stale,
    [],
    "stale LEGACY_REGISTRANTS entr(y/ies) with no live registration token — the census is " +
      "shrink-only: delete the entry in the same change that migrated or removed the registration.",
  );
});

test("Rule F: worker-plane confinement (exact edges; SDK specifiers only in the adapter)", () => {
  const { files, edges } = scan();
  const { inbound, adapterEdges, sdkCarriers } = workerConfinement(
    files,
    edges,
    readProductionFile,
  );
  // (1) Exact-set: the ONLY production edge into worker/ from outside is the composition
  // root → seam edge — which doubles as the live-edge non-vacuity floor (an empty scan or a
  // dropped edge map could never produce exactly this edge).
  assert.deepEqual(
    inbound,
    ["workerMain.ts → worker/stageExecution.ts"],
    "the production edges into worker/ from outside must be exactly " +
      "workerMain.ts → worker/stageExecution.ts — no other production file may import into the " +
      "worker plane; call the seam through workerMain or move the mechanism into substrate/.",
  );
  // (2) Exact-set: the private adapter has exactly one importer — the seam.
  assert.deepEqual(
    adapterEdges,
    ["worker/stageExecution.ts → worker/sdkAdapter.ts"],
    "worker/sdkAdapter.ts is PRIVATE to the seam: its only production importer is " +
      "worker/stageExecution.ts (tests may import it deliberately; production never).",
  );
  // (3) The SDK-specifier census: only the adapter carries @earendil-works/* — and it MUST
  // carry ≥ 1 (the positive floor: the SDK vocabulary provably lives in the adapter and the
  // extractor still sees package specifiers). Covers the seam and any future worker/ file.
  assert.deepEqual(
    sdkCarriers,
    ["worker/sdkAdapter.ts"],
    "across workerMain.ts + worker/*, only worker/sdkAdapter.ts may carry an " +
      "@earendil-works/* specifier (type edges count) — and it must carry at least one.",
  );
});

test("Rule G: report-wave transport confinement (exact importers; interior ban; token census)", () => {
  const { rpcImporters, interiorEdges } = transportConfinement(scan().edges);
  // (1) Exact-set both directions: the ten registration sites — which double as the live-edge
  // non-vacuity floor (an empty scan or a dropped edge map could never produce exactly these).
  assert.deepEqual(
    rpcImporters,
    [...RPC_ADAPTER_IMPORTERS].sort(),
    "the production files outside waves/ importing waves/rpcAdapter.ts must be exactly the " +
      "nine wave registration sites — the census is shrink-only: a site that stops constructing " +
      "its adapter leaves the census in the same change, and no new file may join it.",
  );
  // (2) The interior ban: callers reach the wave mechanism through reportWave.ts's logical
  // tier (and its one sanctioned WaveAdapter re-export) — never the transport tier directly.
  assert.deepEqual(
    interiorEdges,
    [],
    "production edge(s) from outside waves/ into the interior transport modules " +
      "(waves/transport.ts, waves/memoryAdapter.ts): import the logical tier " +
      "(waves/reportWave.ts) instead — transport types are confined by design.",
  );
  // (3) The token census, tests included: no raw RPC channel/envelope vocabulary outside
  // waves/ + testing/ (test doubles ride testing/fakeSubagents.ts, not hand-rolled envelopes).
  const censusFiles = tokenCensusFiles();
  assert.ok(
    censusFiles.some((file) => file.endsWith(".test.ts")),
    "the token census saw no test files — the census corpus is misaimed",
  );
  assert.deepEqual(
    checkTransportTokens(censusFiles, readProductionFile),
    [],
    "raw transport token(s) outside waves/ + testing/: drive the fake responder through " +
      "testing/fakeSubagents.ts instead of naming WAVE_RPC_* constants or the raw " +
      "subagents:rpc:v1 channel.",
  );
  // (4) The positive floor: the adapter itself must carry both token families — a rotted
  // regex or a renamed channel would otherwise leave the census vacuous.
  const adapterSource = readProductionFile("waves/rpcAdapter.ts");
  assert.ok(
    /\bWAVE_RPC_/.test(adapterSource) && adapterSource.includes("subagents:rpc:v1"),
    "waves/rpcAdapter.ts no longer carries the censused tokens — the census is vacuous",
  );
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
    "worker/stageExecution.ts",
  ]) {
    assert.ok(files.includes(anchor), `scan missed ${anchor} — guard is misaimed`);
  }
  assert.ok(edges.size > 0, "edge map came up empty — guard is vacuous");
  assert.ok(
    (edges.get("substrate/config.ts") ?? []).includes("substrate/bindings.ts"),
    "edge map missed the live runtime edge substrate/config.ts → substrate/bindings.ts",
  );
  // Explicit type-extraction floor: this live edge is a type-only import
  // (`import type { ReviewOutcome }`) — if type edges were dropped, this would match nothing.
  assert.ok(
    (edges.get("doors/plannotatorHandoff.ts") ?? []).includes("pi/v1/review.ts"),
    "edge map missed the live type-only edge doors/plannotatorHandoff.ts → pi/v1/review.ts",
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

  // A synthetic allowlist entry (the live allowlist is empty): a matched entry is neither a
  // violation nor stale.
  const allowlisted = checkDirection(
    new Map([["worker/x.ts", ["doors/y.ts"]]]),
    MECHANISM_HOMES,
    FEATURE_HOMES,
    [{ from: "worker/x.ts", to: "doors/y.ts" }],
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

test("control 7: census fixtures (unknown, stale, overlap, anchor floor, valid entry)", () => {
  const frozen = ["alpha", "beta"];
  const inCorpus = (anchor: string) => anchor === "gamma/anchor.ts";

  const unknown = checkDirCensus(["alpha", "beta", "gamma"], frozen, {}, inCorpus);
  assert.deepEqual(unknown.unknown, ["gamma"], "an unknown extra top-level dir must fail");

  const stale = checkDirCensus(["alpha"], frozen, {}, inCorpus);
  assert.deepEqual(stale.stale, ["beta"], "a census entry with no live dir must fail");

  const overlap = checkDirCensus(
    ["alpha", "beta"],
    frozen,
    { beta: ["beta/anchor.ts"] },
    () => true,
  );
  assert.deepEqual(
    overlap.overlap,
    ["beta"],
    "a dir in both the frozen census and ANCHORED_DIRS must fail",
  );

  const emptyAnchors = checkDirCensus(["alpha", "beta", "gamma"], frozen, { gamma: [] }, inCorpus);
  assert.deepEqual(
    emptyAnchors.anchorIssues,
    ["gamma: no anchor files registered (≥1 required)"],
    "an empty anchor registration must fail — a future dir can never become expected anchor-free",
  );
  assert.deepEqual(emptyAnchors.unknown, [], "an anchored dir is a registered dir");

  const outsideAnchor = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["alpha/anchor.ts"] },
    () => true,
  );
  assert.deepEqual(
    outsideAnchor.anchorIssues,
    ["gamma: anchor alpha/anchor.ts is not inside the directory"],
    "an anchor outside its registered directory must fail",
  );

  const uncorpusedAnchor = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["gamma/missing.ts"] },
    inCorpus,
  );
  assert.deepEqual(
    uncorpusedAnchor.anchorIssues,
    ["gamma: anchor gamma/missing.ts is not a scanned production .ts file"],
    "an anchor absent from the scanned corpus must fail",
  );

  const valid = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["gamma/anchor.ts"] },
    inCorpus,
  );
  assert.deepEqual(valid.unknown, []);
  assert.deepEqual(valid.stale, []);
  assert.deepEqual(valid.overlap, []);
  assert.deepEqual(
    valid.anchorIssues,
    [],
    "a registered dir with a valid in-directory corpus anchor must pass",
  );
});

test("control 8: every contractual Rule B prefix bites (literal, array-independent)", () => {
  // Literal contract lists, deliberately independent of the arrays under test: deleting an entry
  // from MECHANISM_HOMES/FEATURE_HOMES fails the deepEqual pins below, and each pair is proven
  // to actually match through checkDirection — so silently weakening either array is caught.
  const sources = ["config/", "execution/", "session/", "substrate/", "waves/", "worker/"];
  const targets = [
    "adapters/",
    "authoring/",
    "codeReview/",
    "delivery/",
    "doors/",
    "factories/",
    "learning/",
  ];
  assert.deepEqual(MECHANISM_HOMES, sources, "MECHANISM_HOMES drifted from the contract list");
  assert.deepEqual(FEATURE_HOMES, targets, "FEATURE_HOMES drifted from the contract list");
  for (const source of sources) {
    for (const target of targets) {
      const { violations } = checkDirection(
        new Map([[`${source}x.ts`, [`${target}y.ts`]]]),
        MECHANISM_HOMES,
        FEATURE_HOMES,
        [],
      );
      assert.deepEqual(
        violations,
        [{ from: `${source}x.ts`, to: `${target}y.ts` }],
        `the ${source} → ${target} pair must be flagged`,
      );
    }
  }
});

test("control 9: an extensionless relative import is reported, never a phantom-node bypass", () => {
  // The discriminating case: a.ts → "./b" (extensionless), b.ts → "./a.ts". Without corpus
  // resolution the cycle would thread through a phantom `b` node and vanish from Tarjan's view;
  // with it, the unresolvable specifier is a reported failure.
  const lax = buildEdges(["a.ts", "b.ts"], (file) =>
    file === "a.ts" ? 'import { x } from "./b";' : 'import { y } from "./a.ts";',
  );
  assert.deepEqual(
    lax.unresolved,
    ['a.ts: "./b" → b'],
    "the extensionless specifier must be reported",
  );
  assert.deepEqual(findCycles(lax.edges), [], "the phantom edge must not fabricate a cycle");

  // The properly-extensioned twin IS the cycle — resolution, not detection, was the gap.
  const strict = buildEdges(["a.ts", "b.ts"], (file) =>
    file === "a.ts" ? 'import { x } from "./b.ts";' : 'import { y } from "./a.ts";',
  );
  assert.deepEqual(strict.unresolved, []);
  assert.deepEqual(findCycles(strict.edges), [["a.ts", "b.ts"]]);
});

test("control 10: feature-purity fixtures (Pi specifier, RPC edge, surfaces edge, clean file, visit floor)", () => {
  const corpus = [
    "authoring/x.ts",
    "session/y.ts",
    "authoring/clean.ts",
    "authoring/adapterEdge.ts",
    "codeReview/z.ts",
    "learning/w.ts",
    "factories/allowed.ts",
  ];
  const sources: Record<string, string> = {
    "authoring/x.ts": 'import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";',
    "session/y.ts":
      'import { call } from "../waves/rpcAdapter.ts";\nimport { report } from "../surfaces/report.ts";',
    "authoring/clean.ts": 'import { helper } from "../substrate/sessionData.ts";',
    // The Rule-D pi/ arm: a feature importing the Pi adapter home must be caught.
    "authoring/adapterEdge.ts": 'import { installPlanBindings } from "../pi/v1/plan.ts";',
    // The codeReview/ home is covered from the day it appeared (all four violation shapes bite).
    "codeReview/z.ts": 'import type { ExtensionContext } from "@earendil-works/pi-coding-agent";',
    // The learning/ home cannot pass Rule D vacuously: a surfaces-seam edge from it must bite.
    "learning/w.ts": 'import { report } from "../surfaces/report.ts";',
    // Outside the Pi-free homes: a factories/ Pi import is Rule-D-invisible by design.
    "factories/allowed.ts": 'import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";',
  };
  const { violations, visited } = checkFeaturePurity(
    corpus,
    (file) => sources[file] ?? "",
    PI_FREE_HOMES,
  );
  assert.deepEqual(violations, [
    'authoring/x.ts: "@earendil-works/pi-coding-agent" (direct Pi import)',
    'session/y.ts: "../waves/rpcAdapter.ts" → waves/rpcAdapter.ts (RPC wire)',
    'session/y.ts: "../surfaces/report.ts" → surfaces/report.ts (surfaces seam)',
    'authoring/adapterEdge.ts: "../pi/v1/plan.ts" → pi/v1/plan.ts (Pi adapter home)',
    'codeReview/z.ts: "@earendil-works/pi-coding-agent" (direct Pi import)',
    'learning/w.ts: "../surfaces/report.ts" → surfaces/report.ts (surfaces seam)',
  ]);
  assert.equal(visited.get("authoring/"), 3, "all three authoring/ files visited");
  assert.equal(visited.get("session/"), 1, "the session/ file visited");
  assert.equal(visited.get("codeReview/"), 1, "the codeReview/ file visited");
  assert.equal(visited.get("learning/"), 1, "the learning/ file visited");
  const empty = checkFeaturePurity(
    ["factories/allowed.ts"],
    (file) => sources[file] ?? "",
    PI_FREE_HOMES,
  );
  assert.equal(empty.visited.get("authoring/"), 0, "an unvisited home reads 0 — the floor bites");
});

test("control 11: registration-confinement fixtures (violation, approved, legacy, stale, word bounds)", () => {
  const sources: Record<string, string> = {
    "substrate/rogue.ts": 'pi.registerTool({ name: "rogue" });',
    "pi/v1/fine.ts": 'pi.registerCommand({ name: "fine" });',
    "index.ts": 'pi.on("session_start", handler);',
    "doors/legacy.ts": "registerPerkCommand(pi, spec);",
    "substrate/quiet.ts": "export const nothing = 1;",
    // Word-bound + whitespace-tolerance probes:
    "substrate/nearMiss.ts":
      'api.on("x", h); pi.online(1); registerPerkCommandFoo(2); spi.registerTool(3);',
    "substrate/split.ts": 'pi\n  .registerTool (\n    { name: "split" });',
  };
  const corpus = Object.keys(sources).sort();
  const read = (file: string) => sources[file] ?? "";
  const { matched, violations, stale } = checkRegistrationConfinement(
    corpus,
    read,
    APPROVED_REGISTRAR_PREFIXES,
    APPROVED_REGISTRAR_FILES,
    ["doors/legacy.ts", "doors/gone.ts"],
  );
  assert.deepEqual(
    matched,
    ["doors/legacy.ts", "index.ts", "pi/v1/fine.ts", "substrate/rogue.ts", "substrate/split.ts"],
    "whitespace-split registrations match; word-bound near-misses never do",
  );
  assert.deepEqual(
    violations,
    ["substrate/rogue.ts", "substrate/split.ts"],
    "a registration outside pi//composition/legacy must fail",
  );
  assert.deepEqual(stale, ["doors/gone.ts"], "a legacy entry with no live token must fail");
});

test("control 12: Rule F mutation fixtures (foreign edge into the seam; a seam SDK specifier)", () => {
  // A synthetic doors/ → seam edge, threaded through the SAME comparison logic as the
  // production assertion, must break the exact-set.
  const mutated = new Map([...scan().edges].map(([file, targets]) => [file, [...targets]]));
  mutated.set("doors/x.ts", [...(mutated.get("doors/x.ts") ?? []), "worker/stageExecution.ts"]);
  const { inbound } = workerConfinement(scan().files, mutated, readProductionFile);
  assert.ok(
    inbound.includes("doors/x.ts → worker/stageExecution.ts"),
    "the synthetic foreign edge into the seam was NOT flagged",
  );
  assert.notDeepEqual(
    inbound,
    ["workerMain.ts → worker/stageExecution.ts"],
    "the exact-set comparison must fail once a foreign edge exists",
  );

  // A synthetic seam-file @earendil-works specifier, threaded through the SAME census logic
  // (extractSpecifiers over fixture text), must join the carrier list — breaking the exact-set.
  const fixtureRead = (file: string): string =>
    file === "worker/stageExecution.ts"
      ? 'import type { Api } from "@earendil-works/pi-ai";'
      : readProductionFile(file);
  const { sdkCarriers } = workerConfinement(scan().files, scan().edges, fixtureRead);
  assert.deepEqual(
    sdkCarriers,
    ["worker/sdkAdapter.ts", "worker/stageExecution.ts"],
    "the synthetic seam SDK specifier was NOT flagged by the census",
  );
});

test("control 13: Rule G mutation fixtures (extra importer; interior edge; token word bounds)", () => {
  // A synthetic extra importer, threaded through the SAME comparison logic as the production
  // assertion, must break the exact-set.
  const mutated = new Map([...scan().edges].map(([file, targets]) => [file, [...targets]]));
  mutated.set("doors/rogue.ts", ["waves/rpcAdapter.ts"]);
  const { rpcImporters } = transportConfinement(mutated);
  assert.ok(
    rpcImporters.includes("doors/rogue.ts"),
    "the synthetic extra rpcAdapter importer was NOT seen",
  );
  assert.notDeepEqual(
    rpcImporters,
    [...RPC_ADAPTER_IMPORTERS].sort(),
    "the exact-set comparison must fail once an unregistered importer exists",
  );
  // The other direction: a census entry whose live edge died must ALSO break the exact-set.
  const shrunk = new Map([...scan().edges].map(([file, targets]) => [file, [...targets]]));
  shrunk.set(
    "doors/address.ts",
    (shrunk.get("doors/address.ts") ?? []).filter((to) => to !== "waves/rpcAdapter.ts"),
  );
  assert.notDeepEqual(
    transportConfinement(shrunk).rpcImporters,
    [...RPC_ADAPTER_IMPORTERS].sort(),
    "a stale census entry (no live edge) must fail the exact-set — the census is shrink-only",
  );

  // A synthetic interior-transport edge must be flagged.
  const interior = transportConfinement(
    new Map([["doors/x.ts", ["waves/transport.ts", "waves/memoryAdapter.ts"]]]),
  );
  assert.deepEqual(interior.interiorEdges, [
    "doors/x.ts → waves/memoryAdapter.ts",
    "doors/x.ts → waves/transport.ts",
  ]);
  // …while waves/-interior edges to the same modules are never flagged (the home is exempt).
  const interiorOk = transportConfinement(
    new Map([["waves/reportWave.ts", ["waves/transport.ts"]]]),
  );
  assert.deepEqual(interiorOk.interiorEdges, []);

  // Token word bounds: raw constants and the raw channel literal match; the PUBLIC
  // PERK_WAVE_RPC_PING_MS env knob (code or comment) never does.
  const sources: Record<string, string> = {
    "doors/rawConstant.test.ts": 'import { WAVE_RPC_REQUEST_EVENT } from "../waves/rpcAdapter.ts";',
    "doors/rawChannel.ts": 'pi.events.emit("subagents:rpc:v1:request", envelope);',
    "doors/knob.test.ts":
      '// pin PERK_WAVE_RPC_PING_MS small\nconst env = { PERK_WAVE_RPC_PING_MS: "20" };',
  };
  const violations = checkTransportTokens(Object.keys(sources).sort(), (f) => sources[f] ?? "");
  assert.deepEqual(violations, [
    "doors/rawChannel.ts:1: subagents:rpc:v1",
    "doors/rawConstant.test.ts:1: WAVE_RPC_",
  ]);
});
