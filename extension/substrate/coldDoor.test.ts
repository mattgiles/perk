import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type {
  ExecOptions,
  ExecResult,
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import {
  activeRunId,
  booleanField,
  type ColdDoorCtx,
  type ColdJson,
  type ExecHost,
  nullableStringField,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "./coldDoor.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

// --- compile-time satisfaction: the structural slices can never drift from the SDK -----------

const _h: ExecHost = {} as ExtensionAPI;
const _c: ColdDoorCtx = {} as ExtensionContext;
void _h;
void _c;

// --- fakes ------------------------------------------------------------------------------------

interface ExecCall {
  command: string;
  args: string[];
  options?: ExecOptions;
}

/** A fake ExecHost recording every call and returning a scripted result (or throwing). */
function fakeExec(result: Partial<ExecResult> | Error): { host: ExecHost; calls: ExecCall[] } {
  const calls: ExecCall[] = [];
  return {
    calls,
    host: {
      exec: (command, args, options) => {
        calls.push({ command, args, options });
        if (result instanceof Error) return Promise.reject(result);
        return Promise.resolve({ stdout: "", stderr: "", code: 0, killed: false, ...result });
      },
    },
  };
}

function fakeCtx(cwd: string, branch: unknown[] = []): ColdDoorCtx {
  return { cwd, sessionManager: { getBranch: () => branch } };
}

function tempCwd(): string {
  return mkdtempSync(join(tmpdir(), "cold-door-test-"));
}

const decodeAll = (payload: ColdJson) => payload;

// --- PERK_BIN resolution -----------------------------------------------------------------------

test("runColdDoor uses PERK_BIN when set, else 'perk'", async () => {
  const cwd = tempCwd();
  const saved = process.env.PERK_BIN;
  try {
    process.env.PERK_BIN = "/opt/custom/perk";
    const withEnv = fakeExec({ stdout: '{"success": true}' });
    await runColdDoor(withEnv.host, fakeCtx(cwd), ["pr-submit", "--json"], {
      label: "perk pr-submit",
      decode: decodeAll,
    });
    assert.equal(withEnv.calls[0]?.command, "/opt/custom/perk");
    assert.deepEqual(withEnv.calls[0]?.args, ["pr-submit", "--json"]);
    assert.equal(withEnv.calls[0]?.options?.cwd, cwd);

    delete process.env.PERK_BIN;
    const noEnv = fakeExec({ stdout: '{"success": true}' });
    await runColdDoor(noEnv.host, fakeCtx(cwd), ["pr-submit", "--json"], {
      label: "perk pr-submit",
      decode: decodeAll,
    });
    assert.equal(noEnv.calls[0]?.command, "perk");
  } finally {
    if (saved === undefined) delete process.env.PERK_BIN;
    else process.env.PERK_BIN = saved;
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- spawn failure -------------------------------------------------------------------------------

test("a thrown spawn error fails soft as exec_failed with the could-not-run message", async () => {
  const { host } = fakeExec(new Error("ENOENT"));
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["land", "--json"], {
    label: "perk land",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.equal(r.errorType, "exec_failed");
    assert.match(r.message, /^could not run '.*': Error: ENOENT$/);
    assert.ok(!("payload" in r), "an exec throw carries no payload");
  }
});

// --- killed / non-zero exit (envelope-aware) ----------------------------------------------------

test("non-zero exit with a success:false envelope surfaces its error_type and message", async () => {
  const { host } = fakeExec({
    code: 1,
    stdout: '{"success": false, "error_type": "no_learn_issues", "message": "nothing to learn"}',
    stderr: "Traceback noise",
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["learn-docs", "--json"], {
    label: "perk learn-docs",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "nothing to learn",
    errorType: "no_learn_issues",
    payload: { success: false, error_type: "no_learn_issues", message: "nothing to learn" },
  });
});

test("non-zero exit envelope carries the parsed payload on the fail arm (extra fields ride through)", async () => {
  const { host } = fakeExec({
    code: 1,
    stdout:
      '{"success": false, "error_type": null, "message": null, ' +
      '"results": [{"thread_id": "t1", "success": false}]}',
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr", "resolve-threads", "--json"], {
    label: "perk pr resolve-threads",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.ok(r.payload !== undefined);
    assert.deepEqual(r.payload?.results, [{ thread_id: "t1", success: false }]);
  }
});

test("non-zero exit envelope with non-string fields falls through to the fallback text", async () => {
  const { host } = fakeExec({
    code: 2,
    stdout: '{"success": false, "error_type": 7, "message": null}',
    stderr: "boom",
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.equal(r.message, "perk pr-submit failed (exit 2): boom");
    // error_type was non-string ⇒ ignored, but the envelope still carried success:false,
    // so the structured arm fires with the exec_failed default.
    assert.equal(r.errorType, "exec_failed");
  }
});

test("non-zero exit without an envelope uses the stderr tail (no payload)", async () => {
  const { host } = fakeExec({ code: 3, stdout: "not json", stderr: "  it broke  \n" });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["ready", "--json"], {
    label: "perk pr-ready",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "perk pr-ready failed (exit 3): it broke",
    errorType: "exec_failed",
  });
  if (!r.ok) assert.ok(!("payload" in r), "unparseable stdout carries no payload");
});

test("non-zero exit without an envelope or stderr hints at PATH/PERK_BIN", async () => {
  const { host } = fakeExec({ code: 127, stdout: "", stderr: "" });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["ready", "--json"], {
    label: "perk pr-ready",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "could not run 'perk' (exit 127) — is the perk CLI on PATH or PERK_BIN set?",
    errorType: "exec_failed",
  });
});

test("killed: true is handled like a non-zero exit", async () => {
  const { host } = fakeExec({ code: 0, killed: true, stdout: "", stderr: "killed" });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["land", "--json"], {
    label: "perk land",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.equal(r.errorType, "exec_failed");
    assert.equal(r.message, "perk land failed (exit 0): killed");
  }
});

// --- JSON boundary (exit 0) ----------------------------------------------------------------------

test("exit 0 with unparseable stdout fails as bad_output", async () => {
  const { host } = fakeExec({ stdout: "not json at all" });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["plan-save", "--json"], {
    label: "perk plan-save",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "perk plan-save returned unparseable JSON",
    errorType: "bad_output",
  });
});

test("exit 0 with a non-object JSON payload fails as bad_output", async () => {
  const { host } = fakeExec({ stdout: "[1, 2, 3]" });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["plan-save", "--json"], {
    label: "perk plan-save",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) assert.equal(r.errorType, "bad_output");
});

// --- envelope check (exit 0) ---------------------------------------------------------------------

test("success:false at exit 0 defaults to github_error with the reported-failure message", async () => {
  const { host } = fakeExec({ stdout: '{"success": false}' });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "perk pr-submit reported failure",
    errorType: "github_error",
    payload: { success: false },
  });
});

test("success:false at exit 0 carries the parsed envelope payload (extra fields ride through)", async () => {
  const { host } = fakeExec({
    stdout: '{"success": false, "results": [{"thread_id": "t2", "success": true}]}',
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr", "resolve-threads", "--json"], {
    label: "perk pr resolve-threads",
    decode: decodeAll,
  });
  assert.equal(r.ok, false);
  if (!r.ok) assert.deepEqual(r.payload?.results, [{ thread_id: "t2", success: true }]);
});

test("success:false at exit 0 honors string error_type and message", async () => {
  const { host } = fakeExec({
    stdout: '{"success": false, "error_type": "not_a_repo", "message": "not a git repo"}',
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: decodeAll,
  });
  assert.deepEqual(r, {
    ok: false,
    message: "not a git repo",
    errorType: "not_a_repo",
    payload: { success: false, error_type: "not_a_repo", message: "not a git repo" },
  });
});

// --- validated decode ----------------------------------------------------------------------------

test("decode returning null fails as bad_output (unexpected payload)", async () => {
  const { host } = fakeExec({ stdout: '{"success": true}' });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: () => null,
  });
  assert.deepEqual(r, {
    ok: false,
    message:
      "perk pr-submit reported success but returned an unexpected payload — the perk CLI and " +
      "the perk extension may be version-skewed (update/rebase so both planes match)",
    errorType: "bad_output",
  });
});

test("a throwing decode fails as bad_output (no throw escapes the client)", async () => {
  const { host } = fakeExec({ stdout: '{"success": true}' });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: () => {
      throw new Error("decode blew up");
    },
  });
  assert.deepEqual(r, {
    ok: false,
    message:
      "perk pr-submit reported success but returned an unexpected payload — the perk CLI and " +
      "the perk extension may be version-skewed (update/rebase so both planes match)",
    errorType: "bad_output",
  });
});

