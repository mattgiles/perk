// The shared plannotator browser-review substrate — everything BOTH plannotator-driving
// surfaces need (`/pr-review-browser`, plus `/review`'s plannotator arm and its
// `open_plannotator_review` tool until that door retires): the presence probe, the pinned
// `code-review` event envelope + annotation decode, the active-PR resolution ladder, the
// respond routing, and the composable browser-open core (port preset + readiness poll). Hosted
// here — not in a door file — for the same reason as `hunkHandoff.ts`: `/review` retires
// wholesale once the surface-named doors land, and nothing the surviving door needs may live in
// a file that retirement deletes.
//
// pi exposes NO API for one extension to invoke another's slash command (`sendUserMessage` sends
// text to the model; `steer`/`followUp` ERROR on slash commands). So perk cannot literally call
// `/plannotator-review`. Instead it speaks plannotator's published `pi.events` API — a
// `plannotator:request` with `action: "code-review"` — which opens the EXACT same browser UI.
// Same in-process bus perk already uses for plan review (createPlannotatorBridge).
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
// (`/api/exit`). Both are consumed by the PR-mode respond routing (`respondMessage`); the
// pre-PR local mode's own routing (`routePrReviewOutcome`) branches on `exit` before the
// approved/feedback arms.
// Unlike plan-review there is NO handshake / no `reviewId` channel and no timeout: for code-review
// plannotator `await openCodeReview(...)` then responds ONCE with the final result.
//
// `"since-base"` is new in plannotator 0.22.0; older versions don't own that diff type and fall
// back to the reviewer's configured default diff — graceful degradation, no version detection.
// The requested diffType only sets the INITIAL view (the reviewer can switch from the header menu).
//
// SERVER ADDRESSING (why `startPlannotatorBrowser`'s env preset works): the pi extension runs
// plannotator's review server IN-PROCESS (`node:http`, not the standalone Bun binary), and its
// port resolution (`server/network.ts getServerPort()`) reads `PLANNOTATOR_PORT` at bind time —
// perk's extension and plannotator's server share one Node process, so an env var set here is
// read there. The core picks a free ephemeral port, presets the env var, emits the bridge
// request, polls `GET /api/diff` (a review-server-only route) for readiness, and ALWAYS restores
// the prior env value in a `finally` when the poll ends. Because the port is read at bind time,
// the server URL is KNOWN the moment the port is picked — before the server is up — which is
// what lets `/pr-review-browser` open the browser in the background and inject its guidance
// immediately. Concurrency caveat: a second plannotator server starting in the same process
// during the window would collide on the fixed port — rare and loud (EADDRINUSE → plannotator
// throws → the bridge settles error), never silent.

import { randomUUID } from "node:crypto";
import { createServer } from "node:net";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlannotatorBus } from "../adapters/planAdapterPlannotator.ts";
import { readPlanRef } from "../substrate/cache.ts";
import {
  type ColdDoorResult,
  type ColdJson,
  numberField,
  objectField,
  stringField,
} from "../substrate/coldDoor.ts";
import { type ReportTarget, report } from "../surfaces/report.ts";

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
 * One decoded plannotator annotation (the content subset of `CodeAnnotation` the PR-mode triage
 * consumes). Perk-pushed external annotations return with their `source` badge set;
 * human-authored ones carry no `source` — the authorship discriminator.
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

// ------------------------------------------------------------------------ the active-PR ladder

/** Where a no-arg browser review points: the active PR, a local since-base review, or fail. */
export type ReviewTarget =
  | { mode: "pr"; prUrl: string; number: number }
  | { mode: "local"; defaultBranch: string | undefined }
  | { mode: "fail"; message: string; errorType: string };

/**
 * Resolve the review target from the `perk pr url` result (the pure, offline-testable core).
 * `no_pr` — a plan worktree whose branch has no PR yet — falls back to the local review with the
 * plan-ref's pinned base (null collapses to undefined: an omitted field means plannotator
 * auto-detects the repo default, matching perk's `base: None ⇒ repo default` semantics). Every
 * other fail arm (including `no_plan_ref`) passes through unchanged — the doors stay plan-scoped;
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

/** Read the plan-ref's pinned base, swallowing read/parse errors (the doors must not throw). */
export function planRefBaseOf(cwd: string): string | undefined {
  try {
    return readPlanRef(cwd)?.base ?? undefined;
  } catch {
    return undefined;
  }
}

