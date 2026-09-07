import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type Attempt,
  type Consumption,
  type DraftReviewRecord,
  decisionDigest,
  decisionEncoding,
  decodeDraftReview,
  deliveryDigest,
  deliveryEncoding,
  deliveryEvidence,
  deliveryMarker,
  encodeDraftReview,
  INVALIDATION_REASONS,
  REVIEW_REFUSALS,
  type ReviewEvent,
  STATUS_DIAGNOSTICS,
  transitionDraftReview,
  UNCERTAINTY_REASONS,
} from "./draftReviewState.ts";
import { digestSessionData } from "./workflowSession.ts";

const requestId = "11111111-1111-4111-8111-111111111111";
const dispatchId = "22222222-2222-4222-8222-222222222222";
const digest = `sha256:${"a".repeat(64)}`;
const id = { requestId, reviewId: "review" };
const attemptId = { ...id, dispatchId };
function record(consumption: Consumption = { state: "pending" }): DraftReviewRecord {
  return {
    schema_version: 1,
    request_id: requestId,
    correlation: {
      review_id: consumption.state === "opening" ? null : "review",
      subject: "plan",
      source: { kind: "artifact" },
      source_digest: digest,
      target: { operation: "plan-save", digest },
    },
    consumption,
  };
}
function revision(): Extract<Attempt, { effect: "revision" | "stale-reference" }> {
  return {
    dispatch_id: dispatchId,
    decision_digest: digest,
    effect: "revision",
    save: { state: "not-required" },
    delivery: null,
  };
}
function withDelivery(): Attempt {
  return {
    ...revision(),
    delivery: {
      carrier: { kind: "tool", tool_call_id: "call" },
      marker: dispatchId,
      content_digest: digest,
    },
  };
}
const candidate: ReviewEvent = {
  kind: "candidate",
  id,
  match: "matching",
  dispatchId,
  decisionDigest: digest,
  effect: "save",
};
function next(prior: DraftReviewRecord | null, event: ReviewEvent): DraftReviewRecord | null {
  const result = transitionDraftReview(prior, event);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.ok(result.ok);
  return result.record;
}
function refusal(prior: DraftReviewRecord | null, event: ReviewEvent, reason: string) {
  const result = transitionDraftReview(prior, event);
  assert.equal(result.ok, false);
  assert.ok(!result.ok);
  assert.equal(result.reason, reason);
}

test("codec round-trips every consumption, reason, subject and source with owned nested trees", () => {
  const consumptions: Consumption[] = [
    { state: "opening" },
    { state: "pending" },
    { state: "dispatch", attempt: revision() },
    {
      state: "dispatch",
      attempt: { ...revision(), effect: "save", save: { state: "not-started" } },
    },
    { state: "dispatch", attempt: { ...revision(), effect: "save", save: { state: "started" } } },
    { state: "dispatch", attempt: { ...revision(), effect: "stale-reference" } },
    { state: "consumed", attempt: withDelivery(), delivery_entry_id: "entry" },
    {
      state: "consumed",
      attempt: {
        ...withDelivery(),
        effect: "save",
        save: { state: "confirmed", id: "42", url: "https://example/42" },
      },
      delivery_entry_id: "entry",
    },
    ...INVALIDATION_REASONS.map((reason) => ({ state: "invalidated" as const, reason })),
    ...UNCERTAINTY_REASONS.map((reason) => ({
      state: "uncertain" as const,
      reason,
      attempt: revision(),
    })),
  ];
  for (const c of consumptions) {
    const raw = record(c);
    if (
      c.state === "invalidated" &&
      (c.reason === "opening-aborted" || c.reason === "handshake-failed")
    )
      raw.correlation.review_id = null;
    const decoded = decodeDraftReview(raw);
    assert.deepEqual(decoded, raw);
    assert.notEqual(decoded, raw);
    assert.notEqual(decoded?.correlation.source, raw.correlation.source);
    assert.deepEqual(decodeDraftReview(JSON.parse(encodeDraftReview(raw))), raw);
  }
  for (const [subject, operation] of [
    ["plan", "plan-save"],
    ["objective", "objective-create"],
    ["gist", "gist-create"],
  ] as const) {
    const raw = record();
    raw.correlation.subject = subject;
    raw.correlation.target.operation = operation;
    assert.deepEqual(decodeDraftReview(raw), raw);
  }
  const raw = record();
  raw.correlation.source = { kind: "parameter", plan: " \n雪\n ", artifact_at_open: "absent" };
  raw.correlation.source_digest = digestSessionData(raw.correlation.source.plan);
  assert.deepEqual(decodeDraftReview(raw), raw);
});

