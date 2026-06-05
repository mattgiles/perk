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

const LAND_JSON_WITH_OBJECTIVE = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, state: "MERGED" },
  branch: "plan-7",
  issue: 7,
  pending_learn: true,
  dry_run: false,
  objective: { number: 5, nodes_marked: ["1.2"], skipped_reason: null },
});

test("tool: land surfaces the objective node-done + /objective-reconcile nudge", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: LAND_JSON_WITH_OBJECTIVE });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Objective #5 node\(s\) 1\.2 marked done/);
    assert.match(text, /\/objective-reconcile #5/);
    const details = result.details as { objective?: { nodes_marked: string[] } };
    assert.deepEqual(details.objective?.nodes_marked, ["1.2"]);
  } finally {
    h.dispose();
  }
});

test("tool: land with a skipped objective adds no nudge", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const skipped = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: 7,
    pending_learn: true,
    dry_run: false,
    objective: { number: null, nodes_marked: [], skipped_reason: "no_objective_link" },
  });
  const bin = fakePerk(cwd, { stdout: skipped });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.doesNotMatch(text, /objective-reconcile/);
    assert.equal((result.details as { ok: boolean }).ok, true);
  } finally {
    h.dispose();
  }
});

test("tool: land surfaces a non-benign learn-consume skip", async () => {
  // #102: a partial `failed: …` close is a real failure — surface it, do not stay silent.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const partial = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: 7,
    pending_learn: true,
    dry_run: false,
    learn: { closed: [45], skipped_reason: "failed: #50" },
  });
  const bin = fakePerk(cwd, { stdout: partial });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Closed 1 learn issue\(s\)/);
    assert.match(text, /learn consume incomplete — failed: #50/);
  } finally {
    h.dispose();
  }
});

test("tool: land stays quiet on a benign learn-consume skip", async () => {
  // #102: `no_consumed_learn` is the ordinary non-factory case — no warning.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const benign = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, state: "MERGED" },
    branch: "plan-7",
    issue: 7,
    pending_learn: true,
    dry_run: false,
    learn: { closed: [], skipped_reason: "no_consumed_learn" },
  });
  const bin = fakePerk(cwd, { stdout: benign });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("land", {});
    const text = result.content[0]?.text ?? "";
    assert.doesNotMatch(text, /learn consume incomplete/);
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
