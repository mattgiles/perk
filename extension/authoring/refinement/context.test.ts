// The refinement CONTEXT transfer: the strict decode, the digest-validated transfer, the exact
// raw-bytes import (Python-serialized → TS-written identity over the shared golden fixture),
// the strict resume, and the cold-claim import. Pi-free; memory session.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { digestSessionData } from "../../session/workflowSession.ts";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import {
  checkoutObservationLine,
  decodeRefinementContext,
  describeRefinementTarget,
  importColdRefinementContext,
  importRefinementContext,
  REFINEMENT_CONTEXT_ARTIFACT,
  REFINEMENT_HANDOFF_KEY,
  resumeRefinementContext,
  validateContextTransfer,
} from "./context.ts";

const FIXTURES = join(
  fileURLToPath(new URL(".", import.meta.url)),
  "..",
  "..",
  "..",
  "tests",
  "fixtures",
  "objective-refinement",
);
/** The Python-serialized golden bytes (canonical JSON + exactly one LF) and their digest. */
export const GOLDEN_CONTEXT = readFileSync(join(FIXTURES, "context.json"), "utf8");
export const GOLDEN_DIGEST = readFileSync(join(FIXTURES, "context.sha256"), "utf8").trim();
export const GOLDEN_RUN = "01AUTHRUN";

test("golden: the Python-serialized context decodes strictly and its digest is the pinned sha256", () => {
  assert.ok(GOLDEN_CONTEXT.endsWith("}\n"), "exactly one trailing LF");
  assert.equal(digestSessionData(GOLDEN_CONTEXT), GOLDEN_DIGEST);
  const decoded = decodeRefinementContext(GOLDEN_CONTEXT);
  assert.ok(decoded.ok, JSON.stringify(decoded));
  const c = decoded.context;
  assert.equal(c.run_id, GOLDEN_RUN);
  assert.equal(c.target.identity.node_id, "2.3");
  assert.equal(c.target.status, "blocked");
  assert.deepEqual(c.target.source.depends_on, ["1.1", "1.2"]);
  assert.equal(c.target.source.description.includes("🚀"), true, "unicode survives");
  assert.equal(c.expected.comment_id, "cmt-9");
  assert.equal(c.provenance.code_basis.dirty, true);
  assert.equal(c.prior?.markdown.startsWith("## Prior"), true);
  assert.deepEqual(c.warnings, ["node engagement unavailable (simulated) — continuing without it"]);
  assert.equal(
    describeRefinementTarget(c),
    "objective proj-1 node 2.3 (blocked; ENG-23; re-refining a prior refinement)",
  );
  assert.equal(
    checkoutObservationLine(c.provenance),
    "Checkout observation captured at 2026-09-07T12:00:00Z: HEAD " +
      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, dirty true; uncommitted files were not " +
      "snapshotted and later checkout changes are not detected. This is not a freshness guarantee.",
  );
});

test("decode: every structural defect is a classified refusal naming the path", () => {
  const base = JSON.parse(GOLDEN_CONTEXT) as Record<string, unknown>;
  const mutate = (fn: (c: Record<string, unknown>) => void): string => {
    const copy = JSON.parse(JSON.stringify(base)) as Record<string, unknown>;
    fn(copy);
    return `${JSON.stringify(copy)}\n`;
  };
  const cases: [string, string][] = [
    ["not json", "not valid JSON"],
    ["[]\n", "context is not an object"],
    [mutate((c) => delete c.warnings), "context.warnings is missing"],
    [mutate((c) => (c.extra = 1)), "context.extra is unknown"],
    [mutate((c) => (c.schema_version = 2)), "context.schema_version is not 1"],
    [mutate((c) => (c.schema_version = "1")), "context.schema_version is not 1"],
    [mutate((c) => (c.run_id = " ")), "context.run_id is blank"],
    [
      mutate((c) => ((c.target as Record<string, unknown>).source_digest = "SHA")),
      "context.target.source_digest is not a 64-char lowercase hex digest",
    ],
    [
      mutate((c) => ((c.expected as Record<string, unknown>).body_digest = null)),
      "context.expected must carry both comment_id and body_digest, or neither",
    ],
    [
      mutate((c) => ((c.target as Record<string, unknown>).has_plan_metadata = "no")),
      "context.target.has_plan_metadata is not a boolean",
    ],
    [
      mutate(
        (c) =>
          ((
            (c.provenance as Record<string, unknown>).code_basis as Record<string, unknown>
          ).head_sha = "abc"),
      ),
      "context.provenance.code_basis.head_sha is not a 40-char lowercase sha",
    ],
    [
      mutate(
        (c) =>
          (((c.target as Record<string, unknown>).source as Record<string, unknown>).depends_on = [
            1,
          ]),
      ),
      "context.target.source.depends_on[0] is not a string",
    ],
    [
      mutate((c) => ((c.prior as Record<string, unknown>).markdown = "")),
      "context.prior.markdown is blank",
    ],
    [mutate((c) => (c.engagement = 4)), "context.engagement is not a string"],
  ];
  for (const [raw, problem] of cases) {
    const decoded = decodeRefinementContext(raw);
    assert.equal(decoded.ok, false, problem);
    assert.ok(
      !decoded.ok && decoded.problem.includes(problem),
      `${problem} ← ${!decoded.ok && decoded.problem}`,
    );
  }
  // A null prior and an absent expectation are valid shapes.
  const minimal = decodeRefinementContext(
    mutate((c) => {
      c.prior = null;
      c.expected = { comment_id: null, body_digest: null };
    }),
  );
  assert.ok(minimal.ok);
  assert.equal(minimal.context.prior, null);
});

