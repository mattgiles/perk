// A2 — failed runs leave a visible incomplete attempt (docs/design/pi-durable-v2-foundations.md §12
// the native assignment, P6): role b reports validly while role a's run ends without an accepted
// report — no report, a report the kernel refuses, a report its arguments check rejects (an extra
// key, and a numeric summary pi-ai's validation alone would coerce to text), a token-limited
// answer, a tool error, and a model error. Each is quiescent `assignment_incomplete` with role a
// visibly unaccepted, no aggregate and no decision, and an `incomplete` ending naming the
// submission's settlement.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fauxAssistantMessage, fauxText } from "@earendil-works/pi-ai/providers/faux";
import type { AttemptEnding } from "../durable/ending.ts";
import { coverageOf, fixturePolicy } from "../kernel/fixture.ts";
import { indexRecords } from "../kernel/records.ts";
import { ofType, T2 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import { expectQuiescent } from "../testing/host.ts";
import {
  assertScript,
  call,
  FINAL,
  fixtureAttemptId,
  reportCall,
  round,
  type Step,
  startNative,
  withStore,
} from "../testing/worker.ts";

type Case = {
  readonly name: string;
  readonly steps: (tree: string) => readonly Step[];
  readonly ending: AttemptEnding;
  /** The error text role a's last tool result carries, when it made a call. */
  readonly toolError?: RegExp;
};

const CASES: readonly Case[] = [
  {
    name: "missing: a final text with no report",
    steps: () => [FINAL],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: null },
  },
  {
    name: "refused invalid_report: the wrong subject, then a final text",
    steps: (tree) => [reportCall(tree, { subjectDigest: T2 }), FINAL],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: "invalid_report" },
    toolError: /^invalid_report: /,
  },
  {
    name: "invalid arguments: an extra key, then a final text",
    steps: (tree) => [reportCall(tree, { verdict: "ok" }), FINAL],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: null },
    toolError: /fixture-report schema/,
  },
  {
    name: "invalid arguments: a numeric summary, then a final text",
    steps: (tree) => [reportCall(tree, { summary: 5 }), FINAL],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: null },
    toolError: /fixture-report schema/,
  },
  {
    name: "token-limited",
    steps: () => [fauxAssistantMessage([fauxText("partial")], { stopReason: "length" })],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: null },
  },
  {
    name: "a tool error: a read of a missing file, then a final text",
    steps: () => [round(call("read", { path: "missing.txt" }, "x1")), FINAL],
    ending: { end: "incomplete", submission: "done", reason: null, refusal: null },
    toolError: /./,
  },
  {
    name: "a model error",
    steps: () => [fauxAssistantMessage([], { stopReason: "error", errorMessage: "boom" })],
    ending: { end: "incomplete", submission: "unanswered", reason: "model_error", refusal: null },
  },
];

for (const row of CASES) {
  test(`A2: ${row.name}`, { timeout: CASE_TIMEOUT_MS }, async (t) => {
    const started = await startNative(t, (tree) => ({ a: row.steps(tree), b: [reportCall(tree)] }));
    const { tree, store, script } = started;
    const view = expectQuiescent(started.outcome).view;
    assert.equal(view.waitReason, "assignment_incomplete");
    assertScript(script, { a: { leftover: 0 }, b: { consumed: 1, leftover: 0 } });
    const coverage = coverageOf(indexRecords(view.records.records), fixturePolicy());
    assert.deepEqual(
      coverage.roles.map((role) => [role.role, role.attempts, role.acceptedOutcomeId === null]),
      [
        ["a", 1, true],
        ["b", 1, false],
      ],
    );
    assert.equal(coverage.complete, false);
    assert.deepEqual(ofType(view.records.records, "aggregate-outcome"), []);
    assert.deepEqual(ofType(view.records.records, "decision"), []);
    assert.deepEqual(view.endings.get(fixtureAttemptId("a", tree)), row.ending);
    assert.equal(view.endings.get(fixtureAttemptId("b", tree))?.end, "accepted");

    const results = await withStore(store, async (storeView) => {
      const worker = view.records.durableMap.get(fixtureAttemptId("a", tree));
      assert.ok(worker !== undefined, "role a has a worker conversation");
      return storeView.toolResults(worker.durableId);
    });
    if (row.toolError === undefined) {
      assert.deepEqual(results, [], "no tool call");
    } else {
      const last = results.at(-1);
      assert.equal(last?.message.isError, true);
      assert.match(last?.text ?? "", row.toolError);
    }
  });
}
