// The warm `/commit-and-compact` door: commit the work so far, then compact the session.
//
// Human-only slash command (no model-facing tool twin, no cold door, no workflow-state field —
// warm-plane only). The commit half needs the model (real staging judgment + a real commit
// message), so the dirty arm DRIVES the session (`pi.sendUserMessage`, warm-door discipline);
// the compaction half is deterministic extension work keyed on `agent_settled` (the one-shot
// "the driven run fully settled" hook — `turn_end` would compact mid-run). Fail-safe posture:
// never compact when uncommitted work might exist — the undeterminable-git-state and no-commit
// arms skip compaction with a loud warning naming pi's builtin `/compact` escape hatch. Clean
// and read-only trees compact immediately (the commit half is vacuous there).
//
// The pending record is in-memory by design (lost on `/reload` — the user re-runs the command);
// re-invoking while a drive is in flight simply overwrites it.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import type { PlanRef } from "../substrate/cache.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { commitsSince, headSha, worktreeDirty } from "../substrate/git.ts";
import { render } from "../substrate/prompts.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report, type Severity } from "../surfaces/report.ts";
import { planReadInstruction } from "./lifecycleGates.ts";

/** The driven-commit guidance (pure + exported for offline tests and the drive-coverage guard). */
export function commitAndCompactGuidance(): string {
  return render("commit-and-compact.md", {});
}

/**
 * Compaction instructions for the arms with nothing to commit (read-only / clean tree). Inline,
 * not a `prompts/` template — compaction `customInstructions` stay inline (the objective
 * threshold-compaction precedent); only injected user-message prose goes to `prompts/`.
 */
export const DIRECT_COMPACT_INSTRUCTIONS =
  "Preserve the current task's intent, progress so far, and the concrete next steps.";

/**
 * Compaction instructions for the committed arm: embed the `git log --oneline` listing of the
 * new commit(s) so the summary references them. Pure + exported for offline tests.
 */
export function compactInstructions(commits: string | null): string {
  return [
    "The work completed so far was just committed:",
    "",
    commits ?? "(commit list unavailable)",
    "",
    "Preserve in the summary: the task being implemented and its current progress, what the new " +
      "commit(s) contain, and the concrete next steps for the remaining work. The committed diff " +
      "is recoverable via git, so prefer intent and next steps over restating the diff.",
  ].join("\n");
}

/** The one-shot record the dirty/drive arm leaves for the `agent_settled` handler. */
export interface PendingCompact {
  cwd: string;
  /** HEAD at invocation (null on an unborn HEAD) — the advance gate compares against this. */
  headBefore: string | null;
}

export type CommitCompactCompletion =
  | { outcome: "committed"; commits: string | null }
  | { outcome: "clean" }
  | { outcome: "read-only" };

/** The door's side-effect surface — `ExtensionContext`-backed in wiring, recorder fakes in tests. */
export interface CommitCompactIo {
  report(severity: Severity, message: string): void;
  send(guidance: string): void;
  compact(customInstructions: string, completion: CommitCompactCompletion): void;
}

/**
 * The command-specific active-plan resolver. Session-tier `active_plan_ref` is the only authority:
 * a checkout cache ref can select a future plan and is unrelated to this live session.
 */
export function activeSessionPlanRef(ctx: ExtensionContext): PlanRef | null {
  try {
    const ref: unknown = rebuildWorkflowState(branchOf(ctx)).active_plan_ref;
    if (typeof ref !== "object" || ref === null) return null;
    const candidate = ref as Record<string, unknown>;
    for (const key of ["provider", "pr_id", "url"] as const) {
      const value = candidate[key];
      if (typeof value !== "string" || value.trim() === "") return null;
    }
    return ref as PlanRef;
  } catch {
    return null;
  }
}

/** Render the completion-gated turn that reorients the resumed agent from repository evidence. */
export function commitAndCompactContinuation(
  planRef: PlanRef | null,
  completion: CommitCompactCompletion,
): string {
  const provider = planRef?.provider ?? "";
  const planId = planRef?.pr_id ?? "";
  const planUrl = planRef?.url ?? "";
  const readCmd =
    planRef === null ? "" : planReadInstruction(planRef.provider, planRef.pr_id, planRef.url);
  return render("commit-and-compact-continuation.md", {
    provider,
    plan_id: planId,
    plan_url: planUrl,
    read_cmd: readCmd,
    is_github: provider === "github" ? "x" : "",
    committed: completion.outcome === "committed" ? "x" : "",
    clean: completion.outcome === "clean" ? "x" : "",
    read_only: completion.outcome === "read-only" ? "x" : "",
    commits: completion.outcome === "committed" ? (completion.commits ?? "") : "",
  });
}

