// whimsical tests — `pickRandom` always returns a member of `messages`; `registerWhimsical`
// registers turn_start/turn_end and routes the label through the headless-safe `setWorkingMessage`
// surfaces seam (a phrase on start, `undefined` on end; no-op when `!hasUI`).

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { messages, pickRandom, registerWhimsical } from "./whimsical.ts";

const savedRandom = Math.random;
afterEach(() => {
  Math.random = savedRandom;
});

type Handler = (event: unknown, ctx: unknown) => Promise<void> | void;

/** A minimal ExtensionAPI fake capturing `pi.on` handlers by event name. */
function fakePi(): { pi: ExtensionAPI; handlers: Map<string, Handler[]> } {
  const handlers = new Map<string, Handler[]>();
  const pi = {
    on(event: string, handler: Handler) {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
    },
  } as unknown as ExtensionAPI;
  return { pi, handlers };
}

/** A fake ctx recording every `setWorkingMessage` argument. */
function fakeCtx(hasUI: boolean): {
  ctx: unknown;
  calls: (string | undefined)[];
} {
  const calls: (string | undefined)[] = [];
  const ctx = {
    hasUI,
    ui: {
      setWorkingMessage(message?: string) {
        calls.push(message);
      },
    },
  };
  return { ctx, calls };
}

test("pickRandom always returns a member of messages, across the full random range", () => {
  for (const r of [0, 0.0001, 0.25, 0.5, 0.75, 0.999999]) {
    Math.random = () => r;
    const picked = pickRandom();
    assert.ok(messages.includes(picked), `pickRandom returned a non-member: ${picked}`);
  }
});

test("registerWhimsical registers turn_start and turn_end", () => {
  const { pi, handlers } = fakePi();
  registerWhimsical(pi);
  assert.equal(handlers.get("turn_start")?.length, 1);
  assert.equal(handlers.get("turn_end")?.length, 1);
});

test("turn_start sets a whimsical phrase; turn_end restores pi's default (undefined)", async () => {
  const { pi, handlers } = fakePi();
  registerWhimsical(pi);
  const { ctx, calls } = fakeCtx(true);

  Math.random = () => 0; // first message
  await handlers.get("turn_start")?.[0]?.({}, ctx);
  await handlers.get("turn_end")?.[0]?.({}, ctx);

  assert.equal(calls.length, 2);
  assert.ok(messages.includes(calls[0] as string), "turn_start did not set a phrase");
  assert.equal(calls[1], undefined, "turn_end did not reset to undefined");
});

test("the setWorkingMessage seam no-ops headlessly (whimsical never touches rich UI)", async () => {
  const { pi, handlers } = fakePi();
  registerWhimsical(pi);
  const { ctx, calls } = fakeCtx(false);

  await handlers.get("turn_start")?.[0]?.({}, ctx);
  await handlers.get("turn_end")?.[0]?.({}, ctx);

  assert.deepEqual(calls, [], "setWorkingMessage was called despite !hasUI");
});
