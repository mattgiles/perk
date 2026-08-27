// The stacked-delivery status read (contracts.md §8.51): the `objective_stack_status` tool +
// the `/objective-stack` command over the Python cold worker `perk objective stack status`
// (read-only end to end — the command works in every session, including gate-on; the tool stays
// deliberately gate-off, documented in toolGating.ts). Pure decoding + rendering + delegation —
// no feature operation backs this slice (zero-policy passthrough); the mutating stack family
// (sync/adopt/recover/land + drives) lives in doors/objectiveStack.ts.
//
// Objective inference: explicit param/argument → workflow `active_objective` → plan-ref
// `objective_id` (`resolveStackObjective`); the warm layer always passes the resolved objective
// explicitly to the cold door. Cold-envelope decodes are lenient/render-only — the fully-lenient
// identity decode keeps the decode-rejection arm unreachable (`bad_output` remains reachable
// only via unparseable/non-object stdout, owned by the cold-door seam).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
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
import { registerPerkCommand } from "../../../substrate/command.ts";
import { failFor, ok, type Result } from "../../../substrate/result.ts";
import { idParam, paramsOf } from "../../../substrate/toolParams.ts";
import {
  parseStackObjectiveArg,
  resolveStackObjective,
  STACK_NO_OBJECTIVE_MESSAGE,
} from "../../../substrate/workflowState.ts";
import { report } from "../../../surfaces/report.ts";

// A deliberate module-private copy: the surviving `renderLandOutcome` (doors/objectiveStack.ts)
// keeps the other one — the cold-door doctrine's two-copy rule; consolidation happens when the
// land family migrates.
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
    const landedLen = numberField(train, "landed_prefix_len") ?? 0;
    const landedNote = landedLen > 0 ? `, landed ${landedLen}` : "";
    lines.push(
      `Objective #${id}: stacked delivery train (base ${stringField(train, "base") ?? "?"}, ` +
        `published prefix ${numberField(train, "published_prefix_len") ?? "?"}/${layers.length}` +
        `${landedNote})`,
    );
    layers.forEach((layer, index) => {
      const parts = [stringField(layer, "node_id") ?? "?"];
      parts.push(stringField(layer, "branch") ?? "no branch");
      const pr = numberField(layer, "pr_number");
      if (pr !== undefined) parts.push(`pr #${pr}`);
      parts.push(`[${stringField(layer, "publication") ?? "?"}]`);
      const handoff = stringField(layer, "handoff");
      if (handoff !== undefined && handoff !== "not_applicable") parts.push(`handoff ${handoff}`);
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
    // The additive planning_gate block (contracts §8.46): render the handoff rows from their
    // pinned fields only — leniently (missing/mistyped fields degrade, never reject); the
    // technical rows already ride the build-blocked line/findings.
    const gate = objectField(train, "planning_gate");
    if (gate !== undefined && booleanField(gate, "ready") !== true) {
      const gatedNode = stringField(gate, "node_id") ?? "?";
      for (const row of objectListField(gate, "blockers")) {
        if (stringField(row, "kind") !== "handoff") continue;
        const state = stringField(row, "handoff_state") ?? "?";
        let detail =
          `${stringField(row, "dependency_node_id") ?? "?"} ` +
          `(plan #${stringField(row, "plan") ?? "?"}, PR #${numberField(row, "pr") ?? "?"}) — ` +
          state;
        const stamped = stringField(row, "stamped_head");
        const current = stringField(row, "current_head");
        if (state === "stale" && stamped !== undefined && current !== undefined) {
          detail += `; stamped ${stamped.slice(0, 12)} ≠ head ${current.slice(0, 12)}`;
        }
        const remediation = stringField(row, "remediation") ?? "?";
        lines.push(
          `  planning gated: ${gatedNode} waits on ${detail}; record the handoff: ${remediation}`,
        );
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
    if (booleanField(continuation, "parseable") === true) {
      lines.push(
        "  resume via objective_stack_sync { continue: true }, discard via { abort: true }, or " +
          "dispatch automated resolution via { resolve: true } (on explicit human request)",
      );
    } else {
      lines.push(
        "  resume via objective_stack_sync { continue: true }, or discard via { abort: true }",
      );
    }
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

/** The one status cold-door read both surfaces share (label keeps every fallback/failure text
 * byte-compatible; the identity decode keeps the envelope render-only). */
function readStackStatus(pi: ExtensionAPI, ctx: ExtensionContext, objective: string) {
  return runColdDoor<ColdJson>(pi, ctx, ["objective", "stack", "status", objective, "--json"], {
    label: "perk objective stack status",
    decode: (payload) => payload,
  });
}

/** The tool implementation: resolve, delegate, render, never throw. */
async function stackStatus(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  objectiveParam: string | undefined,
): Promise<Result<{ objective: string }>> {
  const fail = failFor(ctx, "objective-stack", "objective_stack_status");
  const objective = resolveStackObjective(objectiveParam, ctx);
  if (objective === null) return fail(STACK_NO_OBJECTIVE_MESSAGE, "no_objective");
  const r = await readStackStatus(pi, ctx, objective);
  if (!r.ok) return fail(r.message, r.errorType);
  return ok(renderStackStatus(r.data), { objective });
}

/** Install the stacked-delivery status read: the `objective_stack_status` tool (strict
 * tri-state param decode, non-terminating) + the `/objective-stack` command. */
export function installStackStatusBindings(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "objective_stack_status",
    label: "Objective stack status",
    description:
      "Report an objective's stacked delivery train: layers, publication states, build " +
      "readiness, unresolved operations, pending continuation, and orphaned sync residue. " +
      "Read-only (delegates to the perk cold door).",
    promptSnippet: "Report the objective's stacked delivery train (read-only)",
    promptGuidelines: [
      "objective_stack_status is read-only — call it freely to inspect the delivery train, unresolved operations, pending continuations, and orphaned residue (objective inferred when omitted).",
    ],
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

  registerPerkCommand(pi, "objective-stack", {
    description:
      "Show an objective's stacked delivery train (status, operations, continuation, residue). " +
      "Pass an objective number (else the active objective, else the plan-ref's).",
    handler: async (args, ctx) => {
      const objective = resolveStackObjective(parseStackObjectiveArg(args ?? "") ?? undefined, ctx);
      if (objective === null) {
        report(ctx, "objective-stack", "warning", STACK_NO_OBJECTIVE_MESSAGE);
        return;
      }
      const r = await readStackStatus(pi, ctx, objective);
      if (!r.ok) {
        report(ctx, "objective-stack", "error", r.message, { alsoLog: true });
        return;
      }
      report(ctx, "objective-stack", "info", renderStackStatus(r.data));
    },
  });
}
