// The tool catalog, the one eligibility formula and the provenance-posture table (contracts.md
// §8.40). Every perk tool is registered through `registerPerkTool` (`pi/perkTool.ts`) with a
// policy descriptor; the catalog records it, and every perk-side view — the gated (read-only)
// activation view, the gate-OFF stage diet, the carve-out writer list the read-only context names,
// the Pi metadata (`exposure`, `annotations.readOnlyHint`) and the golden stage×tool matrix — is
// DERIVED from the descriptors. Every other tool is classified by WHO registered it, never by its
// name: Pi's `sourceInfo` provenance (a package spec, an exact synthetic path, or the builtin
// registrar) selects a posture row, and an unrecognized provenance is `unknown` (passes every
// diet, blocked under the gate). Nothing here enumerates a foreign tool name save the one
// in-package exception row.
//
// Activation is own-names-only: perk installs and removes ONLY catalogued names
// (`reconcileTarget`); foreign eligibility is presented by hiding declarations
// (`hiddenDeclarationsFor`, run by the `perk_stage` loadout host) and enforced by the read-only
// `tool_call` backstop — never by deactivating a foreign tool.
//
// Pure: no Pi runtime, no session state beyond the process-wide catalog. The catalog fills as the
// installers register; derived views and the read-only context are computed per call, never at
// module load.

import { loadProviders, PLANNOTATOR_PLAN_PROVIDER_ID } from "./providers.ts";
import { loadRegistry, stageConsumesPlanRef } from "./registry.ts";

/** The loadout host's tool name: always active where registered, never declared to the model. */
export const LOADOUT_HOST_NAME = "perk_stage";

// --- the policy descriptor ----------------------------------------------------------------------

/**
 * What a tool IS. Anything that can return `terminate: true` is `terminal`; a tool that opens a
 * human surface and hands off to it without terminating is `interactive`; anything that spawns
 * children, a wave or a foreground child/resolver is `orchestration`; a pure read is `query`;
 * the rest — including tools whose only dialog is a trust/confirm gate — is `action`. `host` is
 * reserved for the loadout host (`perk_stage`): a tool with no action that exists to run
 * `prepareLoadout`, registered only through `registerLoadoutHost`.
 */
export type ToolKind = "terminal" | "interactive" | "orchestration" | "query" | "action" | "host";
/** A tool's posture under the read-only gate; `carveOut` names its one bounded write, in prose. */
export type GatePosture = "allowed" | "blocked" | { carveOut: string };
/** How the tool is declared to the model: always, or deferred (discoverable, never activated). */
export type Declared = "always" | "deferred";
/** The session's gate mode (the workflow-state `mode` field). */
export type Mode = "read-only" | "read-write";

/** A perk tool's policy descriptor — the one input every derived view reads. */
export type ToolPolicy = {
  /** Registry stage ids where the tool is eligible (validated at registration; empty = reachable only unscoped). */
  stages: readonly string[];
  gated: GatePosture;
  /** A mode gesture needs it regardless of stage (the `/plan` toggle's flow). Default false. */
  modeOverStage?: boolean;
  kind: ToolKind;
  /** Reserved for the discovery pilot; default "always". */
  declared?: Declared;
};

// --- stage families -----------------------------------------------------------------------------

const REGISTRY = loadRegistry();

/** Every registry stage id, in registry order. */
export const REGISTRY_STAGE_IDS: readonly string[] = REGISTRY.stages.map((s) => s.id);
const REGISTRY_STAGE_SET: ReadonlySet<string> = new Set(REGISTRY_STAGE_IDS);

/**
 * The worktree family: the stages that consume the plan-ref selector (implement / submit /
 * address / land / learn). Derived from the registry, never listed.
 */
export const WORKTREE_STAGES: readonly string[] = REGISTRY_STAGE_IDS.filter((id) =>
  stageConsumesPlanRef(REGISTRY, id),
);
/** The plan family: plan authoring, its save, and the objective-plan factory. */
export const PLAN_FAMILY_STAGES: readonly string[] = ["plan", "save", "objective-plan"];
/** The objective authoring pair. */
export const OBJECTIVE_STAGES: readonly string[] = ["objective-author", "objective-save"];
/** The three authoring stages (the scout launcher's home). */
export const AUTHORING_STAGES: readonly string[] = ["plan", "objective-plan", "objective-author"];
/** The gist authoring pair. */
export const GIST_STAGES: readonly string[] = ["gist-author", "gist-save"];

