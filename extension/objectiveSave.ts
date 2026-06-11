// P3.T2 — the warm `objective_save` door, the objective mirror of planSave.ts. The in-session twin
// of the Python cold door (`perk objective create`): a deterministic, terminating tool + command
// that WRAP the existing storage — they do NOT reimplement the GitHub write. `saveObjective()`
// passes the STRUCTURED roadmap as `--roadmap <json>` (the agent never hand-writes roadmap YAML)
// and delegates to `perk objective create --json` via the shared cold-door client (`runColdDoor`,
// Node 1.4 — the prose rides the run-scratch stdin channel), then links the live session: `active_objective` + a fresh `perk:objective-budget` activation marker
// (mirrors the `/objective <id>` activation in objective.ts). Failures are loud-but-non-fatal.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "./bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "./coldDoor.ts";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import { failFor, ok, type Result } from "./result.ts";
import type { ToolGating } from "./toolGating.ts";
import { arrayParam, paramsOf, stringParam } from "./toolParams.ts";
import { appendWorkflowState, branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface ObjectiveSaveOk {
  objective: { number: number; url: string };
  existed: boolean | null;
}

export type ObjectiveSaveResult = Result<ObjectiveSaveOk>;

/** The decoded `perk objective create --json` payload slice the warm door consumes. */
interface ObjectiveCreatePayload {
  objective: { number: number; url: string; existed: boolean | undefined };
}

/** Narrow the `perk objective create --json` success payload; strict on `objective`. */
function decodeObjectiveCreate(payload: ColdJson): ObjectiveCreatePayload | null {
  const objective = objectField(payload, "objective");
  if (objective === undefined) return null;
  const number = numberField(objective, "number");
  const url = stringField(objective, "url");
  if (number === undefined || url === undefined) return null;
  return { objective: { number, url, existed: booleanField(objective, "existed") } };
}

/** The decoded `objective_save` tool params. */
interface ObjectiveSaveParams {
  prose: string;
  title?: string;
  roadmap?: unknown[];
}

/**
 * Decode unknown `objective_save` tool-call params (the tool-boundary seam — Node 3.2). `prose`
 * absent decodes to `""` (so `saveObjective`'s "no objective prose to save" `invalid_input` arm
 * keeps owning that message) but present-but-mistyped → null (strict-fail). `roadmap` stays
 * `unknown[]` — the Python cold door owns node-shape validation.
 */
export function decodeObjectiveSaveParams(params: unknown): ObjectiveSaveParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const prose = stringParam(p, "prose");
  const title = stringParam(p, "title");
  const roadmap = arrayParam(p, "roadmap");
  if (prose === null || title === null || roadmap === null) return null;
  return { prose: prose ?? "", title, roadmap };
}

/**
 * The single save implementation both surfaces call. Delegates the GitHub write to the Python cold
 * door, then links the live session (`active_objective` + budget marker). Returns a soft result
 * (never throws); failures set `details.ok = false` and append no linkage.
 */
export async function saveObjective(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: { prose: string; title?: string; roadmap?: unknown[] },
): Promise<ObjectiveSaveResult> {
  const fail = failFor(ctx, "objective-save");

  const prose = opts.prose.trim();
  if (!prose)
    return fail("no objective prose to save (draft the objective first)", "invalid_input");
  if (opts.roadmap !== undefined && !Array.isArray(opts.roadmap)) {
    return fail("roadmap must be a JSON array of nodes", "invalid_input");
  }

  const branch = () => branchOf(ctx);
  const runId = rebuildWorkflowState(branch()).run_id ?? "";

  const args = ["objective", "create", "--json"];
  if (opts.title) args.push("--title", opts.title);
  if (runId) args.push("--run-id", runId);
  if (opts.roadmap && opts.roadmap.length > 0) {
    args.push("--roadmap", JSON.stringify(opts.roadmap));
  }
  const r = await runColdDoor<ObjectiveCreatePayload>(pi, ctx, args, {
    label: "perk objective create",
    decode: decodeObjectiveCreate,
    stdin: { flag: "--body", content: prose, filename: "objective.md" },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Link the live session: set active_objective (LWW) + seed a fresh budget activation marker
  // (mirrors objective.ts's `/objective <id>` activation), so budget tracking starts immediately.
  const objective = r.data.objective;
  const objectiveId = String(objective.number);
  const linked = rebuildWorkflowState(branch()).active_objective ?? null;
  if (linked !== objectiveId) {
    appendWorkflowState(pi, ctx, {
      data: { active_objective: objectiveId },
      field: "active_objective",
      expected: objectiveId,
      scope: "objective-save",
      failure: `active_objective read-back failed for #${objectiveId}`,
    });
    pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
      objective_id: objectiveId,
      activated_at: new Date().toISOString(),
    });
  }

  const verb = objective.existed ? "Found existing" : "Saved";
  return ok(
    `${verb} objective #${objective.number} → ${objective.url}`,
    {
      objective: { number: objective.number, url: objective.url },
      existed: objective.existed ?? null,
    },
    { terminate: true },
  );
}

