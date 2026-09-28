// The tool-gating primitive (the keystone). Structural read-only enforcement, NOT
// prompting. Mirrors pi's authoritative `examples/extensions/plan-mode/` recipe (the
// `setActiveTools` allowlist + `tool_call` bash sub-allowlist + `before_agent_start` injection
// (once-only per SELECTED BRANCH: full-branch-scan dedup'd on the marker — historical, so a
// copy compaction has summarized out of model context still suppresses; enforcement never rode
// the prose) + `context` strip-when-off) and `preset.ts`'s snapshot-then-restore. The gate attaches to the
// existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no new registry stage.
// Beside the gate lives STAGE_TOOLS: per-stage active-tool scoping for the scoped universe
// (perk's OWN registered tools + the enumerated borrowed-package census), keyed off the
// workflow-state `stage` field and applied at the same rebuild points (contracts.md §8.40) —
// fail-open where the gate is fail-closed, save the one refused call: a borrowed lazy loader
// invoked where the tools it enables are ineligible.
//
// Substrate only: the gate-ENTRY consumers are perk-owned plan mode (`pi/v1/plan.ts`: `/plan`,
// `--plan`, `Ctrl+Alt+P`), the warm `/objective-plan` factory (`pi/v1/objectivePlanning.ts`) and
// the warm `/objective-refine` entry (`pi/v1/objectiveRefinement.ts`); `exit` rides the plan-mode
// toggle and the save/exit doors. The CI executor (`pi/v1/delivery/ci.ts`) never touches the gate.
// The allowlist-restore is wired into the existing `session_start`/`session_tree` rebuild points
// plus one `resources_discover` re-apply.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { commandPositions, REFUSAL_REASONS } from "./commandPositions.ts";
import { render } from "./prompts.ts";
import { branchCarries, branchOf, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/**
 * The `web` seam providers' research tools: the UNION of all known web-provider tool names,
 * enumerated statically and inert when the package is absent (the plan_review precedent —
 * setActiveTools simply has nothing to enable). None mutate the repo — fetch_content's
 * GitHub-clone path (and source_check's page fetches) write only to their own cache outside the
 * worktree, morally equivalent to the already-allowlisted curl. perk does NOT normalize names, so
 * all three providers' divergent names are listed: pi-web-access (its four default tools
 * web_search/source_check/fetch_content/get_search_content, plus its lazy loader `web_enable` —
 * see LAZY_TOOL_LOADERS; `code_search` is not registered by any current version and is kept as an
 * inert static name for version tolerance), @ollama/pi-web-search (ollama_web_search/
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
 * deliberately excluded from the read-only gate AND from every stage list. All 25 register at
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
 * sheds their schemas, and in NO stage list: Linear mutations are the Python plane's job
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
 * re-apply as a late registrant (see `baseline`): inside the diet at launch, kept where a stage
 * list carries it. `subagents_enable` is pi-subagents' lazy loader (see LAZY_TOOL_LOADERS): it
 * registers at load time when the host supports dynamic tools; pi-subagents hides `subagent` in
 * its own `session_start`/`session_tree` handlers on a message-less branch (or replays the
 * transcript's recorded `toolsAdded`/`toolsRemoved`), and re-adds the loader to the active set
 * and `selectedTools` in its own `before_agent_start` — which runs AFTER perk's handlers
 * (extension order), so perk can refuse the loader but never hide it. `intercom` is the separate
 * pi-intercom bridge's tool name — a static census entry, inert unless that package is present.
 * Child-side tools (`structured_output`, `contact_supervisor`) are out of scope for the STAGE
 * census — spawned children stay stage-unscoped by design (§8.40 adopt-never-impersonates) — but
 * they DO ride READ_ONLY_TOOLS, because the read-only gate IS inherited by adopted children (see
 * SUBAGENT_CHILD_TOOLS).
 */
export const SUBAGENT_TOOLS: readonly string[] = [
  "subagent",
  "subagents_enable",
  "wait",
  "subagent_supervisor",
  "intercom",
];

/**
 * Borrowed lazy-activation loaders → the tools each one activates (contracts.md §8.40). While
 * the loader is registered, a lazy-owned tool's ACTIVATION is its owner's decision — the owner
 * hides it until the model calls the loader, and replays the recorded selection on navigation;
 * perk owns only its ELIGIBILITY (mode/stage). Each loader rides the same family constant as the tools it enables, so its
 * eligibility equals theirs everywhere (pinned). Look entries up with `Object.hasOwn` first: a
 * tool named like a prototype key must not match.
 */
export const LAZY_TOOL_LOADERS: Readonly<Record<string, readonly string[]>> = {
  subagents_enable: ["subagent"],
  web_enable: ["web_search", "source_check", "fetch_content", "get_search_content"],
};

/**
 * The tools lazy-owned in this session: those of every loader currently REGISTERED (active or
 * not). An owner that registers its tools eagerly and no loader — an older version, or its
 * host-probe fallback — owns nothing lazily: nothing could re-enable a tool perk stripped, so its
 * tools keep the ordinary snapshot/allowlist behavior.
 */
function lazyOwnedBy(registered: Iterable<string>): ReadonlySet<string> {
  const owned = new Set<string>();
  for (const name of registered) {
    if (!Object.hasOwn(LAZY_TOOL_LOADERS, name)) continue;
    for (const tool of LAZY_TOOL_LOADERS[name] ?? []) owned.add(tool);
  }
  return owned;
}

/** The live tool state one install reads: the active set + the tools lazy-owned right now. */
type LiveSelection = { active: ReadonlySet<string>; lazyOwned: ReadonlySet<string> };

/**
 * Owner-selected membership: drop a lazy-owned name unless its owner currently has it active.
 * Every other name passes through.
 */
function ownerSelected(names: Iterable<string>, live: LiveSelection): string[] {
  return [...names].filter((name) => !live.lazyOwned.has(name) || live.active.has(name));
}

/** Where a loader call was refused: under the gate (optionally stage-scoped), or by a stage. */
export type LazyLoaderRefusalScope =
  | { kind: "gated"; stage: string | null }
  | { kind: "stage"; stage: string };

/** The stage-naming refusal reason for a loader called outside its tools' eligibility. */
export function lazyLoaderRefusalReason(loader: string, scope: LazyLoaderRefusalScope): string {
  const enabled = Object.hasOwn(LAZY_TOOL_LOADERS, loader) ? LAZY_TOOL_LOADERS[loader] : undefined;
  const tools = (enabled ?? []).join(", ");
  if (scope.kind === "gated") {
    const where = scope.stage === null ? "this gated session" : `the gated ${scope.stage} session`;
    return `perk read-only mode: ${loader} is blocked (its tools — ${tools} — are not allowlisted in ${where}).`;
  }
  return `perk stage scoping: ${loader} is blocked (its tools — ${tools} — are not available in the ${scope.stage} stage).`;
}

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
 *    absent there), but this allowlist governs EVERY gated adopted child, including an ad-hoc
 *    `subagent` spawn from a gated session whose bridge is still active: stripping the tool
 *    there would leave the child unable to make a `need_decision` ask while the parent keeps
 *    `subagent_supervisor` to answer it. Gate membership is inertness-safe, never a grant.
 * Native wakes need no wait-tool widening in this census.
 * None mutates the repo (`structured_output` writes only the engine's capture file among the
 * child artifacts under the session directory — pi-subagents ≥ 0.66.0; `pi/subagents.md`
 * § "Child artifacts and wave cleanup"). Census decision, recorded: these names deliberately
 * join NEITHER PERK_TOOLS nor BORROWED_TOOLS — the stage-filter universe never sees them
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
 * scoped universe beside PERK_TOOLS. Same static-name posture as READ_ONLY_TOOLS: names are
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
 *    the name lives HERE, in the borrowed census, not in PERK_TOOLS (hygiene-tested).
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
 *    membership at every reconciliation (`ownerSelected`) + the loader refusal in `tool_call`.
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

/**
 * Tools available while read-only mode is active (mirrors plan-mode's PLAN_MODE_TOOLS).
 * `plan_review` is the backend-neutral review door (planReview.ts) — allowlisted so the model
 * can request a human plan review INSIDE plan mode (review happens before the gate ever comes
 * off); fail-open everywhere (headless / dismissed soft-skip), so it is safe on every path.
 */
