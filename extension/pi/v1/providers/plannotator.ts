// The SECOND 3rd-party plan adapter — and the first with the AUGMENT posture. A perk-owned shim
// that enables `@plannotator/pi-extension` as a REAL, selectable plan provider: unlike the tombell
// adapter (REPLACE posture — perk's plan surface fully vacates), plannotator AUGMENTS perk's plan
// flow. perk's `/plan` mode, authoring injection, and read-only gate STAY (the plan installer
// skips only the `--plan` flag + `Ctrl+Alt+P` shortcut — the two real registration collisions).
//
// INJECTION + BRIDGE ONLY: the `plan_review` TOOL lives in `pi/v1/plan.ts` (perk's
// backend-neutral review door); this module is the injection-only adapter shape. It owns
// (1) the plannotator review-step authoring context (injected while the gate is active AND
// plannotator is selected — THREE content flavors, one customType, each once-only:
// scan-dedup'd on the flavor's marker: the plan bridge context, the objective flavor when the
// stage is `objective-author` or `objective-save` (both objective stages route to the objective
// review arm), or the gist flavor when the stage is `gist-author`) and (2) the pure
// event-bus bridge
// (`requestPlannotatorPlanReview`; `createPlannotatorBridge` is its thin structural wrapper)
// that the review door dispatches to when plannotator is the selected plan provider and the
// plan-review browser open (plannotatorHandoff.ts) launches. The bridge speaks plannotator's
// published `plannotator:request` event API (in-process `pi.events` bus); the decision wait is
// a per-review `plannotator:review-result` listener disposed via the unsubscribe pi's
// `EventBus.on` returns.
//
// Registration is mandatory and fail-closed: verified state hooks precede request/attachment.
// Foreign handshake/decision/status values are contained unknown input, never invented verdicts.
// Subscribe-then-status catch-up closes the handshake event gap without polling or recovery.
//
// INERT BY DEFAULT. The shim is ALWAYS registered in index.ts but the injection fires only when
// the resolved `[providers] plan` selection is `plannotator-plan` (read fresh per-event, same
// shape as the plan installer / tombell adapter). On any other selection the context handler
// only strips its own stale marker — zero behavior change on the default path.
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider` (stays `"github"`). The adapter is INJECTION-ONLY again
// (Invariant 1: composes, never owns) — the review tool, the `approvalSave` composition, and the
// gate exit all live behind the plan installer's seams; the injection's gate-active check reads
// the persisted `perk:workflow-state.mode`, the gate's own state twin.
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.20.0`, `plannotator-events.ts` —
// with callback review-status catch-up specified against 0.27.12):
//   request  — pi.events.emit("plannotator:request", { requestId, action: "plan-review",
//              payload: { planContent, origin? }, respond })   // respond = in-payload callback
//   handshake — respond({ status: "handled", result: { status: "pending", reviewId } })
//             | respond({ status: "unavailable", error? }) | respond({ status: "error", error })
//   decision — pi.events.on("plannotator:review-result", { reviewId, approved, feedback?, ... })
//
// DIRECT EDITS FEEDBACK FORMAT (pinned against plannotator `packages/editor/directEdits.ts`,
// `buildDirectEditsSection` / `composeFeedbackWithDirectEdits`, at v0.26.1). The browser's
// direct-edit mode arrives as PROSE inside the existing `feedback` string, never a new envelope
// field: `# Direct Edits\n` + blank line + a one-sentence preamble (two wording variants — never
// couple to it) + blank line + a ```diff fence containing
// `createTwoFilesPatch('plan.md (original)', 'plan.md (edited)', base, edited, undefined,
// undefined, { context: 3 }).trimEnd()` against the exact bytes perk submitted. The section is
// composed FIRST; non-sentinel annotation feedback follows after `\n\n---\n\n`; edits-only
// feedback is just the section. `extractDirectEdits` below parses it strictly (fail-open — a
// null degrades to today's verbatim behavior).

