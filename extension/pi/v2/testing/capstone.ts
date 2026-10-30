// The capstone's door driver (dev-only; docs/design/pi-durable-v2-foundations.md §16): it drives the
// real `perk v2` door — `uv run --no-sync perk v2 …` → the Python door → `node door/main.ts` — over
// temp git subjects, every call through its own test gate (`door/testGate.ts`), and reads the
// stores the door leaves under the main checkout's `.perk/executions/`.
//
// Invariants the capstone relies on:
//   - Every door call has its own gate, and its host announces its identity (pid and procfs start
//     time) in that gate's log before touching the store.
//   - There is one idempotent `close()` per case, registered through `defer`.
//   - `close()` proves every announced host dead before deleting anything, and on any doubt throws
//     and deletes nothing: the files stay for diagnosis, never removed while a host might live.
//     Host death follows from the door's exit — `uv` exited ⇒ Python returned from
//     `subprocess.run` ⇒ the host was reaped — and, on procfs hosts, `waitGone` over the announced
//     identities is a second, independent check. Process groups are not used.
//   - `close()` signals a host only by its procfs identity. A host whose identity it cannot verify
//     is never signalled by its bare pid, which may already name another process once Python
//     reaped the host: its gate's holds are released instead, so it runs to its end.
//   - Execution ids are learned from door output (an envelope's `executionId`, a post-invocation
//     failure's `execution_id`) or the owner scan (`executionOfOwner`).
//   - Subjects are changed with plain git only (`fixtureGit`).

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { rm } from "node:fs/promises";
import { hostname, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { TestContext } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import { AssistantEntry } from "@earendil-works/pi-durable";
import type { Envelope } from "../door/envelope.ts";
import type { ViewSnapshot } from "../door/snapshot.ts";
import { GATE_LOG, TEST_GATE_ENV } from "../door/testGate.ts";
import type { VerifyPoint } from "../durable/assignment.ts";
import { fixtureWorkerModels } from "../durable/fauxWorker.ts";
import type { HostOptions } from "../host.ts";
import { isExecutionId } from "../kernel/identity.ts";
import { fixtureProgram } from "../program.ts";
import { asOwnerMeta, META_FILE, OWNER_DIR } from "../store/ownerLock.ts";
import { discardTree } from "../subject/snapshot.ts";
import {
  type Identity,
  isDead,
  killIdentity,
  procAvailable,
  waitGone,
} from "./containment/procfs.ts";
import { defer } from "./durable.ts";
import { hostOptions } from "./host.ts";
import { commitAll, fixtureGit, treeOf, writeFiles } from "./subject.ts";
import { SUBJECT_FILES, withStore } from "./worker.ts";

/** This checkout's root: `extension/pi/v2/testing/` is four levels below it. */
export const PERK_ROOT = resolve(import.meta.dirname, "..", "..", "..", "..");

/** How long `close()` waits, in total, for every still-running door to exit. */
export const TEARDOWN_MS = 30_000;

/** How long `door()` waits for one door call to exit. */
export const DOOR_TIMEOUT_MS = 120_000;

const GONE_MS = 5_000;
const GATE_POLL_MS = 25;
const KILL_POLL_MS = 25;
const STDERR_TAIL_LINES = 20;

function gitCommonDir(): string {
  return fixtureGit(PERK_ROOT, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    .toString("utf8")
    .replace(/\n$/, "");
}

/** The main checkout's root (the parent of the shared git dir), even from a linked worktree. */
export function mainCheckout(): string {
  return realpathSync(dirname(gitCommonDir()));
}

/** Where the door puts every execution store. */
export function executionsDir(): string {
  return join(mainCheckout(), ".perk", "executions");
}

/** The workspace identity the door passes the host: the canonical shared git dir. */
export function perkRepoIdentity(): string {
  return realpathSync(gitCommonDir());
}

// ── gates ───────────────────────────────────────────────────────────────────────────────────────

export type GateHost = { readonly pid: number; readonly startTime: string | null };

export type GateVerify = {
  readonly point: VerifyPoint;
  readonly pid: number;
  readonly tree: string;
};

export type GateLog = { readonly hosts: GateHost[]; readonly verifies: GateVerify[] };

const VERIFY_POINTS: readonly string[] = ["attempt-start", "acceptance", "settle"];

function isVerifyPoint(value: string): value is VerifyPoint {
  return VERIFY_POINTS.includes(value);
}

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

function gateText(dir: string): string {
  try {
    return readFileSync(join(dir, GATE_LOG), "utf8");
  } catch (error) {
    if (errorCode(error) === "ENOENT") return "";
    throw error;
  }
}

/** Parse a gate's `verify.log`; a line still being written (no trailing LF) is not read yet. */
export function readGate(dir: string): GateLog {
  const hosts: GateHost[] = [];
  const verifies: GateVerify[] = [];
  for (const line of gateText(dir).split("\n").slice(0, -1)) {
    const [kind = "", pid = "", value = ""] = line.split(" ");
    if (!/^[1-9][0-9]*$/.test(pid) || value === "") {
      throw new Error(`unreadable gate line in ${dir}: ${JSON.stringify(line)}`);
    }
    if (kind === "host") {
      hosts.push({ pid: Number(pid), startTime: value === "-" ? null : value });
    } else if (isVerifyPoint(kind)) {
      verifies.push({ point: kind, pid: Number(pid), tree: value });
    } else {
      throw new Error(`unreadable gate line in ${dir}: ${JSON.stringify(line)}`);
    }
  }
  return { hosts, verifies };
}

/** The number of verify lines at `point`. */
export function countAt(log: GateLog, point: VerifyPoint): number {
  return log.verifies.filter((verify) => verify.point === point).length;
}

/** Verify lines per point, every point present. */
export function perPoint(log: GateLog): Record<VerifyPoint, number> {
  return {
    "attempt-start": countAt(log, "attempt-start"),
    acceptance: countAt(log, "acceptance"),
    settle: countAt(log, "settle"),
  };
}

// ── door calls ──────────────────────────────────────────────────────────────────────────────────

export type JsonObject = { readonly [key: string]: unknown };

export type DoorResult = {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stdout: string;
  readonly stderr: string;
  /** The single stdout JSON object when stdout is exactly one JSON line, else `null`. */
  readonly json: JsonObject | null;
  readonly wallMs: number;
};

export type DoorHandle = {
  readonly label: string;
  readonly gate: string;
  /** Resolves once the door exited and its output closed; never rejects. */
  readonly exited: Promise<DoorResult>;
  /** The door's stderr so far. */
  stderrSoFar(): string;
  /** The door's result once it exited, else `undefined`. */
  result(): DoorResult | undefined;
};

export type DoorTiming = { readonly label: string; readonly wallMs: number };

export type CapstoneSubject = {
  readonly repo: string;
  readonly commit: string;
  readonly tree: string;
};

export type CapstoneRun = {
  /** The run's own temp root: every subject and gate lives under it. */
  readonly root: string;
  /** A fresh repo (branch `main`) under the root with `files` committed as `c1`. */
  subject(files?: Readonly<Record<string, string>>): CapstoneSubject;
  /** Spawn `perk v2 <args>` through a fresh gate holding `holds`; the run owns its teardown. */
  spawnDoor(
    label: string,
    args: readonly string[],
    options?: { readonly holds?: readonly string[] },
  ): DoorHandle;
  /** `spawnDoor`, awaited up to `DOOR_TIMEOUT_MS`; a timeout rejects and kills nothing. */
  door(
    label: string,
    args: readonly string[],
    options?: { readonly holds?: readonly string[] },
  ): Promise<DoorResult & { readonly gate: string }>;
  /** Record an execution's store for teardown (idempotent). */
  learn(executionId: string): void;
  /** Every finished door call's wall time, in exit order. */
  timings(): readonly DoorTiming[];
  /** Prove every announced host dead, then discard every learned store and the root. Idempotent. */
  close(): Promise<{ readonly discarded: string[] }>;
};

function doorEnv(gate: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith("GIT_")) env[key] = value;
  }
  return { ...env, [TEST_GATE_ENV]: gate };
}

