// The per-plan landing bindings: the terminating `land` tool + the `/land` command, the
// in-session twin of the Python cold door (`perk pr land`). A deliberately ZERO-POLICY adapter
// slice (the stack-status precedent — no feature operation backs it): the tool DELEGATES the
// GitHub merge (mutations canonical in Python), then mirrors the envelope's `pending_learn` for
// the in-session path — setting the `pending-learn` marker (an idempotent existence-semaphore;
// the worker sets it too on the cold path) unless the cold door reports the learn-docs
// exemption (`pending_learn: false` — no marker, no /learn nudge). Never throws; a verified
// land result survives every advisory failure (marker writes, malformed sub-objects) as a loud
// warning line, never a post-merge rejection.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { reconcileGuidance } from "../../../authoring/objective/prose.ts";
import { planningStageRefusal } from "../../../session/lifecycleGates.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import { PENDING_LEARN, setMarker } from "../../../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  nullableStringField,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { failFor, ok, type Result } from "../../../substrate/result.ts";
import { report } from "../../../surfaces/report.ts";

// Learn-consume skip reasons that are ordinary, not failures: non-factory plans carry no
// `consumed_learn` (`no_consumed_learn`), and a dry run reports `dry_run`. Anything else surfaces.
const BENIGN_LEARN_SKIPS = new Set(["no_consumed_learn", "dry_run"]);

/** The marker-safe id vocabulary the reconcile drive requires of the objective id — the
 * interpolated guidance is a steering message rendering the id as an unquoted CLI argument,
 * so an out-of-vocabulary id never drives and an option-shaped `-`-leading id never passes
 * (alphanumeric-first). */
const OBJECTIVE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

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

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state.
 * `pending_learn` mirrors the cold envelope: `false` is the learn-docs exemption (no marker). */
interface LandOk {
  pr: { number: number; state: string };
  branch?: string;
  /** Opaque string plan-issue id (§8.21). */
  issue?: string;
  pending_learn: boolean;
  objective?: ObjectiveLandUpdate;
  learn?: LearnConsumeUpdate;
}

type LandResult = Result<LandOk>;
type LandDetails = LandResult["details"];

/** An optional advisory sub-object's three-state decode: absent is ordinary; malformed is
 * DISTINGUISHED (the merge already succeeded, so the success report survives — but the
 * unverified state is reported loudly, never silently dropped). */
type AdvisoryDecode<T> =
  | { state: "absent" }
  | { state: "malformed" }
  | { state: "present"; value: T };

/** The decoded `perk pr land --json` payload — the cold door owns `pending_learn` (the
 * learn-docs-exemption decision point); decoded leniently so skew degrades to legacy. */
interface LandPayload {
  pr: { number: number; state: string };
  branch?: string;
  issue?: string;
  pending_learn: boolean;
  objective: AdvisoryDecode<ObjectiveLandUpdate>;
  learn: AdvisoryDecode<LearnConsumeUpdate>;
}

/** Validate the optional `objective` sub-object — three-state (absent/malformed/present). */
function decodeObjective(payload: ColdJson): AdvisoryDecode<ObjectiveLandUpdate> {
  if (payload.objective === undefined) return { state: "absent" };
  const obj = objectField(payload, "objective");
  if (obj === undefined) return { state: "malformed" };
  const id = obj.id;
  if (typeof id !== "string" && id !== null) return { state: "malformed" };
  const nodesMarked = obj.nodes_marked;
  if (!Array.isArray(nodesMarked) || !nodesMarked.every((n) => typeof n === "string")) {
    return { state: "malformed" };
  }
  const skippedReason = nullableStringField(obj, "skipped_reason");
  if (skippedReason === undefined && obj.skipped_reason !== undefined) {
    return { state: "malformed" };
  }
  // `closed` is an advisory display detail: decode leniently (missing/malformed → false) rather
  // than dropping the whole sub-object.
  return {
    state: "present",
    value: {
      id,
      nodes_marked: nodesMarked,
      skipped_reason: skippedReason ?? null,
      closed: obj.closed === true,
    },
  };
}

/** Validate the optional `learn` sub-object — three-state (absent/malformed/present). */
function decodeLearn(payload: ColdJson): AdvisoryDecode<LearnConsumeUpdate> {
  if (payload.learn === undefined) return { state: "absent" };
  const learn = objectField(payload, "learn");
  if (learn === undefined) return { state: "malformed" };
  const closed = learn.closed;
  if (!Array.isArray(closed) || !closed.every((n) => typeof n === "string")) {
    return { state: "malformed" };
  }
  const skippedReason = nullableStringField(learn, "skipped_reason");
  if (skippedReason === undefined && learn.skipped_reason !== undefined) {
    return { state: "malformed" };
  }
  return { state: "present", value: { closed, skipped_reason: skippedReason ?? null } };
}

/**
 * Narrow the `perk pr land --json` success payload. Strict on `pr` (malformed → bad_output);
 * the optional `objective`/`learn` sub-objects decode three-state — a malformed advisory field
 * is dropped from the details (the merge already succeeded, so the success report must
 * survive it) but reported as an UNVERIFIED-state warning line, never silently.
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
    // Lenient: a missing/mistyped `pending_learn` (an older cold CLI under version skew)
    // defaults to the legacy behavior (marker + /learn nudge) — never a silently-unreleased
    // marker with no visible nudge.
    pending_learn: booleanField(payload, "pending_learn") ?? true,
    objective: decodeObjective(payload),
    learn: decodeLearn(payload),
  };
}

/** The malformed-advisory warning line (the `<objective|learn>` slots are the report name and
 * its unverified-state name). */
