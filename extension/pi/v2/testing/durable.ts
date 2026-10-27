// The Durable characterization suite's shared fixture (dev-only). It lives under `testing/` so its
// bare Durable / pi-ai / chord imports pass `layering.ts`' dependency confinement — the same file
// anywhere else in the workspace would be production code and its imports would be `leaked`.
//
// Sized to the cases in `../characterization/`, not a re-creation of upstream's unpublished test
// support. Three invariants every consumer relies on:
//   - Cleanup is registered at acquisition (`tempDir`, `sqlitePath`, `open`, `crashable`) and runs
//     LIFO after the test, timeout or failure included: node:test runs `t.after` hooks in
//     registration order, so the helper keeps one per-test stack and drains it in reverse — a
//     Harness closes before its storage, and its storage before its directory is removed.
//   - Fault injection is armed explicitly, never at construction: `open()`'s `harness.root()` is
//     itself a storage commit, so a proxy armed up front would fail during setup.
//   - `Opened.dispose()` is idempotent: `Harness.close()` is not, and a Harness closes itself
//     after a storage failure.

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type { Context, JsonValue } from "@earendil-works/chord";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { AssistantMessage, Message, Models, ToolResultMessage } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import {
  type FauxProviderHandle,
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import {
  type AnyTask,
  type Conversation,
  createRegistry,
  defineExtension,
  type EntryRecord,
  Harness,
  type HarnessOptions,
  type HarnessSettings,
  type HookRegistration,
  MemoryStorage,
  type Registry,
  type ReportInfo,
  type Seq,
  type Storage,
  type StorageWrite,
  type ToolRegistration,
  ToolResultEntry,
} from "@earendil-works/pi-durable";

/** The per-case bound: the whole v2 suite runs in well under a second, so a case hitting it hung. */
export const CASE_TIMEOUT_MS = 30_000;

/** The one context every Durable call in the suite runs under. */
export const context: Context = BACKGROUND_CONTEXT;

type Cleanup = () => void | Promise<void>;

const cleanups = new WeakMap<TestContext, Cleanup[]>();

/** Register `cleanup` on `t`'s LIFO stack; the first registration installs the one draining hook. */
function defer(t: TestContext, cleanup: Cleanup): void {
  let stack = cleanups.get(t);
  if (stack === undefined) {
    const owned: Cleanup[] = [];
    stack = owned;
    cleanups.set(t, owned);
    t.after(
      async () => {
        const errors: unknown[] = [];
        for (const step of owned.reverse()) {
          try {
            await step();
          } catch (error) {
            errors.push(error);
          }
        }
        if (errors.length > 0)
          throw new AggregateError(errors, "a characterization cleanup failed");
      },
      { timeout: CASE_TIMEOUT_MS },
    );
  }
  stack.push(cleanup);
}

export type Deferred<T = void> = {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
};

export function deferred<T = void>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/** Reject with the signal's reason once it aborts — for tools and phases that block until cancelled. */
export function aborted(signal: AbortSignal): Promise<never> {
  return new Promise((_, reject) => {
    if (signal.aborted) reject(signal.reason);
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
}

/** One macrotask turn. */
export function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** Poll `check` in real time (5 ms) until it holds; throws past `timeoutMs`. */
export async function waitFor(
  check: () => boolean | Promise<boolean>,
  timeoutMs = 5000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!(await check())) {
    if (Date.now() > deadline) throw new Error("Condition was not reached");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

/** A fresh temp directory, removed after the test. */
export async function tempDir(t: TestContext, prefix: string): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), prefix));
  defer(t, () => rm(dir, { recursive: true, force: true }));
  return dir;
}

/** A SQLite file path in a fresh temp directory, removed after the test. */
export async function sqlitePath(t: TestContext): Promise<string> {
  return join(await tempDir(t, "perk-v2-durable-"), "session.sqlite");
}

/** Models and registry that outlive one Harness, as a host process's own objects outlive a reopen. */
export type Setup = {
  readonly faux: FauxProviderHandle;
  readonly models: Models;
  readonly registry: Registry;
  /** Every `onReport` error, in order (`infos[i]` says what `reports[i]` was about). */
  readonly reports: unknown[];
  readonly infos: ReportInfo[];
};

export function fauxSetup(): Setup {
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  return { faux, models, registry: createRegistry(), reports: [], infos: [] };
}

export interface Opened {
  readonly harness: Harness;
  readonly root: Conversation;
  /** Close the Harness unless it already closed (or was abandoned), then await `closed`. Idempotent. */
  dispose(): Promise<void>;
  /** Mark a Harness whose storage was crashed: every storage call hangs, so it is never closed. */
  abandon(): void;
}

