// The change-publication bindings: the `submit` terminating tool (canonical) + the `/submit`
// command twin, adapting the Pi-free publish operation in `delivery/submit.ts`. The in-session
// twin of the Python cold door (`perk pr submit`): a deterministic, terminating surface that
// DELEGATES the GitHub write — it does NOT reimplement it (GitHub mutations are canonical in
// the Python gateway). Write nothing, delegate to `perk pr submit --json` via the cold-door
// seam, surface the structured result, never throw (failures are loud-but-non-fatal via
// `details.ok = false`).
//
// Mergeability gate: `perk pr submit` probes the PR's mergeability against the base branch
// (a deterministic local `git merge-tree` probe). When it reports a definitively-unmergeable PR
// (`mergeable === false` + conflicts), the feature op decides the bounded follow-up
// (`decideConflictFollowUp`) and this adapter TRANSLATES it (`driveConflictFollowUp`): a
// fresh-context, write-capable `perk.conflict-resolver` subagent rebases + resolves + pushes,
// then the model re-`/submit`s to confirm. The wire vocabulary (`decodeSubmit` + sub-decoders),
// the message render, and the guidance render all live here.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  type ConflictAttempts,
  type ConflictFollowUp,
  type PublishChange,
  type PublishDeps,
  type PublishedChange,
  type SubmitChangeOutcome,
  submitChange,
} from "../../../delivery/submit.ts";
import { planningStageRefusal } from "../../../doors/lifecycleGates.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { subagentModel } from "../../../substrate/config.ts";
import { render } from "../../../substrate/prompts.ts";
import { failFor, ok } from "../../../substrate/result.ts";
import { captureSessionPointer } from "../../../substrate/sessionPointers.ts";
import {
  branchOf,
  conflictResolutionAttempts,
  rebuildWorkflowState,
  setConflictAttempts,
} from "../../../substrate/workflowState.ts";
import { report } from "../../../surfaces/report.ts";

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
function stackField(payload: ColdJson): PublishedChange["stack"] {
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
 * Python/CLI detail; the warm surface needs only their count plus the recovery notes.
 */
function operationField(payload: ColdJson): PublishedChange["operation"] {
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
 * sub-fields): a malformed value must NOT make a successful submit decode to `null`. `issue` is
 * the opaque string id the Python boundary sends (`PrSubmitOut.issue: str`, contracts §8.21).
 */
function decodeSubmit(payload: ColdJson): PublishedChange | null {
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
    issue: stringField(payload, "issue"),
    plan_embedded: booleanField(payload, "plan_embedded"),
    base: stringField(payload, "base"),
    mergeable: mergeableField(payload),
    conflicts: conflictsField(payload),
    delivery: stringField(payload, "delivery"),
    stack: stackField(payload),
    operation: operationField(payload),
  };
}

/**
 * The ONE production `PublishChange` adapter: `perk pr submit --json` through the cold-door
 * seam. On decode success it ALSO reports each `operation.notes` row as a scope-"submit"
 * warning (today's timing: after publish success, before anything downstream — including before
 * resolve on the address path). It reports NOTHING on failure — the callers own failure
 * loudness, keeping the standalone submit path single-report. Module-private: every production
 * consumer composes through `publishDepsFor` (the one-composition invariant is structural).
 */
function createChangePublisher(pi: ExtensionAPI, ctx: ExtensionContext): PublishChange {
  return async ({ runId }) => {
    const args = ["pr", "submit", "--json"];
    if (runId !== null) args.push("--run-id", runId);
    const r = await runColdDoor<PublishedChange>(pi, ctx, args, {
      label: "perk pr submit",
      decode: decodeSubmit,
    });
    if (!r.ok) return { ok: false, message: r.message, errorType: r.errorType };
    for (const note of r.data.operation?.notes ?? []) {
      report(ctx, "submit", "warning", note);
    }
    return { ok: true, change: r.data };
  };
}

/** The shared-counter capability over the checked substrate seam (scope "submit" — the true
 * writing surface for both submit-surface writers). `ctx` IS the `BranchSource`.
 * Module-private: consumed only through `publishDepsFor`. */
function conflictAttemptsFor(pi: ExtensionAPI, ctx: ExtensionContext): ConflictAttempts {
  return {
    read: () => conflictResolutionAttempts(ctx),
    write: (next) => setConflictAttempts(pi, ctx, { attempts: next, scope: "submit" }),
  };
}

