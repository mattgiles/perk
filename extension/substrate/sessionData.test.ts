import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ReportTarget } from "../surfaces/report.ts";
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
const _r: SessionDataCtx & ReportTarget = {} as ExtensionContext;
void _r;

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

/** Capture console.error calls for the duration of `fn`; returns the captured lines. */
function captureStderr(fn: () => void): string[] {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    fn();
  } finally {
    console.error = original;
  }
  return lines;
}

// --- the explicit-run-id file primitives --------------------------------------------------------

test("write/read round-trip under scratch/runs/<rid>/data/ for an explicit run id", () => {
  const cwd = tempCwd();
  try {
    const expected = join(cwd, ".perk", "workflow", "scratch", "runs", "RID", "data");
    assert.equal(expected, sessionDataDir(cwd, "RID"));

    const written = writeSessionData(cwd, "RID", "draft.md", "hello");
    assert.equal(written, join(expected, "draft.md"));
    assert.equal(readSessionData(cwd, "RID", "draft.md"), "hello");
    assert.equal(readSessionData(cwd, "RID", "missing.md"), null);
    // Another run id reads nothing — the explicit identity keys the storage.
    assert.equal(readSessionData(cwd, "OTHER", "draft.md"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("ensureSessionDataDir creates the dir lazily and is idempotent", () => {
  const cwd = tempCwd();
  try {
    const dir = ensureSessionDataDir(cwd, "RID");
    assert.ok(dir !== null && existsSync(dir));
    assert.equal(ensureSessionDataDir(cwd, "RID"), dir);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("an unsafe explicit run id is refused loudly through the write path, before any write", () => {
  const cwd = tempCwd();
  try {
    for (const hostile of ["../escape", "a/b", "a\\b", ".", ".."]) {
      const warnings = captureStderr(() => {
        assert.equal(ensureSessionDataDir(cwd, hostile), null, JSON.stringify(hostile));
        assert.equal(writeSessionData(cwd, hostile, "draft.md", "x"), null);
      });
      assert.ok(warnings.some((line) => line.includes("unsafe run id")));
      assert.deepEqual(readdirSync(cwd), [], "traversal-bearing identity wrote checkout content");
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("a symlinked checkout cache is refused through the session-data write seam", () => {
  const cwd = tempCwd();
  const outside = tempCwd();
  try {
    symlinkSync(outside, join(cwd, ".perk"), "dir");
    const warnings = captureStderr(() => {
      assert.equal(ensureSessionDataDir(cwd, "RID"), null);
      assert.equal(writeSessionData(cwd, "RID", "draft.md", "x"), null);
    });
    assert.ok(warnings.some((line) => line.includes("symlinked run-scratch path")));
    assert.deepEqual(readdirSync(outside), [], "session-data followed the cache redirect");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});

// --- I/O failure: warn + null, never throw ------------------------------------------------------

test("write failure (read-only parent) returns null without throwing", () => {
  const cwd = tempCwd();
  const perkDir = join(cwd, ".perk");
  try {
    mkdirSync(perkDir, { recursive: true });
    chmodSync(perkDir, 0o444);
    const warnings = captureStderr(() => {
      assert.equal(ensureSessionDataDir(cwd, "RID"), null);
      assert.equal(writeSessionData(cwd, "RID", "draft.md", "x"), null);
    });
    assert.ok(warnings.some((line) => line.includes("could not create session data dir")));
  } finally {
    chmodSync(perkDir, 0o755);
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the identity probes: derive once, degrade to null, never invent ----------------------------

test("activeSessionRunId/activeSessionDataDir: resolved identity keys the pure derived path", () => {
  const cwd = tempCwd();
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    assert.equal(activeSessionRunId(ctx), "RID");
    assert.equal(activeSessionDataDir(ctx), sessionDataDir(cwd, "RID"));
    // Pure path: nothing is created by resolution alone.
    assert.ok(!existsSync(sessionDataDir(cwd, "RID")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

for (const [label, branch] of [
  ["no workflow-state entries", []],
  ["empty run_id", [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "" } }]],
  ["non-string run_id", [{ type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: 7 } }]],
] as const) {
  test(`${label}: the identity probes degrade to null`, () => {
    const cwd = tempCwd();
    try {
      const ctx = fakeCtx(cwd, [...branch]);
      assert.equal(activeSessionRunId(ctx), null);
      assert.equal(activeSessionDataDir(ctx), null);
      assert.deepEqual(readdirSync(cwd), [], "resolution touches nothing on disk");
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
}

test("unsafe rebuilt run ids degrade to no-identity at the probe — null before any path derivation", () => {
  // The read-path trust boundary (isSafeRunId): a hostile rebuilt run_id never reaches a path
  // derivation, a write, or a receipt — the SILENT identity-less arm, not a warning (the write
  // path's ensureRunScratch keeps its loud throw for callers with explicit ids, above).
  const cwd = tempCwd();
  try {
    for (const hostile of ["../escape", "a/b", "a\\b", ".", "..", "nul\0l"]) {
      const ctx = fakeCtx(cwd, [runIdEntry(hostile)]);
      const warnings = captureStderr(() => {
        assert.equal(activeSessionRunId(ctx), null, JSON.stringify(hostile));
        assert.equal(activeSessionDataDir(ctx), null);
      });
      assert.deepEqual(warnings, [], "the identity-less degrade is silent");
    }
    // Legitimate ids (ULID mints, fork derivations) pass the boundary untouched.
    assert.equal(activeSessionRunId(fakeCtx(cwd, [runIdEntry("RID.1")])), "RID.1");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

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
    assert.equal(activeSessionDataDir(ctx), null);
    assert.deepEqual(readdirSync(cwd), []);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});
