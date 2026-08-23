// The shared plannotator browser-review substrate (offline): the pure event-bus bridge to
// plannotator's published `code-review` action, the outcome mapping (handled / unavailable), the
// target resolution (PR vs the no-PR local since-base fallback), the presence helper, the flipped
// PR-mode respond mapping, and the composable browser-open core in both flavors
// (`startPlannotatorBrowser` / `startPlannotatorPlanReview` — port preset/restore + readiness
// poll with injected port/probe/clock). Fully offline — the fake plannotator is a test listener
// on an event bus that calls `respond(...)`. See plannotatorHandoff.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import {
  CODE_REVIEW_READINESS_PROBE_PATH,
  type CodeReviewOutcome,
  LOCAL_REVIEW_DIFF_TYPE,
  PLAN_REVIEW_READINESS_PROBE_PATH,
  PLANNOTATOR_REVIEW_COMMAND,
  plannotatorPresent,
  requestPlannotatorCodeReview,
  resolveReviewTarget,
  respondMessage,
  routeBrowserRespond,
  routePrReviewOutcome,
  stackRespondMessage,
  startPlannotatorBrowser,
  startPlannotatorPlanReview,
} from "./plannotatorHandoff.ts";

/** A minimal in-memory event bus (the fake `pi.events` for the pure bridge tests). */
function fakeBus(): PlannotatorBus & { handlers: Map<string, ((data: unknown) => void)[]> } {
  const handlers = new Map<string, ((data: unknown) => void)[]>();
  return {
    handlers,
    emit(channel, data) {
      for (const h of handlers.get(channel) ?? []) h(data);
    },
    on(channel, handler) {
      handlers.set(channel, [...(handlers.get(channel) ?? []), handler]);
      return () => {
        handlers.set(
          channel,
          (handlers.get(channel) ?? []).filter((h) => h !== handler),
        );
      };
    },
  };
}

/** The plannotator:request envelope the fake code-review listener receives (pinned, see header). */
interface CodeReviewEnvelope {
  requestId: string;
  action: string;
  payload: { prUrl?: string; cwd: string; diffType?: string; defaultBranch?: string };
  respond: (response: unknown) => void;
}

test("bridge: code-review request carries action + prUrl; a handled reply maps to the outcome", async () => {
  const bus = fakeBus();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope;
    seen.respond({
      status: "handled",
      result: { approved: false, feedback: "fix X", annotations: [{}] },
    });
  });
  const outcome = await requestPlannotatorCodeReview(bus, {
    prUrl: "https://gh/o/r/pull/42",
    cwd: "/repo",
  });
  assert.equal(seen?.action, "code-review");
  assert.equal(seen?.payload.prUrl, "https://gh/o/r/pull/42");
  assert.deepEqual(outcome, {
    status: "handled",
    approved: false,
    feedback: "fix X",
    annotationCount: 1,
    annotations: [],
    exit: false,
  });
});

test("bridge: an approved reply with no feedback maps to approved + undefined feedback", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({ status: "handled", result: { approved: true } });
  });
  const outcome = await requestPlannotatorCodeReview(bus, { prUrl: "u", cwd: "/repo" });
  assert.deepEqual(outcome, {
    status: "handled",
    approved: true,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
});