// --- the catalog --------------------------------------------------------------------------------

/**
 * The process-wide tool catalog: every perk tool registered through the seam, in registration
 * order. A harness re-activation in the same process re-registers each name with the SAME policy
 * (a no-op); a divergent policy throws.
 */
const CATALOG = new Map<string, ToolPolicy>();

function normalizedPolicy(policy: ToolPolicy): string {
  return JSON.stringify({
    stages: [...policy.stages],
    gated: policy.gated,
    modeOverStage: policy.modeOverStage === true,
    kind: policy.kind,
    declared: policy.declared ?? "always",
  });
}

/** Record a validated perk tool in the catalog (idempotent for an identical policy). */
export function recordPerkTool(name: string, policy: ToolPolicy): void {
  const prior = CATALOG.get(name);
  if (prior !== undefined) {
    if (normalizedPolicy(prior) !== normalizedPolicy(policy)) {
      throw new Error(`perk tool policy: ${name} — re-registered with a divergent policy`);
    }
    return;
  }
  const gated =
    typeof policy.gated === "object" ? { carveOut: policy.gated.carveOut } : policy.gated;
  CATALOG.set(name, Object.freeze({ ...policy, stages: Object.freeze([...policy.stages]), gated }));
}

/** The catalogued policy for a perk tool, or undefined for any other name. */
export function perkToolPolicy(name: string): ToolPolicy | undefined {
  return CATALOG.get(name);
}

/** Every catalogued perk tool, in registration order. */
export function perkToolNames(): string[] {
  return [...CATALOG.keys()];
}

/** Whether a name is a catalogued perk tool. */
export function isPerkTool(name: string): boolean {
  return CATALOG.has(name);
}

// --- derived Pi metadata + registration-time validation ----------------------------------------

/** The kinds Pi must never let `ctx.executeTool()` reach: declared to the model, never callable. */
const MODEL_ONLY_KINDS: ReadonlySet<ToolKind> = new Set([
  "terminal",
  "interactive",
  "orchestration",
  "host",
]);

/** The Pi definition fields the policy owns; a definition carrying one is refused. */
export const POLICY_OWNED_FIELDS = [
  "exposure",
  "annotations",
  "defaultActive",
  "prepareLoadout",
] as const;

/** The Pi metadata a policy derives (`readOnlyHint` = never modifies the worktree — a hint only). */
export type PiToolMetadata = {
  exposure: "direct" | "model-only" | "deferred";
  annotations?: { readOnlyHint: true };
};

/** Derive the Pi `exposure` + `annotations` for a policy — never hand-set on a definition. */
export function derivePiMetadata(policy: ToolPolicy): PiToolMetadata {
  const exposure = MODEL_ONLY_KINDS.has(policy.kind)
    ? "model-only"
    : policy.declared === "deferred"
      ? "deferred"
      : "direct";
  return policy.gated === "blocked"
    ? { exposure }
    : { exposure, annotations: { readOnlyHint: true } };
}

/** Throw `perk tool policy: <name> — …` unless the definition + policy may register. */
export function validateToolPolicy(
  name: string,
  definition: object,
  policy: ToolPolicy,
  registryStageIds: readonly string[],
): void {
  const fail = (why: string): never => {
    throw new Error(`perk tool policy: ${name} — ${why}`);
  };
  if (policy.kind === "host") fail("the loadout host registers through registerLoadoutHost");
  for (const field of POLICY_OWNED_FIELDS) {
    if (Object.hasOwn(definition, field)) {
      fail(`the definition must not set \`${field}\` (it is derived from the policy)`);
    }
  }
  const known = new Set(registryStageIds);
  for (const stage of policy.stages) {
    if (!known.has(stage)) fail(`unknown stage id "${stage}"`);
  }
  if (typeof policy.gated === "object" && policy.gated.carveOut.trim() === "") {
    fail("a carve-out must name its bounded write");
  }
  if (policy.declared === "deferred" && MODEL_ONLY_KINDS.has(policy.kind)) {
    fail(
      `declared: "deferred" requires kind query or action — a ${policy.kind} tool is model-only, and a model-only tool can never be script-callable (exposure is one enum)`,
    );
  }
  const prior = CATALOG.get(name);
  if (prior !== undefined && normalizedPolicy(prior) !== normalizedPolicy(policy)) {
    fail("re-registered with a divergent policy");
  }
}