export const READ_ONLY_TOOLS = [
  "read",
  "grep",
  "find",
  "ls",
  "bash",
  "ask_user_question",
  "plan_review",
  // The plan_draft carve-out: plan_draft is structurally limited to the one working-plan
  // artifact in the run-scoped session data dir (gitignored scratch), so the read-only invariant
  // (worktree untouched) holds; the `tool_call` edit/write/bash blocking below is unchanged.
  "plan_draft",
  // The objective_draft twin of the plan_draft carve-out: objective_draft writes only the one
  // working-objective artifact in the session data dir (fixed artifact name, seam-derived
  // path); the gate's edit/write/bash blocking is unchanged.
  "objective_draft",
  // The gist_draft third of the draft carve-out family: gist_draft writes only the one
  // working-gist artifact in the session data dir (fixed artifact name, seam-derived path);
  // the gate's edit/write/bash blocking is unchanged.
  "gist_draft",
  // The objective_node carve-out: it never touches the worktree — it delegates a bounded,
  // workflow-owned node transition to the canonical Python plane (`perk objective node`). Both
  // objective-plan factory paths run gated (the cold door hands off `mode: read-only`; the warm
  // `/objective-plan` enters the gate before seeding), and the factory loop's
  // `objective_node_claim` carrier — which the approval-driven save's node-link recovery depends
  // on — can only be written by calling this tool inside the gated session. Excluding it
  // silently breaks the warm `/objective-plan` path: the plan saves unlinked.
  "objective_node",
  // The borrowed research families (extracted to family constants; set + order byte-identical).
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  // FFF local search belongs in read-only exploration (the override names find/grep are
  // already present above; these are the additive tools-and-ui names + multi_grep).
  ...FFF_SEARCH_TOOLS,
  // The delegation carve-in: `subagent`/`wait` (+ pi-subagents' late-registered
  // `subagent_supervisor`, kept by every gate-ON re-apply because it is allowlisted here —
  // letting the parent answer ad-hoc children's supervisor asks) stay
  // reachable while gated for the other delegation flows (the gated objective-plan guidance now
  // names the `explore_objective_node` tool below, not a direct spawn). The `subagents_enable`
  // loader rides along; `subagent` itself is lazy-owned, so the gate installs it only while
  // pi-subagents has it selected (the allowlist is a ceiling, never an activation). ACCEPTED LENIENCY,
  // deliberately documented: spawned children are unscoped by design (§8.40
  // adopt-never-impersonates), and the `subagent` tool itself can spawn ad-hoc read-write
  // children — a posture choice with NO agent-allowlist backstop, consistent with the arg-blind
  // `curl`/`agent-browser` precedents (contracts.md §8.3).
  ...SUBAGENT_TOOLS,
  // The explorer-wave carve-in: the gated objective-plan session's OPTIONAL explore step is the
  // `explore_objective_node` tool — it spawns the read-only `perk.objective-explorer` child over
  // the already-carved-in SUBAGENT tools (the draft-review-wave precedent) and writes nothing to
  // the worktree.
  "explore_objective_node",
  // The scout-wave carve-in: the authoring sessions' launcher — `run_scout_wave` spawns
  // read-only `perk.scout` lanes over the already-carved-in delegation family and writes
  // nothing to the worktree; reachable in every gated stage except `objective-refine` on the
  // `explore_objective_node` precedent (contracts.md §8.70).
  "run_scout_wave",
  // The library-writer carve-in: `run_librarian` leaves the PARENT gated — only the dispatched
  // `perk.librarian` child writes, and only the gitignored library in the main checkout, proven
  // after the fact by the fail-closed end-state bracket (contracts.md §8.75(l)).
  "run_librarian",
  // The child-side carve-in: gated adopt-children must keep the engine's injected tools — see
  // SUBAGENT_CHILD_TOOLS.
  ...SUBAGENT_CHILD_TOOLS,
  // The draft-review-door carve-in: plan-authoring sessions run GATED, so the
  // /plan-review-browser companions must be reachable while read-only. `push_annotations` only
  // POSTs findings to the door-primed local plannotator server (no worktree writes — the
  // fetch_content cache-write precedent class); the wave pair spawns the read-only
  // `perk.draft-reviewer` over the already-carved-in SUBAGENT_TOOLS/SUBAGENT_CHILD_TOOLS.
  "push_annotations",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  // The audit-wave carve-in: the seeded `perk-dev audit judge` session runs GATED (the `audit`
  // stage is read-only), so `run_audit_wave` must be reachable while read-only. Its one write
  // (`<bundle>/verdicts.json`) is structurally bound to the cold door's workflow-state
  // `audit_bundle_dir` — the tool takes NO parameters, so no caller-supplied path exists and a
  // gated session cannot aim the writer anywhere (contracts.md §8.50).
  "run_audit_wave",
  // The harvest-wave carve-in: the seeded learn-harvest session runs GATED (the read-only
  // objective-author borrow), so `run_harvest_wave` must be reachable while read-only. Its
  // manifest read is structurally bound to the session's claimed run-scoped scratch path (the
  // `manifest_path` param is verified against it and any other path refused — the
  // `run_audit_wave` no-aimable-writer posture, read-side), it spawns the read-only
  // `perk.harvest-analyst` over the already-carved-in SUBAGENT_TOOLS/SUBAGENT_CHILD_TOOLS, and
  // it writes nothing to the worktree (contracts.md §8.48).
  "run_harvest_wave",
  // The dream-wave carve-in: the seeded `perk learn dream` session runs GATED (the read-only
  // objective-author borrow), so `run_dream_wave` must be reachable while read-only. The tool
  // takes NO parameters: its manifest read AND its one write (the fixed-name run-scratch
  // bundle beside that manifest) are both derived from the claimed run's manifest path — no
  // caller-supplied path exists (the `run_audit_wave` no-aimable-writer posture, BOTH sides),
  // and it spawns only the read-only `perk.dream-analyst`/`perk.dream-reducer` over the
  // already-carved-in delegation family (contracts.md §8.61).
  "run_dream_wave",
];

/**
 * The refinement stage id — the ONE stage whose gate-ON selection differs from READ_ONLY_TOOLS.
 * (Registry vocabulary; the feature module re-declares the same literal as its stage constant.)
 */
export const REFINE_STAGE_ID = "objective-refine";

/**
 * The refinement session's gate-ON selection (contracts.md §8.68): read / research / question
 * / local exploration, the backend-neutral review door, and the ONE refinement draft writer.
 * Deliberately NOT READ_ONLY_TOOLS: no `objective_node` (a refinement never claims), no other
 * draft tools (no plan/objective/gist artifact can be authored or routed from here), no save
 * tools, no delegation spawn surface (children are unscoped by design) — and consequently no
 * SUBAGENT_CHILD_TOOLS either: a child that inherited `stage: objective-refine` would lose
 * `structured_output` under this allowlist. Unreachable today (no perk wave
 * spawns from a refinement session; the lifecycle test pins `gatedToolsFor(stage)`) — revisit
 * the moment refinement gains any delegation. Same static-name posture as READ_ONLY_TOOLS;
 * `setActiveTools` ignores absent names.
 */
export const REFINEMENT_READ_ONLY_TOOLS: readonly string[] = [
  "read",
  "grep",
  "find",
  "ls",
  "bash",
  "ask_user_question",
  "plan_review",
  // The objective_refinement_draft carve-out: it writes only the one working-refinement
  // artifact in the session data dir (fixed artifact name, seam-derived path, bound to the
  // session's grounding context); the gate's edit/write/bash blocking is unchanged.
  "objective_refinement_draft",
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  ...FFF_SEARCH_TOOLS,
];

/** A stage's gate-OFF list; undefined for no stage or an unknown one (a prototype key included). */
function stageToolsFor(stage: string | null): readonly string[] | undefined {
  return stage !== null && Object.hasOwn(STAGE_TOOLS, stage) ? STAGE_TOOLS[stage] : undefined;
}

/** The gate-ON allowlist for a stage: refinement's own selection, else READ_ONLY_TOOLS. */
export function gatedToolsFor(stage: string | null): readonly string[] {
  return stage === REFINE_STAGE_ID ? REFINEMENT_READ_ONLY_TOOLS : READ_ONLY_TOOLS;
}

/**
 * Every tool perk itself registers (contracts.md §8.40). Name-keyed: `setActiveTools` ignores
 * unknown names, so an absent tool is inert (e.g. a borrowed census name whose package stripped
 * or never registered it — `ask_user_question` in a headless session — has nothing to enable).
 * Stage scoping filters the scoped universe `PERK_TOOLS ∪ BORROWED_TOOLS` — builtins and
 * un-enumerated foreign names pass through untouched (fail-open).
 */
export const PERK_TOOLS: readonly string[] = [
  "plan_review",
  "plan_save",
  "plan_draft",
  "objective_save",
  "objective_node",
  "reconcile_objective",
  "add_objective_node",
  "objective_draft",
  "gist_draft",
  "gist_save",
  // The refinement session's ONE model-facing writer (contracts.md §8.67). Never in
  // READ_ONLY_TOOLS: only the refinement gate-ON selection carries it, so no other gated
  // stage can author a refinement draft.
  "objective_refinement_draft",
  "learn",
  "run_learn_wave",
  "run_audit_wave",
  "run_harvest_wave",
  "run_dream_wave",
  "land",
  "post_pr_review",
  "ready",
  "classify_review_feedback",
  "finalize_address",
  "explore_objective_node",
  "run_scout_wave",
  "run_librarian",
  "run_pr_review_wave",
  "submit_pr_review",
  "start_review_wave",
  "collect_review_wave",
  "push_annotations",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  "run_ci",
  "submit",
  "resolve_submit_conflicts",
  // The stack-review launch-recovery tool (contracts.md §8.4): parameterless — the snapshot
  // comes only from the `perk objective stack review` launch handoff.
  "open_stack_review",
  // The stacked-delivery warm surface (contracts.md §8.51/§8.56): read + control tools over
  // the cold `objective stack` workers. Never in READ_ONLY_TOOLS — sync/adopt/recover/land
  // mutate published branches and PRs; the gated posture is the driving commands' soft
  // refusal.
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
  "objective_stack_land",
];

