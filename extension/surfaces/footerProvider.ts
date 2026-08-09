// The footer provider seam (INSTALL-SITE / runtime vacating). The footer is an interface
// seam (no durable artifact to bridge) with a runtime vacating mechanism:
// perk installs its own footer (`installPerkFooter`) inside `index.ts`'s `session_start` event
// handler, so under a foreign `[providers] footer` selection perk simply does NOT call
// `installPerkFooter` — a runtime guard at that single install site, keyed off `ctx.cwd`. That
// leaves the foreign footer (`pi-powerline-footer` or `pi-bar`) as the sole footer surface;
// perk's objective progress still reaches it automatically via the already-publishing
// single-value `perk` `setStatus` slot (both foreign footers render extension statuses), so the
// adapter is vacate-only (`adapter: null`, no shim, no injected context).
//
// This module reads config (via `resolveProviders`/`loadPerkConfig`) so it does NOT belong in the
// dependency-free `surfaces.ts`; it contains no rich-UI calls, so `surfacesGuard.test.ts` passes
// it cleanly. Mirror of `planMode.ts`'s `resolvedPlanProviderId` / `isPerkPlanReferenceSelected`.

import { loadPerkConfig } from "../substrate/config.ts";
import {
  loadProviders,
  PERK_FOOTER_PROVIDER_ID,
  resolveProviders,
} from "../substrate/providers.ts";

/**
 * The resolved `[providers] footer` selection id for `cwd`. Fail-safe to the perk-footer
 * reference: any load/resolution failure returns the reference id so perk keeps installing its
 * own footer — the default path is the hard guarantee. Mirror of `resolvedPlanProviderId`: the
 * catch narrows to genuine file-read/parse failures (the resolver is per-seam fail-open) and is
 * logged, never silent.
 */
export function resolvedFooterProviderId(cwd: string): string {
  try {
    return resolveProviders(loadPerkConfig(cwd).providers, loadProviders()).footer.id;
  } catch (error) {
    console.error(
      `perk: footer provider resolution failed — falling back to ${PERK_FOOTER_PROVIDER_ID}: ${error}`,
    );
    return PERK_FOOTER_PROVIDER_ID;
  }
}

/**
 * Whether perk's own footer reference is the selected footer provider for `cwd`. When a foreign
 * footer provider is selected via `[providers] footer`, perk vacates `installPerkFooter` so the
 * foreign footer is the sole footer surface.
 */
export function isPerkFooterReferenceSelected(cwd: string): boolean {
  return resolvedFooterProviderId(cwd) === PERK_FOOTER_PROVIDER_ID;
}
