---
title: "Workflow commands"
description: "Exact warm-command behavior for the workflow spine, objectives, gists, CI, session utilities, and learn factories."
sidebar:
  order: 3022
---

# Workflow commands

These are perk's warm workflow commands: human gestures inside an existing Pi session. Each entry
names its companion model tool when one exists, marks whether that tool terminates the turn, and
records the refusal or recovery path that keeps the operation safe.

Every slash command acknowledges the gesture with a one-line `running…` notification. When its
outcome has multiple lines, Pi shows a concise one-line headline and appends the complete diagnostic
immediately below as a durable, display-only transcript entry. That entry stays in session
scrollback but is excluded from model context. The equivalent model tool does not append a duplicate
entry: its complete multiline detail remains in the tool Result.

## Warm commands by stage (the spine)

The PR-loop commands resolve the active plan-ref and, where required, its PR. Missing plan or PR
context is a refusal: the command reports the missing state and performs no mutation.

### `/plan`

Toggle perk plan mode — a read-only exploration and plan-authoring session. Paired tools:

- **`plan_draft`** — write or overwrite the working plan draft in the session data directory. It
  is the sanctioned artifact write while read-only, not a save. *Non-terminating.*
- **`plan_review`** — present the draft to the configured review surface and wait for the human
  decision. Approval auto-saves and ends the turn. *Terminating on approval.* Before review, the
  authoring skills direct a one-question-at-a-time pre-review grill.

The Plannotator browser can return a `# Direct Edits` unified diff. On the **plan** arm, approval
applies the diff to the draft and saves the edited bytes; if application fails, perk saves the
original draft with a loud warning and leaves the diff in feedback. Denial returns the diff for a
`plan_draft` rewrite. On the **objective** and **gist** arms, approval with Direct Edits does not
save: the agent must fold the rendered-markdown diff into `objective_draft` or the matching
`gist_draft` fields and request a confirming review.

### `/plan-save`

Persist the plan to the issue backend, link the session to it, and cross the read-only → read-write
boundary. `/plan-save` is the manual failsafe for approval → save. Paired tool:

- **`plan_save`** — save the validated `plan-draft.md` artifact when present, otherwise an explicit
  plan parameter, otherwise the latest assistant-message fallback. *Terminating.*

If none of those sources contains a plan, the tool refuses with `invalid_input`; the slash command
warns and leaves the session in place. Write the working draft with `plan_draft` and retry.

### `/implement-here`

Exit plan mode **without saving an issue** and implement the current draft in this session. The
read-only gate comes off, but no issue or plan-ref is created; editing is allowed while committing,
branching, and pushing remain yours. The first-party plan review offers the same fourth verdict.
With the approve/deny-only Plannotator review surface, use `/implement-here` explicitly.

Because no plan-ref exists, `/submit`, `/ready`, `/address`, `/land`, and `/learn` do not apply.
The draft remains available, so `/plan-save` can still create a canonical plan later. The command
refuses in an objective-node planning session because the node-linked plan must be saved, and the
review surface does not offer the no-save verdict there. It also
warns and does nothing when plan mode is already off. There is no model-tool twin, so the agent
cannot choose this no-save exit itself.

### `/implement`

Refresh implement context through a fresh in-worktree handoff. The command works only in a
read-write session linked to a plan; elsewhere it refuses and points to cold `perk implement`.
It also refuses when the worktree is dirty, because only the saved plan crosses the fresh-context
boundary, and when the host cannot create an interactive session. Cancelling the handoff keeps the
current session. Cross-worktree or first-time implementation always starts with `perk implement`.
No paired tool.

### `/submit`

Push the active plan's branch and open a draft PR linking the plan. Paired tool:

- **`submit`** — publish the branch and open the draft PR. *Terminating.*

