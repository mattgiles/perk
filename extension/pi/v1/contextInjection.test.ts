// The shared context-injection mechanism's DISTINCT policies — owned ONCE here, for every
// `installInjectedContext` caller (gist, plan, objective-authoring, plannotator, tombell): the
// scan-before-construct content thunk, the two guarded reads' failure semantics, the
// submitting-prompt check, the selection-driven retention filter shape (owned copies only —
// user input is preserved byte-for-byte), and one registered-extension composition smoke. Drives the installer through a `pi.on`-recorder fake over REAL `SessionManager` sources
// (no second reconstruction of Pi's selection); the exhaustive carrier/compaction/branch matrix
// lives in `contextEvidence.test.ts`, and feature policy (eligibility, flavor selection, content
// identity) stays pinned in each feature's own suite.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import {
  PLAN_CONTEXT_TYPE,
  PLAN_MARKER,
  planAuthoringContextContent,
} from "../../authoring/plan/prose.ts";
import type { BranchEntry } from "../../substrate/workflowState.ts";
import { loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import { type InjectedContextSpec, installInjectedContext } from "./contextInjection.ts";

const CONTEXT_TYPE = "perk:test-context";
const MARKER = "[TEST CONTEXT]";
const SECOND_MARKER = "[TEST CONTEXT: SECOND]";

type Hook = (event: unknown, ctx: unknown) => Promise<unknown>;

/** Install the spec through a `pi.on`-recorder fake and hand back the two registered hooks. */
function hooksFor(spec: InjectedContextSpec): { inject: Hook; strip: Hook } {
  const handlers = new Map<string, Hook>();
  const pi = {
    on(event: string, handler: Hook) {
      handlers.set(event, handler);
    },
  } as unknown as ExtensionAPI;
  installInjectedContext(pi, spec);
  const inject = handlers.get("before_agent_start");
  const strip = handlers.get("context");
  assert.ok(inject !== undefined && strip !== undefined, "both hooks registered");
  return { inject, strip };
}

/** A structural ctx over a REAL session (both the full branch and Pi's projection are live). */
function ctxOver(manager: SessionManager = SessionManager.inMemory("/nowhere")): ExtensionContext {
  return { cwd: "/nowhere", sessionManager: manager } as unknown as ExtensionContext;
}

/** A structural ctx whose two reads are independently scripted (recording or throwing). */
function ctxFrom(reads: {
  getBranch: () => unknown[];
  buildContextEntries: () => unknown[];
}): ExtensionContext {
  return { cwd: "/nowhere", sessionManager: reads } as unknown as ExtensionContext;
}

/** A minimal always-eligible spec with an invocation-counting content thunk. */
function countingSpec(overrides: Partial<InjectedContextSpec> = {}): {
  spec: InjectedContextSpec;
  counts: { select: number; content: number };
} {
  const counts = { select: 0, content: 0 };
  const spec: InjectedContextSpec = {
    customType: CONTEXT_TYPE,
    flavors: {
      [MARKER]: () => {
        counts.content += 1;
        return `${MARKER}\ninjected content`;
      },
    },
    select: () => {
      counts.select += 1;
      return MARKER;
    },
    ...overrides,
  };
  return { spec, counts };
}

/** The `context` hook over a fixed message list; returns the surviving messages. */
async function retained(
  strip: Hook,
  messages: Record<string, unknown>[],
  ctx: ExtensionContext = ctxOver(),
): Promise<Record<string, unknown>[]> {
  const result = (await strip({ messages }, ctx)) as { messages: Record<string, unknown>[] };
  return result.messages;
}

/** Persist a prior hidden copy the way Pi persists a `before_agent_start` injection. */
function priorCopy(manager: SessionManager, marker = MARKER): string {
  return manager.appendCustomMessageEntry(CONTEXT_TYPE, `${marker}\nprior copy`, false);
}

function assistantTurn(manager: SessionManager, text: string): string {
  return manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text }],
    api: "test",
    provider: "test",
    model: "test",
    usage: {},
    stopReason: "stop",
    timestamp: 1,
  } as never);
}

const EMPTY_EVENT = { prompt: "" };

test("injects when eligible and no live marker (display:false, the owned customType)", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const result = (await inject(EMPTY_EVENT, ctxOver())) as {
    message: { customType: string; content: string; display: boolean };
  };
  assert.equal(result.message.customType, CONTEXT_TYPE);
  assert.ok(result.message.content.includes(MARKER));
  assert.equal(result.message.display, false);
  assert.equal(counts.content, 1, "the content thunk ran exactly once");
});