function singleJson(stdout: string): JsonObject | null {
  const lines = stdout.split("\n");
  if (lines.length !== 2 || lines[1] !== "") return null;
  try {
    const value: unknown = JSON.parse(lines[0] ?? "");
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as JsonObject)
      : null;
  } catch {
    return null;
  }
}

function executionIdOf(json: JsonObject | null): string | null {
  const id = json?.executionId ?? json?.execution_id;
  return typeof id === "string" && isExecutionId(id) ? id : null;
}

function tail(text: string): string {
  return text.trim().split("\n").slice(-STDERR_TAIL_LINES).join("\n");
}

function identityKey(host: GateHost): string {
  return `${host.pid} ${host.startTime ?? "-"}`;
}

/** An announced host's identity, when procfs can re-check it before a signal; else `null`. */
function verifiableIdentity(host: GateHost): Identity | null {
  return host.startTime !== null && procAvailable()
    ? { pid: host.pid, startTime: host.startTime }
    : null;
}

/** Remove every hold file of a gate: its held host then runs to its end, so its door exits. */
function releaseHolds(gate: string): void {
  for (const name of readdirSync(gate)) {
    if (name.startsWith("hold-")) rmSync(join(gate, name), { force: true });
  }
}

/** A capstone run over its own temp root; `close()` runs after the test. */
export function capstone(t: TestContext): CapstoneRun {
  const root = mkdtempSync(join(tmpdir(), "perk-v2-capstone-"));
  const handles: DoorHandle[] = [];
  const stores = new Set<string>();
  const timings: DoorTiming[] = [];
  let made = 0;
  let closing: Promise<{ readonly discarded: string[] }> | undefined;

  const learn = (executionId: string): void => {
    if (!isExecutionId(executionId)) {
      throw new Error(`${JSON.stringify(executionId)} is not an execution id`);
    }
    stores.add(join(executionsDir(), executionId));
  };

  const fresh = (kind: string): string => {
    made++;
    const dir = join(root, `${kind}-${made}`);
    mkdirSync(dir);
    return dir;
  };

  const subject = (files: Readonly<Record<string, string>> = SUBJECT_FILES): CapstoneSubject => {
    const repo = fresh("subject");
    fixtureGit(repo, ["init", "-q", "--initial-branch=main", repo]);
    writeFiles(repo, files);
    const commit = commitAll(repo, "c1");
    return { repo, commit, tree: treeOf(repo, commit) };
  };

  const spawnDoor: CapstoneRun["spawnDoor"] = (label, args, options = {}) => {
    if (closing !== undefined) throw new Error(`the capstone run is closed: ${label}`);
    const gate = fresh(`gate-${label}`);
    for (const hold of options.holds ?? []) writeFileSync(join(gate, hold), "");
    const started = performance.now();
    const child = spawn("uv", ["run", "--no-sync", "perk", "v2", ...args], {
      cwd: PERK_ROOT,
      env: doorEnv(gate),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let result: DoorResult | undefined;
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", (error) => {
      stderr += `\nthe door did not spawn: ${error.message}\n`;
    });
    const exited = new Promise<DoorResult>((resolveExit) => {
      child.once("close", (code, signal) => {
        const json = singleJson(stdout);
        const wallMs = Math.round(performance.now() - started);
        result = { code, signal, stdout, stderr, json, wallMs };
        const executionId = executionIdOf(json);
        if (executionId !== null) learn(executionId);
        timings.push({ label, wallMs });
        resolveExit(result);
      });
    });
    const handle: DoorHandle = {
      label,
      gate,
      exited,
      stderrSoFar: () => stderr,
      result: () => result,
    };
    handles.push(handle);
    return handle;
  };

  const door: CapstoneRun["door"] = async (label, args, options) => {
    const handle = spawnDoor(label, args, options);
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        reject(
          new Error(
            `door ${label} did not exit within ${DOOR_TIMEOUT_MS} ms; stderr so far:\n${tail(handle.stderrSoFar())}`,
          ),
        );
      }, DOOR_TIMEOUT_MS);
    });
    try {
      const result = await Promise.race([handle.exited, timeout]);
      return { ...result, gate: handle.gate };
    } finally {
      clearTimeout(timer);
    }
  };

  const closeOnce = async (): Promise<{ readonly discarded: string[] }> => {
    const pending = handles.filter((handle) => handle.result() === undefined);
    const running = (): DoorHandle[] => pending.filter((handle) => handle.result() === undefined);
    // End every still-running door — including one whose host announces late — until each exited
    // or the bound passed: a host procfs can identify is SIGKILLed by identity, once; any other
    // has its gate's holds released, so it runs to its end and its door exits on its own.
    const signalled = new Set<string>();
    const deadline = Date.now() + TEARDOWN_MS;
    while (running().length > 0 && Date.now() < deadline) {
      for (const handle of running()) {
        for (const host of readGate(handle.gate).hosts) {
          const identity = verifiableIdentity(host);
          if (identity === null) {
            // A bare pid is no identity: never signal it, end the host by releasing its holds.
            releaseHolds(handle.gate);
            continue;
          }
          const key = identityKey(host);
          if (signalled.has(key)) continue;
          signalled.add(key);
          killIdentity(identity);
        }
      }
      await sleep(KILL_POLL_MS);
    }
    const survivors = running();
    const announced: Identity[] = handles.flatMap((handle) =>
      readGate(handle.gate).hosts.flatMap((host) =>
        host.startTime === null ? [] : [{ pid: host.pid, startTime: host.startTime }],
      ),
    );
    const gone = !procAvailable() || (await waitGone(announced, GONE_MS));
    if (survivors.length > 0 || !gone) {
      const doors = survivors.map(
        (handle) =>
          `door ${handle.label} (gate ${handle.gate}) is still running\n  gate log:\n${gateText(handle.gate)}\n  stderr tail:\n${tail(handle.stderrSoFar())}`,
      );
      const living = procAvailable()
        ? announced.filter((id) => !isDead(id)).map((id) => `${id.pid} ${id.startTime}`)
        : [];
      throw new Error(
        [
          `capstone teardown could not prove every host dead; nothing was discarded (root ${root})`,
          ...doors,
          `surviving identities: ${JSON.stringify(living)}`,
        ].join("\n"),
      );
    }
    const discarded: string[] = [];
    for (const store of stores) {
      if (!existsSync(store)) continue;
      await discardTree(store);
      discarded.push(store);
    }
    await rm(root, { recursive: true, force: true });
    return { discarded };
  };

  const run: CapstoneRun = {
    root,
    subject,
    spawnDoor,
    door,
    learn,
    timings: () => [...timings],
    close: () => {
      closing ??= closeOnce();
      return closing;
    },
  };
  defer(t, async () => {
    await run.close();
  });
  return run;
}

