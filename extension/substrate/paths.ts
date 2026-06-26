// perk-owned dot-directory path construction — the TS twin of perk/substrate/paths.py
// (contracts.md §8.1).
//
// The sole construction site for the perk-owned config family (`perk.toml`/`perk.local.toml`) and
// the perk dir. The workflow family lives in the established cache seam (substrate/cache.ts's
// `workflowDir`); together these two modules own every perk-owned `.pi/...` path on this plane.
// Objective #878 migrates each family to `.perk/` one phase at a time — redirecting a family is a
// single edit here. **Pi-native** `.pi/...` paths (`.pi/settings.json`, `.pi/agents/`, `.pi/npm`,
// `.pi/APPEND_SYSTEM.md`) are intentionally NOT owned here — `.pi/` is not generally perk-owned.
//
// No relative imports (only node builtins), so this module loads cleanly under `node --test`.

import { join } from "node:path";

export const CONFIG_FILENAME = "perk.toml";
export const LOCAL_CONFIG_FILENAME = "perk.local.toml";

/** The perk-owned dot-dir root (shared with Pi today). */
export function perkDir(cwd: string): string {
  return join(cwd, ".pi");
}

/** The single config-family redirection point (the file helpers derive from it). */
export function configDir(cwd: string): string {
  return join(cwd, ".pi");
}

/** The committed `perk.toml`. */
export function configFile(cwd: string): string {
  return join(configDir(cwd), CONFIG_FILENAME);
}

/** The gitignored `perk.local.toml`. */
export function localConfigFile(cwd: string): string {
  return join(configDir(cwd), LOCAL_CONFIG_FILENAME);
}
