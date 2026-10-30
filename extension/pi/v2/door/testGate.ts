// The test gate (docs/design/pi-durable-v2-foundations.md §11 and §16, contracts.md §8.77): the
// capstone's timing and process-identity seam. When `PERK_V2_TEST_GATE` names a directory, the host
// entry composes the fixture program with this gate as its `onVerify`, so a test driving the real
// `perk v2` door can see which process verifies what, and hold one verification in flight.
//
// Invariants:
// - It only logs and holds: it never alters a verification result or an observation.
// - On creation it appends `host <pid> <startTime|->` to `<dir>/verify.log` synchronously, so the
//   host announces its identity before any store work; the start time is procfs field 22, or `-`
//   where the liveness seam cannot tell.
// - Before every snapshot verification it appends `<point> <pid> <tree>`, always before any hold,
//   then holds the n-th verification of that point in this process while `<dir>/hold-<point>-<n>`
//   exists. Ordinals count per process and per point.
// - A hold has no upper bound: the test ends a held host, and the door's 600 s timeout is the
//   backstop.

import { appendFileSync, existsSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import type { VerifyPoint } from "../durable/assignment.ts";
import { procfsLiveness } from "../store/liveness.ts";

/** The environment variable naming the gate directory. */
export const TEST_GATE_ENV = "PERK_V2_TEST_GATE";

/** The gate's log, inside its directory. */
export const GATE_LOG = "verify.log";

/** The file whose presence holds the `ordinal`-th verification of `point`. */
export function holdFile(point: VerifyPoint, ordinal: number): string {
  return `hold-${point}-${ordinal}`;
}

export type TestGate = (point: VerifyPoint, tree: string) => Promise<void>;

export type TestGateOptions = {
  /** Default `process.pid`. */
  readonly pid?: number;
  /** Default this process's procfs start time, or `null` where it cannot be read. */
  readonly startTime?: string | null;
  /** How often a hold re-checks its file; default 20 ms. */
  readonly pollMs?: number;
};

function ownStartTime(): string | null {
  const startTime = procfsLiveness().startTimeOf(process.pid);
  return startTime === "unsupported" ? null : startTime;
}

/** A gate over `dir`; announces the host line before it returns. */
export function testGate(dir: string, options: TestGateOptions = {}): TestGate {
  const pid = options.pid ?? process.pid;
  const startTime = options.startTime === undefined ? ownStartTime() : options.startTime;
  const pollMs = options.pollMs ?? 20;
  const log = join(dir, GATE_LOG);
  appendFileSync(log, `host ${pid} ${startTime ?? "-"}\n`);
  const ordinals = new Map<VerifyPoint, number>();
  return async (point, tree) => {
    const ordinal = (ordinals.get(point) ?? 0) + 1;
    ordinals.set(point, ordinal);
    appendFileSync(log, `${point} ${pid} ${tree}\n`);
    const hold = join(dir, holdFile(point, ordinal));
    while (existsSync(hold)) await sleep(pollMs);
  };
}

function isDirectory(path: string): boolean {
  try {
    return statSync(path, { throwIfNoEntry: false })?.isDirectory() === true;
  } catch {
    return false;
  }
}

/**
 * The gate `env` asks for: `undefined` when `PERK_V2_TEST_GATE` is unset or empty, otherwise a gate
 * over the existing absolute directory it names. Any other value throws.
 */
export function testGateFromEnv(env: NodeJS.ProcessEnv): TestGate | undefined {
  const value = env[TEST_GATE_ENV];
  if (value === undefined || value === "") return undefined;
  if (!isAbsolute(value) || !isDirectory(value)) {
    throw new Error(
      `${TEST_GATE_ENV} must name an existing absolute directory, not ${JSON.stringify(value)}`,
    );
  }
  return testGate(value);
}