// --- the provenance-posture table ---------------------------------------------------------------

/**
 * Who registered a tool, as Pi reports it (`ToolInfo.sourceInfo`): `path` is the extension's
 * load path (`builtin:<name>`, `<inline:<name>>`, or a file), `source` the package spec verbatim
 * (`npm:pi-subagents@0.73.1`), `builtin`, `inline`, or another synthetic source. Structural, so
 * this module stays free of Pi imports.
 */
export type Provenance = { path: string; source: string };

/**
 * A foreign tool's posture — the reason it is (or is not) eligible:
 *  - `research`: an external read (web search/fetch, issue-tracker reads, code search) — every
 *    stage keeps it, and it never mutates the repo;
 *  - `universal`: a session-interaction tool every stage keeps (the same matrix as `research`;
 *    the label records the different reason);
 *  - `delegation`: the worktree-flow posture — spawning/supervising children and the
 *    implementation checklist — eligible in the worktree family plus `stack-review`;
 *  - `never`: eligible in no stage and blocked under the gate (bare sessions keep it);
 *  - `child-engine`: the subagent engine's in-child tools — stage-blind (adopted children are
 *    stage-unscoped), gate-allowed because the gate IS inherited by adopted children.
 */
export type ForeignPosture = "research" | "delegation" | "universal" | "never" | "child-engine";

/** A builtin's gate posture: `verdict` = allowed under the gate, subject to the bash verdict. */
export type BuiltinPosture = "allowed" | "blocked" | "verdict";

/** A tool's classification: perk (by catalog name), foreign (by provenance), builtin, or unknown. */
export type Posture =
  | { owner: "perk"; policy: ToolPolicy }
  | { owner: "foreign"; posture: ForeignPosture; key: string }
  | { owner: "builtin"; gated: BuiltinPosture }
  | { owner: "unknown" };

/** Each foreign posture's eligibility row: the stages it is eligible in and its gate posture. */
export const POSTURE_ROWS: Readonly<
  Record<ForeignPosture, { stages: readonly string[]; gated: "allowed" | "blocked" }>
> = {
  research: { stages: REGISTRY_STAGE_IDS, gated: "allowed" },
  universal: { stages: REGISTRY_STAGE_IDS, gated: "allowed" },
  delegation: { stages: [...WORKTREE_STAGES, "stack-review"], gated: "allowed" },
  never: { stages: [], gated: "blocked" },
  "child-engine": { stages: REGISTRY_STAGE_IDS, gated: "allowed" },
};

/**
 * A package spec's identity: an `npm:` spec loses its version/range suffix, scoped-aware
 * (`npm:@scope/name@1.2.3` → `npm:@scope/name`); any other string is returned unchanged. The
 * twin of the Python plane's `_npm_name` (the same `perk init` package vocabulary).
 */
export function normalizePackageSpec(source: string): string {
  if (!source.startsWith("npm:")) return source;
  const spec = source.slice("npm:".length);
  const at = spec.lastIndexOf("@");
  // at === 0 is a scope's leading @, not a version separator.
  return at > 0 ? `npm:${spec.slice(0, at)}` : source;
}

/** A package's posture row; `except` re-postures the named tools of that one package. */
export type PackagePosture = {
  posture: ForeignPosture;
  except?: { names: readonly string[]; posture: ForeignPosture };
};

