import assert from "node:assert/strict";
import { test } from "node:test";
import { type ReportTarget, report, type Severity } from "./report.ts";

/** A fake ReportTarget that records every notify call. */
function fakeTarget(hasUI: boolean): {
  target: ReportTarget;
  notifies: { message: string; type?: Severity }[];
} {
  const notifies: { message: string; type?: Severity }[] = [];
  return {
    target: { hasUI, ui: { notify: (message, type) => notifies.push({ message, type }) } },
    notifies,
  };
}

/** Run `fn` with `console.error` stubbed, returning the captured lines. */
function captureStderr(fn: () => void): string[] {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => lines.push(args.map(String).join(" "));
  try {
    fn();
  } finally {
    console.error = original;
  }
  return lines;
}

test("headful, no alsoLog: notifies once, no stderr", () => {
  const { target, notifies } = fakeTarget(true);
  const stderr = captureStderr(() => {
    const out = report(target, "submit", "error", "boom");
    assert.equal(out, "perk: submit — boom");
  });
  assert.deepEqual(notifies, [{ message: "perk: submit — boom", type: "error" }]);
  assert.deepEqual(stderr, []);
});

test("headless, no alsoLog: stderr once, no notify", () => {
  const { target, notifies } = fakeTarget(false);
  const stderr = captureStderr(() => {
    report(target, "land", "error", "kaboom");
  });
  assert.deepEqual(notifies, []);
  assert.deepEqual(stderr, ["perk: land — kaboom"]);
});

test("headful, alsoLog: both notify and stderr", () => {
  const { target, notifies } = fakeTarget(true);
  const stderr = captureStderr(() => {
    report(target, "ready", "warning", "heads up", { alsoLog: true });
  });
  assert.deepEqual(notifies, [{ message: "perk: ready — heads up", type: "warning" }]);
  assert.deepEqual(stderr, ["perk: ready — heads up"]);
});

test("headless, alsoLog: stderr exactly once (no double-log)", () => {
  const { target, notifies } = fakeTarget(false);
  const stderr = captureStderr(() => {
    report(target, "learn", "error", "oops", { alsoLog: true });
  });
  assert.deepEqual(notifies, []);
  assert.deepEqual(stderr, ["perk: learn — oops"]);
});

test("return value equals the prefixed string", () => {
  const { target } = fakeTarget(false);
  captureStderr(() => {
    assert.equal(report(target, "objective", "info", "hi"), "perk: objective — hi");
  });
});

for (const severity of ["info", "warning", "error"] as const) {
  test(`severity ${severity} passes through to notify`, () => {
    const { target, notifies } = fakeTarget(true);
    captureStderr(() => report(target, "scope", severity, "msg"));
    assert.deepEqual(notifies, [{ message: "perk: scope — msg", type: severity }]);
  });
}
