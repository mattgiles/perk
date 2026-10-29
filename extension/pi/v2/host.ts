// The v2 host entry and its lifecycle (docs/design/pi-durable-v2-foundations.md §10): the program
// composition, the store owner lock, the exact-match manifest gate, the run-to-quiescence driver
// and the read-only status open. With `durable/`, it is the only v2 production home that may import
// Durable, chord or pi-ai — `layeringGuard.test.ts` enforces that confinement. Its first bare
// import stays `@earendil-works/chord/context`: the bare-checkout load proof pins the failure there.
//
// A run, in order: compose the program (once per call) → the store-directory rule → lock → open
// storage and the Harness (never resumed) → gate → observe → the execution conversation → one
// `operate` (a reply's lookup, recording, checks, consumption and continuation all happen in it) →
// resume and wait for a consistent quiescent view → close → release.
//
// Invariants:
// - One composition per host call feeds the registry, the binding's dependencies, the gate's
//   expected manifest and `start`'s manifest, so the manifest's `definitions` and the installed
//   work correspond by construction (checked against the registry).
// - Nothing is opened before the lock, and only `start` creates the store directory.
// - The gate runs before any task phase: a refused or incompatible verb never observes, and no
//   verb resumes before its own commit has been applied.
// - A failed Harness is detected through `wake()`'s failure check, never a probe commit, so status
//   makes no commit call on any path.
// - The Harness closes before the lock is released, on every path; a refusal, a fault and an
//   `uncertain` outcome included. Only a killed process leaves an unreleased epoch.
// - The host never creates step tasks: `run`'s commit is itself a full reconcile pass.
// - A replayed reply still resumes: a continuation an earlier unacknowledged commit created runs
//   now, exactly once.

import { mkdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import type { Context } from "@earendil-works/chord";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { Models } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import {
  type AnyTask,
  createRegistry,
  type Extension,
  Harness,
  type HarnessInspection,
  type HarnessOptions,
  type Registry,
  type ReportInfo,
  SessionFailed,
  type Storage,
  type Wake,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { type AttemptEnding, readAttemptEndings } from "./durable/ending.ts";
import {
  type AttemptLauncher,
  type BindingDeps,
  type BindingReceipt,
  type CommitInput,
  operate,
} from "./durable/operate.ts";
import { type ReadRecordSet, readRecords } from "./durable/records.ts";
import { bindingDefinitions, bindingExtension } from "./durable/tasks.ts";
import { deriveWaitReason } from "./durable/waitReason.ts";
import { normalizeCapabilitySet } from "./kernel/capability.ts";
import { type ManifestMismatch, manifestMismatch } from "./kernel/compatibility.ts";
import { FIXTURE_EXECUTION_KIND, type FixturePolicy } from "./kernel/fixture.ts";
import { type ExecutionManifest, type ObservationFacts, RECORD_VERSION } from "./kernel/records.ts";
import type { Refusal } from "./kernel/refusal.ts";
import type { WaitReason } from "./kernel/waitReason.ts";
import { acquireOwnerLock, type OwnerLockOptions } from "./store/ownerLock.ts";

/** The Durable and chord versions the manifest records; pinned to the workspace manifest by test. */
export const DURABLE_VERSION = "1.4.0";
export const CHORD_VERSION = "1.4.0";
/** The store's SQLite file, under the store directory. */
export const STORE_DATABASE = "durable.sqlite";
/** How often the driver re-reads `wake()` while work is runnable (real time). */
export const QUIESCENCE_POLL_MS = 10;

const context: Context = BACKGROUND_CONTEXT;
const V2_PREFIX = "perk.v2.";

/** What the assignment factory may use: the binding's dependencies (a thunk) and the store. */
export type AssignmentContext = {
  /** The composed dependencies; a thunk, because the launcher is itself one of them. */
  readonly deps: () => BindingDeps;
  readonly storeDir: string;
};

/**
 * The assignment's work: its attempt launcher, the extension registering its tasks, and the model
 * catalog and environment factory its workers need (forwarded to the Harness).
 */
export type AssignmentWork = {
  readonly launcher: AttemptLauncher;
  readonly extension: Extension;
  /** Default `createModels()`, an empty catalog. */
  readonly models?: Models;
  /** Default none: every tool runs without an environment. */
  readonly env?: HarnessOptions["env"];
};

/** What the host executes: the host-resolved policy, its version, and the assignment's work. */
export type HostProgram = {
  readonly policy: FixturePolicy;
  readonly policyVersion: number;
  readonly assignment: (context: AssignmentContext) => AssignmentWork;
};

/**
 * One host call's composition: the dependencies, the registry, the manifest's definitions, and the
 * assignment's model catalog and environment factory.
 */
export type Composition = {
  readonly deps: BindingDeps;
  readonly registry: Registry;
  readonly definitions: Readonly<Record<string, number>>;
  readonly models?: Models;
  readonly env?: HarnessOptions["env"];
};

export type OpenHarness = (
  storage: Storage,
  options: HarnessOptions,
  context: Context,
) => Promise<Harness>;

export type HostOptions = {
  readonly storeDir: string;
  readonly workspace: { readonly repoIdentity: string; readonly executionId: string };
  readonly program: HostProgram;
  readonly lock?: OwnerLockOptions;
  /** Default `openNodeSqliteStorage`. */
  readonly openStorage?: (path: string) => Promise<Storage>;
  /** Default `Harness.open`; a test seam for the Harness clock and timers, or a recording proxy. */
  readonly openHarness?: OpenHarness;
  /** The wall clock for the manifest's `createdAt` only; default `Date.now`. */
  readonly now?: () => number;
  /** Forwarded to the Harness options. */
  readonly onReport?: (error: unknown, info: ReportInfo) => void;
};

export type Observation =
  | { readonly kind: "observed"; readonly facts: ObservationFacts }
  | { readonly kind: "observation_failed"; readonly detail: string };

/** The observing verb's pre-commit read (§8), injected by the caller. */
export type Observe = () => Promise<Observation>;

export type HostVerb =
  | { readonly type: "start"; readonly observe: Observe }
  | { readonly type: "run"; readonly observe: Observe }
  | {
      readonly type: "reply";
      readonly observe: Observe;
      readonly decisionId: string;
      readonly action: string;
      readonly actor: string;
    };

export type HostMismatch =
  | ManifestMismatch
  | { readonly field: "manifest_missing"; readonly expected: null; readonly found: null };

/** What a run or status saw: the records, the live diagnostics, the wake and the wait reason. */
export type HostView = {
  readonly records: ReadRecordSet;
  readonly inspection: HarnessInspection;
  readonly wake: Wake;
  /** The launched attempt tasks' typed endings, by attempt id (committed `getTask` reads). */
  readonly endings: ReadonlyMap<string, AttemptEnding>;
  /** `null` only in a status view while work is runnable (running). */
  readonly waitReason: WaitReason | null;
};

type OwnerBusy = { readonly kind: "owner_busy"; readonly epoch: number };
type Incompatible = {
  readonly kind: "incompatible";
  /** `null` when the call took no lock (a missing store directory). */
  readonly epoch: number | null;
  readonly mismatch: HostMismatch;
};
type Uncertain = { readonly kind: "uncertain"; readonly epoch: number; readonly error: unknown };
type Refused = { readonly kind: "refused"; readonly epoch: number; readonly refusal: Refusal };

export type HostRunOutcome =
  | {
      readonly kind: "quiescent";
      readonly epoch: number;
      /** The verb's own receipt: a reply's, applied or replayed; `null` for `start` and `run`. */
      readonly receipt: BindingReceipt | null;
      readonly view: HostView & { readonly waitReason: WaitReason };
    }
  | OwnerBusy
  | Incompatible
  | Refused
  | { readonly kind: "observation_failed"; readonly epoch: number; readonly detail: string }
  | Uncertain;

export type HostStatusOutcome =
  | { readonly kind: "status"; readonly epoch: number; readonly view: HostView }
  | OwnerBusy
  | Incompatible
  | Uncertain;

/** A consistent, inactive view with no derivable wait reason: a host or binding bug, never an outcome. */
export class HostFault extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HostFault";
  }
}

const MANIFEST_MISSING: HostMismatch = {
  field: "manifest_missing",
  expected: null,
  found: null,
};

function taskDefinitions(tasks: readonly AnyTask[]): Record<string, number> {
  const definitions: Record<string, number> = {};
  for (const task of tasks) definitions[task.definition.name] = task.definition.version;
  return definitions;
}

