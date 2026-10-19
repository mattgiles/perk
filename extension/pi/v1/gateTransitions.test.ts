// The gate-transition projection: one notice sentence per held arm (and none for applied), the
// display-only fold of a multiline error (the result keeps it raw), the best-effort reporter (a
// throwing surface degrades to one stderr line and the helper still returns), and the D1a slice
// that reports a held release once under scope `read-only` and always returns the transition.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { GateTransition } from "../../substrate/toolPolicy.ts";
import { fakeGating } from "../../testing/harness.ts";
import { approvalGateFor, gateTransitionNotice, reportGateTransition } from "./gateTransitions.ts";

const APPLIED_EXIT: GateTransition = {
  status: "applied",
  requested: "read-write",
  access: "read-write",
};
const RESTRICTED: GateTransition = {
  status: "restricted",
  requested: "read-write",
  access: "read-only",
};
const PERSIST_FAILED_ENTER: GateTransition = {
  status: "failed",
  requested: "read-only",
  access: "read-only",
  step: "persist",
  error: "disk full",
};
const INSTALL_FAILED_EXIT: GateTransition = {
  status: "failed",
  requested: "read-write",
  access: "read-only",
  step: "install",
  error: "toolset",
};

type Notified = { message: string; type?: string };

function fakeCtx(opts: { throwing?: boolean } = {}): ExtensionContext & { notified: Notified[] } {
  const notified: Notified[] = [];
  const ctx = {
    hasUI: true,
    mode: "tui",
    notified,
    ui: {
      notify(message: string, type?: string) {
        if (opts.throwing) throw new Error("notify exploded");
        notified.push({ message, type });
      },
    },
  };
  return ctx as unknown as ExtensionContext & { notified: Notified[] };
}

function captureStderr<T>(run: () => T): { value: T; lines: string[] } {
  const original = console.error;
  const lines: string[] = [];
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    return { value: run(), lines };
  } finally {
    console.error = original;
  }
}

test("gateTransitionNotice: applied has no notice", () => {
  assert.equal(gateTransitionNotice(APPLIED_EXIT), null);
  assert.equal(
    gateTransitionNotice({ status: "applied", requested: "read-only", access: "read-only" }),
    null,
  );
});

test("gateTransitionNotice: restricted is a warning naming the runner restriction floor", () => {
  assert.deepEqual(gateTransitionNotice(RESTRICTED), {
    severity: "warning",
    message:
      "the read-only gate stays on — this session carries a runner restriction floor that no in-session gesture lifts",
  });
});

test("gateTransitionNotice: a persist-failed enter carries the unverified-persisted-mode tail", () => {
  assert.deepEqual(gateTransitionNotice(PERSIST_FAILED_ENTER), {
    severity: "error",
    message:
      "could not enter read-only (mode persistence failed: disk full) — the session is read-only; the persisted mode is unverified (the next session start re-syncs from the branch)",
  });
});

test("gateTransitionNotice: an install-failed exit has no persistence tail", () => {
  assert.deepEqual(gateTransitionNotice(INSTALL_FAILED_EXIT), {
    severity: "error",
    message:
      "could not release the read-only gate (tool reconciliation failed: toolset) — the session is read-only",
  });
});

test("gateTransitionNotice folds a multiline error for display; the result keeps it raw", () => {
  const t: GateTransition = { ...INSTALL_FAILED_EXIT, error: "line1\nline2" };
  const notice = gateTransitionNotice(t);
  assert.ok(notice);
  assert.match(notice.message, /\(tool reconciliation failed: line1 line2\)/);
  assert.doesNotMatch(notice.message, /[\r\n]/);
  assert.equal(t.status === "failed" ? t.error : "", "line1\nline2", "the result stays raw");
  const crlf = gateTransitionNotice({ ...INSTALL_FAILED_EXIT, error: "a  \r\n\r\n  b\rc" });
  assert.match(crlf?.message ?? "", /failed: a b c\)/);
});

test("reportGateTransition reports a held transition once with scope and suffix; nothing on applied", () => {
  const ctx = fakeCtx();
  const notice = reportGateTransition(
    ctx,
    "gist-save",
    RESTRICTED,
    " — the save turn was not started",
  );
  assert.deepEqual(notice, gateTransitionNotice(RESTRICTED));
  assert.deepEqual(ctx.notified, [
    {
      message:
        "perk: gist-save — the read-only gate stays on — this session carries a runner restriction floor that no in-session gesture lifts — the save turn was not started",
      type: "warning",
    },
  ]);
  assert.equal(reportGateTransition(ctx, "gist-save", APPLIED_EXIT), null);
  assert.equal(ctx.notified.length, 1, "applied reports nothing");
});

test("reportGateTransition swallows a throwing surface into one stderr line and still returns", () => {
  const ctx = fakeCtx({ throwing: true });
  const { value, lines } = captureStderr(() =>
    reportGateTransition(ctx, "read-only", INSTALL_FAILED_EXIT),
  );
  assert.deepEqual(value, gateTransitionNotice(INSTALL_FAILED_EXIT));
  assert.deepEqual(lines, [
    "perk: read-only — could not release the read-only gate (tool reconciliation failed: toolset) — the session is read-only",
  ]);
});

test("approvalGateFor reports a held release once under scope read-only and returns it", () => {
  const ctx = fakeCtx();
  const gating = fakeGating(true, { exit: RESTRICTED });
  const gate = approvalGateFor(gating, ctx);
  assert.equal(gate.isActive(), true);
  assert.deepEqual(gate.exit(), RESTRICTED);
  assert.equal(gating.exits, 1);
  assert.equal(ctx.notified.length, 1);
  assert.match(ctx.notified[0]?.message ?? "", /^perk: read-only — the read-only gate stays on/);
});

test("approvalGateFor reports nothing on an applied release", () => {
  const ctx = fakeCtx();
  const gating = fakeGating(true);
  assert.deepEqual(approvalGateFor(gating, ctx).exit(), APPLIED_EXIT);
  assert.equal(gating.exits, 1);
  assert.deepEqual(ctx.notified, []);
});
