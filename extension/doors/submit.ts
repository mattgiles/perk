// P1.T5a — the warm `/submit` door (turn-5 §7). The in-session twin of the Python cold door
// (`perk pr submit`): a deterministic, terminating tool + command that DELEGATE the GitHub write —
// they do NOT reimplement it (D1: GitHub mutations are canonical in the Python gateway). Mirrors
// `planSave.ts`: write nothing, delegate to `perk pr submit --json` via `pi.exec`, surface the
// structured result, never throw (failures are loud-but-non-fatal via `details.ok = false`).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "./coldDoor.ts";
import { report } from "./report.ts";
import { failFor, ok, type Result } from "./result.ts";

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface SubmitOk {
  pr: { number: number; url: string; is_draft: boolean; existed: boolean };
  branch?: string;
  issue?: number;
  plan_embedded?: boolean;
}

export type SubmitResult = Result<SubmitOk>;
export type SubmitDetails = SubmitResult["details"];

/** Narrow the `perk pr submit --json` success payload; strict on `pr`, lenient on the rest. */
function decodeSubmit(payload: ColdJson): SubmitOk | null {
  const pr = objectField(payload, "pr");
  if (pr === undefined) return null;
  const number = numberField(pr, "number");
  const url = stringField(pr, "url");
  const isDraft = booleanField(pr, "is_draft");
  const existed = booleanField(pr, "existed");
  if (number === undefined || url === undefined || isDraft === undefined || existed === undefined) {
    return null;
  }
  return {
    pr: { number, url, is_draft: isDraft, existed },
    branch: stringField(payload, "branch"),
    issue: numberField(payload, "issue"),
    plan_embedded: booleanField(payload, "plan_embedded"),
  };
}

/**
 * The single submit implementation both surfaces call. Delegates to the Python cold door; returns a
 * soft result (never throws) — failures set `details.ok = false`.
 */
export async function submitPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<SubmitResult> {
  const fail = failFor(ctx, "submit");

  const r = await runColdDoor<SubmitOk>(pi, ctx, ["pr", "submit", "--json"], {
    label: "perk pr submit",
    decode: decodeSubmit,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  const verb = r.data.pr.existed ? "Found existing" : "Opened draft";
  const embed = r.data.plan_embedded ? "plan embedded" : "no plan embed";
  return ok(`${verb} PR #${r.data.pr.number} → ${r.data.pr.url} (${embed})`, r.data, {
    terminate: true,
  });
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
      // Failure already reported loudly via failFor (the single error surface) — success only.
      if (result.details.ok) {
        report(ctx, "submit", "info", result.content[0]?.text ?? "submit done");
      }
    },
  });
}
