import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
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
  digestSessionData,
  ensureSessionDataDir,
  readSessionArtifact,
  readSessionData,
  type SessionDataCtx,
  writeSessionArtifact,
  writeSessionData,
} from "./sessionData.ts";
import { type EntrySink, rebuildWorkflowState, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

// --- compile-time satisfaction: the structural slice can never drift from the SDK ------------

const _c: SessionDataCtx = {} as ExtensionContext;
void _c;
const _r: SessionDataCtx & ReportTarget = {} as ExtensionContext;
void _r;

// --- fakes ------------------------------------------------------------------------------------

function fakeCtx(cwd: string, branch: unknown[] = []): SessionDataCtx {
  return { cwd, sessionManager: { getBranch: () => branch } };
}

/** A `SessionDataCtx & ReportTarget` over a live branch array (headless, notify is a no-op). */
function reportableCtx(cwd: string, branch: unknown[]): SessionDataCtx & ReportTarget {
  return {
    cwd,
    sessionManager: { getBranch: () => branch },
    hasUI: false,
    ui: { notify() {} },
  };
}

/** A live sink: appends land on the same branch array the ctx rebuilds from. */
function fakeSink(branch: unknown[]): EntrySink {
  return {
    appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }),
  };
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

// --- with a run_id ------------------------------------------------------------------------------