/** Narrow the `perk pr url --json` success payload; strict on `pr.{number,url}`. */
export function decodePrUrl(payload: ColdJson): { number: number; url: string } | null {
  const pr = objectField(payload, "pr");
  if (pr === undefined) return null;
  const number = numberField(pr, "number");
  const url = stringField(pr, "url");
  if (number === undefined || url === undefined) return null;
  return { number, url };
}

// ------------------------------------------------------------------------ respond routing

/**
 * Route the pre-PR local-mode outcome back into the session — mirrors plannotator's own routing.
 * `exit` (closed without feedback) is checked BEFORE the no-feedback arm: an abandoned review
 * must never report as "approved". Structural param slices keep it offline-testable; `scope` is
 * the invoking door's report scope.
 */
export function routePrReviewOutcome(
  pi: Pick<ExtensionAPI, "sendUserMessage">,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  out: CodeReviewOutcome,
  scope: string,
): void {
  if (out.status === "unavailable" || out.status === "error") {
    report(ctx, scope, "error", out.warning, { alsoLog: true });
    return;
  }
  if (out.status !== "handled") return; // aborted: the turn was interrupted — no-op

  if (out.exit) {
    report(ctx, scope, "info", "Code review closed without feedback.");
    return;
  }
  if (out.feedback === undefined) {
    report(ctx, scope, "info", "Code review approved — no changes requested.");
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

/**
 * The pure PR-mode respond → injection mapping (offline-testable). Null = nothing to inject (the
 * non-handled arms route elsewhere: unavailable/error → report(); aborted → no-op).
 *
 * THE POSTING FLIP (contracts §8.4): plannotator's native platform-posting is THE GitHub path —
 * perk composes nothing by default. `submit_pr_review` (gates unchanged) is offered ONLY for a
 * request-changes verdict (the UI cannot post it) or on the human's explicit request; there is
 * no read-back/dedupe step.
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
      "The human approved the code review in plannotator (no annotations) — the review is " +
      "complete. Perk posts nothing; offer `submit_pr_review` only if they explicitly ask " +
      "(e.g. a request-changes verdict, which the UI cannot post)."
    );
  }
  const parts: string[] = [outcome.feedback ?? "The plannotator review returned."];
  if (outcome.annotations.length > 0) {
    parts.push(`\`\`\`json\n${JSON.stringify(outcome.annotations, null, 2)}\n\`\`\``);
    parts.push(
      "These annotations are candidate comments: source-less ones are human-authored; " +
        "`perk:*`-badged ones are your own findings returning. Perk composes nothing by " +
        "default — ask the human what they want; `submit_pr_review` (dry-run repair loop + " +
        "gates unchanged) ONLY for a request-changes verdict or on their explicit request.",
    );
  }
  return parts.join("\n\n");
}

/** The minimal message sink `routeBrowserRespond` needs (an `ExtensionAPI` slice). */
export interface RespondSink {
  sendUserMessage(content: string, options?: { deliverAs?: "steer" | "followUp" }): void;
}

/**
 * Route a settled PR-mode respond into the session (the idle-vs-streaming injection route),
 * shared by `/pr-review-browser`'s PR modes and `open_plannotator_review`. `scope` is the
 * invoking surface's report scope.
 */
export function routeBrowserRespond(
  pi: RespondSink,
  ctx: ReportTarget & Pick<ExtensionContext, "isIdle">,
  out: CodeReviewOutcome,
  scope: string,
): void {
  if (out.status === "unavailable" || out.status === "error") {
    // Degrade-mid-flow: the flow continues in-session (findings table; posting unchanged).
    report(ctx, scope, "error", out.warning, { alsoLog: true });
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

// ------------------------------------------------------------------------ the browser-open core

/** The readiness-probe cadence: one `GET /api/diff` per second. */
export const READINESS_PROBE_INTERVAL_MS = 1_000;

/**
 * The readiness budget — generous because plannotator's setup does real work before the server
 * binds (the PR fetch + its own optional local checkout can be slow).
 */
export const READINESS_PROBE_BUDGET_MS = 120_000;

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

/** How the readiness poll ended (the browser-open core's observable outcome). */
export type BrowserReadiness = "ready" | "timeout" | "bridge_settled" | "aborted";

/** The injectable browser-open seams (tests drive a fake port picker / probe / clock). */
export interface StartBrowserDeps {
  pickFreePort?: () => Promise<number>;
  probe?: (url: string, signal?: AbortSignal) => Promise<boolean>;
  intervalMs?: number;
  budgetMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

/** A started browser open: the deterministic address + the two observable promises. */
export interface StartedBrowser {
  url: string;
  port: number;
  bridgePromise: Promise<CodeReviewOutcome>;
  readiness: Promise<BrowserReadiness>;
}

/**
 * The composable browser-open core: pick a free port → save + preset `PLANNOTATOR_PORT` → emit
 * the `code-review` bridge request (the PR-mode payload `{prUrl, cwd}` byte-for-byte —
 * plannotator's defaults, including its own local checkout for Ask AI / Full-stack: deliberately
 * NOT `useLocal: false`, the human chose the full surface) → return immediately with the
 * deterministic `{url, port}` plus the two promises the caller observes: `bridgePromise` (the
 * single respond) and `readiness` (the `GET /api/diff` poll — 1s cadence, 120s budget,
 * attempt-counted so injected test clocks stay deterministic; stops early when the bridge
 * settles first — an early error/unavailable respond means the server never comes — or the turn
 * aborts). The prior env value is ALWAYS restored (delete if previously unset) in a `finally`
 * when the poll ends: after the window the fixed port is released back to plannotator's own
 * resolution (random port) for any later server. A port-pick failure throws — the caller owns
 * its failure surface.
 */
export async function startPlannotatorBrowser(
  bus: PlannotatorBus,
  opts: { prUrl: string; cwd: string; signal?: AbortSignal },
  deps: StartBrowserDeps = {},
): Promise<StartedBrowser> {
  const pickPort = deps.pickFreePort ?? pickFreePort;
  const probe = deps.probe ?? probeReviewServer;
  const intervalMs = deps.intervalMs ?? READINESS_PROBE_INTERVAL_MS;
  const budgetMs = deps.budgetMs ?? READINESS_PROBE_BUDGET_MS;
  const sleep =
    deps.sleep ?? ((ms: number) => new Promise<void>((r) => globalThis.setTimeout(r, ms)));

  const port = await pickPort();
  const url = `http://127.0.0.1:${port}`;

  const priorPort = process.env.PLANNOTATOR_PORT;
  process.env.PLANNOTATOR_PORT = String(port);

  // Emit the bridge request while PLANNOTATOR_PORT is preset — plannotator's `listenOnPort`
  // reads it at bind time.
  let bridgeSettled = false;
  const bridgePromise = requestPlannotatorCodeReview(bus, {
    prUrl: opts.prUrl,
    cwd: opts.cwd,
    signal: opts.signal,
  });
  void bridgePromise.then(() => {
    bridgeSettled = true;
  });

  const readiness = (async (): Promise<BrowserReadiness> => {
    try {
      const attempts = Math.max(1, Math.floor(budgetMs / intervalMs));
      for (let i = 0; i < attempts; i++) {
        // Abort first: an aborted turn also settles the bridge (as `aborted`), and the abort
        // arm must win so the observer stays silent instead of degrading.
        if (opts.signal?.aborted === true) return "aborted";
        if (bridgeSettled) return "bridge_settled";
        if (await probe(url, opts.signal)) return "ready";
        await sleep(intervalMs);
      }
      return "timeout";
    } finally {
      if (priorPort === undefined) {
        delete process.env.PLANNOTATOR_PORT;
      } else {
        process.env.PLANNOTATOR_PORT = priorPort;
      }
    }
  })();

  return { url, port, bridgePromise, readiness };
}