/**
 * The one production `PublishDeps` composition (the address installer extends it — the
 * one-production-adapter invariant is structural). The run id rides the DIRECT throwing read
 * (`rebuildWorkflowState(branchOf(ctx)).run_id ?? ""` — deliberately NOT `activeSessionRunId`,
 * which catches and would silently drop the stamp), invoked lazily at publish time so a
 * throwing branch read still fails BEFORE the external call while the finalize empty-batch
 * refusal keeps firing first (the pre-migration order). Stamping the id into the plan-header
 * `impl_run_ids` linkage (contracts §8.35) mirrors planSave's `--run-id` thread; absent run_id
 * ⇒ omit (bare-stamp untouched).
 */
export function publishDepsFor(pi: ExtensionAPI, ctx: ExtensionContext): PublishDeps {
  return {
    publish: createChangePublisher(pi, ctx),
    readRunId: () => {
      const runId = rebuildWorkflowState(branchOf(ctx)).run_id ?? "";
      return runId === "" ? null : runId;
    },
    // Capture `implementation/main` at the moment the run id enters `impl_run_ids` (contracts
    // §8.35): any run id stamped into the linkage gets its pointer captured in the same
    // gesture. This covers address/warm sessions that submit — which the stage-gated
    // session_start capture never sees — so a submitted run resolves `found` instead of
    // `missing`. For the implement session's own /submit it is an idempotent same-session
    // refresh; `preserveForeign` guarantees it can never clobber a different session's pointer.
    // Best-effort + non-fatal like every capture site (a successful submit must stand) — the
    // never-throws capability contract.
    recordImplementationPointer: (runId) => {
      captureSessionPointer({
        cwd: ctx.cwd,
        runId,
        klass: "implementation",
        site: "main",
        // Optional-chained: best-effort, and some side-session fakes have no getSessionFile.
        sessionFile: ctx.sessionManager.getSessionFile?.(),
        preserveForeign: true,
      });
    },
    attempts: conflictAttemptsFor(pi, ctx),
  };
}

/**
 * Render the published-change success message (pure): verb + conflicted/clean + the delivery
 * suffix. Automatic-cascade facts supersede the generic stacked suffix; a malformed operation
 * block was dropped by the lenient decoder, so it falls back to the pre-existing stack wording.
 */
export function renderPublishedMessage(change: PublishedChange): string {
  const verb = change.pr.existed ? "Found existing" : "Opened draft";
  const deliverySuffix =
    change.operation?.kind === "sync"
      ? change.operation.no_op
        ? " (suffix already in sync)"
        : ` (cascaded ${change.operation.affected_count} layer(s))`
      : change.stack
        ? ` (stack #${change.stack.number}, layer ${change.stack.position}/${change.stack.size})`
        : change.delivery === "stacked"
          ? " (stacked layer)"
          : "";
  return change.mergeable === false
    ? `${verb} PR #${change.pr.number} → ${change.pr.url} — merge conflicts detected; resolving${deliverySuffix}`
    : `${verb} PR #${change.pr.number} → ${change.pr.url} (${
        change.plan_embedded ? "plan embedded" : "no plan embed"
      })${deliverySuffix}`;
}

/**
 * The follow-up guidance the warm `/submit` injects to dispatch the conflict-resolver (modeled
 * on `prReviewGuidance`). Pure + exported for offline tests. `worktree` is the plan worktree the
 * child's task text pins with a concrete `cd <worktree>` command — a dispatched child otherwise
 * has no cwd guarantee and can run its commands outside the plan worktree. When `model` is set,
 * the ONE workflowScript call carries a workflow-level `model` default; otherwise the agent's
 * default model is used.
 */
export function conflictResolutionGuidance(
  base: string,
  attempt: number,
  cap: number,
  worktree: string,
  model?: string,
): string {
  return render("stages/conflict-resolution.md", {
    base,
    attempt: String(attempt),
    cap: String(cap),
    worktree,
    model: model ?? "",
  });
}