/**
 * The universal non-mutating bundle EVERY stage list carries: web research + Linear reads +
 * FFF local search are useful in every stage session (authoring and worktree alike) and
 * mutate nothing (FFF's frecency state lives under ~/.pi/agent/fff/, outside the worktree).
 */
const RESEARCH_TOOLS: readonly string[] = [
  ...WEB_RESEARCH_TOOLS,
  ...LINEAR_READ_TOOLS,
  ...FFF_SEARCH_TOOLS,
];

/**
 * The PR-loop family shared by ALL FIVE worktree stages (implement/submit/address/land/learn) —
 * deliberately one shared list, not per-stage cuts: any PR-loop warm command must work in any
 * worktree session (warm doors inject guidance naming their companion tool, and a per-stage cut
 * would dead-end e.g. `/land` run inside the implement session; the concrete forcing example is
 * the post-land reconcile drive — `/land` auto-drives `/objective-reconcile` in-session, whose
 * guidance names the reconcile trio, so the trio must be active in every worktree stage). The
 * headless worker also REQUIRES the model-invoked `submit` (implement) /
 * `finalize_address` (address) to reach its completion bar. Borrowed additions: delegation
 * (SUBAGENT_TOOLS — the `/pr-review`/`/address`/`/submit`-conflict/`/learn` orchestration flows)
 * and `todo` (the foreign checklist overlay the implement-progress discipline rides) are
 * worktree-family only.
 */
const WORKTREE_STAGE_TOOLS: readonly string[] = [
  "ask_user_question",
  "submit",
  "resolve_submit_conflicts",
  "ready",
  "run_ci",
  "land",
  "learn",
  "run_learn_wave",
  "classify_review_feedback",
  "finalize_address",
  "post_pr_review",
  "run_pr_review_wave",
  "submit_pr_review",
  // The human review doors' companion tools (/pr-review-terminal, /pr-review-browser): the
  // review-wave pair + the door-primed annotation push. The plan-stage widening landed via the
  // draft-review door (/plan-review-browser): the plan-family stage lists carry the draft-wave
  // pair + push_annotations.
  "start_review_wave",
  "collect_review_wave",
  "push_annotations",
  // The reconcile trio: `/land` auto-drives the objective-reconcile pass inside the CURRENT
  // worktree session (driveReconcileAfterLand), and the manual `/objective-reconcile` gesture is
  // registered globally — both inject guidance naming these three tools.
  "reconcile_objective",
  "add_objective_node",
  "objective_node",
  // The stacked-delivery quintet: `/objective-sync`/`/objective-recover`/`/objective-land`
  // drive worktree sessions (post-amend sync from implement/address; recovery and the atomic
  // landing from anywhere in the PR loop), so their guidance-named tools must be active
  // across the whole family.
  "objective_stack_status",
  "objective_stack_sync",
  "objective_stack_adopt",
  "objective_stack_recover",
  "objective_stack_land",
  // The library writer launcher: the worktree family shares ONE list (see above), so every
  // worktree stage carries it — submit/land by that rule.
  "run_librarian",
  ...RESEARCH_TOOLS,
  ...SUBAGENT_TOOLS,
  "todo",
];

/**
 * Per-stage active perk tools for gate-OFF sessions (contracts.md §8.40). Keys = the registry
 * stage ids; an unknown/absent stage id is fail-open (no filtering — version-skew safety).
 * Rationale pins:
 *  - `ask_user_question` is universal (every stage list carries it); the name is BORROWED now
 *    (the @juicesharp questionnaire, via BORROWED_TOOLS — headless sessions carry no schema).
 *  - `plan`/`save` cover the plan-family stage borrowers (`plan from`/`plan replan`/
 *    `learn docs`/`learn code` borrow `plan`; `skills create/refine` borrow `save`).
 *  - `objective-author`/`objective-save` cover `objective replan` + `objective author --from`.
 *  - `objective-plan` keeps `objective_node` (the factory's claim/transition door) and
 *    `plan_save` (the gate-off manual failsafe for the approval-driven save).
 *  - the reconcile trio (`reconcile_objective`/`add_objective_node`/`objective_node`) rides the
 *    three objective stages (the post-save `/objective-reconcile` gesture) AND the worktree
 *    family (the post-land `driveReconcileAfterLand` drive + the manual `/objective-reconcile`
 *    gesture — its guidance names all three).
 *  - the draft-review companions (`start_draft_review_wave`/`collect_draft_review_wave`/
 *    `push_annotations`) also ride the two objective stages (§8.23's
 *    `/objective-review-browser` — gate-OFF coverage: after `objectiveApprovalSave` exits the
 *    gate mid-flow, late collects/pushes must not dead-end), and `plan_review` rides them
 *    because the door guidance names it (in both objective stages it routes to the objective
 *    review arm; the drive-coverage guard forces both the moment the guidance names them).
 */
export const STAGE_TOOLS: Readonly<Record<string, readonly string[]>> = {
  // The isolated refinement stage (contracts.md §8.68): the gate-OFF (defensive) arm scopes the
  // draft writer + the review door + research only — no PR-loop, save, claim or other draft
  // tools. The session normally runs GATED, where REFINEMENT_READ_ONLY_TOOLS is the set.
  [REFINE_STAGE_ID]: [
    "ask_user_question",
    "objective_refinement_draft",
    "plan_review",
    ...RESEARCH_TOOLS,
  ],
  "gist-author": ["ask_user_question", "gist_draft", "gist_save", ...RESEARCH_TOOLS],
  "gist-save": ["ask_user_question", "gist_draft", "gist_save", ...RESEARCH_TOOLS],
  "objective-author": [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
    // The scout launcher rides the three AUTHORING stages (plan / objective-plan /
    // objective-author) and no other (contracts.md §8.70).
    "run_scout_wave",
    // The library writer launcher rides the three authoring stages and the worktree family
    // (contracts.md §8.75(l)) — with the scout launcher, the two names by which this list and
    // objective-save differ.
    "run_librarian",
    // The /objective-review-browser companions (gate-OFF coverage: after objectiveApprovalSave
    // exits the gate mid-flow, late collects/pushes must not dead-end) + plan_review (the door
    // guidance names it; it routes to the objective review arm here).
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    "plan_review",
    ...RESEARCH_TOOLS,
  ],
  "objective-save": [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
    // The /objective-review-browser companions + plan_review (see the objective-author note).
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    "plan_review",
    ...RESEARCH_TOOLS,
  ],
  "objective-plan": [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    "objective_node",
    "explore_objective_node",
    // The scout launcher and the library writer launcher (see the objective-author note).
    "run_scout_wave",
    "run_librarian",
    "reconcile_objective",
    "add_objective_node",
    // The /plan-review-browser companions (gate-OFF coverage: after approvalSave exits the gate
    // mid-flow, late collects/pushes must not dead-end — the drive-coverage guard forces this
    // the moment the guidance names them).
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...RESEARCH_TOOLS,
  ],
  plan: [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    // The scout launcher and the library writer launcher (see the objective-author note).
    "run_scout_wave",
    "run_librarian",
    // The /plan-review-browser companions (see the objective-plan note).
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...RESEARCH_TOOLS,
  ],
  save: [
    "ask_user_question",
    "plan_draft",
    "plan_review",
    "plan_save",
    // The /plan-review-browser companions (see the objective-plan note).
    "start_draft_review_wave",
    "collect_draft_review_wave",
    "push_annotations",
    ...RESEARCH_TOOLS,
  ],
  implement: WORKTREE_STAGE_TOOLS,
  submit: WORKTREE_STAGE_TOOLS,
  address: WORKTREE_STAGE_TOOLS,
  land: WORKTREE_STAGE_TOOLS,
  learn: WORKTREE_STAGE_TOOLS,
  // The dev-only session-audit orchestrator (`perk-dev audit judge`). The session runs GATED
  // (read-only mode), where this list is inert; it exists for the keys≡registry pin and the
  // defensive gate-off arm.
  audit: ["ask_user_question", "run_audit_wave", ...RESEARCH_TOOLS],
  // The stacked-PR browser-review launcher (`perk objective stack review`): exactly the flow
  // set the stack.md guidance names — the launch-recovery tool, the review-wave pair, the
  // annotation push, per-PR posting, delegation (the wave's relay loop), and research.
  "stack-review": [
    "ask_user_question",
    "open_stack_review",
    "start_review_wave",
    "collect_review_wave",
    "push_annotations",
    "submit_pr_review",
    ...SUBAGENT_TOOLS,
    ...RESEARCH_TOOLS,
  ],
};

/** The read-only marker / custom-message type injected into context while active. */
const MODE_CONTEXT_TYPE = "perk:mode-context";
const READ_ONLY_MARKER = "[READ-ONLY MODE]";
/** The refinement flavor's DISTINCT dedup marker (not a superstring of the default marker, so
 * neither flavor's presence masks the other's dedup scan). */
