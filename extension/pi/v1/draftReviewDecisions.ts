// Claim-bound orchestration only. Provider registration, feature entry points, and Pi lifecycle
// wiring intentionally remain separate; constructing this object performs no discovery/replay.
import { randomUUID } from "node:crypto";
import {
  decodeGistDraft,
  GIST_DRAFT_ARTIFACT,
  renderGistDraft,
} from "../../authoring/gist/draft.ts";
import {
  decodeObjectiveDraft,
  OBJECTIVE_DRAFT_ARTIFACT,
  renderObjectiveDraft,
} from "../../authoring/objective/draft.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import {
  captureDraftReviewBinding,
  type DraftReviewBinding,
} from "../../session/draftReviewBinding.ts";
import {
  type AttemptIdentity,
  type BindingMatch,
  type DeliveryCarrier,
  DRAFT_REVIEW_ARTIFACT,
  type DraftReviewRecord,
  type DraftReviewRegistration,
  decisionDigest,
  deliveryDigest,
  deliveryEvidence,
  deliveryMarker,
  encodeDraftReview,
  isNonblank,
  REVIEW_OPERATIONS,
  type RegistrationResult,
  type ReviewEvent,
  type ReviewIdentity,
  type ReviewSource,
  type ReviewSubject,
  readDraftReview,
  reviewRefused,
  type SaveReceipt,
  type StatusDiagnostic,
  sameReview,
  transitionDraftReview,
  type UncertaintyReason,
} from "../../session/draftReviewState.ts";
import {
  digestSessionData,
  type WorkflowChange,
  type WorkflowChangeResult,
  type WorkflowSession,
  type WriteArtifactResult,
} from "../../session/workflowSession.ts";
import {
  acquireDraftReviewLock,
  type DraftReviewAcquisition,
} from "../../substrate/draftReviewLock.ts";
import type { ExclusiveFileClaim } from "../../substrate/exclusiveFileClaim.ts";

type Refused = Extract<RegistrationResult, { ok: false }>;
export type DraftReviewOperation<T> = { ok: true; value: T } | Refused;
type Outcome<T> = DraftReviewOperation<T>;
const artifactNames = {
  plan: PLAN_DRAFT_ARTIFACT,
  objective: OBJECTIVE_DRAFT_ARTIFACT,
  gist: GIST_DRAFT_ARTIFACT,
} as const;
export type DraftReviewSnapshot = {
  source: ReviewSource;
  raw: string;
  markdown: string;
  sourceDigest: string;
  binding: DraftReviewBinding;
};
function sourceSnapshot(
  session: WorkflowSession,
  subject: ReviewSubject,
  parameter?: string,
): Outcome<Omit<DraftReviewSnapshot, "binding">> {
  const read = session.readArtifact(artifactNames[subject], { provenance: "strict" });
  if (read.status === "invalid") return reviewRefused("invalid-state");
  if (read.status === "absent") {
    if (subject !== "plan" || !isNonblank(parameter)) return reviewRefused("source-changed");
    return {
      ok: true,
      value: {
        source: { kind: "parameter", plan: parameter, artifact_at_open: "absent" },
        raw: parameter,
        markdown: parameter,
        sourceDigest: digestSessionData(parameter),
      },
    };
  }
  const raw = read.content;
  let markdown: string;
  if (subject === "objective") {
    const decoded = decodeObjectiveDraft(raw);
    if (decoded.kind !== "valid") return reviewRefused("invalid-state");
    markdown = renderObjectiveDraft(decoded.draft);
  } else if (subject === "gist") {
    const decoded = decodeGistDraft(raw);
    if (!decoded.ok) return reviewRefused("invalid-state");
    markdown = renderGistDraft(decoded.draft);
  } else {
    if (!isNonblank(raw)) return reviewRefused("source-changed");
    markdown = raw;
  }
  return {
    ok: true,
    value: { source: { kind: "artifact" }, raw, markdown, sourceDigest: digestSessionData(raw) },
  };
}
export interface DraftReviewDecisionDeps {
  cwd: string;
  sessionId: string;
  /** Re-open against the live branch, never a cached workflow-state/pointer snapshot. */
  session(): WorkflowSession;
  /** Persisted active-branch entries, not message_end events or injection spies. */
  entries(): readonly unknown[];
  binding?: (session: WorkflowSession) => ReturnType<typeof captureDraftReviewBinding>;
  acquire?: (runId: string, requestId: string) => DraftReviewAcquisition;
  diagnostic?: (code: StatusDiagnostic, detail: string) => void;
}
class ReviewStop extends Error {
  readonly refusal: Refused;
  constructor(refusal: Refused) {
    super(refusal.detail);
    this.refusal = refusal;
  }
}
function stop(reason: Parameters<typeof reviewRefused>[0]): never {
  throw new ReviewStop(reviewRefused(reason));
}

