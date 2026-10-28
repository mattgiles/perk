// The containment probes' process fixture (dev-only): a probe directory with the heartbeat script,
// the probe process trees, and an owner process the test can SIGKILL at a named milestone.
//
// Every process a probe can leave behind is bounded twice: a heartbeat exits after 60 s, or as soon
// as its probe directory is gone, and teardown kills through `durable.ts`' LIFO stack — every
// identity a probe read, every daemon an owner reported, every owner, then every identity record
// still in the probe directory — before the directory itself is removed. Kills always go through
// `killIdentity`, so a pid reused since it was recorded is never signalled.

import { type ChildProcess, spawn } from "node:child_process";
import { readdirSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { TestContext } from "node:test";
import { defer, tempDir } from "../durable.ts";
import { type Identity, isDead, killIdentity, processStat, readIdentity } from "./procfs.ts";

/** How long an owner may take to reach any milestone line. */
export const READY_TIMEOUT_MS = 10_000;

/** The window a crash row allows the stop set to die in. */
export const GRACE_MS = 2_000;

/** The owner script, beside this file. */
export const OWNER_PATH = resolve(import.meta.dirname, "owner.ts");

/**
 * `node <dir>/heartbeat.cjs <dir> <name>`: write `<dir>/<name>.pid` as `"<pid> <startTime>\n"` —
 * both read from procfs's own view (field 1 is the pid even inside a PID namespace whose procfs was
 * not remounted) — append a tick to `<dir>/<name>.ticks` every 25 ms, write nothing to stdout or
 * stderr, and exit after 60 s or on the first failed write (its directory was removed).
 */
export const HEARTBEAT_SOURCE = `"use strict";
const { appendFileSync, readFileSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");
try {
  const [dir, name] = process.argv.slice(2);
  const stat = readFileSync("/proc/self/stat", "utf8");
  const pid = stat.slice(0, stat.indexOf(" "));
  const fields = stat.slice(stat.lastIndexOf(")") + 1).trim().split(" ");
  writeFileSync(join(dir, name + ".pid"), pid + " " + fields[19] + "\\n");
  const ticks = join(dir, name + ".ticks");
  setInterval(() => {
    try {
      appendFileSync(ticks, ".");
    } catch {
      process.exit(0);
    }
  }, 25);
  setTimeout(() => process.exit(0), 60000);
} catch {
  process.exit(0);
}
`;

/**
 * The probe tree, run as `sh -c "$TREE" sh <node> <dir>`. The leader records its identity as
 * `leader`, prints `started`, then starts in the background and waits on: `child` (level 1), a
 * `middle` shell (level 1) running `grandchild` (level 2), `setsid` (its own session — the escape),
 * and `scrubbed` (`env -i` — in the group, invisible to an environment-label sweep). Shell
 * identities are read with `read < /proc/self/stat` (a builtin, so `self` is the shell itself).
 */
export const TREE = `read -r s < /proc/self/stat
set -- "$1" "$2" $s
printf '%s %s\\n' "$3" "\${24}" > "$2/leader.pid"
echo started
"$1" "$2/heartbeat.cjs" "$2" child &
sh -c 'read -r s < /proc/self/stat; set -- "$1" "$2" $s; printf "%s %s\\n" "$3" "\${24}" > "$2/middle.pid"; "$1" "$2/heartbeat.cjs" "$2" grandchild & wait' sh "$1" "$2" &
setsid "$1" "$2/heartbeat.cjs" "$2" setsid &
env -i "$1" "$2/heartbeat.cjs" "$2" scrubbed &
wait`;

/** Every identity `TREE` records, the leader first. */
export const TREE_NAMES = [
  "leader",
  "child",
  "middle",
  "grandchild",
  "setsid",
  "scrubbed",
] as const;

/** `TREE`'s group set: every recorded process still in the leader's session. */
export const TREE_GROUP_SET = ["leader", "child", "middle", "grandchild", "scrubbed"] as const;

/** The leader-exited case, `sh -c "$LEADER_EXITS" sh <node> <dir>`: the command settles, `bg` runs on. */
export const LEADER_EXITS = `"$1" "$2/heartbeat.cjs" "$2" bg & exit 0`;

/** `["sh", "-c", script, "sh", node, dir]` — a probe script's argv (no wrapper). */
export function shProgram(script: string, dir: string): string[] {
  return ["sh", "-c", script, "sh", process.execPath, dir];
}

/** A fresh probe directory holding `heartbeat.cjs`; every identity recorded in it is killed at teardown. */
export async function probeDir(t: TestContext): Promise<string> {
  const dir = await tempDir(t, "perk-v2-containment-");
  defer(t, () => {
    for (const file of readdirSync(dir)) {
      if (!file.endsWith(".pid") && file !== "registered") continue;
      const id = readIdentity(join(dir, file));
      if (id !== undefined) killIdentity(id);
    }
  });
  writeFileSync(join(dir, "heartbeat.cjs"), HEARTBEAT_SOURCE);
  return dir;
}

/** What `owner.ts` reads from its config file. */
export type OwnerConfig = {
  readonly env: "node" | "supervised";
  /** Start the daemon under util-linux `setsid` (its own session; same pid). */
  readonly daemonWrap?: "setsid";
  readonly cwd: string;
  /** The probe directory the owner polls for identity records. */
  readonly dir: string;
  /** Label values every spawn carries (`PERK_V2_STORE` / `PERK_V2_EPOCH`). */
  readonly store: string;
  readonly epoch: number;
  readonly program: readonly string[];
  /** The identity records whose presence makes the owner print `ready`. */
  readonly expect: readonly string[];
  /** On stdin EOF: `env.cleanup()`, close the connection, exit 0 (the clean-close control). */
  readonly cleanOnStdinEnd?: boolean;
};

export type OwnerExit = { readonly code: number | null; readonly signal: NodeJS.Signals | null };

export interface Owner {
  readonly pid: number;
  readonly child: ChildProcess;
  /** Spawned in its own process group (`-pid` reaches it and everything it did not detach). */
  readonly detached: boolean;
  readonly exited: Promise<OwnerExit>;
  /** The first stdout line equal to `name` or starting with `name + " "`; rejects after the bound or on exit. */
  line(name: string, timeoutMs?: number): Promise<string>;
  /** The daemon identity the owner reported (`daemon <pid>`), once it has. */
  daemon(): Identity | undefined;
  /** Everything the owner wrote to stderr so far. */
  stderr(): string;
  closeStdin(): void;
}

/** Spawn `node owner.ts <dir>/owner.json`; killed (with its group, if detached) at teardown. */
export function startOwner(
  t: TestContext,
  config: OwnerConfig,
  options: { readonly detached?: boolean } = {},
): Owner {
  const detached = options.detached === true;
  const configPath = join(config.dir, "owner.json");
  writeFileSync(configPath, JSON.stringify(config));
  const child = spawn(process.execPath, [OWNER_PATH, configPath], {
    cwd: config.cwd,
    detached,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const pid = child.pid;
  if (pid === undefined) throw new Error("the owner did not spawn");
  const lines: string[] = [];
  const waiters = new Set<() => void>();
  let stderr = "";
  let exit: OwnerExit | undefined;
  let daemon: Identity | undefined;
  let buffered = "";
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    buffered += chunk;
    for (let newline = buffered.indexOf("\n"); newline !== -1; newline = buffered.indexOf("\n")) {
      const line = buffered.slice(0, newline);
      buffered = buffered.slice(newline + 1);
      lines.push(line);
      const reported = /^daemon (\d+)$/.exec(line);
      const stat = reported === null ? undefined : processStat(Number(reported[1]));
      if (stat !== undefined && daemon === undefined) {
        const id = { pid: stat.pid, startTime: stat.startTime };
        daemon = id;
        defer(t, () => {
          killIdentity(id);
        });
      }
    }
    for (const wake of waiters) wake();
  });
  child.stderr?.setEncoding("utf8");
  child.stderr?.on("data", (chunk: string) => {
    stderr += chunk;
  });
  child.stdin?.on("error", () => {});
  const exited = new Promise<OwnerExit>((resolveExit) => {
    child.once("exit", (code, signal) => {
      exit = { code, signal };
      resolveExit(exit);
      for (const wake of waiters) wake();
    });
  });
  defer(t, async () => {
    if (exit !== undefined) return;
    try {
      process.kill(detached ? -pid : pid, "SIGKILL");
    } catch {
      // Already gone.
    }
    await exited;
  });
  const describe = (): string =>
    `lines=${JSON.stringify(lines)} exit=${JSON.stringify(exit)} stderr=${JSON.stringify(stderr)}`;
  const line = (name: string, timeoutMs = READY_TIMEOUT_MS): Promise<string> =>
    new Promise((resolveLine, reject) => {
      const check = (): boolean => {
        const found = lines.find((l) => l === name || l.startsWith(`${name} `));
        if (found !== undefined) {
          resolveLine(found);
          return true;
        }
        if (exit !== undefined) {
          reject(new Error(`the owner exited before "${name}": ${describe()}`));
          return true;
        }
        return false;
      };
      if (check()) return;
      const timer = setTimeout(() => {
        waiters.delete(wake);
        reject(new Error(`no "${name}" line within ${timeoutMs} ms: ${describe()}`));
      }, timeoutMs);
      const wake = (): void => {
        if (check()) {
          clearTimeout(timer);
          waiters.delete(wake);
        }
      };
      waiters.add(wake);
    });
  return {
    pid,
    child,
    detached,
    exited,
    line,
    daemon: () => daemon,
    stderr: () => stderr,
    closeStdin: () => {
      child.stdin?.end();
    },
  };
}

/** SIGKILL the owner (its whole group with `group`) and await its exit. */
export async function killOwner(
  owner: Owner,
  options: { readonly group?: boolean } = {},
): Promise<OwnerExit> {
  process.kill(options.group === true ? -owner.pid : owner.pid, "SIGKILL");
  return owner.exited;
}

/** The complete identity records under `dir` for `names` (absent or incomplete ones omitted). */
export function pidsNow(dir: string, names: readonly string[]): Map<string, Identity> {
  const found = new Map<string, Identity>();
  for (const name of names) {
    const id = readIdentity(join(dir, `${name}.pid`));
    if (id !== undefined) found.set(name, id);
  }
  return found;
}

/** Every `names` identity record under `dir`, each registered for a kill at teardown. */
export function readPids(
  t: TestContext,
  dir: string,
  names: readonly string[],
): Map<string, Identity> {
  const found = pidsNow(dir, names);
  const missing = names.filter((name) => !found.has(name));
  if (missing.length > 0) throw new Error(`no identity record for ${missing.join(", ")} in ${dir}`);
  for (const id of found.values()) {
    defer(t, () => {
      killIdentity(id);
    });
  }
  return found;
}

function ticks(dir: string, name: string): number | undefined {
  try {
    return statSync(join(dir, `${name}.ticks`)).size;
  } catch {
    return undefined;
  }
}

/**
 * Each process's state: `dead`, or — sampled twice 200 ms apart — `alive (ticking)` /
 * `alive (not ticking)` for a heartbeat, `alive` for a shell (no ticks file).
 */
export async function survivalMap(
  dir: string,
  ids: ReadonlyMap<string, Identity>,
): Promise<Record<string, string>> {
  const first = new Map([...ids.keys()].map((name) => [name, ticks(dir, name)]));
  await new Promise((resolveWait) => setTimeout(resolveWait, 200));
  const map: Record<string, string> = {};
  for (const [name, id] of ids) {
    if (isDead(id)) {
      map[name] = "dead";
      continue;
    }
    const before = first.get(name);
    const after = ticks(dir, name);
    if (before === undefined && after === undefined) map[name] = "alive";
    else
      map[name] =
        after !== undefined && after > (before ?? 0) ? "alive (ticking)" : "alive (not ticking)";
  }
  return map;
}

/** One record's fate after a crash: when it appeared and when it was seen dead (ms after the start). */
export type Appearance = { readonly appearedMs?: number; readonly deadMs?: number };

/**
 * Watch `dir` from now: a record may appear within `windowMs`, and each one that does is watched
 * for `graceMs` after it appeared. Returns every name's fate (a name never seen has `{}`).
 */
export async function watchAppearances(
  dir: string,
  names: readonly string[],
  windowMs = GRACE_MS,
  graceMs = GRACE_MS,
): Promise<Map<string, Appearance>> {
  const start = Date.now();
  const seen = new Map<string, { id: Identity; appearedMs: number; deadMs?: number }>();
  for (;;) {
    const now = Date.now() - start;
    if (now <= windowMs) {
      for (const [name, id] of pidsNow(dir, names)) {
        if (!seen.has(name)) seen.set(name, { id, appearedMs: now });
      }
    }
    for (const entry of seen.values()) {
      if (entry.deadMs === undefined && isDead(entry.id)) entry.deadMs = now;
    }
    const watching = [...seen.values()].some(
      (entry) => entry.deadMs === undefined && now - entry.appearedMs <= graceMs,
    );
    if (now > windowMs && !watching) break;
    await new Promise((resolveWait) => setTimeout(resolveWait, 20));
  }
  const fates = new Map<string, Appearance>();
  for (const name of names) {
    const entry = seen.get(name);
    fates.set(
      name,
      entry === undefined
        ? {}
        : {
            appearedMs: entry.appearedMs,
            ...(entry.deadMs === undefined ? {} : { deadMs: entry.deadMs }),
          },
    );
  }
  return fates;
}

/** `name: never` / `name: appeared+Xms dead+Yms` / `name: appeared+Xms ALIVE`, `; `-joined. */
export function describeAppearances(fates: ReadonlyMap<string, Appearance>): string {
  return [...fates]
    .map(([name, fate]) => {
      if (fate.appearedMs === undefined) return `${name}: never`;
      const end = fate.deadMs === undefined ? "ALIVE" : `dead+${fate.deadMs}ms`;
      return `${name}: appeared+${fate.appearedMs}ms ${end}`;
    })
    .join("; ");
}

/** Every appeared `names` record died within `graceMs` of appearing. */
export function diedInGrace(
  fates: ReadonlyMap<string, Appearance>,
  names: readonly string[],
  graceMs = GRACE_MS,
): boolean {
  return names.every((name) => {
    const fate = fates.get(name);
    if (fate?.appearedMs === undefined) return true;
    return fate.deadMs !== undefined && fate.deadMs - fate.appearedMs <= graceMs;
  });
}