/**
 * Poll the handle's gate (25 ms) until `predicate` holds over it. Rejects with the gate log and the
 * door's stderr so far on timeout, or if the door exited first.
 */
export async function waitForGate(
  handle: DoorHandle,
  predicate: (log: GateLog) => boolean,
  options: { readonly timeoutMs?: number } = {},
): Promise<GateLog> {
  const deadline = Date.now() + (options.timeoutMs ?? 90_000);
  for (;;) {
    const log = readGate(handle.gate);
    if (predicate(log)) return log;
    const exited = handle.result();
    if (exited !== undefined || Date.now() >= deadline) {
      const why =
        exited === undefined
          ? "timed out"
          : `the door exited first (code ${exited.code}, signal ${exited.signal})`;
      throw new Error(
        `waiting on door ${handle.label}'s gate: ${why}\n  gate log:\n${gateText(handle.gate)}\n  stderr:\n${tail(handle.stderrSoFar())}`,
      );
    }
    await sleep(GATE_POLL_MS);
  }
}

// ── stores ──────────────────────────────────────────────────────────────────────────────────────

function epochOneMeta(executionDir: string): ReturnType<typeof asOwnerMeta> {
  try {
    return asOwnerMeta(
      JSON.parse(readFileSync(join(executionDir, OWNER_DIR, "1", META_FILE), "utf8")),
    );
  } catch {
    return null;
  }
}

