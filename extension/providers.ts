// The TS plane's reader for the shared provider-selection supported set (`shared/providers.yaml`).
//
// Twin of perk/providers.py: both planes parse the SAME bundled file (no codegen). This is the
// THIRD parsed cross-plane contract (after registry.yaml and bindings.yaml). It is the SUPPORTED
// SET — the catalog of plan/todo providers perk knows how to wire — distinct from the per-repo
// SELECTION (the flat `[providers]` table in .pi/perk.toml).
//
// The Python CLI is the authoritative validator (perk/providers.py); this side does a thin
// structural parse only — no deep content validation here. This node (2.1) ships the shape-only
// loader with no TS consumer: runtime consumption of the selection (perk's plan/todo stepping
// aside when a foreign provider is selected) is Nodes 2.2/3.1.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import { sharedDir } from "./resources.ts";

export interface Provider {
  id: string;
  seam: string;
  package: string | null;
  adapter: string | null;
  default: boolean;
  packageFilter?: Record<string, unknown>;
}

export const PROVIDER_SEAMS = ["plan", "todo"] as const;

/** Parse the bundled `providers.yaml`. Throws on a missing file or unexpected shape. */
export function loadProviders(): Provider[] {
  const path = join(sharedDir(), "providers.yaml");
  const data = parse(readFileSync(path, "utf8")) as unknown;

  if (typeof data !== "object" || data === null) {
    throw new Error(`perk: ${path} is not a mapping`);
  }
  const record = data as Record<string, unknown>;
  const providers = record.providers;
  if (!Array.isArray(providers)) {
    throw new Error(`perk: ${path} has no providers`);
  }

  return providers.map((raw) => {
    const entry = raw as Record<string, unknown>;
    const packageFilter = entry.package_filter;
    const provider: Provider = {
      id: typeof entry.id === "string" ? entry.id : "",
      seam: typeof entry.seam === "string" ? entry.seam : "",
      package: typeof entry.package === "string" ? entry.package : null,
      adapter: typeof entry.adapter === "string" ? entry.adapter : null,
      default: entry.default === true,
    };
    if (typeof packageFilter === "object" && packageFilter !== null) {
      provider.packageFilter = packageFilter as Record<string, unknown>;
    }
    return provider;
  });
}
