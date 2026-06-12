// P1.T5b — the warm `/land` door (turn-5 §7). The in-session twin of the Python cold door
// (`perk pr land`): a terminating tool + command that DELEGATE the GitHub merge (D1 — mutations
// canonical in Python), then set the `pending-learn` marker for the in-session path (the worker
// sets it too on the cold path; the marker is an idempotent existence-semaphore). Never throws.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "./bindingDelivery.ts";
import { PENDING_LEARN, setMarker } from "./cache.ts";
import {
  type ColdJson,
  nullableStringField,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "./coldDoor.ts";
import { reconcileGuidance } from "./objectivePlan.ts";
import { report } from "./report.ts";
import { failFor, ok, type Result } from "./result.ts";

// Learn-consume skip reasons that are ordinary, not failures (#102): non-factory plans carry no
// `consumed_learn` (`no_consumed_learn`), and a dry run reports `dry_run`. Anything else surfaces.
const BENIGN_LEARN_SKIPS = new Set(["no_consumed_learn", "dry_run"]);

export interface ObjectiveLandUpdate {
  /** Opaque string objective id (GitHub "5", Linear "ENG-5") — §8.21. */
  id: string | null;
  nodes_marked: string[];
  skipped_reason: string | null;
  closed: boolean;
}

export interface LearnConsumeUpdate {
  /** Opaque string learn-issue ids (§8.21). */
  closed: string[];
  skipped_reason: string | null;
}

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface LandOk {
  pr: { number: number; state: string };
  branch?: string;
  /** Opaque string plan-issue id (§8.21). */
  issue?: string;
  pending_learn: boolean;
  objective?: ObjectiveLandUpdate;
  learn?: LearnConsumeUpdate;
}

export type LandResult = Result<LandOk>;
export type LandDetails = LandResult["details"];

/** The decoded `perk pr land --json` payload — `LandOk` minus the warm-door-owned `pending_learn`. */
interface LandPayload {
  pr: { number: number; state: string };
  branch?: string;
  issue?: string;
  objective?: ObjectiveLandUpdate;
  learn?: LearnConsumeUpdate;
}

/** Validate the optional `objective` sub-object; malformed → undefined (advisory, never fatal). */
function decodeObjective(payload: ColdJson): ObjectiveLandUpdate | undefined {
  const obj = objectField(payload, "objective");
  if (obj === undefined) return undefined;
  const id = obj.id;
  if (typeof id !== "string" && id !== null) return undefined;
  const nodesMarked = obj.nodes_marked;
  if (!Array.isArray(nodesMarked) || !nodesMarked.every((n) => typeof n === "string")) {
    return undefined;
  }
  const skippedReason = nullableStringField(obj, "skipped_reason");
  if (skippedReason === undefined && obj.skipped_reason !== undefined) return undefined;
  // `closed` is an advisory display detail: decode leniently (missing/malformed → false) rather
  // than dropping the whole sub-object.
  return {
    id,
    nodes_marked: nodesMarked,
    skipped_reason: skippedReason ?? null,
    closed: obj.closed === true,
  };
}

/** Validate the optional `learn` sub-object; malformed → undefined (advisory, never fatal). */
function decodeLearn(payload: ColdJson): LearnConsumeUpdate | undefined {
  const learn = objectField(payload, "learn");
  if (learn === undefined) return undefined;
  const closed = learn.closed;
  if (!Array.isArray(closed) || !closed.every((n) => typeof n === "string")) return undefined;
  const skippedReason = nullableStringField(learn, "skipped_reason");
  if (skippedReason === undefined && learn.skipped_reason !== undefined) return undefined;
  return { closed, skipped_reason: skippedReason ?? null };
}

/**
 * Narrow the `perk pr land --json` success payload. Strict on `pr` (malformed → bad_output);
 * the optional `objective`/`learn` sub-objects are validated but dropped when malformed — the
 * merge already succeeded, so the success report must survive a malformed advisory field.
 */
function decodeLand(payload: ColdJson): LandPayload | null {
  const pr = objectField(payload, "pr");
  if (pr === undefined) return null;
  const number = numberField(pr, "number");
  const state = stringField(pr, "state");
  if (number === undefined || state === undefined) return null;
  return {
    pr: { number, state },
    branch: stringField(payload, "branch"),
    issue: stringField(payload, "issue"),
    objective: decodeObjective(payload),
    learn: decodeLearn(payload),
  };
}

/**
 * The single land implementation both surfaces call. Delegates the merge to the Python cold door,
 * then sets `pending-learn` (in-session path). Returns a soft result (never throws).
 */
export async function landPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<LandResult> {
  const fail = failFor(ctx, "land");

  const r = await runColdDoor<LandPayload>(pi, ctx, ["pr", "land", "--json"], {
    label: "perk pr land",
    decode: decodeLand,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Set the semaphore for the in-session path (idempotent; the worker also set it on disk).
  setMarker(ctx.cwd, PENDING_LEARN);

  const lines = [`Landed PR #${r.data.pr.number}; run /learn to release the worktree.`];
  const obj = r.data.objective;
  if (obj?.nodes_marked.length && obj.id !== null) {
    // The reconcile pass is auto-driven after land (see driveReconcileAfterLand); just report it.
    lines.push(
      `Objective #${obj.id} node(s) ${obj.nodes_marked.join(", ")} marked done — ` +
        `reconciling the roadmap against the merged diff.`,
    );
  }
  if (obj?.closed && obj.id !== null) {
    lines.push(`Objective #${obj.id} complete — closed.`);
  }
  const learn = r.data.learn;
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

  return ok(lines.join("\n"), { ...r.data, pending_learn: true }, { terminate: true });
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
  if (!details.ok) return;
  const obj = details.objective;
  if (!obj || obj.id === null || obj.nodes_marked.length === 0) return;
  const message = reconcileGuidance(obj.id) + bindingSuffix(ctx.cwd, "command:objective-reconcile");
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
      // Failure already reported loudly via failFor (the single error surface) — success only.
      if (result.details.ok) {
        report(ctx, "land", "info", result.content[0]?.text ?? "land done");
      }
      driveReconcileAfterLand(pi, ctx, result.details);
    },
  });
}