const REFINEMENT_READ_ONLY_MARKER = "[READ-ONLY REFINEMENT MODE]";
const MODE_MARKERS: readonly string[] = [READ_ONLY_MARKER, REFINEMENT_READ_ONLY_MARKER];

/** Exported for tests: the injected read-only mode context. (No tool enumeration — gate-ON
 * already applies READ_ONLY_TOOLS via setActiveTools, so the active tool set IS the list.) */
export const READ_ONLY_CONTEXT = render("contexts/read-only.md", {
  marker: READ_ONLY_MARKER,
  writer: "plan_draft",
  artifact: "working-plan artifact",
});

/** Exported for tests: the refinement flavor — names the ACTUAL sanctioned writer. */
export const REFINEMENT_READ_ONLY_CONTEXT = render("contexts/read-only.md", {
  marker: REFINEMENT_READ_ONLY_MARKER,
  writer: "objective_refinement_draft",
  artifact: "working-refinement artifact",
});

/** The mode-context flavor for a stage (the refinement session names its own writer). */
function modeContextFor(stage: string | null): { marker: string; content: string } {
  return stage === REFINE_STAGE_ID
    ? { marker: REFINEMENT_READ_ONLY_MARKER, content: REFINEMENT_READ_ONLY_CONTEXT }
    : { marker: READ_ONLY_MARKER, content: READ_ONLY_CONTEXT };
}

function textCarries(content: unknown, needles: readonly string[]): boolean {
  if (typeof content === "string") return needles.some((n) => content.includes(n));
  if (Array.isArray(content)) {
    return content.some((c) => {
      const part = c as { type?: string; text?: string };
      return part.type === "text" && needles.some((n) => (part.text ?? "").includes(n));
    });
  }
  return false;
}

// --- pure policy (perk-owned and self-contained; it began as a copy of plan-mode/utils.ts) -------
//
// Two layers. (1) A whole-string destructive veto over the walker's veto view (`vetoText`): every
// substitution, `${…}` and heredoc body collapsed out of the text that holds it, each substitution's
// own text appended on a line of its own — so an argument walk crosses `$(a; b)`, a heredoc body is
// data to the command that reads it, and what bash executes inside a substitution is judged
// exactly like top-level text. (2) An allowlist at every command position (`commandPositions.ts`).
// Destructive wins.
//
// The argument-level rule: an allowlisted command whose argument can turn the read into a write or
// select another program gets a scoped veto row, reading through a leading quote or escape on the
// option word. Argument-sensitive Git commands are admitted only in a list form (enumerated options
// plus positionals with a list-implying option among them, or bare with display modifiers and no
// positional); positional-only write forms (`git branch <name>`, `git tag <name>`, `git config
// <key> <value>`, `git symbolic-ref <ref> <target>`) are closed by the allowlist shape. Interpreters
// (`python`, `node`, `uv run`, `sh -c`) are never allowlisted.
//
// Accepted leniencies, recorded rather than chased:
//  1. In-program writers inside allowlisted commands' program text — `awk 'BEGIN{system(…)}'`,
//     `awk -f prog.awk`, `sed 'w f'`/`sed 'e cmd'`, `sed -f script`, `sed -f - <<'EOF'` (the
//     quoted-`>` veto catches `awk '{print > "f"}'` only incidentally).
//  2. Run-time supplied arguments — `xargs`, `find -exec … {}` and `fd -x` append trailing words
//     the gate never sees (`… | xargs git branch --list` could receive a positional from stdin),
//     the class already recorded as `fd -x env`; an expansion (`$X`, `$(…)`) likewise supplies
//     words the rows read only as their source text.
//  3. A quote or escape INSIDE a flag word (`-\i`, `-'i'`, `-""i`) — only a LEADING one
//     (`'-i'`, `\-i`) is read through; and abbreviated long options (`--del`, `--in-pl`,
//     `--out=f` — git's option parser and getopt_long accept unambiguous prefixes) in the veto rows.
//  4. The arg-blind admitted commands `curl -o/-O` and `agent-browser --output`.
//  5. Whole-string vetoes read quoted prose (`echo "git branch -D x"`, `printf '->'`) and flag
//     clusters (`rg -ln` via `\bln\b`) — over-strict by design; heredoc data is the one carve-out.
//  6. Over-strict exact-form rows: quoted, clustered, abbreviated or unlisted options in a list
//     form (`git branch '--list'`, `-av`, `--lis`), a substitution among a list form's words (its
//     inner words read as the command's own: `git branch -a --contains $(git rev-list …)`; quote a
//     variable instead), `git config` keys with non-`[\w-]` subsections (`url.https://…`), a quoted
//     single `symbolic-ref` ref, a ref-first `git reflog <ref>`.
//  7. Existing exported variables, variables populated dynamically (`read`, `printf -v`), and
//     interactive less/more/top input; the walker governs submitted assignment words and `for`
//     names, not the process environment or future input.
//  8. Git helpers selected implicitly by existing config/attributes (fsmonitor, diff/textconv/clean
//     filters), fixed ripgrep decompressors selected through inherited `PATH`, and option
//     abbreviations outside the explicitly-scoped veto spellings.

/**
 * Between the words of ONE command: blanks and `\`-newline continuations, never a bare newline — an
 * argument walk must not cross into the next command. At least one real blank is required because
 * Bash removes a continuation; `a\\⏎b` is the single word `ab`, while `a \\⏎b` remains two words.
 */
const SEP = String.raw`(?=(?:[ \t]|\\\n)*[ \t])(?:[ \t]|\\\n)+`;
/**
 * One shell word as the argument-level rows read it: an escaped character (`\;`), a whole quoted
 * span (`\"` stays inside a double-quoted one) or a single unquoted character — one per iteration
 * and the alternatives disjoint, so backtracking stays linear — never an unescaped operator.
 */
const WORD = String.raw`(?:\\[^\n]|'[^']*'|"(?:[^"\\]|\\[\s\S])*"|[^\s'"|;&\\])+`;
/** An input redirection and its operand; unlike shell words, the operand may be adjacent. */
const INPUT_REDIRECT = String.raw`\d*(?:<<<|<<-|<<|<>|<&|<)(?:[ \t]|\\\n)*${WORD}`;
/**
 * The argument walk: further words or adjacent input redirections of the same command. Output
 * redirects either become spaces in the sanitized veto view (`/dev/null`/fd duplication) or meet
 * the destructive redirect veto first.
 */
const WORDS = `(?:(?:${SEP}${WORD})|${INPUT_REDIRECT})*`;
/**
 * An optional opening quote or escape before a flag word (`'-i.bak'`, `"-w"`, `$'-D'`, `\-i`): bash
 * removes it, so a veto reads through it.
 */
const Q = String.raw`(?:\$?['"]|\\)?`;
/**
 * The end of a flag word in the whole-string scan: a blank or newline, `=`, a closing quote or
 * backtick, an operator or the end — `$` alone is the end of the whole scanned text, not of the
 * command.
 */
const END = String.raw`(?=(?:\\\n)*(?:[\s='"\x60|;&()<>]|$))`;
/**
 * The end of a command or subcommand word in an allowlist row: a blank, an adjacent redirection
 * (`git diff>/dev/null`) or the end of the simple command, after any `\`-newline continuations
 * (bash removes them without ending the word — `show\⏎-x` is `show-x`). Never `=`, `-`, `.` or other
 * text inside the word, so `rg=payload`, `rg-extra`, `git show-x` or `gh pr view-x` never reads as
 * the admitted word. Operators never reach a row: they end the simple-command text.
 */
const TOKEN_END = String.raw`(?=(?:\\\n)*(?:[ \t]|[<>](?!\()|&>|$))`;
/**
 * git's admitted global options. Never `-c key=value` (`-c alias.x='!cmd' x` runs any command),
 * never `--git-dir`/`--work-tree`.
 */
const GIT_OPTIONS = `(?:${SEP}(?:-C${SEP}${WORD}|--no-pager|-P))*`;
/** A `git` command word and its admitted global options, up to the subcommand. */
const GIT = `git${GIT_OPTIONS}${SEP}`;
/**
 * The trailing redirections an exact-form (`$`-anchored) row tolerates: the veto has already
 * reduced them to fd duplication, `/dev/null` and input.
 */
const TAIL = String.raw`(?:${SEP}(?:\d*>&\d+|(?:\d+|&)?>>?[ \t]*/dev/null|\d*<{1,3}[ \t]*${WORD}))*[ \t]*$`;
/** A positional word — never an option, not even a quoted or escaped one (`'--no-list'`). */
const POSITIONAL = `(?!${Q}-)${WORD}`;

/**
 * A list-form row: every word an enumerated option (a value-taking one consumes its value, so
 * `--format --list` is no list flag) or a positional, and at least one list-implying option — so a
 * negation (`--no-list`), an abbreviation or any other unlisted option never passes as list mode.
 * Each word parses one way only (a list option's separate commit is just a positional), and the
 * witness is a lookahead, so a failing match backtracks linearly.
 */
function listForm(subcommand: string, options: string, list: string): string {
  const word = `(?:${options}|${list}|${POSITIONAL})`;
  return String.raw`${subcommand}${TOKEN_END}(?=(?:${SEP}${word})*?${SEP}(?:${list})(?=\s|$))(?:${SEP}${word})*${TAIL}`;
}

