// The v1 corpus: every file under extension/ that v1's tree-walking guards and node:test tiers see
// (dev-only; excluded from the published tarball).
//
// The walk prunes two kinds of directory, at the walk rather than after it: the pi-durable v2
// workspace (`pi/v2/` — its own dependencies, tsconfig, guards and suite; never a v1 surface) and
// every directory named `node_modules` (a nested install must never be scanned — a filter applied
// after a recursive `readdirSync` would still read the whole installed tree, and its files would
// leak into any guard whose own filter forgot it). Each guard keeps its own suffix/prefix filter
// and anchors over this list. v2's own corpus — and the "v1 and v2 never import each other" rule —
// is guarded from the v2 side, by `pi/v2/layeringGuard.test.ts`.

import { readdirSync } from "node:fs";
import { join, resolve } from "node:path";

/** The v2 workspace directory, extension-relative. */
export const V2_WORKSPACE_DIR = "pi/v2";

/** The extension/ directory this module lives under. */
export const EXTENSION_ROOT = resolve(import.meta.dirname, "..");

/**
 * Every file (any extension) under `root`, extension-relative posix paths, sorted — with the v2
 * workspace and every `node_modules` directory pruned. Throws when the walk yields nothing, so a
 * mis-rooted walk fails closed instead of making every guard over it vacuous.
 */
export function v1ExtensionFiles(root: string = EXTENSION_ROOT): string[] {
  const files: string[] = [];
  const walk = (dir: string, rel: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = rel === "" ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || path === V2_WORKSPACE_DIR) continue;
        walk(join(dir, entry.name), path);
      } else if (entry.isFile()) {
        files.push(path);
      }
    }
  };
  walk(root, "");
  if (files.length === 0) throw new Error(`the v1 corpus walk over ${root} found no files`);
  return files.sort();
}
