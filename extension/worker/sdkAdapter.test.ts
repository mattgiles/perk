// Fully-offline coverage for the private SDK adapter's owned helpers: the SDK→perk event
// translation (translateEvent), the drive-session handle's bind/rebind structural contract, and
// the model/auth resolution pair (resolveAuth over the nominal selection; resolveWorkerModel
// with the injected stub runtime — deterministic, no ModelRuntime.create host reads). The
// seam-side policy fold and the drive orchestration are covered in stageExecution.test.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createDriveSession,
  type DriveEvent,
  type DriveSessionLike,
  resolveAuth,
  resolveWorkerModel,
  type StageEvent,
  translateEvent,
  WorkerModelSelection,
} from "./sdkAdapter.ts";

// --- pure: translateEvent -------------------------------------------------------------------------

test("translateEvent: turn_end → turn_ended with the clamped input+output sum", () => {
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 10, output: 5 } },
    }),
    { kind: "turn_ended", freshTokens: 15 },
  );
  // Negative components clamp to 0; absent usage sums to 0.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 3, output: -9 } },
    }),
    { kind: "turn_ended", freshTokens: 3 },
  );
  assert.deepEqual(translateEvent({ type: "turn_end", message: { role: "assistant" } }), {
    kind: "turn_ended",
    freshTokens: 0,
  });
});

test("translateEvent: usage.reasoning is NOT summed — it is a subset of output on every pi-ai provider", () => {
  // The double-count pin: pi-ai normalizes `reasoning` as a breakdown already inside `output`
  // (anthropic thinking_tokens, google thoughtsTokenCount, openai reasoning_tokens — verified
  // @ 0.80.5), so the fresh-work sum stays `input + output` exactly.
  assert.deepEqual(
    translateEvent({
      type: "turn_end",
      message: { role: "assistant", usage: { input: 10, output: 20, reasoning: 15 } },
    }),
    { kind: "turn_ended", freshTokens: 30 },
  );
});

test("translateEvent: tool_execution_end → tool_ended (details.ok wins, !isError fallback, error text)", () => {
  assert.deepEqual(
    translateEvent({
      type: "tool_execution_end",
      toolName: "submit",
      result: { details: { ok: true, pr: { number: 1, url: "u" } } },
    }),
    {
      kind: "tool_ended",
      tool: "submit",
      ok: true,
      details: { ok: true, pr: { number: 1, url: "u" } },
      errorText: null,
    },
  );
  // No details.ok boolean → fall back to !isError; no details block → null.
  assert.deepEqual(
    translateEvent({ type: "tool_execution_end", toolName: "read", isError: false }),
    { kind: "tool_ended", tool: "read", ok: true, details: null, errorText: null },
  );
  // Failure carries pre-cap error text: details.error → string result → generic fallback.
  assert.deepEqual(
    translateEvent({
      type: "tool_execution_end",
      toolName: "submit",
      isError: true,
      result: { details: { ok: false, error: "boom" } },
    }),
    {
      kind: "tool_ended",
      tool: "submit",
      ok: false,
      details: { ok: false, error: "boom" },
      errorText: "boom",
    },
  );
  assert.deepEqual(
    translateEvent({ type: "tool_execution_end", toolName: "bash", isError: true }),
    {
      kind: "tool_ended",
      tool: "bash",
      ok: false,
      details: null,
      errorText: "tool bash failed",
    },
  );
});

test("translateEvent: assistant message_end with stopReason error → model_errored; others → null", () => {
  assert.deepEqual(
    translateEvent({
      type: "message_end",
      message: { role: "assistant", stopReason: "error", errorMessage: "net" },
    }),
    { kind: "model_errored", message: "net" },
  );
  assert.deepEqual(
    translateEvent({ type: "message_end", message: { role: "assistant", stopReason: "error" } }),
    { kind: "model_errored", message: "model error" },
  );
  // Non-error message_end, non-assistant roles, and unobserved event types translate to null.
  assert.equal(
    translateEvent({ type: "message_end", message: { role: "assistant", stopReason: "stop" } }),
    null,
  );
  assert.equal(
    translateEvent({ type: "message_end", message: { role: "user", stopReason: "error" } }),
    null,
  );
  assert.equal(translateEvent({ type: "agent_settled" }), null);
});

// --- the drive-session handle: bind/rebind structural --------------------------------------------

class FakeSession implements DriveSessionLike {
  bindCalls = 0;
  abortCalls = 0;
  branch: unknown[] = [];
  private listeners: ((e: DriveEvent) => void)[] = [];
  private readonly script: (emit: (e: DriveEvent) => void) => Promise<void> | void;
  constructor(script: (emit: (e: DriveEvent) => void) => Promise<void> | void) {
    this.script = script;
  }
  async bindExtensions(): Promise<void> {
    this.bindCalls++;
  }
  subscribe(listener: (e: DriveEvent) => void): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }
  private emit = (e: DriveEvent): void => {
    for (const l of this.listeners) l(e);
  };
  async prompt(): Promise<void> {
    await this.script(this.emit);
  }
  async abort(): Promise<void> {
    this.abortCalls++;
  }
  dispose(): void {}
  sessionManager = {
    getBranch: (): unknown[] => this.branch,
  };
}