test("codec rejects closed-key violations at every owned level, missing keys, getter failures and illegal combinations", () => {
  const base = record({
    state: "consumed",
    attempt: {
      ...withDelivery(),
      effect: "save",
      save: { state: "confirmed", id: "42", url: "url" },
    },
    delivery_entry_id: "entry",
  });
  const paths = [
    [],
    ["correlation"],
    ["correlation", "source"],
    ["correlation", "target"],
    ["consumption"],
    ["consumption", "attempt"],
    ["consumption", "attempt", "save"],
    ["consumption", "attempt", "delivery"],
    ["consumption", "attempt", "delivery", "carrier"],
  ];
  const at = (root: unknown, path: string[]): Record<string, unknown> => {
    let value = root as Record<string, unknown>;
    for (const key of path) value = value[key] as Record<string, unknown>;
    return value;
  };
  for (const path of paths) {
    const extra = structuredClone(base);
    at(extra, path).extra = true;
    assert.equal(decodeDraftReview(extra), null, `extra ${path}`);
    for (const key of Object.keys(at(base, path))) {
      const missing = structuredClone(base);
      delete at(missing, path)[key];
      assert.equal(decodeDraftReview(missing), null, `missing ${path}.${key}`);
    }
  }
  const invalid: unknown[] = [
    null,
    [],
    "{}",
    {},
    { ...base, schema_version: 2 },
    { ...base, request_id: "uuid" },
    {
      ...base,
      get correlation() {
        throw new Error("getter");
      },
    },
  ];
  for (const value of ["", " ", "sha256:ABC", `sha256:${"A".repeat(64)}`, "a".repeat(64)])
    invalid.push({ ...base, correlation: { ...base.correlation, source_digest: value } });
  invalid.push(
    { ...base, correlation: { ...base.correlation, subject: "gist" } },
    { ...base, correlation: { ...base.correlation, review_id: null } },
    { ...base, consumption: { state: "opening" } },
    record({ state: "consumed", attempt: revision(), delivery_entry_id: "entry" }),
    record({ state: "consumed", attempt: withDelivery(), delivery_entry_id: " " }),
    record({
      state: "dispatch",
      attempt: { ...withDelivery(), effect: "save", save: { state: "started" } },
    }),
    record({ state: "invalidated", reason: "opening-aborted" }),
    { ...base, consumption: { state: "invalidated", reason: "pending" } },
    { ...base, consumption: { state: "uncertain", reason: "busy", attempt: revision() } },
    {
      ...base,
      consumption: {
        state: "consumed",
        attempt: {
          ...withDelivery(),
          delivery: { carrier: { kind: "user" }, marker: dispatchId, content_digest: digest },
        },
        delivery_entry_id: "entry",
      },
    },
  );
  for (const [index, bad] of invalid.entries())
    assert.equal(decodeDraftReview(bad), null, `invalid case ${index}`);
  for (const subject of ["plan", "objective", "gist"] as const) {
    for (const plan of [" ", "text"]) {
      const raw = record();
      raw.correlation.subject = subject;
      raw.correlation.target.operation =
        subject === "plan"
          ? "plan-save"
          : subject === "objective"
            ? "objective-create"
            : "gist-create";
      raw.correlation.source = { kind: "parameter", plan, artifact_at_open: "absent" };
      assert.equal(decodeDraftReview(raw), null, "blank, wrong digest, or non-plan parameter");
    }
  }
});

