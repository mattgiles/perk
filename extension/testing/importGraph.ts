// Policy-free import-graph machinery for `extension/importDirectionGuard.test.ts` — the lexer,
// edge map, cycle detector, and the generic direction/census/token helpers. Dev-only by home:
// `testing/` is excluded from the production corpus every guard scans, from the npm tarball
// (package.json `files`), and from `bareImportGuard.test.ts` — so the exact-pinned `typescript`
// devDependency import below never reaches production sources. ALL policy (the rule contracts,
// the constants, the corpus selectors, and the rule-specific bodies) stays in the guard file;
// these functions take every policy input as a parameter. Their own non-vacuity controls live in
// `extension/testing/importGraph.test.ts`.

import path from "node:path";
import ts from "typescript";

/** Every imported/re-exported module specifier `ts.preProcessFile` lexes from the source text. */
export function extractSpecifiers(sourceText: string): string[] {
  return ts.preProcessFile(sourceText, true, true).importedFiles.map((f) => f.fileName);
}

/** Resolve a relative specifier to an extension-relative posix path (imports carry `.ts`). */
export function resolveRelative(fromFile: string, spec: string): string {
  return path.posix.normalize(path.posix.join(path.posix.dirname(fromFile), spec));
}

/**
 * Build the relative-import edge map: file → sorted unique extension-relative targets. Every
 * relative specifier must resolve to a file in the scanned corpus: an extensionless specifier
 * (`./b`) would otherwise mint a phantom node (`b` ≠ `b.ts`) invisible to cycle detection, so
 * unresolvable specifiers are reported in `unresolved`, never silently edged or dropped.
 */
export function buildEdges(
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
export function findCycles(edges: Map<string, string[]>): string[][] {
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

/**
 * Direction rule: the edges from a banned-source home into a banned-target home. Returns the
 * violating edges directly — enforcement is ratcheted at zero (no allowlist parameter); every
 * caller asserts the empty array.
 */
export function checkDirection(
  edges: Map<string, string[]>,
  bannedSources: string[],
  bannedTargets: string[],
): Array<{ from: string; to: string }> {
  const violations: Array<{ from: string; to: string }> = [];
  for (const [from, targets] of edges) {
    if (!bannedSources.some((prefix) => from.startsWith(prefix))) continue;
    for (const to of targets) {
      if (!bannedTargets.some((prefix) => to.startsWith(prefix))) continue;
      violations.push({ from, to });
    }
  }
  return violations;
}

/**
 * Registration-confinement rule: `matched` = every file whose source carries the registration
 * `token`; `violations` = matched files outside `approvedPrefixes ∪ approvedFiles ∪ legacy`;
 * `stale` = legacy entries that no longer register (the shrink-only arm).
 */
export function checkRegistrationConfinement(
  files: string[],
  read: (file: string) => string,
  token: RegExp,
  approvedPrefixes: string[],
  approvedFiles: string[],
  legacy: string[],
): { matched: string[]; violations: string[]; stale: string[] } {
  const matched = files.filter((file) => token.test(read(file)));
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
 * Token census: every `file:line: match` where a census file carries the raw `token`. Raw text
 * matching (no comment stripping): a comment naming a censused token is itself the leakage the
 * census exists to catch.
 */
export function checkTokenCensus(
  files: string[],
  read: (file: string) => string,
  token: RegExp,
): string[] {
  const violations: string[] = [];
  for (const file of files) {
    const lines = read(file).split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line === undefined) continue;
      const match = token.exec(line);
      if (match) violations.push(`${file}:${i + 1}: ${match[0]}`);
    }
  }
  return violations;
}

/**
 * Census rule: live top-level dirs must equal `frozen ∪ keys(anchored)` set-exactly; the frozen
 * census and the anchored registrations never overlap (a new directory registers ONLY in the
 * anchored map — the frozen list never grows); and every anchored dir carries ≥1 anchor,
 * each an in-directory `.ts` file present in the scanned corpus — so a future home can neither
 * become expected anchor-free nor satisfy its floor with a file outside itself.
 */
export function checkDirCensus(
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
