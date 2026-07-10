// The hunk terminal-review substrate serving `/pr-review-terminal`: the strict
// `perk pr review checkout` decode, the `hunk --version` presence probe, and the R7 launch
// handoff (clipboard copy + terminal auto-launch raced against a soft deadline) — plus the
// door-common PR-token arg grammar (`parseReviewArgs`) that `/pr-review-browser` also consumes
// via `parseReviewDoorArgs`. Re-homing the door-common pieces to a neutral module is a deferred
// residual (accepted — no code moves yet).

import { copyToClipboard } from "../substrate/clipboard.ts";
import { type ColdJson, type ExecHost, numberField, stringField } from "../substrate/coldDoor.ts";
import { LAUNCH_SURFACE, launchInTerminal } from "../substrate/terminalLaunch.ts";
import { type ReportTarget, report } from "../surfaces/report.ts";

/** The install hint for the absent hunk binary — the exact `HUNK_INSTALL_HINT` wording
 * (src/perk/convergence/init/review_cli.py). */
export const HUNK_INSTALL_HINT = "npm i -g hunkdiff (or brew install hunk)";

// ------------------------------------------------------------------------ the PR arg grammar

/** A parsed PR-review invocation: the PR number + the optional free-form focus directive. */
export interface ReviewArgs {
  pr: number;
  directive: string;
}

