// A cgroup v2 fence for the comparison probes (dev-only): a child cgroup of this process's own
// cgroup, joined cooperatively by the spawned command (`CGROUP_WRAPPER`), and killed whole through
// `cgroup.kill` — a stop set that ignores sessions and process groups. Whether an unprivileged
// process may do this at all is host policy (the own cgroup must be cgroup2, writable, and offer
// `cgroup.kill`), so `cgroupPreflight` measures it step by step and names the failing step.

import { randomUUID } from "node:crypto";
import {
  accessSync,
  constants,
  existsSync,
  mkdirSync,
  readFileSync,
  rmdirSync,
  statfsSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import type { TestContext } from "node:test";
import { defer } from "../durable.ts";

const CGROUP_ROOT = "/sys/fs/cgroup";
/** `CGROUP2_SUPER_MAGIC` (linux/magic.h). */
const CGROUP2_MAGIC = 0x63677270;

/** This process's cgroup v2 directory (from the `0::` line of `/proc/self/cgroup`). */
export function ownCgroupPath(): string | undefined {
  let text: string;
  try {
    text = readFileSync("/proc/self/cgroup", "utf8");
  } catch {
    return undefined;
  }
  const line = text.split("\n").find((l) => l.startsWith("0::"));
  return line === undefined ? undefined : join(CGROUP_ROOT, line.slice(3));
}

export type Preflight = { ok: true; root: string } | { ok: false; reason: string };

/** Every precondition of a fence under the own cgroup, the first failing one named. */
export function cgroupPreflight(): Preflight {
  const root = ownCgroupPath();
  if (root === undefined) return { ok: false, reason: "no cgroup v2 entry in /proc/self/cgroup" };
  try {
    const type = statfsSync(CGROUP_ROOT).type;
    if (type !== CGROUP2_MAGIC) {
      return {
        ok: false,
        reason: `${CGROUP_ROOT} is not cgroup2 (statfs type 0x${type.toString(16)})`,
      };
    }
  } catch (error) {
    return { ok: false, reason: `statfs ${CGROUP_ROOT}: ${String(error)}` };
  }
  try {
    accessSync(root, constants.W_OK);
    accessSync(join(root, "cgroup.procs"), constants.W_OK);
  } catch (error) {
    return { ok: false, reason: `own cgroup ${root} not writable: ${String(error)}` };
  }
  if (!existsSync(join(root, "cgroup.kill"))) {
    return { ok: false, reason: `${root} has no cgroup.kill` };
  }
  const trial = join(root, `perk-v2-containment-preflight-${randomUUID()}`);
  try {
    mkdirSync(trial);
    rmdirSync(trial);
  } catch (error) {
    return { ok: false, reason: `mkdir+rmdir trial under ${root}: ${String(error)}` };
  }
  return { ok: true, root };
}

export type FenceKill = { readonly unpopulated: boolean; readonly removed: boolean };

function populated(fence: string): boolean {
  return /^populated 1$/m.test(readFileSync(join(fence, "cgroup.events"), "utf8"));
}

/** Kill every process in `fence` via `cgroup.kill`, wait for `populated 0`, then remove it. */
export async function killFenceCgroup(fence: string, timeoutMs = 2000): Promise<FenceKill> {
  if (!existsSync(fence)) return { unpopulated: true, removed: true };
  writeFileSync(join(fence, "cgroup.kill"), "1");
  const deadline = Date.now() + timeoutMs;
  while (populated(fence) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  const unpopulated = !populated(fence);
  try {
    rmdirSync(fence);
  } catch {
    return { unpopulated, removed: false };
  }
  return { unpopulated, removed: true };
}

/** A fresh fence cgroup under `root`, killed and removed after the test. */
export function createFenceCgroup(t: TestContext, root: string): string {
  const fence = join(root, `perk-v2-containment-${randomUUID()}`);
  mkdirSync(fence);
  defer(t, async () => {
    await killFenceCgroup(fence);
  });
  return fence;
}