function packageToolPolicy(): Record<string, PackagePosture> {
  const rows: Record<string, PackagePosture> = {};
  for (const provider of loadProviders()) {
    if (provider.package === null) continue;
    // Every web provider's tools are external reads, whatever their names.
    if (provider.seam === "web")
      rows[normalizePackageSpec(provider.package)] = { posture: "research" };
    // perk never drives plannotator's plan phases (the adapter bridges `plan_review` to its event
    // API), so its phase tools are dead weight in every stage session.
    if (provider.id === PLANNOTATOR_PLAN_PROVIDER_ID) {
      rows[normalizePackageSpec(provider.package)] = { posture: "never" };
    }
  }
  // Frecency-ranked code search: reads only (its history lives outside the worktree).
  rows["npm:@ff-labs/pi-fff"] = { posture: "research" };
  // The questionnaire: a session-interaction tool every stage keeps.
  rows["npm:@juicesharp/rpiv-ask-user-question"] = { posture: "universal" };
  // Delegation (spawn/supervise/wait) belongs to the worktree flow.
  rows["npm:pi-subagents"] = { posture: "delegation" };
  // The implementation checklist rides the same worktree-flow posture as delegation.
  rows["npm:@juicesharp/rpiv-todo"] = { posture: "delegation" };
  // Linear reads are research; its mutators (and the auth writer, which edits the user's Pi auth
  // file) are the Python plane's job — eligible nowhere and blocked under the gate.
  rows["npm:pi-mono-linear"] = {
    posture: "research",
    except: {
      names: [
        "linear_create_issue",
        "linear_update_issue",
        "linear_create_comment",
        "linear_upload_file",
        "linear_upload_file_to_issue_comment",
        "linear_configure_auth",
      ],
      posture: "never",
    },
  };
  return rows;
}

/**
 * The package rows, keyed by normalized package spec (`normalizePackageSpec`). A package perk
 * wires with no row is either tool-less or `unknown` — a new borrow gets a row here (the Python
 * parity test pins the vocabulary against `perk init`'s package lists).
 */
export const PACKAGE_TOOL_POLICY: Readonly<Record<string, PackagePosture>> = packageToolPolicy();

/**
 * Exact synthetic-path rows — never a prefix rule, so an arbitrary `<inline:…>` extension stays
 * `unknown`. pi-subagents registers its in-child engine tools (`structured_output`,
 * `contact_supervisor`, `wait`) through this one named inline factory inside every spawned child.
 */
export const SYNTHETIC_PATH_TOOL_POLICY: Readonly<Record<string, ForeignPosture>> = {
  "<inline:pi-subagents:prompt-runtime>": "child-engine",
};

/** A builtin's row: its gate posture, its registrar, and whether the gate suspends it. */
export type BuiltinRow = {
  gated: BuiltinPosture;
  registrar: "core" | "extension";
  suspendedUnderGate?: true;
};

/**
 * Pi's builtin tools (provenance `source: "builtin"`), never stage-scoped. `registrar: "core"`
 * are the core tools; `extension` the CLI's builtin extensions. `bash` runs under the gate only
 * through `readOnlyBashVerdict`. `tool_search` is a read (what it activates is governed by this
 * table and the reconciliation). `codemode` is blocked AND suspended under the gate — the one
 * non-perk tool the gate ever deactivates: its description embeds the callable direct tools'
 * schemas (`edit`/`write` included), and in mode `only` its own loadout hook hides every callable
 * direct tool, so a hidden-but-active codemode would leave a gated session without `read`, `bash`
 * or perk's direct tools. The gate switches it off instead and back on at release.
 */
export const BUILTIN_TOOL_POLICY: Readonly<Record<string, BuiltinRow>> = {
  read: { gated: "allowed", registrar: "core" },
  grep: { gated: "allowed", registrar: "core" },
  find: { gated: "allowed", registrar: "core" },
  ls: { gated: "allowed", registrar: "core" },
  bash: { gated: "verdict", registrar: "core" },
  edit: { gated: "blocked", registrar: "core" },
  write: { gated: "blocked", registrar: "core" },
  tool_search: { gated: "allowed", registrar: "extension" },
  codemode: { gated: "blocked", registrar: "extension", suspendedUnderGate: true },
};

const BUILTIN_NAMES: readonly string[] = Object.keys(BUILTIN_TOOL_POLICY);

/**
 * Classify a tool. Precedence: the catalog by name (perk eligibility never depends on
 * provenance) → an exact synthetic path → a builtin-sourced builtin name → the package row (then
 * its `except` names) → `unknown` (an absent provenance included).
 */
