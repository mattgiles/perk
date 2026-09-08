// The strict routing-config projection behind the draft-review target fingerprint (contracts.md
// §8.23). Only the few Perk TOML fields that select WHERE a reviewed draft is saved are read;
// every other table (compaction, models, CI, skills, providers, presentation) and every
// formatting/comment/key-order difference is invisible to the fingerprint. Each selected value
// projects as absent or the digest of its exact decoded string — never the raw value, which for
// the Linear credential is a secret.
//
// This is a routing-INPUT fingerprint, not Python's effective resolver: no default selection,
// overlay precedence, stripping, or credential precedence is reproduced, so a change to a declared
// input stays conservatively significant even when a higher-precedence input currently shadows it.
// Deliberately NOT `config.ts`'s fail-soft overlaid reader or its handwritten subset parser: a
// malformed or wrong-shaped selected input refuses (a typed, code-owned explanation; never a parser
// message or a config excerpt, which can carry the secret).
//
// The parser certifies nothing about whole-config validity for the Python CLI, whose TOML 1.0
// reader is authoritative for the save: this parser also accepts TOML 1.1 syntax (a trailing
// inline-table comma, a `\x` escape) that Python rejects, so such an edit is not routing drift —
// the projection may be unchanged — and surfaces when the save subprocess refuses the whole file
// (like any failed CLI call), never as a save to the wrong place. Matching Python's grammar here
// would need a second handwritten parser; `shared/fixtures/draft-review-config.json` pins the gap.
import { parse } from "../vendor/smol-toml/parse.js";
import { digestSessionData } from "./sessionData.ts";

export type ConfigValue = { state: "absent" } | { state: "present"; digest: string };
/** The file roles a capture reads (fixed order); main/worktree roles alias in a main checkout. */
export const ROUTING_CONFIG_ROLES = [
  "main_config",
  "worktree_config",
  "worktree_local",
  "main_local",
] as const;
export type RoutingConfigRole = (typeof ROUTING_CONFIG_ROLES)[number];
/** The complete selected-field surface, named `<role>.<table>.<key>` (fixed order). */
export const ROUTING_CONFIG_FIELDS = [
  { name: "main_config.issues.backend", role: "main_config", table: "issues", key: "backend" },
  { name: "main_config.issues.team", role: "main_config", table: "issues", key: "team" },
  {
    name: "worktree_config.workflow.base",
    role: "worktree_config",
    table: "workflow",
    key: "base",
  },
  { name: "worktree_local.workflow.base", role: "worktree_local", table: "workflow", key: "base" },
  { name: "main_local.linear.api_key", role: "main_local", table: "linear", key: "api_key" },
] as const satisfies readonly {
  name: string;
  role: RoutingConfigRole;
  table: string;
  key: string;
}[];
export type RoutingConfigField = (typeof ROUTING_CONFIG_FIELDS)[number]["name"];
/** The fingerprint's `config` member: fixed key order, `workflow_base` null when inactive. */
export type RoutingConfigProjection = {
  main_issues: { backend: ConfigValue; team: ConfigValue };
  workflow_base: { committed: ConfigValue; local: ConfigValue } | null;
  linear_credentials: { api_key: ConfigValue };
};

/** A refusal-grade routing-config failure; `explanation` is code-owned text (no input bytes). */
export class RoutingConfigError extends Error {
  readonly explanation: string;
  constructor(explanation: string) {
    super(explanation);
    this.name = "RoutingConfigError";
    this.explanation = explanation;
  }
}

/** The parsed TOML document; values are consulted only through `selectRoutingString`. */
export type RoutingConfigDocument = { readonly [key: string]: unknown };
const EMPTY: RoutingConfigDocument = Object.freeze({});
const utf8 = new TextDecoder("utf-8", { fatal: true });

/**
 * Decode one config file strictly: `null` (ENOENT) is the empty document; invalid UTF-8 and any
 * parser failure refuse with the file role. `integersAsBigInt` keeps a huge integer in an
 * unrelated table from failing the capture through number-precision limits.
 */
export function decodeRoutingConfig(bytes: Uint8Array | null, role: string): RoutingConfigDocument {
  if (bytes === null) return EMPTY;
  let text: string;
  try {
    text = utf8.decode(bytes);
  } catch {
    throw new RoutingConfigError(`routing config ${role}: not valid UTF-8`);
  }
  try {
    return parse(text, { integersAsBigInt: true });
  } catch {
    throw new RoutingConfigError(`routing config ${role}: TOML parse failed`);
  }
}