/**
 * Compose the program once: validate it, build its work, install the binding and the assignment
 * extension into a fresh registry, and prove the registry resolves every manifest-named task to
 * exactly the task object it came from. Every violation throws `RangeError`, before any lock or
 * file is touched.
 */
export function composeProgram(options: Pick<HostOptions, "storeDir" | "program">): Composition {
  const { program, storeDir } = options;
  normalizeCapabilitySet(program.policy.capabilitySet);
  if (!Number.isSafeInteger(program.policyVersion) || program.policyVersion < 1) {
    throw new RangeError(`policyVersion ${String(program.policyVersion)} is not an integer ≥ 1`);
  }
  const holder: { deps?: BindingDeps } = {};
  const work = program.assignment({
    deps: () => {
      if (holder.deps === undefined)
        throw new Error("the binding dependencies are not composed yet");
      return holder.deps;
    },
    storeDir,
  });
  const reserved = bindingDefinitions();
  const tasks = work.extension.tasks ?? [];
  const names = new Set<string>();
  for (const task of tasks) {
    const name = task.definition.name;
    if (!name.startsWith(V2_PREFIX)) {
      throw new RangeError(
        `assignment task ${JSON.stringify(name)} does not start with ${V2_PREFIX}`,
      );
    }
    if (names.has(name)) throw new RangeError(`assignment task ${name} is defined twice`);
    if (Object.hasOwn(reserved, name)) {
      throw new RangeError(`assignment task ${name} names a binding definition`);
    }
    names.add(name);
  }
  const deps: BindingDeps = { policy: program.policy, launcher: work.launcher };
  holder.deps = deps;
  const registry = createRegistry();
  const binding = bindingExtension(deps).extension;
  registry.install(binding);
  // `install` replaces an extension of the same name in place, which would drop the binding.
  if (registry.snapshot().extension(work.extension.name) !== undefined) {
    throw new RangeError(`assignment extension ${work.extension.name} is already installed`);
  }
  registry.install(work.extension);
  const definitions = { ...reserved, ...taskDefinitions(tasks) };
  const snapshot = registry.snapshot();
  for (const task of [...(binding.tasks ?? []), ...tasks]) {
    if (snapshot.task(task.definition.name) !== task) {
      throw new RangeError(`the registry does not resolve ${task.definition.name} to its task`);
    }
  }
  return {
    deps,
    registry,
    definitions,
    ...(work.models === undefined ? {} : { models: work.models }),
    ...(work.env === undefined ? {} : { env: work.env }),
  };
}

/** The execution manifest a host with `definitions` expects; pure. */
export function expectedManifest(
  definitions: Readonly<Record<string, number>>,
  options: Pick<HostOptions, "workspace" | "program">,
  createdAt: number,
): ExecutionManifest {
  return {
    type: "manifest",
    recordVersion: RECORD_VERSION,
    definitions: { ...definitions },
    policyVersion: options.program.policyVersion,
    durableVersion: DURABLE_VERSION,
    chordVersion: CHORD_VERSION,
    workspace: {
      repoIdentity: options.workspace.repoIdentity,
      executionId: options.workspace.executionId,
    },
    executionKind: FIXTURE_EXECUTION_KIND,
    createdAt,
  };
}

/**
 * Whether the Harness has failed, read without a commit. Durable sets the failure latch before a
 * failed call's rejection reaches anyone, and `wake()`'s usability check reads that latch before
 * the closing state — so it throws `SessionFailed` even once a failed Harness has begun closing
 * itself. A healthy closing or closed Harness throws a plain closed error instead: not failed.
 */
function harnessHasFailed(harness: Harness): boolean {
  try {
    harness.wake();
    return false;
  } catch (error) {
    return error instanceof SessionFailed;
  }
}

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

/** False only when nothing exists at `dir`; any other stat failure throws. */
async function storeExists(dir: string): Promise<boolean> {
  try {
    await stat(dir);
    return true;
  } catch (error) {
    if (errorCode(error) === "ENOENT") return false;
    throw error;
  }
}

type Session = { readonly harness: Harness; commits(): number };

/**
 * Open storage and the Harness (never resumed), run `body`, and close. An open failure is
 * `uncertain` — initialization and open's recovery bookkeeping may have written — and so is any
 * rejection once the Harness has failed; every other rejection is rethrown after close.
 */
