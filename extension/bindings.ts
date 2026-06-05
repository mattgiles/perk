// The TS plane's reader for the shared skill-binding set (`shared/bindings.yaml`).
//
// Twin of perk/bindings.py: both planes parse the SAME bundled file (no codegen). This is
// the SECOND parsed cross-plane contract (the first being registry.yaml). A binding maps a
// `trigger` ("<kind>:<id>", kind ∈ {stage, command}) to a `skill` plus a per-binding
// delivery `mode` (nudge/transclude).
//
// The Python CLI is the authoritative validator (perk/bindings.py); this side does a thin
// structural parse only — no deep content validation here. This node (1.1) ships the seam
// with no consumer: the resolver is Node 1.2; delivery is Nodes 2.1/2.2.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import { sharedDir } from "./resources.ts";

export interface SkillBinding {
  trigger: string;
  kind: string;
  targetId: string;
  skill: string;
  mode: string;
}

export const BINDING_TRIGGER_KINDS = ["stage", "command"] as const;
export const BINDING_MODES = ["nudge", "transclude"] as const;

/** Split a `"<kind>:<id>"` trigger on the first `:`. No colon -> `["", ""]`. */
function splitTrigger(trigger: string): [string, string] {
  const idx = trigger.indexOf(":");
  if (idx === -1) return ["", ""];
  return [trigger.slice(0, idx), trigger.slice(idx + 1)];
}

/** Parse the bundled `bindings.yaml`. Throws on a missing file or unexpected shape. */
export function loadDefaultBindings(): SkillBinding[] {
  const path = join(sharedDir(), "bindings.yaml");
  const data = parse(readFileSync(path, "utf8")) as unknown;

  if (typeof data !== "object" || data === null) {
    throw new Error(`perk: ${path} is not a mapping`);
  }
  const record = data as Record<string, unknown>;
  const bindings = record.bindings;
  if (!Array.isArray(bindings)) {
    throw new Error(`perk: ${path} has no bindings`);
  }

  return bindings.map((raw) => {
    const entry = raw as Record<string, unknown>;
    const trigger = typeof entry.trigger === "string" ? entry.trigger : "";
    const [kind, targetId] = splitTrigger(trigger);
    return {
      trigger,
      kind,
      targetId,
      skill: typeof entry.skill === "string" ? entry.skill : "",
      mode: typeof entry.mode === "string" ? entry.mode : "",
    };
  });
}
