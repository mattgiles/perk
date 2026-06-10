// P1.T5b — the warm `/land` door (turn-5 §7). The in-session twin of the Python cold door
// (`perk pr-land`): a terminating tool + command that DELEGATE the GitHub merge (D1 — mutations
// canonical in Python), then set the `pending-learn` marker for the in-session path (the worker
// sets it too on the cold path; the marker is an idempotent existence-semaphore). Never throws.

import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "./bindingDelivery.ts";
import { PENDING_LEARN, setMarker } from "./cache.ts";
import { reconcileGuidance } from "./objectivePlan.ts";
import { report } from "./report.ts";

// Learn-consume skip reasons that are ordinary, not failures (#102): non-factory plans carry no
// `consumed_learn` (`no_consumed_learn`), and a dry run reports `dry_run`. Anything else surfaces.
const BENIGN_LEARN_SKIPS = new Set(["no_consumed_learn", "dry_run"]);

export interface ObjectiveLandUpdate {
  number: number | null;
  nodes_marked: string[];
  skipped_reason: string | null;
}

export interface LearnConsumeUpdate {
  closed: number[];
  skipped_reason: string | null;
}

export interface LandDetails {
  ok: boolean;
  pr?: { number: number; state: string };
  branch?: string;
  issue?: number;
  pending_learn?: boolean;
  objective?: ObjectiveLandUpdate;
  learn?: LearnConsumeUpdate;
  error?: string;
  error_type?: string;
}

export interface LandResult {
  content: { type: "text"; text: string }[];
  details: LandDetails;
  terminate?: boolean;
}

interface PrLandJson {
  success: boolean;
  error_type: string | null;
  message: string | null;
  pr?: { number: number; state: string };
  branch?: string;
  issue?: number;
  pending_learn?: boolean;
  objective?: ObjectiveLandUpdate;
  learn?: LearnConsumeUpdate;
}

/**
 * The single land implementation both surfaces call. Delegates the merge to the Python cold door,
 * then sets `pending-learn` (in-session path). Returns a soft result (never throws).
 */
export async function landPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<LandResult> {
  const reportError = (message: string): void => {
    report(ctx, "land", "error", message, { alsoLog: true });
  };
  const fail = (message: string, errorType: string): LandResult => {
    reportError(message);
    return {
      content: [{ type: "text", text: `land failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };

  const perkBin = process.env.PERK_BIN ?? "perk";
  let res: ExecResult;
  try {
    res = await pi.exec(perkBin, ["pr-land", "--json"], { cwd: ctx.cwd, signal: ctx.signal });
  } catch (err) {
    return fail(`could not run '${perkBin}': ${String(err)}`, "exec_failed");
  }

  if (res.killed || res.code !== 0) {
    const tail = res.stderr.trim();
    return fail(
      tail
        ? `perk pr-land failed (exit ${res.code}): ${tail}`
        : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`,
      "exec_failed",
    );
  }

  let parsed: PrLandJson;
  try {
    parsed = JSON.parse(res.stdout) as PrLandJson;
  } catch {
    return fail("perk pr-land returned unparseable JSON", "bad_output");
  }
  if (!parsed.success || !parsed.pr) {
    return fail(
      parsed.message ?? "perk pr-land reported failure",
      parsed.error_type ?? "github_error",
    );
  }

  // Set the semaphore for the in-session path (idempotent; the worker also set it on disk).
  setMarker(ctx.cwd, PENDING_LEARN);

  const lines = [`Landed PR #${parsed.pr.number}; run /learn to release the worktree.`];
  const obj = parsed.objective;
  if (obj?.nodes_marked.length && obj.number !== null) {
    // The reconcile pass is auto-driven after land (see driveReconcileAfterLand); just report it.
    lines.push(
      `Objective #${obj.number} node(s) ${obj.nodes_marked.join(", ")} marked done — ` +
        `reconciling the roadmap against the merged diff.`,
    );
  }
  const learn = parsed.learn;
  if (learn?.closed.length) {
    // hop-2: the consumed perk:learn issues were closed + labelled perk:consolidated on land.
    lines.push(
      `Closed ${learn.closed.length} learn issue(s) (${learn.closed
        .map((n) => `#${n}`)
        .join(", ")}) into docs/learned.`,
    );
  }
  // Surface a non-benign learn-consume skip (#102): `no_consumed_learn` is the ordinary
  // non-factory case, so stay quiet on it; a real failure must be visible, not silent.
  if (learn?.skipped_reason && !BENIGN_LEARN_SKIPS.has(learn.skipped_reason)) {
    lines.push(`Warning: learn consume incomplete — ${learn.skipped_reason}.`);
  }

  return {
    content: [{ type: "text", text: lines.join("\n") }],
    details: {
      ok: true,
      pr: parsed.pr,
      branch: parsed.branch,
      issue: parsed.issue,
      pending_learn: true,
      objective: parsed.objective,
      learn: parsed.learn,
    },
    terminate: true,
  };
}

/**
 * After a successful land that marked at least one objective node done, drive the session into the
 * reconcile pass by injecting the exact guidance `/objective-reconcile` injects (warm-door driving
 * pattern). The terminating `land` tool stays terminating — terminate only skips the *automatic*
 * follow-up LLM call, while a `followUp` user message is a separate deliberate new turn. Short-
 * circuits (sends nothing) unless the land succeeded with an objective node marked done — the exact
 * condition that gated the old copy-pasteable nudge.
 */
export function driveReconcileAfterLand(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  details: LandDetails,
): void {
  const obj = details.objective;
  if (!details.ok || !obj || obj.number === null || obj.nodes_marked.length === 0) return;
  const message =
    reconcileGuidance(String(obj.number)) + bindingSuffix(ctx.cwd, "command:objective-reconcile");
  if (ctx.isIdle()) {
    // The `/land` command path (idle): inject an immediate turn.
    pi.sendUserMessage(message);
  } else {
    // The `land` tool path (streaming): deliver after the terminating land batch.
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

const TOOL_GUIDELINES = [
  "Call land only when the PR is approved and ready to merge; it squash-merges the PR (closing the plan issue) and sets pending-learn.",
  "land operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch.",
];

/** Register the warm door: the `land` terminating tool + the `/land` command twin. */
export function registerLand(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "land",
    label: "Land PR",
    description:
      "Merge the active plan's approved PR (squash, closing the plan issue) and set pending-learn. " +
      "Terminating: ends the turn on land. Call only when the PR is ready to merge.",
    promptSnippet: "Squash-merge the approved PR and set pending-learn (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const result = await landPr(pi, ctx);
      driveReconcileAfterLand(pi, ctx, result.details);
      return result;
    },
  });

  pi.registerCommand("land", {
    description: "Merge the active plan's PR and set pending-learn (submit → land).",
    handler: async (_args, ctx) => {
      const result = await landPr(pi, ctx);
      if (ctx.hasUI) {
        ctx.ui.notify(result.content[0]?.text ?? "land done", result.details.ok ? "info" : "error");
      }
      driveReconcileAfterLand(pi, ctx, result.details);
    },
  });
}
