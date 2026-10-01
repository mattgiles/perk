// The tool catalog and the one eligibility formula (contracts.md §8.40). Every perk tool is
// registered through `registerPerkTool` (`pi/perkTool.ts`) with a policy descriptor; the catalog
// records it, and every view the gate and stage scoping install — the gated (read-only) view, the
// gate-OFF stage diet, the carve-out writer list the read-only context names, the Pi metadata
// (`exposure`, `annotations.readOnlyHint`) and the golden stage×tool matrix — is DERIVED from the
// descriptors plus the interim foreign/builtin posture rows below. Nothing here is hand-listed per
// stage.
//
// Pure: no Pi runtime, no session state beyond the process-wide catalog. The catalog fills as the
// installers register; derived views and the read-only context are computed per call, never at
// module load.

import { loadRegistry, stageConsumesPlanRef } from "./registry.ts";

// --- the borrowed tool families -----------------------------------------------------------------

/**
 * The `web` seam providers' research tools: the UNION of all known web-provider tool names,
 * enumerated statically and inert when the package is absent (the plan_review precedent —
 * setActiveTools simply has nothing to enable). None mutate the repo — fetch_content's
 * GitHub-clone path (and source_check's page fetches) write only to their own cache outside the
 * worktree, morally equivalent to the already-allowlisted curl. perk does NOT normalize names, so
 * all three providers' divergent names are listed: pi-web-access (its four default tools
 * web_search/source_check/fetch_content/get_search_content, plus its lazy loader `web_enable` —
 * see `LAZY_TOOL_LOADERS` in toolGating.ts; `code_search` is not registered by any current
 * version and is kept as an inert static name for version tolerance), @ollama/pi-web-search (ollama_web_search/
 * ollama_web_fetch), and @juicesharp/rpiv-web-tools (web_search shared, web_fetch). All register
 * at load time; `web_enable` registers only when pi-web-access's dynamic-tools probe passes (an
 * inert name otherwise).
 */
export const WEB_RESEARCH_TOOLS: readonly string[] = [
  "web_search",
  "code_search",
  "fetch_content",
  "get_search_content",
  "source_check",
  "web_enable",
  "ollama_web_search",
  "ollama_web_fetch",
  "web_fetch",
];

/**
 * pi-mono-linear's read-only tools (the [issues] backend = "linear" selection): none mutate
 * Linear or the repo. Foreign names are inert when the package is absent (the pi-web-access
 * precedent above). The mutating/sensitive tools live in LINEAR_MUTATING_TOOLS and are
 * deliberately blocked under the read-only gate AND eligible in no stage. All 25 register at
 * load time (verified against the upstream pi-mono-extensions source).
 */
export const LINEAR_READ_TOOLS: readonly string[] = [
  "linear_whoami",
  "linear_workspace_metadata",
  "linear_list_teams",
  "linear_get_team",
  "linear_list_users",
  "linear_get_user",
  "linear_list_issues",
  "linear_get_issue",
  "linear_search_issues",
  "linear_list_my_issues",
  "linear_list_projects",
  "linear_get_project",
  "linear_list_issue_statuses",
  "linear_get_issue_status",
  "linear_list_labels",
  "linear_list_cycles",
  "linear_list_documents",
  "linear_get_document",
  "linear_list_comments",
];

/**
 * pi-mono-linear's mutating/sensitive tools — in the borrowed census so every stage session
 * sheds their schemas, and eligible in NO stage: Linear mutations are the Python plane's job
 * (`linear_configure_auth` even writes ~/.pi/agent/auth.json). Bare/unscoped sessions keep
 * full access.
 */
export const LINEAR_MUTATING_TOOLS: readonly string[] = [
  "linear_create_issue",
  "linear_update_issue",
  "linear_create_comment",
  "linear_upload_file",
  "linear_upload_file_to_issue_comment",
  "linear_configure_auth",
];

