// The objective working-draft feature ops over the MEMORY session (no Pi construction): the
// revise taxonomy + diagnostic precedence, the byte-identical-rewrite short-circuit, the
// payload key-order/omission rules, the resume refusal matrix, and the renderer cases. The
// §8.63 gate arrives scripted here (the routing proof); the REAL resolver matrix stays in
// `dreamReportGate.test.ts` and the live tool boundary in `pi/v1/objectiveAuthoring.test.ts`.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import {
  OBJECTIVE_DRAFT_ARTIFACT,
  type ObjectiveDraft,
  renderObjectiveDraft,
  resumeObjectiveDraft,
  reviseObjectiveDraft,
} from "./draft.ts";
import type { DreamReportGateOutcome, ObjectiveDreamReportBlock } from "./dreamReportGate.ts";

const PROSE = "# Conform objective planning\n\nThe why, the design, the boundaries.\n";
const ROADMAP = [
  { id: "1.1", description: "first" },
  { id: "2.1", description: "second", weird_extra: { nested: true } }, // unknown-shaped: kept verbatim
];

const DREAM_BLOCK: ObjectiveDreamReportBlock = {
  input: { rows: [] },
  generated_at: "2026-01-01T00:00:00Z",
  parts: ["# Dream report — RID\n\nbody\n"],
};

