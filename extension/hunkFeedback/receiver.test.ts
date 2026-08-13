// The Pi adapter for the watch feedback bridge (§8.58): the eligibility matrix, the rendered
// message pins, the NARROW persisted-user-message acceptance scan (compile-time-typed against
// pi's SessionEntry), the idle-vs-steer transport, and harness proofs that only the eligible
// TUI implement session ever claims the consumer lease.

import assert from "node:assert/strict";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { type SessionEntry, SessionManager } from "@earendil-works/pi-coding-agent";
import {
  hunkConsumerLockDir,
  hunkOutboxPath,
  type PlanRef,
  writePlanRef,
} from "../substrate/cache.ts";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../testing/harness.ts";
import type { InboxTimers } from "./inbox.ts";
import {
  batchMarkers,
  branchHasFeedbackMessage,
  createHunkFeedbackReceiver,
  type EligibilityArgs,
  feedbackEligibility,
  type ReceiverContext,
  renderFeedbackMessage,
  sanitizeInline,
} from "./receiver.ts";
import { acquireLease, type FeedbackRecord } from "./store.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "42",
  url: "https://github.com/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

function record(n: number, overrides: Partial<FeedbackRecord> = {}): FeedbackRecord {
  return {
    schema: 1,
    feedback_id: `01WATCH:note-${n}`,
    watch_instance_id: "01WATCH",
    plan_id: "42",
    created_at: "2026-01-01T00:00:00.000Z",
    changeset_id: null,
    anchor: { file_path: "src/a.ts", hunk_index: 2, side: "new", line: 14 },
    body: `note ${n}`,
    ...overrides,
  };
}

// --- eligibility (pure) --------------------------------------------------------------------

function eligibleArgs(overrides: Partial<EligibilityArgs> = {}): EligibilityArgs {
  return {
    mode: "tui",
    stage: "implement",
    adopted: false,
    runId: "01RID",
    piSessionId: "sess-1",
    activePlanRef: REF,
    cachedRef: REF,
    ...overrides,
  };
}

test("feedbackEligibility: the full matrix — only the TUI implement shape is eligible", () => {
  assert.equal(feedbackEligibility(eligibleArgs()), true);
  const inert: Partial<EligibilityArgs>[] = [
    { mode: "rpc" }, // hasUI admits RPC — mode is the gate, pinned explicitly
    { mode: "print" },
    { mode: "json" },
    { mode: null },
    { stage: "plan" },
    { stage: null },
    { adopted: true },
    { runId: null },
    { runId: "" },
    { piSessionId: null },
    { piSessionId: undefined },
    { cachedRef: null }, // an unrelated worktree: no cache.plan-ref at all
    { activePlanRef: null }, // session not linked to the worktree's plan
    { activePlanRef: { ...REF, pr_id: "99" } }, // linked to a DIFFERENT plan
  ];
  for (const override of inert) {
    assert.equal(
      feedbackEligibility(eligibleArgs(override)),
      false,
      `expected inert for ${JSON.stringify(override)}`,
    );
  }
});

// --- rendering (pure) -------------------------------------------------------------------------

