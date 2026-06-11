// perk Pi extension — the session *interior*.
//
// T3 adds the tier-3 session-state mechanics (contracts.md §8.2/§8.3): claim PERK_RUN_ID on
// `session_start` (verified-linkage, Q3), rebuild `perk:workflow-state` on `session_start` AND
// `session_tree` (per-field LWW), and derive a child run_id on fork. No workflow semantics yet.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAddress } from "./address.ts";
import { registerAskUser } from "./askUser.ts";
import { registerBindingDelivery } from "./bindingDelivery.ts";
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
import { registerObjectiveAuthor } from "./objectiveAuthor.ts";
import { registerObjectivePlan } from "./objectivePlan.ts";
import { registerObjectiveSave } from "./objectiveSave.ts";
import { registerPlanAdapterPlannotator } from "./planAdapterPlannotator.ts";
import { registerPlanAdapterTombell } from "./planAdapterTombell.ts";
import { registerPlanMode } from "./planMode.ts";
import { registerPlanSave } from "./planSave.ts";
import { registerPrReview } from "./prReview.ts";
import { registerReady } from "./ready.ts";
import { loadRegistry, type Registry, stageConsumesPlanRef } from "./registry.ts";
import { report } from "./report.ts";
import { perkVersion, sharedDir } from "./resources.ts";
import { registerSelfcheck } from "./selfcheck.ts";
import { registerSubmit } from "./submit.ts";
import { registerTodoAdapterJuicesharp } from "./todoAdapterJuicesharp.ts";
import { registerToolGating } from "./toolGating.ts";
import {
  appendWorkflowState,
  branchOf,
  decideClaim,
  planRefsEqual,
  rebuildWorkflowState,
  resolveRunStage,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "./workflowState.ts";

// Cross-plane proof marker (TS writes via cache.ts; the Python helper reads it — gate check 3).
const T3_MARKER = "t3-extension-cache-write";

function writeT3Sentinel(
  cwd: string,
  source: string,
  state: WorkflowState,
  runMode: string | null,
): void {
  try {
    const dir = join(cwd, ".pi", "workflow");
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, ".perk-t3.json"),
      `${JSON.stringify({
        source,
        // The launch *workflow* mode (read-only/read-write) — drives tool gating.
        run_id: state.run_id ?? null,
        mode: state.mode ?? null,
        // The Pi *run* mode (tui/rpc/json/print) — observability `hasUI` can't express. Distinct
        // from the workflow `mode` above; recorded straight from `ctx.mode`.
        run_mode: runMode,
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

  // Node 2.3 — the first 3rd-party plan adapter: a perk-owned, injection-only bridge that re-enables
  // `@tombell/pi-plan` as a real plan provider. Always registered, but INERT unless
  // `[providers] plan = "tombell-plan"`; it directs the foreign free-form prose `/plan` surface into
  // perk's canonical `plan_save` → `cache.plan-ref` contract. It needs no `gating` (Invariant 1: the
  // read-only gate stays perk's, engaged by the cold-door launch — the shim never arbitrates tools).
  registerPlanAdapterTombell(pi);

  // The second 3rd-party plan adapter — AUGMENT posture: `@plannotator/pi-extension` contributes
  // its browser plan-review UI via the `plan_review` bridge tool while perk's plan surface + gate
  // stay (planMode skips only `--plan`/`Ctrl+Alt+P` under this selection). Always registered, but
  // INERT unless `[providers] plan = "plannotator-plan"`. It needs no `gating` (Invariant 1: the
  // read-only gate stays perk's — the shim never arbitrates tools, and never saves anything).
  registerPlanAdapterPlannotator(pi);

  // P3.T2 — objective-author context injection (the objective mirror of plan mode's authoring
  // half). Keyed off (read-only gate AND stage === objective-author); planMode defers to it.
  registerObjectiveAuthor(pi, gating);
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
    const branchEntries = () => branchOf(ctx);
    const sessionFile = ctx.sessionManager.getSessionFile();
    const currentSessionId = sessionFile ? basename(sessionFile) : null;

    // Headless-safe linkage failure: loud (notify if UI + stderr), non-fatal, leaves unclaimed.
    const reportError = (message: string) => {
      report(ctx, "workflow-state linkage error", "error", message, { alsoLog: true });
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
          // Record the launched stage so the interior can tell e.g. objective-author from plan
          // (both are read-only) and inject the right authoring context (planMode vs objectiveAuthor).
          stage: handoff.stage,
        };
        const okAppend = appendWorkflowState(pi, ctx, {
          data,
          field: "run_id",
          expected: decision.runId,
          scope: "workflow-state linkage error",
          failure: `read-back failed for run ${decision.runId}`,
        });
        if (!okAppend) {
          // do NOT consume
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
          if (
            appendWorkflowState(pi, ctx, {
              data: { active_plan_ref: cachedRef },
              field: "active_plan_ref",
              expected: cachedRef,
              scope: "workflow-state linkage error",
              failure: `plan-ref read-back failed for ${cachedRef.provider}:${cachedRef.pr_id}`,
              equals: planRefsEqual,
            })
          ) {
            resolved = { ...resolved, active_plan_ref: cachedRef };
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
        writeT3Sentinel(ctx.cwd, decision.source, resolved, ctx.mode ?? null);
        setMarker(ctx.cwd, T3_MARKER); // cross-plane cache write (gate check 3)
      } catch {
        // never throw from a load probe
      }
    }
  });

  // Non-negotiable: rebuild on branch navigation too, or state goes stale after /tree (§8.3).
  pi.on("session_tree", async (_event, ctx) => {
    const state = rebuildWorkflowState(branchOf(ctx));
    // Non-negotiable: re-sync the gate on tree navigation too (mode is per-field LWW). Fail-closed.
    try {
      gating.syncFromState(state.mode);
    } catch (error) {
      console.error(`perk: tool-gating sync failed on session_tree — ${error}`);
    }
    if (process.env.PERK_SELFCHECK) {
      writeT3Sentinel(ctx.cwd, "tree", state, ctx.mode ?? null);
    }
  });

  // Warm door: the `plan_save` tool + `/plan-save` command (turn-3). Takes `gating` for D1a:
  // a successful command-path save exits read-only mode (the read-only → read-write boundary).
  registerPlanSave(pi, gating);

  // #187 — the universal `ask_user_question` tool: lets a model interactively ask the human a
  // clarifying question (free-text or multiple-choice). Registered in the factory so it exists
  // before the gate snapshots tools; its name is in READ_ONLY_TOOLS so it survives plan mode.
  registerAskUser(pi);

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

  // #175 — the warm `/pr-review` door: automated code review in a FRESH, isolated subagent that
  // POSTS its review to the PR (the deliberate departure from /address's read-only-child rule).
  registerPrReview(pi);

  // P2.T5 — the read-only CI executor: the `run_ci` tool + `/ci` command + `--allow-project-ci`
  // flag. Runs the project's `[ci]` named checks deterministically and reports (never fixes/loops).
  registerCiExecutor(pi);

  // P2.T2c — perk-owned checkpoints: seed from the plan body's `## Steps`, advance on `[DONE:n]`.
  // Inert when no step list is present (perk plans are prose). Own `session_start`/`session_tree`/
  // `turn_end` handlers (coexist with the others; pi.on supports multiple handlers per event).
  // Node 3.1 todo-seam deferral: perk is the reference todo provider (`perk-checkpoints`); these
  // runtime surfaces step aside when a foreign `[providers] todo` is selected (the todo-seam mirror
  // of planMode's plan-seam deferral) — silent on the event handlers, announced on `/checkpoints`.
  registerCheckpoints(pi);

  // Node 3.2 — the FIRST 3rd-party todo adapter (the todo-seam mirror of registerPlanAdapterTombell).
  // Injection-only: inert unless `[providers] todo = "juicesharp-todo"` is selected AND the session
  // is an active workflow. It carries perk's implement-progress discipline onto `@juicesharp/rpiv-
  // todo`'s checklist overlay (perk's own checkpoints deferred at Node 3.1). No `gating` argument —
  // the shim NEVER arbitrates tools (Invariant 1); no registration-time vacating (no command-name
  // collision on the todo seam, unlike the plan seam); never writes `perk:checkpoint`.
  registerTodoAdapterJuicesharp(pi);

  // P2.T9 — the objective substrate: `/objective` set/clear, budget accounting, threshold
  // compaction, all keyed off the now-live `active_objective`. Inert when no objective is active.
  // (The deterministic objective mechanics live in the Python plane: `perk objective …`.)
  registerObjective(pi);

  // P3.T2 — the warm `objective_save` door: the `objective_save` tool + `/objective-save` command
  // (the objective mirror of plan-save). Takes `gating` for the read-only → read-write boundary.
  registerObjectiveSave(pi, gating);

  // P2.T10 — the objective plan factory's warm transition surface: the `objective_node` bounded
  // tool (delegates to the Python cold door; `status:"done"` requires a completion audit) + the
  // `/objective-plan` command (select the next node and author a bounded plan).
  registerObjectivePlan(pi);

  // hop-2 — the learned-docs plan factory's warm surface: the `/learn-docs` command gathers open
  // perk:learn issues into an inbox (via the `perk learn docs --gather` cold door) and injects the
  // factory guidance so the model authors a docs/learned consolidation plan (no model tool).
  registerLearnDocs(pi);

  // Node 2.2 — warm-door skill-binding delivery: Mechanism A's `before_agent_start` injection of
  // the launched stage's user-originated bindings (+ the stale-context strip). Mechanism B (the
  // `command:<id>` suffix) is wired into the `/objective-reconcile` + `/learn-docs` guidance.
  registerBindingDelivery(pi);

  // `/perk-selfcheck` — the session-wiring verifier (turned from a liveness ping into a real check
  // that the converged ambient index reached `appendSystemPrompt` and the managed `AGENTS.md` block
  // reached `contextFiles`). doctor checks disk; selfcheck checks the prompt.
  registerSelfcheck(pi, { version, sharedOk });
}