test("bridge: content-carrying annotations decode fields, normalize side, skip malformed", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({
      status: "handled",
      result: {
        approved: false,
        feedback: "see notes",
        annotations: [
          {
            id: "a1",
            filePath: "src/a.ts",
            lineStart: 10,
            lineEnd: 12,
            side: "old",
            text: "drop this",
            suggestedCode: "x",
            type: "suggestion",
            scope: "line",
            source: "perk:correctness",
            severity: "major",
          },
          // side anything-but-"old" normalizes to "new"; non-string optionals dropped.
          { filePath: "src/b.ts", lineStart: 3, lineEnd: 3, side: "LEFT", text: 7 },
          // malformed: missing filePath / non-numeric lines — skipped but still counted.
          { lineStart: 1, lineEnd: 1 },
          { filePath: "src/c.ts", lineStart: "4", lineEnd: 4 },
          "not-an-object",
        ],
      },
    });
  });
  const outcome = await requestPlannotatorCodeReview(bus, { prUrl: "u", cwd: "/repo" });
  assert.equal(outcome.status, "handled");
  if (outcome.status !== "handled") return;
  assert.equal(outcome.annotationCount, 5, "the raw array length — malformed items counted");
  assert.deepEqual(outcome.annotations, [
    {
      filePath: "src/a.ts",
      lineStart: 10,
      lineEnd: 12,
      side: "old",
      text: "drop this",
      suggestedCode: "x",
      type: "suggestion",
      scope: "line",
      source: "perk:correctness",
      severity: "major",
    },
    { filePath: "src/b.ts", lineStart: 3, lineEnd: 3, side: "new" },
  ]);
});

test("bridge: exit === true decodes into the outcome (the closed-without-feedback arm)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({
      status: "handled",
      result: { approved: false, exit: true },
    });
  });
  const outcome = await requestPlannotatorCodeReview(bus, { prUrl: "u", cwd: "/repo" });
  assert.equal(outcome.status, "handled");
  if (outcome.status !== "handled") return;
  assert.equal(outcome.exit, true);
  assert.equal(outcome.approved, false);
});

test("bridge: an `unavailable` reply maps to { status: unavailable, warning }", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({ status: "unavailable", error: "no browser" });
  });
  const outcome = await requestPlannotatorCodeReview(bus, { prUrl: "u", cwd: "/repo" });
  assert.equal(outcome.status, "unavailable");
  assert.match((outcome as { warning: string }).warning, /unavailable: no browser/);
});

test("bridge: an already-aborted signal short-circuits before emitting", async () => {
  const bus = fakeBus();
  let emitted = false;
  bus.on("plannotator:request", () => {
    emitted = true;
  });
  const controller = new AbortController();
  controller.abort();
  const outcome: CodeReviewOutcome = await requestPlannotatorCodeReview(bus, {
    prUrl: "u",
    cwd: "/repo",
    signal: controller.signal,
  });
  assert.deepEqual(outcome, { status: "aborted" });
  assert.equal(emitted, false, "no request emitted after an abort");
});

test("resolveReviewTarget: ok → pr with url + number", () => {
  const target = resolveReviewTarget(
    { ok: true, data: { number: 42, url: "https://gh/o/r/pull/42" } },
    "main",
  );
  assert.deepEqual(target, { mode: "pr", prUrl: "https://gh/o/r/pull/42", number: 42 });
});

test("resolveReviewTarget: no_pr + a pinned base → local with that defaultBranch", () => {
  const target = resolveReviewTarget(
    { ok: false, message: "No PR found", errorType: "no_pr" },
    "release-1.x",
  );
  assert.deepEqual(target, { mode: "local", defaultBranch: "release-1.x" });
});

test("resolveReviewTarget: no_pr + null/undefined base → local with defaultBranch undefined", () => {
  const fail = { ok: false as const, message: "No PR found", errorType: "no_pr" };
  assert.deepEqual(resolveReviewTarget(fail, null), { mode: "local", defaultBranch: undefined });
  assert.deepEqual(resolveReviewTarget(fail, undefined), {
    mode: "local",
    defaultBranch: undefined,
  });
});

test("resolveReviewTarget: non-no_pr fail arms pass through message + errorType unchanged", () => {
  assert.deepEqual(
    resolveReviewTarget(
      {
        ok: false,
        message: "No saved plan here — run /plan-save first.",
        errorType: "no_plan_ref",
      },
      "main",
    ),
    {
      mode: "fail",
      message: "No saved plan here — run /plan-save first.",
      errorType: "no_plan_ref",
    },
  );
  assert.deepEqual(
    resolveReviewTarget({ ok: false, message: "gh exploded", errorType: "github_error" }, null),
    { mode: "fail", message: "gh exploded", errorType: "github_error" },
  );
});

