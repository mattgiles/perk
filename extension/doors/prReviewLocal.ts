// The warm `/pr-review-local` command: open the plannotator browser code-review UI on the active
// worktree's PR, with the GitHub PR URL filled in IMPLICITLY (no copy-paste) — or, before
// `/submit` (plan worktree, no PR yet), a LOCAL since-base review of the working tree (merge-base
// vs the plan's pinned base → working tree, including uncommitted + untracked files). The PR mode
// is identical to plannotator's own `/plannotator-review <pr-url>`.
//
// pi exposes NO API for one extension to invoke another's slash command (`sendUserMessage` sends
// text to the model; `steer`/`followUp` ERROR on slash commands). So perk cannot literally call
// `/plannotator-review`. Instead it speaks plannotator's published `pi.events` API — a
// `plannotator:request` with `action: "code-review"` — which opens the EXACT same browser UI.
// Same in-process bus perk already uses for plan review (createPlannotatorBridge).
//
// A tiny read-only `perk pr url --json` cold door resolves the active PR's URL from the worktree's
// plan-ref branch (GitHub resolution stays canonical in Python). On its `no_pr` fail arm the door
// falls back to the local review, threading the plan-ref's pinned `base` as `defaultBranch` — the
// one input plannotator cannot infer (its own detection guesses the repo default, wrong for
// non-default-base plans). Any other fail arm (including `no_plan_ref`) still fails.
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.22.0`, `plannotator-events.ts` —
// byte-identical to 0.21.2, the original pin):
//   request — pi.events.emit("plannotator:request", { requestId, action: "code-review",
//             payload, respond })                   // respond = in-payload callback
//   payload — PR mode:    { prUrl, cwd }
//           — local mode: { cwd, diffType: "since-base", defaultBranch? }
//   reply   — respond({ status: "handled", result: { approved, feedback?, annotations?,
//             exit? } })
//           | respond({ status: "unavailable" | "error", error? })
// `result.annotations` items are plannotator `CodeAnnotation` objects — the content subset
// decoded here is `CodeReviewAnnotation` ({filePath, lineStart, lineEnd, side: "old"|"new"} +
// six optional string fields); `result.exit === true` is the "closed without feedback" arm
// (`/api/exit`). Both are consumed by the `/review` plannotator arm's respond routing —
// `/pr-review-local`'s own routing still keys on `annotationCount` alone (byte-stable).
// Unlike plan-review there is NO handshake / no `reviewId` channel and no timeout: for code-review
// plannotator `await openCodeReview(...)` then responds ONCE with the final result.
//
// `"since-base"` is new in plannotator 0.22.0; older versions don't own that diff type and fall
// back to the reviewer's configured default diff — graceful degradation, no version detection.
// The requested diffType only sets the INITIAL view (the reviewer can switch from the header menu).

import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import { readPlanRef } from "../substrate/cache.ts";
import {
  type ColdDoorResult,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { interceptConsoleError } from "../substrate/consoleCapture.ts";
import { failFor } from "../substrate/result.ts";
import { report } from "../surfaces/report.ts";

/** Plannotator's code-review slash command — its presence detects the extension is loaded. */
export const PLANNOTATOR_REVIEW_COMMAND = "plannotator-review";

/**
 * The diff type forced for the no-PR local fallback: merge-base vs the base branch → working
 * tree (plannotator ≥0.22.0; older versions fall back to their configured default diff). Forced —
 * not left to the reviewer's default — because a perk worktree pre-submit is mostly committed
 * work, so an `uncommitted` default would open a near-empty review.
 */
export const LOCAL_REVIEW_DIFF_TYPE = "since-base";

/**
 * The short, perk-authored triage suffix appended to feedback ONLY when the reviewer left
 * annotations — mirrors plannotator's own "address these notes" routing, but perk-worded.
 */
const TRIAGE_SUFFIX =
  "\n\nTriage these review notes first: decide which are actionable, then address the actionable ones.";

/**
 * One decoded plannotator annotation (the content subset of `CodeAnnotation` the `/review`
 * plannotator arm triages). Perk-pushed external annotations return with their `source` badge
 * set; human-authored ones carry no `source` — the dedupe discriminator.
 */
export interface CodeReviewAnnotation {
  filePath: string;
  lineStart: number;
  lineEnd: number;
  side: "old" | "new";
  text?: string;
  suggestedCode?: string;
  type?: string;
  scope?: string;
  source?: string;
  severity?: string;
}

/** The six pass-through-when-string optional `CodeReviewAnnotation` fields. */
const OPTIONAL_ANNOTATION_FIELDS = [
  "text",
  "suggestedCode",
  "type",
  "scope",
  "source",
  "severity",
] as const;

/**
 * Lenient per-item annotation decode (a triage/render-only consumer): an item is included iff
 * `filePath` is a string and `lineStart`/`lineEnd` are numbers; `side` is `"old"` only when
 * exactly `"old"`, else `"new"`; the optional fields carry through only when strings. Null =
 * skip the item (it still counts toward `annotationCount`).
 */
function decodeAnnotation(item: unknown): CodeReviewAnnotation | null {
  if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
  const raw = item as Record<string, unknown>;
  const filePath = raw.filePath;
  const lineStart = raw.lineStart;
  const lineEnd = raw.lineEnd;
  if (typeof filePath !== "string") return null;
  if (typeof lineStart !== "number" || typeof lineEnd !== "number") return null;
  const annotation: CodeReviewAnnotation = {
    filePath,
    lineStart,
    lineEnd,
    side: raw.side === "old" ? "old" : "new",
  };
  for (const field of OPTIONAL_ANNOTATION_FIELDS) {
    const value = raw[field];
    if (typeof value === "string") annotation[field] = value;
  }
  return annotation;
}

/** Decode the reply's raw `annotations` array; malformed items are skipped (never the batch). */
function decodeAnnotations(raw: unknown): CodeReviewAnnotation[] {
  if (!Array.isArray(raw)) return [];
  const out: CodeReviewAnnotation[] = [];
  for (const item of raw) {
    const decoded = decodeAnnotation(item);
    if (decoded !== null) out.push(decoded);
  }
  return out;
}

/** The outcome of a plannotator code-review request — a small local discriminated union. */
export type CodeReviewOutcome =
  | {
      status: "handled";
      approved: boolean;
      feedback: string | undefined;
      annotationCount: number;
      annotations: CodeReviewAnnotation[];
      exit: boolean;
    }
  | { status: "unavailable" | "error"; warning: string }
  | { status: "aborted" };

/**
 * Whether plannotator is loaded — detected by its `plannotator-review` command being registered
 * (independent of the selected plan provider; code review is orthogonal to plan-review selection).
 * `getCommands()` returns `SlashCommandInfo[]` whose `name` is the bare command name. The param
 * is the structural `getCommands` slice so tool cores with minimal pi slices can call it.
 */
export function plannotatorPresent(pi: Pick<ExtensionAPI, "getCommands">): boolean {
  return pi.getCommands().some((c) => c.name === PLANNOTATOR_REVIEW_COMMAND);
}

/** Plannotator's `respond(...)` reply for a code-review request (pinned envelope, see header). */
interface CodeReviewResponse {
  status?: string;
  error?: string;
  result?: { approved?: unknown; feedback?: unknown; annotations?: unknown; exit?: unknown };
}

/**
 * The pure, offline-testable bridge: emit ONE `plannotator:request` with `action: "code-review"`
 * and resolve when plannotator calls `respond(...)`. No handshake / no timeout (plannotator awaits
 * `openCodeReview(...)` then responds once). Honors a turn abort. Pure over the bus → unit-testable
 * with a fake plannotator listener.
 */
export async function requestPlannotatorCodeReview(
  bus: PlannotatorBus,
  opts: {
    cwd: string;
    prUrl?: string;
    diffType?: string;
    defaultBranch?: string;
    signal?: AbortSignal;
  },
): Promise<CodeReviewOutcome> {
  if (opts.signal?.aborted) return { status: "aborted" };

  // Build the payload conditionally — fields present ONLY when defined, so the PR-mode envelope
  // stays shape-identical to the original `{ prUrl, cwd }` and an omitted `defaultBranch` lets
  // plannotator auto-detect the repo default.
  const payload: Record<string, unknown> = { cwd: opts.cwd };
  if (opts.prUrl !== undefined) payload.prUrl = opts.prUrl;
  if (opts.diffType !== undefined) payload.diffType = opts.diffType;
  if (opts.defaultBranch !== undefined) payload.defaultBranch = opts.defaultBranch;

  return await new Promise<CodeReviewOutcome>((resolve) => {
    let settled = false;
    const finish = (outcome: CodeReviewOutcome): void => {
      if (settled) return;
      settled = true;
      opts.signal?.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onAbort = (): void => finish({ status: "aborted" });
    opts.signal?.addEventListener("abort", onAbort, { once: true });

    bus.emit("plannotator:request", {
      requestId: randomUUID(),
      action: "code-review",
      payload,
      respond: (raw: unknown) => {
        const response = raw as CodeReviewResponse;
        if (response?.status === "handled") {
          const result = response.result ?? {};
          const feedback =
            typeof result.feedback === "string" && result.feedback.trim()
              ? result.feedback
              : undefined;
          finish({
            status: "handled",
            approved: result.approved === true,
            feedback,
            annotationCount: Array.isArray(result.annotations) ? result.annotations.length : 0,
            annotations: decodeAnnotations(result.annotations),
            exit: result.exit === true,
          });
          return;
        }
        const status = response?.status === "error" ? "error" : "unavailable";
        const detail = response?.error ? `: ${response.error}` : "";
        finish({ status, warning: `plannotator reported ${response?.status ?? status}${detail}` });
      },
    });
  });
}

/** Where `/pr-review-local` points the review: the active PR, a local since-base review, or fail. */
export type ReviewTarget =
  | { mode: "pr"; prUrl: string; number: number }
  | { mode: "local"; defaultBranch: string | undefined }
  | { mode: "fail"; message: string; errorType: string };

/**
 * Resolve the review target from the `perk pr url` result (the pure, offline-testable core).
 * `no_pr` — a plan worktree whose branch has no PR yet — falls back to the local review with the
 * plan-ref's pinned base (null collapses to undefined: an omitted field means plannotator
 * auto-detects the repo default, matching perk's `base: None ⇒ repo default` semantics). Every
 * other fail arm (including `no_plan_ref`) passes through unchanged — the door stays plan-scoped;
 * arbitrary local review is plannotator's own `/plannotator-review` territory.
 */
export function resolveReviewTarget(
  r: ColdDoorResult<{ number: number; url: string }>,
  planRefBase: string | null | undefined,
): ReviewTarget {
  if (r.ok) return { mode: "pr", prUrl: r.data.url, number: r.data.number };
  if (r.errorType === "no_pr") return { mode: "local", defaultBranch: planRefBase ?? undefined };
  return { mode: "fail", message: r.message, errorType: r.errorType };
}

/** Read the plan-ref's pinned base, swallowing read/parse errors (the door must not throw). */
function planRefBaseOf(cwd: string): string | undefined {
  try {
    return readPlanRef(cwd)?.base ?? undefined;
  } catch {
    return undefined;
  }
}

/** Narrow the `perk pr url --json` success payload; strict on `pr.{number,url}`. */
function decodePrUrl(payload: ColdJson): { number: number; url: string } | null {
  const pr = objectField(payload, "pr");
  if (pr === undefined) return null;
  const number = numberField(pr, "number");
  const url = stringField(pr, "url");
  if (number === undefined || url === undefined) return null;
  return { number, url };
}

/** Route the code-review outcome back into the session — mirrors plannotator's own routing. */
function routePrReviewOutcome(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  out: CodeReviewOutcome,
): void {
  if (out.status === "unavailable" || out.status === "error") {
    report(ctx, "pr-review-local", "error", out.warning, { alsoLog: true });
    return;
  }
  if (out.status !== "handled") return; // aborted: the turn was interrupted — no-op

  if (out.feedback === undefined) {
    report(ctx, "pr-review-local", "info", "Code review approved — no changes requested.");
    return;
  }
  const message = out.feedback + (out.annotationCount > 0 ? TRIAGE_SUFFIX : "");
  // Inject the feedback as a real turn (the submit.ts driveConflictResolution pattern): an
  // immediate turn when idle, else delivered after the current streaming batch.
  if (ctx.isIdle()) {
    pi.sendUserMessage(message);
  } else {
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

/** Register the warm `/pr-review-local` command. */
export function registerPrReviewLocal(pi: ExtensionAPI): void {
  registerPerkCommand(pi, "pr-review-local", {
    description:
      "Open the plannotator browser code review on the active PR, or a local since-base review of the worktree before /submit.",
    handler: async (_args, ctx) => {
      if (!ctx.hasUI) {
        report(
          ctx,
          "pr-review-local",
          "info",
          "/pr-review-local requires an interactive session (the plannotator browser review needs UI).",
        );
        return;
      }
      if (!plannotatorPresent(pi)) {
        report(
          ctx,
          "pr-review-local",
          "info",
          "/pr-review-local requires the @plannotator/pi-extension package (its /plannotator-review command was not found).",
        );
        return;
      }

      const r = await runColdDoor<{ number: number; url: string }>(
        pi,
        ctx,
        ["pr", "url", "--json"],
        { label: "perk pr url", decode: decodePrUrl },
      );
      const target = resolveReviewTarget(r, planRefBaseOf(ctx.cwd));
      if (target.mode === "fail") {
        failFor(ctx, "pr-review-local")(target.message, target.errorType);
        return;
      }

      if (target.mode === "pr") {
        report(
          ctx,
          "pr-review-local",
          "info",
          `Opening plannotator code review for PR #${target.number} …`,
        );
      } else {
        report(
          ctx,
          "pr-review-local",
          "info",
          `No PR yet — opening plannotator local review (since-base vs ${target.defaultBranch ?? "repo default"}) …`,
        );
      }
      const requestOpts =
        target.mode === "pr"
          ? { prUrl: target.prUrl, cwd: ctx.cwd, signal: ctx.signal }
          : {
              cwd: ctx.cwd,
              diffType: LOCAL_REVIEW_DIFF_TYPE,
              defaultBranch: target.defaultBranch,
              signal: ctx.signal,
            };

      // Kick the long-running review in the BACKGROUND — do not block the session for the whole
      // review (plannotator responds once on completion). Mirrors plannotator's own `.then` route.
      // While setup runs, re-route plannotator's in-process `console.error` chatter through the
      // TUI-safe report() seam so it never clobbers the input box; the debounce restores once setup
      // goes quiet, with the `finally` as a backstop.
      void (async () => {
        const interceptor = interceptConsoleError(
          (line) => report(ctx, "pr-review-local", "info", line),
          // plannotator can pause up to ~4s between setup lines — keep the quiet window comfortably
          // above that so the debounce doesn't restore mid-setup and let the next line clobber.
          { quietMs: 6000 },
        );
        try {
          const out = await requestPlannotatorCodeReview(pi.events, requestOpts);
          routePrReviewOutcome(pi, ctx, out);
        } finally {
          interceptor.restore();
        }
      })();
    },
  });
}
