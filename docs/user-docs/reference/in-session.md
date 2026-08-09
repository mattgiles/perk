# In-session commands & tools

This page references perk's **in-session surface**: the warm `/…` commands you type inside a
running `pi` session and the model-facing **tools** the agent calls on your behalf. It is the
interior counterpart to [CLI commands](./cli.md) (the session **exterior** — the `perk …`
commands you run in your shell). It describes the surface; it does not teach a task (those belong
in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

The in-session surface is registered in the TypeScript extension, so — unlike the CLI reference,
whose shape is fenced by structural drift guards (`test_cli_parity_smoke.py` +
`test_cli_help_sections.py`) — these entries are **human-reviewed for accuracy** against the
extension's command and tool registrations. Accuracy is the governing virtue: each summary is a
reference paraphrase of the registered description.

## Orientation

Inside a `pi` session you drive perk two ways. You type **warm `/…` commands** yourself, and the
agent calls **tools** on your behalf. For the *why* of stages, doors, the two planes, and the
state tiers — read [How perk thinks](../explanation/how-perk-thinks.md); this page only catalogs
the surface and links back to it.

**The warm-door twin pattern.** Most stages expose the same logic two ways inside a session: a
model **tool** the agent calls and a **`/command`** twin you can invoke yourself. The table below
pairs them; the per-stage sections document each pair together.

**The read-only-mode allowlist.** While plan mode is active the agent is structurally restricted
to read/search tools plus the sanctioned write tools (`plan_draft` / `objective_draft`), the
review door (`plan_review`), and subagent delegation (spawned children run per their own agent
definitions) — it cannot edit or run mutating commands until the read-only → 
read-write boundary is crossed at save. The read-only `bash` sub-allowlist also permits the
`agent-browser` CLI (the browser-automation skill) so it can be used for dogfooding / QA while
exploring, alongside `ast-grep`, the read-only `gh` queries, and the read-only `perk objective`
queries (`show`/`next` and the non-mutating `node-engagement` read). The borrowed web/Linear research
tools are also allowed while exploring, as are the pi-fff search tools (`fffind`, `ffgrep`,
`fff-multi-grep`, `multi_grep` — and the FFF-backed `find`/`grep` override names, already in the
allowlist); their depth belongs to the config/provider reference nodes
(4.1/4.2), so this page names them only as a pointer.

**Stage-scoped tools.** When a stage session is read-write (the gate off), the agent's active
tool set carries only that stage's perk tools: the table's "Model tool(s)" column, plus
`ask_user_question` everywhere, plus — in the worktree stages (implement/submit/address/land/
learn) — the shared PR-loop family (`submit`, `ready`, `run_ci`, `land`, `learn`,
`resolve_review_threads`, `run_pr_review_wave`, `post_pr_review`, `submit_pr_review`) plus the reconcile trio
(`reconcile_objective`, `add_objective_node`, `objective_node`), so any PR-loop step works from
any worktree session — `/land` auto-drives objective reconciliation in-session, so the reconcile
tools must be reachable there too. Borrowed-package tools are scoped too: research tools (web
search/fetch + the Linear read tools + the pi-fff local search tools) stay available in every
stage session; delegation
(`subagent`/`wait`) and the `todo` checklist ride only the worktree stages; Linear's mutating
tools and plannotator's submit tool are not offered in stage sessions. Bare sessions are
unchanged, unknown foreign tools still pass through, and slash commands are unaffected.
Sessions with no stage (bare `pi`) keep everything; an unrecognized stage id also scopes
nothing (fail-open).

**Terminating vs non-terminating tools.** A *terminating* tool ends the turn on success
(`plan_save`, `plan_review` on approval, `submit`, `ready`, `land`, `learn`, `objective_save`).
The rest are non-terminating — the turn continues (`plan_draft`, `objective_draft`,
`objective_node`, `reconcile_objective`, `add_objective_node`, `resolve_review_threads`,
`run_pr_review_wave`, `post_pr_review`, `submit_pr_review`, `run_ci`,
`ask_user_question`).
Each entry marks this property.

## The stage/door model

A compact lookup of the workflow spine as the operator sees it
(*objective-author → objective-save → objective-plan → plan → save → implement → submit →
address → land → learn*). The columns are the registry's `mode` and `doors`, the warm command and
its model tool twin, and the cold CLI launcher.

| Stage | Warm command | Model tool(s) | Cold CLI | Mode | Doors |
| --- | --- | --- | --- | --- | --- |
| objective-author | *(none)* | `objective_draft` | `perk objective author` | read-only | cold-local |
| objective-save | `/objective-save` | `objective_draft`, `objective_save` | `perk objective save` | read-write | warm + cold-local |
| objective-plan | `/objective-plan` | `objective_node` | `perk objective plan` | read-only | warm + cold-local |
| plan | `/plan` | `plan_draft`, `plan_review` | `perk plan` | read-only | warm + cold-local |
| save | `/plan-save` | `plan_save` | `perk plan save` | read-write | warm + cold-local |
| implement | *(none)* | *(none)* | `perk implement` | read-write | cold-local + **cold-remote** |
| submit | `/submit` | `submit` | `perk pr submit` | read-write | warm + cold-local |
| address | `/address` | `resolve_review_threads` | `perk pr address` | read-write | warm + cold-local + **cold-remote** |
| land | `/land` | `land` | `perk pr land` | read-write | warm + cold-local |
| learn | `/learn` | `learn` | `perk learn` | read-write | warm + cold-local |

Notable cells: `objective-author` has **no** warm slash command (it is reached cold via
`perk objective author`, or via plan-mode read-only authoring); `implement` is **cold-only**
(`warm: false`) and remote-runnable; `address` is also remote-runnable; every other stage is warm
+ cold-local only.

For *why* a stage is cold-only or remotely runnable, see
[How perk thinks → Stages and doors](../explanation/how-perk-thinks.md).

## Warm commands by stage (the spine)

One subsection per spine stage, pairing the `/command` with its model tool twin where one exists.

### `/plan`

Toggle perk plan mode — a read-only exploration + plan-authoring session. Paired tools:

- **`plan_draft`** — write (or overwrite) the working plan draft to the session data dir. This is
  the only sanctioned write while read-only; it is **not** a save. *Non-terminating.*
- **`plan_review`** — present the draft to the configured review surface (the Plannotator browser
  UI when selected, else perk's in-TUI editor) and wait for the human decision; on approval the
  plan is auto-saved and the turn ends. *Terminating on approval.* Before requesting review, the
  shipped plan/objective authoring skills direct a pre-review grill — a one-question-at-a-time
  stress-test of the plan via the `perk-grill` skill.

  The Plannotator browser additionally lets the reviewer **edit the reviewed document directly**;
  the edits come back as a `# Direct Edits` unified diff opening the review feedback. On the
  **plan** arm an approval auto-applies the diff to the draft and saves the edited bytes (if the
  diff cannot be applied, the plan is saved verbatim with a loud warning and the diff stays in
  the feedback for a manual follow-up); a denial hands the diff to the agent to apply in its
  `plan_draft` rewrite. On the **objective** arm an approval carrying direct edits does **not**
  save — rendered-markdown edits cannot be folded into the structured draft mechanically, so perk
  returns the diff for the agent to fold into `objective_draft`, followed by a confirming
  re-review.

### `/plan-save`

Persist the plan to GitHub as the canonical perk plan and link the session to it — the read-only
→ read-write boundary. `/plan-save` is the manual failsafe for the approval → save flow. Paired
tool:

- **`plan_save`** — the canonical save tool. *Terminating.*

### `/implement-here`

Exit plan mode **without saving an issue** and implement the current plan draft in this session —
the human-owned lightweight path for changes too small to warrant the full plan → issue →
worktree → PR lifecycle. The read-only gate comes off with **no** issue created and no plan-ref
written, and the agent is instructed to make the plan's edits directly in the current checkout —
edits only; committing, branching, and pushing stay with you. The same exit is offered as a 4th
verdict (“Implement here — no issue saved”) in perk's in-TUI plan review; when the Plannotator
review surface is selected (approve/deny only), `/implement-here` is the way to take it.

Because no issue or plan-ref exists, the PR-lifecycle doors (`/submit`, `/ready`, `/address`,
`/land`, `/learn`) do not apply to this work. The plan draft artifact stays intact, so
`/plan-save` can still create the canonical issue later if you change your mind. In an
**objective-node planning session** the command refuses (and the review verdict is not offered) —
a node-linked plan must always be saved. No paired tool: the exit is human-only by construction
(the agent can never choose to skip the save on its own).

### `/implement`

Refresh implement context via an in-worktree handoff. The warm command only refreshes implement
context *inside an existing implement worktree*; cross-worktree / fresh implement is the cold
`perk implement` (cold-only in practice). No paired tool.

### `/submit`

Push the active plan's branch and open a draft PR linking the plan (implement → submit). Paired
tool:

- **`submit`** — push the branch and open the draft PR. *Terminating.*

After the PR opens, `/submit` checks that it is **mergeable** against the target branch (a local
`git merge-tree` probe). If it finds merge conflicts, it spawns a fresh, write-capable
`perk.conflict-resolver` subagent that reads the plan + PR diff, rebases onto the target branch,
carefully resolves every conflict so the diff stays clean and correct, and force-pushes — then you
re-run `/submit` to confirm. This re-drive is bounded (at most twice); if conflicts persist past
that, `/submit` surfaces them loudly so you can resolve them manually. The probe is best-effort: if
it can't run (offline, old git), `/submit` completes with a note that mergeability wasn't determined.

### `/ready`

Mark the active plan's draft PR ready for review — the deliberate publish gate (`/submit` keeps
the PR draft on purpose; `/ready` publishes). Paired tool:

- **`ready`** — mark the draft PR ready. *Terminating.*

### `/address`

Classify PR review feedback in an isolated child, fix only the actionable items yourself, then
batch reply-then-resolve the threads (submit → address). `--preview` classifies only. Paired
tool:

- **`resolve_review_threads`** — batch reply-then-resolve the addressed threads. *Non-terminating.*

### `/land`

Squash-merge the approved PR (closing the plan issue), set the pending-learn marker, and drive
reconciliation (submit → land). When the plan is linked to an objective node, `/land`
auto-drives `/objective-reconcile`. A **learn-docs consolidation plan is exempt** from the
land→learn cycle: no pending-learn marker is set and no `/learn` step follows (`learn_state:
skipped` is stamped as today — the worktree is immediately releasable). Paired tool:

- **`land`** — squash-merge the approved PR, set pending-learn, and stamp the canonical
  `learn_state` plan-header field (`pending`; `skipped` for a learn-docs plan, which also sets
  no marker — the learn-docs exemption). *Terminating.*

### `/learn`

Investigate the landed change and capture learnings into a perk:learn issue, then clear the
pending-learn semaphore and release the worktree. Bare interactive `/learn` is a **multi-angle
orchestrator**: it gathers a **session-grounded evidence bundle** once — the planning +
implementation sessions, the saved plan, the merged PR, and an existing-docs inventory (**missing
evidence is surfaced, not guessed**) — then runs **2–4 fresh-context `perk.learn-analyst`
children** (analyzing distinct angles in isolation) via the **`run_learn_wave`** tool, which
returns **schema-validated structured reports** per angle (a failed analyst is a **reported
skipped angle**, never a failed pass); the session reconciles those reports into **one classified
decision**, and captures it with a **routable classification** persisted on the perk:learn issue
header (the `{decision, target?}` shape — both backends), or skips when nothing durable survives. A
learn-docs consolidation plan short-circuits to a marker-clear no-op (since the land→learn
exemption, land no longer sets the marker for these plans — the short-circuit remains as the
legacy/defensive path); if the bundle can't be
gathered, `/learn` degrades to a simple single-pass capture (never a dead end). `/learn skip`
records the skip canonically on the plan (`learn_state: skipped` via `perk learn skip`) and clears
the marker; `/learn <text>` captures the text verbatim (decision-less). The analyst model is
configurable via `[models.subagents] learn-analyst`. Paired tools:

- **`run_learn_wave`** — run the analyst wave over the gathered bundle (2–4 angles,
  `session-deviations` mandatory — tool-enforced) and return the typed per-angle reports plus
  the explicitly-skipped angles. *Non-terminating.*
- **`learn`** — capture learnings with an optional `decision`/`target` classification (or, with no
  summary, record the skip on the plan and clear the marker). *Terminating.*

## Objective doors (warm)

The objective warm commands as commands. The *objective model* depth — roadmap node schema, node
statuses, the objective-roadmap metadata block — is a later node (3.2); this section catalogs the
command surface only.

### `/objective`

Show, set (`<id>`), or clear (`clear`) the active perk objective + budget for the session. No
paired tool.

### `/objective-plan`

Start the objective plan factory: select the next node and author a bounded plan. Pass an
objective number (else the active objective) and an optional `--node`. Paired tool:

- **`objective_node`** — link a saved plan to its node (`pr:"#N"`) or advance a node's status (on
  `status:"done"` it requires a completion `audit`). *Non-terminating.*