test("validateContextTransfer: digest over the EXACT bytes, run binding, malformed digests", () => {
  const ok = validateContextTransfer(GOLDEN_CONTEXT, {
    runId: GOLDEN_RUN,
    expectedDigest: GOLDEN_DIGEST,
  });
  assert.ok(ok.ok);
  assert.equal(ok.read.raw, GOLDEN_CONTEXT, "the raw string is the caller's, unchanged");
  assert.equal(ok.read.digest, GOLDEN_DIGEST);
  // Any byte change (a dropped LF, a re-encoded space) breaks the declared digest.
  for (const bytes of [
    GOLDEN_CONTEXT.trimEnd(),
    `${GOLDEN_CONTEXT}\n`,
    GOLDEN_CONTEXT.replace('":', '": '),
  ]) {
    const bad = validateContextTransfer(bytes, {
      runId: GOLDEN_RUN,
      expectedDigest: GOLDEN_DIGEST,
    });
    assert.equal(bad.ok, false);
    assert.ok(!bad.ok && bad.problem.includes("do not match their digest"));
  }
  const wrongRun = validateContextTransfer(GOLDEN_CONTEXT, {
    runId: "01OTHER",
    expectedDigest: GOLDEN_DIGEST,
  });
  assert.ok(!wrongRun.ok && wrongRun.problem.includes('belongs to run "01AUTHRUN", not this run'));
  const malformed = validateContextTransfer(GOLDEN_CONTEXT, {
    runId: GOLDEN_RUN,
    expectedDigest: "abc",
  });
  assert.ok(!malformed.ok && malformed.problem.includes("not a sha256: digest"));
  // Without a declared digest the shape + run still gate; the digest is computed.
  const undeclared = validateContextTransfer(GOLDEN_CONTEXT, { runId: GOLDEN_RUN });
  assert.ok(undeclared.ok && undeclared.read.digest === GOLDEN_DIGEST);
});

test("import + resume: the UNCHANGED raw bytes land as the session artifact (byte identity), re-import is unchanged", () => {
  const session = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  const validated = validateContextTransfer(GOLDEN_CONTEXT, {
    runId: GOLDEN_RUN,
    expectedDigest: GOLDEN_DIGEST,
  });
  assert.ok(validated.ok);
  const imported = importRefinementContext(session, validated.read);
  assert.equal(imported.status, "imported");
  assert.ok(imported.status === "imported" && imported.receipt.digest === GOLDEN_DIGEST);
  const stored = session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT, { provenance: "strict" });
  assert.ok(stored.status === "found" && stored.content === GOLDEN_CONTEXT, "byte-identical");
  const again = importRefinementContext(session, validated.read);
  assert.equal(again.status, "unchanged");
  const resumed = resumeRefinementContext(session);
  assert.ok(resumed.kind === "valid");
  assert.equal(resumed.read.raw, GOLDEN_CONTEXT);
  assert.equal(resumed.read.digest, GOLDEN_DIGEST);
  assert.equal(resumed.read.context.target.identity.carrier_id, "issue-23");
});

