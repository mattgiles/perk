// The warm `open_plannotator_review` tool — the `/review` plannotator arm's one deterministic
// browser-open gesture. The tool does ONLY what must live in TS: server addressing (the preset
// `PLANNOTATOR_PORT` mechanism), the `code-review` bridge emit, and routing the single respond
// back into the triage loop. Everything else on this arm is agent-driven HTTP against
// plannotator's own documented external-annotations contract (per-angle waves over
// `POST <url>/api/external-annotations` — the perk-review skill owns the perk-adapted subset;
// `GET /api/diff` is forbidden to the agent: the raw diff never enters the parent session).
//
// SERVER ADDRESSING (why the env preset works): the pi extension runs plannotator's review
// server IN-PROCESS (`node:http`, not the standalone Bun binary), and its port resolution
// (`server/network.ts getServerPort()`) reads `PLANNOTATOR_PORT` at bind time — perk's extension
// and plannotator's server share one Node process, so an env var set here is read there. The
// tool picks a free ephemeral port, presets the env var, emits the bridge request, polls
// `GET /api/diff` (a review-server-only route) for readiness, and ALWAYS restores the prior env
// value in a `finally` around the poll. Concurrency caveat: a second plannotator server starting
// in the same process during the window would collide on the fixed port — rare and loud
// (EADDRINUSE → plannotator throws → the bridge settles error), never silent.
//
// The plannotator-arm posting contract (contracts §8.4) is unchanged by this tool: findings are
// streamed only into the local plannotator session; all perk-side GitHub posting stays with
// `submit_pr_review`; the human platform-posting from the UI is their own action, read back and
// deduped before perk posts the remainder.

import { createServer } from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import { interceptConsoleError } from "../substrate/consoleCapture.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import { numberParam, paramsOf, stringParam } from "../substrate/toolParams.ts";
import { report, type Severity } from "../surfaces/report.ts";
import {
  type CodeReviewOutcome,
  plannotatorPresent,
  requestPlannotatorCodeReview,
} from "./prReviewLocal.ts";

/** The readiness-probe cadence: one `GET /api/diff` per second. */
export const READINESS_PROBE_INTERVAL_MS = 1_000;

/**
 * The readiness budget — generous because plannotator's setup does real work before the server
 * binds (the PR fetch + its own optional local checkout can be slow).
 */
export const READINESS_PROBE_BUDGET_MS = 120_000;

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

// ------------------------------------------------------------------------ server addressing

