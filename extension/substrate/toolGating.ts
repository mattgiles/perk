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
import { render } from "./prompts.ts";
import { readOnlyBashVerdict } from "./readOnlyBash.ts";
import {
  BORROWED_TOOLS,
  FFF_SEARCH_TOOLS,
  LINEAR_READ_TOOLS,
  SUBAGENT_CHILD_TOOLS,
  SUBAGENT_TOOLS,
  WEB_RESEARCH_TOOLS,
} from "./toolPolicy.ts";
import { branchCarries, branchOf, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

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
