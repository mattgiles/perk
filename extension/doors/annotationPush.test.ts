// Tests for the flow-scoped annotation-push tool (registered live in `extension/index.ts`).
// The strict per-mode decoder and the pure finding→annotation mapping are pinned directly; the
// execute core is driven through an injected recording `fetchLike` (the structural-slice
// injection posture — no session needed); registration + the default-fetch wiring run against a
// REAL bound session via the T1 harness (the harness binds perk's extension, so the tool is
// present) and a real ephemeral `node:http` server on 127.0.0.1. Offline like everything here.

import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PERK_TOOLS, STAGE_TOOLS } from "../substrate/toolGating.ts";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  clearAnnotationSurface,
  decodePushAnnotationsParams,
  executePushAnnotations,
  type FetchLike,
  type FetchResponseLike,
  mapFindings,
  type PlanFinding,
  primeAnnotationSurface,
  type ReviewFinding,
  registerAnnotationPushTool,
} from "./annotationPush.ts";

// --- fixtures ----------------------------------------------------------------------------------

const URL_BASE = "http://127.0.0.1:7777";

function reviewFinding(overrides: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    path: "src/a.ts",
    line: 3,
    severity: "major",
    confidence: "high",
    body: "off-by-one in the loop bound",
    ...overrides,
  };
}

function planFinding(overrides: Partial<PlanFinding> = {}): PlanFinding {
  return {
    phrase: "the exact quoted span",
    severity: "minor",
    confidence: "medium",
    body: "this step is underspecified",
    ...overrides,
  };
}

/** A minimal `ReportTarget` capturing notifies (severity-aware). */
function fakeTarget(): {
  target: { hasUI: boolean; ui: { notify(message: string, type?: string): void } };
  notified: { message: string; severity?: string }[];
} {
  const notified: { message: string; severity?: string }[] = [];
  return {
    target: {
      hasUI: true,
      ui: { notify: (message: string, severity?: string) => notified.push({ message, severity }) },
    },
    notified,
  };
}

interface EndpointCall {
  url: string;
  method: string;
  body: unknown;
}

/**
 * A scriptable in-memory annotation endpoint standing in for the injected `fetchLike`:
 * records every call, auto-assigns sequential ids on POST, answers `{ok, removed}` on DELETE,
 * throws while `down`, and can reject the next request of a given method with an HTTP error.
 */
function fakeEndpoint(opts: { removed?: number } = {}): {
  fetchLike: FetchLike;
  calls: EndpointCall[];
  /** Take the endpoint down — optionally for one method only (POST-fails-after-DELETE cases). */
  setDown(down: boolean, only?: "POST" | "DELETE"): void;
  failNext(method: "POST" | "DELETE", status: number, error: string): void;
} {
  const calls: EndpointCall[] = [];
  let down = false;
  let downOnly: "POST" | "DELETE" | null = null;
  let seq = 0;
  let fail: { method: string; status: number; error: string } | null = null;
  const respond = (status: number, body: unknown): FetchResponseLike => ({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  });
  const fetchLike: FetchLike = async (url, init) => {
    calls.push({
      url,
      method: init.method,
      body: init.body === undefined ? undefined : JSON.parse(init.body),
    });
    if (down && (downOnly === null || downOnly === init.method)) {
      throw new Error("connect ECONNREFUSED 127.0.0.1");
    }
    if (fail !== null && fail.method === init.method) {
      const pending = fail;
      fail = null;
      return respond(pending.status, { error: pending.error });
    }
    if (init.method === "DELETE") return respond(200, { ok: true, removed: opts.removed ?? 0 });
    const batch = calls[calls.length - 1]?.body as { annotations: unknown[] };
    return respond(201, {
      ids: Array.from({ length: batch.annotations.length }, () => `id-${++seq}`),
    });
  };
  return {
    fetchLike,
    calls,
    setDown(next: boolean, only?: "POST" | "DELETE") {
      down = next;
      downOnly = next ? (only ?? null) : null;
    },
    failNext(method: "POST" | "DELETE", status: number, error: string) {
      fail = { method, status, error };
    },
  };
}

interface OkDetails {
  ok: boolean;
  mode?: string;
  pushed?: number;
  skipped?: string[];
  held?: number;
  held_batches?: number;
  deleted?: number;
  ids?: string[];
}

interface FailDetails {
  ok: boolean;
  error?: string;
  error_type?: string;
  status?: number;
  server_error?: string;
  dropped_source?: string;
  dropped_count?: number;
  held?: number;
}

// --- decodePushAnnotationsParams: strict whole-refusal decode -----------------------------------

