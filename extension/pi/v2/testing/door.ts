// The door proofs' shared fixture (dev-only): host CLI argv in the Python door's `--name=value`
// shape, a door target over a real fixture repo and store, and synthetic snapshot inputs over
// kernel-model record sets.
//
// Invariants the proofs rely on:
//   - `cliArgv` renders every option as one `--name=value` token, exactly as the Python door does.
//   - A door target's execution id is `E` and its repo identity the fixture repo's git dir, so a
//     second target over the same store would mismatch only in what it overrides.
//   - Synthetic inputs default to no live task, nothing runnable and no endings; records come from
//     the kernel's own reference applier (`modelChain`), so every id is a real derivation.

import type { TestContext } from "node:test";
import { type CliDeps, runCli } from "../door/cli.ts";
import type { Envelope } from "../door/envelope.ts";
import type { SnapshotInput } from "../door/snapshot.ts";
import type { AttemptEnding } from "../durable/ending.ts";
import type { LiveTaskState } from "../durable/waitReason.ts";
import type { KernelRecord } from "../kernel/records.ts";
import type { WaitReason } from "../kernel/waitReason.ts";
import { E, REF } from "./binding.ts";
import { fixtureSubject } from "./worker.ts";

/** Host CLI argv: the verb, then each option as one `--name=value` token, in order. */
export function cliArgv(verb: string, options: Readonly<Record<string, string>>): string[] {
  return [verb, ...Object.entries(options).map(([name, value]) => `--${name}=${value}`)];
}

/** A synthetic snapshot input over `records`: no live task, nothing runnable, no endings. */
export function snapshotInput(
  records: readonly KernelRecord[],
  waitReason: WaitReason | null,
  overrides: {
    readonly live?: readonly LiveTaskState[];
    readonly runnable?: boolean;
    readonly endings?: ReadonlyMap<string, AttemptEnding>;
  } = {},
): SnapshotInput {
  return {
    records,
    live: overrides.live ?? [],
    runnable: overrides.runnable ?? false,
    endings: overrides.endings ?? new Map(),
    waitReason,
  };
}

export type DoorTarget = {
  readonly repo: string;
  readonly tree: string;
  readonly store: string;
  /** The three options every verb requires. */
  readonly common: Readonly<Record<string, string>>;
  /** `start`'s own options: the fixture repo and its `main` ref. */
  readonly startOptions: Readonly<Record<string, string>>;
  /** Every `onReport` line the host emitted, as `<type>: <message>`. */
  readonly reports: string[];
  /** Run `verb` with the common options plus `extra`; fails the test on a usage error. */
  envelope(verb: string, extra?: Readonly<Record<string, string>>): Promise<Envelope>;
};

/** A fixture repo with one commit on `main`, a fresh store, and a host CLI runner over both. */
export async function doorTarget(t: TestContext, deps: CliDeps = {}): Promise<DoorTarget> {
  const { repo, tree, store } = await fixtureSubject(t);
  const common = { store, execution: E, "repo-identity": `${repo}/.git` };
  const reports: string[] = [];
  return {
    repo,
    tree,
    store,
    common,
    startOptions: { repo, ref: REF },
    reports,
    envelope: async (verb, extra = {}) => {
      const result = await runCli(cliArgv(verb, { ...common, ...extra }), {
        onReport: (error, info) => {
          reports.push(`${info.type}: ${String(error)}`);
        },
        ...deps,
      });
      if (result.kind === "usage") throw new Error(`usage: ${result.message}`);
      return result.envelope;
    },
  };
}
