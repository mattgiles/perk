// Direct feature tests for the gist draft model + ops — memory session only, no Pi, no disk.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { MemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import {
  decodeGistDraft,
  encodeGistDraft,
  GIST_DRAFT_ARTIFACT,
  renderGistDraft,
  resumeGistDraft,
  reviseGistDraft,
} from "./draft.ts";

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

function memorySession(runId = "RID"): MemoryWorkflowSession {
  const opened = openMemoryWorkflowSession({ runId });
  assert.equal(opened.status, "opened");
  if (opened.status !== "opened") throw new Error("unreachable");
  return opened.session;
}

/** Capture console.error calls for the duration of `fn` (silences the loud refusal warnings). */
function quietly<T>(fn: () => T): T {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

// --- encode / decode / render --------------------------------------------------------------------

test("encodeGistDraft: deterministic key order; blank title/scope omitted", () => {
  assert.deepEqual(JSON.parse(encodeGistDraft({ prose: PROSE })), {
    schema_version: 1,
    prose: PROSE,
  });
  const full = encodeGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" });
  assert.equal(
    full,
    `${JSON.stringify({ schema_version: 1, title: "Faster reviews", scope: "plan", prose: PROSE }, null, 2)}\n`,
  );
  assert.deepEqual(JSON.parse(encodeGistDraft({ prose: PROSE, title: "   " })), {
    schema_version: 1,
    prose: PROSE,
  });
});

test("decodeGistDraft: round-trips an encode; refuses malformed payloads with warnings", () => {
  assert.deepEqual(
    decodeGistDraft(encodeGistDraft({ prose: PROSE, title: "Faster reviews", scope: "objective" })),
    { title: "Faster reviews", scope: "objective", prose: PROSE },
  );
  for (const [label, content] of [
    ["malformed JSON", "{ not json"],
    ["non-object payload", '["an", "array"]\n'],
    ["wrong schema_version", JSON.stringify({ schema_version: 2, prose: PROSE })],
    ["blank prose", JSON.stringify({ schema_version: 1, prose: "  \n" })],
    ["missing prose", JSON.stringify({ schema_version: 1 })],
  ] as const) {
    assert.equal(
      quietly(() => decodeGistDraft(content)),
      null,
      label,
    );
  }
});

test("decodeGistDraft: blank title dropped; an unknown scope degrades to absent", () => {
  assert.deepEqual(
    decodeGistDraft(
      JSON.stringify({ schema_version: 1, title: "   ", scope: "banana", prose: PROSE }),
    ),
    { prose: PROSE },
  );
});

test("renderGistDraft: title heading + Scope line + prose; both optional", () => {
  assert.equal(
    renderGistDraft({ title: "Faster reviews", scope: "plan", prose: "The intent.\n" }),
    "# Faster reviews\n\nScope: plan\n\nThe intent.\n",
  );
  assert.equal(renderGistDraft({ prose: "Just prose.\n" }), "Just prose.\n");
  assert.equal(renderGistDraft({ scope: "objective", prose: "P\n" }), "Scope: objective\n\nP\n");
});

// --- reviseGistDraft -------------------------------------------------------------------------------

test("revise: diagnostic precedence — blank prose rejects BEFORE missing identity", () => {
  const blankFirst = reviseGistDraft({ prose: "  \n" }, null);
  assert.equal(blankFirst.status, "rejected");
  assert.ok(blankFirst.status === "rejected");
  assert.equal(blankFirst.reason, "blank_prose");
  assert.equal(blankFirst.problem, "no gist prose to write (pass the full working draft)");

  const noIdentity = reviseGistDraft({ prose: PROSE }, null);
  assert.equal(noIdentity.status, "rejected");
  assert.ok(noIdentity.status === "rejected");
  assert.equal(noIdentity.reason, "no_identity");
  assert.equal(noIdentity.problem, "session has no run_id — cannot write the gist-draft artifact");
});

test("revise: happy path writes the artifact, pointer digests the encoded bytes", () => {
  const session = memorySession();
  const result = reviseGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" }, session);
  assert.equal(result.status, "revised");
  assert.ok(result.status === "revised");
  const content = encodeGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" });
  assert.equal(result.bytes, Buffer.byteLength(content, "utf8"));
  assert.equal(result.pointer.name, GIST_DRAFT_ARTIFACT);
  const read = session.readArtifact(GIST_DRAFT_ARTIFACT);
  assert.equal(read.status === "found" && read.content, content);
});

test("revise: a whole-value rewrite replaces everything; identical bytes short-circuit", () => {
  const session = memorySession();
  assert.equal(reviseGistDraft({ prose: PROSE, title: "T" }, session).status, "revised");
  const rewrite = reviseGistDraft({ prose: "# v2\n", scope: "objective" }, session);
  assert.equal(rewrite.status, "revised");
  assert.deepEqual(resumeGistDraft(session), { scope: "objective", prose: "# v2\n" });

  const identical = reviseGistDraft({ prose: "# v2\n", scope: "objective" }, session);
  assert.equal(identical.status, "unchanged");
  assert.ok(identical.status === "unchanged");
  assert.ok(rewrite.status === "revised");
  assert.deepEqual(identical.pointer, rewrite.pointer, "the recorded pointer is returned as-is");
  assert.equal(identical.bytes, rewrite.bytes);
});

test("revise: seam refusal → rejected/write_refused; pointer failure → unverified", () => {
  const refused = memorySession();
  refused.failNextWrite();
  const rejected = reviseGistDraft({ prose: PROSE }, refused);
  assert.equal(rejected.status, "rejected");
  assert.ok(rejected.status === "rejected");
  assert.equal(rejected.reason, "write_refused");
  assert.equal(
    rejected.problem,
    `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
  );

  const orphaned = memorySession();
  orphaned.failNextPointerAppend();
  const unverified = reviseGistDraft({ prose: PROSE }, orphaned);
  assert.equal(unverified.status, "unverified");
  assert.ok(unverified.status === "unverified");
  assert.equal(
    unverified.problem,
    `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
  );
});

// --- resumeGistDraft -------------------------------------------------------------------------------

test("resume: absent → null (silent); invalid seam read → null; refused payload → null", () => {
  const empty = memorySession();
  assert.equal(resumeGistDraft(empty), null, "no draft");

  const corrupted = memorySession();
  assert.equal(reviseGistDraft({ prose: PROSE }, corrupted).status, "revised");
  corrupted.corruptContent(GIST_DRAFT_ARTIFACT);
  assert.equal(
    quietly(() => resumeGistDraft(corrupted)),
    null,
    "an invalid (rewound) artifact refuses",
  );

  const malformed = memorySession();
  assert.equal(malformed.writeArtifact(GIST_DRAFT_ARTIFACT, "{ not json").status, "applied");
  assert.equal(
    quietly(() => resumeGistDraft(malformed)),
    null,
    "a malformed payload refuses through the decode taxonomy",
  );
});

test("resume: round-trips a revise", () => {
  const session = memorySession();
  reviseGistDraft({ prose: PROSE, title: "Faster reviews", scope: "objective" }, session);
  assert.deepEqual(resumeGistDraft(session), {
    title: "Faster reviews",
    scope: "objective",
    prose: PROSE,
  });
});
