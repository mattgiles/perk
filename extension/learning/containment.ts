// The docs/learned corpus-containment policy shared by the harvest and dream flows: the pure
// LEXICAL layer (relative, POSIX-normalizes without escaping, stays under `docs/learned/`) and
// the RESOLVED layer (realpath containment inside the resolved corpus root — the symlink
// posture mirroring `resolve_harvest_docs`). A leaf module by construction: it consumes only a
// structural `LanedDocs` view of a manifest, so both `HarvestManifest` and `DreamManifest`
// pass unchanged with no type edge back into either flow. (contracts.md §8.48/§8.60)

import { existsSync, realpathSync } from "node:fs";
import { isAbsolute, join, posix, sep } from "node:path";

/**
 * The lexical doc-containment layer (pure): relative, POSIX-normalizes without escaping, and
 * stays under `docs/learned/`. Returns the human-readable violation, or null when contained.
 */
export function lexicalContainmentError(path: string): string | null {
  if (posix.isAbsolute(path) || isAbsolute(path)) {
    return "is absolute";
  }
  const normalized = posix.normalize(path);
  if (normalized === ".." || normalized.startsWith("../")) {
    return "escapes the checkout";
  }
  if (!normalized.startsWith("docs/learned/")) {
    return "is outside docs/learned/";
  }
  return null;
}

/** The injectable filesystem slice `verifyDocContainment` resolves through (offline tests). */
export interface ContainmentFs {
  exists: (p: string) => boolean;
  realpath: (p: string) => string;
}

const REAL_FS: ContainmentFs = {
  exists: existsSync,
  realpath: (p) => realpathSync(p),
};

/**
 * The structural manifest view the resolved layer consumes: lanes of docs, each doc a path.
 * Both flows' decoded manifests are structurally assignable, so the call sites pass their
 * manifests unchanged — and this module keeps no type edge back into either flow.
 */
export interface LanedDocs {
  lanes: readonly { id: string; docs: readonly { path: string }[] }[];
}

/**
 * The RESOLVED doc-containment layer (decision beyond the lexical decode): before any spawn,
 * every doc path that exists on the checkout is realpath-checked to stay inside the resolved
 * `docs/learned/` root — matching `resolve_harvest_docs`' symlink posture, so an escaping
 * symlink refuses the wave. The corpus root itself must resolve inside the RESOLVED checkout
 * (the gather core's symlinked-corpus-root guard: an out-of-checkout root would launder every
 * doc beneath the outside target through the per-doc check). A nonexistent doc path passes
 * (nothing to resolve and nothing an analyst can read; doc existence itself is deliberately
 * not required), and the roots are resolved lazily on the first existing doc (all sides
 * realpath'd — containment is judged on resolved paths). A throwing `realpath` on an existing
 * path refuses with the error detail, never a crash.
 */
export function verifyDocContainment(
  manifest: LanedDocs,
  checkoutRoot: string,
  fs: ContainmentFs = REAL_FS,
): { ok: true } | { ok: false; detail: string } {
  let resolvedRoot: string | null = null;
  for (const lane of manifest.lanes) {
    for (const doc of lane.docs) {
      const joined = join(checkoutRoot, doc.path);
      if (!fs.exists(joined)) continue;
      try {
        if (resolvedRoot === null) {
          const resolvedCheckout = fs.realpath(checkoutRoot);
          const candidate = fs.realpath(join(checkoutRoot, "docs", "learned"));
          if (candidate !== resolvedCheckout && !candidate.startsWith(resolvedCheckout + sep)) {
            return {
              ok: false,
              detail:
                "docs/learned resolves outside the checkout (a symlinked corpus root) — the " +
                "wave refuses to dispatch analysts over it",
            };
          }
          resolvedRoot = candidate;
        }
        const resolved = fs.realpath(joined);
        if (resolved !== resolvedRoot && !resolved.startsWith(resolvedRoot + sep)) {
          return {
            ok: false,
            detail:
              `lane '${lane.id}' doc '${doc.path}' resolves outside docs/learned/ ` +
              "(an escaping symlink) — the wave refuses to dispatch analysts over it",
          };
        }
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          detail: `lane '${lane.id}' doc '${doc.path}' could not be resolved: ${detail}`,
        };
      }
    }
  }
  return { ok: true };
}