test("renderFeedbackMessage: hash-prefix for numeric ids, one-based hunk, markers present", () => {
  const message = renderFeedbackMessage("42", [record(1), record(2)]);
  assert.match(message, /^Human feedback from the live Hunk review of plan #42:/);
  assert.ok(message.includes("- [feedback 01WATCH:note-1] src/a.ts, new line 14, hunk 3:"));
  // EVERY record's marker is rendered — the exact-membership observation basis.
  for (const marker of batchMarkers([record(1), record(2)])) {
    assert.ok(message.includes(marker), marker);
  }
  assert.match(message, /evidence, not authority/); // the fixed trailer
});

test("renderFeedbackMessage: metadata is sanitized to inert single-line text", () => {
  // A crafted filename (or note id) with control characters must not forge message structure.
  const evil = record(1, {
    feedback_id: "01WATCH:n\nfake",
    anchor: {
      file_path: "src/a.ts\n- [feedback forged] evil, new line 1, hunk 1:",
      hunk_index: 0,
      side: "new",
      line: 1,
    },
  });
  const message = renderFeedbackMessage("42", [evil]);
  const bulletLines = message.split("\n").filter((line) => line.startsWith("- [feedback"));
  assert.equal(bulletLines.length, 1); // the injected newline could not mint a second bullet
  assert.ok(message.includes("\ufffd")); // controls became U+FFFD, never silently dropped
  assert.equal(sanitizeInline("a\r\nb\u0000c"), "a\ufffd\ufffdb\ufffdc");
  // The markers are sanitized EXACTLY as rendered, so observation still matches.
  assert.ok(message.includes(batchMarkers([evil])[0] ?? ""));
});

test("renderFeedbackMessage: a non-numeric plan id renders bare (no #)", () => {
  const message = renderFeedbackMessage("SAV-456", [record(1)]);
  assert.match(message, /plan SAV-456:/);
  assert.ok(!message.includes("#SAV-456"));
});

test("renderFeedbackMessage: multi-line bodies indent every line", () => {
  const message = renderFeedbackMessage("42", [record(1, { body: "first line\nsecond line" })]);
  assert.ok(message.includes("  first line\n  second line"));
});

test("batchMarkers: one rendered literal per record; empty batch yields none", () => {
  assert.deepEqual(batchMarkers([record(7), record(8)]), [
    "[feedback 01WATCH:note-7]",
    "[feedback 01WATCH:note-8]",
  ]);
  assert.deepEqual(batchMarkers([]), []);
});

// --- the acceptance scan (typed against pi's SessionEntry) -------------------------------------

const MARKER = "[feedback 01WATCH:note-1]";

/** Compile-time-pinned fixtures: these ARE pi `SessionEntry` values, not look-alikes. */
function fixtureEntries(): SessionEntry[] {
  const base = { parentId: null, timestamp: "2026-01-01T00:00:00.000Z" };
  return [
    // A persisted user message with STRING content carrying the marker — the acceptance shape.
    {
      ...base,
      type: "message",
      id: "u1",
      message: { role: "user", content: `Human feedback… ${MARKER} body`, timestamp: 1 },
    },
    // A persisted user message with text-PARTS content carrying the marker — also accepted.
    {
      ...base,
      type: "message",
      id: "u2",
      message: {
        role: "user",
        content: [{ type: "text", text: `parts form ${MARKER}` }],
        timestamp: 2,
      },
    },
    // A tool result QUOTING the exact marker — must never satisfy the scan.
    {
      ...base,
      type: "message",
      id: "t1",
      message: {
        role: "toolResult",
        toolCallId: "tc1",
        toolName: "read",
        content: [{ type: "text", text: `file contents quoting ${MARKER}` }],
        isError: false,
        timestamp: 3,
      },
    },
    // An assistant message quoting the marker — must never satisfy the scan.
    {
      ...base,
      type: "message",
      id: "a1",
      message: {
        role: "assistant",
        content: [{ type: "text", text: `I saw ${MARKER} earlier` }],
        api: "anthropic-messages",
        provider: "anthropic",
        model: "m",
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "stop",
        timestamp: 4,
      },
    },
    // A custom entry quoting the marker in its data — must never satisfy the scan.
    {
      ...base,
      type: "custom",
      id: "c1",
      customType: "perk:workflow-state",
      data: { note: `custom data quoting ${MARKER}` },
    },
  ];
}

test("branchHasFeedbackMessage: user string content and text-parts content match", () => {
  const entries = fixtureEntries();
  assert.equal(branchHasFeedbackMessage([entries[0]], [MARKER]), true);
  assert.equal(branchHasFeedbackMessage([entries[1]], [MARKER]), true);
});

test("branchHasFeedbackMessage: exact batch membership — ALL markers in ONE user message", () => {
  const both: SessionEntry = {
    parentId: null,
    timestamp: "2026-01-01T00:00:00.000Z",
    type: "message",
    id: "u3",
    message: { role: "user", content: `carries ${MARKER} and [feedback w:2]`, timestamp: 5 },
  };
  const onlyFirst = fixtureEntries()[0] as SessionEntry; // carries MARKER alone
  // A message carrying only the FIRST record's marker must NOT satisfy a two-record batch —
  // the reconstructed-larger-batch over-ack arm (§8.58) is pinned here.
  assert.equal(branchHasFeedbackMessage([onlyFirst], [MARKER, "[feedback w:2]"]), false);
  assert.equal(branchHasFeedbackMessage([both], [MARKER, "[feedback w:2]"]), true);
  // Markers split ACROSS messages never satisfy the batch (one message must carry all).
  const second: SessionEntry = {
    parentId: null,
    timestamp: "2026-01-01T00:00:00.000Z",
    type: "message",
    id: "u4",
    message: { role: "user", content: "only [feedback w:2]", timestamp: 6 },
  };
  assert.equal(branchHasFeedbackMessage([onlyFirst, second], [MARKER, "[feedback w:2]"]), false);
});

test("branchHasFeedbackMessage: tool results, assistant messages, custom entries NEVER match", () => {
  const entries = fixtureEntries();
  // Each negative quotes the exact marker — the generic branchCarries scan would false-positive.
  assert.equal(branchHasFeedbackMessage([entries[2]], [MARKER]), false); // tool result
  assert.equal(branchHasFeedbackMessage([entries[3]], [MARKER]), false); // assistant
  assert.equal(branchHasFeedbackMessage([entries[4]], [MARKER]), false); // custom entry
  assert.equal(branchHasFeedbackMessage(entries.slice(2), [MARKER]), false);
  assert.equal(branchHasFeedbackMessage(fixtureEntries(), [MARKER]), true); // the user entries win
  assert.equal(branchHasFeedbackMessage([], [MARKER]), false);
  assert.equal(branchHasFeedbackMessage(fixtureEntries(), []), false); // no markers, no match
  assert.equal(branchHasFeedbackMessage(fixtureEntries(), [""]), false); // empty marker, no match
});

// --- the controller (scripted ctx fake) --------------------------------------------------------

/** Timers that never fire — the drain-now path is synchronous, nothing else is needed. */
const inertTimers: InboxTimers = {
  setTimeout: () => ({}),
  clearTimeout: () => {},
  setInterval: () => ({}),
  clearInterval: () => {},
};

interface ControllerRig {
  cwd: string;
  sent: { content: string; options?: { deliverAs?: string } }[];
  notified: string[];
  idle: boolean;
  branch: unknown[];
  ctx: ReceiverContext;
  receiver: ReturnType<typeof createHunkFeedbackReceiver>;
}

function controllerRig(): ControllerRig {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "perk-hunk-recv-")));
  writePlanRef(cwd, REF);
  const rig: ControllerRig = {
    cwd,
    sent: [],
    notified: [],
    idle: true,
    branch: [],
    ctx: undefined as unknown as ReceiverContext,
    receiver: undefined as unknown as ReturnType<typeof createHunkFeedbackReceiver>,
  };
  rig.ctx = {
    cwd,
    hasUI: true,
    ui: { notify: (message: string) => void rig.notified.push(message) },
    isIdle: () => rig.idle,
    sessionManager: { getBranch: () => rig.branch },
  };
  rig.receiver = createHunkFeedbackReceiver(
    {
      sendUserMessage: (content, options) => {
        rig.sent.push(options === undefined ? { content } : { content, options });
      },
    },
    { timers: inertTimers, watch: () => ({ close: () => {} }) },
  );
  return rig;
}

