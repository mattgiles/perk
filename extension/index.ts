// perk Pi extension — the session *interior*.
//
// T3 adds the tier-3 session-state mechanics (contracts.md §8.2/§8.3): claim PERK_RUN_ID on
// `session_start` (verified-linkage, Q3), rebuild `perk:workflow-state` on `session_start` AND
// `session_tree` (per-field LWW), and derive a child run_id on fork. No workflow semantics yet.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAddress } from "./address.ts";
import {
  ensureRunScratch,
  markHandoffConsumed,
  readHandoff,
  readPlanRef,
  setMarker,
} from "./cache.ts";
import { registerCheckpoints } from "./checkpoints.ts";
import { registerCiExecutor } from "./ciExecutor.ts";
import { registerLand } from "./land.ts";
import { registerLearn } from "./learn.ts";
import { registerLearnDocs } from "./learnDocs.ts";
import { registerLifecycleGates } from "./lifecycleGates.ts";
import { registerObjective } from "./objective.ts";
import { registerObjectivePlan } from "./objectivePlan.ts";
import { registerPlanMode } from "./planMode.ts";
import { registerPlanSave } from "./planSave.ts";
import { registerReady } from "./ready.ts";
import { loadRegistry, type Registry, stageConsumesPlanRef } from "./registry.ts";
import { perkVersion, sharedDir } from "./resources.ts";
import { registerSubmit } from "./submit.ts";
import { registerToolGating } from "./toolGating.ts";
import {
  type BranchEntry,
  decideClaim,
  planRefsEqual,
  rebuildWorkflowState,
  resolveRunStage,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "./workflowState.ts";

// Cross-plane proof marker (TS writes via cache.ts; the Python helper reads it — gate check 3).
const T3_MARKER = "t3-extension-cache-write";

function writeT3Sentinel(cwd: string, source: string, state: WorkflowState): void {
  try {
    const dir = join(cwd, ".pi", "workflow");
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, ".perk-t3.json"),
      `${JSON.stringify({
        source,
        run_id: state.run_id ?? null,
        mode: state.mode ?? null,
        predecessor: state.predecessor ?? null,
        pi_session_id: state.pi_session_id ?? null,
        active_plan_ref: state.active_plan_ref ?? null,
      })}\n`,
      "utf8",
    );
  } catch {
    // never throw from a probe
  }
}

