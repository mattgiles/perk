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
// feedback and directs a `plan_draft` rewrite + re-review. Plannotator's browser "Direct Edits"
// (a `# Direct Edits` unified diff opening the feedback) are handled asymmetrically per arm: the
// PLAN arm mechanically applies an approved diff (strict apply → draft write-back → save the
// edited bytes; any failure falls open to the verbatim save + a loud warning); the OBJECTIVE arm
// cannot fold rendered-markdown edits into the structured draft, so an approve-with-edits SKIPS
// the save and returns one model-mediated revise round; DENY stays model-mediated on both arms. Strict on deny, FAIL-OPEN everywhere
// else: headless / dismissed (Esc anywhere = skip, mirroring ask_user_question's dismissal — deny
// is always explicit) / backend-unavailable all soft-skip so plan authoring never wedges — those
// arms keep the present-the-plan + human-`/plan-save` discipline (the manual failsafe).
//
// THE LAUNCH CHOOSER (plannotator arms only, §8.23): on an eligible round (injected `WaveLaunch`
// deps present, plannotator loaded, the review source a validated draft artifact) the tool first
// asks the human — "Browser review + reviewer wave" vs "Browser review only" — before anything
// launches. The wave choice collects an optional trimmed custom angle, delegates to the door's
// guidance-returning open core (openPlanReviewSurface / openObjectiveReviewSurface, injected —
// never imported: doors value-import this module), and returns the NON-terminating
// `wave_launched` result carrying the door guidance verbatim; the browser decision then routes
// through the door's background decision task. Esc ⇒ the plain flavor (never a cancel); abort
// outranks every dialog result AND the awaited opener (an interrupted turn never reports a
// launched wave); a null opener return (synchronous port-pick failure, loudly reported in the
// core) falls open to the plain blocking review in the same call.
//
// `ctx.ui.editor` takes NO AbortSignal (unlike select/confirm/input) — `signal?.aborted` is
// checked between dialogs; an in-flight editor dialog survives a turn abort and its result is
// discarded (the aborted arm wins). Enter submits in the editor dialog (Shift+Enter = newline),
// so the dialog titles carry the key hints — pi renders no other affordance.
//
// THE OBJECTIVE ARM: an objective-authoring session (read-only, stage `objective-author` or
// `objective-save` — the two stages whose working draft IS the objective draft; neither carries
// `plan_draft`) routes through `executeObjectiveReview` instead of the plan path — the
// reviewed bytes are the RENDERED objective draft (`readObjectiveDraft` + `renderObjectiveDraft`,
// objectiveDraft.ts — never raw JSON, never the `plan` param, never the transcript; no draft
// soft-skips with `reason: "no_objective_draft"`). Dispatch mirrors the plan path (plannotator
// bridge or the first-party editor, VIEW-ONLY — edits are never written back; deny+feedback is
// the change channel). An APPROVED outcome wires into the `objectiveApprovalSave` seam
// (objectiveSave.ts): re-read the STRUCTURED artifact → `saveObjective` → D1a gate
// exit → a TERMINATING result; a failed save is non-terminating, leaves the gate read-only, and
// directs the human `/objective-save` failsafe.
//
// THE GIST ARM is INJECTED: a gist-author session (read-only, stage `gist-author`) dispatches
// to the required `gistArm` parameter — composed in index.ts from the v1 gist installer
// (`pi/v1/gist.ts`, `runGistReviewV1`), which reuses this module's exported subject machinery
// (`ReviewSubject`, `subjectReviewOutcomeResult`, `approvedSubjectSaveResult`, `verdictsFor`,
// `skipResult`, `runFirstPartyReview`). One-directional: `pi/v1` imports this module's exports;
// this module never imports `pi/` — the injection breaks what would otherwise be a cycle.
//
// INVARIANTS HELD: never calls `setActiveTools`, never registers a `tool_call` handler, never
// restamps `cache.plan-ref.provider`. The door composes the gate AND the save EXCLUSIVELY
// through the `approvalSave` seam (Invariant 1: composes, never owns).

import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createPlannotatorBridge,
  extractDirectEdits,
  hasDirectEditsHeading,
  isPlannotatorPlanSelected,
} from "../adapters/planAdapterPlannotator.ts";
import { GIST_AUTHOR_STAGE } from "../authoring/gist/draft.ts";
import type { Result } from "../substrate/result.ts";
import { readSessionArtifact } from "../substrate/sessionData.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import { applyUnifiedDiff } from "../substrate/unifiedDiff.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { implementHereExit, implementHereGuidance } from "./implementHere.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";
import {
  OBJECTIVE_DRAFT_ARTIFACT,
  readObjectiveDraft,
  renderObjectiveDraft,
} from "./objectiveDraft.ts";
import { readNodeClaim } from "./objectivePlan.ts";
import {
  OBJECTIVE_SAVE_STAGE,
  type ObjectiveApprovalSaveOutcome,
  objectiveApprovalSave,
} from "./objectiveSave.ts";
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