/** Pick a free ephemeral port: `node:net` listen(0) → read → close (injectable for tests). */
export async function pickFreePort(): Promise<number> {
  return await new Promise<number>((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address !== null ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

/** The default readiness probe: `GET <url>/api/diff` — a review-server-only route. */
async function probeReviewServer(url: string, signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${url}/api/diff`, { signal });
    return response.ok;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------------ respond routing

/**
 * The pure respond → injection mapping (offline-testable). Null = nothing to inject (the
 * non-handled arms route elsewhere: unavailable/error → report(); aborted → no-op).
 */
export function respondMessage(outcome: CodeReviewOutcome): string | null {
  if (outcome.status !== "handled") return null;
  if (outcome.exit) {
    return (
      "The human closed the plannotator review without submitting — ask them how they want " +
      "to proceed."
    );
  }
  if (outcome.approved && outcome.annotations.length === 0) {
    return (
      "The human approved the code review in plannotator (no annotations). Settle the final " +
      "verdict with them — and ALWAYS read back what already landed on the PR before any " +
      "perk-side post."
    );
  }
  const parts: string[] = [outcome.feedback ?? "The plannotator review returned."];
  if (outcome.annotations.length > 0) {
    parts.push(`\`\`\`json\n${JSON.stringify(outcome.annotations, null, 2)}\n\`\`\``);
    parts.push(
      "These annotations are candidate comments: source-less ones are human-authored " +
        "(default keep); `perk:*`-badged ones are your own findings returning — reconcile, " +
        "don't duplicate. Read back what already landed on the PR and dedupe per the " +
        "perk-review skill before composing the remainder.",
    );
  }
  return parts.join("\n\n");
}

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

/** Route the settled respond into the session (the idle-vs-streaming injection route). */
function routeReviewRespond(pi: OpenReviewPi, ctx: OpenReviewCtx, out: CodeReviewOutcome): void {
  if (out.status === "unavailable" || out.status === "error") {
    // Degrade-mid-flow: the flow continues in-session (findings table; posting unchanged).
    report(ctx, "review", "error", out.warning, { alsoLog: true });
    return;
  }
  const message = respondMessage(out);
  if (message === null) return; // aborted: the turn was interrupted — no-op
  if (ctx.isIdle()) {
    pi.sendUserMessage(message);
  } else {
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

// ------------------------------------------------------------------------ the tool core

/** The injectable seams (tests drive a fake port picker / probe / clock). */
export interface OpenReviewDeps {
  pickFreePort?: () => Promise<number>;
  probe?: (url: string, signal?: AbortSignal) => Promise<boolean>;
  intervalMs?: number;
  budgetMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

/**
 * Open the plannotator browser code review on the PR (the `/review` plannotator arm's one warm
 * tool). Gate ladder — each a soft fail, nothing executed: `plannotator_missing` (the
 * `plannotator-review` command probe) → `headless` (the browser surface and the human are
 * constitutive). Then the port dance: pick a free port, preset `PLANNOTATOR_PORT`, emit the
 * bridge request (background-awaited — the single respond routes back into the session as a
 * message), poll `GET /api/diff` until ready (the poll stops early when the turn aborts or the
 * bridge settles first — an early error/unavailable respond means the server never comes), and
 * ALWAYS restore the prior env value. On readiness: `ok` with the local server url + port.
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

  const pickPort = deps.pickFreePort ?? pickFreePort;
  const probe = deps.probe ?? probeReviewServer;
  const intervalMs = deps.intervalMs ?? READINESS_PROBE_INTERVAL_MS;
  const budgetMs = deps.budgetMs ?? READINESS_PROBE_BUDGET_MS;
  const sleep =
    deps.sleep ?? ((ms: number) => new Promise<void>((r) => globalThis.setTimeout(r, ms)));

  let port: number;
  try {
    port = await pickPort();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`could not pick a free local port: ${detail}`, "server_not_ready");
  }
  const url = `http://127.0.0.1:${port}`;

  const priorPort = process.env.PLANNOTATOR_PORT;
  process.env.PLANNOTATOR_PORT = String(port);

  // Emit the bridge request while PLANNOTATOR_PORT is preset — plannotator's `listenOnPort`
  // reads it at bind time. The payload mirrors `/pr-review-local`'s PR mode byte-for-byte
  // (plannotator's defaults, including its own local checkout for Ask AI / Full-stack —
  // deliberately NOT `useLocal: false`; the human chose the full surface).
  let bridgeSettled = false;
  const bridgePromise = requestPlannotatorCodeReview(pi.events, {
    prUrl: params.pr_url,
    cwd: ctx.cwd,
    signal: ctx.signal,
  });
  void bridgePromise.then(() => {
    bridgeSettled = true;
  });

  // Background-await the respond (the `/pr-review-local` pattern) — the tool returns once the
  // server is ready; the human's single respond arrives later as an injected message. While
  // setup runs, re-route plannotator's in-process `console.error` chatter through report().
  void (async () => {
    const interceptor = interceptConsoleError((line) => report(ctx, "review", "info", line), {
      // plannotator can pause up to ~4s between setup lines — keep the quiet window above that.
      quietMs: 6000,
    });
    try {
      const out = await bridgePromise;
      routeReviewRespond(pi, ctx, out);
    } finally {
      interceptor.restore();
    }
  })();

  // The readiness poll — attempt-counted (budget/interval), so injected test clocks stay
  // deterministic. Env restore is unconditional: after the window the fixed port is released
  // back to plannotator's own resolution (random port) for any later server.
  let ready = false;
  try {
    const attempts = Math.max(1, Math.floor(budgetMs / intervalMs));
    for (let i = 0; i < attempts; i++) {
      if (bridgeSettled || ctx.signal?.aborted === true) break;
      if (await probe(url, ctx.signal)) {
        ready = true;
        break;
      }
      await sleep(intervalMs);
    }
  } finally {
    if (priorPort === undefined) {
      delete process.env.PLANNOTATOR_PORT;
    } else {
      process.env.PLANNOTATOR_PORT = priorPort;
    }
  }

  if (!ready) {
    return fail(
      `the plannotator review server did not become ready at ${url} within ` +
        `${Math.round(budgetMs / 1000)}s — degrade in-session: render the reconciled findings ` +
        "as a table in your reply and run the same triage loop conversationally; posting is " +
        "unchanged (submit_pr_review)",
      "server_not_ready",
    );
  }

  return ok(
    `plannotator code review opened on PR #${params.pr} — the browser is up at ${url}. ` +
      `Stream findings as per-angle waves to ${url}/api/external-annotations per the ` +
      "perk-review skill's cheat sheet (never GET /api/diff). The human's submission will " +
      "arrive in this session as a message.",
    { url, port },
  );
}

const TOOL_GUIDELINES = [
  "Call open_plannotator_review only on the /review plannotator arm (the injected guidance names it) — never on the hunk arm.",
  "Call it ONCE, right after spawning the guest reviewers — the browser opens on the PR while they work.",
  "The tool returns the local annotation endpoint; stream each angle's findings as one atomic POST wave per the perk-review skill's cheat sheet. Never GET /api/diff.",
  "The human's submission arrives later as a message in this session (one-shot: any browser ending resolves it).",
  "GitHub posting stays with submit_pr_review — the browser stream is a local UI surface, never a GitHub mutation.",
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