/** Minted only inside a verified dispatch; all methods fence the same run/record/attempt.
 * Do not retain this capability beyond the callback. No reentrant acquisition is necessary.
 */
export interface DraftReviewCapability {
  readonly dispatchId: string;
  readonly effect: "save" | "revision" | "stale-reference";
  /** One owned plan patch. Failure selects ONLY the frozen original, not artifact-first fallback. */
  writePlan(content: string): WriteArtifactResult;
  /** Save linkage only, not a competing authoring/routing operation. */
  apply(
    change: Extract<
      WorkflowChange,
      { kind: "link-plan-ref" | "link-objective" | "clear-node-claim" }
    >,
  ): WorkflowChangeResult;
  /** Call after title generation/other awaits. Records started immediately before invocation. */
  save<T>(
    invoke: (bound: {
      source: string;
      warmNodeClaim: DraftReviewBinding["warmNodeClaim"];
    }) => Promise<{ receipt: SaveReceipt | null; value: T }>,
    /** Preserve definitive gate facts before fallible receipt bookkeeping. Never invokes the backend. */
    onReceipt?: (receipt: SaveReceipt) => { gateExited: boolean } | undefined,
  ): Promise<T>;
  /** Checkpoint before tool return/user send. The optional send must be synchronous and attempted once. */
  deliver(carrier: DeliveryCarrier, content: unknown, send?: () => void): void;
}