test("a live owned copy in Pi's projection suppresses — the content thunk is never invoked", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const manager = SessionManager.inMemory("/nowhere");
  priorCopy(manager);
  const result = await inject(EMPTY_EVENT, ctxOver(manager));
  assert.equal(result, undefined, "no re-injection over a live copy");
  assert.equal(counts.select, 1, "eligibility still consulted");
  assert.equal(counts.content, 0, "the content thunk never ran on the dedup-suppressed turn");
});

test("re-injects when compaction summarized the prior copy out of context", async () => {
  const { spec } = countingSpec();
  const { inject } = hooksFor(spec);
  const manager = SessionManager.inMemory("/nowhere");
  priorCopy(manager);
  const kept = assistantTurn(manager, "recent work");
  manager.appendCompaction("summary without the marker", kept, 100);
  const result = (await inject(EMPTY_EVENT, ctxOver(manager))) as { message?: unknown } | undefined;
  assert.ok(result?.message !== undefined, "a copy outside live context must not suppress");
});

test("a compaction summary QUOTING the marker does not suppress", async () => {
  const { spec } = countingSpec();
  const { inject } = hooksFor(spec);
  const manager = SessionManager.inMemory("/nowhere");
  const kept = assistantTurn(manager, "recent work");
  manager.appendCompaction(`quoting ${MARKER} is not a live copy`, kept, 100);
  const result = (await inject(EMPTY_EVENT, ctxOver(manager))) as { message?: unknown } | undefined;
  assert.ok(result?.message !== undefined, "a quoting summary is not a live custom block");
});

test("a live retained copy (kept across compaction) still dedups", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const manager = SessionManager.inMemory("/nowhere");
  const copy = priorCopy(manager);
  assistantTurn(manager, "recent work");
  manager.appendCompaction("summary", copy, 100);
  const result = await inject(EMPTY_EVENT, ctxOver(manager));
  assert.equal(result, undefined, "a retained live copy still suppresses");
  assert.equal(counts.content, 0);
});

test("no injection when select returns null (ineligible/defer) — and no projection read", async () => {
  const { spec, counts } = countingSpec({ select: () => null });
  const { inject } = hooksFor(spec);
  const reads: string[] = [];
  const ctx = ctxFrom({
    getBranch: () => [],
    buildContextEntries: () => {
      reads.push("projection");
      return [];
    },
  });
  assert.equal(await inject(EMPTY_EVENT, ctx), undefined);
  assert.equal(counts.content, 0);
  assert.deepEqual(reads, [], "an ineligible turn never reads Pi's projection");
});

test("an off-table select key (a widened K) names no flavor — never injects", async () => {
  const { spec, counts } = countingSpec({ select: () => "[NOT A FLAVOR]" });
  const { inject } = hooksFor(spec);
  assert.equal(await inject(EMPTY_EVENT, ctxOver()), undefined);
  assert.equal(counts.content, 0);
});

test("the submitting prompt carrying the SELECTED marker suppresses (cold delivery before persistence) without a projection read", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const reads: string[] = [];
  const ctx = ctxFrom({
    getBranch: () => [],
    buildContextEntries: () => {
      reads.push("projection");
      return [];
    },
  });
  const result = await inject(
    { prompt: `Do the work.\n\n${MARKER}\nseeded by the cold door` },
    ctx,
  );
  assert.equal(result, undefined, "the cold seed is the delivery on the launch turn");
  assert.equal(counts.content, 0);
  assert.deepEqual(reads, [], "the prompt check settles the turn before any projection read");
});

