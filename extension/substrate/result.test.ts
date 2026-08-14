import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReportTarget, Severity } from "../surfaces/report.ts";
import { failFor, ok, type Result } from "./result.ts";

/** A fake ReportTarget that records every notify call (mirrors report.test.ts). */
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

test("ok() builds a single text block + ok:true details", () => {
  const result = ok("did the thing", { pr: { number: 7 }, branch: "plan-7" });
  assert.deepEqual(result.content, [{ type: "text", text: "did the thing" }]);
  assert.deepEqual(result.details, { ok: true, pr: { number: 7 }, branch: "plan-7" });
});

test("ok() omits the terminate key entirely when not requested", () => {
  assert.equal("terminate" in ok("t", {}), false);
  assert.equal("terminate" in ok("t", {}, {}), false);
  assert.equal("terminate" in ok("t", {}, { terminate: false }), false);
});

test("ok() includes terminate: true iff requested", () => {
  const result = ok("t", { x: 1 }, { terminate: true });
  assert.equal(result.terminate, true);
});

test("failFor() builds the canonical soft failure with no terminate key", () => {
  const { target } = fakeTarget(true);
  const fail = failFor(target, "submit");
  captureStderr(() => {
    const result = fail("boom", "exec_failed");
    assert.deepEqual(result.content, [{ type: "text", text: "submit failed: boom" }]);
    assert.deepEqual(result.details, { ok: false, error: "boom", error_type: "exec_failed" });
    assert.equal("terminate" in result, false);
  });
});

test("failFor() label defaults to scope; explicit label overrides content only", () => {
  const { target, notifies } = fakeTarget(true);
  const fail = failFor(target, "address", "finalize_address");
  captureStderr(() => {
    const result = fail("nope", "bad_input");
    assert.equal(result.content[0]?.text, "finalize_address failed: nope");
  });
  // The report scope stays "address" even though the content label differs.
  assert.deepEqual(notifies, [{ message: "perk: address — nope", type: "error" }]);
});

test("failFor() headful print: headline only, complete soft result, no raw stderr", () => {
  const { target, notifies } = fakeTarget(true, "print");
  const fail = failFor(target, "land");
  const message = "kaboom\nfetch and rebase first\nerror: failed to push";
  let result: ReturnType<typeof fail> | undefined;
  const stderr = captureStderr(() => {
    result = fail(message, "github_error");
  });
  assert.deepEqual(notifies, [{ message: "perk: land — kaboom", type: "error" }]);
  assert.deepEqual(stderr, []);
  assert.deepEqual(result?.content, [{ type: "text", text: `land failed: ${message}` }]);
  assert.deepEqual(result?.details, {
    ok: false,
    error: message,
    error_type: "github_error",
  });
});

test("failFor() headful RPC: headline plus complete stderr mirror", () => {
  const { target, notifies } = fakeTarget(true, "rpc");
  const fail = failFor(target, "land");
  const message = "kaboom\ncomplete detail";
  const stderr = captureStderr(() => {
    fail(message, "github_error");
  });
  assert.deepEqual(notifies, [{ message: "perk: land — kaboom", type: "error" }]);
  assert.deepEqual(stderr, [`perk: land — ${message}`]);
});

test("failFor() headless: stderr exactly once, no notify", () => {
  const { target, notifies } = fakeTarget(false);
  const fail = failFor(target, "learn");
  const stderr = captureStderr(() => {
    fail("oops", "scratch_failed");
  });
  assert.deepEqual(notifies, []);
  assert.deepEqual(stderr, ["perk: learn — oops"]);
});

test("failFor() extras spread into the fail details after error/error_type", () => {
  const { target } = fakeTarget(false);
  const fail = failFor<{ attempts: { flow: string; attempt: number }[] }>(target, "run_learn_wave");
  captureStderr(() => {
    const result = fail("wave failed", "run-failed", {
      attempts: [{ flow: "learn", attempt: 1 }],
    });
    assert.deepEqual(result.details, {
      ok: false,
      error: "wave failed",
      error_type: "run-failed",
      attempts: [{ flow: "learn", attempt: 1 }],
    });
    // Extras never leak into the content text.
    assert.deepEqual(result.content, [
      { type: "text", text: "run_learn_wave failed: wave failed" },
    ]);
  });
});

test("Result discriminates on details.ok (compile-time narrowing exercise)", () => {
  const pick = (result: Result<{ x: number }>): number | string =>
    result.details.ok ? result.details.x : result.details.error;
  assert.equal(pick(ok("t", { x: 42 })), 42);
  const { target } = fakeTarget(false);
  captureStderr(() => {
    assert.equal(pick(failFor(target, "scope")("bad", "t")), "bad");
  });
});
