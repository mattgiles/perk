// P1.T3 — the warm `/plan-save` door (turn-3 §5/§6). The in-session twin of the Python cold
// door (`perk plan-save`): a deterministic, terminating tool + command that WRAP T2's storage —
// they do NOT reimplement the GitHub write. `savePlan()` writes the plan to a temp file, delegates
// to `perk plan-save --json` via `pi.exec` (the sanctioned process-launch + cli-vs-pi §3.2
// machine-JSON channel), then appends `active_plan_ref` so the live session is linked immediately
// (strict read-back, idempotent, headless-safe). Failures are loud-but-non-fatal — never throw.

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "./cache.ts";
import {
  type BranchEntry,
  planRefsEqual,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "./workflowState.ts";

/** The structured `details` surface (turn-3 D6) — doubles as branch-safe persisted state. */
export interface PlanSaveDetails {
  ok: boolean;
  issue?: { number: number; url: string };
  plan_ref?: PlanRef;
  cached?: boolean;
  existed?: boolean | null;
  error?: string;
  error_type?: string;
}

/** A tool result patch (AgentToolResult has no `isError`; failure is signaled via details.ok). */
export interface SaveResult {
  content: { type: "text"; text: string }[];
  details: PlanSaveDetails;
  terminate?: boolean;
}

/** The T2a `perk plan-save --json` success shape (the contract the warm door consumes). */
interface PlanSaveJson {
  success: boolean;
  error_type: string | null;
  message: string | null;
  issue?: { number: number; url: string; existed?: boolean };
  plan_ref?: PlanRef;
  cached?: boolean;
}

/**
 * Detect the borrowed `@tombell/pi-plan` plan mode from its own persisted signal: it appends a
 * `plan-mode-state` custom entry `{ enabled }` on every toggle (and restores from it on
 * session_start). We read the latest such entry (LWW, survives fork/branch) — the lowest-coupling
 * way to know plan mode is on. (A soft coupling to a borrowed package's entry type; removed in
 * Phase 2 when perk owns plan mode.)
 */
export function isPlanModeActive(branch: readonly BranchEntry[]): boolean {
  for (let i = branch.length - 1; i >= 0; i--) {
    const e = branch[i];
    if (e?.type === "custom" && e.customType === "plan-mode-state") {
      return (e.data as { enabled?: unknown } | undefined)?.enabled === true;
    }
  }
  return false;
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

/**
 * Best-effort, deterministic: the whole text of the latest assistant message, or null. This is the
 * `/plan-save` **command**'s fallback plan source and is inherently fragile (it cannot tell a clean
 * plan from conversation). The robust path is the `plan_save` *tool*, where the model hands the
 * finalized plan over via the `plan` parameter. (There is no tag/marker convention to extract — the
 * borrowed plan-mode package emits no structured plan, only free-form prose.)
 */
export function extractPlanMarkdown(entries: readonly unknown[]): string | null {
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
 * The single save implementation both surfaces call. Delegates the GitHub write to the Python
 * cold door, then links the live session. Returns a soft result (never throws); failures set
 * `details.ok = false` and append no linkage.
 */
export async function savePlan(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: { plan: string; title?: string },
): Promise<SaveResult> {
  const reportError = (message: string): void => {
    const full = `perk: plan-save — ${message}`;
    if (ctx.hasUI) ctx.ui.notify(full, "error");
    console.error(full);
  };
  const fail = (message: string, errorType: string): SaveResult => {
    reportError(message);
    return {
      content: [{ type: "text", text: `plan-save failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };

  const plan = opts.plan.trim();
  if (!plan) return fail("no plan markdown to save (propose a plan first)", "invalid_input");

  const branch = (): BranchEntry[] => ctx.sessionManager.getBranch() as unknown as BranchEntry[];
  // Fail fast in plan mode: the `plan_save` tool is hidden by pi-plan, and the `/plan-save`
  // command would otherwise scrape conversation as the "plan". perk cannot cleanly exit pi-plan
  // (it owns that state), so we refuse and tell the user to exit it themselves.
  if (isPlanModeActive(branch())) {
    return fail(
      "plan mode is active — exit it with /plan, then save (or, once it's off, call the plan_save " +
        "tool with the finalized plan)",
      "plan_mode_active",
    );
  }
  const runId = rebuildWorkflowState(branch()).run_id ?? "";
  const perkBin = process.env.PERK_BIN ?? "perk";

  const dir = mkdtempSync(join(tmpdir(), "perk-plansave-"));
  let res: ExecResult;
  try {
    const planFile = join(dir, "plan.md");
    writeFileSync(planFile, plan, "utf8");
    const args = ["plan-save", "--plan-file", planFile, "--json"];
    if (runId) args.push("--run-id", runId);
    // pi.exec returns (does not throw) on spawn/non-zero exit — see turn-3 §3.5 S2.
    res = await pi.exec(perkBin, args, { cwd: ctx.cwd, signal: ctx.signal });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }

  if (res.killed || res.code !== 0) {
    const tail = res.stderr.trim();
    return fail(
      tail
        ? `perk plan-save failed (exit ${res.code}): ${tail}`
        : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`,
      "exec_failed",
    );
  }

  let parsed: PlanSaveJson;
  try {
    parsed = JSON.parse(res.stdout) as PlanSaveJson;
  } catch {
    return fail("perk plan-save returned unparseable JSON", "bad_output");
  }
  if (!parsed.success || !parsed.plan_ref || !parsed.issue) {
    return fail(
      parsed.message ?? "perk plan-save reported failure",
      parsed.error_type ?? "github_error",
    );
  }

  // Link the live session (turn-3 D4): append iff the rebuilt ref differs, with a strict read-back.
  const ref = parsed.plan_ref;
  if (!planRefsEqual(rebuildWorkflowState(branch()).active_plan_ref ?? null, ref)) {
    pi.appendEntry(WORKFLOW_STATE_TYPE, { active_plan_ref: ref });
    if (!planRefsEqual(rebuildWorkflowState(branch()).active_plan_ref ?? null, ref)) {
      reportError(`plan-ref read-back failed for ${ref.provider}:${ref.pr_id}`);
    }
  }

  return {
    content: [{ type: "text", text: `Saved plan #${ref.pr_id} → ${ref.url}` }],
    details: {
      ok: true,
      issue: { number: parsed.issue.number, url: parsed.issue.url },
      plan_ref: ref,
      cached: parsed.cached ?? false,
      existed: parsed.issue.existed ?? null,
    },
    terminate: true,
  };
}

const TOOL_GUIDELINES = [
  "Use plan_save only after the plan is decision-complete and the user has agreed; it creates the canonical GitHub plan and ends the turn.",
  "Pass the full plan markdown to plan_save in the `plan` parameter; never reference line numbers — use durable anchors (function names, behavioral descriptions, structural locations).",
];

/** Register the warm door: the `plan_save` tool (canonical) + the `/plan-save` command twin. */
export function registerPlanSave(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "plan_save",
    label: "Save plan",
    description:
      "Persist the current plan to GitHub as the canonical perk plan and link this session to it. " +
      "Terminating: ends the turn on save. Call only when the plan is decision-complete.",
    promptSnippet: "Save the decision-complete plan to GitHub (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["plan"],
      properties: {
        plan: {
          type: "string",
          description: "The full plan markdown to save (no line-number references).",
        },
        title: {
          type: "string",
          description: "Optional issue title (defaults to the plan's first heading).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const { plan, title } = params as { plan: string; title?: string };
      return savePlan(pi, ctx, { plan, title });
    },
  });

  pi.registerCommand("plan-save", {
    description: "Save the latest proposed plan to GitHub (the read-only → read-write boundary).",
    handler: async (args, ctx) => {
      const plan = extractPlanMarkdown(ctx.sessionManager.getBranch());
      if (plan === null) {
        const message =
          "perk: plan-save — no plan to save; propose a plan first, or call the plan_save tool with the markdown.";
        if (ctx.hasUI) ctx.ui.notify(message, "warning");
        console.error(message);
        return;
      }
      const title = args.trim() || undefined;
      const result = await savePlan(pi, ctx, { plan, title });
      if (ctx.hasUI) {
        ctx.ui.notify(
          result.content[0]?.text ?? "plan-save done",
          result.details.ok ? "info" : "error",
        );
      }
    },
  });
}
