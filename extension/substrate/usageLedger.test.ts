// The once-counted usage ledger: the fold matrix (records once, excluded subsets, clamping,
// record-vs-absent), the branch usage census over every owned boundary, and the dispatch census
// (selection vs physical identity, failed responses excluded but counted).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addUsageRecord,
  branchModelCensus,
  branchUsageCensus,
  emptyUsageTotals,
  formatUsd,
  freshTokens,
  isSuccessfulResponse,
  mergeUsageTotals,
  physicalKey,
} from "./usageLedger.ts";

/** A full Pi-shaped usage record. */
function usage(fields: {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  reasoning?: number;
  cacheWrite1h?: number;
  cost?: number;
}): Record<string, unknown> {
  const cost = fields.cost ?? 0;
  return {
    input: fields.input ?? 0,
    output: fields.output ?? 0,
    cacheRead: fields.cacheRead ?? 0,
    cacheWrite: fields.cacheWrite ?? 0,
    ...(fields.reasoning !== undefined ? { reasoning: fields.reasoning } : {}),
    ...(fields.cacheWrite1h !== undefined ? { cacheWrite1h: fields.cacheWrite1h } : {}),
    totalTokens: 999_999,
    cost: { input: 9, output: 9, cacheRead: 9, cacheWrite: 9, total: cost },
  };
}

test("addUsageRecord: an assistant record plus two tool results (nested already folded) count 3 records once", () => {
  const totals = emptyUsageTotals();
  addUsageRecord(totals, usage({ input: 10, output: 5, cacheRead: 100, cacheWrite: 7, cost: 0.5 }));
  addUsageRecord(totals, usage({ input: 700, output: 300, cacheRead: 40, cost: 0.0125 }));
  addUsageRecord(totals, usage({ input: 1, output: 1 }));
  assert.equal(totals.records, 3);
  assert.equal(totals.input, 711);
  assert.equal(totals.output, 306);
  assert.equal(totals.cacheRead, 140);
  assert.equal(totals.cacheWrite, 7);
  assert.ok(Math.abs(totals.cost - 0.5125) < 1e-12);
  assert.equal(freshTokens(totals), 1_017, "fresh = input + output");
});

test("addUsageRecord: reasoning and cacheWrite1h are never added (subsets of output / cacheWrite)", () => {
  const totals = emptyUsageTotals();
  addUsageRecord(
    totals,
    usage({ input: 10, output: 20, reasoning: 15, cacheWrite: 30, cacheWrite1h: 30 }),
  );
  assert.deepEqual(totals, {
    records: 1,
    input: 10,
    output: 20,
    cacheRead: 0,
    cacheWrite: 30,
    cost: 0,
  });
});

test("addUsageRecord: negatives and non-finite values clamp to 0; the record still counts", () => {
  const totals = emptyUsageTotals();
  addUsageRecord(totals, {
    input: -5,
    output: Number.NaN,
    cacheRead: Number.POSITIVE_INFINITY,
    cacheWrite: "12",
    cost: { total: -1 },
  });
  addUsageRecord(totals, { input: 3, cost: { total: Number.NaN } });
  addUsageRecord(totals, { output: 4, cost: 7 });
  assert.deepEqual(totals, {
    records: 3,
    input: 3,
    output: 4,
    cacheRead: 0,
    cacheWrite: 0,
    cost: 0,
  });
});

test("addUsageRecord: `{}` is a record; absent / null / primitive / array usage is not", () => {
  const totals = emptyUsageTotals();
  for (const notARecord of [undefined, null, 0, "usage", true, []]) {
    addUsageRecord(totals, notARecord);
  }
  assert.equal(totals.records, 0, "nothing counted");
  addUsageRecord(totals, {});
  assert.deepEqual(totals, { ...emptyUsageTotals(), records: 1 });
});

test("addUsageRecord: a recorded zero cost stays a number (an unpriced model)", () => {
  const totals = emptyUsageTotals();
  addUsageRecord(totals, usage({ input: 1, output: 1, cost: 0 }));
  assert.equal(totals.records, 1);
  assert.equal(totals.cost, 0);
  assert.equal(formatUsd(totals.cost), "$0.0000");
});

test("mergeUsageTotals: folds every field, records included", () => {
  const target = emptyUsageTotals();
  addUsageRecord(target, usage({ input: 1, output: 2, cacheRead: 3, cacheWrite: 4, cost: 0.25 }));
  const source = emptyUsageTotals();
  addUsageRecord(source, usage({ input: 10, output: 20, cacheRead: 30, cacheWrite: 40, cost: 1 }));
  addUsageRecord(source, {});
  mergeUsageTotals(target, source);
  assert.deepEqual(target, {
    records: 3,
    input: 11,
    output: 22,
    cacheRead: 33,
    cacheWrite: 44,
    cost: 1.25,
  });
});

test("formatUsd: four decimals with a dollar sign", () => {
  assert.equal(formatUsd(0.0123), "$0.0123");
  assert.equal(formatUsd(12.5), "$12.5000");
});