import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  classifyAuthoringContext,
  readOnlyModeOf,
} from "../../../authoring/context/eligibility.ts";
import type {
  DraftReviewRegistration,
  RegistrationResult,
  ReviewRefusal,
  StatusDiagnostic,
} from "../../../session/draftReviewState.ts";
import type { ContextPolicyInputs } from "../../../substrate/contextPolicy.ts";
import { render } from "../../../substrate/prompts.ts";
import { rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { installInjectedContext } from "../contextInjection.ts";
import { isRefinementSession } from "../objectiveRefinement.ts";
import type { ReviewOutcome } from "../reviewOutcome.ts";
import { isPlannotatorPlanSelected } from "./selection.ts";

/** The plannotator plan-adapter bridge customType (distinct from the `perk:plan-context`). */
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE = "perk:plan-adapter-plannotator";
const PLAN_ADAPTER_PLANNOTATOR_MARKER = "[PLAN ADAPTER: PLANNOTATOR]";
const OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER = "[OBJECTIVE ADAPTER: PLANNOTATOR]";
const GIST_ADAPTER_PLANNOTATOR_MARKER = "[GIST ADAPTER: PLANNOTATOR]";
const REFINEMENT_ADAPTER_PLANNOTATOR_MARKER = "[REFINEMENT ADAPTER: PLANNOTATOR]";

/**
 * The handshake timeout for plannotator's immediate `respond` callback (mirrors plannotator's own
 * `PLANNOTATOR_TIMEOUT_MS = 5_000`). Overridable for tests via PERK_PLANNOTATOR_HANDSHAKE_MS.
 */
export const PLANNOTATOR_HANDSHAKE_TIMEOUT_MS = 5_000;

function handshakeTimeoutMs(): number {
  const raw = Number(process.env.PERK_PLANNOTATOR_HANDSHAKE_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : PLANNOTATOR_HANDSHAKE_TIMEOUT_MS;
}

/**
 * The augment-posture bridge prompt: perk's plan-authoring discipline plus the plannotator review
 * step. Prompting, NOT enforcement (perk's own gate is the read-only authority). Durable anchors
 * only — mirrors PLAN_AUTHORING_CONTEXT, which is also injected (perk's plan mode stays).
 */
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT = render("contexts/adapters/plannotator-plan.md", {
  marker: PLAN_ADAPTER_PLANNOTATOR_MARKER,
});

/**
 * The objective flavor of the bridge prompt, injected in an objective-authoring session
 * (stage `objective-author` or `objective-save`) instead of the plan flavor. An APPROVED review auto-saves the
 * objective via the `objectiveApprovalSave` seam; `/objective-save` is the manual failsafe on
 * the skipped/unavailable arms.
 */
export const OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT = render(
  "contexts/adapters/plannotator-objective.md",
  { marker: OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER },
);

/**
 * The gist flavor of the bridge prompt, injected in a `gist-author` session instead of the
 * plan/objective flavors. The review surface renders the gist draft (title + scope line +
 * prose); an approval carrying `# Direct Edits` does NOT auto-save — the model folds the diff
 * into the matching `gist_draft` fields and re-reviews (contracts.md §8.23's gist arm).
 */
/**
 * The refinement flavor of the bridge prompt, injected in an `objective-refine` session. The
 * review surface renders the (draft, context) pair; header hunks are bound metadata (a new
 * grounding pass), Markdown hunks fold into one `objective_refinement_draft` rewrite
 * (contracts.md §8.23's refinement arm).
 */
export const REFINEMENT_ADAPTER_PLANNOTATOR_CONTEXT = render(
  "contexts/adapters/plannotator-refinement.md",
  { marker: REFINEMENT_ADAPTER_PLANNOTATOR_MARKER },
);

export const GIST_ADAPTER_PLANNOTATOR_CONTEXT = render("contexts/adapters/plannotator-gist.md", {
  marker: GIST_ADAPTER_PLANNOTATOR_MARKER,
});

// ------------------------------------------------------------------ the event-bus bridge core

/** The minimal `pi.events` surface the bridge needs (mirrors pi's EventBus, whose `on` returns an unsubscribe function). */
export interface PlannotatorBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): () => void;
}

export type PlannotatorRefusal = {
  status: "refused";
  code: ReviewRefusal;
  phase: "open" | "attach" | "invalidate" | "subscribe";
  detail: string;
};
export type PlannotatorReviewOutcome = ReviewOutcome | PlannotatorRefusal;
export type PlannotatorReviewStatus =
  | Extract<ReviewOutcome, { status: "completed" | "aborted" }>
  | { status: "pending" | "missing" }
  | { status: "failed"; code: Exclude<StatusDiagnostic, "pending" | "missing"> };

/** Independent from the handshake budget; no polling and no human-decision deadline. */
export const PLANNOTATOR_STATUS_TIMEOUT_MS = 5_000;
export interface PlannotatorTimers {
  setTimeout(callback: () => void, ms: number): ReturnType<typeof setTimeout>;
  clearTimeout(handle: ReturnType<typeof setTimeout>): void;
}
const defaultTimers: PlannotatorTimers = {
  setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle),
};

