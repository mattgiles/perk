// The v2 guard set's two corpora (dev-only): the v2 workspace's own sources and every v1 source
// beside it. A v2-local walker on purpose — v2 may not import v1's `extension/testing/v1Corpus.ts`
// (the cross-generation rule in `layering.ts` allows exactly one v1 dev import). Both walks prune
// every `node_modules` directory at the walk, so a nested install is never read, and both fail
// closed on an empty result so a mis-rooted walk cannot make the guards over it vacuous.

import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

/** The extension/ directory: three levels above `pi/v2/testing/`. */
export const EXTENSION_ROOT = resolve(import.meta.dirname, "..", "..", "..");

const V2_DIR = "pi/v2";

/** Every `.ts` under `root/<start>`, extension-relative posix, with `skip(dir)` directories pruned. */
function walkTs(root: string, start: string, skip: (rel: string) => boolean): string[] {
  const files: string[] = [];
  const walk = (dir: string, rel: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = rel === "" ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || skip(path)) continue;
        walk(join(dir, entry.name), path);
      } else if (entry.isFile() && entry.name.endsWith(".ts")) {
        files.push(path);
      }
    }
  };
  walk(start === "" ? root : join(root, start), start);
  if (files.length === 0) throw new Error(`the walk over ${join(root, start)} found no .ts files`);
  return files.sort();
}

/** Every `.ts` in the v2 workspace (tests included), extension-relative (`pi/v2/host.ts`), sorted. */
export function v2Files(root: string = EXTENSION_ROOT): string[] {
  return walkTs(root, V2_DIR, () => false);
}

/** Every `.ts` under extension/ outside the v2 workspace (tests and `testing/` included), sorted. */
export function v1Files(root: string = EXTENSION_ROOT): string[] {
  return walkTs(root, "", (rel) => rel === V2_DIR);
}

/** One extension-relative file's text. */
export function readExtensionFile(file: string): string {
  return readFileSync(join(EXTENSION_ROOT, file), "utf8");
}