/**
 * pi-subagents' delegation family. `subagent`/`wait` register at load time; the parent supervisor
 * tool `subagent_supervisor` registers during pi-subagents' own `session_start` — AFTER perk's
 * sync (perk is the first `packages` entry) — and is admitted by the `resources_discover`
 * re-apply as a late registrant (see `baseline`): inside the diet at launch, kept where its row
 * makes it eligible. `subagents_enable` is pi-subagents' lazy loader (see `LAZY_TOOL_LOADERS`): it
 * registers at load time when the host supports dynamic tools; pi-subagents hides `subagent` in
 * its own `session_start`/`session_tree` handlers on a message-less branch (or replays the
 * transcript's recorded `toolsAdded`/`toolsRemoved`), and re-adds the loader to the active set
 * and `selectedTools` in its own `before_agent_start` — which runs AFTER perk's handlers
 * (extension order), so perk can refuse the loader but never hide it. `intercom` is the separate
 * pi-intercom bridge's tool name — a static census entry, inert unless that package is present.
 * Child-side tools (`structured_output`, `contact_supervisor`) are out of scope for the STAGE
 * census — spawned children stay stage-unscoped by design (§8.40 adopt-never-impersonates) — but
 * they ARE eligible under the read-only gate, because the gate IS inherited by adopted children
 * (see SUBAGENT_CHILD_TOOLS).
 */
export const SUBAGENT_TOOLS: readonly string[] = [
  "subagent",
  "subagents_enable",
  "wait",
  "subagent_supervisor",
  "intercom",
];

/**
 * pi-subagents' CHILD-side engine tools. `structured_output` and `contact_supervisor` register
 * inside spawned child sessions through the engine's prompt runtime / native supervisor bridge.
 * Absent tools are inert in gated parents (`setActiveTools` ignores unknown names). A gated
 * ADOPTED child (mode inherited via the `adopt` arm, contracts.md §8.3) must keep them active:
 *  - `structured_output` is the engine-REQUIRED completion call when the launch carries an
 *    `outputSchema` — stripping it makes the child physically unable to finish and fails the
 *    run with `structuredOutputFailed`;
 *  - `contact_supervisor` is the child→parent supervisor door. Perk's OWN waves never carry it
 *    (every wave spawns with the intercom bridge off — `WAVE_INTERCOM_BRIDGE` — so it is simply
 *    absent there), but this gate posture governs EVERY gated adopted child, including an ad-hoc
 *    `subagent` spawn from a gated session whose bridge is still active: stripping the tool
 *    there would leave the child unable to make a `need_decision` ask while the parent keeps
 *    `subagent_supervisor` to answer it. Gate membership is inertness-safe, never a grant.
 * Native wakes need no wait-tool widening in this census.
 * None mutates the repo (`structured_output` writes only the engine's capture file among the
 * child artifacts under the session directory — pi-subagents ≥ 0.66.0; `pi/subagents.md`
 * § "Child artifacts and wave cleanup"). Census decision, recorded: these names deliberately
 * join NEITHER the perk catalog nor BORROWED_TOOLS — the stage-filter universe never sees them
 * because children are stage-unscoped by design (adopt never impersonates a stage), so gate
 * membership is their only governance surface.
 */
export const SUBAGENT_CHILD_TOOLS: readonly string[] = ["structured_output", "contact_supervisor"];

/**
 * @ff-labs/pi-fff's search tools. BOTH mode name-sets are enumerated (static names, inert
 * when absent — the code_search version-tolerance precedent): pi-fff's own default is the
 * additive tools-and-ui mode (fffind/ffgrep [+ fff-multi-grep when enabled upstream]) beside
 * pi's builtin find/grep; perk injects no mode (pi-fff's CLI flag → `PI_FFF_MODE` →
 * `pi-fff.json` precedence decides). The override name-set (multi_grep; find/grep already
 * allowlisted/pass-through) stays enumerated for an operator `PI_FFF_MODE=override` opt-in.
 * All register at load time. Frecency/history state lives under ~/.pi/agent/fff/ — outside
 * the worktree (the fetch_content cache-write precedent), so the read-only bar holds.
 */
export const FFF_SEARCH_TOOLS: readonly string[] = [
  "fffind",
  "ffgrep",
  "fff-multi-grep",
  "multi_grep",
];

