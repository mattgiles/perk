// The report child's task-restore policy: the branch readers, the ordered verdict table, the
// restored text and the model-facing reasons. The Pi hooks are tested end-to-end beside their
// adapter in pi/v1/childTaskRestore.test.ts. See childTaskRestore.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyQueued,
  createRestoreState,
  firstUserPrompt,
  latestCompactionId,
  type RestoreInputs,
  type RestoreState,
  restoreDelivered,
  restoreVerdict,
  structuredOutputHoldReason,
  TASK_RESTORE_MAX_ATTEMPTS,
  TASK_RESTORE_MAX_BYTES,
  TASK_RESTORE_PREAMBLE,
  TASK_RESTORE_TYPE,
} from "./childTaskRestore.ts";

const ONCE_ONLY =
  "perk: this structured_output call was not accepted — nothing was captured — so your " +
  "once-only completion rule is unaffected: the accepted call is the one that counts.";

function userEntry(content: unknown, id = "u1"): Record<string, unknown> {
  return { type: "message", id, message: { role: "user", content } };
}

function assistantEntry(id = "a1"): Record<string, unknown> {
  return {
    type: "message",
    id,
    message: { role: "assistant", content: [{ type: "text", text: "ok" }] },
  };
}

function compactionEntry(id: string): Record<string, unknown> {
  return { type: "compaction", id, summary: "summary", firstKeptEntryId: "a1" };
}

function restoreEntry(id: string, customType = TASK_RESTORE_TYPE): Record<string, unknown> {
  return { type: "custom_message", id, customType, content: "restored", display: true };
}

// ------------------------------------------------------------------------- firstUserPrompt

test("firstUserPrompt: string content, one text part, an image before the text part", () => {
  assert.equal(firstUserPrompt([userEntry("Task: review")]), "Task: review");
  assert.equal(
    firstUserPrompt([userEntry([{ type: "text", text: "Task: parts" }])]),
    "Task: parts",
  );
  assert.equal(
    firstUserPrompt([
      userEntry([
        { type: "image", data: "…", mimeType: "image/png" },
        { type: "text", text: "Task: after the image" },
      ]),
    ]),
    "Task: after the image",
  );
});

test("firstUserPrompt: a preceding assistant entry and non-message entries are skipped", () => {
  assert.equal(
    firstUserPrompt([
      { type: "custom", customType: "perk:workflow-state", data: {} },
      assistantEntry(),
      userEntry("Task: first user"),
      userEntry("a later user message", "u2"),
    ]),
    "Task: first user",
  );
});

test("firstUserPrompt: no user message, or a malformed first user message, is null", () => {
  assert.equal(firstUserPrompt([]), null);
  assert.equal(firstUserPrompt([assistantEntry(), compactionEntry("c1")]), null);
  for (const content of [42, null, undefined, { text: "Task" }, [], [{ type: "text", text: 7 }]]) {
    assert.equal(firstUserPrompt([userEntry(content)]), null, JSON.stringify(content));
  }
  // The first user message decides — a later well-formed one does not rescue a malformed first.
  assert.equal(firstUserPrompt([userEntry(42), userEntry("Task: later", "u2")]), null);
  // Non-record entries and parts are ignored, never thrown on.
  assert.equal(
    firstUserPrompt([null, "entry", 3, userEntry([null, "part", { type: "text", text: "T" }])]),
    "T",
  );
});

test("firstUserPrompt: inherited (prototype-carried) shapes never match", () => {
  const inheritedEntry = Object.create({
    type: "message",
    message: { role: "user", content: "Task: inherited entry" },
  });
  const inheritedMessage = {
    type: "message",
    message: Object.create({ role: "user", content: "x" }),
  };
  const inheritedContent = {
    type: "message",
    message: Object.assign(Object.create({ content: "x" }), { role: "user" }),
  };
  const inheritedPart = userEntry([Object.create({ type: "text", text: "Task: inherited part" })]);
  assert.equal(firstUserPrompt([inheritedEntry]), null);
  assert.equal(firstUserPrompt([inheritedMessage]), null);
  assert.equal(firstUserPrompt([inheritedContent]), null);
  assert.equal(firstUserPrompt([inheritedPart]), null);
});

// ------------------------------------------------------------------------- compaction / delivery

test("latestCompactionId / restoreDelivered: none ⇒ null/false", () => {
  assert.equal(latestCompactionId([]), null);
  assert.equal(restoreDelivered([]), false);
  assert.equal(latestCompactionId([userEntry("Task"), assistantEntry()]), null);
  assert.equal(restoreDelivered([userEntry("Task"), assistantEntry()]), false);
});