test("the submitting prompt carrying ANOTHER flavor's marker does not suppress the selected flavor", async () => {
  const { spec, counts } = countingSpec({
    flavors: {
      [MARKER]: () => {
        counts.content += 1;
        return `${MARKER}\nselected flavor`;
      },
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
  });
  const { inject } = hooksFor(spec);
  const result = (await inject({ prompt: `${SECOND_MARKER} rides the prompt` }, ctxOver())) as {
    message?: { content: string };
  };
  assert.ok(result?.message !== undefined, "the selected flavor still injects");
  assert.ok(result.message.content.includes(MARKER));
  assert.equal(counts.content, 1);
});

test("a THROWING branch read: injection short-circuits (no select call, no throw); retention fails closed and removes the owned copy", async () => {
  const { spec, counts } = countingSpec();
  const { inject, strip } = hooksFor(spec);
  const reads: string[] = [];
  const ctx = ctxFrom({
    getBranch: () => {
      throw new Error("adversarial branch read");
    },
    buildContextEntries: () => {
      reads.push("projection");
      return [];
    },
  });

  assert.equal(await inject(EMPTY_EVENT, ctx), undefined, "the injection stays inert — no throw");
  assert.equal(counts.select, 0, "select is never consulted on a failed read");
  assert.deepEqual(reads, [], "the projection is never read after a failed branch read");

  const surviving = await retained(
    strip,
    [
      { customType: CONTEXT_TYPE, content: `${MARKER}\nstale` },
      { role: "user", content: "a normal message" },
    ],
    ctx,
  );
  assert.equal(counts.select, 0, "eligibility cannot be established — select is not consulted");
  assert.deepEqual(
    surviving,
    [{ role: "user", content: "a normal message" }],
    "the owned copy is removed; the user turn survives",
  );
  assert.deepEqual(reads, [], "retention never reads the projection either");
});

test("a THROWING selector on the context event fails closed: the owned copy is removed, nothing else is touched", async () => {
  const { spec } = countingSpec({
    select: () => {
      throw new Error("adversarial selector");
    },
  });
  const { strip } = hooksFor(spec);
  const surviving = await retained(strip, [
    { customType: CONTEXT_TYPE, content: `${MARKER}\nstale` },
    { customType: "perk:other-feature", content: `${MARKER}\nanother feature quoting the marker` },
    { role: "user", content: `${MARKER} quoted by the human` },
  ]);
  assert.deepEqual(surviving, [
    { customType: "perk:other-feature", content: `${MARKER}\nanother feature quoting the marker` },
    { role: "user", content: `${MARKER} quoted by the human` },
  ]);
});

test("a THROWING projection read: guarded return — nothing constructed, nothing injected, no throw", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const ctx = ctxFrom({
    getBranch: () => [],
    buildContextEntries: () => {
      throw new Error("adversarial projection read");
    },
  });
  assert.equal(await inject(EMPTY_EVENT, ctx), undefined, "no guessed copy on a failed read");
  assert.equal(counts.select, 1, "eligibility was consulted (the failure is downstream)");
  assert.equal(counts.content, 0, "the content thunk never ran");
});

/** Every non-owned message shape a retention pass must hand back byte-for-byte. */
const PRESERVED_INPUT: Record<string, unknown>[] = [
  { role: "user", content: `${MARKER} leaked into a user turn` },
  { role: "user", content: `${SECOND_MARKER} the second owned marker in a user string` },
  { role: "user", content: [{ type: "text", text: `text-part carrying ${SECOND_MARKER}` }] },
  {
    role: "user",
    content: [
      {
        type: "text",
        text: `<untrusted_draft>\n${MARKER}\nquoted inside a draft\n</untrusted_draft>`,
      },
      { type: "text", text: "and a trailing part" },
    ],
  },
  { role: "user", content: `Do the work.\n\n${MARKER}\nhistorical cold seed` },
  { role: "user", content: [{ type: "text", text: "an unrelated text part" }] },
  { role: "user", content: "a normal message" },
  { role: "assistant", content: `the assistant quoting ${MARKER} stays` },
  { role: "toolResult", content: [{ type: "text", text: `tool output with ${MARKER}` }] },
  { customType: "perk:other-feature", content: `${MARKER}\nanother feature's custom copy` },
  { customType: "perk:mode-context", content: "[READ-ONLY MODE]\nthe gate's own guidance" },
];

test("retention on null selection: removes EVERY owned copy (all flavors); preserves user input, other roles and other features byte-for-byte", async () => {
  const { spec } = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
    select: () => null,
  });
  const { strip } = hooksFor(spec);
  const input = structuredClone(PRESERVED_INPUT);
  const surviving = await retained(strip, [
    { customType: CONTEXT_TYPE, content: `${MARKER}\nstale` },
    ...input.slice(0, 3),
    { customType: CONTEXT_TYPE, content: `${SECOND_MARKER}\nstale sibling` },
    ...input.slice(3),
    {
      customType: CONTEXT_TYPE,
      content: [{ type: "text", text: `${MARKER}\nstale text-part copy` }],
    },
  ]);
  assert.deepEqual(surviving, PRESERVED_INPUT, "only the owned copies are gone; order intact");
});

test("retention on a selected flavor: keeps that flavor's owned copies, removes obsolete sibling flavors, touches nothing else", async () => {
  const { spec } = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
    select: () => SECOND_MARKER,
  });
  const { strip } = hooksFor(spec);
  const selectedCopy = { customType: CONTEXT_TYPE, content: `${SECOND_MARKER}\nselected flavor` };
  const selectedTextPart = {
    customType: CONTEXT_TYPE,
    content: [{ type: "text", text: `${SECOND_MARKER}\nselected as a text part` }],
  };
  const surviving = await retained(strip, [
    { customType: CONTEXT_TYPE, content: `${MARKER}\nobsolete plan-flavor copy` },
    selectedCopy,
    ...structuredClone(PRESERVED_INPUT),
    { customType: CONTEXT_TYPE, content: "an owned copy carrying NO marker" },
    selectedTextPart,
  ]);
  assert.deepEqual(surviving, [selectedCopy, ...PRESERVED_INPUT, selectedTextPart]);
});

