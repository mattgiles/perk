// Closed persistence and transition vocabulary. The Pi adapter owns exclusion and effects;
// a reducer result alone is never authority to save or deliver (contracts.md §8.23).
import { digestSessionData, type WorkflowSession } from "./workflowSession.ts";

export const DRAFT_REVIEW_ARTIFACT = "draft-review.json";
export const INVALIDATION_REASONS = [
  "opening-aborted",
  "handshake-failed",
  "subscription-failed",
  "source-changed",
  "target-changed",
  "subject-changed",
  "degraded",
  "manual-save",
  "implement-here",
  "first-party-review",
] as const;
export const UNCERTAINTY_REASONS = [
  "aborted-after-intent",
  "backend-unconfirmed",
  "delivery-unconfirmed",
  "effect-failed",
] as const;
export const REVIEW_REFUSALS = [
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
] as const;
export const STATUS_DIAGNOSTICS = [
  "pending",
  "missing",
  "unavailable",
  "malformed",
  "timeout",
  "transport-error",
] as const;
export type InvalidationReason = (typeof INVALIDATION_REASONS)[number];
export type UncertaintyReason = (typeof UNCERTAINTY_REASONS)[number];
export type ReviewRefusal = (typeof REVIEW_REFUSALS)[number];
export type StatusDiagnostic = (typeof STATUS_DIAGNOSTICS)[number];
export type ReviewSubject = "plan" | "objective" | "gist";
export const REVIEW_OPERATIONS = {
  plan: "plan-save",
  objective: "objective-create",
  gist: "gist-create",
} as const;
export type ReviewSource =
  | { kind: "artifact" }
  | { kind: "parameter"; plan: string; artifact_at_open: "absent" };
export type DeliveryCarrier = { kind: "tool"; tool_call_id: string } | { kind: "user" };
export type DeliveryExpectation = {
  carrier: DeliveryCarrier;
  marker: string;
  content_digest: string;
};
export type SaveReceipt = { id: string; url: string };
export type Attempt = {
  dispatch_id: string;
  decision_digest: string;
  delivery: DeliveryExpectation | null;
} & (
  | { effect: "revision" | "stale-reference"; save: { state: "not-required" } }
  | {
      effect: "save";
      save:
        | { state: "not-started" }
        | { state: "started" }
        | ({ state: "confirmed" } & SaveReceipt);
    }
);
export type Consumption =
  | { state: "opening" }
  | { state: "pending" }
  | { state: "invalidated"; reason: InvalidationReason }
  | { state: "dispatch"; attempt: Attempt }
  | { state: "consumed"; attempt: Attempt; delivery_entry_id: string }
  | { state: "uncertain"; reason: UncertaintyReason; attempt: Attempt };
export type DraftReviewRecord = {
  schema_version: 1;
  request_id: string;
  correlation: {
    review_id: string | null;
    subject: ReviewSubject;
    source: ReviewSource;
    source_digest: string;
    target: { operation: (typeof REVIEW_OPERATIONS)[ReviewSubject]; digest: string };
  };
  consumption: Consumption;
};
export type ReviewIdentity = { requestId: string; reviewId: string | null };
export type AttemptIdentity = ReviewIdentity & { dispatchId: string };
export type RegistrationResult =
  | { ok: true }
  | { ok: false; reason: ReviewRefusal; detail: string };
export interface DraftReviewRegistration {
  open(requestId: string): RegistrationResult;
  attach(requestId: string, reviewId: string): RegistrationResult;
  invalidateOpening(
    requestId: string,
    reason: "opening-aborted" | "handshake-failed",
  ): RegistrationResult;
  subscriptionFailed(requestId: string, reviewId: string): RegistrationResult;
  diagnostic(code: StatusDiagnostic, detail: string): void;
}