After opening the PR, `/submit` probes mergeability with `git merge-tree`. A conflict persists one
of at most two attempts and primes **`resolve_submit_conflicts`**, a parameterless, single-use,
non-terminating tool. Its code-owned fresh foreground `perk.conflict-resolver` reads authoritative
PR context, rebases, resolves, verifies and pushes with `--force-with-lease`. Only on `resolved`
does the parent call canonical `submit` again to confirm mergeability. A child report cannot itself
finish the work. Withholding/failure means stop and report, not local conflict edits or another
launch. Mechanical publication remains successful even if resolution fails. If the probe cannot
run, submission succeeds with mergeability undetermined.

Authorization is bound to this session, run, worktree and unchanged attempt counter; direct,
repeated, stale or read-only calls refuse. Full address finalization uses the same tool and cap,
only after publication and thread resolution succeed. Missing/disabled/ambiguous/shadowed native
profiles stop before mutation. Native `worktree: true` allocation defaults are incompatible with
Perk's Python-owned worktree; inspect the native setting and reload after correction, rather than
switching execution mode or adding extensions. No new Perk config key is involved.

A persistent `perk-submit-conflict.lock` in the worktree's canonical Git directory excludes other
participating submit/address resolvers across sessions/processes. Contention does not refund an
attempt or retry. Confirmed native completion releases the lock; uncertain termination retains it.
Cancellation does not undo Git work; reload and PID death do not unlock. Follow the
[human-only lock recovery procedure](../../how-to/recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock)
when a safe diagnostic reports a retained lock. This does not fence manual Git commands or change
retained-continuation dispatch.

For a stacked delivery layer, `/submit` publishes onto the parent layer's branch, registers the
native stack, and records checkpoints only after remote verification. Re-submitting a published
lower layer transactionally synchronizes the published suffix above it from each successor's
verified remote head. Typed failures retain their normal status/recover remedies. A failed publish
leaves a recoverable journal operation; re-running `/submit` resumes it. Conflict probing and
rebasing use the parent branch.

### `/ready`

Ready the active plan's PR. Incremental: mark the draft PR ready for review — `/submit`
deliberately leaves it draft. Stacked: the deliberate **post-review handoff** — review happens
on the draft layer PR, and after review + address `/ready` stamps the exact verified published
head (draft and non-draft PRs); the recorded stamp **unblocks planning of the layer's direct
dependents**. Supervisors and factories name it; it is never auto-run. Paired
tool:

- **`ready`** — open the draft for review (incremental) or record the handoff stamp (stacked).
  *Terminating.*

For a stacked plan, the exact layer must be verified published; flipping a draft additionally
requires no unresolved operation or structural blocker. An already-ready PR is idempotent after
target-publication revalidation — and still stamps. A failed stamp names its remediation
(ambiguous/transient arms converge on re-run).

