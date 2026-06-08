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
import { parseUserBindings, type SkillBinding } from "./bindings.ts";

const CONFIG_FILENAME = "perk.toml";
const LOCAL_CONFIG_FILENAME = "perk.local.toml";

export interface PerkConfig {
  /** Optional project-supplied plan-authoring addendum (`[workflow] plan_authoring = "..."`). */
  planAuthoring?: string;
  /** The `[ci]` named-checks map (`name = "shell command"`); the executor (P2.T5) consumes it. */
  ci?: Record<string, string>;
  /**
   * Optional `[pr-review]` settings (#175). `model` is the per-call inline override the warm
   * `/pr-review` injects on the `perk.pr-reviewer` spawn; when unset, the agent's frontmatter model
   * is the default. (`subagents.agentOverrides` does NOT reach project agents, so this inline
   * override — not an override map — is the configuration mechanism.)
   */
  prReview?: { model?: string };
  /**
   * Optional `[objective] compact_threshold` — the context-usage fraction (0,1] that triggers
   * threshold compaction while an objective is active (P2.T9). Because the TOML subset reads only
   * string values, it must be written as a quoted string (e.g. `compact_threshold = "0.8"`).
   */
  objectiveCompactThreshold?: number;
  /** The `[[bindings]]` user overlay (Node 1.2), resolved against shipped defaults downstream. */
  bindings: SkillBinding[];
  /**
   * The flat `[providers]` per-seam selection (Node 2.1) — bare provider-id strings pointing into
   * `shared/providers.yaml`. Absent keys mean “use the seam default”; resolution against the
   * supported set is a downstream concern (the TS resolver is Node 2.2/3.1, not this node).
   */
  providers: { plan?: string; todo?: string };
}

/** A nested string table: `{ section: { key: value } }` (the only shape perk reads today). */
type StringTable = Record<string, Record<string, string>>;

/**
 * The narrow TOML subset perk reads: `[section]`/top-level string tables plus `[[name]]`
 * array-of-tables (each row a string table). Mirrors `tomllib`'s shape for the keys perk uses.
 */
interface TomlSubset {
  tables: StringTable;
  arrays: Record<string, Array<Record<string, string>>>;
}

function unescapeBasic(raw: string): string {
  return raw
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}

/**
 * Parse the narrow TOML subset perk consumes. Returns `{ tables, arrays }`: `tables` is a
 * `{ section: { key: stringValue } }` map (top-level keys under the `""` section); `arrays` is a
 * `{ name: [{ key: stringValue }, ...] }` map fed by `[[name]]` array-of-tables. Non-string values
 * and unknown syntax are skipped — this is intentionally NOT a full TOML parser.
 */
export function parseTomlSubset(text: string): TomlSubset {
  const root: Record<string, string> = {};
  const tables: StringTable = { "": root };
  const arrays: Record<string, Array<Record<string, string>>> = {};
  // The current write target for `key = value` lines (a section table or an array-of-tables row).
  let dest: Record<string, string> = root;
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = (lines[i] ?? "").trim();
    if (line === "" || line.startsWith("#")) continue;

    // `[[name]]` array-of-tables must be detected BEFORE the `[section]` header (it also matches).
    const arrayHeader = line.match(/^\[\[([^\]]+)\]\]$/);
    if (arrayHeader) {
      const name = (arrayHeader[1] ?? "").trim();
      const row: Record<string, string> = {};
      let rows = arrays[name];
      if (!rows) {
        rows = [];
        arrays[name] = rows;
      }
      rows.push(row);
      dest = row;
      continue;
    }

    const header = line.match(/^\[([^\]]+)\]$/);
    if (header) {
      const section = (header[1] ?? "").trim();
      if (!tables[section]) tables[section] = {};
      dest = tables[section];
      continue;
    }

    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (key === "") continue;

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
  return { tables, arrays };
}

function emptySubset(): TomlSubset {
  return { tables: { "": {} }, arrays: {} };
}

function readTomlFile(path: string): TomlSubset {
  if (!existsSync(path)) return emptySubset();
  try {
    return parseTomlSubset(readFileSync(path, "utf8"));
  } catch (error) {
    // Loud-but-non-fatal: a malformed config never blocks the session.
    console.error(`perk: ignoring malformed ${path} — ${error}`);
    return emptySubset();
  }
}

/**
 * Overlay `over` onto `base` (local wins). Section tables merge leaf-by-leaf; array-of-tables
 * replace as a whole array (mirror of perk/config.py's list-replaces-list overlay).
 */
function overlay(base: TomlSubset, over: TomlSubset): TomlSubset {
  const tables: StringTable = {};
  for (const [section, kv] of Object.entries(base.tables)) tables[section] = { ...kv };
  for (const [section, kv] of Object.entries(over.tables)) {
    tables[section] = { ...(tables[section] ?? {}), ...kv };
  }
  const arrays: Record<string, Array<Record<string, string>>> = { ...base.arrays };
  for (const [name, rows] of Object.entries(over.arrays)) arrays[name] = rows;
  return { tables, arrays };
}

/** Load `.pi/perk.toml` overlaid by `.pi/perk.local.toml` from `cwd` (mirror of perk/config.py). */
export function loadPerkConfig(cwd: string): PerkConfig {
  const piDir = join(cwd, ".pi");
  let merged: TomlSubset = emptySubset();
  for (const name of [CONFIG_FILENAME, LOCAL_CONFIG_FILENAME]) {
    merged = overlay(merged, readTomlFile(join(piDir, name)));
  }

  const planAuthoring = merged.tables.workflow?.plan_authoring;
  const rawThreshold = merged.tables.objective?.compact_threshold;
  const parsedThreshold = rawThreshold != null ? Number.parseFloat(rawThreshold) : Number.NaN;
  const objectiveCompactThreshold =
    Number.isFinite(parsedThreshold) && parsedThreshold > 0 && parsedThreshold <= 1
      ? parsedThreshold
      : undefined;
  return {
    planAuthoring:
      typeof planAuthoring === "string" && planAuthoring.trim() ? planAuthoring : undefined,
    ci: merged.tables.ci ?? {},
    prReview: parsePrReview(merged.tables["pr-review"]),
    objectiveCompactThreshold,
    bindings: parseUserBindings(merged.arrays.bindings ?? []),
    providers: parseProvidersSelection(merged.tables.providers),
  };
}

/** Read the `[pr-review]` table into `{model?}` (string values only); `undefined` when absent. */
function parsePrReview(table: Record<string, string> | undefined): { model?: string } | undefined {
  const model = table?.model;
  if (typeof model === "string" && model.trim()) return { model };
  return undefined;
}

/** Read the flat `[providers]` table into a `{plan?, todo?}` selection (string values only). */
function parseProvidersSelection(table: Record<string, string> | undefined): {
  plan?: string;
  todo?: string;
} {
  const selection: { plan?: string; todo?: string } = {};
  if (typeof table?.plan === "string") selection.plan = table.plan;
  if (typeof table?.todo === "string") selection.todo = table.todo;
  return selection;
}