export function reviewRefused(reason: ReviewRefusal): Extract<RegistrationResult, { ok: false }> {
  return { ok: false, reason, detail: `draft review refused: ${reason}` };
}
export function isNonblank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
export function isReviewDigest(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}
export function isReviewUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  );
}
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("object required");
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: string[]): void {
  const actual = Object.keys(value);
  if (actual.length !== expected.length || expected.some((key) => !Object.hasOwn(value, key)))
    throw new Error("closed keys required");
}
function string(value: unknown): string {
  if (!isNonblank(value)) throw new Error("nonblank string required");
  return value;
}
function digest(value: unknown): string {
  if (!isReviewDigest(value)) throw new Error("digest required");
  return value;
}
function uuid(value: unknown): string {
  if (!isReviewUuid(value)) throw new Error("UUID required");
  return value;
}
function member<T extends string>(value: unknown, vocabulary: readonly T[]): T {
  for (const item of vocabulary) if (value === item) return item;
  throw new Error("unknown variant");
}
function sourceOf(raw: unknown): ReviewSource {
  const r = object(raw);
  if (r.kind === "artifact") {
    keys(r, ["kind"]);
    return { kind: "artifact" };
  }
  keys(r, ["kind", "plan", "artifact_at_open"]);
  if (r.kind !== "parameter" || r.artifact_at_open !== "absent") throw new Error("invalid source");
  return { kind: "parameter", plan: string(r.plan), artifact_at_open: "absent" };
}
function deliveryOf(raw: unknown, dispatchId: string): DeliveryExpectation | null {
  if (raw === null) return null;
  const r = object(raw);
  keys(r, ["carrier", "marker", "content_digest"]);
  const c = object(r.carrier);
  let carrier: DeliveryCarrier;
  if (c.kind === "user") {
    keys(c, ["kind"]);
    carrier = { kind: "user" };
  } else {
    keys(c, ["kind", "tool_call_id"]);
    if (c.kind !== "tool") throw new Error("invalid carrier");
    carrier = { kind: "tool", tool_call_id: string(c.tool_call_id) };
  }
  if (r.marker !== deliveryMarker(carrier, dispatchId)) throw new Error("invalid marker");
  return { carrier, marker: r.marker, content_digest: digest(r.content_digest) };
}
function attemptOf(raw: unknown): Attempt {
  const r = object(raw);
  keys(r, ["dispatch_id", "decision_digest", "effect", "save", "delivery"]);
  const dispatch_id = uuid(r.dispatch_id);
  const base = {
    dispatch_id,
    decision_digest: digest(r.decision_digest),
    delivery: deliveryOf(r.delivery, dispatch_id),
  };
  const s = object(r.save);
  if (r.effect === "revision" || r.effect === "stale-reference") {
    keys(s, ["state"]);
    if (s.state !== "not-required") throw new Error("save forbidden");
    return { ...base, effect: r.effect, save: { state: "not-required" } };
  }
  if (r.effect !== "save") throw new Error("invalid effect");
  if (s.state === "confirmed") {
    keys(s, ["state", "id", "url"]);
    return {
      ...base,
      effect: "save",
      save: { state: "confirmed", id: string(s.id), url: string(s.url) },
    };
  }
  keys(s, ["state"]);
  if (base.delivery !== null) throw new Error("delivery before save confirmation");
  return { ...base, effect: "save", save: { state: member(s.state, ["not-started", "started"]) } };
}
function consumptionOf(raw: unknown): Consumption {
  const c = object(raw);
  if (c.state === "opening" || c.state === "pending") {
    keys(c, ["state"]);
    return { state: c.state };
  }
  if (c.state === "invalidated") {
    keys(c, ["state", "reason"]);
    return { state: "invalidated", reason: member(c.reason, INVALIDATION_REASONS) };
  }
  if (c.state === "dispatch") {
    keys(c, ["state", "attempt"]);
    return { state: "dispatch", attempt: attemptOf(c.attempt) };
  }
  if (c.state === "uncertain") {
    keys(c, ["state", "reason", "attempt"]);
    return {
      state: "uncertain",
      reason: member(c.reason, UNCERTAINTY_REASONS),
      attempt: attemptOf(c.attempt),
    };
  }
  if (c.state !== "consumed") throw new Error("invalid consumption");
  keys(c, ["state", "attempt", "delivery_entry_id"]);
  const attempt = attemptOf(c.attempt);
  if (!canComplete(attempt)) throw new Error("completion lacks proof");
  return { state: "consumed", attempt, delivery_entry_id: string(c.delivery_entry_id) };
}
/** A fresh owned tree, or null; getters and malformed input are contained at this boundary. */
export function decodeDraftReview(raw: unknown): DraftReviewRecord | null {
  try {
    const r = object(raw);
    keys(r, ["schema_version", "request_id", "correlation", "consumption"]);
    if (r.schema_version !== 1) return null;
    const c = object(r.correlation);
    keys(c, ["review_id", "subject", "source", "source_digest", "target"]);
    const subject = member(c.subject, ["plan", "objective", "gist"]);
    const source = sourceOf(c.source);
    const source_digest = digest(c.source_digest);
    if (
      source.kind === "parameter" &&
      (subject !== "plan" || digestSessionData(source.plan) !== source_digest)
    )
      return null;
    const target = object(c.target);
    keys(target, ["operation", "digest"]);
    if (target.operation !== REVIEW_OPERATIONS[subject]) return null;
    const review_id = c.review_id === null ? null : string(c.review_id);
    const consumption = consumptionOf(r.consumption);
    if (
      consumption.state === "opening"
        ? review_id !== null
        : consumption.state !== "invalidated" && review_id === null
    )
      return null;
    if (consumption.state === "invalidated") {
      if (
        (consumption.reason === "opening-aborted" || consumption.reason === "handshake-failed") &&
        review_id !== null
      )
        return null;
      if (consumption.reason === "subscription-failed" && review_id === null) return null;
    }
    return {
      schema_version: 1,
      request_id: uuid(r.request_id),
      correlation: {
        review_id,
        subject,
        source,
        source_digest,
        target: { operation: REVIEW_OPERATIONS[subject], digest: digest(target.digest) },
      },
      consumption,
    };
  } catch {
    return null;
  }
}
export function encodeDraftReview(record: DraftReviewRecord): string {
  const owned = decodeDraftReview(record);
  if (owned === null) throw new Error("invalid draft review record");
  return `${JSON.stringify(owned)}\n`;
}
export function readDraftReview(
  session: WorkflowSession,
): { ok: true; record: DraftReviewRecord | null } | Extract<RegistrationResult, { ok: false }> {
  try {
    const read = session.readArtifact(DRAFT_REVIEW_ARTIFACT, { provenance: "strict" });
    if (read.status === "absent") return { ok: true, record: null };
    if (read.status === "invalid") return reviewRefused("invalid-state");
    const record = decodeDraftReview(JSON.parse(read.content));
    return record === null ? reviewRefused("invalid-state") : { ok: true, record };
  } catch {
    return reviewRefused("invalid-state");
  }
}
export function sameReview(record: DraftReviewRecord, id: ReviewIdentity): boolean {
  return record.request_id === id.requestId && record.correlation.review_id === id.reviewId;
}
function canComplete(attempt: Attempt): boolean {
  return (
    attempt.delivery !== null &&
    (attempt.save.state === "confirmed" || attempt.save.state === "not-required")
  );
}
export type BindingMatch = "matching" | "source-changed" | "target-changed" | "subject-changed";
export type ReviewEvent =
  | { kind: "open"; record: DraftReviewRecord }
  | { kind: "attach"; id: ReviewIdentity; reviewId: string; match: BindingMatch }
  | { kind: "invalidate"; id: ReviewIdentity; reason: InvalidationReason }
  | {
      kind: "candidate";
      id: ReviewIdentity;
      match: BindingMatch;
      dispatchId: string;
      decisionDigest: string;
      effect: "save" | "revision";
    }
  | { kind: "save-started"; id: AttemptIdentity }
  | { kind: "save-confirmed"; id: AttemptIdentity; receipt: SaveReceipt }
  | { kind: "expect-delivery"; id: AttemptIdentity; delivery: DeliveryExpectation }
  | { kind: "complete"; id: AttemptIdentity; entryId: string }
  | { kind: "uncertain"; id: AttemptIdentity; reason: UncertaintyReason }
  | {
      kind: "mutation";
      reason: Exclude<
        InvalidationReason,
        "opening-aborted" | "handshake-failed" | "subscription-failed"
      >;
      identical?: boolean;
    };
