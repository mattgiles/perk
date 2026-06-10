// P1.T5a — the warm `/submit` door (turn-5 §7). The in-session twin of the Python cold door
// (`perk pr-submit`): a deterministic, terminating tool + command that DELEGATE the GitHub write —
// they do NOT reimplement it (D1: GitHub mutations are canonical in the Python gateway). Mirrors
// `planSave.ts`: write nothing, delegate to `perk pr-submit --json` via `pi.exec`, surface the
// structured result, never throw (failures are loud-but-non-fatal via `details.ok = false`).

import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { report } from "./report.ts";

/** The structured `details` surface — doubles as branch-safe persisted state. */
export interface SubmitDetails {
  ok: boolean;
  pr?: { number: number; url: string; is_draft: boolean; existed: boolean };
  branch?: string;
  issue?: number;
  plan_embedded?: boolean;
  error?: string;
  error_type?: string;
}

export interface SubmitResult {
  content: { type: "text"; text: string }[];
  details: SubmitDetails;
  terminate?: boolean;
}

/** The `perk pr-submit --json` success shape (the contract the warm door consumes). */
interface PrSubmitJson {
  success: boolean;
  error_type: string | null;
  message: string | null;
  pr?: { number: number; url: string; is_draft: boolean; existed: boolean };
  branch?: string;
  issue?: number;
  plan_embedded?: boolean;
}

/**
 * The single submit implementation both surfaces call. Delegates to the Python cold door; returns a
 * soft result (never throws) — failures set `details.ok = false`.
 */
export async function submitPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<SubmitResult> {
  const reportError = (message: string): void => {
    report(ctx, "submit", "error", message, { alsoLog: true });
  };
  const fail = (message: string, errorType: string): SubmitResult => {
    reportError(message);
    return {
      content: [{ type: "text", text: `submit failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };

  const perkBin = process.env.PERK_BIN ?? "perk";
  // pi.exec returns (does not throw) on spawn/non-zero exit — turn-3 §3.5 S2.
  let res: ExecResult;
  try {
    res = await pi.exec(perkBin, ["pr-submit", "--json"], { cwd: ctx.cwd, signal: ctx.signal });
  } catch (err) {
    return fail(`could not run '${perkBin}': ${String(err)}`, "exec_failed");
  }

  if (res.killed || res.code !== 0) {
    const tail = res.stderr.trim();
    return fail(
      tail
        ? `perk pr-submit failed (exit ${res.code}): ${tail}`
        : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`,
      "exec_failed",
    );
  }

  let parsed: PrSubmitJson;
  try {
    parsed = JSON.parse(res.stdout) as PrSubmitJson;
  } catch {
    return fail("perk pr-submit returned unparseable JSON", "bad_output");
  }
  if (!parsed.success || !parsed.pr) {
    return fail(
      parsed.message ?? "perk pr-submit reported failure",
      parsed.error_type ?? "github_error",
    );
  }

  const verb = parsed.pr.existed ? "Found existing" : "Opened draft";
  const embed = parsed.plan_embedded ? "plan embedded" : "no plan embed";
  return {
    content: [
      { type: "text", text: `${verb} PR #${parsed.pr.number} → ${parsed.pr.url} (${embed})` },
    ],
    details: {
      ok: true,
      pr: parsed.pr,
      branch: parsed.branch,
      issue: parsed.issue,
      plan_embedded: parsed.plan_embedded,
    },
    terminate: true,
  };
}

const TOOL_GUIDELINES = [
  "Call submit only after the implementation is committed in this worktree; it pushes the branch and opens the draft PR, then ends the turn.",
  "submit operates on the active plan's worktree — it takes no arguments; the branch and plan come from the local plan-ref.",
];

/** Register the warm door: the `submit` terminating tool (canonical) + the `/submit` command twin. */
export function registerSubmit(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "submit",
    label: "Submit PR",
    description:
      "Push the current plan's branch and open a draft pull request linking the plan. " +
      "Terminating: ends the turn on submit. Call only after the implementation is committed.",
    promptSnippet: "Open the draft PR for the committed implementation (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      return submitPr(pi, ctx);
    },
  });

  pi.registerCommand("submit", {
    description: "Push the branch and open a draft PR for the active plan (implement → submit).",
    handler: async (_args, ctx) => {
      const result = await submitPr(pi, ctx);
      if (ctx.hasUI) {
        ctx.ui.notify(
          result.content[0]?.text ?? "submit done",
          result.details.ok ? "info" : "error",
        );
      }
    },
  });
}
