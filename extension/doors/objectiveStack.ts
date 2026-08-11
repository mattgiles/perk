// The warm stacked-delivery surface (contracts.md §8.50): three commands + four typed model
// tools over the Python cold workers (`perk objective stack status|sync|recover` — mutations
// canonical in Python).
//
//   - `/objective-stack [N]` — a direct read door: exec the status worker, render the train
//     projection. Works in every session, including gate-on (read-only end to end).
//   - `/objective-sync [N]` / `/objective-recover [N]` — drive-the-session commands: inject the
//     preview-first guidance naming the typed tools. Gate-on posture: soft-refuse (notify +
//     inject nothing) — stack sync/recovery mutates published branches, and the mutating tools
//     never join READ_ONLY_TOOLS.
//   - `objective_stack_status` / `objective_stack_sync` / `objective_stack_adopt` /
//     `objective_stack_recover` — separately-typed tools (no broad action enum), strict
//     tri-state param decode (refuse the whole call on any malformed field), non-terminating.
//     Warm consent: the plain sync/continue/abort calls pass `--yes` (the human's gesture/driven
//     approval is the consent); adopt (mutating) and recover-with-abandon additionally require
//     `confirm: true`. Cold-envelope decodes are lenient/render-only.
//
// Objective inference everywhere: explicit param/argument → workflow `active_objective` →
// plan-ref `objective_id` (the resolveReconcileObjective precedent); the warm layer always
// passes the resolved objective explicitly to the cold door.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { readPlanRef } from "../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { booleanParam, idParam, paramsOf, stringParam } from "../substrate/toolParams.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";

/** Every stack tool returns the same slim ok-details: the resolved objective the cold door was
 * driven with (the envelope itself is render-only — nothing persisted). */
export type StackResult = Result<{ objective: string }>;

const NO_OBJECTIVE_MESSAGE =
  "no objective given and none active or linked — pass the objective explicitly.";

const GATED_REFUSAL =
  "stack sync/recovery mutates published branches — finish or exit the read-only session first.";

// --- objective inference (explicit → active_objective → plan-ref) -------------------------------