export function postureFor(name: string, provenance: Provenance | undefined): Posture {
  const policy = CATALOG.get(name);
  if (policy !== undefined) return { owner: "perk", policy };
  if (provenance === undefined) return { owner: "unknown" };
  if (Object.hasOwn(SYNTHETIC_PATH_TOOL_POLICY, provenance.path)) {
    const posture = SYNTHETIC_PATH_TOOL_POLICY[provenance.path];
    if (posture !== undefined) return { owner: "foreign", posture, key: provenance.path };
  }
  if (provenance.source === "builtin" && Object.hasOwn(BUILTIN_TOOL_POLICY, name)) {
    const row = BUILTIN_TOOL_POLICY[name];
    if (row !== undefined) return { owner: "builtin", gated: row.gated };
  }
  const key = normalizePackageSpec(provenance.source);
  if (Object.hasOwn(PACKAGE_TOOL_POLICY, key)) {
    const row = PACKAGE_TOOL_POLICY[key];
    if (row !== undefined) {
      const posture = row.except?.names.includes(name) === true ? row.except.posture : row.posture;
      return { owner: "foreign", posture, key };
    }
  }
  return { owner: "unknown" };
}

// --- the formula + the derived views ------------------------------------------------------------

/**
 * A stage id the formula can scope by: a registry id, else null (absent or unknown — treated as
 * unscoped by every view, the fail-open posture for version skew).
 */
export function normalizeStage(stage: string | null | undefined): string | null {
  return typeof stage === "string" && REGISTRY_STAGE_SET.has(stage) ? stage : null;
}

/**
 * The eligibility formula:
 *   (stage ∈ stages ∧ (mode = read-write ∨ gated ≠ blocked)) ∨ (mode = read-only ∧ modeOverStage)
 * with an unscoped stage eligible for exactly the tools the mode allows — the mode-over-stage term
 * scopes known stages only, so a gate-blocked tool never activates in an unscoped gated session.
 */
function formula(
  stages: readonly string[],
  notBlocked: boolean,
  modeOverStage: boolean,
  stage: string | null,
  mode: Mode,
): boolean {
  const modeAllows = mode === "read-write" || notBlocked;
  if (stage === null) return modeAllows;
  return (stages.includes(stage) && modeAllows) || (mode === "read-only" && modeOverStage);
}

/**
 * Whether a tool is eligible in a (stage, mode) landing. A perk tool is classified by its catalog
 * name (pass `undefined` provenance freely); every other tool by its provenance — an `unknown`
 * one is eligible only read-write (it passes every diet; under the gate the backstop blocks it).
 */
export function isEligible(
  name: string,
  provenance: Provenance | undefined,
  stage: string | null | undefined,
  mode: Mode,
): boolean {
  const scoped = normalizeStage(stage);
  const posture = postureFor(name, provenance);
  switch (posture.owner) {
    case "perk": {
      const { policy } = posture;
      return formula(
        policy.stages,
        policy.gated !== "blocked",
        policy.modeOverStage === true,
        scoped,
        mode,
      );
    }
    case "foreign": {
      const row = POSTURE_ROWS[posture.posture];
      return formula(row.stages, row.gated !== "blocked", false, scoped, mode);
    }
    case "builtin":
      return mode === "read-write" || posture.gated !== "blocked";
    case "unknown":
      return mode === "read-write";
  }
}

/**
 * The eligible always-declared perk tools for a (stage, mode) landing, in catalog order —
 * deferred tools are never activated by perk.
 */
export function perkToolsFor(stage: string | null | undefined, mode: Mode): string[] {
  return [...CATALOG].flatMap(([name, policy]) =>
    policy.declared !== "deferred" && isEligible(name, undefined, stage, mode) ? [name] : [],
  );
}

/** The gate-ON perk activation view for a stage (`perkToolsFor(stage, "read-only")`). */
export function gatedToolsFor(stage: string | null | undefined): readonly string[] {
  return perkToolsFor(stage, "read-only");
}

/** The gate-OFF perk activation view for a stage; undefined when unscoped (no diet). */
export function stageToolsFor(stage: string | null | undefined): readonly string[] | undefined {
  if (normalizeStage(stage) === null) return undefined;
  return perkToolsFor(stage, "read-write");
}