test("bridge: local-mode request pins { cwd, diffType, defaultBranch } and omits prUrl", async () => {
  const bus = fakeBus();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope;
    seen.respond({ status: "handled", result: { approved: true } });
  });
  await requestPlannotatorCodeReview(bus, {
    cwd: "/repo",
    diffType: LOCAL_REVIEW_DIFF_TYPE,
    defaultBranch: "main",
  });
  assert.equal(seen?.action, "code-review");
  assert.equal(seen?.payload.cwd, "/repo");
  assert.equal(seen?.payload.diffType, LOCAL_REVIEW_DIFF_TYPE);
  assert.equal(seen?.payload.defaultBranch, "main");
  assert.equal(seen !== undefined && "prUrl" in seen.payload, false, "prUrl absent in local mode");
});

test("bridge: an omitted defaultBranch is ABSENT from the payload (not undefined-valued)", async () => {
  const bus = fakeBus();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope;
    seen.respond({ status: "handled", result: { approved: true } });
  });
  await requestPlannotatorCodeReview(bus, { cwd: "/repo", diffType: LOCAL_REVIEW_DIFF_TYPE });
  assert.equal(
    seen !== undefined && "defaultBranch" in seen.payload,
    false,
    "defaultBranch omitted ⇒ plannotator auto-detects the repo default",
  );
});

// --- outcome routing (exit before the no-feedback "approved" arm) --------------------------------

/** Run routePrReviewOutcome against fakes; collect notifies + injected messages. */
function route(out: CodeReviewOutcome): { notifies: string[]; sent: string[] } {
  const notifies: string[] = [];
  const sent: string[] = [];
  routePrReviewOutcome(
    { sendUserMessage: (message: string) => sent.push(message) },
    { hasUI: true, ui: { notify: (m: string) => notifies.push(m) }, isIdle: () => true },
    out,
    "pr-review-browser",
  );
  return { notifies, sent };
}

test("routing: exit === true reports the neutral closed-without-feedback line — never approved", () => {
  const { notifies, sent } = route({
    status: "handled",
    approved: false,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: true,
  });
  assert.equal(sent.length, 0, "nothing injected");
  assert.equal(notifies.length, 1);
  assert.match(notifies[0] ?? "", /closed without feedback/);
  assert.doesNotMatch(notifies[0] ?? "", /approved/);
});

