// The fixed automated review flow (contracts §8.4) — the typed feature operations behind the
// warm `/pr-review` door's `run_pr_review_wave` + `post_pr_review` tools. This module owns the
// POLICY: the per-activation review-pass state machine (`null` permits the backwards-compatible
// standalone post; a valid new pass moves to `pending` BEFORE target resolution; a normalized
// outcome records `{pr, complete, attempted, covered}` PR-bound and single-use; one successful
// post consumes it; incomplete coverage refuses a clean verdict; a mutation-time PR mismatch
// demotes back to `pending`), plus the `last_pr_review` record a real post applies through the
// session seam (classification ignored — the seam owns loudness).
//
// Pi-free by construction (importDirectionGuard Rule D): the Pi adapter
// (`pi/v1/codeReview/automated.ts`) owns registration, tool-boundary decode, the cold-door and
// RPC-wave compositions, and Result rendering; this module sees only the ports below. The wave
// vocabulary arrives type-only from `waves/prReviewWave.ts` (a legal feature→mechanism type
// edge) — `ChangeReviewOutcome` is an alias of `PrReviewWaveOutcome`, never a second
// hand-mirrored vocabulary.

import type { PrReviewRecord, WorkflowSession } from "../session/workflowSession.ts";
import type { PrReviewAngle, PrReviewWaveOutcome } from "../waves/prReviewWave.ts";

// ------------------------------------------------------------------------ ports

/** The resolved active-plan PR every lane in a pass reviews. */
export interface ReviewTarget {
  number: number;
  url: string;
}

/** The target-resolution role (production: the `perk pr url --json` cold-door composition). */
export interface ReviewTargetResolver {
  resolve(): Promise<
    { ok: true; target: ReviewTarget } | { ok: false; message: string; errorType: string }
  >;
}

/**
 * The external reviewer's request. Cancellation ownership is explicit: the tool's
 * execute-callback signal rides the request; the production adapter forwards it into
 * `runPrReviewWave`'s `opts.signal` (cancellation normalizes into the outcome, never a throw).
 */
export interface ChangeReviewRequest {
  pr: number;
  angles: readonly PrReviewAngle[];
  directive?: string;
  signal?: AbortSignal;
}

/** A type-only alias of the wave outcome — never a second hand-mirrored vocabulary. */
export type ChangeReviewOutcome = PrReviewWaveOutcome;

/** The external reviewer role (production: RPC adapter + `runPrReviewWave` + configured model). */
export interface ChangeReviewer {
  review(request: ChangeReviewRequest): Promise<ChangeReviewOutcome>;
}

/** One reconciled inline finding (the exact `review-post --batch` `comments[]` row). */
export interface ReviewComment {
  path: string;
  line: number;
  body: string;
}

/** The publishing port's input (`expected_pr` threading stays feature policy). */
export interface AutomatedReviewBatch {
  verdict: "clean" | "actionable";
  summary: string;
  comments?: ReviewComment[];
  fyi?: string[];
  expectedPr?: number;
}

/** The cold door's ok-arm fields (the `review-post --json` surface). */
export interface PostOk {
  pr: number;
  mode?: string;
  verdict?: string;
  comment_count?: number;
  next_command?: string;
}

/**
 * The publishing outcome — `errorType` required (the cold-door seam always supplies it; the op
 * branches on the `"review_target_changed"` literal).
 */
export type PublishOutcome =
  | { ok: true; data: PostOk }
  | { ok: false; message: string; errorType: string };

/** The publishing role (production: the `perk pr review-post --json --batch` composition). */
export interface ReviewPublisher {
  publish(batch: AutomatedReviewBatch): Promise<PublishOutcome>;
}

// ------------------------------------------------------------------------ the pass state

/**
 * The review-pass post state: `null` preserves standalone posting before any valid wave attempt;
 * a decoded new pass invalidates old evidence immediately (`pending`); only one `recorded`
 * outcome can post, after which `consumed` refuses duplicates until another valid pass starts.
 */
export type ReviewPassState =
  | null
  | { state: "pending" }
  | {
      state: "recorded";
      pr: number;
      complete: boolean;
      attempted: readonly string[];
      covered: readonly string[];
    }
  | { state: "consumed" };

/**
 * A plain per-activation holder (the installer creates one per activation; the two feature ops
 * own every transition — no module-level state, ever).
 */
export interface ReviewPassHolder {
  current: ReviewPassState;
}

// ------------------------------------------------------------------------ run the wave

/** The decoded wave selection (strict decoding stays at the adapter boundary). */
export interface ReviewSelection {
  angles: readonly PrReviewAngle[];
  directive?: string;
  signal?: AbortSignal;
}

export type RunAutomatedReviewOutcome =
  | { kind: "no_target"; message: string; errorType: string }
  | {
      kind: "reviewed";
      pr: number;
      outcome: ChangeReviewOutcome;
      attempted: readonly string[];
      /** Non-null ⟺ the wave is incomplete — the adapter renders the loud degrade from it. */
      incompleteWarning: { uncovered: string[]; reasons: string } | null;
    };

/**
 * Run one automated review pass: invalidate old evidence (`pending`) → resolve the target
 * (failure leaves the state pending) → run the reviewer → record the PR-bound manifest with
 * `attempted = [...angles, "ponytail"]`. Recording COPIES the arrays — the holder owns its
 * evidence, never aliasing the outcome returned to the adapter.
 */
