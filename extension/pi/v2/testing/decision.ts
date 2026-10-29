// The reply proofs' shared fixture (dev-only): the reply verb, below-host opens of a closed store,
// store-wide task reads, the launched-work oracle, the reply commit's batch predicate and the
// "nothing recorded" oracle.
//
// Invariants the proofs rely on:
//   - Below-host opens bypass the owner lock and are never resumed: they model what another
//     process left (a cancellation commit) or read it (a receipt lookup after a reopen).
//   - Every reader opens a closed store, so call them only between host calls.
//   - "Nothing recorded" means the same record set (op ids and content, observations included)
//     and the same continuation tasks. Snapshot files a refused verb's observation materialized
//     are cache, not records, and are never compared.

import assert from "node:assert/strict";
import type { TestContext } from "node:test";
import type { JsonValue } from "@earendil-works/chord";
import type { StorageWrite, TaskRecord } from "@earendil-works/pi-durable";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import { opKindOf, REPLY_KIND } from "../durable/documents.ts";
import type { BindingTarget } from "../durable/operate.ts";
import type { ReadRecordSet } from "../durable/records.ts";
import {
  composeProgram,
  type HostOptions,
  type HostVerb,
  type Observe,
  readStatus,
} from "../host.ts";
import { FIXTURE_ACTOR } from "../kernel/fixture.ts";
import { replyOpId } from "../kernel/identity.ts";
import type { KernelRecord } from "../kernel/records.ts";
import { assertSameRecords } from "./binding.ts";
import { expectStatus } from "./host.ts";
import { createsDocument, openStoreHarness, withStore } from "./worker.ts";

export type ReplyVerb = Extract<HostVerb, { readonly type: "reply" }>;

export type StoredTask = TaskRecord<JsonValue, JsonValue, JsonValue>;

/** The reply verb over `decisionId`: action `approve` and actor `FIXTURE_ACTOR` unless overridden. */
export function replyVerb(
  observe: Observe,
  decisionId: string,
  overrides: { readonly action?: string; readonly actor?: string } = {},
): ReplyVerb {
  return {
    type: "reply",
    observe,
    decisionId,
    action: overrides.action ?? "approve",
    actor: overrides.actor ?? FIXTURE_ACTOR,
  };
}

/**
 * Open the closed store of `options` below the host — its composed program, no lock, never resumed
 * — run `body` over its binding target on the execution conversation, and always close it.
 */
export async function belowHost<T>(
  t: TestContext,
  options: HostOptions,
  body: (target: BindingTarget) => Promise<T>,
): Promise<T> {
  const composition = composeProgram(options);
  const opened = await openStoreHarness(t, options.storeDir, composition);
  try {
    return await body({
      harness: opened.harness,
      executionConversationId: opened.root.id,
      deps: composition.deps,
    });
  } finally {
    await opened.dispose();
  }
}

/** Every task of `kind` across every conversation of the closed store at `storeDir`, by id. */
export async function storeTasks(storeDir: string, kind: string): Promise<StoredTask[]> {
  return withStore(storeDir, async (view) => {
    const tasks: StoredTask[] = [];
    for (const conversation of await view.conversations()) {
      tasks.push(...(await view.tasks(conversation.id, kind)));
    }
    return tasks.sort((a, b) => a.id - b.id);
  });
}

/**
 * The task records every `launch` durable-map row names: each attempt's launched work, the
 * requesting task that opened a decision included.
 */
export async function launchedTasks(
  storeDir: string,
  durableMap: ReadRecordSet["durableMap"],
): Promise<StoredTask[]> {
  const ids = [...durableMap]
    .filter(([perkId]) => opKindOf(perkId) === "launch")
    .map(([perkId, row]) => {
      assert.equal(row.durableKind, "task", `${perkId} names a task`);
      return row.durableId;
    });
  return withStore(storeDir, async (view) => {
    const tasks: StoredTask[] = [];
    for (const id of ids) {
      const task = await view.task(id);
      assert.ok(task !== undefined, `launched task ${id} exists`);
      tasks.push(task);
    }
    return tasks;
  });
}

/** Whether a batch creates the reply document of `decisionId`: the reply commit's own batch. */
export function replyLands(decisionId: string): (writes: readonly StorageWrite[]) => boolean {
  return (writes) => createsDocument(writes, REPLY_KIND, replyOpId(decisionId));
}

/** The presented record set through a status open (its own epoch). */
export async function recordsOf(options: HostOptions): Promise<ReadRecordSet> {
  return expectStatus(await readStatus(options)).view.records;
}

/** What "nothing recorded" compares: the record set and the continuation task ids. */
export type Recorded = {
  readonly records: readonly KernelRecord[];
  readonly continuations: readonly number[];
};

export async function recorded(options: HostOptions): Promise<Recorded> {
  return {
    records: (await recordsOf(options)).records,
    continuations: (await storeTasks(options.storeDir, CONTINUATION_TASK_NAME)).map(
      (task) => task.id,
    ),
  };
}

/** Assert the store still holds exactly `before`: no record and no continuation task added. */
export async function assertNothingRecorded(
  options: HostOptions,
  before: Recorded,
  message: string,
): Promise<void> {
  const after = await recorded(options);
  assertSameRecords(after.records, before.records, message);
  assert.deepEqual(after.continuations, before.continuations, `${message}: continuation tasks`);
}

/** Assert `task` ended `completed`. */
export function assertCompleted(task: StoredTask | undefined, message: string): void {
  assert.ok(task !== undefined, `${message}: the task exists`);
  assert.equal(task.state.status, "terminal", `${message}: terminal`);
  assert.equal(task.state.outcome?.status, "completed", `${message}: completed`);
}
