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
// REVIEW SEMANTICS (Node 2.4 — file-first, approval auto-saves): plannotator reviews the plan
// while the session is still read-only (the tool is in READ_ONLY_TOOLS — review happens before
// the gate ever comes off). The reviewed plan resolves FILE-FIRST via `resolvePlanSource`: the
// validated `plan-draft.md` artifact wins; the `plan` param is the fallback for sessions that
// never wrote a draft; the transcript scrape is NEVER reviewed (an approval would auto-save
// scraped conversation bytes — no draft + no param soft-skips with a `plan_draft` redirect). An
// APPROVED outcome wires into the shared `approvalSave` seam (`planSave.ts`, Node 2.3): auto-save
// → D1a gate exit on success → terminating result (node link recovered from the
// `objective_node_claim` carrier inside `savePlan`). A DENY returns feedback and directs a
// `plan_draft` rewrite + re-review. Strict on deny, FAIL-OPEN on absence: plannotator missing /
// unresponsive / headless soft-skips with a loud warning so plan authoring never wedges
// (CI/supervisor safe) — those arms keep the present-the-plan + human-`/plan-save` discipline
// (the manual failsafe).
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider` (stays `"github"`). The adapter composes the gate AND the
// save EXCLUSIVELY through the `approvalSave` seam (Invariant 1: composes, never owns — the gate
// exit lives in the seam; the adapter never writes GitHub itself; the injection's gate-active
// check reads the persisted `perk:workflow-state.mode`, the gate's own state twin).
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.20.0`, `plannotator-events.ts`):
//   request  — pi.events.emit("plannotator:request", { requestId, action: "plan-review",
//              payload: { planContent, origin? }, respond })   // respond = in-payload callback
//   handshake — respond({ status: "handled", result: { status: "pending", reviewId } })
//             | respond({ status: "unavailable", error? }) | respond({ status: "error", error })
//   decision — pi.events.on("plannotator:review-result", { reviewId, approved, feedback?, ... })

import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";
import { resolvedPlanProviderId } from "./planMode.ts";
import { type ApprovalSaveOutcome, approvalSave, resolvePlanSource } from "./planSave.ts";
import { PLANNOTATOR_PLAN_PROVIDER_ID } from "./providers.ts";
import type { ToolGating } from "./toolGating.ts";
import { paramsOf, stringParam } from "./toolParams.ts";
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
  terminate?: boolean;
}

const SKIP_TEXT =
  "no external review surface configured — present the complete plan to the user in your next message.";

function skipResult(): ToolResult {
  return { content: [{ type: "text", text: SKIP_TEXT }], details: { status: "skipped" } };
}

/**
 * Map a non-approved bridge outcome into the model-facing tool result (exported for the offline
 * tests). The `completed` case renders the DENIED text — the execute path routes approved
 * outcomes to `approvedSaveResult` first, so callers only reach `completed` here with
 * `approved: false` (kept total for safety).
 */
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
      const text =
        "plan DENIED — revise per this feedback, rewrite the working draft with plan_draft, " +
        `then call plan_review again.${feedback}`;
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

/**
 * Map an APPROVED bridge outcome + the `approvalSave` outcome into the model-facing tool result
 * (exported for the offline tests). A successful save TERMINATES the turn (propagating the
 * seam's `terminate: true` intent); a failed save is non-terminating, leaves the gate read-only,
 * and directs the human `/plan-save` failsafe. Reviewer feedback is surfaced loudly as
 * implementation guidance — the approved bytes were saved verbatim, never post-edited. The
 * `no-plan` arm is defensively unreachable (the reviewed plan is always non-blank) but maps to
 * the save-failed shape rather than throwing.
 */
export function approvedSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ApprovalSaveOutcome,
  opts: { paramMismatch: boolean },
): ToolResult {
  const feedback = outcome.feedback
    ? "\n\nReviewer feedback (implementation guidance — the approved plan was saved verbatim):\n" +
      outcome.feedback
    : "";
  const base = {
    status: "completed",
    approved: true,
    reviewId: outcome.reviewId,
    feedback: outcome.feedback ?? null,
  };
  if (save.status === "saved") {
    const saveText = save.result.content[0]?.text ?? "";
    const mismatch = opts.paramMismatch
      ? "\n\n⚠ differing plan param ignored — the validated draft was reviewed and saved."
      : "";
    return {
      content: [
        { type: "text", text: `plan APPROVED by reviewer.${feedback}\n\n${saveText}${mismatch}` },
      ],
      details: { ...base, saved: true, gateExited: save.gateExited, save: save.result.details },
      terminate: true,
    };
  }
  const error =
    save.status === "no-plan"
      ? "no plan source resolved"
      : save.result.details.ok
        ? "unknown save failure"
        : save.result.details.error;
  return {
    content: [
      {
        type: "text",
        text:
          `plan APPROVED by reviewer, but the auto-save FAILED (${error}) — the session stays ` +
          `read-only. Ask the user to run /plan-save (the manual failsafe) to retry.${feedback}`,
      },
    ],
    details: {
      ...base,
      saved: false,
      save: save.status === "no-plan" ? null : save.result.details,
    },
  };
}

