// Populate this process's tool catalog the way production does — by activating perk in a real
// (offline) session — for suites that read the derived views without driving a session.

import { loadPerkSession, type PerkSession, scaffoldRepo } from "./harness.ts";

/**
 * loadPerkSession with process.cwd() pointed at the scaffold for the load: provider vacating
 * (e.g. perk's plan surface under a foreign `[providers] plan`) resolves `process.cwd()` at
 * factory time, so running a suite from a repo with its own selections would otherwise leak into
 * what registers. Restores cwd before returning.
 */
export async function loadPerkSessionAt(
  cwd: string,
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> = {},
): Promise<PerkSession> {
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, ...opts });
  } finally {
    process.chdir(savedCwd);
  }
}

let loaded: Promise<void> | null = null;

/** Fill the catalog once per process (every registration is recorded on activation). */
export function ensureToolCatalog(): Promise<void> {
  loaded ??= (async () => {
    const h = await loadPerkSessionAt(scaffoldRepo());
    h.dispose();
  })();
  return loaded;
}