test("decode accepts a valid review batch (side/replace optional; [] legal)", () => {
  assert.deepEqual(
    decodePushAnnotationsParams(
      {
        angle: "correctness",
        findings: [
          { path: "a.ts", line: 3, severity: "major", confidence: "high", body: "b" },
          {
            path: "b.ts",
            line: null,
            side: "LEFT",
            severity: "minor",
            confidence: "low",
            body: "c",
          },
        ],
      },
      "review",
    ),
    {
      mode: "review",
      angle: "correctness",
      findings: [
        { path: "a.ts", line: 3, severity: "major", confidence: "high", body: "b" },
        { path: "b.ts", line: null, side: "LEFT", severity: "minor", confidence: "low", body: "c" },
      ],
      replace: false,
    },
  );
  assert.deepEqual(
    decodePushAnnotationsParams({ angle: "tests", findings: [], replace: true }, "review"),
    { mode: "review", angle: "tests", findings: [], replace: true },
  );
});

test("decode accepts a valid plan batch (phrase byte-exact; null = global)", () => {
  assert.deepEqual(
    decodePushAnnotationsParams(
      {
        angle: "custom",
        findings: [
          { phrase: "  spaced span  ", severity: "critical", confidence: "high", body: "b" },
          { phrase: null, severity: "minor", confidence: "low", body: "global note" },
        ],
      },
      "plan",
    ),
    {
      mode: "plan",
      angle: "custom",
      findings: [
        // Never trimmed — the phrase must match the rendered draft byte-exact for pinning.
        { phrase: "  spaced span  ", severity: "critical", confidence: "high", body: "b" },
        { phrase: null, severity: "minor", confidence: "low", body: "global note" },
      ],
      replace: false,
    },
  );
});

test("decode refuses a bad angle slug (whole refusal)", () => {
  const findings = [reviewFinding()];
  for (const angle of [
    undefined,
    7,
    "",
    "Tests", // uppercase
    "9lead", // leading digit
    "-lead", // leading dash
    "has space",
    "perk:tests", // the source is composed by the tool, never passed
    `a${"b".repeat(40)}`, // overlong (41 chars)
  ]) {
    assert.equal(decodePushAnnotationsParams({ angle, findings }, "review"), null, String(angle));
  }
  // The 40-char boundary passes.
  assert.notEqual(
    decodePushAnnotationsParams({ angle: `a${"b".repeat(39)}`, findings }, "review"),
    null,
  );
});

test("decode refuses missing/mis-enumed severity/confidence and a mistyped body", () => {
  for (const bad of [
    { ...reviewFinding(), severity: undefined },
    { ...reviewFinding(), severity: "blocker" },
    { ...reviewFinding(), confidence: undefined },
    { ...reviewFinding(), confidence: "sure" },
    { ...reviewFinding(), body: undefined },
    { ...reviewFinding(), body: 7 },
  ]) {
    assert.equal(
      decodePushAnnotationsParams({ angle: "tests", findings: [bad] }, "review"),
      null,
      JSON.stringify(bad),
    );
  }
});

test("decode refuses malformed review findings (missing keys, bad line/side, foreign keys)", () => {
  for (const bad of [
    "not an object",
    (() => {
      const { path: _path, ...rest } = reviewFinding();
      return rest; // no path key
    })(),
    (() => {
      const { line: _line, ...rest } = reviewFinding();
      return rest; // no line key
    })(),
    { ...reviewFinding(), path: 7 },
    { ...reviewFinding(), line: 1.5 }, // non-integer
    { ...reviewFinding(), line: "12" }, // mistyped
    { ...reviewFinding(), line: 3, path: "" }, // a line needs a path to anchor to
    { ...reviewFinding(), side: "old" }, // upstream vocabulary, not the finding contract's
    { ...reviewFinding(), phrase: "x" }, // a plan-mode key on a review surface
  ]) {
    assert.equal(
      decodePushAnnotationsParams({ angle: "tests", findings: [bad] }, "review"),
      null,
      JSON.stringify(bad),
    );
  }
  // …and one bad finding refuses the WHOLE batch.
  assert.equal(
    decodePushAnnotationsParams(
      { angle: "tests", findings: [reviewFinding(), { ...reviewFinding(), line: "12" }] },
      "review",
    ),
    null,
  );
});

test("decode refuses malformed plan findings (empty/whitespace phrase, missing key, foreign keys)", () => {
  for (const bad of [
    (() => {
      const { phrase: _phrase, ...rest } = planFinding();
      return rest; // no phrase key
    })(),
    { ...planFinding(), phrase: "" }, // cannot anchor — pass null for a global finding
    { ...planFinding(), phrase: "   " }, // whitespace-only cannot anchor either
    { ...planFinding(), phrase: 7 },
    { ...planFinding(), path: "a.ts" }, // a review-mode key on a plan surface
  ]) {
    assert.equal(
      decodePushAnnotationsParams({ angle: "scope", findings: [bad] }, "plan"),
      null,
      JSON.stringify(bad),
    );
  }
});

test("decode refuses non-boolean replace, non-array findings, and non-object params", () => {
  assert.equal(
    decodePushAnnotationsParams({ angle: "tests", findings: [], replace: "true" }, "review"),
    null,
  );
  assert.equal(decodePushAnnotationsParams({ angle: "tests" }, "review"), null); // missing
  assert.equal(decodePushAnnotationsParams({ angle: "tests", findings: "none" }, "review"), null);
  assert.equal(decodePushAnnotationsParams("not an object", "review"), null);
  assert.equal(decodePushAnnotationsParams(null, "review"), null);
});

