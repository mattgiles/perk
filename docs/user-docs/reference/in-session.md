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
to read/search tools plus the sanctioned write tools (`plan_draft` / `objective_draft`) and the
review door (`plan_review`) — it cannot edit or run mutating commands until the read-only → 
read-write boundary is crossed at save. The borrowed web/Linear research tools are also allowed
while exploring; their depth belongs to the config/provider reference nodes (4.1/4.2), so this
page names them only as a pointer.

**Terminating vs non-terminating tools.** A *terminating* tool ends the turn on success
(`plan_save`, `plan_review` on approval, `submit`, `ready`, `land`, `learn`, `objective_save`).
The rest are non-terminating — the turn continues (`plan_draft`, `objective_draft`,
`objective_node`, `reconcile_objective`, `add_objective_node`, `resolve_review_threads`,
`post_pr_review`, `run_ci`, `ask_user_question`).
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
  plan is auto-saved and the turn ends. *Terminating on approval.*

### `/plan-save`

Persist the plan to GitHub as the canonical perk plan and link the session to it — the read-only
→ read-write boundary. `/plan-save` is the manual failsafe for the approval → save flow. Paired
tool:

- **`plan_save`** — the canonical save tool. *Terminating.*

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
auto-drives `/objective-reconcile`. Paired tool:

- **`land`** — squash-merge the approved PR and set pending-learn. *Terminating.*

### `/learn`

Investigate the landed change and capture learnings into a perk:learn issue, then clear the
pending-learn semaphore and release the worktree. `/learn skip` clears the marker only;
`/learn <text>` captures the text verbatim. Paired tool:

- **`learn`** — capture learnings (or clear the marker only). *Terminating.*

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
  **sparingly**, only when a real new unit of work emerged. *Non-terminating.*

### `/objective-save`

Persist a drafted objective + structured roadmap to GitHub, activate it, and start budget
tracking — the read-only → read-write objective boundary (the manual failsafe for the approval →
save flow). Paired tools:

- **`objective_draft`** — write the working objective draft to the session data dir (sanctioned
  read-only write; not a save). Optional `base` targets a non-default branch (omit for the repo
  default). *Non-terminating.*
- **`objective_save`** — the canonical objective save tool (also accepts the optional `base`).
  *Terminating.*

The cold authoring door **`perk objective author`** has **no** warm slash twin — objective
authoring is reached cold, or via plan-mode read-only authoring (`objective_draft` →
`plan_review` / `objective_save`).

## Utility commands & tools

Standalone surfaces not tied to a single spine stage.

### `/checkpoints`

Show perk implementation checkpoints (read-only); inert when the plan has no `## Steps` list.
Checkpoints are driven by the `[WIP:n]` / `[DONE:n]` progress markers the implementer emits. No
paired tool.

### `/ci`

Run the project's configured CI checks and report pass/fail + failure output; never auto-fixes. A
`check` argument runs one configured check. Paired tool:

- **`run_ci`** — run the configured checks and report results; read-only (the agent owns the
  Run → Report → Fix → Verify loop: analyze a failure, fix it in its own turn, then re-verify).
  *Non-terminating.*

### `/pr-review`

Multi-angle automated code review: spawn **2–3 angle-specialized fresh-context reviewers** in
parallel — always **Plan fidelity & completeness** plus 1–2 of **Correctness & regressions**,
**Tests & validation adequacy**, **Code quality, simplicity & docs/contracts accuracy** — each
reviewing one assigned angle and **returning structured findings** (they never post). The parent
**reconciles** the per-angle findings (union, dedupe, derive one verdict) and posts a single
verdict-driven outcome via the paired **`post_pr_review`** tool (actionable → an advisory COMMENT
review; clean → a single 👍 reaction). The reviewers read adversarially and the plan-fidelity angle
runs an explicit **plan-conformance pass** — verifying the diff implements what the plan called for
and flagging forgotten items (and noting when no plan body was found) — so a clean verdict means
*no actionable findings after a genuine hunt*, not a rubber stamp.

- **`post_pr_review`** — post the reconciled multi-angle review to the PR (delegates to
  `perk pr review-post`; records `last_pr_review` in workflow-state). *Non-terminating.*

### `/learn-docs`

Start the learned-docs plan factory: gather open perk:learn issues into an inbox and author a
`docs/learned` consolidation plan. No paired tool.

## Universal model-facing tools

Tools available across stages, independent of a single command.

- **`ask_user_question`** — ask the human a clarifying question (free-text or multiple-choice; a
  free-text escape is always added). The turn continues with the answer; returns a no-user
  sentinel when there is no interactive UI. *Non-terminating.* This is perk's first-party default;
  it is a pluggable provider seam (`askuser`) — a repo may select a foreign provider
  (`juicesharp-ask-user`, a richer multi-question dialog) via `[providers] askuser`, in which case
  perk vacates its own tool and the foreign same-named `ask_user_question` is what fires (see the
  [providers reference](./providers-and-backends.md)).

The per-stage tools documented above are enumerable here in one place (see each command's section
for the full description): `plan_draft`, `plan_review`, `plan_save`, `submit`, `ready`,
`resolve_review_threads`, `post_pr_review`, `land`, `learn`, `run_ci`, `objective_draft`, `objective_save`,
`objective_node`, `reconcile_objective`, `add_objective_node`.

**The read-only-mode allowlist (`READ_ONLY_TOOLS`).** While plan mode is active the agent is
structurally limited to read/search/builtin tools plus the sanctioned write tools
(`plan_draft` / `objective_draft`) and the review door (`plan_review`). The pi builtins
(`read` / `edit` / `write` / `bash` / `grep` / `find` / `ls`) are pi's own surface — see pi's
documentation, not re-documented here (in read-only mode `bash` is sub-allowlisted to read-only
commands). The borrowed web/Linear research tools are allowed while exploring; their depth belongs
to the config/provider reference nodes (4.1/4.2).

## Ancillary in-session features

Two small first-party conveniences ride along inside the perk extension. Neither is a workflow
stage, door, or model tool — they are human-facing only.

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
