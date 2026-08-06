// `gist_draft` tests: the shared-decode smoke (incl. the scope enum's strict-fail), the offline
// core (fakes over a live branch array, mirroring objectiveDraft.test.ts), the reader/renderer,
// and the live harness path proving the tool is callable UNDER the read-only gate (the third
// draft carve-out) with the artifact + pointer landing.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { sessionDataDir } from "../substrate/cache.ts";
import {
  digestSessionData,
  readSessionArtifact,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../substrate/sessionData.ts";
import {
  type EntrySink,
  rebuildWorkflowState,
  type SessionArtifactPointer,
  WORKFLOW_STATE_TYPE,
} from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";
import { loadPerkSession, plantSession, scaffoldRepo } from "../testing/harness.ts";
import {
  decodeGistSaveParams,
  GIST_DRAFT_ARTIFACT,
  type GistDraftResult,
  readGistDraft,
  renderGistDraft,
  writeGistDraft,
} from "./gistDraft.ts";

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

// --- fakes (the objectiveDraft.test.ts fixtures) --------------------------------------------------

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
  return mkdtempSync(join(tmpdir(), "gist-draft-test-"));
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
  return rebuildWorkflowState(branchOfArr(branch)).session_artifacts?.[GIST_DRAFT_ARTIFACT];
}

// --- decode (shared with gist_save) ---------------------------------------------------------------

test("decodeGistSaveParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeGistSaveParams({ prose: "p", scope: "objective" }), {
    prose: "p",
    title: undefined,
    scope: "objective",
  });
  // prose absent decodes to "" (saveGist's invalid_input arm keeps owning that message).
  assert.equal(decodeGistSaveParams({})?.prose, "");
  assert.equal(decodeGistSaveParams(undefined), null);
  assert.equal(decodeGistSaveParams({ prose: 5 }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", title: 5 }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", scope: 5 }), null);
});

test("decodeGistSaveParams: a present scope outside the enum strict-fails", () => {
  assert.equal(decodeGistSaveParams({ prose: "p", scope: "banana" }), null);
  assert.equal(decodeGistSaveParams({ prose: "p", scope: "plan" })?.scope, "plan");
  assert.equal(decodeGistSaveParams({ prose: "p" })?.scope, undefined);
});

// --- core (offline fakes) --------------------------------------------------------------------------

