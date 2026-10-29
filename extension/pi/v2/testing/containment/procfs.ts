// Linux process identity over procfs (dev-only), for the containment probes. A pid alone is never
// an identity — pids are reused — so every helper here pairs it with the process's start time
// (field 22 of `/proc/<pid>/stat`, clock ticks since boot): a live process whose start time differs
// is a different process, and the original is dead. `sweepMarkers` is the report-only sweep the
// verdict candidate runs at open: it lists labelled survivors of earlier epochs and kills nothing.

import { existsSync, readdirSync, readFileSync } from "node:fs";

/** A process as procfs names it: its pid paired with its start time. */
export type Identity = { readonly pid: number; readonly startTime: string };

/** The `/proc/<pid>/stat` fields the probes read. */
export type ProcessStat = Identity & {
  /** One letter: `R`, `S`, `D`, `T`, `Z`, … */
  readonly state: string;
  readonly ppid: number;
  readonly pgid: number;
  readonly sid: number;
};

/** The labels every probe spawn carries; the sweep matches them exactly. Labels, never kill authority. */
export const MARKER_STORE = "PERK_V2_STORE";
export const MARKER_EPOCH = "PERK_V2_EPOCH";

export function procAvailable(): boolean {
  return existsSync("/proc/self/stat");
}

/**
 * `/proc/<pid>/stat`, or `undefined` once the process is gone. The command name (field 2) may hold
 * spaces and parentheses, so fields are counted after its LAST `)`.
 */
export function processStat(pid: number): ProcessStat | undefined {
  let text: string;
  try {
    text = readFileSync(`/proc/${pid}/stat`, "utf8");
  } catch {
    return undefined;
  }
  const close = text.lastIndexOf(")");
  if (close === -1) return undefined;
  // fields[0] is stat field 3 (state), so stat field N is fields[N - 3].
  const fields = text
    .slice(close + 1)
    .trim()
    .split(" ");
  const [state, ppid, pgid, sid] = fields;
  const startTime = fields[19];
  if (state === undefined || startTime === undefined) return undefined;
  return { pid, state, ppid: Number(ppid), pgid: Number(pgid), sid: Number(sid), startTime };
}

/** Dead: gone, a zombie, or a different process under a reused pid. */
export function isDead(id: Identity): boolean {
  const live = processStat(id.pid);
  return (
    live === undefined ||
    live.state === "Z" ||
    live.state === "X" ||
    live.startTime !== id.startTime
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Poll (20 ms) until every identity is dead; `false` if any still lives after `timeoutMs`. */
export async function waitGone(ids: readonly Identity[], timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (ids.every(isDead)) return true;
    if (Date.now() >= deadline) return false;
    await sleep(20);
  }
}

/** SIGKILL `id` only if the live process under its pid is still it. Returns whether it signalled. */
export function killIdentity(id: Identity): boolean {
  if (isDead(id)) return false;
  try {
    process.kill(id.pid, "SIGKILL");
    return true;
  } catch {
    return false;
  }
}

/** Parse a `"<pid> <startTime>\n"` identity record; `undefined` until it is complete. */
export function parseIdentity(text: string): Identity | undefined {
  if (!text.endsWith("\n")) return undefined;
  const match = /^(\d+) (\d+)\n$/.exec(text);
  if (match === null) return undefined;
  return { pid: Number(match[1]), startTime: String(match[2]) };
}

/** The identity record at `path`, or `undefined` while it is absent or incomplete. */
export function readIdentity(path: string): Identity | undefined {
  try {
    return parseIdentity(readFileSync(path, "utf8"));
  } catch {
    return undefined;
  }
}

/**
 * A spawn journal's fence: kill the process `path` registered only if its live start time still
 * matches — `stale` when the pid now names another process (or none), `absent` without a record.
 */
export function fenceRegistered(path: string): "killed" | "stale" | "absent" {
  const id = readIdentity(path);
  if (id === undefined) return "absent";
  return killIdentity(id) ? "killed" : "stale";
}

export type MarkedProcess = {
  readonly pid: number;
  readonly epoch: number;
  readonly startTime: string;
};

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

/**
 * The report-only sweep: every process (but this one) whose initial environment carries exactly
 * `PERK_V2_STORE=<store>` and `PERK_V2_EPOCH=<n>` with `n < belowEpoch`, with its start time read
 * in the same pass. Processes this user cannot read, or that vanish mid-scan, are skipped; a
 * scrubbed environment (`env -i`) is invisible by construction. Kills nothing.
 */
export function sweepMarkers(
  store: string,
  belowEpoch: number,
): MarkedProcess[] | "not_observable" {
  if (!procAvailable()) return "not_observable";
  const found: MarkedProcess[] = [];
  for (const entry of readdirSync("/proc")) {
    if (!/^\d+$/.test(entry)) continue;
    const pid = Number(entry);
    if (pid === process.pid) continue;
    let environ: string;
    try {
      environ = readFileSync(`/proc/${pid}/environ`, "latin1");
    } catch (error) {
      const code = errorCode(error);
      if (code === "EACCES" || code === "ENOENT" || code === "ESRCH" || code === "EPERM") continue;
      throw error;
    }
    const vars = environ.split("\0");
    if (!vars.includes(`${MARKER_STORE}=${store}`)) continue;
    const epochText = vars
      .find((v) => v.startsWith(`${MARKER_EPOCH}=`))
      ?.slice(MARKER_EPOCH.length + 1);
    if (epochText === undefined || !/^\d+$/.test(epochText)) continue;
    const epoch = Number(epochText);
    if (epoch >= belowEpoch) continue;
    const stat = processStat(pid);
    if (stat === undefined) continue;
    found.push({ pid, epoch, startTime: stat.startTime });
  }
  return found.sort((a, b) => a.pid - b.pid);
}
