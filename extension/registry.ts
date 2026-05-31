// The TS plane's reader for the shared stage registry (`shared/registry.yaml`).
//
// Twin of perk/registry.py: both planes parse the SAME bundled file (no codegen, Q6).
// In Phase 0 the extension only needs to prove it can parse its bundled copy; the
// extension drives in-session transitions from the registry in Phase 1+. The Python
// CLI is the authoritative validator (`perk registry check`); this side does a thin
// structural assertion.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import { sharedDir } from "./resources.ts";

export interface RegistryStage {
  id: string;
  command: string;
  doors: Record<string, boolean>;
  predecessors: string[];
  successors: string[];
}

export interface Registry {
  schemaVersion: number;
  stages: RegistryStage[];
}

/** Parse the bundled `registry.yaml`. Throws on a missing file or unexpected shape. */
export function loadRegistry(): Registry {
  const path = join(sharedDir(), "registry.yaml");
  const data = parse(readFileSync(path, "utf8")) as unknown;

  if (typeof data !== "object" || data === null) {
    throw new Error(`perk: ${path} is not a mapping`);
  }
  const record = data as Record<string, unknown>;
  const stages = record.stages;
  if (!Array.isArray(stages) || stages.length === 0) {
    throw new Error(`perk: ${path} has no stages`);
  }

  return {
    schemaVersion: typeof record.schema_version === "number" ? record.schema_version : 0,
    stages: stages.map((raw) => raw as RegistryStage),
  };
}
