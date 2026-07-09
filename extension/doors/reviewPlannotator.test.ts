// Tests for the warm `open_plannotator_review` tool (offline). The pure decode is pinned
// directly; the tool core runs with structural fakes — a fake event bus stands in for
// plannotator (the plannotatorHandoff.test.ts idiom), an injected port picker/probe/clock makes
// the readiness poll deterministic, and a recording sendUserMessage pins the respond routing.
// The pure bridge/respondMessage substrate is pinned in plannotatorHandoff.test.ts; the
// registration path (bad_input through the harness) rides review.test.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import { PLANNOTATOR_REVIEW_COMMAND } from "./plannotatorHandoff.ts";
import {
  decodeOpenReviewParams,
  type OpenReviewCtx,
  type OpenReviewPi,
  openPlannotatorReview,
} from "./reviewPlannotator.ts";

// --- compile-time satisfaction: the structural slices can never drift from the SDK ------------

const _p: OpenReviewPi = {} as ExtensionAPI;
void _p;
const _c: OpenReviewCtx = {} as ExtensionContext;
void _c;

// --- decodeOpenReviewParams --------------------------------------------------------------------

test("decodeOpenReviewParams accepts { pr: int, pr_url: non-empty string }", () => {
  assert.deepEqual(decodeOpenReviewParams({ pr: 77, pr_url: "https://gh/o/r/pull/77" }), {
    pr: 77,
    pr_url: "https://gh/o/r/pull/77",
  });
});

test("decodeOpenReviewParams rejects any malformed field (whole refusal)", () => {
  assert.equal(decodeOpenReviewParams(null), null);
  assert.equal(decodeOpenReviewParams("x"), null);
  assert.equal(decodeOpenReviewParams({}), null);
  assert.equal(decodeOpenReviewParams({ pr: 77 }), null);
  assert.equal(decodeOpenReviewParams({ pr_url: "u" }), null);
  assert.equal(decodeOpenReviewParams({ pr: 1.5, pr_url: "u" }), null);
  assert.equal(decodeOpenReviewParams({ pr: "77", pr_url: "u" }), null);
  assert.equal(decodeOpenReviewParams({ pr: 77, pr_url: "" }), null);
  assert.equal(decodeOpenReviewParams({ pr: 77, pr_url: 9 }), null);
});

// --- fakes --------------------------------------------------------------------------------------

/** The plannotator:request envelope the fake code-review listener receives. */
interface CodeReviewEnvelope {
  requestId: string;
  action: string;
  payload: Record<string, unknown>;
  respond: (response: unknown) => void;
}

/** A minimal in-memory event bus (the fake `pi.events`). */
function fakeBus(): PlannotatorBus & { handlers: Map<string, ((data: unknown) => void)[]> } {
  const handlers = new Map<string, ((data: unknown) => void)[]>();
  return {
    handlers,
    emit(channel, data) {
      for (const h of handlers.get(channel) ?? []) h(data);
    },
    on(channel, handler) {
      handlers.set(channel, [...(handlers.get(channel) ?? []), handler]);
    },
  };
}

interface FakePi {
  pi: OpenReviewPi;
  bus: ReturnType<typeof fakeBus>;
  sent: { message: string; options?: { deliverAs?: string } }[];
}

function fakePi(opts?: { plannotator?: boolean }): FakePi {
  const bus = fakeBus();
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  const commands = opts?.plannotator === false ? [] : [{ name: PLANNOTATOR_REVIEW_COMMAND }];
  return {
    bus,
    sent,
    pi: {
      events: bus,
      getCommands: () => commands as ReturnType<ExtensionAPI["getCommands"]>,
      sendUserMessage: (message: string, options?: { deliverAs?: "steer" | "followUp" }) => {
        sent.push(options === undefined ? { message } : { message, options });
      },
    },
  };
}

function fakeCtx(opts?: { hasUI?: boolean; idle?: boolean }): OpenReviewCtx {
  return {
    cwd: "/repo",
    hasUI: opts?.hasUI ?? true,
    signal: undefined,
    isIdle: () => opts?.idle ?? true,
    ui: { notify: () => {} },
  };
}

/** Let queued microtasks (the background respond routing) run. */
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

const PARAMS = { pr: 77, pr_url: "https://gh/o/r/pull/77" };

// --- the gate ladder ----------------------------------------------------------------------------

test("gate: plannotator absent → plannotator_missing, nothing executed", async () => {
  const { pi, bus } = fakePi({ plannotator: false });
  let picked = false;
  const result = await openPlannotatorReview(pi, fakeCtx(), PARAMS, {
    pickFreePort: () => {
      picked = true;
      return Promise.resolve(45001);
    },
  });
  assert.equal(result.details.ok, false);
  if (!result.details.ok) assert.equal(result.details.error_type, "plannotator_missing");
  assert.match(result.content[0]?.text ?? "", /run `perk init`, then restart pi/);
  assert.equal(picked, false, "no port picked");
  assert.equal(bus.handlers.size, 0, "nothing emitted");
});

test("gate: headless → headless (the browser surface is constitutive)", async () => {
  const { pi } = fakePi();
  const result = await openPlannotatorReview(pi, fakeCtx({ hasUI: false }), PARAMS, {
    pickFreePort: () => Promise.resolve(45001),
  });
  assert.equal(result.details.ok, false);
  if (!result.details.ok) assert.equal(result.details.error_type, "headless");
});

// --- the happy path -----------------------------------------------------------------------------