test("explicit opening replacement table; uncertainty and dispatch never replace", () => {
  const opening = record({ state: "opening" });
  opening.request_id = dispatchId;
  for (const prior of [
    null,
    record({ state: "opening" }),
    record(),
    record({ state: "invalidated", reason: "degraded" }),
    record({ state: "consumed", attempt: withDelivery(), delivery_entry_id: "entry" }),
  ]) {
    assert.deepEqual(next(prior, { kind: "open", record: opening }), opening);
  }
  for (const prior of [
    record({ state: "dispatch", attempt: revision() }),
    record({ state: "uncertain", reason: "effect-failed", attempt: revision() }),
  ])
    refusal(prior, { kind: "open", record: opening }, "unresolved-dispatch");
  refusal(
    record({ state: "opening" }),
    { kind: "open", record: record({ state: "opening" }) },
    "invalid-state",
  );
});

test("attach, invalidation and mutation table covers all reasons and illegal predecessors", () => {
  const opening = record({ state: "opening" });
  for (const match of [
    "matching",
    "source-changed",
    "subject-changed",
    "target-changed",
  ] as const) {
    const result = next(opening, {
      kind: "attach",
      id: { requestId, reviewId: null },
      reviewId: "upstream",
      match,
    });
    assert.deepEqual(
      result?.consumption,
      match === "matching" ? { state: "pending" } : { state: "invalidated", reason: match },
    );
    assert.equal(result?.correlation.review_id, match === "matching" ? "upstream" : null);
  }
  for (const reason of INVALIDATION_REASONS) {
    for (const state of ["opening", "pending"] as const) {
      const prior = record({ state });
      const event: ReviewEvent = {
        kind: "invalidate",
        id: { requestId, reviewId: prior.correlation.review_id },
        reason,
      };
      if (
        (reason === "subscription-failed" && state === "opening") ||
        ((reason === "opening-aborted" || reason === "handshake-failed") && state === "pending")
      )
        refusal(prior, event, "invalid-state");
      else assert.deepEqual(next(prior, event)?.consumption, { state: "invalidated", reason });
    }
  }
  for (const reason of [
    "source-changed",
    "target-changed",
    "subject-changed",
    "degraded",
    "manual-save",
    "implement-here",
    "first-party-review",
  ] as const) {
    for (const state of ["opening", "pending"] as const)
      assert.deepEqual(next(record({ state }), { kind: "mutation", reason })?.consumption, {
        state: "invalidated",
        reason,
      });
  }
  const mutation: ReviewEvent = { kind: "mutation", reason: "source-changed" };
  for (const prior of [
    null,
    record({ state: "invalidated", reason: "manual-save" }),
    record({ state: "consumed", attempt: withDelivery(), delivery_entry_id: "entry" }),
  ])
    assert.deepEqual(next(prior, mutation), prior);
  assert.deepEqual(next(record(), { ...mutation, identical: true }), record());
  for (const c of [
    { state: "dispatch", attempt: revision() },
    { state: "uncertain", reason: "delivery-unconfirmed", attempt: revision() },
  ] as const)
    refusal(record(c), { ...mutation, identical: true }, "unresolved-dispatch");
});