export async function runAutomatedReview(
  selection: ReviewSelection,
  deps: { resolver: ReviewTargetResolver; reviewer: ChangeReviewer; state: ReviewPassHolder },
): Promise<RunAutomatedReviewOutcome> {
  deps.state.current = { state: "pending" };
  const resolved = await deps.resolver.resolve();
  if (!resolved.ok) {
    return { kind: "no_target", message: resolved.message, errorType: resolved.errorType };
  }
  const pr = resolved.target.number;
  // Cancellation normalizes into the outcome (`cancelled`, no retry) — never a throw.
  const outcome = await deps.reviewer.review({
    pr,
    angles: selection.angles,
    ...(selection.directive !== undefined ? { directive: selection.directive } : {}),
    ...(selection.signal !== undefined ? { signal: selection.signal } : {}),
  });
  const attempted = [...selection.angles, "ponytail"];
  deps.state.current = {
    state: "recorded",
    pr,
    complete: outcome.complete,
    attempted: [...attempted],
    covered: [...outcome.covered],
  };
  // Loud degrade — the `unavailable` arm surfaces here too, never a silent fallback.
  const incompleteWarning = outcome.complete
    ? null
    : {
        uncovered: attempted.filter((angle) => !outcome.covered.includes(angle)),
        reasons: outcome.failures
          .map((f) => `${f.key ?? "wave"}: ${f.reason} — ${f.detail}`)
          .join("; "),
      };
  return { kind: "reviewed", pr, outcome, attempted, incompleteWarning };
}

// ------------------------------------------------------------------------ publish the outcome

/** The decoded post params (strict decoding stays at the adapter boundary). */
export interface AutomatedPost {
  verdict: "clean" | "actionable";
  summary: string;
  comments?: ReviewComment[];
  fyi?: string[];
  /** Standalone fallback only; recorded-wave calls use the authoritative attempted manifest. */
  angles?: string[];
}

export type PublishAutomatedReviewOutcome =
  | {
      kind: "ineligible";
      errorType: "review_wave_unavailable" | "review_wave_consumed" | "incomplete_coverage";
      message: string;
    }
  | { kind: "stale"; errorType: "stale_review_wave"; message: string }
  | { kind: "publish_failed"; message: string; errorType: string }
  | { kind: "posted"; data: PostOk; record: PrReviewRecord };

/**
 * Publish the reconciled outcome to the PR: the eligibility ladder (pending ⇒
 * `review_wave_unavailable`; consumed ⇒ `review_wave_consumed`; a clean verdict over an
 * incomplete recorded wave ⇒ `incomplete_coverage` — state untouched on all three) → the
 * publisher (a `review_target_changed` failure while a recorded state exists demotes to
 * `pending`; any other failure passes through verbatim, state untouched) → on success apply
 * `record-pr-review` (classification ignored — the seam owns loudness) and consume iff
 * recorded. The standalone-post arm (a `null` state) is preserved: caller-supplied angles fill
 * both manifests.
 */
export async function publishAutomatedReview(
  post: AutomatedPost,
  deps: { publisher: ReviewPublisher; state: ReviewPassHolder; session: WorkflowSession },
): Promise<PublishAutomatedReviewOutcome> {
  const current = deps.state.current;
  if (current?.state === "pending") {
    return {
      kind: "ineligible",
      errorType: "review_wave_unavailable",
      message: "the latest review pass has no recorded outcome; rerun /pr-review before posting",
    };
  }
  if (current?.state === "consumed") {
    return {
      kind: "ineligible",
      errorType: "review_wave_consumed",
      message:
        "the recorded review outcome has already been posted; rerun /pr-review before posting again",
    };
  }
  // Incomplete coverage is never a clean review. An actionable post may still record the
  // findings plus the coverage caveat, consuming that recorded outcome on success.
  if (post.verdict === "clean" && current?.state === "recorded" && !current.complete) {
    return {
      kind: "ineligible",
      errorType: "incomplete_coverage",
      message:
        "incomplete coverage is never a clean review — the recorded review wave left angle(s) " +
        "uncovered; post the actionable findings with a coverage note, or post nothing and " +
        "suggest re-running /pr-review",
    };
  }

  // A recorded wave binds the Python mutation to the PR that every child reviewed. Standalone
  // calls intentionally omit `expected_pr` for backwards-compatible direct posting.
  const recorded = current?.state === "recorded" ? current : null;
  const batch: AutomatedReviewBatch = { verdict: post.verdict, summary: post.summary };
  if (post.comments !== undefined) batch.comments = post.comments;
  if (post.fyi !== undefined) batch.fyi = post.fyi;
  if (recorded !== null) batch.expectedPr = recorded.pr;

  const published = await deps.publisher.publish(batch);
  if (!published.ok) {
    if (recorded !== null && published.errorType === "review_target_changed") {
      deps.state.current = { state: "pending" };
      return {
        kind: "stale",
        errorType: "stale_review_wave",
        message:
          "the active PR changed after this review wave; the recorded reports are stale — rerun " +
          "/pr-review before posting",
      };
    }
    return { kind: "publish_failed", message: published.message, errorType: published.errorType };
  }

  const data = published.data;
  // Record the outcome (best-effort tier, seam-reported): the classification is ignored — the
  // post already succeeded and the seam owns the loud read-back warning.
  const standaloneAngles = post.angles ?? [];
  const attempted = recorded?.attempted ?? standaloneAngles;
  const covered = recorded?.covered ?? standaloneAngles;
  const record: PrReviewRecord = {
    pr: data.pr,
    verdict: post.verdict,
    angles: [...attempted],
    covered_angles: [...covered],
    comment_count: data.comment_count ?? null,
    mode: data.mode ?? null,
    at: new Date().toISOString(),
  };
  deps.session.apply({ kind: "record-pr-review", record });
  if (recorded !== null) deps.state.current = { state: "consumed" };
  return { kind: "posted", data, record };
}
