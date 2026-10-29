// The store owner lock's liveness seam (docs/design/pi-durable-v2-foundations.md §10 store owner
// lock protocol, "Liveness").
//
// Invariants:
// - A pid alone is never an identity — pids are reused — so a holder is always the pair of its pid
//   and its process start time (Linux `/proc/<pid>/stat` field 22, clock ticks since boot).
// - The seam fails closed: `"unsupported"` (no procfs, an unreadable or unparseable stat) never
//   frees an epoch; only a definite "no such live process" (`null`) or a different start time does.
// - A zombie (`Z`) or dead (`X`) process is no live process: it never runs again.

import { readFileSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";

/** Whether, and as which process, a pid is live on this host. */
export type Liveness = {
  /**
   * The start time of the live process `pid`; `null` when no live process has that pid (absent, or
   * a zombie); `"unsupported"` when this host cannot tell.
   */
  startTimeOf(pid: number): string | null | "unsupported";
};

/** Who holds (or would hold) an epoch: the identity written to its `meta.json`. */
export type HolderIdentity = {
  readonly pid: number;
  readonly host: string;
  /** The process start time; `null` where the liveness seam is unsupported. */
  readonly startedAt: string | null;
};

/**
 * The state (stat field 3) and start time (field 22) of a `/proc/<pid>/stat` line, or `null` when
 * either is missing or the start time is not all digits. The command name (field 2) may hold
 * spaces and parentheses, so fields are counted after its LAST `)`.
 */
export function parseProcStat(text: string): { state: string; startTime: string } | null {
  const close = text.lastIndexOf(")");
  if (close === -1) return null;
  // fields[0] is stat field 3 (state), so stat field N is fields[N - 3].
  const fields = text
    .slice(close + 1)
    .trim()
    .split(/\s+/);
  const state = fields[0];
  const startTime = fields[19];
  if (state === undefined || state === "") return null;
  if (startTime === undefined || !/^[0-9]+$/.test(startTime)) return null;
  return { state, startTime };
}

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

/** Liveness read from a procfs mounted at `root`; `"unsupported"` wherever it cannot be read. */
export function procfsLiveness(root = "/proc"): Liveness {
  return {
    startTimeOf(pid) {
      try {
        readFileSync(join(root, "self", "stat"), "utf8");
      } catch {
        return "unsupported";
      }
      let text: string;
      try {
        text = readFileSync(join(root, String(pid), "stat"), "utf8");
      } catch (error) {
        const code = errorCode(error);
        if (code === "ENOENT" || code === "ESRCH") return null;
        return "unsupported";
      }
      const stat = parseProcStat(text);
      if (stat === null) return "unsupported";
      if (stat.state === "Z" || stat.state === "X") return null;
      return stat.startTime;
    },
  };
}

/** This process's identity under `liveness`: `startedAt` is `null` when the seam cannot tell. */
export function selfIdentity(liveness: Liveness): HolderIdentity {
  const startedAt = liveness.startTimeOf(process.pid);
  return {
    pid: process.pid,
    host: hostname(),
    startedAt: startedAt === "unsupported" ? null : startedAt,
  };
}