async function withHarness<T>(
  options: HostOptions,
  composition: Composition,
  epoch: number,
  body: (session: Session) => Promise<T>,
): Promise<T | Uncertain> {
  const openStorage = options.openStorage ?? openNodeSqliteStorage;
  const openHarness: OpenHarness = options.openHarness ?? Harness.open;
  let storage: Storage;
  try {
    storage = await openStorage(join(options.storeDir, STORE_DATABASE));
  } catch (error) {
    return { kind: "uncertain", epoch, error };
  }
  let harness: Harness;
  try {
    harness = await openHarness(
      storage,
      {
        models: composition.models ?? createModels(),
        registry: composition.registry,
        ...(composition.env === undefined ? {} : { env: composition.env }),
        ...(options.onReport === undefined ? {} : { onReport: options.onReport }),
      },
      context,
    );
  } catch (error) {
    // Durable already closes the storage after an `openTasks` failure, so this close may reject;
    // the open error stays the reported cause.
    await storage.close(context).catch(() => {});
    return { kind: "uncertain", epoch, error };
  }
  let commits = 0;
  let unsubscribe: (() => void) | undefined;
  try {
    unsubscribe = harness.subscribeCommits(() => {
      commits++;
    });
    return await body({ harness, commits: () => commits });
  } catch (error) {
    if (error instanceof SessionFailed || harnessHasFailed(harness)) {
      return { kind: "uncertain", epoch, error };
    }
    throw error;
  } finally {
    unsubscribe?.();
    // A failing storage close is reported by Durable itself (`session_failed`); the outcome stands,
    // since every commit it describes had already resolved.
    await harness.close(context).catch(() => {});
    await harness.closed;
  }
}

/** The stored execution manifest, or `null` when the store has none. */
async function storedManifest(harness: Harness): Promise<ExecutionManifest | null> {
  const { records } = await readRecords(harness);
  return records.find((record) => record.type === "manifest") ?? null;
}

/** The exact-match gate: `incompatible` naming the first differing field, or `null` to proceed. */
function compatibility(
  stored: ExecutionManifest | null,
  composition: Composition,
  options: HostOptions,
  epoch: number,
): Incompatible | null {
  if (stored === null) return { kind: "incompatible", epoch, mismatch: MANIFEST_MISSING };
  const mismatch = manifestMismatch(expectedManifest(composition.definitions, options, 0), stored);
  return mismatch === null ? null : { kind: "incompatible", epoch, mismatch };
}

function liveStates(inspection: HarnessInspection) {
  return inspection.tasks.map((task) => task.state);
}

function noReason(view: string): HostFault {
  return new HostFault(`a consistent, inactive ${view} view has no derivable wait reason`);
}

/**
 * Resume and wait for a consistent quiescent view: poll `wake()` until inactive, then collect
 * `inspect()` and the records, and accept them only if no commit landed during the collection and
 * `wake()` is still inactive after it (a sleeping deadline may have passed meanwhile). Otherwise
 * resume again — which makes due sleepers runnable — and keep polling. No iteration cap: an
 * execution that keeps producing work keeps the run going.
 */
async function quiesce(
  session: Session,
  policy: FixturePolicy,
): Promise<HostView & { readonly waitReason: WaitReason }> {
  const { harness } = session;
  for (;;) {
    harness.resume();
    while (harness.wake().active) await sleep(QUIESCENCE_POLL_MS);
    const before = session.commits();
    const inspection = await harness.inspect(context);
    const records = await readRecords(harness);
    const endings = await readAttemptEndings(harness, records);
    const wake = harness.wake();
    if (session.commits() !== before || wake.active) continue;
    const waitReason = deriveWaitReason(records.records, policy, liveStates(inspection), endings);
    if (waitReason === null) throw noReason("run");
    return { records, inspection, wake, endings, waitReason };
  }
}

/** The status view: one collection; nothing is scheduled during status, so no consistency loop. */
async function collectStatus(harness: Harness, policy: FixturePolicy): Promise<HostView> {
  const inspection = await harness.inspect(context);
  const records = await readRecords(harness);
  const endings = await readAttemptEndings(harness, records);
  const wake = harness.wake();
  if (wake.active) return { records, inspection, wake, endings, waitReason: null };
  const waitReason = deriveWaitReason(records.records, policy, liveStates(inspection), endings);
  if (waitReason === null) throw noReason("status");
  return { records, inspection, wake, endings, waitReason };
}

