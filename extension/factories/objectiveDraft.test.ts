// `objective_draft` tests: the shared-decode smoke, the offline core
// (fakes over a live branch array, mirroring planDraft.test.ts), and the live harness path proving
// the tool is callable UNDER the read-only gate (the carve-out) with the artifact + pointer
// landing.

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
  decodeObjectiveSaveParams,
  OBJECTIVE_DRAFT_ARTIFACT,
  type ObjectiveDraft,
  type ObjectiveDraftResult,
  ROADMAP_PARAM_SCHEMA,
  readObjectiveDraft,
  renderObjectiveDraft,
  writeObjectiveDraft,
} from "./objectiveDraft.ts";

const PROSE = "# Conform objective planning\n\nThe why, the design, the boundaries.\n";
const ROADMAP = [
  { id: "1.1", description: "first" },
  { id: "2.1", description: "second", weird_extra: { nested: true } }, // unknown-shaped: kept verbatim
];

// --- fakes (the planDraft.test.ts fixtures) ------------------------------------------------------

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
  return mkdtempSync(join(tmpdir(), "objective-draft-test-"));
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
  return rebuildWorkflowState(branchOfArr(branch)).session_artifacts?.[OBJECTIVE_DRAFT_ARTIFACT];
}

// --- decode (shared with objective_save; the full vocabulary tests live at the bottom) -----------

test("decode smoke: absent prose decodes to empty string (the core owns invalid_input)", () => {
  assert.deepEqual(decodeObjectiveSaveParams({}), {
    prose: "",
    title: undefined,
    roadmap: undefined,
    base: undefined,
    delivery: undefined,
  });
});

test("decode: base is decoded when a string, refused when mistyped", () => {
  const decoded = decodeObjectiveSaveParams({ prose: "p", base: "develop" });
  assert.equal(decoded?.base, "develop");
  assert.equal(decodeObjectiveSaveParams({ prose: "p", base: 7 }), null);
});

test("decode: delivery is a strict enum — valid values pass, junk/mistyped refuse", () => {
  assert.equal(decodeObjectiveSaveParams({ prose: "p", delivery: "stacked" })?.delivery, "stacked");
  assert.equal(
    decodeObjectiveSaveParams({ prose: "p", delivery: "incremental" })?.delivery,
    "incremental",
  );
  assert.equal(decodeObjectiveSaveParams({ prose: "p" })?.delivery, undefined);
  assert.equal(decodeObjectiveSaveParams({ prose: "p", delivery: "atomic" }), null);
  assert.equal(decodeObjectiveSaveParams({ prose: "p", delivery: 7 }), null);
});

// --- core (offline fakes) -----------------------------------------------------------------------

