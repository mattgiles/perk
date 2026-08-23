// The tool-gating primitive (the keystone). Structural read-only enforcement, NOT
// prompting. Mirrors pi's authoritative `examples/extensions/plan-mode/` recipe (the
// `setActiveTools` allowlist + `tool_call` bash sub-allowlist + `before_agent_start` injection
// (once-only: branch-scan dedup'd on the marker, so a session carries ONE live copy) +
// `context` strip-when-off) and `preset.ts`'s snapshot-then-restore. The gate attaches to the
// existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no new registry stage.
// Beside the gate lives STAGE_TOOLS: per-stage active-tool scoping for the scoped universe
// (perk's OWN registered tools + the enumerated borrowed-package census), keyed off the
// workflow-state `stage` field and applied at the same rebuild points (contracts.md §8.40) —
// fail-open where the gate is fail-closed.
//
// Substrate only: perk-owned plan mode and the read-only CI executor are the consumers of the
// `enter`/`exit` surface; the allowlist-restore is wired into the existing
// `session_start`/`session_tree` rebuild points.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { render } from "./prompts.ts";
import { branchCarries, branchOf, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/**
 * The `web` seam providers' research tools: the UNION of all known web-provider tool names,
 * enumerated statically and inert when the package is absent (the plan_review precedent —
 * setActiveTools simply has nothing to enable). None mutate the repo — fetch_content's
 * GitHub-clone path writes only to its own cache outside the worktree, morally equivalent to the
 * already-allowlisted curl. perk does NOT normalize names, so all three providers' divergent
 * names are listed: pi-web-access (default: web_search/code_search/fetch_content/
 * get_search_content — `code_search` is not registered by any current version; kept as an inert
 * static name for version tolerance), @ollama/pi-web-search (ollama_web_search/ollama_web_fetch),
 * and @juicesharp/rpiv-web-tools (web_search shared, web_fetch). All register at load time.
 */
export const WEB_RESEARCH_TOOLS: readonly string[] = [
  "web_search",
  "code_search",
  "fetch_content",
  "get_search_content",
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
 * pi-subagents' delegation family. `subagent`/`wait` register at load time; the parent intercom
 * pair (`subagent_supervisor`, `intercom`) registers during `session_start` — AFTER perk's sync
 * (perk is the first `packages` entry), so it LEAKS past rebuild-point filtering at launch
 * (≈830 schema chars — accepted, documented, test-pinned). A later `session_tree` re-apply
 * filters over the original snapshot (which lacks the late names), so a tree navigation drops
 * them — the pre-existing snapshot behavior, unchanged. Child-side tools (`contact_supervisor`,
 * `structured_output`) are out of scope for the STAGE census — spawned children stay
 * stage-unscoped by design (§8.40 adopt-never-impersonates) — but they DO ride READ_ONLY_TOOLS,
 * because the read-only gate IS inherited by adopted children (see SUBAGENT_CHILD_TOOLS).
 */
export const SUBAGENT_TOOLS: readonly string[] = [
  "subagent",
  "wait",
  "subagent_supervisor",
  "intercom",
];

/**
 * pi-subagents' CHILD-side engine tools. `structured_output` and `contact_supervisor` register
 * only inside spawned child sessions (the env-keyed prompt-runtime registration — never in
 * parents, so those names are inert in every gated parent session; `setActiveTools` ignores
 * unknown names). `subagent_wait` is ALSO registered by the top-level parent extension
 * (pi-subagents 0.45.1's `registerWaitTool`) — the accepted widening: a wait-only,
 * non-repo-mutating tool active in gated parents. A gated ADOPTED child (mode inherited via the
 * `adopt` arm, contracts.md §8.3) must keep them active:
 *  - `structured_output` is the engine-REQUIRED completion call when the launch carries an
 *    `outputSchema` — stripping it makes the child physically unable to finish and fails the
 *    run with `structuredOutputFailed`;
 *  - `contact_supervisor` is the child→parent intercom door;
 *  - `subagent_wait` is the fanout-child wait door.
 * None mutates the repo (`structured_output` writes only the engine's capture file under
 * `.pi-subagents/` scratch). Census decision, recorded: these names deliberately join NEITHER
 * PERK_TOOLS nor BORROWED_TOOLS — the stage-filter universe never sees them because children
 * are stage-unscoped by design (adopt never impersonates a stage), so gate membership is their
 * only governance surface.
 */
export const SUBAGENT_CHILD_TOOLS: readonly string[] = [
  "structured_output",
  "contact_supervisor",
  "subagent_wait",
];

/**
 * @ff-labs/pi-fff's search tools. BOTH mode name-sets are enumerated (static names, inert
 * when absent — the code_search version-tolerance precedent): warm sessions run pi-fff's
 * default tools-and-ui mode (fffind/ffgrep [+ fff-multi-grep when enabled upstream]);
 * perk cold launches inject PI_FFF_MODE=override, where FFF registers under the builtin
 * names find/grep (already allowlisted/pass-through) plus multi_grep. All register at
 * load time. Frecency/history state lives under ~/.pi/agent/fff/ — outside the worktree
 * (the fetch_content cache-write precedent), so the read-only bar holds.
 */
export const FFF_SEARCH_TOOLS: readonly string[] = [
  "fffind",
  "ffgrep",
  "fff-multi-grep",
  "multi_grep",
];

/**
 * The enumerated borrowed-package tool census (contracts.md §8.40): every foreign tool name perk
 * wires — via `BORROWED_PACKAGES`, a provider package, or the linear issue backend — joins the
 * scoped universe beside PERK_TOOLS. Same static-name posture as READ_ONLY_TOOLS: names are
 * inert when the package is absent, and un-enumerated foreign names always pass through every
 * stage filter (fail-open — enumeration here is diet-completeness, not correctness).
 *
 * Audit records (the per-package census):
 *  - Registration timing: every census name registers at load time EXCEPT pi-subagents' parent
 *    supervisor pair (see SUBAGENT_TOOLS — session_start, leaks past rebuild-point filtering).
 *  - Foreign `setActiveTools` owners: plannotator's phase machinery and @tombell/pi-plan's plan
 *    mode run their OWN toggles — perk re-applies only at rebuild points, so a foreign toggle
 *    between rebuilds wins (fail-open direction), and a mid-session rebuild re-installs perk's
 *    stage set over a foreign restriction. Pre-existing interplay, recorded, not re-engineered.
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
  // @plannotator/pi-extension: perk never drives its plan phases (the adapter bridges
  // `plan_review` to its event API), so the submit tool is dead weight in stage sessions.
  "plannotator_submit_plan",
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
  // The delegation carve-in: `subagent`/`wait` (+ the parent supervisor pair, which already
  // leaks active into cold-door gated sessions via late registration — keeping warm-entered
  // gates consistent, and letting the parent answer child `contact_supervisor` asks) stay
  // reachable while gated for the other delegation flows (the gated objective-plan guidance now
  // names the `explore_objective_node` tool below, not a direct spawn). ACCEPTED LENIENCY,
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
  "run_pr_review_wave",
  "run_pr_review_dynamic_wave",
  "submit_pr_review",
  "start_review_wave",
  "collect_review_wave",
  "push_annotations",
  "start_draft_review_wave",
  "collect_draft_review_wave",
  "run_ci",
  "submit",
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
  "ready",
  "run_ci",
  "land",
  "learn",
  "run_learn_wave",
  "classify_review_feedback",
  "finalize_address",
  "post_pr_review",
  "run_pr_review_wave",
  "run_pr_review_dynamic_wave",
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
  "gist-author": ["ask_user_question", "gist_draft", "gist_save", ...RESEARCH_TOOLS],
  "gist-save": ["ask_user_question", "gist_draft", "gist_save", ...RESEARCH_TOOLS],
  "objective-author": [
    "ask_user_question",
    "objective_draft",
    "objective_save",
    "reconcile_objective",
    "add_objective_node",
    "objective_node",
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

/** Exported for tests: the injected read-only mode context. (No tool enumeration — gate-ON
 * already applies READ_ONLY_TOOLS via setActiveTools, so the active tool set IS the list.) */
export const READ_ONLY_CONTEXT = render("contexts/read-only.md", {
  marker: READ_ONLY_MARKER,
});

// --- pure policy (copied from plan-mode/utils.ts so this primitive is self-contained; perk-owned
// so retiring the borrowed pi-plan extension leaves no dangling import) -------

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
  /\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout|branch\s+-[dD]|stash|cherry-pick|revert|tag|init|clone)/i,
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
  // `code` (the editor) is vetoed in command position only — the old bare \bcode\b veto blocked
  // every command CONTAINING the word (destructive-wins), so the allowlisted `gh search code`
  // could never run. `code f.ts`, `ls; code .`, `x && code .`, `$(code y)` stay blocked.
  /(^|[;&|(]|\$\()\s*code\b/i,
];

const SAFE_PATTERNS = [
  // `cd` mutates nothing — it is the common prefix for scoping a read-only query
  // (`cd repo && perk objective show …`). Safe under the per-segment model: every other
  // segment is still independently validated and the whole-string destructive veto is unchanged.
  /^\s*cd\b/,
  /^\s*cat\b/,
  /^\s*head\b/,
  /^\s*tail\b/,
  /^\s*less\b/,
  /^\s*more\b/,
  /^\s*grep\b/,
  /^\s*find\b/,
  /^\s*ls\b/,
  /^\s*pwd\b/,
  /^\s*echo\b/,
  /^\s*printf\b/,
  /^\s*wc\b/,
  /^\s*sort\b/,
  /^\s*uniq\b/,
  /^\s*diff\b/,
  /^\s*file\b/,
  /^\s*stat\b/,
  /^\s*du\b/,
  /^\s*df\b/,
  /^\s*tree\b/,
  /^\s*which\b/,
  /^\s*whereis\b/,
  /^\s*type\b/,
  /^\s*env\b/,
  /^\s*printenv\b/,
  /^\s*uname\b/,
  /^\s*whoami\b/,
  /^\s*id\b/,
  /^\s*date\b/,
  /^\s*cal\b/,
  /^\s*uptime\b/,
  /^\s*ps\b/,
  /^\s*top\b/,
  /^\s*htop\b/,
  /^\s*free\b/,
  /^\s*git\s+(status|log|diff|show|branch|remote|config\s+--get)/i,
  /^\s*git\s+ls-/i,
  /^\s*npm\s+(list|ls|view|info|search|outdated|audit)/i,
  /^\s*yarn\s+(list|info|why|audit)/i,
  /^\s*node\s+--version/i,
  /^\s*python\s+--version/i,
  /^\s*curl\s/i,
  /^\s*wget\s+-O\s*-/i,
  /^\s*jq\b/,
  /^\s*sed\s+-n/i,
  /^\s*awk\b/,
  /^\s*rg\b/,
  /^\s*fd\b/,
  /^\s*ast-grep\b/,
  // Browser-automation skill (.agents/skills/agent-browser): a command-keyed entry mirroring
  // `ast-grep` — it gates the command, not its args. Two invocation forms: the bare global
  // install on PATH, and the `npx` fallback anchored to `agent-browser` so bare `npx <anything>`
  // stays blocked. Accepted known leniency: the leading-command model cannot inspect args, so
  // agent-browser's own output flags (screenshot/video `--output`) can write files and its actions
  // can mutate external sites — outside the gate's granularity. This is accepted and documented,
  // consistent with the allowlisted `curl` / `fetch_content` GitHub-clone cache-write precedent
  // (both write outside the gate). The whole-string `>`-redirect destructive veto still applies.
  /^\s*agent-browser\b/,
  /^\s*npx\s+agent-browser\b/,
  /^\s*bat\b/,
  /^\s*eza\b/,
  // perk's own read-only objective queries (show/next + their s/n aliases, plus the non-mutating
  // node-engagement read the objective-plan factory needs). The trailing \b keeps the `n` alias
  // from matching the mutating `node` subcommand; node-engagement allowed; create/node/reconcile
  // stay blocked.
  /^\s*perk\s+(objective|obj)\s+(show|s|next|n|node-engagement)\b/i,
  // Read-only `gh` queries — the guidance in the managed AGENTS block ("GitHub access goes
  // through gh") must be followable in read-only sessions. Query-shaped subcommands only;
  // `gh api` stays blocked (it can POST/PATCH), as do all mutating subcommands (create/edit/
  // merge/close/comment/clone/...). Destructive-wins still blocks `> file` redirects.
  /^\s*gh\s+(issue|pr|repo|run|release|label)\s+(view|list|diff|status|checks)\b/i,
  /^\s*gh\s+search\s+(issues|prs|code|commits|repos)\b/i,
  /^\s*gh\s+auth\s+status\b/i,
];

/**
 * Split a command into top-level shell segments for the per-segment safe check. Walks the string
 * character by character tracking single- and double-quote state, splitting only on UNQUOTED
 * sequencing operators `;`, `&&`, `||`, and `|` (`&&`/`||` are two-char operators; a lone `|` is
 * the pipe). Quoted operators must not split — load-bearing: a `|` inside `grep -iE 'a|b'` stays
 * in one segment. Segments are trimmed and empties dropped.
 *
 * Known limitation: backslash-escaped quote characters are not handled. This is acceptable — the
 * whole-string destructive veto in isReadOnlyBashCommand remains the backstop.
 */
function splitTopLevelSegments(command: string): string[] {
  const segments: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === ";" || ch === "|" || ch === "&") {
      const next = command[i + 1];
      if ((ch === "|" && next === "|") || (ch === "&" && next === "&")) {
        // two-char operator (`||` / `&&`)
        segments.push(current);
        current = "";
        i++;
        continue;
      }
      if (ch === ";" || ch === "|") {
        // single-char sequencing operator (`;` / `|`)
        segments.push(current);
        current = "";
        continue;
      }
      // a lone `&` (background / part of `&>`): keep it in the segment so `&>` redirect detection
      // and the destructive veto see it intact.
      current += ch;
      continue;
    }
    current += ch;
  }
  segments.push(current);
  return segments.map((s) => s.trim()).filter((s) => s.length > 0);
}

