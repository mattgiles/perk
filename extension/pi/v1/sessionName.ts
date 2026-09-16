// The v1 Pi binding for perk-owned session names (contracts.md §8.71(h)): composes the
// `SessionNamePorts` slice over the real `pi`/`ctx` (branch → rebuild → plain
// `perk:workflow-state` append → Pi's `getSessionName`/`setSessionName`), runs the Pi-free core
// (`session/sessionName.ts`), and renders ONLY the `failed` outcome through `report()` — every
// other outcome is silent (no toast, no transcript line): names are best-effort metadata.
//
// The `session_start` hook and the later draft/save refreshes both flow through this one
// binding, so the Pi effects a naming refresh may perform are composed in exactly one place.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  type HintPolicy,
  type NamingHints,
  refreshSessionName,
  type SessionNameOutcome,
} from "../../session/sessionName.ts";
import {
  type BranchSource,
  branchOf,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
} from "../../substrate/workflowState.ts";
import { type ReportTarget, report } from "../../surfaces/report.ts";

/** The structural `pi` slice the binding needs (the real ExtensionAPI satisfies it). */
export type SessionNamePi = Pick<ExtensionAPI, "appendEntry" | "getSessionName" | "setSessionName">;

/**
 * The structural `ctx` slice the binding needs — the branch source plus the report target (the
 * real ExtensionContext satisfies both, as the `branchOf(ctx)` / `report(ctx, …)` precedents).
 */
export type SessionNameCtx = BranchSource & ReportTarget;

/**
 * Refresh the perk-owned session name over the live Pi session. `failed` is reported as one
 * warning (`{ alsoLog: true }` — headless always logs; the flag adds the RPC-with-UI stderr
 * mirror like the startup neighbors); every other outcome is silent. Returns the outcome for the
 * caller's own bookkeeping (the hook ignores it).
 */
export function refreshSessionNameV1(
  pi: SessionNamePi,
  ctx: SessionNameCtx,
  input: { hints: NamingHints; policy: HintPolicy },
): SessionNameOutcome {
  const outcome = refreshSessionName(
    {
      branch: () => branchOf(ctx),
      rebuild: () => rebuildWorkflowState(branchOf(ctx)),
      append: (data) => pi.appendEntry(WORKFLOW_STATE_TYPE, data),
      getSessionName: () => pi.getSessionName(),
      setSessionName: (name) => pi.setSessionName(name),
    },
    input,
  );
  if (outcome.status === "failed") {
    report(
      ctx,
      "session name",
      "warning",
      `could not refresh the session name — ${outcome.problem}`,
      {
        alsoLog: true,
      },
    );
  }
  return outcome;
}