/** The one execution whose epoch 1 is held by `pid` on this host; throws unless exactly one. */
export function executionOfOwner(pid: number): string {
  const dir = executionsDir();
  const names = existsSync(dir) ? readdirSync(dir).filter(isExecutionId).sort() : [];
  const matches = names.filter((name) => {
    const meta = epochOneMeta(join(dir, name));
    return meta !== null && meta.pid === pid && meta.host === hostname();
  });
  const [only] = matches;
  if (matches.length !== 1 || only === undefined) {
    throw new Error(
      `expected exactly one execution under ${dir} whose epoch 1 pid ${pid} holds; matches ${JSON.stringify(matches)} among ${JSON.stringify(names)}`,
    );
  }
  return only;
}

/** Host options over a door-made store, for in-process reads once the door calls are done. */
export function capstoneHostOptions(storeDir: string, executionId: string): HostOptions {
  return hostOptions(storeDir, fixtureProgram({ models: fixtureWorkerModels() }), {
    workspace: { repoIdentity: perkRepoIdentity(), executionId },
    now: Date.now,
  });
}

export type WorkerCensus = {
  readonly submissions: number;
  readonly assistantTurns: number;
  readonly reportResults: number;
};

/** Per worker conversation: its submissions, assistant turns and accepted report results. */
export function workerCensus(storeDir: string): Promise<WorkerCensus[]> {
  return withStore(storeDir, async (view) => {
    const census: WorkerCensus[] = [];
    for (const worker of await view.workers()) {
      const entries = await view.entries(worker.id);
      const results = await view.toolResults(worker.id);
      census.push({
        submissions: (await view.submissions(worker.id)).length,
        assistantTurns: entries.filter((entry) => AssistantEntry.is(entry)).length,
        reportResults: results.filter((result) => result.text.startsWith("accepted ")).length,
      });
    }
    return census;
  });
}

