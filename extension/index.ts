// perk Pi extension — the session *interior*.
//
// T3 adds the tier-3 session-state mechanics (contracts.md §8.2/§8.3): claim PERK_RUN_ID on
// `session_start` (verified-linkage, Q3), rebuild `perk:workflow-state` on `session_start` AND
// `session_tree` (per-field LWW), and derive a child run_id on fork. No workflow semantics yet.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  ensureRunScratch,
  markHandoffConsumed,
  readHandoff,
  readPlanRef,
  setMarker,
} from "./cache.ts";
import { registerPlanSave } from "./planSave.ts";
import { loadRegistry } from "./registry.ts";
import { perkVersion, sharedDir } from "./resources.ts";
import {
  type BranchEntry,
  decideClaim,
  planRefsEqual,
  rebuildWorkflowState,
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
  let sharedOk = false;
  try {
    sharedDir();
    sharedOk = true;
  } catch {
    sharedOk = false;
  }

  let registryStages = -1;
  try {
    registryStages = loadRegistry().stages.length;
  } catch {
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

    // Plan-ref linkage (turn-2b §6): reconcile the cache.plan-ref file into active_plan_ref
    // — idempotent by (provider, pr_id), strict read-back, headless-safe. Runs after the
    // run_id claim so the run is settled first; the two append independent LWW fields.
    const cachedRef = readPlanRef(ctx.cwd);
    if (cachedRef !== null) {
      const linked = rebuildWorkflowState(branchEntries()).active_plan_ref ?? null;
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
    if (process.env.PERK_SELFCHECK) {
      writeT3Sentinel(ctx.cwd, "tree", state);
    }
  });

  // Warm door: the `plan_save` tool + `/plan-save` command (turn-3).
  registerPlanSave(pi);

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
