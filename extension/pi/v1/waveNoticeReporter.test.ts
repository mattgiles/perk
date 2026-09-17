// The once-per-activation wave-notice reporter: the tested prose names the method, the superseded
// reply, the doctor check and the /reload caveat; the first notice reports ONE warning through
// the retained ctx, later ones are dropped, a later setContext never resets the latch, and a
// notice with no ctx retained goes to stderr and still latches.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReportTarget } from "../../surfaces/report.ts";
import type { WaveNotice } from "../../waves/reportWave.ts";
import { createWaveNoticeReporter, renderWaveNotice } from "./waveNoticeReporter.ts";

const NOTICE: WaveNotice = {
  method: "spawn",
  superseded: "no_active_session: No active extension context for subagent RPC.",
};

function fakeTarget(): ReportTarget & { notified: { message: string; type?: string }[] } {
  const notified: { message: string; type?: string }[] = [];
  return {
    hasUI: true,
    mode: "tui",
    notified,
    ui: {
      notify(message, type) {
        notified.push({ message, type });
      },
    },
  };
}

function captureStderr(run: () => void): string[] {
  const original = console.error;
  const lines: string[] = [];
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    run();
  } finally {
    console.error = original;
  }
  return lines;
}

test("renderWaveNotice names the method, the superseded reply, the doctor check and the /reload caveat", () => {
  const text = renderWaveNotice(NOTICE);
  assert.match(text, /perk's spawn request/);
  assert.match(text, /`no_active_session: No active extension context for subagent RPC\.`/);
  assert.match(text, /subagent-package-scope/);
  assert.match(text, /\/reload does not clear it/);
  assert.match(text, /once per extension activation/);
  assert.match(text, /duplicate pi-subagents extension/);
  assert.equal(text.split("\n").length, 1, "one logical line — a headline, no detail sink needed");
});

test("the first notice reports one warning through the retained ctx; the second is dropped", () => {
  const reporter = createWaveNoticeReporter();
  const target = fakeTarget();
  reporter.setContext(target);
  const stderr = captureStderr(() => {
    reporter.onNotice(NOTICE);
    reporter.onNotice({ ...NOTICE, method: "stop" });
  });
  assert.equal(target.notified.length, 1);
  assert.equal(target.notified[0]?.type, "warning");
  assert.match(target.notified[0]?.message ?? "", /^perk: waves — A duplicate pi-subagents/);
  assert.match(target.notified[0]?.message ?? "", /perk's spawn request/);
  assert.deepEqual(stderr, [], "a headful tui target never leaks to stderr");
});

test("setContext after the latch does not reset it", () => {
  const reporter = createWaveNoticeReporter();
  const first = fakeTarget();
  reporter.setContext(first);
  reporter.onNotice(NOTICE);
  const second = fakeTarget();
  reporter.setContext(second);
  reporter.onNotice(NOTICE);
  assert.equal(first.notified.length, 1);
  assert.equal(second.notified.length, 0);
});

test("with no ctx retained the full line goes to stderr and still latches", () => {
  const reporter = createWaveNoticeReporter();
  const stderr = captureStderr(() => {
    reporter.onNotice(NOTICE);
  });
  assert.equal(stderr.length, 1);
  assert.match(stderr[0] ?? "", /^perk: waves — A duplicate pi-subagents extension/);
  assert.match(stderr[0] ?? "", /subagent-package-scope/);

  const target = fakeTarget();
  reporter.setContext(target);
  const later = captureStderr(() => {
    reporter.onNotice(NOTICE);
  });
  assert.deepEqual(later, []);
  assert.equal(
    target.notified.length,
    0,
    "the pre-ctx notice consumed the activation's one warning",
  );
});

test("a headless retained ctx reports through report()'s stderr arm", () => {
  const reporter = createWaveNoticeReporter();
  const target: ReportTarget = { hasUI: false, ui: { notify: () => assert.fail("no UI") } };
  reporter.setContext(target);
  const stderr = captureStderr(() => {
    reporter.onNotice(NOTICE);
  });
  assert.equal(stderr.length, 1);
  assert.match(stderr[0] ?? "", /^perk: waves — /);
});