const TOOL_GUIDELINES = [
  "Use objective_save only after the objective + roadmap are decision-complete; it creates the canonical perk:objective issue, activates it, and ends the turn.",
  "Pass the objective PROSE in `prose` and the STRUCTURED roadmap in `roadmap` (a JSON array of nodes) — never hand-write roadmap YAML.",
  'Each roadmap node needs a stable `id` (e.g. "1.1") and a `description`; `status` defaults to pending. Use `depends_on` for explicit ordering.',
];

/**
 * The seed guidance the warm `/objective-save` injects to drive the structured save (the
 * perk-objective-author skill pointer rides the skill-binding suffix — Node 2.3 — not hardcoded
 * here). Pure + exported for offline tests.
 */
export function objectiveSaveGuidance(title?: string): string {
  const named = title?.trim();
  return [
    "perk /objective-save — persist the objective the session converged on.",
    "1. If the objective + roadmap are NOT yet decision-complete, finish converging first, then " +
      "call the tool.",
    "2. Call the `objective_save` tool NOW, passing `prose` (the decision-complete objective " +
      "prose) and `roadmap` (the STRUCTURED roadmap as a JSON array of nodes, each with a stable " +
      "`id` and `description`) — NEVER hand-write the roadmap as YAML.",
    named
      ? `3. Pass \`title: "${named}"\` as the objective title.`
      : "3. `title` is optional (defaults to the prose's first heading).",
    "4. The tool creates the perk:objective issue, activates it, starts budget tracking, and " +
      "terminates the turn. Judgment + durable writes stay with you.",
  ].join("\n");
}

/** Register the warm door: the `objective_save` tool (canonical) + the `/objective-save` twin. */
export function registerObjectiveSave(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_save",
    label: "Save objective",
    description:
      "Persist a drafted objective + structured roadmap to GitHub as a perk:objective issue, " +
      "activate it, and start budget tracking. Terminating: ends the turn on save. Call only when " +
      "the objective and roadmap are decision-complete.",
    promptSnippet: "Save the decision-complete objective + roadmap to GitHub (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["prose"],
      properties: {
        prose: {
          type: "string",
          description: "The objective prose (the why, the design, the boundaries/non-goals).",
        },
        title: {
          type: "string",
          description: "Optional objective title (defaults to the prose's first heading).",
        },
        roadmap: {
          type: "array",
          description:
            "The structured roadmap: a JSON array of nodes. Never hand-write roadmap YAML.",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["id", "description"],
            properties: {
              id: { type: "string", description: 'A stable node id, e.g. "1.1".' },
              description: { type: "string", description: "What this node delivers." },
              status: {
                type: "string",
                enum: ["pending", "planning", "in_progress", "done", "blocked", "skipped"],
                description: "Optional initial status (defaults to pending).",
              },
              slug: { type: "string", description: "Optional short slug." },
              pr: { type: "string", description: 'Optional plan/PR backlink, e.g. "#42".' },
              depends_on: {
                type: "array",
                items: { type: "string" },
                description: "Optional explicit dependency node ids.",
              },
              comment: { type: "string", description: "Optional note." },
            },
          },
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeObjectiveSaveParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-save",
          "objective_save",
        )(
          "objective_save needs { prose: string, roadmap?: array } per the tool schema",
          "bad_input",
        );
      }
      return saveObjective(pi, ctx, decoded);
    },
  });

  pi.registerCommand("objective-save", {
    description:
      "Drive the structured objective save: exit read-only (so the objective_save tool is " +
      "reachable) and inject guidance for the session to call objective_save with prose + the " +
      "structured roadmap.",
    handler: async (args, ctx) => {
      const title = args.trim() || undefined;
      // Exit the read-only gate so the objective_save tool (excluded from READ_ONLY_TOOLS) becomes
      // reachable on the driven turn, then drive the turn — unlike /learn-docs (which early-returns
      // on headless), /objective-save has no pre-gather artifact, so the only useful action is the
      // gate-exit + drive (mirrors /address and /objective-plan).
      if (gating.isActive()) gating.exit(ctx);
      const message = "perk: /objective-save — handing the structured save to the session";
      if (ctx.hasUI) ctx.ui.notify(message, "info");
      else console.error(message);
      // The perk-objective-author pointer rides the skill-binding suffix (Node 2.3, D5) since a warm
      // /objective-save outside a stage:objective-author session gets none from Mechanism A.
      pi.sendUserMessage(
        objectiveSaveGuidance(title) + bindingSuffix(ctx.cwd, "stage:objective-author"),
      );
    },
  });
}