/**
 * @plannotator/pi-extension's plan-phase tools. Both register at LOAD time; plannotator strips
 * them in its OWN `session_start` (the idle-phase `stripPlanningOnlyTools`), which runs AFTER
 * perk's first-engagement snapshot (perk is the first `packages` entry, so its `session_start`
 * sync fires first). Enumeration is therefore load-bearing, not cosmetic: an un-enumerated name
 * sits in the snapshot as a non-scoped passthrough, and the `resources_discover` re-apply
 * re-installs `snapshot ∪ admitted` over plannotator's strip — restoring the tool to every
 * gate-OFF stage session. Perk never drives plannotator's plan phases (the adapter bridges
 * `plan_review` to its event API), so both are dead weight there: in the census, in NO stage
 * list. Bare/unscoped sessions are untouched.
 */
export const PLANNOTATOR_PHASE_TOOLS: readonly string[] = [
  "plannotator_submit_plan",
  "plannotator_mark_done",
];

/**
 * The enumerated borrowed-package tool census (contracts.md §8.40): every foreign tool name perk
 * wires — via `BORROWED_PACKAGES`, a provider package, or the linear issue backend — joins the
 * scoped universe beside the perk catalog. Static-name posture: names are
 * inert when the package is absent, and un-enumerated foreign names always pass through every
 * stage filter (fail-open — enumeration here is diet-completeness, not correctness).
 *
 * Audit records (the per-package census):
 *  - Registration timing: every census name registers at load time EXCEPT pi-subagents'
 *    `subagent_supervisor` (SUBAGENT_TOOLS — session_start; admitted at `resources_discover`).
 *  - Foreign `setActiveTools` owners: plannotator's phase machinery and @tombell/pi-plan's plan
 *    mode run their OWN toggles — perk re-applies only at its reconciliation points (the rebuilds
 *    + the startup `resources_discover` re-apply), so a toggle between them wins (fail-open) and
 *    every reconciliation re-installs perk's set over it, admitted late tools included (§8.40).
 *  - Zero-tool packages: @tombell/pi-diff (commands only), the footer providers, and the hunk
 *    review CLI (not a Pi package) register nothing — nothing to enumerate.
 *  - Single-governance rule: a name is governed ONCE — it lives in exactly one census. perk
 *    registers no same-named `ask_user_question` anymore (the first-party tool is deleted), so
 *    the name lives HERE, in the borrowed census, not in the perk catalog (hygiene-tested).
 *    Registration timing nuance: @juicesharp/rpiv-ask-user-question registers the tool at load
 *    time, then a `hasUI`-keyed reconcile strips/restores it — headless sessions carry no
 *    `ask_user_question` schema at all.
 *  - @ff-labs/pi-fff (FFF_SEARCH_TOOLS): registration timing load-time (both modes); no
 *    `setFooter` (only a keyed optional-chained `setStatus`); zero bundled skills.
 *  - Lazy owners (LAZY_TOOL_LOADERS): pi-subagents and pi-web-access each hide their heavy
 *    tools behind a loader and replay the selection on `session_start`/`session_tree` — with
 *    DIFFERENT rules. pi-subagents: recorded declarations → replay; no messages → hide;
 *    messages without declarations → keep the current state; its `before_agent_start` edits
 *    `selectedTools` AND the active set. pi-web-access: declarations → replay; no messages →
 *    hide; messages without declarations → enable ALL its tools; its `before_agent_start` only
 *    re-adds the loader to the active set. perk's single answer to both: owner-selected
 *    membership at every reconciliation (`ownerSelected` in toolGating.ts) + the loader refusal
 *    in `tool_call`.
 */
export const BORROWED_TOOLS: readonly string[] = [
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  ...LINEAR_MUTATING_TOOLS,
  ...SUBAGENT_TOOLS,
  ...FFF_SEARCH_TOOLS,
  // @juicesharp/rpiv-todo (required borrow) — registers at load; its checklist overlay is
  // `hasUI`-gated (headless-safe).
  "todo",
  // @juicesharp/rpiv-ask-user-question (required borrow) — registers at load; strips itself
  // headlessly (!hasUI reconcile).
  "ask_user_question",
  // @plannotator/pi-extension's phase tools — see PLANNOTATOR_PHASE_TOOLS for the
  // registration-timing fact that makes enumerating every one of them load-bearing.
  ...PLANNOTATOR_PHASE_TOOLS,
];

// --- the policy descriptor ----------------------------------------------------------------------

/**
 * What a tool IS. Anything that can return `terminate: true` is `terminal`; a tool that opens a
 * human surface and hands off to it without terminating is `interactive`; anything that spawns
 * children, a wave or a foreground child/resolver is `orchestration`; a pure read is `query`;
 * the rest — including tools whose only dialog is a trust/confirm gate — is `action`.
 */