### `/objective-reconcile`

Reconcile an objective's Reconcilable prose region against a merged PR (post-land); the roadmap
table and Immutable notes are never touched. Paired tools:

- **`reconcile_objective`** — rewrite the Reconcilable prose region wholesale. *Non-terminating.*
- **`add_objective_node`** — add a genuinely-new roadmap node (auto-assigned `<phase>.<n>`). Used
  **sparingly**, only when a real new unit of work emerged: a deferred follow-up the plan/PR
  flagged, an uncovered defect or gap, a missing prerequisite for a later node, or
  human-requested work from the engagement block. *Non-terminating.*

### `/objective-save`

Persist a drafted objective + structured roadmap to GitHub, activate it, and start budget
tracking — the read-only → read-write objective boundary (the manual failsafe for the approval →
save flow). Paired tools:

- **`objective_draft`** — write the working objective draft to the session data dir (sanctioned
  read-only write; not a save). Optional `base` targets a non-default branch (omit for the repo
  default); optional `delivery` (`incremental` | `stacked`) records the reviewed delivery
  choice — the agent asks the human explicitly, incremental recommended (omit ⇒ incremental;
  stacked is under development and write-gated). *Non-terminating.*
- **`objective_save`** — the canonical objective save tool (also accepts the optional `base`
  and `delivery`). *Terminating.*

