// The ONE owner of the projection/evidence matrix behind every live-context dedup (the shared
// authoring/provider installer, binding delivery, agent scratch): which carriers count, what
// compaction retains/summarizes, and which branch the projection follows. Drives real
// `SessionManager` append/branch/compaction APIs and asserts LITERAL native messages + predicate
// results — never a second local reconstruction of Pi's selection. Consumer suites own only their
// distinct policies and wiring; they do not replay this matrix.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type CustomMessageEntry,
  type SessionEntry,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import {
  activeContextMessages,
  type ContextMessage,
  type ContextProjectionSource,
  contextCarriesMarker,
} from "./contextEvidence.ts";

const OWNER = { customType: "perk:test-context", marker: "[TEST CONTEXT]" };
const MARKER = OWNER.marker;
const OTHER_TYPE = "perk:other-context";

function session(): SessionManager {
  return SessionManager.inMemory("/nowhere");
}

/** Append any runtime message through the real API (shape-agnostic cast at the test boundary). */
function appendMessage(manager: SessionManager, message: Record<string, unknown>): string {
  return manager.appendMessage(message as never);
}

function user(content: unknown, timestamp = 1): Record<string, unknown> {
  return { role: "user", content, timestamp };
}

function assistant(text: string, timestamp = 2): Record<string, unknown> {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    api: "test",
    provider: "test",
    model: "test",
    usage: {},
    stopReason: "stop",
    timestamp,
  };
}

function toolResult(text: string, timestamp = 3): Record<string, unknown> {
  return {
    role: "toolResult",
    toolCallId: "tc-1",
    toolName: "bash",
    content: [{ type: "text", text }],
    isError: false,
    timestamp,
  };
}

function bashExecution(output: string, timestamp = 4): Record<string, unknown> {
  return {
    role: "bashExecution",
    command: "echo",
    output,
    exitCode: 0,
    cancelled: false,
    truncated: false,
    timestamp,
  };
}

/** The epoch-ms timestamp Pi stamps on a projected custom_message (from the entry's ISO stamp). */
function entryTimestamp(manager: SessionManager, id: string): number {
  const entry = manager.getEntry(id);
  assert.ok(entry !== undefined, `entry ${id} exists`);
  return new Date(entry.timestamp).getTime();
}

/** The structural source the leaf reads (a real SessionManager satisfies the Pick). */
function over(manager: SessionManager): ContextProjectionSource {
  return { sessionManager: manager };
}

/** Pi's current projection for `manager`'s selected leaf. */
function projected(manager: SessionManager): ContextMessage[] {
  return activeContextMessages(over(manager));
}

function carries(manager: SessionManager, owner = OWNER): boolean {
  return contextCarriesMarker(projected(manager), owner);
}

/** The retired serialized scan — kept ONLY to prove each negative fixture distinguishes from it. */
function serializedScanWouldMatch(messages: readonly ContextMessage[], marker: string): boolean {
  return messages.some((message) => JSON.stringify(message).includes(marker));
}

// ------------------------------------------------------------------------- carriers (positive)

test("empty and uncompacted context: literal native messages, byte-preserved content shapes", () => {
  const manager = session();
  assert.deepEqual(projected(manager), []);
  assert.equal(carries(manager), false);

  appendMessage(manager, user(`cold prompt\n\n${MARKER}\nseeded`));
  appendMessage(manager, user([{ type: "text", text: `text-part ${MARKER}` }], 5));
  const hiddenId = manager.appendCustomMessageEntry(OWNER.customType, `${MARKER}\nhidden`, false);
  appendMessage(manager, {
    role: "custom",
    customType: OWNER.customType,
    content: [{ type: "text", text: `${MARKER}\nvia message entry` }],
    display: false,
    timestamp: 6,
  });

  assert.deepEqual(projected(manager), [
    { role: "user", content: `cold prompt\n\n${MARKER}\nseeded`, timestamp: 1 },
    { role: "user", content: [{ type: "text", text: `text-part ${MARKER}` }], timestamp: 5 },
    {
      role: "custom",
      customType: OWNER.customType,
      content: `${MARKER}\nhidden`,
      display: false,
      details: undefined,
      timestamp: entryTimestamp(manager, hiddenId),
    },
    {
      role: "custom",
      customType: OWNER.customType,
      content: [{ type: "text", text: `${MARKER}\nvia message entry` }],
      display: false,
      timestamp: 6,
    },
  ]);
  assert.equal(carries(manager), true);
});

