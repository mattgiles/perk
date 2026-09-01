// The `finishLearn` policy matrix over fake ports: skip/capture routing on the trimmed summary,
// decision/target passthrough, the marker cleared ONLY on backend success (both arms), the
// failure arm retaining the marker, the already-captured arm, and the null-issue
// (undecodable-payload) arm. The production ports live in the pi/v1 adapter; these fakes prove
// the policy without any cold door.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CAPTURED_DECISIONS,
  type CapturedDecision,
  finishLearn,
  isCapturedDecision,
  type LearnBackend,
  type LearnIssue,
} from "./capture.ts";

const ISSUE: LearnIssue = { id: "99", url: "https://gh/o/r/issues/99", existed: false };

/** A recording backend whose two arms are scripted per test. */
function fakeBackend(script: {
  capture?: Awaited<ReturnType<LearnBackend["capture"]>>;
  skip?: Awaited<ReturnType<LearnBackend["skip"]>>;
}) {
  const calls: {
    capture: { body: string; decision?: CapturedDecision; target?: string }[];
    skip: number;
  } = { capture: [], skip: 0 };
  const backend: LearnBackend = {
    async capture(input) {
      calls.capture.push(input);
      return script.capture ?? { ok: true, issue: ISSUE };
    },
    async skip() {
      calls.skip += 1;
      return script.skip ?? { ok: true, learnState: "skipped" };
    },
  };
  return { backend, calls };
}

/** A marker fake that records clears and reports a scripted wasPending. */
function fakeMarker(wasPending = true) {
  const state = { clears: 0 };
  return {
    state,
    marker: {
      clear: () => {
        state.clears += 1;
        return { wasPending };
      },
    },
  };
}

test("finishLearn: a blank/absent summary routes to skip (decision/target intentionally ignored)", async () => {
  for (const summary of [undefined, "", "   \n\t "]) {
    const { backend, calls } = fakeBackend({});
    const { marker, state } = fakeMarker();
    const outcome = await finishLearn(
      { ...(summary !== undefined ? { summary } : {}), decision: "NEW_DOC", target: "docs/x.md" },
      { backend, marker },
    );
    assert.deepEqual(outcome, { kind: "skip_recorded", wasPending: true, alreadyCaptured: false });
    assert.equal(calls.skip, 1, "the skip arm delegates to the backend");
    assert.equal(calls.capture.length, 0, "no capture on the skip arm");
    assert.equal(state.clears, 1, "the marker cleared on a verified skip success");
  }
});

test("finishLearn: the already-captured skip arm (learnState === 'captured')", async () => {
  const { backend } = fakeBackend({ skip: { ok: true, learnState: "captured" } });
  const { marker } = fakeMarker(false);
  const outcome = await finishLearn({}, { backend, marker });
  assert.deepEqual(outcome, { kind: "skip_recorded", wasPending: false, alreadyCaptured: true });
});

test("finishLearn: a failed skip keeps the marker (backend_failed passthrough)", async () => {
  const { backend } = fakeBackend({
    skip: { ok: false, message: "skip door down", errorType: "exec_failed" },
  });
  const { marker, state } = fakeMarker();
  const outcome = await finishLearn({}, { backend, marker });
  assert.deepEqual(outcome, {
    kind: "backend_failed",
    message: "skip door down",
    errorType: "exec_failed",
  });
  assert.equal(state.clears, 0, "the marker is NEVER cleared on failure — it is the retry signal");
});

test("finishLearn: a non-blank summary routes to capture (trimmed body, passthrough fields)", async () => {
  const { backend, calls } = fakeBackend({});
  const { marker, state } = fakeMarker();
  const outcome = await finishLearn(
    {
      summary: "  a durable trap \n",
      decision: "UPDATE_EXISTING_DOC",
      target: "docs/learned/x.md",
    },
    { backend, marker },
  );
  assert.deepEqual(outcome, { kind: "captured", wasPending: true, issue: ISSUE });
  assert.deepEqual(calls.capture, [
    { body: "a durable trap", decision: "UPDATE_EXISTING_DOC", target: "docs/learned/x.md" },
  ]);
  assert.equal(calls.skip, 0, "no skip on the capture arm");
  assert.equal(state.clears, 1, "the marker cleared on a verified capture success");
});

test("finishLearn: decision/target are absent from the capture input when not given", async () => {
  const { backend, calls } = fakeBackend({});
  const { marker } = fakeMarker();
  await finishLearn({ summary: "x" }, { backend, marker });
  assert.deepEqual(calls.capture, [{ body: "x" }]);
});

test("finishLearn: a null issue is still captured (the success envelope is authoritative)", async () => {
  const { backend } = fakeBackend({ capture: { ok: true, issue: null } });
  const { marker, state } = fakeMarker();
  const outcome = await finishLearn({ summary: "x" }, { backend, marker });
  assert.deepEqual(outcome, { kind: "captured", wasPending: true, issue: null });
  assert.equal(state.clears, 1, "a success envelope clears the marker even without issue details");
});

test("finishLearn: a failed capture keeps the marker", async () => {
  const { backend } = fakeBackend({
    capture: { ok: false, message: "capture door down", errorType: "github_error" },
  });
  const { marker, state } = fakeMarker();
  const outcome = await finishLearn({ summary: "x" }, { backend, marker });
  assert.deepEqual(outcome, {
    kind: "backend_failed",
    message: "capture door down",
    errorType: "github_error",
  });
  assert.equal(state.clears, 0, "the marker is kept on a failed capture");
});

test("CAPTURED_DECISIONS: the frozen five-token vocabulary + the boundary predicate", () => {
  assert.deepEqual(
    [...CAPTURED_DECISIONS],
    ["CAPTURE_LEARN", "SHOULD_BE_CODE", "UPDATE_EXISTING_DOC", "NEW_DOC", "STALE_DOC"],
    "the captured-classification tokens are contract vocabulary (§8.35) — never re-spell them",
  );
  for (const token of CAPTURED_DECISIONS) {
    assert.equal(isCapturedDecision(token), true);
  }
  assert.equal(isCapturedDecision("SKIP"), false, "SKIP is schema-only vocabulary, never captured");
  assert.equal(isCapturedDecision("NONSENSE"), false);
});