/** The carve-out writers eligible under the gate for a stage, in catalog order. */
export function carveOutWritersFor(
  stage: string | null | undefined,
): { name: string; carveOut: string }[] {
  const writers: { name: string; carveOut: string }[] = [];
  for (const [name, policy] of CATALOG) {
    if (typeof policy.gated !== "object" || policy.declared === "deferred") continue;
    if (isEligible(name, undefined, stage, "read-only")) {
      writers.push({ name, carveOut: policy.gated.carveOut });
    }
  }
  return writers;
}

// --- own-names-only activation + presentation ---------------------------------------------------

/**
 * The active set perk installs for a (stage, mode) landing, or null when the live set already
 * equals it (order-insensitive) — so a session whose live set needs no change gets no install:
 *   (live active − perk-owned) ∪ eligible-always-perk ∪ (live active ∩ eligible-deferred-perk)
 * Foreign names keep their live order and membership (perk never activates or deactivates one);
 * perk names follow in catalog order. Only REGISTERED perk names count: a catalogued name the host
 * did not register (a vacated provider tool, a host registry filter) is never installed.
 */
export function reconcileTarget(
  live: { active: readonly string[]; registered: readonly string[] },
  stage: string | null | undefined,
  mode: Mode,
): string[] | null {
  const registered = new Set(live.registered);
  const active = new Set(live.active);
  const foreign = live.active.filter((name) => !CATALOG.has(name));
  const perk = [...CATALOG].flatMap(([name, policy]) => {
    if (!registered.has(name) || !isEligible(name, undefined, stage, mode)) return [];
    return policy.declared !== "deferred" || active.has(name) ? [name] : [];
  });
  const target = [...foreign, ...perk];
  return sameNames(target, live.active) ? null : target;
}

/**
 * The declarations the loadout host hides from the next request: itself always, plus every
 * declared tool ineligible in the landing (by its provenance — `infos` maps each registered name
 * to its `sourceInfo`). Presentation only: hidden tools stay active and callable; the read-only
 * `tool_call` backstop is the enforcement.
 */
export function hiddenDeclarationsFor(
  declared: readonly string[],
  infos: ReadonlyMap<string, Provenance>,
  stage: string | null | undefined,
  mode: Mode,
): string[] {
  const hidden = [LOADOUT_HOST_NAME];
  for (const name of declared) {
    if (name === LOADOUT_HOST_NAME) continue;
    if (!isEligible(name, infos.get(name), stage, mode)) hidden.push(name);
  }
  return hidden;
}

/** Whether the read-only gate suspends this tool: a builtin-sourced row marked suspended. */
export function gateSuspends(name: string, provenance: Provenance | undefined): boolean {
  if (provenance?.source !== "builtin" || !Object.hasOwn(BUILTIN_TOOL_POLICY, name)) return false;
  return BUILTIN_TOOL_POLICY[name]?.suspendedUnderGate === true;
}

/**
 * The gate's suspension step, applied to the live active set before `reconcileTarget`: presenting
 * read-only removes every active suspended builtin (remembering it); presenting read-write
 * restores what the gate suspended earlier, when still registered and inactive, and forgets the
 * memo. `suspended` is the memo to keep once the install succeeds.
 */
export function suspensionStep(
  live: { active: readonly string[]; infos: ReadonlyMap<string, Provenance> },
  mode: Mode,
  suspended: readonly string[],
): { active: string[]; suspended: string[] } {
  if (mode === "read-only") {
    const now = live.active.filter((name) => gateSuspends(name, live.infos.get(name)));
    return {
      active: live.active.filter((name) => !now.includes(name)),
      suspended: [...new Set([...suspended, ...now])],
    };
  }
  const restore = suspended.filter(
    (name) => gateSuspends(name, live.infos.get(name)) && !live.active.includes(name),
  );
  return { active: [...live.active, ...restore], suspended: [] };
}

/** Whether two name lists hold the same names (order-insensitive). */
export function sameNames(a: readonly string[], b: readonly string[]): boolean {
  const left = new Set(a);
  const right = new Set(b);
  return left.size === right.size && [...left].every((name) => right.has(name));
}

// --- the golden matrix --------------------------------------------------------------------------