test("each carrier alone is evidence: string user, text-part user, hidden custom, custom message entry", () => {
  const cases: ((manager: SessionManager) => void)[] = [
    (m) => appendMessage(m, user(`${MARKER} as a string`)),
    (m) => appendMessage(m, user([{ type: "text", text: `${MARKER} as a text part` }])),
    (m) => m.appendCustomMessageEntry(OWNER.customType, `${MARKER}\nhidden`, false),
    (m) =>
      m.appendCustomMessageEntry(
        OWNER.customType,
        [{ type: "text", text: `${MARKER} part` }],
        true,
      ),
    (m) =>
      appendMessage(m, {
        role: "custom",
        customType: OWNER.customType,
        content: `${MARKER} runtime custom`,
        display: false,
        timestamp: 7,
      }),
  ];
  for (const [index, plant] of cases.entries()) {
    const manager = session();
    plant(manager);
    assert.equal(carries(manager), true, `carrier #${index} is live evidence`);
  }
});

// ------------------------------------------------------------------------- carriers (negative)

test("the exact marker in non-evidence roles/shapes is NOT live delivery (typed, not serialized)", () => {
  const cases: { name: string; plant: (manager: SessionManager) => void }[] = [
    { name: "assistant text", plant: (m) => appendMessage(m, assistant(`${MARKER} quoted`)) },
    { name: "tool result text", plant: (m) => appendMessage(m, toolResult(`${MARKER} output`)) },
    { name: "bash output", plant: (m) => appendMessage(m, bashExecution(`${MARKER} printed`)) },
    {
      name: "wrong-owner custom content",
      plant: (m) => m.appendCustomMessageEntry(OTHER_TYPE, `${MARKER}\nanother owner`, false),
    },
    {
      name: "wrong-owner custom message entry",
      plant: (m) =>
        appendMessage(m, {
          role: "custom",
          customType: OTHER_TYPE,
          content: `${MARKER} other runtime custom`,
          display: false,
          timestamp: 8,
        }),
    },
    {
      name: "owned custom details (metadata, not content)",
      plant: (m) =>
        m.appendCustomMessageEntry(OWNER.customType, "unrelated content", false, {
          note: `${MARKER} in details`,
        }),
    },
    {
      name: "compaction summary quoting the marker",
      plant: (m) => {
        const kept = appendMessage(m, assistant("recent"));
        m.appendCompaction(`history mentioned ${MARKER} once`, kept, 100);
      },
    },
    {
      name: "branch summary quoting the marker",
      plant: (m) => {
        const keep = appendMessage(m, assistant("keep"));
        appendMessage(m, assistant("abandoned"));
        m.branchWithSummary(keep, `the abandoned branch carried ${MARKER}`);
      },
    },
  ];
  for (const { name, plant } of cases) {
    const manager = session();
    plant(manager);
    const messages = projected(manager);
    assert.equal(
      serializedScanWouldMatch(messages, MARKER),
      true,
      `${name}: the bytes ARE in the projection (the old scan would have matched)`,
    );
    assert.equal(contextCarriesMarker(messages, OWNER), false, `${name}: not typed evidence`);
  }
});

test("plain `custom` state never projects — `data.content` is state, not model delivery", () => {
  const manager = session();
  manager.appendCustomEntry(OWNER.customType, { content: `${MARKER}\nlooks like a prior copy` });
  assert.deepEqual(projected(manager), [], "Pi projects no message for custom state");
  assert.equal(carries(manager), false);
  // The entry IS on the branch — the distinction from the retired serialized branch scan.
  assert.equal(
    manager.getBranch().some((entry) => JSON.stringify(entry).includes(MARKER)),
    true,
  );
});

test("non-text/malformed parts are ignored; a marker split across parts is not evidence", () => {
  const [head, tail] = ["[TEST ", "CONTEXT]"];
  assert.equal(head + tail, MARKER);
  const malformed: ContextMessage[] = [
    { role: "user", content: [{ type: "image", data: MARKER, mimeType: "image/png" }] } as never,
    { role: "user", content: [{ type: "text" }] } as never,
    { role: "user", content: [{ type: "text", text: 42 }] } as never,
    { role: "user", content: [null, "string part", { text: MARKER }] } as never,
    { role: "user", content: { text: MARKER } } as never,
    { role: "user", content: undefined } as never,
    {
      role: "user",
      content: [
        { type: "text", text: head },
        { type: "text", text: tail },
      ],
    } as never,
    {
      role: "custom",
      customType: OWNER.customType,
      content: [
        { type: "text", text: head },
        { type: "text", text: tail },
      ],
      display: false,
      timestamp: 1,
    } as never,
  ];
  for (const message of malformed) {
    assert.equal(contextCarriesMarker([message], OWNER), false, JSON.stringify(message));
  }
  // …while one valid part beside malformed siblings still counts (parts are checked, not joined).
  assert.equal(
    contextCarriesMarker(
      [
        {
          role: "user",
          content: [{ type: "text" }, { type: "text", text: `${MARKER} whole` }],
        } as never,
      ],
      OWNER,
    ),
    true,
  );
});

// ------------------------------------------------------------------------- compaction sequence

