// Offline, deterministic tests for the console.error interceptor: capture + join, debounce restore
// (with reset-on-line), the zero-line case, restore idempotency, and the never-clobber-a-newer-
// patcher guard. The fake clock (injected schedule/clearScheduled) drives all timing.

import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { interceptConsoleError } from "./consoleCapture.ts";

/** A deterministic timer: schedule returns an id; fire(id)/advance run due callbacks. */
function fakeClock() {
  let now = 0;
  let nextId = 1;
  const pending = new Map<number, { fn: () => void; due: number }>();
  return {
    schedule: (fn: () => void, ms: number): unknown => {
      const id = nextId++;
      pending.set(id, { fn, due: now + ms });
      return id;
    },
    clearScheduled: (handle: unknown): void => {
      pending.delete(handle as number);
    },
    advance: (ms: number): void => {
      now += ms;
      for (const [id, t] of [...pending]) {
        if (t.due <= now) {
          pending.delete(id);
          t.fn();
        }
      }
    },
    get size() {
      return pending.size;
    },
  };
}

let realError: typeof console.error;
beforeEach(() => {
  realError = console.error;
});
afterEach(() => {
  console.error = realError;
});

test("captures single- and multi-arg console.error into the sink, joined by spaces", () => {
  const clock = fakeClock();
  const lines: string[] = [];
  const interceptor = interceptConsoleError((line) => lines.push(line), {
    quietMs: 1500,
    schedule: clock.schedule,
    clearScheduled: clock.clearScheduled,
  });

  console.error("a");
  console.error("a", "b");
  assert.deepEqual(lines, ["a", "a b"]);

  interceptor.restore();
  console.error = realError; // restore() reclaimed the slot; this is a no-op assertion guard
  console.error("after");
  assert.deepEqual(lines, ["a", "a b"], "no forwarding after restore");
});

test("debounce: restores after quietMs of silence; a line before the deadline resets the timer", () => {
  const clock = fakeClock();
  const lines: string[] = [];
  interceptConsoleError((line) => lines.push(line), {
    quietMs: 1500,
    schedule: clock.schedule,
    clearScheduled: clock.clearScheduled,
  });
  const installed = console.error;

  console.error("setup 1");
  clock.advance(1000); // under quietMs
  assert.equal(console.error, installed, "still installed before the deadline");

  console.error("setup 2"); // resets the timer
  clock.advance(1000); // 1000ms since the reset — still under quietMs
  assert.equal(console.error, installed, "reset kept it installed");

  clock.advance(500); // now 1500ms since the last line
  assert.equal(console.error, realError, "restored after quietMs of silence");
  assert.deepEqual(lines, ["setup 1", "setup 2"]);
});

test("zero-line case: restores after quietMs even with no captured lines", () => {
  const clock = fakeClock();
  interceptConsoleError(() => {}, {
    quietMs: 1500,
    schedule: clock.schedule,
    clearScheduled: clock.clearScheduled,
  });
  assert.notEqual(console.error, realError, "installed on entry");
  clock.advance(1500);
  assert.equal(console.error, realError, "restored with no lines");
});

test("restore() is idempotent", () => {
  const clock = fakeClock();
  const interceptor = interceptConsoleError(() => {}, {
    quietMs: 1500,
    schedule: clock.schedule,
    clearScheduled: clock.clearScheduled,
  });
  interceptor.restore();
  assert.equal(console.error, realError);
  interceptor.restore(); // second call is a no-op
  assert.equal(console.error, realError);
});

test("restore() does not clobber a newer patcher installed after ours", () => {
  const clock = fakeClock();
  const interceptor = interceptConsoleError(() => {}, {
    quietMs: 1500,
    schedule: clock.schedule,
    clearScheduled: clock.clearScheduled,
  });
  const newer = (..._args: unknown[]) => {};
  console.error = newer;
  interceptor.restore();
  assert.equal(console.error, newer, "left the newer patcher untouched");
});