/** A scripted §8.63 gate that records its calls (absent unless overridden). */
function scriptedGate(outcome: DreamReportGateOutcome = { kind: "absent" }): {
  resolveDreamGate: (input: unknown, generatedAt: string) => DreamReportGateOutcome;
  calls: { input: unknown; generatedAt: string }[];
} {
  const calls: { input: unknown; generatedAt: string }[] = [];
  return {
    resolveDreamGate: (input, generatedAt) => {
      calls.push({ input, generatedAt });
      return outcome;
    },
    calls,
  };
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

/** The stored artifact bytes (via the session read — the memory backing's observation). */
function storedContent(session: ReturnType<typeof openMemoryWorkflowSession>): string | null {
  const read = session.readArtifact(OBJECTIVE_DRAFT_ARTIFACT);
  return read.status === "found" ? read.content : null;
}

// --- reviseObjectiveDraft: taxonomy + precedence -------------------------------------------------

test("revise: blank prose ⇒ rejected/blank_prose BEFORE identity and the gate", () => {
  const session = openMemoryWorkflowSession({ runId: null });
  const gate = scriptedGate();
  for (const prose of ["", "   \n\t "]) {
    const result = reviseObjectiveDraft(
      { prose },
      { session, resolveDreamGate: gate.resolveDreamGate },
    );
    assert.deepEqual(result, {
      status: "rejected",
      reason: "blank_prose",
      problem: "no objective prose to write (pass the full working draft)",
      errorType: "invalid_input",
    });
  }
  assert.equal(gate.calls.length, 0, "the gate is never consulted for blank prose");
});

test("revise: no identity ⇒ rejected/no_identity BEFORE the gate; nothing stored", () => {
  const session = openMemoryWorkflowSession({ runId: null });
  const gate = scriptedGate();
  const result = reviseObjectiveDraft(
    { prose: PROSE },
    { session, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.deepEqual(result, {
    status: "rejected",
    reason: "no_identity",
    problem: "session has no run_id — cannot write the objective-draft artifact",
    errorType: "no_run_id",
  });
  assert.equal(gate.calls.length, 0);
  assert.equal(storedContent(session), null);
});

test("revise: a gate refusal ⇒ rejected/gate_refused carrying the resolver's detail/errorType", () => {
  for (const [errorType, detail] of [
    ["invalid_input", "dream_report is only valid inside a perk learn dream session"],
    ["bad_state", "the dream wave state is broken — re-run the dream wave"],
  ] as const) {
    const session = openMemoryWorkflowSession({ runId: "RID" });
    const gate = scriptedGate({ kind: "refuse", errorType, detail });
    const result = reviseObjectiveDraft(
      { prose: PROSE, dream_report: { rows: [] } },
      { session, resolveDreamGate: gate.resolveDreamGate },
    );
    assert.deepEqual(result, {
      status: "rejected",
      reason: "gate_refused",
      problem: detail,
      errorType,
    });
    assert.equal(storedContent(session), null, "a refusal writes nothing");
    // The gate receives the raw input + a fresh ISO stamp.
    assert.deepEqual(gate.calls[0]?.input, { rows: [] });
    assert.ok(Number.isFinite(Date.parse(gate.calls[0]?.generatedAt ?? "")));
  }
});

test("revise: write refusal ⇒ rejected/write_refused; pointer failure ⇒ unverified", () => {
  const problem = `could not write the ${OBJECTIVE_DRAFT_ARTIFACT} artifact (see warnings)`;
  const refused = openMemoryWorkflowSession({ runId: "RID" });
  refused.failNextWrite();
  assert.deepEqual(
    quietly(() =>
      reviseObjectiveDraft(
        { prose: PROSE },
        { session: refused, resolveDreamGate: scriptedGate().resolveDreamGate },
      ),
    ),
    { status: "rejected", reason: "write_refused", problem, errorType: "write_failed" },
  );

  const orphaned = openMemoryWorkflowSession({ runId: "RID" });
  orphaned.failNextPointerAppend();
  assert.deepEqual(
    quietly(() =>
      reviseObjectiveDraft(
        { prose: PROSE },
        { session: orphaned, resolveDreamGate: scriptedGate().resolveDreamGate },
      ),
    ),
    { status: "unverified", problem },
  );
});

test("revise: happy path ⇒ revised with pointer + bytes + roadmapNodes; re-write is unchanged", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const gate = scriptedGate();
  const input = { prose: PROSE, title: "Objective title", roadmap: ROADMAP };
  const first = reviseObjectiveDraft(input, {
    session,
    resolveDreamGate: gate.resolveDreamGate,
  });
  assert.equal(first.status, "revised");
  if (first.status !== "revised") return;
  assert.equal(first.roadmapNodes, 2);
  assert.equal(first.pointer.name, OBJECTIVE_DRAFT_ARTIFACT);
  assert.equal(first.pointer.run_id, "RID");
  const content = storedContent(session);
  assert.ok(content !== null);
  assert.equal(first.bytes, Buffer.byteLength(content, "utf8"));

  // Byte-identical rewrite short-circuits via the seam's classified cores.
  const again = reviseObjectiveDraft(input, {
    session,
    resolveDreamGate: gate.resolveDreamGate,
  });
  assert.equal(again.status, "unchanged");
  if (again.status !== "unchanged") return;
  assert.equal(again.roadmapNodes, 2);
  assert.deepEqual(again.pointer.digest, first.pointer.digest);
});

// --- payload key order + omission rules ----------------------------------------------------------

test("revise: payload bytes are the explicit literal — key order + blank/absent omission", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const gate = scriptedGate();
  reviseObjectiveDraft(
    { prose: PROSE, title: "Objective title", roadmap: ROADMAP },
    { session, resolveDreamGate: gate.resolveDreamGate },
  );
  // Byte-identical to the pre-migration literal — the absent dream arm changes NOTHING.
  assert.equal(
    storedContent(session),
    `${JSON.stringify(
      { schema_version: 1, title: "Objective title", prose: PROSE, roadmap: ROADMAP },
      null,
      2,
    )}\n`,
  );

  // Blank title/base omit; absent roadmap serializes as []; delivery rides when present.
  const bare = openMemoryWorkflowSession({ runId: "RID" });
  reviseObjectiveDraft(
    { prose: PROSE, title: "  ", base: "" },
    { session: bare, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.equal(
    storedContent(bare),
    `${JSON.stringify({ schema_version: 1, prose: PROSE, roadmap: [] }, null, 2)}\n`,
  );

  const chosen = openMemoryWorkflowSession({ runId: "RID" });
  reviseObjectiveDraft(
    { prose: PROSE, base: "develop", delivery: "stacked" },
    { session: chosen, resolveDreamGate: gate.resolveDreamGate },
  );
  const parsed = JSON.parse(storedContent(chosen) ?? "{}") as Record<string, unknown>;
  assert.deepEqual(Object.keys(parsed), ["schema_version", "base", "delivery", "prose", "roadmap"]);
  assert.equal(parsed.base, "develop");
  assert.equal(parsed.delivery, "stacked");
});

test("revise: a gate block stores the tool-written dream_report before prose; resume round-trips", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const gate = scriptedGate({ kind: "block", block: DREAM_BLOCK });
  const result = reviseObjectiveDraft(
    { prose: PROSE, dream_report: DREAM_BLOCK.input },
    { session, resolveDreamGate: gate.resolveDreamGate },
  );
  assert.equal(result.status, "revised");
  const parsed = JSON.parse(storedContent(session) ?? "{}") as Record<string, unknown>;
  assert.deepEqual(Object.keys(parsed), ["schema_version", "dream_report", "prose", "roadmap"]);
  assert.deepEqual(parsed.dream_report, DREAM_BLOCK);
  assert.deepEqual(resumeObjectiveDraft(session)?.dream_report, DREAM_BLOCK);
});

// --- resumeObjectiveDraft: the refusal matrix ----------------------------------------------------

/** Plant raw artifact bytes through the seam (valid pointer, arbitrary payload). */
function plantedSession(content: string): ReturnType<typeof openMemoryWorkflowSession> {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(session.writeArtifact(OBJECTIVE_DRAFT_ARTIFACT, content).status, "applied");
  return session;
}

test("resume: no draft ⇒ null (silent); identity-less session reads absent ⇒ null", () => {
  assert.equal(resumeObjectiveDraft(openMemoryWorkflowSession({ runId: "RID" })), null);
  assert.equal(resumeObjectiveDraft(openMemoryWorkflowSession({ runId: null })), null);
});

test("resume: happy path round-trips a revise", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  reviseObjectiveDraft(
    { prose: PROSE, title: "Objective title", roadmap: ROADMAP },
    { session, resolveDreamGate: scriptedGate().resolveDreamGate },
  );
  assert.deepEqual(resumeObjectiveDraft(session), {
    title: "Objective title",
    prose: PROSE,
    roadmap: ROADMAP,
  });
});

/** Capture console.error lines for the duration of `fn` (the reader's diagnostic contract). */
function capturingStderr<T>(fn: () => T): { value: T; lines: string[] } {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    return { value: fn(), lines };
  } finally {
    console.error = original;
  }
}

