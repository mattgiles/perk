// The refinement working DRAFT: TS-owned serialization (fixed order, compact, one LF — proven
// byte-equal to the shared golden the Python reader consumes), strict decode, the context-bound
// revise/resume pair (mismatch is rewrite evidence, never a rebind), and the review rendering.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { GOLDEN_CONTEXT, GOLDEN_DIGEST, GOLDEN_RUN } from "./context.test.ts";
import {
  importRefinementContext,
  REFINEMENT_CONTEXT_ARTIFACT,
  validateContextTransfer,
} from "./context.ts";
import {
  decodeRefinementDraft,
  encodeRefinementDraft,
  REFINEMENT_DRAFT_ARTIFACT,
  renderRefinementDraft,
  resumeRefinementDraft,
  reviseRefinementDraft,
} from "./draft.ts";

const GOLDEN_DRAFT = readFileSync(
  join(
    fileURLToPath(new URL(".", import.meta.url)),
    "..",
    "..",
    "..",
    "tests",
    "fixtures",
    "objective-refinement",
    "draft.json",
  ),
  "utf8",
);
const MARKDOWN =
  '## Refinement\n\nÜnïcode ✓ — tabs\tand "quotes" and \\backslashes\\.\n\n- trailing spaces   \n- final line without LF';

/** A session with the golden context imported (the grounding pass already happened). */
function groundedSession() {
  const session = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  const validated = validateContextTransfer(GOLDEN_CONTEXT, { runId: GOLDEN_RUN });
  assert.ok(validated.ok);
  assert.equal(importRefinementContext(session, validated.read).status, "imported");
  return session;
}

test("golden: encodeRefinementDraft is byte-equal to the shared draft fixture Python parses", () => {
  const encoded = encodeRefinementDraft({
    runId: GOLDEN_RUN,
    contextDigest: GOLDEN_DIGEST,
    markdown: MARKDOWN,
  });
  assert.equal(encoded, GOLDEN_DRAFT, "fixed key order, compact separators, exactly one LF");
  assert.ok(encoded.endsWith("}\n") && !encoded.endsWith("}\n\n"));
  const decoded = decodeRefinementDraft(GOLDEN_DRAFT);
  assert.ok(decoded.ok);
  assert.equal(decoded.draft.markdown, MARKDOWN, "the Markdown tail (no final LF) is preserved");
  assert.equal(decoded.draft.context_digest, GOLDEN_DIGEST);
});

test("decodeRefinementDraft: strict shape — exactly four keys, version 1, sha256 digest, nonblank markdown", () => {
  const bad = (raw: string, problem: string) => {
    const decoded = decodeRefinementDraft(raw);
    assert.equal(decoded.ok, false, problem);
    assert.ok(
      !decoded.ok && decoded.problem.includes(problem),
      `${problem} ← ${!decoded.ok && decoded.problem}`,
    );
  };
  bad("{", "not valid JSON");
  bad("[]", "not a JSON object");
  bad(JSON.stringify({ schema_version: 1, run_id: "r", context_digest: GOLDEN_DIGEST }), "exactly");
  bad(
    JSON.stringify({
      schema_version: 1,
      run_id: "r",
      context_digest: GOLDEN_DIGEST,
      markdown: "x",
      extra: 1,
    }),
    "exactly",
  );
  bad(
    JSON.stringify({
      schema_version: 2,
      run_id: "r",
      context_digest: GOLDEN_DIGEST,
      markdown: "x",
    }),
    "schema_version",
  );
  bad(
    JSON.stringify({
      schema_version: 1,
      run_id: " ",
      context_digest: GOLDEN_DIGEST,
      markdown: "x",
    }),
    "blank run_id",
  );
  bad(
    JSON.stringify({ schema_version: 1, run_id: "r", context_digest: "abc", markdown: "x" }),
    "malformed context_digest",
  );
  bad(
    JSON.stringify({
      schema_version: 1,
      run_id: "r",
      context_digest: GOLDEN_DIGEST,
      markdown: " \n",
    }),
    "blank markdown",
  );
});

test("revise: writes the small context-bound envelope; identical bytes are unchanged; refusals classify", () => {
  const session = groundedSession();
  const revised = reviseRefinementDraft({ markdown: MARKDOWN }, session);
  assert.equal(revised.status, "revised");
  assert.ok(revised.status === "revised" && revised.context.digest === GOLDEN_DIGEST);
  const stored = session.readArtifact(REFINEMENT_DRAFT_ARTIFACT);
  assert.ok(
    stored.status === "found" && stored.content === GOLDEN_DRAFT,
    "the TS-serialized golden bytes",
  );
  assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, session).status, "unchanged");
  assert.equal(
    reviseRefinementDraft({ markdown: `${MARKDOWN}\n` }, session).status,
    "revised",
    "a tail LF is a change",
  );

  const blank = reviseRefinementDraft({ markdown: "  \n" }, session);
  assert.ok(blank.status === "rejected" && blank.reason === "blank_markdown");
  const noIdentity = reviseRefinementDraft(
    { markdown: MARKDOWN },
    openMemoryWorkflowSession({ runId: null }),
  );
  assert.ok(noIdentity.status === "rejected" && noIdentity.reason === "no_identity");
  const noContext = reviseRefinementDraft(
    { markdown: MARKDOWN },
    openMemoryWorkflowSession({ runId: GOLDEN_RUN }),
  );
  assert.ok(noContext.status === "rejected" && noContext.reason === "no_context");
  const corrupt = groundedSession();
  corrupt.corruptContent(REFINEMENT_CONTEXT_ARTIFACT);
  const refused = reviseRefinementDraft({ markdown: MARKDOWN }, corrupt);
  assert.ok(refused.status === "rejected" && refused.reason === "context_refused");
  const failing = groundedSession();
  failing.failNextWrite();
  assert.ok(reviseRefinementDraft({ markdown: MARKDOWN }, failing).status === "rejected");
  const orphan = groundedSession();
  orphan.failNextPointerAppend();
  assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, orphan).status, "unverified");
});

