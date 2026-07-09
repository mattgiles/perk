// The warm `open_plannotator_review` tool — the `/review` plannotator arm's one deterministic
// browser-open gesture. The tool does ONLY what must live in TS: composing the shared
// browser-open core (`startPlannotatorBrowser` in plannotatorHandoff.ts — server addressing via
// the preset `PLANNOTATOR_PORT` mechanism + the `code-review` bridge emit + the readiness poll)
// and routing the single respond back into the triage loop. Everything else on this arm is
// agent-driven HTTP against plannotator's own documented external-annotations contract
// (per-angle waves over `POST <url>/api/external-annotations` — the perk-review skill owns the
// perk-adapted subset; `GET /api/diff` is forbidden to the agent: the raw diff never enters the
// parent session).
//
// The plannotator-arm posting contract (contracts §8.4) is the FLIPPED one: findings are
// streamed only into the local plannotator session; the human's native platform-posting from
// the UI is THE GitHub path; perk composes nothing by default — `submit_pr_review` (gates
// unchanged) is used only for a request-changes verdict or on the human's explicit request.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import { interceptConsoleError } from "../substrate/consoleCapture.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import { numberParam, paramsOf, stringParam } from "../substrate/toolParams.ts";
import { report, type Severity } from "../surfaces/report.ts";
import {
  plannotatorPresent,
  READINESS_PROBE_BUDGET_MS,
  routeBrowserRespond,
  type StartBrowserDeps,
  type StartedBrowser,
  startPlannotatorBrowser,
} from "./plannotatorHandoff.ts";

// ------------------------------------------------------------------------ params

/** The strict-decoded `open_plannotator_review` params (threaded from the injected guidance). */
export interface OpenReviewParams {
  pr: number;
  pr_url: string;
}

/**
 * Strict-decode unknown tool-call params: `pr` an int, `pr_url` a non-empty string — both
 * non-guessable strings from the door's checkout envelope. ANY malformed field ⇒ null
 * (`bad_input`, nothing executed).
 */
export function decodeOpenReviewParams(params: unknown): OpenReviewParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const pr = numberParam(p, "pr");
  if (typeof pr !== "number" || !Number.isInteger(pr)) return null;
  const prUrl = stringParam(p, "pr_url");
  if (typeof prUrl !== "string" || prUrl.length === 0) return null;
  return { pr, pr_url: prUrl };
}

// ------------------------------------------------------------------------ the tool core

/**
 * The minimal `pi` slice the tool core needs — `ExtensionAPI` satisfies it (compile-checked in
 * the test); tests fake it with a recording bus + message sink.
 */
export interface OpenReviewPi extends Pick<ExtensionAPI, "getCommands"> {
  events: PlannotatorBus;
  sendUserMessage(content: string, options?: { deliverAs?: "steer" | "followUp" }): void;
}

/** The minimal ctx slice — `ExtensionContext` satisfies it (compile-checked in the test). */
export interface OpenReviewCtx {
  cwd: string;
  hasUI: boolean;
  signal: AbortSignal | undefined;
  isIdle(): boolean;
  ui: { notify(message: string, type?: Severity): void };
}

/** The injectable seams (tests drive a fake port picker / probe / clock). */
export type OpenReviewDeps = StartBrowserDeps;

/**
 * Open the plannotator browser code review on the PR (the `/review` plannotator arm's one warm
 * tool). Gate ladder — each a soft fail, nothing executed: `plannotator_missing` (the
 * `plannotator-review` command probe) → `headless` (the browser surface and the human are
 * constitutive). Then the shared browser-open core: pick a free port, preset `PLANNOTATOR_PORT`,
 * emit the bridge request (background-awaited — the single respond routes back into the session
 * as a message), and await the readiness poll (which stops early when the turn aborts or the
 * bridge settles first — an early error/unavailable respond means the server never comes; the
 * prior env value is always restored). On readiness: `ok` with the local server url + port.
 */
