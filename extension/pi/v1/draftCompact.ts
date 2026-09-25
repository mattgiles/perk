// The draft + compaction bindings: the warm `/draft-and-compact` command — the read-only
// authoring twin of `/commit-and-compact` — expressed as one spec over the shared
// driven-compaction seam (`pi/v1/drivenCompaction.ts`), adapting the Pi-free operation in
// `authoring/draftCompact.ts`. Human-only slash command (no model-facing tool twin, no cold door,
// no workflow-state field — warm-plane only). The drive embeds the CURRENT draft bytes so the
// whole-value writers rewrite from the authoritative artifact; the continuation embeds the
// just-written draft (a message carries it without the `read` tool's per-line bound — JSON
// artifacts keep the prose on one physical line). Both fence the bytes as untrusted DATA.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  type DraftCompactCompletion,
  type DraftCompactPending,
  settleDraftAndCompact,
  startDraftAndCompact,
} from "../../authoring/draftCompact.ts";
import { DRAFT_SUBJECT_WRITERS, type DraftSubject } from "../../authoring/review/subjects.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { render } from "../../substrate/prompts.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { fenceSafe, installDrivenCompaction } from "./drivenCompaction.ts";

/** The fence tag both renders quote the draft inside. */
const DRAFT_FENCE = "working-draft";

/** The driven checkpoint guidance (the subject literal doubles as the noun). */
export function draftAndCompactGuidance(subject: DraftSubject, current: string | null): string {
  return render("draft-and-compact.md", {
    writer: DRAFT_SUBJECT_WRITERS[subject],
    noun: subject,
    is_objective: subject === "objective" ? "x" : "",
    is_gist: subject === "gist" ? "x" : "",
    has_draft: current === null ? "" : "x",
    draft: current === null ? "" : fenceSafe(current, DRAFT_FENCE),
  });
}

/** The completion-gated resume turn, embedding the just-written draft. */
export function draftAndCompactContinuation(subject: DraftSubject, content: string): string {
  return render("draft-and-compact-continuation.md", {
    writer: DRAFT_SUBJECT_WRITERS[subject],
    noun: subject,
    is_objective: subject === "objective" ? "x" : "",
    is_gist: subject === "gist" ? "x" : "",
    is_refinement: subject === "refinement" ? "x" : "",
    draft: fenceSafe(content, DRAFT_FENCE),
  });
}

/** The loud invocation skips, keyed by the typed reasons (a missing key fails to compile). */
const START_WARNINGS = {
  "not-gated":
    "not a read-only authoring session — nothing to draft; run /commit-and-compact (or /compact) instead.",
  "no-identity":
    "session has no run_id — the draft tools cannot write; run /compact to compact anyway.",
  "invalid-state":
    "session workflow state is malformed — compaction skipped; run /compact to compact anyway.",
} as const;

/** The loud settle skips — every one names pi's builtin `/compact` escape hatch. */
const SETTLE_WARNINGS = {
  "run-changed":
    "the session's run identity changed during the checkpoint turn — compaction skipped; run /compact to compact anyway.",
  "no-draft":
    "no valid working draft was written — compaction skipped; run /compact to compact anyway.",
  "unchanged-draft":
    "the working draft is unchanged since invocation — compaction skipped; run /compact to compact anyway.",
} as const;

/** Register the `/draft-and-compact` door: one spec over the driven-compaction seam. */
export function installDraftCompactBindings(pi: ExtensionAPI, gating: ToolGating): void {
  installDrivenCompaction<DraftCompactPending, DraftCompactCompletion>(pi, {
    command: "draft-and-compact",
    description:
      "Checkpoint the working draft (a driven model turn rewrites it from the current " +
      "artifact, recording open questions in an `## Unresolved` section), compact, then " +
      "continue automatically on the draft after compaction succeeds. Only read-only authoring " +
      "sessions qualify; a skipped or failed compaction never continues.",
    start: (ctx) => {
      // The factory is lazy on purpose: opening the branch session rebuilds workflow state, so
      // the gate-OFF arm must decide before it is ever called.
      const outcome = startDraftAndCompact(gating.isActive(), () =>
        openBranchWorkflowSession(pi, ctx),
      );
      switch (outcome.kind) {
        case "skip":
          return { kind: "skip", warning: START_WARNINGS[outcome.reason] };
        case "drive": {
          const subject = outcome.pending.subject;
          return {
            kind: "drive",
            notice: `driving a checkpoint of the working ${subject} draft…`,
            guidance: draftAndCompactGuidance(subject, outcome.current),
            pending: outcome.pending,
          };
        }
      }
      const exhaustive: never = outcome; // no default arm: union growth breaks the adapter here
      throw new Error(`unreachable start outcome: ${JSON.stringify(exhaustive)}`);
    },
    settle: (ctx, pending) => {
      const outcome = settleDraftAndCompact(pending, openBranchWorkflowSession(pi, ctx));
      switch (outcome.kind) {
        case "skip":
          return { kind: "skip", warning: SETTLE_WARNINGS[outcome.reason] };
        case "compact-now":
          return { kind: "compact-now", notice: "draft written", completion: outcome.completion };
      }
      const exhaustive: never = outcome; // no default arm: union growth breaks the adapter here
      throw new Error(`unreachable settle outcome: ${JSON.stringify(exhaustive)}`);
    },
    // Inline on purpose: compaction `customInstructions` stay inline; only injected user-message
    // prose goes to `prompts/`.
    instructions: (_ctx, completion) =>
      `The working ${completion.subject} draft was just written to the session's draft artifact ` +
      "and is the authoritative record of the authoring state, including its `## Unresolved` " +
      "section; perk re-delivers the draft in full after compaction. Preserve in the summary: " +
      "the authoring goal, the decisions taken and why, the evidence gathered that the draft " +
      "does not itself carry (file paths, symbols, observed behavior), and every unresolved " +
      "item. Prefer intent, evidence pointers, and next steps over restating the draft.",
    continuation: (_ctx, completion) =>
      draftAndCompactContinuation(completion.subject, completion.content),
  });
}
