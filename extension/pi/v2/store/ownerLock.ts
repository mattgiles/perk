// The store owner lock (docs/design/pi-durable-v2-foundations.md §10 store owner lock protocol).
// Durable has no cross-process locking, so exclusivity is the protocol's own, with no OS advisory
// lock.
//
// Layout: `<store>/owner/<epoch>/meta.json` per acquisition (`<epoch>` a decimal ≥ 1 with no
// leading zeros), plus a `released` marker once released. Temp directories `owner/.tmp.<nonce>/`
// and every other non-epoch name are ignored when listing.
//
// Acquire: list `owner/`, take the highest epoch *n* (0 when none) and classify it — free when
// released or its holder is dead, else `owner_busy`. When free, write `meta.json` for *n*+1 into a
// fresh temp directory and rename it to `owner/<n+1>`. A rename onto an existing non-empty
// directory fails, so exactly one contender creates each epoch, and an epoch directory never exists
// without its complete metadata. A lost rename starts the round again, at most `ACQUIRE_ROUNDS`
// times.
//
// Invariants:
// - The epoch is the name of the lock: each epoch number names exactly one acquisition, and epochs
//   strictly increase.
// - "Released" and "dead" are permanent classifications — a marker is never removed, and a process
//   with a given pid and start time never comes back — so creating *n*+1 on the strength of either
//   stays safe however late the rename lands.
// - There is no reclaim rename and no deletion of an epoch directory: deleting one could let a
//   contender working from an older listing re-create it. Retention is store GC's (deferred).
// - Liveness fails closed: a missing or malformed `meta.json`, an epoch mismatch, a foreign host, a
//   `null` start time or an unsupported seam all count as a live holder.
// - Release checks the nonce: a process's memory of having acquired is not a fence.
// - `meta.json` and `released` are synced before their rename. The parent directory is not: the
//   protocol guards process death, not power loss.

import { randomUUID } from "node:crypto";
import { mkdir, open, readdir, readFile, rename, rm, stat } from "node:fs/promises";
import { join } from "node:path";
import { type HolderIdentity, type Liveness, procfsLiveness, selfIdentity } from "./liveness.ts";

export const OWNER_DIR = "owner";
export const META_FILE = "meta.json";
export const RELEASED_FILE = "released";
export const ACQUIRE_ROUNDS = 3;

/** An epoch's `meta.json`: the acquisition's epoch, its holder, and the nonce release checks. */
export type OwnerMeta = {
  readonly epoch: number;
  readonly pid: number;
  readonly host: string;
  readonly startedAt: string | null;
  readonly nonce: string;
};

export type OwnerLockOptions = {
  /** Default `procfsLiveness()`. */
  readonly liveness?: Liveness;
  /** The acquiring identity; default `selfIdentity(liveness)`. */
  readonly self?: HolderIdentity;
  /**
   * Test-only. `beforeRename(epoch)` runs once the temp directory holds its complete `meta.json`,
   * immediately before the rename that would create `owner/<epoch>`.
   */
  readonly hooks?: { beforeRename?(epoch: number): Promise<void> };
};

export type OwnerLockResult =
  | {
      readonly kind: "acquired";
      readonly epoch: number;
      /** Write the `released` marker (nonce-checked). Idempotent: a second call writes nothing. */
      release(): Promise<void>;
    }
  | { readonly kind: "owner_busy"; readonly epoch: number };

const EPOCH_NAME = /^[1-9][0-9]*$/;

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

/** The epoch a directory name denotes, or `null` for any other name. */
function epochOf(name: string): number | null {
  if (!EPOCH_NAME.test(name)) return null;
  const epoch = Number(name);
  return Number.isSafeInteger(epoch) ? epoch : null;
}

async function highestEpoch(ownerDir: string): Promise<number> {
  let highest = 0;
  for (const name of await readdir(ownerDir)) {
    const epoch = epochOf(name);
    if (epoch !== null && epoch > highest) highest = epoch;
  }
  return highest;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

/** `value` as an `OwnerMeta`, or `null` when it is not one. */
export function asOwnerMeta(value: unknown): OwnerMeta | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const epoch: unknown = Reflect.get(value, "epoch");
  const pid: unknown = Reflect.get(value, "pid");
  const host: unknown = Reflect.get(value, "host");
  const startedAt: unknown = Reflect.get(value, "startedAt");
  const nonce: unknown = Reflect.get(value, "nonce");
  if (!isPositiveInteger(epoch) || !isPositiveInteger(pid)) return null;
  if (typeof host !== "string" || host === "") return null;
  if (startedAt !== null && (typeof startedAt !== "string" || !/^[0-9]+$/.test(startedAt))) {
    return null;
  }
  if (typeof nonce !== "string" || nonce === "") return null;
  return { epoch, pid, host, startedAt, nonce };
}

