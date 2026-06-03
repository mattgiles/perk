// P2.T8a — the warm `/ready` door (D6): the deliberate draft→ready review gate. The in-session twin
// of the Python cold door (`perk pr-ready`): a terminating tool + command that DELEGATE the GitHub
// mark-ready (D1 — mutations canonical in Python). perk deliberately does NOT auto-publish on
// submit; `/ready` is the explicit gesture that opens the PR for review. Mirrors `submit.ts`: write
// nothing, delegate via `pi.exec`, surface the structured result, never throw.

import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

/** The structured `details` surface — doubles as branch-safe persisted state. */
export interface ReadyDetails {
  ok: boolean;
  pr?: { number: number; url: string };
  was_draft?: boolean;
  error?: string;
  error_type?: string;
}

export interface ReadyResult {
  content: { type: "text"; text: string }[];
  details: ReadyDetails;
  terminate?: boolean;
}

/** The `perk pr-ready --json` success shape (the contract the warm door consumes). */
interface PrReadyJson {
  success: boolean;
  error_type: string | null;
  message: string | null;
  pr?: { number: number; url: string };
  was_draft?: boolean;
}

/**
 * The single ready implementation both surfaces call. Delegates to the Python cold door; returns a
 * soft result (never throws) — failures set `details.ok = false`.
 */
export async function markReady(pi: ExtensionAPI, ctx: ExtensionContext): Promise<ReadyResult> {
  const reportError = (message: string): void => {
    const full = `perk: ready — ${message}`;
    if (ctx.hasUI) ctx.ui.notify(full, "error");
    console.error(full);
  };
  const fail = (message: string, errorType: string): ReadyResult => {
    reportError(message);
    return {
      content: [{ type: "text", text: `ready failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };

  const perkBin = process.env.PERK_BIN ?? "perk";
  let res: ExecResult;
  try {
    res = await pi.exec(perkBin, ["pr-ready", "--json"], { cwd: ctx.cwd, signal: ctx.signal });
  } catch (err) {
    return fail(`could not run '${perkBin}': ${String(err)}`, "exec_failed");
  }

  if (res.killed || res.code !== 0) {
    const tail = res.stderr.trim();
    return fail(
      tail
        ? `perk pr-ready failed (exit ${res.code}): ${tail}`
        : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`,
      "exec_failed",
    );
  }

  let parsed: PrReadyJson;
  try {
    parsed = JSON.parse(res.stdout) as PrReadyJson;
  } catch {
    return fail("perk pr-ready returned unparseable JSON", "bad_output");
  }
  if (!parsed.success || !parsed.pr) {
    return fail(
      parsed.message ?? "perk pr-ready reported failure",
      parsed.error_type ?? "github_error",
    );
  }

  const verb = parsed.was_draft ? "Marked ready" : "Already ready";
  return {
    content: [{ type: "text", text: `${verb}: PR #${parsed.pr.number} is open for review.` }],
    details: { ok: true, pr: parsed.pr, was_draft: parsed.was_draft },
    terminate: true,
  };
}

const TOOL_GUIDELINES = [
  "Call ready only when the PR is ready for human review; it marks the draft PR ready (the deliberate review gate). submit keeps the PR draft on purpose.",
  "ready operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch. Idempotent: an already-ready PR is success.",
];

/** Register the warm door: the `ready` terminating tool + the `/ready` command twin. */
export function registerReady(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "ready",
    label: "Mark PR ready",
    description:
      "Mark the active plan's draft PR ready for review (the deliberate review gate). " +
      "Terminating: ends the turn. submit keeps the PR draft; ready is the explicit publish gesture.",
    promptSnippet: "Mark the draft PR ready for review (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      return markReady(pi, ctx);
    },
  });

  pi.registerCommand("ready", {
    description: "Mark the active plan's draft PR ready for review (submit → ready).",
    handler: async (_args, ctx) => {
      const result = await markReady(pi, ctx);
      if (ctx.hasUI) {
        ctx.ui.notify(
          result.content[0]?.text ?? "ready done",
          result.details.ok ? "info" : "error",
        );
      }
    },
  });
}