// --- mapFindings: the pure code-owned mapping ----------------------------------------------------

test("mapFindings review mode: line/file/general classification with the [severity/confidence] prefix", () => {
  const mapped = mapFindings("review", "correctness", [
    reviewFinding({ path: "src/a.ts", line: 12, side: "LEFT" }),
    reviewFinding({ path: "src/a.ts", line: 14, side: "RIGHT", severity: "critical" }),
    reviewFinding({ path: "src/b.ts", line: 9 }), // side omitted → new
    reviewFinding({ path: "src/c.ts", line: null, body: "file-wide concern" }),
    reviewFinding({ path: "", line: null, body: "review-level concern", confidence: "low" }),
  ]);
  assert.deepEqual(mapped, [
    {
      key: "line:src/a.ts:12",
      source: "perk:correctness",
      annotation: {
        source: "perk:correctness",
        type: "concern",
        scope: "line",
        filePath: "src/a.ts",
        lineStart: 12,
        lineEnd: 12,
        side: "old",
        text: "[major/high] off-by-one in the loop bound",
      },
    },
    {
      key: "line:src/a.ts:14",
      source: "perk:correctness",
      annotation: {
        source: "perk:correctness",
        type: "concern",
        scope: "line",
        filePath: "src/a.ts",
        lineStart: 14,
        lineEnd: 14,
        side: "new",
        text: "[critical/high] off-by-one in the loop bound",
      },
    },
    {
      key: "line:src/b.ts:9",
      source: "perk:correctness",
      annotation: {
        source: "perk:correctness",
        type: "concern",
        scope: "line",
        filePath: "src/b.ts",
        lineStart: 9,
        lineEnd: 9,
        side: "new",
        text: "[major/high] off-by-one in the loop bound",
      },
    },
    {
      key: "file:src/c.ts",
      source: "perk:correctness",
      annotation: {
        source: "perk:correctness",
        type: "concern",
        scope: "file",
        filePath: "src/c.ts",
        text: "[major/high] file-wide concern",
      },
    },
    {
      key: "general:[major/low] review-level concern",
      source: "perk:correctness",
      annotation: {
        source: "perk:correctness",
        type: "concern",
        scope: "general",
        text: "[major/low] review-level concern",
      },
    },
  ]);
  // The upstream severity/reasoning metadata fields are never set — upstream's severity
  // vocabulary (important|nit|pre_existing) is not perk's; the text prefix is the one carrier.
  for (const { annotation } of mapped) {
    assert.equal("severity" in annotation, false);
    assert.equal("reasoning" in annotation, false);
  }
});

test("mapFindings plan mode: COMMENT-with-originalText vs GLOBAL_COMMENT", () => {
  assert.deepEqual(
    mapFindings("plan", "scope", [
      planFinding({ phrase: "  the exact  span " }),
      planFinding({ phrase: null, severity: "critical", body: "missing rollback story" }),
    ]),
    [
      {
        key: "comment:  the exact  span ",
        source: "perk:scope",
        annotation: {
          source: "perk:scope",
          type: "COMMENT",
          originalText: "  the exact  span ", // byte-exact — never trimmed or normalized
          text: "[minor/medium] this step is underspecified",
        },
      },
      {
        key: "global:[critical/medium] missing rollback story",
        source: "perk:scope",
        annotation: {
          source: "perk:scope",
          type: "GLOBAL_COMMENT",
          text: "[critical/medium] missing rollback story",
        },
      },
    ],
  );
});

// --- executePushAnnotations: the execute core over the injected fetchLike -----------------------