test("resume: malformed payloads null with the exact byte-stable warning line", () => {
  // The diagnostic contract is part of the reader's behavior: each failure names the artifact,
  // the reason, and the refusal — deleting or misrouting a warning must fail this pin, not
  // just the null return.
  for (const [content, expected] of [
    ["{ not json", "perk: warning: objective-draft.json is not valid JSON — refusing the draft"],
    [
      '["an", "array"]\n',
      "perk: warning: objective-draft.json is not a JSON object — refusing the draft",
    ],
    [
      JSON.stringify({ schema_version: 2, prose: PROSE, roadmap: [] }),
      "perk: warning: objective-draft.json has an unsupported schema_version (2) — refusing the draft",
    ],
    [
      JSON.stringify({ schema_version: "one", prose: PROSE, roadmap: [] }),
      'perk: warning: objective-draft.json has an unsupported schema_version ("one") — refusing the draft',
    ],
    [
      JSON.stringify({ schema_version: 1, prose: "  \n", roadmap: [] }),
      "perk: warning: objective-draft.json has no prose — refusing the draft",
    ],
    [
      JSON.stringify({ schema_version: 1, roadmap: [] }),
      "perk: warning: objective-draft.json has no prose — refusing the draft",
    ],
  ] as const) {
    const { value, lines } = capturingStderr(() => resumeObjectiveDraft(plantedSession(content)));
    assert.equal(value, null, expected);
    assert.deepEqual(lines, [expected]);
  }
});

test("resume: a malformed dream_report block refuses the WHOLE draft (exact warning + null)", () => {
  for (const dreamReport of [
    "nope",
    { input: "not-an-object", generated_at: "2026-01-01T00:00:00Z", parts: ["p"] },
    { input: {}, generated_at: "", parts: ["p"] },
    { input: {}, generated_at: "2026-01-01T00:00:00Z", parts: [] },
    { input: {}, generated_at: "2026-01-01T00:00:00Z", parts: ["p", 7] },
  ]) {
    const session = plantedSession(
      JSON.stringify({ schema_version: 1, dream_report: dreamReport, prose: PROSE, roadmap: [] }),
    );
    const { value, lines } = capturingStderr(() => resumeObjectiveDraft(session));
    assert.equal(value, null, JSON.stringify(dreamReport));
    assert.deepEqual(
      lines,
      [
        "perk: warning: objective-draft.json carries a malformed dream_report block — refusing the draft",
      ],
      JSON.stringify(dreamReport),
    );
  }
});

test("resume: junk base/delivery drop to absent; blank title dropped; roadmap defaults to []", () => {
  const session = plantedSession(
    JSON.stringify({
      schema_version: 1,
      title: "   ",
      base: "  ",
      delivery: "atomic",
      prose: PROSE,
      roadmap: "nope",
    }),
  );
  assert.deepEqual(resumeObjectiveDraft(session), { prose: PROSE, roadmap: [] });
});

test("resume: valid base/delivery survive the validated read", () => {
  const session = plantedSession(
    JSON.stringify({
      schema_version: 1,
      base: "develop",
      delivery: "stacked",
      prose: PROSE,
      roadmap: [],
    }),
  );
  assert.deepEqual(resumeObjectiveDraft(session), {
    base: "develop",
    delivery: "stacked",
    prose: PROSE,
    roadmap: [],
  });
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
    /\*\*Delivery: STACKED\*\* — all non-skipped roadmap nodes land as ONE atomic pull-request train \(capability-checked at save\)/,
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

test("renderObjectiveDraft: the dream parts append as the final section (byte-stable joining)", () => {
  const block: ObjectiveDreamReportBlock = {
    input: {},
    generated_at: "2026-01-01T00:00:00Z",
    parts: [
      "# Dream report — R\n\nbody one\n",
      "# Dream report — R (continued, part 2 of 2)\n\nbody two\n",
    ],
  };
  // After the roadmap table.
  const withRoadmap = renderObjectiveDraft({
    prose: "P",
    roadmap: [{ id: "1.1", description: "first" }],
    dream_report: block,
  });
  const base = renderObjectiveDraft({ prose: "P", roadmap: [{ id: "1.1", description: "first" }] });
  assert.equal(withRoadmap, `${base.trimEnd()}\n\n${block.parts.join("\n\n")}\n`);
  assert.match(withRoadmap, /\| 1\.1 \| first \| - \| pending \|\n\n# Dream report — R\n/);
  // After the prose when the roadmap is empty.
  const noRoadmap = renderObjectiveDraft({
    prose: "Just prose.\n",
    roadmap: [],
    dream_report: block,
  });
  assert.equal(
    noRoadmap,
    "**Delivery: incremental** (the default — each plan lands independently)\n\n" +
      `Just prose.\n\n${block.parts.join("\n\n")}\n`,
  );
});