export interface ToolResult {
  content: { type: "text"; text: string }[];
  details: Record<string, unknown>;
  terminate?: boolean;
}

/**
 * The subject descriptor parameterizing the shared renderer cores below — the plan and objective
 * review arms (in this module) and the injected gist arm (`pi/v1/gist.ts`) render the same
 * outcome shapes, differing only in these fields. Exported so an externally-owned review subject
 * constructs its own descriptor and reuses the cores.
 */
export interface ReviewSubject {
  /** The display noun in every rendered text ("plan" / "objective"). */
  noun: string;
  /** The lowercase present-the-work phrase (dismissed / implement-here arms). */
  present: string;
  /** The unavailable-arm phrase (the plan flavor appends "in your next message"). */
  presentUnavailable: string;
  /** Where an implement-here verdict "cannot" have come from (the defensive arm's text). */
  implementHereWhere: string;
  /** The draft-rewrite tool the DENIED text redirects to. */
  draftTool: string;
  /** The manual-failsafe slash command. */
  failsafeCmd: string;
  /** Extra keys merged into every details object ({} on the plan arm). */
  detailsExtra: Record<string, unknown>;
  /** The defensively-unreachable no-source save arm's error string. */
  noSourceError: string;
}

const PLAN_SUBJECT: ReviewSubject = {
  noun: "plan",
  present: "the complete plan to the user",
  presentUnavailable: "the complete plan to the user in your next message",
  implementHereWhere: "outside the execute path",
  draftTool: "plan_draft",
  failsafeCmd: "/plan-save",
  detailsExtra: {},
  noSourceError: "no plan source resolved",
};

const OBJECTIVE_SUBJECT: ReviewSubject = {
  noun: "objective",
  present: "the complete objective + structured roadmap to the user",
  presentUnavailable: "the complete objective + structured roadmap to the user",
  implementHereWhere: "on the objective path",
  draftTool: "objective_draft",
  failsafeCmd: "/objective-save",
  detailsExtra: { subject: "objective" },
  noSourceError: "no objective draft resolved",
};

const SKIP_TEXT =
  "no interactive review surface available — present the complete plan to the user in your next message.";

export function skipResult(): ToolResult {
  return { content: [{ type: "text", text: SKIP_TEXT }], details: { ok: true, status: "skipped" } };
}

/**
 * The shared outcome-mapper core: map a non-approved review outcome into the model-facing tool
 * result for `subject`. The `completed` case renders the DENIED text — both execute paths route
 * approved outcomes to their approved-save mapper FIRST, so callers only reach `completed` here
 * with `approved: false` (kept total for safety; the `approved: outcome.approved` passthrough is
 * deliberately behavior-preserving — never hardcode `false`). The `dismissed` arm renders as a
 * skip — the human declined to decide, so the present-the-work + manual-failsafe discipline
 * applies.
 */
export function subjectReviewOutcomeResult(
  subject: ReviewSubject,
  outcome: ReviewOutcome,
): ToolResult {
  switch (outcome.status) {
    case "unavailable":
      return {
        content: [
          {
            type: "text",
            text:
              `WARNING: ${outcome.warning} — no review performed. ` +
              `Present ${subject.presentUnavailable} instead.`,
          },
        ],
        details: {
          ok: false,
          error: outcome.warning,
          error_type: "unavailable",
          status: "unavailable",
          ...subject.detailsExtra,
        },
      };
    case "aborted":
      return {
        content: [{ type: "text", text: `${subject.noun} review aborted (turn interrupted).` }],
        details: { ok: true, status: "aborted", ...subject.detailsExtra },
      };
    case "dismissed":
      return {
        content: [
          {
            type: "text",
            text:
              `${subject.noun} review dismissed — present ${subject.present}; the human runs ` +
              `${subject.failsafeCmd} (the manual failsafe).`,
          },
        ],
        details: { ok: true, status: "skipped", reason: "dismissed", ...subject.detailsExtra },
      };
    case "implement-here":
      // Defensively unreachable: the plan execute path routes implement-here to
      // implementHereResult FIRST (mirror the approved-first routing), and the objective arm
      // never offers the verdict. Map to a skip shape rather than throwing.
      return {
        content: [
          {
            type: "text",
            text:
              `implement-here verdict received ${subject.implementHereWhere} — nothing saved; ` +
              `present ${subject.present}.`,
          },
        ],
        details: { ok: true, status: "skipped", reason: "implement-here", ...subject.detailsExtra },
      };
    case "completed": {
      const feedback = outcome.feedback ? `\n\nReviewer feedback:\n${outcome.feedback}` : "";
      const text =
        `${subject.noun} DENIED — revise per this feedback, rewrite the working draft with ` +
        `${subject.draftTool}, then call plan_review again.${feedback}`;
      return {
        content: [{ type: "text", text }],
        details: {
          ok: true,
          status: "completed",
          approved: outcome.approved,
          feedback: outcome.feedback ?? null,
          reviewId: outcome.reviewId,
          ...subject.detailsExtra,
        },
      };
    }
  }
}