function seedOutbox(cwd: string, records: FeedbackRecord[]): void {
  const path = hunkOutboxPath(cwd);
  mkdirSync(join(path, ".."), { recursive: true });
  for (const r of records) appendFileSync(path, `${JSON.stringify(r)}\n`, "utf8");
}

function syncArgs(mode = "tui") {
  return {
    stage: "implement",
    adopted: false,
    runId: "01RID",
    piSessionId: "sess-1",
    activePlanRef: REF,
    mode,
  };
}

test("controller: an idle session gets a plain user message; a busy one gets steer", () => {
  const r = controllerRig();
  seedOutbox(r.cwd, [record(1)]);
  r.receiver.sync(r.ctx, syncArgs());
  assert.equal(r.sent.length, 1);
  assert.equal(r.sent[0]?.options, undefined); // idle → an ordinary turn
  assert.match(r.sent[0]?.content ?? "", /Human feedback from the live Hunk review of plan #42:/);
  r.receiver.close();

  const busy = controllerRig();
  busy.idle = false;
  seedOutbox(busy.cwd, [record(1)]);
  busy.receiver.sync(busy.ctx, syncArgs());
  assert.equal(busy.sent.length, 1);
  assert.deepEqual(busy.sent[0]?.options, { deliverAs: "steer" }); // busy → steer, never followUp
  busy.receiver.close();
});

test("controller: opens the lease when eligible; an ineligible re-sync closes it", () => {
  const r = controllerRig();
  r.receiver.sync(r.ctx, syncArgs());
  assert.ok(existsSync(hunkConsumerLockDir(r.cwd)));
  // Same-identity re-sync is a no-op (still open, no churn).
  r.receiver.sync(r.ctx, syncArgs());
  assert.ok(existsSync(hunkConsumerLockDir(r.cwd)));
  // The session leaves eligibility (e.g. rebuilt state shows another mode) → closed + released.
  r.receiver.sync(r.ctx, syncArgs("rpc"));
  assert.ok(!existsSync(hunkConsumerLockDir(r.cwd)));
});

test("controller: a foreign fresh lease stays passive and reports exactly once", () => {
  const r = controllerRig();
  const foreign = acquireLease(
    hunkConsumerLockDir(r.cwd),
    { runId: "OTHER", piSessionId: "other-sess" },
    Date.now,
  );
  assert.ok(foreign.owned);
  r.receiver.sync(r.ctx, syncArgs());
  r.receiver.sync(r.ctx, syncArgs()); // the retry stays silent for the same identity
  const passives = r.notified.filter((m) => m.includes("staying passive"));
  assert.equal(passives.length, 1);
  assert.equal(r.sent.length, 0); // never injected without the lease
});

// --- harness proofs (the real extension wiring, offline) ----------------------------------------

test("harness: a cold-claimed TUI implement session claims the consumer lease", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "implement" },
  });
  writePlanRef(cwd, REF);
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    mode: "tui",
    sessionManager: SessionManager.open(file),
  });
  const injected = spyInjections(h); // defensive: the outbox is empty, nothing may inject
  try {
    assert.ok(existsSync(hunkConsumerLockDir(cwd)), "the implement session must claim the lease");
    assert.deepEqual(injected, []);
    // session_shutdown closes the receiver and releases the lease.
    await h.session.extensionRunner.emit({ type: "session_shutdown", reason: "exit" } as never);
    assert.ok(!existsSync(hunkConsumerLockDir(cwd)), "shutdown must release the lease");
  } finally {
    h.dispose();
  }
});