test("createDriveSession: rebindIfReplaced unsubscribes the prior listener (no double-count) and re-binds", async () => {
  const seen: StageEvent[] = [];
  const turn = (emit: (e: DriveEvent) => void) =>
    emit({ type: "turn_end", message: { role: "assistant" } });
  const s1 = new FakeSession(turn);
  const s2 = new FakeSession(turn);
  const runtime: { session: DriveSessionLike; dispose(): void } = {
    session: s1,
    dispose() {},
  };
  const handle = createDriveSession(runtime, (e) => seen.push(e));
  await handle.bind();
  assert.equal(await handle.rebindIfReplaced(), false, "an unchanged session never rebinds");

  runtime.session = s2; // the mid-drive replacement
  assert.equal(await handle.rebindIfReplaced(), true, "a replaced session rebinds");
  // s1's listener is detached: driving s1 must NOT reach the (single) listener.
  await s1.prompt();
  assert.equal(seen.length, 0, "prior listener was unsubscribed on rebind");
  // The live binding is s2: driving it reaches the listener exactly once — translated.
  await s2.prompt();
  assert.deepEqual(seen, [{ kind: "turn_ended", freshTokens: 0 }]);
  assert.equal(s1.bindCalls, 1);
  assert.equal(s2.bindCalls, 1);
  await handle.dispose();
});

test("createDriveSession: abort is idempotent — repeated trips launch exactly one SDK abort", async () => {
  const session = new FakeSession(() => {});
  const handle = createDriveSession({ session, dispose() {} }, () => {});
  handle.abort();
  handle.abort();
  handle.abort();
  assert.equal(session.abortCalls, 1, "later aborts are no-ops once one is retained");
  await handle.dispose();
});

// --- resolveAuth over the nominal selection — the model pick is deferred to the SDK --------------

function snapshotRuntime(
  available: unknown[],
): ConstructorParameters<typeof WorkerModelSelection>[0] {
  return { getAvailableSnapshot: () => available } as never;
}

test("resolveAuth: an explicit-model selection passes through untouched", async () => {
  const explicit = { provider: "anthropic", id: "claude-sonnet-4-5" };
  const selection = new WorkerModelSelection(snapshotRuntime([]), explicit as never);
  const r = await resolveAuth(selection);
  assert.equal(r, selection);
  assert.equal(r?.model, explicit);
});

test("resolveAuth: no explicit model → model stays undefined (the SDK picks at session creation)", async () => {
  // The availability snapshot sorts alphabetically, so pre-pinning [0] would select the OLDEST
  // model of the first provider (a since-removed dated claude-3-5-haiku pin 404'd a remote drive).
  const selection = new WorkerModelSelection(
    snapshotRuntime([{ id: "claude-3-5-haiku-20241022" }, { id: "claude-sonnet-4-5" }]),
  );
  const r = await resolveAuth(selection);
  assert.equal(r, selection);
  assert.equal(r?.model, undefined);
});

test("resolveAuth: no explicit model and an empty catalogue → null (the no_model fail-fast)", async () => {
  const selection = new WorkerModelSelection(snapshotRuntime([]));
  assert.equal(await resolveAuth(selection), null);
});

// --- resolveWorkerModel — `--model` resolves with pi's CLI semantics -----------------------------

// `resolveCliModel` consults `getModels()` + `hasConfiguredAuth()` (NOT the availability
// snapshot): unauthenticated models resolve by design, matching an interactive pi launch.
const SONNET = { provider: "anthropic", id: "claude-sonnet-4-5" };
const HAIKU = { provider: "anthropic", id: "claude-haiku-4-5" };

function stubRuntime(models: unknown[]): NonNullable<Parameters<typeof resolveWorkerModel>[1]> {
  return { getModels: () => models, hasConfiguredAuth: () => true } as never;
}

test("resolveWorkerModel: exact provider/id resolves", async () => {
  const r = await resolveWorkerModel("anthropic/claude-sonnet-4-5", stubRuntime([SONNET, HAIKU]));
  assert.ok(r.ok);
  assert.equal(r.selection.model, SONNET);
  assert.equal(r.selection.thinkingLevel, undefined);
  assert.equal(r.warning, undefined);
});

test("resolveWorkerModel: a bare partial id resolves (fuzzy matching parity)", async () => {
  const r = await resolveWorkerModel("sonnet", stubRuntime([SONNET, HAIKU]));
  assert.ok(r.ok);
  assert.equal(r.selection.model, SONNET);
});

test("resolveWorkerModel: a `:thinking` suffix yields the model + the parsed level", async () => {
  const r = await resolveWorkerModel(
    "anthropic/claude-sonnet-4-5:high",
    stubRuntime([SONNET, HAIKU]),
  );
  assert.ok(r.ok);
  assert.equal(r.selection.model, SONNET);
  assert.equal(r.selection.thinkingLevel, "high");
});

test("resolveWorkerModel: an unknown pattern ⇒ ok:false with an error (fail-fast, never guess)", async () => {
  const r = await resolveWorkerModel("totally-unknown-model-zzz", stubRuntime([SONNET, HAIKU]));
  assert.equal(r.ok, false);
  assert.equal(typeof (r as { error: unknown }).error, "string");
});

test("resolveWorkerModel: undefined raw ⇒ a default-runtime selection (the SDK deferral)", async () => {
  const runtime = stubRuntime([SONNET]);
  const r = await resolveWorkerModel(undefined, runtime);
  assert.ok(r.ok);
  assert.equal(r.selection.model, undefined);
  assert.equal(r.selection.thinkingLevel, undefined);
  assert.equal(r.selection.modelRuntime, runtime);
  assert.equal(r.warning, undefined);
});

test("resolveWorkerModel: '' ≡ omitted (the documented bare `--model` CLI tolerance)", async () => {
  // workerMain's flag grammar yields "" for a bare `--model`; the equivalence is deliberate and
  // pinned here — both arms defer the pick to the SDK at session creation.
  const runtime = stubRuntime([SONNET]);
  const r = await resolveWorkerModel("", runtime);
  assert.ok(r.ok);
  assert.equal(r.selection.model, undefined);
  assert.equal(r.selection.thinkingLevel, undefined);
  assert.equal(r.selection.modelRuntime, runtime);
  assert.equal(r.warning, undefined);
});