/**
 * Map a non-approved review outcome into the model-facing tool result (exported for the offline
 * tests) — the plan flavor of `subjectReviewOutcomeResult`. The execute path routes approved
 * outcomes to `approvedSaveResult` first, so `completed` renders DENIED here.
 */
export function reviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  return subjectReviewOutcomeResult(PLAN_SUBJECT, outcome);
}

/**
 * The normalized approval-save outcome the shared core consumes — each delegator maps its
 * subject-specific no-source discriminant (`no-plan` / `no-draft`) onto `no-source`. `result`
 * widens to `Result<object>`: the core reads only `content[0]?.text` and the `details.ok`
 * discriminant (+ `details.error` on the fail arm), passing `details` through opaquely.
 */
export type SubjectSaveOutcome =
  | { status: "no-source" }
  | { status: "saved" | "save-failed"; result: Result<object>; gateExited: boolean };

/**
 * The shared approved-save mapper core: map an APPROVED review outcome + the approval-save
 * outcome into the model-facing tool result for `subject`. A successful save TERMINATES the turn
 * (propagating the seam's `terminate: true` intent); a failed save is non-terminating, leaves
 * the gate read-only, and directs the human manual failsafe. Reviewer feedback is surfaced
 * loudly as implementation guidance — the approved bytes were saved verbatim, never post-edited.
 * The `paramMismatch`/`edited`/`directEditsFailed` opts are plan-arm-only (their literals name
 * "plan"/"draft"): the objective delegator never passes opts, so the suffixes render empty and
 * `edited` never reaches its details. `directEditsFailed` (plannotator-only) flags that a Direct
 * Edits section was seen but could not be honored — the saved arm gains a loud warning that the
 * plan was saved WITHOUT the reviewer's edits, and details carry `direct_edits_applied: false`.
 * The `no-source` arm is defensively unreachable (the reviewed source is always
 * non-blank) but maps to the save-failed shape rather than throwing.
 */
export function approvedSubjectSaveResult(
  subject: ReviewSubject,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: SubjectSaveOutcome,
  opts?: { paramMismatch?: boolean; edited?: boolean; directEditsFailed?: boolean },
): ToolResult {
  const feedback = outcome.feedback
    ? `\n\nReviewer feedback (implementation guidance — the approved ${subject.noun} was saved ` +
      `verbatim):\n${outcome.feedback}`
    : "";
  const base = {
    status: "completed",
    approved: true,
    reviewId: outcome.reviewId,
    feedback: outcome.feedback ?? null,
    ...subject.detailsExtra,
    ...(opts?.edited === true ? { edited: true } : {}),
    ...(opts?.directEditsFailed === true ? { direct_edits_applied: false } : {}),
  };
  if (save.status === "saved") {
    const saveText = save.result.content[0]?.text ?? "";
    const edited =
      opts?.edited === true ? " · human edits were written back to the draft and saved" : "";
    const mismatch =
      opts?.paramMismatch === true
        ? "\n\n⚠ differing plan param ignored — the validated draft was reviewed and saved."
        : "";
    const editsWarning =
      opts?.directEditsFailed === true
        ? "\n\n⚠ WARNING: the reviewer's Direct Edits could NOT be auto-applied — the plan was " +
          "saved WITHOUT them. The diff remains in the reviewer feedback above; apply it to the " +
          "plan issue manually or via a follow-up."
        : "";
    return {
      content: [
        {
          type: "text",
          text: `${subject.noun} APPROVED by reviewer.${feedback}\n\n${saveText}${edited}${mismatch}${editsWarning}`,
        },
      ],
      // `ok` sits per-branch, NOT in `base` — `base` is spread into the fail branch too.
      details: {
        ok: true,
        ...base,
        saved: true,
        gateExited: save.gateExited,
        save: save.result.details,
      },
      terminate: true,
    };
  }
  const error =
    save.status === "no-source"
      ? subject.noSourceError
      : save.result.details.ok
        ? "unknown save failure"
        : save.result.details.error;
  return {
    content: [
      {
        type: "text",
        text:
          `${subject.noun} APPROVED by reviewer, but the auto-save FAILED (${error}) — the ` +
          `session stays read-only. Ask the user to run ${subject.failsafeCmd} (the manual ` +
          `failsafe) to retry.${feedback}`,
      },
    ],
    details: {
      ok: false,
      error,
      error_type: "save_failed",
      ...base,
      saved: false,
      save: save.status === "no-source" ? null : save.result.details,
    },
  };
}

