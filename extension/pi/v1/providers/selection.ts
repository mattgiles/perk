// The plan-provider selection probes — a LEAF module (imports substrate only) so the plan
// installer (`pi/v1/plan.ts`) and the provider adapters (`plannotator.ts`/`tombell.ts`) stay
// acyclic: every consumer reads the resolved `[providers] plan` selection through these probes,
// none through each other.

import { loadPerkConfig } from "../../../substrate/config.ts";
import {
  loadProviders,
  PERK_PLAN_PROVIDER_ID,
  PLANNOTATOR_PLAN_PROVIDER_ID,
  resolveProviders,
  TOMBELL_PLAN_PROVIDER_ID,
} from "../../../substrate/providers.ts";

/**
 * The resolved `[providers] plan` selection id for `cwd`, read fresh per-event (no static state —
 * the same per-event-read shape the context builders use). Fail-safe to the perk-plan
 * reference: any load/resolution failure returns the reference id so perk's own plan mode keeps
 * working — the default path is the hard guarantee. With the resolver's per-seam fail-open
 * fallbacks this catch narrows to genuine file-read/parse failures — logged loudly (consoleCapture
 * routes it into the session log), never swallowed: a silent catch here once masked a
 * version-skew throw and silently swapped the review surface to first-party.
 */
export function resolvedPlanProviderId(cwd: string): string {
  try {
    return resolveProviders(loadPerkConfig(cwd).providers, loadProviders()).plan.id;
  } catch (error) {
    console.error(
      `perk: plan provider resolution failed — falling back to ${PERK_PLAN_PROVIDER_ID}: ${error}`,
    );
    return PERK_PLAN_PROVIDER_ID;
  }
}

/** Whether the foreign `plannotator-plan` provider is the selected plan provider for `cwd`. */
export function isPlannotatorPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === PLANNOTATOR_PLAN_PROVIDER_ID;
}

/** Whether the foreign `tombell-plan` provider is the selected plan provider for `cwd`. */
export function isTombellPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === TOMBELL_PLAN_PROVIDER_ID;
}
