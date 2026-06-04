// P3.T2 — the warm `objective_save` door, the objective mirror of planSave.ts. The in-session twin
// of the Python cold door (`perk objective create`): a deterministic, terminating tool + command
// that WRAP the existing storage — they do NOT reimplement the GitHub write. `saveObjective()`
// writes the prose to a temp file, passes the STRUCTURED roadmap as `--roadmap <json>` (the agent
// never hand-writes roadmap YAML), delegates to `perk objective create --json` via `pi.exec`, then
// links the live session: `active_objective` + a fresh `perk:objective-budget` activation marker
// (mirrors the `/objective <id>` activation in objective.ts). Failures are loud-but-non-fatal.

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import type { ToolGating } from "./toolGating.ts";
import { type BranchEntry, rebuildWorkflowState, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/** The structured `details` surface (doubles as branch-safe persisted state). */
export interface ObjectiveSaveDetails {
  ok: boolean;
  objective?: { number: number; url: string };
  existed?: boolean | null;
  error?: string;
  error_type?: string;
}

export interface ObjectiveSaveResult {
  content: { type: "text"; text: string }[];
  details: ObjectiveSaveDetails;
  terminate?: boolean;
}

/** The `perk objective create --json` success shape (the contract the warm door consumes). */
interface ObjectiveCreateJson {
  success: boolean;
  error_type: string | null;
  message?: string | null;
  objective?: { number: number; url: string; existed?: boolean };
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) => {
      const b = block as { type?: string; text?: string };
      return b.type === "text" && typeof b.text === "string" ? b.text : "";
    })
    .filter(Boolean)
    .join("\n");
}

/** Best-effort fallback prose source for the `/objective-save` command: the latest assistant text. */
export function extractObjectiveMarkdown(entries: readonly unknown[]): string | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i] as { type?: string; message?: { role?: string; content?: unknown } };
    if (entry.type !== "message" || entry.message?.role !== "assistant") continue;
    const text = textOf(entry.message.content).trim();
    if (!text) continue;
    return text;
  }
  return null;
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
  const reportError = (message: string): void => {
    const full = `perk: objective-save — ${message}`;
    if (ctx.hasUI) ctx.ui.notify(full, "error");
    console.error(full);
  };
  const fail = (message: string, errorType: string): ObjectiveSaveResult => {
    reportError(message);
    return {
      content: [{ type: "text", text: `objective-save failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };

  const prose = opts.prose.trim();
  if (!prose)
    return fail("no objective prose to save (draft the objective first)", "invalid_input");
  if (opts.roadmap !== undefined && !Array.isArray(opts.roadmap)) {
    return fail("roadmap must be a JSON array of nodes", "invalid_input");
  }

  const branch = (): BranchEntry[] => ctx.sessionManager.getBranch() as unknown as BranchEntry[];
  const runId = rebuildWorkflowState(branch()).run_id ?? "";
  const perkBin = process.env.PERK_BIN ?? "perk";

  const dir = mkdtempSync(join(tmpdir(), "perk-objsave-"));
  let res: ExecResult;
  try {
    const bodyFile = join(dir, "objective.md");
    writeFileSync(bodyFile, prose, "utf8");
    const args = ["objective", "create", "--body", bodyFile, "--json"];
    if (opts.title) args.push("--title", opts.title);
    if (runId) args.push("--run-id", runId);
    if (opts.roadmap && opts.roadmap.length > 0) {
      args.push("--roadmap", JSON.stringify(opts.roadmap));
    }
    res = await pi.exec(perkBin, args, { cwd: ctx.cwd, signal: ctx.signal });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }

  if (res.killed || res.code !== 0) {
    const tail = res.stderr.trim();
    return fail(
      tail
        ? `perk objective create failed (exit ${res.code}): ${tail}`
        : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`,
      "exec_failed",
    );
  }

  let parsed: ObjectiveCreateJson;
  try {
    parsed = JSON.parse(res.stdout) as ObjectiveCreateJson;
  } catch {
    return fail("perk objective create returned unparseable JSON", "bad_output");
  }
  if (!parsed.success || !parsed.objective) {
    return fail(
      parsed.message ?? "perk objective create reported failure",
      parsed.error_type ?? "github_error",
    );
  }

  // Link the live session: set active_objective (LWW) + seed a fresh budget activation marker
  // (mirrors objective.ts's `/objective <id>` activation), so budget tracking starts immediately.
  const objective = parsed.objective;
  const objectiveId = String(objective.number);
  const linked = rebuildWorkflowState(branch()).active_objective ?? null;
  if (linked !== objectiveId) {
    pi.appendEntry(WORKFLOW_STATE_TYPE, { active_objective: objectiveId });
    pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
      objective_id: objectiveId,
      activated_at: new Date().toISOString(),
    });
    if ((rebuildWorkflowState(branch()).active_objective ?? null) !== objectiveId) {
      reportError(`active_objective read-back failed for #${objectiveId}`);
    }
  }

  const verb = objective.existed ? "Found existing" : "Saved";
  return {
    content: [{ type: "text", text: `${verb} objective #${objective.number} → ${objective.url}` }],
    details: {
      ok: true,
      objective: { number: objective.number, url: objective.url },
      existed: objective.existed ?? null,
    },
    terminate: true,
  };
}

const TOOL_GUIDELINES = [
  "Use objective_save only after the objective + roadmap are decision-complete; it creates the canonical perk:objective issue, activates it, and ends the turn.",
  "Pass the objective PROSE in `prose` and the STRUCTURED roadmap in `roadmap` (a JSON array of nodes) — never hand-write roadmap YAML.",
  'Each roadmap node needs a stable `id` (e.g. "1.1") and a `description`; `status` defaults to pending. Use `depends_on` for explicit ordering.',
];

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
      const { prose, title, roadmap } = params as {
        prose: string;
        title?: string;
        roadmap?: unknown[];
      };
      return saveObjective(pi, ctx, { prose, title, roadmap });
    },
  });

  pi.registerCommand("objective-save", {
    description:
      "Save the latest drafted objective to GitHub (the read-only → read-write boundary). " +
      "Prefer the objective_save tool to pass a structured roadmap.",
    handler: async (args, ctx) => {
      const prose = extractObjectiveMarkdown(ctx.sessionManager.getBranch());
      if (prose === null) {
        const message =
          "perk: objective-save — no objective to save; draft one first, or call the objective_save tool.";
        if (ctx.hasUI) ctx.ui.notify(message, "warning");
        else console.error(message);
        return;
      }
      const title = args.trim() || undefined;
      // The command may run while read-only; on a successful save exit the gate (the read-only →
      // read-write boundary in one gesture). The command scrapes prose only — no roadmap.
      const wasReadOnly = gating.isActive();
      const result = await saveObjective(pi, ctx, { prose, title });
      if (result.details.ok && wasReadOnly) {
        gating.exit(ctx);
      }
      if (ctx.hasUI) {
        ctx.ui.notify(
          result.content[0]?.text ?? "objective-save done",
          result.details.ok ? "info" : "error",
        );
      }
    },
  });
}