export function registrationHook(
  phase: PlannotatorRefusal["phase"],
  hook: () => RegistrationResult,
): PlannotatorRefusal | null {
  try {
    const result = hook();
    return result.ok
      ? null
      : { status: "refused", code: result.reason, phase, detail: result.detail };
  } catch {
    return {
      status: "refused",
      code: "persistence-failed",
      phase,
      detail: `draft review registration threw during ${phase}`,
    };
  }
}
function safeDiagnostic(
  registration: DraftReviewRegistration,
  code: StatusDiagnostic,
  detail: string,
) {
  try {
    registration.diagnostic(code, detail);
  } catch {
    console.error("perk: draft review diagnostic sink failed");
  }
}
function parseReviewStatus(value: unknown, reviewId: string): PlannotatorReviewStatus {
  const malformed = { status: "failed", code: "malformed" } as const;
  try {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return malformed;
    const envelope = value as Record<string, unknown>;
    const status = envelope.status;
    if (status === "unavailable") return { status: "failed", code: "unavailable" };
    if (status === "error") return { status: "failed", code: "transport-error" };
    if (status !== "handled") return malformed;
    const result = envelope.result;
    if (typeof result !== "object" || result === null || Array.isArray(result)) return malformed;
    const record = result as Record<string, unknown>;
    const state = record.status;
    if (state === "pending" || state === "missing") return { status: state };
    if (state !== "completed") return malformed;
    const decision = parseReviewDecision(record);
    return decision !== null && decision.reviewId === reviewId
      ? { status: "completed", ...decision }
      : malformed;
  } catch {
    return malformed;
  }
}

/** The callback feeds catch-up synchronously so a later live event cannot overtake status. */
function queryStatus(
  bus: PlannotatorBus,
  reviewId: string,
  signal: AbortSignal | undefined,
  timers: PlannotatorTimers,
  candidate: (status: PlannotatorReviewStatus) => void,
): Promise<PlannotatorReviewStatus> {
  return new Promise((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (status: PlannotatorReviewStatus) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) timers.clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      resolve(status);
      candidate(status);
    };
    const abort = () => finish({ status: "aborted" });
    if (signal?.aborted) {
      abort();
      return;
    }
    if (!reviewId.trim()) {
      finish({ status: "failed", code: "malformed" });
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });
    timer = timers.setTimeout(
      () => finish({ status: "failed", code: "timeout" }),
      PLANNOTATOR_STATUS_TIMEOUT_MS,
    );
    try {
      bus.emit("plannotator:request", {
        requestId: randomUUID(),
        action: "review-status",
        payload: { reviewId },
        respond: (value: unknown) => {
          if (!settled) finish(parseReviewStatus(value, reviewId));
        },
      });
    } catch {
      finish({ status: "failed", code: "transport-error" });
    }
  });
}

/** Public callback-only status API; never reads upstream storage or starts a review. */
export function queryPlannotatorReviewStatus(
  bus: PlannotatorBus,
  reviewId: string,
  signal?: AbortSignal,
  timers: PlannotatorTimers = defaultTimers,
): Promise<PlannotatorReviewStatus> {
  return queryStatus(bus, reviewId, signal, timers, () => {});
}

/** Plannotator's immediate `respond` handshake payload (pinned envelope, see header). */
interface HandshakeResponse {
  status?: string;
  error?: string;
  result?: { status?: string; reviewId?: string };
}

/**
 * Narrow the foreign `respond` payload to the load-bearing handshake fields — contained: an
 * adversarial getter/malformed shape degrades to `{}` (the downstream "invalid response" arm),
 * never a throw; well-typed fields pass through byte-identically.
 */
function parseHandshakeResponse(response: unknown): HandshakeResponse {
  try {
    if (typeof response !== "object" || response === null || Array.isArray(response)) return {};
    const record = response as Record<string, unknown>;
    const status = record.status;
    const error = record.error;
    const result = record.result;
    let narrowedResult: { status?: string; reviewId?: string } | undefined;
    if (typeof result === "object" && result !== null && !Array.isArray(result)) {
      const r = result as Record<string, unknown>;
      const resultStatus = r.status;
      const reviewId = r.reviewId;
      narrowedResult = {
        ...(typeof resultStatus === "string" ? { status: resultStatus } : {}),
        ...(typeof reviewId === "string" ? { reviewId } : {}),
      };
    }
    return {
      ...(typeof status === "string" ? { status } : {}),
      ...(typeof error === "string" ? { error } : {}),
      ...(narrowedResult !== undefined ? { result: narrowedResult } : {}),
    };
  } catch {
    return {};
  }
}

