// The stacked-delivery recovery bindings (contracts.md §8.51): the `objective_stack_recover`
// typed tool and the `/objective-recover` driving command over the Python cold worker
// `perk objective stack recover` (mutations canonical in Python — recovery classification,
// roll-forward, and the sweep are cold-plane facts; the warm layer decodes, renders, and
// delegates). The §8.56 reconcile decision (`decideStackReconcile`) rides every successful
// envelope — recover's journal-complete re-emission may carry evidence (the death-after-close
// repair) and must drive exactly like a landing close.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { STACK_NO_OBJECTIVE_MESSAGE } from "../../../delivery/stackObjective.ts";
import { decideStackReconcile } from "../../../delivery/stackReconcile.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  objectListField,
  runColdDoor,
  stringField,
  stringListField,
} from "../../../substrate/coldDoor.ts";
import { render } from "../../../substrate/prompts.ts";
import { failFor, ok } from "../../../substrate/result.ts";
import type { ToolGating } from "../../../substrate/toolGating.ts";
import { booleanParam, idParam, paramsOf, stringParam } from "../../../substrate/toolParams.ts";
import { resolveStackObjective } from "../../../substrate/workflowState.ts";
import { driveStackReconcile, evidenceLines, registerStackDrivingCommand } from "./stackDrive.ts";
import type { StackResult } from "./stackSync.ts";

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
    // The external-prefix structured preview (dry-run included — what --accept-prefix records).
    for (const merged of objectListField(row, "merged_layers")) {
      const sha = stringField(merged, "merge_commit_sha") ?? "?";
      lines.push(
        `  merged: ${stringField(merged, "node_id") ?? "?"} ` +
          `pr #${numberField(merged, "pr_number") ?? "?"} as ${sha.slice(0, 12)}`,
      );
    }
    for (const rem of objectListField(row, "remainder")) {
      const head = stringField(rem, "head_sha") ?? "?";
      lines.push(
        `  remainder: pr #${numberField(rem, "pr_number") ?? "?"} ` +
          `${stringField(rem, "state") ?? "?"} at ${head.slice(0, 12)}`,
      );
    }
  }
  if (booleanField(payload, "selection_required") === true) {
    lines.push('several operations are unresolved — re-run with operation: "<ULID>" to act on one');
  }
  for (const row of objectListField(payload, "landed_layers")) {
    const finalized = booleanField(row, "finalized");
    const verdict =
      finalized === true
        ? "finalized"
        : finalized === false
          ? "FINALIZE FAILED (see notes)"
          : "would finalize";
    const sha = stringField(row, "merge_commit_sha") ?? "?";
    lines.push(
      `landed ${stringField(row, "node_id") ?? "?"} plan #${stringField(row, "plan_id") ?? "?"} ` +
        `(pr #${numberField(row, "pr_number") ?? "?"}, merged as ${sha.slice(0, 12)}): ${verdict}`,
    );
  }
  if (booleanField(payload, "objective_closed") === true) {
    const id = stringField(objectField(payload, "objective") ?? {}, "id") ?? "?";
    lines.push(`objective #${id} complete — closed`);
  }
  lines.push(...evidenceLines(payload));
  lines.push(...stringListField(payload, "notes").map((note) => `note: ${note}`));
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

/** The seed guidance the warm `/objective-recover` injects (classify → human approval → act). */
export function objectiveRecoverGuidance(objective: string): string {
  return render("stages/objective-recover.md", { objective });
}

interface RecoverToolParams {
  objective: string | undefined;
  operation: string | undefined;
  dryRun: boolean;
  abandon: boolean;
  acceptPrefix: boolean;
  confirm: boolean;
}