export type ToolKind = "terminal" | "interactive" | "orchestration" | "query" | "action";
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

// --- the interim foreign + builtin posture rows -------------------------------------------------

/** A foreign family's interim posture: the stages it is eligible in and its gate posture. */
export type ForeignToolRow = {
  names: readonly string[];
  stages: readonly string[];
  gated: "allowed" | "blocked";
};

/**
 * The interim name-keyed posture rows for foreign tools — the borrowed census plus the
 * pi-subagents child-side tools. Interim by design: provenance-derived rows replace this table
 * and the borrowed family constants above. `SUBAGENT_CHILD_TOOLS` sit outside the gate-OFF diet
 * universe (stage-unscoped children pass through the diet); their row excludes
 * `objective-refine`, the refinement session's least-privilege selection (contracts.md §8.68).
 */
export const FOREIGN_TOOL_POLICY: readonly ForeignToolRow[] = [
  { names: ["ask_user_question"], stages: REGISTRY_STAGE_IDS, gated: "allowed" },
  {
    names: [...WEB_RESEARCH_TOOLS, ...LINEAR_READ_TOOLS, ...FFF_SEARCH_TOOLS],
    stages: REGISTRY_STAGE_IDS,
    gated: "allowed",
  },
  { names: SUBAGENT_TOOLS, stages: [...WORKTREE_STAGES, "stack-review"], gated: "allowed" },
  { names: ["todo"], stages: WORKTREE_STAGES, gated: "blocked" },
  { names: [...LINEAR_MUTATING_TOOLS, ...PLANNOTATOR_PHASE_TOOLS], stages: [], gated: "blocked" },
  {
    names: SUBAGENT_CHILD_TOOLS,
    stages: REGISTRY_STAGE_IDS.filter((id) => id !== "objective-refine"),
    gated: "allowed",
  },
];

/** A builtin's gate posture: `verdict` = allowed under the gate, subject to the bash verdict. */
export type BuiltinPosture = "allowed" | "blocked" | "verdict";

/**
 * Pi's builtin tools: never stage-scoped (outside the diet universe — they pass through), never
 * scanned by the prompt guard. `bash` runs under the gate only through `readOnlyBashVerdict`.
 */
export const BUILTIN_TOOL_POLICY: Readonly<Record<string, BuiltinPosture>> = {
  read: "allowed",
  grep: "allowed",
  find: "allowed",
  ls: "allowed",
  bash: "verdict",
  edit: "blocked",
  write: "blocked",
};

const BUILTIN_NAMES: readonly string[] = Object.keys(BUILTIN_TOOL_POLICY);
const FOREIGN_NAMES: readonly string[] = FOREIGN_TOOL_POLICY.flatMap((row) => row.names);
const FOREIGN_BY_NAME: ReadonlyMap<string, ForeignToolRow> = new Map(
  FOREIGN_TOOL_POLICY.flatMap((row) => row.names.map((name) => [name, row] as const)),
);
const BORROWED_SET: ReadonlySet<string> = new Set(BORROWED_TOOLS);

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
 * Whether a tool is eligible in a (stage, mode) landing — over the catalog, the foreign rows and
 * the builtin rows. Any other name is eligible only read-write (fail-open pass-through; under the
 * gate the backstop blocks it).
 */
export function isEligible(name: string, stage: string | null | undefined, mode: Mode): boolean {
  const scoped = normalizeStage(stage);
  const perk = CATALOG.get(name);
  if (perk !== undefined) {
    return formula(
      perk.stages,
      perk.gated !== "blocked",
      perk.modeOverStage === true,
      scoped,
      mode,
    );
  }
  const foreign = FOREIGN_BY_NAME.get(name);
  if (foreign !== undefined) {
    return formula(foreign.stages, foreign.gated !== "blocked", false, scoped, mode);
  }
  if (Object.hasOwn(BUILTIN_TOOL_POLICY, name)) {
    return mode === "read-write" || BUILTIN_TOOL_POLICY[name] !== "blocked";
  }
  return mode === "read-write";
}

