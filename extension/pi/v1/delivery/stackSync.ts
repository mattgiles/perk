// The stacked-delivery sync bindings (contracts.md §8.49/§8.51): the `objective_stack_sync` +
// `objective_stack_adopt` typed tools and the `/objective-sync` driving command over the Python
// cold worker `perk objective stack sync` (mutations canonical in Python). Pure decoding,
// rendering, argv building, process invocation, refusal shapes, and injection — the warm
// conflict DECISIONS (corroboration, the bounded dispatch pipeline, the episode reset) live in
// `delivery/stackConflict.ts`; this adapter composes their production ports and translates the
// typed outcomes.
//
// The §8.51 sync conflict drive rides here: a mutating sync/continue refusing `rebase_conflict`
// auto-dispatches the `perk.conflict-resolver` subagent into the retained continuation worktree
// (`objective_stack_sync { resolve: true }` is the explicit-request twin). Adopt NEVER enters
// the dispatch pipeline — pinned at this adapter, not via a widened predicate.
//
// Objective inference everywhere: explicit param/argument → workflow `active_objective` →
// plan-ref `objective_id`; the warm layer always passes the resolved objective explicitly to
// the cold door. Warm consent: the plain sync/continue/abort calls pass `--yes` where they
// reach the cold door (the human's gesture/driven approval is the consent); adopt (mutating)
// additionally requires `confirm: true`. Cold-envelope decodes are lenient/render-only.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  autoDispatchEligible,
  decideSyncResolution,
  type SyncConflictDispatch,
  type SyncMode,
  type SyncResolutionOutcome,
  settleSyncEpisode,
} from "../../../delivery/stackConflict.ts";
import { STACK_NO_OBJECTIVE_MESSAGE } from "../../../delivery/stackObjective.ts";
import {
  CONFLICT_RESOLUTION_ATTEMPT_CAP,
  type ConflictAttempts,
} from "../../../delivery/submit.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectListField,
  runColdDoor,
  stringField,
  stringListField,
} from "../../../substrate/coldDoor.ts";
import { subagentModel } from "../../../substrate/config.ts";
import { render } from "../../../substrate/prompts.ts";
import { acquireResolverLease, releaseResolverClaim } from "../../../substrate/resolverLease.ts";
import { failFor, ok, type Result } from "../../../substrate/result.ts";
import type { ToolGating } from "../../../substrate/toolGating.ts";
import { booleanParam, idParam, paramsOf, stringParam } from "../../../substrate/toolParams.ts";
import {
  conflictResolutionAttempts,
  resolveStackObjective,
  setConflictAttempts,
} from "../../../substrate/workflowState.ts";
import { report } from "../../../surfaces/report.ts";
import { registerStackDrivingCommand } from "./stackDrive.ts";

/** Every stack tool returns the same slim ok-details: the resolved objective the cold door was
 * driven with (the envelope itself is render-only — nothing persisted). */
export type StackResult = Result<{ objective: string }>;

// --- the lenient sync render (the cold envelopes are render-only DATA) ---------------------------

function withSyncNotes(payload: ColdJson, text: string): string {
  const notes = stringListField(payload, "notes");
  return notes.length === 0 ? text : [text, ...notes.map((note) => `note: ${note}`)].join("\n");
}

