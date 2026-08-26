// The minimal TS config port. Mirrors `perk/substrate/config.py`'s overlay: read
// `.perk/config.toml` (committed) overlaid by `.perk/local.toml` (gitignored, local wins). The only
// setting consumed today is an optional `[workflow]` plan-authoring addendum, appended into the
// `perk:plan-context` injection (extension/pi/v1/plan.ts) when present.
//
// Deliberately dependency-free: rather than pull a runtime TOML dependency into the published
// extension, this reads the narrow TOML subset perk actually uses — `[section]` headers +
// `[[name]]` array-of-tables + `key = "basic"` / `key = """multiline"""` strings + native
// booleans/numbers + `#` comments.
// Read-only, LBYL: a missing/unreadable file is `{}`; anything outside the subset is ignored.
// Dynamic `resources_discover` skill/prompt contribution is a flagged follow-up, not built here.

import { existsSync, readFileSync } from "node:fs";
import { parseUserBindings, type SkillBinding } from "./bindings.ts";
import { mainCheckoutRoot } from "./git.ts";
import { configFile, localConfigFile } from "./paths.ts";

/**
 * A TOML scalar the subset parser reads: quoted strings plus native booleans and numbers.
 * Anything else (dates, arrays, inline tables) is still deliberately ignored.
 */
export type TomlScalar = string | boolean | number;

/**
 * One configured CI check (a `[[ci.checks]]` array-of-tables row). `name`/`command` are required
 * non-blank strings; an optional `glob` (a single comma-separated pattern string, e.g.
 * `"*.ts,*.tsx"`) declares which changed files the check is relevant to — the read-only CI
 * executor skips it on the run-all path when no changed file (vs trunk) matches.
 */
export interface CiCheck {
  name: string;
  command: string;
  glob?: string;
}

export interface PerkConfig {
  /** Optional project-supplied plan-authoring addendum (`[workflow] plan_authoring = "..."`). */
  planAuthoring?: string;
  /**
   * The `[ci]` verification namespace. `checks` is the `[[ci.checks]]` ordered array-of-tables
   * (each row name/command/optional glob) the read-only CI executor consumes; absent/empty ⇒ `[]`.
   * `trusted` (`[ci] trusted = true`, a native boolean) declares those project-supplied checks
   * trusted, so the executor runs them WITHOUT a per-session confirm on every surface, including
   * headless (it overrides the fail-closed refuse). Absent/`false`/non-boolean ⇒ untrusted
   * (confirm with UI; refuse headless). Always present; defaults `{trusted: false, checks: []}`.
   */
  ci: { trusted: boolean; checks: CiCheck[] };
  /**
   * The agent-keyed `[models.subagents]` table: a per-agent model override for each perk-owned
   * project agent (`pr-reviewer`, `review-classifier`, `objective-explorer`, `conflict-resolver`,
   * `learn-analyst`, `adversarial-reviewer`, `draft-reviewer`,
   * `harvest-analyst` — consumed by `run_harvest_wave` at execute time — `dream-analyst` and
   * `dream-reducer` — consumed by `run_dream_wave` at execute time — and the
   * dev-only `session-auditor`, whose def is repo-local to perk's own repository
   * (`.pi/agents/perk-dev/session-auditor.md`, never delivered by `perk init`), so the key is
   * dormant in consumer repos). Each configured
   * value is injected as the top-level workflow-level `model` on that agent's one `subagent`
   * workflowScript call — a default flowing onto every lane, single-child runs included (as
   * /pr-review does); when a key is absent the agent's frontmatter `model` (in
   * `.pi/agents/perk/<name>.md`; the session-auditor's in its repo-local def) is the default.
   * (Since pi-subagents 0.52, `subagents.agentOverrides` also reaches custom/project agents —
   * but only as a frontmatter-sensitive fill that never displaces a field the def's own
   * frontmatter sets; every perk def pins `model:` in frontmatter, so this inline workflow-level
   * injection remains the mechanism.)
   * A value may carry a `:thinking` suffix (`"anthropic/claude-sonnet-4-5:high"`) or be the
   * `"inherit"` sentinel (child inherits the parent session's model) — both resolved by
   * pi-subagents on the injected value (the last-colon segment counts as thinking only when it
   * is a pi level, so ollama-style tags stay part of the model id).
   * Always-present object; absent keys omitted (mirror of `providers`).
   */
  subagents: {
    "pr-reviewer"?: string;
    "review-classifier"?: string;
    "objective-explorer"?: string;
    "conflict-resolver"?: string;
    "learn-analyst"?: string;
    "adversarial-reviewer"?: string;
    "draft-reviewer"?: string;
    "harvest-analyst"?: string;
    "dream-analyst"?: string;
    "dream-reducer"?: string;
    "session-auditor"?: string;
  };
  /**
   * Optional `[compaction] objective_threshold` — the context-usage fraction (0,1] that triggers
   * threshold compaction while an objective is active. A native TOML float (e.g.
   * `objective_threshold = 0.8`); string/out-of-range values are ignored. The Python plane
   * deliberately ignores this key (it converges the rest of `[compaction]` into settings).
   */
  objectiveCompactThreshold?: number;
  /** The `[[bindings]]` user overlay, resolved against shipped defaults downstream. */
  bindings: SkillBinding[];
  /**
   * The flat `[providers]` per-seam selection — bare provider-id strings pointing into
   * `shared/providers.yaml`. Absent keys mean “use the seam default”; resolution against the
   * supported set is a downstream concern.
   */
  providers: {
    plan?: string;
    footer?: string;
    web?: string;
  };
}

