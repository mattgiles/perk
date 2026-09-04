// Direct feature tests for the gist draft model + ops — memory session only, no Pi, no disk.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { MemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import {
  decodeGistDraft,
  encodeGistDraft,
  GIST_DRAFT_ARTIFACT,
  renderGistDraft,
  resumeGistDraft,
  reviseGistDraft,
} from "./draft.ts";

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

function memorySession(runId: string | null = "RID"): MemoryWorkflowSession {
  return openMemoryWorkflowSession({ runId });
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

test("decodeGistDraft: round-trips an encode; refuses malformed payloads with exact problems", () => {
  assert.deepEqual(
    decodeGistDraft(encodeGistDraft({ prose: PROSE, title: "Faster reviews", scope: "objective" })),
    { ok: true, draft: { title: "Faster reviews", scope: "objective", prose: PROSE } },
  );
  for (const [content, problem] of [
    ["{ not json", "gist-draft.json is not valid JSON — refusing the draft"],
    ['["an", "array"]\n', "gist-draft.json is not a JSON object — refusing the draft"],
    [
      JSON.stringify({ schema_version: 2, prose: PROSE }),
      "gist-draft.json has an unsupported schema_version (2) — refusing the draft",
    ],
    [
      JSON.stringify({ schema_version: 1, prose: "  \n" }),
      "gist-draft.json has no prose — refusing the draft",
    ],
    [JSON.stringify({ schema_version: 1 }), "gist-draft.json has no prose — refusing the draft"],
  ] as const) {
    assert.deepEqual(decodeGistDraft(content), { ok: false, problem });
  }
});

test("decodeGistDraft: blank title dropped; an unknown scope degrades to absent", () => {
  assert.deepEqual(
    decodeGistDraft(
      JSON.stringify({ schema_version: 1, title: "   ", scope: "banana", prose: PROSE }),
    ),
    { ok: true, draft: { prose: PROSE } },
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
  const blankFirst = reviseGistDraft({ prose: "  \n" }, memorySession(null));
  assert.equal(blankFirst.status, "rejected");
  assert.ok(blankFirst.status === "rejected");
  assert.equal(blankFirst.reason, "blank_prose");
  assert.equal(blankFirst.problem, "no gist prose to write (pass the full working draft)");

  const noIdentity = reviseGistDraft({ prose: PROSE }, memorySession(null));
  assert.equal(noIdentity.status, "rejected");
  assert.ok(noIdentity.status === "rejected");
  assert.equal(noIdentity.reason, "no_identity");
  assert.equal(noIdentity.problem, "session has no run_id — cannot write the gist-draft artifact");
});

test("revise: happy path writes the artifact, receipt digests the encoded bytes", () => {
  const session = memorySession();
  const result = reviseGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" }, session);
  assert.equal(result.status, "revised");
  assert.ok(result.status === "revised");
  const content = encodeGistDraft({ prose: PROSE, title: "Faster reviews", scope: "plan" });
  assert.equal(result.bytes, Buffer.byteLength(content, "utf8"));
  assert.equal(result.receipt.path, GIST_DRAFT_ARTIFACT);
  assert.match(result.receipt.digest, /^sha256:[0-9a-f]{64}$/);
  const read = session.readArtifact(GIST_DRAFT_ARTIFACT);
  assert.equal(read.status === "found" && read.content, content);
});

test("revise: a whole-value rewrite replaces everything; identical bytes short-circuit", () => {
  const session = memorySession();
  assert.equal(reviseGistDraft({ prose: PROSE, title: "T" }, session).status, "revised");
  const rewrite = reviseGistDraft({ prose: "# v2\n", scope: "objective" }, session);
  assert.equal(rewrite.status, "revised");
  assert.deepEqual(resumeGistDraft(session), {
    kind: "valid",
    draft: { scope: "objective", prose: "# v2\n" },
  });

  const identical = reviseGistDraft({ prose: "# v2\n", scope: "objective" }, session);
  assert.equal(identical.status, "unchanged");
  assert.ok(identical.status === "unchanged");
  assert.ok(rewrite.status === "revised");
  assert.deepEqual(identical.receipt, rewrite.receipt, "the re-derived receipt is identical");
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
  const unverified = quietly(() => reviseGistDraft({ prose: PROSE }, orphaned));
  assert.equal(unverified.status, "unverified");
  assert.ok(unverified.status === "unverified");
  assert.equal(
    unverified.problem,
    `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
  );
});

// --- resumeGistDraft -------------------------------------------------------------------------------

test("resume: absent → absent (silent); invalid seam read and refused payload → refused", () => {
  const empty = memorySession();
  assert.deepEqual(resumeGistDraft(empty), { kind: "absent" }, "no draft");

  const corrupted = memorySession();
  assert.equal(reviseGistDraft({ prose: PROSE }, corrupted).status, "revised");
  corrupted.corruptContent(GIST_DRAFT_ARTIFACT);
  // The seam's own stderr tier still speaks (untouched); the classified arm carries its problem.
  assert.deepEqual(
    quietly(() => resumeGistDraft(corrupted)),
    {
      kind: "refused",
      problem: `session artifact ${GIST_DRAFT_ARTIFACT} digest mismatch (rewound or modified)`,
    },
    "an invalid (rewound) artifact refuses with the seam's problem",
  );

  const malformed = memorySession();
  assert.equal(malformed.writeArtifact(GIST_DRAFT_ARTIFACT, "{ not json").status, "applied");
  assert.deepEqual(
    resumeGistDraft(malformed),
    { kind: "refused", problem: "gist-draft.json is not valid JSON — refusing the draft" },
    "a malformed payload refuses through the decode taxonomy",
  );
});

test("resume: round-trips a revise", () => {
  const session = memorySession();
  reviseGistDraft({ prose: PROSE, title: "Faster reviews", scope: "objective" }, session);
  assert.deepEqual(resumeGistDraft(session), {
    kind: "valid",
    draft: {
      title: "Faster reviews",
      scope: "objective",
      prose: PROSE,
    },
  });
});
