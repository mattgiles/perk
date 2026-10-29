// A7 — the `submit` payload comparison and the attempt ending's shape
// (docs/design/pi-durable-v2-foundations.md §4, §6, §12 the native assignment). `compareSubmit`
// records an absent mapping, replays an equal one, and refuses `duplicate_conflict` for any other;
// `parseAttemptEnding` accepts exactly the three ending kinds. The instruction-render and
// capability-resolution checks are pinned per failure.

import assert from "node:assert/strict";
import { test } from "node:test";
import { Type } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import { fauxProvider } from "@earendil-works/pi-ai/providers/faux";
import type { Extension, ToolRegistration } from "@earendil-works/pi-durable";
import { sha256Hex } from "../kernel/canonical.ts";
import { fixturePolicy, renderFixtureInstructions } from "../kernel/fixture.ts";
import { compareSubmit, renderInstructionsChecked, resolveCapabilities } from "./assignment.ts";
import { type AttemptEnding, parseAttemptEnding } from "./ending.ts";
import type { DurableMapRow } from "./records.ts";

const ATTEMPT = "v2/E/fixture-report/a/tree/cap/1";
const SUBMIT = `${ATTEMPT}/submit`;

function rows(entries: Record<string, DurableMapRow>): ReadonlyMap<string, DurableMapRow> {
  return new Map(Object.entries(entries));
}

test("A7: compareSubmit records an absent row and replays an equal one", () => {
  const worker: DurableMapRow = { durableKind: "conversation", durableId: 7 };
  assert.deepEqual(compareSubmit(rows({ [ATTEMPT]: worker }), ATTEMPT, 7, 9), { kind: "record" });
  assert.deepEqual(
    compareSubmit(
      rows({ [ATTEMPT]: worker, [SUBMIT]: { durableKind: "submission", durableId: 9 } }),
      ATTEMPT,
      7,
      9,
    ),
    { kind: "replayed" },
  );
});

test("A7: compareSubmit refuses duplicate_conflict for any other mapping", () => {
  const cases: [string, Record<string, DurableMapRow>][] = [
    ["no worker row", {}],
    [
      "a worker row naming another conversation",
      { [ATTEMPT]: { durableKind: "conversation", durableId: 8 } },
    ],
    ["a worker row of another kind", { [ATTEMPT]: { durableKind: "task", durableId: 7 } }],
    [
      "a submit row naming another submission",
      {
        [ATTEMPT]: { durableKind: "conversation", durableId: 7 },
        [SUBMIT]: { durableKind: "submission", durableId: 10 },
      },
    ],
    [
      "a submit row of another kind",
      {
        [ATTEMPT]: { durableKind: "conversation", durableId: 7 },
        [SUBMIT]: { durableKind: "task", durableId: 9 },
      },
    ],
  ];
  for (const [name, entries] of cases) {
    const result = compareSubmit(rows(entries), ATTEMPT, 7, 9);
    assert.equal(result.kind, "refused", name);
    if (result.kind === "refused") assert.equal(result.refusal.reason, "duplicate_conflict", name);
  }
});

test("A7: parseAttemptEnding accepts exactly the three ending kinds", () => {
  const valid: AttemptEnding[] = [
    { end: "accepted", outcomeId: `${ATTEMPT}/accept-report` },
    { end: "incomplete", submission: "done", reason: null, refusal: null },
    {
      end: "incomplete",
      submission: "unanswered",
      reason: "model_error",
      refusal: "invalid_report",
    },
    { end: "repair", cause: "snapshot_tampered", detail: "content differs" },
  ];
  for (const ending of valid) assert.deepEqual(parseAttemptEnding(ending), ending);
  const invalid: unknown[] = [
    null,
    undefined,
    "accepted",
    [],
    {},
    { end: "finished" },
    { end: "accepted", outcomeId: "" },
    { end: "accepted", outcomeId: "x", extra: 1 },
    { end: "incomplete", submission: "lost", reason: null, refusal: null },
    { end: "incomplete", submission: "done", reason: 1, refusal: null },
    { end: "incomplete", submission: "done", reason: null, refusal: "bogus" },
    { end: "incomplete", submission: "done", reason: null },
    { end: "repair", cause: "unknown", detail: "x" },
    { end: "repair", cause: "capability_missing", detail: 5 },
    { end: "repair", cause: "capability_missing", detail: "x", extra: true },
  ];
  for (const value of invalid) assert.equal(parseAttemptEnding(value), null, JSON.stringify(value));
});

test("the instructions must render to the recorded digest", () => {
  const digest = fixturePolicy().capabilitySet.instructionsDigest;
  assert.deepEqual(renderInstructionsChecked(renderFixtureInstructions, digest), {
    ok: true,
    text: renderFixtureInstructions(),
  });
  const failures: [string, () => string, RegExp][] = [
    [
      "a throw",
      () => {
        throw new Error("boom");
      },
      /threw: boom/,
    ],
    ["empty", () => "", /no well-formed text/],
    ["ill-formed", () => "\uD800", /no well-formed text/],
    ["another text", () => "other", new RegExp(`digest ${sha256Hex("other")} is not the recorded`)],
  ];
  for (const [name, render, detail] of failures) {
    const result = renderInstructionsChecked(render, digest);
    assert.equal(result.ok, false, name);
    if (!result.ok) assert.match(result.detail, detail, name);
  }
});

test("every capability resolves to exactly one object, or names what is missing", () => {
  const tool = (name: string): ToolRegistration => ({
    name,
    description: name,
    parameters: Type.Object({}),
    execute: async () => ({}),
  });
  const ext: Extension = {
    name: "perk.v2.report",
    tools: ["find", "grep", "ls", "read", "report"].map(tool),
  };
  const models = createModels();
  models.setProvider(fauxProvider().provider);
  const registry = (extensions: readonly Extension[]) => ({
    extension: (name: string) => extensions.find((candidate) => candidate.name === name),
  });
  const capabilitySet = fixturePolicy().capabilitySet;
  const resolved = resolveCapabilities(capabilitySet, models, registry([ext]));
  assert.equal(resolved.ok, true);
  if (resolved.ok) {
    assert.deepEqual(resolved.model, { provider: "faux", modelId: "faux-1" });
    assert.deepEqual(resolved.extensions, [ext]);
    assert.deepEqual(
      resolved.tools.map((candidate) => candidate.name),
      ["find", "grep", "ls", "read", "report"],
    );
  }
  const failures: [string, ReturnType<typeof resolveCapabilities>, RegExp][] = [
    [
      "no model",
      resolveCapabilities(capabilitySet, createModels(), registry([ext])),
      /model faux\/faux-1 is not available/,
    ],
    [
      "no extension",
      resolveCapabilities(capabilitySet, models, registry([])),
      /extension perk\.v2\.report is not installed/,
    ],
    [
      "a missing tool",
      resolveCapabilities(
        capabilitySet,
        models,
        registry([{ ...ext, tools: ext.tools?.slice(1) }]),
      ),
      /tool find is provided by 0/,
    ],
    [
      "a doubled tool",
      resolveCapabilities(
        capabilitySet,
        models,
        registry([{ ...ext, tools: [...(ext.tools ?? []), tool("ls")] }]),
      ),
      /tool ls is provided by 2/,
    ],
  ];
  for (const [name, result, detail] of failures) {
    assert.equal(result.ok, false, name);
    if (!result.ok) assert.match(result.detail, detail, name);
  }
});