test("candidate table: stale reference only with target/subject and known ID; consumed is a no-op", () => {
  for (const match of [
    "matching",
    "source-changed",
    "target-changed",
    "subject-changed",
  ] as const) {
    const r = next(record(), { ...candidate, match });
    if (match === "target-changed" || match === "subject-changed")
      assert.deepEqual(r?.consumption, { state: "invalidated", reason: match });
    else {
      assert.equal(r?.consumption.state, "dispatch");
      assert.ok(r?.consumption.state === "dispatch");
      assert.equal(r.consumption.attempt.effect, match === "matching" ? "save" : "stale-reference");
    }
  }
  for (const reason of INVALIDATION_REASONS) {
    const prior = record({ state: "invalidated", reason });
    if (reason === "opening-aborted" || reason === "handshake-failed")
      prior.correlation.review_id = null;
    const event = { ...candidate, id: { requestId, reviewId: prior.correlation.review_id } };
    if (reason === "source-changed") {
      const r = next(prior, event);
      assert.ok(r?.consumption.state === "dispatch");
      assert.equal(r.consumption.attempt.effect, "stale-reference");
      for (const match of ["target-changed", "subject-changed"] as const)
        refusal(prior, { ...event, match }, match);
      prior.correlation.review_id = null;
      refusal(prior, { ...candidate, id: { requestId, reviewId: null } }, "invalid-state");
    } else refusal(prior, event, "invalid-state");
  }
  const consumed = record({
    state: "consumed",
    attempt: withDelivery(),
    delivery_entry_id: "entry",
  });
  assert.deepEqual(next(consumed, candidate), consumed);
});

test("dispatch checkpoints are single-use, attempt-fenced, and completion never checks original binding", () => {
  let r = next(record(), candidate);
  assert.ok(r);
  refusal(
    r,
    { kind: "save-confirmed", id: attemptId, receipt: { id: "42", url: "url" } },
    "invalid-state",
  );
  refusal(r, { kind: "save-started", id: { ...attemptId, dispatchId: requestId } }, "superseded");
  r = next(r, { kind: "save-started", id: attemptId });
  assert.ok(r);
  refusal(r, { kind: "save-started", id: attemptId }, "invalid-state");
  r = next(r, { kind: "save-confirmed", id: attemptId, receipt: { id: "42", url: "url" } });
  assert.ok(r);
  refusal(r, { kind: "complete", id: attemptId, entryId: "entry" }, "invalid-state");
  const delivery = withDelivery().delivery;
  assert.ok(delivery);
  r = next(r, { kind: "expect-delivery", id: attemptId, delivery });
  assert.ok(r);
  refusal(r, { kind: "expect-delivery", id: attemptId, delivery }, "invalid-state");
  r.correlation.source_digest = `sha256:${"b".repeat(64)}`;
  r = next(r, { kind: "complete", id: attemptId, entryId: "entry" });
  assert.equal(r?.consumption.state, "consumed");
  for (const reason of UNCERTAINTY_REASONS) {
    const prior = record({ state: "dispatch", attempt: withDelivery() });
    const result = next(prior, { kind: "uncertain", id: attemptId, reason });
    assert.deepEqual(result?.consumption, { state: "uncertain", reason, attempt: withDelivery() });
    assert.ok(result);
    refusal(result, candidate, "unresolved-dispatch");
  }
});

test("request/review fences precede every identity-bearing event even at terminals", () => {
  const events: ReviewEvent[] = [
    candidate,
    { kind: "attach", id, reviewId: "new", match: "matching" },
    { kind: "invalidate", id, reason: "degraded" },
    { kind: "save-started", id: attemptId },
    { kind: "save-confirmed", id: attemptId, receipt: { id: "42", url: "url" } },
    { kind: "complete", id: attemptId, entryId: "entry" },
    { kind: "uncertain", id: attemptId, reason: "effect-failed" },
  ];
  const delivery = withDelivery().delivery;
  assert.ok(delivery);
  events.push({ kind: "expect-delivery", id: attemptId, delivery });
  for (const event of events) {
    assert.ok("id" in event);
    for (const c of [
      { state: "pending" },
      { state: "dispatch", attempt: revision() },
      { state: "uncertain", reason: "effect-failed", attempt: revision() },
      { state: "consumed", attempt: withDelivery(), delivery_entry_id: "entry" },
    ] as const) {
      const wrongRequest = structuredClone(event);
      wrongRequest.id.requestId = dispatchId;
      refusal(record(c), wrongRequest, "superseded");
      const wrongReview = structuredClone(event);
      wrongReview.id.reviewId = "other";
      refusal(record(c), wrongReview, "superseded");
    }
  }
});

