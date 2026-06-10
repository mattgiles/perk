// The SECOND 3rd-party plan adapter — and the first with the AUGMENT posture. A perk-owned bridge
// that enables `@plannotator/pi-extension` as a REAL, selectable plan provider: unlike the tombell
// adapter (REPLACE posture — perk's plan surface fully vacates), plannotator AUGMENTS perk's plan
// flow. perk's `/plan` mode, authoring injection, and read-only gate STAY (planMode skips only the
// `--plan` flag + `Ctrl+Alt+P` shortcut — the two real registration collisions); this shim
// contributes plannotator's browser plan-review UI via a model-callable `plan_review` tool that
// bridges to plannotator's published `plannotator:request` event API (in-process `pi.events` bus).
//
// INERT BY DEFAULT. The shim is ALWAYS registered in index.ts but the injection fires — and the
// `plan_review` tool does real work — only when the resolved `[providers] plan` selection is
// `plannotator-plan` (read fresh per-event, same shape as planMode/planAdapterTombell). On any
// other selection the tool soft-skips and the context handler only strips its own stale marker —
// zero behavior change on the default path.
//
// REVIEW SEMANTICS (the user-confirmed shape): plannotator is a review surface at PRESENTATION
// time, not a save-time gate. The model calls `plan_review` with the complete plan markdown while
// still read-only (the tool is in READ_ONLY_TOOLS — review happens before the gate ever comes
// off); the human approves/denies in the browser; a deny returns feedback for revision. Saving
// stays the human-run `/plan-save` — `savePlan`/`plan_save`/`/plan-save` are untouched and never
// launch a browser. Strict on deny, FAIL-OPEN on absence: plannotator missing / unresponsive /
// headless soft-skips with a loud warning so plan authoring never wedges (CI/supervisor safe).
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// touches the gate (the gate-active check reads the persisted `perk:workflow-state.mode`, the
// gate's own state twin), never restamps `cache.plan-ref.provider` (stays `"github"`), and never
// saves anything.
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.20.0`, `plannotator-events.ts`):
//   request  — pi.events.emit("plannotator:request", { requestId, action: "plan-review",
//              payload: { planContent, origin? }, respond })   // respond = in-payload callback
//   handshake — respond({ status: "handled", result: { status: "pending", reviewId } })
//             | respond({ status: "unavailable", error? }) | respond({ status: "error", error })
//   decision — pi.events.on("plannotator:review-result", { reviewId, approved, feedback?, ... })

import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";
import { resolvedPlanProviderId } from "./planMode.ts";
import { PLANNOTATOR_PLAN_PROVIDER_ID } from "./providers.ts";
import { branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** The plannotator plan-adapter bridge customType (distinct from planMode's `perk:plan-context`). */
export const PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE = "perk:plan-adapter-plannotator";
const PLAN_ADAPTER_PLANNOTATOR_MARKER = "[PLAN ADAPTER: PLANNOTATOR]";

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
read-only exactly as the plan-authoring contract describes; then add one review step before
presenting:

- When the plan is decision-complete, call the plan_review tool with the COMPLETE plan markdown.
  The Plannotator browser UI opens for the human reviewer.
- If the review is DENIED: revise the plan per the returned annotations/feedback, then call
  plan_review again with the revised complete plan.
- If the review is APPROVED: write the complete final plan as your last message (incorporating any
  approval feedback as implementation guidance) and tell the user to run /plan-save when satisfied.
- Never attempt to save the plan yourself — the human-run /plan-save is the only save path here.
- If plan_review reports no review surface is available, fall back to presenting the complete plan
  to the user directly.`;

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

/** The bridge outcome the tool maps into a result (also `details.status`). */
export type ReviewOutcome =
  | { status: "unavailable"; warning: string }
  | { status: "aborted" }
  | { status: "completed"; approved: boolean; feedback?: string; reviewId: string };

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

// ------------------------------------------------------------------------ tool result mapping

interface ToolResult {
  content: { type: "text"; text: string }[];
  details: Record<string, unknown>;
}

const SKIP_TEXT =
  "no external review surface configured — present the complete plan to the user in your next message.";

function skipResult(): ToolResult {
  return { content: [{ type: "text", text: SKIP_TEXT }], details: { status: "skipped" } };
}