function isTable(value: unknown): value is RoutingConfigDocument {
  // TOML dates parse to Date subclasses and arrays-of-tables to arrays: neither is a table.
  return (
    typeof value === "object" && value !== null && !Array.isArray(value) && !(value instanceof Date)
  );
}

/**
 * Select `[table] key` as its exact decoded string (whitespace and empty strings preserved), or
 * `undefined` when the table or key is absent. A present non-table or a non-string value refuses
 * with the role/field named; nothing else in the document is validated.
 */
export function selectRoutingString(
  document: RoutingConfigDocument,
  role: string,
  table: string,
  key: string,
): string | undefined {
  const selected = document[table];
  if (selected === undefined) return undefined;
  if (!isTable(selected))
    throw new RoutingConfigError(`routing config ${role}: [${table}] is not a table`);
  const value = selected[key];
  if (value === undefined) return undefined;
  if (typeof value !== "string")
    throw new RoutingConfigError(`routing config ${role}: [${table}] ${key} is not a string`);
  return value;
}

export function markRoutingValue(value: string | undefined): ConfigValue {
  return value === undefined
    ? { state: "absent" }
    : { state: "present", digest: digestSessionData(value) };
}

export interface RoutingConfigInputs {
  /** Whether the subject's save consumes `[workflow] base` (plan/objective); gist/refinement do not. */
  workflowBase: boolean;
  paths: Readonly<Record<RoutingConfigRole, string>>;
  /** null means ENOENT only; every other read failure throws (translated to the file role). */
  read(path: string): Uint8Array | null;
}

/**
 * Read, decode, and project the selected routing inputs. Each DISTINCT path is read and parsed
 * exactly once per capture, so aliasing roles (main == worktree) observe one version of the file.
 * Roles whose fields are inactive for the subject are not read at all.
 */
export function projectRoutingConfig(inputs: RoutingConfigInputs): RoutingConfigProjection {
  const active = new Set<RoutingConfigRole>(
    inputs.workflowBase
      ? ROUTING_CONFIG_ROLES
      : ROUTING_CONFIG_ROLES.filter(
          (role) => role !== "worktree_config" && role !== "worktree_local",
        ),
  );
  const documents = new Map<string, RoutingConfigDocument>();
  for (const role of ROUTING_CONFIG_ROLES) {
    if (!active.has(role)) continue;
    const path = inputs.paths[role];
    if (documents.has(path)) continue;
    const label = ROUTING_CONFIG_ROLES.filter(
      (r) => active.has(r) && inputs.paths[r] === path,
    ).join("/");
    let bytes: Uint8Array | null;
    try {
      bytes = inputs.read(path);
    } catch {
      throw new RoutingConfigError(`routing config ${label}: unreadable`);
    }
    documents.set(path, decodeRoutingConfig(bytes, label));
  }
  const select = (field: (typeof ROUTING_CONFIG_FIELDS)[number]): ConfigValue => {
    const document = documents.get(inputs.paths[field.role]);
    if (document === undefined)
      throw new RoutingConfigError(`routing config ${field.role}: not read`);
    return markRoutingValue(selectRoutingString(document, field.role, field.table, field.key));
  };
  const [backend, team, committed, local, apiKey] = ROUTING_CONFIG_FIELDS;
  return {
    main_issues: { backend: select(backend), team: select(team) },
    workflow_base: inputs.workflowBase
      ? { committed: select(committed), local: select(local) }
      : null,
    linear_credentials: { api_key: select(apiKey) },
  };
}

/** The per-field values behind a projection, keyed by the fixed component names (diagnostics). */
export function routingConfigComponents(
  projection: RoutingConfigProjection,
): Record<RoutingConfigField, ConfigValue | null> {
  return {
    "main_config.issues.backend": projection.main_issues.backend,
    "main_config.issues.team": projection.main_issues.team,
    "worktree_config.workflow.base": projection.workflow_base?.committed ?? null,
    "worktree_local.workflow.base": projection.workflow_base?.local ?? null,
    "main_local.linear.api_key": projection.linear_credentials.api_key,
  };
}
