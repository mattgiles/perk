// The shared review-surface machinery every review arm composes (plan, gist, objective): the
// review-outcome vocabulary, the subject descriptor + the shared outcome/approved-save mapper
// cores, the first-party in-TUI editor review core, and the launch chooser for the plannotator
// wave arm. This module imports NO provider adapter and NO feature module — it is the leaf the
// `pi/v1` arms (plan.ts/planReview.ts/objectiveReview.ts/gist.ts) and the browser doors share.
//
// REVIEW SEMANTICS (file-first, approval auto-saves) live with the arms; what lives HERE is the
// surface mechanics: `ctx.ui.editor` takes NO AbortSignal (unlike select/confirm/input) —
// `signal?.aborted` is checked between dialogs; an in-flight editor dialog survives a turn abort
// and its result is discarded (the aborted arm wins). Enter submits in the editor dialog
// (Shift+Enter = newline), so the dialog titles carry the key hints — pi renders no other
// affordance.

import { randomUUID } from "node:crypto";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Result } from "../../substrate/result.ts";

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
 * review arms and the gist arm (`pi/v1/gist.ts`) render the same outcome shapes, differing only
 * in these fields. Exported so an externally-owned review subject constructs its own descriptor
 * and reuses the cores.
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

/** The plan-arm descriptor (the plan-flavor mappers in planReview.ts delegate with it). */
export const PLAN_SUBJECT: ReviewSubject = {
  noun: "plan",
  present: "the complete plan to the user",
  presentUnavailable: "the complete plan to the user in your next message",
  implementHereWhere: "outside the execute path",
  draftTool: "plan_draft",
  failsafeCmd: "/plan-save",
  detailsExtra: {},
  noSourceError: "no plan source resolved",
};

export const SKIP_TEXT =
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

// ------------------------------------------------------ the launch chooser (the wave arm)

/**
 * The injected wave-launch deps (composed in index.ts from the door exports — structural on
 * purpose: this module imports NOTHING from door modules, avoiding the value-import cycle;
 * `planReviewBrowser.ts` value-imports the review arms). `present` is the plannotator
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
export function waveLaunchedResult(subject: ReviewSubject, guidance: string): ToolResult {
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
export const VERDICT_IMPLEMENT_HERE = "Implement here — no issue saved";

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
  /** Bound to the session draft write by the execute path. */
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
