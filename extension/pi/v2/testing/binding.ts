// The binding proofs' shared fixture (dev-only): constants and op builders mirroring the kernel's
// reconcile tests, a fake assignment task standing in for the native assignment, the store
// oracles, and narrowing helpers. It lives under `testing/` so the proofs can combine it with
// `durable.ts` (the faux setup, SQLite and LIFO cleanup) — `durable/` files may import only
// `kernel/` and `durable/`.
//
// Invariants the proofs rely on:
//   - Every id is a real kernel derivation; observation facts are synthetic (no git).
//   - The fake assignment and the host-level `acceptOp` submit the same default report
//     (`fakeReport`), so a host acceptance and a fake's acceptance converge by replay.
//   - The oracles read storage directly, below the binding: `storeDocuments` and
//     `nonSessionV2Documents` open their own SQLite handle, so the Harness must be closed first.

import assert from "node:assert/strict";
import type { TestContext } from "node:test";
import {
  type Cursor,
  type DocumentRecord,
  defineTask,
  type Harness,
  type JsonObject,
  type Page,
  type Storage,
  type Task,
  type TaskRecord,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  type AttemptLauncher,
  type BindingDeps,
  type BindingTarget,
  type CommitInput,
  type OperateOutcome,
  operateInTx,
} from "../durable/operate.ts";
import { bindingDefinitions, bindingExtension, type StepTask } from "../durable/tasks.ts";
import { canonicalJson } from "../kernel/canonical.ts";
import type { CapabilitySet } from "../kernel/capability.ts";
import {
  FIXTURE_ACTOR,
  FIXTURE_DECISION_KIND,
  FIXTURE_EXECUTION_KIND,
  type FixturePolicy,
  roleAssignmentId,
} from "../kernel/fixture.ts";
import { deriveAttemptId, deriveDecisionId } from "../kernel/identity.ts";
import { evaluateOperation, nextRecords } from "../kernel/reconcile.ts";
import type {
  ExecutionManifest,
  FixtureReport,
  KernelRecord,
  ObservationFacts,
} from "../kernel/records.ts";
import type { RefusalReason } from "../kernel/refusal.ts";
import {
  completed,
  context,
  installTasks,
  type Opened,
  open,
  type Setup,
  waitFor,
} from "./durable.ts";

// ── constants ───────────────────────────────────────────────────────────────────────────────────

export const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
export const T1 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
export const T2 = "9b9a1c8e6a2b1c0d7e5f4a3b2c1d0e9f8a7b6c5d";
export const T3 = "e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3";
export const C1 = "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1";
export const C1B = "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1";
export const C2 = "c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2";
export const C2B = "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2";
export const C2C = "d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2";
export const C3 = "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3";
export const C3B = "b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3b3";
export const REPO = "/repo/.git";
export const REF = "refs/heads/main";

const MANIFEST_DIGESTS: Readonly<Record<string, string>> = {
  [T1]: "a1".repeat(32),
  [T2]: "a2".repeat(32),
  [T3]: "a3".repeat(32),
};

/** The snapshot-manifest digest of `tree` (what the fake verifies and the host accepts with). */
export function digestOf(tree: string): string {
  const digest = MANIFEST_DIGESTS[tree];
  assert.ok(digest !== undefined, `a manifest digest for ${tree}`);
  return digest;
}

const CAPABILITY_SET: CapabilitySet = {
  model: { provider: "faux", modelId: "faux-1" },
  extensions: ["perk.v2.report"],
  tools: ["read", "ls", "grep", "find"],
  instructionsDigest: "1".repeat(64),
  posture: "read-only",
  workspaceRoot: "subject-snapshot",
};

/** The host policy the proofs run under. */
export const policyA: FixturePolicy = { capabilitySet: CAPABILITY_SET };
/** A second policy, differing from `policyA` only in its instructions digest. */
export const policyB: FixturePolicy = {
  capabilitySet: { ...CAPABILITY_SET, instructionsDigest: "2".repeat(64) },
};

export const FAKE_ASSIGNMENT_NAME = "perk.v2.fake-assignment";

