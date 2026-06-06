// P3.T2 — live warm-door tests for the `objective_save` tool + `/objective-save` command. Drive a
// REAL bound AgentSession via the harness and prove the `perk objective create` delegation +
// session linkage (active_objective + budget marker) end-to-end, OFFLINE: a fake `perk` (PERK_BIN)
// stands in for the GitHub write. The pure objectiveSaveGuidance twin is unit-tested below.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import { objectiveSaveGuidance } from "./objectiveSave.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

const CREATE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  objective: { number: 7, url: "https://gh/o/r/issues/7", existed: false },
  dry_run: false,
});

const PROSE = "# Ship retries\n\n## Why\nThe gateway needs retries.\n";

interface BudgetEntry {
  type?: string;
  customType?: string;
  data?: { objective_id?: string };
}

test("tool: objective_save delegates, links active_objective + seeds budget marker, terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CREATE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", {
      prose: PROSE,
      roadmap: [{ id: "1.1", description: "first" }],
    });
    const details = result.details as { ok: boolean; objective?: { number: number } };
    assert.equal(details.ok, true);
    assert.equal(details.objective?.number, 7);
    assert.equal(result.terminate, true);
    // active_objective linked on the live session.
    assert.equal(h.workflowState().active_objective, "7");
    // a fresh budget activation marker was seeded for #7.
    const entries = h.session.sessionManager.getEntries() as unknown as BudgetEntry[];
    const marker = entries.find((e) => e.customType === OBJECTIVE_BUDGET_TYPE);
    assert.ok(marker, "budget marker seeded");
    assert.equal(marker?.data?.objective_id, "7");
  } finally {
    h.dispose();
  }
});

test("tool: objective_save passes the structured roadmap as --roadmap <json>", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = `${cwd}/argv.txt`;
  const bin = fakePerk(cwd, { stdout: CREATE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_save", {
      prose: PROSE,
      title: "Ship retries",
      roadmap: [{ id: "1.1", description: "first" }],
    });
    const argv = readFileSync(argvFile, "utf8");
    assert.match(argv, /objective\ncreate/);
    assert.match(argv, /--roadmap/);
    assert.match(argv, /"id":"1.1"/);
    assert.match(argv, /--run-id\n01RID/);
    assert.match(argv, /--title\nShip retries/);
  } finally {
    h.dispose();
  }
});

test("tool: objective_save surfaces a cold-door failure as details.ok=false (no linkage)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: false, error_type: "github_error", message: "boom" }),
    code: 1,
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_save", { prose: PROSE });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.equal(h.workflowState().active_objective ?? null, null, "no linkage on failure");
  } finally {
    h.dispose();
  }
});

test("/objective-save registers and is headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(
      h.registeredCommands().includes("objective-save"),
      "the /objective-save command is registered",
    );
  } finally {
    h.dispose();
  }
});

// --- pure helpers (offline unit) --------------------------------------------------------

test("objectiveSaveGuidance: with no title, drives the objective_save tool with prose + roadmap", () => {
  const text = objectiveSaveGuidance();
  assert.match(text, /objective_save/);
  assert.match(text, /prose/);
  assert.match(text, /roadmap/);
  assert.match(text, /JSON array of nodes/);
  assert.match(text, /defaults to the prose's first heading/);
});

test("objectiveSaveGuidance: with a title argument, names that title", () => {
  const text = objectiveSaveGuidance("Ship retries");
  assert.match(text, /title: "Ship retries"/);
});

test("objectiveSaveGuidance: does not hardcode the perk-objective-author skill pointer", () => {
  // The skill pointer rides the binding suffix (Node 2.3), never the guidance body.
  assert.doesNotMatch(objectiveSaveGuidance(), /perk-objective-author/);
});