/** Render the `stack sync --json` envelope for one invocation mode — fully lenient. */
export function renderSyncOutcome(payload: ColdJson, mode: SyncMode): string {
  if (booleanField(payload, "aborted") === true) {
    return withSyncNotes(payload, "retained continuation discarded");
  }
  if (booleanField(payload, "declined") === true) {
    if (mode === "abort")
      return withSyncNotes(payload, "abort declined; everything stays retained");
    if (mode === "continue") {
      return withSyncNotes(
        payload,
        "continuation declined; everything stays retained " +
          "(re-enter via objective_stack_sync { continue: true })",
      );
    }
    return withSyncNotes(payload, "cascade declined; nothing pushed");
  }
  const affected = objectListField(payload, "affected");
  const layerLines = affected.map(
    (layer) =>
      `  ${stringField(layer, "node_id") ?? "?"} ${stringField(layer, "branch") ?? "?"} ` +
      `(pr #${numberField(layer, "pr_number") ?? "?"}): ` +
      `${stringField(layer, "before_sha") ?? "?"} → ${stringField(layer, "after_sha") ?? "?"}`,
  );
  const adopted = stringField(payload, "adopted_node");
  if (booleanField(payload, "dry_run") === true) {
    if (booleanField(payload, "no_op") === true) {
      return withSyncNotes(payload, "dry run: nothing to synchronize");
    }
    const verb = adopted !== undefined ? "adopt + cascade" : "cascade";
    return withSyncNotes(
      payload,
      [
        `dry run: a real sync would ${verb} ${affected.length} layer(s)`,
        ...layerLines,
        "nothing was journaled, pushed, or retained",
      ].join("\n"),
    );
  }
  if (booleanField(payload, "no_op") === true) {
    const baseHint =
      booleanField(payload, "base_advanced") === true
        ? " (the base advanced — pass base: true to cascade onto it)"
        : "";
    return withSyncNotes(payload, `nothing to synchronize${baseHint}`);
  }
  const verb = booleanField(payload, "continued") === true ? "continued" : "synchronized";
  const suffix = adopted !== undefined ? ` (adopted node ${adopted})` : "";
  const lines = [`${verb} ${affected.length} layer(s)${suffix}`, ...layerLines];
  const operationId = stringField(payload, "operation_id");
  if (operationId !== undefined) lines.push(`operation ${operationId} complete`);
  return withSyncNotes(payload, lines.join("\n"));
}

/** The seed guidance the warm `/objective-sync` injects (preview → human approval → typed act).
 * Pure; the skill pointer rides the binding suffix, never hardcoded. */
export function objectiveSyncGuidance(objective: string): string {
  return render("stages/objective-sync.md", { objective });
}

/** Render the resolver dispatch (§8.57: the template is the canonical carrier of the dispatch
 * procedure AND the completed-only outcome gate — no other surface re-carries them). */
export function syncConflictResolutionGuidance(
  dispatch: SyncConflictDispatch,
  attempt: number,
  cap: number,
  model?: string,
): string {
  return render("stages/conflict-resolution-continuation.md", {
    objective: dispatch.objective,
    node: dispatch.node,
    branch: dispatch.branch,
    pr: String(dispatch.pr),
    worktree: dispatch.worktree,
    worktree_json: JSON.stringify(dispatch.worktree),
    attempt: String(attempt),
    cap: String(cap),
    model: model ?? "",
  });
}

// --- strict tool decodes + argv builders ----------------------------------------------------------

interface SyncToolParams {
  objective: string | undefined;
  base: boolean;
  dryRun: boolean;
  continue_: boolean;
  abort: boolean;
  /** The warm-only explicit resolver dispatch (§8.51) — never reaches the cold sync
   * mutation worker (its only cold call is the corroborating status re-read). */
  resolve: boolean;
}

/** Strict decode + the §8.49 mode matrix (same as the CLI's, plus the warm-only `resolve`,
 * which composes with NOTHING): null = refuse the whole call. */
function decodeSyncParams(params: unknown): SyncToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const base = booleanParam(p, "base");
  const dryRun = booleanParam(p, "dry_run");
  const continue_ = booleanParam(p, "continue");
  const abort = booleanParam(p, "abort");
  const resolve = booleanParam(p, "resolve");
  if (objective === null || base === null || dryRun === null || continue_ === null) return null;
  if (abort === null || resolve === null) return null;
  const decoded: SyncToolParams = {
    objective: objective ?? undefined,
    base: base ?? false,
    dryRun: dryRun ?? false,
    continue_: continue_ ?? false,
    abort: abort ?? false,
    resolve: resolve ?? false,
  };
  if (decoded.resolve && (decoded.base || decoded.dryRun || decoded.continue_ || decoded.abort)) {
    return null;
  }
  if (decoded.continue_ && decoded.abort) return null;
  if ((decoded.continue_ || decoded.abort) && (decoded.base || decoded.dryRun)) return null;
  return decoded;
}

