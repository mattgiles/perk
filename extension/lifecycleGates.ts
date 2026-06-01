// P1.T4b — session-lifecycle gates (the interior safety primitive; cli-vs-pi §4.1, pi
// best-practices §7). One reusable dirty-repo guard on session_before_switch / session_before_fork
// that returns { cancel: true } when an *active perk workflow* has uncommitted changes — so a stage
// transition never silently orphans work. Plus the guard-only `/implement` command that *enforces*
// the implement stage's `warm: false` legality (the plan→implement jump requires fresh context;
// that is the cold door `perk implement`, T4a).
//
// Spike S-B (turn-4 §3.5) verified: pi.on("session_before_fork"/"...switch") handlers are fired by
// extensionRunner.emit({type,...}) and their { cancel } result round-trips; the handler's
// pi.exec("git",["status","--porcelain"],{cwd}) resolves the session cwd.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type BranchEntry, rebuildWorkflowState } from "./workflowState.ts";

const DIRTY_MESSAGE =
  "perk: uncommitted changes — commit or stash before switching/forking this stage.";

/**
 * Pure gate policy (D6): cancel a transition only inside an active perk workflow whose tree is
 * dirty. Kept separate from the `pi.exec` effect so the matrix is unit-testable offline.
 */
export function gateDecision(inputs: { active: boolean; dirty: boolean }): { cancel: boolean } {
  return { cancel: inputs.active && inputs.dirty };
}

function branchOf(ctx: ExtensionContext): BranchEntry[] {
  return ctx.sessionManager.getBranch() as unknown as BranchEntry[];
}

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
  const active = workflowActive(ctx);
  if (!active) return undefined; // perk does not interfere with non-perk transitions
  const res = await pi.exec("git", ["status", "--porcelain"], { cwd: ctx.cwd });
  const dirty = res.code === 0 && res.stdout.trim().length > 0;
  if (!gateDecision({ active, dirty }).cancel) return undefined;
  if (ctx.hasUI) ctx.ui.notify(DIRTY_MESSAGE, "warning");
  else console.error(DIRTY_MESSAGE); // fail-safe-headless: loud, still cancels
  return { cancel: true };
}

/**
 * The guard-only warm `/implement` (D7). Never performs the plan→implement transition — it makes
 * `implement.doors.warm: false` enforced at the surface: continue if already implementing, else
 * point at the cold door. (Impl context ≈ read-write mode + a linked plan-ref.)
 */
function registerImplementGuard(pi: ExtensionAPI): void {
  pi.registerCommand("implement", {
    description: "Implement requires fresh context — use the cold door `perk implement`.",
    handler: async (_args, ctx) => {
      const state = rebuildWorkflowState(branchOf(ctx));
      const inImpl = state.mode === "read-write" && state.active_plan_ref != null;
      const message = inImpl
        ? "perk: already implementing — continue in this session."
        : "perk: /implement is cold-only — run `perk implement` from a shell for fresh context.";
      if (ctx.hasUI) ctx.ui.notify(message, inImpl ? "info" : "warning");
      else console.error(message);
    },
  });
}

/** Register the dirty-repo lifecycle gate (switch + fork) and the guard-only `/implement`. */
export function registerLifecycleGates(pi: ExtensionAPI): void {
  pi.on("session_before_fork", async (_event, ctx) => guardTransition(pi, ctx));
  pi.on("session_before_switch", async (_event, ctx) => guardTransition(pi, ctx));
  registerImplementGuard(pi);
}