// ── envelopes and rows ──────────────────────────────────────────────────────────────────────────

/** The door's `--json` envelope; fails the test unless stdout was one envelope line. */
export function envelopeOf(result: DoorResult): Envelope {
  const json = result.json;
  if (json === null || json.envelope !== 1) {
    assert.fail(
      `expected one envelope line (exit ${result.code}): stdout ${JSON.stringify(result.stdout)}, stderr ${tail(result.stderr)}`,
    );
  }
  return json as unknown as Envelope;
}

export type DoorFailure = {
  readonly success: false;
  readonly error_type: string;
  readonly message: string;
  readonly execution_id?: string;
};

/** The door's `--json` failure; fails the test unless stdout was one failure line. */
export function failureOf(result: DoorResult): DoorFailure {
  const json = result.json;
  if (json === null || json.success !== false || typeof json.error_type !== "string") {
    assert.fail(
      `expected one failure line (exit ${result.code}): stdout ${JSON.stringify(result.stdout)}, stderr ${tail(result.stderr)}`,
    );
  }
  return json as unknown as DoorFailure;
}

/** The envelope's view snapshot; fails the test for a marker or no snapshot. */
export function viewOf(envelope: Envelope): ViewSnapshot {
  const status = envelope.status;
  if (status === null || !("diagnostics" in status)) {
    assert.fail(`expected a view snapshot: ${JSON.stringify(envelope)}`);
  }
  return status;
}

/** One evidence row: `perk-v2-capstone <proof> <name> <json>`. */
export function row(t: TestContext, proof: string, name: string, value: unknown): void {
  t.diagnostic(`perk-v2-capstone ${proof} ${name} ${JSON.stringify(value)}`);
}