test("execute: unprimed → no_surface; bad params → bad_input — no fetch either way", async () => {
  clearAnnotationSurface();
  const { target, notified } = fakeTarget();
  const endpoint = fakeEndpoint();
  const unprimed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(unprimed.details.ok, false);
  assert.equal((unprimed.details as FailDetails).error_type, "no_surface");
  assert.equal(endpoint.calls.length, 0);
  assert.ok(
    notified.some((n) => n.severity === "error"),
    "loud soft-fail through report()",
  );

  // The primed mode selects the refusal shape (surface check precedes decode).
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const badReview = await executePushAnnotations(
    target,
    { angle: "tests", findings: [planFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((badReview.details as FailDetails).error_type, "bad_input");
  assert.match(badReview.content[0]?.text ?? "", /review-mode/);
  assert.equal(endpoint.calls.length, 0, "decode-before-side-effect");

  primeAnnotationSurface({ mode: "plan", url: URL_BASE });
  const badPlan = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((badPlan.details as FailDetails).error_type, "bad_input");
  assert.match(badPlan.content[0]?.text ?? "", /plan-mode/);
  assert.equal(endpoint.calls.length, 0);
});

test("execute: a push is ONE POST with the exact batch body; 201 ids captured in details", async () => {
  primeAnnotationSurface({ mode: "review", url: `${URL_BASE}/` }); // trailing slash normalized
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  const result = await executePushAnnotations(
    target,
    {
      angle: "tests",
      findings: [reviewFinding(), reviewFinding({ path: "src/b.ts", line: null })],
    },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(result.details.ok, true);
  const details = result.details as OkDetails;
  assert.equal(details.mode, "review");
  assert.equal(details.pushed, 2);
  assert.deepEqual(details.skipped, []);
  assert.equal(details.held, 0);
  assert.equal(details.deleted, 0);
  assert.deepEqual(details.ids, ["id-1", "id-2"]);
  assert.equal(endpoint.calls.length, 1);
  assert.equal(endpoint.calls[0]?.url, `${URL_BASE}/api/external-annotations`);
  assert.equal(endpoint.calls[0]?.method, "POST");
  assert.deepEqual(endpoint.calls[0]?.body, {
    annotations: [
      {
        source: "perk:tests",
        type: "concern",
        scope: "line",
        filePath: "src/a.ts",
        lineStart: 3,
        lineEnd: 3,
        side: "new",
        text: "[major/high] off-by-one in the loop bound",
      },
      {
        source: "perk:tests",
        type: "concern",
        scope: "file",
        filePath: "src/b.ts",
        text: "[major/high] off-by-one in the loop bound",
      },
    ],
  });
  const text = result.content[0]?.text ?? "";
  assert.match(text, /perk:tests: pushed 2/);
  assert.equal(text.includes(URL_BASE), false, "the prose never echoes the surface URL");
});

test("execute: dedupe skips pushed anchors — same angle, cross-angle, and intra-batch", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(endpoint.calls.length, 1);

  // Re-push of a pushed anchor: skipped, no POST, still ok (skipped, never refused).
  const repush = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding({ body: "reworded duplicate" })] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(repush.details.ok, true);
  const repushDetails = repush.details as OkDetails;
  assert.equal(repushDetails.pushed, 0);
  assert.deepEqual(repushDetails.skipped, ["line:src/a.ts:3"]);
  assert.equal(endpoint.calls.length, 1, "no POST for an all-duplicate batch");
  assert.match(repush.content[0]?.text ?? "", /Skipped 1 duplicate anchor/);

  // Cross-angle collision: an anchor pushed under one source is never re-pushed under another;
  // intra-batch duplicates collapse too.
  const cross = await executePushAnnotations(
    target,
    {
      angle: "quality",
      findings: [
        reviewFinding(),
        reviewFinding({ path: "src/new.ts", line: 1 }),
        reviewFinding({ path: "src/new.ts", line: 1, body: "intra-batch duplicate" }),
      ],
    },
    { fetchLike: endpoint.fetchLike },
  );
  const crossDetails = cross.details as OkDetails;
  assert.equal(crossDetails.pushed, 1);
  assert.deepEqual(crossDetails.skipped, ["line:src/a.ts:3", "line:src/new.ts:1"]);
  assert.equal(endpoint.calls.length, 2);
  const posted = endpoint.calls[1]?.body as { annotations: { filePath?: string }[] };
  assert.equal(posted.annotations.length, 1);
  assert.equal(posted.annotations[0]?.filePath, "src/new.ts");
});

test("execute: a network failure holds the batch (ok, never a degrade); [] flushes FIFO", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target, notified } = fakeTarget();
  const endpoint = fakeEndpoint();
  endpoint.setDown(true);

  const heldOne = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(heldOne.details.ok, true, "a network failure is ok + held, never a soft-fail");
  const heldOneDetails = heldOne.details as OkDetails;
  assert.equal(heldOneDetails.pushed, 0);
  assert.equal(heldOneDetails.held, 1);
  assert.equal(heldOneDetails.held_batches, 1);
  assert.deepEqual(heldOneDetails.ids, []);
  assert.match(heldOne.content[0]?.text ?? "", /held/);
  assert.match(heldOne.content[0]?.text ?? "", /findings: \[\] is the pure retry/);
  assert.equal(
    notified.some((n) => n.severity === "error"),
    false,
    "never a degrade signal",
  );

  // A second batch queues behind (FIFO); a held anchor dedupes (not re-held).
  const heldTwo = await executePushAnnotations(
    target,
    {
      angle: "quality",
      findings: [reviewFinding(), reviewFinding({ path: "src/q.ts", line: 7 })],
    },
    { fetchLike: endpoint.fetchLike },
  );
  const heldTwoDetails = heldTwo.details as OkDetails;
  assert.equal(heldTwoDetails.held, 2);
  assert.equal(heldTwoDetails.held_batches, 2);
  assert.deepEqual(heldTwoDetails.skipped, ["line:src/a.ts:3"]);

  // The server comes up: an empty-findings call is the pure retry — FIFO order pinned.
  endpoint.setDown(false);
  const flushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(flushed.details.ok, true);
  const flushedDetails = flushed.details as OkDetails;
  assert.equal(flushedDetails.pushed, 2);
  assert.equal(flushedDetails.held, 0);
  assert.equal(flushedDetails.held_batches, 0);
  assert.equal(flushedDetails.ids?.length, 2);
  // Down attempts were recorded too: the last two calls are the successful FIFO flush.
  const bodies = endpoint.calls.slice(-2).map((c) => c.body) as {
    annotations: { source?: string; filePath?: string }[];
  }[];
  assert.equal(bodies[0]?.annotations[0]?.source, "perk:tests");
  assert.equal(bodies[1]?.annotations[0]?.source, "perk:quality");
  assert.equal(bodies[1]?.annotations[0]?.filePath, "src/q.ts");

  // The flushed anchors are in the ledger now: re-pushing them skips.
  const repush = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.deepEqual((repush.details as OkDetails).skipped, ["line:src/a.ts:3"]);
});