test("resume: valid pair, absent, no-context, mismatch (re-prepared context) and refused arms", () => {
  const session = groundedSession();
  assert.deepEqual(resumeRefinementDraft(session), { kind: "absent" });
  reviseRefinementDraft({ markdown: MARKDOWN }, session);
  const valid = resumeRefinementDraft(session);
  assert.ok(valid.kind === "valid");
  assert.equal(valid.pair.draftRaw, GOLDEN_DRAFT);
  assert.equal(valid.pair.context.digest, GOLDEN_DIGEST);

  // The context is re-prepared (any byte change) → the existing draft is a MISMATCH: evidence
  // that names the rewrite, never a silent rebind or a plan fallback.
  const replaced = session.writeArtifact(
    REFINEMENT_CONTEXT_ARTIFACT,
    GOLDEN_CONTEXT.replace('"warnings":[', '"warnings":["w",'),
  );
  assert.equal(replaced.status, "applied");
  const mismatch = resumeRefinementDraft(session);
  assert.ok(mismatch.kind === "mismatch" && mismatch.problem.includes("re-prepared"));
  // Rewriting binds to the current context again.
  assert.equal(reviseRefinementDraft({ markdown: MARKDOWN }, session).status, "revised");
  assert.equal(resumeRefinementDraft(session).kind, "valid");

  // A draft without its context: `no-context` (a grounding pass is needed).
  const bare = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  bare.writeArtifact(REFINEMENT_DRAFT_ARTIFACT, GOLDEN_DRAFT);
  assert.deepEqual(resumeRefinementDraft(bare), { kind: "no-context" });
  // Corruption of either artifact refuses.
  const corruptDraft = groundedSession();
  reviseRefinementDraft({ markdown: MARKDOWN }, corruptDraft);
  corruptDraft.corruptContent(REFINEMENT_DRAFT_ARTIFACT);
  assert.equal(resumeRefinementDraft(corruptDraft).kind, "refused");
  const corruptContext = groundedSession();
  reviseRefinementDraft({ markdown: MARKDOWN }, corruptContext);
  corruptContext.dropContent(REFINEMENT_CONTEXT_ARTIFACT);
  assert.equal(resumeRefinementDraft(corruptContext).kind, "refused");
  // A draft belonging to another run under this run's pointer is refused.
  const foreign = groundedSession();
  foreign.writeArtifact(REFINEMENT_DRAFT_ARTIFACT, GOLDEN_DRAFT.replace(GOLDEN_RUN, "01OTHER"));
  const foreignResult = resumeRefinementDraft(foreign);
  assert.ok(foreignResult.kind === "refused" && foreignResult.problem.includes("another run"));
  assert.equal(resumeRefinementDraft(openMemoryWorkflowSession({ runId: null })).kind, "refused");
});

test("render: identity + carrier + pass time, the advisory notice, the capture-time observation label, then the full Markdown", () => {
  const session = groundedSession();
  reviseRefinementDraft({ markdown: MARKDOWN }, session);
  const resumed = resumeRefinementDraft(session);
  assert.ok(resumed.kind === "valid");
  const rendered = renderRefinementDraft(resumed.pair);
  assert.ok(rendered.startsWith("# Refinement — objective proj-1 · node 2.3\n"));
  assert.ok(rendered.includes("Node 2.3 (blocked): Ünïcode déscription"));
  assert.ok(rendered.includes("Carrier: ENG-23 — https://linear.app/x/issue/ENG-23"));
  assert.ok(rendered.includes("Authoring pass started: 2026-09-07T12:00:00Z (run 01AUTHRUN)"));
  assert.ok(rendered.includes("Replaces the prior refinement saved at 2026-08-01T10:00:00Z"));
  assert.ok(
    rendered.includes(
      "> ADVISORY: this is a dated refinement of a FUTURE node, not an executable plan.",
    ),
  );
  assert.ok(
    rendered.includes(
      "> Checkout observation captured at 2026-09-07T12:00:00Z: HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, dirty true; uncommitted files were not snapshotted and later checkout changes are not detected. This is not a freshness guarantee.",
    ),
  );
  for (const banned of ["verified code", "frozen", "current code"]) {
    assert.equal(rendered.includes(banned), false, banned);
  }
  assert.ok(rendered.endsWith(`\n---\n\n${MARKDOWN}`), "the full Markdown verbatim below the rule");
});