/**
 * Narrow a foreign `plannotator:review-result` payload to the load-bearing decision fields —
 * contained: an adversarial getter/malformed shape degrades to `null` (ignored, the wait
 * continues), never a throw. `approved` must be an actual boolean: a decision is a human
 * verdict, so a missing/mistyped approval field makes the whole payload malformed (ignored) —
 * it must never coerce into a DENY that completes a live review.
 */
function parseReviewDecision(
  data: unknown,
): { reviewId: string; approved: boolean; feedback?: string } | null {
  try {
    if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
    const record = data as Record<string, unknown>;
    const reviewId = record.reviewId;
    if (typeof reviewId !== "string" || !reviewId.trim()) return null;
    const approved = record.approved;
    if (typeof approved !== "boolean") return null;
    const feedback = record.feedback;
    return {
      reviewId,
      approved,
      ...(typeof feedback === "string" && feedback.trim() ? { feedback } : {}),
    };
  } catch {
    return null;
  }
}

/**
 * The pure, offline-testable plan-review bridge (the ergonomic mirror of
 * `requestPlannotatorCodeReview` in plannotatorHandoff.ts): emit ONE `plannotator:request` with
 * `action: "plan-review"`, await the bounded `respond` handshake, then await the human decision
 * on a PER-REVIEW `plannotator:review-result` listener with one status catch-up query. Hooks
 * finish exclusion before transport work. Refused/throwing hooks stop, never fall back or emit
 * a verdict. Every transport exit clears its own timers/listeners; local abort is not upstream
 * cancellation. A candidate is correlation only: persisted consumption authorizes effects.
 */