test("execute: an HTTP rejection is the loud push_rejected — the batch is NOT held", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target, notified } = fakeTarget();
  const endpoint = fakeEndpoint();
  endpoint.failNext("POST", 400, "annotations[0] missing required field");
  const result = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(result.details.ok, false);
  const details = result.details as FailDetails;
  assert.equal(details.error_type, "push_rejected");
  assert.equal(details.status, 400);
  assert.match(details.server_error ?? "", /missing required field/);
  assert.equal(details.dropped_source, "perk:tests");
  assert.equal(details.dropped_count, 1);
  assert.equal(details.held, 0, "an HTTP rejection never holds the batch");
  assert.ok(notified.some((n) => n.severity === "error"));
  // Nothing held: a following pure-retry call makes no fetch at all.
  const idle = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(idle.details.ok, true);
  assert.equal(endpoint.calls.length, 1);
});

test("execute: a 400 mid-flush drops only the rejected batch and retains the rest", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  endpoint.setDown(true);
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  await executePushAnnotations(
    target,
    { angle: "quality", findings: [reviewFinding({ path: "src/q.ts", line: 7 })] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(false);
  endpoint.failNext("POST", 400, "drifted");
  const rejected = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(rejected.details.ok, false);
  const details = rejected.details as FailDetails;
  assert.equal(details.error_type, "push_rejected");
  assert.equal(details.dropped_source, "perk:tests");
  assert.equal(details.held, 1, "the rest of the queue is retained");

  // The retained batch flushes on the next call.
  const flushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  const flushedDetails = flushed.details as OkDetails;
  assert.equal(flushedDetails.pushed, 1);
  assert.equal(flushedDetails.held, 0);
  const last = endpoint.calls[endpoint.calls.length - 1];
  assert.equal(
    (last?.body as { annotations: { source?: string }[] }).annotations[0]?.source,
    "perk:quality",
  );
});

test("execute: replace is DELETE-then-POST — angle ledger cleared, other angles' anchors skip", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 2 });
  await executePushAnnotations(
    target,
    {
      angle: "tests",
      findings: [reviewFinding(), reviewFinding({ path: "src/t2.ts", line: 5 })],
    },
    { fetchLike: endpoint.fetchLike },
  );
  await executePushAnnotations(
    target,
    { angle: "quality", findings: [reviewFinding({ path: "src/q.ts", line: 7 })] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.calls.length = 0;

  // Reconcile re-shapes the tests angle: the previously-pushed anchor re-pushes after the
  // source-scoped clear; the other angle's anchor skips (its annotations are untouchable).
  const replaced = await executePushAnnotations(
    target,
    {
      angle: "tests",
      findings: [
        reviewFinding({ body: "final reconciled body" }),
        reviewFinding({ path: "src/q.ts", line: 7, body: "collides with quality" }),
      ],
      replace: true,
    },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(replaced.details.ok, true);
  const details = replaced.details as OkDetails;
  assert.equal(details.deleted, 2);
  assert.equal(details.pushed, 1);
  assert.deepEqual(details.skipped, ["line:src/q.ts:7"]);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE", "POST"],
    "the DELETE-then-POST sequence",
  );
  assert.equal(
    endpoint.calls[0]?.url,
    `${URL_BASE}/api/external-annotations?source=${encodeURIComponent("perk:tests")}`,
    "the only expressible delete is source-scoped to the validated angle",
  );
  const posted = endpoint.calls[1]?.body as { annotations: { text?: string }[] };
  assert.equal(posted.annotations.length, 1);
  assert.equal(posted.annotations[0]?.text, "[major/high] final reconciled body");
  assert.match(replaced.content[0]?.text ?? "", /perk:tests: pushed 1, cleared 2/);

  // replace + findings: [] is a pure source clear — DELETE only, no POST.
  endpoint.calls.length = 0;
  const cleared = await executePushAnnotations(
    target,
    { angle: "tests", findings: [], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(cleared.details.ok, true);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE"],
  );

  // …and the cleared anchor is re-pushable (the angle's ledger entries went with the clear).
  const repushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((repushed.details as OkDetails).pushed, 1);
});

test("execute: a DELETE network failure holds the WHOLE replace unit (retried together)", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 1 });
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true);
  const heldUnit = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding({ body: "reconciled" })], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(heldUnit.details.ok, true);
  assert.equal((heldUnit.details as OkDetails).held, 1);

  // The next call retries delete + post together, atomically per angle.
  endpoint.setDown(false);
  endpoint.calls.length = 0;
  const flushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(flushed.details.ok, true);
  const details = flushed.details as OkDetails;
  assert.equal(details.deleted, 1);
  assert.equal(details.pushed, 1);
  assert.equal(details.held, 0);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE", "POST"],
  );
});