test("run_id present: dir resolution + write/read round-trip under scratch/runs/<rid>/data/", () => {
  const cwd = tempCwd();
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    assert.equal(activeSessionRunId(ctx), "RID");

    const expected = join(cwd, ".perk", "workflow", "scratch", "runs", "RID", "data");
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

test("unsafe run ids are refused through the session-data write seam before any write", () => {
  const cwd = tempCwd();
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("../escape")]);
    const warnings = captureStderr(() => {
      assert.equal(ensureSessionDataDir(ctx), null);
      assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
    });
    assert.ok(warnings.some((line) => line.includes("unsafe run id")));
    assert.deepEqual(readdirSync(cwd), [], "traversal-bearing identity wrote checkout content");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("a symlinked checkout cache is refused through the session-data write seam", () => {
  const cwd = tempCwd();
  const outside = tempCwd();
  try {
    symlinkSync(outside, join(cwd, ".perk"), "dir");
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    const warnings = captureStderr(() => {
      assert.equal(ensureSessionDataDir(ctx), null);
      assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
    });
    assert.ok(warnings.some((line) => line.includes("symlinked run-scratch path")));
    assert.deepEqual(readdirSync(outside), [], "session-data followed the cache redirect");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
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
    assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
    assert.deepEqual(readdirSync(cwd), []);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- I/O failure: warn + null, never throw ------------------------------------------------------

test("write failure (read-only parent) returns null without throwing", () => {
  const cwd = tempCwd();
  const perkDir = join(cwd, ".perk");
  try {
    const ctx = fakeCtx(cwd, [runIdEntry("RID")]);
    mkdirSync(perkDir, { recursive: true });
    chmodSync(perkDir, 0o444);
    assert.equal(ensureSessionDataDir(ctx), null);
    assert.equal(writeSessionData(ctx, "draft.md", "x"), null);
  } finally {
    chmodSync(perkDir, 0o755);
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- provenance pointers -------------------------------------------------------------

test("artifact round-trip: pointer recorded, read returns content + derived path", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const sink = fakeSink(branch);

    const written = writeSessionArtifact(sink, ctx, "draft.md", "hello");
    assert.equal(written, join(sessionDataDir(cwd, "RID"), "draft.md"));

    const pointer = rebuildWorkflowState(branchOfArr(branch)).session_artifacts?.["draft.md"];
    assert.ok(pointer);
    assert.equal(pointer.run_id, "RID");
    assert.equal(pointer.name, "draft.md");
    assert.equal(pointer.digest, digestSessionData("hello"));
    assert.equal(
      pointer.path,
      join(".perk", "workflow", "scratch", "runs", "RID", "data", "draft.md"),
    );
    assert.ok(!Number.isNaN(Date.parse(pointer.at)));

    const read = readSessionArtifact(ctx, "draft.md");
    assert.deepEqual(read, { path: written, content: "hello" });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("sibling merge: each append carries the whole map, so earlier pointers survive", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const sink = fakeSink(branch);

    assert.ok(writeSessionArtifact(sink, ctx, "a.md", "alpha"));
    assert.ok(writeSessionArtifact(sink, ctx, "b.md", "beta"));

    const map = rebuildWorkflowState(branchOfArr(branch)).session_artifacts ?? {};
    assert.deepEqual(Object.keys(map).sort(), ["a.md", "b.md"]);
    assert.deepEqual(readSessionArtifact(ctx, "a.md")?.content, "alpha");
    assert.deepEqual(readSessionArtifact(ctx, "b.md")?.content, "beta");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("rewind: older pointer vs newer disk bytes ⇒ digest mismatch ⇒ warn + null", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const sink = fakeSink(branch);

    assert.ok(writeSessionArtifact(sink, ctx, "draft.md", "v1"));
    const afterV1 = branch.length;
    assert.ok(writeSessionArtifact(sink, ctx, "draft.md", "v2")); // disk now holds v2

    // Tree navigation back to just after v1's entry: the rebuilt branch carries v1's pointer.
    const rewound = reportableCtx(cwd, branch.slice(0, afterV1));
    let result: ReturnType<typeof readSessionArtifact> = null;
    const warnings = captureStderr(() => {
      result = readSessionArtifact(rewound, "draft.md");
    });
    assert.equal(result, null);
    assert.ok(warnings.some((line) => line.includes("digest mismatch")));
    // The current (un-rewound) ctx still reads v2 fine.
    assert.equal(readSessionArtifact(ctx, "draft.md")?.content, "v2");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("fork: inherited pointer under a derived child run_id ⇒ silent null, fresh dir", () => {
  const cwd = tempCwd();
  try {
    const parentBranch: unknown[] = [runIdEntry("RID")];
    const parentCtx = reportableCtx(cwd, parentBranch);
    assert.ok(writeSessionArtifact(fakeSink(parentBranch), parentCtx, "draft.md", "parent"));

    // A fork child inherits the parent's entries; decideClaim then derives `RID.1`.
    const childBranch = [...parentBranch, runIdEntry("RID.1")];
    const childCtx = reportableCtx(cwd, childBranch);
    assert.equal(activeSessionRunId(childCtx), "RID.1");
    const warnings = captureStderr(() => {
      assert.equal(readSessionArtifact(childCtx, "draft.md"), null);
    });
    assert.deepEqual(warnings, []); // the designed isolation path is silent
    assert.ok(!existsSync(sessionDataDir(cwd, "RID.1"))); // fresh dir — no inheritance
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("reload persistence: a fresh ctx over the same entries + cwd still validates", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    assert.ok(writeSessionArtifact(fakeSink(branch), reportableCtx(cwd, branch), "draft.md", "x"));

    const reloaded = reportableCtx(cwd, [...branch]); // same run_id, rebuilt-from-scratch view
    assert.equal(readSessionArtifact(reloaded, "draft.md")?.content, "x");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("concurrent isolation: run_id keying isolates pointers and dirs across sessions", () => {
  const cwd = tempCwd();
  try {
    const branchA: unknown[] = [runIdEntry("A")];
    const branchB: unknown[] = [runIdEntry("B")];
    const ctxA = reportableCtx(cwd, branchA);
    const ctxB = reportableCtx(cwd, branchB);
    assert.ok(writeSessionArtifact(fakeSink(branchA), ctxA, "a.md", "from A"));
    assert.ok(writeSessionArtifact(fakeSink(branchB), ctxB, "b.md", "from B"));

    assert.equal(readSessionArtifact(ctxA, "a.md")?.content, "from A");
    assert.equal(readSessionArtifact(ctxB, "b.md")?.content, "from B");
    assert.equal(readSessionArtifact(ctxA, "b.md"), null); // silent: no pointer on A's branch
    assert.equal(readSessionArtifact(ctxB, "a.md"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("untrusted pointer.path is never dereferenced — validation uses the derived path only", () => {
  const cwd = tempCwd();
  try {
    // A real artifact on disk at the derived location…
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const real = writeSessionData(ctx, "draft.md", "real");
    assert.ok(real);
    // …and a foreign file elsewhere that a malicious pointer.path points at.
    const foreign = join(cwd, "foreign.md");
    writeFileSync(foreign, "foreign", "utf8");
    branch.push({
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: {
        session_artifacts: {
          "draft.md": {
            run_id: "RID",
            name: "draft.md",
            path: foreign, // absolute, hostile — must be ignored
            digest: digestSessionData("real"),
            at: new Date().toISOString(),
          },
        },
      },
    });

    const read = readSessionArtifact(ctx, "draft.md");
    assert.deepEqual(read, { path: real, content: "real" }); // derived file, never the foreign one
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("pointer-append failure (dropping sink) ⇒ writer returns null though the file exists", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const droppingSink: EntrySink = { appendEntry: () => {} };
    let written: string | null = "sentinel";
    const warnings = captureStderr(() => {
      written = writeSessionArtifact(droppingSink, ctx, "draft.md", "hello");
    });
    assert.equal(written, null);
    assert.ok(warnings.some((line) => line.includes("session_artifacts pointer read-back failed")));
    // The orphan file exists on disk (gitignored scratch; the GC prunes it)…
    assert.ok(existsSync(join(sessionDataDir(cwd, "RID"), "draft.md")));
    // …but it is not consumable: no pointer landed.
    assert.equal(readSessionArtifact(ctx, "draft.md"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("no identity: artifact helpers degrade to null, nothing appended, nothing on disk", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [];
    const ctx = reportableCtx(cwd, branch);
    assert.equal(writeSessionArtifact(fakeSink(branch), ctx, "draft.md", "x"), null);
    assert.equal(readSessionArtifact(ctx, "draft.md"), null);
    assert.equal(branch.length, 0); // no pointer entry appended
    assert.deepEqual(readdirSync(cwd), []);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("file-write failure: writer returns null and appends no pointer", () => {
  const cwd = tempCwd();
  const perkDir = join(cwd, ".perk");
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    mkdirSync(perkDir, { recursive: true });
    chmodSync(perkDir, 0o444);
    assert.equal(writeSessionArtifact(fakeSink(branch), ctx, "draft.md", "x"), null);
    assert.equal(branch.length, 1); // only the run_id entry — no pointer
  } finally {
    chmodSync(perkDir, 0o755);
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("missing file despite a pointer ⇒ warn + null", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    assert.ok(writeSessionArtifact(fakeSink(branch), ctx, "draft.md", "hello"));
    rmSync(join(sessionDataDir(cwd, "RID"), "draft.md"));

    let result: ReturnType<typeof readSessionArtifact> = null;
    const warnings = captureStderr(() => {
      result = readSessionArtifact(ctx, "draft.md");
    });
    assert.equal(result, null);
    assert.ok(warnings.some((line) => line.includes("has a pointer but no file")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

/** The test-side branch cast (the tests own their fixture shapes; mirrors fakeCtx's looseness). */
function branchOfArr(branch: unknown[]) {
  return branch as Parameters<typeof rebuildWorkflowState>[0];
}
