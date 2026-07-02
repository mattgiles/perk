// The backend-neutral `plan_review` review door. perk's UNIVERSAL
// plan-review surface: the model calls ONE tool; this module dispatches to the configured review
// backend. Plannotator-selected → the event-bus bridge (`createPlannotatorBridge`,
// planAdapterPlannotator.ts — the AUGMENT-posture path, byte-stable); ANY other
// selection (perk-plan, tombell, unknown ids) → the FIRST-PARTY in-TUI editor review
// (`runFirstPartyReview`): display the draft in pi's built-in `ctx.ui.editor` dialog (scrollable,
// Ctrl+G opens the user's external $EDITOR), write optional human edits back to the draft via
// `writePlanDraft` BEFORE the verdict (reviewed bytes == artifact bytes == saved bytes — a failed
// write-back ABORTS the review fail-open, nothing saved), then an approve/deny/skip
// `ctx.ui.select` verdict — on the plan arm with a 4th "Implement here — no issue saved" option
// (§8.23; suppressed in objective-node planning sessions) — with deny feedback via a second
// editor dialog.
//
// REVIEW SEMANTICS (file-first, approval auto-saves): the review runs while the session is still
// read-only (the tool is in READ_ONLY_TOOLS — review happens before the gate ever comes off).
// The reviewed plan resolves FILE-FIRST via `resolvePlanSource` (the validated `plan-draft.md`
// artifact wins; the `plan` param is the fallback; the transcript scrape is NEVER reviewed — an
// approval would auto-save scraped conversation bytes, so no draft + no param soft-skips with a
// `plan_draft` redirect). An APPROVED outcome (either backend) wires into the shared
// `approvalSave` seam (planSave.ts): auto-save → D1a gate exit → terminating result,
// node link recovered from the `objective_node_claim` carrier inside `savePlan`. A DENY returns
// feedback and directs a `plan_draft` rewrite + re-review. Strict on deny, FAIL-OPEN everywhere
// else: headless / dismissed (Esc anywhere = skip, mirroring ask_user_question's dismissal — deny
// is always explicit) / backend-unavailable all soft-skip so plan authoring never wedges — those
// arms keep the present-the-plan + human-`/plan-save` discipline (the manual failsafe).
//
// `ctx.ui.editor` takes NO AbortSignal (unlike select/confirm/input) — `signal?.aborted` is
// checked between dialogs; an in-flight editor dialog survives a turn abort and its result is
// discarded (the aborted arm wins). Enter submits in the editor dialog (Shift+Enter = newline),
// so the dialog titles carry the key hints — pi renders no other affordance.
//
// THE OBJECTIVE ARM: an objective-author session (read-only, stage
// `objective-author`) routes through `executeObjectiveReview` instead of the plan path — the
// reviewed bytes are the RENDERED objective draft (`readObjectiveDraft` + `renderObjectiveDraft`,
// objectiveDraft.ts — never raw JSON, never the `plan` param, never the transcript; no draft
// soft-skips with `reason: "no_objective_draft"`). Dispatch mirrors the plan path (plannotator
// bridge or the first-party editor, VIEW-ONLY — edits are never written back; deny+feedback is
// the change channel). An APPROVED outcome wires into the `objectiveApprovalSave` seam
// (objectiveSave.ts): re-read the STRUCTURED artifact → `saveObjective` → D1a gate
// exit → a TERMINATING result; a failed save is non-terminating, leaves the gate read-only, and
// directs the human `/objective-save` failsafe.
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider`. The door composes the gate AND the save EXCLUSIVELY
// through the `approvalSave` seam (Invariant 1: composes, never owns).

import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createPlannotatorBridge,
  isPlannotatorPlanSelected,
} from "../adapters/planAdapterPlannotator.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { implementHereExit, implementHereGuidance } from "./implementHere.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";
import { readObjectiveDraft, renderObjectiveDraft } from "./objectiveDraft.ts";
import { readNodeClaim } from "./objectivePlan.ts";
import { type ObjectiveApprovalSaveOutcome, objectiveApprovalSave } from "./objectiveSave.ts";
import { writePlanDraft } from "./planDraft.ts";
import { type ApprovalSaveOutcome, approvalSave, resolvePlanSource } from "./planSave.ts";

// ----------------------------------------------------------------------------- review outcomes

/**
 * The review outcome a backend produces, mapped into a tool result below (also `details.status`).
 * The `dismissed` arm is FIRST-PARTY ONLY (Esc anywhere = fail-open skip; the plannotator bridge
 * never produces it). The `implement-here` arm is first-party PLAN-arm only (the human chose the
 * no-save exit — contracts.md §8.23); the plannotator bridge never produces it (its browser
 * envelope returns only approve/deny) and the objective arm never offers it.
 */
export type ReviewOutcome =
  | { status: "unavailable"; warning: string }
  | { status: "aborted" }
  | { status: "dismissed" }
  | { status: "implement-here"; reviewId: string }
  | { status: "completed"; approved: boolean; feedback?: string; reviewId: string };

interface ToolResult {
  content: { type: "text"; text: string }[];
  details: Record<string, unknown>;
  terminate?: boolean;
}

const SKIP_TEXT =
  "no interactive review surface available — present the complete plan to the user in your next message.";

function skipResult(): ToolResult {
  return { content: [{ type: "text", text: SKIP_TEXT }], details: { status: "skipped" } };
}

/**
 * Map a non-approved review outcome into the model-facing tool result (exported for the offline
 * tests). The `completed` case renders the DENIED text — the execute path routes approved
 * outcomes to `approvedSaveResult` first, so callers only reach `completed` here with
 * `approved: false` (kept total for safety). The `dismissed` arm renders as a skip — the human
 * declined to decide, so the present-plan + `/plan-save` manual-failsafe discipline applies.
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
    case "dismissed":
      return {
        content: [
          {
            type: "text",
            text:
              "plan review dismissed — present the complete plan to the user; the human runs " +
              "/plan-save (the manual failsafe).",
          },
        ],
        details: { status: "skipped", reason: "dismissed" },
      };
    case "implement-here":
      // Defensively unreachable: the execute path routes implement-here to implementHereResult
      // FIRST (mirror the approved-first routing). Map to a skip shape rather than throwing.
      return {
        content: [
          {
            type: "text",
            text:
              "implement-here verdict received outside the execute path — nothing saved; " +
              "present the complete plan to the user.",
          },
        ],
        details: { status: "skipped", reason: "implement-here" },
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
 * Map an APPROVED review outcome + the `approvalSave` outcome into the model-facing tool result
 * (exported for the offline tests). A successful save TERMINATES the turn (propagating the
 * seam's `terminate: true` intent); a failed save is non-terminating, leaves the gate read-only,
 * and directs the human `/plan-save` failsafe. Reviewer feedback is surfaced loudly as
 * implementation guidance — the approved bytes were saved verbatim, never post-edited. `edited`
 * (first-party only) flags that human edits were written back to the draft pre-verdict, so the
 * saved bytes carry them. The `no-plan` arm is defensively unreachable (the reviewed plan is
 * always non-blank) but maps to the save-failed shape rather than throwing.
 */
export function approvedSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ApprovalSaveOutcome,
  opts: { paramMismatch: boolean; edited?: boolean },
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
    ...(opts.edited === true ? { edited: true } : {}),
  };
  if (save.status === "saved") {
    const saveText = save.result.content[0]?.text ?? "";
    const mismatch = opts.paramMismatch
      ? "\n\n⚠ differing plan param ignored — the validated draft was reviewed and saved."
      : "";
    const edited =
      opts.edited === true ? " · human edits were written back to the draft and saved" : "";
    return {
      content: [
        {
          type: "text",
          text: `plan APPROVED by reviewer.${feedback}\n\n${saveText}${edited}${mismatch}`,
        },
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

/**
 * Map an IMPLEMENT-HERE review outcome + the `implementHereExit` outcome into the model-facing
 * tool result (exported for the offline tests). NON-terminating on purpose — the model continues
 * the turn and implements immediately. The text is the implement-here guidance; when the human
 * edited the plan during review (`edited`), the final reviewed bytes are inlined so the model
 * implements THOSE, not its stale in-context version (the draft write-back already happened
 * pre-verdict). Nothing is saved: no issue, no plan-ref, the draft artifact intact (§8.23).
 */
export function implementHereResult(
  outcome: Extract<ReviewOutcome, { status: "implement-here" }>,
  exit: { gateExited: boolean },
  opts: { cwd: string; plan: string; edited: boolean },
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: implementHereGuidance(opts.cwd, { editedPlan: opts.edited ? opts.plan : undefined }),
      },
    ],
    details: {
      status: "implement-here",
      saved: false,
      gateExited: exit.gateExited,
      reviewId: outcome.reviewId,
      ...(opts.edited ? { edited: true } : {}),
    },
  };
}

// ----------------------------------------------------------------- the first-party review core

/** The minimal structural `ctx.ui` subset the first-party review needs (the askUser.ts recipe). */
export interface PlanReviewUI {
  editor(title: string, prefill?: string): Promise<string | undefined>;
  select(
    title: string,
    options: string[],
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
}

/** The verdict options (plain text — charter D3: no emoji outside the footer). */
const VERDICT_APPROVE = "Approve — auto-save to GitHub";
const VERDICT_DENY = "Deny — send feedback for revision";
const VERDICT_SKIP = "Skip — decide later (manual /plan-save)";
/** The optional 4th verdict (plan arm only): the no-save implement-here exit (§8.23). */
const VERDICT_IMPLEMENT_HERE = "Implement here — no issue saved";

const REVIEW_EDITOR_TITLE =
  "Plan review — Enter: continue to verdict · Esc: skip · Ctrl+G: $EDITOR";
const DENY_FEEDBACK_TITLE = "Deny feedback (optional) — Enter to send";

/**
 * The first-party in-TUI review core, pure over injected seams (the askUser.ts recipe) — fully
 * offline-testable. Flow: (1) display the plan in the editor dialog (Esc = dismissed; the human
 * may edit, incl. via Ctrl+G/$EDITOR); (2) a non-blank edit differing from the displayed plan is
 * written back to the draft BEFORE the verdict (reviewed bytes == artifact bytes == saved bytes;
 * a failed write-back aborts the review fail-open — never let an approval save a stale artifact;
 * a blank edit result is treated as no-edit); (3) the 3-option verdict select (Esc/Skip =
 * dismissed); (4) on deny, optional feedback via a second editor dialog. `ctx.ui.editor` takes no
 * AbortSignal — `signal?.aborted` is checked before each dialog (the aborted arm wins).
 *
 * Presentation options (defaults preserve the plan-path behavior byte-for-byte):
 * `editorTitle`/`verdicts` swap the displayed strings; `verdicts.implementHere`, when present,
 * makes the verdict select 4 options — approve, implement-here, deny, skip (implement-here sits
 * adjacent to approve: both are "accept the plan" outcomes) — and selecting it returns the
 * `implement-here` outcome arm; `viewOnly: true` skips the write-back
 * branch entirely — the editor output is used only for Esc/dismissed detection, `plan` is
 * returned unchanged and `edited` stays false (deny+feedback is the change channel).
 */
export async function runFirstPartyReview(args: {
  ui: PlanReviewUI;
  plan: string;
  /** Bound to `writePlanDraft(pi, ctx, …).details.ok` by the execute path. */
  writeDraft(plan: string): boolean;
  signal?: AbortSignal;
  editorTitle?: string;
  verdicts?: { approve: string; deny: string; skip: string; implementHere?: string };
  viewOnly?: boolean;
}): Promise<{ outcome: ReviewOutcome; plan: string; edited: boolean }> {
  const { ui, writeDraft, signal } = args;
  const editorTitle = args.editorTitle ?? REVIEW_EDITOR_TITLE;
  const verdicts = args.verdicts ?? {
    approve: VERDICT_APPROVE,
    deny: VERDICT_DENY,
    skip: VERDICT_SKIP,
  };
  let plan = args.plan;
  let edited = false;
  const result = (
    outcome: ReviewOutcome,
  ): { outcome: ReviewOutcome; plan: string; edited: boolean } => ({
    outcome,
    plan,
    edited,
  });

  if (signal?.aborted) return result({ status: "aborted" });
  const reviewed = await ui.editor(editorTitle, plan);
  if (signal?.aborted) return result({ status: "aborted" });
  if (reviewed === undefined) return result({ status: "dismissed" });

  // Write human edits back to the draft BEFORE the verdict (blank = no-edit, review the original
  // bytes). A failed write-back aborts the review fail-open — nothing saved. View-only reviews
  // skip the branch entirely (the editor is display-only; deny+feedback is the change channel).
  if (args.viewOnly !== true && reviewed !== plan && reviewed.trim().length > 0) {
    if (!writeDraft(reviewed)) {
      return result({
        status: "unavailable",
        warning:
          "could not write the edited draft back to the session data dir — review aborted, " +
          "nothing saved",
      });
    }
    plan = reviewed;
    edited = true;
  }

  if (signal?.aborted) return result({ status: "aborted" });
  const options =
    verdicts.implementHere === undefined
      ? [verdicts.approve, verdicts.deny, verdicts.skip]
      : [verdicts.approve, verdicts.implementHere, verdicts.deny, verdicts.skip];
  const verdict = await ui.select("Plan review verdict", options, { signal });
  if (signal?.aborted) return result({ status: "aborted" });
  if (verdict === verdicts.approve) {
    return result({ status: "completed", approved: true, reviewId: randomUUID() });
  }
  if (verdicts.implementHere !== undefined && verdict === verdicts.implementHere) {
    return result({ status: "implement-here", reviewId: randomUUID() });
  }
  if (verdict === verdicts.deny) {
    const feedback = await ui.editor(DENY_FEEDBACK_TITLE, "");
    if (signal?.aborted) return result({ status: "aborted" });
    return result({
      status: "completed",
      approved: false,
      feedback: feedback?.trim() ? feedback : undefined,
      reviewId: randomUUID(),
    });
  }
  // Skip option, or the select dismissed (Esc) — fail-open skip.
  return result({ status: "dismissed" });
}

// ------------------------------------------------------------------- the objective review arm

/** The objective-flavored verdict options (approval auto-saves). */
const OBJECTIVE_VERDICTS = {
  approve: "Approve — auto-save to GitHub",
  deny: "Deny — send feedback for revision",
  skip: "Skip — decide later (manual /objective-save)",
};

const OBJECTIVE_REVIEW_EDITOR_TITLE =
  "Objective review (view only — edits are not saved) — Enter: continue to verdict · Esc: skip · " +
  "Ctrl+G: $EDITOR";

/**
 * Map a non-approved objective review outcome into the model-facing tool result (exported for
 * the offline tests) — the objective-flavored sibling of `reviewOutcomeResult`. Every arm
 * carries `details.subject: "objective"`; the texts redirect to `objective_draft` /
 * `/objective-save`. The `completed` case renders the DENIED text — the execute path routes
 * approved outcomes to `approvedObjectiveSaveResult` first, so callers only reach `completed`
 * here with `approved: false` (kept total for safety).
 */
export function objectiveReviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  switch (outcome.status) {
    case "unavailable":
      return {
        content: [
          {
            type: "text",
            text:
              `WARNING: ${outcome.warning} — no review performed. ` +
              "Present the complete objective + structured roadmap to the user instead.",
          },
        ],
        details: { status: "unavailable", subject: "objective" },
      };
    case "aborted":
      return {
        content: [{ type: "text", text: "objective review aborted (turn interrupted)." }],
        details: { status: "aborted", subject: "objective" },
      };
    case "dismissed":
      return {
        content: [
          {
            type: "text",
            text:
              "objective review dismissed — present the complete objective + structured roadmap " +
              "to the user; the human runs /objective-save (the manual failsafe).",
          },
        ],
        details: { status: "skipped", reason: "dismissed", subject: "objective" },
      };
    case "implement-here":
      // Defensively unreachable twice over: the objective arm never offers the verdict, and the
      // execute path routes implement-here first. Map to a skip shape rather than throwing.
      return {
        content: [
          {
            type: "text",
            text:
              "implement-here verdict received on the objective path — nothing saved; present " +
              "the complete objective + structured roadmap to the user.",
          },
        ],
        details: { status: "skipped", reason: "implement-here", subject: "objective" },
      };
    case "completed": {
      const feedback = outcome.feedback ? `\n\nReviewer feedback:\n${outcome.feedback}` : "";
      return {
        content: [
          {
            type: "text",
            text:
              "objective DENIED — revise per this feedback, rewrite the working draft with " +
              `objective_draft, then call plan_review again.${feedback}`,
          },
        ],
        details: {
          status: "completed",
          approved: outcome.approved,
          feedback: outcome.feedback ?? null,
          reviewId: outcome.reviewId,
          subject: "objective",
        },
      };
    }
  }
}

/**
 * Map an APPROVED objective review outcome + the `objectiveApprovalSave` outcome into the
 * model-facing tool result (exported for the offline tests) — the objective sibling of
 * `approvedSaveResult` (no `paramMismatch`/`edited` opts: the objective path reviews only the
 * rendered draft, view-only). A successful save TERMINATES the turn; a failed save is
 * non-terminating, leaves the gate read-only, and directs the human `/objective-save` failsafe.
 * The `no-draft` arm is defensively unreachable (the review just read the draft) but maps to
 * the save-failed shape rather than throwing.
 */
export function approvedObjectiveSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ObjectiveApprovalSaveOutcome,
): ToolResult {
  const feedback = outcome.feedback
    ? "\n\nReviewer feedback (implementation guidance — the approved objective was saved " +
      `verbatim):\n${outcome.feedback}`
    : "";
  const base = {
    status: "completed",
    approved: true,
    reviewId: outcome.reviewId,
    feedback: outcome.feedback ?? null,
    subject: "objective",
  };
  if (save.status === "saved") {
    const saveText = save.result.content[0]?.text ?? "";
    return {
      content: [
        { type: "text", text: `objective APPROVED by reviewer.${feedback}\n\n${saveText}` },
      ],
      details: { ...base, saved: true, gateExited: save.gateExited, save: save.result.details },
      terminate: true,
    };
  }
  const error =
    save.status === "no-draft"
      ? "no objective draft resolved"
      : save.result.details.ok
        ? "unknown save failure"
        : save.result.details.error;
  return {
    content: [
      {
        type: "text",
        text:
          `objective APPROVED by reviewer, but the auto-save FAILED (${error}) — the session ` +
          "stays read-only. Ask the user to run /objective-save (the manual failsafe) to " +
          `retry.${feedback}`,
      },
    ],
    details: {
      ...base,
      saved: false,
      save: save.status === "no-draft" ? null : save.result.details,
    },
  };
}

/**
 * The objective review arm, mirroring `executePlanReview`'s shape but
 * with the rendered objective draft as the SOLE review source (never the `plan` param, never
 * the transcript). First-party reviews run VIEW-ONLY (edits are never written back;
 * deny+feedback is the change channel). An APPROVED outcome wires into the
 * `objectiveApprovalSave` seam (re-read the STRUCTURED artifact → `saveObjective` → D1a gate
 * exit → terminating); every other outcome maps via `objectiveReviewOutcomeResult`.
 */
export async function executeObjectiveReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  signal?: AbortSignal,
): Promise<ToolResult> {
  // 1. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  // 2. The draft artifact is the sole review source — no draft → soft skip with the
  //    objective_draft redirect.
  const draft = readObjectiveDraft(ctx);
  if (draft === null) {
    return {
      content: [
        {
          type: "text",
          text:
            "no objective draft to review — write the working objective with objective_draft " +
            "(prose + the structured roadmap), then call plan_review again.",
        },
      ],
      details: { status: "skipped", reason: "no_objective_draft" },
    };
  }
  // 3. The reviewed bytes are the RENDERED markdown (prose + roadmap table) — never raw JSON.
  const rendered = renderObjectiveDraft(draft);
  // 4. Backend dispatch (mirrors the plan path): plannotator-selected → the bridge; ANY other
  //    selection → the first-party editor, view-only.
  const sig = signal ?? ctx.signal;
  let outcome: ReviewOutcome;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    outcome = await bridge.review(rendered, sig);
  } else {
    const fp = await runFirstPartyReview({
      ui: ctx.ui,
      plan: rendered,
      writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
      signal: sig,
      editorTitle: OBJECTIVE_REVIEW_EDITOR_TITLE,
      verdicts: OBJECTIVE_VERDICTS,
      viewOnly: true,
    });
    outcome = fp.outcome;
  }
  // 5. An APPROVED decision (either backend) wires into the objectiveApprovalSave seam (the
  //    STRUCTURED artifact is re-read at save time — never the rendered bytes; auto-save → D1a
  //    gate exit → terminating result); everything else maps via objectiveReviewOutcomeResult.
  //    Approved-first routing: objectiveReviewOutcomeResult's completed case renders DENIED.
  if (outcome.status === "completed" && outcome.approved) {
    const save = await objectiveApprovalSave(pi, ctx, gating);
    return approvedObjectiveSaveResult(outcome, save);
  }
  return objectiveReviewOutcomeResult(outcome);
}

// ------------------------------------------------------------------------- the execute core

/**
 * The `plan_review` execute core, extracted pure-over-its-seams (the bridge, the gating, the
 * ctx) so the resolution + dispatch + approved-save paths are unit-testable offline. Arm order:
 * param decode → the objective-author arm (`executeObjectiveReview` — the rendered objective
 * draft is the review subject there) → headless skip → file-first resolution → backend
 * dispatch (plannotator-selected → the event-bus bridge; ANY other selection → the first-party
 * in-TUI editor review) → approved → `approvalSave`.
 */
export async function executePlanReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  params: unknown,
  signal?: AbortSignal,
): Promise<ToolResult> {
  // Tool-boundary decode, in this tool's native fail-open vocabulary: a MISTYPED
  // `plan` (or non-object params) skip-shapes (`reason: "bad_input"`) without reviewing; an
  // ABSENT `plan` proceeds — the validated draft artifact is the preferred source.
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
  // 1. Objective-author session → the objective review arm: the rendered
  //    objective draft is the sole review source; a well-typed `plan` param is ignored here.
  if (rebuildWorkflowState(branchOf(ctx)).stage === OBJECTIVE_AUTHOR_STAGE) {
    return executeObjectiveReview(pi, ctx, gating, bridge, signal ?? ctx.signal);
  }
  // 2. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  // 3. File-first resolution: artifact → param, NEVER transcript — an approval
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
  // 4. Backend dispatch: plannotator-selected → the event-bus bridge; ANY other selection
  //    (perk-plan, tombell, unknown ids) → the first-party in-TUI editor review.
  const sig = signal ?? ctx.signal;
  let outcome: ReviewOutcome;
  let reviewedPlan = src.plan;
  let edited = false;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    outcome = await bridge.review(src.plan, sig);
  } else {
    // The 4th verdict (implement-here, the no-save exit) is offered UNLESS this is an
    // objective-node planning session — a node-linked plan must save (the node advance and
    // backlink depend on it), so the claim suppresses it back to the 3-option select.
    const fp = await runFirstPartyReview({
      ui: ctx.ui,
      plan: src.plan,
      writeDraft: (text) => writePlanDraft(pi, ctx, text).details.ok,
      signal: sig,
      verdicts:
        readNodeClaim(ctx) === null
          ? {
              approve: VERDICT_APPROVE,
              deny: VERDICT_DENY,
              skip: VERDICT_SKIP,
              implementHere: VERDICT_IMPLEMENT_HERE,
            }
          : undefined,
    });
    outcome = fp.outcome;
    reviewedPlan = fp.plan;
    edited = fp.edited;
  }
  // 5. IMPLEMENT-HERE (first-party only) routes before the generic mapper (mirror the
  //    approved-first split): gate exit WITHOUT save through the implementHereExit seam → a
  //    NON-terminating result carrying the implement-now guidance.
  if (outcome.status === "implement-here") {
    const exit = implementHereExit(ctx, gating);
    return implementHereResult(outcome, exit, { cwd: ctx.cwd, plan: reviewedPlan, edited });
  }
  // 6. An APPROVED decision (either backend) wires into the approvalSave seam (auto-save → D1a
  //    gate exit → terminating result); everything else maps via reviewOutcomeResult.
  if (outcome.status === "completed" && outcome.approved) {
    const save = await approvalSave(pi, ctx, gating, { reviewedPlan });
    return approvedSaveResult(outcome, save, { paramMismatch: src.paramMismatch, edited });
  }
  return reviewOutcomeResult(outcome);
}

// ----------------------------------------------------------------------------- registration

/**
 * Register `plan_review` — perk's universal review door. In READ_ONLY_TOOLS so it is callable
 * INSIDE plan mode (the whole point — review happens before the gate ever comes off). Fail-open
 * everywhere: headless / dismissed / backend-unavailable all soft-skip so authoring never wedges.
 */
export function registerPlanReview(pi: ExtensionAPI, gating: ToolGating): void {
  const bridge = createPlannotatorBridge(pi.events);

  pi.registerTool({
    name: "plan_review",
    label: "Plan review",
    description:
      "Present the plan to the configured review surface — the Plannotator browser UI when " +
      "selected, otherwise perk's in-TUI editor review — and wait for the human decision. " +
      "Reviews the validated plan-draft artifact (keep it current with plan_draft); on approval " +
      "the plan is auto-saved and the turn terminates. On deny, revise per the returned " +
      "feedback, rewrite the draft with plan_draft, and call again. No-op skip when the session " +
      "is headless or the review is dismissed.",
    promptSnippet: "Request a human review of the working plan draft",
    promptGuidelines: [
      "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_review reviews AND auto-saves; the plan param is only a fallback when no draft exists.",
      "Call plan_review only when the plan is decision-complete.",
      "On a DENIED review, revise per the feedback, rewrite the draft with plan_draft, then call plan_review again.",
      "On an APPROVED review, the plan is auto-saved and the turn ends — never re-dump the plan as a final message and never tell the user to run /plan-save; relay the save outcome instead.",
      "If plan_review reports it was skipped or unavailable (headless, dismissed), fall back to presenting the complete plan; the human runs /plan-save (the manual failsafe).",
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