export function manifest(): ExecutionManifest {
  return {
    type: "manifest",
    recordVersion: 1,
    definitions: { ...bindingDefinitions(), [FAKE_ASSIGNMENT_NAME]: 1 },
    policyVersion: 1,
    durableVersion: "1.4.0",
    chordVersion: "1.4.0",
    workspace: { repoIdentity: REPO, executionId: E },
    executionKind: FIXTURE_EXECUTION_KIND,
    createdAt: 1_700_000_000_000,
  };
}

export function facts(tree: string, commit: string): ObservationFacts {
  return { repo: REPO, ref: REF, commit, tree, manifestDigest: digestOf(tree), observedAt: 1000 };
}

/** The one default report: the fake assignment's and the host-level `acceptOp`'s. */
export function fakeReport(tree: string): FixtureReport {
  return { subjectDigest: tree, summary: "fake report", findings: [] };
}

// ── ids ─────────────────────────────────────────────────────────────────────────────────────────

export type Role = "a" | "b";

export function assignmentIdOf(role: Role, tree: string, policy: FixturePolicy = policyA): string {
  return roleAssignmentId(E, role, tree, policy);
}

export function attemptIdOf(role: Role, tree: string, policy: FixturePolicy = policyA): string {
  return deriveAttemptId(assignmentIdOf(role, tree, policy), 1);
}

export function decisionIdOf(tree: string): string {
  return deriveDecisionId({
    executionId: E,
    subjectDigest: tree,
    decisionKind: FIXTURE_DECISION_KIND,
  });
}

// ── operations ──────────────────────────────────────────────────────────────────────────────────

export function startOp(): CommitInput {
  return { type: "start", manifest: manifest(), observation: facts(T1, C1) };
}

export function runOp(tree: string, commit: string): CommitInput {
  return { type: "run", observation: facts(tree, commit) };
}

export function acceptOp(
  role: Role,
  tree: string,
  overrides: Partial<{ report: unknown; verifiedDigest: string }> = {},
): CommitInput {
  return {
    type: "accept-report",
    attemptId: attemptIdOf(role, tree),
    report: fakeReport(tree),
    verifiedDigest: digestOf(tree),
    ...overrides,
  };
}

export function replyOp(
  tree: string,
  overrides: Partial<{ action: string; actor: string; observation: ObservationFacts }> = {},
): CommitInput {
  return {
    type: "reply",
    decisionId: decisionIdOf(tree),
    action: "approve",
    actor: FIXTURE_ACTOR,
    observation: facts(tree, tree === T1 ? C1 : tree === T2 ? C2 : C3),
    ...overrides,
  };
}

export function cancelOp(reason = "operator stop"): CommitInput {
  return { type: "cancel", reason };
}

// ── the fake assignment ─────────────────────────────────────────────────────────────────────────

export type FakeInput = {
  readonly attemptId: string;
  readonly subjectDigest: string;
  readonly verifiedDigest: string;
};

export type FakeAssignment = Task<FakeInput, { phase: "run" }, null, object>;

/**
 * Test hooks around the fake's one commit, in the phase: `before` runs before it, `after` once it
 * resolved. They count phases, block a phase (resolve its deferred in teardown — `close()` joins a
 * running phase), or arm a storage failure.
 */
export type FakeHooks = {
  before?(input: FakeInput): void | Promise<void>;
  after?(input: FakeInput): void | Promise<void>;
};

/**
 * The attempt's stand-in work: one commit that, when `accept`, accepts `fakeReport(subject)` with
 * the verified digest through `operateInTx`, then completes; `hooks` run around that commit. `deps`
 * is a thunk because the launcher that creates this task is itself part of the dependencies.
 */
