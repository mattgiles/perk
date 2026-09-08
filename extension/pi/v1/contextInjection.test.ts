// The shared context-injection mechanism's DISTINCT policies — owned ONCE here, for every
// `installInjectedContext` caller (gist, plan, objective-authoring, plannotator, tombell): the
// scan-before-construct content thunk, the two guarded reads' asymmetric failure semantics, the
// submitting-prompt check, the stale-strip filter shape, and one registered-extension composition
// smoke. Drives the installer through a `pi.on`-recorder fake over REAL `SessionManager` sources
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
    live: () => false,
    ...overrides,
  };
  return { spec, counts };
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

test("a THROWING branch read: injection short-circuits (no select call, no throw); the strip still fires over []", async () => {
  const { spec, counts } = countingSpec();
  const liveBranches: (readonly BranchEntry[])[] = [];
  spec.live = (_ctx, branch) => {
    liveBranches.push(branch);
    return false;
  };
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

  const result = (await strip(
    {
      messages: [
        { customType: CONTEXT_TYPE, content: `${MARKER}\nstale` },
        { role: "user", content: "a normal message" },
      ],
    },
    ctx,
  )) as { messages: { customType?: string }[] };
  assert.deepEqual(liveBranches, [[]], "live sees the degraded empty branch");
  assert.equal(
    result.messages.some((m) => m.customType === CONTEXT_TYPE),
    false,
    "the stale custom message is still stripped",
  );
  assert.equal(result.messages.length, 1, "the normal message survives");
  assert.deepEqual(reads, [], "the strip never reads the projection either");
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

test("strip: drops the owned customType and any user turn carrying ANY owned marker", async () => {
  const { spec } = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
  });
  const { strip } = hooksFor(spec);
  const result = (await strip(
    {
      messages: [
        { customType: CONTEXT_TYPE, content: `${MARKER}\nstale` },
        { role: "user", content: `${MARKER} leaked into a user turn` },
        { role: "user", content: `${SECOND_MARKER} the second owned marker leaks too` },
        { role: "user", content: [{ type: "text", text: `text-part carrying ${SECOND_MARKER}` }] },
        { role: "user", content: [{ type: "text", text: "an unrelated text part" }] },
        { role: "user", content: "a normal message" },
      ],
    },
    ctxOver(),
  )) as { messages: { role?: string; customType?: string; content?: unknown }[] };
  assert.equal(result.messages.length, 2, "only the unrelated user turns survive");
  assert.ok(result.messages.every((m) => m.customType !== CONTEXT_TYPE));
  assert.ok(
    result.messages.every((m) => !JSON.stringify(m.content).includes("[TEST CONTEXT")),
    "no owned marker survives on a user turn",
  );
});

test("strip: keeps non-user roles even when they quote a marker", async () => {
  const { spec } = countingSpec();
  const { strip } = hooksFor(spec);
  const result = (await strip(
    {
      messages: [
        { role: "assistant", content: `the assistant quoting ${MARKER} stays` },
        { role: "toolResult", content: [{ type: "text", text: `tool output with ${MARKER}` }] },
      ],
    },
    ctxOver(),
  )) as { messages: unknown[] };
  assert.equal(result.messages.length, 2, "non-user roles are never marker-stripped");
});

test("strip: keeps everything while live (the hook yields no filter)", async () => {
  const { spec } = countingSpec({ live: () => true });
  const { strip } = hooksFor(spec);
  const result = await strip(
    { messages: [{ customType: CONTEXT_TYPE, content: `${MARKER}\nstill relevant` }] },
    ctxOver(),
  );
  assert.equal(result, undefined, "a live context is never stripped");
});

test("strip: while live, a copy of a NON-selected flavor is stale — stripped alongside user turns carrying it; the selected flavor's copy and unrelated turns survive", async () => {
  const { spec } = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
    select: () => SECOND_MARKER,
    live: () => true,
  });
  const { strip } = hooksFor(spec);
  const result = (await strip(
    {
      messages: [
        { customType: CONTEXT_TYPE, content: `${MARKER}\nthe previous flavor's copy` },
        { customType: CONTEXT_TYPE, content: `${SECOND_MARKER}\nthe selected flavor's copy` },
        { role: "user", content: `${MARKER} leaked into a user turn` },
        { role: "user", content: [{ type: "text", text: `${SECOND_MARKER} selected, on a turn` }] },
        { role: "assistant", content: `the assistant quoting ${MARKER} stays` },
        { role: "user", content: "a normal message" },
      ],
    },
    ctxOver(),
  )) as { messages: { role?: string; customType?: string; content?: unknown }[] };
  assert.deepEqual(
    result.messages.map((m) => m.customType ?? m.role),
    [CONTEXT_TYPE, "user", "assistant", "user"],
    "the stale flavor's copy and its leaked user turn are gone; everything else survives",
  );
  assert.deepEqual(
    result.messages.map((m) => JSON.stringify(m.content).includes(MARKER)),
    [false, false, true, false],
    "the stale marker survives only on the non-user (assistant) quote",
  );
  assert.ok(
    String(result.messages[0]?.content).startsWith(SECOND_MARKER),
    "exactly the selected flavor's owned copy survives",
  );
});

test("strip: while live with NOTHING selected this turn, or a single-flavor spec, the hook yields no filter", async () => {
  const idle = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
    select: () => null,
    live: () => true,
  });
  const messages = [{ customType: CONTEXT_TYPE, content: `${MARKER}\na prior copy` }];
  assert.equal(await hooksFor(idle.spec).strip({ messages }, ctxOver()), undefined);
  const single = countingSpec({ live: () => true });
  assert.equal(await hooksFor(single.spec).strip({ messages }, ctxOver()), undefined);
  // A live multi-flavor spec whose messages carry no stale flavor yields no filter either.
  const clean = countingSpec({
    flavors: {
      [MARKER]: () => `${MARKER}\ninjected content`,
      [SECOND_MARKER]: () => `${SECOND_MARKER}\nsecond flavor`,
    },
    select: () => MARKER,
    live: () => true,
  });
  assert.equal(await hooksFor(clean.spec).strip({ messages }, ctxOver()), undefined);
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
