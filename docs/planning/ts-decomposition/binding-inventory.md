# Binding inventory

> **Snapshot:** Perk commit `95ff7cc7`, inspected 2026-08-24. This is the
> frozen per-registration binding inventory required by
> [`migration-and-verification.md`](migration-and-verification.md) ("Baseline
> before the first migration"): **a verification inventory, not a target
> contribution catalog**. It describes what IS registered, never what should
> exist. The derivation method is the
> [`current-system-map.md`](current-system-map.md) **Method** section (same
> production selector, same ast-grep + literal cross-checks); this inventory
> was hand-authored from that mechanical derivation. The inventory's own
> commits are docs-only changes under `docs/` and do not invalidate the
> `extension/` facts measured at the stamped commit.

**Freeze depth.** Compact facts are inline; bulky byte-exact facts — schema
JSON, `description`/`promptSnippet`/`promptGuidelines` text, prompt templates —
are frozen **by anchor** (registering file + registration/export name) at the
stamped commit, where git preserves the exact bytes. Anchors are durable (file
paths + names), never line numbers. Every registration has a row; facts uniform
across a whole host form are stated once in that section's preamble.

**Row census** (matches the map's headline census at the same commit): 37
tools, 31 effective commands (29 `registerPerkCommand` call sites → 30 runtime
commands, because the learn-factory site is invoked once per kind, plus direct
`/btw`), 2 flags, 1 shortcut, 33 hooks.

The nine binding facts from `migration-and-verification.md`'s baseline table
map onto the sections below: host form and name + input schema + prose units +
availability/execution mode + progress + final result/headless behavior are
per-row in §1–§3; hooks and lifecycle ordering are §4; borrowed-tool access is
§5; prompt-evidence audience/Session-shape/provenance is §6.

## 1. Tools (37 rows)

Uniform facts, stated once:

- **Host form.** Every row is one `pi.registerTool({...})` object literal in
  the registering file. Anchor = registering file + the tool `name` string
  (unique per file).
- **Execution mode.** All 37 declare `executionMode: "sequential"`.
- **Prose units.** All 37 carry all three prose units — `description`,
  `promptSnippet`, and `promptGuidelines` — inline in the registering file
  (guidelines typically via a module-level `TOOL_GUIDELINES` constant). No
  tool sources its registration prose from `prompts/` templates; the
  `prompts/` renders (via `substrate/prompts.ts`) feed injected *guidance and
  context*, not tool registration fields. Byte-exact text is frozen by anchor.
- **Progress.** `onUpdate` is unused by 36 of 37 tools (the parameter is bound
  as `_onUpdate`). The one exception is `run_ci`, which emits incremental
  per-check progress through `onUpdate` (UI-only partials with an honest
  `in_progress` marker).
- **Final result + headless behavior.** Every tool returns the canonical
  warm-door result from `substrate/result.ts`: `content: [{type: "text"}]`
  plus a typed `details` object (discriminated on `details.ok`), so the
  outcome reaches the model identically with or without a UI. Failures use the
  loud-but-soft idiom (`"<label> failed: <message>"` + `{ok: false, error,
  error_type}`). Presentation side effects route through
  `surfaces/report.ts`, which notifies when `ctx.hasUI` and mirrors to stderr
  when headless. Tools marked **T** in Notes additionally return
  `terminate: true` on full success (the turn ends).
- **Availability.** Two axes, both owned by `substrate/toolGating.ts`
  (`shared/contracts.md` §8.40): **Gate‑ON** = whether the tool is in
  `READ_ONLY_TOOLS` (reachable while the read-only gate is active; gate‑ON
  sets the active set to exactly that list). **Stages** = which
  `STAGE_TOOLS` lists carry it for gate‑OFF stage-scoped sessions (a
  subtractive filter over the scoped universe `PERK_TOOLS ∪ BORROWED_TOOLS`;
  unknown/absent stage = fail-open unscoped). Family shorthand: *worktree* =
  implement/submit/address/land/learn; *plan* = objective-plan/plan/save;
  *objective* = objective-author/objective-save; *gist* =
  gist-author/gist-save.
- **Context-evidence provenance.** No tool handler consumes
  `activeContextWindow()`, `firstKeptEntryId`, or injection-marker scans
  directly — that provenance machinery is hook-side (see §6). Tool handlers
  read *durable* branch state (`rebuildWorkflowState`) only.

Schema cells list top-level parameter names (`*` = required) with their JSON
schema types; nested item shapes and all description text are frozen by
anchor.

| Tool | Registering file | Label | Input schema (top-level) | Gate‑ON | Stages (gate‑OFF) | Notes |
| --- | --- | --- | --- | :---: | --- | --- |
| `classify_review_feedback` | `doors/address.ts` | Classify review feedback | none (empty object) | — | worktree | isolated read-only classifier child |
| `finalize_address` | `doors/address.ts` | Finalize addressed feedback | `threads`* array; `pr` number; `counts` object | — | worktree | **T** on full success |
| `push_annotations` | `doors/annotationPush.ts` | Push annotations | `angle`* string; `findings`* array; `replace` boolean | ✓ | objective + plan + worktree + stack-review | refuses outside a door-primed flow |
| `run_audit_wave` | `doors/auditWaveTools.ts` | Run audit wave | none (empty object) | ✓ | audit | write bound to `audit_bundle_dir` (no aimable path) |
| `run_ci` | `doors/ciExecutor.ts` | Run CI checks | `check` string | — | worktree | **the one `onUpdate` user** (incremental per-check progress) |
| `start_draft_review_wave` | `doors/draftReviewWaveTools.ts` | Start draft review wave | `angles`* array of enum(grounding\|scope\|decision-completeness\|risk) | ✓ | objective + plan | module-level pending slot |
| `collect_draft_review_wave` | `doors/draftReviewWaveTools.ts` | Collect draft review wave | none (empty object) | ✓ | objective + plan | |
| `run_dream_wave` | `doors/dreamWaveTools.ts` | Run dream wave | none (empty object) | ✓ | *(none)* | paths derived from the claimed run's manifest |
| `run_harvest_wave` | `doors/harvestWaveTools.ts` | Run harvest wave | `manifest_path`* string | ✓ | *(none)* | `manifest_path` verified against the claimed run scratch |
| `land` | `doors/land.ts` | Land PR | none (empty object) | — | worktree | **T**; refuses stacked-delivery plans |
| `learn` | `doors/learn.ts` | Finish learn | `summary` string; `decision` enum(5 captured classifications); `target` string | — | worktree | **T** |
| `run_learn_wave` | `doors/learn.ts` | Run learn wave | `bundle_dir`* string; `angles`* array of `{angle enum, emphasis?}` | — | worktree | |
| `objective_stack_status` | `doors/objectiveStack.ts` | Objective stack status | `objective` string\|number | — | worktree | read-only |
| `objective_stack_sync` | `doors/objectiveStack.ts` | Objective stack sync | `objective` string\|number; `base`, `dry_run`, `continue`, `abort`, `resolve` boolean | — | worktree | |
| `objective_stack_adopt` | `doors/objectiveStack.ts` | Objective stack adopt | `objective` string\|number; `node`* string; `dry_run`, `confirm` boolean | — | worktree | |
| `objective_stack_recover` | `doors/objectiveStack.ts` | Objective stack recover | `objective` string\|number; `operation` string; `dry_run`, `abandon`, `accept_prefix`, `confirm` boolean | — | worktree | |
| `objective_stack_land` | `doors/objectiveStack.ts` | Objective stack land | `objective` string\|number; `dry_run`, `confirm` boolean | — | worktree | |
| `run_pr_review_wave` | `doors/prReview.ts` | Run PR review wave | `angles`* array of enum(7 review angles); `directive` string | — | worktree | |
| `post_pr_review` | `doors/prReview.ts` | Post PR review | `verdict`* enum(clean\|actionable); `summary`* string; `comments`, `fyi`, `angles` array | — | worktree | module-level `reviewWaveState` slot in the same file |
| `run_pr_review_dynamic_wave` | `doors/prReviewDynamic.ts` | Run dynamic PR review wave | `directive` string; `force_angles` array of enum(6 forceable angles) | — | worktree | |
| `ready` | `doors/ready.ts` | Mark PR ready | none (empty object) | — | worktree | **T** |
| `start_review_wave` | `doors/reviewWaveTools.ts` | Start review wave | `angles`* array of enum(claimed-intent\|correctness\|tests\|quality); `pr`* number; `worktree`* string; `directive` string; `stack` boolean | — | worktree + stack-review | module-level pending slot |
| `collect_review_wave` | `doors/reviewWaveTools.ts` | Collect review wave | none (empty object) | — | worktree + stack-review | |
| `open_stack_review` | `doors/stackReviewBrowser.ts` | Open stack review | none (empty object) | — | stack-review | snapshot from the cold-launch handoff only |
| `submit` | `doors/submit.ts` | Submit PR | none (empty object) | — | worktree | **T** |
| `submit_pr_review` | `doors/submitPrReview.ts` | Submit PR review | `pr`* number; `event`* enum(approve\|request-changes\|comment); `body`* string; `comments` array; `dry_run`, `allow_repost` boolean | — | worktree + stack-review | formal events raise a blocking UI confirm; headless refuses them |
| `gist_draft` | `factories/gistDraft.ts` | Gist draft | `prose`* string; `title` string; `scope` enum(plan\|objective) | ✓ | gist | structurally limited to the session-data draft artifact |
| `gist_save` | `factories/gistSave.ts` | Save gist | `prose`* string; `title` string; `scope` enum(plan\|objective) | — | gist | **T** |
| `objective_draft` | `factories/objectiveDraft.ts` | Objective draft | `prose`* string; `title`, `base` string; `delivery` enum(incremental\|stacked); `dream_report` object; `roadmap` array | ✓ | objective | draft-artifact carve-out |
| `objective_node` | `factories/objectivePlan.ts` | Update objective node | `objective`* string\|number; `node`* string; `status` enum(6 node statuses); `pr`, `description`, `audit` string | ✓ | objective + objective-plan + worktree | |
| `explore_objective_node` | `factories/objectivePlan.ts` | Explore objective node | `node`* string; `description`* string; `focus` string | ✓ | objective-plan | spawns the read-only objective-explorer child |
| `reconcile_objective` | `factories/objectivePlan.ts` | Reconcile objective prose | `objective`* string\|number; `prose`* string | — | objective + objective-plan + worktree | |
| `add_objective_node` | `factories/objectivePlan.ts` | Add objective node | `objective`* string\|number; `phase`* number; `description`* string; `status` enum(6 node statuses); `slug`, `comment` string; `depends_on` array | — | objective + objective-plan + worktree | |
| `objective_save` | `factories/objectiveSave.ts` | Save objective | `prose`* string; `title`, `base` string; `delivery` enum(incremental\|stacked); `dream_report` object; `roadmap` array | — | objective | **T** |
| `plan_draft` | `factories/planDraft.ts` | Plan draft | `plan`* string | ✓ | plan | draft-artifact carve-out |
| `plan_review` | `factories/planReview.ts` | Plan review | `plan` string | ✓ | objective + plan | **T** on the approved auto-save path; dispatches to the plannotator adapter when selected |
| `plan_save` | `factories/planSave.ts` | Save plan | `plan`, `title`, `objective_id`, `node_id` string; `consumed_learn` array | — | plan | **T** |

## 2. Commands (31 rows)

Shared machinery, stated once: every helper-registered command goes through
`registerPerkCommand` in `substrate/command.ts`, which wraps the handler with
(a) a per-context durable **report-detail sink** attachment and (b) one
uniform, immediate `"running…"` entry toast via `surfaces/report.ts` before
awaiting the original handler. Errors propagate unwrapped. All command
handlers report results through `surfaces/report.ts` (notify when `hasUI`,
stderr mirror when headless). **No command registers argument completions.**
Commands are not tool-gated (tool gating governs tools); per-command
availability below is the handler's own refusal policy plus any
registration-time condition. Anchor = registering file + the command name
string (the `registerPerkCommand`/`pi.registerCommand` call).

The 29 `registerPerkCommand` source call sites produce 30 runtime commands:
`doors/learnFactory.ts` has one call site (`registerLearnFactoryDoor`) invoked
twice at composition, once per kind (`/learn-docs`, `/learn-code`). `/btw`
registers directly via `pi.registerCommand` in `vendor/btw/btw.ts` — the
sanctioned `ctx.ui.custom`/`hasUI` charter exception — for 31 effective.

| Command | Registering file | Argument contract | Availability / refusal policy |
| --- | --- | --- | --- |
| `/address` | `doors/address.ts` | optional `--preview` token | refuses in planning stages |
| `/ci` | `doors/ciExecutor.ts` | optional check name(s), comma-separated | project-CI trust prompt unless trusted/flagged |
| `/commit-and-compact` | `doors/commitCompact.ts` | none (ignored) | human-only; no tool twin |
| `/land` | `doors/land.ts` | none (ignored) | refuses stacked-delivery plans |
| `/learn` | `doors/learn.ts` | bare = evidence pipeline; `skip` = record skip; other text = verbatim capture | refuses in planning stages |
| `/learn-docs` | `doors/learnFactory.ts` | none (ignored) | one call site, DOCS kind |
| `/learn-code` | `doors/learnFactory.ts` | none (ignored) | same call site, CODE kind |
| `/implement` | `doors/lifecycleGates.ts` | none (ignored) | guard-only surface |
| `/objective-review-browser` | `doors/objectiveReviewBrowser.ts` | optional free-form focus note | requires `hasUI` (refuses headless) |
| `/objective-stack` | `doors/objectiveStack.ts` | optional objective id | read-only report |
| `/objective-sync` | `doors/objectiveStack.ts` | optional objective id | soft-refuses while the read-only gate is ON |
| `/objective-recover` | `doors/objectiveStack.ts` | optional objective id | soft-refuses while the read-only gate is ON |
| `/objective-land` | `doors/objectiveStack.ts` | optional objective id | soft-refuses while the read-only gate is ON |
| `/plan-review-browser` | `doors/planReviewBrowser.ts` | optional free-form focus note | requires `hasUI` (refuses headless) |
| `/pr-review` | `doors/prReview.ts` | optional free-form directive | injects guidance for the wave flow |
| `/pr-review-browser` | `doors/prReviewBrowser.ts` | `[pr number\|url] [focus note]` | usage error on unparsable args |
| `/pr-review-dynamic` | `doors/prReviewDynamic.ts` | optional free-form directive | experimental sibling of `/pr-review` |
| `/pr-review-terminal` | `doors/prReviewTerminal.ts` | `[pr number\|url] [focus note]` | usage error on unparsable args |
| `/ready` | `doors/ready.ts` | none (ignored) | |
| `/perk-selfcheck` | `doors/selfcheck.ts` | none (ignored) | session-wiring verifier |
| `/stack-review-browser` | `doors/stackReviewBrowser.ts` | `[pr number\|url] [focus note]` | usage error on unparsable args |
| `/submit` | `doors/submit.ts` | none (ignored) | |
| `/gist-save` | `factories/gistSave.ts` | optional title | artifact-first manual failsafe of the approval→save seam |
| `/implement-here` | `factories/implementHere.ts` | none (ignored) | human-only no-save exit from plan mode; no model tool |
| `/objective` | `factories/objective.ts` | `""` = show status; `clear` = deactivate; `<id>` = activate | |
| `/objective-reconcile` | `factories/objectivePlan.ts` | optional objective id | warns when no objective resolves |
| `/objective-plan` | `factories/objectivePlan.ts` | optional objective number + node id | warns when no objective resolves |
| `/objective-save` | `factories/objectiveSave.ts` | optional title | artifact-first manual failsafe of the approval→save seam |
| `/plan` | `factories/planMode.ts` | none (ignored) | **registration is provider-conditional** (see §3 preamble); toggles the read-only gate |
| `/plan-save` | `factories/planSave.ts` | optional title | artifact-first manual failsafe of the approval→save seam |
| `/btw` | `vendor/btw/btw.ts` (direct `pi.registerCommand`) | `/btw <text>` asks immediately; bare `/btw` opens the side thread (continue/fresh select) | human-only; `hasUI`-gated `ctx.ui.custom` overlay (the one charter exception); isolated in-memory side session mirrors the read-only gate |

## 3. Flags and shortcuts (2 + 1 rows)

Registration-time condition, stated once: `registerPlanMode` implements a
three-tier provider branch on `[providers] plan` — full registration for the
perk reference (fail-safe default), a **partial vacate** under the plannotator
selection (skip the `--plan` flag, the shortcut, and the flag's
`session_start` arm; keep `/plan`), and a **full vacate** (nothing registered)
under any other foreign selection (e.g. tombell). The flag/shortcut rows below
therefore exist only under the perk-reference selection.

| Kind | Name | Registering file | Facts |
| --- | --- | --- | --- |
| Flag | `plan` | `factories/planMode.ts` | boolean, default `false`; cold-start into plan mode (read-only gate) on `session_start` when set; provider-conditional (above) |
| Flag | `allow-project-ci` | `doors/ciExecutor.ts` | boolean, default `false`; runs project-supplied CI checks without the per-session confirm (headless path); unconditional registration |
| Shortcut | `Key.ctrlAlt("p")` | `factories/planMode.ts` | toggles plan mode (same `toggle` as `/plan`); provider-conditional (above) |

## 4. Hooks (33 rows) and lifecycle ordering

One row per `pi.on(...)` call site. Role classes: **state** (compose or
rebuild durable session state), **gate** (tool/transition enforcement),
**inject** (context injection with once-only marker dedup), **strip** (stale
injected-context removal on the `context` event), **present** (rendering or
status). The inject/strip pairs all follow the same recipe: inject a
`display:false` custom message when active and not already carried by the
branch; strip the marker/customType when inactive.

| Event | Registering file | Role |
| --- | --- | --- |
| `before_agent_start` | `adapters/planAdapterPlannotator.ts` | inject — plannotator bridge context (plan/objective/gist flavor by stage) when selected + gated |
| `context` | `adapters/planAdapterPlannotator.ts` | strip — plannotator markers when deselected |
| `before_agent_start` | `adapters/planAdapterTombell.ts` | inject — tombell bridge context when selected + a plan-authoring mode is on |
| `context` | `adapters/planAdapterTombell.ts` | strip — tombell marker when deselected |
| `agent_settled` | `doors/commitCompact.ts` | state — one-shot commit→compact continuation consumer |
| `session_before_fork` | `doors/lifecycleGates.ts` | gate — dirty-repo transition guard |
| `session_before_switch` | `doors/lifecycleGates.ts` | gate — dirty-repo transition guard |
| `before_agent_start` | `factories/gistAuthor.ts` | inject — gist-authoring context (gated + gist-author stage) |
| `context` | `factories/gistAuthor.ts` | strip — gist-authoring marker |
| `session_start` | `factories/objective.ts` | present — objective status segment render |
| `session_tree` | `factories/objective.ts` | present — re-render on branch navigation |
| `agent_settled` | `factories/objective.ts` | state/present — budget rebuild after each settled run |
| `turn_end` | `factories/objective.ts` | state — threshold compaction when an objective is active |
| `before_agent_start` | `factories/objectiveAuthor.ts` | inject — objective-authoring context (gated + objective-author stage) |
| `context` | `factories/objectiveAuthor.ts` | strip — objective-authoring marker |
| `session_start` | `factories/planMode.ts` | gate — `--plan` cold start enters the read-only gate (provider-conditional registration) |
| `before_agent_start` | `factories/planMode.ts` | inject — plan-authoring context while gated (defers to objective/gist author stages) |
| `context` | `factories/planMode.ts` | strip — plan-authoring marker when the gate is off |
| `session_shutdown` | `index.ts` | state — close the hunk-feedback receiver (lease release) |
| `session_start` | `index.ts` | state/gate — the claim/fork/adopt/mint decision, gate + stage-scope sync, plan-ref reconciliation, pointer capture, receiver sync, footer install |
| `session_tree` | `index.ts` | state/gate — LWW rebuild + gate re-sync + receiver re-sync on branch navigation |
| `before_agent_start` | `substrate/agentScratch.ts` | inject — run-scoped agent-scratch guidance block |
| `context` | `substrate/agentScratch.ts` | strip — stale scratch blocks |
| `before_agent_start` | `substrate/bindingDelivery.ts` | inject — the launched stage's user-originated skill bindings (Mechanism A) |
| `context` | `substrate/bindingDelivery.ts` | strip — stale binding injections |
| `tool_call` | `substrate/toolGating.ts` | gate — block `edit`/`write`/non-allowlisted `bash` while the gate is on (fail-closed) |
| `before_agent_start` | `substrate/toolGating.ts` | inject — hidden read-only mode context while active |
| `context` | `substrate/toolGating.ts` | strip — stale read-only marker when the gate is off |
| `session_start` | `vendor/btw/btw.ts` | state — restore the `/btw` side thread |
| `session_tree` | `vendor/btw/btw.ts` | state — restore on branch navigation |
| `session_shutdown` | `vendor/btw/btw.ts` | state — dispose the side session + dismiss the overlay |
| `turn_start` | `vendor/whimsical/whimsical.ts` | present — set the whimsical working message |
| `turn_end` | `vendor/whimsical/whimsical.ts` | present — reset the working message |

### Hooks-ordering: the activation sequence as composed by `index.ts`

`index.ts`'s extension factory calls the installers in this order (hooks each
installs in parentheses; installers registering no hooks are elided except
where order is load-bearing):

1. `registerToolGating` (`tool_call`, `before_agent_start`, `context`) — the
   gate exists before anything that consumes it.
2. `registerAgentScratch` (`before_agent_start`, `context`).
3. `registerBtw` (`session_start`, `session_tree`, `session_shutdown`; +
   direct `/btw`).
4. `registerWhimsical` (`turn_start`, `turn_end`).
5. `registerPlanMode` (`session_start` [provider-conditional],
   `before_agent_start`, `context`).
6. `registerPlanAdapterTombell` (`before_agent_start`, `context`).
7. `registerPlanAdapterPlannotator` (`before_agent_start`, `context`).
8. `registerPlanReview`, `registerObjectiveAuthor` (`before_agent_start`,
   `context`), `registerGistAuthor` (`before_agent_start`, `context`),
   transcript renderers.
9. `createHunkFeedbackReceiver` + index's own `session_shutdown` (receiver
   close).