/** Open a Harness over `storage` and its root (faux model). Never resumes — each case decides. */
export async function open(
  t: TestContext,
  storage: Storage,
  setup: Setup,
  options: { readonly settings?: HarnessSettings; readonly env?: HarnessOptions["env"] } = {},
): Promise<Opened> {
  const harness = await Harness.open(
    storage,
    {
      models: setup.models,
      registry: setup.registry,
      onReport: (error, info) => {
        setup.reports.push(error);
        setup.infos.push(info);
      },
      ...(options.settings === undefined ? {} : { settings: options.settings }),
      ...(options.env === undefined ? {} : { env: options.env }),
    },
    context,
  );
  let closed = false;
  void harness.closed.then(() => {
    closed = true;
  });
  let abandoned = false;
  let disposing: Promise<void> | undefined;
  const dispose = (): Promise<void> => {
    disposing ??= (async () => {
      if (abandoned) return;
      if (!closed) await harness.close(context).catch(() => {});
      await harness.closed;
    })();
    return disposing;
  };
  defer(t, dispose);
  const root = await harness.root(context, {
    agent: { model: { provider: "faux", modelId: "faux-1" } },
  });
  return {
    harness,
    root,
    dispose,
    abandon: () => {
      abandoned = true;
    },
  };
}

export function installTasks(setup: Setup, name: string, tasks: readonly AnyTask[]): void {
  setup.registry.install(defineExtension({ name, tasks }));
}

export function installTools(
  setup: Setup,
  name: string,
  tools: readonly ToolRegistration[],
  hooks?: readonly HookRegistration[],
): void {
  setup.registry.install(
    defineExtension({ name, tools, ...(hooks === undefined ? {} : { hooks }) }),
  );
}

/** A faux tool-calling answer with one call. */
export function toolCall(
  name: string,
  args: Record<string, JsonValue> = {},
  id = "c1",
): AssistantMessage {
  return fauxAssistantMessage([fauxToolCall(name, args, { id })], { stopReason: "toolUse" });
}

/** A faux final text answer. */
export const DONE: AssistantMessage = fauxAssistantMessage([fauxText("done")]);

/** A conversation's raw entries, oldest first. */
export async function allEntries(conversation: Conversation): Promise<EntryRecord[]> {
  const page = await conversation.entries({}, 1000, undefined, context);
  return [...page.items].reverse();
}

function isToolResult(message: Message | undefined): message is ToolResultMessage {
  return message?.role === "toolResult";
}

/** The tool-result messages of `entries`, in order. */
export function toolResults(entries: readonly EntryRecord[]): ToolResultMessage[] {
  return entries
    .filter((entry) => ToolResultEntry.is(entry))
    .map((entry) => entry.model?.[0])
    .filter(isToolResult);
}

/** A tool result's text content, items joined with `|`. */
export function resultText(message: ToolResultMessage): string {
  return message.content.map((item) => (item.type === "text" ? item.text : "")).join("|");
}

/** Memory storage that records every committed batch (detached) and announces each commit. */
export class CountingStorage extends MemoryStorage {
  readonly commits: (readonly StorageWrite[])[] = [];
  /** Called right after a commit resolved at the backend. */
  onCommitted: ((writes: readonly StorageWrite[]) => void) | undefined;

  override async commit(writes: readonly StorageWrite[], callContext: Context): Promise<Seq> {
    const detached = structuredClone(writes);
    const seq = await super.commit(writes, callContext);
    this.commits.push(detached);
    this.onCommitted?.(detached);
    return seq;
  }
}

/** A delegating proxy over `inner` whose `commit` is replaced by `commit(target)`. */
function withCommit(inner: Storage, commit: (target: Storage) => Storage["commit"]): Storage {
  return new Proxy(inner, {
    get(target, property) {
      if (property === "commit") return commit(target);
      const value: unknown = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

/** Count `commit` calls reaching `inner` (a delegating proxy, for storages that cannot be subclassed). */
export function counting(inner: Storage): { storage: Storage; commits(): number } {
  let count = 0;
  const storage = withCommit(inner, (target) => (writes, callContext) => {
    count++;
    return target.commit(writes, callContext);
  });
  return { storage, commits: () => count };
}

/**
 * Delegate everything to `inner`, unarmed. `armNextCommit(error)` makes exactly the next `commit`
 * reject with `error`, then disarms. `close` always delegates, so a failed Harness's self-close
 * reaches the backend.
 */
export function failing(inner: Storage): {
  storage: Storage;
  armNextCommit(error: Error): void;
} {
  let armed: Error | undefined;
  const storage = withCommit(inner, (target) => (writes, callContext) => {
    const error = armed;
    if (error === undefined) return target.commit(writes, callContext);
    armed = undefined;
    return Promise.reject(error);
  });
  return {
    storage,
    armNextCommit: (error) => {
      armed = error;
    },
  };
}

/**
 * A storage a crash can cut off: after `crash()` every method call hangs forever, so the Harness
 * over it writes nothing more — not even the `pending` records a close writes (a close would not
 * count as a restart). `inner` is closed after the test.
 */
export function crashable(t: TestContext, inner: Storage): { storage: Storage; crash(): void } {
  defer(t, () => inner.close(context).catch(() => {}));
  let dead = false;
  const storage = new Proxy(inner, {
    get(target, property) {
      const value: unknown = Reflect.get(target, property, target);
      if (typeof value !== "function") return value;
      return (...args: unknown[]) =>
        dead ? new Promise(() => {}) : Reflect.apply(value, target, args);
    },
  });
  return {
    storage,
    crash: () => {
      dead = true;
    },
  };
}

/** The next state that completes a task with `result`. */
export function completed<R>(result: R) {
  return { status: "terminal", outcome: { status: "completed", result } } as const;
}