/**
 * Whether a bash command is allowed under read-only mode. Two independent checks:
 *  - NOT destructive: a WHOLE-STRING scan against DESTRUCTIVE_PATTERNS (destructive-wins — content
 *    anywhere in the string, incl. command substitutions, still vetoes). Two redirect carve-outs
 *    are neutralized first: FD duplications (`2>&1`, `1>&2`) and redirects to `/dev/null`
 *    (`>/dev/null`, `2>/dev/null`, `&>/dev/null`, `>>/dev/null`) — both discard output and write
 *    nothing to the filesystem. Redirects to a REAL path (`> file`, `&> file`, `>> file`) are NOT
 *    carved out and stay destructive.
 *  - SAFE per segment: split into quote-aware top-level segments (on `;`/`&&`/`||`/`|`) and require
 *    EVERY segment's leading command to match a SAFE_PATTERNS entry. This unblocks `cd`-prefixed
 *    chains and tightens the model — a non-safe command anywhere in a chain is now blocked, not
 *    just when it leads.
 * Pure → unit-testable offline.
 */
export function isReadOnlyBashCommand(command: string): boolean {
  const withoutFdRedirects = command
    .replace(/\d*>&\d+/g, " ")
    .replace(/(?:\d+|&)?>>?\s*\/dev\/null\b/g, " ");
  const isDestructive = DESTRUCTIVE_PATTERNS.some((p) => p.test(withoutFdRedirects));
  const segments = splitTopLevelSegments(command);
  const isSafe =
    segments.length > 0 && segments.every((seg) => SAFE_PATTERNS.some((p) => p.test(seg)));
  return !isDestructive && isSafe;
}

