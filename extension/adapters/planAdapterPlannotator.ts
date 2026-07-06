// The SECOND 3rd-party plan adapter — and the first with the AUGMENT posture. A perk-owned shim
// that enables `@plannotator/pi-extension` as a REAL, selectable plan provider: unlike the tombell
// adapter (REPLACE posture — perk's plan surface fully vacates), plannotator AUGMENTS perk's plan
// flow. perk's `/plan` mode, authoring injection, and read-only gate STAY (planMode skips only the
// `--plan` flag + `Ctrl+Alt+P` shortcut — the two real registration collisions).
//
// INJECTION + BRIDGE ONLY: the `plan_review` TOOL lives in `extension/factories/planReview.ts`
// (perk's backend-neutral review door); this module is the injection-only adapter shape. It owns
// (1) the plannotator review-step authoring context (injected while the gate is active AND
// plannotator is selected — TWO content flavors, one customType: the plan bridge context, or the
// objective flavor when the stage is `objective-author`) and (2) the pure event-bus bridge
// (`createPlannotatorBridge`) that planReview.ts dispatches to when plannotator is the
// selected plan provider. The bridge speaks plannotator's published `plannotator:request` event
// API (in-process `pi.events` bus).
//
// INERT BY DEFAULT. The shim is ALWAYS registered in index.ts but the injection fires only when
// the resolved `[providers] plan` selection is `plannotator-plan` (read fresh per-event, same
// shape as planMode/planAdapterTombell). On any other selection the context handler only strips
// its own stale marker — zero behavior change on the default path.
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider` (stays `"github"`). The adapter is INJECTION-ONLY again
// (Invariant 1: composes, never owns) — the review tool, the `approvalSave` composition, and the
// gate exit all live behind planReview.ts's seams; the injection's gate-active check reads the
// persisted `perk:workflow-state.mode`, the gate's own state twin.
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.20.0`, `plannotator-events.ts` —
// verified unchanged through 0.22.0):
//   request  — pi.events.emit("plannotator:request", { requestId, action: "plan-review",
//              payload: { planContent, origin? }, respond })   // respond = in-payload callback
//   handshake — respond({ status: "handled", result: { status: "pending", reviewId } })
//             | respond({ status: "unavailable", error? }) | respond({ status: "error", error })
//   decision — pi.events.on("plannotator:review-result", { reviewId, approved, feedback?, ... })

import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_AUTHOR_STAGE } from "../factories/objectiveAuthor.ts";
import { resolvedPlanProviderId } from "../factories/planMode.ts";
// Type-only (erased at runtime — no cycle): the outcome vocabulary lives with the review door.
import type { ReviewOutcome } from "../factories/planReview.ts";
import { PLANNOTATOR_PLAN_PROVIDER_ID } from "../substrate/providers.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";

/** The plannotator plan-adapter bridge customType (distinct from planMode's `perk:plan-context`). */
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE = "perk:plan-adapter-plannotator";
const PLAN_ADAPTER_PLANNOTATOR_MARKER = "[PLAN ADAPTER: PLANNOTATOR]";
const OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER = "[OBJECTIVE ADAPTER: PLANNOTATOR]";

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
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT = `${PLAN_ADAPTER_PLANNOTATOR_MARKER}
A Plannotator browser review surface is configured for plan authoring in this repo. Author the plan
read-only exactly as the plan-authoring contract describes; then add one review step:

- Keep the working draft current with plan_draft — the validated plan-draft artifact is what gets
  reviewed AND auto-saved; the plan param is only a fallback for sessions that never wrote a draft.
- When the plan is decision-complete, call the plan_review tool. The Plannotator browser UI opens
  for the human reviewer.
- If the review is DENIED: revise per the returned annotations/feedback, rewrite the working draft
  with plan_draft, then call plan_review again.
- If the review is APPROVED: the plan is auto-saved to GitHub and the session leaves read-only.
  Do NOT re-dump the plan as a final message and do NOT tell the user to run /plan-save — relay
  the save outcome (and any reviewer feedback) instead.
- If plan_review reports it was skipped or no review surface is available: fall back to presenting
  the complete plan to the user; the human runs /plan-save (the manual failsafe).`;

/**
 * The objective flavor of the bridge prompt, injected in an
 * `objective-author` session instead of the plan flavor. An APPROVED review auto-saves the
 * objective via the `objectiveApprovalSave` seam; `/objective-save` is the manual failsafe on
 * the skipped/unavailable arms.
 */
export const OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT = `${OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER}
A Plannotator browser review surface is configured for objective authoring in this repo. Author
the objective read-only exactly as the objective-authoring contract describes; then add one
review step:

- Keep the working objective current with objective_draft — pass the FULL prose and the FULL
  structured roadmap each call (it rewrites the whole draft); never hand-write roadmap YAML.
- When the objective + roadmap are decision-complete, call the plan_review tool. The Plannotator
  browser UI shows the RENDERED objective (the prose + a roadmap table) derived from the draft
  artifact — never raw JSON.
- If the review is DENIED: revise per the returned annotations/feedback, rewrite the working
  draft with objective_draft, then call plan_review again.
- If the review is APPROVED: the objective is auto-saved to GitHub and the session leaves
  read-only — do NOT re-dump the objective as a final message and do NOT tell the user to run
  /objective-save; relay the save outcome (and any reviewer feedback) instead.
- If plan_review reports it was skipped or no review surface is available: present the complete
  objective + structured roadmap to the user; the human runs /objective-save (the manual
  failsafe).`;