/** Deferred tools are never activated by perk — excluded from both activation views. */
function isDeferred(name: string): boolean {
  return CATALOG.get(name)?.declared === "deferred";
}

/**
 * The gate-ON activation view for a stage: every eligible read-only name, in canonical order —
 * builtins, then the foreign rows in table order, then perk tools in catalog order.
 */
export function gatedToolsFor(stage: string | null | undefined): readonly string[] {
  return [...BUILTIN_NAMES, ...FOREIGN_NAMES, ...perkToolNames()].filter(
    (name) => !isDeferred(name) && isEligible(name, stage, "read-only"),
  );
}

/**
 * The gate-OFF diet universe: the catalogued perk tools plus the borrowed census. Builtins,
 * child-side tools and un-enumerated foreign names sit outside it and pass through every diet.
 */
export function dietUniverse(): string[] {
  return [...FOREIGN_NAMES.filter((name) => BORROWED_SET.has(name)), ...perkToolNames()];
}

/** The gate-OFF diet for a stage over the diet universe; undefined when unscoped (no diet). */
export function stageToolsFor(stage: string | null | undefined): readonly string[] | undefined {
  if (normalizeStage(stage) === null) return undefined;
  return dietUniverse().filter(
    (name) => !isDeferred(name) && isEligible(name, stage, "read-write"),
  );
}

/** The carve-out writers eligible under the gate for a stage, in catalog order. */
export function carveOutWritersFor(
  stage: string | null | undefined,
): { name: string; carveOut: string }[] {
  const writers: { name: string; carveOut: string }[] = [];
  for (const [name, policy] of CATALOG) {
    if (typeof policy.gated !== "object" || policy.declared === "deferred") continue;
    if (isEligible(name, stage, "read-only")) {
      writers.push({ name, carveOut: policy.gated.carveOut });
    }
  }
  return writers;
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
  | { owner: "foreign"; stages: "all" | string[]; gated: "allowed" | "blocked" }
  | { owner: "builtin"; gated: BuiltinPosture };

/** The derived stage×tool matrix both planes' prompt guards read. */
export type ToolMatrix = {
  $comment: string;
  stages: string[];
  tools: Record<string, ToolMatrixEntry>;
  eligible: Record<string, { "read-only": string[]; "read-write": string[] }>;
};

/** The matrix's key for the unscoped (`null`) landing. */
export const UNSCOPED_MATRIX_KEY = "unscoped";

function registryOrdered(stages: readonly string[]): string[] {
  return REGISTRY_STAGE_IDS.filter((id) => stages.includes(id));
}

/** The golden matrix, derived from the catalog + the posture rows (order-independent). */
export function toolMatrix(): ToolMatrix {
  const tools: Record<string, ToolMatrixEntry> = {};
  for (const name of BUILTIN_NAMES) {
    tools[name] = { owner: "builtin", gated: BUILTIN_TOOL_POLICY[name] ?? "blocked" };
  }
  for (const row of FOREIGN_TOOL_POLICY) {
    const all = REGISTRY_STAGE_IDS.every((id) => row.stages.includes(id));
    for (const name of row.names) {
      tools[name] = {
        owner: "foreign",
        stages: all ? "all" : registryOrdered(row.stages),
        gated: row.gated,
      };
    }
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
  const passThrough = [
    ...BUILTIN_NAMES,
    ...FOREIGN_NAMES.filter((name) => !BORROWED_SET.has(name)),
  ];
  const sorted = (names: Iterable<string>): string[] => [...new Set(names)].sort();
  const eligible: ToolMatrix["eligible"] = {};
  for (const stage of REGISTRY_STAGE_IDS) {
    eligible[stage] = {
      "read-only": sorted(gatedToolsFor(stage)),
      "read-write": sorted([...(stageToolsFor(stage) ?? []), ...passThrough]),
    };
  }
  eligible[UNSCOPED_MATRIX_KEY] = {
    "read-only": sorted(gatedToolsFor(null)),
    "read-write": sorted(Object.keys(tools)),
  };
  return {
    $comment:
      "GENERATED by extension/substrate/toolMatrix.test.ts (PERK_UPDATE_TOOL_MATRIX=1 node --test extension/substrate/toolMatrix.test.ts) — do not edit",
    stages: [...REGISTRY_STAGE_IDS],
    tools,
    eligible,
  };
}