/**
 * The invocation arms (gate → undeterminable → clean → dirty, in that order). Returns the
 * pending record only on the dirty/drive arm — every other arm resolves immediately.
 */
export function startCommitAndCompact(
  cwd: string,
  gateActive: boolean,
  io: CommitCompactIo,
): PendingCompact | null {
  if (gateActive) {
    io.report("info", "read-only session — nothing to commit; compacting…");
    io.compact(DIRECT_COMPACT_INSTRUCTIONS, { outcome: "read-only" });
    return null;
  }
  const dirty = worktreeDirty(cwd);
  if (dirty === null) {
    // Fail-safe: never compact when uncommitted work might exist.
    io.report(
      "warning",
      "cannot determine the git worktree state — compaction skipped; run /compact to compact anyway.",
    );
    return null;
  }
  if (!dirty) {
    io.report("info", "worktree clean — nothing to commit; compacting…");
    io.compact(DIRECT_COMPACT_INSTRUCTIONS, { outcome: "clean" });
    return null;
  }
  io.report("info", "driving a commit of the work completed so far…");
  const headBefore = headSha(cwd);
  io.send(commitAndCompactGuidance());
  return { cwd, headBefore };
}

/**
 * The settle arms: compact only when HEAD actually advanced past the invocation-time sha;
 * otherwise (model declined / commit failed / HEAD unreadable) warn and skip — same fail-safe.
 */
export function settleCommitAndCompact(pending: PendingCompact, io: CommitCompactIo): void {
  const headNow = headSha(pending.cwd);
  if (headNow === null || headNow === pending.headBefore) {
    io.report(
      "warning",
      "no commit was made — compaction skipped; run /compact to compact anyway.",
    );
    return;
  }
  io.report("info", "committed — compacting the session…");
  const commits = commitsSince(pending.cwd, pending.headBefore);
  io.compact(compactInstructions(commits), { outcome: "committed", commits });
}

/** Register the `/commit-and-compact` command + its one-shot `agent_settled` consumer. */
export function registerCommitAndCompact(pi: ExtensionAPI, gating: ToolGating): void {
  let pending: PendingCompact | null = null;

  const ioFor = (ctx: ExtensionContext): CommitCompactIo => ({
    report: (severity, message) => {
      report(ctx, "commit-and-compact", severity, message);
    },
    send: (guidance) => {
      // The trigger lets repos bind a skill via `[[bindings]]`; drive unconditionally — report()
      // already carries the headless stderr fallback.
      pi.sendUserMessage(guidance + bindingSuffix(ctx.cwd, "command:commit-and-compact"));
    },
    compact: (customInstructions, completion) => {
      // Render while the command/event context is current. Manual compaction stays in the same
      // AgentSession + extension runner, so onComplete may use captured `pi`; it must not read
      // `ctx` or recompute session/filesystem state after compaction.
      const continuation = commitAndCompactContinuation(activeSessionPlanRef(ctx), completion);
      ctx.compact({
        customInstructions,
        onComplete: () => {
          try {
            // Optionless on purpose: resume immediately under the active stage's own bindings.
            pi.sendUserMessage(continuation);
          } catch (error) {
            console.error(`perk: commit-and-compact — continuation dispatch failed — ${error}`);
          }
        },
        onError: (error) => {
          console.error(`perk: commit-and-compact — compaction failed — ${error}`);
        },
      });
    },
  });

  pi.on("agent_settled", async (_event, ctx) => {
    if (pending === null) return;
    const record = pending;
    pending = null; // consume-then-clear: the record is strictly one-shot
    try {
      settleCommitAndCompact(record, ioFor(ctx));
    } catch (error) {
      console.error(`perk: commit-and-compact — settle handling failed — ${error}`);
    }
  });

  registerPerkCommand(pi, "commit-and-compact", {
    description:
      "Commit the work completed so far (a driven model turn stages and writes the message), " +
      "then compact the session. Clean or read-only sessions compact immediately; if no commit " +
      "results, compaction is skipped.",
    handler: async (_args, ctx) => {
      pending = startCommitAndCompact(ctx.cwd, gating.isActive(), ioFor(ctx));
    },
  });
}
