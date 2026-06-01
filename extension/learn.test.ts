// P1.T5b — live warm-door tests for `/learn` (turn-5 §10). TS-only: no delegation, no gh — `/learn`
// clears the pending-learn semaphore. Driven through a REAL bound AgentSession via the T1 harness.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
import { markerPath, PENDING_LEARN, setMarker } from "./cache.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("tool: learn clears pending-learn and terminates", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN); // land left it set
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", {});
    assert.equal(result.terminate, true);
    const details = result.details as { ok: boolean; was_pending: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.was_pending, true);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn cleared");
  } finally {
    h.dispose();
  }
});

test("tool: learn is idempotent when nothing is pending", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", {});
    const details = result.details as { ok: boolean; was_pending: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.was_pending, false, "nothing was pending");
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)));
  } finally {
    h.dispose();
  }
});

test("/learn command: clears the marker", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("learn");
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "command cleared pending-learn");
  } finally {
    h.dispose();
  }
});