/**
 * Translate the feature op's bounded conflict decision into the warm-door driving pattern:
 * `none` ⇒ nothing; `exhausted` ⇒ the loud at-cap report (surface the unresolved conflict
 * instead of looping); `withheld` ⇒ the loud unpersisted-increment report (an unverifiable
 * counter must never bypass the cap — NO injection); `drive` ⇒ inject the rendered guidance.
 * Scope "submit" for every arm — both consumers (submit AND address) report through it, parity
 * with the shared `exhausted` wording. The terminating `submit` tool stays terminating — a
 * `followUp` user message is a separate deliberate new turn.
 */
export function driveConflictFollowUp(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  followUp: ConflictFollowUp,
): void {
  if (followUp.kind === "none") return;
  if (followUp.kind === "exhausted") {
    report(
      ctx,
      "submit",
      "error",
      `merge conflicts persist after ${followUp.attempts} resolution attempt(s) — resolve manually ` +
        `(rebase onto \`${followUp.base}\` and push), then re-run /submit.`,
      { alsoLog: true },
    );
    return;
  }
  if (followUp.kind === "withheld") {
    report(
      ctx,
      "submit",
      "error",
      "conflict-resolution dispatch withheld — the attempt counter could not be persisted (an " +
        "unverifiable counter must never bypass the cap); resolve manually (rebase onto " +
        `\`${followUp.base}\` and push), then re-run /submit.`,
      { alsoLog: true },
    );
    return;
  }
  const model = subagentModel(ctx.cwd, "conflict-resolver");
  const message =
    // `/submit` runs only in worktree-bound sessions (planning sessions are refused first), so
    // the session cwd IS the plan worktree.
    conflictResolutionGuidance(followUp.base, followUp.attempt, followUp.cap, ctx.cwd, model) +
    bindingSuffix(ctx.cwd, "command:submit");
  if (ctx.isIdle()) {
    // The `/submit` command path (idle): inject an immediate turn.
    pi.sendUserMessage(message);
  } else {
    // The `submit` tool path (streaming): deliver after the terminating submit batch.
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

/** The refusal-or-outcome the two surfaces translate (drive translation stays per surface). */
type SubmitSurfaceOutcome = { kind: "refused"; message: string } | SubmitChangeOutcome;

/**
 * The shared surface core: planning refusal first (a positioned stacked planning session's cwd
 * binding is the PREDECESSOR — planning sessions never legitimately submit), then the feature
 * op over the production deps.
 */
async function performSubmit(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
): Promise<SubmitSurfaceOutcome> {
  const planningRefusal = planningStageRefusal(ctx, "submit");
  if (planningRefusal !== null) return { kind: "refused", message: planningRefusal };
  return submitChange(publishDepsFor(pi, ctx));
}

const TOOL_GUIDELINES = [
  "Call submit only after the implementation is committed in this worktree; it pushes the branch and opens the draft PR, then ends the turn.",
  "submit operates on the active plan's worktree — it takes no arguments; the branch and plan come from the local plan-ref.",
];

/** Install the change-publication bindings: the `submit` terminating tool (canonical) + the
 * `/submit` command twin. */
export function installSubmitBindings(pi: ExtensionAPI): void {
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
      const fail = failFor(ctx, "submit");
      const outcome = await performSubmit(pi, ctx);
      if (outcome.kind === "refused") return fail(outcome.message, "planning_session");
      if (outcome.kind === "publish_failed") return fail(outcome.message, outcome.errorType);
      const result = ok(renderPublishedMessage(outcome.change), outcome.change, {
        terminate: true,
      });
      driveConflictFollowUp(pi, ctx, outcome.conflict);
      return result;
    },
  });

  registerPerkCommand(pi, "submit", {
    description: "Push the branch and open a draft PR for the active plan (implement → submit).",
    handler: async (_args, ctx) => {
      const fail = failFor(ctx, "submit");
      const outcome = await performSubmit(pi, ctx);
      // Failure is reported loudly via failFor (the single error surface) — success only.
      if (outcome.kind === "refused") {
        fail(outcome.message, "planning_session");
        return;
      }
      if (outcome.kind === "publish_failed") {
        fail(outcome.message, outcome.errorType);
        return;
      }
      // Report-before-drive (load-bearing order): the success line lands before the injected
      // conflict-resolution turn.
      report(ctx, "submit", "info", renderPublishedMessage(outcome.change));
      driveConflictFollowUp(pi, ctx, outcome.conflict);
    },
  });
}