/** The `meta.json` in `dir`, or `null` when it is missing or malformed; other read errors throw. */
async function readMeta(dir: string): Promise<OwnerMeta | null> {
  let text: string;
  try {
    text = await readFile(join(dir, META_FILE), "utf8");
  } catch (error) {
    if (errorCode(error) === "ENOENT") return null;
    throw error;
  }
  try {
    return asOwnerMeta(JSON.parse(text));
  } catch {
    return null;
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch (error) {
    if (errorCode(error) === "ENOENT") return false;
    throw error;
  }
}

/** Whether the highest epoch `epoch` is free for the next acquisition. Fails closed (`false`). */
async function isFree(
  ownerDir: string,
  epoch: number,
  self: HolderIdentity,
  liveness: Liveness,
): Promise<boolean> {
  const dir = join(ownerDir, String(epoch));
  if (await exists(join(dir, RELEASED_FILE))) return true;
  const meta = await readMeta(dir);
  if (meta === null || meta.epoch !== epoch) return false;
  if (meta.host !== self.host || meta.startedAt === null) return false;
  const current = liveness.startTimeOf(meta.pid);
  if (current === "unsupported") return false;
  // No live process under the pid, or another process reusing it: the holder is dead.
  return current === null || current !== meta.startedAt;
}

/** Create `path` (it must not exist), write `text`, and sync it before closing. */
async function writeSynced(path: string, text: string): Promise<void> {
  const handle = await open(path, "wx");
  try {
    await handle.writeFile(text, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
}

/** Mark `owner/<epoch>` released, after checking the epoch still names this acquisition. */
async function writeReleased(ownerDir: string, epoch: number, nonce: string): Promise<void> {
  const dir = join(ownerDir, String(epoch));
  const meta = await readMeta(dir);
  if (meta === null || meta.nonce !== nonce) {
    throw new Error(`owner epoch ${epoch} is not this acquisition's (its nonce differs)`);
  }
  const tmp = join(dir, `.released.${nonce}.tmp`);
  await writeSynced(tmp, JSON.stringify({ epoch, nonce }));
  await rename(tmp, join(dir, RELEASED_FILE));
}

/**
 * Acquire `<storeDir>/owner/<n+1>`, or report the live holder's epoch as `owner_busy`. After
 * `ACQUIRE_ROUNDS` lost renames, `owner_busy` names the epoch whose creation was lost last.
 */
export async function acquireOwnerLock(
  storeDir: string,
  options: OwnerLockOptions = {},
): Promise<OwnerLockResult> {
  const liveness = options.liveness ?? procfsLiveness();
  const self = options.self ?? selfIdentity(liveness);
  const ownerDir = join(storeDir, OWNER_DIR);
  await mkdir(ownerDir, { recursive: true });
  let lost = 0;
  for (let round = 0; round < ACQUIRE_ROUNDS; round++) {
    const highest = await highestEpoch(ownerDir);
    if (highest > 0 && !(await isFree(ownerDir, highest, self, liveness))) {
      return { kind: "owner_busy", epoch: highest };
    }
    const epoch = highest + 1;
    const nonce = randomUUID();
    const tmp = join(ownerDir, `.tmp.${nonce}`);
    await mkdir(tmp);
    const meta: OwnerMeta = {
      epoch,
      pid: self.pid,
      host: self.host,
      startedAt: self.startedAt,
      nonce,
    };
    try {
      await writeSynced(join(tmp, META_FILE), JSON.stringify(meta));
      await options.hooks?.beforeRename?.(epoch);
    } catch (error) {
      await rm(tmp, { recursive: true, force: true });
      throw error;
    }
    try {
      await rename(tmp, join(ownerDir, String(epoch)));
    } catch (error) {
      await rm(tmp, { recursive: true, force: true });
      const code = errorCode(error);
      if (code === "ENOTEMPTY" || code === "EEXIST") {
        lost = epoch;
        continue;
      }
      throw error;
    }
    let released: Promise<void> | undefined;
    return {
      kind: "acquired",
      epoch,
      release: () => {
        released ??= writeReleased(ownerDir, epoch, nonce);
        return released;
      },
    };
  }
  return { kind: "owner_busy", epoch: lost };
}
