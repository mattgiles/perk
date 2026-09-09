// Dev-only fixtures for the draft-review guards (`pi/v1/draftReview.ts`): a scripted bridge that
// records the reviewed bytes and returns a canned outcome, a slot whose git-remotes read is
// scripted (the tool-arm suites fence destinations without a repo), and a seeded browser-review
// scaffold (a git repo with one `origin` remote — the destination fence needs a verifiable
// checkout — plus the subject's draft artifact written through the branch session) returning a
// fresh slot. Outside the production corpus, the guard scans, and the npm tarball (the
// `testing/` home).

import { execFileSync } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createDraftReviewSlot,
  type DraftReviewSlot,
  type DraftReviewSubject,
  type OpenDraftReview,
  REVIEW_SUBJECT_ARTIFACTS,
} from "../pi/v1/draftReview.ts";
import type { ReviewOutcome } from "../pi/v1/reviewOutcome.ts";
import { openBranchWorkflowSession } from "../session/branchWorkflowSession.ts";
import { captureSaveDestination } from "../session/saveDestination.ts";
import { resolveIssueRouting } from "../substrate/config.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import { gitInit } from "./harness.ts";

/** A recording bridge: captures every reviewed plan, returns the canned outcome. */
export function scriptedDraftReviewBridge(outcome: ReviewOutcome): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
  reviewed: string[];
} {
  const reviewed: string[] = [];
  return {
    reviewed,
    async review(plan: string) {
      reviewed.push(plan);
      return outcome;
    },
  };
}

/**
 * A bridge that models "another surface opened while the decision was outstanding": `review`
 * records the plan, opens a SECOND review on `slot` (superseding the caller's), stores the
 * returned review in `opened` (the slot has no current-review getter — tests read
 * `opened.isCurrent()` for the newer review's currency assertion), then returns `outcome`. A
 * slot refusal throws: the fixture must never silently leave the caller current.
 */
export function supersedingDraftReviewBridge(
  slot: DraftReviewSlot,
  ctx: ExtensionContext,
  subject: DraftReviewSubject,
  outcome: ReviewOutcome,
): {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
  reviewed: string[];
  opened: OpenDraftReview | null;
} {
  const reviewed: string[] = [];
  const bridge = {
    reviewed,
    opened: null as OpenDraftReview | null,
    async review(plan: string) {
      reviewed.push(plan);
      const newer = slot.open(ctx, {
        subject,
        source: "artifact",
        raw: "# a newer review\n",
        markdown: "# a newer review\n",
      });
      if (!newer.ok)
        throw new Error(
          `supersedingDraftReviewBridge: the superseding open refused (${newer.detail})`,
        );
      bridge.opened = newer.review;
      return outcome;
    },
  };
  return bridge;
}

/** The scripted `git config remote.*` read a fresh `scriptedRemotesSlot` starts from. */
export const SCRIPTED_ORIGIN = "remote.origin.url\nhttps://github.com/acme/widgets.git";

/**
 * A slot over a scripted git-remotes reader (no repo needed): the real committed `[issues]` and
 * node-claim capture, with `remotes.current` standing in for the checkout's `remote.*` entries.
 * Flip it mid-review to simulate `git remote set-url`; set it to `null` for an unverifiable
 * checkout.
 */
export function scriptedRemotesSlot(
  pi: ExtensionAPI,
  remotes: { current: string | null } = { current: SCRIPTED_ORIGIN },
): DraftReviewSlot {
  return createDraftReviewSlot(pi, {
    session: openBranchWorkflowSession,
    destination: (cwd, nodeClaim) =>
      captureSaveDestination(cwd, nodeClaim, {
        issues: resolveIssueRouting,
        remotes: () => remotes.current,
      }),
  });
}

/**
 * Seed a browser-reviewable session: git-init `ctx.cwd` (with an `origin` remote so the GitHub
 * destination arm captures), write `raw` as the subject's draft artifact through the branch
 * session, and return a fresh slot bound to `pi`.
 */
export function seedBrowserReview(
  pi: ExtensionAPI & EntrySink,
  ctx: SessionArtifactCtx,
  subject: DraftReviewSubject,
  raw: string,
): DraftReviewSlot {
  gitInit(ctx.cwd, { dirty: false });
  execFileSync("git", ["remote", "add", "origin", "https://github.com/acme/widgets.git"], {
    cwd: ctx.cwd,
    stdio: "ignore",
  });
  const written = openBranchWorkflowSession(pi, ctx).writeArtifact(
    REVIEW_SUBJECT_ARTIFACTS[subject],
    raw,
  );
  if (written.status !== "applied" && written.status !== "unchanged")
    throw new Error(`seedBrowserReview: draft write ${written.status}`);
  return createDraftReviewSlot(pi);
}
