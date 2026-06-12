// P1.T5a — live warm-door tests (turn-5 §10). Drive a REAL bound AgentSession via the T1 harness
// and prove the `perk pr submit` delegation end-to-end, OFFLINE: a fake `perk` (PERK_BIN) stands in
// for the GitHub write, so no LLM / network / gh / Python is invoked.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";

const SUBMIT_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://gh/o/r/pull/42", is_draft: true, existed: false },
  branch: "plan-7",
  issue: 7,
  plan_embedded: true,
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
    assert.equal((details as { plan_embedded?: boolean }).plan_embedded, true);
    assert.match(result.content[0]?.text ?? "", /plan embedded/);
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

test("tool: a success:false envelope at non-zero exit surfaces the structured error", async () => {
  // The envelope-aware regression (Node 2.1): the Python plane prints a structured failure
  // envelope to stdout before exiting non-zero — the door must surface it, not the stderr tail.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const envelope = JSON.stringify({
    success: false,
    error_type: "no_plan_ref",
    message: "no active plan-ref on this branch",
  });
  const bin = fakePerk(cwd, { stdout: envelope, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_plan_ref");
    assert.equal(details.error, "no active plan-ref on this branch");
  } finally {
    h.dispose();
  }
});

test("tool: success:true with a malformed pr fails as bad_output (unexpected payload)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: "42", url: "https://gh/o/r/pull/42", is_draft: true, existed: false },
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit", {});
    const details = result.details as { ok: boolean; error?: string; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.match(details.error ?? "", /unexpected payload/);
  } finally {
    h.dispose();
  }
});

test("/submit command: failure surfaces exactly ONE error notify (failFor's — no duplicate)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("submit");
    const errors = h.notifyEvents.filter((e) => e.severity === "error");
    assert.equal(errors.length, 1, `expected one error notify, got: ${JSON.stringify(errors)}`);
    assert.match(errors[0]?.message ?? "", /^perk: submit — /);
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
