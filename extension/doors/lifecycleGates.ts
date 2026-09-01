// Session-lifecycle gates (the interior safety primitive). One reusable dirty-repo guard on
// session_before_switch / session_before_fork that returns { cancel: true } when an *active perk
// workflow* has uncommitted changes — so a stage transition never silently orphans work. Plus the
// guard-only `/implement` command that *enforces* the implement stage's `warm: false` legality (the
// plan→implement jump requires fresh context; that is the cold door `perk implement`).
//
// pi.on("session_before_fork"/"...switch") handlers are fired by extensionRunner.emit({type,...})
// and their { cancel } result round-trips; the handler's
// pi.exec("git",["status","--porcelain"],{cwd}) resolves the session cwd.

import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "../substrate/cache.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { planReadInstruction, render } from "../substrate/prompts.ts";
import { type BranchSource, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";

// The planning stages whose sessions never legitimately run lifecycle doors. After an approved
// save, a still-live planning session holds TWO plan identities — the cwd binding (a positioned
// stacked session's predecessor checkout, read via readPlanRef(ctx.cwd)) and the just-saved plan
// on active_plan_ref — so a door invocation there could act on the predecessor. At the repo root
// the same invocation fails confusingly today; the refusal is honest in both shapes.
const PLANNING_STAGES = new Set(["plan", "objective-plan"]);

/**
 * The planning-stage lifecycle-door refusal (the shared first check of the warm /submit,
 * /address, /land, and /learn doors): when this session's workflow-state `stage` is a planning
 * stage, return the refusal message directing the human at the fresh-session implement door;
 * `null` otherwise (non-planning stages — and stage-less sessions — are unaffected). Fail-CLOSED
 * on an unreadable branch: without the state this guard cannot prove the session is not a
 * positioned planning session (whose cwd binding is the PREDECESSOR — the exact target it
 * protects), so an unreadable read refuses rather than letting the door act.
 */
export function planningStageRefusal(ctx: BranchSource, door: string): string | null {
  let stage: string | undefined;
  try {
    stage = rebuildWorkflowState(branchOf(ctx)).stage;
  } catch (error) {
    return (
      `${door} is unavailable: the session's workflow state could not be read ` +
      `(${String(error)}), so this cannot be proven not to be a planning session — ` +
      "retry, or implement the saved plan with `perk impl <N>` in a fresh session."
    );
  }
  if (stage === undefined || !PLANNING_STAGES.has(stage)) return null;
  return (
    `${door} is unavailable in a planning session (stage ${stage}): a planning session can ` +
    "hold two plan identities (its checkout's own binding and the just-saved plan) — " +
    "implement the saved plan with `perk impl <N>` in a fresh session instead."
  );
}

const DIRTY_MESSAGE = "uncommitted changes — commit or stash before switching/forking this stage.";
const HANDOFF_DIRTY_MESSAGE =
  "uncommitted changes — commit before a fresh-context /implement handoff (the plan is the " +
  "only artifact that crosses the boundary).";

/**
 * Pure gate policy: cancel a transition only inside an active perk workflow whose tree is
 * dirty. Kept separate from the `pi.exec` effect so the matrix is unit-testable offline.
 */
export function gateDecision(inputs: { active: boolean; dirty: boolean }): { cancel: boolean } {
  return { cancel: inputs.active && inputs.dirty };
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
  report(ctx, "lifecycle", "warning", DIRTY_MESSAGE); // fail-safe-headless: loud, still cancels
  return { cancel: true };
}

/**
 * The plan-read priming seed for a fresh implement session. The in-session twin of
 * `perk/run/launch.py`'s `_implement_prompt`: carry the plan FORWARD (read it from its canonical
 * source), never summarize it — the plan is the only artifact that crosses the boundary.
 *
 * The wording lives in the canonical template `prompts/stages/implement.md`, rendered by the shared
 * seam (contracts.md §8.31); branching stays in code — only the `read_cmd` var differs. This warm
 * handoff is now byte-identical to the cold/worker primer, so it carries the same "Progress
 * tracking:" tail (the prior shorter near-copy omission is removed).
 */
export function implementHandoffPrompt(ref: PlanRef): string {
  const readCmd = planReadInstruction(ref.provider, String(ref.pr_id), ref.url);
  return render("stages/implement.md", {
    provider: ref.provider,
    pr_id: String(ref.pr_id),
    url: ref.url,
    read_cmd: readCmd,
  });
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