test("compaction sequence: retained → summarized (quoted) → fresh direct copy", () => {
  const manager = session();
  appendMessage(manager, user("start"));
  const deliveryId = manager.appendCustomMessageEntry(OWNER.customType, `${MARKER}\nv1`, false);
  appendMessage(manager, assistant("work"));
  appendMessage(manager, assistant("more work"));
  assert.equal(carries(manager), true, "uncompacted: the delivery is live");

  // Checkpoint 1: compaction RETAINS the delivery (kept from its id onward).
  manager.appendCompaction("summary one", deliveryId, 100);
  assert.deepEqual(
    projected(manager).map((m) => m.role),
    ["compactionSummary", "custom", "assistant", "assistant"],
    "Pi keeps the summary + the retained tail",
  );
  assert.equal(carries(manager), true, "a retained delivery is still live evidence");

  // Checkpoint 2: a later compaction SUMMARIZES it away — the summary even quotes the marker.
  const postId = appendMessage(manager, assistant("work after the first compaction", 9));
  manager.appendCompaction(`summary two: the model was told ${MARKER} earlier`, postId, 200);
  assert.deepEqual(
    projected(manager).map((m) => m.role),
    ["compactionSummary", "assistant"],
    "only the latest compaction + its kept tail project",
  );
  assert.equal(carries(manager), false, "a quoted marker in the summary is not live delivery");
  assert.equal(
    manager.getBranch().some((e) => e.id === deliveryId),
    true,
    "the historical delivery is still on the full branch (history ≠ live context)",
  );

  // Checkpoint 3: a fresh direct copy restores evidence.
  manager.appendCustomMessageEntry(OWNER.customType, `${MARKER}\nv2`, false);
  assert.equal(carries(manager), true);
});

// ------------------------------------------------------------------------- branch selection

test("branch sequence: live/missing siblings, an abandoned-branch summary quote, a pre-compaction checkpoint", () => {
  const manager = session();
  const rootId = appendMessage(manager, assistant("root"));
  const liveId = manager.appendCustomMessageEntry(OWNER.customType, `${MARKER}\nlive`, false);
  const afterLiveId = appendMessage(manager, assistant("after the live copy"));
  assert.equal(carries(manager), true);

  // A sibling branch off the root that never received the delivery.
  manager.branch(rootId);
  const missingId = appendMessage(manager, assistant("the sibling without a delivery"));
  assert.equal(carries(manager), false, "the projection follows the selected leaf");
  assert.deepEqual(
    projected(manager).map((m) => m.role),
    ["assistant", "assistant"],
  );

  // Back onto the live sibling: evidence returns.
  manager.branch(afterLiveId);
  assert.equal(carries(manager), true);

  // Abandon the live sibling with a summary that QUOTES the marker — not evidence on the new path.
  manager.branchWithSummary(missingId, `abandoned path had ${MARKER} delivered`);
  const onNewPath = projected(manager);
  assert.deepEqual(
    onNewPath.map((m) => m.role),
    ["assistant", "assistant", "branchSummary"],
  );
  assert.equal(serializedScanWouldMatch(onNewPath, MARKER), true);
  assert.equal(contextCarriesMarker(onNewPath, OWNER), false);

  // Compact the live sibling so its delivery is summarized away, then revisit the checkpoint
  // BEFORE that compaction: the pre-compaction leaf still projects the direct copy.
  manager.branch(afterLiveId);
  manager.appendCompaction("compacted the live sibling", afterLiveId, 50);
  assert.equal(carries(manager), false, "post-compaction leaf: the copy is summarized away");
  manager.branch(liveId);
  assert.equal(carries(manager), true, "the pre-compaction checkpoint still carries it directly");
});

// ------------------------------------------------------------------------- source discipline

test("the leaf reads buildContextEntries() exactly once and never getBranch(); a throw propagates", () => {
  const calls: string[] = [];
  const hidden: CustomMessageEntry = {
    type: "custom_message",
    id: "cm1",
    parentId: null,
    timestamp: "2025-01-01T00:00:00.000Z",
    customType: OWNER.customType,
    content: `${MARKER}\nrecorded`,
    display: false,
  };
  const recording = {
    sessionManager: {
      buildContextEntries(): SessionEntry[] {
        calls.push("buildContextEntries");
        return [hidden];
      },
      getBranch(): SessionEntry[] {
        calls.push("getBranch");
        return [];
      },
    },
  };
  const messages = activeContextMessages(recording);
  assert.deepEqual(calls, ["buildContextEntries"], "one projection read, no full-branch read");
  assert.deepEqual(messages, [
    {
      role: "custom",
      customType: OWNER.customType,
      content: `${MARKER}\nrecorded`,
      display: false,
      details: undefined,
      timestamp: Date.parse("2025-01-01T00:00:00.000Z"),
    },
  ]);
  assert.equal(contextCarriesMarker(messages, OWNER), true);

  const throwing: ContextProjectionSource = {
    sessionManager: {
      buildContextEntries(): SessionEntry[] {
        throw new Error("adversarial projection read");
      },
    },
  };
  assert.throws(
    () => activeContextMessages(throwing),
    /adversarial projection read/,
    "a failed read is never manufactured into an empty projection",
  );
});
