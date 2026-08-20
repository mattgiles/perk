// The SECOND 3rd-party plan adapter — and the first with the AUGMENT posture. A perk-owned shim
// that enables `@plannotator/pi-extension` as a REAL, selectable plan provider: unlike the tombell
// adapter (REPLACE posture — perk's plan surface fully vacates), plannotator AUGMENTS perk's plan
// flow. perk's `/plan` mode, authoring injection, and read-only gate STAY (planMode skips only the
// `--plan` flag + `Ctrl+Alt+P` shortcut — the two real registration collisions).
//
// INJECTION + BRIDGE ONLY: the `plan_review` TOOL lives in `extension/factories/planReview.ts`
// (perk's backend-neutral review door); this module is the injection-only adapter shape. It owns
// (1) the plannotator review-step authoring context (injected while the gate is active AND
// plannotator is selected — THREE content flavors, one customType, each once-only: branch-scan
// dedup'd on the flavor's marker: the plan bridge context, the objective flavor when the stage
// is `objective-author` or `objective-save` (both objective stages route to the objective
// review arm), or the gist flavor when the stage is `gist-author`) and (2) the pure
// event-bus bridge
// (`requestPlannotatorPlanReview`; `createPlannotatorBridge` is its thin structural wrapper)
// that planReview.ts dispatches to when plannotator is the selected plan provider and the
// plan-review browser open (plannotatorHandoff.ts) launches. The bridge speaks plannotator's
// published `plannotator:request` event API (in-process `pi.events` bus); the decision wait is
// a per-review `plannotator:review-result` listener disposed via the unsubscribe pi's
// `EventBus.on` returns.
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
import { GIST_AUTHOR_STAGE } from "../factories/gistAuthor.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "../factories/objectiveAuthor.ts";
import { OBJECTIVE_SAVE_STAGE } from "../factories/objectiveSave.ts";
import { resolvedPlanProviderId } from "../factories/planMode.ts";
// Type-only (erased at runtime — no cycle): the outcome vocabulary lives with the review door.
import type { ReviewOutcome } from "../factories/planReview.ts";
import { render } from "../substrate/prompts.ts";
import { PLANNOTATOR_PLAN_PROVIDER_ID } from "../substrate/providers.ts";
import { branchCarries, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";

/** The plannotator plan-adapter bridge customType (distinct from planMode's `perk:plan-context`). */
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

/** Whether the foreign `plannotator-plan` provider is the selected plan provider for `cwd`. */
export function isPlannotatorPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === PLANNOTATOR_PLAN_PROVIDER_ID;
}

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

/** The human decision arriving on `plannotator:review-result`. */
interface ReviewDecision {
  approved: boolean;
  feedback?: string;
}

/**
 * The pure, offline-testable plan-review bridge (the ergonomic mirror of
 * `requestPlannotatorCodeReview` in plannotatorHandoff.ts): emit ONE `plannotator:request` with
 * `action: "plan-review"`, await the bounded `respond` handshake, then await the human decision
 * on a PER-REVIEW `plannotator:review-result` listener — filtered on the handshake's `reviewId`
 * and disposed via the unsubscribe `bus.on` returns when the decision arrives or the turn
 * aborts. Pure over the bus → unit-testable offline with a fake plannotator listener.
 */
export async function requestPlannotatorPlanReview(
  bus: PlannotatorBus,
  plan: string,
  signal?: AbortSignal,
): Promise<ReviewOutcome> {
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

  // A turn aborted DURING the handshake wait must not wedge: `addEventListener("abort", …)` on
  // an already-aborted signal never fires, so re-check before registering the decision wait.
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
      const d = data as { reviewId?: unknown; approved?: unknown; feedback?: unknown };
      if (d?.reviewId !== reviewId) return;
      const decision: ReviewDecision = {
        approved: d.approved === true,
        feedback: typeof d.feedback === "string" && d.feedback.trim() ? d.feedback : undefined,
      };
      finish({ status: "completed", reviewId, ...decision });
    });
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Create the plannotator bridge over an event bus — the thin structural slice
 * (`{ review(plan, signal) }`) that `registerPlanReview` injects into the review door; the body
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
 * Register the plannotator plan adapter: the augment-posture authoring-context injection, inert
 * unless `[providers] plan = "plannotator-plan"`. INJECTION-ONLY (Invariant 1: composes, never
 * owns) — the `plan_review` tool lives in planReview.ts (the backend-neutral review door), which
 * dispatches to this module's bridge when plannotator is selected; the adapter itself never
 * arbitrates tools and needs no gating.
 */
export function registerPlanAdapterPlannotator(pi: ExtensionAPI): void {
  // Inject the bridge context while the read-only gate is active AND plannotator is selected.
  // Three content flavors, one customType: an objective-authoring session (also read-only —
  // BOTH objective stages: `plan_review` routes objective-author AND objective-save to the
  // objective review arm) gets the objective flavor (the review surface renders the objective
  // draft), a gist-author session gets the gist flavor (the rendered gist draft); any other
  // gated stage gets the plan flavor. The gate-active check reads the persisted
  // `perk:workflow-state.mode` (the gate's state twin) — never the gate itself.
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isPlannotatorPlanSelected(ctx.cwd)) return;
    const branch = branchOf(ctx);
    const state = rebuildWorkflowState(branch);
    if (state.mode !== "read-only") return;
    const flavor =
      state.stage === OBJECTIVE_AUTHOR_STAGE || state.stage === OBJECTIVE_SAVE_STAGE
        ? "objective"
        : state.stage === GIST_AUTHOR_STAGE
          ? "gist"
          : "plan";
    const content =
      flavor === "objective"
        ? OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT
        : flavor === "gist"
          ? GIST_ADAPTER_PLANNOTATOR_CONTEXT
          : PLAN_ADAPTER_PLANNOTATOR_CONTEXT;
    // Once-only PER FLAVOR: the dedup key is the flavor's marker (not the shared customType), so
    // a stage change still delivers the missing flavor while a prior copy of another flavor
    // sits on the branch. Injected customs persist, so a live copy suppresses re-injection;
    // compaction dropping it makes the scan come up clean and the next turn re-injects.
    const marker =
      flavor === "objective"
        ? OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER
        : flavor === "gist"
          ? GIST_ADAPTER_PLANNOTATOR_MARKER
          : PLAN_ADAPTER_PLANNOTATOR_MARKER;
    if (branchCarries(branch, marker)) return;
    return {
      message: {
        customType: PLAN_ADAPTER_PLANNOTATOR_CONTEXT_TYPE,
        content,
        display: false,
      },
    };
  });

  // Strip the stale bridge markers (ALL THREE flavors) from context when plannotator-plan is no
  // longer selected (same hygiene as the tombell shim), so they never linger across a deselect.
  const hasMarker = (text: string): boolean =>
    text.includes(PLAN_ADAPTER_PLANNOTATOR_MARKER) ||
    text.includes(OBJECTIVE_ADAPTER_PLANNOTATOR_MARKER) ||
    text.includes(GIST_ADAPTER_PLANNOTATOR_MARKER);
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
