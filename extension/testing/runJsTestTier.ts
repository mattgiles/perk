// Run one node:test selection: `node extension/testing/runJsTestTier.ts <fast|slow|all> [node --test
// flags…]` — `fast` / `slow` are the `test-js-fast` / `test-js-slow` tiers, `all` is the whole v1
// suite the `test-js` and `test` recipes run (a raw `node --test "<glob>"` cannot exclude the v2
// workspace subtree, so the full entrypoints route through the one selector too). The dot reporter
// and 2× core concurrency (session construction is I/O-bound, so more in-flight files overlap
// their I/O waits) over the selection's explicit file list; extra flags ride before the files
// (e.g. `--test-name-pattern=…`). Exits with node's own status.

import { spawnSync } from "node:child_process";
import { availableParallelism } from "node:os";
import { resolve } from "node:path";
import { argv, execPath, exit } from "node:process";
import { allJsTestFiles, jsTestTierFiles } from "./jsTestTiers.ts";

const [tier, ...flags] = argv.slice(2);
if (tier !== "fast" && tier !== "slow" && tier !== "all") {
  console.error(
    "usage: node extension/testing/runJsTestTier.ts <fast|slow|all> [node --test flags…]",
  );
  exit(2);
}
// extension/testing/ → the repo root is two levels up.
const root = resolve(import.meta.dirname, "..", "..");
const files = tier === "all" ? allJsTestFiles(root) : jsTestTierFiles(tier, root);
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
