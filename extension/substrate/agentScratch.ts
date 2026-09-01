// Run-owned agent scratch provisioning and hidden model guidance (contracts.md §8.1).
//
// This module is guidance, not enforcement: it registers no tool and changes no process-global
// temp environment. Eligible write-capable model turns receive the repository-relative current-run
// path after the confined directory has been established. The context filter removes inherited or
// stale direct scratch custom blocks. A compaction summary may quote old prose/path text; that is
// not a live guidance delivery or authoritative provenance, and is deliberately left intact.

import { relative, sep } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type ReportTarget, report } from "../surfaces/report.ts";
import { agentScratchDir, ensureAgentScratch } from "./cache.ts";
import { activeSessionRunId, type SessionDataCtx } from "./sessionData.ts";
import {
  activeContextWindow,
  type BranchEntry,
  type BranchSource,
  branchOf,
  rebuildWorkflowState,
} from "./workflowState.ts";

export const AGENT_SCRATCH_CONTEXT_TYPE = "perk:agent-scratch";

/** Perk-owned children whose canonical definitions are report-only. */
export const REPORT_ONLY_CHILD_AGENTS = [
  "perk.adversarial-reviewer",
  "perk.draft-reviewer",
  "perk.dream-analyst",
  "perk.dream-reducer",
  "perk.harvest-analyst",
  "perk.learn-analyst",
  "perk.objective-explorer",
  "perk.pr-reviewer",
  "perk.review-classifier",
] as const;

const REPORT_ONLY_CHILD_SET = new Set<string>(REPORT_ONLY_CHILD_AGENTS);

export interface AgentScratchBlock {
  runId: string;
  /** Repository-relative POSIX-style path carried in model context. */
  path: string;
  marker: string;
  content: string;
}

export type AgentScratchContext = SessionDataCtx & ReportTarget;

/** Render the exact run-aware hidden block; provisioning stays in the resolver below. */
export function renderAgentScratchBlock(cwd: string, runId: string): AgentScratchBlock {
  const path = relative(cwd, agentScratchDir(cwd, runId)).split(sep).join("/");
  const marker = `[PERK AGENT SCRATCH run=${runId} path=${path}]`;
  const content = [
    marker,
    `Put disposable command/model intermediate files for this run in \`${path}/\` instead of shared \`/tmp\`.`,
    "Use descriptive, non-colliding names. These files are non-authoritative: re-read canonical repository or backend sources before making durable decisions.",
  ].join("\n");
  return { runId, path, marker, content };
}

/**
 * Eligibility follows the branch-LWW workflow mode and the locally exposed pi-subagents child
 * identity. Unknown/custom children remain eligible because no generic report-only metadata exists.
 */
export function isAgentScratchEligible(
  ctx: BranchSource,
  childAgent: string | undefined = process.env.PI_SUBAGENT_CHILD_AGENT,
): boolean {
  try {
    if (rebuildWorkflowState(branchOf(ctx)).mode === "read-only") return false;
  } catch {
    // No rebuilt explicit read-only mode means the parent posture remains the fallback.
  }
  return childAgent === undefined || !REPORT_ONLY_CHILD_SET.has(childAgent);
}

export interface AgentScratchProvisioner {
  resolve(ctx: AgentScratchContext): AgentScratchBlock | null;
}

/**
 * Build one extension-activation-scoped resolver. Failures warn once per run but are retried on
 * every call; one success clears suppression so a later regression is reported again.
 */
export function createAgentScratchProvisioner(
  deps: {
    ensure?: typeof ensureAgentScratch;
    warn?: (ctx: AgentScratchContext, runId: string, error: unknown) => void;
  } = {},
): AgentScratchProvisioner {
  const ensure = deps.ensure ?? ensureAgentScratch;
  const warn =
    deps.warn ??
    ((ctx: AgentScratchContext, runId: string, error: unknown) => {
      report(
        ctx,
        "agent scratch",
        "warning",
        `could not provision scratch for run ${runId}: ${String(error)}`,
        { alsoLog: true },
      );
    });
  const suppressedRuns = new Set<string>();

  return {
    resolve(ctx): AgentScratchBlock | null {
      const runId = activeSessionRunId(ctx);
      if (runId === null) return null;
      try {
        ensure(ctx.cwd, runId);
      } catch (error) {
        if (!suppressedRuns.has(runId)) {
          suppressedRuns.add(runId);
          warn(ctx, runId, error);
        }
        return null;
      }
      suppressedRuns.delete(runId);
      return renderAgentScratchBlock(ctx.cwd, runId);
    },
  };
}

/** Whether this exact current-run block remains directly represented after compaction. */
function branchHasBlock(branch: readonly BranchEntry[], block: AgentScratchBlock): boolean {
  return activeContextWindow(branch).some(
    (entry) =>
      entry.customType === AGENT_SCRATCH_CONTEXT_TYPE &&
      ((entry.type === "custom_message" && entry.content === block.content) ||
        (entry.type === "custom" && entry.data?.content === block.content)),
  );
}

/** Register eligible-turn delivery and direct scratch-custom context hygiene. */
export function registerAgentScratch(
  pi: ExtensionAPI,
  provisioner: AgentScratchProvisioner = createAgentScratchProvisioner(),
): void {
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isAgentScratchEligible(ctx)) return;

    // Provision before dedup: an externally deleted directory is repaired even while the live
    // branch still carries this run's exact guidance block.
    const block = provisioner.resolve(ctx);
    if (block === null) return;
    if (branchHasBlock(branchOf(ctx), block)) return;
    return {
      message: {
        customType: AGENT_SCRATCH_CONTEXT_TYPE,
        content: block.content,
        display: false,
      },
    };
  });

  pi.on("context", async (event, ctx) => {
    const eligible = isAgentScratchEligible(ctx);
    const block = eligible ? provisioner.resolve(ctx) : null;
    let keptCurrent = false;
    return {
      messages: event.messages.filter((message) => {
        const candidate = message as { customType?: string; content?: unknown };
        if (candidate.customType !== AGENT_SCRATCH_CONTEXT_TYPE) return true;
        if (block === null || candidate.content !== block.content || keptCurrent) return false;
        keptCurrent = true;
        return true;
      }),
    };
  });
}
