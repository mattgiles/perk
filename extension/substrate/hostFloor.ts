// The TS plane's reader for the shared host floor (`shared/host-floor.yaml`, contracts.md §8.76).
//
// Twin of perk/substrate/host_floor.py: both planes parse the SAME bundled file (no codegen). This
// is the FOURTH parsed cross-plane contract (after registry.yaml, bindings.yaml and
// providers.yaml). The declaration names the minimum supported Pi and Node versions as semver
// floors (>=) — a minimum, never a pin.
//
// The Python plane is the authoritative validator (non-empty, parseable, a release); this side
// does a thin structural parse only (string checks). It is consumed by the two SDK-boundary entry
// bootstraps (`extension/index.ts`, `extension/workerMain.ts`) through `hostAdmission.ts`; the TS
// semver comparator is `semver.ts`.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "./miniYaml.ts";
import { sharedDir } from "./resources.ts";

export const HOST_FLOOR_FILENAME = "host-floor.yaml";

export interface HostFloor {
  schemaVersion: number;
  piMinVersion: string;
  nodeMinVersion: string;
}

function minVersion(record: Record<string, unknown>, host: string, source: string): string {
  const entry = record[host];
  const value =
    typeof entry === "object" && entry !== null
      ? (entry as Record<string, unknown>).min_version
      : undefined;
  if (typeof value !== "string") {
    throw new Error(`perk: ${source} has no ${host}.min_version`);
  }
  return value;
}

/** Parse host-floor YAML text. Throws on a non-mapping or a missing/non-string `min_version`. */
export function parseHostFloor(text: string, source: string): HostFloor {
  const data = parse(text) as unknown;
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error(`perk: ${source} is not a mapping`);
  }
  const record = data as Record<string, unknown>;
  return {
    schemaVersion: typeof record.schema_version === "number" ? record.schema_version : 0,
    piMinVersion: minVersion(record, "pi", source),
    nodeMinVersion: minVersion(record, "node", source),
  };
}

/** Parse the bundled `host-floor.yaml`. Throws on a missing file or unexpected shape. */
export function loadHostFloor(): HostFloor {
  const path = join(sharedDir(), HOST_FLOOR_FILENAME);
  return parseHostFloor(readFileSync(path, "utf8"), path);
}