test("routing: no feedback without exit still reports the approved line", () => {
  const { notifies, sent } = route({
    status: "handled",
    approved: true,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.equal(sent.length, 0, "nothing injected");
  assert.equal(notifies.length, 1);
  assert.match(notifies[0] ?? "", /approved — no changes requested/);
});

test("routing: feedback injects a user message (exit false), not a notify", () => {
  const { notifies, sent } = route({
    status: "handled",
    approved: false,
    feedback: "fix X",
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.equal(notifies.length, 0);
  assert.deepEqual(sent, ["fix X"]);
});

test("plannotatorPresent: true iff getCommands lists plannotator-review", () => {
  const present = {
    getCommands: () => [{ name: PLANNOTATOR_REVIEW_COMMAND }, { name: "other" }],
  } as unknown as ExtensionAPI;
  const absent = {
    getCommands: () => [{ name: "other" }],
  } as unknown as ExtensionAPI;
  assert.equal(plannotatorPresent(present), true);
  assert.equal(plannotatorPresent(absent), false);
});

// --- respondMessage (the pure PR-mode respond → injection mapping, flipped posting) --------------

test("respondMessage: exit → the closed-without-submitting ask", () => {
  const msg = respondMessage({
    status: "handled",
    approved: false,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: true,
  });
  assert.match(msg ?? "", /closed the plannotator review without submitting/);
  assert.match(msg ?? "", /how they want to proceed/);
});

test("respondMessage: approved + no annotations → complete; perk posts nothing (no read-back)", () => {
  const msg = respondMessage({
    status: "handled",
    approved: true,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.match(msg ?? "", /approved the code review in plannotator/);
  assert.match(msg ?? "", /the review is complete/);
  assert.match(msg ?? "", /Perk posts nothing/);
  assert.match(msg ?? "", /only if they explicitly ask/);
  assert.match(msg ?? "", /request-changes verdict, which the UI cannot post/);
  assert.doesNotMatch(msg ?? "", /read back/i, "the read-back reminder is deleted");
});

test("respondMessage: feedback + annotations → text, fenced JSON, and the flipped triage pointer", () => {
  const annotation = {
    filePath: "src/a.ts",
    lineStart: 3,
    lineEnd: 3,
    side: "new" as const,
    text: "fix this",
    source: "perk:correctness",
  };
  const msg = respondMessage({
    status: "handled",
    approved: false,
    feedback: "please address the notes",
    annotationCount: 1,
    annotations: [annotation],
    exit: false,
  });
  assert.ok(msg?.startsWith("please address the notes"));
  assert.ok(msg?.includes("```json"));
  assert.ok(msg?.includes(JSON.stringify([annotation], null, 2)));
  assert.match(msg ?? "", /source-less ones are human-authored/);
  assert.match(msg ?? "", /`perk:\*`-badged/);
  assert.match(msg ?? "", /Perk composes nothing by default/);
  assert.match(msg ?? "", /ONLY for a request-changes verdict or on their explicit request/);
  assert.doesNotMatch(msg ?? "", /read back/i, "the read-back/dedupe step is deleted");
});

test("respondMessage: feedback with NO annotations (the platform-post ending) → just the text", () => {
  const msg = respondMessage({
    status: "handled",
    approved: false,
    feedback: "Pull request approved on GitHub: https://gh/o/r/pull/77",
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.equal(msg, "Pull request approved on GitHub: https://gh/o/r/pull/77");
});

test("respondMessage: non-handled arms map to null (routed via report, not injection)", () => {
  assert.equal(respondMessage({ status: "unavailable", warning: "w" }), null);
  assert.equal(respondMessage({ status: "error", warning: "w" }), null);
  assert.equal(respondMessage({ status: "aborted" }), null);
});

// --- stackRespondMessage (the stack flow's mapper) ------------------------------------------------

test("stackRespondMessage: exit → the same closed-without-submitting arm", () => {
  const msg = stackRespondMessage({
    status: "handled",
    approved: false,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: true,
  });
  assert.match(msg ?? "", /closed the plannotator review without submitting/);
  assert.match(msg ?? "", /how they want to proceed/);
});

test("stackRespondMessage: approved + no annotations → ask about per-PR COMMENT reviews", () => {
  const msg = stackRespondMessage({
    status: "handled",
    approved: true,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.match(msg ?? "", /approved the stack review/);
  assert.match(msg ?? "", /no attached PR/);
  assert.match(msg ?? "", /per-PR COMMENT reviews/);
  assert.match(msg ?? "", /perk posts only what the\s+human approves/i);
  // The single-PR browser policy line must NOT leak in — the browser posted nothing here.
  assert.doesNotMatch(msg ?? "", /request-changes verdict, which the UI cannot post/);
});

test("stackRespondMessage: annotations → combined-diff framing + the routing/posting protocol", () => {
  const annotation = {
    filePath: "src/a.ts",
    lineStart: 3,
    lineEnd: 3,
    side: "new" as const,
    text: "fix this",
    source: "perk:correctness",
  };
  const msg = stackRespondMessage({
    status: "handled",
    approved: false,
    feedback: "please address the notes",
    annotationCount: 1,
    annotations: [annotation],
    exit: false,
  });
  assert.ok(msg?.startsWith("please address the notes"));
  assert.ok(msg?.includes(JSON.stringify([annotation], null, 2)));
  assert.match(msg ?? "", /COMBINED-DIFF coordinates/);
  assert.match(msg ?? "", /routing \+ per-PR posting\s+protocol/);
  assert.match(msg ?? "", /dry-run\s+ALL per-PR batches first/);
  assert.match(msg ?? "", /bottom→top via `submit_pr_review`/);
  assert.match(msg ?? "", /ALL GitHub posting is perk-side/);
  // The single-PR "perk composes nothing by default" posting flip must NOT leak in.
  assert.doesNotMatch(msg ?? "", /composes nothing by default/);
});

test("stackRespondMessage: feedback without annotations still carries the posting framing", () => {
  const msg = stackRespondMessage({
    status: "handled",
    approved: false,
    feedback: "the naming is off across the stack",
    annotationCount: 0,
    annotations: [],
    exit: false,
  });
  assert.ok(msg?.startsWith("the naming is off across the stack"));
  assert.match(msg ?? "", /No annotations came back with this feedback/);
  assert.match(msg ?? "", /nothing was posted from the browser/);
  assert.match(msg ?? "", /bottom→top via `submit_pr_review`/);
  assert.match(msg ?? "", /only what the human approves/);
});

test("stackRespondMessage: non-handled arms map to null", () => {
  assert.equal(stackRespondMessage({ status: "unavailable", warning: "w" }), null);
  assert.equal(stackRespondMessage({ status: "error", warning: "w" }), null);
  assert.equal(stackRespondMessage({ status: "aborted" }), null);
});

test("routeBrowserRespond: the injectable mapper routes the handled arm (default = respondMessage)", () => {
  const sent: string[] = [];
  const pi = { sendUserMessage: (m: string) => void sent.push(m) };
  const ctx = {
    hasUI: true,
    ui: { notify: () => {} },
    isIdle: () => true,
  } as unknown as Parameters<typeof routeBrowserRespond>[1];
  const handled: CodeReviewOutcome = {
    status: "handled",
    approved: true,
    feedback: undefined,
    annotationCount: 0,
    annotations: [],
    exit: false,
  };
  routeBrowserRespond(pi, ctx, handled, "scope", stackRespondMessage);
  assert.equal(sent.length, 1);
  assert.match(sent[0] ?? "", /approved the stack review/);
  routeBrowserRespond(pi, ctx, handled, "scope");
  assert.equal(sent.length, 2);
  assert.match(sent[1] ?? "", /approved the code review in plannotator/);
});

// --- startPlannotatorBrowser (the composable browser-open core) ----------------------------------

test("startPlannotatorBrowser: env preset while probing, PR-mode payload, ready + restore", async () => {
  const bus = fakeBus();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope; // no respond — the review is still open
  });
  const envDuringProbe: (string | undefined)[] = [];
  const prior = process.env.PLANNOTATOR_PORT;
  process.env.PLANNOTATOR_PORT = "4242"; // the prior-SET arm: restored, not deleted
  try {
    const started = await startPlannotatorBrowser(
      bus,
      { prUrl: "https://gh/o/r/pull/77", cwd: "/repo" },
      {
        pickFreePort: () => Promise.resolve(45001),
        probe: (url) => {
          envDuringProbe.push(process.env.PLANNOTATOR_PORT);
          assert.equal(url, "http://127.0.0.1:45001");
          return Promise.resolve(envDuringProbe.length >= 2); // ready on the second attempt
        },
        intervalMs: 1,
        budgetMs: 100,
        sleep: () => Promise.resolve(),
      },
    );
    assert.equal(started.url, "http://127.0.0.1:45001", "the URL is known at start time");
    assert.equal(started.port, 45001);
    assert.equal(seen?.action, "code-review", "the bridge request is emitted at start");
    // The payload mirrors the PR mode byte-for-byte: { prUrl, cwd } only.
    assert.deepEqual(seen?.payload, { cwd: "/repo", prUrl: "https://gh/o/r/pull/77" });
    assert.equal(await started.readiness, "ready");
    assert.deepEqual(envDuringProbe, ["45001", "45001"], "env preset for plannotator's bind");
    assert.equal(process.env.PLANNOTATOR_PORT, "4242", "prior value restored after the poll");
  } finally {
    if (prior === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = prior;
  }
});

test("startPlannotatorBrowser: probe never true → timeout, env RESTORED-BY-DELETE (prior-unset arm)", async () => {
  const bus = fakeBus();
  const prior = process.env.PLANNOTATOR_PORT;
  delete process.env.PLANNOTATOR_PORT;
  try {
    const started = await startPlannotatorBrowser(
      bus,
      { prUrl: "u", cwd: "/repo" },
      {
        pickFreePort: () => Promise.resolve(45002),
        probe: () => Promise.resolve(false),
        intervalMs: 1,
        budgetMs: 3,
        sleep: () => Promise.resolve(),
      },
    );
    assert.equal(await started.readiness, "timeout");
    assert.equal("PLANNOTATOR_PORT" in process.env, false, "prior-unset ⇒ deleted");
  } finally {
    if (prior !== undefined) process.env.PLANNOTATOR_PORT = prior;
  }
});

test("startPlannotatorBrowser: local-mode fields render ONLY when defined (the stack shape)", async () => {
  // The stack door's payload: {cwd, diffType, defaultBranch} — no prUrl key at all. The
  // PR-mode byte-identity pin is the deepEqual above ({ cwd, prUrl } exactly).
  const bus = fakeBus();
  let seen: CodeReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as CodeReviewEnvelope;
  });
  const started = await startPlannotatorBrowser(
    bus,
    { cwd: "/checkout", diffType: "since-base", defaultBranch: "origin/main" },
    {
      pickFreePort: () => Promise.resolve(45007),
      probe: () => Promise.resolve(true),
      intervalMs: 1,
      budgetMs: 10,
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "ready");
  assert.deepEqual(seen?.payload, {
    cwd: "/checkout",
    diffType: "since-base",
    defaultBranch: "origin/main",
  });
});

test("startPlannotatorBrowser: early bridge settle stops the poll → bridge_settled", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as CodeReviewEnvelope).respond({ status: "error", error: "boom" });
  });
  let probes = 0;
  const started = await startPlannotatorBrowser(
    bus,
    { prUrl: "u", cwd: "/repo" },
    {
      pickFreePort: () => Promise.resolve(45003),
      probe: () => {
        probes++;
        return Promise.resolve(false);
      },
      intervalMs: 1,
      budgetMs: 1000, // 1000 attempts available — the settle must stop the loop, not the budget
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "bridge_settled");
  assert.ok(probes <= 1, "the poll stopped as soon as the bridge settled");
  const out = await started.bridgePromise;
  assert.equal(out.status, "error");
});

test("startPlannotatorBrowser: a turn abort stops the poll → aborted", async () => {
  const bus = fakeBus();
  const controller = new AbortController();
  let probes = 0;
  const started = await startPlannotatorBrowser(
    bus,
    { prUrl: "u", cwd: "/repo", signal: controller.signal },
    {
      pickFreePort: () => Promise.resolve(45004),
      probe: () => {
        probes++;
        if (probes === 1) controller.abort(); // abort mid-poll
        return Promise.resolve(false);
      },
      intervalMs: 1,
      budgetMs: 1000,
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "aborted");
  assert.equal(probes, 1, "the poll stopped on the abort");
});

test("startPlannotatorBrowser: a port-pick failure throws (the caller owns the surface)", async () => {
  const bus = fakeBus();
  await assert.rejects(
    startPlannotatorBrowser(
      bus,
      { prUrl: "u", cwd: "/repo" },
      { pickFreePort: () => Promise.reject(new Error("no ports")) },
    ),
    /no ports/,
  );
});

// --- startPlannotatorPlanReview (the plan-review flavor of the browser-open core) ----------------

/** The plannotator:request envelope the fake plan-review listener receives (pinned, see header). */
interface PlanReviewEnvelope {
  requestId: string;
  action: string;
  payload: { planContent: string; origin?: string };
  respond: (response: unknown) => void;
}

test("startPlannotatorPlanReview: env preset while probing, plan-review envelope, ready + restore", async () => {
  const bus = fakeBus();
  let seen: PlanReviewEnvelope | undefined;
  bus.on("plannotator:request", (data) => {
    seen = data as PlanReviewEnvelope;
    seen.respond({ status: "handled", result: { status: "pending", reviewId: "rev-b1" } });
  });
  const envDuringProbe: (string | undefined)[] = [];
  const prior = process.env.PLANNOTATOR_PORT;
  process.env.PLANNOTATOR_PORT = "4242"; // the prior-SET arm: restored, not deleted
  try {
    const started = await startPlannotatorPlanReview(
      bus,
      { plan: "# A plan" },
      {
        pickFreePort: () => Promise.resolve(46001),
        probe: (url) => {
          envDuringProbe.push(process.env.PLANNOTATOR_PORT);
          assert.equal(url, "http://127.0.0.1:46001", "the probe receives the BASE url");
          return Promise.resolve(envDuringProbe.length >= 2); // ready on the second attempt
        },
        intervalMs: 1,
        budgetMs: 100,
        sleep: () => Promise.resolve(),
      },
    );
    assert.equal(started.url, "http://127.0.0.1:46001", "the URL is known at start time");
    assert.equal(started.port, 46001);
    assert.equal(seen?.action, "plan-review", "the bridge request is emitted at start");
    // The payload mirrors the plan-review envelope byte-for-byte: { planContent, origin }.
    assert.deepEqual(seen?.payload, { planContent: "# A plan", origin: "perk" });
    assert.equal(await started.readiness, "ready");
    assert.deepEqual(envDuringProbe, ["46001", "46001"], "env preset for plannotator's bind");
    assert.equal(process.env.PLANNOTATOR_PORT, "4242", "prior value restored after the poll");
  } finally {
    if (prior === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = prior;
  }
});

test("startPlannotatorPlanReview: a later review-result decision resolves the bridgePromise", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    const req = data as PlanReviewEnvelope;
    req.respond({ status: "handled", result: { status: "pending", reviewId: "rev-b2" } });
    // The human decision arrives later on the result channel.
    setTimeout(() => {
      bus.emit("plannotator:review-result", {
        reviewId: "rev-b2",
        approved: true,
        feedback: "ship it",
      });
    }, 10);
  });
  const started = await startPlannotatorPlanReview(
    bus,
    { plan: "# A plan" },
    {
      pickFreePort: () => Promise.resolve(46002),
      probe: () => Promise.resolve(true),
      intervalMs: 1,
      budgetMs: 100,
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "ready");
  assert.deepEqual(await started.bridgePromise, {
    status: "completed",
    approved: true,
    feedback: "ship it",
    reviewId: "rev-b2",
  });
});

test("startPlannotatorPlanReview: an early handshake error settles the bridge → bridge_settled", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as PlanReviewEnvelope).respond({ status: "error", error: "boom" });
  });
  let probes = 0;
  const started = await startPlannotatorPlanReview(
    bus,
    { plan: "# A plan" },
    {
      pickFreePort: () => Promise.resolve(46003),
      probe: () => {
        probes++;
        return Promise.resolve(false);
      },
      intervalMs: 1,
      budgetMs: 1000, // 1000 attempts available — the settle must stop the loop, not the budget
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "bridge_settled");
  assert.ok(probes <= 1, "the poll stopped as soon as the bridge settled");
  const out = await started.bridgePromise;
  assert.equal(out.status, "unavailable");
  assert.match((out as { warning: string }).warning, /error: boom/);
});

test("startPlannotatorPlanReview: a turn abort stops the poll → aborted (bridge aborted too)", async () => {
  const bus = fakeBus();
  bus.on("plannotator:request", (data) => {
    (data as PlanReviewEnvelope).respond({
      status: "handled",
      result: { status: "pending", reviewId: "rev-b4" },
    });
  });
  const controller = new AbortController();
  let probes = 0;
  const started = await startPlannotatorPlanReview(
    bus,
    { plan: "# A plan", signal: controller.signal },
    {
      pickFreePort: () => Promise.resolve(46004),
      probe: () => {
        probes++;
        if (probes === 1) controller.abort(); // abort mid-poll
        return Promise.resolve(false);
      },
      intervalMs: 1,
      budgetMs: 1000,
      sleep: () => Promise.resolve(),
    },
  );
  assert.equal(await started.readiness, "aborted");
  assert.equal(probes, 1, "the poll stopped on the abort");
  assert.deepEqual(await started.bridgePromise, { status: "aborted" });
});

test("startPlannotatorPlanReview: a port-pick failure throws (the caller owns the surface)", async () => {
  const bus = fakeBus();
  await assert.rejects(
    startPlannotatorPlanReview(
      bus,
      { plan: "# A plan" },
      { pickFreePort: () => Promise.reject(new Error("no ports")) },
    ),
    /no ports/,
  );
});

test("readiness probe paths: each names a server-flavor-unique route (pinned @ 0.26.4)", () => {
  assert.equal(CODE_REVIEW_READINESS_PROBE_PATH, "/api/diff");
  assert.equal(PLAN_REVIEW_READINESS_PROBE_PATH, "/api/plan");
});

test("default probe wiring: each wrapper's default probe fetches its own flavor's route", async () => {
  // No injected `deps.probe` here — this exercises the real default probe (a mocked global
  // fetch records the requested URLs), pinning that each wrapper hands the engine ITS route.
  const priorFetch = globalThis.fetch;
  const priorPort = process.env.PLANNOTATOR_PORT;
  const requested: string[] = [];
  globalThis.fetch = ((input: Parameters<typeof fetch>[0]) => {
    requested.push(String(input));
    return Promise.resolve(new Response("{}", { status: 200 }));
  }) as typeof fetch;
  try {
    const codeBus = fakeBus(); // no respond — the review stays open; the probe settles readiness
    const code = await startPlannotatorBrowser(
      codeBus,
      { prUrl: "u", cwd: "/repo" },
      {
        pickFreePort: () => Promise.resolve(46005),
        intervalMs: 1,
        budgetMs: 100,
        sleep: () => Promise.resolve(),
      },
    );
    assert.equal(await code.readiness, "ready");

    const planBus = fakeBus();
    planBus.on("plannotator:request", (data) => {
      (data as PlanReviewEnvelope).respond({
        status: "handled",
        result: { status: "pending", reviewId: "rev-b6" },
      });
    });
    const plan = await startPlannotatorPlanReview(
      planBus,
      { plan: "# A plan" },
      {
        pickFreePort: () => Promise.resolve(46006),
        intervalMs: 1,
        budgetMs: 100,
        sleep: () => Promise.resolve(),
      },
    );
    assert.equal(await plan.readiness, "ready");

    assert.deepEqual(requested, [
      `http://127.0.0.1:46005${CODE_REVIEW_READINESS_PROBE_PATH}`,
      `http://127.0.0.1:46006${PLAN_REVIEW_READINESS_PROBE_PATH}`,
    ]);
  } finally {
    globalThis.fetch = priorFetch;
    if (priorPort === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = priorPort;
  }
});