test("closed diagnostic/refusal vocabularies are pinned independently", () => {
  assert.deepEqual(REVIEW_REFUSALS, [
    "no-identity",
    "busy",
    "invalid-state",
    "source-changed",
    "target-changed",
    "subject-changed",
    "superseded",
    "unresolved-dispatch",
    "persistence-failed",
    "ownership-lost",
    "io-error",
  ]);
  assert.deepEqual(STATUS_DIAGNOSTICS, [
    "pending",
    "missing",
    "unavailable",
    "malformed",
    "timeout",
    "transport-error",
  ]);
});

test("independent decision and delivery encoding vectors preserve Unicode and whitespace", () => {
  assert.equal(
    decisionEncoding(true, " \n雪\t "),
    'perk/draft-review-decision/v1\n{"approved":true,"feedback":" \\n雪\\t "}',
  );
  assert.equal(
    decisionEncoding(false),
    'perk/draft-review-decision/v1\n{"approved":false,"feedback":null}',
  );
  assert.equal(
    deliveryEncoding(" \n雪\t "),
    'perk/draft-review-delivery/v1\n[{"type":"text","text":" \\n雪\\t "}]',
  );
  assert.equal(
    deliveryEncoding([{ text: "雪", ignored: true, type: "text" }]),
    'perk/draft-review-delivery/v1\n[{"type":"text","text":"雪"}]',
  );
  assert.equal(deliveryDigest([{ type: "image", data: "x" }]), null);
  assert.throws(() => decisionDigest(true, " "));
  assert.equal(
    decisionDigest(false),
    "sha256:c345b744c8618a46f41d8da5edadef48b1525c198c135627c6a40c3568bc291b",
  );
  assert.equal(
    deliveryDigest(" \n雪\t "),
    "sha256:306fc8a58247797b94fa125a1808f62638b42a722b3b9e658f6032d5a6478234",
  );
});

test("delivery evidence requires persisted whole-content/role/tool/marker match, not callbacks or quotes", () => {
  const text = "review feedback";
  const content_digest = deliveryDigest(text);
  assert.ok(content_digest);
  const attempt: Attempt = {
    ...revision(),
    delivery: {
      carrier: { kind: "tool", tool_call_id: "call" },
      marker: dispatchId,
      content_digest,
    },
  };
  const tool = {
    type: "message",
    id: "entry",
    message: {
      role: "toolResult",
      toolName: "plan_review",
      toolCallId: "call",
      details: { draft_review_dispatch: dispatchId },
      content: [{ type: "text", text }],
    },
  };
  assert.equal(deliveryEvidence(attempt, [tool]), "entry");
  for (const message of [
    { ...tool.message, role: "assistant" },
    { ...tool.message, toolName: "other" },
    { ...tool.message, toolCallId: "other" },
    { ...tool.message, details: {} },
    { ...tool.message, content: `${text}!` },
    { ...tool.message, content: [{ type: "image", data: "x" }] },
  ])
    assert.equal(deliveryEvidence(attempt, [{ ...tool, message }]), null);
  assert.equal(deliveryEvidence(attempt, [{ ...tool, type: "message_end" }]), null);
  const marker = deliveryMarker({ kind: "user" }, dispatchId);
  const userText = `feedback\n${marker}`;
  const userDigest = deliveryDigest(userText);
  assert.ok(userDigest);
  const userAttempt: Attempt = {
    ...revision(),
    delivery: { carrier: { kind: "user" }, marker, content_digest: userDigest },
  };
  assert.equal(
    deliveryEvidence(userAttempt, [
      { type: "message", id: "user", message: { role: "user", content: userText } },
    ]),
    "user",
  );
  assert.equal(
    deliveryEvidence(userAttempt, [
      { type: "message", id: "quoted", message: { role: "assistant", content: userText } },
    ]),
    null,
  );
});