/** A nested scalar table: `{ section: { key: scalar } }` (dotted section names kept literal). */
type ScalarTable = Record<string, Record<string, TomlScalar>>;

/**
 * The narrow TOML subset perk reads: `[section]`/top-level scalar tables plus `[[name]]`
 * array-of-tables (each row a scalar table). Mirrors `tomllib`'s shape for the keys perk uses.
 */
interface TomlSubset {
  tables: ScalarTable;
  arrays: Record<string, Array<Record<string, TomlScalar>>>;
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
 * `{ section: { key: scalar } }` map (top-level keys under the `""` section); `arrays` is a
 * `{ name: [{ key: scalar }, ...] }` map fed by `[[name]]` array-of-tables. Scalars are quoted
 * strings, native `true`/`false` booleans, and numeric literals; anything else is skipped —
 * this is intentionally NOT a full TOML parser.
 */
export function parseTomlSubset(text: string): TomlSubset {
  const root: Record<string, TomlScalar> = {};
  const tables: ScalarTable = { "": root };
  const arrays: Record<string, Array<Record<string, TomlScalar>>> = {};
  // The current write target for `key = value` lines (a section table or an array-of-tables row).
  let dest: Record<string, TomlScalar> = root;
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = (lines[i] ?? "").trim();
    if (line === "" || line.startsWith("#")) continue;

    // `[[name]]` array-of-tables must be detected BEFORE the `[section]` header (it also matches).
    const arrayHeader = line.match(/^\[\[([^\]]+)\]\]$/);
    if (arrayHeader) {
      const name = (arrayHeader[1] ?? "").trim();
      const row: Record<string, TomlScalar> = {};
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
      continue;
    }

