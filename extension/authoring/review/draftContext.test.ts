// Pure unit tests of the door-primed draft-review state module alone — no wave, no harness.
// The launch/collect arcs (which couple the prime/clear discipline to the execute cores) live
// in `pi/v1/draftReviewWaveTools.test.ts`.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReportWaveRef } from "../../waves/reportWave.ts";
import {
  clearDraftReviewContext,
  createDraftReviewWaveState,
  primeDraftReviewContext,
} from "./draftContext.ts";

// The ref is an opaque brand — an empty object cast is the honest test stand-in (the state
// module never looks inside it; identity is all that matters here).
const refA = {} as ReportWaveRef;
const refB = {} as ReportWaveRef;

test("createDraftReviewWaveState yields empty slots", () => {
  const state = createDraftReviewWaveState();
  assert.equal(state.pending, null);
  assert.equal(state.context, null);
});

test("primeDraftReviewContext copies the fields, includes custom only when supplied, resets pending", () => {
  const state = createDraftReviewWaveState();
  state.pending = refA;
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft\n" });
  assert.deepEqual(state.context, { draftType: "plan", draft: "# Draft\n" });
  assert.equal(
    Object.hasOwn(state.context ?? {}, "custom"),
    false,
    "no custom key when none was supplied",
  );
  assert.equal(state.pending, null, "a prime resets the pending slot");

  primeDraftReviewContext(state, {
    draftType: "objective",
    draft: "# Objective\n",
    custom: "check the phasing",
  });
  assert.deepEqual(state.context, {
    draftType: "objective",
    draft: "# Objective\n",
    custom: "check the phasing",
  });
});

test("clearDraftReviewContext drops only the context — a set pending survives (launched wave stays collectable)", () => {
  const state = createDraftReviewWaveState();
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft\n" });
  state.pending = refA;
  clearDraftReviewContext(state);
  assert.equal(state.context, null, "the primed inputs die with the browser session");
  assert.equal(state.pending, refA, "the launched wave stays collectable");
});

test("a re-prime supersedes a previous context and pending ref", () => {
  const state = createDraftReviewWaveState();
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft v1\n", custom: "old lane" });
  state.pending = refB;
  primeDraftReviewContext(state, { draftType: "plan", draft: "# Draft v2\n" });
  assert.deepEqual(
    state.context,
    { draftType: "plan", draft: "# Draft v2\n" },
    "the new prime replaces the context wholesale (the stale custom lane is gone)",
  );
  assert.equal(state.pending, null, "the superseded pending ref is dropped");
});