/**
 * Map an APPROVED review outcome + the `approvalSave` outcome into the model-facing tool result
 * (exported for the offline tests) — the plan flavor of `approvedSubjectSaveResult`. `edited`
 * flags that human edits were written back to the draft pre-verdict (the first-party editor, or
 * the plannotator Direct Edits auto-apply), so the saved bytes carry them. `directEditsFailed`
 * (plannotator-only, optional — absent keeps every existing call site byte-stable) flags a
 * Direct Edits section that could not be honored: the plan saved verbatim, a loud warning added.
 */
export function approvedSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ApprovalSaveOutcome,
  opts: { paramMismatch: boolean; edited?: boolean; directEditsFailed?: boolean },
): ToolResult {
  return approvedSubjectSaveResult(
    PLAN_SUBJECT,
    outcome,
    save.status === "no-plan" ? { status: "no-source" } : save,
    opts,
  );
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
      ok: true,
      status: "implement-here",
      saved: false,
      gateExited: exit.gateExited,
      reviewId: outcome.reviewId,
      ...(opts.edited ? { edited: true } : {}),
    },
  };
}

// ------------------------------------------------------ the plannotator Direct-Edits apply

/**
 * The shared plannotator APPROVE mechanical-apply path (contracts.md §8.23): inspect an
 * APPROVED outcome's feedback for a `# Direct Edits` section and mechanically apply the
 * reviewer's diff to the exact bytes reviewed (`basePlan`), writing the patched bytes back to
 * the draft (reviewed bytes == artifact bytes == saved bytes). Consumed by `executePlanReview`'s
 * plannotator arm AND the `/plan-review-browser` door — one apply path, byte-identical
 * semantics:
 *
 * - only an `approved` outcome WITH feedback is inspected (anything else passes through
 *   verbatim);
 * - a clean extract + apply + write-back swaps `reviewedPlan` to the patched bytes, sets
 *   `edited: true`, and strips the applied section from the returned outcome's feedback (only
 *   the annotation remainder survives — the applied diff must never render as "apply these
 *   exact changes" guidance);
 * - a seen-but-unhonorable heading (or a failed apply / write-back) sets
 *   `directEditsFailed: true` with the plan left verbatim (the caller renders the loud warning;
 *   the diff stays in the surfaced feedback for a manual follow-up).
 */
export function applyPlannotatorDirectEdits(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  basePlan: string,
): {
  outcome: Extract<ReviewOutcome, { status: "completed" }>;
  reviewedPlan: string;
  edited: boolean;
  directEditsFailed: boolean;
} {
  if (!outcome.approved || outcome.feedback === undefined) {
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: false };
  }
  const section = extractDirectEdits(outcome.feedback);
  if (section !== null) {
    const patched = applyUnifiedDiff(basePlan, section.diff);
    if (patched !== null && writePlanDraft(pi, ctx, patched).details.ok) {
      return {
        outcome: { ...outcome, feedback: section.remainder },
        reviewedPlan: patched,
        edited: true,
        directEditsFailed: false,
      };
    }
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: true };
  }
  if (hasDirectEditsHeading(outcome.feedback)) {
    return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: true };
  }
  return { outcome, reviewedPlan: basePlan, edited: false, directEditsFailed: false };
}

// ------------------------------------------------------ the launch chooser (the wave arm)

/**
 * The injected wave-launch deps (composed in index.ts from the door exports — structural on
 * purpose: this module imports NOTHING from door modules, avoiding the value-import cycle;
 * `planReviewBrowser.ts` already value-imports this module). `present` is the plannotator
 * presence probe (`plannotatorPresent(pi)` at the call site); `plan`/`objective` are the
 * guidance-returning door open cores (`openPlanReviewSurface` / `openObjectiveReviewSurface`) —
 * one open path, byte-identical door semantics (contracts.md §8.23). `null` from an opener is
 * the synchronous port-pick failure (already loudly reported inside the core) — the caller
 * falls open to the plain blocking review.
 */
export interface WaveLaunch {
  present(): boolean;
  plan(ctx: ExtensionContext, opts: { draft: string; custom?: string }): Promise<string | null>;
  objective(
    ctx: ExtensionContext,
    opts: { rendered: string; artifactRaw: string; custom?: string },
  ): Promise<string | null>;
}