test("core: no run_id ⇒ no_run_id, nothing on disk", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [];
    const result = quietly(() =>
      writeObjectiveDraft(fakeSink(branch), reportableCtx(cwd, branch), { prose: PROSE }),
    );
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "no_run_id");
    assert.ok(!existsSync(join(cwd, ".pi")));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: empty/whitespace prose ⇒ invalid_input, nothing on disk", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    for (const prose of ["", "   \n\t "]) {
      const result = quietly(() =>
        writeObjectiveDraft(fakeSink(branch), reportableCtx(cwd, branch), { prose }),
      );
      assert.equal(result.details.ok, false);
      assert.equal(result.details.ok === false && result.details.error_type, "invalid_input");
    }
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
    const result = writeObjectiveDraft(fakeSink(branch), ctx, {
      prose: PROSE,
      title: "Objective title",
      roadmap: ROADMAP,
    });

    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    const content = readFileSync(path, "utf8");
    // Round-trip: the payload shape is locked; the roadmap rides verbatim (never validated).
    assert.deepEqual(JSON.parse(content), {
      schema_version: 1,
      title: "Objective title",
      prose: PROSE,
      roadmap: ROADMAP,
    });

    const pointer = pointerOf(branch);
    assert.ok(pointer);
    assert.equal(pointer.digest, digestSessionData(content));

    assert.equal(result.details.ok, true);
    assert.deepEqual(result.details, {
      ok: true,
      name: OBJECTIVE_DRAFT_ARTIFACT,
      path: join(".perk", "workflow", "scratch", "runs", "RID", "data", OBJECTIVE_DRAFT_ARTIFACT),
      digest: digestSessionData(content),
      bytes: Buffer.byteLength(content, "utf8"),
      run_id: "RID",
      roadmap_nodes: 2,
    });
    assert.match(result.content[0]?.text ?? "", /Objective draft written → /);
    assert.match(result.content[0]?.text ?? "", /2 roadmap nodes/);
    assert.equal(result.terminate, undefined, "non-terminating by design");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: title omitted from the JSON when not passed; absent roadmap serializes as []", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    const result = writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE });
    assert.equal(result.details.ok, true);
    assert.equal(result.details.ok === true && result.details.roadmap_nodes, 0);

    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    assert.deepEqual(parsed, { schema_version: 1, prose: PROSE, roadmap: [] });
    assert.ok(!("title" in parsed));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: delivery persists through write/read; omitted when absent; junk dropped on read", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE, delivery: "stacked" });
    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    assert.equal(JSON.parse(readFileSync(path, "utf8")).delivery, "stacked");
    assert.equal(readObjectiveDraft(ctx)?.delivery, "stacked");

    // A subsequent write with no delivery drops it from disk + the validated read.
    writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE });
    assert.ok(!("delivery" in JSON.parse(readFileSync(path, "utf8"))));
    assert.equal(readObjectiveDraft(ctx)?.delivery, undefined);

    // Junk in the artifact recovers as absent (mirrors `base`'s fail-open posture).
    plantArtifact(
      cwd,
      branch,
      JSON.stringify({ schema_version: 1, delivery: "atomic", prose: PROSE, roadmap: [] }),
    );
    assert.equal(readObjectiveDraft(ctx)?.delivery, undefined);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("core: base persists through write/read; omitted when absent", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE, base: "develop" });
    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    assert.equal(parsed.base, "develop");
    assert.equal(readObjectiveDraft(ctx)?.base, "develop");

    // A subsequent write with no base drops it from disk + the validated read.
    writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE });
    const reparsed = JSON.parse(readFileSync(path, "utf8"));
    assert.ok(!("base" in reparsed));
    assert.equal(readObjectiveDraft(ctx)?.base, undefined);
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

    assert.equal(writeObjectiveDraft(sink, ctx, { prose: "# v1\n" }).details.ok, true);
    assert.equal(
      writeObjectiveDraft(sink, ctx, { prose: "# v2\n", roadmap: ROADMAP }).details.ok,
      true,
    );

    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    const content = readFileSync(path, "utf8");
    assert.deepEqual(JSON.parse(content), { schema_version: 1, prose: "# v2\n", roadmap: ROADMAP });
    assert.equal(pointerOf(branch)?.digest, digestSessionData(content));
    assert.equal(readSessionArtifact(ctx, OBJECTIVE_DRAFT_ARTIFACT)?.content, content);
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
      writeObjectiveDraft(droppingSink, reportableCtx(cwd, branch), { prose: PROSE }),
    );
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "write_failed");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- readObjectiveDraft (the node-2.2 review-surface reader) -------------------------------------

/** Plant a raw artifact write (file + valid pointer) so malformed payloads are readable. */
function plantArtifact(cwd: string, branch: unknown[], content: string): void {
  const ctx = reportableCtx(cwd, branch);
  assert.ok(writeSessionArtifact(fakeSink(branch), ctx, OBJECTIVE_DRAFT_ARTIFACT, content));
}

