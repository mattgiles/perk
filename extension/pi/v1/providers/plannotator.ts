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
// Foreign handshake/decision values are contained unknown input, never invented verdicts. The
// result listener is installed BEFORE the request is emitted (an early-decision buffer bridges
// the handshake gap), so no status catch-up query exists.
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
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.20.0`, `plannotator-events.ts`):
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
import { GIST_AUTHOR_STAGE } from "../../../authoring/gist/draft.ts";
import {
  OBJECTIVE_AUTHOR_STAGE,
  OBJECTIVE_SAVE_STAGE,
} from "../../../authoring/objective/prose.ts";
import { REFINE_STAGE } from "../../../authoring/refinement/context.ts";
import { render } from "../../../substrate/prompts.ts";
import { rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { ACTIVITY_BROWSER_REVIEW, type ActivitySink } from "../../../surfaces/surfaces.ts";
import { installInjectedContext, isPlanGuidanceStage } from "../contextInjection.ts";
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

export interface PlannotatorTimers {
  setTimeout(callback: () => void, ms: number): ReturnType<typeof setTimeout>;
  clearTimeout(handle: ReturnType<typeof setTimeout>): void;
}
const defaultTimers: PlannotatorTimers = {
  setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle),
};

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

type Decision = { reviewId: string; approved: boolean; feedback?: string };

/**
 * Narrow a foreign `plannotator:review-result` payload to the load-bearing decision fields —
 * contained: an adversarial getter/malformed shape degrades to `null` (ignored, the wait
 * continues), never a throw. `approved` must be an actual boolean: a decision is a human
 * verdict, so a missing/mistyped approval field makes the whole payload malformed (ignored) —
 * it must never coerce into a DENY that completes a live review.
 */
function parseReviewDecision(data: unknown): Decision | null {
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
 * `requestPlannotatorCodeReview` in plannotatorHandoff.ts): subscribe to
 * `plannotator:review-result` FIRST, emit ONE `plannotator:request` with `action: "plan-review"`,
 * await the bounded `respond` handshake, then await the human decision on the listener (no
 * timeout — the reviewer takes as long as they take), honoring a turn abort so an interrupted
 * session never leaks a wedged promise.
 *
 * Subscribe-before-emit closes the handshake gap: a decision emitted synchronously inside (or
 * right after) the `respond` callback — before the handshake promise resolves — lands in the
 * `early` buffer; once the handshake yields the `reviewId`, the buffer is scanned for the first
 * matching decision (which completes the review) and discarded. No status catch-up query is
 * needed and none is emitted. Every exit (completion, abort, handshake failure/timeout) removes
 * the listener and clears the timer.
 */
export async function requestPlannotatorPlanReview(
  bus: PlannotatorBus,
  plan: string,
  signal?: AbortSignal,
  timers: PlannotatorTimers = defaultTimers,
): Promise<ReviewOutcome> {
  if (signal?.aborted) return { status: "aborted" };

  const requestId = randomUUID();

  // 1. The result listener — installed BEFORE the request goes out. Until the handshake attaches
  //    a reviewId, decisions are buffered; afterwards a live match completes the wait.
  let reviewId: string | null = null;
  const early: Decision[] = [];
  let settleDecision: ((outcome: ReviewOutcome) => void) | null = null;
  let unsubscribe: (() => void) | undefined;
  const dispose = (): void => {
    const release = unsubscribe;
    unsubscribe = undefined;
    try {
      release?.();
    } catch {
      // A throwing unsubscribe must not mask the outcome being delivered.
    }
  };
  try {
    unsubscribe = bus.on("plannotator:review-result", (data) => {
      const decision = parseReviewDecision(data);
      if (decision === null) return;
      if (reviewId === null) {
        early.push(decision);
        return;
      }
      if (decision.reviewId !== reviewId || settleDecision === null) return;
      settleDecision({ status: "completed", ...decision });
    });
  } catch {
    return { status: "unavailable", warning: "plannotator result subscription failed" };
  }

  // 2. The bounded handshake.
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
    dispose();
    return { status: "unavailable", warning: "plannotator review request failed" };
  }
  const response = await handshake;
  settleHandshake();

  const fail = (outcome: ReviewOutcome): ReviewOutcome => {
    dispose();
    return outcome;
  };
  if (response === "aborted") return fail({ status: "aborted" });
  if (response === "timeout") {
    return fail({
      status: "unavailable",
      warning: "plannotator did not respond to the review request (handshake timeout)",
    });
  }
  if (response?.status !== "handled") {
    const detail = response?.error ? `: ${response.error}` : "";
    return fail({
      status: "unavailable",
      warning: `plannotator reported ${response?.status ?? "an invalid response"}${detail}`,
    });
  }
  const id = response.result?.reviewId;
  if (response.result?.status !== "pending" || typeof id !== "string" || !id.trim()) {
    return fail({
      status: "unavailable",
      warning: "plannotator handshake returned no pending reviewId",
    });
  }
  // A usable ID wins the handshake race: preserve pending even if abort followed respond.
  if (signal?.aborted) return fail({ status: "aborted" });

  // 3. Attach the id: an early decision for THIS review completes immediately; the rest of the
  //    buffer (other reviews' decisions) is discarded.
  reviewId = id;
  const buffered = early.find((decision) => decision.reviewId === id);
  early.length = 0;
  if (buffered !== undefined) return fail({ status: "completed", ...buffered });

  // 4. Await the live decision (or the abort). Either exit disposes the listener.
  return await new Promise<ReviewOutcome>((resolve) => {
    let settled = false;
    const finish = (outcome: ReviewOutcome): void => {
      if (settled) return;
      settled = true;
      settleDecision = null;
      dispose();
      signal?.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onAbort = (): void => finish({ status: "aborted" });
    settleDecision = finish;
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Create the plannotator bridge over an event bus — the thin structural slice
 * (`{ review(plan, signal) }`) injected into the review door; the body lives in
 * `requestPlannotatorPlanReview`. The `activity` wait spans the whole blocking review (begun
 * before delegating, ended in `finally` — decision, abort or unavailable alike): every warm
 * arm (plan, objective, gist, refinement) reviews through here, so this one site covers them.
 */
export function createPlannotatorBridge(
  bus: PlannotatorBus,
  activity: ActivitySink,
): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
} {
  return {
    async review(plan, signal) {
      const end = activity(ACTIVITY_BROWSER_REVIEW);
      try {
        return await requestPlannotatorPlanReview(bus, plan, signal);
      } finally {
        end();
      }
    },
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
export function installPlannotatorPlanAdapter(pi: ExtensionAPI, runnerChild: () => boolean): void {
  // Inject the bridge context while the read-only gate is active AND plannotator is selected.
  // Four content flavors, one customType, dispatched on the stage: an objective-authoring
  // session (BOTH objective stages: `plan_review` routes objective-author AND objective-save to
  // the objective review arm) gets the objective flavor (the review surface renders the
  // objective draft), a gist-author session gets the gist flavor (the rendered gist draft), an
  // `objective-refine` session gets the refinement flavor (the review surface renders the
  // (draft, context) pair), and every other stage `isPlanGuidanceStage` admits gets the plan
  // flavor (so the `audit` door — and a runner child, fenced in the shared helper — get
  // nothing). Every flavor sits behind the same gate check: a refinement stage left on the
  // branch after the approved save exited the gate selects nothing. The gate signal is the
  // persisted `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  //
  // Once-only PER FLAVOR: the dedup key is the SELECTED flavor's marker (not the shared
  // customType), so a stage change still delivers the missing flavor while a prior copy of
  // another flavor sits on the branch. Retention follows selection: the shared helper removes
  // obsolete sibling flavors (a warm `/objective-refine` after a plan-mode turn leaves only the
  // refinement flavor directing the model) and every owned copy once nothing is selected.
  installInjectedContext(
    pi,
    {
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
        if (state.mode !== "read-only") return null;
        switch (state.stage) {
          case OBJECTIVE_AUTHOR_STAGE:
          case OBJECTIVE_SAVE_STAGE:
            return OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER;
          case GIST_AUTHOR_STAGE:
            return GIST_ADAPTER_PLANNOTATOR_MARKER;
          case REFINE_STAGE:
            return REFINEMENT_ADAPTER_PLANNOTATOR_MARKER;
          default:
            return isPlanGuidanceStage(state.stage) ? PLAN_ADAPTER_PLANNOTATOR_MARKER : null;
        }
      },
    },
    runnerChild,
  );
}
