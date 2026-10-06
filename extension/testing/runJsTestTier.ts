// Run one node:test tier: `node extension/testing/runJsTestTier.ts <fast|slow> [node --test flags…]`
// (the `test-js-fast` / `test-js-slow` recipes). Same runner flags as the full `test-js` recipe —
// the dot reporter and 2× core concurrency — over the tier's explicit file list; extra flags ride
// before the files (e.g. `--test-name-pattern=…`). Exits with node's own status.

import { spawnSync } from "node:child_process";
import { availableParallelism } from "node:os";
import { resolve } from "node:path";
import { argv, execPath, exit } from "node:process";
import { jsTestTierFiles } from "./jsTestTiers.ts";

const [tier, ...flags] = argv.slice(2);
if (tier !== "fast" && tier !== "slow") {
  console.error("usage: node extension/testing/runJsTestTier.ts <fast|slow> [node --test flags…]");
  exit(2);
}
// extension/testing/ → the repo root is two levels up.
const root = resolve(import.meta.dirname, "..", "..");
const files = jsTestTierFiles(tier, root);
if (files.length === 0) {
  // An empty list would make `node --test` fall back to its default discovery — never widen.
  console.error(`perk: the ${tier} node:test tier selected no files`);
  exit(1);
}
const result = spawnSync(
  execPath,
  [
    "--test",
    "--test-reporter=dot",
    `--test-concurrency=${availableParallelism() * 2}`,
    ...flags,
    ...files,
  ],
  { cwd: root, stdio: "inherit" },
);
exit(result.status ?? 1);