test("readObjectiveDraft: happy path round-trips a writeObjectiveDraft write", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    assert.equal(
      writeObjectiveDraft(fakeSink(branch), ctx, {
        prose: PROSE,
        title: "Objective title",
        roadmap: ROADMAP,
      }).details.ok,
      true,
    );
    assert.deepEqual(readObjectiveDraft(ctx), {
      title: "Objective title",
      prose: PROSE,
      roadmap: ROADMAP,
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("readObjectiveDraft: no pointer/run_id → null (silent fail-open)", () => {
  const cwd = tempCwd();
  try {
    assert.equal(readObjectiveDraft(reportableCtx(cwd, [])), null, "no run_id");
    assert.equal(readObjectiveDraft(reportableCtx(cwd, [runIdEntry("RID")])), null, "no pointer");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("readObjectiveDraft: malformed payloads warn + null", () => {
  for (const [label, content] of [
    ["malformed JSON", "{ not json"],
    ["non-object payload", '["an", "array"]\n'],
    ["wrong schema_version", JSON.stringify({ schema_version: 2, prose: PROSE, roadmap: [] })],
    ["blank prose", JSON.stringify({ schema_version: 1, prose: "  \n", roadmap: [] })],
    ["missing prose", JSON.stringify({ schema_version: 1, roadmap: [] })],
  ] as const) {
    const cwd = tempCwd();
    try {
      const branch: unknown[] = [runIdEntry("RID")];
      plantArtifact(cwd, branch, content);
      const draft = quietly(() => readObjectiveDraft(reportableCtx(cwd, branch)));
      assert.equal(draft, null, label);
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  }
});

test("readObjectiveDraft: absent/non-array roadmap → []; blank title dropped", () => {
  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    plantArtifact(
      cwd,
      branch,
      JSON.stringify({ schema_version: 1, title: "   ", prose: PROSE, roadmap: "nope" }),
    );
    assert.deepEqual(readObjectiveDraft(reportableCtx(cwd, branch)), {
      prose: PROSE,
      roadmap: [],
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- renderObjectiveDraft (the markdown review surface) ------------------------------------------

test("renderObjectiveDraft: title heading + prose + roadmap table with defaults", () => {
  const draft: ObjectiveDraft = {
    title: "Objective title",
    prose: "The why.\n",
    roadmap: [
      { id: "1.1", description: "first", status: "done" },
      { id: "2.1", description: "second", depends_on: ["1.1", "1.2"] },
    ],
  };
  const md = renderObjectiveDraft(draft);
  assert.ok(
    md.startsWith(
      "# Objective title\n\n**Delivery: incremental** (the default — each plan lands " +
        "independently)\n\nThe why.\n",
    ),
  );
  assert.match(md, /## Roadmap/);
  assert.match(md, /\| Node \| Description \| Depends On \| Status \|/);
  assert.match(md, /\| 1\.1 \| first \| - \| done \|/);
  assert.match(md, /\| 2\.1 \| second \| 1\.1, 1\.2 \| pending \|/, "status defaults to pending");
  assert.doesNotMatch(md, /\| Phase \|/, "no Phase column without a phase");
});

test("renderObjectiveDraft: no title → no heading; empty roadmap → no Roadmap section", () => {
  const md = renderObjectiveDraft({ prose: "Just prose.\n", roadmap: [] });
  assert.equal(
    md,
    "**Delivery: incremental** (the default — each plan lands independently)\n\nJust prose.\n",
  );
  assert.doesNotMatch(md, /## Roadmap/);
});

test("renderObjectiveDraft: the Delivery line is always present — both variants pinned", () => {
  // Explicit-incremental and absent render the SAME default line.
  const incremental = renderObjectiveDraft({ prose: "P", roadmap: [], delivery: "incremental" });
  const absent = renderObjectiveDraft({ prose: "P", roadmap: [] });
  assert.equal(incremental, absent);
  assert.match(
    absent,
    /\*\*Delivery: incremental\*\* \(the default — each plan lands independently\)/,
  );

  const stacked = renderObjectiveDraft({
    title: "T",
    prose: "P",
    roadmap: [],
    delivery: "stacked",
  });
  assert.match(
    stacked,
    /\*\*Delivery: STACKED\*\* — all non-skipped roadmap nodes land as ONE atomic pull-request train \(capability-checked at save; write-gated while under development\)/,
  );
  // Directly under the title heading.
  assert.ok(stacked.startsWith("# T\n\n**Delivery: STACKED**"));
});

test("renderObjectiveDraft: Phase column appears iff any node carries a phase", () => {
  const md = renderObjectiveDraft({
    prose: "P",
    roadmap: [
      { id: "1.1", description: "first", phase: "Phase 1" },
      { id: "2.1", description: "second" },
    ],
  });
  assert.match(md, /\| Node \| Phase \| Description \| Depends On \| Status \|/);
  assert.match(md, /\| 1\.1 \| Phase 1 \| first \| - \| pending \|/);
  assert.match(
    md,
    /\| 2\.1 \| {2}\| second \| - \| pending \|/,
    "phase-less node gets an empty cell",
  );
});

test("renderObjectiveDraft: cells are sanitized (pipes escaped, newlines collapsed)", () => {
  const md = renderObjectiveDraft({
    prose: "P",
    roadmap: [{ id: "1.1", description: "a | b\nc", status: 7 }],
  });
  assert.match(md, /\| 1\.1 \| a \\\| b c \| - \| pending \|/, "mistyped status falls to pending");
});

// --- harness: the tool is live UNDER the read-only gate (the carve-out) -------------------------

test("harness: objective_draft succeeds while read-only; artifact + pointer land", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().mode, "read-only", "the gate is active");
    const result = await h.invokeTool("objective_draft", { prose: PROSE, roadmap: ROADMAP });
    const details = result.details as { ok: boolean; run_id?: string; roadmap_nodes?: number };
    assert.equal(details.ok, true);
    assert.equal(details.run_id, "01RID");
    assert.equal(details.roadmap_nodes, 2);

    const path = join(sessionDataDir(cwd, "01RID"), OBJECTIVE_DRAFT_ARTIFACT);
    assert.ok(existsSync(path));
    const content = readFileSync(path, "utf8");
    assert.deepEqual(JSON.parse(content), { schema_version: 1, prose: PROSE, roadmap: ROADMAP });
    const pointer = h.workflowState().session_artifacts?.[OBJECTIVE_DRAFT_ARTIFACT];
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
    const result = (await h.invokeTool("objective_draft", {
      prose: PROSE,
      roadmap: "not-an-array",
    })) as unknown as ObjectiveDraftResult;
    assert.equal(result.details.ok, false);
    assert.equal(result.details.ok === false && result.details.error_type, "bad_input");
  } finally {
    h.dispose();
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the shared draft/save param vocabulary (moved in with its module) ----------

test("decodeObjectiveSaveParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeObjectiveSaveParams({ prose: "p", roadmap: [{ id: "1.1" }] }), {
    prose: "p",
    title: undefined,
    roadmap: [{ id: "1.1" }],
    base: undefined,
    delivery: undefined,
  });
  // prose absent decodes to "" (saveObjective's invalid_input arm keeps owning that message).
  assert.equal(decodeObjectiveSaveParams({})?.prose, "");
  assert.equal(decodeObjectiveSaveParams(undefined), null);
  assert.equal(decodeObjectiveSaveParams({ prose: 5 }), null);
  assert.equal(decodeObjectiveSaveParams({ prose: "p", title: 5 }), null);
  assert.equal(decodeObjectiveSaveParams({ prose: "p", roadmap: "x" }), null);
});

test("ROADMAP_PARAM_SCHEMA: the shared roadmap-items schema keeps its node shape", () => {
  assert.equal(ROADMAP_PARAM_SCHEMA.type, "object");
  assert.equal(ROADMAP_PARAM_SCHEMA.additionalProperties, false);
  assert.deepEqual([...ROADMAP_PARAM_SCHEMA.required], ["id", "description"]);
  assert.deepEqual(Object.keys(ROADMAP_PARAM_SCHEMA.properties), [
    "id",
    "description",
    "status",
    "slug",
    "pr",
    "depends_on",
    "comment",
    "adopt_issue",
  ]);
});

test("adopt_issue: a node carrying adopt_issue decodes + writes through verbatim", () => {
  // The schema accepts adopt_issue (additionalProperties:false would otherwise reject it) and the
  // decoder keeps roadmap opaque, so the field rides unchanged to the Python cold door.
  assert.equal(
    (ROADMAP_PARAM_SCHEMA.properties as Record<string, unknown>).adopt_issue !== undefined,
    true,
  );
  const adoptRoadmap = [{ id: "1.1", description: "first", adopt_issue: "ENG-1" }];
  const decoded = decodeObjectiveSaveParams({ prose: "p", roadmap: adoptRoadmap });
  assert.deepEqual(decoded?.roadmap, adoptRoadmap);

  const cwd = tempCwd();
  try {
    const branch: unknown[] = [runIdEntry("RID")];
    const ctx = reportableCtx(cwd, branch);
    writeObjectiveDraft(fakeSink(branch), ctx, { prose: PROSE, roadmap: adoptRoadmap });
    const path = join(sessionDataDir(cwd, "RID"), OBJECTIVE_DRAFT_ARTIFACT);
    const parsed = JSON.parse(readFileSync(path, "utf8")) as { roadmap: unknown };
    assert.deepEqual(parsed.roadmap, adoptRoadmap);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});