/** Extracts the PR number from a GitHub PR URL (with optional trailing /path, #fragment, ?query). */
export const PR_URL_RE = /\/pull\/(\d+)(?:\/|$|#|\?)/;

/**
 * Parse a PR-review arg string: the first token is a bare PR number or a GitHub PR URL; the rest
 * is the optional free-form focus directive. Null on a missing/unparseable PR (usage failure).
 * Cross-repo URLs are NOT validated against the session repo — the number is extracted as-is.
 */
export function parseReviewArgs(args: string): ReviewArgs | null {
  const trimmed = args.trim();
  if (trimmed.length === 0) return null;
  const split = trimmed.match(/^(\S+)(?:\s+([\s\S]*))?$/);
  if (split === null) return null;
  const first = split[1] ?? "";
  const directive = (split[2] ?? "").trim();
  let pr: number | null = null;
  if (/^\d+$/.test(first)) {
    pr = Number(first);
  } else {
    const url = first.match(PR_URL_RE);
    if (url?.[1] !== undefined) pr = Number(url[1]);
  }
  if (pr === null || !Number.isSafeInteger(pr) || pr <= 0) return null;
  return { pr, directive };
}

// ------------------------------------------------------------------------ checkout decode

/** The `perk pr review checkout --json` ok-arm (all six fields always emitted — strict). */
export interface CheckoutOk {
  path: string;
  pr: number;
  url: string;
  head_sha: string;
  base_sha: string;
  base_ref: string;
}

/** Strict decode of the checkout payload — the guidance dereferences `path`/`base_sha`/`url`. */
export function decodeCheckout(payload: ColdJson): CheckoutOk | null {
  const path = stringField(payload, "path");
  const pr = numberField(payload, "pr");
  const url = stringField(payload, "url");
  const headSha = stringField(payload, "head_sha");
  const baseSha = stringField(payload, "base_sha");
  const baseRef = stringField(payload, "base_ref");
  if (
    path === undefined ||
    pr === undefined ||
    url === undefined ||
    headSha === undefined ||
    baseSha === undefined ||
    baseRef === undefined
  ) {
    return null;
  }
  return { path, pr, url, head_sha: headSha, base_sha: baseSha, base_ref: baseRef };
}

// ------------------------------------------------------------------------ the hunk probe

/**
 * Whether the `hunk` review CLI is present — the `hunk --version` probe (`!killed && code === 0`;
 * any throw ⇒ false). The terminal door refuses-at-start on a false, before any cold-door call.
 */
export async function hunkPresent(
  pi: ExecHost,
  ctx: { cwd: string; signal?: AbortSignal },
): Promise<boolean> {
  try {
    const probe = await pi.exec("hunk", ["--version"], { cwd: ctx.cwd, signal: ctx.signal });
    return !probe.killed && probe.code === 0;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------------ the R7 handoff

/** The minimal ctx slice the hunk launch handoff needs (report + the exec cwd/signal). */
interface ReviewLaunchCtx extends ReportTarget {
  cwd: string;
  signal?: AbortSignal;
}

/** The default soft deadline the launch is raced against (ms) — see `handleHunkLaunch`. */
const LAUNCH_SOFT_DEADLINE_MS = 2000;

/**
 * The soft-deadline knob: `PERK_REVIEW_LAUNCH_DEADLINE_MS` (an internal test seam — documented
 * in contracts §8.4 beside the two human-facing seams, never in user docs; tests drive the whole
 * command handler, so an env knob is the only injectable surface). Falls back to the 2s default.
 */
function softDeadlineMs(): number {
  const raw = process.env.PERK_REVIEW_LAUNCH_DEADLINE_MS;
  if (raw !== undefined) {
    const n = Number(raw);
    if (Number.isFinite(n) && n >= 0) return n;
  }
  return LAUNCH_SOFT_DEADLINE_MS;
}

/**
 * A cancellable `null`-resolving timer — the soft-deadline arm of the launch race. The caller
 * cancels it once the race settles so a won race never leaves a live timer behind (a leak in
 * production; a hang/latency drag under test runners that wait for pending timers).
 */
function delay(ms: number): { promise: Promise<null>; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const promise = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  return {
    promise,
    cancel: () => {
      if (timer !== undefined) clearTimeout(timer);
    },
  };
}

/**
 * The hunk R7 handoff (contracts §8.4). Copies the launch command to the clipboard, then
 * auto-launches hunk in a terminal the human can see — raced against a soft deadline so a
 * first-run macOS Automation/TCC dialog (which blocks `osascript` until answered) never inserts
 * ~18s of silence before the guidance injection. Reports the outcome under `opts.scope` (the
 * invoking door's report scope): an **info** "opened hunk" when the launch settled cleanly within
 * the deadline, else a **warning** "ACTION NEEDED" (the launch failed, no rung matched, or it is
 * still pending). For the pending case, a background follow-up info note lands if/when consent is
 * granted and the launch succeeds. Non-blocking: the caller injects the guidance immediately
 * either way. The `hunk session get` handshake (driven by the model per the template) — never a
 * spawn success — remains the only verification hunk is up.
 */
export async function handleHunkLaunch(
  pi: ExecHost,
  ctx: ReviewLaunchCtx,
  opts: { cwd: string; hunkCmd: string; launchLine: string; scope: string },
): Promise<void> {
  const copied = await copyToClipboard(pi, ctx, opts.launchLine);
  const clip = copied ? " (it's on your clipboard)" : "";
  const settled = launchInTerminal(pi, ctx, { cwd: opts.cwd, command: opts.hunkCmd });
  const deadline = delay(softDeadlineMs());
  const quick = await Promise.race([settled, deadline.promise]);
  deadline.cancel();
  if (quick?.launched) {
    report(
      ctx,
      opts.scope,
      "info",
      `opened hunk in a new ${LAUNCH_SURFACE[quick.via ?? "terminal-app"]} — if nothing ` +
        `appeared, run this in another terminal:\n  ${opts.launchLine}${clip}`,
    );
    return;
  }
  report(
    ctx,
    opts.scope,
    "warning",
    `ACTION NEEDED — run hunk in another terminal:\n  ${opts.launchLine}${clip}`,
  );
  if (quick === null) {
    // Still pending past the soft deadline (a first-run TCC dialog): proceed now, and note it if
    // consent is granted and the launch lands so the human can ignore the manual step.
    // `launchInTerminal` never rejects by contract — the `.catch` is belt-and-braces.
    void settled
      .then((r) => {
        if (r.launched) {
          report(
            ctx,
            opts.scope,
            "info",
            `hunk opened in a new ${LAUNCH_SURFACE[r.via ?? "terminal-app"]} — ignore the ` +
              "manual step above",
          );
        }
      })
      .catch(() => {});
  }
}
