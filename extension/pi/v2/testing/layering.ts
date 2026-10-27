// The v2 guard set's policy and rules (dev-only) — enforced by `../layeringGuard.test.ts`.
//
// Three rules, each a pure function over `(files, read)` so the live corpus and the synthetic
// controls run the SAME code:
//
//   Cross-generation (`checkCrossImports`): v1 and v2 never import each other. A v2 → v1 relative
//     import is allowed only from a dev file (`*.test.ts`, `testing/`) to `V1_DEV_ALLOWLIST`, or
//     from a production file to `V1_PRODUCTION_ALLOWLIST` (empty — each addition is a reviewed
//     edit, and an entry nothing imports is reported stale). Every v1 file, tests included, is
//     checked for an import into the v2 workspace — relative, or by the workspace's npm package
//     name (the install links `node_modules/perk-v2` to the workspace, and its manifest has no
//     `exports` restriction, so `perk-v2/<file>` resolves to any v2 file). A v2 → v1 import by
//     package name needs no rule here: v1's package is not linked, and any bare name v2 does not
//     declare is `checkDependencyConfinement`'s `undeclared`.
//   Dependency confinement (`checkDependencyConfinement`): every bare specifier in v2 names a
//     package the workspace manifest declares; in production files bare specifiers live only in
//     the Durable homes (the host entry and `durable/`); files under `kernel/` (tests included)
//     carry none at all.
//   Intra-v2 layering (`checkLayering`): `kernel/ → kernel/`; `durable/ → kernel/ | durable/`;
//     the host entry and the dev files may import any v2 file; no cycles; no unresolved v2 target.
//
// Together the last two prove the kernel Durable-free transitively: its relative closure stays
// inside `kernel/`, and no kernel file names a bare non-`node:` package — so nothing in the
// kernel's runtime graph can reach Durable, chord or pi-ai.

import {
  buildEdges,
  extractSpecifiers,
  findCycles,
  resolveRelative,
} from "../../../testing/importGraph.ts";

export const V2_PREFIX = "pi/v2/";
export const KERNEL_PREFIX = "pi/v2/kernel/";
export const DURABLE_PREFIX = "pi/v2/durable/";
export const HOST_ENTRY = "pi/v2/host.ts";
const V2_TESTING_PREFIX = "pi/v2/testing/";

/** Where production v2 code may import a bare package: the host entry (exact) or `durable/` (prefix). */
export const DURABLE_HOMES: readonly string[] = [HOST_ENTRY, DURABLE_PREFIX];

/** The only v1 files a v2 dev file may import (the policy-free import-graph machinery). */
export const V1_DEV_ALLOWLIST: readonly string[] = ["testing/importGraph.ts"];

/** The v1 files a v2 production file may import — empty; each addition is a reviewed edit here. */
export const V1_PRODUCTION_ALLOWLIST: readonly string[] = [];

/** The workspace's npm package name (its manifest `name`; the live guard pins the two equal). */
export const V2_PACKAGE_NAME = "perk-v2";

type Read = (file: string) => string;

/** A v2 production file: under the workspace, not a test, not under `pi/v2/testing/`. */
export function isV2Production(file: string): boolean {
  return (
    file.startsWith(V2_PREFIX) && !file.endsWith(".test.ts") && !file.startsWith(V2_TESTING_PREFIX)
  );
}

function isRelative(spec: string): boolean {
  return spec.startsWith(".");
}

function isBare(spec: string): boolean {
  return !spec.startsWith(".") && !spec.startsWith("node:");
}

/** A bare specifier's package: its first segment, or the first two for `@scope/name`. */
export function packageName(spec: string): string {
  const segments = spec.split("/");
  return spec.startsWith("@") ? segments.slice(0, 2).join("/") : (segments[0] ?? spec);
}

function inDurableHome(file: string): boolean {
  return DURABLE_HOMES.some((home) => (home.endsWith("/") ? file.startsWith(home) : file === home));
}

/**
 * v1 ↔ v2 imports. `v2ToV1`: a v2 relative import resolving outside the workspace that its file's
 * allowlist does not name. `v1ToV2`: any v1 relative import resolving into the workspace, and any
 * v1 import of the workspace's package name or one of its subpaths. `staleAllowlist`: a
 * production-allowlist entry that is not a v1 file or that no v2 production file imports.
 */