/** No state/effects at construction; current-activation delivery expectations live only here. */
export function createDraftReviewDecisions(deps: DraftReviewDecisionDeps) {
  const binding = (session: WorkflowSession) =>
    deps.binding?.(session) ?? captureDraftReviewBinding(deps.cwd, session);
  const expectations = new Map<string, { id: AttemptIdentity; runId: string }>();
  let ended = false;

  function acquire(requestId: string, expectedRun?: string) {
    if (ended) stop("invalid-state");
    const context = deps.session().currentRunIdentity();
    if (!context.ok) stop(context.reason);
    if (expectedRun !== undefined && context.runId !== expectedRun) stop("superseded");
    const runId = context.runId;
    const acquired =
      deps.acquire?.(runId, requestId) ??
      acquireDraftReviewLock(deps.cwd, { sessionId: deps.sessionId, runId, requestId });
    if (acquired.kind === "busy") {
      const refusal = reviewRefused("busy");
      const owner = acquired.owner;
      throw new ReviewStop({
        ...refusal,
        detail:
          owner === undefined
            ? refusal.detail
            : `${refusal.detail}; incumbent metadata only: run ${JSON.stringify(owner.ownerRunId)}, request ${JSON.stringify(owner.requestId)} (not proof of effects)`,
      });
    }
    if (acquired.kind === "io-error") stop("io-error");
    if (acquired.kind === "unavailable")
      stop(acquired.reason === "no-identity" ? "no-identity" : "io-error");
    return held(acquired.claim, runId);
  }
  function held(claim: ExclusiveFileClaim, runId: string) {
    let failure: Refused | null = null;
    let closed = false;
    let phase = "strict-read";
    const poison = (reason: Refused["reason"]): never => {
      failure ??= {
        ...reviewRefused(reason),
        detail: `${reviewRefused(reason).detail}; checkpoint: ${phase}`,
      };
      throw new ReviewStop(failure);
    };
    const check = (): WorkflowSession => {
      if (failure !== null) throw new ReviewStop(failure);
      if (ended) return poison("ownership-lost");
      if (closed) stop("ownership-lost");
      const ownership = claim.check();
      if (ownership !== "owned")
        return poison(ownership === "ownership-error" ? "ownership-lost" : "io-error");
      try {
        const session = deps.session();
        const current = session.currentRunIdentity();
        if (!current.ok || current.runId !== runId) return poison("ownership-lost");
        return session;
      } catch (error) {
        if (error instanceof ReviewStop) throw error;
        return poison("ownership-lost");
      }
    };
    const read = (): DraftReviewRecord | null => {
      const loaded = readDraftReview(check());
      if (!loaded.ok) return poison(loaded.reason);
      return loaded.record;
    };
    const transition = (event: ReviewEvent) => {
      phase = event.kind;
      const prior = read();
      const next = transitionDraftReview(prior, event);
      if (!next.ok) throw new ReviewStop(next);
      if (next.changed && next.record !== null) {
        try {
          const session = check();
          const written = session.writeArtifact(
            DRAFT_REVIEW_ARTIFACT,
            encodeDraftReview(next.record),
            { provenance: "strict" },
          );
          if (written.status !== "applied" && written.status !== "unchanged")
            return poison("persistence-failed");
          check();
          const verified = readDraftReview(check());
          if (
            !verified.ok ||
            verified.record === null ||
            encodeDraftReview(verified.record) !== encodeDraftReview(next.record)
          )
            return poison("persistence-failed");
        } catch (error) {
          if (error instanceof ReviewStop) throw error;
          return poison("persistence-failed");
        }
      }
      return next.record;
    };
    return {
      check,
      read,
      transition,
      poison,
      get failed() {
        return failure !== null;
      },
      get released() {
        return closed;
      },
      finish() {
        if (closed) {
          if (failure !== null) throw new ReviewStop(failure);
          return;
        }
        closed = true;
        const result = claim.finish(failure === null ? "release" : "retain");
        if (failure !== null) throw new ReviewStop(failure);
        if (result.kind === "ownership-error") poison("ownership-lost");
        if (result.kind === "io-error") poison("io-error");
      },
    };
  }
  type Held = ReturnType<typeof held>;
  // A lifecycle stop uses this existing claim-bound capability, never reentrant acquisition.
  let activeDispatch: { owned: Held; id: AttemptIdentity } | undefined;
  function caught(error: unknown): Refused {
    return error instanceof ReviewStop ? error.refusal : reviewRefused("io-error");
  }
  function sync<T>(requestId: string, work: (owned: Held) => T, runId?: string): Outcome<T> {
    let owned: Held | undefined;
    let outcome: Outcome<T>;
    try {
      owned = acquire(requestId, runId);
      outcome = { ok: true, value: work(owned) };
    } catch (error) {
      outcome = caught(error);
    } finally {
      if (owned !== undefined) {
        try {
          owned.finish();
        } catch (error) {
          outcome = caught(error);
        }
      }
    }
    return outcome;
  }
  function currentMatch(owned: Held, record: DraftReviewRecord): BindingMatch {
    const captured = binding(owned.check());
    if (!captured.ok) throw new ReviewStop(captured);
    if (captured.binding.subject !== record.correlation.subject) return "subject-changed";
    if (captured.binding.digest !== record.correlation.target.digest) return "target-changed";
    const source = record.correlation.source;
    const read = owned
      .check()
      .readArtifact(artifactNames[record.correlation.subject], { provenance: "strict" });
    if (read.status === "invalid") return owned.poison("invalid-state");
    if (source.kind === "parameter")
      return read.status === "absent" ? "matching" : "source-changed";
    return read.status === "found" &&
      digestSessionData(read.content) === record.correlation.source_digest
      ? "matching"
      : "source-changed";
  }
  function expected(owned: Held, id: ReviewIdentity): DraftReviewRecord {
    const record = owned.read();
    if (record === null || !sameReview(record, id)) stop("superseded");
    return record;
  }
  function attempt(owned: Held, id: AttemptIdentity) {
    const record = expected(owned, id);
    if (
      record.consumption.state !== "dispatch" ||
      record.consumption.attempt.dispatch_id !== id.dispatchId
    )
      stop("superseded");
    return record;
  }
  function registration(snapshot: DraftReviewSnapshot): DraftReviewRegistration {
    // Nothing supplied by a renderer/provider may mutate captured authority after open.
    const frozen = structuredClone(snapshot);
    const hook = (requestId: string, work: (owned: Held) => void): RegistrationResult => {
      const observed = observeCurrent();
      if (!observed.ok) return observed;
      const result = sync(requestId, work, frozen.binding.runId);
      return result.ok ? { ok: true } : result;
    };
    return {
      open(requestId) {
        return hook(requestId, (owned) => {
          const record: DraftReviewRecord = {
            schema_version: 1,
            request_id: requestId,
            correlation: {
              review_id: null,
              subject: frozen.binding.subject,
              source: frozen.source,
              source_digest: frozen.sourceDigest,
              target: {
                operation: REVIEW_OPERATIONS[frozen.binding.subject],
                digest: frozen.binding.digest,
              },
            },
            consumption: { state: "opening" },
          };
          // Refuse unresolved intent before consulting a new source; do not hide a human stop.
          const eligible = transitionDraftReview(owned.read(), { kind: "open", record });
          if (!eligible.ok) throw new ReviewStop(eligible);
          const match = currentMatch(owned, record);
          if (match !== "matching") stop(match);
          owned.transition({ kind: "open", record });
        });
      },
      attach(requestId, reviewId) {
        return hook(requestId, (owned) => {
          const id = { requestId, reviewId: null };
          const match = currentMatch(owned, expected(owned, id));
          owned.transition({ kind: "attach", id, reviewId, match });
          if (match !== "matching") stop(match);
        });
      },
      invalidateOpening(requestId, reason) {
        return hook(requestId, (owned) => {
          owned.transition({ kind: "invalidate", id: { requestId, reviewId: null }, reason });
        });
      },
      subscriptionFailed(requestId, reviewId) {
        return hook(requestId, (owned) => {
          owned.transition({
            kind: "invalidate",
            id: { requestId, reviewId },
            reason: "subscription-failed",
          });
        });
      },
      diagnostic(code, detail) {
        try {
          deps.diagnostic?.(code, detail);
        } catch {
          console.error("perk: draft review diagnostic sink failed");
        }
      },
    };
  }
  function observe(entries: readonly unknown[]): RegistrationResult {
    for (const [dispatchId, expectation] of expectations) {
      const result = sync(
        expectation.id.requestId,
        (owned) => {
          const record = expected(owned, expectation.id);
          const c = record.consumption;
          if (c.state === "consumed" && c.attempt.dispatch_id === dispatchId) return true;
          if (c.state === "uncertain") stop("unresolved-dispatch");
          if (c.state !== "dispatch" || c.attempt.dispatch_id !== dispatchId) stop("superseded");
          const entryId = deliveryEvidence(c.attempt, entries);
          if (entryId === null) return false;
          owned.transition({ kind: "complete", id: expectation.id, entryId });
          return true;
        },
        expectation.runId,
      );
      if (!result.ok) return result;
      if (result.value) expectations.delete(dispatchId);
    }
    return { ok: true };
  }
  function observeCurrent(): RegistrationResult {
    try {
      return observe(deps.entries());
    } catch {
      return reviewRefused("io-error");
    }
  }
  function interrupt(id?: ReviewIdentity, entries?: readonly unknown[]): RegistrationResult {
    const observed = entries === undefined ? observeCurrent() : observe(entries);
    if (!observed.ok) return observed;
    for (const [dispatchId, expectation] of expectations) {
      if (
        id !== undefined &&
        (id.requestId !== expectation.id.requestId || id.reviewId !== expectation.id.reviewId)
      )
        continue;
      const result = sync(
        expectation.id.requestId,
        (owned) =>
          owned.transition({
            kind: "uncertain",
            id: expectation.id,
            reason: "delivery-unconfirmed",
          }),
        expectation.runId,
      );
      if (!result.ok) return result;
      expectations.delete(dispatchId);
    }
    return { ok: true };
  }
  function mutationSession(
    owned: Held,
    reason: Extract<ReviewEvent, { kind: "mutation" }>["reason"],
    draft?: { subject: ReviewSubject; content?: string },
  ): WorkflowSession {
    // Structured writers own serialization (including the dream gate). When bytes are not
    // supplied yet, admit only the bounded callback; invalidate at its actual write below.
    let identical = draft !== undefined && draft.content === undefined;
    if (draft?.content !== undefined && reason === "source-changed") {
      const current = owned
        .check()
        .readArtifact(artifactNames[draft.subject], { provenance: "strict" });
      if (current.status === "invalid") owned.poison("invalid-state");
      identical = current.status === "found" && current.content === draft.content;
    }
    owned.transition({ kind: "mutation", reason, identical });
    return {
      get runId() {
        return owned.check().runId;
      },
      currentRunIdentity: () => owned.check().currentRunIdentity(),
      draftReviewContext: () => owned.check().draftReviewContext(),
      readArtifact: (name) => owned.check().readArtifact(name, { provenance: "strict" }),
      writeArtifact(name, content) {
        if (
          name === DRAFT_REVIEW_ARTIFACT ||
          (draft !== undefined &&
            (name !== artifactNames[draft.subject] ||
              (draft.content !== undefined && content !== draft.content)))
        )
          stop("invalid-state");
        if (draft !== undefined && reason === "source-changed") {
          const current = owned.check().readArtifact(name, { provenance: "strict" });
          if (current.status === "invalid") owned.poison("invalid-state");
          owned.transition({
            kind: "mutation",
            reason,
            identical: current.status === "found" && current.content === content,
          });
        }
        const result = owned.check().writeArtifact(name, content, { provenance: "strict" });
        owned.check();
        if (result.status !== "applied" && result.status !== "unchanged")
          owned.poison("persistence-failed");
        return result;
      },
      nodeClaim: () => owned.check().nodeClaim(),
      activeObjective: () => owned.check().activeObjective(),
      reviewPosts: () => owned.check().reviewPosts(),
      apply(change) {
        if (draft !== undefined) stop("invalid-state");
        const result = owned.check().apply(change);
        owned.check();
        if (result.status !== "applied" && result.status !== "unchanged")
          owned.poison("persistence-failed");
        return result;
      },
    };
  }
  return {
    /** Capture exactly one raw→decode→render source snapshot. open() checks it again under claim. */
    prepare(
      parameter?: string,
    ): Outcome<{ snapshot: DraftReviewSnapshot; registration: DraftReviewRegistration }> {
      try {
        if (ended) return reviewRefused("invalid-state");
        const session = deps.session();
        const captured = binding(session);
        if (!captured.ok) return captured;
        const source = sourceSnapshot(session, captured.binding.subject, parameter);
        if (!source.ok) return source;
        const snapshot = { ...source.value, binding: captured.binding };
        return { ok: true, value: { snapshot, registration: registration(snapshot) } };
      } catch {
        return reviewRefused("io-error");
      }
    },
    /** Readiness belongs to this review, not whichever successor is now on disk. */
    degrade(id: ReviewIdentity, runId: string): RegistrationResult {
      const observed = observeCurrent();
      if (!observed.ok) return observed;
      const result = sync(
        id.requestId,
        (owned) => {
          expected(owned, id);
          owned.transition({ kind: "invalidate", id, reason: "degraded" });
        },
        runId,
      );
      return result.ok ? { ok: true } : result;
    },
    /** Exclusion + verified invalidation through a synchronous participating mutation. */
    mutate<T>(
      reason: Extract<ReviewEvent, { kind: "mutation" }>["reason"],
      work: (session: WorkflowSession) => T,
      options: {
        draft?: { subject: ReviewSubject; content?: string };
        entries?: readonly unknown[];
      } = {},
    ): Outcome<T> {
      const observed = options.entries === undefined ? observeCurrent() : observe(options.entries);
      if (!observed.ok) return observed;
      return sync(randomUUID(), (owned) => {
        const session = mutationSession(owned, reason, options.draft);
        const value = work(session);
        if (typeof value === "object" && value !== null && "then" in value)
          owned.poison("invalid-state");
        owned.check();
        return value;
      });
    },
    /** Manual saves/node transitions hold exclusion through their awaited effects, not editor waits. */
    async mutateAsync<T>(
      reason: Extract<ReviewEvent, { kind: "mutation" }>["reason"],
      work: (session: WorkflowSession) => Promise<T>,
    ): Promise<Outcome<T>> {
      const observed = observeCurrent();
      if (!observed.ok) return observed;
      let owned: Held | undefined;
      let outcome: Outcome<T>;
      try {
        owned = acquire(randomUUID());
        const value = await work(mutationSession(owned, reason));
        owned.check();
        outcome = { ok: true, value };
      } catch (error) {
        outcome = caught(error);
      } finally {
        if (owned !== undefined) {
          try {
            owned.finish();
          } catch (error) {
            outcome = caught(error);
          }
        }
      }
      return outcome;
    },
    observe,
    interrupt,
    /** Context replacement cannot use even cached expectations against the replacement branch. */
    abandon() {
      expectations.clear();
      ended = true;
    },
    hasExpectation(id: ReviewIdentity): boolean {
      return [...expectations.values()].some(
        (expectation) =>
          expectation.id.requestId === id.requestId && expectation.id.reviewId === id.reviewId,
      );
    },
    async dispatch<T>(options: {
      id: ReviewIdentity;
      runId: string;
      approved: boolean;
      feedback?: string;
      effect: "save" | "revision";
      signal?: AbortSignal;
      execute: (capability: DraftReviewCapability) => Promise<T>;
    }): Promise<
      Outcome<T | { status: "consumed" }> & { saveReceipt: SaveReceipt | null; gateExited: boolean }
    > {
      options = { ...options, id: { ...options.id } };
      let saveReceipt: SaveReceipt | null = null;
      let gateExited = false;
      let owned: Held | undefined;
      let intent: AttemptIdentity | undefined;
      let delivered = false;
      let outcome: Outcome<T | { status: "consumed" }>;
      const uncertain = (reason: UncertaintyReason) => {
        if (owned !== undefined && intent !== undefined && !owned.failed)
          owned.transition({ kind: "uncertain", id: intent, reason });
      };
      try {
        const observed = observeCurrent();
        if (!observed.ok) throw new ReviewStop(observed);
        owned = acquire(options.id.requestId, options.runId);
        const owner = owned;
        const prior = expected(owner, options.id);
        if (prior.consumption.state === "consumed") {
          outcome = { ok: true, value: { status: "consumed" } };
        } else {
          if (prior.consumption.state === "dispatch" || prior.consumption.state === "uncertain")
            stop("unresolved-dispatch");
          if (options.signal?.aborted) stop("invalid-state");
          if (!options.approved && options.effect === "save") stop("invalid-state");
          const match = currentMatch(owner, prior);
          const dispatchId = randomUUID();
          const next = owner.transition({
            kind: "candidate",
            id: options.id,
            match,
            dispatchId,
            decisionDigest: decisionDigest(options.approved, options.feedback),
            effect: options.effect,
          });
          if (next?.consumption.state !== "dispatch")
            stop(match === "matching" ? "invalid-state" : match);
          const id = { ...options.id, dispatchId };
          intent = id;
          activeDispatch = { owned: owner, id };
          const effect = next.consumption.attempt.effect;
          const original =
            effect === "stale-reference"
              ? null
              : sourceSnapshot(
                  owner.check(),
                  prior.correlation.subject,
                  prior.correlation.source.kind === "parameter"
                    ? prior.correlation.source.plan
                    : undefined,
                );
          if (original !== null && !original.ok) throw new ReviewStop(original);
          if (original?.ok && original.value.sourceDigest !== prior.correlation.source_digest)
            stop("source-changed");
          let selectedSource = original?.ok ? original.value.raw : "";
          let patchAttempted = false;
          let patchFailed = false;
          const abortCheck = () => {
            attempt(owner, id);
            if (delivered) stop("invalid-state");
            if (options.signal?.aborted) {
              uncertain("aborted-after-intent");
              stop("unresolved-dispatch");
            }
          };
          const capability: DraftReviewCapability = {
            dispatchId,
            effect,
            writePlan(content) {
              abortCheck();
              if (
                effect !== "save" ||
                prior.correlation.subject !== "plan" ||
                patchAttempted ||
                !isNonblank(content)
              )
                stop("invalid-state");
              patchAttempted = true;
              const result = owner
                .check()
                .writeArtifact(PLAN_DRAFT_ARTIFACT, content, { provenance: "strict" });
              owner.check();
              if (result.status === "applied" || result.status === "unchanged")
                selectedSource = content;
              else patchFailed = true;
              return result;
            },
            apply(change) {
              abortCheck();
              if (effect !== "save") stop("invalid-state");
              const result = owner.check().apply(change);
              owner.check();
              if (result.status !== "applied" && result.status !== "unchanged")
                owner.poison("persistence-failed");
              return result;
            },
            async save(invoke, onReceipt) {
              abortCheck();
              if (effect !== "save") stop("invalid-state");
              const captured = binding(owner.check());
              if (!captured.ok) throw new ReviewStop(captured);
              if (captured.binding.subject !== prior.correlation.subject) stop("subject-changed");
              if (captured.binding.digest !== prior.correlation.target.digest)
                stop("target-changed");
              // Owned failed patches alone allow the original-bytes fallback. The review intent,
              // subject, target, and save-started checkpoint must still verify independently.
              if (!patchFailed) {
                const current = owner
                  .check()
                  .readArtifact(artifactNames[prior.correlation.subject], { provenance: "strict" });
                if (current.status === "invalid") owner.poison("invalid-state");
                const parameterUnwritten =
                  prior.correlation.source.kind === "parameter" &&
                  !patchAttempted &&
                  current.status === "absent";
                if (
                  !parameterUnwritten &&
                  (current.status !== "found" ||
                    digestSessionData(current.content) !== digestSessionData(selectedSource))
                )
                  stop("source-changed");
              }
              owner.transition({ kind: "save-started", id });
              let result: Awaited<ReturnType<typeof invoke>>;
              let receipt: SaveReceipt;
              try {
                result = await invoke({
                  source: selectedSource,
                  warmNodeClaim: captured.binding.warmNodeClaim,
                });
                if (
                  typeof result !== "object" ||
                  result === null ||
                  result.receipt === null ||
                  !isNonblank(result.receipt.id) ||
                  !isNonblank(result.receipt.url)
                )
                  throw new Error("unconfirmed backend result");
                receipt = { id: result.receipt.id, url: result.receipt.url };
              } catch {
                uncertain("backend-unconfirmed");
                stop("unresolved-dispatch");
              }
              saveReceipt = receipt;
              // Backend awaits may lose the claim. Receipt facts survive, but no gate effect
              // is permitted until ownership and the same dispatch are verified again.
              attempt(owner, id);
              const gate = onReceipt?.(receipt);
              gateExited = gate?.gateExited === true;
              owner.transition({ kind: "save-confirmed", id, receipt: saveReceipt });
              return result.value;
            },
            deliver(carrier, content, send) {
              abortCheck();
              const content_digest = deliveryDigest(content);
              if (content_digest === null) stop("invalid-state");
              const marker = deliveryMarker(carrier, dispatchId);
              if (carrier.kind === "user" && !JSON.stringify(content).includes(marker))
                stop("invalid-state");
              owner.transition({
                kind: "expect-delivery",
                id,
                delivery: { carrier, marker, content_digest },
              });
              expectations.set(dispatchId, { id, runId: options.runId });
              delivered = true;
              try {
                send?.();
              } catch {
                uncertain("delivery-unconfirmed");
                expectations.delete(dispatchId);
                stop("unresolved-dispatch");
              }
              // Expectation and the immediate send attempt are the end of the critical section.
              // The caller may return a tool result later; never hold exclusion for that wait.
              owner.finish();
            },
          };
          const value = await options.execute(capability);
          if (!delivered) {
            uncertain("delivery-unconfirmed");
            stop("unresolved-dispatch");
          }
          if (options.signal?.aborted) stop("unresolved-dispatch");
          outcome = { ok: true, value };
        }
      } catch (error) {
        try {
          if (owned !== undefined && intent !== undefined && !owned.failed) {
            const reason = options.signal?.aborted ? "aborted-after-intent" : "effect-failed";
            if (owned.released) {
              const observed = observeCurrent();
              if (!observed.ok) throw new ReviewStop(observed);
              if (expectations.has(intent.dispatchId)) {
                const pending = intent;
                const marked = sync(
                  pending.requestId,
                  (current) =>
                    current.transition({
                      kind: "uncertain",
                      id: pending,
                      reason: options.signal?.aborted ? "delivery-unconfirmed" : reason,
                    }),
                  options.runId,
                );
                if (!marked.ok) throw new ReviewStop(marked);
                expectations.delete(pending.dispatchId);
              }
            } else {
              const record = owned.read();
              if (record?.consumption.state === "dispatch") uncertain(reason);
            }
          }
          outcome = caught(error);
        } catch (failure) {
          outcome = caught(failure);
        }
      } finally {
        if (owned !== undefined) {
          try {
            owned.finish();
          } catch (error) {
            outcome = caught(error);
          }
        }
      }
      if (activeDispatch?.id === intent) activeDispatch = undefined;
      return { ...outcome, saveReceipt, gateExited };
    },
    /** Call at abort/shutdown with existing branch evidence; never query, resend, or auto-clear. */
    end(entries: readonly unknown[]): RegistrationResult {
      if (ended) return reviewRefused("invalid-state");
      if (activeDispatch !== undefined && !activeDispatch.owned.released) {
        const { owned, id } = activeDispatch;
        try {
          const record = attempt(owned, id);
          if (record.consumption.state === "dispatch") {
            const entryId = deliveryEvidence(record.consumption.attempt, entries);
            owned.transition(
              entryId === null
                ? { kind: "uncertain", id, reason: "delivery-unconfirmed" }
                : { kind: "complete", id, entryId },
            );
            expectations.delete(id.dispatchId);
          }
        } catch (error) {
          ended = true;
          return caught(error);
        }
      }
      const result = interrupt(undefined, entries);
      ended = true;
      return result;
    },
  };
}
