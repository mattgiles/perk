// The stacked-delivery landing bindings (contracts.md §8.55/§8.56): the `objective_stack_land`
// typed tool and the `/objective-land` driving command over the Python cold worker
// `perk objective stack land` (the atomic train merge is canonical in Python — readiness,
// journaling, finalization, and the close are cold-plane facts; the warm layer decodes,
// renders, and delegates). The §8.56 reconcile decision (`decideStackReconcile`) rides every
// successful envelope — a merged close carries journal-assembled evidence and drives the
// reconcile pass.

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
import { booleanParam, idParam, paramsOf } from "../../../substrate/toolParams.ts";
import { resolveStackObjective } from "../../../substrate/workflowState.ts";
import { driveStackReconcile, evidenceLines, registerStackDrivingCommand } from "./stackDrive.ts";
import { findingLines } from "./stackStatus.ts";
import type { StackResult } from "./stackSync.ts";

/** Render the `stack land --json` envelope — fully lenient. A `dry_run: true` payload is the
 * §8.55 readiness preview (disposition + plan + findings); anything else is the §8.56 mutation
 * outcome (outcome, landed layers, uuid, objective close, notes). */
export function renderLandOutcome(payload: ColdJson): string {
  const lines: string[] = [];
  const id = stringField(objectField(payload, "objective") ?? {}, "id") ?? "?";
  if (booleanField(payload, "dry_run") === true) {
    const disposition = stringField(payload, "disposition") ?? "?";
    lines.push(`Objective #${id}: landing readiness (dry run) — ${disposition.toUpperCase()}`);
    const plan = objectField(payload, "plan");
    if (plan !== undefined) {
      const layers = objectListField(plan, "layers");
      lines.push(
        `plan: ${stringField(plan, "mode") ?? "?"} via ${stringField(plan, "merge_method") ?? "?"} — ` +
          `top pr #${numberField(plan, "top_pr_number") ?? "?"} (${layers.length} layer(s))`,
      );
      for (const layer of layers) {
        lines.push(
          `  ${stringField(layer, "node_id") ?? "?"} plan #${stringField(layer, "plan_id") ?? "?"} ` +
            `(pr #${numberField(layer, "pr_number") ?? "?"}): ` +
            `${stringField(layer, "base_sha") ?? "?"} → ${stringField(layer, "head_sha") ?? "?"}`,
        );
      }
    }
    lines.push(...findingLines(payload, "blockers"));
    lines.push(...findingLines(payload, "information"));
    return lines.join("\n");
  }
  const outcome = stringField(payload, "outcome") ?? "?";
  const operationId = stringField(payload, "operation_id");
  if (outcome === "declined") {
    lines.push("landing declined; nothing merged or journaled");
  } else if (outcome === "completed_without_merge") {
    // Honest close reporting: the close is state-aware — never announce a close that
    // did not happen (a rerun on an already-closed objective, or a skipped close).
    lines.push(
      booleanField(payload, "objective_closed") === true
        ? `nothing to merge — objective #${id} closed as complete`
        : `nothing to merge — objective #${id} was NOT closed (see notes)`,
    );
  } else if (outcome === "merged") {
    const layers = objectListField(payload, "landed_layers");
    lines.push(
      `landed ${layers.length} layer(s) atomically` +
        (operationId !== undefined ? ` (operation ${operationId})` : ""),
    );
    for (const layer of layers) {
      const sha = stringField(layer, "merge_commit_sha") ?? "?";
      const finalized = booleanField(layer, "finalized") === true;
      lines.push(
        `  ${stringField(layer, "node_id") ?? "?"} plan #${stringField(layer, "plan_id") ?? "?"} ` +
          `(pr #${numberField(layer, "pr_number") ?? "?"}): merged as ${sha.slice(0, 12)}` +
          (finalized ? "" : " — FINALIZE FAILED (see notes)"),
      );
    }
    if (booleanField(payload, "objective_closed") === true) {
      lines.push(`objective #${id} complete — closed`);
    }
  } else {
    // pending / unexpected_enqueued (or an unknown arm — rendered honestly, never retried).
    const uuid = stringField(payload, "merge_async_uuid");
    lines.push(
      `landing outcome: ${outcome}` +
        (operationId !== undefined ? ` (operation ${operationId}` : "") +
        (operationId !== undefined ? (uuid !== undefined ? `, merge ${uuid})` : ")") : ""),
    );
    lines.push(
      "  the LAND operation is UNRESOLVED — landing is blocked until it concludes; report " +
        "this and STOP (never re-submit); once the merge settles or expires, /objective-recover " +
        "classifies it against fresh authority and concludes it",
    );
  }
  lines.push(...evidenceLines(payload));
  const notes = stringListField(payload, "notes");
  lines.push(...notes.map((note) => `note: ${note}`));
  return lines.join("\n");
}

