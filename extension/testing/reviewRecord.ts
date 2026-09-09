// A test-side current-review record runtime (dev-only): the REAL runtime over an injected,
// deterministic save-destination reader (no git/config shelling) and a read-only branch-backed
// session for the approve-time artifact re-read. Tests that drive destination drift pass their
// own `destination` reader; everything else gets a fixed snapshot.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ReviewOutcome } from "../pi/v1/reviewOutcome.ts";
import {
  type CurrentReviewRuntime,
  createCurrentReviewRuntime,
  type PlanReviewBridge,
  type ReviewDestination,
} from "../pi/v1/reviewRecord.ts";
import { openBranchWorkflowSession } from "../session/branchWorkflowSession.ts";

/** The fixed destination every non-drift test reviews under. */
export const TEST_REVIEW_DESTINATION: ReviewDestination = {
  backend: "github",
  team: null,
  remotes: ["remote.origin.url https://example.com/origin.git"],
};

export function testReviewRuntime(
  opts: {
    destination?: (cwd: string) => ReviewDestination;
    session?: (ctx: ExtensionContext) => ReturnType<typeof openBranchWorkflowSession>;
  } = {},
): CurrentReviewRuntime {
  // The default session dep never appends (the approve gate only reads), so no real `pi` is
  // needed; the runtime's `pi` parameter feeds only the production default session closure.
  const noPi = { appendEntry() {} } as unknown as ExtensionAPI;
  return createCurrentReviewRuntime(noPi, {
    destination: opts.destination ?? (() => TEST_REVIEW_DESTINATION),
    session: opts.session ?? ((ctx) => openBranchWorkflowSession({ appendEntry() {} }, ctx)),
  });
}

/**
 * A bridge whose review is SUPERSEDED mid-flight: while the decision is outstanding another
 * record opens on the same runtime (a door run, say), so the arm's record is no longer current
 * when `outcome` lands. `reviewed` records the rendered bytes the bridge was handed.
 */
export function supersedingBridge(
  outcome: ReviewOutcome,
  ctx: ExtensionContext,
  reviews: CurrentReviewRuntime = testReviewRuntime(),
): PlanReviewBridge & { reviewed: string[] } {
  const bridge = {
    reviewed: [] as string[],
    current: reviews,
    async review(plan: string): Promise<ReviewOutcome> {
      bridge.reviewed.push(plan);
      reviews.open(ctx, null);
      return outcome;
    },
  };
  return bridge;
}