/** Whether the foreign `plannotator-plan` provider is the selected plan provider for `cwd`. */
export function isPlannotatorPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === PLANNOTATOR_PLAN_PROVIDER_ID;
}

// ------------------------------------------------------------------ the event-bus bridge core

/** The minimal `pi.events` surface the bridge needs (mirrors pi's EventBus). */
export interface PlannotatorBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): void;
}

/** Plannotator's immediate `respond` handshake payload (pinned envelope, see header). */
interface HandshakeResponse {
  status?: string;
  error?: string;
  result?: { status?: string; reviewId?: string };
}

/** The human decision arriving on `plannotator:review-result`. */
interface ReviewDecision {
  approved: boolean;
  feedback?: string;
}

/**
 * Create the plannotator bridge over an event bus: ONE persistent `plannotator:review-result`
 * listener registered up front, resolving pending reviews from a Map keyed by reviewId (no
 * dependence on an undocumented `pi.events.off`). Pure over the bus → unit-testable offline with a
 * fake plannotator listener.
 */
export function createPlannotatorBridge(bus: PlannotatorBus): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
} {
  const pending = new Map<string, (decision: ReviewDecision) => void>();

  bus.on("plannotator:review-result", (data) => {
    const d = data as { reviewId?: unknown; approved?: unknown; feedback?: unknown };
    if (typeof d?.reviewId !== "string") return;
    const resolve = pending.get(d.reviewId);
    if (resolve === undefined) return;
    pending.delete(d.reviewId);
    resolve({
      approved: d.approved === true,
      feedback: typeof d.feedback === "string" && d.feedback.trim() ? d.feedback : undefined,
    });
  });

  async function review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> {
    if (signal?.aborted) return { status: "aborted" };

    // 1. Emit the request and await the immediate `respond` handshake (bounded — fail-open).
    const requestId = randomUUID();
    let respondResolve: (response: HandshakeResponse) => void = () => {};
    const handshake = new Promise<HandshakeResponse | "timeout">((resolve) => {
      respondResolve = resolve;
    });
    const timer = setTimeout(() => respondResolve("timeout" as never), handshakeTimeoutMs());
    bus.emit("plannotator:request", {
      requestId,
      action: "plan-review",
      payload: { planContent: plan, origin: "perk" },
      respond: (response: unknown) => respondResolve(response as HandshakeResponse),
    });
    const response = await handshake;
    clearTimeout(timer);

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

    // 2. Await the human decision (no timeout — the reviewer takes as long as they take), but
    //    honor a turn abort so an interrupted session never leaks a wedged promise.
    return await new Promise<ReviewOutcome>((resolve) => {
      const onAbort = (): void => {
        pending.delete(reviewId);
        resolve({ status: "aborted" });
      };
      pending.set(reviewId, (decision) => {
        signal?.removeEventListener("abort", onAbort);
        resolve({ status: "completed", reviewId, ...decision });
      });
      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }

  return { review };
}

// ----------------------------------------------------------------------------- registration

/**
 * Register the plannotator plan adapter: the augment-posture authoring-context injection, inert
 * unless `[providers] plan = "plannotator-plan"`. INJECTION-ONLY (Invariant 1: composes, never
 * owns) — the `plan_review` tool lives in planReview.ts (the backend-neutral review door), which
 * dispatches to this module's bridge when plannotator is selected; the adapter itself never
 * arbitrates tools and needs no gating.
 */
export function registerPlanAdapterPlannotator(pi: ExtensionAPI): void {
  // Inject the bridge context while the read-only gate is active AND plannotator is selected.
  // Two content flavors, one customType: an objective-author session (also read-only) gets the
  // objective flavor (the review surface renders the objective draft); any other
  // gated stage gets the plan flavor. The gate-active check reads the persisted
  // `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isPlannotatorPlanSelected(ctx.cwd)) return;
    const state = rebuildWorkflowState(branchOf(ctx));
    if (state.mode !== "read-only") return;
    const content =
      state.stage === OBJECTIVE_AUTHOR_STAGE
        ? OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT
        : PLAN_ADAPTER_PLANNOTATOR_CONTEXT;
    return {
      message: {
        customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        content,
        display: false,
      },
    };
  });

  // Strip the stale bridge markers (BOTH flavors) from context when plannotator-plan is no
  // longer selected (same hygiene as the tombell shim), so they never linger across a deselect.
  const hasMarker = (text: string): boolean =>
    text.includes(PLAN_ADAPTER_PLANNOTATOR_MARKER) ||
    text.includes(OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER);
  pi.on("context", async (event, ctx) => {
    if (isPlannotatorPlanSelected(ctx.cwd)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !hasMarker(content);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              hasMarker((c as { text?: string }).text ?? ""),
          );
        }
        return true;
      }),
    };
  });
}