test("execute: plan-mode batches post the COMMENT/GLOBAL_COMMENT shapes", async () => {
  primeAnnotationSurface({ mode: "plan", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  const result = await executePushAnnotations(
    target,
    { angle: "scope", findings: [planFinding(), planFinding({ phrase: null, body: "global" })] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(result.details.ok, true);
  assert.equal((result.details as OkDetails).mode, "plan");
  assert.deepEqual(endpoint.calls[0]?.body, {
    annotations: [
      {
        source: "perk:scope",
        type: "COMMENT",
        originalText: "the exact quoted span",
        text: "[minor/medium] this step is underspecified",
      },
      {
        source: "perk:scope",
        type: "GLOBAL_COMMENT",
        text: "[minor/medium] global",
      },
    ],
  });
});

test("execute: re-priming resets the ledger and the held queue (a new session supersedes)", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true);
  await executePushAnnotations(
    target,
    { angle: "quality", findings: [reviewFinding({ path: "src/q.ts", line: 7 })] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(false);

  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  endpoint.calls.length = 0;
  // The held batch is gone (no flush POST) and the pushed anchor re-pushes.
  const repush = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  const details = repush.details as OkDetails;
  assert.equal(details.pushed, 1);
  assert.equal(details.held, 0);
  assert.deepEqual(details.skipped, []);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["POST"],
    "exactly the one re-push POST — no flush of a stale held queue",
  );
});

test("execute: POST success is the contract's 201 exactly — a non-201 2xx is push_rejected", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  // A 200-with-body answer is endpoint drift, not success — recording anchors against it would
  // suppress the retries drift needs to surface.
  endpoint.failNext("POST", 200, "drifted endpoint");
  const drifted = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(drifted.details.ok, false);
  const details = drifted.details as FailDetails;
  assert.equal(details.error_type, "push_rejected");
  assert.equal(details.status, 200);
  assert.equal(details.held, 0);
  // Nothing was recorded in the ledger: the same anchor re-pushes (and succeeds on a real 201).
  const repush = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((repush.details as OkDetails).pushed, 1);
  assert.deepEqual((repush.details as OkDetails).skipped, []);
});

test("execute: a network-failed pure clear stays a visible pending operation", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 1 });
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true);
  const heldClear = await executePushAnnotations(
    target,
    { angle: "tests", findings: [], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(heldClear.details.ok, true);
  const heldDetails = heldClear.details as OkDetails;
  assert.equal(heldDetails.held, 0, "a pure clear holds zero findings…");
  assert.equal(heldDetails.held_batches, 1, "…but IS a pending held operation");
  const prose = heldClear.content[0]?.text ?? "";
  assert.match(prose, /1 pending source clear\(s\)/);
  assert.match(prose, /findings: \[\] is the pure retry/);

  // The retry actually performs the clear.
  endpoint.setDown(false);
  endpoint.calls.length = 0;
  const retried = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  const retriedDetails = retried.details as OkDetails;
  assert.equal(retriedDetails.deleted, 1);
  assert.equal(retriedDetails.held_batches, 0);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE"],
  );
});

test("execute: a new batch never dedupes against a ledger entry a held clear is about to remove", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 1 });
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true);
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [], replace: true },
    { fetchLike: endpoint.fetchLike },
  ); // the clear is held; the ledger entry for line:src/a.ts:3 is now unstable
  endpoint.setDown(false);
  endpoint.calls.length = 0;

  // The server recovered; an ordinary batch re-supplies the anchor. The flush runs the clear
  // FIRST, then the new batch dedupes against the settled (cleared) ledger — the finding posts
  // instead of being silently lost to the stale entry.
  const repush = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  const details = repush.details as OkDetails;
  assert.equal(details.pushed, 1);
  assert.deepEqual(details.skipped, []);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE", "POST"],
    "the held clear flushes before the new batch is deduped/sent",
  );
});

test("execute: hold-time dedupe carves out sources with a pending held clear", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 1 });
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true);
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [], replace: true },
    { fetchLike: endpoint.fetchLike },
  ); // pending clear for perk:tests
  // Still down: another angle supplies the same anchor. The stale (unstable) ledger entry must
  // not veto it at hold time — it is held, then deduped for real at flush time.
  const heldCross = await executePushAnnotations(
    target,
    { angle: "quality", findings: [reviewFinding({ body: "quality's take" })] },
    { fetchLike: endpoint.fetchLike },
  );
  const heldDetails = heldCross.details as OkDetails;
  assert.equal(heldDetails.held, 1);
  assert.equal(heldDetails.held_batches, 2);
  assert.deepEqual(heldDetails.skipped, []);

  endpoint.setDown(false);
  endpoint.calls.length = 0;
  const flushed = await executePushAnnotations(
    target,
    { angle: "quality", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((flushed.details as OkDetails).pushed, 1);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE", "POST"],
  );
  const posted = endpoint.calls[1]?.body as { annotations: { source?: string }[] };
  assert.equal(posted.annotations[0]?.source, "perk:quality");
});