export type ReviewTransition =
  | { ok: true; record: DraftReviewRecord | null; changed: boolean }
  | Extract<RegistrationResult, { ok: false }>;
/** Pure transition table. Callers must strict-read under exclusion and VERIFY its replacement. */
export function transitionDraftReview(
  prior: DraftReviewRecord | null,
  event: ReviewEvent,
): ReviewTransition {
  const result = (next: DraftReviewRecord | null, changed: boolean): ReviewTransition => {
    const record = next === null ? null : decodeDraftReview(next);
    return next !== null && record === null
      ? reviewRefused("invalid-state")
      : { ok: true, record, changed };
  };
  const unchanged = () => result(prior, false);
  if (prior !== null && decodeDraftReview(prior) === null) return reviewRefused("invalid-state");
  if ("id" in event && (prior === null || !sameReview(prior, event.id)))
    return reviewRefused("superseded");
  const c = prior?.consumption;
  if (event.kind === "open") {
    if (c?.state === "dispatch" || c?.state === "uncertain")
      return reviewRefused("unresolved-dispatch");
    if (
      event.record.consumption.state !== "opening" ||
      event.record.request_id === prior?.request_id
    )
      return reviewRefused("invalid-state");
    return result(event.record, true);
  }
  if (c?.state === "uncertain") return reviewRefused("unresolved-dispatch");
  if (event.kind === "mutation") {
    if (c?.state === "dispatch") return reviewRefused("unresolved-dispatch");
    if (prior === null || c?.state === "consumed" || c?.state === "invalidated" || event.identical)
      return unchanged();
    return result({ ...prior, consumption: { state: "invalidated", reason: event.reason } }, true);
  }
  if (prior === null || c === undefined) return reviewRefused("superseded");
  const update = (consumption: Consumption) => result({ ...prior, consumption }, true);
  if (event.kind === "attach") {
    if (c.state !== "opening" || !isNonblank(event.reviewId)) return reviewRefused("invalid-state");
    if (event.match !== "matching") return update({ state: "invalidated", reason: event.match });
    return result(
      {
        ...prior,
        correlation: { ...prior.correlation, review_id: event.reviewId },
        consumption: { state: "pending" },
      },
      true,
    );
  }
  if (event.kind === "invalidate") {
    if (c.state === "dispatch") return reviewRefused("unresolved-dispatch");
    if (c.state !== "opening" && c.state !== "pending") return reviewRefused("invalid-state");
    if (
      (event.reason === "opening-aborted" || event.reason === "handshake-failed") &&
      c.state !== "opening"
    )
      return reviewRefused("invalid-state");
    if (event.reason === "subscription-failed" && c.state !== "pending")
      return reviewRefused("invalid-state");
    return update({ state: "invalidated", reason: event.reason });
  }
  if (event.kind === "candidate") {
    if (c.state === "consumed") return unchanged();
    if (c.state === "dispatch") return reviewRefused("unresolved-dispatch");
    const reference =
      c.state === "invalidated" &&
      c.reason === "source-changed" &&
      prior.correlation.review_id !== null;
    if (c.state !== "pending" && !reference) return reviewRefused("invalid-state");
    if (event.match === "subject-changed" || event.match === "target-changed") {
      return c.state === "pending"
        ? update({ state: "invalidated", reason: event.match })
        : reviewRefused(event.match);
    }
    const effect = reference || event.match === "source-changed" ? "stale-reference" : event.effect;
    const base = {
      dispatch_id: event.dispatchId,
      decision_digest: event.decisionDigest,
      delivery: null,
    };
    const attempt: Attempt =
      effect === "save"
        ? { ...base, effect, save: { state: "not-started" } }
        : { ...base, effect, save: { state: "not-required" } };
    return update({ state: "dispatch", attempt });
  }
  if (
    !("dispatchId" in event.id) ||
    !("attempt" in c) ||
    c.attempt.dispatch_id !== event.id.dispatchId
  )
    return reviewRefused("superseded");
  if (c.state !== "dispatch") return reviewRefused("invalid-state");
  const attempt = c.attempt;
  switch (event.kind) {
    case "save-started":
      if (
        attempt.effect !== "save" ||
        attempt.save.state !== "not-started" ||
        attempt.delivery !== null
      )
        return reviewRefused("invalid-state");
      return update({ state: "dispatch", attempt: { ...attempt, save: { state: "started" } } });
    case "save-confirmed":
      if (attempt.effect !== "save" || attempt.save.state !== "started")
        return reviewRefused("invalid-state");
      return update({
        state: "dispatch",
        attempt: {
          ...attempt,
          save: { state: "confirmed", id: event.receipt.id, url: event.receipt.url },
        },
      });
    case "expect-delivery":
      if (
        attempt.delivery !== null ||
        (attempt.save.state !== "confirmed" && attempt.save.state !== "not-required")
      )
        return reviewRefused("invalid-state");
      return update({ state: "dispatch", attempt: { ...attempt, delivery: event.delivery } });
    case "complete":
      if (!canComplete(attempt)) return reviewRefused("invalid-state");
      return update({ state: "consumed", attempt, delivery_entry_id: event.entryId });
    case "uncertain":
      return update({ state: "uncertain", reason: event.reason, attempt });
  }
}