test("physicalKey: provider/model; →responseModel only when it differs; null without both ids", () => {
  assert.equal(physicalKey({ provider: "anthropic", model: "claude-x" }), "anthropic/claude-x");
  assert.equal(
    physicalKey({ provider: "openai", model: "gpt-5", responseModel: "gpt-5-2026-01-01" }),
    "openai/gpt-5→gpt-5-2026-01-01",
  );
  assert.equal(
    physicalKey({ provider: "openai", model: "gpt-5", responseModel: "gpt-5" }),
    "openai/gpt-5",
    "an identical responseModel adds no suffix",
  );
  assert.equal(
    physicalKey({ provider: "openai", model: "gpt-5", responseModel: "" }),
    "openai/gpt-5",
  );
  assert.equal(physicalKey({ provider: "openai" }), null);
  assert.equal(physicalKey({ provider: "", model: "m" }), null);
  assert.equal(physicalKey({ model: "m" }), null);
  assert.equal(physicalKey(undefined), null);
  assert.equal(physicalKey("anthropic/claude-x"), null);
});

test("isSuccessfulResponse: error and aborted are failures; every other stopReason succeeds", () => {
  assert.equal(isSuccessfulResponse({ stopReason: "error" }), false);
  assert.equal(isSuccessfulResponse({ stopReason: "aborted" }), false);
  for (const stopReason of ["stop", "toolUse", "length", undefined]) {
    assert.equal(isSuccessfulResponse({ stopReason }), true, String(stopReason));
  }
  assert.equal(isSuccessfulResponse(null), false);
});

/** A branch `message` entry. */
const message = (body: Record<string, unknown>): Record<string, unknown> => ({
  type: "message",
  message: body,
});

test("branchUsageCensus: every owned boundary counted once; custom data and user messages never read", () => {
  const census = branchUsageCensus([
    message({ role: "user", content: "go", usage: usage({ input: 999 }) }),
    message({
      role: "assistant",
      usage: usage({ input: 100, output: 20, cacheRead: 500, cost: 0.01 }),
    }),
    message({ role: "toolResult", usage: usage({ input: 700, output: 300, cost: 0.0125 }) }),
    message({ role: "toolResult" }), // a tool result without usage is not a record
    { type: "compaction", summary: "s", usage: usage({ input: 50, output: 5, cacheWrite: 80 }) },
    { type: "compaction", summary: "s" }, // an extension compaction may omit usage
    { type: "branch_summary", summary: "b", usage: usage({ input: 10, output: 1 }) },
    { type: "usage", kind: "x", provider: "p", model: "m", usage: usage({ input: 2, output: 2 }) },
    { type: "custom_message", customType: "perk:x", content: "c", usage: usage({ input: 999 }) },
    { type: "custom", customType: "perk:workflow-state", data: { usage: usage({ input: 999 }) } },
    "not an entry",
    null,
  ]);
  assert.deepEqual(census.bySource, {
    assistant: 1,
    toolResult: 1,
    compaction: 1,
    branchSummary: 1,
    usageEntry: 1,
  });
  assert.equal(census.totals.records, 5);
  assert.equal(census.totals.input, 862);
  assert.equal(census.totals.output, 328);
  assert.equal(census.totals.cacheRead, 500);
  assert.equal(census.totals.cacheWrite, 80);
  assert.ok(Math.abs(census.totals.cost - 0.0225) < 1e-12);
});

test("branchUsageCensus: an empty branch has no records (unavailable, not zero-with-records)", () => {
  const census = branchUsageCensus([]);
  assert.deepEqual(census.totals, emptyUsageTotals());
  assert.equal(census.totals.records, 0);
});

test("branchModelCensus: latest successful response wins; error/aborted excluded but counted; →responseModel only when different", () => {
  const census = branchModelCensus([
    message({ role: "assistant", provider: "ext-faux", model: "m-1", stopReason: "toolUse" }),
    // A failed routing leaves the selected (virtual) identity on its error message.
    message({ role: "assistant", provider: "router", model: "auto", stopReason: "error" }),
    message({ role: "assistant", provider: "ext-faux", model: "m-1", stopReason: "stop" }),
    message({ role: "assistant", provider: "ext-faux", model: "m-2", stopReason: "aborted" }),
    message({
      role: "assistant",
      provider: "ext-faux",
      model: "m-2",
      responseModel: "m-2-2026",
      stopReason: "stop",
    }),
    message({ role: "assistant", provider: "ext-faux", model: "m-1", stopReason: "toolUse" }),
    // A successful message naming no identity is skipped; tool results never count.
    message({ role: "assistant", stopReason: "stop" }),
    message({ role: "toolResult", provider: "x", model: "y" }),
  ]);
  assert.deepEqual(census, {
    dispatched: "ext-faux/m-1",
    requested: "ext-faux/m-1",
    responses: [
      { model: "ext-faux/m-1", count: 3 },
      { model: "ext-faux/m-2→m-2-2026", count: 1 },
    ],
    errors: 1,
    aborted: 1,
  });
});

test("branchModelCensus: the dispatched key carries the suffix; requested does not", () => {
  const census = branchModelCensus([
    message({ role: "assistant", provider: "openai", model: "gpt-5", responseModel: "gpt-5-x" }),
  ]);
  assert.equal(census.dispatched, "openai/gpt-5→gpt-5-x");
  assert.equal(census.requested, "openai/gpt-5");
});

test("branchModelCensus: an empty branch or one with only failures dispatched nothing", () => {
  assert.deepEqual(branchModelCensus([]), {
    dispatched: null,
    requested: null,
    responses: [],
    errors: 0,
    aborted: 0,
  });
  const failures = branchModelCensus([
    message({ role: "assistant", provider: "router", model: "auto", stopReason: "error" }),
  ]);
  assert.equal(failures.dispatched, null);
  assert.deepEqual(failures.responses, []);
  assert.equal(failures.errors, 1);
});
