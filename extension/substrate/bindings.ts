// The TS plane's reader for the shared skill-binding set (`shared/bindings.yaml`).
//
// Twin of perk/substrate/bindings.py: both planes parse the SAME bundled file (no codegen). This is
// the SECOND parsed cross-plane contract (the first being registry.yaml). A binding maps a
// `trigger` ("<kind>:<id>", kind ∈ {stage, command}) to a `skill` plus a per-binding
// delivery `mode` (nudge/transclude).
//
// The Python CLI is the authoritative validator (perk/substrate/bindings.py); this side does a thin
// structural parse only — no deep content validation here. The binding set is CONSUMED: the
// resolver (`resolveBindings`) and warm-door delivery (`extension/substrate/bindingDelivery.ts`)
// are live.

import { readFileSync } from "node:fs";
import { join } from "node:path";
// Type-only import (config.ts value-imports this module; a value import here would cycle).
import type { TomlScalar } from "./config.ts";
import { parse } from "./miniYaml.ts";
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

/** One shape finding for a user binding (registry-free; mirror of Python's `Issue`). */
export interface BindingIssue {
  where: string;
  message: string;
}

/** The effective binding set after overlaying user bindings onto shipped defaults. */
export interface ResolvedBindings {
  bindings: SkillBinding[];
  issues: BindingIssue[];
}

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

/**
 * Parse `.perk/config.toml` `[[bindings]]` rows (scalar tables) into `SkillBinding`s. Tolerant like
 * the YAML reader: absent/ill-typed fields become empty strings so the *resolver* reports them.
 */
export function parseUserBindings(rows: Array<Record<string, TomlScalar>>): SkillBinding[] {
  return rows.map((row) => {
    const trigger = typeof row.trigger === "string" ? row.trigger : "";
    const [kind, targetId] = splitTrigger(trigger);
    return {
      trigger,
      kind,
      targetId,
      skill: typeof row.skill === "string" ? row.skill : "",
      mode: typeof row.mode === "string" ? row.mode : "",
    };
  });
}

/**
 * Shape issues for a *single* binding (skill/mode/trigger well-formedness). Registry-free —
 * target-existence is `doctor`'s job. Duplicate-trigger detection is the caller's.
 */
function bindingIssues(binding: SkillBinding): BindingIssue[] {
  const issues: BindingIssue[] = [];
  const where = binding.trigger || "bindings";

  if (!binding.skill) issues.push({ where, message: "missing `skill`" });
  if (!(BINDING_MODES as readonly string[]).includes(binding.mode)) {
    issues.push({ where, message: `\`mode\` must be one of ${BINDING_MODES.join(", ")}` });
  }

  if (!binding.trigger) {
    issues.push({ where: "bindings", message: "a binding is missing its `trigger`" });
  } else if (!binding.trigger.includes(":")) {
    issues.push({ where, message: "`trigger` must be of the form `<kind>:<id>`" });
  } else if (!(BINDING_TRIGGER_KINDS as readonly string[]).includes(binding.kind)) {
    issues.push({
      where,
      message: `\`trigger\` kind must be one of ${BINDING_TRIGGER_KINDS.join(", ")}`,
    });
  } else if (!binding.targetId) {
    issues.push({ where, message: "`trigger` has an empty `<id>`" });
  }

  return issues;
}

/** Return every shape issue across a user binding set (empty == valid); duplicates included. */
export function validateUserBindings(bindings: SkillBinding[]): BindingIssue[] {
  const issues: BindingIssue[] = [];
  const seen = new Set<string>();
  for (const binding of bindings) {
    issues.push(...bindingIssues(binding));
    if (binding.trigger) {
      if (seen.has(binding.trigger)) {
        issues.push({ where: binding.trigger, message: "duplicate `trigger`" });
      }
      seen.add(binding.trigger);
    }
  }
  return issues;
}

/**
 * Overlay user bindings onto shipped defaults (trigger-keyed; pure). Defaults are trusted (not
 * re-validated). Each user binding is applied iff it is shape-valid AND its trigger was not already
 * applied by an earlier user binding; otherwise it is dropped and its issue recorded. An applied
 * binding replaces in place the default with the same trigger, or appends at a new trigger — so the
 * resolved set has unique triggers by construction. Target-existence stays `doctor`.
 */
export function resolveBindings(
  userBindings: SkillBinding[],
  defaults: SkillBinding[] = loadDefaultBindings(),
): ResolvedBindings {
  const resolved = [...defaults];
  const index = new Map<string, number>();
  for (let i = 0; i < resolved.length; i++) {
    const entry = resolved[i];
    if (entry) index.set(entry.trigger, i);
  }
  const issues: BindingIssue[] = [];
  const applied = new Set<string>();

  for (const binding of userBindings) {
    const shapeIssues = bindingIssues(binding);
    if (shapeIssues.length > 0) {
      issues.push(...shapeIssues);
      continue;
    }
    if (applied.has(binding.trigger)) {
      issues.push({ where: binding.trigger, message: "duplicate `trigger`" });
      continue;
    }
    applied.add(binding.trigger);
    const at = index.get(binding.trigger);
    if (at !== undefined) {
      resolved[at] = binding;
    } else {
      index.set(binding.trigger, resolved.length);
      resolved.push(binding);
    }
  }

  return { bindings: resolved, issues };
}
