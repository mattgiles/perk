// The deepened warm `/learn` door. Graduates the thin marker-clear into a real knowledge-capture
// pass: when a `summary` is given, DELEGATE to `perk learn capture --json` via the shared cold-door
// client (`runColdDoor` — the body rides the run-scratch stdin channel; GitHub writes canonical in
// Python), which creates a `perk:learn` issue + clears
// `pending-learn`; then mirror the marker-clear in-session (idempotent). With no `summary`, stay
// the thin TS-only marker-clear (graceful — no empty issue). Never throws (soft `details.ok`);
// the capture decode is fully LENIENT — a `success: true` envelope always yields the captured-ok
// terminating result even when `learn_issue` is undecodable (render-only field; see
// `decodeLearnCapture`).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import {
  clearMarker,
  hasMarker,
  PENDING_LEARN,
  type PlanRef,
  readPlanRef,
} from "../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";
import { planReadInstruction } from "./lifecycleGates.ts";

/** The ok-arm fields. */
export interface LearnOk {
  was_pending: boolean;
  captured: boolean;
  /** `id` is the opaque string issue id (GitHub "42", Linear "ENG-123") — §8.21. */
  learn_issue?: { id: string; url: string; existed: boolean };
}

export type LearnResult = Result<LearnOk>;

/** The decoded `perk learn capture --json` payload slice the warm door consumes. */
interface LearnCapturePayload {
  learn_issue?: { id: string; url: string; existed: boolean };
}

/**
 * Narrow the `perk learn capture --json` success payload — fully LENIENT, per the decode-policy
 * criterion (strict iff the field is appended to workflow-state; see
 * `docs/learned/workflow/cold-door-client.md`). `learn_issue` is render-only — it feeds only the
 * success message text and `details` — and the `success: true` envelope is the cold door's
 * authoritative statement that the capture mutation completed and the on-disk `pending-learn`
 * marker was already cleared. So any miss on the sub-object (absent key, a legacy `number` shape,
 * mistyped fields — e.g. under CLI↔extension version skew) yields
 * `{ learn_issue: undefined }`, never null: the warm report must survive an undecodable payload,
 * and the `bad_output` arm is deliberately unreachable for this door. `pending_cleared` is
 * unconsumed.
 */
function decodeLearnCapture(payload: ColdJson): LearnCapturePayload {
  const issue = objectField(payload, "learn_issue");
  if (issue === undefined) return { learn_issue: undefined };
  const id = stringField(issue, "id");
  const url = stringField(issue, "url");
  const existed = booleanField(issue, "existed");
  if (id === undefined || url === undefined || existed === undefined) {
    return { learn_issue: undefined };
  }
  return { learn_issue: { id, url, existed } };
}

/** Clear `pending-learn` (idempotent — a no-op if it was not set). Reports whether it was set. */
function clearPending(ctx: ExtensionContext): { wasPending: boolean } {
  const wasPending = hasMarker(ctx.cwd, PENDING_LEARN);
  clearMarker(ctx.cwd, PENDING_LEARN);
  return { wasPending };
}

/**
 * The single learn implementation both surfaces call. With a `summary`, delegate the capture to the
 * Python cold door (then mirror the marker-clear); without one, stay the thin marker-clear. Returns
 * a soft result (never throws).
 */