export function defineFakeAssignment(
  deps: () => BindingDeps,
  options: { readonly accept: boolean; readonly hooks?: FakeHooks },
): FakeAssignment {
  const { hooks } = options;
  return defineTask<FakeInput, { phase: "run" }, null>({
    name: FAKE_ASSIGNMENT_NAME,
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: {
      run: async (task, runtime, phaseContext) => {
        await hooks?.before?.(task.input);
        await runtime.commit(async (tx) => {
          if (options.accept) {
            const { attemptId, subjectDigest, verifiedDigest } = task.input;
            await operateInTx(
              tx,
              {
                type: "accept-report",
                attemptId,
                report: fakeReport(subjectDigest),
                verifiedDigest,
              },
              deps(),
              runtime.conversationId,
            );
          }
          return completed(null);
        }, phaseContext);
        await hooks?.after?.(task.input);
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

/** A launcher creating `task` on the execution conversation (conversation-owned, background). */
export function fakeLauncher(task: FakeAssignment): AttemptLauncher {
  return (tx, launch) =>
    tx.createTask(
      task,
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
    );
}

export type Installed = {
  readonly deps: BindingDeps;
  readonly step: StepTask;
  readonly fake: FakeAssignment;
};

/**
 * Install the binding's extension and the fake assignment into `setup`'s registry — once per
 * setup; a reopen over the same setup reuses the result. `launcher` wraps or replaces the fake
 * launcher.
 */
export function installBinding(
  setup: Setup,
  options: {
    readonly policy: FixturePolicy;
    readonly accept: boolean;
    readonly launcher?: (fake: FakeAssignment) => AttemptLauncher;
  },
): Installed {
  const holder: { deps?: BindingDeps } = {};
  const fake = defineFakeAssignment(
    () => {
      assert.ok(holder.deps !== undefined, "the binding dependencies are built");
      return holder.deps;
    },
    { accept: options.accept },
  );
  const deps: BindingDeps = {
    policy: options.policy,
    launcher: (options.launcher ?? fakeLauncher)(fake),
  };
  holder.deps = deps;
  const { extension, step } = bindingExtension(deps);
  setup.registry.install(extension);
  installTasks(setup, "perk.v2.fake", [fake]);
  return { deps, step, fake };
}

/** Open a Harness over `storage` (never resumed) and its binding target on the root conversation. */
export async function openBinding(
  t: TestContext,
  storage: Storage,
  setup: Setup,
  installed: Installed,
): Promise<{ opened: Opened; target: BindingTarget }> {
  const opened = await open(t, storage, setup);
  return {
    opened,
    target: {
      harness: opened.harness,
      executionConversationId: opened.root.id,
      deps: installed.deps,
    },
  };
}

/** Resume scheduling and wait until no task can run. */
export async function quiesce(harness: Harness): Promise<void> {
  harness.resume();
  await waitFor(() => !harness.wake().active);
}

// ── the model ───────────────────────────────────────────────────────────────────────────────────

/** The kernel's own record set after `input` (a step when absent): the reference applier. */
export function modelAfter(
  before: readonly KernelRecord[],
  input: CommitInput | undefined,
  policy: FixturePolicy = policyA,
): readonly KernelRecord[] {
  return nextRecords(before, evaluateOperation(before, input ?? { type: "step" }, policy));
}

/** `modelAfter` folded over `inputs` from the empty set. */
export function modelChain(
  inputs: readonly (CommitInput | undefined)[],
  policy: FixturePolicy = policyA,
): readonly KernelRecord[] {
  return inputs.reduce<readonly KernelRecord[]>(
    (records, input) => modelAfter(records, input, policy),
    [],
  );
}

function recordKey(record: KernelRecord): string {
  return record.type === "manifest" ? "manifest" : record.opId;
}

function canonicalByKey(records: readonly KernelRecord[], message: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const record of records) {
    const key = recordKey(record);
    if (map.has(key)) assert.fail(`${message}: ${key} appears twice`);
    map.set(key, canonicalJson(record));
  }
  return map;
}

/** Assert equal record sets, keyed by op id (`manifest` for the manifest); fails naming the keys. */
export function assertSameRecords(
  actual: readonly KernelRecord[],
  expected: readonly KernelRecord[],
  message: string,
): void {
  const got = canonicalByKey(actual, message);
  const want = canonicalByKey(expected, message);
  const missing = [...want.keys()].filter((key) => !got.has(key)).sort();
  const extra = [...got.keys()].filter((key) => !want.has(key)).sort();
  const differing = [...want.keys()]
    .filter((key) => got.has(key) && got.get(key) !== want.get(key))
    .sort();
  if (missing.length + extra.length + differing.length > 0) {
    assert.fail(
      `${message}: missing ${JSON.stringify(missing)}, extra ${JSON.stringify(extra)}, differing ${JSON.stringify(differing)}`,
    );
  }
}

/** The records of one type, narrowed. */
export function ofType<K extends KernelRecord["type"]>(
  records: readonly KernelRecord[],
  type: K,
): Extract<KernelRecord, { readonly type: K }>[] {
  return records.filter(
    (record): record is Extract<KernelRecord, { readonly type: K }> => record.type === type,
  );
}

// ── outcome narrowing ───────────────────────────────────────────────────────────────────────────

function shown(outcome: OperateOutcome): string {
  return outcome.kind === "uncertain"
    ? `uncertain (${String(outcome.error)})`
    : JSON.stringify(outcome);
}

export function expectApplied(
  outcome: OperateOutcome,
): Extract<OperateOutcome, { kind: "applied" }> {
  if (outcome.kind !== "applied") assert.fail(`expected applied: ${shown(outcome)}`);
  return outcome;
}

export function expectReplayed(
  outcome: OperateOutcome,
): Extract<OperateOutcome, { kind: "replayed" }> {
  if (outcome.kind !== "replayed") assert.fail(`expected replayed: ${shown(outcome)}`);
  return outcome;
}

export function expectRefused(outcome: OperateOutcome, reason: RefusalReason): string {
  if (outcome.kind !== "refused") assert.fail(`expected refused ${reason}: ${shown(outcome)}`);
  assert.equal(outcome.refusal.reason, reason, outcome.refusal.detail);
  return outcome.refusal.detail;
}

export function expectUncertain(outcome: OperateOutcome): unknown {
  if (outcome.kind !== "uncertain") assert.fail(`expected uncertain: ${shown(outcome)}`);
  return outcome.error;
}

// ── storage oracles ─────────────────────────────────────────────────────────────────────────────

async function scanAll<T>(
  page: (cursor: Cursor | undefined) => Promise<Page<T, Cursor>>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: Cursor | undefined;
  do {
    const next = await page(cursor);
    items.push(...next.items);
    cursor = next.next;
  } while (cursor !== undefined);
  return items;
}

/**
 * The storage oracle: every current `perk.v2.*` session document in the store at `path`, by kind
 * then key (`""` for a singleton), materialized below the binding. Close the Harness first.
 */
export async function storeDocuments(path: string): Promise<Map<string, Map<string, JsonObject>>> {
  const storage = await openNodeSqliteStorage(path);
  try {
    const records = await scanAll((cursor) =>
      storage.scanDocuments({ scope: { kind: "session" }, at: "current" }, 100, cursor, context),
    );
    const found = new Map<string, Map<string, JsonObject>>();
    for (const record of records) {
      if (!record.kind.startsWith("perk.v2.")) continue;
      const stored = await storage.document(record.id, "current", context);
      assert.ok(stored !== undefined, `document ${record.id} (${record.kind}) materializes`);
      const byKey = found.get(record.kind) ?? new Map<string, JsonObject>();
      byKey.set(record.key ?? "", stored.value);
      found.set(record.kind, byKey);
    }
    return found;
  } finally {
    await storage.close(context);
  }
}

/** Every current `perk.v2.*` document in a conversation or task scope of the store at `path`. */
export async function nonSessionV2Documents(
  path: string,
): Promise<{ kind: string; scope: string }[]> {
  const storage = await openNodeSqliteStorage(path);
  try {
    const scopes: DocumentRecord["scope"][] = [];
    const conversations = await scanAll((cursor) =>
      storage.scanConversations({}, 100, cursor, context),
    );
    for (const conversation of conversations) {
      scopes.push({ kind: "conversation", conversationId: conversation.id });
    }
    const tasks = await scanAll((cursor) => storage.scanTasks({}, 100, cursor, context));
    for (const task of tasks) scopes.push({ kind: "task", taskId: task.id });
    const found: { kind: string; scope: string }[] = [];
    for (const scope of scopes) {
      const records = await scanAll((cursor) =>
        storage.scanDocuments({ scope, at: "current" }, 100, cursor, context),
      );
      for (const record of records) {
        if (record.kind.startsWith("perk.v2."))
          found.push({ kind: record.kind, scope: JSON.stringify(scope) });
      }
    }
    return found;
  } finally {
    await storage.close(context);
  }
}

/** Every task of `kind` in the store, through the Harness. */
export async function tasksOfKind(
  harness: Harness,
  kind: string,
): Promise<readonly TaskRecord<unknown, unknown, unknown>[]> {
  const page = await harness.commit((tx) => tx.scanTasks({ kind }, 100), context);
  return page.items;
}
