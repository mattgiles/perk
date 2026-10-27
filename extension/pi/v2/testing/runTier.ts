// Run one v2 node:test tier: `node extension/pi/v2/testing/runTier.ts <fast|slow> [node --test
// flags…]` (the `test-v2` / `test-v2-slow` recipes). The dot reporter and 2× core concurrency over
// the tier's explicit file list; extra flags ride before the files. Exits with node's own status.
// An independent, v2-owned copy of `extension/testing/runJsTestTier.ts` — v2 may not import v1's
// runner (`layering.ts`' cross-generation rule).

import { spawnSync } from "node:child_process";
import { availableParallelism } from "node:os";
import { resolve } from "node:path";
import { argv, execPath, exit } from "node:process";
import { v2TierFiles } from "./tiers.ts";

const [tier, ...flags] = argv.slice(2);
if (tier !== "fast" && tier !== "slow") {
  console.error("usage: node extension/pi/v2/testing/runTier.ts <fast|slow> [node --test flags…]");
  exit(2);
}
// extension/pi/v2/testing/ → the repo root is four levels up.
const root = resolve(import.meta.dirname, "..", "..", "..", "..");
const files = v2TierFiles(tier, root);
if (files.length === 0) {
  if (tier === "slow") {
    // The slow tier is legitimately empty until its first real-process test lands.
    console.log(
      "perk v2: the slow tier selected no files — it stays empty until the first *.slow.test.ts lands",
    );
    exit(0);
  }
  // The fast tier always holds the host smoke and the guards; an empty list would make
  // `node --test` fall back to its default discovery — never widen.
  console.error("perk v2: the fast tier selected no files");
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