export async function requestPlannotatorPlanReview(
  bus: PlannotatorBus,
  plan: string,
  registration: DraftReviewRegistration,
  signal?: AbortSignal,
  timers: PlannotatorTimers = defaultTimers,
): Promise<PlannotatorReviewOutcome> {
  if (signal?.aborted) return { status: "aborted" };

  const requestId = randomUUID();
  const opened = registrationHook("open", () => registration.open(requestId));
  if (opened !== null) return opened;
  const invalidate = (reason: "opening-aborted" | "handshake-failed") =>
    registrationHook("invalidate", () => registration.invalidateOpening(requestId, reason));
  if (signal?.aborted) return invalidate("opening-aborted") ?? { status: "aborted" };
  let handshakeSettled = false;
  let respondResolve: (response: HandshakeResponse | "timeout" | "aborted") => void = () => {};
  const handshake = new Promise<HandshakeResponse | "timeout" | "aborted">((resolve) => {
    respondResolve = (response) => {
      if (handshakeSettled) return;
      handshakeSettled = true;
      resolve(response);
    };
  });
  const timer = timers.setTimeout(() => respondResolve("timeout"), handshakeTimeoutMs());
  const onHandshakeAbort = (): void => respondResolve("aborted");
  signal?.addEventListener("abort", onHandshakeAbort, { once: true });
  const settleHandshake = (): void => {
    timers.clearTimeout(timer);
    signal?.removeEventListener("abort", onHandshakeAbort);
  };
  try {
    bus.emit("plannotator:request", {
      requestId,
      action: "plan-review",
      payload: { planContent: plan, origin: "perk" },
      respond: (response: unknown) => {
        if (!handshakeSettled) respondResolve(parseHandshakeResponse(response));
      },
    });
  } catch {
    settleHandshake();
    respondResolve("timeout");
    return (
      invalidate("handshake-failed") ?? {
        status: "unavailable",
        warning: "plannotator review request failed",
      }
    );
  }
  const response = await handshake;
  settleHandshake();

  if (response === "aborted") return invalidate("opening-aborted") ?? { status: "aborted" };
  if (response === "timeout") {
    return (
      invalidate("handshake-failed") ?? {
        status: "unavailable",
        warning: "plannotator did not respond to the review request (handshake timeout)",
      }
    );
  }
  if (response?.status !== "handled") {
    const detail = response?.error ? `: ${response.error}` : "";
    return (
      invalidate("handshake-failed") ?? {
        status: "unavailable",
        warning: `plannotator reported ${response?.status ?? "an invalid response"}${detail}`,
      }
    );
  }
  const reviewId = response.result?.reviewId;
  if (response.result?.status !== "pending" || typeof reviewId !== "string" || !reviewId.trim()) {
    return (
      invalidate("handshake-failed") ?? {
        status: "unavailable",
        warning: "plannotator handshake returned no pending reviewId",
      }
    );
  }

  // A usable ID wins the handshake race: preserve pending even if abort followed respond.
  const attached = registrationHook("attach", () => registration.attach(requestId, reviewId));
  if (attached !== null) return attached;
  if (signal?.aborted) return { status: "aborted" };

  // 2. Await the human decision (no timeout — the reviewer takes as long as they take), but
  //    honor a turn abort so an interrupted session never leaks a wedged promise. Either exit
  //    disposes the result listener via the unsubscribe.
  return await new Promise<PlannotatorReviewOutcome>((resolve) => {
    let settled = false;
    let installing = true;
    let early: PlannotatorReviewOutcome | undefined;
    let unsubscribe: (() => void) | undefined;
    const queryAbort = new AbortController();
    const dispose = () => {
      const release = unsubscribe;
      unsubscribe = undefined;
      try {
        release?.();
      } catch {
        safeDiagnostic(registration, "transport-error", "live listener cleanup failed");
      }
    };
    const finish = (outcome: PlannotatorReviewOutcome): void => {
      if (settled) return;
      if (installing) {
        early ??= outcome;
        return;
      }
      settled = true;
      dispose();
      signal?.removeEventListener("abort", onAbort);
      queryAbort.abort();
      resolve(outcome);
    };
    const onAbort = (): void => finish({ status: "aborted" });
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      unsubscribe = bus.on("plannotator:review-result", (data) => {
        if (settled) return;
        const decision = parseReviewDecision(data);
        if (decision === null || decision.reviewId !== reviewId) return;
        finish({ status: "completed", ...decision });
      });
    } catch {
      installing = false;
      finish(
        registrationHook("subscribe", () =>
          registration.subscriptionFailed(requestId, reviewId),
        ) ?? {
          status: "unavailable",
          warning: "plannotator result subscription failed",
        },
      );
      return;
    }
    // A callback cannot authorize completion until subscription setup returns successfully.
    installing = false;
    if (early !== undefined) {
      finish(early);
      return;
    }
    if (signal?.aborted) {
      onAbort();
      return;
    }
    void queryStatus(bus, reviewId, queryAbort.signal, timers, (status) => {
      if (settled) return;
      if (status.status === "completed") finish(status);
      else if (status.status !== "aborted") {
        const code = status.status === "failed" ? status.code : status.status;
        safeDiagnostic(
          registration,
          code,
          `plannotator review status: ${code}; live wait remains open`,
        );
      }
    });
  });
}

/**
 * Create the plannotator bridge over an event bus — the thin structural slice
 * (`{ review(plan, registration, signal) }`) injected into the review door; the body
 * lives in `requestPlannotatorPlanReview`.
 */
export function createPlannotatorBridge(bus: PlannotatorBus): {
  review(
    plan: string,
    registration: DraftReviewRegistration,
    signal?: AbortSignal,
  ): Promise<PlannotatorReviewOutcome>;
} {
  return {
    review: (plan, registration, signal) =>
      requestPlannotatorPlanReview(bus, plan, registration, signal),
  };
}

// ------------------------------------------------------------------ Direct Edits extraction

const DIRECT_EDITS_HEADING = "# Direct Edits";
const DIFF_FENCE_OPEN = "```diff\n";
const REMAINDER_SEPARATOR = "\n\n---\n\n";

/**
 * Whether `feedback` OPENS with the Direct Edits heading (plan-review feedback composes the
 * section first — a heading anywhere else is quoted prose, not a section). Callers pair this
 * with `extractDirectEdits`: heading present but extraction null means the section was seen but
 * could not be honored (the fail-open ladder's loud-warning arm).
 */
export function hasDirectEditsHeading(feedback: string): boolean {
  return feedback === DIRECT_EDITS_HEADING || feedback.startsWith(`${DIRECT_EDITS_HEADING}\n`);
}

/**
 * Strictly extract the Direct Edits unified diff from a plannotator review-result `feedback`
 * string (the format pin lives in the module header). Returns the fence body as `diff` plus the
 * annotation `remainder` after the section (one leading `\n\n---\n\n` separator stripped;
 * `undefined` when blank). Null means "no extractable Direct Edits section" — both the
 * no-section case AND a present-heading-but-unparseable body (callers distinguish the two via
 * `hasDirectEditsHeading`). The preamble prose between the heading and the fence is skipped
 * without inspecting its wording (plannotator ships two variants).
 */