10. index's own `session_start` — the load-bearing interior sequence:
    **establish before consume** (the run-identity claim/fork/adopt/mint arm
    settles first), **gate sync before fallible reconciliation**
    (`gating.syncFromState` runs before the plan-ref reconciliation so no
    cache read or reconciliation failure can leave the gate unsynced), and
    **strict linkage reads before pointer capture** (the implementation
    session pointer and the feedback-receiver sync run last, on the settled
    identity + reconciled ref).
11. index's own `session_tree` — LWW rebuild + the same gate/receiver
    re-sync.
12. The door/factory installers (`registerPlanSave` … `registerSelfcheck`),
    among which the remaining hook installers run in file order:
    `registerLifecycleGates` (`session_before_fork`,
    `session_before_switch`), `registerObjective` (`session_start`,
    `session_tree`, `agent_settled`, `turn_end`), `registerCommitAndCompact`
    (`agent_settled`), `registerBindingDelivery` (`before_agent_start`,
    `context`).

## 5. Borrowed-tool access (pointer, not a transcription)

The borrowed census is **owned** by `BORROWED_TOOLS` in
`substrate/toolGating.ts` (`shared/contracts.md` §8.40) — this inventory
deliberately does not transcribe it a third time. At the stamped commit it
enumerates **43 names**, composed from the family constants
`WEB_RESEARCH_TOOLS`, `LINEAR_READ_TOOLS`, `LINEAR_MUTATING_TOOLS`,
`SUBAGENT_TOOLS`, `FFF_SEARCH_TOOLS` plus `todo`, `ask_user_question`, and
`plannotator_submit_plan`.