/** The sync argv by mode: continue/abort take no cascade flags; `--yes` rides every mutating
 * path (warm consent — the human's gesture/driven approval); a dry run passes no `--yes`.
 * Never reached with `resolve` — the tool branches to the warm dispatcher first. */
export function buildStackSyncArgs(objective: string, p: SyncToolParams): string[] {
  const args = ["objective", "stack", "sync", objective];
  if (p.continue_) {
    args.push("--continue", "--yes");
  } else if (p.abort) {
    args.push("--abort", "--yes");
  } else {
    if (p.base) args.push("--base");
    if (p.dryRun) args.push("--dry-run");
    else args.push("--yes");
  }
  args.push("--json");
  return args;
}

interface AdoptToolParams {
  objective: string | undefined;
  node: string;
  dryRun: boolean;
  confirm: boolean;
}

function decodeAdoptParams(params: unknown): AdoptToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const node = stringParam(p, "node");
  const dryRun = booleanParam(p, "dry_run");
  const confirm = booleanParam(p, "confirm");
  if (objective === null || dryRun === null || confirm === null) return null;
  if (node === undefined || node === null || node.length === 0) return null;
  return {
    objective: objective ?? undefined,
    node,
    dryRun: dryRun ?? false,
    confirm: confirm ?? false,
  };
}

/** The adopt argv: `--adopt <node>` over the sync worker; dry-run previews, else `--yes`. */
export function buildStackAdoptArgs(objective: string, p: AdoptToolParams): string[] {
  const args = ["objective", "stack", "sync", objective, "--adopt", p.node];
  if (p.dryRun) args.push("--dry-run");
  else args.push("--yes");
  args.push("--json");
  return args;
}

// --- the production port compositions -------------------------------------------------------------

/** The shared-counter capability over the checked substrate seam (scope "objective-sync" — the
 * true writing surface for the stack-side writers; the counter itself is shared with the
 * submit/address drive, reset on any clean completion of either surface). */
function conflictAttemptsFor(pi: ExtensionAPI, ctx: ExtensionContext): ConflictAttempts {
  return {
    read: () => conflictResolutionAttempts(ctx),
    write: (next) => setConflictAttempts(pi, ctx, { attempts: next, scope: "objective-sync" }),
  };
}

/**
 * The one production dispatch composition: the corroborating `perk objective stack status
 * --json` re-read, the real resolver lease, and the checked counter — through the feature
 * pipeline (`decideSyncResolution`). On `dispatched` this adapter renders and injects the
 * resolver dispatch (§8.57's template + the configured `[models.subagents] conflict-resolver`
 * model + the binding suffix); translation of the refusal arms stays with each caller.
 * Exported for the offline suite (the streaming `followUp` arm is unreachable through the
 * idle harness — the exported-core precedent).
 */
export async function runSyncResolution(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  objective: string,
  refusalMessage: string | null,
): Promise<SyncResolutionOutcome> {
  const outcome = await decideSyncResolution(
    {
      readProjection: async () => {
        const r = await runColdDoor<ColdJson>(
          pi,
          ctx,
          ["objective", "stack", "status", objective, "--json"],
          { label: "perk objective stack status", decode: (payload) => payload },
        );
        return r.ok ? { ok: true, payload: r.data } : { ok: false, message: r.message };
      },
      claim: {
        acquire: (manifestPath, operationId) => acquireResolverLease(manifestPath, operationId),
        release: (manifestPath, token) => releaseResolverClaim(manifestPath, token),
      },
      attempts: conflictAttemptsFor(pi, ctx),
    },
    refusalMessage,
  );
  if (outcome.kind === "dispatched") {
    const model = subagentModel(ctx.cwd, "conflict-resolver");
    const message =
      syncConflictResolutionGuidance(outcome.dispatch, outcome.attempt, outcome.cap, model) +
      bindingSuffix(ctx.cwd, "command:objective-sync");
    if (ctx.isIdle()) {
      pi.sendUserMessage(message);
    } else {
      pi.sendUserMessage(message, { deliverAs: "followUp" });
    }
  }
  return outcome;
}

/** Settle the shared conflict budget after a clean cold completion; a failed reset is loud
 * (the counter may be stale) but never fatal to an already-verified completion. */