/** The minimal structural `ctx.ui` subset the launch chooser needs (both dialogs signal-aware). */
export interface ReviewLaunchUI {
  select(
    title: string,
    options: string[],
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
  input(
    title: string,
    placeholder?: string,
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
}

/** The launch chooser's outcome: the review flavor (never a cancel), or the aborted turn. */
export type ReviewLaunchChoice =
  | { launch: "plain" }
  | { launch: "wave"; custom?: string }
  | { launch: "aborted" };

const LAUNCH_WAVE = "Browser review + reviewer wave";
const LAUNCH_PLAIN = "Browser review only";
const CUSTOM_ANGLE_TITLE = "Custom review angle (optional — Enter to skip)";

/**
 * The launch chooser (pure over the injected ui slice — offline-testable): every eligible
 * plannotator round asks the human whether the browser review launches WITH the streamed
 * reviewer wave; the wave choice then asks for an optional custom review angle. Esc/dismiss
 * anywhere selects a FLAVOR, never cancels the review (Esc at the chooser ⇒ plain; Esc/blank at
 * the angle input ⇒ wave with no custom lane — the input is `.trim()`'d before blank detection,
 * the door handlers' exact discipline). ABORT OUTRANKS EVERYTHING: `signal?.aborted` is checked
 * at entry and re-checked immediately after each awaited dialog, BEFORE interpreting its result
 * (the `runFirstPartyReview` discipline) — a conforming caller can never launch a browser or
 * enter a blocking review after the turn was interrupted. No other return paths exist.
 */
export async function chooseReviewLaunch(
  ui: ReviewLaunchUI,
  subjectNoun: string,
  signal?: AbortSignal,
): Promise<ReviewLaunchChoice> {
  if (signal?.aborted) return { launch: "aborted" };
  const picked = await ui.select(`${subjectNoun} review launch`, [LAUNCH_WAVE, LAUNCH_PLAIN], {
    signal,
  });
  if (signal?.aborted) return { launch: "aborted" }; // abort outranks Esc AND any selection
  if (picked !== LAUNCH_WAVE) return { launch: "plain" }; // Esc/dismiss = the plain flavor
  const raw = await ui.input(CUSTOM_ANGLE_TITLE, undefined, { signal });
  if (signal?.aborted) return { launch: "aborted" }; // abort outranks the input result too
  const custom = (raw ?? "").trim();
  return custom.length > 0 ? { launch: "wave", custom } : { launch: "wave" };
}

/**
 * The NON-terminating wave-launched result: the door core's guidance rides back verbatim as the
 * tool text (same templates, same binding suffix — the model behaves identically whether the
 * human summoned the door or chose the wave inside `plan_review`), and the human's browser
 * decision routes through the door's background decision task — never through this call.
 */
function waveLaunchedResult(subject: ReviewSubject, guidance: string): ToolResult {
  return {
    content: [{ type: "text", text: guidance }],
    details: { ok: true, status: "wave_launched", ...subject.detailsExtra },
  };
}

// ----------------------------------------------------------------- the first-party review core

/** The minimal structural `ctx.ui` subset the first-party review needs (the ciExecutor.ts pure-core + injected-fakes recipe). */
export interface PlanReviewUI {
  editor(title: string, prefill?: string): Promise<string | undefined>;
  select(
    title: string,
    options: string[],
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
}

/**
 * Derive a subject's verdict options (plain text — charter D3: no emoji outside the footer);
 * only the skip label's manual-failsafe command varies by subject. `VERDICT_IMPLEMENT_HERE`
 * stays a standalone constant on purpose — the no-save exit is plan-arm-only by contract
 * (§8.23), never part of the descriptor.
 */
export function verdictsFor(subject: ReviewSubject): {
  approve: string;
  deny: string;
  skip: string;
} {
  return {
    approve: "Approve — auto-save to GitHub",
    deny: "Deny — send feedback for revision",
    skip: `Skip — decide later (manual ${subject.failsafeCmd})`,
  };
}

/** The optional 4th verdict (plan arm only): the no-save implement-here exit (§8.23). */
const VERDICT_IMPLEMENT_HERE = "Implement here — no issue saved";

const REVIEW_EDITOR_TITLE =
  "Plan review — Enter: continue to verdict · Esc: skip · Ctrl+G: $EDITOR";
const DENY_FEEDBACK_TITLE = "Deny feedback (optional) — Enter to send";

/**
 * The first-party in-TUI review core, pure over injected seams (the ciExecutor.ts pure-core + injected-fakes recipe) — fully
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
  const verdicts: { approve: string; deny: string; skip: string; implementHere?: string } =
    args.verdicts ?? verdictsFor(PLAN_SUBJECT);
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

const OBJECTIVE_REVIEW_EDITOR_TITLE =
  "Objective review (view only — edits are not saved) — Enter: continue to verdict · Esc: skip · " +
  "Ctrl+G: $EDITOR";

/**
 * Map a non-approved objective review outcome into the model-facing tool result (exported for
 * the offline tests) — the objective-flavored sibling of `reviewOutcomeResult`, delegating to
 * `subjectReviewOutcomeResult` with `OBJECTIVE_SUBJECT`. Every arm carries
 * `details.subject: "objective"`; the texts redirect to `objective_draft` / `/objective-save`.
 * The execute path routes approved outcomes to `approvedObjectiveSaveResult` first, so
 * `completed` renders DENIED here.
 */
export function objectiveReviewOutcomeResult(outcome: ReviewOutcome): ToolResult {
  return subjectReviewOutcomeResult(OBJECTIVE_SUBJECT, outcome);
}

/**
 * Map an APPROVED objective review outcome + the `objectiveApprovalSave` outcome into the
 * model-facing tool result (exported for the offline tests) — the objective sibling of
 * `approvedSaveResult`, delegating to `approvedSubjectSaveResult` with `OBJECTIVE_SUBJECT` and
 * no opts (the objective path reviews only the rendered draft, view-only — no
 * `paramMismatch`/`edited`).
 */
export function approvedObjectiveSaveResult(
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  save: ObjectiveApprovalSaveOutcome,
): ToolResult {
  return approvedSubjectSaveResult(
    OBJECTIVE_SUBJECT,
    outcome,
    save.status === "no-draft" ? { status: "no-source" } : save,
  );
}

/**
 * The objective review arm, mirroring `executePlanReview`'s shape but
 * with the rendered objective draft as the SOLE review source (never the `plan` param, never
 * the transcript). First-party reviews run VIEW-ONLY (edits are never written back;
 * deny+feedback is the change channel). An APPROVED outcome wires into the
 * `objectiveApprovalSave` seam (re-read the STRUCTURED artifact → `saveObjective` → D1a gate
 * exit → terminating); every other outcome maps via `objectiveReviewOutcomeResult`. ONE
 * carve-out (plannotator only): an approval whose feedback opens a Direct Edits section SKIPS
 * the save — rendered-markdown edits cannot be folded back into the structured draft
 * mechanically — and returns a NON-terminating revise round with the gate untouched (fold the
 * diff in via `objective_draft`, re-review to confirm); perk never saves an objective the
 * reviewer explicitly edited away from.
 */
export async function executeObjectiveReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  signal?: AbortSignal,
  wave?: WaveLaunch,
): Promise<ToolResult> {
  // 1. Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  // 2. The wave arm's stale-guard baseline is captured BEFORE the validated read below (the
  //    objective door's fail-closed ordering): the rendered bytes always derive from a read at
  //    or after this baseline, so a concurrent objective_draft write between the two reads makes
  //    the browsed render NEWER than the baseline and routeObjectiveReviewDecision's existing
  //    guard refuses the approval — the reverse order would fail open (approve unreviewed
  //    bytes). Raw artifact bytes on purpose: the save-authoritative surface catches
  //    render-invisible changes.
  const baseline = readSessionArtifact(ctx, OBJECTIVE_DRAFT_ARTIFACT);
  // 3. The draft artifact is the sole review source — no draft → soft skip with the
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
      details: {
        ok: false,
        error: "no objective draft to review — write it with objective_draft first",
        error_type: "no_objective_draft",
        status: "skipped",
        reason: "no_objective_draft",
      },
    };
  }
  // 4. The reviewed bytes are the RENDERED markdown (prose + roadmap table) — never raw JSON.
  const rendered = renderObjectiveDraft(draft);
  // 5. Backend dispatch (mirrors the plan path): plannotator-selected → the bridge; ANY other
  //    selection → the first-party editor, view-only.
  const sig = signal ?? ctx.signal;
  let outcome: ReviewOutcome;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door stale-guards the raw artifact baseline, so a null baseline keeps the plain path
    // (silently: there is no forced mode to warn about).
    if (wave?.present() && baseline !== null) {
      const choice = await chooseReviewLaunch(ctx.ui, "Objective", sig);
      if (choice.launch === "aborted") return objectiveReviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave.objective(ctx, {
          rendered,
          artifactRaw: baseline.content,
          ...(choice.custom !== undefined ? { custom: choice.custom } : {}),
        });
        // Abort outranks the opener result too: a turn interrupted during the awaited open must
        // never report a successful launch (the door's own bridge abort handling settles the
        // background tasks and clears the primed surfaces).
        if (sig?.aborted) return objectiveReviewOutcomeResult({ status: "aborted" });
        if (guidance !== null) return waveLaunchedResult(OBJECTIVE_SUBJECT, guidance);
        // null = the synchronous port-pick failure (already loudly reported inside the core) —
        // fall open to the plain blocking review in the same call: the review never wedges.
      }
    }
    outcome = await bridge.review(rendered, sig);
    // APPROVE + Direct Edits (browser edits of the RENDERED markdown), checked BEFORE the
    // approved-save routing (the approved-first discipline): the save seam re-reads the
    // STRUCTURED artifact, so rendered-markdown edits — roadmap-table rows included — cannot be
    // folded back without model judgment. Skip the save, keep the gate read-only, and route ONE
    // revise round: the model folds the diff into `objective_draft`, then re-reviews to confirm.
    // The heading check suffices (extraction success is irrelevant here — the diff goes to the
    // model verbatim either way).
    if (
      outcome.status === "completed" &&
      outcome.approved &&
      outcome.feedback !== undefined &&
      hasDirectEditsHeading(outcome.feedback)
    ) {
      return {
        content: [
          {
            type: "text",
            text:
              "objective APPROVED with direct browser edits — these cannot be auto-applied to " +
              "the structured draft, so nothing was saved. Fold the Direct Edits diff below into " +
              "the working draft with objective_draft (prose hunks → the prose; roadmap-table " +
              "hunks → the matching node fields), then call plan_review again to confirm.\n\n" +
              `Reviewer feedback:\n${outcome.feedback}`,
          },
        ],
        details: {
          ok: true,
          status: "revise",
          reason: "direct_edits",
          approved: true,
          feedback: outcome.feedback,
          reviewId: outcome.reviewId,
          subject: "objective",
        },
      };
    }
  } else {
    const fp = await runFirstPartyReview({
      ui: ctx.ui,
      plan: rendered,
      writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
      signal: sig,
      editorTitle: OBJECTIVE_REVIEW_EDITOR_TITLE,
      verdicts: verdictsFor(OBJECTIVE_SUBJECT),
      viewOnly: true,
    });
    outcome = fp.outcome;
  }
  // 6. An APPROVED decision (either backend) wires into the objectiveApprovalSave seam (the
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
 * The injected gist review arm's shape (structural on purpose — this module imports NOTHING
 * from `pi/`): index.ts composes it from the v1 gist installer (`runGistReviewV1`), and the
 * gist stage dispatch below calls it with this module's bridge + gating.
 */