test("happy path returns ok:true with the decoded value", async () => {
  const { host } = fakeExec({
    stdout: '{"success": true, "pr_number": 7, "branch": "plan-7"}',
  });
  const r = await runColdDoor(host, fakeCtx(tempCwd()), ["pr-submit", "--json"], {
    label: "perk pr-submit",
    decode: (payload) => {
      const pr = payload.pr_number;
      return typeof pr === "number" ? { pr } : null;
    },
  });
  assert.deepEqual(r, { ok: true, data: { pr: 7 } });
});

// --- the stdin channel ---------------------------------------------------------------------------

test("stdin channel stages content in run scratch and appends [flag, path] to argv", async () => {
  const cwd = tempCwd();
  try {
    const branch = [
      { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "run-abc" } },
    ];
    const { host, calls } = fakeExec({ stdout: '{"success": true}' });
    const r = await runColdDoor(host, fakeCtx(cwd, branch), ["pr-resolve-threads", "--json"], {
      label: "perk pr-resolve-threads",
      decode: decodeAll,
      stdin: { flag: "--batch", content: '[{"thread_id": "t1"}]', filename: "batch.json" },
    });
    assert.equal(r.ok, true);
    const expectedPath = join(cwd, ".perk", "workflow", "scratch", "runs", "run-abc", "batch.json");
    assert.deepEqual(calls[0]?.args, ["pr-resolve-threads", "--json", "--batch", expectedPath]);
    assert.equal(readFileSync(expectedPath, "utf8"), '[{"thread_id": "t1"}]');
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("a ctx whose getBranch throws falls back to a cold-door-<ts> stamp run id", async () => {
  const cwd = tempCwd();
  try {
    const ctx: ColdDoorCtx = {
      cwd,
      sessionManager: {
        getBranch: () => {
          throw new Error("no session");
        },
      },
    };
    assert.match(activeRunId(ctx), /^cold-door-\d+$/);
    const { host, calls } = fakeExec({ stdout: '{"success": true}' });
    const r = await runColdDoor(host, ctx, ["learn", "--json"], {
      label: "perk learn",
      decode: decodeAll,
      stdin: { flag: "--summary-file", content: "learned", filename: "summary.md" },
    });
    assert.equal(r.ok, true);
    const path = calls[0]?.args.at(-1);
    assert.ok(path !== undefined);
    assert.match(path, /scratch[/\\]runs[/\\]cold-door-\d+[/\\]summary\.md$/);
    assert.equal(readFileSync(path, "utf8"), "learned");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("an unwritable scratch path fails soft as scratch_failed", async (t) => {
  if (process.platform === "win32" || process.getuid?.() === 0) {
    t.skip("permission-based test needs a non-root POSIX user");
    return;
  }
  const cwd = tempCwd();
  // Make `.perk` read-only so ensureRunScratch's mkdir fails beneath it.
  const perkDir = join(cwd, ".perk");
  mkdirSync(perkDir);
  chmodSync(perkDir, 0o444);
  try {
    const { host, calls } = fakeExec({ stdout: '{"success": true}' });
    const r = await runColdDoor(host, fakeCtx(cwd), ["learn", "--json"], {
      label: "perk learn",
      decode: decodeAll,
      stdin: { flag: "--summary-file", content: "x", filename: "summary.md" },
    });
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.errorType, "scratch_failed");
      assert.match(r.message, /^could not stage input for perk learn: /);
    }
    assert.equal(calls.length, 0); // never exec'd
  } finally {
    chmodSync(perkDir, 0o755);
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the payload-narrowing helpers ---------------------------------------------------------------

test("stringField accepts strings and rejects everything else", () => {
  const payload: ColdJson = { s: "hi", n: 7, missing: undefined, nul: null };
  assert.equal(stringField(payload, "s"), "hi");
  assert.equal(stringField(payload, "n"), undefined);
  assert.equal(stringField(payload, "nul"), undefined);
  assert.equal(stringField(payload, "absent"), undefined);
});

test("numberField accepts numbers and rejects everything else", () => {
  const payload: ColdJson = { n: 42, s: "42", b: true };
  assert.equal(numberField(payload, "n"), 42);
  assert.equal(numberField(payload, "s"), undefined);
  assert.equal(numberField(payload, "b"), undefined);
  assert.equal(numberField(payload, "absent"), undefined);
});

test("booleanField accepts booleans and rejects everything else", () => {
  const payload: ColdJson = { t: true, f: false, n: 0, s: "true" };
  assert.equal(booleanField(payload, "t"), true);
  assert.equal(booleanField(payload, "f"), false);
  assert.equal(booleanField(payload, "n"), undefined);
  assert.equal(booleanField(payload, "s"), undefined);
  assert.equal(booleanField(payload, "absent"), undefined);
});

test("objectField accepts plain objects and rejects arrays/null/scalars", () => {
  const payload: ColdJson = { o: { k: 1 }, a: [1, 2], nul: null, n: 7 };
  assert.deepEqual(objectField(payload, "o"), { k: 1 });
  assert.equal(objectField(payload, "a"), undefined);
  assert.equal(objectField(payload, "nul"), undefined);
  assert.equal(objectField(payload, "n"), undefined);
  assert.equal(objectField(payload, "absent"), undefined);
});

test("nullableStringField accepts strings and null; wrong-typed yields undefined", () => {
  const payload: ColdJson = { s: "hi", nul: null, n: 7 };
  assert.equal(nullableStringField(payload, "s"), "hi");
  assert.equal(nullableStringField(payload, "nul"), null);
  assert.equal(nullableStringField(payload, "n"), undefined);
  assert.equal(nullableStringField(payload, "absent"), undefined);
});

// --- activeRunId ---------------------------------------------------------------------------------

test("activeRunId reads the workflow-state run_id when present", () => {
  const branch = [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "run-xyz" } }];
  assert.equal(activeRunId(fakeCtx("/tmp", branch)), "run-xyz");
});

test("activeRunId stamps a fallback when the run_id is empty or absent", () => {
  assert.match(activeRunId(fakeCtx("/tmp", [])), /^cold-door-\d+$/);
  const branch = [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "" } }];
  assert.match(activeRunId(fakeCtx("/tmp", branch)), /^cold-door-\d+$/);
});
