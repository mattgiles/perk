// The host proofs' shared fixture (dev-only): host programs over the fake assignment (and a
// sleeping variant), host options over temp store directories, observation seams, phase counting,
// a call-recording Harness proxy, a binding-level started-store seed, owner-lock oracles and fake
// liveness, outcome narrowing, and the real child process the SIGKILL proof kills.
//
// Invariants the proofs rely on:
//   - Every host program's work is the binding fixture's: the fake assignment accepts
//     `fakeReport(subject)` through `operateInTx`, so host runs and binding-level seeds converge.
//   - `hostOptions` pins the workspace and the manifest clock to `testing/binding.ts::manifest()`,
//     so a host `start` writes exactly that manifest.
//   - `seedStartedStore` and the oracles bypass the lock: they model what earlier processes left.
//   - Identities used with fake liveness carry pids above 4_000_000, which no real process has.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, writeFileSync } from "node:fs";
import { mkdir, readdir, readFile } from "node:fs/promises";
import { hostname } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { TestContext } from "node:test";
import type { Context } from "@earendil-works/chord";
import {
  type AnyTask,
  defineExtension,
  defineTask,
  Harness,
  type HarnessOptions,
  type Task,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { type BindingDeps, operate, operateInTx } from "../durable/operate.ts";
import {
  type HostMismatch,
  type HostOptions,
  type HostProgram,
  type HostRunOutcome,
  type HostStatusOutcome,
  type Observe,
  type OpenHarness,
  STORE_DATABASE,
} from "../host.ts";
import type { FixturePolicy } from "../kernel/fixture.ts";
import type { ExecutionManifest } from "../kernel/records.ts";
import type { RefusalReason } from "../kernel/refusal.ts";
import type { HolderIdentity, Liveness } from "../store/liveness.ts";
import {
  asOwnerMeta,
  META_FILE,
  OWNER_DIR,
  type OwnerMeta,
  RELEASED_FILE,
} from "../store/ownerLock.ts";
import {
  attemptIdOf,
  C1,
  defineFakeAssignment,
  E,
  expectApplied,
  type FakeHooks,
  type FakeInput,
  facts,
  fakeLauncher,
  fakeReport,
  installBinding,
  manifest,
  openBinding,
  policyA,
  REPO,
  type Role,
  T1,
  T2,
} from "./binding.ts";
import { completed, defer, fauxSetup, tempDir } from "./durable.ts";

/** The manifest clock `hostOptions` pins (`manifest().createdAt`). */
export const HOST_NOW = 1_700_000_000_000;

// ── programs ────────────────────────────────────────────────────────────────────────────────────

/**
 * A host program over the fake assignment: `policyA`, policy version 1, accepting, no hooks, its
 * task registered by the extension `perk.v2.fake` (plus any `extraTasks`).
 */
export function fakeProgram(
  options: {
    readonly policy?: FixturePolicy;
    readonly policyVersion?: number;
    readonly accept?: boolean;
    readonly hooks?: FakeHooks;
    readonly extensionName?: string;
    readonly extraTasks?: readonly AnyTask[];
  } = {},
): HostProgram {
  return {
    policy: options.policy ?? policyA,
    policyVersion: options.policyVersion ?? 1,
    assignment: (context) => {
      const fake = defineFakeAssignment(context.deps, {
        accept: options.accept ?? true,
        ...(options.hooks === undefined ? {} : { hooks: options.hooks }),
      });
      return {
        launcher: fakeLauncher(fake),
        extension: defineExtension({
          name: options.extensionName ?? "perk.v2.fake",
          tasks: [fake, ...(options.extraTasks ?? [])],
        }),
      };
    },
  };
}

export const SLEEPY_ASSIGNMENT_NAME = "perk.v2.sleepy-assignment";

type SleepyState = { phase: "sleep" } | { phase: "run" };

export type SleepyAssignment = Task<FakeInput, SleepyState, null, object>;

/**
 * The fake assignment with a sleep first: its `sleep` phase sleeps until `until` on the Harness
 * clock, then its `run` phase makes the fake's one accepting commit and completes.
 */
export function defineSleepyAssignment(deps: () => BindingDeps, until: number): SleepyAssignment {
  return defineTask<FakeInput, SleepyState, null>({
    name: SLEEPY_ASSIGNMENT_NAME,
    version: 1,
    initial: () => ({ phase: "sleep" }),
    phases: {
      sleep: async (_task, runtime, phaseContext) => {
        await runtime.sleepUntil(until, { phase: "run" }, phaseContext);
      },
      run: async (task, runtime, phaseContext) => {
        await runtime.commit(async (tx) => {
          const { attemptId, subjectDigest, verifiedDigest } = task.input;
          await operateInTx(
            tx,
            { type: "accept-report", attemptId, report: fakeReport(subjectDigest), verifiedDigest },
            deps(),
            runtime.conversationId,
          );
          return completed(null);
        }, phaseContext);
      },
    },
    abort: async (_task, runtime, phaseContext) => {
      await runtime.commit(
        () => ({ status: "terminal", outcome: { status: "aborted" } }),
        phaseContext,
      );
    },
  });
}

/** A host program whose attempts sleep until `until` before accepting (extension `perk.v2.sleepy`). */
export function sleepyProgram(until: number): HostProgram {
  return {
    policy: policyA,
    policyVersion: 1,
    assignment: (context) => {
      const sleepy = defineSleepyAssignment(context.deps, until);
      return {
        launcher: (tx, launch) =>
          tx.createTask(
            sleepy,
            {
              attemptId: launch.attempt.attemptId,
              subjectDigest: launch.assignment.subject.digest,
              verifiedDigest: launch.latest.manifestDigest,
            },
            {
              ownership: { kind: "conversation" },
              conversationId: launch.executionConversationId,
              background: true,
            },
          ),
        extension: defineExtension({ name: "perk.v2.sleepy", tasks: [sleepy] }),
      };
    },
  };
}

// ── options and observation ─────────────────────────────────────────────────────────────────────

/** Host options over `storeDir`: workspace `{REPO, E}` and the manifest clock `HOST_NOW`. */
export function hostOptions(
  storeDir: string,
  program: HostProgram = fakeProgram(),
  overrides: Partial<Omit<HostOptions, "storeDir" | "program">> = {},
): HostOptions {
  return {
    storeDir,
    workspace: { repoIdentity: REPO, executionId: E },
    program,
    now: () => HOST_NOW,
    ...overrides,
  };
}

/** A not-yet-existing `store` path inside a fresh temp directory. */
export async function storeIn(t: TestContext): Promise<string> {
  return join(await tempDir(t, "perk-v2-host-"), "store");
}

export function observed(tree = T1, commit = C1): Observe {
  return () => Promise.resolve({ kind: "observed", facts: facts(tree, commit) });
}

export function failedObservation(detail: string): Observe {
  return () => Promise.resolve({ kind: "observation_failed", detail });
}

/** `inner`, counting its calls. */
export function spyObserve(inner: Observe): { observe: Observe; calls(): number } {
  let calls = 0;
  return {
    observe: () => {
      calls++;
      return inner();
    },
    calls: () => calls,
  };
}

// ── phases ──────────────────────────────────────────────────────────────────────────────────────

/** The fixture role an attempt id belongs to (attempt 1 over `T1` or `T2`). */
export function roleOf(attemptId: string): Role {
  for (const role of ["a", "b"] as const) {
    for (const tree of [T1, T2]) if (attemptIdOf(role, tree) === attemptId) return role;
  }
  assert.fail(`no fixture role has attempt ${attemptId}`);
}

/** Hooks recording the role of every fake phase that started, and their count. */
export function phaseLog(): { hooks: FakeHooks; count(role?: Role): number } {
  const roles: Role[] = [];
  return {
    hooks: {
      before: (input) => {
        roles.push(roleOf(input.attemptId));
      },
    },
    count: (role) => (role === undefined ? roles.length : roles.filter((r) => r === role).length),
  };
}

/**
 * Hooks appending `"<role> <pid>\n"` to `path` as each fake phase starts — a phase log shared across
 * processes. A phase of role `block` then reports `<role>-blocked` and never settles; every
 * accepted phase reports `<role>-accepted`.
 */
export function filePhaseHooks(
  path: string,
  options: { readonly block?: Role | null; readonly say?: (line: string) => void } = {},
): FakeHooks {
  return {
    before: async (input) => {
      const role = roleOf(input.attemptId);
      appendFileSync(path, `${role} ${process.pid}\n`);
      if (role === options.block) {
        options.say?.(`${role}-blocked`);
        await new Promise<never>(() => {});
      }
    },
    after: (input) => {
      options.say?.(`${roleOf(input.attemptId)}-accepted`);
    },
  };
}

// ── the recording Harness ───────────────────────────────────────────────────────────────────────

/** Every Harness call a status open must never make. */
export const FORBIDDEN_STATUS_CALLS = [
  "commit",
  "resume",
  "root",
  "createConversation",
  "retryTask",
  "abortTask",
  "abortSubmission",
  "waitForTask",
  "waitForIdle",
] as const;

/**
 * An `openHarness` seam calling `Harness.open` with the host's options merged with
 * `options.harness` (the Harness clock and timers), and returning a proxy that records the name of
 * every method called through it. Each method is bound to the real Harness (it uses private
 * fields). Before forwarding the n-th `inspect`, it awaits `onInspect(n, realHarness)`.
 */
export function harnessSpy(
  options: {
    readonly harness?: Partial<Pick<HarnessOptions, "now" | "setTimer">>;
    onInspect?(call: number, harness: Harness): void | Promise<void>;
  } = {},
): { openHarness: OpenHarness; calls(): readonly string[] } {
  const calls: string[] = [];
  let inspects = 0;
  const openHarness: OpenHarness = async (storage, harnessOptions, openContext) => {
    const harness = await Harness.open(
      storage,
      { ...harnessOptions, ...options.harness },
      openContext,
    );
    return new Proxy(harness, {
      get(target, property) {
        const value: unknown = Reflect.get(target, property, target);
        if (typeof value !== "function") return value;
        const name = String(property);
        if (name === "inspect") {
          return async (inspectContext: Context) => {
            calls.push(name);
            inspects++;
            await options.onInspect?.(inspects, target);
            return target.inspect(inspectContext);
          };
        }
        return (...args: unknown[]) => {
          calls.push(name);
          return Reflect.apply(value, target, args);
        };
      },
    });
  };
  return { openHarness, calls: () => [...calls] };
}

// ── stores ──────────────────────────────────────────────────────────────────────────────────────

/**
 * A started store, binding-level and bypassing the lock: `start` (`seeded` as its manifest, the
 * observation `facts(T1, C1)`) committed over `<storeDir>/durable.sqlite`, then closed without
 * resuming — two pending fake tasks remain.
 */
export async function seedStartedStore(
  t: TestContext,
  storeDir: string,
  seeded: ExecutionManifest = manifest(),
): Promise<void> {
  await mkdir(storeDir, { recursive: true });
  const setup = fauxSetup();
  const installed = installBinding(setup, { policy: policyA, accept: true });
  const { opened, target } = await openBinding(
    t,
    await openNodeSqliteStorage(join(storeDir, STORE_DATABASE)),
    setup,
    installed,
  );
  expectApplied(
    await operate(target, { type: "start", manifest: seeded, observation: facts(T1, C1) }),
  );
  await opened.dispose();
}

export type OwnerEpoch = {
  readonly epoch: number;
  readonly released: boolean;
  readonly meta: OwnerMeta;
};

/** Every epoch directory under `<storeDir>/owner/`, numerically. */
export async function ownerEpochs(storeDir: string): Promise<OwnerEpoch[]> {
  const dir = join(storeDir, OWNER_DIR);
  const epochs: OwnerEpoch[] = [];
  for (const name of await readdir(dir)) {
    if (!/^[1-9][0-9]*$/.test(name)) continue;
    const meta = asOwnerMeta(JSON.parse(await readFile(join(dir, name, META_FILE), "utf8")));
    assert.ok(meta !== null, `owner/${name}/${META_FILE} is complete`);
    epochs.push({
      epoch: Number(name),
      released: existsSync(join(dir, name, RELEASED_FILE)),
      meta,
    });
  }
  return epochs.sort((a, b) => a.epoch - b.epoch);
}

/** The raw entry names of `<storeDir>/owner/`, sorted. */
export async function ownerEntries(storeDir: string): Promise<string[]> {
  return (await readdir(join(storeDir, OWNER_DIR))).sort();
}

// ── liveness ────────────────────────────────────────────────────────────────────────────────────

/** Liveness answering from `map` by pid, and `unknown` for every other pid. */
export function fakeLiveness(
  map: Readonly<Record<number, string | null>>,
  unknown: null | "unsupported" = null,
): Liveness {
  return {
    startTimeOf: (pid) => {
      const known = map[pid];
      return known === undefined ? unknown : known;
    },
  };
}

export const THIS_HOST = hostname();
/** An identity whose process is gone (absent from every fake liveness map). */
export const GHOST: HolderIdentity = { pid: 4_000_001, host: THIS_HOST, startedAt: "1001" };
export const LIVE_A: HolderIdentity = { pid: 4_000_002, host: THIS_HOST, startedAt: "1002" };
export const LIVE_B: HolderIdentity = { pid: 4_000_003, host: THIS_HOST, startedAt: "1003" };
/** Liveness under which `LIVE_A` and `LIVE_B` are live and every other pid (`GHOST`) is gone. */
export function liveAB(): Liveness {
  return fakeLiveness({ [LIVE_A.pid]: LIVE_A.startedAt, [LIVE_B.pid]: LIVE_B.startedAt });
}

// ── outcome narrowing ───────────────────────────────────────────────────────────────────────────

function shown(outcome: HostRunOutcome | HostStatusOutcome): string {
  switch (outcome.kind) {
    case "uncertain":
      return `uncertain at ${outcome.epoch}: ${String(outcome.error)}`;
    case "quiescent":
    case "status":
      return `${outcome.kind} at ${outcome.epoch} (${String(outcome.view.waitReason)})`;
    default:
      return JSON.stringify(outcome);
  }
}

export function expectQuiescent(
  outcome: HostRunOutcome,
): Extract<HostRunOutcome, { kind: "quiescent" }> {
  if (outcome.kind !== "quiescent") assert.fail(`expected quiescent: ${shown(outcome)}`);
  return outcome;
}

export function expectStatus(
  outcome: HostStatusOutcome,
): Extract<HostStatusOutcome, { kind: "status" }> {
  if (outcome.kind !== "status") assert.fail(`expected status: ${shown(outcome)}`);
  return outcome;
}

export function expectIncompatible(
  outcome: HostRunOutcome | HostStatusOutcome,
  field: HostMismatch["field"],
): Extract<HostRunOutcome, { kind: "incompatible" }> {
  if (outcome.kind !== "incompatible")
    assert.fail(`expected incompatible ${field}: ${shown(outcome)}`);
  assert.equal(outcome.mismatch.field, field, shown(outcome));
  return outcome;
}

/** Assert a `refused` run outcome with `reason`; its detail. */
export function expectHostRefused(outcome: HostRunOutcome, reason: RefusalReason): string {
  if (outcome.kind !== "refused") assert.fail(`expected refused ${reason}: ${shown(outcome)}`);
  assert.equal(outcome.refusal.reason, reason, outcome.refusal.detail);
  return outcome.refusal.detail;
}

/** Assert an `observation_failed` run outcome; its detail. */
export function expectObservationFailed(outcome: HostRunOutcome): string {
  if (outcome.kind !== "observation_failed") {
    assert.fail(`expected observation_failed: ${shown(outcome)}`);
  }
  return outcome.detail;
}

// ── the host child ──────────────────────────────────────────────────────────────────────────────

/** What `hostChild.ts` reads from its config file. */
export type HostChildConfig = {
  readonly storeDir: string;
  /** The shared phase log (`filePhaseHooks`). */
  readonly phaseLog: string;
  /** The role whose phase blocks forever, or none. */
  readonly blockRole: Role | null;
};

export type HostChildExit = {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
};

export type HostChild = {
  readonly pid: number;
  /** The first stdout line equal to `name` or starting with `name + " "`; rejects after the bound or on exit. */
  line(name: string, timeoutMs?: number): Promise<string>;
  /** SIGKILL the child and await its exit. */
  kill(): Promise<HostChildExit>;
  readonly exited: Promise<HostChildExit>;
};

/** The child entry, beside this file. */
export const HOST_CHILD_PATH = resolve(import.meta.dirname, "hostChild.ts");

const LINE_TIMEOUT_MS = 10_000;

/**
 * Spawn `node hostChild.ts <config.json>` (the config written beside the store directory); its
 * stdout lines are collected, and it is SIGKILLed at teardown.
 */
export function startHostChild(t: TestContext, config: HostChildConfig): HostChild {
  const configPath = join(dirname(config.storeDir), "host-child.json");
  writeFileSync(configPath, JSON.stringify(config));
  const child = spawn(process.execPath, [HOST_CHILD_PATH, configPath], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  const pid = child.pid;
  if (pid === undefined) throw new Error("the host child did not spawn");
  const lines: string[] = [];
  const waiters = new Set<() => void>();
  let stdout = "";
  let stderr = "";
  let exit: HostChildExit | undefined;
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    stdout += chunk;
    lines.splice(0, lines.length, ...stdout.split("\n").slice(0, -1));
    for (const wake of waiters) wake();
  });
  child.stderr?.setEncoding("utf8");
  child.stderr?.on("data", (chunk: string) => {
    stderr += chunk;
  });
  const exited = new Promise<HostChildExit>((resolveExit) => {
    child.once("exit", (code, signal) => {
      exit = { code, signal };
      resolveExit(exit);
      for (const wake of waiters) wake();
    });
  });
  defer(t, async () => {
    if (exit !== undefined) return;
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // Already gone.
    }
    await exited;
  });
  const describe = (): string =>
    `stdout=${JSON.stringify(stdout)} exit=${JSON.stringify(exit)} stderr=${JSON.stringify(stderr)}`;
  const line = (name: string, timeoutMs = LINE_TIMEOUT_MS): Promise<string> =>
    new Promise((resolveLine, reject) => {
      const check = (): boolean => {
        const found = lines.find((l) => l === name || l.startsWith(`${name} `));
        if (found !== undefined) {
          resolveLine(found);
          return true;
        }
        if (exit !== undefined) {
          reject(new Error(`the host child exited before "${name}": ${describe()}`));
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
    line,
    kill: () => {
      process.kill(pid, "SIGKILL");
      return exited;
    },
    exited,
  };
}