test("happy path: env preset while probing, bridge payload mirrors PR mode, ok carries url/port", async () => {
  const { pi, bus } = fakePi();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope; // no respond — the review is still open
  });
  const envDuringProbe: (string | undefined)[] = [];
  const prior = process.env.PLANNOTATOR_PORT;
  process.env.PLANNOTATOR_PORT = "4242"; // the prior-SET arm: restored, not deleted
  try {
    const result = await openPlannotatorReview(pi, fakeCtx(), PARAMS, {
      pickFreePort: () => Promise.resolve(45001),
      probe: (url) => {
        envDuringProbe.push(process.env.PLANNOTATOR_PORT);
        assert.equal(url, "http://127.0.0.1:45001");
        return Promise.resolve(envDuringProbe.length >= 2); // ready on the second attempt
      },
      intervalMs: 1,
      budgetMs: 100,
      sleep: () => Promise.resolve(),
    });
    assert.equal(result.details.ok, true);
    if (result.details.ok) {
      assert.equal(result.details.url, "http://127.0.0.1:45001");
      assert.equal(result.details.port, 45001);
    }
    assert.match(result.content[0]?.text ?? "", /api\/external-annotations/);
    assert.match(result.content[0]?.text ?? "", /arrive in this session as a message/);
    assert.match(result.content[0]?.text ?? "", /perk composes nothing by default/);
    assert.deepEqual(envDuringProbe, ["45001", "45001"], "env preset for plannotator's bind");
    assert.equal(process.env.PLANNOTATOR_PORT, "4242", "prior value restored after the poll");
    assert.equal(seen?.action, "code-review");
    // The payload mirrors the pinned PR-mode envelope byte-for-byte: { prUrl, cwd } only.
    assert.deepEqual(seen?.payload, { cwd: "/repo", prUrl: "https://gh/o/r/pull/77" });
  } finally {
    if (prior === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = prior;
  }
});

test("server_not_ready: probe never true → fail, env RESTORED-BY-DELETE (prior-unset arm)", async () => {
  const { pi } = fakePi();
  const prior = process.env.PLANNOTATOR_PORT;
  delete process.env.PLANNOTATOR_PORT;
  try {
    const result = await openPlannotatorReview(pi, fakeCtx(), PARAMS, {
      pickFreePort: () => Promise.resolve(45002),
      probe: () => Promise.resolve(false),
      intervalMs: 1,
      budgetMs: 3,
      sleep: () => Promise.resolve(),
    });
    assert.equal(result.details.ok, false);
    if (!result.details.ok) assert.equal(result.details.error_type, "server_not_ready");
    assert.match(result.content[0]?.text ?? "", /degrade in-session/);
    assert.match(result.content[0]?.text ?? "", /submit_pr_review/);
    assert.equal("PLANNOTATOR_PORT" in process.env, false, "prior-unset ⇒ deleted");
  } finally {
    if (prior !== undefined) process.env.PLANNOTATOR_PORT = prior;
  }
});

test("early bridge settle stops the poll (an error respond means the server never comes)", async () => {
  const { pi, bus } = fakePi();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({ status: "error", error: "boom" });
  });
  let probes = 0;
  const result = await openPlannotatorReview(pi, fakeCtx(), PARAMS, {
    pickFreePort: () => Promise.resolve(45003),
    probe: () => {
      probes++;
      return Promise.resolve(false);
    },
    intervalMs: 1,
    budgetMs: 1000, // 1000 attempts available — the settle must stop the loop, not the budget
    sleep: () => Promise.resolve(),
  });
  assert.equal(result.details.ok, false);
  if (!result.details.ok) assert.equal(result.details.error_type, "server_not_ready");
  assert.equal(probes, 1, "the poll stopped as soon as the bridge settled");
});

// --- respond routing (idle vs followUp; error → report, no injection) ---------------------------

async function openAndRespond(opts: {
  idle: boolean;
  respond: unknown;
}): Promise<{ sent: FakePi["sent"]; notifies: string[] }> {
  const { pi, bus, sent } = fakePi();
  let envelope: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    envelope = data as CodeReviewEnvelope;
  });
  const notifies: string[] = [];
  const ctx = fakeCtx({ idle: opts.idle });
  ctx.ui = { notify: (m: string) => notifies.push(m) };
  const result = await openPlannotatorReview(pi, ctx, PARAMS, {
    pickFreePort: () => Promise.resolve(45004),
    probe: () => Promise.resolve(true),
    intervalMs: 1,
    budgetMs: 10,
    sleep: () => Promise.resolve(),
  });
  assert.equal(result.details.ok, true);
  envelope?.respond(opts.respond);
  await flush();
  return { sent, notifies };
}

test("routing: an idle session gets a plain injection; streaming gets deliverAs followUp", async () => {
  const respond = {
    status: "handled",
    result: { approved: false, feedback: "notes", annotations: [] },
  };
  const idle = await openAndRespond({ idle: true, respond });
  assert.equal(idle.sent.length, 1);
  assert.equal(idle.sent[0]?.message, "notes");
  assert.equal(idle.sent[0]?.options, undefined);

  const busy = await openAndRespond({ idle: false, respond });
  assert.equal(busy.sent.length, 1);
  assert.deepEqual(busy.sent[0]?.options, { deliverAs: "followUp" });
});

test("routing: an unavailable respond reports the error and injects nothing", async () => {
  const { sent, notifies } = await openAndRespond({
    idle: true,
    respond: { status: "unavailable", error: "no browser" },
  });
  assert.equal(sent.length, 0, "nothing injected");
  assert.ok(
    notifies.some((n) => n.includes("unavailable: no browser")),
    "the degrade is loud",
  );
});