After a successful stacked stamp (a re-stamp included), `/ready` **drives the ready-time
reconcile pass in-session — unless a refusal arm applies**: the stamp report itself carries
only the stamp facts, and the continuation is announced separately, once accepted. When it
drives, the same session is steered into reconciling the objective against the accepted
layer's pinned diff range (`parent_checkpoint..stamped_head`) — prose rewrites, node
description updates, and guarded `pending` tail-appends only; nothing is marked done, because
nothing landed. The refusal arms are **loud, never silent**: a read-only (gated) session warns
instead of driving (the pass's write tools are gated off), and a malformed/mixed-version
envelope or evidence failing strict validation warns and skips. Failure anywhere is fail-open
— the handoff stamp always stands, and re-running `/ready` (or `perk ready <plan>` from a
terminal) re-enters the pass.

### `/address`

Classify review feedback in an isolated child, fix only actionable items yourself, then publish and
resolve. `--preview` classifies only. Paired tools:

- **`classify_review_feedback`** — run the read-only `perk.review-classifier` through the wave
  module and return an engine-validated report. Raw GitHub text never enters the parent session;
  on failure, surface the error and stop. *Non-terminating.*
- **`finalize_address`** — after fixes are committed, publish through the normal submit operation
  (including a stacked suffix cascade), then reply to and resolve addressed threads. Full success
  records `last_review_batch` and terminates. A structured partial resolve returns a reduced
  `retry_threads` batch; unstructured failure requires inspection. Never push manually.
  *Terminating on full success.*

### `/land`

Squash-merge the approved PR, close the plan issue, set the pending-learn marker, and drive
objective reconciliation when linked. A learn-docs consolidation plan is exempt from land → learn:
land stamps `learn_state: skipped`, sets no marker, and releases the worktree. The command refuses a
stacked-delivery plan before mutation; stacked layers land only as one atomic train. Paired tool:

- **`land`** — merge, stamp the canonical `learn_state`, and set the marker when applicable.
  *Terminating.*

### `/learn`

Investigate the landed change, capture durable learning when warranted, clear the pending-learn
semaphore, and release the worktree. Bare interactive `/learn` gathers one session-grounded
evidence bundle (planning and implementation sessions, saved plan, merged PR, existing-docs
inventory), then runs 2–4 fresh `perk.learn-analyst` lanes through `run_learn_wave`. Missing
evidence is surfaced rather than guessed; a failed analyst is a reported skipped angle, and a
malformed or misattributed analyst report degrades to a skipped angle too (its body is never
relayed). The parent
reconciles all reports into one classified decision and either captures it or skips.

If bundle gathering fails, the flow degrades to a single-pass capture. `/learn skip` records a
canonical skip and clears the marker. `/learn <text>` captures the text verbatim without a decision
classification. A learn-docs plan short-circuits to the defensive marker-clear path. Paired tools:

- **`run_learn_wave`** — run 2–4 analyst angles with `session-deviations` mandatory and return
  schema-validated reports plus skipped angles. *Non-terminating.*
- **`learn`** — capture an optional `{decision, target?}` classification, or record a skip when no
  summary is supplied. *Terminating.*

## Objective doors (warm)

These commands control the active objective and its roadmap workflow.

### `/objective`

Show, set (`<id>`), or clear (`clear`) the active objective and its session budget. No paired tool.

### `/objective-plan`

Start the objective plan factory: select the next node and author a bounded plan. Pass an objective
id (otherwise the active objective) and optional `--node ID`. If neither an argument nor an active
objective exists, the command refuses and points to `/objective-plan <id>` or `/objective <id>`.
The command enters the read-only gate before driving the factory turn. Paired tools:

- **`objective_node`** — link a saved plan to its node, change a node status, or update its
  description. A `status:"done"` call requires a non-trivial requirement→evidence audit; malformed
  fields and calls with no actual change refuse. *Non-terminating.*
- **`explore_objective_node`** — optionally inspect a large node through one isolated read-only
  `perk.objective-explorer` lane and return engine-validated findings. On failure, explore directly.
  *Non-terminating.*

### `/objective-reconcile`

Reconcile an objective's Reconcilable prose region against merged evidence. The roadmap table and
Immutable notes are never touched. The objective resolves from an explicit id, the active
objective, then the linked plan; if none exists, the command refuses and asks for an id. Paired
tools:

- **`reconcile_objective`** — replace the full Reconcilable prose region. *Non-terminating.*
- **`add_objective_node`** — sparingly add genuinely new work: a deferred follow-up, uncovered gap,
  missing prerequisite, or human-requested unit. *Non-terminating.*

### `/objective-save`

Persist a drafted objective and structured roadmap, activate it, and start budget tracking — the
manual approval → save failsafe and read-only → read-write boundary. Paired tools:

- **`objective_draft`** — write the working structured draft. Optional `base` targets a
  non-default branch; optional `delivery` is `incremental` or `stacked`, with incremental the
  recommended default. Optional `dream_report` (`perk learn dream` only — required inside a
  dream session, refused outside one; reviewed with the objective as one bundle).
  *Non-terminating.*
- **`objective_save`** — save the structured draft, including optional base and delivery.
  Optional `dream_report` (`perk learn dream` only — required inside a dream session, refused
  outside one; re-validated at save). *Terminating.*

The review surface renders the delivery choice directly below the title. When the validated draft
exists, `/objective-save` drives the shared approval-save seam. If no draft exists, it exits the
read-only gate and hands a structured save turn to the session instead of silently failing; that
turn must create the draft and call `objective_save`. If the draft exists but is invalid
(corrupted or undecodable), the command stops with an error naming the problem — rewrite the
draft with `objective_draft` and re-run; it never hands a save turn over a corrupted artifact.

The cold `perk objective author` door has no `/objective-author` twin.

### `/objective-stack`, `/objective-sync`, `/objective-recover`, `/objective-land`

The stacked-delivery control surface delegates mutations to the
[`perk objective stack` workers](../cli/objective.md#perk-objective-stack-status-objective). Every operation
resolves its objective from an explicit id, the active objective, then the linked plan. With no
match it refuses and asks for an explicit objective.

- **`/objective-stack [N]`** renders the train, build readiness, blockers, unresolved operations,
  pending conflict continuation, and orphaned residue. It works in read-only sessions.
- **`/objective-sync [N]`**, **`/objective-recover [N]`**, and **`/objective-land [N]`** drive a
  preview-first flow and act through typed tools only after explicit approval. All three
  soft-refuse while read-only because they mutate published branches or PRs. When a mutating
  sync/continue stops on a rebase conflict, `/objective-sync` automatically dispatches the
  `perk.conflict-resolver` subagent into the retained worktree (resolve-and-stop: the agent only
  resolves — resuming the cascade stays your explicit gesture). Both the workflow and child are
  foreground; the child's actual cwd is the freshly containment-validated retained worktree,
  not the calling session's directory. No wiring is installed and no parent handoff is copied
  there. Only a completed rebase with passing verification may be offered for explicit continue;
  the child never pushes or aborts the retained rebase.

Paired tools are non-terminating and strictly decoded; malformed or mutually exclusive fields
refuse before the cold worker runs:

- **`objective_stack_status`** `{objective?}` — read stack status.
- **`objective_stack_sync`** `{objective?, base?, dry_run?, continue?, abort?, resolve?}` —
  preview/cascade, resume a resolved retained conflict, discard it, or (on explicit request)
  dispatch the conflict-resolver subagent into the retained worktree. `continue`/`abort` are
  mutually exclusive and cannot combine with `base`/`dry_run`; `resolve` composes with nothing and
  never reaches the cold sync mutation (its only cold call is the corroborating status re-read). A mutating sync/continue that stops on a rebase conflict
  auto-dispatches the resolver (bounded attempts, guarded by a machine-local resolver claim beside
  the manifest); publication stays your explicit `continue`. Warnings include cleanup leftovers
  and their recovery command.
- **`objective_stack_adopt`** `{objective?, node, dry_run?, confirm?}` — adopt one manually pushed
  node head and cascade successors. Mutation requires `confirm: true` after preview.
- **`objective_stack_recover`** `{objective?, operation?, dry_run?, abandon?, accept_prefix?,
  confirm?}` — classify or conclude unresolved operations and sweep residue. `all_after` rolls
  forward. Abandonment requires all-before proof plus confirmation. Prefix acceptance requires an
  `external_prefix` LAND classification plus confirmation, after which sync with `base: true` and
  re-land the remainder.
- **`objective_stack_land`** `{objective?, dry_run?, confirm?}` — preview or atomically land the
  remaining train and close the objective when all nodes are terminal. Mutation requires
  `confirm: true`. A `pending` or `unexpected_enqueued` outcome leaves LAND unresolved: report it,
  stop, and use recovery after the merge settles or expires.

Landing or recovery with journal-assembled landed-train evidence drives
`/objective-reconcile`. The evidence is ordered per layer, sanitized, and recovered at read time.
The at-least-once drive may re-emit for an already closed objective; reconciliation skips when
nothing is stale.

## Gist doors (warm)

A gist is a rough, problem-space statement of intent upstream of plans and objectives. See the
[`perk gist` CLI group](../cli/learn-and-gist.md#perk-gist). Direct authoring starts cold with `perk gist author`.

### `/gist-save`

Persist the working gist draft — the manual approval → save failsafe. Paired tools:

- **`gist_draft`** — rewrite the working prose plus optional title/scope artifact.
  *Non-terminating.*
- **`gist_save`** — create the canonical gist and report its plan/objective consumption command.
  *Terminating.*

In a `gist-author` session, `plan_review` reviews the rendered gist. First-party review is
view-only and approval auto-saves. Plannotator Direct Edits turn an approval into a revise round:
fold title, scope, and prose hunks into `gist_draft`, then re-review. If `/gist-save` finds no draft,
it drives the session to create one and call `gist_save`; it does not invent or scrape gist content.
If the draft exists but is invalid (corrupted or undecodable), the command stops with an error
naming the problem — rewrite the draft with `gist_draft` and re-run.

## Utility commands & factories

### `/ci`

Run configured CI checks and show a one-line summary; never auto-fix. Checks run concurrently. Pass
one name or comma-separated names (for example, `/ci lint,test`) for a subset. Paired tool:

- **`run_ci`** — return the detailed per-check report and failure output. The agent owns
  Run → Report → Fix → Verify. A green subset is labelled selected; a green run-all is definitive
  for the diff, with glob-skipped checks disclosed as intentionally out of scope. *Non-terminating.*

### `/commit-and-compact`

Commit completed work, compact, then automatically start a continuation turn only after Pi reports
that compaction succeeded. On a dirty tree, perk drives one model turn to stage only the completed
changes and write a real commit; it never performs blanket `git add -A` or pushes, and compacts only
after HEAD advances. Clean and read-only sessions compact immediately. The continuation distinguishes
committed, already-clean, and read-only outcomes. A valid active-session plan gets provider-aware
identity and canonical re-read guidance; sessions without that verified linkage resume the current
task generically. Before continuing, the agent reorients from repository evidence (`git status`,
recent log, and relevant diffs) instead of trusting the compacted summary alone. If worktree state
cannot be determined or no commit appears, compaction is skipped loudly; a skipped or failed
compaction never dispatches the continuation. Pi's `/compact` remains the escape hatch. No paired tool.

### `/perk-selfcheck`

Verify that converged context reached the live prompt, then report identifier/count/byte censuses
for the append prompt, context files, skill catalog, active tool definitions grouped by source, and
perk branch context. `perk doctor` checks disk; `/perk-selfcheck` checks prompt delivery. It is
report-only and never reveals prompt or message text. No paired tool.

### `/learn-docs`

Gather doc-destined open perk:learn issues and author a `docs/learned` consolidation plan. The cold
door pre-routes classifications; the inbox carries classifications and an existing-docs scan. The
factory can emit a `SHOULD_BE_CODE` follow-up and regenerates routing with `perk learn docs-sync`.

In an interactive session, the door refuses **before gathering** when `plan_save` is not active —
including read-only, worktree-stage, or provider-restricted sessions — and points to cold
`perk learn docs`. An empty inbox reports a gentle warning. Headless invocation may materialize the
inbox but cannot drive an authoring turn; it logs the gathered path and asks you to run
interactively. No paired tool.

### `/learn-code`

Gather pre-classified `SHOULD_BE_CODE` perk:learn issues and author a bounded plan that verifies
each target and routes the insight into its real code home. It never edits code directly. The same
interactive `plan_save` gate, empty-inbox warning, and headless gather-without-driven-turn behavior
as `/learn-docs` apply; the cold fallback is `perk learn code`. No paired tool.

## Related

- **Look up:** [Stages and doors](./stages-and-doors.mdx) — distinguish warm capability from a
  standalone launcher.
- **Look up:** [Review and authoring](./review-and-authoring.md) — review-specific commands and
  companion tools.
- **Look up:** [In-session commands & tools](../in-session.md) — return to the stable surface map.
