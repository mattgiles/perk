// P1.T5b — live warm-door tests for `/land` (turn-5 §10). Drive a REAL bound AgentSession via the
// T1 harness; the `perk pr-land` merge is faked via PERK_BIN, so no LLM / network / gh / Python.
// The warm door's own effect (setting pending-learn for the in-session path) is verified on disk.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { markerPath, PENDING_LEARN } from "./cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

const LAND_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, state: "MERGED" },
  branch: "plan-7",
  issue: 7,
  pending_learn: true,
  dry_run: false,
});

test("tool: land delegates, sets pending-learn, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: LAND_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    assert.equal(result.terminate, true, "land terminates the turn");
    const details = result.details as { ok: boolean; pr?: { number?: number } };
    assert.equal(details.ok, true);
    assert.equal(details.pr?.number, 42);
    // the warm door set pending-learn for the in-session path
    assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn is set");
  } finally {
    h.dispose();
  }
});

test("tool: a failing land does not set pending-learn (soft fail)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true);
    assert.ok(
      !existsSync(join(cwd, ".pi", "workflow", "markers", PENDING_LEARN)),
      "no marker on failure",
    );
  } finally {
    h.dispose();
  }
});

test("/land command: notifies success", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: LAND_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("land");
    assert.ok(
      h.notifies.some((n) => /#42/.test(n)),
      "command notifies the landed PR",
    );
  } finally {
    h.dispose();
  }
});