export default function (pi: ExtensionAPI) {
  const version = perkVersion();

  // P2.T1 — the read-only tool-gating primitive. Attaches to perk:workflow-state.mode; synced on
  // both session_start AND session_tree below. enter/exit are the surface T2/T5 consume.
  const gating = registerToolGating(pi);

  // P2.T2a — perk-owned plan mode: the `/plan` + Ctrl+Alt+P + `--plan` toggle surface over T1's
  // gate, plus the plan-authoring context injection. perk owns plan mode end-to-end now (the
  // borrowed `@tombell/pi-plan` is retired).
  registerPlanMode(pi, gating);
  let sharedOk = false;
  try {
    sharedDir();
    sharedOk = true;
  } catch {
    sharedOk = false;
  }

  let registry: Registry | null = null;
  let registryStages = -1;
  try {
    registry = loadRegistry();
    registryStages = registry.stages.length;
  } catch {
    registry = null;
    registryStages = -1;
  }
  const registryOk = registryStages > 0;

  pi.on("session_start", async (_event, ctx) => {
    const branchEntries = () => ctx.sessionManager.getBranch() as unknown as BranchEntry[];
    const sessionFile = ctx.sessionManager.getSessionFile();
    const currentSessionId = sessionFile ? basename(sessionFile) : null;

    // Headless-safe linkage failure: loud (notify if UI + stderr), non-fatal, leaves unclaimed.
    const reportError = (message: string) => {
      const full = `perk: workflow-state linkage error — ${message}`;
      if (ctx.hasUI) ctx.ui.notify(full, "error");
      console.error(full);
    };

    const decision = decideClaim({
      state: rebuildWorkflowState(branchEntries()),
      currentSessionId,
      envRunId: process.env.PERK_RUN_ID ?? null,
      cwd: ctx.cwd,
    });

    let resolved: WorkflowState = decision.action === "claim" ? {} : decision.state;

    if (decision.action === "claim") {
      // Cold claim — establish before consume (Q3 strict).
      const handoff = readHandoff(ctx.cwd, decision.runId);
      if (handoff === null || handoff.run_id !== decision.runId) {
        reportError(`handoff missing or mismatched for run ${decision.runId}`);
      } else {
        const data: WorkflowState = {
          run_id: decision.runId,
          pi_session_id: currentSessionId ?? undefined,
          mode: handoff.mode,
        };
        pi.appendEntry(WORKFLOW_STATE_TYPE, data);
        if (rebuildWorkflowState(branchEntries()).run_id !== decision.runId) {
          reportError(`read-back failed for run ${decision.runId}`); // do NOT consume
        } else {
          markHandoffConsumed(ctx.cwd, decision.runId, {
            piSessionId: currentSessionId ?? undefined,
          });
          resolved = data;
        }
      }
    } else if (decision.action === "fork") {
      // Inherited a run_id from a different session file → isolate the child's scratch.
      ensureRunScratch(ctx.cwd, decision.childRunId);
      const data: WorkflowState = {
        run_id: decision.childRunId,
        pi_session_id: currentSessionId ?? undefined,
        predecessor: decision.parentRunId,
        mode: decision.state.mode,
      };
      pi.appendEntry(WORKFLOW_STATE_TYPE, data);
      resolved = data;
    }

    // Plan-ref linkage (turn-2b §6, stage-gated #43): reconcile the cache.plan-ref file into
    // active_plan_ref — but ONLY when the launched stage *consumes* the ref (its registry
    // `requires`/`reads` list `cache.plan-ref`). That is the worktree binding stages
    // (implement/submit/address/land/learn); the root `worktree: none` stages
    // (plan/objective-plan/save) must NOT inherit the root *selector* into a fresh planning
    // session. Idempotent by (provider, pr_id), strict read-back, headless-safe. Runs after the
    // run_id claim so the run is settled first; the two append independent LWW fields.
    // Reload/fork/tree (no launched stage) rely on the LWW rebuild — never re-read the file.
    const linked = rebuildWorkflowState(branchEntries()).active_plan_ref ?? null;
    const runStage = resolveRunStage(decision, ctx.cwd);
    // Registry-missing is permissive when a stage is present, to preserve implement linkage.
    const consumesPlanRef =
      runStage !== null && (registry === null || stageConsumesPlanRef(registry, runStage));
    if (consumesPlanRef) {
      const cachedRef = readPlanRef(ctx.cwd);
      if (cachedRef !== null) {
        if (planRefsEqual(linked, cachedRef)) {
          resolved = { ...resolved, active_plan_ref: linked };
        } else {
          pi.appendEntry(WORKFLOW_STATE_TYPE, { active_plan_ref: cachedRef });
          if (
            planRefsEqual(rebuildWorkflowState(branchEntries()).active_plan_ref ?? null, cachedRef)
          ) {
            resolved = { ...resolved, active_plan_ref: cachedRef };
          } else {
            reportError(`plan-ref read-back failed for ${cachedRef.provider}:${cachedRef.pr_id}`);
          }
        }
      } else if (linked !== null) {
        resolved = { ...resolved, active_plan_ref: linked };
      }
    } else if (linked !== null) {
      // Non-consuming stage (or no launched stage): preserve any already-linked ref via LWW,
      // but NEVER read the cache file — the root selector must not leak in.
      resolved = { ...resolved, active_plan_ref: linked };
    }

    // Reapply the read-only allowlist from the resolved mode. Fail-closed: if the sync throws,
    // leave the gate as-is (a failed sync never opens it).
    try {
      gating.syncFromState(resolved.mode);
    } catch (error) {
      console.error(`perk: tool-gating sync failed on session_start — ${error}`);
    }

    if (ctx.hasUI) {
      ctx.ui.notify(`perk ${version} loaded`, "info");
    }

    if (process.env.PERK_SELFCHECK) {
      try {
        const dir = join(ctx.cwd, ".pi", "workflow");
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
        // T1/T2 sentinel (unchanged — those gates parse this line).
        writeFileSync(
          join(dir, ".perk-loaded"),
          `perk ${version} loaded; shared=${sharedOk ? "ok" : "miss"}; ` +
            `registry=${registryOk ? "ok" : "miss"} stages=${registryStages}; hasUI=${ctx.hasUI}\n`,
        );
        writeT3Sentinel(ctx.cwd, decision.source, resolved);
        setMarker(ctx.cwd, T3_MARKER); // cross-plane cache write (gate check 3)
      } catch {
        // never throw from a load probe
      }
    }
  });

  // Non-negotiable: rebuild on branch navigation too, or state goes stale after /tree (§8.3).
  pi.on("session_tree", async (_event, ctx) => {
    const state = rebuildWorkflowState(ctx.sessionManager.getBranch() as unknown as BranchEntry[]);
    // Non-negotiable: re-sync the gate on tree navigation too (mode is per-field LWW). Fail-closed.
    try {
      gating.syncFromState(state.mode);
    } catch (error) {
      console.error(`perk: tool-gating sync failed on session_tree — ${error}`);
    }
    if (process.env.PERK_SELFCHECK) {
      writeT3Sentinel(ctx.cwd, "tree", state);
    }
  });

  // Warm door: the `plan_save` tool + `/plan-save` command (turn-3). Takes `gating` for D1a:
  // a successful command-path save exits read-only mode (the read-only → read-write boundary).
  registerPlanSave(pi, gating);

  // Lifecycle gates: the dirty-repo switch/fork guard + the guard-only `/implement` (turn-4b).
  registerLifecycleGates(pi);

  // Warm door: the `submit` tool + `/submit` command (turn-5a).
  registerSubmit(pi);

  // P2.T8a — the warm `ready` door: the deliberate draft→ready review gate (submit keeps draft).
  registerReady(pi);

  // Warm doors: `land` (turn-5b) merges + sets pending-learn; `learn` clears it (TS-only).
  registerLand(pi);
  registerLearn(pi);

  // P2.T7 — the warm `/address` review loop: the `resolve_review_threads` tool + `/address`
  // command. Classify-then-act (the verbose feedback fetch + classification runs in an isolated
  // spawned child; the parent fixes actionable items and batch-resolves the threads).
  registerAddress(pi);

  // P2.T5 — the read-only CI executor: the `run_ci` tool + `/ci` command + `--allow-project-ci`
  // flag. Runs the project's `[ci]` named checks deterministically and reports (never fixes/loops).
  registerCiExecutor(pi);

  // P2.T2c — perk-owned checkpoints: seed from the plan body's `## Steps`, advance on `[DONE:n]`.
  // Inert when no step list is present (perk plans are prose). Own `session_start`/`session_tree`/
  // `turn_end` handlers (coexist with the others; pi.on supports multiple handlers per event).
  registerCheckpoints(pi);

  // P2.T9 — the objective substrate: `/objective` set/clear, budget accounting, threshold
  // compaction, all keyed off the now-live `active_objective`. Inert when no objective is active.
  // (The deterministic objective mechanics live in the Python plane: `perk objective …`.)
  registerObjective(pi);

  // P2.T10 — the objective plan factory's warm transition surface: the `objective_node` bounded
  // tool (delegates to the Python cold door; `status:"done"` requires a completion audit) + the
  // `/objective-plan` command (select the next node and author a bounded plan).
  registerObjectivePlan(pi);

  // hop-2 — the learned-docs plan factory's warm surface: the `/learn-docs` command gathers open
  // perk:learn issues into an inbox (via the `perk learn-docs --gather` cold door) and injects the
  // factory guidance so the model authors a docs/learned consolidation plan (no model tool).
  registerLearnDocs(pi);

  pi.registerCommand("perk-selfcheck", {
    description: "Report that the perk extension is loaded.",
    handler: async (_args, ctx) => {
      ctx.ui.notify(
        `perk ${version} loaded; shared=${sharedOk ? "ok" : "miss"}`,
        sharedOk ? "info" : "warning",
      );
    },
  });
}