/** One tool's row in the golden matrix (`shared/fixtures/tool-matrix.json`). */
export type ToolMatrixEntry =
  | {
      owner: "perk";
      kind: ToolKind;
      stages: string[];
      gated: "allowed" | "blocked" | "carve-out";
      mode_over_stage: boolean;
      declared: Declared;
      exposure: PiToolMetadata["exposure"];
    }
  | { owner: "builtin"; gated: BuiltinPosture; registrar: "core" | "extension" };

/** One foreign posture row as the matrix renders it. */
export type PostureMatrixEntry = {
  posture: ForeignPosture;
  stages: "all" | string[];
  gated: "allowed" | "blocked";
};

/** The derived stage×tool matrix both planes' prompt guards (and the posture parity test) read. */
export type ToolMatrix = {
  $comment: string;
  stages: string[];
  tools: Record<string, ToolMatrixEntry>;
  postures: {
    packages: Record<
      string,
      PostureMatrixEntry & { except?: { names: string[]; posture: ForeignPosture } }
    >;
    paths: Record<string, PostureMatrixEntry>;
    unknown: { stages: "all"; gated: "blocked" };
  };
  eligible: Record<string, { "read-only": string[]; "read-write": string[] }>;
};

/** The matrix's key for the unscoped (`null`) landing. */
export const UNSCOPED_MATRIX_KEY = "unscoped";

function registryOrdered(stages: readonly string[]): string[] {
  return REGISTRY_STAGE_IDS.filter((id) => stages.includes(id));
}

function postureEntry(posture: ForeignPosture): PostureMatrixEntry {
  const row = POSTURE_ROWS[posture];
  const all = REGISTRY_STAGE_IDS.every((id) => row.stages.includes(id));
  return { posture, stages: all ? "all" : registryOrdered(row.stages), gated: row.gated };
}

/** The golden matrix, derived from the catalog + the posture table (order-independent). */
export function toolMatrix(): ToolMatrix {
  const tools: Record<string, ToolMatrixEntry> = {};
  for (const [name, row] of Object.entries(BUILTIN_TOOL_POLICY)) {
    tools[name] = { owner: "builtin", gated: row.gated, registrar: row.registrar };
  }
  for (const [name, policy] of CATALOG) {
    tools[name] = {
      owner: "perk",
      kind: policy.kind,
      stages: registryOrdered(policy.stages),
      gated: typeof policy.gated === "object" ? "carve-out" : policy.gated,
      mode_over_stage: policy.modeOverStage === true,
      declared: policy.declared ?? "always",
      exposure: derivePiMetadata(policy).exposure,
    };
  }
  const packages: ToolMatrix["postures"]["packages"] = {};
  for (const [spec, row] of Object.entries(PACKAGE_TOOL_POLICY)) {
    packages[spec] = {
      ...postureEntry(row.posture),
      ...(row.except !== undefined
        ? { except: { names: [...row.except.names], posture: row.except.posture } }
        : {}),
    };
  }
  const paths: ToolMatrix["postures"]["paths"] = {};
  for (const [path, posture] of Object.entries(SYNTHETIC_PATH_TOOL_POLICY)) {
    paths[path] = postureEntry(posture);
  }
  const sorted = (names: Iterable<string>): string[] => [...new Set(names)].sort();
  const builtinsFor = (mode: Mode): string[] =>
    BUILTIN_NAMES.filter((name) =>
      isEligible(name, { path: `builtin:${name}`, source: "builtin" }, null, mode),
    );
  const eligible: ToolMatrix["eligible"] = {};
  for (const stage of [...REGISTRY_STAGE_IDS, null]) {
    eligible[stage ?? UNSCOPED_MATRIX_KEY] = {
      "read-only": sorted([...perkToolsFor(stage, "read-only"), ...builtinsFor("read-only")]),
      "read-write": sorted([...perkToolsFor(stage, "read-write"), ...builtinsFor("read-write")]),
    };
  }
  return {
    $comment:
      "GENERATED by extension/substrate/toolMatrix.test.ts (PERK_UPDATE_TOOL_MATRIX=1 node --test extension/substrate/toolMatrix.test.ts) — do not edit",
    stages: [...REGISTRY_STAGE_IDS],
    tools,
    postures: { packages, paths, unknown: { stages: "all", gated: "blocked" } },
    eligible,
  };
}