export async function openPlannotatorReview(
  pi: OpenReviewPi,
  ctx: OpenReviewCtx,
  params: OpenReviewParams,
  deps: OpenReviewDeps = {},
): Promise<Result<{ url: string; port: number }>> {
  const fail = failFor(ctx, "review", "open_plannotator_review");
  if (!plannotatorPresent(pi)) {
    return fail(
      "the plannotator extension is not loaded (its /plannotator-review command was not " +
        "found) — the plannotator-review selection converges npm:@plannotator/pi-extension: " +
        "run `perk init`, then restart pi",
      "plannotator_missing",
    );
  }
  if (!ctx.hasUI) {
    return fail(
      "open_plannotator_review requires an interactive session — the plannotator browser " +
        "review and the human triage are constitutive",
      "headless",
    );
  }

  let started: StartedBrowser;
  try {
    started = await startPlannotatorBrowser(
      pi.events,
      { prUrl: params.pr_url, cwd: ctx.cwd, signal: ctx.signal },
      deps,
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`could not pick a free local port: ${detail}`, "server_not_ready");
  }

  // Background-await the respond — the tool returns once the server is ready; the human's
  // single respond arrives later as an injected message. While setup runs, re-route
  // plannotator's in-process `console.error` chatter through report().
  void (async () => {
    const interceptor = interceptConsoleError((line) => report(ctx, "review", "info", line), {
      // plannotator can pause up to ~4s between setup lines — keep the quiet window above that.
      quietMs: 6000,
    });
    try {
      const out = await started.bridgePromise;
      routeBrowserRespond(pi, ctx, out, "review");
    } finally {
      interceptor.restore();
    }
  })();

  const readiness = await started.readiness;
  if (readiness !== "ready") {
    const budgetMs = deps.budgetMs ?? READINESS_PROBE_BUDGET_MS;
    return fail(
      `the plannotator review server did not become ready at ${started.url} within ` +
        `${Math.round(budgetMs / 1000)}s — degrade in-session: render the reconciled findings ` +
        "as a table in your reply and run the same triage loop conversationally; posting is " +
        "unchanged (submit_pr_review)",
      "server_not_ready",
    );
  }

  return ok(
    `plannotator code review opened on PR #${params.pr} — the browser is up at ${started.url}. ` +
      `Stream findings as per-angle waves to ${started.url}/api/external-annotations per the ` +
      "perk-review skill's cheat sheet (never GET /api/diff). The human's submission will " +
      "arrive in this session as a message — their native platform-posting from the UI is " +
      "the GitHub path; perk composes nothing by default.",
    { url: started.url, port: started.port },
  );
}

const TOOL_GUIDELINES = [
  "Call open_plannotator_review only on the /review plannotator arm (the injected guidance names it) — never on the hunk arm.",
  "Call it ONCE, right after spawning the adversarial reviewers — the browser opens on the PR while they work.",
  "The tool returns the local annotation endpoint; stream each angle's findings as one atomic POST wave per the perk-review skill's cheat sheet. Never GET /api/diff.",
  "The human's submission arrives later as a message in this session (one-shot: any browser ending resolves it).",
  "The human platform-posts to GitHub from the browser UI — that is the GitHub path. Perk composes nothing by default; submit_pr_review only for a request-changes verdict or on the human's explicit request — the browser stream itself is a local UI surface, never a GitHub mutation.",
];

// ------------------------------------------------------------------------ registration

/** Register the `open_plannotator_review` tool (called from `registerReview` — one entry). */
export function registerReviewPlannotator(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "open_plannotator_review",
    label: "Open plannotator review",
    description:
      "Open the plannotator browser code-review UI on the foreign PR (the /review plannotator " +
      "arm). Returns the local server URL — findings then stream agent-driven to " +
      "<url>/api/external-annotations; the human's submission routes back into this session " +
      "as a message.",
    promptSnippet: "Open the plannotator browser review on the PR",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["pr", "pr_url"],
      properties: {
        pr: { type: "number", description: "The foreign PR number being reviewed." },
        pr_url: {
          type: "string",
          description: "The PR's GitHub URL (from the /review guidance — never guessed).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeOpenReviewParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "review",
          "open_plannotator_review",
        )("open_plannotator_review needs { pr: int, pr_url: non-empty string }", "bad_input");
      }
      return openPlannotatorReview(pi, ctx, decoded);
    },
  });
}