test("retention on an off-table select key (a widened K): removes the owned copies — never retains on a marker the table does not own", async () => {
  const { spec } = countingSpec({ select: () => "[NOT A FLAVOR]" });
  const { strip } = hooksFor(spec);
  const surviving = await retained(strip, [
    { customType: CONTEXT_TYPE, content: `${MARKER}\nowned` },
    { customType: CONTEXT_TYPE, content: "[NOT A FLAVOR]\nowned, tagged with the stray key" },
    { role: "user", content: "[NOT A FLAVOR] typed by the human" },
  ]);
  assert.deepEqual(surviving, [{ role: "user", content: "[NOT A FLAVOR] typed by the human" }]);
});

test("retention reads the FULL branch through select (compaction-independent), never the projection", async () => {
  const seen: (readonly BranchEntry[])[] = [];
  const { spec } = countingSpec({
    select: (_ctx, branch) => {
      seen.push(branch);
      return MARKER;
    },
  });
  const { strip } = hooksFor(spec);
  const reads: string[] = [];
  const branch = [
    { type: "custom", customType: "perk:workflow-state", data: { mode: "read-only" } },
  ];
  const ctx = ctxFrom({
    getBranch: () => branch,
    buildContextEntries: () => {
      reads.push("projection");
      return [];
    },
  });
  const kept = { customType: CONTEXT_TYPE, content: `${MARKER}\nstill relevant` };
  assert.deepEqual(await retained(strip, [kept], ctx), [kept], "a selected copy is retained");
  assert.deepEqual(seen, [branch], "select saw the full branch");
  assert.deepEqual(reads, [], "retention never reads the projection");
});

// --- composition smoke: the REAL registered extension rides the projection leaf -----------------

test("composition: the bound extension injects, dedups on the live copy, re-injects off it, and keeps it on reload", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.inMemory(cwd),
    env: { PERK_RUN_ID: "01RID" },
  });
  try {
    const manager = h.session.sessionManager;
    const expected = planAuthoringContextContent(undefined);
    const planContexts = (injected: { customType?: string; content?: unknown }[]) =>
      injected.filter((m) => m.customType === PLAN_CONTEXT_TYPE).map((m) => m.content);

    // A non-user checkpoint BEFORE any delivery (the last claim-time state entry): navigating
    // here later lands on a leaf with no plan context in Pi's projection.
    const beforeDelivery = manager.getLeafId();
    assert.ok(beforeDelivery !== null);

    // Turn 1: the plan-authoring context is injected with the exact rendered bytes.
    assert.deepEqual(planContexts(await h.emitBeforeAgentStart()), [expected]);
    // The harness does not persist the returned custom — append it the way Pi would.
    manager.appendCustomMessageEntry(PLAN_CONTEXT_TYPE, expected, false);
    const afterDelivery = h.session.sessionManager.appendMessage({
      role: "assistant",
      content: [{ type: "text", text: "planning work after the delivery" }],
      api: "test",
      provider: "test",
      model: "test",
      usage: {},
      stopReason: "stop",
      timestamp: 1,
    } as never);

    // Turn 2: the live copy suppresses.
    assert.deepEqual(planContexts(await h.emitBeforeAgentStart()), []);

    // Navigate to the pre-delivery checkpoint (the guidance is MISSING there): re-inject.
    await h.navigateTo(beforeDelivery);
    assert.equal(h.workflowState().mode, "read-only", "the rebuilt gate still holds here");
    assert.deepEqual(planContexts(await h.emitBeforeAgentStart()), [expected]);

    // Back onto the live copy's branch: suppressed again.
    await h.navigateTo(afterDelivery);
    assert.deepEqual(planContexts(await h.emitBeforeAgentStart()), []);

    // Reload onto the same leaf: still suppressed (no process-global latch involved either way).
    await h.reload();
    assert.deepEqual(planContexts(await h.emitBeforeAgentStart()), []);

    // The `context` payload survives intact while live: the hidden copy AND the user turn.
    const surviving = await h.emitContext([
      { customType: PLAN_CONTEXT_TYPE, content: expected },
      { role: "user", content: "keep drafting" },
    ]);
    assert.deepEqual(surviving, [
      { customType: PLAN_CONTEXT_TYPE, content: expected },
      { role: "user", content: "keep drafting" },
    ]);
    assert.ok(expected.includes(PLAN_MARKER), "the rendered bytes carry the dedup key");
  } finally {
    h.dispose();
  }
});
