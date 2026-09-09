// Unit tests for the current-review record: the identity fence, the approve gate's ordered
// reasons, the destination comparator (through the gate — it is module-private) and the save
// dedupe.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  closeCurrentReview,
  createCurrentReviewState,
  gateApprovedSave,
  isCurrentReview,
  openCurrentReview,
  type ReviewDestination,
} from "./currentReview.ts";

const DEST: ReviewDestination = {
  backend: "github",
  team: null,
  remotes: ["remote.origin.url https://example.com/a.git"],
};
const SOURCE = { name: "plan-draft.md", raw: "# plan\n" };

test("openCurrentReview returns a fresh record that supersedes the previous one and resets saved", () => {
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: SOURCE, destination: DEST });
  assert.equal(isCurrentReview(state, a), true);
  assert.deepEqual(gateApprovedSave(state, a, { source: SOURCE.raw, destination: DEST }), {
    ok: true,
  });
  assert.equal(state.saved, true);

  // Identical inputs still open a DISTINCT record: identity is the object, not its contents.
  const b = openCurrentReview(state, { source: SOURCE, destination: DEST });
  assert.notEqual(a, b);
  assert.equal(isCurrentReview(state, a), false);
  assert.equal(isCurrentReview(state, b), true);
  assert.equal(
    isCurrentReview(state, { source: SOURCE, destination: DEST }),
    false,
    "a structurally equal copy is not the current record",
  );
  assert.equal(state.saved, false, "a new open resets the dedupe");
  assert.deepEqual(gateApprovedSave(state, a, { source: SOURCE.raw, destination: DEST }), {
    ok: false,
    reason: "superseded",
  });
  assert.equal(state.saved, false, "a refused gate never marks saved");
});

test("gateApprovedSave: a second approve for the same record refuses already-saved", () => {
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: SOURCE, destination: DEST });
  assert.deepEqual(gateApprovedSave(state, a, { source: SOURCE.raw, destination: DEST }), {
    ok: true,
  });
  assert.deepEqual(gateApprovedSave(state, a, { source: SOURCE.raw, destination: DEST }), {
    ok: false,
    reason: "already-saved",
  });
});

test("gateApprovedSave: source-changed when the re-read differs or is null; a null source skips the compare", () => {
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: SOURCE, destination: DEST });
  assert.deepEqual(gateApprovedSave(state, a, { source: "# plan v2\n", destination: DEST }), {
    ok: false,
    reason: "source-changed",
  });
  assert.deepEqual(gateApprovedSave(state, a, { source: null, destination: DEST }), {
    ok: false,
    reason: "source-changed",
  });
  const sourceless = openCurrentReview(state, { source: null, destination: DEST });
  assert.deepEqual(gateApprovedSave(state, sourceless, { source: null, destination: DEST }), {
    ok: true,
  });
});

test("gateApprovedSave: destination-changed on a backend, team or remote change", () => {
  const cases: Array<Partial<ReviewDestination>> = [
    { backend: "linear" },
    { backend: null },
    { team: "ENG" },
    { remotes: ["remote.origin.url https://example.com/b.git"] },
    { remotes: [] },
    { remotes: [...(DEST.remotes ?? []), "remote.upstream.url https://example.com/u.git"] },
  ];
  for (const change of cases) {
    const state = createCurrentReviewState();
    const a = openCurrentReview(state, { source: SOURCE, destination: DEST });
    assert.deepEqual(
      gateApprovedSave(state, a, { source: SOURCE.raw, destination: { ...DEST, ...change } }),
      { ok: false, reason: "destination-changed" },
      JSON.stringify(change),
    );
  }
});

test("gateApprovedSave: absence is a value — null backend/team and [] remotes compare equal; order is irrelevant", () => {
  const absent: ReviewDestination = { backend: null, team: null, remotes: [] };
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: null, destination: absent });
  assert.deepEqual(gateApprovedSave(state, a, { source: null, destination: { ...absent } }), {
    ok: true,
  });

  const unordered: ReviewDestination = { backend: "github", team: "ENG", remotes: ["b", "a"] };
  const b = openCurrentReview(state, { source: null, destination: unordered });
  assert.deepEqual(
    gateApprovedSave(state, b, {
      source: null,
      destination: { ...unordered, remotes: ["a", "b"] },
    }),
    { ok: true },
  );
});

test("gateApprovedSave: an unreadable remote reading at either end refuses destination-unreadable", () => {
  const state = createCurrentReviewState();
  const openedUnreadable = openCurrentReview(state, {
    source: null,
    destination: { ...DEST, remotes: null },
  });
  assert.deepEqual(gateApprovedSave(state, openedUnreadable, { source: null, destination: DEST }), {
    ok: false,
    reason: "destination-unreadable",
  });
  const approvedUnreadable = openCurrentReview(state, { source: null, destination: DEST });
  assert.deepEqual(
    gateApprovedSave(state, approvedUnreadable, {
      source: null,
      destination: { ...DEST, remotes: null },
    }),
    { ok: false, reason: "destination-unreadable" },
  );
  // Unreadable outranks changed: both null is still unreadable, never "equal".
  const bothUnreadable = openCurrentReview(state, {
    source: null,
    destination: { ...DEST, remotes: null },
  });
  assert.deepEqual(
    gateApprovedSave(state, bothUnreadable, {
      source: null,
      destination: { ...DEST, remotes: null },
    }),
    { ok: false, reason: "destination-unreadable" },
  );
});

test("gate order: already-saved outranks source/destination drift; source-changed outranks destination", () => {
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: SOURCE, destination: DEST });
  assert.deepEqual(
    gateApprovedSave(state, a, { source: "changed", destination: { ...DEST, remotes: null } }),
    { ok: false, reason: "source-changed" },
  );
  assert.deepEqual(gateApprovedSave(state, a, { source: SOURCE.raw, destination: DEST }), {
    ok: true,
  });
  assert.deepEqual(
    gateApprovedSave(state, a, { source: "changed", destination: { ...DEST, remotes: null } }),
    { ok: false, reason: "already-saved" },
  );
});

test("closeCurrentReview clears only its own record — a superseding open survives the older close", () => {
  const state = createCurrentReviewState();
  const a = openCurrentReview(state, { source: null, destination: DEST });
  const b = openCurrentReview(state, { source: null, destination: DEST });
  closeCurrentReview(state, a);
  assert.equal(isCurrentReview(state, b), true);
  closeCurrentReview(state, b);
  assert.equal(state.current, null);
  assert.equal(isCurrentReview(state, b), false);
});
