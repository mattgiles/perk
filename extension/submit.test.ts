// P1.T5a — live warm-door tests (turn-5 §10). Drive a REAL bound AgentSession via the T1 harness
// and prove the `perk pr-submit` delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in
// for the GitHub write, so no LLM / network / gh / Python is invoked.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

const SUBMIT_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://gh/o/r/pull/42", is_draft: true, existed: false },
  branch: "plan-7",
  issue: 7,
  dry_run: false,
});

test("tool: submit delegates, surfaces the PR, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: SUBMIT_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    assert.equal(result.terminate, true, "submit terminates the turn");
    const details = result.details as { ok: boolean; pr?: { number?: number }; branch?: string };
    assert.equal(details.ok, true);
    assert.equal(details.pr?.number, 42);
    assert.equal(details.branch, "plan-7");
    assert.match(result.content[0]?.text ?? "", /#42/);
  } finally {
    h.dispose();
  }
});

test("tool: a missing/failing worker fails loud-but-soft (no terminate)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true, "a failed submit does not terminate");
  } finally {
    h.dispose();
  }
});

test("tool: garbage worker output fails soft with bad_output", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "not json" });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
  } finally {
    h.dispose();
  }
});

test("/submit command: notifies success", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: SUBMIT_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("submit");
    assert.ok(
      h.notifies.some((n) => /#42/.test(n)),
      "command notifies the opened PR",
    );
  } finally {
    h.dispose();
  }
});
