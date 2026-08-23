// The warm `/submit` door. The in-session twin of the Python cold door
// (`perk pr submit`): a deterministic, terminating tool + command that DELEGATE the GitHub write —
// they do NOT reimplement it (GitHub mutations are canonical in the Python gateway). Mirrors
// `planSave.ts`: write nothing, delegate to `perk pr submit --json` via `pi.exec`, surface the
// structured result, never throw (failures are loud-but-non-fatal via `details.ok = false`).
//
// Mergeability gate: `perk pr submit` probes the PR's mergeability against the base branch
// (a deterministic local `git merge-tree` probe). When it reports a definitively-unmergeable PR
// (`mergeable === false` + conflicts), the warm door drives a fresh-context, write-capable
// `perk.conflict-resolver` subagent (mirroring `/pr-review`'s dispatch and `/land`'s reconcile
// drive) to rebase + resolve + push, then asks the model to re-`/submit` to confirm. Bounded by
// `CONFLICT_RESOLUTION_ATTEMPT_CAP` via the `conflict_resolution_attempts` workflow-state field.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { subagentModel } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, type OkDetails, ok, type Result } from "../substrate/result.ts";
import { captureSessionPointer } from "../substrate/sessionPointers.ts";
import { appendWorkflowState, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";
import { planningStageRefusal } from "./lifecycleGates.ts";

/** The bounded conflict-resolution re-drive cap: drive the resolver at most this many times. */
export const CONFLICT_RESOLUTION_ATTEMPT_CAP = 2;

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface SubmitOk {
  pr: { number: number; url: string; is_draft: boolean; existed: boolean };
  branch?: string;
  issue?: number;
  plan_embedded?: boolean;
  /** The target branch the PR merges into (the conflict-resolver rebases onto it). */
  base?: string;
  /** Tri-state mergeability from the Python `git merge-tree` probe: true/false/null/absent. */
  mergeable?: boolean | null;
  /** The conflicted paths when `mergeable === false`; `[]` otherwise (advisory). */
  conflicts?: string[];
  /** `"stacked"` when the submit routed through the delivery publish operation (§8.47). */
  delivery?: string;
  /** The native-stack facts of a stacked submit (absent for the bottom layer). */
  stack?: { number: number; size: number; position: number };
  /** Lenient summary of an automatic suffix synchronization. */
  operation?: {
    kind: string;
    operation_id: string | null;
    no_op: boolean;
    affected_count: number;
    notes: string[];
  };
}

export type SubmitResult = Result<SubmitOk>;
export type SubmitDetails = SubmitResult["details"];

/**
 * A tri-state read of the advisory `mergeable` field: `true`/`false`/`null` pass through;
 * anything else (absent, mistyped) → `undefined`. Kept lenient so a malformed value never sinks
 * an otherwise-successful submit decode.
 */
function mergeableField(payload: ColdJson): boolean | null | undefined {
  const value = payload.mergeable;
  if (value === true || value === false || value === null) return value;
  return undefined;
}

/** A lenient string-array read for the advisory `conflicts` field; malformed → `[]`. */
function conflictsField(payload: ColdJson): string[] {
  const value = payload.conflicts;
  if (Array.isArray(value) && value.every((p) => typeof p === "string")) return value as string[];
  return [];
}

/**
 * A lenient read of the advisory stacked `stack` facts: all three numbers or nothing — a
 * malformed value must NOT sink a successful submit decode (it just drops the suffix).
 */
function stackField(payload: ColdJson): SubmitOk["stack"] {
  const value = objectField(payload, "stack");
  if (value === undefined) return undefined;
  const number = numberField(value, "number");
  const size = numberField(value, "size");
  const position = numberField(value, "position");
  if (number === undefined || size === undefined || position === undefined) return undefined;
  return { number, size, position };
}

/**
 * Lenient all-or-nothing decode of the cascade operation block. The full affected rows remain a
 * Python/CLI detail; the warm door needs only their count plus the recovery notes.
 */
function operationField(payload: ColdJson): SubmitOk["operation"] {
  const value = objectField(payload, "operation");
  if (value === undefined) return undefined;
  const kind = stringField(value, "kind");
  const operationId = value.operation_id;
  const noOp = booleanField(value, "no_op");
  const affected = value.affected;
  const notes = value.notes;
  if (
    kind === undefined ||
    (typeof operationId !== "string" && operationId !== null) ||
    noOp === undefined ||
    !Array.isArray(affected) ||
    !Array.isArray(notes) ||
    !notes.every((note) => typeof note === "string")
  ) {
    return undefined;
  }
  return {
    kind,
    operation_id: operationId,
    no_op: noOp,
    affected_count: affected.length,
    notes: notes as string[],
  };
}

/**
 * Narrow the `perk pr submit --json` success payload; strict on `pr`, lenient on the rest. The
 * `base`/`mergeable`/`conflicts` mergeability fields are advisory (mirror land.ts's lenient
 * sub-fields): a malformed value must NOT make a successful submit decode to `null`.
 */
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
    base: stringField(payload, "base"),
    mergeable: mergeableField(payload),
    conflicts: conflictsField(payload),
    delivery: stringField(payload, "delivery"),
    stack: stackField(payload),
    operation: operationField(payload),
  };
}