/** The first command-arg token as the explicit objective (leading `#` stripped); null if none. */
function parseObjectiveArg(args: string): string | null {
  const token = args.trim().split(/\s+/)[0]?.replace(/^#/, "") ?? "";
  return token.length > 0 ? token : null;
}

/** The three-tier objective resolution shared by every stack tool + command. */
export function resolveStackObjective(
  explicit: string | undefined,
  ctx: ExtensionContext,
): string | null {
  if (explicit !== undefined && explicit.length > 0) return explicit;
  try {
    const active = rebuildWorkflowState(branchOf(ctx)).active_objective;
    if (active !== undefined && active !== null) return active;
  } catch {
    // fall through to the plan-ref tier
  }
  try {
    return readPlanRef(ctx.cwd)?.objective_id ?? null;
  } catch {
    return null;
  }
}

// --- lenient render helpers (the cold envelopes are render-only DATA) ----------------------------

/** Lenient object-list field: a non-array (or any non-object element) contributes nothing. */
function objectListField(payload: ColdJson, key: string): ColdJson[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  const out: ColdJson[] = [];
  for (const item of value) {
    if (typeof item === "object" && item !== null && !Array.isArray(item)) {
      out.push(item as ColdJson);
    }
  }
  return out;
}

/** Lenient string-list field: non-string elements are dropped. */
function stringListField(payload: ColdJson, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function findingLines(train: ColdJson, key: string): string[] {
  const rows = objectListField(train, key);
  if (rows.length === 0) return [];
  return [
    `${key}:`,
    ...rows.map((f) => `  - [${stringField(f, "code") ?? "?"}] ${stringField(f, "message") ?? ""}`),
  ];
}

/** Render the `stack status --json` envelope (train + operations + continuation + residue) —
 * fully lenient: a missing/mistyped field degrades that line, never the render. */
export function renderStackStatus(payload: ColdJson): string {
  const lines: string[] = [];
  const id = stringField(objectField(payload, "objective") ?? {}, "id") ?? "?";
  const noTrain = stringField(payload, "no_train");
  if (noTrain !== undefined) lines.push(`Objective #${id}: ${noTrain}`);
  const train = objectField(payload, "train");
  if (train !== undefined) {
    const layers = objectListField(train, "layers");
    lines.push(
      `Objective #${id}: stacked delivery train (base ${stringField(train, "base") ?? "?"}, ` +
        `published prefix ${numberField(train, "published_prefix_len") ?? "?"}/${layers.length})`,
    );
    layers.forEach((layer, index) => {
      const parts = [stringField(layer, "node_id") ?? "?"];
      parts.push(stringField(layer, "branch") ?? "no branch");
      const pr = numberField(layer, "pr_number");
      if (pr !== undefined) parts.push(`pr #${pr}`);
      parts.push(`[${stringField(layer, "publication") ?? "?"}]`);
      lines.push(`  ${index + 1}. ${parts.join(" ")}`);
    });
    const readiness = objectField(train, "next_build_ready");
    if (readiness !== undefined) {
      if (booleanField(readiness, "ready") === true) {
        lines.push(`  next build-ready: ${stringField(readiness, "node_id") ?? "?"}`);
      } else {
        lines.push(`  build blocked: ${stringField(readiness, "reason") ?? "?"}`);
      }
    }
    lines.push(...findingLines(train, "blockers"));
    lines.push(...findingLines(train, "information"));
  }
  for (const op of objectListField(payload, "operations")) {
    lines.push(
      `unresolved operation: ${stringField(op, "operation_id") ?? "?"} ` +
        `(${stringField(op, "kind") ?? "?"}, prepared ${stringField(op, "prepared_created") ?? "?"})`,
    );
  }
  const continuation = objectField(payload, "continuation");
  if (continuation !== undefined) {
    if (booleanField(continuation, "parseable") === true) {
      lines.push(
        `pending continuation: operation ${stringField(continuation, "operation_id") ?? "?"} ` +
          `stopped on node ${stringField(continuation, "conflict_node_id") ?? "?"} ` +
          `(worktree ${stringField(continuation, "worktree_path") ?? "?"})`,
      );
    } else {
      lines.push(
        `pending continuation: UNPARSEABLE manifest at ${
          stringField(continuation, "manifest_path") ?? "?"
        }`,
      );
    }
    lines.push(
      "  resume via objective_stack_sync { continue: true }, or discard via { abort: true }",
    );
  }
  const orphans = objectField(payload, "orphaned_residue");
  if (orphans !== undefined) {
    const worktrees = stringListField(orphans, "worktrees");
    const refs = stringListField(orphans, "refs");
    if (booleanField(orphans, "observed") === false) {
      lines.push(`orphaned residue: not observed — ${stringField(orphans, "reason") ?? "?"}`);
    } else if (worktrees.length > 0 || refs.length > 0) {
      lines.push(
        `orphaned residue: ${worktrees.length} worktree(s), ${refs.length} ref(s) — ` +
          "sweep via objective_stack_recover",
      );
    }
  }
  return lines.length > 0 ? lines.join("\n") : `Objective #${id}: empty status report`;
}

/** The sync-tool invocation mode (which control flags the call carried) — decline wording and
 * the completion verb depend on it, and the flags do not fully disambiguate the envelope. */
export type SyncMode = "sync" | "continue" | "abort";

/** Render the `stack sync --json` envelope for one invocation mode — fully lenient. */
export function renderSyncOutcome(payload: ColdJson, mode: SyncMode): string {
  if (booleanField(payload, "aborted") === true) {
    return "retained continuation discarded";
  }
  if (booleanField(payload, "declined") === true) {
    if (mode === "abort") return "abort declined; everything stays retained";
    if (mode === "continue") {
      return (
        "continuation declined; everything stays retained " +
        "(re-enter via objective_stack_sync { continue: true })"
      );
    }
    return "cascade declined; nothing pushed";
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
    if (booleanField(payload, "no_op") === true) return "dry run: nothing to synchronize";
    const verb = adopted !== undefined ? "adopt + cascade" : "cascade";
    return [
      `dry run: a real sync would ${verb} ${affected.length} layer(s)`,
      ...layerLines,
      "nothing was journaled, pushed, or retained",
    ].join("\n");
  }
  if (booleanField(payload, "no_op") === true) {
    const baseHint =
      booleanField(payload, "base_advanced") === true
        ? " (the base advanced — pass base: true to cascade onto it)"
        : "";
    return `nothing to synchronize${baseHint}`;
  }
  const verb = booleanField(payload, "continued") === true ? "continued" : "synchronized";
  const suffix = adopted !== undefined ? ` (adopted node ${adopted})` : "";
  const lines = [`${verb} ${affected.length} layer(s)${suffix}`, ...layerLines];
  const operationId = stringField(payload, "operation_id");
  if (operationId !== undefined) lines.push(`operation ${operationId} complete`);
  return lines.join("\n");
}

/** Render the `stack recover --json` envelope (classification rows + sweep) — fully lenient. */
export function renderRecoverOutcome(payload: ColdJson): string {
  const lines: string[] = [];
  const dryRun = booleanField(payload, "dry_run") === true;
  if (dryRun) lines.push("dry run: nothing was concluded, journaled, or swept");
  const operations = objectListField(payload, "operations");
  if (operations.length === 0) lines.push("no unresolved operations");
  for (const row of operations) {
    lines.push(
      `${stringField(row, "operation_id") ?? "?"} (${stringField(row, "kind") ?? "?"}, ` +
        `prepared ${stringField(row, "prepared_created") ?? "?"}): ` +
        `${stringField(row, "classification") ?? "?"} → ${stringField(row, "action") ?? "?"}`,
    );
    const detail = stringField(row, "detail");
    if (detail !== undefined) lines.push(`  ${detail}`);
  }
  if (booleanField(payload, "selection_required") === true) {
    lines.push('several operations are unresolved — re-run with operation: "<ULID>" to act on one');
  }
  const sweepSkipped = stringField(payload, "sweep_skipped");
  if (sweepSkipped !== undefined) {
    lines.push(`sweep skipped: ${sweepSkipped}`);
  } else {
    const worktrees = stringListField(payload, "swept_worktrees");
    const refs = stringListField(payload, "swept_refs");
    if (worktrees.length > 0 || refs.length > 0) {
      const verb = dryRun ? "would sweep" : "swept";
      lines.push(
        `${verb} ${worktrees.length} orphaned worktree(s) and ${refs.length} orphaned ref(s)`,
      );
    }
  }
  for (const failure of objectListField(payload, "sweep_failures")) {
    lines.push(
      `sweep failure: ${stringField(failure, "target") ?? "?"} ` +
        `(${stringField(failure, "error") ?? "?"})`,
    );
  }
  return lines.join("\n");
}

// --- the driving guidance (pure; the skill pointer rides the binding suffix, never hardcoded) ----

/** The seed guidance the warm `/objective-sync` injects (preview → human approval → typed act). */
export function objectiveSyncGuidance(objective: string): string {
  return render("stages/objective-sync.md", { objective });
}

/** The seed guidance the warm `/objective-recover` injects (classify → human approval → act). */
export function objectiveRecoverGuidance(objective: string): string {
  return render("stages/objective-recover.md", { objective });
}

// --- strict tool decodes + argv builders ---------------------------------------------------------

interface SyncToolParams {
  objective: string | undefined;
  base: boolean;
  dryRun: boolean;
  continue_: boolean;
  abort: boolean;
}

/** Strict decode + the §8.49 mode matrix (same as the CLI's): null = refuse the whole call. */
function decodeSyncParams(params: unknown): SyncToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const base = booleanParam(p, "base");
  const dryRun = booleanParam(p, "dry_run");
  const continue_ = booleanParam(p, "continue");
  const abort = booleanParam(p, "abort");
  if (objective === null || base === null || dryRun === null || continue_ === null) return null;
  if (abort === null) return null;
  const decoded: SyncToolParams = {
    objective: objective ?? undefined,
    base: base ?? false,
    dryRun: dryRun ?? false,
    continue_: continue_ ?? false,
    abort: abort ?? false,
  };
  if (decoded.continue_ && decoded.abort) return null;
  if ((decoded.continue_ || decoded.abort) && (decoded.base || decoded.dryRun)) return null;
  return decoded;
}

/** The sync argv by mode: continue/abort take no cascade flags; `--yes` rides every mutating
 * path (warm consent — the human's gesture/driven approval); a dry run passes no `--yes`. */
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

interface RecoverToolParams {
  objective: string | undefined;
  operation: string | undefined;
  dryRun: boolean;
  abandon: boolean;
  confirm: boolean;
}

function decodeRecoverParams(params: unknown): RecoverToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const operation = stringParam(p, "operation");
  const dryRun = booleanParam(p, "dry_run");
  const abandon = booleanParam(p, "abandon");
  const confirm = booleanParam(p, "confirm");
  if (objective === null || operation === null || dryRun === null || abandon === null) return null;
  if (confirm === null) return null;
  if (dryRun && abandon) return null; // the CLI matrix: preview first, then abandon
  return {
    objective: objective ?? undefined,
    operation: operation ?? undefined,
    dryRun: dryRun ?? false,
    abandon: abandon ?? false,
    confirm: confirm ?? false,
  };
}