// ------------------------------------------------------------------------- the execute core

/**
 * The `plan_review` execute core, extracted pure-over-its-seams (the bridge, the gating, the
 * ctx) so the resolution + approved-save paths are unit-testable offline (the same
 * pure-over-a-fake-bus split the bridge tests use, extended over the whole tool).
 */
export async function executePlanReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  params: unknown,
  signal?: AbortSignal,
): Promise<ToolResult> {
  // Tool-boundary decode (Node 3.2), in this tool's native fail-open vocabulary: a MISTYPED
  // `plan` (or non-object params) skip-shapes (`reason: "bad_input"`) without calling the
  // bridge; an ABSENT `plan` proceeds — the validated draft artifact is the preferred source.
  const p = paramsOf(params);
  const plan = p === null ? null : stringParam(p, "plan");
  if (plan === null) {
    return {
      content: [
        {
          type: "text",
          text: "plan_review takes { plan?: string } — omit it (the plan-draft artifact is preferred) or pass a string.",
        },
      ],
      details: { status: "skipped", reason: "bad_input" },
    };
  }
  // 1. Not plannotator-selected → soft skip (the tool is allowlisted on every path).
  if (!isPlannotatorPlanSelected(ctx.cwd)) return skipResult();
  // 2. Headless → soft skip (fail-open; never wedges CI/supervisor runs on a browser UI).
  if (!ctx.hasUI) return skipResult();
  // 3. Objective-author session → soft skip (mirrors the injection's stage exception): an
  //    approval here would auto-save a PLAN issue + exit the gate mid objective-authoring.
  if (rebuildWorkflowState(branchOf(ctx)).stage === OBJECTIVE_AUTHOR_STAGE) {
    return {
      content: [
        {
          type: "text",
          text: "objective authoring saves with objective_save — plan_review does not apply here.",
        },
      ],
      details: { status: "skipped", reason: "objective-author" },
    };
  }
  // 4. File-first resolution (Node 2.4): artifact → param, NEVER transcript — an approval
  //    auto-saves the reviewed bytes, and scraped conversation bytes must never be those.
  const src = resolvePlanSource(ctx, plan);
  if (src === null || src.source === "transcript") {
    return {
      content: [
        {
          type: "text",
          text:
            "no plan to review — write the working draft with plan_draft (or pass the plan " +
            "param), then call plan_review again.",
        },
      ],
      details: { status: "skipped", reason: "no_plan" },
    };
  }
  // 5. Bridge to plannotator; an APPROVED decision wires into the approvalSave seam (auto-save
  //    → D1a gate exit → terminating result); everything else maps via reviewOutcomeResult.
  const outcome = await bridge.review(src.plan, signal ?? ctx.signal);
  if (outcome.status === "completed" && outcome.approved) {
    const save = await approvalSave(pi, ctx, gating, { reviewedPlan: src.plan });
    return approvedSaveResult(outcome, save, { paramMismatch: src.paramMismatch });
  }
  return reviewOutcomeResult(outcome);
}

// ----------------------------------------------------------------------------- registration

/**
 * Register the plannotator plan adapter: the augment-posture injection + the `plan_review` bridge
 * tool, inert unless `[providers] plan = "plannotator-plan"`. It NEVER calls setActiveTools and
 * never owns the gate — the APPROVED arm composes the gate + the save exclusively through the
 * `approvalSave` seam (Invariant 1: composes, never owns).
 */
export function registerPlanAdapterPlannotator(pi: ExtensionAPI, gating: ToolGating): void {
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
      "Present the plan to the configured external review surface (Plannotator browser UI) and " +
      "wait for the human decision. Reviews the validated plan-draft artifact (keep it current " +
      "with plan_draft); on approval the plan is auto-saved to GitHub and the turn terminates. " +
      "On deny, revise per the returned feedback, rewrite the draft with plan_draft, and call " +
      "again. No-op skip when no review surface is configured or the session is headless.",
    promptSnippet: "Request a human review of the working plan draft (Plannotator)",
    promptGuidelines: [
      "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_review reviews AND auto-saves; the plan param is only a fallback when no draft exists.",
      "Call plan_review only when the plan is decision-complete.",
      "On a DENIED review, revise per the feedback, rewrite the draft with plan_draft, then call plan_review again.",
      "On an APPROVED review, the plan is auto-saved and the turn ends — never re-dump the plan as a final message and never tell the user to run /plan-save; relay the save outcome instead.",
      "If plan_review reports it was skipped or unavailable, fall back to presenting the complete plan; the human runs /plan-save (the manual failsafe).",
    ],
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        plan: {
          type: "string",
          description:
            "Optional — the validated plan-draft.md artifact is preferred when present; this " +
            "param is the fallback for sessions that never wrote a draft.",
        },
      },
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executePlanReview(pi, ctx, gating, bridge, params, signal);
    },
  });
}
