# CLI commands

This page references the `perk` command-line interface — the session **exterior**: the commands
you run in your shell to scaffold a repo, manage worktrees, mint run ids, and launch primed `pi`
sessions for each stage of the plan workflow. It describes the surface; it does not teach a task
(those belong in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

Following the reference quadrant's rule, every entry is written against the command's real
`--help` output. Structural surface tests (`tests/test_cli_parity_smoke.py` and the
`tests/test_cli_help_sections.py` drift guard) catch real surface regressions; this prose is kept
current by hand against the canonical taxonomy (SSOT:
[`python-cli-guidelines.md` §11](../../guiding-principles/python-cli-guidelines.md)).

## Orientation

The `perk` surface is organized as **noun-groups** — `plan`, `objective`, `pr`, `learn`,
`worktree`, `state`, `registry`, `skills`, `workflow` — each holding both **warm stage launchers** (a launch
opens a primed `pi` session for one workflow stage) and **cold deterministic workers** (`--json`
machine surfaces the warm in-session doors shell out to), separated by help sections. Four things
escape a group:

- **The one earned flat verb** `implement` (`impl`) — the heavy cold-only working stage, typed
  constantly, reads as a bare imperative.
- **The hot-path PR flat aliases** `submit` / `address` / `land` / `ready`, each aliasing its
  canonical `perk pr <verb>` (the canonical `pr` entry is authoritative; the flat alias is the
  ergonomic spelling).
- **Setup & Health**: `init` and `doctor` (which is itself a group).
- **The informational `release-notes`** — prints the bundled changelog's release notes (see
  [Other](#other)).

**The launcher+worker merge.** Where a stage has *both* a real session-launcher half and a
deterministic worker half, they merge into **one** command: a session by default, the worker under
`--json` (the mode the warm door already shells). The genuinely merged commands are exactly
`pr submit`, `pr land`, and `plan save`. `pr address` is launcher-only; `pr ready` is worker-only;
each still gains its flat alias.

The in-session, warm `/…` commands and the model-facing tools you use *inside* a `pi` session are
a separate surface, documented in [In-session commands & tools](./in-session.md). This page covers
only the `perk` CLI you run from your shell.

Aliases are noted inline next to each command. Common flags: launcher commands accept `--worktree`
(position a worktree), `--dry-run` (print the resolved launch plan without exec'ing `pi`), and
`--remote` (dispatch the stage to a CI runner instead of running locally — only the remotely
runnable stages, `implement` and `address`, dispatch; every other launcher rejects `--remote` as
local-only); worker commands accept `--json` (emit a machine-readable report).

## Setup & Health

### `perk init`

Scaffold or converge the current repo for perk (idempotent; safe to re-run). Wires
`.pi/settings.json` and the borrowed package set, creates the `.perk/workflow/` cache, scaffolds
config, manages `.gitignore` and the `AGENTS.md` managed block, and verifies GitHub access
without mutating it. It converges a skills-manifest fragment (`.agents/manifest.d/perk.yaml`)
declaring perk's own skills **plus a set of required external skills** (from upstream sources),
materialized via the `skills` CLI; a missing required skill fails `init` (and `doctor`). It also
checks for the optional `ast-grep` CLI (structural code search) —
non-fatal: a missing `ast-grep` is a `⚠️` warning, never a blocking failure. Init also writes the
committed `.perk/required-perk-version` pin (the repo's required perk version); `perk doctor`
reports a missing or stale pin as drift and `--fix` rewrites it to the running CLI's version.
When your running `perk` CLI's version differs from that committed pin, interactive `perk`
invocations also print one soft stderr warning (never fatal). It is suppressed for
`--version`/`--help`, any `--json`/machine-output command, the `run-worker` worker path, non-TTY
stderr, `CI`, outside a git repo, and when `PERK_SKIP_VERSION_CHECK=1` (any non-empty value) is
set; the same opt-out also silences the post-upgrade notice (see
[`perk release-notes`](#perk-release-notes)).
Init also records `.perk/managed-state.toml` — a machine-written version+hash record of every
managed artifact, written as a convergence side effect (commit it; a converged repo re-runs
without touching it).
`--force` re-seeds
the user-editable config to defaults; `--no-interactive`
never prompts (CI/supervisor); `--json` emits a machine-readable report.

### `perk doctor`

Diagnose the perk-managed repo, reporting a grouped health view. `--fix` re-converges drifted
managed pieces (and seeds missing config) without ever mutating GitHub or overwriting your config
edits. `--fix` also **reconciles perk's own npm version pin** (`npm:@mgiles/perk`) in
`.pi/settings.json` to the version this perk wants (e.g. a stale `npm:@mgiles/perk@0.0.0` → the
pinned `@{version}`). perk's own extension is delivered as the pinned `npm:@mgiles/perk` install
(below); the older `git:`-clone delivery path has been retired. If your repo was previously on the
git clone, `perk doctor --fix` **migrates it forward** by removing the now-orphaned
`.pi/git/<host>/<path>` clone (filesystem-only; idempotent — a no-op once gone).
The `package` group's `extension-install` check verifies perk's own `@mgiles/perk` npm extension is
**physically installed** under `.pi/npm/` at the pinned version. Because pi installs a missing
project-scope `npm:` package lazily and unlocked at launch, perk owns the install: `perk init`
installs the pin (and reinstalls it on version drift), `perk doctor` **fails** when the install is
absent or its version differs from the pin and `perk doctor --fix` installs/reinstalls
`npm:@mgiles/perk@{version}` (`npm install … --prefix .pi/npm --legacy-peer-deps`, under a cross-process
lock), and `perk <stage>` **warms** the install before every local launch — installing it if absent
under the same lock — so concurrent sessions never race pi's unlocked lazy install. All npm work is
best-effort and non-fatal: a not-yet-published pin or flaky network is swallowed (init/doctor/launch
never crash; pi's lazy install remains the fallback). The self-repo (which wires the local `..`
package) is exempt.
The `package` group also carries the report-only `cli-version` check: it compares the running
`perk` CLI's version against the repo's committed `.perk/required-perk-version` pin and **warns**
(never fails — a running CLI cannot install itself) on a mismatch. There are two remedies:
upgrade perk (e.g. `uv tool upgrade perk`) to match the repo, or — if the *pin* is the stale
side — re-run `perk init` / `perk doctor --fix`, which reconverges the pin to this CLI (the
`required-perk-version` managed check owns that file drift and fails alongside the warn on a
mismatch, deliberately).
The `package` group also carries the report-only `resource-overrides` check: it warns (never
fails, and `--fix` never touches it) when a pi resource override reaches perk's own resources —
either perk's `packages` entry rewritten to object form with filter keys (filtering perk's own
extension breaks every interactive stage session), or a `-`/`!` disable pattern in the top-level
`extensions`/`skills`/`prompts`/`themes` override arrays that mentions `@mgiles/perk` or a perk
skill name (a substring heuristic — perk does not reimplement pi's filter semantics). Review the
overrides via `pi config -l`; see
[How to scope pi resources per-project](../how-to/scope-pi-resources-per-project.md).
The `package` group also carries the report-only `subagent-compat` check: it reads the installed
pi-subagents version and probes the installed source for the orchestration surfaces perk's
guidance assumes (`workflowScript` orchestration, the `outputSchema` → `structuredOutput`
results, the `subagent_wait` async wait tool, the supervisor channel, the
`workflowScript`-only public-execution cutover, the v1 extension RPC events, retained
children + the retained-child resume contract, the statement-body explicit-return script
wrapper, the completion-receipt surfaces — the wait-completion projection,
`details.completions` on `subagent_wait`, and the serialized workflow child `runId` — and the
streaming-wave delivery-chain surfaces: session-scoped supervisor delivery, the orchestrator
session env stamps, the in-process async workflow host, and the foreground default for workflow
children). When the package is
not installed (pi lazy-installs it at launch) the check is `info` — compatibility is simply not
evaluated. On any divergence it warns **loudly** but never fails, and there is no `--fix` arm —
pi-subagents deliberately stays unpinned, so the check is an early-warning surface, not an
enforcement gate.
The `package` group also carries the report-only `subagent-bridge-config` check: it reads
`subagents.intercomBridge.mode` from both pi settings scopes — the project `.pi/settings.json`
and the user-global `~/.pi/agent/settings.json` — and warns (never fails, no `--fix` arm — perk
neither sets nor manages the key) when either scope sets it to `"off"` or `"fork-only"`. Either
value silently disables pi-subagents' supervisor channel for perk's fresh-context wave children,
so perk's live-streaming review flows degrade to completion-only; remove the key (or set it to
`"always"`) in the named settings file to restore streaming.
Beyond these doctor checks, a local `perk <stage>` launch also surfaces a **soft, non-fatal warning
at session start** when the `@mgiles/perk` extension that pi actually loaded differs in version from the
running `perk` CLI (pi can lazy-load a stale `npm:` package), pointing you at `perk doctor --fix` to
reinstall the pinned version. It is silent when versions match and for an ad-hoc `pi` launch.
The `state` group carries the report-only `artifact-health` check: it classifies every managed
artifact against the recorded `.perk/managed-state.toml` state as `up-to-date`,
`not-installed`, `locally-modified` (you changed it since perk last wrote it — a fork that
`--fix` would overwrite), `changed-upstream` (untouched by you, but perk's desired content moved
— e.g. a version upgrade), or `state-missing` (drift with no recorded hash to arbitrate). It is
diagnostic only (`ok`/`info`/`warn`, never `fail`) — the managed dry-run checks stay
authoritative for pass/fail — and the per-artifact rows appear in the `--json` report's
`artifact_health` array. `--fix` reconverges the drifted artifacts and then re-records the state
file.
The
`environment` group reports required tools as `fail` when missing and optional tools
(e.g. `ast-grep`) as `warn`. `--verbose` shows every check, not just failures; `--json` emits a machine-readable report.
This is a group whose bare invocation runs the health report.

### `perk doctor workflow`

Diagnose the remote-runner subsystem: static prerequisites plus an optional live CI smoke.

### `perk doctor workflow check`

Run the static remote-runner prerequisite checks (GitHub readiness, runner prereqs, the managed
workflow file). `--verbose` shows every check; `--json` emits a machine-readable report.

### `perk doctor workflow smoke-test`

Dispatch a throwaway CI run (a smoke short-circuit) to prove the runner is live. `--wait` polls
the dispatched run to completion; `--verbose` shows every prereq check; `--json` emits a
machine-readable report.

## Stage launchers (the earned flat names)

The flat top-level launchers: the one earned working verb `implement`, plus the hot-path PR
aliases. Each opens a primed `pi` session and accepts `--worktree`, `--dry-run`, and `--remote`
(dispatching only for the remotely runnable stages, `implement` and `address`); passthrough
`pi_args` are forwarded to `pi`.

perk-launched sessions run the borrowed [pi-fff](https://github.com/dmtrKovalenko/fff.nvim)
search extension in **override mode** (`find`/`grep` become FFF-backed — pre-indexed,
frecency-ranked) via an injected `PI_FFF_MODE=override` env default; your environment wins, so
export `PI_FFF_MODE=tools-and-ui` (or any valid mode) to override.

### `perk implement [PLAN]` (alias `impl`)

Do the work on a branch; requires fresh context (cold-only). `PLAN` is an optional plan issue id
(`42`, `#42`, or `ENG-123`) — or the plan's **issue URL** (GitHub `.../issues/N`; Linear
`.../issue/IDENT` or `.../project/SLUG`), which is peeled to the id; omit it to implement the active
saved plan in this repo. The worktree
branch is cut from the plan's pinned base (`origin/<base>`) when the plan declared one, else
`origin/<trunk>` (see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)). Adds `--base`
to override the start-point with a ref of your choosing (e.g. to stack on an unlanded branch); the
flag wins verbatim over the plan's pinned base but does not change the PR's merge target.

### `perk submit`

Flat alias for [`perk pr submit`](#perk-pr-submit) (the canonical entry). Push the branch and open
a draft PR (the implement → submit boundary); a session by default, the worker under `--json`.

### `perk address`

Flat alias for [`perk pr address`](#perk-pr-address) (the canonical entry). Classify PR review
feedback in an isolated child and resolve the threads (launcher-only); `--preview` classifies the
feedback and takes no action.

### `perk land`

Flat alias for [`perk pr land`](#perk-pr-land) (the canonical entry). Merge the ready/approved PR
and reconcile, setting the pending-learn marker (submit → land); a session by default, the worker
under `--json`. A learn-docs consolidation plan is exempt: no marker, no learn pass.

### `perk ready`

Flat alias for [`perk pr ready`](#perk-pr-ready) (the canonical entry). Mark the active plan's
draft PR ready for review (the deliberate review gate) — a worker-only command (`--dry-run` /
`--json`).

## Command groups

> **Pre-launch fast-forward (read-only planning/authoring).** The read-only planning and authoring
> launchers — `perk plan` (bare), `perk plan replan`, `perk plan from`, `perk objective plan`,
> `perk objective author` (incl. `--from`), `perk objective replan`, `perk gist author`, and
> `perk learn docs` — run in
> your **main checkout** (not a fresh `plan-<id>` worktree). To avoid planning against a stale tree,
> they **fast-forward the main checkout before launch** by default: a best-effort `git fetch`, then
> `git merge --ff-only` of your branch's upstream — but **only** when the checkout is clean, on a
> branch, has an upstream, and can fast-forward. Any other condition (dirty tree, detached HEAD, no
> upstream, diverged history, no remote, offline) **warns and skips** — it never aborts the launch,
> never creates a merge commit, and never touches a dirty or detached tree. Pass `--no-sync` to any
> of these commands to opt out. (`perk plan resume` and `perk objective run` keep the default and
> have no `--no-sync` flag.)

### `perk plan`

Author and revise plans. Bare `perk plan` launches the read-only `plan` stage (a primed `pi`
session for exploration + plan authoring); the verbs below are the save boundary and the revision
launchers. Help renders the launchers and the merged save together as the group's commands.

### `perk plan save`

Persist the plan to GitHub — the read-only → read-write boundary. The **merged** launcher+worker:
bare `perk plan save` opens a primed `pi` session for the `save` stage; `--json` runs the
deterministic save worker instead (the mode the warm `/plan-save` door shells). As a launcher it
takes `--worktree`, `--dry-run`, and `--remote`; local-only (`cold_remote:false`). As the worker
(`--json`) it keeps the full
plan-write flag set: `--plan-file` (the plan markdown to save), `--run-id`, `--title`,
`--objective-id`/`--node-id` (link to an objective and advance the node), `--consumed-learn` (the
perk:learn ids a docs plan consumes), and `--dry-run` (compose + print, no GitHub). The plan's
target branch is *derived* at save time (the linked objective's base → `[workflow] base` → the
GitHub default) and pinned — there is no `--base` flag here; see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md).

When a plan issue is first created, perk prepends a **copyable command callout** to the top of the
issue body — a one-click-copy ` ```perk impl <id>``` ` block (where `<id>` is the plan's ref id:
the GitHub issue number, a Linear `ENG-N` identifier, or a Linear project UUID) — so opening the
plan surfaces the exact command to start implementing it. Anywhere perk accepts an id, you may paste
the issue/objective **URL** instead (GitHub `.../issues/N`; Linear `.../issue/IDENT` or
`.../project/SLUG`) — perk peels the id from it. It renders with a copy button on both
GitHub and Linear and is added only once (re-saving never duplicates it).

### `perk plan resume PLAN`

Resume `PLAN` (a plan issue id, or the plan's issue URL) at its current lifecycle stage, relaunching
it with fresh context. perk classifies the plan's canonical state into its **next action**:

| plan state | next action |
| --- | --- |
| no PR yet | launches `implement` |
| PR open, **draft** | the ready-for-review gate (yours: mark it ready, then `/land`) |
| PR open, actionable review feedback | launches `address` |
| PR open, clean | awaiting the human review/land gate |
| PR merged, learn pending | launches `learn` |
| PR merged and learned | done — nothing to resume |
| PR closed unmerged | needs human attention (reopen it or replan) |

Gate outcomes (draft / awaiting review / closed / done) are **reported, never launched** — resume
names the human gate instead of opening a session at the wrong stage. `--dry-run` resolves and
prints the outcome without launching; `--remote` dispatches to CI only when the resolved stage is
remotely runnable (`implement`/`address`) — gate and `learn` outcomes stay local; `--json` emits a
machine-readable report carrying the verdict in a `next_action` field. A merged plan's
learn-vs-done resolution reads the canonical plan-header `learn_state` field (so it works from any
machine or a fresh clone); the local pending-learn marker is only the fallback for legacy plans
that predate the field.

### `perk plan replan PLAN`

Re-author the open plan `PLAN` (a plan issue id or its issue URL) against the current codebase, in
place (read-only). Local-only
(`cold_remote:false`); `--dry-run` materializes the prior plan and prints the seed without
launching; `--worktree` and `--json` are also accepted. The materialized prior plan also includes
the plan issue's human engagement (comments + description edits) as untrusted DATA when present
(Linear-first; honest on GitHub where the primitive exists), so the rewrite can incorporate human
feedback, not only landed PRs.

### `perk plan from ISSUE`

Adopt a pre-existing, human-authored issue `ISSUE` (a GitHub number, a Linear identifier like
`PER-45`, or the issue's URL) **in place** as a perk plan: perk reads the issue's title/body (and any human discussion)
as untrusted seed DATA, authors a plan over it in a read-only session, and on save stamps the plan
metadata **additively** into the *same* issue — the plan-header block (with `adopted_from`
provenance), the `perk:plan` label, the impl callout, and the plan-body comment — preserving the
human title/body verbatim and **never minting a second object**. Local-only (`cold_remote:false`);
`--dry-run` materializes the source issue and prints the seed without launching; `--worktree` and
`--json` are also accepted. Refuses when the issue is not found, not open, or already a perk plan
(use [`perk plan replan`](#perk-plan-replan-plan) for the latter). See
[Adopt an existing issue as a plan](../how-to/adopt-an-existing-issue.md).

`ISSUE` may also be a path to a **local file** (relative to your shell's cwd, or absolute). When the
argument resolves to an existing file, perk runs **seed-from-file** mode instead: it reads the
file's contents as untrusted seed DATA, primes the read-only authoring session with it, and on save
mints a **fresh** `perk:plan` issue (no in-place adoption — the file on disk is never modified, and
there is no `adopted_from` stamp). A non-existent path falls through to the issue-id path unchanged.

### `perk objective` (alias `obj`)

The objective group. Help renders **Launchers** (each opens a primed `pi` session: `author`,
`save`, `plan`, `replan`) and **Workers** (the deterministic dev/CI/T10 storage + mechanics surface, not an
agent affordance: `create` (`new`), `show` (`s`), `node`, `reconcile` (`rec`), `next` (`n`), `run`
(`r`)). Bare `perk objective` shows this group help.

### `perk objective author`

Draft a new objective and roadmap in a read-only authoring session. Local-only
(`cold_remote:false`); adds `--json`.

With **`--from <source>`** it instead **adopts a pre-existing source IN PLACE** as the objective: a
Linear project UUID, a GitHub issue id, or the source's URL. perk reads the source's prose + existing issues (and any
human discussion) as untrusted seed DATA, authors an objective + roadmap over it in a read-only
session, and on save stamps the objective metadata **additively** into the *same* source — the
`objective-header` block (with `adopted_from` provenance), the `objective-manifest`, the
model-authored prose, and the original overview preserved verbatim in an `Adopted-from` Immutable
note — **never minting a second project/issue**. On Linear, a roadmap node's optional `adopt_issue`
field maps it to an existing project issue (reused in place, title/body verbatim); GitHub is bounded
to a single issue (no child mapping). `--dry-run` materializes the source and prints the seed
without launching. Refuses when the source is not found, not open (GitHub issues only), or already a
perk objective. See [Adopt an existing project as an objective](../how-to/adopt-an-existing-project.md).

`--from <source>` may also be a path to a **local file** (relative or absolute). When it resolves to
an existing file, perk runs **seed-from-file** mode: it reads the file as untrusted seed DATA, primes
the read-only authoring session, and on save mints a **fresh** `perk:objective` issue (no in-place
adoption — the file is never modified). A non-existent path falls through to the source-id path.

### `perk objective save`

Persist the drafted objective to GitHub — the read-only → read-write objective boundary (the
`objective-save` stage). Local-only; adds `--json`.

### `perk objective plan [NUMBER]`

Select the next objective node and author a bounded plan (read-only). `NUMBER` is the objective
issue id, or the objective's **URL** (required — a cold session has no active objective); `--node`
plans a specific node id instead of the next actionable one. Local-only; adds `--json`.

### `perk objective create` (alias `new`)

Mint a `run_id` and create the perk:objective issue from authored markdown. Reads the required
`--body` file; `--title`, `--roadmap` (a JSON array of nodes, preferred over embedding YAML),
`--base` (the target branch this objective's node plans inherit — else `[workflow] base`, else the
GitHub default; see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)), `--run-id`,
`--adopt-from <source>` (adopt the named pre-existing source IN PLACE rather than minting a fresh
objective — normally set automatically via the run handoff by `objective author --from`),
`--dry-run`, and `--json` tune the create.

### `perk objective show NUMBER` (alias `s`)

Show an objective's header, roadmap, summary, and next actionable node.

### `perk objective node NUMBER`

Update one roadmap node (explicit-status-only). `--node` selects the node id (required); `--status`
sets its status (never inferred from `--pr`); `--pr` sets or clears the PR backlink;
`--description` updates the node description; `--dry-run` validates without writing.

### `perk objective node-add NUMBER`

Insert a **new** roadmap node into a phase (auto-assigned `<phase>.<n>`, appended after that phase's
last node). `--phase` (int, required) and `--description` (required) define the node; `--status`
sets its initial status (default `pending`); `--slug` overrides the auto-derived slug;
`--depends-on` (repeatable) adds a dependency edge; `--comment` attaches a note; `--dry-run`
validates without writing. Used **sparingly** during reconciliation, when a genuinely-new unit of
work emerged: a deferred follow-up the plan/PR flagged, an uncovered defect or gap, a missing
prerequisite for a later node, or human-requested work from the engagement block.

A successful **non-terminal** add (any `--status` other than `done`/`skipped`) also **reopens a
closed objective** (the reopen-on-incomplete invariant — roadmap incomplete ⇒ open, the mirror of
land's close-on-complete; human output adds `✓ Reopened #N (roadmap incomplete again)`). The one
exemption is a **superseded** objective (its header carries `superseded_by` — `objective replan`
closed it deliberately): the reopen is skipped with a stderr note, as policy, not an error. The
reopen is fail-open — a reopen failure never discards the add. The `--json` payload carries two
keys for it: `reopened` (bool — `false` on dry-run / terminal add / already-open / superseded-skip
/ failure) and `reopen_error` (string \| null — `null` on the superseded skip). Flipping an
existing node's status via `perk objective node` never auto-reopens — the invariant rides node
*insertion* only.

### `perk objective engagement NUMBER`

Read the **objective + its node-issues' human engagement** — comments + description edits on the
objective and every roadmap node-issue — as one untrusted-DATA `<untrusted_objective_engagement>`
block. `--json` emits the machine payload (`project_comments`, `project_description_edits`, and a
`nodes` list of per-node `comments` / `description_edits`). Read-only; the `/objective-reconcile`
pass uses it to weigh human feedback alongside the merged diff. **GitHub** surfaces the objective
issue's own comments + edits (no per-node sections); **Linear** surfaces the project's comments +
each node-issue's comments/edits (project description edits are an honest empty — node-issue edits
carry that signal). Empty → `no human engagement on objective <N>`.

### `perk objective node-engagement NUMBER`

Read a roadmap node-issue's **pre-planning human engagement** — comments + description edits left on
the node-issue *before* perk planned it — as an untrusted-DATA block. `--node` selects the node id
(required); `--json` emits the machine payload (`comments`, `description_edits`). Read-only; the
`/objective-plan` factory uses it to fold human feedback into the authored plan. **Linear-first** —
GitHub single-issue objectives (and the dormant issue-backed Linear store) report no engagement.

### `perk objective reconcile NUMBER` (alias `rec`)

Reconcile an objective's Reconcilable prose region against the merged diff — rewriting only the
marker-bounded region, never the roadmap table or Immutable notes. Reads the required `--body`
file; `--dry-run` composes without writing.

### `perk objective replan NUMBER`

Re-author an objective as a **net-new objective that supersedes and closes the old one** — the
objective analog of [`perk plan replan`](#perk-plan-replan-plan), but close-old/create-new rather
than in-place (perk's `objective_save` is not an upsert). Carries forward only the **unfinished**
work (reshaped); already-`done` nodes stay as history on the closed old objective. Read-only,
local-only (`cold_remote:false`); `--dry-run` materializes the old objective + prints the seed
without launching; `--worktree` and `--json` are also accepted. Refuses when the objective is not
found, already superseded, or (GitHub) not open. The `supersedes` link rides the run handoff, the
new header gets `supersedes`, the old header gets `superseded_by`. On **Linear** the unfinished
node-issues are **moved** into the new objective (identity / open PRs preserved) and dropped open
node-issues are Canceled; on **GitHub** carried nodes are authored as fresh roadmap rows and the
old issue is closed. See
[How to replan an objective](../how-to/replan-an-objective.md).

### `perk objective next NUMBER` (alias `n`)

Print the next plannable node (pending, or a resumable `planning` claim).

### `perk objective run NUMBER` (alias `r`)

Advance an objective's backlog one autonomously-safe step, then pause at the human gate.
`--remote` sets the runner ref for remote dispatches; `--wait` polls an in-flight run to
completion then re-evaluates; `--dry-run` resolves and reports the decision only. The `--json`
payload carries the classifier's verdict in a `next_action` field — for the same plan state it
matches what [`perk plan resume --dry-run`](#perk-plan-resume-plan) reports (both surfaces share
one classifier).

### `perk objective doctor NUMBER` (alias `doc`)

Detect (and optionally repair) **drift** between a Linear-Project objective's persisted
`objective-manifest` and its live state (node-issues, blocking relations, milestones). Detect-only
by default; `--fix` applies the **safe, unambiguous** repairs (a missing manifest is backfilled, a
missing node-issue or phase milestone is recreated, a missing blocking relation is re-added) in a
deterministic order, stopping at the first failed write; `--dry-run` (with `--fix`) plans the
repairs without writing. Report-only conditions perk has no authority to auto-resolve (duplicate
ids, an unexpected extra relation, a renamed milestone, a relation cycle) are surfaced but never
touched. GitHub objectives have no divergence surface, so the report is always empty. `--json`
emits the full drift + fix report. See
[How to check an objective for drift](../how-to/check-an-objective-for-drift.md).

### `perk gist`

The gist group. A **gist** is a rough, problem-space-focused statement of intent ("something we
would likely want to do") tracked in the issue backend — upstream of both plans and objectives,
code-informed but carrying **no implementation detail** (no steps, no roadmap, no estimates).
Help renders **Launchers** (`author`, `save` — each opens a primed `pi` session) and **Workers**
(`create` (`new`), `list`). Bare `perk gist` shows this group help.

A saved gist sits in the backlog until someone consumes it through the **unchanged adoption
doors**: `perk plan from <gist>` (plan scope) or `perk objective author --from <gist>` (objective
scope) — adoption stamps the plan/objective metadata beside the gist's own header in place, which
is what marks it adopted.

### `perk gist author`

Draft a new gist in a read-only authoring session: clarify the intent, explore lightly, keep the
draft current with the `gist_draft` tool, review via `plan_review` (approval auto-saves).
`--scope [plan|objective]` pre-seeds the consumption tier (it rides the run handoff; an explicit
save-time scope wins). Local-only (`cold_remote:false`); adds `--json`.

### `perk gist save`

Flip a gist-authoring session to read-write to save — the manual hand-off door (the `gist-save`
stage; normally the `plan_review` approval auto-saves instead). Local-only; adds `--json`.

### `perk gist create` (alias `new`)

Mint a `run_id` and persist the gist from authored markdown. Reads the required `--body` file;
`--title`, `--scope [plan|objective]`, `--run-id`, `--dry-run`, and `--json` tune the create.
Scope resolution: explicit `--scope` > the launch handoff's pre-seeded scope > `plan`. Scope
`objective` stores the gist on the project tier when the backend has one (on Linear: a
deliberately light **project**, so `objective author --from` adopts it in place), else falls back
to the issue tier with the scope stamped in the gist's header. Human output prints the
consumption command for the saved scope.

### `perk gist list`

List open gists. The default view **hides adopted gists** (the "what's still unconsumed" backlog
view); `--all` shows everything with an adopted marker. `--json` emits
`{gists: [{id, url, title, scope, adopted, kind}]}` (`kind` is `issue` or `project`). Exits 0 on
an empty list.

### `perk pr`

PR lifecycle group: the submit/land launchers, the address launcher, and the review workers.
`submit` and `land` open a primed `pi` session by default and run the deterministic worker under
`--json` (the merged commands); `address` is launcher-only; `ready` and the rest are cold-door
workers the warm TS doors delegate to, each running from inside the plan's worktree (reading the
local `cache.plan-ref`) and accepting `--json`.

### `perk pr submit`

Open a draft PR for the active plan's branch (the implement → submit boundary). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`; the
launcher is local-only (`cold_remote:false`). `--dry-run` follows the mode (print the launch
plan, or compose without pushing/hitting GitHub). Flat alias: [`perk submit`](#perk-submit).

After opening the PR, the worker probes mergeability against the target branch (a local
`git merge-tree` probe) and adds three fields to the `--json` report: `base` (the target branch),
`mergeable` (`true` clean / `false` conflicts present / `null` undetermined — the probe is
fail-open and never changes the exit code), and `conflicts` (the conflicted paths). `--dry-run`
stays fully offline (`base: ""`, `mergeable: null`).

When the branch already has a PR (a replan reuses the `plan-<n>` branch), submit reuses it: an
**open** PR is decorated as before, a **closed** PR is reopened first (a loud `reopened closed PR
#n` note), and an **already-merged** PR is refused with `error_type: pr_already_merged` (there is
nothing to submit — start a fresh plan/branch).

### `perk pr address`

Classify PR review feedback (in an isolated child) and resolve the threads — launcher-only (no
merged `--json` worker; its mechanics are `pr feedback` + `pr resolve-threads`). `--preview`
classifies the feedback only and takes no action (the warm `/address --preview` gesture; local-only,
inert on `--remote`). Flat alias: [`perk address`](#perk-address).

### `perk pr land`

Merge the active plan's PR and set the pending-learn semaphore (submit → land) — except for a
learn-docs consolidation plan, which is exempt from the land→learn cycle (no marker;
`pending_learn: false` in the envelope). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`; the
launcher is local-only (`cold_remote:false`). `--dry-run` follows the mode (print the launch plan, or compose without touching GitHub). The
worker also stamps the canonical `learn_state` field onto the plan-header (`pending`, or `skipped`
for a learn-docs consolidation plan; an already-`captured`/`skipped` plan is never downgraded) —
fail-open: a failed stamp warns and reports `learn_state: null` in the `--json` envelope. Flat
alias: [`perk land`](#perk-land).

### `perk pr ready`

Mark the active plan's draft PR ready for review (the deliberate review gate) — a **worker-only**
command (not a merged L+W: `ready` is not a registry stage and has no launcher). `--dry-run`
resolves the PR without marking it ready; `--json` emits a machine-readable report. Flat alias:
[`perk ready`](#perk-ready).

### `perk pr check`

Validate the active plan's PR checkout footer (the deterministic `pr check`).

### `perk pr feedback`

Fetch the active plan's PR review feedback (read-only; the classify child runs this).

### `perk pr resolve-threads`

Reply-then-resolve a batch of PR review threads (the parent's resolve step). Reads the batch from
the required `--batch` JSON file (an array of `{thread_id, comment?}` objects); `--dry-run`
validates without touching GitHub.

### `perk pr review-context`

Fetch the active plan's PR review context (read-only; each angle-specialized pr-reviewer child runs
this). `--pr <n>` resolves an arbitrary PR by number instead, plan-ref-free (`plan_body` is null;
a nonexistent PR is a clean `pr_not_found` error).

### `perk pr review-post`

Submit a `/pr-review` verdict to the active plan's PR. Reads the review from the required
`--batch` JSON file (`{verdict, summary, comments?}`); an `actionable` verdict posts an advisory
COMMENT review, a `clean` verdict posts a single thumbs-up reaction. `--dry-run` validates without
touching GitHub. Invoked by the warm **`post_pr_review`** tool (the parent reconciles the reviewers'
findings and posts once) — the reviewer children no longer call it directly.

### `perk pr review-submit`

Submit **one atomic review** (inline comments + body + formal event) to PR *N* — the review
doors' submission substrate, **consumed by the warm `submit_pr_review` posting tool, not
human-CLI-first** (the structural human gate for formal events lives at the warm layer). `--pr <n>` and
`--batch <file>` are required; `--event` is `approve`, `request-changes`, or `comment`
(default `comment` — an omitted flag can never accidentally post a verdict). The batch is strict
JSON: `{body: str, comments?: [{path, line, side?, body}]}` — `side` defaults to `RIGHT` (`LEFT`
anchors a deleted line), `line` is non-nullable (unanchorable findings are folded into the review
body upstream, during triage curation), and a stray key (including `fyi`) is a `bad_batch`.

Before anything touches GitHub, every comment's `path`/`line`/`side` anchor is **validated against
the PR diff** (the merge-base 3-dot diff GitHub validates review anchors against): any failure
exits 1 with `error_type: bad_anchors` and per-comment `invalid[]` detail — nothing is submitted.
`--dry-run` runs the full validation and stops before the mutation (`mode: "validated"`) — unlike
`review-post`'s fully-offline dry-run it **requires `gh` + auth** (it fetches the PR diff); the
repair loop is: fix the anchors, re-run `--dry-run` until it exits 0.

A real run submits one atomic review through the gateway's event-aware ladder: a failed `comment`
review degrades to a discussion comment (`comment_fallback`); a failed formal event is retried
once with the comments folded into the review body and the **event preserved** (`review_folded`) —
never converted to a non-review comment, never a silent verdict drop. Approving or requesting
changes on your own PR is the clean `own_pr` error arm.

### `perk pr review checkout`

Create an ephemeral, **detached** checkout of PR *N*'s head at `<worktree_root>/review-<n>` —
investigation material for the review doors' foreign mode (reviewers read real surrounding code
at head, not just the diff). `--pr <n>` is required. The `--json` envelope carries `path`
(absolute), `pr`, `url` (the PR's GitHub URL — feeds `/pr-review-browser`), `head_sha` (the
fetched PR head), `base_sha` (the local **merge-base** of `origin/<base_ref>` and the head — the
3-dot base GitHub's PR diff uses, *not* REST `base.sha`), and `base_ref` (the PR's base branch).

Semantics:

- **Refresh** — an existing `review-<n>` (registered worktree or leftover dir) is force-removed
  and re-created at the *current* head; a failed fetch leaves an existing checkout untouched.
- **GC backstop** — stale sibling `review-<n>` checkouts (older than 7 days, or broken residue
  missing their `.git` gitlink) are reaped before creating; failures warn and continue.
- **Untrusted-code posture** — the head is foreign code: the door **never runs
  `[worktree] setup` and never installs anything**. Any PR state (OPEN/MERGED/CLOSED) is
  checkout-able; a non-OPEN state only adds a stderr note.

Review checkouts live outside the `plan-<N>` namespace, so `perk worktree wipe` never touches
them; `perk worktree list` shows them and `perk worktree remove` is the manual fallback.

### `perk pr review cleanup`

Remove PR *N*'s review checkout (`--pr <n>` required). Single-PR and **idempotent**: nothing to
remove is success (`removed: false`, exit 0). Fully offline — no GitHub calls. A dirty checkout
is still removed (it is disposable by construction), and a leftover `refs/perk/review/<n>` temp
ref is deleted best-effort. The `--json` envelope carries `pr`, `path`, and `removed`.

### `perk learn`

Capture and consolidate learnings. Bare `perk learn` launches the `learn` stage (a primed `pi`
session); its `capture`, `skip`, `code`, `docs`, and `evidence` verbs are the cold workers the
warm doors delegate to; `pending` lists closed plans still awaiting /learn.

### `perk learn pending`

List the closed plan issues still awaiting /learn — those whose canonical plan-header
`learn_state` reads `pending` (landed, /learn not yet run). `--limit` bounds the scan window to
the N most recently updated closed plans (default 50, max 100); the pending stamp lands at close
time, so pending plans cluster at the head of that window. Each row prints
`#id  closed-at  title  url`, followed by a `perk plan resume <id>` hint (the resume
classifier's MERGED+pending arm launches the learn stage). `--json` emits a
`{success, error_type, plans:[{id, title, url, closed_at}]}` envelope; an empty list exits 0.
Canonical-field only: legacy pre-field plans (whose pending state lives solely in the local
per-worktree marker) are not listed. Exit `0` ok/empty · `1` backend failure · `2` not-a-repo.

### `perk learn capture`

Create the perk:learn issue from captured learnings and clear pending-learn (land → learn). Reads
the markdown from the required `--body` file; `--dry-run` composes without creating an issue or
clearing. The optional `--decision` (one of `CAPTURE_LEARN`, `SHOULD_BE_CODE`, `UPDATE_EXISTING_DOC`,
`NEW_DOC`, `STALE_DOC`) and `--target` (a routable pointer, e.g. a doc path) persist the reconciled
captured classification onto the perk:learn issue header (both backends); the `--json` envelope is
unchanged (the classification lives on the issue, not the capture result). Capture also stamps the
canonical `learn_state: captured` onto the plan-header — strictly, and before the local marker
clear, so a failed stamp leaves the marker set (the retry signal).

### `perk learn skip`

Record a deliberate learn skip canonically and clear pending-learn (land → learn). Stamps
`learn_state: skipped` onto the plan-header (unless the plan is already `captured` — then a no-op
that reports the kept state), then clears the local marker. The warm no-summary `/learn` arm
(`/learn skip`, the `learn` tool without a summary) delegates here, so a merged-but-skipped plan
reads as done from any machine. `--dry-run` composes offline (no stamp, no marker change); `--json`
emits a machine-readable report.

### `perk learn docs`

Consolidate the **doc-destined** open perk:learn issues into a `docs/learned` plan (a read-only
factory). The cold door partitions the open issues by their captured `decision`: every
classification except a pre-stamped `SHOULD_BE_CODE` (those route to `perk learn code`; legacy /
unclassified default to docs) lands here. The inbox carries each learning's classification line
(`decision` + optional `target`) plus an existing-docs scan (inventory + stale pointers / broken
links / duplicate cues) for cleanup-first placement. The factory remains a **curator and verifier**:
it still emits a `SHOULD_BE_CODE` follow-up step when a doc-destined learning actually belongs in
code/comment/docstring/schema/user-docs, and regenerates the routing via `perk learn docs-sync`
(never by hand). `--gather` materializes the inbox and emits `{inbox_path, learn_numbers}` without
launching (the warm path); `--worktree`, `--dry-run`, `--remote` (local-only), and `--json` are also
accepted.

### `perk learn code`

Route the pre-stamped `SHOULD_BE_CODE` open perk:learn issues into a code plan (a read-only factory,
the additive sibling of `perk learn docs`). Gathers only the issues `/learn` classified
`SHOULD_BE_CODE` and materializes a **lean** inbox (classification + `target`, no docs scan); the
factory authors a bounded plan that lands each insight in its real code home (a type/constant,
comment, docstring, schema, or user-doc) after verifying the `target` against the codebase. Options
are identical to `perk learn docs` (`--gather`, `--worktree`, `--dry-run`, `--remote` local-only,
`--json`). An empty inbox exits non-zero, cross-hinting `perk learn docs`.

### `perk learn evidence`

Gather a landed plan's session-grounded evidence bundle and emit a stable manifest. Reads the local
plan-ref (no positional arg); resolves the saved plan, the merged PR's metadata/diff, the planning
and implementation session JSONLs (main + worker, labelled distinctly), and a basic existing-docs
inventory, materializing the artifacts under `.perk/workflow/scratch/learn-evidence/`. Each source
carries a `found` / `missing` / `ambiguous` status — a missing or ambiguous source is **surfaced,
never guessed**, and never fails the command. A learn-docs consolidation plan (non-empty
`consumed_learn`) returns a stable skip up front.

The `--json` bundle also carries `docs_findings` — an advisory, deterministic enrichment of the
existing-docs inventory: `stale_pointers` (source pointers like `` `perk/x.py::sym` `` that no
longer resolve), `broken_doc_paths` (doc→doc `.md` links that no longer exist), and
`duplicate_groups` (the rare exact title/`read_when` collision guard). It surfaces doc drift
advisorily (the `/learn` existing-docs analyst weighs it candidate-vs-corpus); it never fixes
anything. `--json` emits the machine-readable bundle (the
default is a compact human summary to stderr). On a gathered (non-skip) bundle the command also
writes the full manifest to `.perk/workflow/scratch/learn-evidence/manifest.json` — the same payload
as `--json` stdout (written unconditionally, so the bundle is self-contained for the `/learn` analyst
children that read it).

`--render` additionally normalizes the **found** session JSONLs into bounded, untrusted-DATA-fenced
Markdown chunks under `.perk/workflow/scratch/learn-evidence/chunks/` (one or more `<stem>[-N].md`
parts per session role) through a deterministic pipeline — branch selection, boilerplate-drop,
dedup, prune, per-payload truncation, then split-by-budget at entry boundaries (no entry is ever
elided). With `--json`, a stable normalization report (per-role counters + chunk paths) rides the
envelope's `render` field (`null` unless `--render`); with the human summary, one `render:` line per
role. `--render` and `--json` are independent.

### `perk learn docs-sync`

Regenerate the `docs/learned/` navigation from each doc's `title` + `read_when` frontmatter (the
single source of truth). Writes two artifacts: the terse, ambient routing block in
`.pi/APPEND_SYSTEM.md` (one line per doc, loaded into every session's system prompt) and the per-doc
catalog table in `docs/learned/index.md` (one row per doc, linking the doc with a single-line *when to
read* cue). Both wrap their generated region in `<!-- BEGIN perk docs-sync … -->` /
`<!-- END perk docs-sync -->` markers, leaving a hand-editable preamble outside the markers untouched.
Generation is deterministic and idempotent — only artifacts whose content changed are written, and
re-running on a current tree is a no-op. `--dry-run` reports what would change without writing;
`--json` emits a `{written, unchanged, dry_run}` envelope. Purely local (no GitHub/config). Exit `0`
ok · `2` not-a-repo.

### `perk learn docs-check`

Verify the generated `docs/learned/` navigation is current, and report advisory hygiene. Two
categories **gate the exit**:

- **Freshness** — each artifact's marked region must match a fresh render (absent markers or a
  mismatch ⇒ stale; run `perk learn docs-sync`).
- **The per-cue budget** — each doc's `read_when` must be ≤ 200 chars and free of the YAML
  plain-scalar hazards that silently corrupt the rendered cue: a ` #` (space-then-hash) starts a
  YAML comment and silently truncates the cue, a `: ` (colon-space) breaks the whole frontmatter
  parse so the cue renders empty, and a multi-line value breaks the one-line routing grammar.
  Quoting the scalar is the sanctioned escape for a cue that needs `: ` or ` #`.

**Hygiene** is advisory — always printed, never changing the exit — and covers missing
`title`/`read_when` frontmatter, copied-source-looking code blocks (a source-language fence with `≥ 10`
non-blank lines; data-format/CLI fences are ignored), duplicated `read_when` cues, stale source
pointers, and broken doc→doc links. Read-only and purely local. Exit `0` ok · `1` stale or cue
violation · `2` not-a-repo. Freshness is intentionally **not** wired into `just ci` / `just test` —
run `docs-check` on demand — but the cue budget **is**: a pytest fails CI on the same overlong-cue /
hazard violations.

### `perk worktree` (alias `wt`)

Create, list, remove, and check out git worktrees: `checkout` (`co`), `create` (`new`),
`list` (`ls`), `remove` (`rm`), `wipe`.

### `perk worktree checkout NAME` (alias `co`)

Print or activate the worktree `NAME`. A subprocess can never `cd` its parent shell, so bare
invocation prints the worktree's absolute path on **stdout** (nothing else) plus a copyable hint
on stderr — it composes as `cd "$(perk wt co NAME)"`. To actually switch directories in the
current shell, source the `--script` mode's emitted `cd` script:

```bash
source <(perk wt co plan-3 --script)
```

A failed `--script` resolution still sources cleanly but returns non-zero, so `&&` chains break
as expected. `NAME` `root` navigates back to the main checkout, and a bare plan number (`3` or
`#3`) resolves to the `plan-3` worktree (a literal name match always wins over the number sugar).

### `perk worktree create NAME` (alias `new`)

Create a worktree `NAME` under the configured worktree root. `--branch` sets the branch to create
(default: the worktree name).

### `perk worktree list` (alias `ls`)

List the repo's worktrees.

### `perk worktree remove NAME` (alias `rm`)

Remove the worktree `NAME`. `--force` removes even with uncommitted changes. After removal it also
prunes the worktree's stale admin entry, so a worktree a prior interrupted removal left half-removed
is still cleared.

### `perk worktree wipe`

Remove all merged, safe-to-delete `plan-<N>` worktrees (and their branches). Each wiped worktree's
**remote** branch on `origin` is also deleted (best-effort — already-deleted remote branches, e.g.
from GitHub's auto-delete-head-branch-on-merge, are tolerated; an offline run just skips the remote
step). Worktree removal and branch cleanup are parallelized/batched for speed. Removal **self-heals**
slow/huge worktrees (a `rm -rf` over large gitignored trees that would otherwise time out) and broken
worktrees (a prior interrupted run left the `.git` gitlink missing) by falling back to a direct
directory removal, then prunes the stale admin entries those leave behind — so a wipe is effective
even on worktrees a half-removed prior run left in place. `--dry-run` previews removals; `--force`
bypasses the safety guards (removes even if dirty or pending-learn).

Wipe also sweeps two kinds of leftovers git no longer tracks:

- **Residue dirs** — unregistered `plan-*` directories under the worktree root (what a timed-out
  removal plus a later `git worktree prune` leaves behind). An unregistered dir with **no** `.git`
  entry is provably not a worktree and is removed regardless of PR state (the sweep is fully
  offline — no backend needed); an unregistered dir that still *has* a `.git` is skipped with a
  reason (use `git worktree` / `perk worktree remove` manually).
- **Stranded branches** — local `plan-*` branches not checked out in **any** worktree. A stranded
  branch is deleted (locally, and on `origin` via the same batched remote step) only when its
  plan's PR is provably **MERGED**; an unmerged or undeterminable one is kept, and an offline run
  skips them all. Reported as one aggregate line, not per branch.

### `perk state` (alias `st`)

Inspect the local workflow cache and mint run ids (a dev/CI/doctor surface): `new-run` (`nr`),
`show` (`s`), `prune` (`gc`).

### `perk state new-run` (alias `nr`)

Mint a `run_id`, write its handoff blob, and print the id on stdout. `--handoff` supplies a
handoff JSON object (or `@file`) for the extension to claim.

### `perk state show` (alias `s`)

Show a run's handoff and scratch, or list known runs and markers. `--run-id` shows one run; omit
it to list all.

### `perk state prune` (alias `gc`)

Prune stale `.perk/workflow/` run dirs and handoff blobs (terminal-stage and age rules).
`--max-age-days` sets the age threshold (default 14); `--dry-run` previews removals; `--json`
emits a machine-readable payload.

### `perk registry` (alias `reg`)

Inspect and validate the shared stage registry (`shared/registry.yaml`): `check` (`ch`), `show`
(`s`).

### `perk registry check` (alias `ch`)

Validate the bundled registry (shape, graph, state-key vocabulary); exits 0 when valid, 1 on any
error. `--json` emits a machine-readable result.

### `perk registry show` (alias `s`)

Print the stages and their transitions (a dev/doctor convenience).

### `perk skills` (alias `sk`)

Ergonomic sugar over the upstream [`skills`](https://github.com/mattgiles/skills) CLI for managing
this repo's skills. **Every verb is a thin pass-through to the `skills` binary** (inheriting its
stdio and propagating its exit code) **except `remove`** (edits `.agents/manifest.yaml` directly)
**and the repo-authored-skill verbs `scaffold`/`create`/`refine`/`delete`** (which manage this repo's *own*
`.perk/skills/*/SKILL.md` skills and the perk-managed `.agents/manifest.d/perk-repo-skills.yaml`
fragment). The `skills` CLI must
be on `PATH` (and the repo initialized via `perk init`, which runs `skills init`); otherwise the
verbs surface a clean error.

For the task-oriented lifecycle of the repo-authored verbs (scaffold → author → commit-push-resync →
refine → delete), see [How to author a repo-specific skill](../how-to/author-a-repo-skill.md).

- **`perk skills list` (alias `ls`)** — list skills discoverable across this repo's sources
  (→ `skills skill list`).
- **`perk skills status`** — show installed skill link status for this repo (→ `skills status`).
- **`perk skills add --source S --skill K [--source-url URL] [--ref R]`** — add a skill (and its
  source) and sync (→ `skills add S K [--url URL] [--ref R]`). `--source-url` is **optional** when
  the source alias is already declared; it is required for a brand-new source. `--ref` pins a git
  ref (defaults to the remote's default branch). `skills` owns the reuse/require-url/sync/rollback
  logic.
- **`perk skills remove` (alias `rm`) `--source S --skill K`** — remove a skill from
  `.agents/manifest.yaml` (dropping its source when no skills remain), then run `skills sync` to
  drop the now-undeclared link. **The single reimplementation** (no upstream removal command). It
  edits only the user's main manifest, **refuses perk-managed sources** (those declared in
  `.agents/manifest.d/perk.yaml` — re-run `perk init` after editing perk's source set instead), and
  restores the original bytes if `skills sync` fails. Note: the rewrite uses `yaml.safe_dump`, so
  the main manifest's comments/layout are not preserved.
- **`perk skills scaffold NAME`** — scaffold a repo-authored skill stub at `.perk/skills/NAME/SKILL.md`
  in the **main checkout** (resolved even when invoked from a linked worktree). Create-only —
  refuses if `.perk/skills/NAME/` already exists (no overwrite flag; edit the existing `SKILL.md`
  directly). Writes a TODO template — including a `stages: all` declaration with a narrowing TODO
  (a stage-id list, `all`, or `[]` for interactive-only) — then reconverges the
  `perk-repo-skills.yaml` fragment, skipping the heavy all-sources sync. `--json` emits a stable report. (The freshly-scaffolded skill is
  uncommitted, so the reconverge surfaces a non-fatal "not committed — commit it" warning; that is
  expected.)
- **`perk skills create NAME`** — a write-capable authoring cold door: pre-scaffolds
  `.perk/skills/NAME/SKILL.md` in the **main checkout** (the same write as `scaffold`, including
  the stub's `stages: all` declaration), then launches a
  session seeded to author the skill (following the `perk-skill-author` skill). Refuses if
  `.perk/skills/NAME/` already exists, pointing at `perk skills refine NAME`. The authoring scope
  (`.perk/skills/NAME/**` plus any directly-required docs/bindings) is a **soft scope** in the seed
  prompt, not a structural sandbox; committing is left to you. With **`--from <file|url>`** the
  authoring session is seeded from a source document (mirroring `objective author --from`): a **local
  file** (relative/absolute) is read as untrusted seed DATA and materialized into a gitignored
  scratch the session reads; an **http(s) URL** to a `SKILL.md` is handed to the session, which
  **fetches it (and any sibling `references/`/`scripts/` or linked files) in-session**, treats
  everything as DATA, and ports selectively. Either way it always creates a **fresh** skill (no
  in-place adoption) and the door stays **offline** (no network in the command — the agent does any
  fetching in-session). A non-URL, non-file `--from` fails `seed_file_error`. `--dry-run` prints the
  seed + intended path and scaffolds/launches nothing (the existence-refusal still runs). `--json`
  emits a stable report. Trailing args after `NAME` pass through to `pi`.
- **`perk skills refine NAME`** — a write-capable cold door that re-opens an **existing**
  repo-authored skill: it reads `.perk/skills/NAME/SKILL.md` in the **main checkout** and launches a
  session seeded to improve it in place (following the `perk-skill-author` skill). Refuses if the
  skill is absent, pointing at `perk skills create NAME`. Never scaffolds and skips sync (the file
  already exists); the door is read-only on the filesystem until the launched session edits. The
  refine scope (`.perk/skills/NAME/**` plus any directly-required docs/bindings) is a **soft scope**
  in the seed prompt, not a structural sandbox; committing is left to you. `--dry-run` prints the
  seed + intended path and launches nothing (the absent-skill refusal still runs). `--json` emits a
  stable report. Trailing args after `NAME` pass through to `pi`.
- **`perk skills delete NAME --yes`** — remove a repo-authored skill (`.perk/skills/NAME/`) in the
  **main checkout** and reconverge the fragment (skipping the heavy all-sources sync). Without
  `--yes` it prompts interactively when a TTY is present; under `--json`/non-interactive it refuses
  and prints the path that would be removed. Best-effort unlinks a dangling `.agents/skills/NAME`
  symlink. `--json` emits a stable report (with `symlink_removed`).
- **`perk skills sync`** — update all sources to newer commits and re-sync links
  (→ `skills update --sync`).

Repo-scoped only (no `--global`); for broader upstream flags use the `skills` CLI directly.

### `perk workflow` (alias `wf`)

Supervisor surface over dispatched runs (a dev/CI/supervisor surface, not an agent affordance):
the `run` subgroup.

### `perk workflow run`

Observe and control dispatched runs: `list` (`ls`), `cancel`, `retry`.

### `perk workflow run list` (alias `ls`)

Enumerate runs, correlating `run_id ↔ plan ↔ PR`. **GitHub's own run enumeration is the existence
source** — the managed workflow's run-name embeds the stage, plan id, and perk `run_id`, so runs
dispatched from *any* machine appear here, even with an empty local cache. Local dispatch records
enrich the listing (plan URL, objective correlation, precise dispatch time) and keep
failed/never-triggered dispatches — plus runs older than the newest 100 — visible; each `--json`
row carries a `source` field (`"discovered"` / `"local"` / `"both"`) saying which side(s) knew the
run. `--no-refresh` skips **all** GitHub reads (the local-cache-only view); `--limit` caps the
display (default 50); `--json` emits a machine-readable report.

### `perk workflow run cancel RUN_ID`

Cancel an in-flight (queued/in_progress) dispatched run by its perk `run_id`. Works without a
local dispatch record — the run is recovered from GitHub's enumeration, so any machine can cancel
a run it did not dispatch.

### `perk workflow run retry RUN_ID`

Re-run a completed/failed dispatched run by its perk `run_id`. `--failed` re-runs only the failed
jobs. Like `cancel`, works without a local dispatch record (any machine).

## Other

### `perk release-notes`

Show perk's bundled release notes. By default it shows the notes for the perk version you are
running; `--all` shows every released version (newest first); `--version X.Y.Z` shows one
specific release (`--all` and `--version` are mutually exclusive). Notes are read from the
`CHANGELOG.md` bundled with the perk package, so the command works outside a git repo; the notes
print to stderr, and `[Unreleased]` entries are never shown. An unknown version or an unreadable
bundled changelog exits 1 with a clean `Error:` line — never a traceback.

After upgrading perk, the first **interactive** `perk` invocation prints a one-line stderr notice
pointing here (``perk updated to X.Y.Z; run `perk release-notes` for what's new.``) and records
the version in the user-level `~/.perk/last-seen-version` store. It follows the same suppression
rules as the version warning — never in `--json`/CI/non-TTY/worker paths, and
`PERK_SKIP_VERSION_CHECK` silences it — though unlike the warning it also fires outside a git
repo. Downgrades never re-trigger it (the store keeps the max version seen), and it is never
fatal: any store failure silently skips the notice.
