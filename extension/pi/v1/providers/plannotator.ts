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
// BRIDGE HARDENING (fail-open by construction): the handshake/decision payloads arrive as
// `unknown` from a foreign package — every load-bearing field is narrowed by a contained parser
// (an adversarial getter or malformed shape degrades to the documented `unavailable`/ignored
// arms, never a throw), and a synchronous `bus.emit` throw is contained with deterministic
// timer cleanup. The well-formed lifecycle is byte-identical.
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
// verified unchanged through 0.26.1):
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
import { render } from "../../../substrate/prompts.ts";
import { rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { installInjectedContext } from "../contextInjection.ts";
// Type-only (erased at runtime — no cycle): the outcome vocabulary lives with the shared
// review-surface machinery.
import type { ReviewOutcome } from "../review.ts";
import { isPlannotatorPlanSelected } from "./selection.ts";

/** The plannotator plan-adapter bridge customType (distinct from the `perk:plan-context`). */
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE = "perk:plan-adapter-plannotator";
const PLAN_ADAPTER_PLANNOTATOR_MARKER = "[PLAN ADAPTER: PLANNOTATOR]";
const OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER = "[OBJECTIVE ADAPTER: PLANNOTATOR]";
const GIST_ADAPTER_PLANNOTATOR_MARKER = "[GIST ADAPTER: PLANNOTATOR]";

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
export const GIST_ADAPTER_PLANNOTATOR_CONTEXT = render("contexts/adapters/plannotator-gist.md", {
  marker: GIST_ADAPTER_PLANNOTATOR_MARKER,
});

// ------------------------------------------------------------------ the event-bus bridge core

/** The minimal `pi.events` surface the bridge needs (mirrors pi's EventBus, whose `on` returns an unsubscribe function). */
export interface PlannotatorBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): () => void;
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
    if (typeof response !== "object" || response === null) return {};
    const record = response as Record<string, unknown>;
    const status = record.status;
    const error = record.error;
    const result = record.result;
    let narrowedResult: { status?: string; reviewId?: string } | undefined;
    if (typeof result === "object" && result !== null) {
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
    if (typeof data !== "object" || data === null) return null;
    const record = data as Record<string, unknown>;
    const reviewId = record.reviewId;
    if (typeof reviewId !== "string") return null;
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
 * on a PER-REVIEW `plannotator:review-result` listener — filtered on the handshake's `reviewId`
 * and disposed via the unsubscribe `bus.on` returns when the decision arrives or the turn
 * aborts. Pure over the bus → unit-testable offline with a fake plannotator listener. Fail-open
 * end to end: a synchronous `emit` throw (a throwing foreign handler) is contained with the
 * handshake timer + abort listener cleared, a turn abort settles the PENDING handshake promptly
 * (never parked on the timeout), and malformed payloads degrade per the parsers above.
 */
export async function requestPlannotatorPlanReview(
  bus: PlannotatorBus,
  plan: string,
  signal?: AbortSignal,
): Promise<ReviewOutcome> {
  if (signal?.aborted) return { status: "aborted" };

  // 1. Emit the request and await the immediate `respond` handshake (bounded — fail-open).
  //    Every handshake exit — respond, timeout, emit throw, turn abort — clears the timer and
  //    the abort listener deterministically (the promise's first settle wins; later respond
  //    calls are inert).
  const requestId = randomUUID();
  let respondResolve: (response: HandshakeResponse | "timeout" | "aborted") => void = () => {};
  const handshake = new Promise<HandshakeResponse | "timeout" | "aborted">((resolve) => {
    respondResolve = resolve;
  });
  const timer = setTimeout(() => respondResolve("timeout"), handshakeTimeoutMs());
  const onHandshakeAbort = (): void => respondResolve("aborted");
  signal?.addEventListener("abort", onHandshakeAbort, { once: true });
  const settleHandshake = (): void => {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onHandshakeAbort);
  };
  try {
    bus.emit("plannotator:request", {
      requestId,
      action: "plan-review",
      payload: { planContent: plan, origin: "perk" },
      respond: (response: unknown) => respondResolve(parseHandshakeResponse(response)),
    });
  } catch (error) {
    // A synchronous throw from a foreign handler must not leak the handshake timer/abort
    // listener or reject a fail-open path — contain it as the unavailable arm.
    settleHandshake();
    return {
      status: "unavailable",
      warning: `plannotator review request failed: ${String(error)}`,
    };
  }
  const response = await handshake;
  settleHandshake();

  if (response === "aborted") return { status: "aborted" };
  if (response === "timeout") {
    return {
      status: "unavailable",
      warning: "plannotator did not respond to the review request (handshake timeout)",
    };
  }
  if (response?.status !== "handled") {
    const detail = response?.error ? `: ${response.error}` : "";
    return {
      status: "unavailable",
      warning: `plannotator reported ${response?.status ?? "an invalid response"}${detail}`,
    };
  }
  const reviewId = response.result?.reviewId;
  if (response.result?.status !== "pending" || typeof reviewId !== "string") {
    return {
      status: "unavailable",
      warning: "plannotator handshake returned no pending reviewId",
    };
  }

  // Belt for the unlistened gap between the handshake settling and the decision wait
  // registering: `addEventListener("abort", …)` on an already-aborted signal never fires, so
  // re-check before registering the decision listener.
  if (signal?.aborted) return { status: "aborted" };

  // 2. Await the human decision (no timeout — the reviewer takes as long as they take), but
  //    honor a turn abort so an interrupted session never leaks a wedged promise. Either exit
  //    disposes the result listener via the unsubscribe.
  return await new Promise<ReviewOutcome>((resolve) => {
    let settled = false;
    const finish = (outcome: ReviewOutcome): void => {
      if (settled) return;
      settled = true;
      unsubscribe();
      signal?.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onAbort = (): void => finish({ status: "aborted" });
    const unsubscribe = bus.on("plannotator:review-result", (data) => {
      const decision = parseReviewDecision(data);
      if (decision === null || decision.reviewId !== reviewId) return;
      finish({
        status: "completed",
        reviewId,
        approved: decision.approved,
        ...(decision.feedback !== undefined ? { feedback: decision.feedback } : {}),
      });
    });
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Create the plannotator bridge over an event bus — the thin structural slice
 * (`{ review(plan, signal) }`) that the plan installer injects into the review door; the body
 * lives in `requestPlannotatorPlanReview`.
 */
export function createPlannotatorBridge(bus: PlannotatorBus): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
} {
  return { review: (plan, signal) => requestPlannotatorPlanReview(bus, plan, signal) };
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
export function installPlannotatorPlanAdapter(pi: ExtensionAPI): void {
  // Inject the bridge context while the read-only gate is active AND plannotator is selected.
  // Three content flavors, one customType: an objective-authoring session (also read-only —
  // BOTH objective stages: `plan_review` routes objective-author AND objective-save to the
  // objective review arm) gets the objective flavor (the review surface renders the objective
  // draft), a gist-author session gets the gist flavor (the rendered gist draft); any other
  // gated stage gets the plan flavor. The gate-active check reads the persisted
  // `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  //
  // Once-only PER FLAVOR: the dedup key is the SELECTED flavor's marker (not the shared
  // customType), so a stage change still delivers the missing flavor while a prior copy of
  // another flavor sits on the branch; the strip owns ALL THREE markers, firing when
  // plannotator-plan is no longer selected (same hygiene as the tombell shim). The inject/strip
  // mechanics live in the shared helper.
  installInjectedContext(pi, {
    customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
    flavors: {
      [PLAN_ADAPTER_PLANNOTATOR_MARKER]: () => PLAN_ADAPTER_PLANNOTATOR_CONTEXT,
      [OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER]: () => OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT,
      [GIST_ADAPTER_PLANNOTATOR_MARKER]: () => GIST_ADAPTER_PLANNOTATOR_CONTEXT,
    },
    select: (ctx, branch) => {
      if (!isPlannotatorPlanSelected(ctx.cwd)) return null;
      const state = rebuildWorkflowState(branch);
      if (state.mode !== "read-only") return null;
      return state.stage === OBJECTIVE_AUTHOR_STAGE || state.stage === OBJECTIVE_SAVE_STAGE
        ? OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER
        : state.stage === GIST_AUTHOR_STAGE
          ? GIST_ADAPTER_PLANNOTATOR_MARKER
          : PLAN_ADAPTER_PLANNOTATOR_MARKER;
    },
    live: (ctx) => isPlannotatorPlanSelected(ctx.cwd),
  });
}
