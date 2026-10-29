// The native assignment proofs' shared fixture (dev-only): per-role faux scripts, report and round
// builders, host options over the fixture program, a read-only store view, a binding-level open of
// a composed program, and a storage that crashes right after a chosen commit lands.
//
// Invariants the proofs rely on:
//   - Concurrent workers stay deterministic: every model request is routed to the role whose
//     `fixtureWorkerPrompt(role, tree)` is the transcript's first user message, and shifts only that
//     role's queue. A request with no routable role, or past its role's queue, is answered with a
//     provider error and counted, so a proof can assert none happened.
//   - The store view opens the SQLite file directly and only reads; open it after the host closed.
//   - `crashAfterCommit` lets the matching commit land at the backend, then hangs every call — the
//     acknowledgement included — as a killed process would.

import assert from "node:assert/strict";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type { Context, JsonValue } from "@earendil-works/chord";
import type { AssistantMessage, ToolCall, ToolResultMessage } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import {
  type FauxProviderHandle,
  type FauxResponseStep,
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import {
  type Conversation,
  type ConversationRecord,
  type Cursor,
  type EntryRecord,
  Harness,
  type JsonObject,
  type Page,
  type ReportInfo,
  type Storage,
  type StorageWrite,
  type SubmissionRecord,
  type TaskId,
  type TaskRecord,
  type ToolDiagnostic,
  ToolResultEntry,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  type Composition,
  type HostOptions,
  type HostRunOutcome,
  type Observe,
  runHost,
  STORE_DATABASE,
} from "../host.ts";
import { fixturePolicy, fixtureWorkerPrompt } from "../kernel/fixture.ts";
import { type FixtureProgramOptions, fixtureProgram } from "../program.ts";
import { gitObserver } from "../subject/observe.ts";
import { attemptIdOf, REF, type Role } from "./binding.ts";
import { context, crashable, defer, fauxSetup, type Opened, type Setup } from "./durable.ts";
import { hostOptions } from "./host.ts";
import { commitAll, gitRepo, subjectStore, treeOf, writeFiles } from "./subject.ts";

export const ROLES: readonly Role[] = ["a", "b"];

/** The summary every scripted report carries unless overridden. */
export const REPORT_SUMMARY = "nothing to note";

/** A final text answer with no report. */
export const FINAL: AssistantMessage = fauxAssistantMessage([fauxText("done")]);

/** The fixture program's attempt id for `role` over `tree`. */
export function fixtureAttemptId(role: Role, tree: string): string {
  return attemptIdOf(role, tree, fixturePolicy());
}

// ── scripted workers ────────────────────────────────────────────────────────────────────────────

export type Step = FauxResponseStep;

export type RoleScripts = Partial<Record<Role, readonly Step[]>>;

export type RoleScript = {
  /** Steps of `role` answered so far. */
  consumed(role: Role): number;
  /** Steps of `role` not answered yet. */
  leftover(role: Role): number;
  /** Requests with no routable role or past their role's queue. */
  strays(): number;
  /** Append steps to `role`'s queue (and dispatchers to match). */
  append(role: Role, steps: readonly Step[]): void;
};

function messageText(content: string | readonly { readonly type: string }[]): string {
  if (typeof content === "string") return content;
  return content.map((item) => (item.type === "text" ? Reflect.get(item, "text") : "")).join("");
}

/** The role whose prompt over `tree` is the first user message of `messages`, or `null`. */
export function roleOfMessages(
  messages: readonly { readonly role: string; readonly content?: unknown }[],
  tree: string,
): Role | null {
  const first = messages.find((message) => message.role === "user");
  if (first === undefined) return null;
  const content = first.content;
  if (typeof content !== "string" && !Array.isArray(content)) return null;
  const text = messageText(content);
  return ROLES.find((role) => text === fixtureWorkerPrompt(role, tree)) ?? null;
}

/** How many spare dispatchers stay installed for stray requests. */
const SPARE_DISPATCHERS = 8;

/** Install per-role dispatchers on `faux` for workers over `tree`; replaces its responses. */
export function roleScript(
  faux: FauxProviderHandle,
  tree: string,
  scripts: RoleScripts,
): RoleScript {
  const queues = new Map<Role, Step[]>(ROLES.map((role) => [role, [...(scripts[role] ?? [])]]));
  const consumed = new Map<Role, number>(ROLES.map((role) => [role, 0]));
  let strays = 0;
  const stray = (detail: string): AssistantMessage => {
    strays++;
    return fauxAssistantMessage([], { stopReason: "error", errorMessage: `stray: ${detail}` });
  };
  const dispatcher: Step = (transcript, options, state, model) => {
    const role = roleOfMessages(transcript.messages, tree);
    if (role === null) return stray("no routable role");
    const step = queues.get(role)?.shift();
    if (step === undefined) return stray(`role ${role} has no step left`);
    consumed.set(role, (consumed.get(role) ?? 0) + 1);
    return typeof step === "function" ? step(transcript, options, state, model) : step;
  };
  const total = [...queues.values()].reduce((sum, queue) => sum + queue.length, 0);
  faux.setResponses(Array.from({ length: total + SPARE_DISPATCHERS }, () => dispatcher));
  return {
    consumed: (role) => consumed.get(role) ?? 0,
    leftover: (role) => queues.get(role)?.length ?? 0,
    strays: () => strays,
    append: (role, steps) => {
      queues.get(role)?.push(...steps);
      faux.appendResponses(steps.map(() => dispatcher));
    },
  };
}

/** Report arguments over `tree`: `{subjectDigest, summary, findings: []}` plus `overrides`. */
export function reportArgs(
  tree: string,
  overrides: Readonly<Record<string, JsonValue>> = {},
): Record<string, JsonValue> {
  return { subjectDigest: tree, summary: REPORT_SUMMARY, findings: [], ...overrides };
}

/** One tool call. */
export function call(name: string, args: Record<string, JsonValue>, id: string): ToolCall {
  return fauxToolCall(name, args, { id });
}

/** One assistant message issuing `calls` as one round. */
export function round(...calls: ToolCall[]): AssistantMessage {
  return fauxAssistantMessage(calls, { stopReason: "toolUse" });
}

/** A round with one report call over `tree`. */
export function reportCall(
  tree: string,
  overrides: Readonly<Record<string, JsonValue>> = {},
  id = "report-1",
): AssistantMessage {
  return round(call("report", reportArgs(tree, overrides), id));
}

/** A step that runs `effect` when its request arrives, then answers with `message`. */
export function after(effect: () => void | Promise<void>, message: AssistantMessage): Step {
  return async () => {
    await effect();
    return message;
  };
}

// ── subjects ────────────────────────────────────────────────────────────────────────────────────

/** The fixture subject's files. */
export const SUBJECT_FILES: Readonly<Record<string, string>> = {
  "a.txt": "alpha\n",
  "dir/b.ts": "beta\n",
  "dir/c.md": "gamma\n",
};

export type Subject = {
  readonly repo: string;
  readonly tree: string;
  readonly store: string;
  readonly observe: Observe;
};

/** A fixture repo with `files` committed on `main`, a fresh store, and a git observer over both. */
export async function fixtureSubject(
  t: TestContext,
  files: Readonly<Record<string, string>> = SUBJECT_FILES,
): Promise<Subject> {
  const repo = await gitRepo(t);
  writeFiles(repo, files);
  const tree = treeOf(repo, commitAll(repo, "c1"));
  const store = await subjectStore(t);
  return { repo, tree, store, observe: gitObserver({ storeDir: store, repo, ref: REF }) };
}

export type NativeStart = Subject &
  NativeHost & { readonly script: RoleScript; readonly outcome: HostRunOutcome };

/** A fixture subject, workers scripted by `scripts(tree)`, and the host's `start` over it. */
export async function startNative(
  t: TestContext,
  scripts: (tree: string) => RoleScripts,
  overrides: Partial<FixtureProgramOptions> & { readonly setup?: Setup } = {},
  files?: Readonly<Record<string, string>>,
): Promise<NativeStart> {
  const subject = await fixtureSubject(t, files);
  const host = nativeOptions(subject.store, overrides);
  const script = roleScript(host.setup.faux, subject.tree, scripts(subject.tree));
  const outcome = await runHost(host.options, { type: "start", observe: subject.observe });
  return { ...subject, ...host, script, outcome };
}

// ── host options ────────────────────────────────────────────────────────────────────────────────

export type Reported = { readonly error: unknown; readonly info: ReportInfo };

export type NativeHost = {
  readonly setup: Setup;
  readonly options: HostOptions;
  readonly reports: Reported[];
};

/**
 * Host options over `storeDir` running `fixtureProgram` on `setup`'s faux catalog (a fresh setup by
 * default), every `onReport` captured.
 */
export function nativeOptions(
  storeDir: string,
  overrides: Partial<FixtureProgramOptions> & { readonly setup?: Setup } = {},
): NativeHost {
  const { setup: given, ...program } = overrides;
  const setup = given ?? fauxSetup();
  const reports: Reported[] = [];
  const options = hostOptions(storeDir, fixtureProgram({ models: setup.models, ...program }), {
    onReport: (error, info) => {
      reports.push({ error, info });
    },
  });
  return { setup, options, reports };
}

/** The report types of `reports`, for an assertion message. */
export function reportTypes(reports: readonly Reported[]): string[] {
  return reports.map((report) => `${report.info.type}: ${String(report.error)}`);
}

// ── the store view ──────────────────────────────────────────────────────────────────────────────

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

/** A read-only view of a closed store's Durable tables. */
export type StoreView = {
  conversations(): Promise<ConversationRecord[]>;
  /** Every task-owned conversation: the worker conversations. */
  workers(): Promise<ConversationRecord[]>;
  entries(conversationId: number): Promise<EntryRecord[]>;
  submissions(conversationId: number): Promise<SubmissionRecord[]>;
  task(id: number): Promise<TaskRecord<JsonValue, JsonValue, JsonValue> | undefined>;
  /** The conversation's current `pi.agent` document. */
  agent(conversationId: number): Promise<JsonObject | undefined>;
  /** The conversation's tool results with their persisted diagnostics, in order. */
  toolResults(conversationId: number): Promise<ToolResultView[]>;
};

export type ToolResultView = {
  readonly message: ToolResultMessage;
  readonly text: string;
  readonly diagnostics: readonly ToolDiagnostic[];
};

function asConversationId(id: number): Conversation["id"] {
  return id as Conversation["id"];
}

function asTaskId(id: number): TaskId {
  return id as TaskId;
}

/** Run `read` over a read-only view of the store at `storeDir`, then close it. */
export async function withStore<T>(
  storeDir: string,
  read: (view: StoreView) => Promise<T>,
): Promise<T> {
  const storage = await openNodeSqliteStorage(join(storeDir, STORE_DATABASE));
  const entries = (conversationId: number) =>
    scanAll((cursor) =>
      storage.scanEntries(
        { conversationId: asConversationId(conversationId), order: "ascending" },
        100,
        cursor,
        context,
      ),
    );
  const view: StoreView = {
    conversations: () => scanAll((cursor) => storage.scanConversations({}, 100, cursor, context)),
    workers: async () =>
      (await scanAll((cursor) => storage.scanConversations({}, 100, cursor, context))).filter(
        (conversation) => conversation.owner !== undefined,
      ),
    entries,
    submissions: (conversationId) =>
      scanAll((cursor) =>
        storage.scanSubmissions(
          { conversationId: asConversationId(conversationId) },
          100,
          cursor,
          context,
        ),
      ),
    task: (id) => storage.task(asTaskId(id), context),
    agent: async (conversationId) => {
      const records = await scanAll((cursor) =>
        storage.scanDocuments(
          {
            scope: { kind: "conversation", conversationId: asConversationId(conversationId) },
            at: "current",
          },
          100,
          cursor,
          context,
        ),
      );
      const record = records.find((candidate) => candidate.kind === "pi.agent");
      if (record === undefined) return undefined;
      return (await storage.document(record.id, "current", context))?.value;
    },
    toolResults: async (conversationId) =>
      (await entries(conversationId)).flatMap((entry) => {
        if (!ToolResultEntry.is(entry)) return [];
        const message = entry.model?.[0];
        if (message?.role !== "toolResult") return [];
        const text = message.content
          .map((item) => (item.type === "text" ? item.text : ""))
          .join("|");
        return [{ message, text, diagnostics: entry.data.diagnostics }];
      }),
  };
  try {
    return await read(view);
  } finally {
    await storage.close(context);
  }
}

/** Every tool-result text of every worker conversation in the store. */
export async function allWorkerResultTexts(storeDir: string): Promise<string[]> {
  return withStore(storeDir, async (view) => {
    const texts: string[] = [];
    for (const worker of await view.workers()) {
      for (const result of await view.toolResults(worker.id)) texts.push(result.text);
    }
    return texts;
  });
}

// ── binding-level opens and crashes ─────────────────────────────────────────────────────────────

/**
 * Open a Harness over `storage` for a composed program — its registry, models and env, every
 * `onReport` into `reports` — and its root (never resumed). Closed after the test unless
 * abandoned.
 */
export async function openProgramHarness(
  t: TestContext,
  storage: Storage,
  composition: Composition,
  reports: Reported[],
): Promise<Opened> {
  const harness = await Harness.open(
    storage,
    {
      models: composition.models ?? createModels(),
      registry: composition.registry,
      ...(composition.env === undefined ? {} : { env: composition.env }),
      onReport: (error, info) => {
        reports.push({ error, info });
      },
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
  const root = await harness.root(context);
  return {
    harness,
    root,
    dispose,
    abandon: () => {
      abandoned = true;
    },
  };
}

/** `openProgramHarness` over the closed store at `storeDir` (the Harness closes the storage). */
export async function openStoreHarness(
  t: TestContext,
  storeDir: string,
  composition: Composition,
  reports: Reported[] = [],
): Promise<Opened> {
  const storage = await openNodeSqliteStorage(join(storeDir, STORE_DATABASE));
  return openProgramHarness(t, storage, composition, reports);
}

/**
 * `crashable` over `inner`, plus a crash right after the first landed commit whose writes match
 * `predicate`: that commit reaches the backend, and its acknowledgement never returns. `crashed`
 * resolves once it fired.
 */
export function crashAfterCommit(
  t: TestContext,
  inner: Storage,
  predicate: (writes: readonly StorageWrite[]) => boolean,
): { storage: Storage; crash(): void; crashed: Promise<void> } {
  const store = crashable(t, inner);
  let fire!: () => void;
  const crashed = new Promise<void>((resolve) => {
    fire = resolve;
  });
  let fired = false;
  const storage = new Proxy(store.storage, {
    get(target, property) {
      const value: unknown = Reflect.get(target, property, target);
      if (property !== "commit" || typeof value !== "function") {
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (writes: readonly StorageWrite[], callContext: Context) => {
        const seq: unknown = await Reflect.apply(value, target, [writes, callContext]);
        if (!fired && predicate(writes)) {
          fired = true;
          store.crash();
          fire();
          return new Promise(() => {});
        }
        return seq;
      };
    },
  });
  return { storage, crash: store.crash, crashed };
}

/** Whether `writes` create a document of `kind` keyed `key`. */
export function createsDocument(
  writes: readonly StorageWrite[],
  kind: string,
  key: string,
): boolean {
  return writes.some(
    (write) =>
      write.type === "document.create" && write.record.kind === kind && write.record.key === key,
  );
}

/** Whether `writes` write a submission whose request id is `requestId`. */
export function writesSubmission(writes: readonly StorageWrite[], requestId: string): boolean {
  return writes.some((write) => write.type === "submission" && write.value.requestId === requestId);
}

/** Assert no stray request, and `leftover` steps left per role. */
export function assertScript(
  script: RoleScript,
  expected: Partial<Record<Role, { readonly consumed?: number; readonly leftover?: number }>>,
): void {
  assert.equal(script.strays(), 0, "no stray model request");
  for (const role of ROLES) {
    const want = expected[role];
    if (want?.consumed !== undefined) {
      assert.equal(script.consumed(role), want.consumed, `role ${role} consumed`);
    }
    if (want?.leftover !== undefined) {
      assert.equal(script.leftover(role), want.leftover, `role ${role} leftover`);
    }
  }
}