test("execute: cross-source duplicates in final batches are retained and promoted, never lost", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  // Streamed: tests owns anchor X.
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  // quality's FINAL batch also carries X: skipped (tests owns it) but RETAINED as a candidate.
  const qualityFinal = await executePushAnnotations(
    target,
    {
      angle: "quality",
      findings: [
        reviewFinding({ body: "quality's final take" }),
        reviewFinding({ path: "src/q.ts", line: 7 }),
      ],
      replace: true,
    },
    { fetchLike: endpoint.fetchLike },
  );
  assert.deepEqual((qualityFinal.details as OkDetails).skipped, ["line:src/a.ts:3"]);

  // tests' FINAL batch omits X: the replace releases the anchor and the retained quality
  // candidate is promoted in the same POST — the union of final batches survives the order.
  endpoint.calls.length = 0;
  const testsFinal = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding({ path: "src/t.ts", line: 9 })], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  const details = testsFinal.details as OkDetails;
  assert.equal(details.pushed, 2, "the angle's own finding + the promoted candidate");
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["DELETE", "POST"],
  );
  const posted = endpoint.calls[1]?.body as {
    annotations: { source?: string; text?: string }[];
  };
  assert.deepEqual(
    posted.annotations.map((a) => a.source),
    ["perk:tests", "perk:quality"],
    "the promoted candidate posts under ITS source",
  );
  assert.equal(posted.annotations[1]?.text, "[major/high] quality's final take");
  assert.match(testsFinal.content[0]?.text ?? "", /perk:quality: pushed 1/);

  // Ownership transferred: the anchor now dedupes against quality.
  const repush = await executePushAnnotations(
    target,
    { angle: "correctness", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.deepEqual((repush.details as OkDetails).skipped, ["line:src/a.ts:3"]);
});

test("execute: a DELETE HTTP rejection is push_rejected — the replace unit is dropped", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  endpoint.failNext("DELETE", 500, "boom");
  const result = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(result.details.ok, false);
  const details = result.details as FailDetails;
  assert.equal(details.error_type, "push_rejected");
  assert.equal(details.status, 500);
  assert.equal(details.dropped_source, "perk:tests");
  assert.equal(details.held, 0);
  // Nothing held: the pure retry makes no fetch.
  const idle = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(idle.details.ok, true);
  assert.equal(endpoint.calls.length, 1);
});

test("execute: a replace supersedes the angle's held work (units and items), sparing other sources", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint();
  endpoint.setDown(true);
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  ); // held: tests [X]
  await executePushAnnotations(
    target,
    { angle: "quality", findings: [reviewFinding({ path: "src/q.ts", line: 7 })] },
    { fetchLike: endpoint.fetchLike },
  ); // held: tests [X], quality [Q]
  const replaced = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding({ path: "src/t.ts", line: 9 })], replace: true },
    { fetchLike: endpoint.fetchLike },
  ); // tests' held batch superseded; quality's retained; the replace unit itself held
  const heldDetails = replaced.details as OkDetails;
  assert.equal(heldDetails.held, 2, "quality's finding + the replace unit's finding");
  assert.equal(heldDetails.held_batches, 2);

  endpoint.setDown(false);
  endpoint.calls.length = 0;
  const flushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((flushed.details as OkDetails).pushed, 2);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["POST", "DELETE", "POST"],
    "quality's held batch, then the replace unit (delete + post)",
  );
  const anchors = endpoint.calls
    .filter((c) => c.method === "POST")
    .flatMap((c) => (c.body as { annotations: { filePath?: string }[] }).annotations)
    .map((a) => a.filePath);
  assert.deepEqual(anchors, ["src/q.ts", "src/t.ts"], "the superseded finding never posts");
});

test("execute: a POST network failure after a successful DELETE holds only the post remainder", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { target } = fakeTarget();
  const endpoint = fakeEndpoint({ removed: 1 });
  await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding()] },
    { fetchLike: endpoint.fetchLike },
  );
  endpoint.setDown(true, "POST");
  const partial = await executePushAnnotations(
    target,
    { angle: "tests", findings: [reviewFinding({ body: "reconciled" })], replace: true },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal(partial.details.ok, true);
  const partialDetails = partial.details as OkDetails;
  assert.equal(partialDetails.deleted, 1, "the delete landed");
  assert.equal(partialDetails.held, 1);
  assert.equal(partialDetails.held_batches, 1);

  endpoint.setDown(false);
  endpoint.calls.length = 0;
  const flushed = await executePushAnnotations(
    target,
    { angle: "tests", findings: [] },
    { fetchLike: endpoint.fetchLike },
  );
  assert.equal((flushed.details as OkDetails).pushed, 1);
  assert.deepEqual(
    endpoint.calls.map((c) => c.method),
    ["POST"],
    "the landed delete is not replayed — only the post remainder was held",
  );
});