Derivation rules (what a parity check must preserve):

- **Gate ON** → the active tool set is exactly `READ_ONLY_TOOLS` (which
  carves in the borrowed research/read families, delegation, and the named
  structurally-bounded perk tools), with the `tool_call` hook additionally
  blocking `edit`/`write`/non-allowlisted `bash` fail-closed.
- **Gate OFF + stage scoped** → a subtractive filter over the session's tool
  snapshot: names inside the scoped universe `PERK_TOOLS ∪ BORROWED_TOOLS`
  survive only if the stage's `STAGE_TOOLS` list carries them; names outside
  the universe (builtins, un-enumerated foreign tools) pass through
  untouched. Unknown/absent stage id = fail-open (no filtering).
- **Resynchronization** — the gate + stage scope re-sync from persisted
  workflow state on both `session_start` and `session_tree` (host lifecycle
  events), fail-closed on sync errors.
- **Unknown names are inert** — `setActiveTools` ignores names that are not
  registered (e.g. a borrowed name whose package is absent), so the census
  can safely enumerate tools that a given session never loaded.

## 6. Context-evidence provenance summary

The consumer census at the stamped commit: exactly **three** production files
touch `activeContextWindow()` / `firstKeptEntryId`:

- `substrate/workflowState.ts` — the owner. `activeContextWindow()` returns
  the branch entries still represented directly in model context: before
  compaction, the full branch; after, the entries from the v3
  `firstKeptEntryId` cutoff onward plus later appends. Compaction entries are
  excluded because **text quoted by a compaction summary is not a live custom
  block** — the direct-vs-quoted distinction later parity checks must
  preserve.
- `substrate/agentScratch.ts` — `branchHasBlock` asks whether the exact
  current-run scratch block is still directly represented after compaction
  (re-injects when the active window lost it).
- `substrate/bindingDelivery.ts` — `branchHasHeader` asks whether a cold
  prompt or warm injection still active in model context carries the binding
  header marker (re-delivers when only a summary quote survives).

The once-only injection dedup used by the inject/strip hook pairs
(`branchCarries`) scans the **whole branch**, by design: an injected custom
persists durably, so a live copy suppresses re-injection, while
compaction dropping it from the active window makes the consumer-specific
scans above come up clean and triggers re-injection. Per binding, live
evidence therefore means *present in the active context window* (direct
custom context or submitting prompt); marker text surviving only inside a
compaction summary is quoted, not live. No other production file reads these
projections; no tool handler does (§1).
