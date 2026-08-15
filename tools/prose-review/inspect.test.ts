import assert from "node:assert/strict";
import test from "node:test";
import { parseUnitInspect, type UnitInspect } from "./src/inspect.ts";

// The exact happy wire shape: every section populated, nested entries included.
const INSPECT: UnitInspect = {
  id: "typescript-tool:plan_review",
  kind: "typescript-tool",
  path: "extension/factories/planReview.ts",
  selector: "tool:plan_review",
  audience: "shipped",
  role: "tool-contract",
  breadcrumb: [
    { id: "review", label: "Review" },
    { id: "review.drafts", label: "Draft review" },
  ],
  capability_children: [{ id: "review.drafts.save", label: "Draft save" }],
  consumers: [
    { assembly: "plan-authoring", position: 5, label: "Review contract", optional: true },
    { assembly: "plan-adoption", position: 2, label: null, optional: false },
  ],
  shapes: [
    {
      id: "plan.cold",
      label: "Plan authoring — cold door",
      delivery: "cold",
      breadcrumb: [{ id: "planning", label: "Planning" }],
      siblings: [{ id: "plan.warm", label: "Plan authoring — warm door", delivery: "warm" }],
    },
  ],
  concerns: [
    {
      id: "review-first-save",
      label: "Review-first save",
      summary: "Authoring judgment remains in the reviewed draft.",
      canonical: false,
      relation: "Model-visible review and auto-save contract.",
      members: [
        {
          unit: {
            id: "markdown:prompts/contexts/plan-authoring.md",
            kind: "markdown",
            path: "prompts/contexts/plan-authoring.md",
          },
          relation: null,
          canonical: true,
        },
      ],
    },
  ],
  lineage: [
    {
      id: "delivered-skills",
      relationship: "materializes-to",
      targets: [".agents/skills/<skill>/"],
    },
  ],
};

function clone(): Record<string, unknown> {
  return structuredClone(INSPECT) as unknown as Record<string, unknown>;
}

test("parseUnitInspect accepts the exact happy shape", () => {
  assert.deepEqual(parseUnitInspect(clone()), INSPECT);
});

test("parseUnitInspect rejects non-record payloads", () => {
  assert.equal(parseUnitInspect(null), null);
  assert.equal(parseUnitInspect("inspect"), null);
  assert.equal(parseUnitInspect(42), null);
});

test("parseUnitInspect rejects a missing field", () => {
  for (const field of Object.keys(INSPECT)) {
    const payload = clone();
    delete payload[field];
    assert.equal(parseUnitInspect(payload), null, `missing ${field} must reject`);
  }
});

test("parseUnitInspect rejects ill-typed scalar fields", () => {
  assert.equal(parseUnitInspect({ ...clone(), id: 7 }), null);
  assert.equal(parseUnitInspect({ ...clone(), path: null }), null);
  assert.equal(parseUnitInspect({ ...clone(), selector: false }), null);
  assert.equal(parseUnitInspect({ ...clone(), breadcrumb: "review" }), null);
});

test("parseUnitInspect rejects unknown enum values", () => {
  assert.equal(parseUnitInspect({ ...clone(), kind: "latin" }), null);
  assert.equal(parseUnitInspect({ ...clone(), audience: "everyone" }), null);
  assert.equal(parseUnitInspect({ ...clone(), role: "boss" }), null);
});

test("parseUnitInspect rejects an unknown lineage relationship", () => {
  const payload = clone();
  payload.lineage = [{ id: "rule", relationship: "copied-from", targets: ["x"] }];
  assert.equal(parseUnitInspect(payload), null);
});

test("parseUnitInspect rejects an unknown sibling delivery mode", () => {
  const payload = clone();
  payload.shapes = [
    {
      id: "plan.cold",
      label: "Plan authoring — cold door",
      delivery: "cold",
      breadcrumb: [{ id: "planning", label: "Planning" }],
      siblings: [{ id: "plan.warm", label: "Plan authoring — warm door", delivery: "postal" }],
    },
  ];
  assert.equal(parseUnitInspect(payload), null);
});

test("parseUnitInspect rejects malformed nested entries", () => {
  const badConsumer = clone();
  badConsumer.consumers = [{ assembly: "a", position: 0, label: null, optional: false }];
  assert.equal(parseUnitInspect(badConsumer), null, "zero layer position must reject");

  const badBreadcrumb = clone();
  badBreadcrumb.breadcrumb = [{ id: "review" }];
  assert.equal(parseUnitInspect(badBreadcrumb), null, "label-less capability must reject");

  const badMember = clone();
  badMember.concerns = [
    {
      id: "review-first-save",
      label: "Review-first save",
      summary: "Authoring judgment remains in the reviewed draft.",
      canonical: false,
      relation: null,
      members: [{ unit: { id: "u" }, relation: null, canonical: true }],
    },
  ];
  assert.equal(parseUnitInspect(badMember), null, "ill-shaped member unit must reject");

  const badTargets = clone();
  badTargets.lineage = [{ id: "rule", relationship: "bundled-as", targets: ["ok", 7] }];
  assert.equal(parseUnitInspect(badTargets), null, "non-string lineage target must reject");
});

test("parseUnitInspect accepts empty relation sections", () => {
  const payload = {
    ...clone(),
    capability_children: [],
    consumers: [],
    shapes: [],
    concerns: [],
    lineage: [],
  };
  const parsed = parseUnitInspect(payload);
  assert.ok(parsed !== null);
  assert.deepEqual(parsed.consumers, []);
  assert.deepEqual(parsed.lineage, []);
});