function malformedAdvisoryWarning(field: "objective" | "learn"): string {
  const stateName = field === "objective" ? "objective reconcile" : "learn";
  return (
    `Warning: the land envelope's ${field} report was malformed — ${stateName} state ` +
    "UNVERIFIED; inspect the objective (or run /objective-reconcile) manually."
  );
}

/**
 * The single land implementation both surfaces call. Delegates the merge to the Python cold
 * door, then mirrors the envelope's `pending_learn` (in-session path): marker + /learn nudge on
 * the ordinary arm; no marker, no nudge on the learn-docs exemption. A marker WRITE failure is
 * loud-not-fatal: the merge is already verified, so the success result (and the reconcile
 * drive) survive with a warning line naming the /learn remediation. Returns a soft result
 * (never throws).
 */
async function landPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<LandResult> {
  const fail = failFor(ctx, "land");

  // Planning sessions never legitimately land — the first check, before any cold-door
  // delegation (a positioned stacked planning session's cwd binding is the PREDECESSOR).
  const planningRefusal = planningStageRefusal(ctx, "land");
  if (planningRefusal !== null) return fail(planningRefusal, "planning_session");

  const r = await runColdDoor<LandPayload>(pi, ctx, ["pr", "land", "--json"], {
    label: "perk pr land",
    decode: decodeLand,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  const lines = [
    r.data.pending_learn
      ? `Landed PR #${r.data.pr.number}; run /learn to release the worktree.`
      : `Landed PR #${r.data.pr.number}; learn-docs plan — no learn pass needed; the worktree is releasable.`,
  ];
  if (r.data.pending_learn) {
    // Set the semaphore for the in-session path (idempotent; the cold door also set it on
    // disk). Guarded: a filesystem failure must never erase a VERIFIED land result — the
    // success report + reconcile drive survive, with the /learn remediation named loudly.
    try {
      setMarker(ctx.cwd, PENDING_LEARN);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      lines.push(
        `Warning: the pending-learn marker could not be written (${detail}); run /learn ` +
          "before releasing the worktree.",
      );
    }
  }
  const obj = r.data.objective.state === "present" ? r.data.objective.value : undefined;
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
  const learn = r.data.learn.state === "present" ? r.data.learn.value : undefined;
  if (learn?.closed.length) {
    // hop-2: the consumed perk:learn issues were closed + labelled perk:consolidated on land.
    lines.push(
      `Closed ${learn.closed.length} learn issue(s) (${learn.closed
        .map((n) => `#${n}`)
        .join(", ")}) into docs/learned.`,
    );
  }
  // Surface a non-benign learn-consume skip: `no_consumed_learn` is the ordinary
  // non-factory case, so stay quiet on it; a real failure must be visible, not silent.
  if (learn?.skipped_reason && !BENIGN_LEARN_SKIPS.has(learn.skipped_reason)) {
    lines.push(`Warning: learn consume incomplete — ${learn.skipped_reason}.`);
  }
  // A malformed advisory sub-object leaves the merge verified but its state UNKNOWN: the
  // details omit the field (as before) and the drive stays suppressed, but the miss is loud.
  if (r.data.objective.state === "malformed") lines.push(malformedAdvisoryWarning("objective"));
  if (r.data.learn.state === "malformed") lines.push(malformedAdvisoryWarning("learn"));

  const details: LandOk = {
    pr: r.data.pr,
    branch: r.data.branch,
    issue: r.data.issue,
    pending_learn: r.data.pending_learn,
    objective: obj,
    learn: learn,
  };
  return ok(lines.join("\n"), details, { terminate: true });
}

/**
 * After a successful land that marked at least one objective node done, drive the session into
 * the reconcile pass by injecting the exact guidance `/objective-reconcile` injects (warm-door
 * driving pattern). The terminating `land` tool stays terminating — terminate only skips the
 * *automatic* follow-up LLM call, while a `followUp` user message is a separate deliberate new
 * turn. Short-circuits (sends nothing) unless the land succeeded with an objective node marked
 * done AND the id passes the marker-safe vocabulary — the id is interpolated into a steering
 * message, so a poisoned envelope id never drives. Exported for the offline suite (the
 * streaming `followUp` branch is unreachable through the idle harness).
 */
export function driveReconcileAfterLand(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  details: LandDetails,
): void {
  if (!details.ok) return;
  const obj = details.objective;
  if (!obj || obj.id === null || obj.nodes_marked.length === 0) return;
  if (!OBJECTIVE_ID_RE.test(obj.id)) return;
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
  "land refuses a stacked-delivery plan (`delivery_lineage`): stacked layers land as one atomic train, never individually.",
];

/** Install the per-plan landing bindings: the `land` terminating tool + the `/land` command
 * twin. */
export function installLandBindings(pi: ExtensionAPI): void {
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

  registerPerkCommand(pi, "land", {
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
