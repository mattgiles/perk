// The warm `/pr-review-local` command: open the plannotator browser code-review UI on the active
// worktree's PR, with the GitHub PR URL filled in IMPLICITLY (no copy-paste). The end result is
// identical to plannotator's own `/plannotator-review <pr-url>`.
//
// pi exposes NO API for one extension to invoke another's slash command (`sendUserMessage` sends
// text to the model; `steer`/`followUp` ERROR on slash commands). So perk cannot literally call
// `/plannotator-review`. Instead it speaks plannotator's published `pi.events` API — a
// `plannotator:request` with `action: "code-review"` and a `prUrl` payload — which opens the EXACT
// same browser UI. Same in-process bus perk already uses for plan review (createPlannotatorBridge).
//
// A tiny read-only `perk pr url --json` cold door resolves the active PR's URL from the worktree's
// plan-ref branch (GitHub resolution stays canonical in Python).
//
// EVENT ENVELOPE (pinned against `@plannotator/pi-extension@0.21.2`, `plannotator-events.ts`):
//   request — pi.events.emit("plannotator:request", { requestId, action: "code-review",
//             payload: { prUrl, cwd }, respond })   // respond = in-payload callback
//   reply   — respond({ status: "handled", result: { approved, feedback?, annotations? } })
//           | respond({ status: "unavailable" | "error", error? })
// Unlike plan-review there is NO handshake / no `reviewId` channel and no timeout: for code-review
// plannotator `await openCodeReview(...)` then responds ONCE with the final result.

import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import {
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { interceptConsoleError } from "../substrate/consoleCapture.ts";
import { failFor } from "../substrate/result.ts";
import { report } from "../surfaces/report.ts";

/** Plannotator's code-review slash command — its presence detects the extension is loaded. */
export const PLANNOTATOR_REVIEW_COMMAND = "plannotator-review";

/**
 * The short, perk-authored triage suffix appended to feedback ONLY when the reviewer left
 * annotations — mirrors plannotator's own "address these notes" routing, but perk-worded.
 */
const TRIAGE_SUFFIX =
  "\n\nTriage these review notes first: decide which are actionable, then address the actionable ones.";

/** The outcome of a plannotator code-review request — a small local discriminated union. */
export type CodeReviewOutcome =
  | {
      status: "handled";
      approved: boolean;
      feedback: string | undefined;
      annotationCount: number;
    }
  | { status: "unavailable" | "error"; warning: string }
  | { status: "aborted" };

/**
 * Whether plannotator is loaded — detected by its `plannotator-review` command being registered
 * (independent of the selected plan provider; code review is orthogonal to plan-review selection).
 * `getCommands()` returns `SlashCommandInfo[]` whose `name` is the bare command name.
 */
export function plannotatorPresent(pi: ExtensionAPI): boolean {
  return pi.getCommands().some((c) => c.name === PLANNOTATOR_REVIEW_COMMAND);
}

/** Plannotator's `respond(...)` reply for a code-review request (pinned envelope, see header). */
interface CodeReviewResponse {
  status?: string;
  error?: string;
  result?: { approved?: unknown; feedback?: unknown; annotations?: unknown };
}

/**
 * The pure, offline-testable bridge: emit ONE `plannotator:request` with `action: "code-review"`
 * and resolve when plannotator calls `respond(...)`. No handshake / no timeout (plannotator awaits
 * `openCodeReview(...)` then responds once). Honors a turn abort. Pure over the bus → unit-testable
 * with a fake plannotator listener.
 */
export async function requestPlannotatorCodeReview(
  bus: PlannotatorBus,
  opts: { prUrl: string; cwd: string; signal?: AbortSignal },
): Promise<CodeReviewOutcome> {
  if (opts.signal?.aborted) return { status: "aborted" };

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
      payload: { prUrl: opts.prUrl, cwd: opts.cwd },
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
  pi.registerCommand("pr-review-local", {
    description:
      "Open the plannotator browser code review on the active PR (URL filled in automatically).",
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
      if (!r.ok) {
        failFor(ctx, "pr-review-local")(r.message, r.errorType);
        return;
      }

      report(
        ctx,
        "pr-review-local",
        "info",
        `Opening plannotator code review for PR #${r.data.number} …`,
      );

      // Kick the long-running review in the BACKGROUND — do not block the session for the whole
      // review (plannotator responds once on completion). Mirrors plannotator's own `.then` route.
      // While setup runs, re-route plannotator's in-process `console.error` chatter through the
      // TUI-safe report() seam so it never clobbers the input box; the debounce restores once setup
      // goes quiet, with the `finally` as a backstop.
      void (async () => {
        const interceptor = interceptConsoleError(
          (line) => report(ctx, "pr-review-local", "info", line),
          { quietMs: 1500 },
        );
        try {
          const out = await requestPlannotatorCodeReview(pi.events, {
            prUrl: r.data.url,
            cwd: ctx.cwd,
            signal: ctx.signal,
          });
          routePrReviewOutcome(pi, ctx, out);
        } finally {
          interceptor.restore();
        }
      })();
    },
  });
}
