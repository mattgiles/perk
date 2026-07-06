// The warm `/pr-review-local` bridge (offline): the pure event-bus bridge to plannotator's
// published `code-review` action, the outcome mapping (handled / unavailable), the target
// resolution (PR vs the no-PR local since-base fallback), and the presence helper. Fully
// offline — the fake plannotator is a test listener on an event bus that calls `respond(...)`.
// See prReviewLocal.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import {
  type CodeReviewOutcome,
  LOCAL_REVIEW_DIFF_TYPE,
  PLANNOTATOR_REVIEW_COMMAND,
  plannotatorPresent,
  requestPlannotatorCodeReview,
  resolveReviewTarget,
} from "./prReviewLocal.ts";

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
  });
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
