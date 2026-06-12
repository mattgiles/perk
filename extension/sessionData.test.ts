import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { sessionDataDir } from "./cache.ts";
import {
  activeSessionDataDir,
  activeSessionRunId,
  ensureSessionDataDir,
  readSessionData,
  type SessionDataCtx,
  writeSessionData,
} from "./sessionData.ts";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

// --- compile-time satisfaction: the structural slice can never drift from the SDK ------------

const _c: SessionDataCtx = {} as ExtensionContext;
void _c;

// --- fakes ------------------------------------------------------------------------------------

function fakeCtx(cwd: string, branch: unknown[] = []): SessionDataCtx {
  return { cwd, sessionManager: { getBranch: () => branch } };
}

function runIdEntry(runId: string): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: runId } };
}

function tempCwd(): string {
  return mkdtempSync(join(tmpdir(), "session-data-test-"));
}

// --- with a run_id ------------------------------------------------------------------------------

test("run_id present: dir resolution + write/read round-trip under scratch/runs/<rid>/data/", () => {
  const cwd = tempCwd();
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    assert.equal(activeSessionRunId(ctx), "RID");

    const expected = join(cwd, ".pi", "workflow", "scratch", "runs", "RID", "data");
    assert.equal(activeSessionDataDir(ctx), expected);
    assert.equal(expected, sessionDataDir(cwd, "RID"));
    // Pure path: nothing is created by resolution alone.
    assert.ok(!existsSync(expected));

    const written = writeSessionData(ctx, "draft.md", "hello");
    assert.equal(written, join(expected, "draft.md"));
    assert.equal(readSessionData(ctx, "draft.md"), "hello");
    assert.equal(readSessionData(ctx, "missing.md"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("ensureSessionDataDir creates the dir lazily and is idempotent", () => {
  const cwd = tempCwd();
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    const dir = ensureSessionDataDir(ctx);
    assert.ok(dir !== null && existsSync(dir));
    assert.equal(ensureSessionDataDir(ctx), dir);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- without an identity: every helper degrades to null, nothing touches disk ------------------

for (const [label, branch] of [
  ["no workflow-state entries", []],
  ["empty run_id", [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "" } }]],
  ["non-string run_id", [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: 7 } }]],
] as const) {
  test(`${label}: all helpers return null and create nothing`, () => {
    const cwd = tempCwd();
    try {
      const ctx = fakeCtx(cwd, [...branch]);
      assert.equal(activeSessionRunId(ctx), null);
      assert.equal(activeSessionDataDir(ctx), null);
      assert.equal(ensureSessionDataDir(ctx), null);
      assert.equal(readSessionData(ctx, "draft.md"), null);
      assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
      assert.deepEqual(readdirSync(cwd), []);
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
}

test("a throwing getBranch degrades to null (no stamp fallback, unlike coldDoor.activeRunId)", () => {
  const cwd = tempCwd();
  try {
    const ctx: SessionDataCtx = {
      cwd,
      sessionManager: {
        getBranch: () => {
          throw new Error("no session yet");
        },
      },
    };
    assert.equal(activeSessionRunId(ctx), null);
    assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
    assert.deepEqual(readdirSync(cwd), []);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- I/O failure: warn + null, never throw ------------------------------------------------------

test("write failure (read-only parent) returns null without throwing", () => {
  const cwd = tempCwd();
  const piDir = join(cwd, ".pi");
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    mkdirSync(piDir, { recursive: true });
    chmodSync(piDir, 0o444);
    assert.equal(ensureSessionDataDir(ctx), null);
    assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
  } finally {
    chmodSync(piDir, 0o755);
    rmSync(cwd, { recursive: true, force: true });
  }
});
