import assert from "node:assert/strict";
import { test } from "node:test";
import { attachReportDetailSink, type ReportTarget, report, type Severity } from "./report.ts";

/** A fake ReportTarget that records every notify call. */
function fakeTarget(
  hasUI: boolean,
  mode?: ReportTarget["mode"],
): {
  target: ReportTarget;
  notifies: { message: string; type?: Severity }[];
} {
  const notifies: { message: string; type?: Severity }[] = [];
  return {
    target: {
      hasUI,
      ...(mode === undefined ? {} : { mode }),
      ui: { notify: (message, type) => notifies.push({ message, type }) },
    },
    notifies,
  };
}

/** Run `fn` with `console.error` stubbed, returning the captured calls. */
function captureStderr(fn: () => void): string[] {
  const calls: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => calls.push(args.map(String).join(" "));
  try {
    fn();
  } finally {
    console.error = original;
  }
  return calls;
}

for (const [name, message, headline] of [
  ["LF", "\n \t \n  first   line\tvalue \nsecond", "first line value"],
  ["CRLF", "\r\n\t\r\n first\t \tline \r\nsecond", "first line"],
  ["bare CR", "\r \t\r first\tline \rsecond", "first line"],
] as const) {
  test(`headline recognizes ${name}, skips blank rows, and normalizes horizontal whitespace`, () => {
    const { target, notifies } = fakeTarget(true, "tui");
    const stderr = captureStderr(() => {
      assert.equal(report(target, "submit", "error", message), `perk: submit — ${message}`);
    });
    assert.deepEqual(notifies, [{ message: `perk: submit — ${headline}`, type: "error" }]);
    assert.deepEqual(stderr, []);
  });
}

test("complete return value preserves continuation bytes exactly", () => {
  const { target } = fakeTarget(true, "print");
  const message = "fetch first\r\n  indented\n\tgit line\rbared";
  captureStderr(() => {
    assert.equal(report(target, "submit", "error", message), `perk: submit — ${message}`);
  });
});

test("all-empty logical rows use the existing prefixed empty-message headline", () => {
  const { target, notifies } = fakeTarget(true);
  const message = "\r\n \t\r";
  captureStderr(() => {
    assert.equal(report(target, "scope", "warning", message), `perk: scope — ${message}`);
  });
  assert.deepEqual(notifies, [{ message: "perk: scope — ", type: "warning" }]);
});

test("headless writes the complete value to stderr exactly once without notifying or sinking", () => {
  const { target, notifies } = fakeTarget(false, "print");
  const details: { text: string; severity: Severity }[] = [];
  attachReportDetailSink(target, (text, severity) => details.push({ text, severity }));
  const message = "kaboom\nfetch and rebase first\nerror: failed to push";
  const stderr = captureStderr(() => {
    report(target, "land", "error", message, { alsoLog: true });
  });
  assert.deepEqual(notifies, []);
  assert.deepEqual(stderr, [`perk: land — ${message}`]);
  assert.deepEqual(details, []);
});

for (const alsoLog of [false, true]) {
  test(`headful RPC notifies with a headline and ${alsoLog ? "does" : "does not"} mirror detail`, () => {
    const { target, notifies } = fakeTarget(true, "rpc");
    const details: { text: string; severity: Severity }[] = [];
    attachReportDetailSink(target, (text, severity) => details.push({ text, severity }));
    const message = "heads   up\ncomplete detail";
    const stderr = captureStderr(() => {
      report(target, "ready", "warning", message, { alsoLog });
    });
    assert.deepEqual(notifies, [{ message: "perk: ready — heads up", type: "warning" }]);
    assert.deepEqual(stderr, alsoLog ? [`perk: ready — ${message}`] : []);
    assert.deepEqual(details, []);
  });
}

for (const mode of ["tui", "print", "json", undefined] as const) {
  test(`headful ${mode ?? "missing"} mode never writes stderr and sinks multiline detail`, () => {
    const { target, notifies } = fakeTarget(true, mode);
    const details: { text: string; severity: Severity }[] = [];
    attachReportDetailSink(target, (text, severity) => details.push({ text, severity }));
    const message = "first line\nsecond line";
    const stderr = captureStderr(() => {
      report(target, "learn", "info", message, { alsoLog: true });
    });
    assert.deepEqual(notifies, [{ message: "perk: learn — first line", type: "info" }]);
    assert.deepEqual(stderr, []);
    assert.deepEqual(details, [{ text: `perk: learn — ${message}`, severity: "info" }]);
  });
}

test("attached detail sink is not called for a single-line message", () => {
  const { target } = fakeTarget(true, "tui");
  const details: string[] = [];
  attachReportDetailSink(target, (text) => details.push(text));
  captureStderr(() => report(target, "scope", "info", "one line"));
  assert.deepEqual(details, []);
});

test("detail sink attachment is scoped to the exact target object", () => {
  const first = fakeTarget(true, "tui").target;
  const second = fakeTarget(true, "tui").target;
  const details: string[] = [];
  attachReportDetailSink(first, (text) => details.push(text));
  captureStderr(() => report(second, "scope", "info", "one\ntwo"));
  assert.deepEqual(details, []);
});

for (const severity of ["info", "warning", "error"] as const) {
  test(`severity ${severity} passes through to notify`, () => {
    const { target, notifies } = fakeTarget(true, "tui");
    captureStderr(() => report(target, "scope", severity, "msg"));
    assert.deepEqual(notifies, [{ message: "perk: scope — msg", type: severity }]);
  });
}