/** A definitively-unmergeable submit; parsed conflict paths are advisory only. */
function isUnmergeable(details: SubmitDetails): details is OkDetails<SubmitOk> {
  return details.ok && details.mergeable === false;
}

/**
 * The single submit implementation both surfaces call. Delegates to the Python cold door; returns a
 * soft result (never throws) — failures set `details.ok = false`. On a clean submit
 * (`mergeable !== false`) it resets the bounded conflict-resolution counter so a later independent
 * conflict starts fresh; on conflicts the success message reflects the in-flight resolution.
 */
export async function submitPr(pi: ExtensionAPI, ctx: ExtensionContext): Promise<SubmitResult> {
  const fail = failFor(ctx, "submit");

  // Planning sessions never legitimately submit — the first check, before any cold-door
  // delegation (a positioned stacked planning session's cwd binding is the PREDECESSOR).
  const planningRefusal = planningStageRefusal(ctx, "submit");
  if (planningRefusal !== null) return fail(planningRefusal, "planning_session");

  // Stamp this implement run id into the plan-header `impl_run_ids` linkage (contracts.md
  // §8.35) so a later/other session can resolve the implement session pointers cross-run.
  // Mirrors planSave's `--run-id` thread; covers the interactive /submit AND the headless worker
  // drive (both flow through this warm door). Absent run_id ⇒ omit (bare-stamp untouched).
  const runId = rebuildWorkflowState(branchOf(ctx)).run_id ?? "";
  const args = ["pr", "submit", "--json"];
  if (runId) args.push("--run-id", runId);
  const r = await runColdDoor<SubmitOk>(pi, ctx, args, {
    label: "perk pr submit",
    decode: decodeSubmit,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Capture `implementation/main` at the moment the run id enters `impl_run_ids` (contracts.md
  // §8.35): any run id stamped into the linkage gets its pointer captured in the same gesture.
  // This covers address/warm sessions that submit — which the stage-gated `session_start` capture
  // never sees — so a submitted run resolves `found` instead of `missing`. For the implement
  // session's own /submit it is an idempotent same-session refresh; `preserveForeign` guarantees
  // it can never clobber a different session's pointer. Best-effort + non-fatal like every
  // capture site (a successful submit must stand).
  if (runId) {
    captureSessionPointer({
      cwd: ctx.cwd,
      runId,
      klass: "implementation",
      site: "main",
      // Optional-chained: best-effort, and some side-session fakes have no getSessionFile.
      sessionFile: ctx.sessionManager.getSessionFile?.(),
      preserveForeign: true,
    });
  }

  const verb = r.data.pr.existed ? "Found existing" : "Opened draft";
  const conflicted = r.data.mergeable === false;
  // Reset the counter on every clean (or undetermined) submit — idempotent; keeps a later
  // independent conflict bounded fresh.
  if (r.data.mergeable !== false) resetConflictAttempts(pi, ctx);
  // Automatic-cascade facts supersede the generic stacked suffix. A malformed operation block was
  // dropped by the lenient decoder, so it falls back to the pre-existing stack wording.
  const deliverySuffix =
    r.data.operation?.kind === "sync"
      ? r.data.operation.no_op
        ? " (suffix already in sync)"
        : ` (cascaded ${r.data.operation.affected_count} layer(s))`
      : r.data.stack
        ? ` (stack #${r.data.stack.number}, layer ${r.data.stack.position}/${r.data.stack.size})`
        : r.data.delivery === "stacked"
          ? " (stacked layer)"
          : "";
  for (const note of r.data.operation?.notes ?? []) {
    report(ctx, "submit", "warning", note);
  }
  const message = conflicted
    ? `${verb} PR #${r.data.pr.number} → ${r.data.pr.url} — merge conflicts detected; resolving${deliverySuffix}`
    : `${verb} PR #${r.data.pr.number} → ${r.data.pr.url} (${
        r.data.plan_embedded ? "plan embedded" : "no plan embed"
      })${deliverySuffix}`;
  return ok(message, r.data, { terminate: true });
}

/** Reset `conflict_resolution_attempts` to 0 (idempotent: a no-op when already 0/absent). */
function resetConflictAttempts(pi: ExtensionAPI, ctx: ExtensionContext): void {
  const attempts = rebuildWorkflowState(branchOf(ctx)).conflict_resolution_attempts ?? 0;
  if (attempts === 0) return;
  appendWorkflowState(pi, ctx, {
    data: { conflict_resolution_attempts: 0 },
    field: "conflict_resolution_attempts",
    expected: 0,
    scope: "submit",
    failure: "conflict_resolution_attempts reset read-back failed (expected 0)",
  });
}

/**
 * The follow-up guidance the warm `/submit` injects to dispatch the conflict-resolver (modeled on
 * `prReviewGuidance`). Pure + exported for offline tests. When `model` is set, the ONE
 * workflowScript call carries a workflow-level `model` default; otherwise the agent's default
 * model is used.
 */
export function conflictResolutionGuidance(
  base: string,
  attempt: number,
  cap: number,
  model?: string,
): string {
  return render("stages/conflict-resolution.md", {
    base,
    attempt: String(attempt),
    cap: String(cap),
    model: model ?? "",
  });
}

/**
 * After a submit that opened a PR with detected merge conflicts, drive the session into the
 * conflict-resolution pass by injecting `conflictResolutionGuidance` (warm-door driving pattern,
 * modeled on `driveReconcileAfterLand`). The terminating `submit` tool stays terminating — a
 * `followUp` user message is a separate deliberate new turn. Short-circuits (sends nothing) unless
 * the submit succeeded with a definitively-unmergeable PR. Bounded by
 * `CONFLICT_RESOLUTION_ATTEMPT_CAP` via the `conflict_resolution_attempts` field: past the cap it
 * surfaces the unresolved conflict loudly instead of looping.
 */
export function driveConflictResolution(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  details: SubmitDetails,
): void {
  if (!isUnmergeable(details)) return;
  const base = details.base ?? "";
  const attempts = rebuildWorkflowState(branchOf(ctx)).conflict_resolution_attempts ?? 0;
  if (attempts >= CONFLICT_RESOLUTION_ATTEMPT_CAP) {
    report(
      ctx,
      "submit",
      "error",
      `merge conflicts persist after ${attempts} resolution attempt(s) — resolve manually ` +
        `(rebase onto \`${base}\` and push), then re-run /submit.`,
      { alsoLog: true },
    );
    return;
  }
  const next = attempts + 1;
  appendWorkflowState(pi, ctx, {
    data: { conflict_resolution_attempts: next },
    field: "conflict_resolution_attempts",
    expected: next,
    scope: "submit",
    failure: `conflict_resolution_attempts read-back failed (expected ${next})`,
  });
  const model = subagentModel(ctx.cwd, "conflict-resolver");
  const message =
    conflictResolutionGuidance(base, next, CONFLICT_RESOLUTION_ATTEMPT_CAP, model) +
    bindingSuffix(ctx.cwd, "command:submit");
  if (ctx.isIdle()) {
    // The `/submit` command path (idle): inject an immediate turn.
    pi.sendUserMessage(message);
  } else {
    // The `submit` tool path (streaming): deliver after the terminating submit batch.
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
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
      const result = await submitPr(pi, ctx);
      driveConflictResolution(pi, ctx, result.details);
      return result;
    },
  });

  registerPerkCommand(pi, "submit", {
    description: "Push the branch and open a draft PR for the active plan (implement → submit).",
    handler: async (_args, ctx) => {
      const result = await submitPr(pi, ctx);
      // Failure already reported loudly via failFor (the single error surface) — success only.
      if (result.details.ok) {
        report(ctx, "submit", "info", result.content[0]?.text ?? "submit done");
      }
      driveConflictResolution(pi, ctx, result.details);
    },
  });
}
