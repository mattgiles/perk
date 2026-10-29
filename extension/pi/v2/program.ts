// The fixture review program (docs/design/pi-durable-v2-foundations.md §12 the native assignment):
// the host program that composes the fixture policy with the native Durable report assignment over
// the store's subject snapshots. The door composes this program.
//
// Invariants:
// - The policy is `fixturePolicy()` at `FIXTURE_POLICY_VERSION`; the worker's instructions default
//   to `renderFixtureInstructions`, whose digest that policy binds.
// - Snapshots are verified by the subject layer's `verifySnapshot` over the store directory; the
//   binding never reads the subject layer itself, so the verifier arrives through here.
// - `onVerify` runs before every verification, naming its call site — the test seam that blocks,
//   tampers or restores at exactly one point.

import {
  nativeAssignment,
  type SnapshotVerification,
  type VerifyPoint,
  type WorkerModels,
} from "./durable/assignment.ts";
import type { HostProgram } from "./host.ts";
import {
  FIXTURE_POLICY_VERSION,
  fixturePolicy,
  renderFixtureInstructions,
} from "./kernel/fixture.ts";
import { snapshotDir, verifySnapshot } from "./subject/snapshot.ts";

export type FixtureProgramOptions = {
  readonly models: WorkerModels;
  /** Default `renderFixtureInstructions`. */
  readonly renderInstructions?: () => string;
  /** Default `verifySnapshot`. */
  readonly verifier?: (
    storeDir: string,
    tree: string,
    manifestDigest: string,
  ) => Promise<SnapshotVerification>;
  /** Runs before every verification. */
  readonly onVerify?: (point: VerifyPoint, tree: string) => void | Promise<void>;
};

export function fixtureProgram(options: FixtureProgramOptions): HostProgram {
  const verifier = options.verifier ?? verifySnapshot;
  return {
    policy: fixturePolicy(),
    policyVersion: FIXTURE_POLICY_VERSION,
    assignment: (context) =>
      nativeAssignment({
        deps: context.deps,
        models: options.models,
        verify: async (tree, manifestDigest, point) => {
          await options.onVerify?.(point, tree);
          return verifier(context.storeDir, tree, manifestDigest);
        },
        snapshotRoot: (tree) => snapshotDir(context.storeDir, tree),
        renderInstructions: options.renderInstructions ?? renderFixtureInstructions,
      }),
  };
}