test("latestCompactionId / restoreDelivered: a restore after the latest compaction", () => {
  const branch = [userEntry("Task"), assistantEntry(), compactionEntry("c1"), restoreEntry("r1")];
  assert.equal(latestCompactionId(branch), "c1");
  assert.equal(restoreDelivered(branch), true);
  // With no compaction, a restore anywhere on the branch counts.
  assert.equal(restoreDelivered([userEntry("Task"), restoreEntry("r1")]), true);
});

test("restoreDelivered: a restore BEFORE the latest compaction, or a foreign customType, is not delivery", () => {
  const before = [
    userEntry("Task"),
    compactionEntry("c1"),
    restoreEntry("r1"),
    assistantEntry("a2"),
    compactionEntry("c2"),
  ];
  assert.equal(latestCompactionId(before), "c2");
  assert.equal(restoreDelivered(before), false);
  const foreign = [userEntry("Task"), compactionEntry("c1"), restoreEntry("x1", "perk:other")];
  assert.equal(restoreDelivered(foreign), false);
  const inherited = [compactionEntry("c1"), Object.create(restoreEntry("r1"))];
  assert.equal(restoreDelivered(inherited), false, "an inherited shape never counts");
  assert.equal(latestCompactionId([Object.create(compactionEntry("c9"))]), null);
});

// ------------------------------------------------------------------------- the verdict table

const PROMPT = "Task: Angle: grounding\n<untrusted_draft>\n# Plan\n</untrusted_draft>";

function inputs(overrides: Partial<RestoreInputs> = {}): RestoreInputs {
  return {
    state: createRestoreState(),
    prompt: PROMPT,
    taskLive: false,
    compactionId: "c1",
    delivered: false,
    ...overrides,
  };
}

function withState(overrides: Partial<RestoreState>): RestoreState {
  return { ...createRestoreState(), ...overrides };
}

test("verdict: an accepted report allows, even when nothing is live and the attempts are spent", () => {
  assert.deepEqual(
    restoreVerdict(
      inputs({ state: withState({ accepted: true, restores: TASK_RESTORE_MAX_ATTEMPTS }) }),
    ),
    { kind: "allow" },
  );
});

test("verdict: a null prompt allows (nothing to protect)", () => {
  assert.deepEqual(restoreVerdict(inputs({ prompt: null })), { kind: "allow" });
});

test("verdict: a live task allows", () => {
  assert.deepEqual(restoreVerdict(inputs({ taskLive: true })), { kind: "allow" });
  // Liveness short-circuits the size cap: an oversized prompt still in context is untouched.
  const huge = "x".repeat(TASK_RESTORE_MAX_BYTES + 1);
  assert.deepEqual(restoreVerdict(inputs({ prompt: huge, taskLive: true })), { kind: "allow" });
});

test("verdict: the byte cap — exactly the cap queues, one byte over (multi-byte) refuses naming bytes and cap", () => {
  const exact = "x".repeat(TASK_RESTORE_MAX_BYTES);
  assert.equal(restoreVerdict(inputs({ prompt: exact })).kind, "queue");
  // One two-byte character: the CHARACTER count equals the cap, the byte count is one over.
  const over = `${"x".repeat(TASK_RESTORE_MAX_BYTES - 1)}é`;
  assert.equal(over.length, TASK_RESTORE_MAX_BYTES);
  assert.equal(Buffer.byteLength(over, "utf8"), TASK_RESTORE_MAX_BYTES + 1);
  const verdict = restoreVerdict(inputs({ prompt: over }));
  assert.equal(verdict.kind, "refuse");
  assert.ok(verdict.kind === "refuse");
  assert.equal(
    verdict.reason,
    structuredOutputHoldReason({ kind: "oversized", bytes: TASK_RESTORE_MAX_BYTES + 1 }),
  );
  assert.match(verdict.reason, new RegExp(`at ${TASK_RESTORE_MAX_BYTES + 1} bytes`));
  assert.match(verdict.reason, new RegExp(`the ${TASK_RESTORE_MAX_BYTES}-byte restore cap`));
});

test("verdict: queued for the same compaction and undelivered holds", () => {
  const verdict = restoreVerdict(inputs({ state: withState({ restores: 1, queuedFor: "c1" }) }));
  assert.deepEqual(verdict, { kind: "hold", reason: structuredOutputHoldReason({ kind: "held" }) });
  // No compaction: a queue recorded as "none" holds against a null id.
  assert.equal(
    restoreVerdict(
      inputs({ compactionId: null, state: withState({ restores: 1, queuedFor: "none" }) }),
    ).kind,
    "hold",
  );
});