export function extractDirectEdits(feedback: string): { diff: string; remainder?: string } | null {
  if (!hasDirectEditsHeading(feedback)) return null;
  const openIdx = feedback.indexOf(`\n${DIFF_FENCE_OPEN}`, DIRECT_EDITS_HEADING.length);
  if (openIdx === -1) return null;
  const bodyStart = openIdx + 1 + DIFF_FENCE_OPEN.length;
  // The closing fence is the first line that is exactly ``` — unambiguous inside the body,
  // because every diff body line carries a prefix char (` `/`-`/`+`/`\`/`@`), so no body line
  // can start with a backtick.
  let close = -1;
  let searchFrom = bodyStart;
  while (close === -1) {
    const idx = feedback.indexOf("\n```", searchFrom);
    if (idx === -1) return null;
    const after = feedback[idx + 4];
    if (after === undefined || after === "\n") {
      close = idx;
    } else {
      searchFrom = idx + 4;
    }
  }
  const diff = feedback.slice(bodyStart, close);
  if (diff.trim() === "") return null;
  let rest = feedback.slice(close + 4);
  if (rest.startsWith(REMAINDER_SEPARATOR)) rest = rest.slice(REMAINDER_SEPARATOR.length);
  return { diff, remainder: rest.trim() === "" ? undefined : rest };
}

// ----------------------------------------------------------------------------- registration

/**
 * Install the plannotator plan adapter: the augment-posture authoring-context injection, inert
 * unless `[providers] plan = "plannotator-plan"`. INJECTION-ONLY (Invariant 1: composes, never
 * owns) — the `plan_review` tool lives in the plan installer (the backend-neutral review door),
 * which dispatches to this module's bridge when plannotator is selected; the adapter itself
 * never arbitrates tools and needs no gating.
 */
export function installPlannotatorPlanAdapter(
  pi: ExtensionAPI,
  contextPolicy: ContextPolicyInputs,
): void {
  // Inject the bridge context while plannotator is selected AND the shared authoring-context
  // policy (`authoring/context/eligibility.ts`) classifies the session. Three content flavors,
  // one customType: an objective-authoring session (BOTH objective stages: `plan_review` routes
  // objective-author AND objective-save to the objective review arm) gets the objective flavor
  // (the review surface renders the objective draft), a gist-author session gets the gist
  // flavor (the rendered gist draft), and an ELIGIBLE plan author (plan-family stage or warm
  // `plan_authoring` intent) gets the plan flavor; anything else — gate off, a runner child, a
  // bare gate with no plan evidence, or the `gist-save` stage — selects nothing. The gate signal
  // is the persisted `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  //
  // Once-only PER FLAVOR: the dedup key is the SELECTED flavor's marker (not the shared
  // customType), so a stage change still delivers the missing flavor while a prior copy of
  // Retention follows selection; obsolete sibling flavors are removed by the shared helper.
  installInjectedContext(pi, {
    customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
    flavors: {
      [PLAN_ADAPTER_PLANNOTATOR_MARKER]: () => PLAN_ADAPTER_PLANNOTATOR_CONTEXT,
      [OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER]: () => OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT,
      [GIST_ADAPTER_PLANNOTATOR_MARKER]: () => GIST_ADAPTER_PLANNOTATOR_CONTEXT,
      [REFINEMENT_ADAPTER_PLANNOTATOR_MARKER]: () => REFINEMENT_ADAPTER_PLANNOTATOR_CONTEXT,
    },
    select: (ctx, branch) => {
      if (!isPlannotatorPlanSelected(ctx.cwd)) return null;
      const state = rebuildWorkflowState(branch);
      if (isRefinementSession(branch)) return REFINEMENT_ADAPTER_PLANNOTATOR_MARKER;
      switch (
        classifyAuthoringContext({
          gateActive: readOnlyModeOf(state),
          runnerChild: contextPolicy.runnerChild(),
          state,
        })
      ) {
        case "plan":
          return PLAN_ADAPTER_PLANNOTATOR_MARKER;
        case "objective-author":
        case "objective-save":
          return OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER;
        case "gist-author":
          return GIST_ADAPTER_PLANNOTATOR_MARKER;
        default:
          return null;
      }
    },
  });
}
