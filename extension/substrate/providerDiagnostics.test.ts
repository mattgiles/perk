import assert from "node:assert/strict";
import { test } from "node:test";
import {
  decodeProviderDiagnostics,
  PROVIDER_ERROR_KINDS,
  PROVIDER_RETRY_PHASES,
} from "./providerDiagnostics.ts";

// Local literals (the shape of `testing/fakeConflictResolver.ts::providerRetryDiagnostics`) keep
// this Pi-free module's test Pi-free: the shared fixture module imports the Pi SDK.
function providerRetryDiagnostics(phase: "backoff" | "in_flight") {
  return {
    errorCount: 1,
    lastError: { kind: "rate_limited", message: "SECRET provider body", at: 1 },
    retry: { phase, attempt: 2, maxAttempts: 5, delayMs: 8000, scheduledAt: 1 },
  };
}
function providerHistoryDiagnostics() {
  return {
    errorCount: 1,
    lastError: { kind: "rate_limited", message: "SECRET provider body", at: 1 },
  };
}

test("absent or non-object values decode as unavailable (old payloads)", () => {
  for (const value of [undefined, null, [], "backoff", 3, true]) {
    assert.equal(decodeProviderDiagnostics(value), undefined, JSON.stringify(value));
  }
});

test("a count-only snapshot decodes to just the count", () => {
  assert.deepEqual(decodeProviderDiagnostics({ errorCount: 0 }), { errorCount: 0 });
});

test("a backoff snapshot decodes field by field and drops the supplier's message", () => {
  const input = providerRetryDiagnostics("backoff");
  const before = structuredClone(input);
  const decoded = decodeProviderDiagnostics(input);
  assert.deepEqual(decoded, {
    errorCount: 1,
    lastError: { kind: "rate_limited", at: 1 },
    retry: { phase: "backoff", attempt: 2, maxAttempts: 5, delayMs: 8000, scheduledAt: 1 },
  });
  assert.ok(decoded?.lastError);
  assert.equal(Object.hasOwn(decoded.lastError, "message"), false);
  assert.doesNotMatch(JSON.stringify(decoded), /SECRET/);
  assert.notEqual(decoded, input);
  assert.notEqual(decoded?.retry, input.retry);
  assert.deepEqual(input, before, "the input is never mutated");
});

test("an in-flight snapshot and a history-only snapshot decode", () => {
  assert.deepEqual(decodeProviderDiagnostics(providerRetryDiagnostics("in_flight"))?.retry, {
    phase: "in_flight",
    attempt: 2,
    maxAttempts: 5,
    delayMs: 8000,
    scheduledAt: 1,
  });
  assert.deepEqual(decodeProviderDiagnostics(providerHistoryDiagnostics()), {
    errorCount: 1,
    lastError: { kind: "rate_limited", at: 1 },
  });
});

test("unknown extra keys at every level are ignored", () => {
  const input = {
    ...providerRetryDiagnostics("backoff"),
    future: "x",
    lastError: { kind: "unknown", message: "SECRET", at: 2, detail: "y" },
    retry: {
      phase: "in_flight",
      attempt: 1,
      maxAttempts: 1,
      delayMs: 0,
      scheduledAt: 3,
      jitter: 4,
    },
  };
  assert.deepEqual(decodeProviderDiagnostics(input), {
    errorCount: 1,
    lastError: { kind: "unknown", at: 2 },
    retry: { phase: "in_flight", attempt: 1, maxAttempts: 1, delayMs: 0, scheduledAt: 3 },
  });
});

test("a malformed field anywhere makes the whole snapshot unavailable", () => {
  const backoff = providerRetryDiagnostics("backoff");
  const retry = (patch: Record<string, unknown>) => ({
    ...backoff,
    retry: { ...backoff.retry, ...patch },
  });
  const lastError = (patch: Record<string, unknown>) => ({
    ...backoff,
    lastError: { ...backoff.lastError, ...patch },
  });
  const rows: [string, unknown][] = [
    ["errorCount negative", { ...backoff, errorCount: -1 }],
    ["errorCount fractional", { ...backoff, errorCount: 1.5 }],
    ["errorCount a string", { ...backoff, errorCount: "1" }],
    ["errorCount missing", { retry: backoff.retry }],
    ["lastError not an object", { ...backoff, lastError: "boom" }],
    ["lastError.kind outside the vocabulary", lastError({ kind: "billing" })],
    ["lastError.at NaN", lastError({ at: Number.NaN })],
    ["retry.phase outside the vocabulary", retry({ phase: "sleeping" })],
    ["retry.attempt zero", retry({ attempt: 0 })],
    ["retry.attempt fractional", retry({ attempt: 1.5 })],
    ["retry.maxAttempts below attempt", retry({ attempt: 3, maxAttempts: 2 })],
    ["retry.delayMs negative", retry({ delayMs: -1 })],
    ["retry.delayMs infinite", retry({ delayMs: Number.POSITIVE_INFINITY })],
    ["retry.scheduledAt a string", retry({ scheduledAt: "now" })],
    ["retry an array", { ...backoff, retry: [backoff.retry] }],
  ];
  for (const [name, value] of rows) {
    assert.equal(decodeProviderDiagnostics(value), undefined, name);
  }
});

test("the closed vocabularies mirror the supplier's declared unions (re-read at each bump)", () => {
  // pi-subagents 0.81.0 `src/api/delegation.d.ts::SubagentDelegationProviderDiagnostics`.
  assert.deepEqual([...PROVIDER_ERROR_KINDS], ["rate_limited", "transient_other", "unknown"]);
  assert.deepEqual([...PROVIDER_RETRY_PHASES], ["backoff", "in_flight"]);
});