test("resume: absent / corrupt / dropped / foreign-run / wrong-run artifacts classify, never fall back", () => {
  assert.deepEqual(resumeRefinementContext(openMemoryWorkflowSession({ runId: "01RID" })), {
    kind: "absent",
  });
  const noIdentity = resumeRefinementContext(openMemoryWorkflowSession({ runId: null }));
  assert.ok(noIdentity.kind === "refused" && noIdentity.problem.includes("session identity"));

  const validated = validateContextTransfer(GOLDEN_CONTEXT, { runId: GOLDEN_RUN });
  assert.ok(validated.ok);
  for (const corruption of ["corruptContent", "dropContent"] as const) {
    const session = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
    importRefinementContext(session, validated.read);
    session[corruption](REFINEMENT_CONTEXT_ARTIFACT);
    assert.equal(resumeRefinementContext(session).kind, "refused", corruption);
  }
  const disowned = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  importRefinementContext(disowned, validated.read);
  disowned.disownPointer(REFINEMENT_CONTEXT_ARTIFACT);
  // Strict provenance: a foreign-run (orphan) pointer is REFUSED, never read as absent.
  const orphaned = resumeRefinementContext(disowned);
  assert.ok(orphaned.kind === "refused" && orphaned.problem.includes("orphan"));
  // A context whose run_id is another run is refused on resume even with an intact pointer.
  const wrongRun = openMemoryWorkflowSession({ runId: "01OTHER" });
  wrongRun.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, GOLDEN_CONTEXT, { provenance: "strict" });
  const result = resumeRefinementContext(wrongRun);
  assert.ok(result.kind === "refused" && result.problem.includes("not this run"));
  // A write refusal / orphan write classifies, never a half-imported context.
  const refusing = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  refusing.failNextWrite();
  assert.equal(importRefinementContext(refusing, validated.read).status, "rejected");
  const orphan = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
  orphan.failNextPointerAppend();
  assert.equal(importRefinementContext(orphan, validated.read).status, "unverified");
});

test("cold import: only the actual objective-refine claim imports; every defect refuses fail-closed", () => {
  const handoff = { [REFINEMENT_HANDOFF_KEY]: { context_digest: GOLDEN_DIGEST } };
  const port = (raw: string | null) => ({ readTransfer: () => raw });
  const imported = importColdRefinementContext(
    openMemoryWorkflowSession({ runId: GOLDEN_RUN }),
    { runId: GOLDEN_RUN, stage: "objective-refine", handoff },
    port(GOLDEN_CONTEXT),
  );
  assert.equal(imported.status, "imported");
  assert.ok(imported.status === "imported" && imported.read.raw === GOLDEN_CONTEXT);

  assert.deepEqual(
    importColdRefinementContext(
      openMemoryWorkflowSession({ runId: GOLDEN_RUN }),
      { runId: GOLDEN_RUN, stage: "objective-plan", handoff },
      port(GOLDEN_CONTEXT),
    ),
    { status: "not-applicable" },
  );
  const refusals: [Parameters<typeof importColdRefinementContext>[1], string | null, string][] = [
    [
      { runId: GOLDEN_RUN, stage: "objective-refine", handoff: {} },
      GOLDEN_CONTEXT,
      "carries no objective_refinement block",
    ],
    [
      {
        runId: GOLDEN_RUN,
        stage: "objective-refine",
        handoff: { [REFINEMENT_HANDOFF_KEY]: { context_digest: "nope" } },
      },
      GOLDEN_CONTEXT,
      "not a sha256: digest",
    ],
    [{ runId: GOLDEN_RUN, stage: "objective-refine", handoff }, null, "transfer is missing"],
    [
      { runId: GOLDEN_RUN, stage: "objective-refine", handoff },
      GOLDEN_CONTEXT.trimEnd(),
      "do not match their digest",
    ],
    [
      { runId: "01OTHER", stage: "objective-refine", handoff },
      GOLDEN_CONTEXT,
      "not the session's run",
    ],
  ];
  for (const [claim, raw, problem] of refusals) {
    const session = openMemoryWorkflowSession({ runId: GOLDEN_RUN });
    const result = importColdRefinementContext(session, claim, port(raw));
    assert.equal(result.status, "refused", problem);
    assert.ok(
      result.status === "refused" && result.problem.includes(problem),
      `${problem} ← ${result.status === "refused" && result.problem}`,
    );
    assert.equal(
      session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT).status,
      "absent",
      "nothing persisted",
    );
  }
  const throwing = importColdRefinementContext(
    openMemoryWorkflowSession({ runId: GOLDEN_RUN }),
    { runId: GOLDEN_RUN, stage: "objective-refine", handoff },
    {
      readTransfer() {
        throw new Error("EACCES");
      },
    },
  );
  assert.ok(
    throwing.status === "refused" &&
      throwing.problem.includes("could not read the context transfer"),
  );
});