test("verdict: queued for the same compaction, delivered but not live, re-queues (the omission arm)", () => {
  const verdict = restoreVerdict(
    inputs({ delivered: true, state: withState({ restores: 1, queuedFor: "c1" }) }),
  );
  assert.equal(verdict.kind, "queue");
});

test("verdict: a different compaction id queues", () => {
  assert.equal(
    restoreVerdict(
      inputs({ compactionId: "c2", state: withState({ restores: 1, queuedFor: "c1" }) }),
    ).kind,
    "queue",
  );
});

test("verdict: attempts exhausted refuses", () => {
  const verdict = restoreVerdict(
    inputs({
      compactionId: "c4",
      state: withState({ restores: TASK_RESTORE_MAX_ATTEMPTS, queuedFor: "c3" }),
    }),
  );
  assert.deepEqual(verdict, {
    kind: "refuse",
    reason: structuredOutputHoldReason({ kind: "exhausted" }),
  });
  // One short of the bound still queues.
  assert.equal(
    restoreVerdict(
      inputs({
        compactionId: "c3",
        state: withState({ restores: TASK_RESTORE_MAX_ATTEMPTS - 1, queuedFor: "c2" }),
      }),
    ).kind,
    "queue",
  );
});

test('applyQueued increments restores and records queuedFor ("none" for a null id)', () => {
  const state = createRestoreState();
  assert.deepEqual(state, { accepted: false, restores: 0, queuedFor: null });
  applyQueued(state, "c1");
  assert.deepEqual(state, { accepted: false, restores: 1, queuedFor: "c1" });
  applyQueued(state, null);
  assert.deepEqual(state, { accepted: false, restores: 2, queuedFor: "none" });
  assert.notStrictEqual(createRestoreState(), createRestoreState(), "fresh state per call");
});

// ------------------------------------------------------------------------- restored text + reasons

test("queue text is the preamble, a blank line, and the prompt byte-for-byte", () => {
  const prompt =
    "Task: ünïcödé\r\n  trailing spaces  \n\n\t<untrusted_draft>\n</untrusted_draft>\n";
  const verdict = restoreVerdict(inputs({ prompt }));
  assert.ok(verdict.kind === "queue");
  assert.equal(verdict.text, `${TASK_RESTORE_PREAMBLE}\n\n${prompt}`);
  assert.ok(verdict.text.includes(prompt));
  assert.ok(
    Buffer.from(verdict.text, "utf8")
      .subarray(-Buffer.byteLength(prompt))
      .equals(Buffer.from(prompt)),
  );
  assert.equal(verdict.reason, structuredOutputHoldReason({ kind: "held" }));
});

test("the preamble is role-neutral: no anchoring rule, no instructions-vs-data verdict", () => {
  assert.equal(TASK_RESTORE_PREAMBLE.includes("phrase"), false);
  assert.equal(TASK_RESTORE_PREAMBLE.includes("never instructions"), false);
  assert.ok(TASK_RESTORE_PREAMBLE.startsWith("perk: this session was compacted."));
  assert.equal(TASK_RESTORE_TYPE, "perk:task-restore");
});

test("every reason leads with the once-only sentence; the refuse arms differ only in their cause", () => {
  const held = structuredOutputHoldReason({ kind: "held" });
  const oversized = structuredOutputHoldReason({ kind: "oversized", bytes: 300000 });
  const exhausted = structuredOutputHoldReason({ kind: "exhausted" });
  for (const reason of [held, oversized, exhausted])
    assert.ok(reason.startsWith(`${ONCE_ONLY} `), reason);
  assert.match(held, /a byte-exact restored copy arrives as the next message/);
  assert.match(held, /then call structured_output again\.$/);

  const lead = `${ONCE_ONLY} Your task prompt cannot be restored: `;
  const tail =
    ". A report reconstructed from a summary cannot be faithful — stop here without calling " +
    "structured_output again; the parent records this lane as uncovered.";
  for (const reason of [oversized, exhausted]) {
    assert.ok(reason.startsWith(lead), reason);
    assert.ok(reason.endsWith(tail), reason);
  }
  const cause = (reason: string) => reason.slice(lead.length, reason.length - tail.length);
  assert.equal(
    cause(oversized),
    `at 300000 bytes it exceeds the ${TASK_RESTORE_MAX_BYTES}-byte restore cap`,
  );
  assert.equal(
    cause(exhausted),
    `it has already been restored ${TASK_RESTORE_MAX_ATTEMPTS} times and keeps being compacted away`,
  );
});