function decodeRecoverParams(params: unknown): RecoverToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const operation = stringParam(p, "operation");
  const dryRun = booleanParam(p, "dry_run");
  const abandon = booleanParam(p, "abandon");
  const acceptPrefix = booleanParam(p, "accept_prefix");
  const confirm = booleanParam(p, "confirm");
  if (objective === null || operation === null || dryRun === null || abandon === null) return null;
  if (acceptPrefix === null || confirm === null) return null;
  if (dryRun && (abandon || acceptPrefix)) return null; // the CLI matrix: preview first, then act
  if (abandon && acceptPrefix) return null; // mutually exclusive conclusions
  return {
    objective: objective ?? undefined,
    operation: operation ?? undefined,
    dryRun: dryRun ?? false,
    abandon: abandon ?? false,
    acceptPrefix: acceptPrefix ?? false,
    confirm: confirm ?? false,
  };
}

/** The recover argv: report/dry-run modes pass neither conclusion flag nor `--yes`. */
export function buildStackRecoverArgs(objective: string, p: RecoverToolParams): string[] {
  const args = ["objective", "stack", "recover", objective];
  if (p.operation !== undefined) args.push("--operation", p.operation);
  if (p.dryRun) args.push("--dry-run");
  if (p.abandon) args.push("--abandon", "--yes");
  if (p.acceptPrefix) args.push("--accept-prefix", "--yes");
  args.push("--json");
  return args;
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
  if (p.acceptPrefix && !p.confirm) {
    return fail(
      "accepting an externally merged prefix journals a permanent degraded-atomicity breach — " +
        "preview with dry_run: true, then pass confirm: true on explicit human approval.",
      "confirmation_required",
    );
  }
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(STACK_NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackRecoverArgs(objective, p), {
    label: "perk objective stack recover",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  const decision = decideStackReconcile(r.data);
  if (decision.drive) driveStackReconcile(pi, ctx, decision.evidence);
  return ok(renderRecoverOutcome(r.data), { objective });
}

const RECOVER_TOOL_GUIDELINES = [
  "Call objective_stack_recover inside the /objective-recover flow: dry_run: true classifies and reports; the real call concludes deterministically (all-after rolls forward — LAND included) and sweeps orphaned residue.",
  "abandon: true requires confirm: true (explicit human approval) and an all-before classification — never abandon to make a report go away; mixed classifications need human investigation.",
  "accept_prefix: true requires confirm: true and an external_prefix LAND classification — it records the externally merged prefix as a degraded-atomicity breach; then cascade the remainder with objective_stack_sync { base: true } and land it with objective_stack_land.",
];

/** Install the stacked-delivery recovery bindings: the `objective_stack_recover` typed tool +
 * the `/objective-recover` driving command. */
export function installStackRecoverBindings(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_stack_recover",
    label: "Objective stack recover",
    description:
      "Conclude an objective's unresolved stack operations (classify against fresh authority; " +
      "roll forward what verified complete — LAND included; abandon with proof under " +
      "abandon+confirm; accept an externally merged LAND prefix as a recorded breach under " +
      "accept_prefix+confirm) and sweep orphaned sync residue. dry_run reports without acting. " +
      "Delegates to the perk cold door.",
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
        accept_prefix: {
          type: "boolean",
          description:
            "Accept an externally merged LAND prefix as a recorded degraded-atomicity breach " +
            "(requires an external_prefix classification + confirm).",
        },
        confirm: {
          type: "boolean",
          description: "Explicit human approval (required with abandon or accept_prefix).",
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
            "accept_prefix?, confirm? } — dry_run composes with neither conclusion flag, and " +
            "abandon and accept_prefix are mutually exclusive",
          "bad_input",
        );
      }
      return stackRecover(pi, ctx, decoded);
    },
  });

  registerStackDrivingCommand(pi, gating, {
    name: "objective-recover",
    description:
      "Drive stack recovery: classify unresolved operations, present the report, conclude via " +
      "the typed recover tool on explicit approval. Pass an objective number (else the active " +
      "objective).",
    guidance: objectiveRecoverGuidance,
  });
}