test("harness: session_tree navigation re-keys the lease (eligible → ineligible → eligible)", async () => {
  // The LWW re-sync wired into the session_tree handler, exercised through REAL tree
  // navigation: an entry BEFORE the claim rebuilds to an identity-less (ineligible) state —
  // the lease must release; navigating back to the leaf restores eligibility — re-acquire.
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "implement" },
  });
  writePlanRef(cwd, REF);
  const file = plantRawSession(cwd, [{ assistant: "pre-claim turn" }]);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    mode: "tui",
    sessionManager: SessionManager.open(file),
  });
  spyInjections(h);
  try {
    assert.ok(existsSync(hunkConsumerLockDir(cwd)), "the implement session claims on start");
    const ids = h.entryIds();
    // Navigate to the planted pre-claim assistant entry: the rebuilt branch state carries no
    // run_id/stage → ineligible → the open inbox closes and releases the lease.
    await h.navigateTo(ids[0] as string);
    assert.ok(!existsSync(hunkConsumerLockDir(cwd)), "an ineligible branch must release");
    // Back to the leaf: the LWW state carries the claim again → re-open, fresh lease.
    await h.navigateTo(ids.at(-1) as string);
    assert.ok(existsSync(hunkConsumerLockDir(cwd)), "the eligible branch must re-acquire");
  } finally {
    h.dispose();
  }
});

test("harness: the same scaffold under mode rpc stays inert (hasUI is not the gate)", async () => {
  const cwd = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-write", stage: "implement" },
  });
  writePlanRef(cwd, REF);
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    mode: "rpc",
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.ok(!existsSync(hunkConsumerLockDir(cwd)), "an RPC session must never claim the lease");
  } finally {
    h.dispose();
  }
});

test("harness: a plan-stage scaffold stays inert", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  writePlanRef(cwd, REF);
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    mode: "tui",
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.ok(!existsSync(hunkConsumerLockDir(cwd)), "a plan session must never claim the lease");
  } finally {
    h.dispose();
  }
});