    // Unquoted scalar: strip an inline `#` comment, then read native booleans and numbers.
    const hash = value.indexOf("#");
    const bare = (hash === -1 ? value : value.slice(0, hash)).trim();
    if (bare === "true" || bare === "false") {
      dest[key] = bare === "true";
      continue;
    }
    if (/^[+-]?\d[\d_]*(\.[\d_]+)?([eE][+-]?\d+)?$/.test(bare)) {
      const parsed = Number(bare.replace(/_/g, ""));
      if (Number.isFinite(parsed)) dest[key] = parsed;
    }
    // Other value shapes (dates, arrays, inline tables) are intentionally ignored.
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
 * replace as a whole array (mirror of perk/substrate/config.py's list-replaces-list overlay).
 */
function overlay(base: TomlSubset, over: TomlSubset): TomlSubset {
  const tables: ScalarTable = {};
  for (const [section, kv] of Object.entries(base.tables)) tables[section] = { ...kv };
  for (const [section, kv] of Object.entries(over.tables)) {
    tables[section] = { ...(tables[section] ?? {}), ...kv };
  }
  const arrays: Record<string, Array<Record<string, TomlScalar>>> = { ...base.arrays };
  for (const [name, rows] of Object.entries(over.arrays)) arrays[name] = rows;
  return { tables, arrays };
}

/** Load `.perk/config.toml` overlaid by `.perk/local.toml` from `cwd` (mirror of perk/substrate/config.py). */
export function loadPerkConfig(cwd: string): PerkConfig {
  let merged: TomlSubset = emptySubset();
  for (const file of [configFile(cwd), localConfigFile(cwd)]) {
    merged = overlay(merged, readTomlFile(file));
  }

  const planAuthoring = merged.tables.workflow?.plan_authoring;
  // `[compaction] objective_threshold` is a native float in (0,1]; strings/out-of-range ignored.
  const rawThreshold = merged.tables.compaction?.objective_threshold;
  const objectiveCompactThreshold =
    typeof rawThreshold === "number" && rawThreshold > 0 && rawThreshold <= 1
      ? rawThreshold
      : undefined;
  return {
    planAuthoring:
      typeof planAuthoring === "string" && planAuthoring.trim() ? planAuthoring : undefined,
    ci: {
      trusted: merged.tables.ci?.trusted === true,
      checks: parseCiChecks(merged.arrays["ci.checks"] ?? []),
    },
    subagents: parseSubagentsSelection(merged.tables["models.subagents"]),
    objectiveCompactThreshold,
    bindings: parseUserBindings(merged.arrays.bindings ?? []),
    providers: parseProvidersSelection(merged.tables.providers),
  };
}

/**
 * Resolve one `[models.subagents]` model at execute time — the flow-tool read for sessions that
 * may run inside a linked worktree. Committed `.perk/config.toml` is read from `cwd` (the
 * worktree's committed semantics), but the gitignored `.perk/local.toml` lives only in the MAIN
 * checkout when `cwd` is a linked worktree (worktrees never materialize it), so the local
 * overlay is additionally anchored via `mainCheckoutRoot` — a user's session-transient model
 * override survives the cold worktree launch. A worktree-local `local.toml`, if one exists,
 * still wins (most specific last); in the main checkout the two local reads are the same file
 * (byte-identical behavior). Fail-open like everything here — missing/malformed files are empty.
 */
export function subagentModel(cwd: string, agent: SubagentKey): string | undefined {
  const merged = overlay(
    overlay(readTomlFile(configFile(cwd)), readTomlFile(localConfigFile(mainCheckoutRoot(cwd)))),
    readTomlFile(localConfigFile(cwd)),
  );
  return parseSubagentsSelection(merged.tables["models.subagents"])[agent];
}

/**
 * Read the `[[ci.checks]]` array-of-tables into an ordered `CiCheck[]`. A row is kept only when
 * both `name` and `command` are non-blank strings; `glob` is kept only when a non-blank string.
 * Declared order is preserved; ill-typed rows are silently dropped (mirror of
 * `parseProvidersSelection`).
 */
export function parseCiChecks(rows: Array<Record<string, TomlScalar>>): CiCheck[] {
  const checks: CiCheck[] = [];
  for (const row of rows) {
    const name = row.name;
    const command = row.command;
    if (typeof name !== "string" || !name.trim()) continue;
    if (typeof command !== "string" || !command.trim()) continue;
    const check: CiCheck = { name, command };
    const glob = row.glob;
    if (typeof glob === "string" && glob.trim()) check.glob = glob;
    checks.push(check);
  }
  return checks;
}

/** One perk-owned project agent name configurable via the `[models.subagents]` table. */
export type SubagentKey = (typeof SUBAGENT_KEYS)[number];

/** The perk-owned project agents configurable via the `[models.subagents]` table. */
const SUBAGENT_KEYS = [
  "pr-reviewer",
  "review-classifier",
  "objective-explorer",
  "conflict-resolver",
  "learn-analyst",
  "adversarial-reviewer",
  "draft-reviewer",
  "harvest-analyst",
  "dream-analyst",
  "dream-reducer",
  // Dev-only: the perk-dev session-audit judgment wave's auditor (dormant in consumer repos).
  "session-auditor",
] as const;

/**
 * Read the agent-keyed `[models.subagents]` table into a selection (string values only). For each
 * known agent key, the value is kept only when it is a non-blank string; absent/ill-typed/unknown
 * keys are omitted (mirror of `parseProvidersSelection`).
 */
function parseSubagentsSelection(
  table: Record<string, TomlScalar> | undefined,
): PerkConfig["subagents"] {
  const selection: PerkConfig["subagents"] = {};
  for (const key of SUBAGENT_KEYS) {
    const value = table?.[key];
    if (typeof value === "string" && value.trim()) selection[key] = value;
  }
  return selection;
}

/** Read the flat `[providers]` table into a `{plan?, footer?, web?}` selection (string values only). Retired keys (`review`, `askuser`, `todo`) are silently ignored (the TS fail-safe posture; the Python plane's tripwire is the loud surface). */
function parseProvidersSelection(table: Record<string, TomlScalar> | undefined): {
  plan?: string;
  footer?: string;
  web?: string;
} {
  const selection: {
    plan?: string;
    footer?: string;
    web?: string;
  } = {};
  if (typeof table?.plan === "string") selection.plan = table.plan;
  if (typeof table?.footer === "string") selection.footer = table.footer;
  if (typeof table?.web === "string") selection.web = table.web;
  return selection;
}

/** The `[issues] backend` vocabulary (contracts.md §8.21). */
export type IssueBackendId = "github" | "linear";

export const GITHUB_ISSUE_BACKEND_ID: IssueBackendId = "github";

/**
 * The fail-safe TS mirror of the issue-backend selection.
 *
 * Reads ONLY committed `.perk/config.toml` — deliberately not `loadPerkConfig`'s overlay, mirroring
 * the Python committed-only read (the backend decides where canonical durable state is written;
 * a per-user `.perk/local.toml` override would fragment the canonical store). The read is
 * anchored to the MAIN checkout via `mainCheckoutRoot` (fail-open: `cwd` outside a git repo),
 * mirroring Python's main-worktree anchoring — a linked worktree's checkout state (detached /
 * stale branch / missing `.perk/`) must never flip a Linear repo's prompt clauses to GitHub.
 * Python (`perk/backends/resolve.py::resolve_issue_backend_id`) is the AUTHORITATIVE validator and
 * **raises** on unknown values; this mirror is fail-safe (absence/unknown/any error → `"github"`)
 * because the TS plane only renders prompts — it never writes canonical issues.
 */
export function resolveIssueBackendId(cwd: string): IssueBackendId {
  try {
    const committed = readTomlFile(configFile(mainCheckoutRoot(cwd)));
    const backend = committed.tables.issues?.backend;
    if (backend === "github" || backend === "linear") return backend;
    return GITHUB_ISSUE_BACKEND_ID;
  } catch {
    return GITHUB_ISSUE_BACKEND_ID;
  }
}
