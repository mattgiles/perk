// Session-lifecycle gates (the interior safety primitive), the Pi registration half. One
// reusable dirty-repo guard on session_before_switch / session_before_fork that returns
// { cancel: true } when an *active perk workflow* has uncommitted changes — so a stage
// transition never silently orphans work. Plus the guard-only `/implement` command that
// *enforces* the implement stage's `warm: false` legality (the plan→implement jump requires
// fresh context; that is the cold door `perk implement`). The Pi-free policy these hooks apply
// (`implementHandoffPrompt`, `planningStageRefusal`) lives in `session/lifecycleGates.ts`.
//
// pi.on("session_before_fork"/"...switch") handlers are fired by extensionRunner.emit({type,...})
// and their { cancel } result round-trips; the handler's
// pi.exec("git",["status","--porcelain"],{cwd}) resolves the session cwd.

import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { implementHandoffPrompt } from "../../session/lifecycleGates.ts";
import type { PlanRef } from "../../substrate/cache.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { branchOf, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { report } from "../../surfaces/report.ts";

const DIRTY_MESSAGE = "uncommitted changes — commit or stash before switching/forking this stage.";
const HANDOFF_DIRTY_MESSAGE =
  "uncommitted changes — commit before a fresh-context /implement handoff (the plan is the " +
  "only artifact that crosses the boundary).";

/** True when this session is linked to a plan (a perk workflow is in progress). */
function workflowActive(ctx: ExtensionContext): boolean {
  return rebuildWorkflowState(branchOf(ctx)).active_plan_ref != null;
}

/**
 * The shared dirty-repo guard for switch/fork. Allows (returns undefined) outside a workflow or on
 * a clean tree; cancels with a loud, fail-safe-headless message on a dirty tree in a workflow. If
 * `git status` itself fails (e.g. not a repo) we allow — this is a hygiene guard, not a validator.
 */
async function guardTransition(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
): Promise<{ cancel: true } | undefined> {
  if (!workflowActive(ctx)) return undefined; // perk does not interfere with non-perk transitions
  const res = await pi.exec("git", ["status", "--porcelain"], { cwd: ctx.cwd });
  const dirty = res.code === 0 && res.stdout.trim().length > 0;
  if (!dirty) return undefined;
  report(ctx, "lifecycle", "warning", DIRTY_MESSAGE); // fail-safe-headless: loud, still cancels
  return { cancel: true };
}

/**
 * The warm `/implement`. It still NEVER performs the cross-worktree plan→implement
 * transition (that is structurally the Python cold door's job — no extension session API can change
 * cwd). Outside an impl context it refuses and points at `perk implement`. INSIDE an active
 * impl worktree (read-write + a linked plan-ref) it offers the in-process twin of the cold door: a
 * lossless `ctx.newSession` fresh-context handoff seeded with the plan-read priming (the plan, and
 * the worktree's materialized plan-ref, are the durable state — model-visible output stays capped).
 * Dirty-tree hygiene is gated manually here (belt-and-suspenders: `newSession` is a session-replace,
 * not a fork/switch, so it may bypass the `session_before_*` gate — we refuse on a dirty tree
 * either way), fail-safe-headless.
 */
function registerImplementGuard(pi: ExtensionAPI): void {
  registerPerkCommand(pi, "implement", {
    description:
      "Refresh implement context (in-worktree handoff); cross-worktree is `perk implement`.",
    handler: async (_args, ctx) => {
      const state = rebuildWorkflowState(branchOf(ctx));
      const ref = state.active_plan_ref;
      const inImpl = state.mode === "read-write" && ref != null;
      if (!inImpl) {
        report(
          ctx,
          "implement",
          "warning",
          "/implement is cold-only here — run `perk implement` from a shell for fresh context.",
        );
        return;
      }

      // Dirty-tree gate (manual; see the doc comment). Refuse the handoff with uncommitted work.
      const status = await pi.exec("git", ["status", "--porcelain"], { cwd: ctx.cwd });
      if (status.code === 0 && status.stdout.trim().length > 0) {
        report(ctx, "implement", "warning", HANDOFF_DIRTY_MESSAGE);
        return;
      }

      const commandCtx = ctx as ExtensionCommandContext;
      if (typeof commandCtx.newSession !== "function") {
        report(
          ctx,
          "implement",
          "warning",
          "a fresh-context /implement handoff needs an interactive session.",
        );
        return;
      }

      const prompt = implementHandoffPrompt(ref as PlanRef);
      const parentSession = ctx.sessionManager.getSessionFile() ?? undefined;
      const result = await commandCtx.newSession({
        parentSession,
        withSession: async (fresh) => {
          await fresh.sendUserMessage(prompt);
        },
      });

      // Verify + cap model-visible output (the full state lives in the worktree + the plan issue).
      if (result.cancelled) {
        report(ctx, "implement", "info", "/implement handoff cancelled — staying in this session.");
        return;
      }
      report(
        ctx,
        "implement",
        "info",
        `fresh implement session started for plan #${(ref as PlanRef).pr_id} — the plan is carried forward, not summarized.`,
      );
    },
  });
}

/** Register the dirty-repo lifecycle gate (switch + fork) and the guard-only `/implement`. */
export function registerLifecycleGates(pi: ExtensionAPI): void {
  pi.on("session_before_fork", async (_event, ctx) => guardTransition(pi, ctx));
  pi.on("session_before_switch", async (_event, ctx) => guardTransition(pi, ctx));
  registerImplementGuard(pi);
}