/** The verb's commit input over its observation; `manifest` is called for `start` only. */
function verbInput(
  verb: HostVerb,
  facts: ObservationFacts,
  manifest: () => ExecutionManifest,
): CommitInput {
  switch (verb.type) {
    case "start":
      return { type: "start", manifest: manifest(), observation: facts };
    case "run":
      return { type: "run", observation: facts };
    case "reply":
      return {
        type: "reply",
        decisionId: verb.decisionId,
        action: verb.action,
        actor: verb.actor,
        observation: facts,
      };
  }
}

/**
 * Run one verb (`start`, `run` or `reply`) to quiescence under the store owner lock. `start`
 * creates the store directory and refuses `already_started` on a started store; `run` and `reply`
 * on a missing store directory are `incompatible` (`manifest_missing`, `epoch: null`) and create
 * nothing, and both pass the gate before observing. An applied or replayed verb resumes; the
 * quiescent outcome carries the verb's own receipt: a reply's, applied or replayed, whose
 * continuation row names the continuation it created; `null` for `start` and `run`.
 */
export async function runHost(options: HostOptions, verb: HostVerb): Promise<HostRunOutcome> {
  const composition = composeProgram(options);
  if (verb.type === "start") {
    await mkdir(options.storeDir, { recursive: true });
  } else if (!(await storeExists(options.storeDir))) {
    return { kind: "incompatible", epoch: null, mismatch: MANIFEST_MISSING };
  }
  const lock = await acquireOwnerLock(options.storeDir, options.lock);
  if (lock.kind === "owner_busy") return { kind: "owner_busy", epoch: lock.epoch };
  const { epoch } = lock;
  try {
    return await withHarness(
      options,
      composition,
      epoch,
      async (session): Promise<HostRunOutcome> => {
        const { harness } = session;
        const stored = await storedManifest(harness);
        if (verb.type === "start" && stored !== null) {
          return {
            kind: "refused",
            epoch,
            refusal: {
              reason: "already_started",
              detail: `${stored.workspace.executionId} already has a manifest`,
            },
          };
        }
        if (verb.type !== "start") {
          const incompatible = compatibility(stored, composition, options, epoch);
          if (incompatible !== null) return incompatible;
        }
        const observation = await verb.observe();
        if (observation.kind === "observation_failed") {
          return { kind: "observation_failed", epoch, detail: observation.detail };
        }
        const root = await harness.root(context);
        const input = verbInput(verb, observation.facts, () =>
          expectedManifest(composition.definitions, options, (options.now ?? Date.now)()),
        );
        const outcome = await operate(
          { harness, executionConversationId: root.id, deps: composition.deps },
          input,
        );
        if (outcome.kind === "refused") return { kind: "refused", epoch, refusal: outcome.refusal };
        if (outcome.kind === "uncertain") return { kind: "uncertain", epoch, error: outcome.error };
        return {
          kind: "quiescent",
          epoch,
          receipt: outcome.receipt,
          view: await quiesce(session, composition.deps.policy),
        };
      },
    );
  } finally {
    await lock.release();
  }
}

/**
 * The read-only status open: lock → open → gate → records + `inspect()` → close → release. It never
 * resumes, commits, creates a conversation, submits, waits, retries or aborts. A missing store
 * directory or manifest is `incompatible`; the directory is never created.
 */
export async function readStatus(options: HostOptions): Promise<HostStatusOutcome> {
  const composition = composeProgram(options);
  if (!(await storeExists(options.storeDir))) {
    return { kind: "incompatible", epoch: null, mismatch: MANIFEST_MISSING };
  }
  const lock = await acquireOwnerLock(options.storeDir, options.lock);
  if (lock.kind === "owner_busy") return { kind: "owner_busy", epoch: lock.epoch };
  const { epoch } = lock;
  try {
    return await withHarness(
      options,
      composition,
      epoch,
      async ({ harness }): Promise<HostStatusOutcome> => {
        const incompatible = compatibility(
          await storedManifest(harness),
          composition,
          options,
          epoch,
        );
        if (incompatible !== null) return incompatible;
        return {
          kind: "status",
          epoch,
          view: await collectStatus(harness, composition.deps.policy),
        };
      },
    );
  } finally {
    await lock.release();
  }
}