/** Map a bridge outcome into the model-facing tool result (exported for the offline tests). */
export function reviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  switch (outcome.status) {
    case "unavailable":
      return {
        content: [
          {
            type: "text",
            text:
              `WARNING: ${outcome.warning} — no review performed. ` +
              "Present the complete plan to the user in your next message instead.",
          },
        ],
        details: { status: "unavailable" },
      };
    case "aborted":
      return {
        content: [{ type: "text", text: "plan review aborted (turn interrupted)." }],
        details: { status: "aborted" },
      };
    case "completed": {
      const feedback = outcome.feedback ? `\n\nReviewer feedback:\n${outcome.feedback}` : "";
      const text = outcome.approved
        ? "plan APPROVED by reviewer." +
          (feedback ? `${feedback}\n\nIncorporate this as implementation guidance.` : "") +
          "\n\nWrite the complete final plan as your last message and tell the user to run /plan-save."
        : `plan DENIED — revise per this feedback and call plan_review again.${feedback}`;
      return {
        content: [{ type: "text", text }],
        details: {
          status: "completed",
          approved: outcome.approved,
          feedback: outcome.feedback ?? null,
          reviewId: outcome.reviewId,
        },
      };
    }
  }
}

// ----------------------------------------------------------------------------- registration

/**
 * Register the plannotator plan adapter: the augment-posture injection + the `plan_review` bridge
 * tool, inert unless `[providers] plan = "plannotator-plan"`. It NEVER touches tool gating /
 * setActiveTools (Invariant 1) and never saves anything.
 */
export function registerPlanAdapterPlannotator(pi: ExtensionAPI): void {
  const bridge = createPlannotatorBridge(pi.events);

  // Inject the bridge context while the read-only gate is active AND plannotator is selected —
  // EXCEPT in an objective-author session (also read-only, but objectiveAuthor.ts owns its
  // authoring context there; mirrors planMode's stage exception). The gate-active check reads the
  // persisted `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isPlannotatorPlanSelected(ctx.cwd)) return;
    const state = rebuildWorkflowState(branchOf(ctx));
    if (state.mode !== "read-only") return;
    if (state.stage === OBJECTIVE_AUTHOR_STAGE) return;
    return {
      message: {
        customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        content: PLAN_ADAPTER_PLANNOTATOR_CONTEXT,
        display: false,
      },
    };
  });

  // Strip the stale bridge marker from context when plannotator-plan is no longer selected (same
  // hygiene as the tombell shim), so it never lingers across a deselect.
  pi.on("context", async (event, ctx) => {
    if (isPlannotatorPlanSelected(ctx.cwd)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(PLAN_ADAPTER_PLANNOTATOR_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(PLAN_ADAPTER_PLANNOTATOR_MARKER),
          );
        }
        return true;
      }),
    };
  });

  // The model-callable review bridge. In READ_ONLY_TOOLS so it is callable INSIDE plan mode (the
  // whole point — review happens before the gate ever comes off). Fail-open everywhere: not
  // selected / headless / plannotator unresponsive all soft-skip so authoring never wedges.
  pi.registerTool({
    name: "plan_review",
    label: "Plan review",
    description:
      "Present the complete plan to the configured external review surface (Plannotator browser " +
      "UI) and wait for the human decision. On deny, revise per the returned feedback and call " +
      "again. No-op skip when no review surface is configured or the session is headless.",
    promptSnippet: "Request a human review of the complete plan (Plannotator)",
    promptGuidelines: [
      "Call plan_review with the COMPLETE plan markdown only when the plan is decision-complete.",
      "On a DENIED review, revise the plan per the feedback and call plan_review again.",
      "On an APPROVED review, write the complete final plan as your last message; the user runs /plan-save. Never attempt to save yourself.",
    ],
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["plan"],
      properties: {
        plan: {
          type: "string",
          description: "The full plan markdown to review (the complete, decision-ready plan).",
        },
      },
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const { plan } = params as { plan: string };
      // 1. Not plannotator-selected → soft skip (the tool is allowlisted on every path).
      if (!isPlannotatorPlanSelected(ctx.cwd)) return skipResult();
      // 2. Headless → soft skip (fail-open; never wedges CI/supervisor runs on a browser UI).
      if (!ctx.hasUI) return skipResult();
      // 3–5. Bridge to plannotator and map the outcome.
      return reviewOutcomeResult(await bridge.review(plan, signal ?? ctx.signal));
    },
  });
}