// --- the controller -----------------------------------------------------------------------------

/** The API the plan-mode and read-only-stage consumers use + the lifecycle hooks index.ts wires. */
export interface ToolGating {
  /**
   * Reapply the gate + stage scoping from a rebuilt `mode` + `stage` (called on session_start
   * AND session_tree). `stage` is the branch-LWW workflow-state stage id (undefined = unscoped).
   */
  syncFromState(mode: string | undefined, stage: string | undefined): void;
  /** Enter read-only mode: persist `mode=read-only` + snapshot/restrict tools. (Called by the plan-mode toggle and the objective-plan factory.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + restore tools. (Called by the plan-mode toggle and the save/exit doors.) */
  exit(ctx?: ExtensionContext): void;
  /** Whether the gate is currently active (in-memory source of truth for `tool_call`). */
  isActive(): boolean;
}

function isReadOnlyMode(mode: string | undefined): boolean {
  return mode === "read-only";
}

export function registerToolGating(pi: ExtensionAPI): ToolGating {
  // In-memory gate (mirrors plan-mode's `planModeEnabled`): the authority `tool_call` consults.
  // Fail-closed — a failed sync never opens this; tool_call blocks on any internal error.
  let active = false;
  // The branch-LWW stage id this session is scoped to (null = unscoped). Fail-open by contrast
  // with `active`: no stage / unknown stage / any lookup miss → no filtering.
  let stageId: string | null = null;
  // Pre-engagement tool snapshot, taken ONCE on the first engagement of either concern (the
  // preset.ts discipline, shared by the gate and stage scoping).
  let snapshot: string[] | null = null;

  /**
   * Recompute + install the active tool set from both concerns (contracts.md §8.40):
   *  - gate ON → exactly READ_ONLY_TOOLS, NO stage filter (the decided composition: the gated
   *    set is already the diet, and a strict intersection would break the documented warm
   *    `/objective-plan` carve-out and recreate the seed/gate contradiction class). "The gate
   *    never widens a stage's set and vice versa" still holds: engaging the gate only ever
   *    narrows, and stage scoping never adds a tool.
   *  - gate OFF + stage scoped → a SUBTRACTIVE filter over the snapshot: names outside the
   *    scoped universe (builtins, un-enumerated foreign tools) pass through untouched; scoped
   *    names (PERK_TOOLS ∪ BORROWED_TOOLS) survive only when the stage's list carries them.
   *  - neither engaged → restore the snapshot if one exists (a session that never engages gets
   *    ZERO setActiveTools calls — bare warm sessions stay byte-identical).
   * While engaged the set is re-installed on every sync (tree navigation across mode entries
   * must recompute correctly).
   */
  // The scoped universe: perk's own tools + the enumerated borrowed census. Builtins and
  // un-enumerated foreign names pass through every stage filter untouched (fail-open).
  const SCOPED_TOOL_NAMES: ReadonlySet<string> = new Set([...PERK_TOOLS, ...BORROWED_TOOLS]);

  function apply(nextActive: boolean, nextStage: string | null): void {
    const stageList = nextStage === null ? undefined : STAGE_TOOLS[nextStage];
    // First engagement of either concern: take the one snapshot.
    if ((nextActive || stageList !== undefined) && snapshot === null) {
      snapshot = pi.getActiveTools();
    }
    if (nextActive) {
      pi.setActiveTools([...READ_ONLY_TOOLS]);
    } else if (stageList !== undefined) {
      // The snapshot-missing fallback mirrors the restore path below: the FULL configured tool
      // set (pi.getAllTools()), never a hardcoded list that would silently drop grep/find/ls
      // and perk's custom tools (plan_save/submit/land/learn).
      const base = snapshot ?? pi.getAllTools().map((t) => t.name);
      pi.setActiveTools(
        base.filter((name) => !SCOPED_TOOL_NAMES.has(name) || stageList.includes(name)),
      );
    } else if (snapshot !== null) {
      pi.setActiveTools(snapshot);
      snapshot = null;
    }
    active = nextActive;
    stageId = nextStage;
  }

  // Structural backstop: block writes + non-allowlisted bash while active. Fail-closed on error.
  pi.on("tool_call", async (event) => {
    try {
      if (!active) return;
      if (event.toolName === "edit" || event.toolName === "write") {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (file modifications disabled).`,
        };
      }
      if (event.toolName === "bash") {
        const command = String((event.input as { command?: unknown }).command ?? "");
        if (!isReadOnlyBashCommand(command)) {
          return {
            block: true,
            reason: `perk read-only mode: command blocked (not allowlisted).\nCommand: ${command}`,
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
    if (!active) return;
    // Once-only: injected customs persist to the branch, so a live copy suppresses re-injection;
    // compaction dropping it makes the scan come up clean and the next turn re-injects.
    if (branchCarries(branchOf(ctx), READ_ONLY_MARKER)) return;
    return {
      message: { customType: MODE_CONTEXT_TYPE, content: READ_ONLY_CONTEXT, display: false },
    };
  });

  // Strip the stale read-only marker from context when the gate is off (so it never lingers).
  pi.on("context", async (event) => {
    if (active) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === MODE_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(READ_ONLY_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(READ_ONLY_MARKER),
          );
        }
        return true;
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
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-write" });
      apply(false, stageId);
    },
    isActive(): boolean {
      return active;
    },
  };
}
