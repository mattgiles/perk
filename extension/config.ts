// P2.T2a — the minimal TS config port (D1b). Mirrors `perk/config.py`'s overlay: read
// `.pi/perk.toml` (committed) overlaid by `.pi/perk.local.toml` (gitignored, local wins). The only
// setting consumed today is an optional `[workflow]` plan-authoring addendum, appended into the
// `perk:plan-context` injection (extension/planMode.ts) when present.
//
// Deliberately dependency-free: rather than pull a runtime TOML dependency into the published
// extension for a single optional string, this reads the narrow TOML subset perk actually uses —
// `[section]` headers + `key = "basic"` / `key = """multiline"""` string values + `#` comments.
// Read-only, LBYL: a missing/unreadable file is `{}`; anything outside the subset is ignored.
// Dynamic `resources_discover` skill/prompt contribution is a flagged follow-up, not built here.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const CONFIG_FILENAME = "perk.toml";
const LOCAL_CONFIG_FILENAME = "perk.local.toml";

export interface PerkConfig {
  /** Optional project-supplied plan-authoring addendum (`[workflow] plan_authoring = "..."`). */
  planAuthoring?: string;
  /** The `[ci]` named-checks map (`name = "shell command"`); the executor (P2.T5) consumes it. */
  ci?: Record<string, string>;
  /**
   * Optional `[objective] compact_threshold` — the context-usage fraction (0,1] that triggers
   * threshold compaction while an objective is active (P2.T9). Because the TOML subset reads only
   * string values, it must be written as a quoted string (e.g. `compact_threshold = "0.8"`).
   */
  objectiveCompactThreshold?: number;
}

/** A nested string table: `{ section: { key: value } }` (the only shape perk reads today). */
type StringTable = Record<string, Record<string, string>>;

function unescapeBasic(raw: string): string {
  return raw
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}

/**
 * Parse the narrow TOML subset perk consumes. Returns a `{ section: { key: stringValue } }` map.
 * Top-level keys land under the `""` section. Non-string values and unknown syntax are skipped —
 * this is intentionally NOT a full TOML parser.
 */
export function parseTomlSubset(text: string): StringTable {
  const table: StringTable = { "": {} };
  let section = "";
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = (lines[i] ?? "").trim();
    if (line === "" || line.startsWith("#")) continue;

    const header = line.match(/^\[([^\]]+)\]$/);
    if (header) {
      section = (header[1] ?? "").trim();
      if (!table[section]) table[section] = {};
      continue;
    }

    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (key === "") continue;
    const dest: Record<string, string> = table[section] ?? {};
    table[section] = dest;

    // Multi-line basic string: """ ... """ (possibly spanning lines).
    if (value.startsWith('"""')) {
      let body = value.slice(3);
      if (body.endsWith('"""') && body.length >= 3) {
        body = body.slice(0, -3);
      } else {
        const parts: string[] = [body];
        i++;
        for (; i < lines.length; i++) {
          const raw = lines[i] ?? "";
          const end = raw.indexOf('"""');
          if (end !== -1) {
            // A bare closing delimiter on its own line contributes no trailing content (so the
            // newline that precedes it is not appended as an empty segment).
            if (end > 0) parts.push(raw.slice(0, end));
            break;
          }
          parts.push(raw);
        }
        body = parts.join("\n");
        // A leading newline immediately after the opening delimiter is trimmed (TOML rule).
        if (body.startsWith("\n")) body = body.slice(1);
      }
      dest[key] = unescapeBasic(body);
      continue;
    }

    // Single-line basic string: "..." (strip a trailing inline comment outside the quotes).
    const basic = value.match(/^"((?:[^"\\]|\\.)*)"/);
    if (basic) {
      dest[key] = unescapeBasic(basic[1] ?? "");
    }
    // Non-string scalars are intentionally ignored (perk reads only strings today).
  }
  return table;
}

function readTomlFile(path: string): StringTable {
  if (!existsSync(path)) return { "": {} };
  try {
    return parseTomlSubset(readFileSync(path, "utf8"));
  } catch (error) {
    // Loud-but-non-fatal: a malformed config never blocks the session.
    console.error(`perk: ignoring malformed ${path} — ${error}`);
    return { "": {} };
  }
}

/** Overlay `over` onto `base` (local wins; sections merge, leaf keys replace). */
function overlay(base: StringTable, over: StringTable): StringTable {
  const merged: StringTable = {};
  for (const [section, kv] of Object.entries(base)) merged[section] = { ...kv };
  for (const [section, kv] of Object.entries(over)) {
    merged[section] = { ...(merged[section] ?? {}), ...kv };
  }
  return merged;
}

/** Load `.pi/perk.toml` overlaid by `.pi/perk.local.toml` from `cwd` (mirror of perk/config.py). */
export function loadPerkConfig(cwd: string): PerkConfig {
  const piDir = join(cwd, ".pi");
  let merged: StringTable = { "": {} };
  for (const name of [CONFIG_FILENAME, LOCAL_CONFIG_FILENAME]) {
    merged = overlay(merged, readTomlFile(join(piDir, name)));
  }

  const planAuthoring = merged.workflow?.plan_authoring;
  const rawThreshold = merged.objective?.compact_threshold;
  const parsedThreshold = rawThreshold != null ? Number.parseFloat(rawThreshold) : Number.NaN;
  const objectiveCompactThreshold =
    Number.isFinite(parsedThreshold) && parsedThreshold > 0 && parsedThreshold <= 1
      ? parsedThreshold
      : undefined;
  return {
    planAuthoring:
      typeof planAuthoring === "string" && planAuthoring.trim() ? planAuthoring : undefined,
    ci: merged.ci ?? {},
    objectiveCompactThreshold,
  };
}