export function decisionEncoding(approved: boolean, feedback?: string | null): string {
  if (typeof approved !== "boolean" || (feedback != null && !isNonblank(feedback)))
    throw new Error("invalid decision");
  return `perk/draft-review-decision/v1\n${JSON.stringify({ approved, feedback: feedback ?? null })}`;
}
export function decisionDigest(approved: boolean, feedback?: string | null): string {
  return digestSessionData(decisionEncoding(approved, feedback));
}
export function deliveryMarker(carrier: DeliveryCarrier, dispatchId: string): string {
  return carrier.kind === "tool" ? dispatchId : `<!-- perk:draft-review-dispatch:${dispatchId} -->`;
}
/** Nontext blocks cannot acknowledge. Rebuild text keys, preserving byte and block order. */
export function deliveryEncoding(content: unknown): string | null {
  try {
    const blocks = typeof content === "string" ? [{ type: "text", text: content }] : content;
    if (!Array.isArray(blocks)) return null;
    const texts: { type: "text"; text: string }[] = [];
    for (const raw of blocks) {
      const block = object(raw);
      if (block.type !== "text" || typeof block.text !== "string") return null;
      texts.push({ type: "text", text: block.text });
    }
    return `perk/draft-review-delivery/v1\n${JSON.stringify(texts)}`;
  } catch {
    return null;
  }
}
export function deliveryDigest(content: unknown): string | null {
  const encoding = deliveryEncoding(content);
  return encoding === null ? null : digestSessionData(encoding);
}
/** Only persisted branch entries supplied by the adapter; callbacks are not receipts. */
export function deliveryEvidence(attempt: Attempt, entries: readonly unknown[]): string | null {
  if (attempt.delivery === null) return null;
  const expected = attempt.delivery;
  for (const entry of entries) {
    try {
      const e = object(entry);
      if (e.type !== "message" || !isNonblank(e.id)) continue;
      const m = object(e.message);
      if (deliveryDigest(m.content) !== expected.content_digest) continue;
      if (expected.carrier.kind === "tool") {
        if (
          m.role !== "toolResult" ||
          m.toolName !== "plan_review" ||
          m.toolCallId !== expected.carrier.tool_call_id ||
          object(m.details).draft_review_dispatch !== expected.marker
        )
          continue;
      } else {
        if (m.role !== "user") continue;
        const encoding = deliveryEncoding(m.content);
        // Digest already proves the whole text; the exact code-authored marker must also occur.
        if (encoding === null || !encoding.includes(expected.marker)) continue;
      }
      return e.id;
    } catch {
      /* An unrelated malformed entry is never evidence. */
    }
  }
  return null;
}