test("core: no run_id ⇒ no_run_id; empty prose ⇒ invalid_input; nothing on disk", () => {
  const cwd = tempCwd();
  try {
    const bare: unknown[] = [];
    const noRun = quietly(() =>
      writeGistDraft(fakeSink(bare), reportableCtx(cwd, bare), { prose: PROSE }),
    );
    assert.equal(noRun.details.ok, false);
    assert.equal(noRun.details.ok === false && noRun.details.error_type, "no_run_id");

    const branch: unknown[] = [runIdEntry("RID")];
    const empty = quietly(() =>
      writeGistDraft(fakeSink(branch), reportableCtx(cwd, branch), { prose: "  \n" }),
    );
    assert.equal(empty.details.ok, false);
    assert.equal(empty.details.ok === false && empty.details.error_type, "invalid_input");
    assert.ok(!existsSync(join(cwd, ".pi")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: happy path writes the JSON artifact, appends the pointer, returns provenance details", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const result = writeGistDraft(fakeSink(branch), ctx, {
      prose: PROSE,
      title: "Faster reviews",
      scope: "plan",
    });

    const path = join(sessionDataDir(cwd, "RID"), GIST_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    const content = readFileSync(path, "utf8");
    // Round-trip: the payload shape is locked (no roadmap — a gist is deliberately light).
    assert.deepEqual(JSON.parse(content), {
      schema_version: 1,
      title: "Faster reviews",
      scope: "plan",
      prose: PROSE,
    });

    const pointer = pointerOf(branch);
    assert.ok(pointer);
    assert.equal(pointer.digest, digestSessionData(content));

    assert.equal(result.details.ok, true);
    assert.deepEqual(result.details, {
      ok: true,
      name: GIST_DRAFT_ARTIFACT,
      path: join(".perk", "workflow", "scratch", "runs", "RID", "data", GIST_DRAFT_ARTIFACT),
      digest: digestSessionData(content),
      bytes: Buffer.byteLength(content, "utf8"),
      run_id: "RID",
    });
    assert.match(result.content[0]?.text ?? "", /Gist draft written → /);
    assert.equal(result.terminate, undefined, "non-terminating by design");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: title/scope omitted from the JSON when not passed; full rewrite updates everything", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const sink = fakeSink(branch);

    assert.equal(writeGistDraft(sink, ctx, { prose: PROSE }).details.ok, true);
    const path = join(sessionDataDir(cwd, "RID"), GIST_DRAFT_ARTIFACT);
    const first = JSON.parse(readFileSync(path, "utf8"));
    assert.deepEqual(first, { schema_version: 1, prose: PROSE });
    assert.ok(!("title" in first) && !("scope" in first));

    assert.equal(
      writeGistDraft(sink, ctx, { prose: "# v2\n", scope: "objective" }).details.ok,
      true,
    );
    const content = readFileSync(path, "utf8");
    assert.deepEqual(JSON.parse(content), {
      schema_version: 1,
      scope: "objective",
      prose: "# v2\n",
    });
    assert.equal(pointerOf(branch)?.digest, digestSessionData(content));
    assert.equal(readSessionArtifact(ctx, GIST_DRAFT_ARTIFACT)?.content, content);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: pointer-append failure (dropping sink) ⇒ write_failed", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const droppingSink: EntrySink = { appendEntry: () => {} };
    const result = quietly(() =>
      writeGistDraft(droppingSink, reportableCtx(cwd, branch), { prose: PROSE }),
    );
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "write_failed");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- readGistDraft (the review-surface reader) ------------------------------------------------------

/** Plant a raw artifact write (file + valid pointer) so malformed payloads are readable. */
function plantArtifact(cwd: string, branch: unknown[], content: string): void {
  const ctx = reportableCtx(cwd, branch);
  assert.ok(writeSessionArtifact(fakeSink(branch), ctx, GIST_DRAFT_ARTIFACT, content));
}

test("readGistDraft: happy path round-trips a writeGistDraft write", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    assert.equal(
      writeGistDraft(fakeSink(branch), ctx, {
        prose: PROSE,
        title: "Faster reviews",
        scope: "objective",
      }).details.ok,
      true,
    );
    assert.deepEqual(readGistDraft(ctx), {
      title: "Faster reviews",
      scope: "objective",
      prose: PROSE,
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("readGistDraft: no pointer/run_id → null (silent fail-open)", () => {
  const cwd = tempCwd();
  try {
    assert.equal(readGistDraft(reportableCtx(cwd, [])), null, "no run_id");
    assert.equal(readGistDraft(reportableCtx(cwd, [runIdEntry("RID")])), null, "no pointer");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("readGistDraft: malformed payloads warn + null", () => {
  for (const [label, content] of [
    ["malformed JSON", "{ not json"],
    ["non-object payload", '["an", "array"]\n'],
    ["wrong schema_version", JSON.stringify({ schema_version: 2, prose: PROSE })],
    ["blank prose", JSON.stringify({ schema_version: 1, prose: "  \n" })],
    ["missing prose", JSON.stringify({ schema_version: 1 })],
  ] as const) {
    const cwd = tempCwd();
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      plantArtifact(cwd, branch, content);
      const draft = quietly(() => readGistDraft(reportableCtx(cwd, branch)));
      assert.equal(draft, null, label);
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  }
});

test("readGistDraft: blank title dropped; an unknown scope degrades to absent", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    plantArtifact(
      cwd,
      branch,
      JSON.stringify({ schema_version: 1, title: "   ", scope: "banana", prose: PROSE }),
    );
    assert.deepEqual(readGistDraft(reportableCtx(cwd, branch)), { prose: PROSE });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- renderGistDraft (the markdown review surface) --------------------------------------------------

test("renderGistDraft: title heading + Scope line + prose", () => {
  const md = renderGistDraft({ title: "Faster reviews", scope: "plan", prose: "The intent.\n" });
  assert.equal(md, "# Faster reviews\n\nScope: plan\n\nThe intent.\n");
});

test("renderGistDraft: no title → no heading; no scope → no Scope line", () => {
  assert.equal(renderGistDraft({ prose: "Just prose.\n" }), "Just prose.\n");
  assert.equal(renderGistDraft({ scope: "objective", prose: "P\n" }), "Scope: objective\n\nP\n");
});

// --- harness: the tool is live UNDER the read-only gate (the carve-out) -----------------------------

test("harness: gist_draft succeeds while read-only; artifact + pointer land", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().mode, "read-only", "the gate is active");
    const result = await h.invokeTool("gist_draft", { prose: PROSE, scope: "plan" });
    const details = result.details as { ok: boolean; run_id?: string };
    assert.equal(details.ok, true);
    assert.equal(details.run_id, "01RID");

    const path = join(sessionDataDir(cwd, "01RID"), GIST_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    const content = readFileSync(path, "utf8");
    assert.deepEqual(JSON.parse(content), { schema_version: 1, scope: "plan", prose: PROSE });
    const pointer = h.workflowState().session_artifacts?.[GIST_DRAFT_ARTIFACT];
    assert.equal(pointer?.digest, digestSessionData(content));
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("harness: mistyped params ⇒ bad_input", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const result = (await h.invokeTool("gist_draft", {
      prose: PROSE,
      scope: "banana",
    })) as unknown as GistDraftResult;
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "bad_input");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});