/** `git branch`'s display modifiers (a value-taking one with its value). */
const BRANCH_DISPLAY = String.raw`-v|-vv|--verbose|-q|--quiet|-i|--ignore-case|--no-color|--color(?:=\S+)?|--column(?:=\S+)?|--no-column|--abbrev(?:=\d+)?|--no-abbrev|--omit-empty|(?:--sort|--format)(?:=|${SEP})${WORD}`;
/** Its list-implying options: `-a`/`-r` refuse a branch name; the filters imply list mode. */
const BRANCH_LIST = `-l|--list|-a|--all|-r|--remotes|--show-current|(?:--contains|--no-contains|--merged|--no-merged|--points-at)(?:=${WORD})?`;
/** `git tag`'s display modifiers. */
const TAG_DISPLAY = String.raw`-i|--ignore-case|--no-color|--color(?:=\S+)?|--column(?:=\S+)?|--no-column|--omit-empty|(?:--sort|--format)(?:=|${SEP})${WORD}`;
/** Its list-implying options: `-n` and the filters imply list mode. */
const TAG_LIST = String.raw`-l|--list|-n\d*|(?:--contains|--no-contains|--merged|--no-merged|--points-at)(?:=${WORD})?`;
/** `git config`'s scope, type and display options (a value-taking one with its value). */
const CONFIG_OPTIONS = String.raw`--local|--global|--system|--worktree|--show-origin|--show-scope|--name-only|-z|--null|--includes|--no-includes|--bool|--int|--bool-or-int|--path|--expiry-date|--type=\S+|(?:--default|--file|-f|--blob)(?:=|${SEP})${WORD}`;
/** Its getter/list actions — git refuses mixing one with any other action. */
const CONFIG_GET = "--get(?:-all|-regexp|-urlmatch|-color|-colorbool)?|--list|-l";

/**
 * An allowlist row for one `git` subcommand shape (case-sensitive: git flag case is meaningful).
 */
function git(body: string): RegExp {
  return new RegExp(String.raw`^\s*${GIT}${body}`);
}

/**
 * A command-keyed allowlist row: the command word and any enumerated subcommand words, the last one
 * ending at TOKEN_END (the earlier ones already end at the whitespace that follows them).
 */
function keyed(words: string, flags = ""): RegExp {
  return new RegExp(String.raw`^\s*${words}${TOKEN_END}`, flags);
}

/**
 * A whole-string veto row; the lookbehind keeps another command's `--sort`/`--tree`-style flag from
 * reading as the command.
 */
function veto(body: string): RegExp {
  return new RegExp(String.raw`(?<![\w-])${body}`);
}

const DESTRUCTIVE_PATTERNS = [
  /\brm\b/i,
  /\brmdir\b/i,
  /\bmv\b/i,
  /\bcp\b/i,
  /\bmkdir\b/i,
  /\btouch\b/i,
  /\bchmod\b/i,
  /\bchown\b/i,
  /\bchgrp\b/i,
  /\bln\b/i,
  /\btee\b/i,
  /\btruncate\b/i,
  /\bdd\b/i,
  /\bshred\b/i,
  /(^|[^<])>(?!>)/,
  />>/,
  /\bnpm\s+(install|uninstall|update|ci|link|publish)/i,
  /\byarn\s+(add|remove|install|publish)/i,
  /\bpnpm\s+(add|remove|install|publish)/i,
  /\bpip\s+(install|uninstall)/i,
  /\bapt(-get)?\s+(install|remove|purge|update|upgrade)/i,
  /\bbrew\s+(install|uninstall|upgrade)/i,
  // git: whole-subcommand mutators (the word ends there — `merge-base` is a read), then one row per
  // argument-level writer of an admitted subcommand.
  veto(
    String.raw`${GIT}(?:add|commit|push|pull|fetch|merge|rebase|reset|checkout|switch|restore|cherry-pick|revert|init|clone|am|apply|notes|update-ref|reflog${SEP}(?:expire|delete|drop))(?![\w-])`,
  ),
  // Anywhere among branch's words, clusters (`-rd`) included: git does not refuse every mix with a
  // list flag (`git branch -a -D foo` deletes). The safe shorts `a r l v i q` carry none of these.
  veto(
    String.raw`${GIT}branch\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*[dDmMcCuft][a-zA-Z]*|--(?:delete|move|copy|set-upstream-to|unset-upstream|edit-description|force|track|create-reflog))${END}`,
  ),
  veto(
    String.raw`${GIT}tag\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*[adefFmsu][a-zA-Z]*|--(?:annotate|sign|local-user|delete|force|message|file|edit|create-reflog|cleanup|trailer))${END}`,
  ),
  // Every stash form but `list`/`show` — bare `git stash` is `push`.
  veto(String.raw`${GIT}stash\b(?!${SEP}(?:list|show)\b)`),
  veto(
    String.raw`${GIT}remote(?:${SEP}(?:-v|--verbose))*${SEP}(?:add|remove|rm|rename|set-url|set-head|set-branches|prune|update)\b`,
  ),
  veto(String.raw`${GIT}worktree${SEP}(?:add|remove|move|prune|lock|unlock|repair)\b`),
  veto(String.raw`${GIT}symbolic-ref\b${WORDS}${SEP}${Q}(?:-d|--delete|-m)${END}`),
  veto(
    String.raw`${GIT}config\b(?:${SEP}(?:set|unset|rename-section|remove-section|edit)\b|${WORDS}${SEP}${Q}(?:--(?:add|unset|unset-all|replace-all|rename-section|remove-section|edit)|-e)${END})`,
  ),
  // `-w` writes the object database; attached spellings (`-wt blob`) included.
  veto(String.raw`${GIT}hash-object\b${WORDS}${SEP}${Q}-[a-zA-Z]*w`),
  // `git diff/log/show --output=<file>` writes a file.
  veto(String.raw`git\b${WORDS}${SEP}${Q}--output${END}`),
  // Explicit helper switches on the reads that take diff/log options: `--ext-diff` runs the
  // configured external diff and `--textconv` the configured converters (`reflog` and `stash
  // show|list` take them too; these options never abbreviate). `--no-ext-diff`/`--no-textconv` pass.
  veto(
    String.raw`${GIT}(?:diff|log|show|range-diff|reflog|stash|shortlog)\b${WORDS}${SEP}${Q}--(?:ext-diff|textconv)${END}`,
  ),
  // Exec flags of admitted subcommands: `git grep -O<cmd>` runs its pager through the shell and
  // `git ls-remote --upload-pack=<cmd>` (hidden alias `--exec`) runs a local command for a local
  // path — prefixes included, as git accepts unambiguous abbreviations.
  veto(String.raw`${GIT}grep\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*O|--op)`),
  veto(String.raw`${GIT}ls-remote\b${WORDS}${SEP}${Q}--(?:up|exe)`),
  // Converters and filters named by path: `grep --textconv`, `cat-file --textconv|--filters`,
  // `hash-object --path|--filters|--stdin-paths` — run the path's configured helpers. Whole
  // positive option words only: `--no-filters` and a bare `--stdin` pass.
  veto(String.raw`${GIT}grep\b${WORDS}${SEP}${Q}--textconv${END}`),
  veto(String.raw`${GIT}cat-file\b${WORDS}${SEP}${Q}--(?:textconv|filters)${END}`),
  veto(String.raw`${GIT}hash-object\b${WORDS}${SEP}${Q}--(?:path|filters|stdin-paths)${END}`),
  // Argument-level writers of the admitted text utilities.
  veto(String.raw`find\b${WORDS}${SEP}${Q}-(?:delete|fprint0?|fprintf|fls)${END}`),
  // `-i` anywhere among sed's words (GNU sed permutes options after operands), clustered or with a
  // suffix (`-ni`, `-i.bak`, `-i''`), BSD `-I`, `--in-place[=SUF]`; `--silent`/`--posix` start with
  // `--` and never reach the cluster arm.
  veto(String.raw`sed\b${WORDS}${SEP}${Q}-(?:[a-zA-Z]*[iI]|-in-place\b)`),
  // `-o` is sort's only short flag with an `o`; an attached operand (`-o./out.txt`) included.
  veto(String.raw`sort\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*o|--output)`),
  veto(String.raw`tree\b${WORDS}${SEP}${Q}-[a-zA-Z]*o`),
  // Program selectors of the admitted readers. `sort --compress-program=<cmd>` (and its
  // unambiguous `--comp…` abbreviation), ripgrep's preprocessor and hostname helper, bat's pager.
  veto(String.raw`sort\b${WORDS}${SEP}${Q}--comp`),
  veto(String.raw`rg\b${WORDS}${SEP}${Q}--(?:pre|hostname-bin)${END}`),
  veto(String.raw`bat\b${WORDS}${SEP}${Q}--pager${END}`),
  // less (and macOS more, the same binary): the dangerous leading startup commands shell out
  // (`!`, `#`, `|`), edit (`v`) or save (`s`); `--cmd` likewise; a lesskey file or source can set
  // the environment. Searches (`+/pattern`) and ordinary motion (`+G`) pass.
  veto(String.raw`(?:less|more)\b${WORDS}${SEP}${Q}\+\+?[!#|vs]`),
  veto(
    String.raw`(?:less|more)\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*k|--(?:cmd|lesskey-file|lesskey-src|lesskey-context)${END})`,
  ),
  // In more's compatibility mode `-p` names a startup command: every spelling is refused.
  veto(String.raw`more\b${WORDS}${SEP}${Q}-[a-zA-Z]*p`),
  new RegExp(String.raw`\bnpm${SEP}audit${SEP}fix\b`, "i"),
  /\bsudo\b/i,
  /\bsu\b/i,
  /\bkill\b/i,
  /\bpkill\b/i,
  /\bkillall\b/i,
  /\breboot\b/i,
  /\bshutdown\b/i,
  /\bsystemctl\s+(start|stop|restart|enable|disable)/i,
  /\bservice\s+\S+\s+(start|stop|restart)/i,
  /\b(vim?|nano|emacs|subl)\b/i,
];