The rendered review surface always carries a prominent `**Delivery:**` line directly under the
title (`**Delivery: STACKED** — all non-skipped roadmap nodes land as ONE atomic pull-request
train …` vs `**Delivery: incremental** (the default — each plan lands independently)`), so the
reviewer approves the choice explicitly.

The cold authoring door **`perk objective author`** has **no** warm slash twin — objective
authoring is reached cold, or via plan-mode read-only authoring (`objective_draft` →
`plan_review` / `objective_save`).

## Gist doors (warm)

A **gist** is a rough, problem-space-focused statement of intent tracked in the issue backend —
upstream of both plans and objectives, carrying no implementation detail (see the
[`perk gist` group](./cli.md#perk-gist)). Authoring is the review-first mirror of
plan/objective authoring, reached cold via `perk gist author`.

### `/gist-save`

Persist the working gist draft to the issue backend — the manual failsafe for the approval →
save flow (artifact-first; drives the save only when no draft exists). Paired tools:

- **`gist_draft`** — write the working gist draft (prose + optional `title`/`scope`) to the
  session data dir (sanctioned read-only write; not a save). Full rewrite per call.
  *Non-terminating.*
- **`gist_save`** — the canonical gist save tool; delegates to `perk gist create` and relays the
  consumption command (`perk plan from <id>` / `perk objective author --from <id>`).
  *Terminating.*

In a `gist-author` session, **`plan_review`** routes to the gist arm: it reviews the **rendered**
gist (title + scope + prose) view-only (deny + feedback is the change channel; implement-here is
never offered), and an APPROVED review auto-saves the draft artifact via `gist_save`'s seam.

## Utility commands & tools

Standalone surfaces not tied to a single spine stage.

### `/ci`

Run the project's configured CI checks and report pass/fail + failure output; never auto-fixes. A
`check` argument runs one configured check. Paired tool:

- **`run_ci`** — run the configured checks and report results; read-only (the agent owns the
  Run → Report → Fix → Verify loop: analyze a failure, fix it in its own turn, then re-verify).
  *Non-terminating.*

### `/commit-and-compact`

Commit the work completed so far, then compact the session. On a dirty worktree it drives one
model turn to stage exactly the changes that belong to the completed work and write a real commit
message (never a blanket `git add -A`, never a push); once that driven run settles **and HEAD has
actually advanced**, perk compacts the session with instructions referencing the new commit(s), so
the compaction summary carries them. Clean-tree and read-only sessions compact immediately (there
is nothing to commit). Two fail-safe skips — perk never compacts when uncommitted work might be
lost: if the git worktree state cannot be determined, or if the driven turn produces **no** commit,
compaction is skipped with a loud warning pointing at pi's builtin `/compact` (the always-available
escape hatch). No paired tool — a human gesture by construction.

### `/perk-selfcheck`

Verify the session's wiring and report a per-surface payload census. The wiring check confirms
perk's converged context actually reached the live system prompt — the ambient routing index
(`.pi/APPEND_SYSTEM.md`) reached the append prompt, and the managed `AGENTS.md` block reached the
context files. Division of labor: `perk doctor` checks the **disk** (files converged);
`/perk-selfcheck` checks the **prompt** (the content reached the model). The census then reports
derived counts for each context surface — the append prompt, context files, the skills catalog
section, active tool definitions (grouped by registering source), and perk-injected branch
context. Output is identifiers plus derived counts/bytes only — never prompt or message text — and
report-only (never a gate). No paired tool.

### `/pr-review`

Multi-angle automated code review: run **one reviewer wave** of **2–3 angle-specialized
fresh-context reviewer lanes** — always **Plan fidelity & completeness** plus 1–2 of **Correctness
& regressions**, **Tests & validation adequacy**, **Code quality, simplicity & docs/contracts
accuracy** — each reviewing one assigned angle and returning an **engine-validated structured
report** (they never post). The wave runs through the flow-scoped **`run_pr_review_wave`** tool:
the perk wave module renders and launches the wave itself (a module-rendered script, never
model-authored mechanics) and applies **one bounded retry** inside the tool. The parent
**reconciles** the per-angle reports (union, dedupe, derive one verdict) and posts a single
verdict-driven outcome via the paired **`post_pr_review`** tool (actionable → an advisory COMMENT
review; clean → a single 👍 reaction). Coverage is strict: if an angle still fails after the
tool's retry the review is reported **incomplete** — actionable findings still post with an
explicit coverage note, but a clean verdict is **never** posted from partial coverage
(`post_pr_review` refuses it with `incomplete_coverage` while the session's recorded wave is
incomplete). The reviewers read adversarially and the plan-fidelity angle
runs an explicit **plan-conformance pass** — verifying the diff implements what the plan called for
and flagging forgotten items (and noting when no plan body was found) — so a clean verdict means
*no actionable findings after a genuine hunt*, not a rubber stamp.

You can pass an **optional free-form focus note** after the command (everything after `/pr-review`),
e.g. `/pr-review have one reviewer focus on the dignified-python skill`. It is threaded into the
reviewer-angle selection step and steers angle selection/emphasis **within** the door's invariants
— Plan fidelity stays mandatory, the 2–3-reviewer cap holds, and the clean/actionable posting bar
is unchanged.

- **`run_pr_review_wave`** — run the multi-angle reviewer wave (2–3 unique angles including
  `plan-fidelity`, plus the optional operator directive threaded to every reviewer as DATA);
  the tool owns the wave mechanics and the one bounded retry, and returns the typed aggregate
  `{ complete, covered, retried, reports, failures }`. *Non-terminating.*
- **`post_pr_review`** — post the reconciled multi-angle review to the PR (delegates to
  `perk pr review-post`; records `last_pr_review` in workflow-state; refuses a clean verdict
  while the session's recorded wave is incomplete). *Non-terminating.*

### `/pr-review-dynamic`

**Experimental.** The selector-driven sibling of `/pr-review`: instead of the parent session
choosing the review angles, selection is **delegated to a fresh `perk.review-angle-selector`
lane** run **concurrently with the mandatory plan-fidelity reviewer** inside one perk-rendered
workflow. The selector classifies the change profile from its own `perk pr review-context` fetch
and recommends angles; **module-rendered code normalizes the selection deterministically** —
additional angles come only from the `correctness`/`tests`/`quality` allowlist (unknown slugs and
any `plan-fidelity` echo dropped, duplicates deduped), plan-fidelity always runs and is never
displaced, at most 2 additional angles (2–3 lanes total, matching `/pr-review`'s window),
operator-forced angles come first and are always honored, and a failed/low-confidence/empty
selection falls back to **correctness + tests**. Reviewers never see the selector's output (bias
control) — their tasks come only from the embedded angle vocabulary. Reconciliation and posting
are unchanged: the parent reconciles the typed reports and posts once via the **shared
`post_pr_review`** tool, under the same clean guard (an incomplete dynamic wave makes a clean
verdict refuse with `incomplete_coverage`). The baseline `/pr-review` stays canonical.

An optional free-form focus note after the command rides `directive` (DATA to the selector and
every reviewer); when the note **explicitly names angles**, the parent passes them as
`force_angles` instead. Models: `[models.subagents] pr-reviewer` (every reviewer lane) and
`review-angle-selector` (the selector lane) — both per-lane, so an unset selector key falls back
to the selector agent's own default model.

- **`run_pr_review_dynamic_wave`** — run the selector-driven dynamic review wave (optional
  `directive`; optional `force_angles` = 1–2 unique slugs among `correctness|tests|quality`,
  never `plan-fidelity` — pass it only when the operator explicitly names angles); the tool owns
  the whole dynamic workflow and the one bounded retry, and returns the typed aggregate
  `{ complete, covered, retried, reports, failures, selection }` (the `selection` metadata is
  in-session DATA, never posted). *Non-terminating.*

### `/pr-review-terminal`

The **terminal-surface** entry into human-in-the-loop adversarial PR review — always the
[hunk](https://github.com/modem-dev/hunk) TUI, no provider selection needed (the command names
the surface). Both arguments are optional:
`/pr-review-terminal [pr number|url] [focus note]`. With a **PR number or URL** it reviews that
**foreign PR** — one perk's own flow did not author — from a detached read-only checkout
(`perk pr review checkout` — untrusted foreign code: nothing from it is ever executed), with 2–3
adversarial reviewers
(`claimed-intent` always included; model via `[models.subagents] adversarial-reviewer`) — spawned
**async**, so their **finding batches stream into your live hunk session while they still work**
(each batch pushed incrementally, never the same anchor twice; held until the hunk handshake
connects), with the reviewers' final reports reconciled as the source of truth — then the triage
loop, one curated post via `submit_pr_review`, and cleanup. With **no PR argument** it reviews
the **active worktree's own PR**: the same streaming flow
runs in your own worktree (no checkout, no cleanup) on the local since-base diff — perk fetches
the base branch best-effort (offline falls back to the stale local ref) and diffs from the
merge-base; since this is usually your own PR, expect the `comment` event (GitHub rejects formal
verdicts from the PR author). Any other text after the command is a **focus note** for the
reviewers (a malformed `http(s)://` token is a usage error, never a silent focus note). **Before
`/submit`** (a plan worktree whose branch has no PR yet) it degrades to a **surface-only**
since-base review: hunk opens on the working tree's diff, no reviewers are spawned and nothing
posts to GitHub — review, leave notes, and say when you're done; your notes are read back and
triaged in-session.

The door **auto-launches hunk in a terminal you can see** (a tmux pane, or your macOS terminal
keyed off `$TERM_PROGRAM` — Ghostty / iTerm2 / Terminal.app; the first macOS run may show an
Automation permission prompt attributed to your terminal app — denying or missing it just means
you run the command yourself) and ALSO prints the launch command
(`cd <worktree> && hunk diff <base_sha> --agent-notes`) loudly and copies it to your clipboard
(`--agent-notes` makes pushed findings visible in hunk immediately). The auto-launched window
runs the command through **your own login shell, interactively** (`$SHELL -i -l -c …`), so a
`hunk` (and the `node` its shebang needs) that only your shell's rc files put on `PATH` (say,
via mise/nvm activation) resolves there just like in your own terminal. The two env seams
`PERK_TERMINAL_LAUNCH` and `PERK_CLIPBOARD_CMD` each take *unset* → the platform default,
*empty* → disabled, *non-empty* → a custom launcher/copier (the launcher receives the worktree
as `$1` and the command as `$2`). If hunk doesn't come up the flow **checks in and waits** — it
re-shows the command and asks whether to keep checking or continue without hunk; it never
degrades on a timer or on its own initiative (continuing without hunk degrades loudly to an
in-session findings table — triage and posting are unchanged). The triage loop runs **with
you** — keep / drop / reword each finding, your own hunk notes read back as first-class
candidates, the review event (`comment` / `approve` / `request-changes`) settled last. Nothing
perk-driven reaches GitHub before your triage, and all perk-side posting flows through
`submit_pr_review` (below); on a foreign PR a final `perk pr review cleanup` removes the
checkout. The door requires an interactive session and the `hunk` CLI (refusing with the
install hint). The reviewer streaming is **tool-owned** (operator-visible behavior — args,
modes, posting — is unchanged):

- **`start_review_wave`** / **`collect_review_wave`** (shared by both review doors) — launch
  the 2–3-lane adversarial-review wave non-blocking (the reviewer model still comes from
  `[models.subagents] adversarial-reviewer`) and collect its typed reports
  `{ complete, covered, reports, failures }` once the run completes; an incomplete wave is
  reported honestly, never papered over. *Non-terminating.*
- **`submit_pr_review`** — submit the human-curated review batch to the PR as ONE atomic
  review (comments + body + event — the verdict never lands before the comments; delegates to
  `perk pr review-submit`; records `last_review` in workflow-state). `dry_run: true` validates
  the comment anchors without posting (the repair loop) and fails a formal event on your **own**
  PR early (`own_pr` — GitHub always rejects approve/request-changes from the PR author, so only
  `comment` can land there). Formal events (`approve` /
  `request-changes`) raise a **blocking confirm dialog** and are refused headless; `comment`
  posts on your conversational go-ahead alone. On `/pr-review-terminal` this tool is the sole
  GitHub path; on `/pr-review-browser` it is used only for a request-changes verdict or on your
  explicit ask (you post from the browser there). *Non-terminating.*

### `/pr-review-browser`

The **browser-surface** entry into the same human-in-the-loop adversarial review — always
[plannotator](https://github.com/backnotprop/plannotator)'s browser code-review UI, no provider
selection needed (the command names the surface). The
arguments mirror `/pr-review-terminal`: `/pr-review-browser [pr number|url] [focus note]`. With
a **PR number or URL** it reviews that foreign PR: detached read-only checkout, then the browser
opens **in the background** — the door ends its turn immediately (the local server URL is known
before the server is even up), 2–3 adversarial reviewers fan out **async**, and each arriving
finding batch is pushed live into the browser as badged annotations (`perk:<angle>`; never the
same anchor twice; batches are held and retried while the server is still starting). With **no
PR argument** it reviews the **active worktree's own PR** in place (no checkout, no cleanup).
Once the streaming turn ends **the session is free** — you review in the browser while the
conversation stays usable. **You post to GitHub from the browser**: inline comments (yours and
perk's pushed findings) plus an APPROVE or COMMENT verdict, natively — that is the GitHub path.
Perk composes nothing by default; `submit_pr_review` (same gates) is used only for a
**request-changes** verdict (the UI cannot post it) or when you explicitly ask perk to post. Any
browser ending routes back into the session as a message — one shot. **Before `/submit`** (a
plan worktree whose branch has no PR yet) it opens a **local since-base browser review** of the
working tree against the plan's pinned base — no reviewers, nothing posts to GitHub; your
feedback and annotations route back as a follow-up turn. If the browser server never becomes
ready the flow degrades loudly to an in-session findings table — triage and posting are
unchanged. The door fails fast when the plannotator extension is not loaded (select the
plannotator plan provider — `[providers] plan = "plannotator-plan"` —
then `perk init` and restart pi) or the session is headless. The streaming and the annotation
delivery are **tool-owned** (operator-visible behavior — args, modes, posting — is unchanged):
the reviewer fan-out rides the shared **`start_review_wave`** / **`collect_review_wave`** pair
(above), and

- **`push_annotations`** (browser door) — push each finding batch into the plannotator surface
  as badged annotations (`perk:<angle>`; tool-owned mapping, dedupe, hold-and-retry, and
  source-scoped replace). **Door-primed:** the door primes the surface when the browser opens
  and clears it when the session ends or degrades, so the tool refuses (`no_surface`) outside a
  door-opened flow. *Non-terminating.*

### `/learn-docs`

Start the learned-docs plan factory: gather the **doc-destined** open perk:learn issues into an
inbox and author a `docs/learned` consolidation plan. The cold door pre-routes by captured
classification (pre-stamped `SHOULD_BE_CODE` issues go to `/learn-code`; legacy/unclassified default
to docs); the inbox carries each learning's classification line and an existing-docs scan for
cleanup-first placement. The factory is a **curator and verifier** — it still emits a
`SHOULD_BE_CODE` follow-up step when a doc-destined learning belongs in code, and regenerates the
routing via `perk learn docs-sync` (never by hand). No paired tool.

### `/learn-code`

Start the learn-code plan factory (the additive sibling of `/learn-docs`): gather the pre-stamped
`SHOULD_BE_CODE` open perk:learn issues into a lean inbox (classification + `target`, no docs scan)
and author a bounded plan that lands each insight in its real code home (a type/constant, comment,
docstring, schema, or user-doc) after verifying the `target` against the codebase. Output stays a
plan — it never edits code directly. No paired tool.

## Universal model-facing tools

Tools available across stages, independent of a single command.

- **`ask_user_question`** — ask the human a **structured questionnaire**: 1–4 questions per call,
  each with 2–4 options, an automatic "Type something." free-text row on every question,
  optional `multiSelect`, and optional per-option previews (side-by-side mockups/snippets). The
  turn continues with the answers. *Non-terminating.* **Headless:** the tool is **stripped from
  the active tool set** when there is no interactive UI (no sentinel — a headless session simply
  carries no `ask_user_question`). Provided by the borrowed `@juicesharp/rpiv-ask-user-question`
  package — built-in for every perk repo, not a provider seam (see the
  [providers reference](./providers-and-backends.md)).

The per-stage tools documented above are enumerable here in one place (see each command's section
for the full description): `plan_draft`, `plan_review`, `plan_save`, `submit`, `ready`,
`resolve_review_threads`, `run_pr_review_wave`, `post_pr_review`, `submit_pr_review`,
`land`, `learn`, `run_ci`, `objective_draft`, `objective_save`, `objective_node`,
`reconcile_objective`, `add_objective_node`, `gist_draft`, `gist_save`.

**The read-only-mode allowlist (`READ_ONLY_TOOLS`).** While plan mode is active the agent is
structurally limited to read/search/builtin tools plus the sanctioned write tools
(`plan_draft` / `objective_draft` / `gist_draft`), the review door (`plan_review`), and the subagent delegation
family (`subagent` / `wait` + the supervisor pair) — spawning subagents (e.g. the objective-plan
explorer) stays available while gated. Spawned children of a cold-launched read-only session
**inherit the read-only gate** (edits blocked, `bash` sub-allowlisted) while keeping their
engine-side tools available — `structured_output` (the schema-validated report call) and the
supervisor channel; children of read-write sessions are not gate-restricted. The pi builtins
(`read` / `edit` / `write` / `bash` / `grep` / `find` / `ls`) are pi's own surface — see pi's
documentation, not re-documented here (in read-only mode `bash` is sub-allowlisted to read-only
commands — the sub-allowlist also permits the `agent-browser` CLI (the browser-automation skill)
for dogfooding / QA, alongside `ast-grep`, the read-only `gh` queries, and the read-only
`perk objective` queries — `show`/`next` and the non-mutating `node-engagement` read). The borrowed web/Linear
research tools are allowed while exploring; their depth belongs to the config/provider reference
nodes (4.1/4.2).

## Ancillary in-session features

Four small first-party conveniences ride along inside the perk extension. None is a workflow
stage, door, or model tool — they are human-facing only.

- **The perk footer** — the one-line footer perk owns in the interactive TUI (it supersedes pi's
  default footer wholesale): perk identity · 🎯 objective on the left; branch ·
  model · thinking · **cache-hit rate** · context · guest-extension statuses right-aligned. The
  cache segment (`CH42.3%`) restores pi's default-footer `CH` prompt-cache-hit display and stays
  absent until the session shows cache activity. For per-miss detail, enable pi's
  `showCacheMissNotices` setting **per-user** via `/settings` (user scope) — an operator
  diagnostic perk deliberately **never converges** into managed repo settings. Reading the
  notices: transition misses (stage flips, skill-binding deliveries) are expected and bounded;
  idle-gap misses (the provider's ~5-minute cache TTL expiring between turns) are not perk's
  doing.
- **`/btw`** — a side-chat popover (a separate, in-memory conversation seeded with your main
  conversation context, so it can give informed answers without polluting the main thread).
  `/btw <text>` asks immediately; bare `/btw` opens (or, with an existing thread, offers to continue
  or start fresh). Closing the popover offers to **inject a summary** of the side conversation back
  into the main chat. Its side session's tools follow perk's read-only mode — read-only sessions get
  `read` only, read-write sessions get the full tool set — so it never escapes the structural
  read-only guarantee. **TUI-only** (it never opens in a headless / RPC / cold session) and exposes
  **no model tool**.
- **`whimsical`** — replaces pi's default “Working…” label with a random whimsical phrase each turn.
  Ambient and cosmetic; always on, no command, no config toggle.
- **Transcript markers** — perk's workflow moments (run claims, read-only/read-write flips,
  objective activation + budget start, node claims, `/btw` exchanges) render
  as durable one-line markers in the interactive transcript (expandable where there is detail —
  e.g. a `/btw` answer). They are display-only (never sent to the
  model), appear only in the interactive TUI, and require pi ≥ 0.80.4 (on older hosts they are
  silently absent). No config.

## See also

If you want the shell exterior — the `perk …` commands you run before a session — that is the
**[CLI commands](./cli.md)** reference. For task-focused recipes, see the
**[how-to](../how-to/index.md)** quadrant. For the *why* behind stages, doors, and the two planes,
see **[How perk thinks](../explanation/how-perk-thinks.md)** in the
**[explanation](../explanation/index.md)** quadrant. The **[user-docs router](../index.md)** ties
all four quadrants together.

> **Status:** this page is part of Objective
> [#453](https://github.com/mattgiles/perk/issues/453) (Node 2.2). The in-session surface is
> human-reviewed for accuracy against the extension's command and tool registrations.