export async function learnDone(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  summary?: string,
): Promise<LearnResult> {
  const trimmed = (summary ?? "").trim();

  // No summary: the thin, graceful path — just clear the marker (no empty issue).
  if (trimmed.length === 0) {
    const { wasPending } = clearPending(ctx);
    const text = wasPending
      ? "Cleared pending-learn — the worktree is releasable. (No summary given; no learn issue created.)"
      : "No pending-learn set — nothing to clear.";
    return ok(text, { was_pending: wasPending, captured: false }, { terminate: true });
  }

  const fail = failFor(ctx, "learn");

  const r = await runColdDoor<LearnCapturePayload>(pi, ctx, ["learn", "capture", "--json"], {
    label: "perk learn capture",
    decode: decodeLearnCapture,
    stdin: { flag: "--body", content: `${trimmed}\n`, filename: `learn-${Date.now()}.md` },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Mirror the marker-clear in-session (idempotent; the worker also cleared it on disk). Runs
  // even when `learn_issue` is undecodable — a success envelope clears the marker.
  const { wasPending } = clearPending(ctx);
  const issue = r.data.learn_issue;
  if (issue === undefined) {
    return ok(
      "Captured learnings; pending-learn cleared. (learn issue details undecodable — the perk " +
        "CLI and the perk extension may be version-skewed.)",
      { was_pending: wasPending, captured: true },
      { terminate: true },
    );
  }
  const verb = issue.existed ? "Found existing" : "Created";
  return ok(
    `${verb} learn issue #${issue.id}; pending-learn cleared.`,
    { was_pending: wasPending, captured: true, learn_issue: issue },
    { terminate: true },
  );
}

const TOOL_GUIDELINES = [
  "Call learn after a plan has landed; pass a `summary` of the durable learnings to capture them in a perk:learn issue (and clear pending-learn). Omit `summary` to just clear the marker.",
  "The summary is captured verbatim — write the learnings as markdown (what changed vs. the plan, deviations, residual risks).",
];

/** Resolve the active plan-ref (worktree first, then the rebuilt workflow-state). */
function activePlanRef(ctx: ExtensionContext): PlanRef | null {
  const fromWorktree = readPlanRef(ctx.cwd);
  if (fromWorktree) return fromWorktree;
  try {
    const branch = branchOf(ctx);
    return (rebuildWorkflowState(branch).active_plan_ref as PlanRef | null) ?? null;
  } catch {
    return null;
  }
}

/**
 * Inject the learn-workflow guidance the model follows (the perk-learn skill pointer rides the
 * skill-binding suffix — not hardcoded here). The wording lives in the canonical template
 * `prompts/stages/learn.md`, rendered identically by both planes via the shared render seam
 * (contracts.md §8.31); the github/linear/other/no-ref branching is the template conditional on
 * `provider` (+ `pr_id` presence), and `read_cmd` is the node-2.1 plan-read instruction. Unified
 * onto the cold `_learn_prompt` body — byte-identical to it for every provider arm (the four
 * `learn-*` golden cases are the cross-plane parity proof). When no plan-ref is known, render the
 * no-ref arm (learn can proceed without a ref — no dead-end null-guard).
 */
export function learnGuidance(planRef: PlanRef | null): string {
  if (planRef === null) {
    return render("stages/learn.md", { provider: "", pr_id: "", url: "", read_cmd: "" });
  }
  const read_cmd = planReadInstruction(planRef.provider, planRef.pr_id, planRef.url);
  return render("stages/learn.md", {
    provider: planRef.provider,
    pr_id: planRef.pr_id,
    url: planRef.url,
    read_cmd,
  });
}

/** Register the warm door: the `learn` terminating tool + the `/learn` command twin. */
export function registerLearn(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "learn",
    label: "Finish learn",
    description:
      "Capture learnings from a landed plan into a perk:learn issue (pass `summary`), then clear " +
      "the pending-learn semaphore and release the worktree. Omit `summary` to only clear the marker. " +
      "Terminating: ends the turn.",
    promptSnippet:
      "Capture learnings (optional summary) and clear pending-learn (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        summary: {
          type: "string",
          description: "Markdown learnings to capture in a perk:learn issue. Omit to only clear.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // Tool-boundary decode: absent → undefined (the marker-clear path); mistyped →
      // strict-fail — never silently clear the pending-learn marker on uncertainty.
      const p = paramsOf(params);
      const summary = p === null ? undefined : stringParam(p, "summary");
      if (summary === null) {
        return failFor(ctx, "learn")("learn `summary` must be a string", "bad_input");
      }
      return learnDone(pi, ctx, summary);
    },
  });

  pi.registerCommand("learn", {
    description:
      "Investigate the landed change and capture learnings (bare /learn drives the workflow); " +
      "/learn skip clears pending-learn only; /learn <text> captures the text verbatim.",
    handler: async (args, ctx) => {
      const trimmed = (args ?? "").trim();

      // Explicit text (or `skip`): the existing learnDone path — capture verbatim / marker-clear.
      if (trimmed.length > 0) {
        const summary = trimmed === "skip" ? "" : args;
        const result = await learnDone(pi, ctx, summary);
        // Failure already reported loudly via failFor (the single error surface) — success only.
        if (result.details.ok) {
          report(ctx, "learn", "info", result.content[0]?.text ?? "learn done");
        }
        return;
      }

      // Bare `/learn`: headless can't drive a turn — stay the safe marker-clear (fail-safe). An
      // interactive session injects the perk-learn guidance so the agent does the capture pass
      // (it clears the marker itself by calling the `learn` tool — do NOT clear it here).
      if (!ctx.hasUI) {
        const result = await learnDone(pi, ctx, "");
        console.error(`perk: /learn invoked (headless) — ${result.content[0]?.text ?? "cleared"}`);
        return;
      }
      report(ctx, "learn", "info", "investigate the landed change and capture learnings");
      pi.sendUserMessage(learnGuidance(activePlanRef(ctx)) + bindingSuffix(ctx.cwd, "stage:learn"));
    },
  });
}
