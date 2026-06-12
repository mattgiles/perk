// Objective #339 Node 2.1 — `plan_draft` tests: the pure decode, the offline core (fakes over a
// live branch array, mirroring sessionData.test.ts), and the live harness path proving the tool
// is callable UNDER the read-only gate (the carve-out) with the artifact + pointer landing.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { sessionDataDir } from "./cache.ts";
import {
  decodePlanDraftParams,
  PLAN_DRAFT_ARTIFACT,
  type PlanDraftResult,
  writePlanDraft,
} from "./planDraft.ts";
import type { ReportTarget } from "./report.ts";
import { digestSessionData, readSessionArtifact, type SessionDataCtx } from "./sessionData.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import {
  type EntrySink,
  rebuildWorkflowState,
  type SessionArtifactPointer,
  WORKFLOW_STATE_TYPE,
} from "./workflowState.ts";

const PLAN_MD = "# Add retry\n\n## Summary\nAdd retry to the gateway.\n";

// --- fakes (the sessionData.test.ts fixtures) ---------------------------------------------------

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
  return mkdtempSync(join(tmpdir(), "plan-draft-test-"));
}

/** Capture console.error calls for the duration of `fn` (silences the seam's loud warnings). */
function quietly<T>(fn: () => T): T {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

/** The test-side branch cast (the tests own their fixture shapes). */
function branchOfArr(branch: unknown[]) {
  return branch as Parameters<typeof rebuildWorkflowState>[0];
}

function pointerOf(branch: unknown[]): SessionArtifactPointer | undefined {
  return rebuildWorkflowState(branchOfArr(branch)).session_artifacts?.[PLAN_DRAFT_ARTIFACT];
}

// --- decode -------------------------------------------------------------------------------------

test("decode: absent plan decodes to empty string (the core owns invalid_input)", () => {
  assert.deepEqual(decodePlanDraftParams({}), { plan: "" });
});

test("decode: mistyped plan (number) is strict-fail null", () => {
  assert.equal(decodePlanDraftParams({ plan: 42 }), null);
});

test("decode: non-object params are null", () => {
  assert.equal(decodePlanDraftParams("plan"), null);
  assert.equal(decodePlanDraftParams(null), null);
  assert.equal(decodePlanDraftParams([PLAN_MD]), null);
});

test("decode: extra keys are ignored (the schema owns additionalProperties)", () => {
  assert.deepEqual(decodePlanDraftParams({ plan: PLAN_MD, extra: 1 }), { plan: PLAN_MD });
});

// --- core (offline fakes) -----------------------------------------------------------------------

test("core: no run_id ⇒ no_run_id, nothing on disk", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [];
    const result = quietly(() =>
      writePlanDraft(fakeSink(branch), reportableCtx(cwd, branch), PLAN_MD),
    );
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "no_run_id");
    assert.ok(!existsSync(join(cwd, ".pi")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: empty/whitespace plan ⇒ invalid_input", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    for (const plan of ["", "   \n\t "]) {
      const result = quietly(() =>
        writePlanDraft(fakeSink(branch), reportableCtx(cwd, branch), plan),
      );
      assert.equal(result.details.ok, false);
      assert.equal(result.details.ok === false && result.details.error_type, "invalid_input");
    }
    assert.ok(!existsSync(join(cwd, ".pi")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: happy path writes the file, appends the pointer, returns provenance details", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const result = writePlanDraft(fakeSink(branch), ctx, PLAN_MD);

    const path = join(sessionDataDir(cwd, "RID"), PLAN_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    assert.equal(readFileSync(path, "utf8"), PLAN_MD);

    const pointer = pointerOf(branch);
    assert.ok(pointer);
    assert.equal(pointer.digest, digestSessionData(PLAN_MD));

    assert.equal(result.details.ok, true);
    assert.deepEqual(result.details, {
      ok: true,
      name: PLAN_DRAFT_ARTIFACT,
      path: join(".pi", "workflow", "scratch", "runs", "RID", "data", PLAN_DRAFT_ARTIFACT),
      digest: digestSessionData(PLAN_MD),
      bytes: Buffer.byteLength(PLAN_MD, "utf8"),
      run_id: "RID",
    });
    assert.match(result.content[0]?.text ?? "", /Plan draft written → /);
    assert.equal(result.terminate, undefined, "non-terminating by design");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: full rewrite — a second call updates disk, pointer digest, and the validated read", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const sink = fakeSink(branch);

    assert.equal(writePlanDraft(sink, ctx, "# v1\nbody\n").details.ok, true);
    assert.equal(writePlanDraft(sink, ctx, "# v2\nrevised\n").details.ok, true);

    const path = join(sessionDataDir(cwd, "RID"), PLAN_DRAFT_ARTIFACT);
    assert.equal(readFileSync(path, "utf8"), "# v2\nrevised\n");
    assert.equal(pointerOf(branch)?.digest, digestSessionData("# v2\nrevised\n"));
    assert.equal(readSessionArtifact(ctx, PLAN_DRAFT_ARTIFACT)?.content, "# v2\nrevised\n");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: pointer-append failure (dropping sink) ⇒ write_failed", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const droppingSink: EntrySink = { appendEntry: () => {} };
    const result = quietly(() => writePlanDraft(droppingSink, reportableCtx(cwd, branch), PLAN_MD));
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "write_failed");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- harness: the tool is live UNDER the read-only gate (the carve-out) -------------------------

test("harness: plan_draft succeeds while read-only; artifact + pointer land", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().mode, "read-only", "the gate is active");
    const result = await h.invokeTool("plan_draft", { plan: PLAN_MD });
    const details = result.details as { ok: boolean; run_id?: string; digest?: string };
    assert.equal(details.ok, true);
    assert.equal(details.run_id, "01RID");

    const path = join(sessionDataDir(cwd, "01RID"), PLAN_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    assert.equal(readFileSync(path, "utf8"), PLAN_MD);
    const pointer = h.workflowState().session_artifacts?.[PLAN_DRAFT_ARTIFACT];
    assert.equal(pointer?.digest, digestSessionData(PLAN_MD));
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("harness: mistyped params ⇒ bad_input", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const result = (await h.invokeTool("plan_draft", { plan: 42 })) as unknown as PlanDraftResult;
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "bad_input");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});
