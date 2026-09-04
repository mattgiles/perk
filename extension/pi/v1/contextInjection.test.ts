// The shared context-injection mechanism matrix — owned ONCE here, for every
// `installInjectedContext` caller (gist, plan, objective-authoring, plannotator, tombell): the
// active-window dedup scan, the scan-before-construct content thunk, the guarded branch read's
// asymmetric failure semantics, and the stale-strip filter shape. Drives the installer through a
// `pi.on`-recorder fake + structural ctx (no harness); feature policy (eligibility, flavor
// selection, content identity) stays pinned in each feature's own suite.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { BranchEntry } from "../../substrate/workflowState.ts";
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

/** A structural ctx whose branch read returns (or throws) as directed. */
function ctxOver(getBranch: () => unknown[]): ExtensionContext {
  return { cwd: "/nowhere", sessionManager: { getBranch } } as unknown as ExtensionContext;
}

/** A minimal always-eligible spec with an invocation-counting content thunk. */
function countingSpec(overrides: Partial<InjectedContextSpec> = {}): {
  spec: InjectedContextSpec;
  counts: { select: number; content: number };
} {
  const counts = { select: 0, content: 0 };
  const spec: InjectedContextSpec = {
    customType: CONTEXT_TYPE,
    markers: [MARKER],
    select: () => {
      counts.select += 1;
      return {
        marker: MARKER,
        content: () => {
          counts.content += 1;
          return `${MARKER}\ninjected content`;
        },
      };
    },
    live: () => false,
    ...overrides,
  };
  return { spec, counts };
}

function priorCopy(): BranchEntry {
  return { type: "custom", customType: CONTEXT_TYPE, data: { content: `${MARKER}\nprior copy` } };
}

test("injects when eligible and no live marker (display:false, the owned customType)", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const result = (await inject({}, ctxOver(() => []))) as {
    message: { customType: string; content: string; display: boolean };
  };
  assert.equal(result.message.customType, CONTEXT_TYPE);
  assert.ok(result.message.content.includes(MARKER));
  assert.equal(result.message.display, false);
  assert.equal(counts.content, 1, "the content thunk ran exactly once");
});

test("a live marker in the active window suppresses — the content thunk is never invoked", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const result = await inject({}, ctxOver(() => [priorCopy()]));
  assert.equal(result, undefined, "no re-injection over a live copy");
  assert.equal(counts.select, 1, "eligibility still consulted");
  assert.equal(counts.content, 0, "the content thunk never ran on the dedup-suppressed turn");
});

test("re-injects when the marker sits only BEFORE the compaction cutoff", async () => {
  const { spec } = countingSpec();
  const { inject } = hooksFor(spec);
  const branch = [
    priorCopy(),
    { type: "compaction" } as BranchEntry,
    { type: "assistant" } as BranchEntry,
  ];
  const result = (await inject({}, ctxOver(() => branch))) as { message?: unknown } | undefined;
  assert.ok(result?.message !== undefined, "a copy outside the active window must not suppress");
});

test("a compaction summary QUOTING the marker does not suppress", async () => {
  const { spec } = countingSpec();
  const { inject } = hooksFor(spec);
  const branch = [
    { type: "compaction", data: { summary: `quoting ${MARKER} is not a live copy` } } as BranchEntry,
  ];
  const result = (await inject({}, ctxOver(() => branch))) as { message?: unknown } | undefined;
  assert.ok(result?.message !== undefined, "a quoting summary is not a live custom block");
});

test("a live retained copy (kept across compaction via firstKeptEntryId) still dedups", async () => {
  const { spec, counts } = countingSpec();
  const { inject } = hooksFor(spec);
  const branch = [
    { ...priorCopy(), id: "e1" } as BranchEntry,
    { type: "assistant", id: "e2" } as BranchEntry,
    { type: "compaction", firstKeptEntryId: "e1" } as BranchEntry,
  ];
  const result = await inject({}, ctxOver(() => branch));
  assert.equal(result, undefined, "a retained live copy still suppresses");
  assert.equal(counts.content, 0);
});

test("no injection when select returns null (ineligible/defer)", async () => {
  const { spec, counts } = countingSpec({ select: () => null });
  const { inject } = hooksFor(spec);
  const result = await inject({}, ctxOver(() => []));
  assert.equal(result, undefined);
  assert.equal(counts.content, 0);
});

test("a THROWING branch read: injection short-circuits (no select call, no throw); the strip still fires over []", async () => {
  const { spec, counts } = countingSpec();
  const liveBranches: (readonly BranchEntry[])[] = [];
  spec.live = (_ctx, branch) => {
    liveBranches.push(branch);
    return false;
  };
  const { inject, strip } = hooksFor(spec);
  const ctx = ctxOver(() => {
    throw new Error("adversarial branch read");
  });

  assert.equal(await inject({}, ctx), undefined, "the injection stays inert — no throw");
  assert.equal(counts.select, 0, "select is never consulted on a failed read");

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
});

test("strip: drops the owned customType and any user turn carrying ANY owned marker", async () => {
  const { spec } = countingSpec({ markers: [MARKER, SECOND_MARKER] });
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
    ctxOver(() => []),
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
    ctxOver(() => []),
  )) as { messages: unknown[] };
  assert.equal(result.messages.length, 2, "non-user roles are never marker-stripped");
});

test("strip: keeps everything while live (the hook yields no filter)", async () => {
  const { spec } = countingSpec({ live: () => true });
  const { strip } = hooksFor(spec);
  const result = await strip(
    { messages: [{ customType: CONTEXT_TYPE, content: `${MARKER}\nstill relevant` }] },
    ctxOver(() => []),
  );
  assert.equal(result, undefined, "a live context is never stripped");
});