// --- registration --------------------------------------------------------------------------------

/** A captured-`registerTool` fake pi (the module never touches anything else at register time). */
function fakePi(): {
  pi: ExtensionAPI;
  tools: Map<string, { promptGuidelines?: string[]; executionMode?: string }>;
} {
  const tools = new Map<string, { promptGuidelines?: string[]; executionMode?: string }>();
  const pi = {
    registerTool(def: { name: string }) {
      tools.set(def.name, def as never);
    },
  } as unknown as ExtensionAPI;
  return { pi, tools };
}

test("registerAnnotationPushTool registers exactly the one tool and resets ALL module state", async () => {
  primeAnnotationSurface({ mode: "review", url: URL_BASE });
  const { pi, tools } = fakePi();
  registerAnnotationPushTool(pi);
  assert.deepEqual([...tools.keys()], ["push_annotations"]);
  const def = tools.get("push_annotations");
  // Sequential execution is load-bearing for the ledger ordering (dedupe reads-then-writes).
  assert.equal(def?.executionMode, "sequential");
  const guidelines = (def?.promptGuidelines ?? []).join("\n");
  assert.match(guidelines, /never compose annotation HTTP/);
  assert.match(guidelines, /untrusted DATA/);
  assert.match(guidelines, /replace: true/);
  assert.match(guidelines, /never a degrade/);

  // A fresh registration is a fresh session: the primed surface is gone.
  const { target } = fakeTarget();
  const result = await executePushAnnotations(target, { angle: "tests", findings: [] });
  assert.equal((result.details as FailDetails).error_type, "no_surface");
});

test("push_annotations is in the tool census (PERK_TOOLS + every worktree stage list)", () => {
  assert.ok(PERK_TOOLS.includes("push_annotations"));
  for (const stage of ["implement", "submit", "address", "land", "learn"]) {
    assert.ok(STAGE_TOOLS[stage]?.includes("push_annotations"), stage);
  }
});

// --- the registered tool end-to-end (real session, real ephemeral node:http server) -------------

/** A real 127.0.0.1 annotation endpoint proving the default-fetch wiring (offline-local). */
async function startAnnotationServer(): Promise<{
  url: string;
  requests: { method: string; url: string; body: string }[];
  close(): Promise<void>;
}> {
  const requests: { method: string; url: string; body: string }[] = [];
  let seq = 0;
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString("utf8");
    });
    req.on("end", () => {
      requests.push({ method: req.method ?? "", url: req.url ?? "", body });
      if (req.method === "POST") {
        const batch = JSON.parse(body) as { annotations: unknown[] };
        res.writeHead(201, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            ids: Array.from({ length: batch.annotations.length }, () => `srv-${++seq}`),
          }),
        );
        return;
      }
      if (req.method === "DELETE") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, removed: 1 }));
        return;
      }
      res.writeHead(404);
      res.end();
    });
  });
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    requests,
    close: () =>
      new Promise((resolve) => {
        server.close(() => resolve());
      }),
  };
}

test("tool: boundary refusals + one full round trip over the real default fetch", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  const server = await startAnnotationServer();
  try {
    // Unprimed: the loud no_surface refusal (registration reset any prior surface).
    const unprimed = await h.invokeTool("push_annotations", { angle: "tests", findings: [] });
    assert.equal((unprimed.details as FailDetails).error_type, "no_surface");

    primeAnnotationSurface({ mode: "review", url: server.url });

    // The boundary decode refusal (strict, whole-batch).
    const bad = await h.invokeTool("push_annotations", {
      angle: "tests",
      findings: [{ severity: "major", confidence: "high", body: "no path/line keys" }],
    });
    assert.equal((bad.details as FailDetails).error_type, "bad_input");
    assert.equal(server.requests.length, 0);

    // The round trip: default-fetch POST → 201 ids captured; replace → the DELETE query string.
    const pushed = await h.invokeTool("push_annotations", {
      angle: "demo",
      findings: [{ path: "src/a.ts", line: 3, severity: "major", confidence: "high", body: "b" }],
    });
    const pushedDetails = pushed.details as OkDetails;
    assert.equal(pushedDetails.ok, true);
    assert.deepEqual(pushedDetails.ids, ["srv-1"]);
    assert.equal(server.requests[0]?.method, "POST");
    assert.equal(server.requests[0]?.url, "/api/external-annotations");

    const cleared = await h.invokeTool("push_annotations", {
      angle: "demo",
      findings: [],
      replace: true,
    });
    assert.equal((cleared.details as OkDetails).deleted, 1);
    const del = server.requests[1];
    assert.equal(del?.method, "DELETE");
    const parsed = new URL(del?.url ?? "", server.url);
    assert.equal(parsed.pathname, "/api/external-annotations");
    assert.equal(parsed.searchParams.get("source"), "perk:demo");
  } finally {
    clearAnnotationSurface();
    await server.close();
    h.dispose();
  }
});