const SAFE_PATTERNS = [
  // `cd` mutates nothing — it is the common prefix for scoping a read-only query
  // (`cd repo && perk objective show …`). Safe because every other command position is
  // independently validated and the whole-string destructive veto is unchanged.
  keyed("cd"),
  keyed("cat"),
  keyed("head"),
  keyed("tail"),
  keyed("less"),
  keyed("more"),
  keyed("grep"),
  keyed("find"),
  keyed("ls"),
  keyed("pwd"),
  keyed("echo"),
  keyed("printf"),
  keyed("wc"),
  keyed("sort"),
  keyed("uniq"),
  keyed("diff"),
  keyed("file"),
  keyed("stat"),
  keyed("du"),
  keyed("df"),
  keyed("tree"),
  keyed("which"),
  keyed("whereis"),
  keyed("type"),
  keyed("env"),
  keyed("printenv"),
  keyed("uname"),
  keyed("whoami"),
  keyed("id"),
  keyed("date"),
  keyed("cal"),
  keyed("uptime"),
  keyed("ps"),
  keyed("top"),
  keyed("htop"),
  keyed("free"),
  // git's read-only plumbing. Pure reads take any arguments (their writer flags are vetoed); an
  // argument-sensitive subcommand is admitted in its list form only — enumerated options plus
  // positionals with a list-implying option among them (positionals are then patterns/commits),
  // or bare with display modifiers and no positional — so `git branch <name>` / `git tag <name>` /
  // `git config <key> <value>` / `git symbolic-ref <ref> <target>` fail the shape.
  git(
    `(?:status|log|diff|show|blame|grep|check-ignore|merge-base|rev-list|rev-parse|cat-file|describe|name-rev|ls-files|ls-tree|ls-remote|for-each-ref|show-ref|shortlog|count-objects|range-diff|patch-id|hash-object|var|version|--version)${TOKEN_END}`,
  ),
  git(listForm("branch", BRANCH_DISPLAY, BRANCH_LIST)),
  git(`branch${TOKEN_END}(?:${SEP}(?:${BRANCH_DISPLAY}))*${TAIL}`),
  git(listForm("tag", TAG_DISPLAY, TAG_LIST)),
  git(`tag${TOKEN_END}(?:${SEP}(?:${TAG_DISPLAY}))*${TAIL}`),
  git(
    `remote${TOKEN_END}(?:${SEP}(?:-v|--verbose)${TOKEN_END})*(?:${SEP}(?:show|get-url)${TOKEN_END}|${TAIL})`,
  ),
  git(`worktree${SEP}list${TOKEN_END}`),
  git(`stash${SEP}(?:list|show)${TOKEN_END}`),
  // Exactly one `<ref>`.
  git(
    String.raw`symbolic-ref${TOKEN_END}(?:${SEP}(?:-q|--quiet|--short|--no-recurse|--recurse))*${SEP}[^-\s'"]\S*${TAIL}`,
  ),
  // A positive list: bare (= show), `show …`, `list`, `exists <ref>`, flag-first; every other
  // action (`expire`/`delete`/`drop`, and any future one) falls outside it.
  git(`reflog${TOKEN_END}(?:${SEP}(?:show|list|exists)${TOKEN_END}|${SEP}-|${TAIL})`),
  // A getter/list action present (`--file --get` gives `--get` to `--file`), the git ≥ 2.46
  // subcommand form, or exactly one dotted key.
  git(listForm("config", CONFIG_OPTIONS, CONFIG_GET)),
  git(`config${SEP}(?:get|list)${TOKEN_END}`),
  git(
    String.raw`config${TOKEN_END}(?:${SEP}(?:${CONFIG_OPTIONS}))*${SEP}[A-Za-z][\w-]*(?:\.[\w-]+)+${TAIL}`,
  ),
  keyed(`npm${SEP}(?:list|ls|view|info|search|outdated|audit)`, "i"),
  keyed(`yarn${SEP}(?:list|info|why|audit)`, "i"),
  keyed(`node${SEP}--version`, "i"),
  keyed(`python${SEP}--version`, "i"),
  /^\s*curl\s/i,
  keyed(`wget${SEP}(?:-O-|-O${SEP}-)`, "i"),
  keyed("jq"),
  // `sed` in every form (`-i` is vetoed).
  keyed("sed"),
  keyed("awk"),
  // Everyday read-only utilities — none has an output-file flag.
  keyed(
    "(?:nl|shasum|sha1sum|sha224sum|sha256sum|sha384sum|sha512sum|md5|md5sum|readlink|realpath|basename|dirname|test|true|false|read|set|column|tr|cut|paste|comm|tac|rev|od|strings|sleep|fold|cmp)",
  ),
  // `[ -f x ]` (`[[` stays refused by the walker).
  keyed(String.raw`\[`),
  // `command -v NAME`: the walker yields the query itself as the command.
  keyed(`command${SEP}-[pvV]+`),
  // xxd's second positional is an output file: flag-only switches, the count-taking flags with
  // their number, and at most ONE file operand.
  new RegExp(
    String.raw`^\s*xxd(?:${SEP}(?:-[abeEiprCu]+|-[cglos][ \t]*[+-]?(?:0x)?[0-9a-fA-F]+))*(?:${SEP}(?!-)${WORD})?${TAIL}`,
  ),
  keyed("rg"),
  keyed("fd"),
  keyed("ast-grep"),
  // Browser-automation skill (.agents/skills/agent-browser): a command-keyed entry mirroring
  // `ast-grep` — it gates the command, not its args. Two invocation forms: the bare global
  // install on PATH, and the `npx` fallback anchored to `agent-browser` so bare `npx <anything>`
  // stays blocked. Accepted known leniency: the command-position model checks command words, not
  // their arguments, so agent-browser's own output flags (screenshot/video `--output`) can write
  // files and its actions can mutate external sites — outside the gate's granularity. This is
  // accepted and documented, consistent with the allowlisted `curl` / `fetch_content`
  // GitHub-clone cache-write precedent (both write outside the gate). The whole-string
  // `>`-redirect destructive veto still applies.
  keyed("agent-browser"),
  keyed(`npx${SEP}agent-browser`),
  keyed("bat"),
  keyed("eza"),
  // perk's own read-only objective queries (show/next + their s/n aliases, plus the non-mutating
  // node-engagement read the objective-plan factory needs). The complete-word ending keeps the `n`
  // alias from matching the mutating `node` subcommand; node-engagement allowed; create/node/reconcile
  // stay blocked. node-engagement materializes a present refinement under the run scratch dir —
  // the same accepted leniency as `perk pr review-context` below (the CLI writes its own
  // gitignored scratch file; the destructive veto still blocks `> file` redirects).
  keyed(`perk${SEP}(?:objective|obj)${SEP}(?:show|s|next|n|node-engagement)`, "i"),
  // Report children need exactly these query forms, not arbitrary PR operations: plan-bound
  // children (`/pr-review`, `/address`) use the `--expected-pr` form; the human-triage doors'
  // adversarial children use the foreign `--pr` / `--pr --stack` forms (a read-only parent would
  // otherwise block the doors' children outright); the stack-review flow's lanes AND its routing
  // step run the PINNED `--pr N --stack --pin-base <sha> --pin-head <pr>=<sha>…` form the door
  // rendered (`pinnedReviewContextCommand` — full 40-hex lowercase shas, at least two heads; the
  // CLI re-validates the grammar and topology). ONE anchored alternation: `--json` last, nothing
  // else; the flagless form stays out (only the write-capable foreground conflict-resolver uses
  // it, outside the gate). The destructive veto still blocks `> file` redirects — the CLI writes
  // its own scratch files.
  /^\s*perk\s+pr\s+review-context\s+(?:--expected-pr\s+[1-9][0-9]*|--pr\s+[1-9][0-9]*(?:\s+--stack(?:\s+--pin-base\s+[0-9a-f]{40}(?:\s+--pin-head\s+[1-9][0-9]*=[0-9a-f]{40}){2,})?)?)\s+--json\s*$/,
  /^\s*perk\s+pr\s+feedback\s+--json\s*$/,
  // The perk library workers' deterministic `--json` forms (contracts.md §8.75(f)). The CLI mutates
  // only the gitignored `docs/library/` cache and refuses unless its representative ignore probes
  // pass and nothing under the library is tracked (the probes run before its lock, except
  // `remove`'s entry probe): the `perk pr review-context` leniency, made operational by the CLI's
  // cache-only preflight. The three network verbs — `check` (the only freshness probe),
  // `refresh` and `add source` — mutate only that same cache behind the same preflight, and
  // their git operations run config-pinned (no global/system config, hooks disabled), so nothing
  // a cloned tree or the user's global config selects can execute (env config and a checkout's
  // repo-local config stay trusted, §8.75(i)). `add docs` is not admitted.
  // `--json` last, any whitespace-separated arguments before it; the destructive veto still
  // blocks real-file redirects and chained mutations. The trailing `--json` must be a real
  // argument: the simple-command text keeps a trailing comment and redirection operands, so an
  // argument word may not start a comment (`#`) or hold a redirection (`<`/`>`) — otherwise
  // `refresh <slug> # --json` or `refresh <slug> <<< --json` would run the human form, which on
  // a docs entry is the write-capable refresh door (§8.75(k)).
  /^\s*perk\s+librarian\s+(?:list|record|remove|check|refresh|add\s+source)\b(?:\s+(?!#)[^\s<>]+)*\s+--json\s*$/,
  // Read-only `gh` queries — the guidance in the managed AGENTS block ("GitHub access goes
  // through gh") must be followable in read-only sessions. Query-shaped subcommands only;
  // `gh api` stays blocked (it can POST/PATCH), as do all mutating subcommands (create/edit/
  // merge/close/comment/clone/...). Destructive-wins still blocks `> file` redirects.
  keyed(`gh${SEP}(?:issue|pr|repo|run|release|label)${SEP}(?:view|list|diff|status|checks)`, "i"),
  keyed(`gh${SEP}search${SEP}(?:issues|prs|code|commits|repos)`, "i"),
  keyed(`gh${SEP}auth${SEP}status`, "i"),
  // `perk --help`, `perk <group> --help`, `perk <group> <verb> --help`: only bare lowercase
  // identifier words precede the help flag, so no option can consume it as a value — Click's
  // eager help then exits before any command body runs (no perk command disables it). Never `-h`:
  // perk registers only `--help`, so `-h` reaches a command body as an ordinary argument.
  /^\s*perk(?:\s+[a-z][\w-]*){0,3}\s+--help(?:\s|$)/,
  // Version stamps + the learned-docs verifier (it writes nothing).
  keyed(`perk${SEP}--version`),
  keyed(`perk${SEP}learn${SEP}docs-check`),
  keyed(`pi${SEP}--version`),
];

/** The read-only gate's bash verdict; a refusal carries the one-line reason the block message shows. */
export type ReadOnlyBashVerdict = { allowed: true } | { allowed: false; reason: string };

/**
 * Whether a bash command is allowed under read-only mode — first hit wins:
 *  1. NOT destructive: a WHOLE-STRING scan against DESTRUCTIVE_PATTERNS (destructive-wins — content
 *     anywhere in the string, incl. command substitutions, still vetoes) over the walker's veto
 *     view: every substitution, `${…}` and heredoc body collapsed out of the text that holds it
 *     and each substitution's own text appended on a line of its own, so an argument walk crosses
 *     `$(a; b)`, a `>` or `git add` in `<<'EOF' … EOF` is not a write, and `$(echo x > out)` in an
 *     unquoted body is judged exactly like top-level text. Two redirect carve-outs are neutralized first:
 *     FD duplications (`2>&1`, `1>&2`) and redirects to `/dev/null` (`>/dev/null`, `2>/dev/null`,
 *     `&>/dev/null`, `>>/dev/null`) — both discard output and write nothing to the filesystem.
 *     Redirects to a REAL path (`> file`, `&> file`, `>> file`) are NOT carved out and stay
 *     destructive.
 *  2. SAFE at every command position (`commandPositions.ts`): the start of input and the word after
 *     an unquoted `;` `|` `|&` `&&` `||`, a lone `&` or a newline; inside `$(…)`/backticks (also
 *     within double quotes) and `<(…)`/`>(…)`; after `NAME=value` prefixes, leading redirections,
 *     the keywords `for…in`/`do`/`done`/`while`/`until`/`if`/`then`/`elif`/`else`/`fi`/`{`/`}`/`!`
 *     and the wrappers `env`/`timeout N`/`xargs`/`nice`/`time`/`command`/`nohup`; and at
 *     `find -exec`/`fd -x` — EVERY simple command there must match a SAFE_PATTERNS entry. A dynamic
 *     command word (`$VAR`, quoted, escaped, substituted), an unterminated quote/substitution/heredoc,
 *     an unmodeled wrapper flag or unmodeled syntax is refused, as is a command with nothing to
 *     run. The allowlist matches the simple-command text (command word to the end of that simple
 *     command), so the anchored `perk pr … --json\s*$` rows still see the full argument tail;
 *     every command word inside a heredoc body's substitutions is allowlisted like any other.
 * Pure → unit-testable offline.
 */
export function readOnlyBashVerdict(command: string): ReadOnlyBashVerdict {
  const positions = commandPositions(command);
  const scanned = positions.vetoText
    .replace(/\d*>&\d+/g, " ")
    .replace(/(?:\d+|&)?>>?\s*\/dev\/null\b/g, " ");
  const veto = DESTRUCTIVE_PATTERNS.find((p) => p.test(scanned));
  if (veto !== undefined) return { allowed: false, reason: `matches the destructive veto ${veto}` };
  if (!positions.ok) return { allowed: false, reason: REFUSAL_REASONS[positions.refusal] };
  if (positions.commands.length === 0)
    return {
      allowed: false,
      reason: "no command to run (only assignments, comments or whitespace)",
    };
  const unlisted = positions.commands.find((c) => !SAFE_PATTERNS.some((p) => p.test(c)));
  if (unlisted === undefined) return { allowed: true };
  const line = unlisted.split("\n")[0] ?? "";
  return {
    allowed: false,
    reason: `not allowlisted: ${line.length > 100 ? `${line.slice(0, 100)}…` : line}`,
  };
}

/** The boolean form of `readOnlyBashVerdict`. */
export function isReadOnlyBashCommand(command: string): boolean {
  return readOnlyBashVerdict(command).allowed;
}

// --- the controller -----------------------------------------------------------------------------

/** The API the plan-mode and read-only-stage consumers use + the lifecycle hooks index.ts wires. */
export interface ToolGating {
  /**
   * Reapply the gate + stage scoping from a rebuilt `mode` + `stage` (called on session_start
   * AND session_tree). `stage` is the branch-LWW workflow-state stage id (undefined = unscoped).
   */
  syncFromState(mode: string | undefined, stage: string | undefined): void;
  /** Enter read-only mode: persist `mode=read-only` + snapshot/restrict tools. (Called by plan mode — `/plan`, `--plan`, `Ctrl+Alt+P` — the warm objective-plan factory and the warm objective-refine entry; never the CI executor.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + restore tools. (Called by the plan-mode toggle and the save/exit doors.) */
  exit(ctx?: ExtensionContext): void;
  /** Whether the gate is currently active (in-memory source of truth for `tool_call`). */
  isActive(): boolean;
}

function isReadOnlyMode(mode: string | undefined): boolean {
  return mode === "read-only";
}

/** The engagement record: the host's active starting set (the restore authority — never
 * `getAllTools()` — for every name EXCEPT lazy-owned ones, whose membership is the owner's live
 * selection), the registry census at snapshot time, and the late registrants admitted so far. */
type Engaged = { snapshot: readonly string[]; census: ReadonlySet<string>; admitted: Set<string> };

export function registerToolGating(
  pi: ExtensionAPI,
  readOnlyFloor: () => boolean = () => false,
): ToolGating {
  // In-memory gate (mirrors plan-mode's `planModeEnabled`): the authority `tool_call` consults.
  // Fail-closed — a failed sync never opens this; tool_call blocks on any internal error.
  let active = false;
  // The branch-LWW stage id this session is scoped to (null = unscoped). Fail-open by contrast
  // with `active`: no stage / unknown stage / any lookup miss → no filtering.
  let stageId: string | null = null;
  // Taken ONCE on the first engagement of either concern (the preset.ts discipline, shared by the
  // gate and stage scoping); cleared when neither is engaged any more.
  let engaged: Engaged | null = null;

  function hasFloor(): boolean {
    try {
      return readOnlyFloor();
    } catch {
      // A broken restriction supplier cannot grant authority for this observation.
      return true;
    }
  }

  const isActive = () => active || hasFloor();
  // The gate-ON allowlist follows the scoped stage: refinement's own selection, else the
  // shared READ_ONLY_TOOLS (recomputed per observation — a late stage sync re-scopes it).
  const gatedToolNames = (): ReadonlySet<string> => new Set(gatedToolsFor(stageId));

  /**
   * Recompute + install the active tool set from both concerns (contracts.md §8.40):
   *  - gate ON → the stage's gated allowlist (READ_ONLY_TOOLS, or refinement's own), NO stage
   *    filter (the decided composition: the gated set is already the diet, and a strict
   *    intersection would break the documented warm `/objective-plan` carve-out and recreate the
   *    seed/gate contradiction class). "The gate never widens a stage's set and vice versa" still
   *    holds: engaging the gate only ever narrows, and stage scoping never adds a tool.
   *  - gate OFF + stage scoped → a SUBTRACTIVE filter over the baseline (`baseline`): names
   *    outside the scoped universe (builtins, un-enumerated foreign tools) pass through untouched;
   *    scoped names (PERK_TOOLS ∪ BORROWED_TOOLS) survive only when the stage's list carries them.
   *  - neither engaged → restore the baseline and forget it (a session that never engages gets
   *    ZERO setActiveTools calls — bare warm sessions stay byte-identical).
   * Lazy-owned names (the tools of every REGISTERED loader in LAZY_TOOL_LOADERS) take their
   * membership from the owner's live selection in every arm: the gated allowlist is a ceiling (installed only while the owner has the tool
   * selected), and the baseline neither restores one the owner hid nor drops one it enabled.
   * perk never re-activates or restores a lazy-owned tool — Pi's transcript restore and the
   * owner's recorded-selection replay do; perk only keeps it or (by stage) strips it.
   * While engaged the set is re-installed on every sync (tree navigation across mode entries
   * must recompute correctly).
   */
  // The scoped universe: perk's own tools + the enumerated borrowed census. Builtins and
  // un-enumerated foreign names pass through every stage filter untouched (fail-open).
  const SCOPED_TOOL_NAMES: ReadonlySet<string> = new Set([...PERK_TOOLS, ...BORROWED_TOOLS]);

  /**
   * The gate-OFF reconciliation baseline: `snapshot ∪ admitted` under owner-selected membership,
   * plus every lazy-owned tool currently active. A tool the census never saw (pi-subagents'
   * `subagent_supervisor` registers in its own `session_start`, after perk's sync) is admitted
   * the first time it is seen active and stays admitted through perk's own filtering (so a
   * navigation back to an admitting stage restores it); an owner that deactivates its late tool
   * before perk ever sees it active is respected; a tool the census saw inactive is never
   * re-activated. A lazy-owned snapshot member the owner has since hidden is dropped, and one the
   * owner enabled after the snapshot is kept. Gate-OFF paths only (the gate-ON set is by name —
   * no bookkeeping there).
   */
  function baseline(e: Engaged, live: LiveSelection): string[] {
    for (const name of live.active) if (!e.census.has(name)) e.admitted.add(name);
    const lazyActive = [...live.active].filter((name) => live.lazyOwned.has(name));
    return [...new Set([...ownerSelected([...e.snapshot, ...e.admitted], live), ...lazyActive])];
  }

  /** The owner's live selection, read per install (after the first-engagement snapshot). */
  function readLive(): LiveSelection {
    return {
      active: new Set(pi.getActiveTools()),
      lazyOwned: lazyOwnedBy(pi.getAllTools().map((t) => t.name)),
    };
  }

  function apply(nextActive: boolean, nextStage: string | null): void {
    // Fail-closed: a read-only sync engages the in-memory gate BEFORE the fallible reads/installs.
    if (nextActive) active = true;
    const effective = nextActive || hasFloor();
    const stageList = stageToolsFor(nextStage);
    // First engagement of either concern: ONE literal (a throwing read records no half state).
    if ((effective || stageList !== undefined) && engaged === null) {
      engaged = {
        snapshot: pi.getActiveTools(),
        census: new Set(pi.getAllTools().map((t) => t.name)),
        admitted: new Set(),
      };
    }
    // The live reads follow the snapshot literal above, so the fail-closed ordering is unchanged.
    if (effective) {
      pi.setActiveTools(ownerSelected(gatedToolsFor(nextStage), readLive()));
    } else if (engaged !== null) {
      const base = baseline(engaged, readLive());
      if (stageList !== undefined) {
        pi.setActiveTools(
          base.filter((name) => !SCOPED_TOOL_NAMES.has(name) || stageList.includes(name)),
        );
      } else {
        pi.setActiveTools(base);
        engaged = null;
      }
    }
    active = nextActive;
    stageId = nextStage;
  }

  // Pi fires `resources_discover` after EVERY extension's `session_start` has run (pi-subagents
  // registers `subagent_supervisor` there, after perk's sync) — the one point where startup-late
  // registrants meet the gate/stage diet: re-apply the in-memory mode/stage (no rebuild, no other
  // checkpoint). Idempotent on `reason: "reload"`; a throw is Pi-reported and never opens the gate.
  pi.on("resources_discover", async () => {
    apply(active, stageId);
  });

  /**
   * The lazy-loader refusal (the one stage-enforced `tool_call`, contracts.md §8.40): a loader
   * called where the tools it enables are ineligible is refused with a stage-naming reason. The
   * owner re-advertises its loader every turn in its own `before_agent_start`, AFTER perk's
   * handler, so schema removal cannot hide it — refusing the activation call is the only way to
   * keep a stage-excluded tool from being reintroduced. The activated tool itself stays under
   * the fail-open stage filter. An unscoped or unknown-stage session never refuses.
   */
  function lazyLoaderRefusal(toolName: string): string | null {
    if (!Object.hasOwn(LAZY_TOOL_LOADERS, toolName)) return null;
    if (isActive()) {
      return gatedToolNames().has(toolName)
        ? null
        : lazyLoaderRefusalReason(toolName, { kind: "gated", stage: stageId });
    }
    const stageList = stageToolsFor(stageId);
    return stageId !== null && stageList !== undefined && !stageList.includes(toolName)
      ? lazyLoaderRefusalReason(toolName, { kind: "stage", stage: stageId })
      : null;
  }

  // Enforce the whole allowlist even if toolset narrowing failed or foreign tools registered late.
  pi.on("tool_call", async (event) => {
    try {
      const refusal = lazyLoaderRefusal(event.toolName);
      if (refusal !== null) return { block: true, reason: refusal };
      if (!isActive()) return;
      if (event.toolName === "edit" || event.toolName === "write") {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (file modifications disabled).`,
        };
      }
      if (!gatedToolNames().has(event.toolName)) {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (tool not allowlisted).`,
        };
      }
      if (event.toolName === "bash") {
        const command = String((event.input as { command?: unknown }).command ?? "");
        const verdict = readOnlyBashVerdict(command);
        if (!verdict.allowed) {
          return {
            block: true,
            reason: `perk read-only mode: command blocked (not allowlisted).\nCommand: ${command}\nReason: ${verdict.reason}`,
          };
        }
      }
      return;
    } catch {
      // Never let an internal error open the gate — fail closed.
      return { block: true, reason: "perk read-only mode: blocked (internal gating error)." };
    }
  });

  // Inject the hidden read-only mode context while active (display:false → not shown in transcript).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isActive()) return;
    // Once-only per selected branch: injected customs persist to the branch, and the FULL-branch
    // scan (not live model context) dedups — a copy compaction summarized away still counts as
    // delivered on this branch history and is NOT re-injected; navigating to a branch that never
    // carried it injects again. Deliberate: this is the structural gate's guidance, and the gate
    // itself (tool_call) enforces regardless of what the model can still read.
    // The flavor follows the scoped stage: the refinement session names its actual writer. The
    // dedup key is the SELECTED flavor's marker, so a session gated under the default flavor
    // that then enters refinement still receives the refinement flavor once.
    const flavor = modeContextFor(stageId);
    try {
      if (branchCarries(branchOf(ctx), flavor.marker)) return;
    } catch {
      // An unreadable branch cannot suppress required read-only guidance.
    }
    return {
      message: { customType: MODE_CONTEXT_TYPE, content: flavor.content, display: false },
    };
  });

  // Gate OFF: strip every stale mode-context flavor (so none lingers). Gate ON: retain ONLY the
  // current flavor's injected block — a stale `plan_draft`-only block from before a stage
  // change is dropped from model context (the injected customType only; user content is never
  // touched while the gate is on).
  pi.on("context", async (event) => {
    if (isActive()) {
      const current = modeContextFor(stageId).marker;
      const stale = (m: unknown): boolean => {
        const msg = m as { customType?: string; content?: unknown };
        return (
          msg.customType === MODE_CONTEXT_TYPE &&
          textCarries(msg.content, MODE_MARKERS) &&
          !textCarries(msg.content, [current])
        );
      };
      // No stale flavor → no intervention (the hook stays a no-op for every other message).
      if (!event.messages.some(stale)) return;
      return { messages: event.messages.filter((m) => !stale(m)) };
    }
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === MODE_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        return !textCarries(msg.content, MODE_MARKERS);
      }),
    };
  });

  return {
    syncFromState(mode: string | undefined, stage: string | undefined): void {
      apply(isReadOnlyMode(mode), stage ?? null);
    },
    enter(_ctx?: ExtensionContext): void {
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-only" });
      apply(true, stageId);
    },
    exit(_ctx?: ExtensionContext): void {
      if (hasFloor()) {
        apply(true, stageId);
        return;
      }
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-write" });
      apply(false, stageId);
    },
    isActive,
  };
}
