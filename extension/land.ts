// P1.T5b — the warm `/land` door (turn-5 §7). The in-session twin of the Python cold door
// (`perk pr-land`): a terminating tool + command that DELEGATE the GitHub merge (D1 — mutations
// canonical in Python), then set the `pending-learn` marker for the in-session path (the worker
// sets it too on the cold path; the marker is an idempotent existence-semaphore). Never throws.

import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { PENDING_LEARN, setMarker } from "./cache.ts";

export interface LandDetails {
  ok: boolean;
  pr?: { number: number; state: string };
  branch?: string;
  issue?: number;
  pending_learn?: boolean;
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
}

/**
 * The single land implementation both surfaces call. Delegates the merge to the Python cold door,
 * then sets `pending-learn` (in-session path). Returns a soft result (never throws).
 */
export async function landPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<LandResult> {
  const reportError = (message: string): void => {
    const full = `perk: land — ${message}`;
    if (ctx.hasUI) ctx.ui.notify(full, "error");
    console.error(full);
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

  return {
    content: [
      { type: "text", text: `Landed PR #${parsed.pr.number}; run /learn to release the worktree.` },
    ],
    details: {
      ok: true,
      pr: parsed.pr,
      branch: parsed.branch,
      issue: parsed.issue,
      pending_learn: true,
    },
    terminate: true,
  };
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
      return landPr(pi, ctx);
    },
  });

  pi.registerCommand("land", {
    description: "Merge the active plan's PR and set pending-learn (submit → land).",
    handler: async (_args, ctx) => {
      const result = await landPr(pi, ctx);
      if (ctx.hasUI) {
        ctx.ui.notify(result.content[0]?.text ?? "land done", result.details.ok ? "info" : "error");
      }
    },
  });
}