export function checkCrossImports(
  v2Files: readonly string[],
  v1Files: readonly string[],
  read: Read,
  allowlists: { production: readonly string[]; dev: readonly string[] } = {
    production: V1_PRODUCTION_ALLOWLIST,
    dev: V1_DEV_ALLOWLIST,
  },
): { v2ToV1: string[]; v1ToV2: string[]; staleAllowlist: string[] } {
  const v2ToV1: string[] = [];
  const v1ToV2: string[] = [];
  const usedProduction = new Set<string>();
  for (const file of v2Files) {
    const production = isV2Production(file);
    for (const spec of extractSpecifiers(read(file))) {
      if (!isRelative(spec)) continue;
      const target = resolveRelative(file, spec);
      if (target.startsWith(V2_PREFIX)) continue;
      if (production && allowlists.production.includes(target)) {
        usedProduction.add(target);
      } else if (!production && allowlists.dev.includes(target)) {
        // The sanctioned dev import.
      } else {
        v2ToV1.push(`${file}: "${spec}" → ${target}`);
      }
    }
  }
  for (const file of v1Files) {
    for (const spec of extractSpecifiers(read(file))) {
      if (isRelative(spec)) {
        const target = resolveRelative(file, spec);
        if (target.startsWith(V2_PREFIX)) v1ToV2.push(`${file}: "${spec}" → ${target}`);
      } else if (packageName(spec) === V2_PACKAGE_NAME) {
        v1ToV2.push(`${file}: "${spec}" → the ${V2_PACKAGE_NAME} workspace package`);
      }
    }
  }
  const v1Set = new Set(v1Files);
  const staleAllowlist = allowlists.production.filter(
    (entry) => !v1Set.has(entry) || !usedProduction.has(entry),
  );
  return { v2ToV1, v1ToV2, staleAllowlist };
}

/**
 * Bare (non-relative, non-`node:`) specifiers in v2. `undeclared`: the package is not in
 * `declared` (the workspace manifest's dependencies). `leaked`: a bare specifier in a production
 * file outside the Durable homes, or in any file under `kernel/`.
 */
export function checkDependencyConfinement(
  v2Files: readonly string[],
  read: Read,
  declared: ReadonlySet<string>,
): { undeclared: string[]; leaked: string[] } {
  const undeclared: string[] = [];
  const leaked: string[] = [];
  for (const file of v2Files) {
    for (const spec of extractSpecifiers(read(file))) {
      if (!isBare(spec)) continue;
      if (!declared.has(packageName(spec))) undeclared.push(`${file}: "${spec}"`);
      const kernel = file.startsWith(KERNEL_PREFIX);
      if (kernel || (isV2Production(file) && !inDurableHome(file))) {
        leaked.push(`${file}: "${spec}"`);
      }
    }
  }
  return { undeclared, leaked };
}

type Layer = "kernel" | "durable" | "open";

/** `kernel/` and `durable/` files (tests included) are their layer; everything else is open. */
function layerOf(file: string): Layer {
  if (file.startsWith(KERNEL_PREFIX)) return "kernel";
  if (file.startsWith(DURABLE_PREFIX)) return "durable";
  return "open";
}

const ALLOWED_TARGETS: Readonly<Record<Layer, readonly Layer[]>> = {
  kernel: ["kernel"],
  durable: ["kernel", "durable"],
  open: ["kernel", "durable", "open"],
};

/**
 * Intra-v2 relative edges. `violations`: an edge its source layer may not take (`from → to`).
 * `cycles`: every import cycle. `unresolved`: a relative specifier resolving inside the workspace
 * to no corpus file — targets outside the workspace are `checkCrossImports`' business, so they are
 * filtered out of `buildEdges`' report here.
 */
export function checkLayering(
  v2Files: readonly string[],
  read: Read,
): {
  edges: Map<string, string[]>;
  violations: string[];
  cycles: string[][];
  unresolved: string[];
} {
  const { edges, unresolved } = buildEdges([...v2Files], read);
  const violations: string[] = [];
  for (const [from, targets] of edges) {
    const allowed = ALLOWED_TARGETS[layerOf(from)];
    for (const to of targets) {
      if (!allowed.includes(layerOf(to))) violations.push(`${from} → ${to}`);
    }
  }
  // `buildEdges` reports `file: "spec" → resolved`; keep the entries whose resolved target is v2.
  const unresolvedInV2 = unresolved.filter((entry) =>
    entry.slice(entry.lastIndexOf(" → ") + " → ".length).startsWith(V2_PREFIX),
  );
  return { edges, violations, cycles: findCycles(edges), unresolved: unresolvedInV2 };
}
