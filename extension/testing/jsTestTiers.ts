// The node:test suite's two tiers (dev-only; excluded from the published tarball).
//
// The full suite (`just test-js`, `just test`, GitHub CI) runs every file. The in-session
// `run_ci` gate runs only the FAST tier (`just test-js-fast`) so the run-all report fits its time
// budget; the SLOW tier (`just test-js-slow`) is the measured set of files whose own wall time
// dominates the suite (real Pi sessions over real git repositories) — run it ad hoc when working
// near those files. A selection, never a skip: fast ∪ slow is exactly the full suite and the two
// are disjoint (`jsTestTiers.test.ts` pins both, plus the recipe and gate wiring).
//
// Membership rule: a file whose own wall time was ≥ 20 s in a full-suite run under the recipe's
// concurrency (the measurement is recorded in docs/design/archive/js-test-tiers.md). A new slow
// file joins the list in the change that makes it slow.

import { globSync } from "node:fs";

/** The full suite's file globs — exactly the ones the `test-js` and `test` recipes pass. */
export const JS_TEST_GLOBS = [
  "extension/**/*.test.ts",
  "docs/site/src/**/*.test.mjs",
  "packages/perk-dev/**/*.test.mjs",
] as const;

/** The slow tier: repo-relative paths, sorted. */
export const SLOW_JS_TEST_FILES: readonly string[] = [
  "extension/pi/v1/codeReview/automated.test.ts",
  "extension/pi/v1/codeReview/browser.test.ts",
  "extension/pi/v1/codeReview/stack.test.ts",
  "extension/pi/v1/codeReview/terminal.test.ts",
  "extension/pi/v1/delivery/address.test.ts",
  "extension/pi/v1/delivery/commitCompact.test.ts",
  "extension/pi/v1/delivery/conflictResolverEngine.test.ts",
  "extension/pi/v1/delivery/land.test.ts",
  "extension/pi/v1/delivery/ready.test.ts",
  "extension/pi/v1/delivery/stackSync.test.ts",
  "extension/pi/v1/delivery/stackSyncNative.test.ts",
  "extension/pi/v1/delivery/submit.test.ts",
  "extension/pi/v1/delivery/submitConflict.test.ts",
  "extension/pi/v1/draftReviewWaveTools.test.ts",
  "extension/pi/v1/gist.test.ts",
  "extension/pi/v1/learning/dream.test.ts",
  "extension/pi/v1/learning/learn.test.ts",
  "extension/pi/v1/librarian.test.ts",
  "extension/pi/v1/lifecycleGates.test.ts",
  "extension/pi/v1/objectiveAuthoring.test.ts",
  "extension/pi/v1/objectiveDreamGate.test.ts",
  "extension/pi/v1/objectivePlanning.test.ts",
  "extension/pi/v1/objectiveRefinement.test.ts",
  "extension/pi/v1/objectiveReviewBrowser.test.ts",
  "extension/pi/v1/plan.test.ts",
  "extension/pi/v1/planReview.test.ts",
  "extension/pi/v1/planReviewBrowser.test.ts",
  "extension/pi/v1/waveIsolation.test.ts",
  "extension/runSessionRecord.test.ts",
  "extension/session/saveDestination.test.ts",
  "extension/substrate/config.test.ts",
  "extension/substrate/discoveryPilot.test.ts",
  "extension/substrate/git.test.ts",
  "extension/substrate/sessionPointers.test.ts",
  "extension/substrate/worktreeResolverLock.test.ts",
  "extension/worker/stageExecutionE2e.test.ts",
];

export type JsTestTier = "fast" | "slow";

/** Every file the full suite runs, repo-relative and sorted (`node_modules` never included). */
export function allJsTestFiles(root: string): string[] {
  const files = new Set<string>();
  for (const pattern of JS_TEST_GLOBS) {
    for (const file of globSync(pattern, { cwd: root })) {
      const normalized = file.split("\\").join("/");
      if (!normalized.split("/").includes("node_modules")) files.add(normalized);
    }
  }
  return [...files].sort();
}

/** The files of one tier, repo-relative and sorted. */
export function jsTestTierFiles(tier: JsTestTier, root: string): string[] {
  const slow = new Set(SLOW_JS_TEST_FILES);
  return allJsTestFiles(root).filter((file) => slow.has(file) === (tier === "slow"));
}
