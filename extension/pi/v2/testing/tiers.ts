// The v2 workspace's node:test tiers (dev-only), by filename: a `*.slow.test.ts` file is SLOW
// (real-process / SIGKILL cases), every other v2 test is FAST. Slow tests are born with the
// suffix, so a file never moves between tiers by editing a list. `tiers.test.ts` pins the
// partition, the fast anchors and the recipe / `[[ci.checks]]` wiring. v1's own tiers
// (`extension/testing/jsTestTiers.ts`) never select a v2 file.

import { globSync } from "node:fs";

/** Every v2 test, repo-relative. */
export const V2_TEST_GLOB = "extension/pi/v2/**/*.test.ts";

/** The suffix that puts a v2 test in the SLOW tier. */
export const SLOW_SUFFIX = ".slow.test.ts";

export type V2Tier = "fast" | "slow";

/** Every v2 test file under `root` (the repo root), repo-relative posix, sorted; `node_modules` pruned. */
export function allV2TestFiles(root: string): string[] {
  return globSync(V2_TEST_GLOB, { cwd: root })
    .map((file) => file.split("\\").join("/"))
    .filter((file) => !file.split("/").includes("node_modules"))
    .sort();
}

/** The files of one v2 tier, repo-relative and sorted. */
export function v2TierFiles(tier: V2Tier, root: string): string[] {
  return allV2TestFiles(root).filter((file) => file.endsWith(SLOW_SUFFIX) === (tier === "slow"));
}