function settleEpisode(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  outcome: { mutating: boolean; declined: boolean },
): void {
  if (!settleSyncEpisode(conflictAttemptsFor(pi, ctx), outcome)) {
    report(
      ctx,
      "objective-sync",
      "warning",
      "conflict budget reset failed — the persisted counter may be stale (the seam's warning " +
        "names the details).",
    );
  }
}

// --- the tool implementations (delegate, render, never throw) -------------------------------------

async function stackSync(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  p: SyncToolParams,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-sync", "objective_stack_sync");
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(STACK_NO_OBJECTIVE_MESSAGE, "no_objective");
  if (p.resolve) {
    // The warm-only explicit dispatch (§8.51): never calls the cold sync worker — the shared
    // dispatch pipeline corroborates against the CURRENT status projection (no freshness token;
    // the human's explicit request is the trigger) and this adapter injects the dispatch.
    const outcome = await runSyncResolution(pi, ctx, objective, null);
    if (outcome.kind === "dispatched") {
      return ok(
        `conflict-resolution dispatch injected (attempt ${outcome.attempt} of ` +
          `${CONFLICT_RESOLUTION_ATTEMPT_CAP})`,
        { objective },
      );
    }
    return fail(outcome.reason, outcome.kind);
  }
  const mode: SyncMode = p.continue_ ? "continue" : p.abort ? "abort" : "sync";
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackSyncArgs(objective, p), {
    label: "perk objective stack sync",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  // Any clean, non-declined mutating completion re-opens the shared bounded conflict budget.
  settleEpisode(pi, ctx, {
    mutating: !p.dryRun,
    declined: booleanField(r.data, "declined") === true,
  });
  return ok(renderSyncOutcome(r.data, mode), { objective });
}

async function stackAdopt(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  p: AdoptToolParams,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-sync", "objective_stack_adopt");
  if (!p.dryRun && !p.confirm) {
    return fail(
      "adoption accepts a published branch head, may cascade successor branch heads, and " +
        "updates checkpoints — preview with dry_run: true, then pass confirm: true on " +
        "explicit human approval.",
      "confirmation_required",
    );
  }
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(STACK_NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackAdoptArgs(objective, p), {
    label: "perk objective stack sync --adopt",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  settleEpisode(pi, ctx, {
    mutating: !p.dryRun,
    declined: booleanField(r.data, "declined") === true,
  });
  return ok(renderSyncOutcome(r.data, "sync"), { objective });
}

// --- registration ---------------------------------------------------------------------------------

const SYNC_TOOL_GUIDELINES = [
  "Call objective_stack_sync only inside the /objective-sync flow: preview with dry_run: true, present the cascade to the human, and act (no dry_run) ONLY on explicit human approval.",
  "The modes are mutually exclusive: continue resumes a resolved conflict continuation, abort discards it, resolve dispatches the perk.conflict-resolver subagent into the retained worktree on explicit human request; none composes with base/dry_run.",
  "A mutating sync/continue that stops on a rebase conflict auto-dispatches the resolver (bounded attempts); follow the injected dispatch instructions — they own the resume gate.",
];

const ADOPT_TOOL_GUIDELINES = [
  "Call objective_stack_adopt only when the human wants a node's manually-pushed remote head adopted as intended: preview with dry_run: true, then pass confirm: true on explicit human approval (refused otherwise).",
];

/** Install the stacked-delivery sync bindings: the `objective_stack_sync` +
 * `objective_stack_adopt` typed tools and the `/objective-sync` driving command. */
export function installStackSyncBindings(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_stack_sync",
    label: "Objective stack sync",
    description:
      "Synchronize an objective's published stack after an amend or base advance: preview " +
      "(dry_run), cascade, resume a resolved conflict continuation (continue), discard it " +
      "(abort), or dispatch the conflict-resolver subagent into the retained worktree " +
      "(resolve, on explicit human request). Modes are mutually exclusive. Delegates to the " +
      "perk cold door; call mutating modes only on explicit human approval.",
    promptSnippet:
      "Cascade-sync the objective's published stack (preview/continue/abort/resolve modes)",
    promptGuidelines: SYNC_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        objective: {
          type: ["string", "number"],
          description: "The objective issue id (inferred from the session when omitted).",
        },
        base: {
          type: "boolean",
          description: "Also advance the stack root onto the current base head.",
        },
        dry_run: {
          type: "boolean",
          description: "Preview the cascade — no journal, push, or retention.",
        },
        continue: {
          type: "boolean",
          description:
            "Resume the retained conflict continuation (after the rebase was finished — by " +
            "the human or by the dispatched resolver; publication stays the human's call).",
        },
        abort: {
          type: "boolean",
          description: "Discard the retained conflict continuation (worktree + temp refs).",
        },
        resolve: {
          type: "boolean",
          description:
            "Dispatch the conflict-resolver subagent into the retained continuation worktree " +
            "(explicit human request; composes with no other mode).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeSyncParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-sync",
          "objective_stack_sync",
        )(
          "objective_stack_sync takes { objective?, base?, dry_run?, continue?, abort?, " +
            "resolve? } — continue/abort are mutually exclusive and take no other mode flag; " +
            "resolve composes with nothing",
          "bad_input",
        );
      }
      const result = await stackSync(pi, ctx, decoded);
      // The auto-fire drive (§8.51): after the tool result settles, a mutating sync/continue
      // that refused `rebase_conflict` dispatches the resolver. Skipped for `resolve` (that IS
      // the dispatch) and when no objective resolved (the fail was `no_objective`).
      if (!decoded.resolve) {
        const objective = resolveStackObjective(decoded.objective, ctx);
        if (objective !== null) {
          const mode: SyncMode = decoded.continue_ ? "continue" : decoded.abort ? "abort" : "sync";
          const failure = result.details.ok ? null : { errorType: result.details.error_type ?? "" };
          if (autoDispatchEligible(mode, decoded.dryRun, failure)) {
            const outcome = await runSyncResolution(
              pi,
              ctx,
              objective,
              result.details.ok ? null : result.details.error,
            );
            // Failure arms only report: the tool result already carries the `rebase_conflict`
            // refusal, so a miss here must never mask it.
            if (outcome.kind !== "dispatched") {
              if (outcome.kind === "attempt_cap" || outcome.kind === "state_error") {
                report(ctx, "objective-sync", "error", outcome.reason, { alsoLog: true });
              } else {
                report(ctx, "objective-sync", "warning", outcome.reason);
              }
            }
          }
        }
      }
      return result;
    },
  });

  pi.registerTool({
    name: "objective_stack_adopt",
    label: "Objective stack adopt",
    description:
      "Adopt one node's manually-pushed remote head as the intended stack state, then cascade " +
      "the layers above it. Mutating: requires confirm: true (preview first with dry_run: " +
      "true). Delegates to the perk cold door.",
    promptSnippet: "Adopt a node's manually-pushed head into the stack (confirm-gated)",
    promptGuidelines: ADOPT_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["node"],
      properties: {
        objective: {
          type: ["string", "number"],
          description: "The objective issue id (inferred from the session when omitted).",
        },
        node: { type: "string", description: "The roadmap node id whose remote head to adopt." },
        dry_run: {
          type: "boolean",
          description: "Preview the adoption cascade — no journal, push, or retention.",
        },
        confirm: {
          type: "boolean",
          description: "Explicit human approval (required for the mutating call).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeAdoptParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-sync",
          "objective_stack_adopt",
        )(
          "objective_stack_adopt needs { node: <id> } (plus objective?, dry_run?, confirm?)",
          "bad_input",
        );
      }
      // Adopt never enters the dispatch pipeline: its failures — `rebase_conflict` included —
      // only ever report through the tool result (pinned here, not via a widened predicate).
      return stackAdopt(pi, ctx, decoded);
    },
  });

  registerStackDrivingCommand(pi, gating, {
    name: "objective-sync",
    description:
      "Drive a stack sync: preview the cascade, present it, act via the typed stack tools on " +
      "explicit approval. Pass an objective number (else the active objective).",
    guidance: objectiveSyncGuidance,
  });
}