/** The seed guidance the warm `/objective-land` injects (preview → human approval → land). */
export function objectiveLandGuidance(objective: string): string {
  return render("stages/objective-land.md", { objective });
}

interface LandToolParams {
  objective: string | undefined;
  dryRun: boolean;
  confirm: boolean;
}

function decodeLandParams(params: unknown): LandToolParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const dryRun = booleanParam(p, "dry_run");
  const confirm = booleanParam(p, "confirm");
  if (objective === null || dryRun === null || confirm === null) return null;
  return { objective: objective ?? undefined, dryRun: dryRun ?? false, confirm: confirm ?? false };
}

/** The land argv: dry-run previews without `--yes`; the confirmed call passes `--yes`. */
export function buildStackLandArgs(objective: string, p: LandToolParams): string[] {
  const args = ["objective", "stack", "land", objective];
  if (p.dryRun) args.push("--dry-run");
  else args.push("--yes");
  args.push("--json");
  return args;
}

async function stackLand(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  p: LandToolParams,
): Promise<StackResult> {
  const fail = failFor(ctx, "objective-land", "objective_stack_land");
  if (!p.dryRun && !p.confirm) {
    return fail(
      "landing merges the ENTIRE remaining train atomically — preview with dry_run: true, " +
        "then pass confirm: true on explicit human approval.",
      "confirmation_required",
    );
  }
  const objective = resolveStackObjective(p.objective, ctx);
  if (objective === null) return fail(STACK_NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await runColdDoor<ColdJson>(pi, ctx, buildStackLandArgs(objective, p), {
    label: "perk objective stack land",
    decode: (payload) => payload,
  });
  if (!r.ok) return fail(r.message, r.errorType);
  const decision = decideStackReconcile(r.data);
  if (decision.drive) driveStackReconcile(pi, ctx, decision.evidence);
  return ok(renderLandOutcome(r.data), { objective });
}

const LAND_TOOL_GUIDELINES = [
  "Call objective_stack_land only inside the /objective-land flow: preview with dry_run: true, present the land plan (or blockers) to the human, then pass confirm: true ONLY on explicit human approval.",
  "Never loop retries. A pending or unexpected_enqueued outcome means the LAND operation is UNRESOLVED — report it and stop (never re-submit); once the merge settles or expires, /objective-recover (objective_stack_recover) classifies it against fresh authority and concludes it.",
];

/** Install the stacked-delivery landing bindings: the `objective_stack_land` typed tool +
 * the `/objective-land` driving command. */
export function installStackLandBindings(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_stack_land",
    label: "Objective stack land",
    description:
      "Land an objective's remaining delivery train atomically: preview readiness (dry_run), " +
      "or merge the whole train in one journaled operation (merge-async for a multi-layer " +
      "train; a SHA-pinned direct squash for the dynamic singleton), finalize every layer, " +
      "and close the objective once every node is terminal. Mutating: requires confirm: true " +
      "(preview first with dry_run: true). Delegates to the perk cold door.",
    promptSnippet: "Land the objective's delivery train atomically (confirm-gated)",
    promptGuidelines: LAND_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        objective: {
          type: ["string", "number"],
          description: "The objective issue id (inferred from the session when omitted).",
        },
        dry_run: {
          type: "boolean",
          description: "Preview landing readiness and the land plan — read-only.",
        },
        confirm: {
          type: "boolean",
          description: "Explicit human approval (required for the mutating call).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeLandParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-land",
          "objective_stack_land",
        )("objective_stack_land takes { objective?, dry_run?, confirm? }", "bad_input");
      }
      return stackLand(pi, ctx, decoded);
    },
  });

  registerStackDrivingCommand(pi, gating, {
    name: "objective-land",
    description:
      "Drive an atomic landing: preview readiness, present the land plan, merge the whole " +
      "train via the typed land tool on explicit approval. Pass an objective number (else " +
      "the active objective).",
    guidance: objectiveLandGuidance,
  });
}