export type GistReviewArm = (
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  signal?: AbortSignal,
) => Promise<ToolResult>;

/**
 * The `plan_review` execute core, extracted pure-over-its-seams (the bridge, the gating, the
 * ctx) so the resolution + dispatch + approved-save paths are unit-testable offline. Arm order:
 * param decode → the objective arm (`executeObjectiveReview` — the rendered objective draft is
 * the review subject in BOTH objective-authoring stages) → headless skip → file-first
 * resolution → backend
 * dispatch (plannotator-selected → the event-bus bridge; ANY other selection → the first-party
 * in-TUI editor review) → approved → `approvalSave`.
 */
export async function executePlanReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  gistArm: GistReviewArm,
  params: unknown,
  signal?: AbortSignal,
  wave?: WaveLaunch,
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
      details: {
        ok: false,
        error: "plan must be a string",
        error_type: "bad_input",
        status: "skipped",
        reason: "bad_input",
      },
    };
  }
  // 1. An objective-authoring session (objective-author OR objective-save — both stages'
  //    working draft is the objective draft, and neither carries `plan_draft`) → the objective
  //    review arm: the rendered objective draft is the sole review source; a well-typed `plan`
  //    param is ignored here — the plan-arm fallthrough could otherwise review/save an
  //    unrelated plan param from an objective session. A gist-author session likewise routes to
  //    the gist arm (the rendered gist draft).
  const launchedStage = rebuildWorkflowState(branchOf(ctx)).stage;
  if (launchedStage === OBJECTIVE_AUTHOR_STAGE || launchedStage === OBJECTIVE_SAVE_STAGE) {
    return executeObjectiveReview(pi, ctx, gating, bridge, signal ?? ctx.signal, wave);
  }
  if (launchedStage === GIST_AUTHOR_STAGE) {
    return gistArm(pi, ctx, gating, bridge, signal ?? ctx.signal);
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
      details: {
        ok: false,
        error: "no plan to review — write the draft with plan_draft first",
        error_type: "no_plan",
        status: "skipped",
        reason: "no_plan",
      },
    };
  }
  // 4. Backend dispatch: plannotator-selected → the event-bus bridge; ANY other selection
  //    (perk-plan, tombell, unknown ids) → the first-party in-TUI editor review.
  const sig = signal ?? ctx.signal;
  let outcome: ReviewOutcome;
  let reviewedPlan = src.plan;
  let edited = false;
  let directEditsFailed = false;
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    // The launch chooser (contracts.md §8.23): every eligible round the human picks with/without
    // the streamed reviewer wave BEFORE anything launches. Eligibility is drafts-only — the wave
    // door reviews and stale-guards the validated artifact, so a param-tier source keeps the
    // plain path (silently: there is no forced mode to warn about; the `wave === undefined` arm
    // is defensive/test-only and behaves identically).
    if (wave?.present() && src.source === "plan-draft") {
      const choice = await chooseReviewLaunch(ctx.ui, "Plan", sig);
      if (choice.launch === "aborted") return reviewOutcomeResult({ status: "aborted" });
      if (choice.launch === "wave") {
        const guidance = await wave.plan(ctx, {
          draft: src.plan,
          ...(choice.custom !== undefined ? { custom: choice.custom } : {}),
        });
        // Abort outranks the opener result too: a turn interrupted during the awaited open must
        // never report a successful launch (the door's own bridge abort handling settles the
        // background tasks and clears the primed surfaces).
        if (sig?.aborted) return reviewOutcomeResult({ status: "aborted" });
        if (guidance !== null) return waveLaunchedResult(PLAN_SUBJECT, guidance);
        // null = the synchronous port-pick failure (already loudly reported inside the core) —
        // fall open to the plain blocking review in the same call: the review never wedges.
      }
    }
    outcome = await bridge.review(src.plan, sig);
    // APPROVE + Direct Edits (browser plan edits, contracts.md §8.23): mechanically apply the
    // reviewer's diff via the shared helper (the first-party pre-verdict write-back, replayed
    // here post-verdict because the bridge only reports the diff), and save the EDITED bytes.
    // Every rung fails open to the verbatim path (never save bytes the artifact doesn't carry).
    // DENY stays model-mediated — the feedback (diff included) passes through for the
    // plan_draft rewrite.
    if (outcome.status === "completed") {
      const applied = applyPlannotatorDirectEdits(pi, ctx, outcome, src.plan);
      outcome = applied.outcome;
      reviewedPlan = applied.reviewedPlan;
      edited = applied.edited;
      directEditsFailed = applied.directEditsFailed;
    }
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
          ? { ...verdictsFor(PLAN_SUBJECT), implementHere: VERDICT_IMPLEMENT_HERE }
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
    return approvedSaveResult(outcome, save, {
      paramMismatch: src.paramMismatch,
      edited,
      directEditsFailed,
    });
  }
  return reviewOutcomeResult(outcome);
}