/** The recover argv: report/dry-run modes pass neither `--abandon` nor `--yes`. */
export function buildStackRecoverArgs(objective: string, p: RecoverToolParams): string[] {
  const args = ["objective", "stack", "recover", objective];
  if (p.operation !== undefined) args.push("--operation", p.operation);
  if (p.dryRun) args.push("--dry-run");
  if (p.abandon) args.push("--abandon", "--yes");
  args.push("--json");
  return args;
}

// --- the tool implementations (delegate, render, never throw) ------------------------------------

async function stackStatus(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  objectiveParam: string | undefined,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-stack", "objective_stack_status");
  const objective = resolveStackObjective(objectiveParam, ctx);
  if (objective === null) return fail(NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(
    pi,
    ctx,
    ["objective", "stack", "status", objective, "--json"],
    { label: "perk objective stack status", decode: (payload) => payload },
  );
  if (!r.ok) return fail(r.message, r.errorType);
  return ok(renderStackStatus(r.data), { objective });
}

async function stackSync(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  p: SyncToolParams,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-sync", "objective_stack_sync");
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(NO_OBJECTIVE_MESSAGE, "no_objective");
  const mode: SyncMode = p.continue_ ? "continue" : p.abort ? "abort" : "sync";
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackSyncArgs(objective, p), {
    label: "perk objective stack sync",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
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
      "adoption rewrites published stack membership — preview with dry_run: true, then pass " +
        "confirm: true on explicit human approval.",
      "confirmation_required",
    );
  }
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackAdoptArgs(objective, p), {
    label: "perk objective stack sync --adopt",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  return ok(renderSyncOutcome(r.data, "sync"), { objective });
}

async function stackRecover(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  p: RecoverToolParams,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-recover", "objective_stack_recover");
  if (p.abandon && !p.confirm) {
    return fail(
      "abandoning an unresolved operation journals its permanent conclusion — preview with " +
        "dry_run: true, then pass confirm: true on explicit human approval.",
      "confirmation_required",
    );
  }
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackRecoverArgs(objective, p), {
    label: "perk objective stack recover",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  return ok(renderRecoverOutcome(r.data), { objective });
}

// --- registration --------------------------------------------------------------------------------

const STATUS_TOOL_GUIDELINES = [
  "objective_stack_status is read-only — call it freely to inspect the delivery train, unresolved operations, pending continuations, and orphaned residue (objective inferred when omitted).",
];

const SYNC_TOOL_GUIDELINES = [
  "Call objective_stack_sync only inside the /objective-sync flow: preview with dry_run: true, present the cascade to the human, and act (no dry_run) ONLY on explicit human approval.",
  "The modes are mutually exclusive: continue resumes a human-resolved conflict continuation, abort discards it; neither composes with base/dry_run. perk never drives conflict resolution — the human finishes the rebase in the retained worktree first.",
];

const ADOPT_TOOL_GUIDELINES = [
  "Call objective_stack_adopt only when the human wants a node's manually-pushed remote head adopted as intended: preview with dry_run: true, then pass confirm: true on explicit human approval (refused otherwise).",
];

const RECOVER_TOOL_GUIDELINES = [
  "Call objective_stack_recover inside the /objective-recover flow: dry_run: true classifies and reports; the real call concludes deterministically (all-after rolls forward) and sweeps orphaned residue.",
  "abandon: true requires confirm: true (explicit human approval) and an all-before classification — never abandon to make a report go away; mixed classifications need human investigation.",
];

/** Register the warm stacked-delivery surface: four typed tools + three commands. */
export function registerObjectiveStack(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_stack_status",
    label: "Objective stack status",
    description:
      "Report an objective's stacked delivery train: layers, publication states, build " +
      "readiness, unresolved operations, pending continuation, and orphaned sync residue. " +
      "Read-only (delegates to the perk cold door).",
    promptSnippet: "Report the objective's stacked delivery train (read-only)",
    promptGuidelines: STATUS_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        objective: {
          type: ["string", "number"],
          description: "The objective issue id (inferred from the session when omitted).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const p = paramsOf(params);
      const objective = p === null ? null : idParam(p, "objective");
      if (p === null || objective === null) {
        return failFor(
          ctx,
          "objective-stack",
          "objective_stack_status",
        )("objective_stack_status takes { objective?: <id> }", "bad_input");
      }
      return stackStatus(pi, ctx, objective);
    },
  });

  pi.registerTool({
    name: "objective_stack_sync",
    label: "Objective stack sync",
    description:
      "Synchronize an objective's published stack after an amend or base advance: preview " +
      "(dry_run), cascade, resume a human-resolved conflict continuation (continue), or " +
      "discard it (abort). Modes are mutually exclusive. Delegates to the perk cold door; " +
      "call mutating modes only on explicit human approval.",
    promptSnippet: "Cascade-sync the objective's published stack (preview/continue/abort modes)",
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
            "Resume the retained conflict continuation (after the human finished the rebase).",
        },
        abort: {
          type: "boolean",
          description: "Discard the retained conflict continuation (worktree + temp refs).",
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
          "objective_stack_sync takes { objective?, base?, dry_run?, continue?, abort? } — " +
            "continue/abort are mutually exclusive and take no other mode flag",
          "bad_input",
        );
      }
      return stackSync(pi, ctx, decoded);
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
      return stackAdopt(pi, ctx, decoded);
    },
  });

  pi.registerTool({
    name: "objective_stack_recover",
    label: "Objective stack recover",
    description:
      "Conclude an objective's unresolved stack operations (classify against fresh authority; " +
      "roll forward what verified complete; abandon with proof under abandon+confirm) and " +
      "sweep orphaned sync residue. dry_run reports without acting. Delegates to the perk " +
      "cold door.",
    promptSnippet: "Conclude unresolved stack operations + sweep orphaned residue",
    promptGuidelines: RECOVER_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        objective: {
          type: ["string", "number"],
          description: "The objective issue id (inferred from the session when omitted).",
        },
        operation: {
          type: "string",
          description: "The target operation ULID (required when several are unresolved).",
        },
        dry_run: {
          type: "boolean",
          description: "Classify and report only — no roll-forward, no abandon, no sweep.",
        },
        abandon: {
          type: "boolean",
          description: "Abandon the target operation (requires an all-before proof + confirm).",
        },
        confirm: {
          type: "boolean",
          description: "Explicit human approval (required with abandon).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeRecoverParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-recover",
          "objective_stack_recover",
        )(
          "objective_stack_recover takes { objective?, operation?, dry_run?, abandon?, " +
            "confirm? } — dry_run and abandon are mutually exclusive",
          "bad_input",
        );
      }
      return stackRecover(pi, ctx, decoded);
    },
  });

  registerPerkCommand(pi, "objective-stack", {
    description:
      "Show an objective's stacked delivery train (status, operations, continuation, residue). " +
      "Pass an objective number (else the active objective, else the plan-ref's).",
    handler: async (args, ctx) => {
      const objective = resolveStackObjective(parseObjectiveArg(args ?? "") ?? undefined, ctx);
      if (objective === null) {
        report(ctx, "objective-stack", "warning", NO_OBJECTIVE_MESSAGE);
        return;
      }
      const r = await runColdDoor<ColdJson>(
        pi,
        ctx,
        ["objective", "stack", "status", objective, "--json"],
        { label: "perk objective stack status", decode: (payload) => payload },
      );
      if (!r.ok) {
        report(ctx, "objective-stack", "error", r.message, { alsoLog: true });
        return;
      }
      report(ctx, "objective-stack", "info", `\n${renderStackStatus(r.data)}`);
    },
  });

  registerPerkCommand(pi, "objective-sync", {
    description:
      "Drive a stack sync: preview the cascade, present it, act via the typed stack tools on " +
      "explicit approval. Pass an objective number (else the active objective).",
    handler: async (args, ctx) => {
      if (gating.isActive()) {
        report(ctx, "objective-sync", "warning", GATED_REFUSAL);
        return;
      }
      const objective = resolveStackObjective(parseObjectiveArg(args ?? "") ?? undefined, ctx);
      if (objective === null) {
        report(ctx, "objective-sync", "warning", NO_OBJECTIVE_MESSAGE);
        return;
      }
      report(ctx, "objective-sync", "info", `#${objective}`);
      pi.sendUserMessage(
        objectiveSyncGuidance(objective) + bindingSuffix(ctx.cwd, "command:objective-sync"),
      );
    },
  });

  registerPerkCommand(pi, "objective-recover", {
    description:
      "Drive stack recovery: classify unresolved operations, present the report, conclude via " +
      "the typed recover tool on explicit approval. Pass an objective number (else the active " +
      "objective).",
    handler: async (args, ctx) => {
      if (gating.isActive()) {
        report(ctx, "objective-recover", "warning", GATED_REFUSAL);
        return;
      }
      const objective = resolveStackObjective(parseObjectiveArg(args ?? "") ?? undefined, ctx);
      if (objective === null) {
        report(ctx, "objective-recover", "warning", NO_OBJECTIVE_MESSAGE);
        return;
      }
      report(ctx, "objective-recover", "info", `#${objective}`);
      pi.sendUserMessage(
        objectiveRecoverGuidance(objective) + bindingSuffix(ctx.cwd, "command:objective-recover"),
      );
    },
  });
}