// ----------------------------------------------------------------------------- registration

/**
 * Register `plan_review` — perk's universal review door. In READ_ONLY_TOOLS so it is callable
 * INSIDE plan mode (the whole point — review happens before the gate ever comes off). Fail-open
 * everywhere: headless / dismissed / backend-unavailable all soft-skip so authoring never wedges.
 * `gistArm` is the injected gist review arm (index.ts composes it from the v1 gist installer);
 * `wave` is the injected wave-launch deps (index.ts composes them from the door open cores);
 * absent ⇒ the chooser never appears and every path is byte-stable.
 */
export function registerPlanReview(
  pi: ExtensionAPI,
  gating: ToolGating,
  gistArm: GistReviewArm,
  wave?: WaveLaunch,
): void {
  const bridge = createPlannotatorBridge(pi.events);

  pi.registerTool({
    name: "plan_review",
    label: "Plan review",
    description:
      "Present the plan to the configured review surface — the Plannotator browser UI when " +
      "selected, otherwise perk's in-TUI editor review — and wait for the human decision. " +
      "Reviews the validated plan-draft artifact (keep it current with plan_draft); on approval " +
      "the plan is auto-saved and the turn terminates. On deny, revise per the returned " +
      "feedback, rewrite the draft with plan_draft, and call again. On the Plannotator surface " +
      "the human may first opt into a streamed reviewer wave — the call then returns immediately " +
      'with wave guidance (status "wave_launched") to follow in the same turn, and the browser ' +
      "decision routes back automatically. No-op skip when the session is headless or the " +
      "review is dismissed.",
    promptSnippet: "Request a human review of the working plan draft",
    promptGuidelines: [
      "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_review reviews AND auto-saves; the plan param is only a fallback when no draft exists.",
      "Call plan_review only when the plan is decision-complete.",
      "On a DENIED review, revise per the feedback, rewrite the draft with plan_draft, then call plan_review again.",
      "On an APPROVED plan_review, the plan is auto-saved and the turn ends — never re-dump the plan as a final message and never tell the user to run /plan-save; relay the save outcome instead.",
      "On a wave_launched result (the human opted into the reviewer wave), follow the returned guidance in the same turn — launch the wave and relay its findings; the human's browser decision routes back automatically, so never re-call plan_review while that browser review is open.",
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
      return executePlanReview(pi, ctx, gating, bridge, gistArm, params, signal, wave);
    },
  });
}
